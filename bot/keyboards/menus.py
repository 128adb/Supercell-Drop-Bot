from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⚙️ Settings", callback_data="settings_menu"),
            InlineKeyboardButton(text="📋 My Lots", callback_data="my_lots"),
        ],
        [
            InlineKeyboardButton(text="📊 Stats", callback_data="stats"),
            InlineKeyboardButton(text="👁 Watchlist", callback_data="my_watchlist"),
        ],
        [
            InlineKeyboardButton(text="🗑 Delete Lot", callback_data="delete_lot_menu"),
            InlineKeyboardButton(text="❓ Help", callback_data="help"),
        ],
    ])


def settings_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔑 Lolz Token", callback_data="set_lolz_token")],
        [InlineKeyboardButton(text="🔒 Lolz Secret Code", callback_data="set_lolz_secret")],
        [InlineKeyboardButton(text="💳 Funpay Golden Key", callback_data="set_funpay_key")],
        [InlineKeyboardButton(text="📈 Markup (%)", callback_data="set_markup")],
        [InlineKeyboardButton(text="🌐 Proxy", callback_data="set_proxy")],
        [InlineKeyboardButton(text="🚀 Auto-Bump", callback_data="bump_settings")],
        [InlineKeyboardButton(text="📉 Auto Price Drop", callback_data="price_drop_settings")],
        [InlineKeyboardButton(text="⚡ Balance Alert", callback_data="set_balance_alert")],
        [InlineKeyboardButton(text="◀️ Back", callback_data="main_menu")],
    ])


def bump_settings_menu(auto_bump_bs: bool, auto_bump_cr: bool, auto_bump_coc: bool) -> InlineKeyboardMarkup:
    def toggle(val: bool) -> str:
        return "✅" if val else "❌"

    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"{toggle(auto_bump_bs)} Brawl Stars",
            callback_data="toggle_bump_bs",
        )],
        [InlineKeyboardButton(
            text=f"{toggle(auto_bump_cr)} Clash Royale",
            callback_data="toggle_bump_cr",
        )],
        [InlineKeyboardButton(
            text=f"{toggle(auto_bump_coc)} Clash of Clans",
            callback_data="toggle_bump_coc",
        )],
        [InlineKeyboardButton(text="◀️ Back", callback_data="settings_menu")],
    ])


def price_drop_menu(enabled: bool) -> InlineKeyboardMarkup:
    toggle = "✅ Enabled — Click to disable" if enabled else "❌ Disabled — Click to enable"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=toggle, callback_data="toggle_price_drop")],
        [InlineKeyboardButton(text="📅 Days between drops", callback_data="set_price_drop_days")],
        [InlineKeyboardButton(text="📉 Drop % per cycle", callback_data="set_price_drop_percent")],
        [InlineKeyboardButton(text="🛑 Floor margin %", callback_data="set_price_drop_floor")],
        [InlineKeyboardButton(text="◀️ Back", callback_data="settings_menu")],
    ])


def cancel_button() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Cancel", callback_data="cancel")]
    ])


def back_to_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Main Menu", callback_data="main_menu")]
    ])


def back_to_settings() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Settings", callback_data="settings_menu")]
    ])


def lot_actions(lot_id: int, funpay_lot_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🗑 Delete this lot",
            callback_data=f"delete_lot:{lot_id}",
        )],
        [InlineKeyboardButton(
            text="🔗 Open on Funpay",
            url=f"https://funpay.com/lots/offer?id={funpay_lot_id}",
        )],
        [InlineKeyboardButton(text="◀️ Back", callback_data="my_lots")],
    ])
