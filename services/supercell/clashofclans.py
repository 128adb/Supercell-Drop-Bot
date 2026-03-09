"""Clash of Clans stats via official API."""
from __future__ import annotations
from dataclasses import dataclass
import aiohttp
from config import COC_API_BASE

HERO_NAMES = {
    "Barbarian King": "King",
    "Archer Queen": "Queen",
    "Grand Warden": "Warden",
    "Royal Champion": "Champion",
    "Battle Machine": "War Machine",
    "Battle Copter": "Combat Helicopter",
}


@dataclass
class CoCStats:
    town_hall: int
    builder_hall: int
    xp_level: int
    trophies: int
    best_trophies: int
    heroes: dict[str, int]   # short_name -> level

    def heroes_str(self) -> str:
        """Return heroes as slash-separated levels, e.g. 90/90/65/30."""
        order = ["King", "Queen", "Warden", "Champion", "War Machine", "Combat Helicopter"]
        parts = [str(self.heroes.get(h, 0)) for h in order if self.heroes.get(h, 0) > 0]
        return "/".join(parts) if parts else "0"


async def get_stats(tag: str, api_key: str) -> CoCStats:
    clean_tag = tag.lstrip("#").upper()
    url = f"{COC_API_BASE}/players/%23{clean_tag}"
    headers = {"Authorization": f"Bearer {api_key}"}

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            resp.raise_for_status()
            data = await resp.json()

    heroes: dict[str, int] = {}
    for hero in data.get("heroes", []):
        name = hero.get("name", "")
        short = HERO_NAMES.get(name, name)
        heroes[short] = hero.get("level", 0)

    # Builder base level via builderBaseTrophies or dedicated field
    builder_hall = data.get("builderHallLevel", 0)

    return CoCStats(
        town_hall=data.get("townHallLevel", 0),
        builder_hall=builder_hall,
        xp_level=data.get("expLevel", 0),
        trophies=data.get("trophies", 0),
        best_trophies=data.get("bestTrophies", 0),
        heroes=heroes,
    )
