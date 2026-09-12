"""
handlers/admin_announcement.py
----------------------------------
/announcement - admin writes a building-wide notice, confirms, and it
is broadcast to every active tenant who has linked their Telegram account.
"""

from telegram import Update
from telegram.ext import (ContextTypes, ConversationHandler, MessageHandler, filters,
                           CommandHandler, CallbackQueryHandler)

from utils.auth import admin_only
from utils.validators import validate_non_empty, ValidationError
from services import announcement_service
from keyboards.keyboards import yes_no
from handlers.common import CANCEL_FALLBACKS

ANNOUNCE_MESSAGE = 30


@admin_only
async def show_announce_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    recent = announcement_service.list_announcements(limit=3)
    text = "📢 ANNOUNCEMENTS\n\nSend /announcement to write a new building-wide notice."
    if recent:
        text += "\n\nMost recent:\n" + "\n---\n".join(a["message"][:200] for a in recent)
    await update.callback_query.edit_message_text(text)


@admin_only
async def announcement_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Write the announcement message you want to send to all tenants:"
    )
    return ANNOUNCE_MESSAGE


async def announcement_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        message = validate_non_empty(update.message.text, "Message")
    except ValidationError as e:
        await update.message.reply_text(f"⚠️ {e}")
        return ANNOUNCE_MESSAGE
    context.user_data["announce_message"] = message
    await update.message.reply_text(
        f"📢 BUILDING NOTICE\n\n{message}\n\nSend to all tenants?",
        reply_markup=yes_no("announceconfirm", "cancel"),
    )
    return ConversationHandler.END


announcement_conversation = ConversationHandler(
    entry_points=[CommandHandler("announcement", announcement_start)],
    states={ANNOUNCE_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, announcement_receive)]},
    fallbacks=CANCEL_FALLBACKS,
)


@admin_only
async def announcement_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    message = context.user_data.get("announce_message")
    if not message:
        await query.edit_message_text("No pending announcement found. Please run /announcement again.")
        return
    recipient_ids = announcement_service.active_tenant_telegram_ids()
    sent = 0
    for tid in recipient_ids:
        try:
            await context.bot.send_message(chat_id=tid, text=f"📢 BUILDING NOTICE\n\n{message}")
            sent += 1
        except Exception:
            continue
    announcement_service.record_announcement(message, update.effective_user.id, sent)
    await query.edit_message_text(f"✅ Announcement sent to {sent} tenant(s).")
    context.user_data.pop("announce_message", None)
