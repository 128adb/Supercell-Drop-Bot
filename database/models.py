import aiosqlite
from config import DATABASE_PATH

CREATE_USERS = """
CREATE TABLE IF NOT EXISTS users (
    telegram_id       INTEGER PRIMARY KEY,
    lolz_token        TEXT,
    lolz_secret       TEXT,
    funpay_golden_key TEXT,
    markup_percent    REAL DEFAULT 35.0,
    proxy             TEXT,
    auto_bump_bs      INTEGER DEFAULT 0,
    auto_bump_cr      INTEGER DEFAULT 0,
    auto_bump_coc     INTEGER DEFAULT 0,
    price_drop_enabled INTEGER DEFAULT 0,
    price_drop_days   INTEGER DEFAULT 3,
    price_drop_percent REAL DEFAULT 10.0,
    price_drop_floor  REAL DEFAULT 50.0,
    lolz_balance_alert REAL DEFAULT 0,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

CREATE_LOTS = """
CREATE TABLE IF NOT EXISTS lots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(telegram_id),
    lolz_lot_url    TEXT NOT NULL,
    lolz_lot_id     TEXT NOT NULL,
    funpay_lot_id   TEXT,
    game            TEXT NOT NULL,
    account_tag     TEXT,
    lolz_price      REAL,
    funpay_price    REAL,
    status          TEXT DEFAULT 'active',
    error_count     INTEGER DEFAULT 0,
    sold_at         TIMESTAMP,
    price_drop_count INTEGER DEFAULT 0,
    last_price_drop  TIMESTAMP,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

CREATE_SALES = """
CREATE TABLE IF NOT EXISTS sales (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL,
    lot_id       INTEGER,
    order_id     TEXT NOT NULL UNIQUE,
    game         TEXT,
    account_tag  TEXT,
    lolz_price   REAL DEFAULT 0,
    funpay_price REAL DEFAULT 0,
    profit       REAL DEFAULT 0,
    login        TEXT,
    password     TEXT,
    sold_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

CREATE_WATCHLIST = """
CREATE TABLE IF NOT EXISTS watchlist (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL,
    lolz_seller   TEXT NOT NULL,
    enabled       INTEGER DEFAULT 1,
    last_seen_lot TEXT,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, lolz_seller)
)
"""

# Migrations for existing DBs (new columns added after initial release)
_MIGRATIONS = [
    "ALTER TABLE users ADD COLUMN price_drop_enabled INTEGER DEFAULT 0",
    "ALTER TABLE users ADD COLUMN price_drop_days INTEGER DEFAULT 3",
    "ALTER TABLE users ADD COLUMN price_drop_percent REAL DEFAULT 10.0",
    "ALTER TABLE users ADD COLUMN price_drop_floor REAL DEFAULT 50.0",
    "ALTER TABLE users ADD COLUMN lolz_balance_alert REAL DEFAULT 0",
    "ALTER TABLE lots ADD COLUMN sold_at TIMESTAMP",
    "ALTER TABLE lots ADD COLUMN price_drop_count INTEGER DEFAULT 0",
    "ALTER TABLE lots ADD COLUMN last_price_drop TIMESTAMP",
]


async def init_db() -> None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(CREATE_USERS)
        await db.execute(CREATE_LOTS)
        await db.execute(CREATE_SALES)
        await db.execute(CREATE_WATCHLIST)
        await db.commit()

        # Run migrations for existing databases (ignore duplicate column errors)
        for sql in _MIGRATIONS:
            try:
                await db.execute(sql)
                await db.commit()
            except Exception:
                pass  # Column already exists — safe to ignore
