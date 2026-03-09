"""Shared lot-listing logic — used by both the Telegram bot handler and watchlist monitor."""
from __future__ import annotations
import logging
from typing import Optional

from database import crud
from database.crud import _execute
from services import funpay, templates
from services import lolzteam
from services.supercell import brawlstars, clashroyale, clashofclans
import config

log = logging.getLogger(__name__)


async def get_game_stats(game: str, tag: str):
    """Fetch Supercell account stats for any supported game."""
    if game == "bs":
        return await brawlstars.get_stats(tag, config.BS_API_KEY)
    if game == "cr":
        return await clashroyale.get_stats(tag, config.CR_API_KEY)
    if game == "coc":
        return await clashofclans.get_stats(tag, config.COC_API_KEY)
    raise ValueError(f"Unknown game: {game}")


async def list_lot(
    user_id: int,
    user: dict,
    lot_data: lolzteam.LotData,
    url: str,
) -> tuple[int, str, float]:
    """
    Core lot-listing logic (no Telegram message updates).

    Steps:
      1. Save lot to DB
      2. Fetch Supercell stats
      3. Generate Funpay titles/descriptions
      4. Create Funpay lot
      5. Finalize DB record

    Returns:
        (lot_id, funpay_lot_id, funpay_price)

    Raises:
        ValueError with a user-friendly message on any failure.
    """
    # ── Step 1: Save to DB ────────────────────────────────────────────────────
    lot_id = await crud.create_lot(
        user_id=user_id,
        lolz_lot_url=url,
        lolz_lot_id=lot_data.lot_id,
        game=lot_data.game,
        account_tag=lot_data.account_tag,
        lolz_price=lot_data.price,
        funpay_price=0,
    )

    # ── Step 2: Fetch Supercell stats ─────────────────────────────────────────
    try:
        stats = await get_game_stats(lot_data.game, lot_data.account_tag)
    except Exception as e:
        await crud.update_lot_status(lot_id, "invalid")
        raise ValueError(f"Could not fetch stats for {lot_data.account_tag}: {e}") from e

    # ── Step 3: Generate titles + descriptions ────────────────────────────────
    markup = user.get("markup_percent", 35.0)
    funpay_price = round(lot_data.price * (1 + markup / 100), 2)
    title_ru, title_en, desc_ru, desc_en = templates.generate(
        lot_data.game, stats, lot_data.inactivity_days, lot_data.account_tag
    )

    # ── Step 4: Create Funpay lot ─────────────────────────────────────────────
    try:
        funpay_lot_id = await funpay.create_lot(
            golden_key=user["funpay_golden_key"],
            game=lot_data.game,
            title_ru=title_ru,
            title_en=title_en,
            desc_ru=desc_ru,
            desc_en=desc_en,
            price=funpay_price,
            game_fields=templates.funpay_game_fields(lot_data.game, stats),
            proxy=user.get("proxy"),
        )
    except funpay.FunpayError as e:
        await crud.update_lot_status(lot_id, "invalid")
        raise ValueError(f"Funpay error: {e}") from e
    except Exception as e:
        await crud.update_lot_status(lot_id, "invalid")
        raise ValueError(f"Could not create Funpay lot: {e}") from e

    # ── Step 5: Finalize in DB ────────────────────────────────────────────────
    await crud.update_lot_funpay_id(lot_id, funpay_lot_id)
    await crud.update_lot_status(lot_id, "active")
    await _execute(
        "UPDATE lots SET funpay_price = ? WHERE id = ?",
        (funpay_price, lot_id),
    )

    log.info(
        "Lot listed: lot_id=%s game=%s tag=%s funpay_lot_id=%s price=%.2f",
        lot_id, lot_data.game, lot_data.account_tag, funpay_lot_id, funpay_price,
    )
    return lot_id, funpay_lot_id, funpay_price
