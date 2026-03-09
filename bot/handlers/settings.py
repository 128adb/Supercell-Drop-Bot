from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from database.crud import get_user, update_user
from bot.states import SettingsState
from bot.keyboards.menus import (
    settings_menu, bump_settings_menu, price_drop_menu,
    cancel_button, main_menu, back_to_settings,
)

router = Router()


async def _show_settings(callback: CallbackQuery, user: dict) -> None:
    lolz_token = "✅ Set" if user.get("lolz_token") else "❌ Not set"
    lolz_secret = "✅ Set" if user.get("lolz_secret") else "❌ Not set"
    funpay_key = "✅ Set" if user.get("funpay_golden_key") else "❌ Not set"
    markup = user.get("markup_percent", 35.0)
    proxy = "✅ Connected" if user.get("proxy") else "❌ Not set"
    drop_enabled = "✅ On" if user.get("price_drop_enabled") else "❌ Off"
    balance_alert = user.get("lolz_balance_alert", 0) or 0
    balance_str = f"{balance_alert}₽" if balance_alert > 0 else "❌ Off"

    text = (
        "⚙️ *Settings*\n\n"
        f"🔑 Lolz Token: {lolz_token}\n"
        f"🔒 Lolz Secret: {lolz_secret}\n"
        f"💳 Funpay Key: {funpay_key}\n"
        f"📈 Markup: {markup}%\n"
        f"🌐 Proxy: {proxy}\n"
        f"📉 Auto Price Drop: {drop_enabled}\n"
        f"⚡ Balance Alert: {balance_str}\n\n"
        "Tap a button to change a setting:"
    )
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=settings_menu())


@router.callback_query(F.data == "settings_menu")
async def cb_settings(callback: CallbackQuery) -> None:
    user = await get_user(callback.from_user.id)
    await _show_settings(callback, user or {})
    await callback.answer()


# ─── Lolz Token ───────────────────────────────────────────────────────────────

@router.callback_query(F.data == "set_lolz_token")
async def cb_set_lolz_token(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingsState.waiting_lolz_token)
    await callback.message.edit_text(
        "🔑 Enter your *Lolz Token*\n\n"
        "Get it at: lolz.live → Settings → API → Create token",
        parse_mode="Markdown",
        reply_markup=cancel_button(),
    )
    await callback.answer()


@router.message(SettingsState.waiting_lolz_token)
async def msg_lolz_token(message: Message, state: FSMContext) -> None:
    await update_user(message.from_user.id, lolz_token=message.text.strip())
    await state.clear()
    await message.answer("✅ Lolz Token saved!", reply_markup=settings_menu())


# ─── Lolz Secret ──────────────────────────────────────────────────────────────

@router.callback_query(F.data == "set_lolz_secret")
async def cb_set_lolz_secret(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingsState.waiting_lolz_secret)
    await callback.message.edit_text(
        "🔒 Enter your *Lolz Secret Code*\n\n"
        "This is the secret code from your lolz.live account settings (required for purchases).",
        parse_mode="Markdown",
        reply_markup=cancel_button(),
    )
    await callback.answer()


@router.message(SettingsState.waiting_lolz_secret)
async def msg_lolz_secret(message: Message, state: FSMContext) -> None:
    await update_user(message.from_user.id, lolz_secret=message.text.strip())
    await state.clear()
    await message.answer("✅ Lolz Secret Code saved!", reply_markup=settings_menu())


# ─── Funpay Key ───────────────────────────────────────────────────────────────

@router.callback_query(F.data == "set_funpay_key")
async def cb_set_funpay_key(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingsState.waiting_funpay_key)
    await callback.message.edit_text(
        "💳 Enter your *Funpay Golden Key*\n\n"
        "Get it: open DevTools on funpay.com → Application → Cookies → `golden_key`",
        parse_mode="Markdown",
        reply_markup=cancel_button(),
    )
    await callback.answer()


@router.message(SettingsState.waiting_funpay_key)
async def msg_funpay_key(message: Message, state: FSMContext) -> None:
    await update_user(message.from_user.id, funpay_golden_key=message.text.strip())
    await state.clear()
    await message.answer("✅ Funpay Golden Key saved!", reply_markup=settings_menu())


# ─── Markup ───────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "set_markup")
async def cb_set_markup(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingsState.waiting_markup)
    await callback.message.edit_text(
        "📈 Enter your *markup in %*\n\nExample: `35` means price × 1.35",
        parse_mode="Markdown",
        reply_markup=cancel_button(),
    )
    await callback.answer()


@router.message(SettingsState.waiting_markup)
async def msg_markup(message: Message, state: FSMContext) -> None:
    try:
        markup = float(message.text.strip().replace(",", ".").replace("%", ""))
        if markup < 0 or markup > 1000:
            raise ValueError
    except ValueError:
        await message.answer("❌ Enter a valid number, e.g. `35`", parse_mode="Markdown")
        return
    await update_user(message.from_user.id, markup_percent=markup)
    await state.clear()
    await message.answer(f"✅ Markup set to {markup}%", reply_markup=settings_menu())


# ─── Proxy ────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "set_proxy")
async def cb_set_proxy(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingsState.waiting_proxy)
    await callback.message.edit_text(
        "🌐 Enter your proxy in format:\n`user:pass@ip:port`\n\n"
        "Or send `-` to disable proxy.",
        parse_mode="Markdown",
        reply_markup=cancel_button(),
    )
    await callback.answer()


@router.message(SettingsState.waiting_proxy)
async def msg_proxy(message: Message, state: FSMContext) -> None:
    proxy = message.text.strip()
    if proxy == "-":
        proxy = ""
    await update_user(message.from_user.id, proxy=proxy)
    await state.clear()
    status = "removed" if not proxy else f"set to `{proxy}`"
    await message.answer(f"✅ Proxy {status}", parse_mode="Markdown", reply_markup=settings_menu())


# ─── Auto-bump settings ───────────────────────────────────────────────────────

@router.callback_query(F.data == "bump_settings")
async def cb_bump_settings(callback: CallbackQuery) -> None:
    user = await get_user(callback.from_user.id) or {}
    await callback.message.edit_text(
        "🚀 *Auto-Bump Lots*\n\nEnable for the games you want (every 3 hours):",
        parse_mode="Markdown",
        reply_markup=bump_settings_menu(
            bool(user.get("auto_bump_bs")),
            bool(user.get("auto_bump_cr")),
            bool(user.get("auto_bump_coc")),
        ),
    )
    await callback.answer()


async def _toggle_bump(callback: CallbackQuery, field: str) -> None:
    user = await get_user(callback.from_user.id) or {}
    current = bool(user.get(field, False))
    await update_user(callback.from_user.id, **{field: int(not current)})
    user[field] = int(not current)
    await callback.message.edit_reply_markup(
        reply_markup=bump_settings_menu(
            bool(user.get("auto_bump_bs")),
            bool(user.get("auto_bump_cr")),
            bool(user.get("auto_bump_coc")),
        )
    )
    await callback.answer("✅ Updated!")


@router.callback_query(F.data == "toggle_bump_bs")
async def cb_toggle_bs(callback: CallbackQuery) -> None:
    await _toggle_bump(callback, "auto_bump_bs")


@router.callback_query(F.data == "toggle_bump_cr")
async def cb_toggle_cr(callback: CallbackQuery) -> None:
    await _toggle_bump(callback, "auto_bump_cr")


@router.callback_query(F.data == "toggle_bump_coc")
async def cb_toggle_coc(callback: CallbackQuery) -> None:
    await _toggle_bump(callback, "auto_bump_coc")


# ─── Auto Price Drop settings ─────────────────────────────────────────────────

@router.callback_query(F.data == "price_drop_settings")
async def cb_price_drop_settings(callback: CallbackQuery) -> None:
    user = await get_user(callback.from_user.id) or {}
    enabled = bool(user.get("price_drop_enabled"))
    days = user.get("price_drop_days", 3)
    percent = user.get("price_drop_percent", 10.0)
    floor = user.get("price_drop_floor", 50.0)
    await callback.message.edit_text(
        f"📉 *Auto Price Drop*\n\n"
        f"Status: {'✅ Enabled' if enabled else '❌ Disabled'}\n"
        f"Every: *{days} days*\n"
        f"Drop: *{percent}%* per cycle\n"
        f"Floor: *{floor}%* above Lolz cost (minimum margin)\n\n"
        f"_Example: if you paid 100₽ and floor is 50%, price won't drop below 150₽_",
        parse_mode="Markdown",
        reply_markup=price_drop_menu(enabled),
    )
    await callback.answer()


@router.callback_query(F.data == "toggle_price_drop")
async def cb_toggle_price_drop(callback: CallbackQuery) -> None:
    user = await get_user(callback.from_user.id) or {}
    current = bool(user.get("price_drop_enabled"))
    await update_user(callback.from_user.id, price_drop_enabled=int(not current))
    await cb_price_drop_settings(callback)


@router.callback_query(F.data == "set_price_drop_days")
async def cb_set_price_drop_days(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingsState.waiting_price_drop_days)
    await callback.message.edit_text(
        "📅 Enter how many *days between each price drop*:\n\n"
        "Example: `3` means price drops every 3 days.",
        parse_mode="Markdown",
        reply_markup=cancel_button(),
    )
    await callback.answer()


@router.message(SettingsState.waiting_price_drop_days)
async def msg_price_drop_days(message: Message, state: FSMContext) -> None:
    try:
        days = int(message.text.strip())
        if days < 1 or days > 365:
            raise ValueError
    except ValueError:
        await message.answer("❌ Enter a whole number between 1 and 365.", parse_mode="Markdown")
        return
    await update_user(message.from_user.id, price_drop_days=days)
    await state.clear()
    await message.answer(f"✅ Price drop interval set to {days} days.", reply_markup=settings_menu())


@router.callback_query(F.data == "set_price_drop_percent")
async def cb_set_price_drop_percent(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingsState.waiting_price_drop_percent)
    await callback.message.edit_text(
        "📉 Enter the *price drop percentage* per cycle:\n\n"
        "Example: `10` means the price drops by 10% every interval.",
        parse_mode="Markdown",
        reply_markup=cancel_button(),
    )
    await callback.answer()


@router.message(SettingsState.waiting_price_drop_percent)
async def msg_price_drop_percent(message: Message, state: FSMContext) -> None:
    try:
        pct = float(message.text.strip().replace(",", ".").replace("%", ""))
        if pct <= 0 or pct > 90:
            raise ValueError
    except ValueError:
        await message.answer("❌ Enter a number between 1 and 90.", parse_mode="Markdown")
        return
    await update_user(message.from_user.id, price_drop_percent=pct)
    await state.clear()
    await message.answer(f"✅ Price drop set to {pct}% per cycle.", reply_markup=settings_menu())


@router.callback_query(F.data == "set_price_drop_floor")
async def cb_set_price_drop_floor(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingsState.waiting_price_drop_floor)
    await callback.message.edit_text(
        "🛑 Enter the *minimum margin % above Lolz cost*:\n\n"
        "Example: `50` means the price won't drop below Lolz cost + 50%.\n"
        "If you paid 100₽, the floor is 150₽.",
        parse_mode="Markdown",
        reply_markup=cancel_button(),
    )
    await callback.answer()


@router.message(SettingsState.waiting_price_drop_floor)
async def msg_price_drop_floor(message: Message, state: FSMContext) -> None:
    try:
        floor = float(message.text.strip().replace(",", ".").replace("%", ""))
        if floor < 0 or floor > 500:
            raise ValueError
    except ValueError:
        await message.answer("❌ Enter a number between 0 and 500.", parse_mode="Markdown")
        return
    await update_user(message.from_user.id, price_drop_floor=floor)
    await state.clear()
    await message.answer(f"✅ Floor margin set to {floor}%.", reply_markup=settings_menu())


# ─── Balance alert ────────────────────────────────────────────────────────────

@router.callback_query(F.data == "set_balance_alert")
async def cb_set_balance_alert(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingsState.waiting_balance_alert)
    await callback.message.edit_text(
        "⚡ Enter your *low-balance alert threshold* in ₽:\n\n"
        "The bot will warn you after each purchase when your Lolzteam "
        "balance drops below this amount.\n\n"
        "Send `0` to disable.",
        parse_mode="Markdown",
        reply_markup=cancel_button(),
    )
    await callback.answer()


@router.message(SettingsState.waiting_balance_alert)
async def msg_balance_alert(message: Message, state: FSMContext) -> None:
    try:
        threshold = float(message.text.strip().replace(",", ".").replace("₽", ""))
        if threshold < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Enter a positive number (or 0 to disable).", parse_mode="Markdown")
        return
    await update_user(message.from_user.id, lolz_balance_alert=threshold)
    await state.clear()
    if threshold > 0:
        await message.answer(
            f"✅ Balance alert set to {threshold}₽.",
            reply_markup=settings_menu(),
        )
    else:
        await message.answer("✅ Balance alert disabled.", reply_markup=settings_menu())
