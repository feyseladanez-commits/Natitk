"""
handlers/tenant_maintenance.py
----------------------------------
Tenant-side "🛠 Report Maintenance" flow: choose a category, describe
the problem, optionally attach a photo/video, and notify the admin(s).
"""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (ContextTypes, ConversationHandler, MessageHandler, filters,
                           CallbackQueryHandler, CommandHandler)

from config import config
from utils.auth import get_tenant_by_telegram_id
from utils.validators import validate_non_empty, ValidationError
from services import shop_service, maintenance_service
from services.maintenance_service import CATEGORIES
from keyboards.keyboards import maintenance_categories
from handlers.common import CANCEL_FALLBACKS

MAINT_DESCRIPTION, MAINT_MEDIA = range(70, 72)


async def _require_tenant(update: Update):
    tenant = get_tenant_by_telegram_id(update.effective_user.id)
    if not tenant:
        if update.callback_query:
            await update.callback_query.answer(
                "You are not linked to a shop. Contact the administrator.", show_alert=True
            )
        else:
            await update.message.reply_text("You are not linked to a shop. Contact the administrator.")
    return tenant


async def maintenance_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tenant = await _require_tenant(update)
    if not tenant:
        return ConversationHandler.END
    await query.edit_message_text("What type of problem are you reporting?", reply_markup=maintenance_categories())
    return ConversationHandler.END


async def category_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tenant = await _require_tenant(update)
    if not tenant:
        return ConversationHandler.END
    category = query.data.split(":")[1]
    context.user_data["maint_category"] = category
    context.user_data["maint_shop_id"] = tenant["shop_id"]
    context.user_data["maint_tenant_id"] = tenant["id"]
    await query.edit_message_text(
        f"{CATEGORIES.get(category, category)}\n\nPlease describe the problem:"
    )
    return MAINT_DESCRIPTION


async def description_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        desc = validate_non_empty(update.message.text, "Description")
    except ValidationError as e:
        await update.message.reply_text(f"⚠️ {e}")
        return MAINT_DESCRIPTION
    context.user_data["maint_description"] = desc
    await update.message.reply_text(
        "You can attach a photo or short video of the problem, or send /skip."
    )
    return MAINT_MEDIA


async def _finalize(update: Update, context: ContextTypes.DEFAULT_TYPE, photo_file_id=None, video_file_id=None):
    d = context.user_data
    request_id = maintenance_service.create_request(
        shop_id=d["maint_shop_id"],
        tenant_id=d["maint_tenant_id"],
        category=d["maint_category"],
        description=d["maint_description"],
        photo_file_id=photo_file_id,
        video_file_id=video_file_id,
    )
    shop = shop_service.get_shop(d["maint_shop_id"])
    await update.message.reply_text(
        "✅ Your maintenance report has been submitted. The administrator will review it shortly."
    )

    text = (
        f"🛠 NEW MAINTENANCE REQUEST\n\n"
        f"Shop: {shop['shop_number']}\n"
        f"Problem: {CATEGORIES.get(d['maint_category'], d['maint_category'])}\n"
        f"Description: {d['maint_description']}"
    )
    for admin_id in config.ADMIN_IDS:
        try:
            if photo_file_id:
                await context.bot.send_photo(chat_id=admin_id, photo=photo_file_id, caption=text)
            elif video_file_id:
                await context.bot.send_video(chat_id=admin_id, video=video_file_id, caption=text)
            else:
                await context.bot.send_message(chat_id=admin_id, text=text)
        except Exception:
            continue

    context.user_data.clear()


async def media_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo_file_id = update.message.photo[-1].file_id if update.message.photo else None
    video_file_id = update.message.video.file_id if update.message.video else None
    await _finalize(update, context, photo_file_id=photo_file_id, video_file_id=video_file_id)
    return ConversationHandler.END


async def media_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _finalize(update, context)
    return ConversationHandler.END


tenant_maintenance_conversation = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(maintenance_entry, pattern="^t:maintenance$"),
        CallbackQueryHandler(category_chosen, pattern=r"^maintcat:"),
    ],
    states={
        MAINT_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, description_received)],
        MAINT_MEDIA: [
            MessageHandler(filters.PHOTO | filters.VIDEO, media_received),
            CommandHandler("skip", media_skip),
        ],
    },
    fallbacks=CANCEL_FALLBACKS,
)
