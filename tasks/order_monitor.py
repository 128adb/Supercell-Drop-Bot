"""Background task: monitor Funpay orders every 30 seconds."""
from __future__ import annotations
import logging
from aiogram import Bot

from database import crud
from services import funpay, lolzteam

log = logging.getLogger(__name__)

# ─── In-memory state (lost on restart — DB is the persistent source) ─────────

# Cache of delivered order IDs so we don't query DB every cycle
_delivered_cache: set[str] = set()

# Orders where the "no errors" prompt has already been sent to the buyer
_prompted_orders: set[str] = set()

# Orders that failed to purchase — track attempt count {order_id: attempt_count}
_failed_attempts: dict[str, int] = {}

# Orders where we've already sent an FAQ reply
_faq_replied: set[str] = set()

# Orders where post-delivery resend has already been done
_post_delivery_replied: set[str] = set()

MAX_BUY_ATTEMPTS = 5

# ─── Constants ────────────────────────────────────────────────────────────────

_CONFIRM_PROMPT = (
    "✅ Thank you for your purchase!\n\n"
    "To receive your account credentials automatically, please reply with:\n\n"
    "no errors\n\n"
    "(This confirms your payment was intentional and the delivery system is working.)"
)

_FAQ_REPLIES: list[tuple[list[str], str]] = [
    (
        ["how", "connect", "login", "start", "access", "use"],
        "💡 To receive your account credentials, simply reply with:\n\n*no errors*",
    ),
    (
        ["when", "where", "get", "send", "credentials", "account", "password", "email"],
        "📦 Your credentials will be sent automatically once you confirm:\n\n*no errors*",
    ),
    (
        ["problem", "help", "stuck", "error", "issue", "not working"],
        "🔧 Please confirm your purchase by replying:\n\n*no errors*\n\nCredentials will be delivered instantly!",
    ),
]

# Strings found in messages sent BY the bot (used to filter them out)
_BOT_MESSAGE_MARKERS = [
    "thank you for your purchase",
    "reply with:\n\nno errors",
    "to receive your account credentials",
    "credentials will be sent",
    "📧 login:",
    "🔑 password:",
]


def mark_delivered(order_id: str) -> None:
    """Mark an order as delivered so the monitor won't process it again."""
    _delivered_cache.add(order_id)
    _failed_attempts.pop(order_id, None)


def _is_bot_message(text: str) -> bool:
    """Return True if the message text looks like it was sent by our bot."""
    t = text.lower()
    return any(marker in t for marker in _BOT_MESSAGE_MARKERS)


async def _is_delivered(order_id: str) -> bool:
    """Check delivery status: in-memory cache first, then DB."""
    if order_id in _delivered_cache:
        return True
    if await crud.is_order_delivered(order_id):
        _delivered_cache.add(order_id)  # populate cache
        return True
    return False


# ─── Main loop ────────────────────────────────────────────────────────────────

async def run(bot: Bot) -> None:
    users = await crud.get_all_users()

    for user in users:
        funpay_key = user.get("funpay_golden_key")
        lolz_token = user.get("lolz_token")
        lolz_secret = user.get("lolz_secret", "")
        proxy = user.get("proxy")

        if not funpay_key or not lolz_token:
            continue

        try:
            orders = await funpay.get_pending_orders(funpay_key, proxy)
        except Exception as e:
            log.error("Error fetching orders for user %s: %s", user["telegram_id"], e)
            continue

        for order in orders:
            # ── Skip permanently failed orders ────────────────────────────────
            if _failed_attempts.get(order.order_id, 0) >= MAX_BUY_ATTEMPTS:
                continue

            # ── Skip already-delivered orders (with DB persistence check) ─────
            if await _is_delivered(order.order_id):
                # Post-delivery: if buyer replies again, resend credentials
                if order.order_id not in _post_delivery_replied:
                    await _handle_post_delivery(bot, user, order, funpay_key, proxy)
                continue

            # ── Fetch order detail page ───────────────────────────────────────
            try:
                page = await funpay.get_order_page(funpay_key, order.order_id, proxy)
            except Exception as e:
                log.error("Failed to fetch order page %s: %s", order.order_id, e)
                continue

            # ── Check if buyer already replied "no errors" ────────────────────
            confirmed = any(
                "no errors" in msg["text"].lower()
                for msg in page.messages
                if not _is_bot_message(msg["text"])
            )

            # ── Step A: send "no errors" prompt if not done yet ───────────────
            if order.order_id not in _prompted_orders and not confirmed:
                try:
                    await funpay.send_message(
                        funpay_key, order.order_id, _CONFIRM_PROMPT, proxy,
                        chat_node_id=page.chat_node_id,
                        csrf_token=page.csrf_token,
                        chat_tag=page.chat_tag,
                    )
                    _prompted_orders.add(order.order_id)
                    log.info("Sent 'no errors' prompt for order %s", order.order_id)
                except Exception as e:
                    log.error("Failed to send prompt for order %s: %s", order.order_id, e)
                continue  # wait for buyer's reply on next cycle

            # ── Step B: FAQ auto-reply if buyer asked something ───────────────
            if not confirmed and order.order_id not in _faq_replied:
                buyer_messages = [
                    m for m in page.messages
                    if not _is_bot_message(m["text"]) and "no errors" not in m["text"].lower()
                ]
                if buyer_messages:
                    last_text = buyer_messages[-1]["text"].lower()
                    for keywords, reply_text in _FAQ_REPLIES:
                        if any(kw in last_text for kw in keywords):
                            try:
                                await funpay.send_message(
                                    funpay_key, order.order_id, reply_text, proxy,
                                    chat_node_id=page.chat_node_id,
                                    csrf_token=page.csrf_token,
                                    chat_tag=page.chat_tag,
                                )
                                _faq_replied.add(order.order_id)
                                log.info("Sent FAQ reply for order %s", order.order_id)
                            except Exception as e:
                                log.error("FAQ reply failed for order %s: %s", order.order_id, e)
                            break

            if not confirmed:
                continue

            # ── Mark as prompted (survives restart via memory) ────────────────
            _prompted_orders.add(order.order_id)

            # ── Step C: find matching lot in DB ───────────────────────────────
            lot = None
            if page.funpay_lot_id:
                lot = await crud.get_lot_by_funpay_id(page.funpay_lot_id)
            if not lot and page.account_tag:
                lot = await crud.get_lot_by_account_tag(page.account_tag)
            if not lot:
                log.warning(
                    "Order %s: no active lot found (funpay_lot_id=%s, account_tag=%s) — will retry",
                    order.order_id, page.funpay_lot_id, page.account_tag,
                )
                continue

            try:
                await _complete_order(
                    bot=bot,
                    user=user,
                    lot=lot,
                    order=order,
                    page=page,
                    lolz_token=lolz_token,
                    lolz_secret=lolz_secret,
                    funpay_key=funpay_key,
                    proxy=proxy,
                )
            except Exception as e:
                log.exception("Unhandled error in _complete_order for order %s: %s", order.order_id, e)
                try:
                    await bot.send_message(
                        user["telegram_id"],
                        f"🚨 *Order #{order.order_id} — Unexpected error*\n\n`{e}`\n\nCheck logs.",
                        parse_mode="Markdown",
                    )
                except Exception:
                    pass


# ─── Post-delivery resend ─────────────────────────────────────────────────────

async def _handle_post_delivery(
    bot: Bot, user: dict, order, funpay_key: str, proxy
) -> None:
    """
    If the buyer replies AFTER we delivered credentials, resend them from DB.
    This handles the case where the buyer missed the delivery message.
    """
    try:
        page = await funpay.get_order_page(funpay_key, order.order_id, proxy)
    except Exception:
        return

    # Check if there are buyer messages that aren't "no errors" or our own
    buyer_msgs = [
        m for m in page.messages
        if not _is_bot_message(m["text"])
    ]
    if not buyer_msgs:
        return

    # Check if they seem to be asking for help
    last_text = buyer_msgs[-1]["text"].lower()
    asking_for_help = any(
        kw in last_text
        for kw in ["where", "credentials", "login", "password", "account", "received", "send"]
    )
    if not asking_for_help:
        return

    # Fetch credentials from DB
    sale = await crud.get_sale_by_order(order.order_id)
    if not sale or not sale.get("login"):
        return

    resend_text = (
        f"✅ Your credentials were already sent in this chat!\n\n"
        f"📧 Login: {sale['login']}\n"
        f"🔑 Password: {sale['password']}\n\n"
        f"Please leave a review — it means a lot to the seller! 🙏"
    )
    try:
        await funpay.send_message(
            funpay_key, order.order_id, resend_text, proxy,
            chat_node_id=page.chat_node_id,
            csrf_token=page.csrf_token,
            chat_tag=page.chat_tag,
        )
        _post_delivery_replied.add(order.order_id)
        log.info("Post-delivery credentials resent for order %s", order.order_id)
    except Exception as e:
        log.error("Failed post-delivery resend for order %s: %s", order.order_id, e)


# ─── Order completion ─────────────────────────────────────────────────────────

async def _complete_order(
    bot: Bot,
    user: dict,
    lot: dict,
    order: funpay.FunpayOrder,
    page: funpay.OrderPage,
    lolz_token: str,
    lolz_secret: str,
    funpay_key: str,
    proxy: str | None,
) -> None:
    user_id = user["telegram_id"]
    lot_id = lot["id"]
    lolz_lot_id = lot["lolz_lot_id"]
    lolz_price = lot.get("lolz_price", 0)

    attempts = _failed_attempts.get(order.order_id, 0)
    log.info(
        "Processing order %s for lot %s (attempt %d/%d)",
        order.order_id, lot_id, attempts + 1, MAX_BUY_ATTEMPTS,
    )

    # ── Step 1: Buy the account on Lolzteam ───────────────────────────────────
    try:
        creds = await lolzteam.buy_account(
            lot_id=lolz_lot_id,
            token=lolz_token,
            secret_answer=lolz_secret,
            price=lolz_price,
            proxy=proxy,
        )
    except Exception as e:
        err_str = str(e)
        is_already_sold = "this item is sold" in err_str.lower()
        is_permanent = (
            "more than 3 errors" in err_str.lower()
            or "account validation" in err_str.lower()
            or is_already_sold
        )

        if is_already_sold:
            # Account was already purchased — try to retrieve credentials directly
            log.info(
                "Order %s: lot %s already sold, attempting to retrieve credentials",
                order.order_id, lolz_lot_id,
            )
            try:
                creds = await lolzteam.get_credentials(lolz_lot_id, lolz_token, proxy)
                log.info(
                    "Order %s: retrieved credentials for already-purchased lot %s",
                    order.order_id, lolz_lot_id,
                )
            except Exception as creds_err:
                _failed_attempts[order.order_id] = MAX_BUY_ATTEMPTS
                log.error(
                    "Order %s: could not retrieve credentials for already-bought lot %s: %s",
                    order.order_id, lolz_lot_id, creds_err,
                )
                creds_err_str = str(creds_err)
                partial_hint = ""
                import re as _re
                m = _re.search(r"login found \(([^)]+)\)", creds_err_str)
                if m:
                    partial_hint = f"\n📧 Partial info — login: `{m.group(1)}`"
                await bot.send_message(
                    user_id,
                    f"🚨 *Order #{order.order_id} — MANUAL ACTION REQUIRED*\n\n"
                    f"The account was already purchased (likely by this bot on a previous attempt), "
                    f"but credentials couldn't be retrieved automatically.\n\n"
                    f"⚠️ Go to your Lolzteam purchases and find lot `{lolz_lot_id}` to get the credentials.{partial_hint}\n"
                    f"Then use: `/deliver {order.order_id} LOGIN PASSWORD`",
                    parse_mode="Markdown",
                )
                return
        elif is_permanent:
            _failed_attempts[order.order_id] = MAX_BUY_ATTEMPTS
            log.error(
                "Permanent buy failure for order %s (lot %s): %s",
                order.order_id, lolz_lot_id, e,
            )
            await bot.send_message(
                user_id,
                f"🚨 *Order #{order.order_id} — MANUAL ACTION REQUIRED*\n\n"
                f"Lolzteam refuses to sell this account — it failed validation too many times.\n"
                f"Error: `{e}`\n\n"
                f"⚠️ The buyer is waiting! Please:\n"
                f"1. Find another account manually\n"
                f"2. Use: `/deliver {order.order_id} LOGIN PASSWORD`",
                parse_mode="Markdown",
            )
            return
        else:
            attempts += 1
            _failed_attempts[order.order_id] = attempts
            log.error(
                "Failed to buy Lolzteam account for order %s (attempt %d): %s",
                order.order_id, attempts, e,
            )
            is_funds_error = "enough money" in err_str.lower() or "insufficient" in err_str.lower()
            if attempts >= MAX_BUY_ATTEMPTS:
                await bot.send_message(
                    user_id,
                    f"🚨 *Order #{order.order_id} — MANUAL ACTION REQUIRED*\n\n"
                    f"Failed to auto-buy on Lolzteam after {MAX_BUY_ATTEMPTS} attempts.\n"
                    f"Last error: `{e}`\n\n"
                    f"⚠️ The buyer is waiting! Please:\n"
                    f"1. Buy lot `{lolz_lot_id}` manually\n"
                    f"2. Use: `/deliver {order.order_id} LOGIN PASSWORD`",
                    parse_mode="Markdown",
                )
            else:
                remaining = MAX_BUY_ATTEMPTS - attempts
                hint = "💡 Check your Lolzteam balance!" if is_funds_error else "💡 Will retry on next cycle."
                await bot.send_message(
                    user_id,
                    f"⚠️ *Order #{order.order_id} — Purchase failed (attempt {attempts}/{MAX_BUY_ATTEMPTS})*\n\n"
                    f"Error: `{e}`\n\n"
                    f"Will retry automatically. {remaining} attempt(s) remaining.\n"
                    f"{hint}",
                    parse_mode="Markdown",
                )
            return

    # ── Step 2: Send credentials to buyer on Funpay ───────────────────────────
    log.info(
        "Bought order %s — login=%r password=%r — sending to buyer via Funpay",
        order.order_id, creds.login, bool(creds.password),
    )
    delivery_text = (
        f"✅ Thank you for your purchase!\n\n"
        f"📧 Login: {creds.login}\n"
        f"🔑 Password: {creds.password}\n\n"
        f"Please leave a review — it means a lot to the seller! 🙏"
    )

    message_sent = False
    try:
        await funpay.send_message(
            funpay_key, order.order_id, delivery_text, proxy,
            chat_node_id=page.chat_node_id,
            csrf_token=page.csrf_token,
            chat_tag=page.chat_tag,
        )
        message_sent = True
        log.info("Credentials sent to buyer for order %s", order.order_id)
    except Exception as e:
        log.error("Failed to send Funpay message for order %s: %s", order.order_id, e)
        try:
            await bot.send_message(
                user_id,
                f"⚠️ *Order #{order.order_id} — Credentials NOT sent to buyer!*\n\n"
                f"Account was purchased on Lolzteam but the Funpay message failed.\n"
                f"📧 Login: `{creds.login}`\n"
                f"🔑 Password: `{creds.password}`\n\n"
                f"Please send these manually in order #{order.order_id}.\n"
                f"Or use: `/deliver {order.order_id} {creds.login} {creds.password}`",
                parse_mode="Markdown",
            )
        except Exception as te:
            log.error("Also failed to notify seller via Telegram for order %s: %s", order.order_id, te)

    # ── Step 3: Mark as delivered (memory + DB) ───────────────────────────────
    mark_delivered(order.order_id)
    await crud.update_lot_status(lot_id, "sold")

    # ── Step 4: Save sale to DB (persistent history + post-delivery resend) ───
    fp_price = lot.get("funpay_price", 0)
    profit = round(fp_price - lolz_price, 2)
    try:
        await crud.create_sale(
            user_id=user_id,
            lot_id=lot_id,
            order_id=order.order_id,
            game=lot.get("game", ""),
            account_tag=lot.get("account_tag", ""),
            lolz_price=lolz_price,
            funpay_price=fp_price,
            profit=profit,
            login=creds.login,
            password=creds.password,
        )
    except Exception as e:
        log.error("Failed to save sale record for order %s: %s", order.order_id, e)

    # ── Step 5: Check Lolzteam balance alert ──────────────────────────────────
    alert_threshold = user.get("lolz_balance_alert", 0) or 0
    if alert_threshold > 0:
        try:
            balance = await lolzteam.get_balance(user["lolz_token"], proxy)
            if balance < alert_threshold:
                await bot.send_message(
                    user_id,
                    f"⚠️ *Low Lolzteam Balance*\n\n"
                    f"Your balance is *{balance:.2f}₽* — below your alert threshold of {alert_threshold}₽.\n"
                    f"Please top up to avoid failed purchases!",
                    parse_mode="Markdown",
                )
        except Exception as e:
            log.error("Balance check failed for user %s: %s", user_id, e)

    # ── Step 6: Notify seller ─────────────────────────────────────────────────
    game_names = {"bs": "Brawl Stars", "cr": "Clash Royale", "coc": "Clash of Clans"}
    game = game_names.get(lot.get("game", ""), lot.get("game", "").upper())
    delivery_status = "✅ Credentials automatically sent to buyer!" if message_sent else "⚠️ Failed to send credentials — send manually!"

    try:
        await bot.send_message(
            user_id,
            f"💰 *Sale completed!*\n\n"
            f"🎮 {game} | `{lot.get('account_tag', '?')}`\n"
            f"📦 Order: #{order.order_id}\n"
            f"💵 Sale price: {fp_price}₽\n"
            f"💸 Bought on Lolz: {lolz_price}₽\n"
            f"📈 Profit: ~{profit}₽\n\n"
            f"{delivery_status}",
            parse_mode="Markdown",
        )
    except Exception as e:
        log.error("Failed to send sale notification to seller for order %s: %s", order.order_id, e)
