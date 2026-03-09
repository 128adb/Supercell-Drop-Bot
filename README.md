# 🎮 Supercell Dropbot

A Telegram bot that automates Supercell account dropshipping from **Lolzteam** (lolz.live) to **Funpay**. When a buyer purchases an account on Funpay, the bot automatically buys it on Lolzteam and delivers the credentials to the buyer.

---

## Features

| # | Feature | Description |
|---|---------|-------------|
| ✅ | **Auto Listing** | Send a lolz.live URL → bot fetches stats, generates Funpay listing, sets price |
| ✅ | **Bulk Import** | Send multiple lolz.live URLs at once for batch listing |
| ✅ | **Auto Delivery** | Monitors Funpay orders every 30s, buys on Lolzteam, sends credentials automatically |
| ✅ | **Auto-Reply** | FAQ responses to buyer questions; post-delivery credential resend |
| ✅ | **Auto-Bump** | Raises lots on Funpay automatically (configurable per game, every 3h) |
| ✅ | **Auto Price Drop** | Progressively reduces price every N days until floor is reached |
| ✅ | **Sales Stats** | `/stats` command — revenue, profit, by-game breakdown, recent sales |
| ✅ | **Balance Alert** | Warns you when your Lolzteam balance drops below a threshold after a purchase |
| ✅ | **Seller Watchlist** | Watch Lolzteam sellers — new lots are auto-listed on Funpay |
| ✅ | **Web Dashboard** | Local dashboard at `http://localhost:8080` — stats, active lots, recent sales |

---

## Requirements

- Python 3.11+
- Telegram Bot Token (from [@BotFather](https://t.me/BotFather))
- Lolzteam API Token + Secret Code
- Funpay `golden_key` cookie
- Supercell developer API keys (Brawl Stars, Clash Royale, Clash of Clans)

---

## Installation

```bash
git clone <repo>
cd supercell_dropbot
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill in:

```env
BOT_TOKEN=your_telegram_bot_token

# Supercell API keys
BS_API_KEY=your_brawl_stars_api_key
CR_API_KEY=your_clash_royale_api_key
COC_API_KEY=your_clash_of_clans_api_key

# Optional
DATABASE_PATH=bot.db
ORDER_CHECK_INTERVAL=30
BUMP_INTERVAL=10800
```

```bash
python run.py
```

---

## Per-User Configuration (via Bot Settings)

Each user configures their own credentials via the ⚙️ Settings menu:

| Setting | Description |
|---------|-------------|
| 🔑 Lolz Token | Lolzteam API token (lolz.live → Settings → API) |
| 🔒 Lolz Secret | Account secret code (required for purchases) |
| 💳 Funpay Key | `golden_key` cookie from funpay.com |
| 📈 Markup % | Markup over Lolz price (e.g. `35` = price × 1.35) |
| 🌐 Proxy | Optional proxy (`user:pass@ip:port`) |
| 🚀 Auto-Bump | Toggle auto-bump per game (BS / CR / CoC) |
| 📉 Auto Price Drop | Progressive price reduction settings |
| ⚡ Balance Alert | Alert when Lolzteam balance drops below threshold |

---

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Open main menu |
| `/stats` | View your sales statistics |
| `/deliver ORDER_ID login password` | Manually deliver credentials to a buyer |
| `/watch seller_name` | Add a Lolzteam seller to your watchlist |
| `/unwatch seller_name` | Remove a seller from your watchlist |

---

## How It Works

### Listing a lot
1. Send a lolz.live URL (or multiple URLs for bulk import)
2. Bot fetches lot data from Lolzteam API
3. Bot fetches live account stats from Supercell API
4. Bot creates a listing on Funpay with auto-generated title/description
5. Lot is tracked — validity checked every 5 minutes

### Order delivery
1. Bot polls Funpay orders every 30 seconds
2. New paid order detected → bot sends "no errors" confirmation prompt
3. Buyer replies "no errors" → bot buys account on Lolzteam
4. Credentials (login + password) extracted from Lolzteam API
5. Credentials sent to buyer via Funpay chat
6. Sale recorded in DB (persistent across restarts)
7. If buyer asks questions (FAQ detection), bot replies with guidance

### Auto Price Drop
- Every hour, lots eligible for price drop are checked
- Price is reduced by `price_drop_percent`% every `price_drop_days` days
- Price never drops below: `lolz_price × (1 + floor_margin%)`
- You receive a Telegram notification for each price drop

### Seller Watchlist
- Add sellers with `/watch seller_name`
- Every 10 minutes, bot checks for new lots from watched sellers
- New lots are automatically listed on Funpay
- You receive a notification for each auto-listed lot

---

## Project Structure

```
supercell_dropbot/
├── bot/
│   ├── handlers/
│   │   ├── start.py         # /start, /stats, /deliver, main menu
│   │   ├── lots.py          # URL listing, bulk import, lot management
│   │   ├── settings.py      # All settings (tokens, markup, price drop, etc.)
│   │   └── watchlist.py     # /watch, /unwatch, watchlist management
│   ├── keyboards/
│   │   └── menus.py         # All inline keyboards
│   ├── states.py            # FSM states
│   └── main.py              # Bot startup, scheduler, dispatcher
├── database/
│   ├── models.py            # DB schema + migrations
│   └── crud.py              # All DB operations
├── services/
│   ├── funpay.py            # Funpay: create/delete/update lots, orders, messages
│   ├── lolzteam.py          # Lolzteam: parse lots, buy, get credentials, balance
│   ├── listing.py           # Shared lot-listing core logic
│   ├── templates.py         # Funpay title/description generation
│   ├── web_dashboard.py     # Local aiohttp dashboard (localhost:8080)
│   └── supercell/           # Brawl Stars, Clash Royale, CoC API clients
├── tasks/
│   ├── order_monitor.py     # Polls Funpay orders, auto-buys and delivers
│   ├── auto_bump.py         # Auto-raises lots on Funpay
│   ├── price_dropper.py     # Progressive auto price drop
│   └── watchlist_monitor.py # Monitors Lolzteam sellers for new lots
├── config.py                # Configuration from .env
├── run.py                   # Entry point
└── README.md
```

---

## Database Schema

### `users`
Stores per-user API credentials and settings (tokens, markup, price drop config, etc.)

### `lots`
Tracks every listing created by the bot — status (`active`, `sold`, `invalid`, `deleted`), prices, price drop history.

### `sales`
Persistent record of every completed sale — order ID, game, credentials, profit. Survives bot restarts (used for delivery deduplication).

### `watchlist`
Lolzteam sellers to monitor per user — tracks last seen lot ID to detect new listings.

---

## Web Dashboard

The dashboard is available at **http://localhost:8080** while the bot is running.

It shows:
- Global stats (active lots, total sold, revenue, profit, users)
- Table of all active lots
- Last 20 sales with profit

Auto-refreshes every 60 seconds.

---

## Supported Games

| Game | Code | Tag Example |
|------|------|-------------|
| Brawl Stars | `bs` | `#2V2RRRQ09` |
| Clash Royale | `cr` | `#ABC123XY` |
| Clash of Clans | `coc` | `#PP82VULJU` |
