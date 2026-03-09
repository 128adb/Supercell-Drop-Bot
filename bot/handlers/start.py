from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from database.crud import upsert_user, get_user, get_user_stats, get_lot_by_funpay_id, get_lot_by_account_tag, update_lot_status
from services import funpay
from tasks import order_monitor
from bot.keyboards.menus import main_menu, back_to_main
import config

router = Router()

HELP_TEXT = (
    "📖 *How to use this bot:*\n\n"
    "1️⃣ Go to ⚙️ *Settings* and fill in:\n"
    "   • Lolz Token (from lolz.live → API)\n"
    "   • Lolz Secret Code (your account secret)\n"
    "   • Funpay Golden Key (cookie `golden_key` from funpay.com)\n"
    "   • Markup in % (e.g. 35)\n"
    "   • Proxy (optional, format: user:pass@ip:port)\n\n"
    "2️⃣ Send the bot a lolz.live lot link (one or multiple URLs)\n\n"
    "3️⃣ The bot will automatically:\n"
    "   • Fetch live account stats from Supercell API\n"
    "   • Create the lot on Funpay\n"
    "   • Monitor validity every 5 minutes\n"
    "   • Buy and deliver the account automatically when sold\n\n"
    "📋 *Commands:*\n"
    "   • `/stats` — your sales statistics\n"
    "   • `/deliver ORDER_ID login password` — manual delivery\n"
    "   • `/watch seller_name` — watch a Lolzteam seller\n"
    "   • `/unwatch seller_name` — stop watching a seller\n\n"
    "❓ Supercell API keys (set by admin in .env):\n"
    "   • BS: developer.brawlstars.com\n"
    "   • CR: developer.clashroyale.com\n"
    "   • CoC: developer.clashofclans.com"
)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await upsert_user(message.from_user.id)
    await message.answer(
        "👋 *Welcome to Supercell Dropship Bot!*\n\n"
        "Send a lolz.live lot link to list it on Funpay.\n"
        "Or choose an action below:",
        parse_mode="Markdown",
        reply_markup=main_menu(),
    )


@router.callback_query(F.data == "main_menu")
async def cb_main_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text(
        "🏠 *Main Menu*\n\nChoose an action:",
        parse_mode="Markdown",
        reply_markup=main_menu(),
    )
    await callback.answer()


@router.callback_query(F.data == "help")
async def cb_help(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        HELP_TEXT,
        parse_mode="Markdown",
        reply_markup=back_to_main(),
    )
    await callback.answer()


# ─── /stats command ───────────────────────────────────────────────────────────

@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    user_id = message.from_user.id
    await upsert_user(user_id)
    await _send_stats(message, user_id)


@router.callback_query(F.data == "stats")
async def cb_stats(callback: CallbackQuery) -> None:
    await _send_stats(callback.message, callback.from_user.id, edit=True)
    await callback.answer()


async def _send_stats(message, user_id: int, edit: bool = False) -> None:
    stats = await get_user_stats(user_id)

    by_game_lines = []
    game_names = {"bs": "Brawl Stars", "cr": "Clash Royale", "coc": "Clash of Clans"}
    for game_key, data in stats["by_game"].items():
        gname = game_names.get(game_key, game_key.upper())
        by_game_lines.append(
            f"   • {gname}: {data['count']} sold — +{data['profit']}₽"
        )

    recent_lines = []
    for sale in stats["recent_sales"]:
        gname = game_names.get(sale.get("game", ""), (sale.get("game") or "?").upper())
        tag = sale.get("account_tag", "?")
        profit = sale.get("profit", 0)
        date = (sale.get("sold_at") or "")[:10]
        recent_lines.append(f"   • {gname} `{tag}` — +{profit}₽ ({date})")

    text = (
        f"📊 *Your Stats*\n\n"
        f"📋 Lots listed: {stats['total_listed']}\n"
        f"💰 Sold: {stats['total_sold']}\n\n"
        f"💵 Total revenue: {stats['total_revenue']}₽\n"
        f"💸 Total cost: {stats['total_cost']}₽\n"
        f"📈 Total profit: ~{stats['total_profit']}₽\n"
    )

    if by_game_lines:
        text += "\n🎮 *By game:*\n" + "\n".join(by_game_lines) + "\n"

    if recent_lines:
        text += "\n📅 *Recent sales:*\n" + "\n".join(recent_lines)
    else:
        text += "\n_No sales yet — start listing lots!_"

    kwargs = dict(parse_mode="Markdown", reply_markup=back_to_main())
    if edit:
        await message.edit_text(text, **kwargs)
    else:
        await message.answer(text, **kwargs)


# ─── /deliver command ─────────────────────────────────────────────────────────

@router.message(Command("deliver"))
async def cmd_deliver(message: Message) -> None:
    """
    Manually deliver credentials to a FunPay buyer.
    Usage: /deliver ORDER_ID login password
    """
    parts = (message.text or "").split(maxsplit=3)
    if len(parts) < 4:
        await message.answer(
            "❌ Usage: `/deliver ORDER_ID login password`\n"
            "Example: `/deliver J3TXP73H akgwiikx@dfirstmail.com CCscPsgbv6`",
            parse_mode="Markdown",
        )
        return

    _, order_id, login, password = parts
    order_id = order_id.upper().lstrip("#")

    user = await get_user(message.from_user.id)
    if not user or not user.get("funpay_golden_key"):
        await message.answer("❌ Configure your FunPay Golden Key first via /start → Settings.")
        return

    golden_key = user["funpay_golden_key"]
    proxy = user.get("proxy")

    await message.answer(f"📤 Sending credentials to buyer for order `#{order_id}`...", parse_mode="Markdown")

    delivery_text = (
        f"✅ Thank you for your purchase!\n\n"
        f"📧 Login: {login}\n"
        f"🔑 Password: {password}\n\n"
        f"Please leave a review — it means a lot to the seller! 🙏"
    )

    try:
        await funpay.send_message(golden_key, order_id, delivery_text, proxy)
        order_monitor.mark_delivered(order_id)

        # Persist delivered state to DB
        try:
            page = await funpay.get_order_page(golden_key, order_id, proxy)
            lot = None
            if page.funpay_lot_id:
                lot = await get_lot_by_funpay_id(page.funpay_lot_id)
            if not lot and page.account_tag:
                lot = await get_lot_by_account_tag(page.account_tag)
            if lot:
                await update_lot_status(lot["id"], "sold")
                # Save to sales table for post-delivery resend
                from database.crud import create_sale
                await create_sale(
                    user_id=message.from_user.id,
                    lot_id=lot["id"],
                    order_id=order_id,
                    game=lot.get("game", ""),
                    account_tag=lot.get("account_tag", ""),
                    lolz_price=lot.get("lolz_price", 0),
                    funpay_price=lot.get("funpay_price", 0),
                    profit=round(lot.get("funpay_price", 0) - lot.get("lolz_price", 0), 2),
                    login=login,
                    password=password,
                )
        except Exception:
            pass  # Best-effort — don't block delivery confirmation

        await message.answer(
            f"✅ Credentials sent to buyer for order `#{order_id}`!\n\n"
            f"📧 `{login}`\n🔑 `{password}`",
            parse_mode="Markdown",
        )
    except Exception as e:
        await message.answer(
            f"❌ Failed to send message to buyer: `{e}`\n\n"
            f"Please send manually in FunPay order #{order_id}:\n"
            f"📧 Login: `{login}`\n🔑 Password: `{password}`",
            parse_mode="Markdown",
        )


@router.callback_query(F.data == "cancel")
async def cb_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text(
        "❌ Cancelled. Main menu:",
        reply_markup=main_menu(),
    )
    await callback.answer()
