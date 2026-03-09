"""Bot setup, scheduler configuration, and entry point."""
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import config
from database.models import init_db
from bot.handlers import start, settings, lots, watchlist
from services import web_dashboard
from tasks import order_monitor, auto_bump, price_dropper, watchlist_monitor

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
# Silence noisy third-party loggers
logging.getLogger("aiohttp").setLevel(logging.WARNING)
logging.getLogger("asyncio").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
log = logging.getLogger(__name__)


async def main() -> None:
    await init_db()
    log.info("Database initialized")

    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    # Register routers
    dp.include_router(start.router)
    dp.include_router(settings.router)
    dp.include_router(lots.router)
    dp.include_router(watchlist.router)

    # Setup APScheduler
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        order_monitor.run,
        trigger="interval",
        seconds=config.ORDER_CHECK_INTERVAL,
        args=[bot],
        id="order_monitor",
        max_instances=1,
    )
    scheduler.add_job(
        auto_bump.run,
        trigger="interval",
        seconds=config.BUMP_INTERVAL,
        args=[bot],
        id="auto_bump",
        max_instances=1,
    )
    scheduler.add_job(
        price_dropper.run,
        trigger="interval",
        hours=1,
        args=[bot],
        id="price_dropper",
        max_instances=1,
    )
    scheduler.add_job(
        watchlist_monitor.run,
        trigger="interval",
        minutes=10,
        args=[bot],
        id="watchlist_monitor",
        max_instances=1,
    )
    scheduler.start()
    log.info("Scheduler started (order_monitor, auto_bump, price_dropper, watchlist_monitor)")

    # Start local web dashboard
    try:
        dashboard_runner = await web_dashboard.start_dashboard()
        log.info("Web dashboard available at http://127.0.0.1:8080")
    except Exception as e:
        dashboard_runner = None
        log.warning("Could not start web dashboard: %s", e)

    log.info("Bot starting...")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.shutdown()
        if dashboard_runner:
            await dashboard_runner.cleanup()
        await bot.session.close()
