"""Background task: forward FunPay pre-sale chat messages to Telegram.

Polls /chat/ every 30 s and forwards any new/unread message to the seller's
Telegram.  For each message the bot also looks up the corresponding Lolzteam
source URL from the lots table so the seller can open the original listing
directly.

Deduplication is done in-memory via a per-user dict:
    {node_id: last_forwarded_msg_hash}

The hash is a short MD5 of "sender:last_message_text" — good enough to detect
new messages in the same chat thread without persisting anything to DB.
"""
from __future__ import annotations

import hashlib
import logging
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from database import crud
from services import funpay

log = logging.getLogger(__name__)

# In-memory dedup state: {user_telegram_id: {node_id: msg_hash}}
_seen: dict[int, dict[str, str]] = {}

# Strings that indicate a message was sent by our own bot — we skip those
_BOT_MSG_MARKERS = [
    "thank you for your purchase",
    "reply with:\n\nno errors",
    "credentials will be sent",
    "📧 login:",
    "🔑 password:",
    "your credentials were already sent",
]


def _is_bot_msg(text: str) -> bool:
    t = text.lower()
    return any(m in t for m in _BOT_MSG_MARKERS)


async def run(bot: Bot) -> None:
    """Entry point called by APScheduler every 30 seconds."""
    users = await crud.get_all_users()

    for user in users:
        funpay_key = user.get("funpay_golden_key")
        proxy = user.get("proxy")
        user_id = user["telegram_id"]

        if not funpay_key:
            continue

        try:
            chats = await funpay.get_unread_chats(funpay_key, proxy)
        except Exception as e:
            log.error("chat_forwarder: error fetching chat inbox for user %s: %s", user_id, e)
            continue

        if not chats:
            continue

        user_seen = _seen.setdefault(user_id, {})

        for chat in chats:
            # ── Dedup check ───────────────────────────────────────────────────
            msg_key = f"{chat.sender}:{chat.last_message}"
            msg_hash = hashlib.md5(msg_key.encode()).hexdigest()[:10]

            if user_seen.get(chat.node_id) == msg_hash:
                continue  # already forwarded this exact message

            # ── Fetch chat detail for full context ────────────────────────────
            funpay_lot_id = chat.funpay_lot_id
            lot_title = chat.lot_title
            last_msg = chat.last_message

            try:
                detail_lot_id, detail_title, messages = await funpay.get_chat_detail(
                    funpay_key, chat.node_id, proxy
                )
                if detail_lot_id:
                    funpay_lot_id = detail_lot_id
                if detail_title:
                    lot_title = detail_title
                if messages:
                    # Use the last non-bot message as the "current" message
                    buyer_msgs = [m for m in messages if not _is_bot_msg(m["text"])]
                    if buyer_msgs:
                        last_msg = buyer_msgs[-1]["text"]
            except Exception as e:
                log.warning(
                    "chat_forwarder: could not fetch detail for node %s: %s",
                    chat.node_id, e,
                )

            # ── Lolzteam URL lookup ───────────────────────────────────────────
            lolz_url: str | None = None
            if funpay_lot_id:
                lot = await crud.get_lot_by_funpay_id_any(funpay_lot_id)
                if lot:
                    lolz_url = lot.get("lolz_lot_url")

            # ── Send Telegram notification ────────────────────────────────────
            await _notify(
                bot=bot,
                user_id=user_id,
                chat=chat,
                funpay_lot_id=funpay_lot_id,
                lot_title=lot_title,
                last_msg=last_msg,
                lolz_url=lolz_url,
            )

            # Mark as seen so we don't re-forward on the next cycle
            user_seen[chat.node_id] = msg_hash


async def _notify(
    bot: Bot,
    user_id: int,
    chat: funpay.ChatPreview,
    funpay_lot_id: str,
    lot_title: str,
    last_msg: str,
    lolz_url: str | None,
) -> None:
    """Build and send the Telegram notification for one incoming chat message."""

    lines: list[str] = [f"💬 *Message from {chat.sender}*\n"]

    # Lot context
    if lot_title:
        trimmed = lot_title[:80] + ("…" if len(lot_title) > 80 else "")
        lines.append(f"👀 _{trimmed}_")

    # Links row
    links: list[str] = []
    if funpay_lot_id:
        links.append(f"[FunPay lot](https://funpay.com/lots/offer?id={funpay_lot_id})")
    if lolz_url:
        links.append(f"[Lolzteam source]({lolz_url})")
    if links:
        lines.append("🔗 " + " · ".join(links))

    lines.append("")

    # Message content — trim very long messages
    trimmed_msg = last_msg[:300] + ("…" if len(last_msg) > 300 else "")
    lines.append(f'"{trimmed_msg}"')

    # Inline keyboard: Reply button + Open chat link button
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text=f"✏️ Reply to {chat.sender}",
            callback_data=f"reply_chat:{chat.node_id}",
        ),
        InlineKeyboardButton(
            text="🔗 Open chat",
            url=f"https://funpay.com/chat/?node={chat.node_id}",
        ),
    ]])

    try:
        await bot.send_message(
            user_id,
            "\n".join(lines),
            parse_mode="Markdown",
            disable_web_page_preview=True,
            reply_markup=keyboard,
        )
        log.info(
            "chat_forwarder: forwarded msg from %s (node=%s, lot=%s) to user %s",
            chat.sender, chat.node_id, funpay_lot_id or "?", user_id,
        )
    except Exception as e:
        log.error(
            "chat_forwarder: failed to notify user %s for node %s: %s",
            user_id, chat.node_id, e,
        )
