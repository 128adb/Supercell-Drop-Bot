"""Handles lot listing (URL parsing) and lot management."""
from __future__ import annotations
import re
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from database import crud
from services import lolzteam, funpay
from services.listing import list_lot
from bot.keyboards.menus import main_menu, back_to_main, lot_actions, cancel_button
from bot.states import LotState

router = Router()

LOLZ_URL_RE = re.compile(
    r"https?://(?:lolz\.live|zelenka\.guru|ttz\.market|lzt\.market)/(?:market/|threads/)?[\w/-]+"
)

GAME_NAMES = {"bs": "Brawl Stars", "cr": "Clash Royale", "coc": "Clash of Clans"}


@router.message(F.text.regexp(LOLZ_URL_RE))
async def handle_lolz_url(message: Message, state: FSMContext) -> None:
    user_id = message.from_user.id
    user = await crud.get_user(user_id)

    if not user:
        await crud.upsert_user(user_id)
        user = await crud.get_user(user_id)

    # Validate required settings
    missing = []
    if not user.get("lolz_token"):
        missing.append("Lolz Token")
    if not user.get("funpay_golden_key"):
        missing.append("Funpay Golden Key")
    if missing:
        await message.answer(
            f"⚠️ Please set the following in Settings first: {', '.join(missing)}",
            reply_markup=main_menu(),
        )
        return

    urls = LOLZ_URL_RE.findall(message.text)

    # ── Single URL → step-by-step flow with live status message ───────────────
    if len(urls) == 1:
        await _handle_single_url(message, state, user, urls[0])
        return

    # ── Multiple URLs → bulk import ────────────────────────────────────────────
    await _handle_bulk_urls(message, user, urls)


async def _handle_single_url(
    message: Message, state: FSMContext, user: dict, url: str
) -> None:
    """Process a single Lolzteam URL with step-by-step status updates."""
    status_msg = await message.answer("⏳ Fetching lot from Lolzteam...")

    try:
        lot_data = await lolzteam.parse_lot(url, user["lolz_token"], user.get("proxy"))
    except lolzteam.LolzError as e:
        await status_msg.edit_text(f"❌ Lolzteam error: {e}")
        return
    except Exception as e:
        await status_msg.edit_text(f"❌ Could not fetch lot data: {e}")
        return

    # If tag not found automatically, ask the user
    if not lot_data.account_tag:
        await status_msg.edit_text(
            f"✅ Lot found!\n"
            f"🎮 Game: *{lot_data.game.upper()}*\n"
            f"💰 Lolz price: {lot_data.price}₽\n\n"
            f"⚠️ Could not detect account tag automatically.\n"
            f"Please enter the tag manually (e.g. `#ABC123XY`):",
            parse_mode="Markdown",
            reply_markup=cancel_button(),
        )
        await state.set_state(LotState.waiting_account_tag)
        await state.update_data(lot_data=lot_data, url=url)
        return

    await _process_lot(message, state, user, lot_data, url, status_msg)


async def _handle_bulk_urls(message: Message, user: dict, urls: list[str]) -> None:
    """Process multiple Lolzteam URLs sequentially with a shared progress message."""
    user_id = message.from_user.id
    total = len(urls)
    results: list[str] = []
    success_count = 0
    fail_count = 0

    progress_msg = await message.answer(
        f"⏳ Bulk import: processing {total} lots (1/{total})..."
    )

    for i, url in enumerate(urls, 1):
        # Update progress (skip update for first item — message already shows 1/N)
        if i > 1:
            preview = "\n".join(results[-8:])  # show last 8 to stay within Telegram limits
            await progress_msg.edit_text(
                f"⏳ Bulk import: processing {total} lots ({i}/{total})...\n\n{preview}"
            )

        # Fetch lot metadata from Lolzteam
        try:
            lot_data = await lolzteam.parse_lot(url, user["lolz_token"], user.get("proxy"))
        except Exception as e:
            fail_count += 1
            results.append(f"❌ Lot {i}: {str(e)[:60]}")
            continue

        if not lot_data.account_tag:
            fail_count += 1
            results.append(f"❌ Lot {i}: could not detect account tag")
            continue

        # List on Funpay
        try:
            _lot_id, funpay_lot_id, funpay_price = await list_lot(
                user_id, user, lot_data, url
            )
            game_label = GAME_NAMES.get(lot_data.game, lot_data.game.upper())
            success_count += 1
            results.append(f"✅ {game_label} `{lot_data.account_tag}` — {funpay_price}₽")
        except Exception as e:
            fail_count += 1
            results.append(f"❌ Lot {i} (`{lot_data.account_tag}`): {str(e)[:60]}")

    summary = f"📊 *Done:* {success_count} listed, {fail_count} failed"
    await progress_msg.edit_text(
        f"{summary}\n\n" + "\n".join(results),
        parse_mode="Markdown",
        reply_markup=back_to_main(),
    )


@router.message(LotState.waiting_account_tag)
async def handle_manual_tag(message: Message, state: FSMContext) -> None:
    tag = message.text.strip().upper()
    if not re.match(r"^#?[0-9A-Z]{6,12}$", tag):
        await message.answer(
            "❌ Invalid tag format. It should look like `#ABC123XY`\nTry again:",
            parse_mode="Markdown",
            reply_markup=cancel_button(),
        )
        return

    if not tag.startswith("#"):
        tag = f"#{tag}"

    data = await state.get_data()
    lot_data = data["lot_data"]
    url = data["url"]
    lot_data.account_tag = tag
    await state.clear()

    user = await crud.get_user(message.from_user.id)
    status_msg = await message.answer(
        f"✅ Tag set to `{tag}`, processing...", parse_mode="Markdown"
    )
    await _process_lot(message, state, user, lot_data, url, status_msg)


async def _process_lot(message, state, user, lot_data, url, status_msg):
    """Single-lot flow with step-by-step status message updates."""
    user_id = message.from_user.id
    markup = user.get("markup_percent", 35.0)

    await status_msg.edit_text(
        f"✅ Lot found!\n"
        f"🎮 Game: *{lot_data.game.upper()}*\n"
        f"🏷 Tag: `{lot_data.account_tag}`\n"
        f"💰 Lolz price: {lot_data.price}₽\n\n"
        f"⏳ Fetching stats and listing on Funpay...",
        parse_mode="Markdown",
    )

    try:
        lot_id, funpay_lot_id, funpay_price = await list_lot(
            user_id, user, lot_data, url
        )
    except ValueError as e:
        await status_msg.edit_text(f"❌ {e}")
        return
    except Exception as e:
        await status_msg.edit_text(f"❌ Unexpected error: {e}")
        return

    game_name = GAME_NAMES.get(lot_data.game, lot_data.game.upper())
    await status_msg.edit_text(
        f"🎉 *Lot successfully listed!*\n\n"
        f"🎮 {game_name}\n"
        f"🏷 Tag: `{lot_data.account_tag}`\n"
        f"💰 Price: {funpay_price}₽ (+{markup}%)\n"
        f"🔗 [Open on Funpay](https://funpay.com/lots/offer?id={funpay_lot_id})\n\n"
        f"🔍 The bot will check validity every 5 minutes.",
        parse_mode="Markdown",
        disable_web_page_preview=True,
        reply_markup=lot_actions(lot_id, funpay_lot_id),
    )


# ─── My lots ──────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "my_lots")
async def cb_my_lots(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    lots = await crud.get_active_lots_for_user(user_id)

    if not lots:
        await callback.message.edit_text(
            "📋 You have no active lots.\n\nSend a lolz.live link to add one.",
            reply_markup=back_to_main(),
        )
        await callback.answer()
        return

    lines = ["📋 *Your active lots:*\n"]
    for lot in lots:
        game = GAME_NAMES.get(lot["game"], lot["game"].upper())
        fp_id = lot.get("funpay_lot_id", "—")
        lines.append(
            f"• {game} | {lot.get('account_tag', '?')} | "
            f"{lot.get('funpay_price', 0)}₽ | "
            f"[Funpay](https://funpay.com/lots/offer?id={fp_id})"
        )

    await callback.message.edit_text(
        "\n".join(lines),
        parse_mode="Markdown",
        disable_web_page_preview=True,
        reply_markup=back_to_main(),
    )
    await callback.answer()


# ─── Delete lot ───────────────────────────────────────────────────────────────

@router.callback_query(F.data == "delete_lot_menu")
async def cb_delete_lot_menu(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    lots = await crud.get_active_lots_for_user(user_id)

    if not lots:
        await callback.message.edit_text(
            "📋 No active lots to delete.",
            reply_markup=back_to_main(),
        )
        await callback.answer()
        return

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    buttons = []
    for lot in lots:
        game = GAME_NAMES.get(lot["game"], lot["game"].upper())
        label = f"🗑 {game} | {lot.get('account_tag', '?')} | {lot.get('funpay_price', 0)}₽"
        buttons.append([InlineKeyboardButton(
            text=label,
            callback_data=f"delete_lot:{lot['id']}",
        )])
    buttons.append([InlineKeyboardButton(text="◀️ Back", callback_data="main_menu")])

    await callback.message.edit_text(
        "🗑 *Select a lot to delete:*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("delete_lot:"))
async def cb_delete_lot(callback: CallbackQuery) -> None:
    lot_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id

    # Get lot and verify ownership
    from database.crud import _fetchone
    lot = await _fetchone("SELECT * FROM lots WHERE id = ? AND user_id = ?", (lot_id, user_id))
    if not lot:
        await callback.answer("❌ Lot not found.", show_alert=True)
        return

    user = await crud.get_user(user_id)
    if not user or not user.get("funpay_golden_key"):
        await callback.answer("❌ Funpay Golden Key not set.", show_alert=True)
        return

    try:
        if lot.get("funpay_lot_id"):
            await funpay.delete_lot(user["funpay_golden_key"], lot["funpay_lot_id"], user.get("proxy"))
    except Exception as e:
        await callback.answer(f"⚠️ Funpay error: {e}", show_alert=True)

    await crud.delete_lot(lot_id)
    await callback.message.edit_text(
        "✅ Lot deleted from Funpay and database.",
        reply_markup=back_to_main(),
    )
    await callback.answer()
