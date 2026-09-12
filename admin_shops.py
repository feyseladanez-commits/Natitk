"""
handlers/admin_shops.py
---------------------------
/addshop, /editshop, /deleteshop, /shops, /shopinfo, /bulkshops
"""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (ContextTypes, ConversationHandler, MessageHandler, filters,
                           CommandHandler, CallbackQueryHandler)

from utils.auth import admin_only, mask_id_number, mask_phone
from utils.validators import validate_shop_number, validate_positive_number, ValidationError, parse_bulk_shops
from services import floor_service, shop_service, tenant_service, rent_service
from services.shop_service import ShopError
from services.floor_service import FloorError
from handlers.common import CANCEL_FALLBACKS
from keyboards.keyboards import (floors_menu, shops_list_menu, shop_detail_menu, back_cancel,
                                  confirm_cancel)

(ADDSHOP_FLOOR, ADDSHOP_NUMBER, ADDSHOP_SIZE, ADDSHOP_RENT, ADDSHOP_STATUS) = range(5)
(EDITSHOP_FIELD, EDITSHOP_VALUE) = range(5, 7)
BULKSHOPS_INPUT = 7


# ---------- /shops : browse by floor ----------

@admin_only
async def show_floor_picker_for_shops(update: Update, context: ContextTypes.DEFAULT_TYPE):
    floors = floor_service.list_floors()
    if not floors:
        text = "No floors exist yet. Use ➕ Add Floor first."
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("➕ Add Floor", callback_data="floors:add")],
                                        [InlineKeyboardButton("⬅️ Back", callback_data="back:main")]])
    else:
        text = "🏪 SHOPS\n\nSelect a floor:"
        markup = floors_menu(floors, prefix="shopsfloor")
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=markup)
    else:
        await update.message.reply_text(text, reply_markup=markup)


@admin_only
async def shops_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_floor_picker_for_shops(update, context)


@admin_only
async def shops_by_floor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    floor_id = int(query.data.split(":")[1])
    floor = floor_service.get_floor(floor_id)
    shops = shop_service.list_shops(floor_id)
    context.user_data["shops_page_list"] = [s["id"] for s in shops]
    context.user_data["shops_page_prefix"] = "shopinfo"
    context.user_data["shops_page_back"] = "menu:shops"
    if not shops:
        text = f"{floor['name'].upper()}\n\nNo shops registered on this floor yet."
    else:
        lines = [f"{floor['name'].upper()}", ""]
        for s in shops:
            dot = "🟢" if s["status"] == "OCCUPIED" else "⚪"
            lines.append(f"{dot} Shop {s['shop_number']} — {s['size_sqm']:.0f} m²")
        text = "\n".join(lines)
    await query.edit_message_text(
        text, reply_markup=shops_list_menu(shops, page=0, prefix="shopinfo", back_cb="menu:shops")
    )


@admin_only
async def shops_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Generic pagination handler shared by every 'browse shops by floor' list
    (shops, tenants, payment history, manual payment entry). Whichever
    screen built the current list stores its own prefix/back-button target
    in user_data so the Next/Prev buttons keep working no matter which
    section they were opened from.
    """
    query = update.callback_query
    await query.answer()
    page = int(query.data.split(":")[1])
    ids = context.user_data.get("shops_page_list", [])
    shops = [shop_service.get_shop(i) for i in ids]
    prefix = context.user_data.get("shops_page_prefix", "shopinfo")
    back_cb = context.user_data.get("shops_page_back", "menu:shops")
    await query.edit_message_reply_markup(
        reply_markup=shops_list_menu(shops, page=page, prefix=prefix, back_cb=back_cb)
    )


# ---------- /shopinfo : shop detail ----------

def _format_shop_detail(shop, tenant, rent_summary) -> str:
    lines = [f"🏪 Shop {shop['shop_number']}", ""]
    lines.append(f"📍 Floor: {shop['floor_name']}")
    lines.append(f"📐 Size: {shop['size_sqm']:.0f} m²")
    if tenant:
        lines.append(f"👤 Tenant: {tenant['full_name']}")
        lines.append(f"📱 Phone: {tenant['phone']}")
    lines.append(f"💰 Monthly Rent: {shop['monthly_rent']:,.0f} ETB")
    status_dot = "🟢" if shop["status"] == "OCCUPIED" else "⚪"
    lines.append(f"{status_dot} Status: {shop['status'].title()}")
    if tenant:
        lines.append("")
        lines.append(f"Paid months: {rent_summary['paid']}")
        lines.append(f"Unpaid months: {rent_summary['unpaid']}")
        lines.append(f"Outstanding: {rent_summary['outstanding']:,.0f} ETB")
    return "\n".join(lines)


@admin_only
async def shop_info_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    shop_id = int(query.data.split(":")[1])
    await render_shop_detail(update, context, shop_id)


async def render_shop_detail(update, context, shop_id):
    shop = shop_service.get_shop(shop_id)
    if not shop:
        await update.callback_query.edit_message_text("Shop not found.")
        return
    tenant = tenant_service.get_active_tenant_for_shop(shop_id)
    rent_rows = rent_service.shop_rent_rows(shop_id)
    paid = sum(1 for r in rent_rows if r["status"] == "PAID")
    unpaid = sum(1 for r in rent_rows if r["status"] in ("UNPAID", "OVERDUE"))
    outstanding = rent_service.shop_outstanding_amount(shop_id)
    text = _format_shop_detail(shop, tenant, {"paid": paid, "unpaid": unpaid, "outstanding": outstanding})
    await update.callback_query.edit_message_text(
        text, reply_markup=shop_detail_menu(shop_id, has_tenant=bool(tenant))
    )


@admin_only
async def shopinfo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /shopinfo <shop_number>")
        return
    shop = shop_service.get_shop_by_number(context.args[0])
    if not shop:
        await update.message.reply_text("Shop not found.")
        return
    tenant = tenant_service.get_active_tenant_for_shop(shop["id"])
    rent_rows = rent_service.shop_rent_rows(shop["id"])
    paid = sum(1 for r in rent_rows if r["status"] == "PAID")
    unpaid = sum(1 for r in rent_rows if r["status"] in ("UNPAID", "OVERDUE"))
    outstanding = rent_service.shop_outstanding_amount(shop["id"])
    text = _format_shop_detail(shop, tenant, {"paid": paid, "unpaid": unpaid, "outstanding": outstanding})
    await update.message.reply_text(text, reply_markup=shop_detail_menu(shop["id"], has_tenant=bool(tenant)))


# ---------- /addshop conversation ----------

@admin_only
async def addshop_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    floors = floor_service.list_floors()
    if not floors:
        msg = "⚠️ Create a floor first with /addfloor."
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(msg)
        else:
            await update.message.reply_text(msg)
        return ConversationHandler.END
    text = "Select floor for the new shop:"
    markup = floors_menu(floors, prefix="newshopfloor", extra_back="cancel")
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=markup)
    else:
        await update.message.reply_text(text, reply_markup=markup)
    return ADDSHOP_FLOOR


async def addshop_floor_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    floor_id = int(query.data.split(":")[1])
    context.user_data["new_shop_floor_id"] = floor_id
    await query.edit_message_text("Shop number (e.g. 12):", reply_markup=back_cancel("cancel", include_cancel=False))
    return ADDSHOP_NUMBER


async def addshop_number_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        number = validate_shop_number(update.message.text)
    except ValidationError as e:
        await update.message.reply_text(f"⚠️ {e}")
        return ADDSHOP_NUMBER
    context.user_data["new_shop_number"] = number
    await update.message.reply_text("Shop size in m²:")
    return ADDSHOP_SIZE


async def addshop_size_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        size = validate_positive_number(update.message.text, "Size")
    except ValidationError as e:
        await update.message.reply_text(f"⚠️ {e}")
        return ADDSHOP_SIZE
    context.user_data["new_shop_size"] = size
    await update.message.reply_text("Monthly rent (ETB):")
    return ADDSHOP_RENT


async def addshop_rent_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        rent = validate_positive_number(update.message.text, "Rent")
    except ValidationError as e:
        await update.message.reply_text(f"⚠️ {e}")
        return ADDSHOP_RENT
    context.user_data["new_shop_rent"] = rent
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("Occupied", callback_data="shopstatus:OCCUPIED"),
         InlineKeyboardButton("Vacant", callback_data="shopstatus:VACANT")],
    ])
    await update.message.reply_text("Shop status:", reply_markup=markup)
    return ADDSHOP_STATUS


async def addshop_status_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    status = query.data.split(":")[1]
    d = context.user_data
    try:
        shop_id = shop_service.add_shop(
            d["new_shop_number"], d["new_shop_floor_id"], d["new_shop_size"],
            d["new_shop_rent"], status, update.effective_user.id,
        )
    except ShopError as e:
        await query.edit_message_text(f"⚠️ {e}")
        return ConversationHandler.END

    floor = floor_service.get_floor(d["new_shop_floor_id"])
    await query.edit_message_text(
        f"✅ Shop registered:\n\n"
        f"Shop Number: {d['new_shop_number']}\n"
        f"Floor: {floor['name']}\n"
        f"Size: {d['new_shop_size']:.0f} m²\n"
        f"Monthly Rent: {d['new_shop_rent']:,.0f} ETB\n"
        f"Status: {status.title()}"
    )
    context.user_data.clear()
    return ConversationHandler.END


addshop_conversation = ConversationHandler(
    entry_points=[CommandHandler("addshop", addshop_start),
                  CallbackQueryHandler(addshop_start, pattern="^shops:add$")],
    states={
        ADDSHOP_FLOOR: [CallbackQueryHandler(addshop_floor_chosen, pattern=r"^newshopfloor:\d+$")],
        ADDSHOP_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, addshop_number_received)],
        ADDSHOP_SIZE: [MessageHandler(filters.TEXT & ~filters.COMMAND, addshop_size_received)],
        ADDSHOP_RENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, addshop_rent_received)],
        ADDSHOP_STATUS: [CallbackQueryHandler(addshop_status_received, pattern=r"^shopstatus:")],
    },
    fallbacks=CANCEL_FALLBACKS,
)


# ---------- /editshop ----------

EDITABLE_FIELDS = {
    "number": "Shop number",
    "size": "Size (m²)",
    "rent": "Monthly rent (ETB)",
    "status": "Status",
}


@admin_only
async def editshop_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    shop_id = int(query.data.split(":")[1])
    context.user_data["edit_shop_id"] = shop_id
    rows = [[InlineKeyboardButton(label, callback_data=f"editshopfield:{key}")]
            for key, label in EDITABLE_FIELDS.items()]
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"shopinfo:{shop_id}")])
    await query.edit_message_text("What would you like to edit?", reply_markup=InlineKeyboardMarkup(rows))
    return EDITSHOP_FIELD


async def editshop_field_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    field = query.data.split(":")[1]
    context.user_data["edit_shop_field"] = field
    if field == "status":
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("Occupied", callback_data="editshopstatus:OCCUPIED"),
             InlineKeyboardButton("Vacant", callback_data="editshopstatus:VACANT")]
        ])
        await query.edit_message_text("New status:", reply_markup=markup)
        return EDITSHOP_VALUE
    await query.edit_message_text(f"Enter new {EDITABLE_FIELDS[field]}:")
    return EDITSHOP_VALUE


async def _apply_shop_edit(update, context, admin_id, **kwargs):
    shop_id = context.user_data["edit_shop_id"]
    try:
        shop_service.update_shop(shop_id, admin_id, **kwargs)
    except ShopError as e:
        text = f"⚠️ {e}"
    else:
        text = "✅ Shop updated."
    context.user_data.clear()
    return shop_id, text


async def editshop_value_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    field = context.user_data.get("edit_shop_field")
    try:
        if field == "number":
            value = validate_shop_number(update.message.text)
            shop_id, text = await _apply_shop_edit(update, context, update.effective_user.id, shop_number=value)
        elif field == "size":
            value = validate_positive_number(update.message.text, "Size")
            shop_id, text = await _apply_shop_edit(update, context, update.effective_user.id, size_sqm=value)
        elif field == "rent":
            value = validate_positive_number(update.message.text, "Rent")
            shop_id, text = await _apply_shop_edit(update, context, update.effective_user.id, monthly_rent=value)
        else:
            await update.message.reply_text("Unknown field.")
            return ConversationHandler.END
    except (ValidationError, ShopError) as e:
        await update.message.reply_text(f"⚠️ {e}")
        return EDITSHOP_VALUE
    await update.message.reply_text(text)
    return ConversationHandler.END


async def editshop_status_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    status = query.data.split(":")[1]
    shop_id, text = await _apply_shop_edit(update, context, update.effective_user.id, status=status)
    await query.edit_message_text(text)
    await render_shop_detail(update, context, shop_id)
    return ConversationHandler.END


# ---------- /editshop (command entry point) ----------

@admin_only
async def editshop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Usage: /editshop <shop_number> - shows the same field picker used by the
    ✏️ Edit Shop button, so both entry points share one conversation."""
    if not context.args:
        await update.message.reply_text("Usage: /editshop <shop_number>")
        return ConversationHandler.END
    shop = shop_service.get_shop_by_number(context.args[0])
    if not shop:
        await update.message.reply_text("Shop not found.")
        return ConversationHandler.END
    context.user_data["edit_shop_id"] = shop["id"]
    rows = [[InlineKeyboardButton(label, callback_data=f"editshopfield:{key}")]
            for key, label in EDITABLE_FIELDS.items()]
    rows.append([InlineKeyboardButton("⬅️ Cancel", callback_data="cancel")])
    await update.message.reply_text("What would you like to edit?", reply_markup=InlineKeyboardMarkup(rows))
    return EDITSHOP_FIELD


editshop_conversation = ConversationHandler(
    entry_points=[CallbackQueryHandler(editshop_start, pattern=r"^editshop:\d+$"),
                  CommandHandler("editshop", editshop_command)],
    states={
        EDITSHOP_FIELD: [CallbackQueryHandler(editshop_field_chosen, pattern=r"^editshopfield:")],
        EDITSHOP_VALUE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, editshop_value_received),
            CallbackQueryHandler(editshop_status_received, pattern=r"^editshopstatus:"),
        ],
    },
    fallbacks=CANCEL_FALLBACKS,
)


# ---------- /deleteshop ----------

@admin_only
async def deleteshop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /deleteshop <shop_number>")
        return
    shop = shop_service.get_shop_by_number(context.args[0])
    if not shop:
        await update.message.reply_text("Shop not found.")
        return
    context.user_data["delete_shop_id"] = shop["id"]
    await update.message.reply_text(
        f"Delete shop {shop['shop_number']}? This cannot be undone.",
        reply_markup=confirm_cancel(f"deleteshopconfirm:{shop['id']}", "cancel"),
    )


@admin_only
async def deleteshop_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    shop_id = int(query.data.split(":")[1])
    try:
        shop_service.delete_shop(shop_id, update.effective_user.id)
        await query.edit_message_text("✅ Shop deleted.")
    except ShopError as e:
        await query.edit_message_text(f"⚠️ {e}")


# ---------- /bulkshops ----------

@admin_only
async def bulkshops_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Paste your floors and shops in this format:\n\n"
        "Ground Floor\n01,32,20000\n02,28,18000\n\n1st Floor\n04,35,22000\n05,40,25000\n\n"
        "(shop_number,size_sqm,monthly_rent per line)\n\nSend /cancel to abort."
    )
    return BULKSHOPS_INPUT


@admin_only
async def bulkshops_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        entries = parse_bulk_shops(update.message.text)
    except ValidationError as e:
        await update.message.reply_text(f"⚠️ {e}\n\nPlease correct and resend, or /cancel.")
        return BULKSHOPS_INPUT
    context.user_data["bulk_entries"] = entries
    await update.message.reply_text(
        f"You are about to register {len(entries)} shops. Continue?",
        reply_markup=confirm_cancel("bulkconfirm", "cancel"),
    )
    return ConversationHandler.END


@admin_only
async def bulkshops_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    entries = context.user_data.get("bulk_entries")
    if not entries:
        await query.edit_message_text("No pending bulk shop data found. Please run /bulkshops again.")
        return
    try:
        created = shop_service.bulk_add_shops(entries, update.effective_user.id)
        await query.edit_message_text(f"✅ {created} shops registered successfully.")
    except ShopError as e:
        await query.edit_message_text(f"⚠️ {e}\n\nNo shops were saved (all-or-nothing).")
    context.user_data.pop("bulk_entries", None)


bulkshops_conversation = ConversationHandler(
    entry_points=[CommandHandler("bulkshops", bulkshops_start)],
    states={BULKSHOPS_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, bulkshops_receive)]},
    fallbacks=CANCEL_FALLBACKS,
)
