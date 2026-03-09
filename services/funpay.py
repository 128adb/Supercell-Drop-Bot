"""Funpay.com integration — create/delete lots, monitor orders, send messages, bump."""
from __future__ import annotations
import asyncio
import logging
import re
import json
from dataclasses import dataclass
from typing import Optional
import aiohttp
from bs4 import BeautifulSoup
from yarl import URL

_log = logging.getLogger(__name__)

FUNPAY_BASE = "https://funpay.com"

GAME_OFFER_MAP = {
    "bs": {"nodeId": "436"},   # Brawl Stars accounts node ID
    "cr": {"nodeId": "114"},   # Clash Royale accounts node ID
    "coc": {"nodeId": "112"},  # Clash of Clans accounts node ID
}


@dataclass
class FunpayOrder:
    order_id: str
    chat_id: str
    funpay_lot_id: str
    buyer_message: Optional[str]
    unread: bool


class FunpayError(Exception):
    pass


def _make_proxy(proxy: Optional[str]) -> Optional[str]:
    if not proxy:
        return None
    if "@" in proxy:
        auth, addr = proxy.rsplit("@", 1)
        return f"http://{auth}@{addr}"
    return f"http://{proxy}"


def _session_headers(golden_key: str) -> dict:
    return {
        "Cookie": f"golden_key={golden_key}; PHPSESSID=placeholder",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8",
        "Referer": FUNPAY_BASE,
    }


async def _fetch_home(golden_key: str, proxy: Optional[str] = None) -> str:
    """Fetch Funpay home page (authenticated) and return HTML."""
    async with aiohttp.ClientSession(headers=_session_headers(golden_key)) as session:
        async with session.get(
            FUNPAY_BASE,
            proxy=_make_proxy(proxy),
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            return await resp.text()


def _extract_csrf_token(html: str) -> str:
    m = (
        re.search(r'&quot;csrf-token&quot;:&quot;([^&]+)&quot;', html)
        or re.search(r'"csrf-token"\s*:\s*"([^"]+)"', html)
        or re.search(r'<meta[^>]+name=["\']csrf-token["\'][^>]+content=["\']([^"\']+)["\']', html)
        or re.search(r"csrf[_-]?token\s*[=:]\s*['\"]([^'\"]+)['\"]", html, re.IGNORECASE)
    )
    if not m:
        raise FunpayError("Could not extract CSRF token from Funpay")
    return m.group(1)


def _extract_user_id(html: str) -> str:
    m = (
        re.search(r'"userId"\s*:\s*(\d+)', html)
        or re.search(r"data-app-data=['\"].*?userId.*?(\d+)", html)
    )
    if not m:
        raise FunpayError("Could not extract user ID (golden_key invalide ou expiré ?)")
    return m.group(1)


async def _get_csrf_token(golden_key: str, proxy: Optional[str] = None) -> str:
    """Fetch Funpay home page and extract csrf_token."""
    return _extract_csrf_token(await _fetch_home(golden_key, proxy))


async def get_user_id(golden_key: str, proxy: Optional[str] = None) -> str:
    """Get authenticated user's Funpay user ID."""
    return _extract_user_id(await _fetch_home(golden_key, proxy))


async def _get_offer_form_fields(
    golden_key: str,
    node_id: str,
    proxy: Optional[str] = None,
) -> dict:
    """GET /lots/offerEdit?node=NODE_ID and extract every form field with its default value."""
    async with aiohttp.ClientSession(headers=_session_headers(golden_key)) as session:
        async with session.get(
            f"{FUNPAY_BASE}/lots/offerEdit?node={node_id}",
            proxy=_make_proxy(proxy),
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            html = await resp.text()

    soup = BeautifulSoup(html, "lxml")
    form = soup.find("form")
    if not form:
        raise FunpayError("offerEdit: formulaire introuvable (golden_key invalide ou session expirée)")

    fields: dict = {}
    for el in form.find_all(["input", "textarea", "select"]):
        name = el.get("name")
        if not name:
            continue
        if el.name == "textarea":
            fields[name] = el.get_text()
        elif el.name == "select":
            selected = el.find("option", selected=True)
            fields[name] = selected.get("value", "") if selected else ""
        elif el.get("type") in ("checkbox", "radio"):
            if el.get("checked"):
                fields[name] = el.get("value", "on")
        else:
            fields[name] = el.get("value", "")
    return fields


async def _public_offer_ids(
    user_id: str,
    proxy: Optional[str] = None,
    timeout: Optional[aiohttp.ClientTimeout] = None,
) -> set:
    """
    Fetch the PUBLIC (unauthenticated) profile page and return offer IDs.

    FunPay shows the seller's active listings in static HTML on the public
    profile page (as buyers see it).  The authenticated owner view loads lots
    via JavaScript and cannot be scraped.
    """
    if timeout is None:
        timeout = aiohttp.ClientTimeout(total=15)
    # Use a plain session — no golden_key cookie → public view
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{FUNPAY_BASE}/users/{user_id}/",
            proxy=proxy,
            timeout=timeout,
        ) as resp:
            html = await resp.text()
    # Links look like /lots/offer?id=12345 (or /en/lots/offer?id=12345)
    return set(re.findall(r'offer\?id=(\d+)', html))


async def _get_user_offer_ids(
    golden_key: str,
    user_id: str,
    proxy: Optional[str] = None,
) -> set:
    """Fetch the user's profile page and return all offer IDs visible there."""
    async with aiohttp.ClientSession(headers=_session_headers(golden_key)) as session:
        async with session.get(
            f"{FUNPAY_BASE}/users/{user_id}/",
            proxy=_make_proxy(proxy),
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            html = await resp.text()
    # Offer links look like: /lots/offer?id=12345
    return set(re.findall(r'lots/offer\?id=(\d+)', html))


async def create_lot(
    golden_key: str,
    game: str,
    title_ru: str,
    title_en: str,
    desc_ru: str,
    desc_en: str,
    price: float,
    game_fields: Optional[dict] = None,
    proxy: Optional[str] = None,
) -> str:
    """
    Create a lot on Funpay. Returns the funpay_lot_id.

    All HTTP requests share ONE aiohttp session so PHP's PHPSESSID (set via
    Set-Cookie on the first request) persists in the cookie jar.  This ensures
    the CSRF token extracted from the form page is valid when we POST to
    /lots/offerSave — the classic "Обновите страницу" error happens when
    CSRF and PHPSESSID belong to different PHP sessions.
    """
    node_id = GAME_OFFER_MAP.get(game, {}).get("nodeId", "436")
    proxy_str = _make_proxy(proxy)
    timeout = aiohttp.ClientTimeout(total=20)

    # Cookie jar pre-seeded with golden_key; PHPSESSID will be added
    # automatically when PHP sends Set-Cookie on the first response.
    jar = aiohttp.CookieJar()
    jar.update_cookies({"golden_key": golden_key}, URL(FUNPAY_BASE))

    base_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8",
        "Referer": FUNPAY_BASE,
    }

    async with aiohttp.ClientSession(headers=base_headers, cookie_jar=jar) as session:

        # ── Step 1 : home page → user ID (PHP sets real PHPSESSID here) ──────
        async with session.get(FUNPAY_BASE, proxy=proxy_str, timeout=timeout) as resp:
            home_html = await resp.text()
        user_id = _extract_user_id(home_html)

        # ── Step 1b : snapshot of existing offers (public/unauthenticated view) ─
        # The authenticated owner view loads lots via JS; the public buyer view
        # embeds them in the static HTML that we can scrape.
        old_ids = await _public_offer_ids(user_id, proxy_str, timeout)

        # ── Step 2 : form fields + CSRF (same PHPSESSID → CSRF is valid) ─────
        async with session.get(
            f"{FUNPAY_BASE}/lots/offerEdit?node={node_id}",
            proxy=proxy_str,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            form_html = await resp.text()

        soup = BeautifulSoup(form_html, "lxml")
        # The page has multiple forms — we need the offer editor, NOT the search bar.
        form = soup.select_one("form.form-offer-editor")
        if not form:
            raise FunpayError(
                "offerEdit: formulaire introuvable (golden_key invalide ou expiré ?)"
            )

        # Use the form's own action URL (may include /en/ prefix)
        form_action = form.get("action") or f"{FUNPAY_BASE}/lots/offerSave"

        form_fields: dict = {}
        for el in form.find_all(["input", "textarea", "select"]):
            name = el.get("name")
            if not name:
                continue
            if el.name == "textarea":
                form_fields[name] = el.get_text()
            elif el.name == "select":
                selected = el.find("option", selected=True)
                form_fields[name] = selected.get("value", "") if selected else ""
            elif el.get("type") in ("checkbox", "radio"):
                if el.get("checked"):
                    form_fields[name] = el.get("value", "on")
            else:
                form_fields[name] = el.get("value", "")

        csrf_token = _extract_csrf_token(form_html)

        # ── Step 3 : build payload ────────────────────────────────────────────
        payload = {
            **form_fields,
            "csrf_token": csrf_token,
            "offer_id": "0",   # 0 = create new lot
            "node_id": node_id,
            "location": "",
            "deleted": "",
            "active": "on",
            "price": f"{price:.2f}",
            "amount": "1",
            # Real field names from the offer editor form
            "fields[summary][ru]": title_ru,
            "fields[summary][en]": title_en,
            "fields[desc][ru]": desc_ru,
            "fields[desc][en]": desc_en,
            # Game-specific required fields (e.g. fields[cup], fields[hero] for BS)
            **(game_fields or {}),
        }

        # ── Step 4 : POST offerSave ───────────────────────────────────────────
        # FunPay's JS submits the form as AJAX.  We must replicate those headers:
        #   - X-Requested-With: XMLHttpRequest  → tells PHP it is an AJAX call
        #   - Referer: the form page URL         → CSRF/referer check
        #   - Origin: funpay.com                 → same-origin check
        # With these headers and allow_redirects=True the final resp.url contains
        # the new offer ID when FunPay redirects on success.
        referer_url = f"{FUNPAY_BASE}/lots/offerEdit?node={node_id}"
        ajax_headers = {
            "Referer": referer_url,
            "Origin": FUNPAY_BASE,
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        }
        async with session.post(
            form_action,
            data=payload,
            proxy=proxy_str,
            allow_redirects=True,
            headers=ajax_headers,
            timeout=aiohttp.ClientTimeout(total=25),
        ) as resp:
            save_status = resp.status
            final_url = str(resp.url)
            location = resp.headers.get("Location", "")
            save_html = await resp.text()

        # ── Step 5 : recover new lot ID ──────────────────────────────────────

        # 5a. Final URL after redirect (allow_redirects=True) or Location header
        for src in (final_url, location):
            m = re.search(r'[?&]offer=(\d+)', src)
            if m:
                return m.group(1)

        # 5b. Body may be JSON (some FunPay endpoints return JSON errors)
        try:
            data = json.loads(save_html)
            if data.get("error"):
                msg = data.get("msg") or data.get("message") or str(data.get("errors", ""))
                raise FunpayError(f"Rejeté par Funpay : {msg}")
            for key in ("offer_id", "offerId", "id"):
                if data.get(key):
                    return str(data[key])
        except (json.JSONDecodeError, AttributeError):
            pass

        # 5c. Patterns in response body
        m = (
            re.search(r'[?&]offer=(\d+)', save_html)
            or re.search(r'lots/offer\?id=(\d+)', save_html)
            or re.search(r'"offer[_-]?id"\s*:\s*"?(\d+)"?', save_html)
        )
        if m:
            return m.group(1)

        # 5d. Profile diff — public view (static HTML contains lot links).
        # FunPay propagates the new lot to the public profile with a small delay,
        # so we retry a few times before giving up.
        for attempt in range(4):
            await asyncio.sleep(3)
            async with aiohttp.ClientSession() as pub:
                async with pub.get(
                    f"{FUNPAY_BASE}/users/{user_id}/",
                    proxy=proxy_str,
                    timeout=timeout,
                ) as resp:
                    profile_html2 = await resp.text()
            new_ids = set(re.findall(r'offer\?id=(\d+)', profile_html2))
            created = new_ids - old_ids
            if created:
                return created.pop()

        # 5e: nothing worked — dump debug info for inspection
        debug = (
            f"STATUS: {save_status}\n"
            f"FINAL_URL: {final_url}\n"
            f"LOCATION: {location}\n"
            f"BODY ({len(save_html)} chars):\n{save_html}\n\n"
            f"old_ids: {old_ids}\n"
            f"new_ids: {new_ids}\n"
        )
        with open("error_funpay.html", "w", encoding="utf-8") as f:
            f.write(debug)
        with open("debug_profile.html", "w", encoding="utf-8") as f:
            f.write(profile_html2)

        soup2 = BeautifulSoup(save_html, "lxml")
        error_div = soup2.select_one(".help-block, .has-error, .alert, .error, .text-danger")
        extracted_error = (
            error_div.get_text(strip=True) if error_div
            else f"HTTP {save_status} — Location: '{location}' — voir error_funpay.html"
        )
        raise FunpayError(f"Lot créé mais ID introuvable : {extracted_error}")


async def delete_lot(
    golden_key: str, lot_id: str, proxy: Optional[str] = None
) -> None:
    """
    Deactivate (soft-delete) a lot on Funpay.

    FunPay has no separate delete endpoint.  The correct way is to POST to
    /lots/offerSave with the existing offer_id and deleted=1, which marks the
    lot as deleted.  We first GET /lots/offerEdit?offer={lot_id} to obtain the
    full form fields and a valid CSRF token (same PHP session → CSRF works).
    """
    proxy_str = _make_proxy(proxy)
    timeout = aiohttp.ClientTimeout(total=20)

    jar = aiohttp.CookieJar()
    jar.update_cookies({"golden_key": golden_key}, URL(FUNPAY_BASE))

    base_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8",
        "Referer": FUNPAY_BASE,
    }

    async with aiohttp.ClientSession(headers=base_headers, cookie_jar=jar) as session:
        # GET the offer edit page — PHP sets PHPSESSID; we get form fields + CSRF
        async with session.get(
            f"{FUNPAY_BASE}/lots/offerEdit?offer={lot_id}",
            proxy=proxy_str,
            timeout=timeout,
        ) as resp:
            form_html = await resp.text()

        soup = BeautifulSoup(form_html, "lxml")
        form = soup.select_one("form.form-offer-editor")
        if not form:
            raise FunpayError(f"delete_lot: offer edit form not found for lot {lot_id}")

        form_action = form.get("action") or f"{FUNPAY_BASE}/lots/offerSave"
        csrf_token = _extract_csrf_token(form_html)

        # Collect all existing form fields
        form_fields: dict = {}
        for el in form.find_all(["input", "textarea", "select"]):
            name = el.get("name")
            if not name:
                continue
            if el.name == "textarea":
                form_fields[name] = el.get_text()
            elif el.name == "select":
                selected = el.find("option", selected=True)
                form_fields[name] = selected.get("value", "") if selected else ""
            elif el.get("type") in ("checkbox", "radio"):
                if el.get("checked"):
                    form_fields[name] = el.get("value", "on")
            else:
                form_fields[name] = el.get("value", "")

        payload = {
            **form_fields,
            "csrf_token": csrf_token,
            "offer_id": lot_id,
            "deleted": "1",   # marks the lot as deleted
        }

        async with session.post(
            form_action,
            data=payload,
            proxy=proxy_str,
            headers={
                "Referer": f"{FUNPAY_BASE}/lots/offerEdit?offer={lot_id}",
                "Origin": FUNPAY_BASE,
                "X-Requested-With": "XMLHttpRequest",
            },
            timeout=timeout,
        ) as resp:
            if resp.status not in (200, 302):
                raise FunpayError(f"Failed to delete lot {lot_id}: HTTP {resp.status}")


async def get_pending_orders(
    golden_key: str, proxy: Optional[str] = None
) -> list[FunpayOrder]:
    """
    Fetch sales from /orders/trade and return paid (not yet closed) orders.

    Note: funpay_lot_id is NOT available on the orders list page.
    Call get_order_page() for each order to fill it in.
    """
    async with aiohttp.ClientSession(headers=_session_headers(golden_key)) as session:
        async with session.get(
            f"{FUNPAY_BASE}/orders/trade",
            proxy=_make_proxy(proxy),
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            html = await resp.text()

    soup = BeautifulSoup(html, "lxml")
    orders = []

    for row in soup.select(".tc-item"):
        order_id_el = row.select_one(".tc-order")
        status_el = row.select_one(".tc-status")
        if not order_id_el:
            continue

        order_id = order_id_el.get_text(strip=True).lstrip("#")
        status_text = status_el.get_text(strip=True).lower() if status_el else ""

        # Only process orders that are "paid" (open) — skip "closed", "dispute", etc.
        if "paid" not in status_text and "оплач" not in status_text:
            continue

        orders.append(FunpayOrder(
            order_id=order_id,
            chat_id=order_id,
            funpay_lot_id="",   # filled in by get_order_page()
            buyer_message=None,
            unread=True,
        ))

    return orders


@dataclass
class OrderPage:
    funpay_lot_id: str   # may be empty — use account_tag as fallback
    account_tag: str     # extracted from detailed description, e.g. "#2CQYC0RV9C"
    messages: list
    csrf_token: str
    chat_node_id: str
    chat_tag: str  # data-tag attribute of .chat div, required by the runner API


async def get_order_page(
    golden_key: str, order_id: str, proxy: Optional[str] = None
) -> OrderPage:
    """
    Fetch an order detail page and extract:
      - funpay_lot_id : the offer ID of the purchased lot
      - messages      : list of {sender, text} dicts (user messages only)
      - csrf_token    : for subsequent POSTs in the same session
      - chat_node_id  : numeric data-id of the .chat div (used by /chat/message)
    """
    async with aiohttp.ClientSession(headers=_session_headers(golden_key)) as session:
        async with session.get(
            f"{FUNPAY_BASE}/orders/{order_id}/",
            proxy=_make_proxy(proxy),
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            html = await resp.text()

    soup = BeautifulSoup(html, "lxml")

    # ── Lot / offer ID ────────────────────────────────────────────────────────
    # Offer IDs have ≥5 digits; node IDs are typically 3 digits — filter by length.
    lot_id = ""
    m = re.search(r'offer[?=&]id[=](\d+)', html)  # /lots/offer?id=65477619
    if not m:
        m = re.search(r'/lots/(\d{5,})/', html)
    if m:
        lot_id = m.group(1)

    # ── Account tag ───────────────────────────────────────────────────────────
    # The detailed description contains "Account tag: #XXXXXXX" (generated by us).
    account_tag = ""
    mt = re.search(r'Account tag:\s*#?([A-Z0-9]{4,12})', html)
    if mt:
        account_tag = "#" + mt.group(1)

    # ── Chat messages ─────────────────────────────────────────────────────────
    messages = []
    for item in soup.select(".chat-msg-item"):
        if item.select_one(".chat-msg-author-label"):  # system notification → skip
            continue
        text_el = item.select_one(".chat-msg-text")
        if not text_el:
            continue
        sender_el = item.select_one(".chat-msg-author-link")
        messages.append({
            "sender": sender_el.get_text(strip=True) if sender_el else "unknown",
            "text": text_el.get_text(strip=True),
        })

    # ── CSRF + chat node ─────────────────────────────────────────────────────
    csrf_token = _extract_csrf_token(html)
    chat_div = soup.select_one(".chat[data-id]")
    if not chat_div:
        raise FunpayError(f"Could not find chat node_id on order page {order_id}")
    chat_node_id = chat_div["data-id"]

    chat_tag = chat_div.get("data-tag", "") if chat_div else ""

    return OrderPage(
        funpay_lot_id=lot_id,
        account_tag=account_tag,
        messages=messages,
        csrf_token=csrf_token,
        chat_node_id=chat_node_id,
        chat_tag=chat_tag,
    )


async def send_message(
    golden_key: str,
    order_id: str,
    text: str,
    proxy: Optional[str] = None,
    chat_node_id: Optional[str] = None,
    csrf_token: Optional[str] = None,
    chat_tag: Optional[str] = None,
) -> None:
    """
    Send a message in a FunPay order chat via the runner API.

    FunPay's chat is driven by a long-polling runner endpoint at /runner/.

    IMPORTANT: Uses the CookieJar approach (like create_lot/delete_lot) so that
    PHP sets a real PHPSESSID via Set-Cookie on the first GET.  With a fake
    PHPSESSID (the old _session_headers approach), FunPay returns 200 OK but
    silently drops the message content and never delivers it to the buyer.

    Flow:
      1. GET home → real PHPSESSID is set in the cookie jar + CSRF token extracted
      2. GET order page (same session, if chat info not pre-fetched) → chat_node_id + chat_tag
      3. POST /runner/ (same session) → real PHPSESSID sent → message delivered
    """
    proxy_str = _make_proxy(proxy)
    timeout = aiohttp.ClientTimeout(total=15)

    # CookieJar pre-seeded with golden_key; PHPSESSID will be added by PHP's Set-Cookie
    jar = aiohttp.CookieJar()
    jar.update_cookies({"golden_key": golden_key}, URL(FUNPAY_BASE))

    base_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8",
        "Referer": FUNPAY_BASE,
    }

    async with aiohttp.ClientSession(headers=base_headers, cookie_jar=jar) as session:

        # ── Step 1: GET home page → FunPay sets real PHPSESSID + CSRF token ──
        async with session.get(FUNPAY_BASE, proxy=proxy_str, timeout=timeout) as resp:
            home_html = await resp.text()
        csrf_token = _extract_csrf_token(home_html)

        # Debug: confirm PHPSESSID is now in the jar (not "placeholder")
        phpsessid = next(
            (c.value for c in jar if c.key == "PHPSESSID"), "NOT SET"
        )
        _log.debug("send_message: PHPSESSID in jar = %r", phpsessid)

        # ── Step 2: GET order page for chat_node_id + chat_tag if not provided ─
        if not chat_node_id or not chat_tag:
            async with session.get(
                f"{FUNPAY_BASE}/orders/{order_id}/",
                proxy=proxy_str,
                timeout=timeout,
            ) as resp:
                html = await resp.text()
            soup = BeautifulSoup(html, "lxml")
            chat_div = soup.select_one(".chat[data-id]")
            if not chat_div:
                raise FunpayError(f"Could not find chat div for order {order_id}")
            chat_node_id = chat_div["data-id"]
            chat_tag = chat_div.get("data-tag", "")

        node_id_int = int(chat_node_id)

        # ── Step 3: POST to /runner/ — send the message ───────────────────────
        #
        # FunPay's runner protocol (confirmed from FunPayVertex / FunPayCardinal):
        #   objects  → chat_node subscription (tag="00000000", last_message=-1)
        #   request  → action to perform (singular "request", NOT "requests")
        #              format: {"action": "chat_message", "data": {...}}
        #
        # Sending `last_message: -1` means "don't filter by message ID" (correct for send).
        # Using tag "00000000" is the canonical value when establishing a fresh subscription.
        runner_headers = {
            "Referer": f"{FUNPAY_BASE}/orders/{order_id}/",
            "Origin": FUNPAY_BASE,
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "*/*",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        }

        send_objects = json.dumps([{
            "type": "chat_node",
            "id": node_id_int,
            "tag": "00000000",
            "data": {
                "node": node_id_int,
                "last_message": -1,
                "content": "",
            },
        }])
        send_request = json.dumps({
            "action": "chat_message",
            "data": {
                "node": node_id_int,
                "last_message": -1,
                "content": text,
            },
        })

        async with session.post(
            f"{FUNPAY_BASE}/runner/",
            data={
                "csrf_token": csrf_token,
                "objects": send_objects,
                "request": send_request,   # singular "request"
            },
            proxy=proxy_str,
            headers=runner_headers,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            if resp.status not in (200, 302):
                raise FunpayError(f"Failed to send message: HTTP {resp.status}")
            body = await resp.text()
            _log.debug(
                "Runner send response for order %s (node=%s): %s",
                order_id, chat_node_id, body[:2000],
            )
            try:
                rdata = json.loads(body)
                if isinstance(rdata, dict) and (rdata.get("error") or rdata.get("errors")):
                    raise FunpayError(f"Runner error: {rdata}")
            except (json.JSONDecodeError, TypeError):
                pass  # non-JSON response is fine

        # ── Verification: re-fetch order page to confirm message appeared ─────
        await asyncio.sleep(1)
        async with session.get(
            f"{FUNPAY_BASE}/orders/{order_id}/",
            proxy=proxy_str,
            timeout=timeout,
        ) as resp:
            verify_html = await resp.text()

        all_msg_ids = re.findall(r'id="message-(\d+)"', verify_html)
        _log.debug(
            "Verification for order %s: message IDs in page = %s",
            order_id, all_msg_ids,
        )


async def update_lot_price(
    golden_key: str, lot_id: str, new_price: float, proxy: Optional[str] = None
) -> None:
    """
    Update the price of an existing Funpay lot.

    Same session pattern as delete_lot: GET offerEdit for form fields + CSRF,
    then POST offerSave with the updated price (without deleted=1).
    """
    proxy_str = _make_proxy(proxy)
    timeout = aiohttp.ClientTimeout(total=20)

    jar = aiohttp.CookieJar()
    jar.update_cookies({"golden_key": golden_key}, URL(FUNPAY_BASE))

    base_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8",
        "Referer": FUNPAY_BASE,
    }

    async with aiohttp.ClientSession(headers=base_headers, cookie_jar=jar) as session:
        async with session.get(
            f"{FUNPAY_BASE}/lots/offerEdit?offer={lot_id}",
            proxy=proxy_str,
            timeout=timeout,
        ) as resp:
            form_html = await resp.text()

        soup = BeautifulSoup(form_html, "lxml")
        form = soup.select_one("form.form-offer-editor")
        if not form:
            raise FunpayError(f"update_lot_price: offer edit form not found for lot {lot_id}")

        form_action = form.get("action") or f"{FUNPAY_BASE}/lots/offerSave"
        csrf_token = _extract_csrf_token(form_html)

        form_fields: dict = {}
        for el in form.find_all(["input", "textarea", "select"]):
            name = el.get("name")
            if not name:
                continue
            if el.name == "textarea":
                form_fields[name] = el.get_text()
            elif el.name == "select":
                selected = el.find("option", selected=True)
                form_fields[name] = selected.get("value", "") if selected else ""
            elif el.get("type") in ("checkbox", "radio"):
                if el.get("checked"):
                    form_fields[name] = el.get("value", "on")
            else:
                form_fields[name] = el.get("value", "")

        payload = {
            **form_fields,
            "csrf_token": csrf_token,
            "offer_id": lot_id,
            "price": f"{new_price:.2f}",
            "deleted": "",    # NOT deleted — keep active
            "active": "on",
        }

        async with session.post(
            form_action,
            data=payload,
            proxy=proxy_str,
            headers={
                "Referer": f"{FUNPAY_BASE}/lots/offerEdit?offer={lot_id}",
                "Origin": FUNPAY_BASE,
                "X-Requested-With": "XMLHttpRequest",
            },
            timeout=timeout,
        ) as resp:
            if resp.status not in (200, 302):
                raise FunpayError(f"Failed to update price for lot {lot_id}: HTTP {resp.status}")


@dataclass
class ChatPreview:
    """A chat entry from the FunPay /chat/ inbox."""
    node_id: str
    sender: str
    last_message: str
    lot_title: str       # "Viewing …" context shown by FunPay, may be empty
    funpay_lot_id: str   # associated offer ID extracted from the page, may be empty
    unread_count: int


async def get_unread_chats(
    golden_key: str, proxy: Optional[str] = None
) -> list[ChatPreview]:
    """
    Fetch /chat/ and return only the contact items that have unread messages.

    FunPay renders the chat list in server-side HTML: each conversation is a
    .contact-item div with a data-id attribute (the chat node ID).  Unread
    conversations have a visible badge element with the unread count.
    """
    async with aiohttp.ClientSession(headers=_session_headers(golden_key)) as session:
        async with session.get(
            f"{FUNPAY_BASE}/chat/",
            proxy=_make_proxy(proxy),
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            html = await resp.text()

    soup = BeautifulSoup(html, "lxml")
    result: list[ChatPreview] = []

    for item in soup.select(".contact-item"):
        # Unread indicator — FunPay uses a .badge or data-unread attribute
        badge = item.select_one(".badge, .unread-count")
        try:
            unread_count = int(badge.get_text(strip=True)) if badge else 0
        except (ValueError, AttributeError):
            unread_count = 1 if badge else 0

        if unread_count == 0:
            continue

        node_id = item.get("data-id", "").strip()
        if not node_id:
            continue

        # Sender username
        sender_el = (
            item.select_one(".chat-name")
            or item.select_one(".contact-item-username")
            or item.select_one(".username")
        )
        sender = sender_el.get_text(strip=True) if sender_el else "Unknown"

        # Message preview
        text_el = (
            item.select_one(".link-muted")
            or item.select_one(".contact-item-text")
            or item.select_one(".last-message")
        )
        last_msg = text_el.get_text(strip=True) if text_el else ""

        # Lot title shown in the contact item (e.g. "Viewing: BS account …")
        title_el = (
            item.select_one(".contact-item-offer")
            or item.select_one(".offer-title")
            or item.select_one(".contact-item-title")
        )
        lot_title = title_el.get_text(strip=True) if title_el else ""

        # Try to find an offer ID embedded in this item's HTML
        item_html = str(item)
        funpay_lot_id = ""
        m = re.search(r'offer\?id=(\d+)', item_html) or re.search(r'offer[=&](\d{5,})', item_html)
        if m:
            funpay_lot_id = m.group(1)

        result.append(ChatPreview(
            node_id=node_id,
            sender=sender,
            last_message=last_msg,
            lot_title=lot_title,
            funpay_lot_id=funpay_lot_id,
            unread_count=unread_count,
        ))

    return result


async def get_chat_detail(
    golden_key: str, node_id: str, proxy: Optional[str] = None
) -> tuple[str, str, list[dict]]:
    """
    Fetch /chat/?node=NODE_ID.

    Returns:
        funpay_lot_id  — offer ID associated with this chat (may be empty)
        lot_title      — lot title / "Viewing" context (may be empty)
        messages       — list of {sender, text} dicts (newest last)
    """
    async with aiohttp.ClientSession(headers=_session_headers(golden_key)) as session:
        async with session.get(
            f"{FUNPAY_BASE}/chat/?node={node_id}",
            proxy=_make_proxy(proxy),
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            html = await resp.text()

    soup = BeautifulSoup(html, "lxml")

    # ── Extract offer ID from any lot link on the page ────────────────────────
    funpay_lot_id = ""
    m = re.search(r'/lots/offer\?id=(\d+)', html) or re.search(r'offer\?id=(\d+)', html)
    if m:
        funpay_lot_id = m.group(1)

    # ── Lot title / "Viewing" subject ─────────────────────────────────────────
    lot_title = ""
    for sel in [".chat-offer-link", ".offer-title", ".subject",
                ".chat-subject", ".contact-item-title", ".offer-name",
                ".chat-header-subject"]:
        el = soup.select_one(sel)
        if el:
            lot_title = el.get_text(strip=True)
            break
    # Fallback: look for the literal "Viewing" text pattern in raw HTML
    if not lot_title:
        mv = re.search(r'Viewing[:\s]+([^\n<"]{5,})', html)
        if mv:
            lot_title = mv.group(1).strip()

    # ── Chat messages (same structure as order pages) ─────────────────────────
    messages: list[dict] = []
    for item in soup.select(".chat-msg-item"):
        if item.select_one(".chat-msg-author-label"):   # system note → skip
            continue
        text_el = item.select_one(".chat-msg-text")
        if not text_el:
            continue
        sender_el = item.select_one(".chat-msg-author-link")
        messages.append({
            "sender": sender_el.get_text(strip=True) if sender_el else "unknown",
            "text": text_el.get_text(strip=True),
        })

    return funpay_lot_id, lot_title, messages


async def bump_lots(
    golden_key: str,
    games: list[str],
    proxy: Optional[str] = None,
) -> None:
    """Auto-raise lots for specified games."""
    csrf_token = await _get_csrf_token(golden_key, proxy)
    async with aiohttp.ClientSession(headers=_session_headers(golden_key)) as session:
        for game in games:
            node_id = GAME_OFFER_MAP.get(game, {}).get("nodeId", "")
            if not node_id:
                continue
            payload = {"csrf_token": csrf_token, "node_id": node_id}
            async with session.post(
                f"{FUNPAY_BASE}/lots/raise",
                data=payload,
                proxy=_make_proxy(proxy),
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                pass  # best-effort, ignore per-game failures
