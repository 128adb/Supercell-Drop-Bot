from __future__ import annotations
from typing import Any
import aiosqlite
from config import DATABASE_PATH


# ─── helpers ──────────────────────────────────────────────────────────────────

async def _fetchone(query: str, params: tuple = ()) -> dict | None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(query, params) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def _fetchall(query: str, params: tuple = ()) -> list[dict]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(query, params) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def _execute(query: str, params: tuple = ()) -> int:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute(query, params) as cur:
            await db.commit()
            return cur.lastrowid or 0


# ─── users ────────────────────────────────────────────────────────────────────

async def get_user(telegram_id: int) -> dict | None:
    return await _fetchone("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))


async def upsert_user(telegram_id: int) -> None:
    await _execute(
        "INSERT OR IGNORE INTO users (telegram_id) VALUES (?)",
        (telegram_id,),
    )


async def update_user(telegram_id: int, **fields: Any) -> None:
    if not fields:
        return
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = tuple(fields.values()) + (telegram_id,)
    await _execute(f"UPDATE users SET {set_clause} WHERE telegram_id = ?", values)


async def get_all_users() -> list[dict]:
    return await _fetchall("SELECT * FROM users")


# ─── lots ─────────────────────────────────────────────────────────────────────

async def create_lot(
    user_id: int,
    lolz_lot_url: str,
    lolz_lot_id: str,
    game: str,
    account_tag: str,
    lolz_price: float,
    funpay_price: float,
    funpay_lot_id: str = "",
    desc_ru: str = "",
) -> int:
    return await _execute(
        """INSERT INTO lots
           (user_id, lolz_lot_url, lolz_lot_id, game, account_tag,
            lolz_price, funpay_price, funpay_lot_id, desc_ru)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, lolz_lot_url, lolz_lot_id, game, account_tag,
         lolz_price, funpay_price, funpay_lot_id, desc_ru),
    )


async def get_lot_by_funpay_id(funpay_lot_id: str) -> dict | None:
    # Include 'invalid' lots: validity checker may have fired before order delivery.
    return await _fetchone(
        "SELECT * FROM lots WHERE funpay_lot_id = ? AND status NOT IN ('sold', 'deleted') ORDER BY id DESC",
        (funpay_lot_id,),
    )


async def get_lot_by_funpay_id_any(funpay_lot_id: str) -> dict | None:
    """Look up a lot by funpay_lot_id regardless of status.
    Used by chat_forwarder to retrieve the Lolzteam source URL for any lot,
    even if it has already been sold or deleted."""
    return await _fetchone(
        "SELECT * FROM lots WHERE funpay_lot_id = ? ORDER BY id DESC LIMIT 1",
        (funpay_lot_id,),
    )


async def get_lot_by_account_tag(account_tag: str) -> dict | None:
    """Look up a lot by account tag for order delivery.
    Includes 'invalid' lots to handle the race between validity checker and order monitor."""
    return await _fetchone(
        "SELECT * FROM lots WHERE account_tag = ? AND status NOT IN ('sold', 'deleted') ORDER BY id DESC",
        (account_tag,),
    )


async def get_active_lots_for_user(user_id: int) -> list[dict]:
    return await _fetchall(
        "SELECT * FROM lots WHERE user_id = ? AND status = 'active' ORDER BY created_at DESC",
        (user_id,),
    )


async def get_all_active_lots() -> list[dict]:
    return await _fetchall("SELECT * FROM lots WHERE status = 'active'")


async def update_lot_status(lot_id: int, status: str) -> None:
    if status == "sold":
        await _execute(
            "UPDATE lots SET status = ?, sold_at = CURRENT_TIMESTAMP WHERE id = ?",
            (status, lot_id),
        )
    else:
        await _execute("UPDATE lots SET status = ? WHERE id = ?", (status, lot_id))


async def update_lot_funpay_id(lot_id: int, funpay_lot_id: str) -> None:
    await _execute(
        "UPDATE lots SET funpay_lot_id = ? WHERE id = ?",
        (funpay_lot_id, lot_id),
    )


async def update_lot_price(lot_id: int, new_price: float) -> None:
    await _execute(
        """UPDATE lots
           SET funpay_price = ?,
               price_drop_count = price_drop_count + 1,
               last_price_drop = CURRENT_TIMESTAMP
           WHERE id = ?""",
        (new_price, lot_id),
    )


async def get_lots_for_price_drop() -> list[dict]:
    """Return active lots whose price should be dropped based on user settings."""
    return await _fetchall(
        """SELECT l.*, u.price_drop_enabled, u.price_drop_days,
                  u.price_drop_percent, u.price_drop_floor,
                  u.funpay_golden_key, u.proxy
           FROM lots l
           JOIN users u ON l.user_id = u.telegram_id
           WHERE l.status = 'active'
             AND u.price_drop_enabled = 1
             AND l.funpay_lot_id IS NOT NULL AND l.funpay_lot_id != ''
             AND (
               l.last_price_drop IS NULL
               AND CAST((julianday('now') - julianday(l.created_at)) AS INTEGER) >= u.price_drop_days
               OR
               l.last_price_drop IS NOT NULL
               AND CAST((julianday('now') - julianday(l.last_price_drop)) AS INTEGER) >= u.price_drop_days
             )"""
    )


async def increment_lot_errors(lot_id: int) -> int:
    """Increment error count and return new value."""
    await _execute(
        "UPDATE lots SET error_count = error_count + 1 WHERE id = ?",
        (lot_id,),
    )
    row = await _fetchone("SELECT error_count FROM lots WHERE id = ?", (lot_id,))
    return row["error_count"] if row else 0


async def delete_lot(lot_id: int) -> None:
    await _execute("UPDATE lots SET status = 'deleted' WHERE id = ?", (lot_id,))


# ─── sales ────────────────────────────────────────────────────────────────────

async def create_sale(
    user_id: int,
    order_id: str,
    lot_id: int | None = None,
    game: str = "",
    account_tag: str = "",
    lolz_price: float = 0,
    funpay_price: float = 0,
    profit: float = 0,
    login: str = "",
    password: str = "",
) -> int:
    return await _execute(
        """INSERT OR IGNORE INTO sales
           (user_id, lot_id, order_id, game, account_tag,
            lolz_price, funpay_price, profit, login, password)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, lot_id, order_id, game, account_tag,
         lolz_price, funpay_price, profit, login, password),
    )


async def get_sale_by_order(order_id: str) -> dict | None:
    return await _fetchone("SELECT * FROM sales WHERE order_id = ?", (order_id,))


async def is_order_delivered(order_id: str) -> bool:
    """Check DB if an order was already delivered (survives restart)."""
    row = await _fetchone("SELECT id FROM sales WHERE order_id = ?", (order_id,))
    return row is not None


async def get_user_stats(user_id: int) -> dict:
    """Return aggregated stats for a user."""
    total_listed = await _fetchone(
        "SELECT COUNT(*) as c FROM lots WHERE user_id = ? AND status != 'deleted'",
        (user_id,),
    )
    sold_stats = await _fetchone(
        """SELECT COUNT(*) as count,
                  COALESCE(SUM(funpay_price), 0) as revenue,
                  COALESCE(SUM(lolz_price), 0) as cost,
                  COALESCE(SUM(profit), 0) as profit
           FROM sales WHERE user_id = ?""",
        (user_id,),
    )
    by_game = await _fetchall(
        """SELECT game,
                  COUNT(*) as count,
                  COALESCE(SUM(profit), 0) as profit
           FROM sales WHERE user_id = ?
           GROUP BY game""",
        (user_id,),
    )
    recent = await _fetchall(
        """SELECT order_id, game, account_tag, profit, sold_at
           FROM sales WHERE user_id = ?
           ORDER BY sold_at DESC LIMIT 5""",
        (user_id,),
    )
    return {
        "total_listed": (total_listed or {}).get("c", 0),
        "total_sold": (sold_stats or {}).get("count", 0),
        "total_revenue": round((sold_stats or {}).get("revenue", 0), 2),
        "total_cost": round((sold_stats or {}).get("cost", 0), 2),
        "total_profit": round((sold_stats or {}).get("profit", 0), 2),
        "by_game": {row["game"]: {"count": row["count"], "profit": round(row["profit"], 2)}
                    for row in by_game},
        "recent_sales": recent,
    }


async def get_all_stats() -> dict:
    """Global stats across all users (for web dashboard)."""
    sold = await _fetchone(
        """SELECT COUNT(*) as count,
                  COALESCE(SUM(funpay_price), 0) as revenue,
                  COALESCE(SUM(profit), 0) as profit
           FROM sales""",
    )
    active = await _fetchone("SELECT COUNT(*) as c FROM lots WHERE status = 'active'")
    users = await _fetchone("SELECT COUNT(*) as c FROM users")
    return {
        "total_sold": (sold or {}).get("count", 0),
        "total_revenue": round((sold or {}).get("revenue", 0), 2),
        "total_profit": round((sold or {}).get("profit", 0), 2),
        "active_lots": (active or {}).get("c", 0),
        "total_users": (users or {}).get("c", 0),
    }


async def get_recent_sales(limit: int = 20) -> list[dict]:
    return await _fetchall(
        "SELECT * FROM sales ORDER BY sold_at DESC LIMIT ?",
        (limit,),
    )


# ─── watchlist ────────────────────────────────────────────────────────────────

async def add_to_watchlist(user_id: int, seller: str) -> bool:
    """Returns True if newly added, False if already existed."""
    existing = await _fetchone(
        "SELECT id FROM watchlist WHERE user_id = ? AND lolz_seller = ?",
        (user_id, seller),
    )
    if existing:
        return False
    await _execute(
        "INSERT INTO watchlist (user_id, lolz_seller) VALUES (?, ?)",
        (user_id, seller),
    )
    return True


async def remove_from_watchlist(user_id: int, seller: str) -> bool:
    row = await _fetchone(
        "SELECT id FROM watchlist WHERE user_id = ? AND lolz_seller = ?",
        (user_id, seller),
    )
    if not row:
        return False
    await _execute(
        "DELETE FROM watchlist WHERE user_id = ? AND lolz_seller = ?",
        (user_id, seller),
    )
    return True


async def get_watchlist(user_id: int) -> list[dict]:
    return await _fetchall(
        "SELECT * FROM watchlist WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,),
    )


async def get_all_watchlist_entries() -> list[dict]:
    return await _fetchall(
        """SELECT w.*, u.lolz_token, u.funpay_golden_key, u.markup_percent, u.proxy
           FROM watchlist w
           JOIN users u ON w.user_id = u.telegram_id
           WHERE w.enabled = 1
             AND u.lolz_token IS NOT NULL
             AND u.funpay_golden_key IS NOT NULL"""
    )


async def update_watchlist_last_seen(entry_id: int, lot_id: str) -> None:
    await _execute(
        "UPDATE watchlist SET last_seen_lot = ? WHERE id = ?",
        (lot_id, entry_id),
    )


async def toggle_watchlist_entry(entry_id: int, enabled: bool) -> None:
    await _execute(
        "UPDATE watchlist SET enabled = ? WHERE id = ?",
        (int(enabled), entry_id),
    )
