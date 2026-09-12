"""
handlers/admin_maintenance.py
---------------------------------
Admin side of /maintenance: view tenant-reported maintenance requests
and change their status (New -> In Progress -> Completed / Rejected).
"""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler, CommandHandler

from utils.auth import admin_only
from services import maintenance_service, shop_service
from services.maintenance_service import CATEGORIES, STATUS_EMOJI
from keyboards.keyboards import maintenance_status_actions


def _status_filter_menu():
    rows = [
        [InlineKeyboardButton("🔴 New", callback_data="maintlist:NEW"),
         InlineKeyboardButton("🟡 In Progress", callback_data="maintlist:IN_PROGRESS")],
        [InlineKeyboardButton("🟢 Completed", callback_data="maintlist:COMPLETED"),
         InlineKeyboardButton("❌ Rejected", callback_data="maintlist:REJECTED")],
        [InlineKeyboardButton("📋 All", callback_data="maintlist:ALL")],
        [InlineKeyboardButton("⬅️ Back", callback_data="back:main")],
    ]
    return InlineKeyboardMarkup(rows)


@admin_only
async def show_maintenance_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    open_count = len(maintenance_service.list_requests(status="NEW"))
    text = f"🛠 MAINTENANCE\n\n🔴 Open (new) requests: {open_count}\n\nFilter by status:"
    await update.callback_query.edit_message_text(text, reply_markup=_status_filter_menu())


@admin_only
async def maintenance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    open_count = len(maintenance_service.list_requests(status="NEW"))
    text = f"🛠 MAINTENANCE\n\n🔴 Open (new) requests: {open_count}"
    await update.message.reply_text(text, reply_markup=_status_filter_menu())


@admin_only
async def maintenance_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    status = query.data.split(":")[1]
    requests = maintenance_service.list_requests(status=None if status == "ALL" else status)
    if not requests:
        await query.edit_message_text(
            "No maintenance requests in this category.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="menu:maintenance")]]),
        )
        return
    rows = []
    for r in requests[:20]:
        label = f"{STATUS_EMOJI.get(r['status'], '')} Shop {r['shop_number']} — {CATEGORIES.get(r['category'], r['category'])}"
        rows.append([InlineKeyboardButton(label, callback_data=f"maintview:{r['id']}")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="menu:maintenance")])
    await query.edit_message_text(f"Requests ({status}):", reply_markup=InlineKeyboardMarkup(rows))


@admin_only
async def maintenance_view_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    request_id = int(query.data.split(":")[1])
    req = maintenance_service.get_request(request_id)
    if not req:
        await query.edit_message_text("Request not found.")
        return
    shop = shop_service.get_shop(req["shop_id"])
    text = (
        f"🛠 MAINTENANCE REQUEST\n\n"
        f"Shop: {shop['shop_number']}\n"
        f"Category: {CATEGORIES.get(req['category'], req['category'])}\n"
        f"Description: {req['description'] or '(none provided)'}\n"
        f"Status: {STATUS_EMOJI.get(req['status'], '')} {req['status']}\n"
        f"Reported: {req['reported_at']}"
    )
    if req["photo_file_id"]:
        try:
            await context.bot.send_photo(chat_id=update.effective_user.id, photo=req["photo_file_id"])
        except Exception:
            pass
    if req["video_file_id"]:
        try:
            await context.bot.send_video(chat_id=update.effective_user.id, video=req["video_file_id"])
        except Exception:
            pass
    await query.edit_message_text(text, reply_markup=maintenance_status_actions(request_id))


@admin_only
async def maintenance_status_change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, request_id, new_status = query.data.split(":")
    request_id = int(request_id)
    maintenance_service.update_status(request_id, new_status, update.effective_user.id)
    req = maintenance_service.get_request(request_id)
    shop = shop_service.get_shop(req["shop_id"])

    # Notify the tenant of the status change, if linked.
    tenant_row = None
    if req["tenant_id"]:
        from services import tenant_service
        tenant_row = tenant_service.get_tenant(req["tenant_id"])
    if tenant_row and tenant_row["telegram_id"]:
        try:
            await context.bot.send_message(
                chat_id=tenant_row["telegram_id"],
                text=(f"🛠 Your maintenance report for Shop {shop['shop_number']} is now: "
                      f"{STATUS_EMOJI.get(new_status, '')} {new_status.replace('_', ' ').title()}"),
            )
        except Exception:
            pass

    await query.edit_message_text(f"✅ Status updated to {new_status.replace('_', ' ').title()}.")
