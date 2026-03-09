"""Lolzteam (lolz.live) integration — parse lots, check validity, buy accounts."""
from __future__ import annotations
import json
import re
from dataclasses import dataclass
from typing import Optional
import aiohttp
from bs4 import BeautifulSoup

LOLZ_API = "https://api.lzt.market"
LOLZ_MARKET = "https://lolz.live/market"

GAME_MAP = {
    "brawlstars": "bs",
    "brawl-stars": "bs",
    "brawl_stars": "bs",
    "clashroyale": "cr",
    "clash-royale": "cr",
    "clash_royale": "cr",
    "clashofclans": "coc",
    "clash-of-clans": "coc",
    "clash_of_clans": "coc",
}

# Lolzteam's internal game-system mapping used in supercell_systems JSON field:
#   {"laser": "BSTAG", "scroll": "COCTAG", "magic": "CRTAG"}
_GAME_TO_SYSTEM = {"bs": "laser", "coc": "scroll", "cr": "magic"}


@dataclass
class LotData:
    lot_id: str
    game: str               # 'bs', 'cr', 'coc'
    account_tag: str
    price: float
    inactivity_days: int
    email: str
    password: str
    title: str


@dataclass
class Credentials:
    login: str
    password: str


class LolzError(Exception):
    pass


class CloudflareError(LolzError):
    """Raised when Lolzteam is protected by Cloudflare (temporary)."""
    pass


def _make_proxy(proxy: Optional[str]) -> Optional[str]:
    """Convert log:pass@ip:port to aiohttp proxy URL."""
    if not proxy:
        return None
    if "@" in proxy:
        auth, addr = proxy.rsplit("@", 1)
        return f"http://{auth}@{addr}"
    return f"http://{proxy}"


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }


async def _parse_response(resp) -> dict:
    """Read response body once, handle errors, return parsed dict."""
    import json as _json
    text = await resp.text()
    if resp.status == 401:
        raise LolzError("401 Unauthorized — check your Lolzteam API token")
    if resp.status == 403:
        if "cloudflare" in text.lower():
            raise CloudflareError("Cloudflare protection active")
        raise LolzError(f"403 Forbidden: {text[:200]}")
    if resp.status >= 400:
        raise LolzError(f"HTTP {resp.status}: {text[:200]}")
    try:
        data = _json.loads(text)
    except Exception:
        raise LolzError(f"Invalid JSON from API: {text[:300]}")
    if not isinstance(data, dict):
        raise LolzError(f"Unexpected API response ({type(data).__name__}): {str(data)[:200]}")
    return data


async def _api_get(path: str, token: str, proxy: Optional[str] = None) -> dict:
    url = f"{LOLZ_API}/{path.lstrip('/')}"
    async with aiohttp.ClientSession() as session:
        async with session.get(
            url,
            headers=_headers(token),
            proxy=_make_proxy(proxy),
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            return await _parse_response(resp)


async def _api_post(path: str, token: str, data: dict, proxy: Optional[str] = None) -> dict:
    url = f"{LOLZ_API}/{path.lstrip('/')}"
    async with aiohttp.ClientSession() as session:
        async with session.post(
            url,
            headers=_headers(token),
            json=data,
            proxy=_make_proxy(proxy),
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            return await _parse_response(resp)


def _extract_lot_id(url: str) -> str:
    """Extract numeric lot ID from lolz.live / ttz.market URL."""
    # Supports: /market/GAME/ID, /market/ID, /threads/ID, ttz.market/ID
    m = re.search(r"/(?:market/[^/]+/|market/|threads/)?(\d+)", url)
    if not m:
        raise LolzError(f"Cannot extract lot ID from URL: {url}")
    return m.group(1)


def _detect_game_from_url(url: str) -> Optional[str]:
    url_lower = url.lower()
    for key, val in GAME_MAP.items():
        if key in url_lower:
            return val
    return None


def _extract_tag_from_text(text: str, game: str = "bs") -> Optional[str]:
    """Try to find a Supercell tag in any text.

    Handles formats:
      - '#PP82VULJU' or '#pp82vulju' (case-insensitive)
      - 'Тег: PP82VULJU' / 'Tag: PP82VULJU' (Russian & English keyword)
      - 'Brawl Stars: PP82VULJU' / 'BS: PP82VULJU'
      - standalone uppercase alphanumeric word (last resort)
    Also strips HTML tags if present before searching.
    """
    if not text:
        return None

    # Strip HTML tags if the text looks like HTML
    if "<" in text:
        text = BeautifulSoup(text, "lxml").get_text(separator=" ")

    # Format 1: explicit # prefix — #PP82VULJU (case-insensitive)
    m = re.search(r"#([0-9A-Za-z]{6,12})", text)
    if m:
        return f"#{m.group(1).upper()}"

    # Format 2: Russian/English "tag" keyword — "Тег: PP82VULJU" / "Tag: PP82VULJU"
    m = re.search(r"(?:т[еэ]г|tag|тек)\s*[:\s]+#?([0-9A-Za-z]{6,12})", text, re.IGNORECASE)
    if m:
        return f"#{m.group(1).upper()}"

    # Format 3: game label before tag — "Brawl Stars: PP82VULJU" / "BS: PP82VULJU"
    game_patterns = {
        "bs":  r"(?:brawl\s*stars?|bs)\s*[:\-–]\s*#?([0-9A-Za-z]{6,12})",
        "cr":  r"(?:clash\s*royale?|cr)\s*[:\-–]\s*#?([0-9A-Za-z]{6,12})",
        "coc": r"(?:clash\s*of\s*clans?|coc)\s*[:\-–]\s*#?([0-9A-Za-z]{6,12})",
    }
    pattern = game_patterns.get(game, game_patterns["bs"])
    m = re.search(pattern, text, re.IGNORECASE)
    if m:
        return f"#{m.group(1).upper()}"

    # Format 4: standalone uppercase alphanumeric word (7-12 chars, last resort)
    m = re.search(r"\b([0-9A-Z]{7,12})\b", text)
    if m:
        return f"#{m.group(1)}"

    return None


def _extract_tag_from_page(html: str, game: str) -> Optional[str]:
    """Extract Supercell tag from a Lolzteam listing page HTML.

    Searches:
    1. The og:description / description meta tag (clean summary text)
    2. All visible text nodes for '#XXXXXXXX' patterns
    """
    if not html or "cloudflare" in html.lower()[:2000]:
        return None

    soup = BeautifulSoup(html, "lxml")

    # 1. og:description / meta description often has a clean human-readable summary
    for meta in soup.find_all("meta"):
        content = meta.get("content", "")
        if meta.get("property") in ("og:description",) or meta.get("name") in ("description",):
            result = _extract_tag_from_text(content, game)
            if result:
                return result

    # 2. Search every text node for '#XXXXXXX' — matches only visible text, not CSS
    tag_re = re.compile(r"#([0-9A-Za-z]{6,12})")
    for text_node in soup.find_all(string=tag_re):
        m = tag_re.search(str(text_node))
        if m:
            return f"#{m.group(1).upper()}"

    return None


def _extract_inactivity_days(html: str) -> int:
    """Parse 'days since last activity' from Lolzteam lot page."""
    # Look for patterns like "30 дней" / "30 days" in activity logs
    m = re.search(r"(\d+)\s*(?:дней|days?)\s*(?:не|inactive|без|without)", html, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return 0


async def parse_lot(url: str, token: str, proxy: Optional[str] = None) -> LotData:
    """Parse a Lolzteam market lot and return structured data."""
    import logging
    log = logging.getLogger(__name__)

    lot_id = _extract_lot_id(url)
    game = _detect_game_from_url(url)

    # Fetch lot details from API
    data = await _api_get(f"/{lot_id}", token, proxy)
    log.debug("Lolzteam API response keys: %s", list(data.keys()))

    # The API wraps the item under "item" key
    item = data.get("item") or data
    if not isinstance(item, dict):
        raise LolzError(f"Unexpected 'item' value in API response: {type(item).__name__}: {str(item)[:200]}")

    log.debug("Item keys: %s", list(item.keys()))

    if not game:
        category = (item.get("category") or {})
        if not isinstance(category, dict):
            category = {}
        category_name = category.get("name", "").lower().replace(" ", "")
        game = GAME_MAP.get(category_name, "bs")

    title = item.get("title", "")
    price = float(item.get("price", 0))

    item_origin = item.get("item_origin") or {}
    if not isinstance(item_origin, dict):
        item_origin = {}
    email = item_origin.get("email", "") or item.get("email", "")
    password = item_origin.get("password", "") or item.get("password", "")

    # ── Tag extraction — most reliable sources first ──────────────────────────
    #
    # 1. supercell_systems: JSON field {"laser":"BSTAG","scroll":"COCTAG","magic":"CRTAG"}
    #    This is Lolzteam's verified data — the definitive source for the tag.
    #    Mapping: bs→laser, coc→scroll, cr→magic
    account_tag = ""
    systems_raw = item.get("supercell_systems") or ""
    if systems_raw and isinstance(systems_raw, str):
        try:
            systems = json.loads(systems_raw)
            system_key = _GAME_TO_SYSTEM.get(game, "laser")
            raw = systems.get(system_key, "")
            if raw and isinstance(raw, str):
                account_tag = f"#{raw.strip('#').upper()}"
        except (json.JSONDecodeError, AttributeError):
            pass

    # 2. Explicit API fields (rarely populated for unsold lots)
    if not account_tag:
        account_tag = (
            item.get("account_tag") or item.get("tag")
            or item_origin.get("account_tag") or item_origin.get("tag")
            or ""
        )
        if account_tag and isinstance(account_tag, str):
            account_tag = account_tag.strip().upper()
            if not account_tag.startswith("#"):
                account_tag = f"#{account_tag}"

    # 3. Text extraction from description / title (fallback for older-style listings)
    if not account_tag:
        description = item.get("description", "") or ""
        description_en = item.get("description_en", "") or ""
        title_en = item.get("title_en", "") or ""
        account_tag = (
            _extract_tag_from_text(description, game)
            or _extract_tag_from_text(description_en, game)
            or _extract_tag_from_text(title, game)
            or _extract_tag_from_text(title_en, game)
            or ""
        )

    log.debug("Extracted account_tag=%r from lot %s (systems_raw=%r)", account_tag, lot_id, systems_raw)
    inactivity_days = 0

    return LotData(
        lot_id=lot_id,
        game=game,
        account_tag=account_tag,
        price=price,
        inactivity_days=inactivity_days,
        email=email,
        password=password,
        title=title,
    )


async def check_validity(
    lot_id: str, token: str, proxy: Optional[str] = None
) -> bool:
    """
    Return True if the account is still valid (not bought / not restored).
    Raises CloudflareError if Lolzteam is down temporarily.
    """
    try:
        data = await _api_get(f"/{lot_id}/check-account", token, proxy)
        # API returns {"status": "ok"} or {"status": "error", "reason": "..."}
        status = data.get("status", "error")
        return status == "ok"
    except CloudflareError:
        raise
    except Exception:
        return False


def _parse_nested(value: object) -> dict:
    """Return value as a dict, JSON-parsing it first if it's a string."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    return {}


def _extract_creds_from_item(item: object) -> tuple[str, str]:
    """Extract (login, password) from a Lolzteam item dict.

    Priority order (confirmed from debug logs — item_origin is empty after purchase):
    1. emailLoginData  — dict Lolzteam populates after purchase (email login + password)
    2. loginData       — Supercell login data dict
    3. item_origin     — only filled for unsold listings
    4. Flat item fields: login / email / password / old_password
    Returns ("", "") when nothing useful is found.
    """
    import logging as _logging
    log = _logging.getLogger(__name__)

    if not isinstance(item, dict):
        log.debug("_extract_creds_from_item: item is %s, skipping", type(item).__name__)
        return "", ""

    # ── 1. emailLoginData — most reliable source after purchase ──────────────
    raw_eld = item.get("emailLoginData")
    log.debug("emailLoginData raw type=%s value=%r", type(raw_eld).__name__, raw_eld)
    email_login_data = _parse_nested(raw_eld)
    if email_login_data:
        log.debug("emailLoginData keys=%s", list(email_login_data.keys()))
        eld_login = email_login_data.get("login") or email_login_data.get("email") or ""
        eld_pass = (
            email_login_data.get("password") or email_login_data.get("old_password") or ""
        )
        if eld_login and eld_pass:
            return str(eld_login).strip(), str(eld_pass).strip()
    else:
        email_login_data = {}

    # ── 2. loginData ──────────────────────────────────────────────────────────
    raw_ld = item.get("loginData")
    log.debug("loginData raw type=%s value=%r", type(raw_ld).__name__, raw_ld)
    login_data = _parse_nested(raw_ld)
    if login_data:
        log.debug("loginData keys=%s", list(login_data.keys()))
        ld_login = login_data.get("login") or login_data.get("email") or ""
        ld_pass = login_data.get("password") or login_data.get("old_password") or ""
        if ld_login and ld_pass:
            return str(ld_login).strip(), str(ld_pass).strip()
    else:
        login_data = {}

    # ── 3. item_origin (pre-sale, usually empty after purchase) ───────────────
    item_origin = _parse_nested(item.get("item_origin"))

    # ── 4. Best-effort flat field sweep ──────────────────────────────────────
    login = (
        item_origin.get("email") or item_origin.get("login")
        or email_login_data.get("login")
        or login_data.get("login")
        or item.get("login") or item.get("email") or ""
    )
    password = (
        item_origin.get("password") or item_origin.get("old_password")
        or email_login_data.get("password") or email_login_data.get("old_password")
        or login_data.get("password") or login_data.get("old_password")
        or item.get("password") or item.get("old_password") or ""
    )

    log.debug(
        "_extract_creds_from_item: login=%r password_found=%s",
        login, bool(password),
    )
    return str(login).strip(), str(password).strip()


async def buy_account(
    lot_id: str,
    token: str,
    secret_answer: str,
    price: float,
    proxy: Optional[str] = None,
) -> Credentials:
    """Purchase the lot and return login credentials."""
    import logging as _logging
    log = _logging.getLogger(__name__)

    data = await _api_post(
        f"/{lot_id}/fast-buy",
        token,
        {"price": price, "secret_answer": secret_answer},
        proxy,
    )

    # Try credentials from the fast-buy response itself first
    buy_item = data.get("item", {})
    login, password = _extract_creds_from_item(buy_item)
    if login and password:
        log.debug("buy_account: credentials found in fast-buy response for lot %s", lot_id)
        return Credentials(login=login, password=password)

    # Fall back: re-fetch the item (propagation delay after purchase)
    import asyncio as _asyncio
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            item_data = await _api_get(f"/{lot_id}", token, proxy)
            item = item_data.get("item", item_data)
            login, password = _extract_creds_from_item(item)
            if login and password:
                return Credentials(login=login, password=password)
            if login and not password:
                log.debug(
                    "buy_account: got login=%r but empty password for lot %s (attempt %d), retrying",
                    login, lot_id, attempt + 1,
                )
                last_err = ValueError(f"login found ({login!r}) but password empty")
            elif not isinstance(item, dict):
                last_err = ValueError(
                    f"item is {type(item).__name__} (expected dict): {str(item)[:100]}"
                )
        except Exception as e:
            last_err = e
        await _asyncio.sleep(2)
    raise LolzError(
        f"Bought lot {lot_id} but failed to retrieve credentials after 3 attempts: {last_err}"
    )


async def get_balance(token: str, proxy: Optional[str] = None) -> float:
    """Return the current Lolzteam account balance in ₽."""
    data = await _api_get("/me", token, proxy)
    # API returns {"user": {"balance": 123.45, ...}} or flat fields
    user_info = data.get("user", data)
    if isinstance(user_info, dict):
        balance = user_info.get("balance") or user_info.get("money") or 0
        return float(balance)
    return 0.0


async def get_seller_new_lots(
    seller: str,
    token: str,
    last_seen_lot_id: Optional[str],
    proxy: Optional[str] = None,
) -> list[tuple[str, str]]:
    """
    Return a list of (url, lot_id) for lots from this seller that are newer
    than last_seen_lot_id (determined by position in the API response, which
    is sorted newest-first).

    If last_seen_lot_id is None (first scan), returns at most 3 lots to avoid
    flooding the user with auto-listed lots on initial setup.
    """
    import logging as _logging
    log = _logging.getLogger(__name__)

    new_lots: list[tuple[str, str]] = []
    found_known = False

    game_paths = ("brawlstars", "clashroyale", "clashofclans")
    for game_path in game_paths:
        try:
            data = await _api_get(
                f"/{game_path}?user={seller}&count=20&order=price_to_up",
                token,
                proxy,
            )
            items = data.get("items", [])
            for item in items:
                if not isinstance(item, dict):
                    continue
                lid = str(item.get("item_id") or item.get("id") or "")
                if not lid:
                    continue
                if lid == last_seen_lot_id:
                    found_known = True
                    break
                url = f"https://lolz.live/market/{lid}"
                new_lots.append((url, lid))
        except Exception as exc:
            log.debug("get_seller_new_lots: skipped %s for seller %s: %s", game_path, seller, exc)

    # Limit on first scan to avoid bulk-listing everything the seller has ever posted
    if not found_known and last_seen_lot_id is None and new_lots:
        new_lots = new_lots[:3]

    return new_lots


async def get_credentials(
    lot_id: str, token: str, proxy: Optional[str] = None
) -> Credentials:
    """Fetch credentials for a Lolzteam item that was already purchased."""
    import asyncio as _asyncio
    import logging as _logging
    log = _logging.getLogger(__name__)
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            item_data = await _api_get(f"/{lot_id}", token, proxy)
            item = item_data.get("item", item_data)
            login, password = _extract_creds_from_item(item)
            if login and password:
                return Credentials(login=login, password=password)
            if login and not password:
                log.debug(
                    "get_credentials: got login=%r but empty password for lot %s (attempt %d), retrying",
                    login, lot_id, attempt + 1,
                )
                last_err = ValueError(f"login found ({login!r}) but password empty")
            elif not isinstance(item, dict):
                last_err = ValueError(
                    f"item is {type(item).__name__} (expected dict): {str(item)[:100]}"
                )
        except Exception as e:
            last_err = e
        await _asyncio.sleep(2)
    raise LolzError(
        f"Could not fetch credentials for already-purchased lot {lot_id}: {last_err}"
    )
