"""Background task: auto-bump lots on Funpay every 3 hours."""
from __future__ import annotations
import logging
from aiogram import Bot

from database import crud
from services import funpay

log = logging.getLogger(__name__)


async def run(bot: Bot) -> None:
    users = await crud.get_all_users()

    for user in users:
        funpay_key = user.get("funpay_golden_key")
        if not funpay_key:
            continue

        games_to_bump = []
        if user.get("auto_bump_bs"):
            games_to_bump.append("bs")
        if user.get("auto_bump_cr"):
            games_to_bump.append("cr")
        if user.get("auto_bump_coc"):
            games_to_bump.append("coc")

        if not games_to_bump:
            continue

        try:
            await funpay.bump_lots(funpay_key, games_to_bump, user.get("proxy"))
            log.info(
                "Bumped lots for user %s: %s",
                user["telegram_id"],
                ", ".join(g.upper() for g in games_to_bump),
            )
        except Exception as e:
            log.error("Auto-bump failed for user %s: %s", user["telegram_id"], e)
