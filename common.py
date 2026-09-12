"""
handlers/common.py
---------------------
/start dispatch (admin vs tenant), shared cancel/back handling, and the
top-level menu callback router that dispatches "menu:*" button presses
to the right section.
"""

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, CallbackQueryHandler

from config import config
from utils.auth import is_admin, get_tenant_by_telegram_id
from keyboards.keyboards import admin_main_menu, tenant_main_menu


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if is_admin(user.id):
        await update.message.reply_text(
            f"🏢 {config.BUILDING_NAME}\n\nWelcome, administrator.",
        )
        await show_admin_dashboard(update, context)
        return

    tenant = get_tenant_by_telegram_id(user.id)
    if tenant:
        await update.message.reply_text(
            f"👋 Welcome back, {tenant['full_name']}.",
            reply_markup=tenant_main_menu(),
        )
        return

    await update.message.reply_text(
        "👋 Welcome.\n\n"
        "This bot manages "
        f"{config.BUILDING_NAME}.\n\n"
        "Your Telegram account is not yet linked to a shop. Please contact the "
        "building administrator with your Telegram username so they can link "
        f"your tenant profile.\n\nYour Telegram ID: {user.id}"
    )


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ You are not authorized to use this command.")
        return
    await show_admin_dashboard(update, context)


async def show_admin_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from services import shop_service, rent_service, maintenance_service

    counts = shop_service.counts_summary()
    rent_status = rent_service.building_rent_status()
    open_maint = len(maintenance_service.list_requests(status="NEW"))

    text = (
        f"🏢 {config.BUILDING_NAME}\n\n"
        f"{counts['total']} Shops\n\n"
        f"🟢 Occupied: {counts['occupied']}\n"
        f"⚪ Vacant: {counts['vacant']}\n\n"
        f"💰 Monthly Rent Expected:\n{rent_status['expected']:,.0f} {config.CURRENCY}\n\n"
        f"✅ Collected:\n{rent_status['collected']:,.0f} {config.CURRENCY}\n\n"
        f"🔴 Outstanding:\n{rent_status['outstanding']:,.0f} {config.CURRENCY}\n\n"
        f"🛠 Open Maintenance:\n{open_maint}"
    )

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=admin_main_menu())
    else:
        await update.message.reply_text(text, reply_markup=admin_main_menu())


async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("Cancelled.")
    else:
        await update.message.reply_text("Cancelled.")
    return ConversationHandler.END


async def back_to_tenant_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Main menu:", reply_markup=tenant_main_menu())


# Shared fallback list every ConversationHandler in this project includes, so
# that the "❌ Cancel" inline button (callback_data="cancel") works exactly
# like typing /cancel, no matter which step of a conversation the admin or
# tenant is on. Import CANCEL_FALLBACKS and splice it into each
# ConversationHandler's `fallbacks=[...]` list.
CANCEL_FALLBACKS = [
    CommandHandler("cancel", cancel_conversation),
    CallbackQueryHandler(cancel_conversation, pattern="^cancel$"),
]


async def back_to_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if is_admin(update.effective_user.id):
        await show_admin_dashboard(update, context)
    else:
        await query.edit_message_text("Main menu:", reply_markup=tenant_main_menu())


async def menu_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Dispatches top-level 'menu:<section>' callbacks from the admin dashboard."""
    query = update.callback_query
    await query.answer()
    section = query.data.split(":", 1)[1]

    if section == "shops":
        from handlers.admin_shops import show_floor_picker_for_shops
        await show_floor_picker_for_shops(update, context)
    elif section == "tenants":
        from handlers.admin_tenants import show_tenants_entry
        await show_tenants_entry(update, context)
    elif section == "rent":
        from handlers.admin_status import show_rent_status
        await show_rent_status(update, context)
    elif section == "payments":
        from handlers.admin_payments import show_payments_entry
        await show_payments_entry(update, context)
    elif section == "status":
        from handlers.admin_status import show_status_entry
        await show_status_entry(update, context)
    elif section == "maintenance":
        from handlers.admin_maintenance import show_maintenance_entry
        await show_maintenance_entry(update, context)
    elif section == "expenses":
        from handlers.admin_expenses import show_expenses_entry
        await show_expenses_entry(update, context)
    elif section == "announce":
        from handlers.admin_announcement import show_announce_entry
        await show_announce_entry(update, context)
    elif section == "reports":
        from handlers.admin_reports import show_reports_entry
        await show_reports_entry(update, context)
    elif section == "search":
        from handlers.admin_misc import show_search_entry
        await show_search_entry(update, context)
    elif section == "backup":
        from handlers.admin_misc import show_backup_entry
        await show_backup_entry(update, context)
    elif section == "settings":
        from handlers.admin_misc import show_settings_entry
        await show_settings_entry(update, context)
