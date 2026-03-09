"""Background task: auto-drop prices for active lots (runs every hour)."""
from __future__ import annotations
import logging
from aiogram import Bot

from database import crud
from services import funpay

log = logging.getLogger(__name__)

GAME_NAMES = {"bs": "Brawl Stars", "cr": "Clash Royale", "coc": "Clash of Clans"}


async def run(bot: Bot) -> None:
    """
    For each active lot whose user has price_drop_enabled and enough time has
    passed since the last drop (or since listing), reduce the Funpay price by
    price_drop_percent %, but never below the floor price.

    Floor price = lolz_price × (1 + price_drop_floor / 100)
    """
    lots = await crud.get_lots_for_price_drop()

    for lot in lots:
        lot_id = lot["id"]
        funpay_lot_id = lot.get("funpay_lot_id")
        if not funpay_lot_id:
            continue

        current_price = lot.get("funpay_price", 0) or 0
        lolz_price = lot.get("lolz_price", 0) or 0
        drop_percent = lot.get("price_drop_percent", 10.0) or 10.0
        floor_percent = lot.get("price_drop_floor", 50.0) or 50.0
        golden_key = lot.get("funpay_golden_key")
        proxy = lot.get("proxy")
        user_id = lot["user_id"]

        if not golden_key or current_price <= 0:
            continue

        # Calculate new price
        new_price = round(current_price * (1 - drop_percent / 100), 2)

        # Floor = lolz_price + floor_percent% margin
        floor_price = round(lolz_price * (1 + floor_percent / 100), 2)

        if new_price < floor_price:
            new_price = floor_price

        # Skip if no meaningful change
        if new_price >= current_price:
            log.debug("Lot %s already at floor price (%.2f), skipping", lot_id, current_price)
            continue

        try:
            await funpay.update_lot_price(golden_key, funpay_lot_id, new_price, proxy)
            await crud.update_lot_price(lot_id, new_price)

            game = GAME_NAMES.get(lot.get("game", ""), lot.get("game", "").upper())
            drop_count = (lot.get("price_drop_count") or 0) + 1

            await bot.send_message(
                user_id,
                f"📉 *Price dropped!*\n\n"
                f"🎮 {game} | `{lot.get('account_tag', '?')}`\n"
                f"💵 {current_price}₽ → *{new_price}₽* (-{drop_percent}%)\n"
                f"🔄 Drop #{drop_count} | Floor: {floor_price}₽\n"
                f"🔗 [Open on Funpay](https://funpay.com/lots/offer?id={funpay_lot_id})",
                parse_mode="Markdown",
                disable_web_page_preview=True,
            )
            log.info(
                "Price dropped for lot %s: %.2f → %.2f (drop #%d)",
                lot_id, current_price, new_price, drop_count,
            )
        except Exception as e:
            log.error("Failed to drop price for lot %s: %s", lot_id, e)
            try:
                await bot.send_message(
                    user_id,
                    f"⚠️ *Price drop failed*\n\n"
                    f"Lot `{lot.get('account_tag', '?')}` — Error: `{e}`",
                    parse_mode="Markdown",
                )
            except Exception:
                pass
