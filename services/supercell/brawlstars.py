"""Brawl Stars stats via official API."""
from __future__ import annotations
from dataclasses import dataclass
import aiohttp
from config import BS_API_BASE


@dataclass
class BSStats:
    trophies: int
    highest_trophies: int
    total_brawlers: int
    legendary_count: int
    max11_count: int        # power level 11 (max)
    max10_count: int        # power level 10
    hypercharge_count: int  # brawlers with hypercharge unlocked


async def get_stats(tag: str, api_key: str) -> BSStats:
    """Fetch Brawl Stars player stats by account tag (with or without #)."""
    clean_tag = tag.lstrip("#").upper()
    url = f"{BS_API_BASE}/players/%23{clean_tag}"
    headers = {"Authorization": f"Bearer {api_key}"}

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            resp.raise_for_status()
            data = await resp.json()

    brawlers = data.get("brawlers", [])
    legendary_count = 0
    max11_count = 0
    max10_count = 0
    hypercharge_count = 0

    for b in brawlers:
        rarity = b.get("rarity", {}).get("name", "").lower()
        if rarity == "legendary":
            legendary_count += 1
        power = b.get("power", 0)
        if power == 11:
            max11_count += 1
        elif power == 10:
            max10_count += 1
        # Hypercharge: API exposes it as a dict under "hypercharge" when unlocked
        if b.get("hypercharge"):
            hypercharge_count += 1

    return BSStats(
        trophies=data.get("trophies", 0),
        highest_trophies=data.get("highestTrophies", 0),
        total_brawlers=len(brawlers),
        legendary_count=legendary_count,
        max11_count=max11_count,
        max10_count=max10_count,
        hypercharge_count=hypercharge_count,
    )
