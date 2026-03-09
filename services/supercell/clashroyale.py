"""Clash Royale stats via official API."""
from __future__ import annotations
from dataclasses import dataclass, field
import aiohttp
from config import CR_API_BASE


@dataclass
class CRStats:
    king_level: int
    trophies: int
    best_trophies: int
    arena_name: str
    total_cards: int
    champion_count: int
    legendary_count: int
    cards_lvl13: int
    cards_lvl14: int
    cards_lvl15: int
    cards_lvl16: int
    evolution_count: int


async def get_stats(tag: str, api_key: str) -> CRStats:
    clean_tag = tag.lstrip("#").upper()
    url = f"{CR_API_BASE}/players/%23{clean_tag}"
    headers = {"Authorization": f"Bearer {api_key}"}

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            resp.raise_for_status()
            data = await resp.json()

    cards = data.get("cards", [])
    champion_rarities = {"champion"}
    legendary_rarities = {"legendary", "champion"}

    champ_count = 0
    legend_count = 0
    lvl_counts = {13: 0, 14: 0, 15: 0, 16: 0}
    evo_count = 0

    for card in cards:
        rarity = card.get("rarity", "").lower()
        if rarity in champion_rarities:
            champ_count += 1
        if rarity in legendary_rarities:
            legend_count += 1
        level = card.get("level", 0)
        if level in lvl_counts:
            lvl_counts[level] += 1
        if card.get("evolutionLevel", 0) > 0:
            evo_count += 1

    arena = data.get("currentPathOfLegendSeasonResult") or {}
    arena_name = data.get("arena", {}).get("name", "Unknown")

    return CRStats(
        king_level=data.get("expLevel", 0),
        trophies=data.get("trophies", 0),
        best_trophies=data.get("bestTrophies", 0),
        arena_name=arena_name,
        total_cards=len(cards),
        champion_count=champ_count,
        legendary_count=legend_count,
        cards_lvl13=lvl_counts[13],
        cards_lvl14=lvl_counts[14],
        cards_lvl15=lvl_counts[15],
        cards_lvl16=lvl_counts[16],
        evolution_count=evo_count,
    )
