"""Handles seller watchlist management (/watch, /unwatch, my_watchlist)."""
from __future__ import annotations
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery

from database import crud
from bot.keyboards.menus import back_to_main

router = Router()


@router.message(Command("watch"))
async def cmd_watch(message: Message) -> None:
    """
    Add a Lolzteam seller to the watchlist.
    Usage: /watch seller_username
    """
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.answer(
            "❌ Usage: `/watch seller_username`\n\n"
            "Example: `/watch john_seller`\n\n"
            "The bot will auto-list new lots from this seller on Funpay.",
            parse_mode="Markdown",
        )
        return

    seller = parts[1].strip().lower()
    user_id = message.from_user.id

    user = await crud.get_user(user_id)
    if not user or not user.get("lolz_token") or not user.get("funpay_golden_key"):
        await message.answer(
            "⚠️ Please configure your Lolz Token and Funpay Golden Key in Settings first.",
        )
        return

    added = await crud.add_to_watchlist(user_id, seller)
    if added:
        await message.answer(
            f"✅ *Seller `{seller}` added to watchlist!*\n\n"
            f"The bot will check every 10 minutes for new lots and auto-list them on Funpay.\n\n"
            f"Use `/unwatch {seller}` to remove.",
            parse_mode="Markdown",
        )
    else:
        await message.answer(
            f"ℹ️ Seller `{seller}` is already in your watchlist.",
            parse_mode="Markdown",
        )


@router.message(Command("unwatch"))
async def cmd_unwatch(message: Message) -> None:
    """
    Remove a Lolzteam seller from the watchlist.
    Usage: /unwatch seller_username
    """
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.answer(
            "❌ Usage: `/unwatch seller_username`\n\n"
            "Example: `/unwatch john_seller`",
            parse_mode="Markdown",
        )
        return

    seller = parts[1].strip().lower()
    user_id = message.from_user.id

    removed = await crud.remove_from_watchlist(user_id, seller)
    if removed:
        await message.answer(f"✅ Seller `{seller}` removed from watchlist.", parse_mode="Markdown")
    else:
        await message.answer(f"❌ Seller `{seller}` was not in your watchlist.", parse_mode="Markdown")


@router.callback_query(F.data == "my_watchlist")
async def cb_my_watchlist(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    entries = await crud.get_watchlist(user_id)

    if not entries:
        await callback.message.edit_text(
            "👁 *Your watchlist is empty.*\n\n"
            "Use `/watch seller_username` to add a Lolzteam seller.\n"
            "New lots from watched sellers are automatically listed on Funpay.",
            parse_mode="Markdown",
            reply_markup=back_to_main(),
        )
        await callback.answer()
        return

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    lines = ["👁 *Your watchlist:*\n"]
    buttons = []

    for entry in entries:
        status = "✅" if entry.get("enabled") else "⏸"
        seller = entry["lolz_seller"]
        last_seen = entry.get("last_seen_lot") or "none"
        lines.append(f"{status} `{seller}` — last seen: `{last_seen}`")
        buttons.append([
            InlineKeyboardButton(
                text=f"{'⏸ Pause' if entry.get('enabled') else '▶️ Resume'} {seller}",
                callback_data=f"watchlist_toggle:{entry['id']}",
            ),
            InlineKeyboardButton(
                text=f"🗑 Remove",
                callback_data=f"watchlist_remove:{entry['id']}",
            ),
        ])

    buttons.append([InlineKeyboardButton(text="◀️ Back", callback_data="main_menu")])

    await callback.message.edit_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("watchlist_toggle:"))
async def cb_watchlist_toggle(callback: CallbackQuery) -> None:
    entry_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id

    from database.crud import _fetchone
    entry = await _fetchone(
        "SELECT * FROM watchlist WHERE id = ? AND user_id = ?", (entry_id, user_id)
    )
    if not entry:
        await callback.answer("❌ Entry not found.", show_alert=True)
        return

    new_state = not bool(entry.get("enabled", 1))
    await crud.toggle_watchlist_entry(entry_id, new_state)
    status = "enabled" if new_state else "paused"
    await callback.answer(f"✅ Watchlist entry {status}!")

    # Refresh the watchlist view
    await cb_my_watchlist(callback)


@router.callback_query(F.data.startswith("watchlist_remove:"))
async def cb_watchlist_remove(callback: CallbackQuery) -> None:
    entry_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id

    from database.crud import _fetchone, _execute
    entry = await _fetchone(
        "SELECT * FROM watchlist WHERE id = ? AND user_id = ?", (entry_id, user_id)
    )
    if not entry:
        await callback.answer("❌ Entry not found.", show_alert=True)
        return

    seller = entry["lolz_seller"]
    await _execute("DELETE FROM watchlist WHERE id = ?", (entry_id,))
    await callback.answer(f"✅ {seller} removed from watchlist!")

    # Refresh the watchlist view
    await cb_my_watchlist(callback)
