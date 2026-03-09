"""Background task: monitor Lolzteam sellers and auto-list new lots (runs every 10 min)."""
from __future__ import annotations
import logging
from aiogram import Bot

from database import crud
from services import lolzteam
from services.listing import list_lot

log = logging.getLogger(__name__)

GAME_NAMES = {"bs": "Brawl Stars", "cr": "Clash Royale", "coc": "Clash of Clans"}


async def run(bot: Bot) -> None:
    """
    For each active watchlist entry:
      1. Fetch recent lots from the watched Lolzteam seller
      2. Identify lots newer than last_seen_lot
      3. Auto-list each new lot on Funpay
      4. Notify the user and update last_seen_lot
    """
    entries = await crud.get_all_watchlist_entries()

    for entry in entries:
        seller = entry["lolz_seller"]
        last_seen = entry.get("last_seen_lot")
        token = entry["lolz_token"]
        proxy = entry.get("proxy")
        user_id = entry["user_id"]
        entry_id = entry["id"]

        try:
            new_lots = await lolzteam.get_seller_new_lots(seller, token, last_seen, proxy)
        except Exception as e:
            log.error("Watchlist: failed to fetch lots for seller %s (user %s): %s", seller, user_id, e)
            continue

        if not new_lots:
            continue

        log.info("Watchlist: found %d new lot(s) from seller %s for user %s", len(new_lots), seller, user_id)

        # Fetch user record for Funpay credentials
        user = await crud.get_user(user_id)
        if not user or not user.get("funpay_golden_key"):
            log.warning("Watchlist: user %s has no Funpay key — skipping", user_id)
            continue

        newest_lot_id: str | None = None

        for url, lot_id_str in new_lots:
            if newest_lot_id is None:
                newest_lot_id = lot_id_str  # first = newest (API sorts newest-first)

            try:
                lot_data = await lolzteam.parse_lot(url, token, proxy)
            except Exception as e:
                log.error("Watchlist: failed to parse lot %s from seller %s: %s", lot_id_str, seller, e)
                continue

            if not lot_data.account_tag:
                log.warning("Watchlist: lot %s has no account tag — skipping", lot_id_str)
                continue

            try:
                _lot_id, funpay_lot_id, funpay_price = await list_lot(user_id, user, lot_data, url)
                game = GAME_NAMES.get(lot_data.game, lot_data.game.upper())
                await bot.send_message(
                    user_id,
                    f"👁 *Watchlist: New lot auto-listed!*\n\n"
                    f"👤 Seller: `{seller}`\n"
                    f"🎮 {game} | `{lot_data.account_tag}`\n"
                    f"💰 Price: {funpay_price}₽\n"
                    f"🔗 [Open on Funpay](https://funpay.com/lots/offer?id={funpay_lot_id})",
                    parse_mode="Markdown",
                    disable_web_page_preview=True,
                )
                log.info(
                    "Watchlist: listed lot %s from seller %s → Funpay lot %s (%.2f₽)",
                    lot_id_str, seller, funpay_lot_id, funpay_price,
                )
            except Exception as e:
                log.error("Watchlist: failed to list lot %s from seller %s: %s", lot_id_str, seller, e)
                try:
                    await bot.send_message(
                        user_id,
                        f"⚠️ *Watchlist: Failed to list lot from {seller}*\n\n"
                        f"Lot: `{lot_id_str}`\n"
                        f"Error: `{str(e)[:100]}`",
                        parse_mode="Markdown",
                    )
                except Exception:
                    pass

        # Update last_seen_lot to the newest lot ID seen this cycle
        if newest_lot_id:
            await crud.update_watchlist_last_seen(entry_id, newest_lot_id)
