"""Background task: check all active lots for validity every 5 minutes."""
from __future__ import annotations
import logging
from aiogram import Bot

from database import crud
from services import lolzteam, funpay
from services.lolzteam import CloudflareError
import config

log = logging.getLogger(__name__)


async def run(bot: Bot) -> None:
    """Called by APScheduler every VALIDITY_CHECK_INTERVAL seconds."""
    lots = await crud.get_all_active_lots()
    if not lots:
        return

    # Group lots by user to avoid fetching user config repeatedly
    user_cache: dict[int, dict] = {}

    for lot in lots:
        user_id = lot["user_id"]

        if user_id not in user_cache:
            user = await crud.get_user(user_id)
            if not user:
                continue
            user_cache[user_id] = user

        user = user_cache[user_id]
        lolz_token = user.get("lolz_token")
        funpay_key = user.get("funpay_golden_key")
        proxy = user.get("proxy")

        if not lolz_token:
            continue

        lot_id = lot["id"]
        lolz_lot_id = lot["lolz_lot_id"]

        try:
            valid = await lolzteam.check_validity(lolz_lot_id, lolz_token, proxy)
        except CloudflareError:
            log.warning("Cloudflare protection active on Lolzteam — skipping validity check")
            continue
        except Exception as e:
            log.error("Error checking lot %s validity: %s", lot_id, e)
            error_count = await crud.increment_lot_errors(lot_id)
            if error_count >= config.MAX_LOT_ERRORS:
                await _invalidate_lot(bot, lot, user, funpay_key, proxy,
                                      reason="Too many check errors")
            continue

        if not valid:
            await _invalidate_lot(bot, lot, user, funpay_key, proxy,
                                  reason="Account became invalid or was purchased")


async def _invalidate_lot(
    bot: Bot,
    lot: dict,
    user: dict,
    funpay_key: str | None,
    proxy: str | None,
    reason: str,
) -> None:
    lot_id = lot["id"]
    funpay_lot_id = lot.get("funpay_lot_id", "")
    user_id = lot["user_id"]

    log.info("Invalidating lot %s (funpay=%s): %s", lot_id, funpay_lot_id, reason)

    # Delete from Funpay
    if funpay_key and funpay_lot_id:
        try:
            await funpay.delete_lot(funpay_key, funpay_lot_id, proxy)
        except Exception as e:
            log.warning("Could not delete Funpay lot %s: %s", funpay_lot_id, e)

    await crud.update_lot_status(lot_id, "invalid")

    # Notify user in Telegram
    game_names = {"bs": "Brawl Stars", "cr": "Clash Royale", "coc": "Clash of Clans"}
    game = game_names.get(lot.get("game", ""), lot.get("game", "").upper())
    tag = lot.get("account_tag", "?")
    fp_link = (
        f"https://funpay.com/lots/{funpay_lot_id}/"
        if funpay_lot_id else "—"
    )

    try:
        await bot.send_message(
            user_id,
            f"⚠️ *Lot deleted!*\n\n"
            f"🎮 {game} | `{tag}`\n"
            f"📌 Reason: {reason}\n"
            f"🔗 Funpay lot: {fp_link}\n\n"
            f"Lot removed from Funpay and database.",
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )
    except Exception as e:
        log.warning("Could not notify user %s: %s", user_id, e)
