"""Handle replies from the seller to FunPay pre-sale chat messages.

Flow:
  1. chat_forwarder sends a notification with a [✏️ Reply] inline button.
     The callback_data is "reply_chat:{node_id}".
  2. Seller taps the button → bot asks them to type their reply.
  3. Seller sends the text → bot forwards it to FunPay via send_chat_message()
     and confirms delivery.
  4. /cancel at any point cancels the FSM.
"""
from __future__ import annotations

import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext

from bot.states import ChatReplyState
from database import crud
from services import funpay

router = Router()
log = logging.getLogger(__name__)


# ─── Step 1: seller taps [✏️ Reply] ───────────────────────────────────────────

@router.callback_query(F.data.startswith("reply_chat:"))
async def cb_start_reply(call: CallbackQuery, state: FSMContext) -> None:
    node_id = call.data.split(":", 1)[1]

    # Persist the target node_id in FSM so the next message handler can use it
    await state.set_state(ChatReplyState.waiting_reply)
    await state.update_data(funpay_node_id=node_id)

    await call.message.reply(
        "✏️ *Type your reply* and send it.\n\n"
        "Send /cancel to abort.",
        parse_mode="Markdown",
    )
    await call.answer()


# ─── Cancel ───────────────────────────────────────────────────────────────────

@router.message(ChatReplyState.waiting_reply, F.text == "/cancel")
async def cmd_cancel_reply(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("❌ Reply cancelled.")


# ─── Step 2: seller sends the reply text ──────────────────────────────────────

@router.message(ChatReplyState.waiting_reply, F.text)
async def handle_reply_text(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    node_id: str = data.get("funpay_node_id", "")

    if not node_id:
        await state.clear()
        await message.answer("⚠️ Something went wrong — node ID not found. Please try again.")
        return

    user = await crud.get_user(message.from_user.id)
    if not user:
        await state.clear()
        await message.answer("⚠️ User not found. Use /start first.")
        return

    funpay_key = user.get("funpay_golden_key")
    if not funpay_key:
        await state.clear()
        await message.answer("⚠️ No FunPay key configured. Go to ⚙️ Settings first.")
        return

    proxy = user.get("proxy")

    # Send the reply to FunPay
    try:
        await funpay.send_chat_message(funpay_key, node_id, message.text, proxy)
        await message.answer(
            "✅ *Reply sent to FunPay!*\n\n"
            f"[Open chat](https://funpay.com/chat/?node={node_id})",
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )
        log.info(
            "chat_reply: user %s replied to node %s",
            message.from_user.id, node_id,
        )
    except Exception as e:
        log.error(
            "chat_reply: failed to send reply to node %s for user %s: %s",
            node_id, message.from_user.id, e,
        )
        await message.answer(
            f"❌ Failed to send reply: `{e}`\n\n"
            f"[Try manually on FunPay](https://funpay.com/chat/?node={node_id})",
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )
    finally:
        await state.clear()
