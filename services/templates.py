"""Generate RU + EN titles and descriptions for Funpay lots."""
from __future__ import annotations
from services.supercell.brawlstars import BSStats
from services.supercell.clashroyale import CRStats
from services.supercell.clashofclans import CoCStats


def _trophies_k(trophies: int) -> str:
    """Format trophies as e.g. '27.1K' or '850'."""
    if trophies >= 1000:
        val = round(trophies / 1000, 1)
        return f"{val:.0f}K" if val == int(val) else f"{val}K"
    return str(trophies)


_AUTO_DELIVERY_WARNING_RU = (
    "🔥 ЗА АВТОВЫДАЧУ ОТВЕЧАЕТ БОТ 🔥\n"
    "🔥 ПОСЛЕ ОПЛАТЫ БОТ УТОЧНИТ НЕ СЛУЧАЙНО ЛИ ВЫ ОПЛАТИЛИ ЛОТ, "
    "ВАМ НУЖНО БУДЕТ ОТВЕТИТЬ ЧЕТКО КАК ПРОСИТ БОТ 🔥\n\n"
)

_AUTO_DELIVERY_WARNING_EN = (
    "🔥 DELIVERY IS HANDLED BY A BOT 🔥\n"
    "🔥 AFTER PAYMENT THE BOT WILL ASK IF YOU PAID INTENTIONALLY — "
    "REPLY EXACTLY AS THE BOT ASKS 🔥\n\n"
)

_DISCLAIMER_RU = (
    "\n❌ Гарантия только на момент покупки.\n"
    "❌ Возврата нет после получения данных."
)

_DISCLAIMER_EN = (
    "\n❌ Warranty valid at the time of purchase only.\n"
    "❌ No refunds after credentials are received."
)


# ─── Brawl Stars ──────────────────────────────────────────────────────────────

def generate_bs(
    stats: BSStats,
    inactivity_days: int = 0,
    account_tag: str = "",
) -> tuple[str, str, str, str]:
    tag_clean = account_tag.lstrip("#")
    trophies = _trophies_k(stats.trophies)

    # ── Parties optionnelles du titre : on n'affiche que ce qui est > 0 ───────
    hc = stats.hypercharge_count
    hc_ru  = f" ⚡ {hc} ГИПЕРЗАРЯД" if hc else ""
    hc_en  = f" ⚡ {hc} HYPERCHARGE" if hc else ""
    leg_ru = f" 🌟 {stats.legendary_count} ЛЕГ" if stats.legendary_count else ""
    leg_en = f" 🌟 {stats.legendary_count} LEG" if stats.legendary_count else ""
    inact_ru = " | ОТЛЁГА" if inactivity_days else ""
    inact_en = " | INACTIVE" if inactivity_days else ""

    # ── Titre : valoriser les points forts, jamais de "(0 LEG)" ──────────────
    title_ru = (
        f"АВТОВЫДАЧА ⚡ {stats.total_brawlers} БОЙЦОВ 🏆 {trophies} КУБКОВ"
        f" 💥 {stats.max11_count} МАКС СИЛА{leg_ru}{hc_ru}{inact_ru}"
    )
    title_en = (
        f"AUTO-DELIVERY ⚡ {stats.total_brawlers} BRAWLERS 🏆 {trophies} TROPHIES"
        f" 💥 {stats.max11_count} MAX POWER{leg_en}{hc_en}{inact_en}"
    )

    # ── Description : détail complet (on affiche tout, même les 0) ───────────
    desc_ru = _AUTO_DELIVERY_WARNING_RU
    if tag_clean:
        desc_ru += f"Тег аккаунта: #{tag_clean}\n"
        desc_ru += f"Статистика: https://brawltime.ninja/profile/{tag_clean}\n\n"
    desc_ru += (
        f"💥 {stats.total_brawlers} БОЙЦОВ\n"
        f"🏆 {trophies} КУБКОВ\n"
        f"⚡ {stats.max11_count} МАКС СИЛА (СИЛ 10: {stats.max10_count})\n"
    )
    if hc:
        desc_ru += f"🌩 {hc} ГИПЕРЗАРЯДА\n"
    if stats.legendary_count:
        desc_ru += f"🌟 {stats.legendary_count} ЛЕГЕНДАРОК\n"
    if inactivity_days:
        desc_ru += f"✅ ОТЛЁГА {inactivity_days} дн\n"
    desc_ru += (
        "\n✅ ДАННЫЕ ВЫДАЮТСЯ МОМЕНТАЛЬНО ✅\n"
        "✅ ТЕЛЕФОН НЕ ПРИВЯЗАН ✅\n"
    )
    desc_ru += _DISCLAIMER_RU

    desc_en = _AUTO_DELIVERY_WARNING_EN
    if tag_clean:
        desc_en += f"Account tag: #{tag_clean}\n"
        desc_en += f"Stats: https://brawltime.ninja/profile/{tag_clean}\n\n"
    desc_en += (
        f"💥 {stats.total_brawlers} BRAWLERS\n"
        f"🏆 {trophies} TROPHIES\n"
        f"⚡ {stats.max11_count} MAX POWER (PWR 10: {stats.max10_count})\n"
    )
    if hc:
        desc_en += f"🌩 {hc} HYPERCHARGE(S)\n"
    if stats.legendary_count:
        desc_en += f"🌟 {stats.legendary_count} LEGENDARIES\n"
    if inactivity_days:
        desc_en += f"✅ INACTIVE {inactivity_days} days\n"
    desc_en += (
        "\n✅ CREDENTIALS DELIVERED INSTANTLY ✅\n"
        "✅ NO PHONE LINKED ✅\n"
    )
    desc_en += _DISCLAIMER_EN

    return title_ru, title_en, desc_ru, desc_en


# ─── Clash Royale ─────────────────────────────────────────────────────────────

def generate_cr(
    stats: CRStats,
    inactivity_days: int = 0,
    account_tag: str = "",
) -> tuple[str, str, str, str]:
    tag_clean = account_tag.lstrip("#")
    trophies = _trophies_k(stats.trophies)

    title_ru = (
        f"АВТОВЫДАЧА 🔥 КИНГ {stats.king_level} 🔥 {trophies} КУБКОВ 🔥 "
        f"{stats.legendary_count} ЛЕГ 🔥 {stats.champion_count} ЧЕМП 🔥"
        + (" ОТЛЁГА 🔥" if inactivity_days else "")
    )
    title_en = (
        f"AUTO-DELIVERY 🔥 KING {stats.king_level} 🔥 {trophies} TROPHIES 🔥 "
        f"{stats.legendary_count} LEG 🔥 {stats.champion_count} CHAMP 🔥"
        + (" INACTIVE 🔥" if inactivity_days else "")
    )

    desc_ru = _AUTO_DELIVERY_WARNING_RU
    if tag_clean:
        desc_ru += f"Тег аккаунта: #{tag_clean}\n\n"
    desc_ru += (
        f"🔥 КИНГ {stats.king_level} 🔥\n"
        f"🔥 {trophies} КУБКОВ (ЛУЧШИЕ: {_trophies_k(stats.best_trophies)}) 🔥\n"
        f"🔥 {stats.legendary_count} ЛЕГЕНДАРОК | {stats.champion_count} ЧЕМПИОНОВ 🔥\n"
        f"🔥 КАРТЫ: 16ур={stats.cards_lvl16} | 15ур={stats.cards_lvl15} | "
        f"14ур={stats.cards_lvl14} | 13ур={stats.cards_lvl13} 🔥\n"
        f"🔥 ЭВОЛЮЦИИ: {stats.evolution_count} 🔥\n\n"
        f"✅ ДАННЫЕ ВЫДАЮТСЯ МОМЕНТАЛЬНО ✅\n"
        f"✅ ТЕЛЕФОН НЕ ПРИВЯЗАН ✅\n"
    )
    if inactivity_days:
        desc_ru += f"✅ ОТЛЁГА {inactivity_days} дн ✅\n"
    desc_ru += _DISCLAIMER_RU

    desc_en = _AUTO_DELIVERY_WARNING_EN
    if tag_clean:
        desc_en += f"Account tag: #{tag_clean}\n\n"
    desc_en += (
        f"🔥 KING {stats.king_level} 🔥\n"
        f"🔥 {trophies} TROPHIES (BEST: {_trophies_k(stats.best_trophies)}) 🔥\n"
        f"🔥 {stats.legendary_count} LEGENDARIES | {stats.champion_count} CHAMPIONS 🔥\n"
        f"🔥 CARDS: 16={stats.cards_lvl16} | 15={stats.cards_lvl15} | "
        f"14={stats.cards_lvl14} | 13={stats.cards_lvl13} 🔥\n"
        f"🔥 EVOLUTIONS: {stats.evolution_count} 🔥\n\n"
        f"✅ CREDENTIALS DELIVERED INSTANTLY ✅\n"
        f"✅ NO PHONE LINKED ✅\n"
    )
    if inactivity_days:
        desc_en += f"✅ INACTIVE {inactivity_days} days ✅\n"
    desc_en += _DISCLAIMER_EN

    return title_ru, title_en, desc_ru, desc_en


# ─── Clash of Clans ───────────────────────────────────────────────────────────

def generate_coc(
    stats: CoCStats,
    inactivity_days: int = 0,
    account_tag: str = "",
) -> tuple[str, str, str, str]:
    tag_clean = account_tag.lstrip("#")
    heroes = stats.heroes_str()

    title_ru = (
        f"АВТОВЫДАЧА 🔥 ТХ{stats.town_hall} 🔥 ГЕРОИ {heroes} 🔥 "
        f"{_trophies_k(stats.trophies)} КУБКОВ 🔥"
        + (" ОТЛЁГА 🔥" if inactivity_days else "")
    )
    title_en = (
        f"AUTO-DELIVERY 🔥 TH{stats.town_hall} 🔥 HEROES {heroes} 🔥 "
        f"{_trophies_k(stats.trophies)} TROPHIES 🔥"
        + (" INACTIVE 🔥" if inactivity_days else "")
    )

    desc_ru = _AUTO_DELIVERY_WARNING_RU
    if tag_clean:
        desc_ru += f"Тег аккаунта: #{tag_clean}\n\n"
    desc_ru += (
        f"🔥 РАТУША {stats.town_hall} 🔥\n"
        f"🔥 ГЕРОИ: {heroes} 🔥\n"
        f"🔥 {_trophies_k(stats.trophies)} КУБКОВ 🔥\n\n"
        f"✅ ДАННЫЕ ВЫДАЮТСЯ МОМЕНТАЛЬНО ✅\n"
        f"✅ ТЕЛЕФОН НЕ ПРИВЯЗАН ✅\n"
    )
    if inactivity_days:
        desc_ru += f"✅ ОТЛЁГА {inactivity_days} дн ✅\n"
    desc_ru += _DISCLAIMER_RU

    desc_en = _AUTO_DELIVERY_WARNING_EN
    if tag_clean:
        desc_en += f"Account tag: #{tag_clean}\n\n"
    desc_en += (
        f"🔥 TOWN HALL {stats.town_hall} 🔥\n"
        f"🔥 HEROES: {heroes} 🔥\n"
        f"🔥 {_trophies_k(stats.trophies)} TROPHIES 🔥\n\n"
        f"✅ CREDENTIALS DELIVERED INSTANTLY ✅\n"
        f"✅ NO PHONE LINKED ✅\n"
    )
    if inactivity_days:
        desc_en += f"✅ INACTIVE {inactivity_days} days ✅\n"
    desc_en += _DISCLAIMER_EN

    return title_ru, title_en, desc_ru, desc_en


# ─── Dispatcher ───────────────────────────────────────────────────────────────

def generate(
    game: str,
    stats,
    inactivity_days: int = 0,
    account_tag: str = "",
) -> tuple[str, str, str, str]:
    """Route to the correct generator. Returns (title_ru, title_en, desc_ru, desc_en)."""
    if game == "bs":
        return generate_bs(stats, inactivity_days, account_tag)
    if game == "cr":
        return generate_cr(stats, inactivity_days, account_tag)
    if game == "coc":
        return generate_coc(stats, inactivity_days, account_tag)
    raise ValueError(f"Unknown game: {game}")


def funpay_game_fields(game: str, stats) -> dict:
    """Return the game-specific required form fields for FunPay's offer editor."""
    if game == "bs":
        return {
            "fields[cup]": str(stats.trophies),
            "fields[hero]": str(stats.total_brawlers),
        }
    if game == "cr":
        return {
            "fields[cup]": str(stats.trophies),
            "fields[hero]": str(stats.king_level),
        }
    if game == "coc":
        return {
            "fields[cup]": str(stats.trophies),
        }
    return {}
