"""Local web dashboard on http://localhost:8080 — overview of the bot's activity."""
from __future__ import annotations
import json
import logging
from datetime import datetime
from aiohttp import web

from database import crud

log = logging.getLogger(__name__)


def _html_page(stats: dict, lots: list, sales: list) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lots_rows = "".join(
        f"<tr>"
        f"<td>{l.get('game', '').upper()}</td>"
        f"<td><code>{l.get('account_tag', '?')}</code></td>"
        f"<td>{l.get('funpay_price', 0)}₽</td>"
        f"<td>{l.get('created_at', '')[:10]}</td>"
        f"<td><a href='https://funpay.com/lots/offer?id={l.get('funpay_lot_id', '')}' target='_blank'>🔗</a></td>"
        f"</tr>"
        for l in lots
    )

    sales_rows = "".join(
        f"<tr>"
        f"<td><code>{s.get('order_id', '')}</code></td>"
        f"<td>{s.get('game', '').upper()}</td>"
        f"<td><code>{s.get('account_tag', '?')}</code></td>"
        f"<td>{s.get('funpay_price', 0)}₽</td>"
        f"<td style='color:{'green' if (s.get('profit') or 0) >= 0 else 'red'}'>"
        f"+{s.get('profit', 0)}₽</td>"
        f"<td>{(s.get('sold_at') or '')[:10]}</td>"
        f"</tr>"
        for s in sales
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Supercell Dropbot Dashboard</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: #0f0f0f; color: #e0e0e0; padding: 24px; }}
    h1 {{ font-size: 1.6rem; margin-bottom: 4px; }}
    .subtitle {{ color: #888; font-size: 0.85rem; margin-bottom: 24px; }}
    .status {{ display: inline-block; background: #1a3a1a; color: #4caf50;
               padding: 3px 10px; border-radius: 20px; font-size: 0.8rem; margin-left: 8px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
             gap: 16px; margin-bottom: 32px; }}
    .card {{ background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 10px;
             padding: 18px; }}
    .card-value {{ font-size: 2rem; font-weight: 700; color: #4caf50; }}
    .card-label {{ font-size: 0.8rem; color: #888; margin-top: 4px; text-transform: uppercase;
                   letter-spacing: 0.5px; }}
    section {{ margin-bottom: 32px; }}
    h2 {{ font-size: 1.1rem; margin-bottom: 12px; color: #ccc; }}
    table {{ width: 100%; border-collapse: collapse; background: #1a1a1a;
             border: 1px solid #2a2a2a; border-radius: 10px; overflow: hidden; }}
    th {{ background: #252525; padding: 10px 14px; text-align: left; font-size: 0.8rem;
          color: #888; text-transform: uppercase; letter-spacing: 0.5px; }}
    td {{ padding: 10px 14px; border-bottom: 1px solid #1e1e1e; font-size: 0.9rem; }}
    tr:last-child td {{ border-bottom: none; }}
    code {{ background: #252525; padding: 2px 6px; border-radius: 4px; font-size: 0.85em; }}
    a {{ color: #4caf50; text-decoration: none; }}
    .empty {{ color: #555; font-size: 0.9rem; padding: 20px; text-align: center; }}
  </style>
</head>
<body>
  <h1>🎮 Supercell Dropbot <span class="status">🟢 Online</span></h1>
  <p class="subtitle">Last updated: {now}</p>

  <div class="grid">
    <div class="card">
      <div class="card-value">{stats.get('active_lots', 0)}</div>
      <div class="card-label">Active Lots</div>
    </div>
    <div class="card">
      <div class="card-value">{stats.get('total_sold', 0)}</div>
      <div class="card-label">Total Sold</div>
    </div>
    <div class="card">
      <div class="card-value">{stats.get('total_revenue', 0):.0f}₽</div>
      <div class="card-label">Revenue</div>
    </div>
    <div class="card">
      <div class="card-value" style="color:#66bb6a">{stats.get('total_profit', 0):.0f}₽</div>
      <div class="card-label">Profit</div>
    </div>
    <div class="card">
      <div class="card-value">{stats.get('total_users', 0)}</div>
      <div class="card-label">Users</div>
    </div>
  </div>

  <section>
    <h2>📋 Active Lots</h2>
    {'<table><thead><tr><th>Game</th><th>Tag</th><th>Price</th><th>Listed</th><th>Link</th></tr></thead><tbody>' + lots_rows + '</tbody></table>' if lots else '<p class="empty">No active lots.</p>'}
  </section>

  <section>
    <h2>📅 Recent Sales (last 20)</h2>
    {'<table><thead><tr><th>Order</th><th>Game</th><th>Tag</th><th>Sale Price</th><th>Profit</th><th>Date</th></tr></thead><tbody>' + sales_rows + '</tbody></table>' if sales else '<p class="empty">No sales yet.</p>'}
  </section>

  <script>setTimeout(() => location.reload(), 60000);</script>
</body>
</html>"""


async def _handle_index(request: web.Request) -> web.Response:
    try:
        stats = await crud.get_all_stats()
        lots = await crud.get_all_active_lots()
        sales = await crud.get_recent_sales(20)
        return web.Response(
            text=_html_page(stats, lots, sales),
            content_type="text/html",
        )
    except Exception as e:
        log.error("Dashboard error: %s", e)
        return web.Response(text=f"<pre>Error: {e}</pre>", content_type="text/html", status=500)


async def _handle_api_stats(request: web.Request) -> web.Response:
    stats = await crud.get_all_stats()
    return web.json_response(stats)


async def _handle_api_lots(request: web.Request) -> web.Response:
    lots = await crud.get_all_active_lots()
    return web.json_response(lots)


async def _handle_api_sales(request: web.Request) -> web.Response:
    limit = int(request.rel_url.query.get("limit", 20))
    sales = await crud.get_recent_sales(limit)
    return web.json_response(sales)


async def start_dashboard(host: str = "127.0.0.1", port: int = 8080) -> web.AppRunner:
    """Start the aiohttp web dashboard and return the runner (for clean shutdown)."""
    app = web.Application()
    app.router.add_get("/", _handle_index)
    app.router.add_get("/api/stats", _handle_api_stats)
    app.router.add_get("/api/lots", _handle_api_lots)
    app.router.add_get("/api/sales", _handle_api_sales)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    log.info("Web dashboard started at http://%s:%d", host, port)
    return runner
