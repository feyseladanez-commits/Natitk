"""
handlers/admin_floors.py
---------------------------
/addfloor, /floors, and floor edit/delete flows.
"""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, MessageHandler, filters, CommandHandler, CallbackQueryHandler

from utils.auth import admin_only
from utils.validators import validate_non_empty, ValidationError
from services import floor_service
from services.floor_service import FloorError
from keyboards.keyboards import back_cancel
from handlers.common import CANCEL_FALLBACKS

ADDFLOOR_NAME = 1
EDITFLOOR_NAME = 2


@admin_only
async def addfloor_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = "Floor name:\nExample:\nGround Floor\n1st Floor\n2nd Floor"
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(msg, reply_markup=back_cancel("floors:list"))
    else:
        await update.message.reply_text(msg, reply_markup=back_cancel("floors:list"))
    return ADDFLOOR_NAME


@admin_only
async def addfloor_receive_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        name = validate_non_empty(update.message.text, "Floor name")
        floor_service.add_floor(name, update.effective_user.id)
    except (ValidationError, FloorError) as e:
        await update.message.reply_text(f"⚠️ {e}\n\nTry again or /cancel.")
        return ADDFLOOR_NAME
    await update.message.reply_text(f"✅ Floor '{name}' created.")
    await list_floors(update, context)
    return ConversationHandler.END


addfloor_conversation = ConversationHandler(
    entry_points=[CommandHandler("addfloor", addfloor_start),
                  CallbackQueryHandler(addfloor_start, pattern="^floors:add$")],
    states={ADDFLOOR_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, addfloor_receive_name)]},
    fallbacks=CANCEL_FALLBACKS,
)


@admin_only
async def list_floors(update: Update, context: ContextTypes.DEFAULT_TYPE):
    floors = floor_service.list_floors()
    if not floors:
        text = "No floors have been created yet."
    else:
        text = "🏢 FLOORS\n\n" + "\n".join(f"• {f['name']}" for f in floors)

    rows = [[InlineKeyboardButton(f"✏️ {f['name']}", callback_data=f"floor:edit:{f['id']}"),
             InlineKeyboardButton("🗑", callback_data=f"floor:delete:{f['id']}")] for f in floors]
    rows.append([InlineKeyboardButton("➕ Add Floor", callback_data="floors:add")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="back:main")])
    markup = InlineKeyboardMarkup(rows)

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=markup)
    else:
        await update.message.reply_text(text, reply_markup=markup)


@admin_only
async def floors_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await list_floors(update, context)


@admin_only
async def floor_edit_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    floor_id = int(query.data.split(":")[2])
    context.user_data["edit_floor_id"] = floor_id
    await query.edit_message_text("Enter the new name for this floor:", reply_markup=back_cancel("floors:list"))
    return EDITFLOOR_NAME


@admin_only
async def floor_edit_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    floor_id = context.user_data.get("edit_floor_id")
    try:
        name = validate_non_empty(update.message.text, "Floor name")
        floor_service.rename_floor(floor_id, name, update.effective_user.id)
    except (ValidationError, FloorError) as e:
        await update.message.reply_text(f"⚠️ {e}\n\nTry again or /cancel.")
        return EDITFLOOR_NAME
    await update.message.reply_text(f"✅ Floor renamed to '{name}'.")
    await list_floors(update, context)
    return ConversationHandler.END


editfloor_conversation = ConversationHandler(
    entry_points=[CallbackQueryHandler(floor_edit_start, pattern=r"^floor:edit:\d+$")],
    states={EDITFLOOR_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, floor_edit_receive)]},
    fallbacks=CANCEL_FALLBACKS,
)


@admin_only
async def floor_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    floor_id = int(query.data.split(":")[2])
    try:
        floor_service.delete_floor(floor_id, update.effective_user.id)
        await query.edit_message_text("✅ Floor deleted.")
    except FloorError as e:
        await query.answer(str(e), show_alert=True)
        return
    await list_floors(update, context)
