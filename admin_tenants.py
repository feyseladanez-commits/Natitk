"""
handlers/admin_tenants.py
-----------------------------
/addtenant, /edittenant, /deletetenant, /tenantinfo, and secure ID
document attach/view.
"""

import uuid
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (ContextTypes, ConversationHandler, MessageHandler, filters,
                           CommandHandler, CallbackQueryHandler)

from config import config
from utils.auth import admin_only, mask_id_number, mask_phone, is_admin
from utils.validators import validate_non_empty, validate_phone, validate_positive_number, ValidationError
from calendar_utils.ethiopian import parse_ethiopian_input, ethiopian_to_gregorian, gregorian_to_ethiopian
from calendar_utils.ethiopian import EthiopianDate
from services import tenant_service, shop_service, floor_service
from services.tenant_service import TenantError
from handlers.common import CANCEL_FALLBACKS
from keyboards.keyboards import floors_menu, shops_list_menu, confirm_cancel

(ADDT_NAME, ADDT_PHONE, ADDT_IDTYPE, ADDT_IDNUM, ADDT_START, ADDT_END,
 ADDT_RENT, ADDT_NOTES, ADDT_DOC) = range(9)

(EDITT_FIELD, EDITT_VALUE) = range(9, 11)


# ---------- entry from main menu: browse tenants via floor -> shop ----------

@admin_only
async def show_tenants_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    floors = floor_service.list_floors()
    if not floors:
        await update.callback_query.edit_message_text("No floors/shops exist yet.")
        return
    await update.callback_query.edit_message_text(
        "👥 TENANTS\n\nSelect a floor to browse tenants by shop:",
        reply_markup=floors_menu(floors, prefix="tenantsfloor"),
    )


@admin_only
async def tenants_by_floor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    floor_id = int(query.data.split(":")[1])
    shops = shop_service.list_shops(floor_id)
    context.user_data["shops_page_list"] = [s["id"] for s in shops]
    context.user_data["shops_page_prefix"] = "tenantshop"
    context.user_data["shops_page_back"] = "menu:tenants"
    await query.edit_message_text(
        "Select a shop:", reply_markup=shops_list_menu(shops, page=0, prefix="tenantshop", back_cb="menu:tenants")
    )


@admin_only
async def tenant_view_by_shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    shop_id = int(query.data.split(":")[1])
    await render_tenant_view(update, context, shop_id)


@admin_only
async def tenant_view_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    shop_id = int(query.data.split(":")[1])
    await render_tenant_view(update, context, shop_id)


async def render_tenant_view(update, context, shop_id):
    shop = shop_service.get_shop(shop_id)
    tenant = tenant_service.get_active_tenant_for_shop(shop_id)
    if not tenant:
        rows = [[InlineKeyboardButton("➕ Add Tenant", callback_data=f"addtenant:{shop_id}")],
                [InlineKeyboardButton("⬅️ Back", callback_data=f"shopinfo:{shop_id}")]]
        await update.callback_query.edit_message_text(
            f"Shop {shop['shop_number']} has no active tenant.",
            reply_markup=InlineKeyboardMarkup(rows),
        )
        return

    text = (
        f"Shop {shop['shop_number']}\n"
        f"Tenant: {tenant['full_name']}\n"
        f"ID: {mask_id_number(tenant['id_number'])}\n"
        f"Phone: {tenant['phone']}\n"
        f"Contract: {tenant['contract_start']} → {tenant['contract_end'] or 'open-ended'}\n"
    )
    if tenant["notes"]:
        text += f"Notes: {tenant['notes']}\n"

    rows = [
        [InlineKeyboardButton("📄 View ID Document", callback_data=f"viewdoc:{tenant['id']}")],
        [InlineKeyboardButton("✏️ Edit Tenant", callback_data=f"edittenant:{tenant['id']}"),
         InlineKeyboardButton("🗑 Remove Tenant", callback_data=f"deltenant:{tenant['id']}")],
        [InlineKeyboardButton("⬅️ Back", callback_data=f"shopinfo:{shop_id}")],
    ]
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows))


@admin_only
async def tenantinfo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /tenantinfo <shop_number>")
        return
    shop = shop_service.get_shop_by_number(context.args[0])
    if not shop:
        await update.message.reply_text("Shop not found.")
        return
    tenant = tenant_service.get_active_tenant_for_shop(shop["id"])
    if not tenant:
        await update.message.reply_text("No active tenant for this shop.")
        return
    text = (
        f"Shop {shop['shop_number']}\n"
        f"Tenant: {tenant['full_name']}\n"
        f"ID: {mask_id_number(tenant['id_number'])}\n"
        f"Phone: {tenant['phone']}\n"
        f"Contract: {tenant['contract_start']} → {tenant['contract_end'] or 'open-ended'}\n"
    )
    rows = [[InlineKeyboardButton("📄 View ID Document", callback_data=f"viewdoc:{tenant['id']}")]]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(rows))


# ---------- /addtenant conversation ----------

@admin_only
async def addtenant_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Usage: /addtenant <shop_number> - command equivalent of the ➕ Add Tenant button."""
    if not context.args:
        await update.message.reply_text("Usage: /addtenant <shop_number>")
        return ConversationHandler.END
    shop = shop_service.get_shop_by_number(context.args[0])
    if not shop:
        await update.message.reply_text("Shop not found.")
        return ConversationHandler.END
    existing = tenant_service.get_active_tenant_for_shop(shop["id"])
    if existing:
        await update.message.reply_text(
            "This shop already has an active tenant. Remove/replace the existing tenant first."
        )
        return ConversationHandler.END
    context.user_data["new_tenant_shop_id"] = shop["id"]
    context.user_data["new_tenant_rent"] = shop["monthly_rent"]
    await update.message.reply_text("Tenant full name:")
    return ADDT_NAME


@admin_only
async def addtenant_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    shop_id = int(query.data.split(":")[1])
    shop = shop_service.get_shop(shop_id)
    existing = tenant_service.get_active_tenant_for_shop(shop_id)
    if existing:
        await query.edit_message_text(
            "This shop already has an active tenant. Remove the current tenant first."
        )
        return ConversationHandler.END
    context.user_data["new_tenant_shop_id"] = shop_id
    context.user_data["new_tenant_rent"] = shop["monthly_rent"]
    await query.edit_message_text("Tenant full name:")
    return ADDT_NAME


async def addtenant_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        name = validate_non_empty(update.message.text, "Full name")
    except ValidationError as e:
        await update.message.reply_text(f"⚠️ {e}")
        return ADDT_NAME
    context.user_data["new_tenant_name"] = name
    await update.message.reply_text("Phone number:")
    return ADDT_PHONE


async def addtenant_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        phone = validate_phone(update.message.text)
    except ValidationError as e:
        await update.message.reply_text(f"⚠️ {e}")
        return ADDT_PHONE
    context.user_data["new_tenant_phone"] = phone
    await update.message.reply_text("National ID type (e.g. Kebele ID, Passport, Driving License):")
    return ADDT_IDTYPE


async def addtenant_idtype(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_tenant_idtype"] = validate_non_empty(update.message.text, "ID type")
    await update.message.reply_text("National ID number:")
    return ADDT_IDNUM


async def addtenant_idnum(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_tenant_idnum"] = validate_non_empty(update.message.text, "ID number")
    await update.message.reply_text(
        "Contract start date (Ethiopian calendar, e.g. 2019 1 1 for Meskerem, or type 'today'):"
    )
    return ADDT_START


async def addtenant_start_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    try:
        if text == "today":
            from calendar_utils.ethiopian import today_ethiopian
            e_date = today_ethiopian()
        else:
            e_date = parse_ethiopian_input(update.message.text)
        g_date = ethiopian_to_gregorian(e_date)
    except ValueError as e:
        await update.message.reply_text(f"⚠️ {e}\n\nFormat: YYYY MM DD (Ethiopian), e.g. 2019 1 1")
        return ADDT_START
    context.user_data["new_tenant_start_greg"] = g_date.isoformat()
    context.user_data["new_tenant_start_e"] = e_date.display()
    await update.message.reply_text(
        "Contract end date (Ethiopian calendar, e.g. 2021 1 1), or type 'none' for open-ended:"
    )
    return ADDT_END


async def addtenant_end_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    if text in ("none", "n/a", "-", "open"):
        context.user_data["new_tenant_end_greg"] = None
    else:
        try:
            e_date = parse_ethiopian_input(update.message.text)
            g_date = ethiopian_to_gregorian(e_date)
        except ValueError as e:
            await update.message.reply_text(f"⚠️ {e}\n\nFormat: YYYY MM DD (Ethiopian) or 'none'")
            return ADDT_END
        context.user_data["new_tenant_end_greg"] = g_date.isoformat()
    rent = context.user_data.get("new_tenant_rent")
    await update.message.reply_text(
        f"Monthly rent (ETB) [shop default: {rent:,.0f}] — send a number, or 'default':"
    )
    return ADDT_RENT


async def addtenant_rent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    if text == "default":
        rent = context.user_data["new_tenant_rent"]
    else:
        try:
            rent = validate_positive_number(update.message.text, "Rent")
        except ValidationError as e:
            await update.message.reply_text(f"⚠️ {e}")
            return ADDT_RENT
    context.user_data["new_tenant_rent"] = rent
    await update.message.reply_text("Any optional notes? (or send 'none')")
    return ADDT_NOTES


async def addtenant_notes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data["new_tenant_notes"] = None if text.lower() in ("none", "-", "n/a") else text
    await update.message.reply_text(
        "Please send a photo or scanned document of the tenant's national ID.\n"
        "(This will be stored securely and shown only to authorized administrators.)\n\n"
        "Or send /skip to add it later."
    )
    return ADDT_DOC


async def _finalize_tenant(update, context, doc_file_path=None, doc_file_id=None):
    d = context.user_data
    try:
        tenant_id = tenant_service.add_tenant(
            shop_id=d["new_tenant_shop_id"],
            full_name=d["new_tenant_name"],
            phone=d["new_tenant_phone"],
            id_type=d["new_tenant_idtype"],
            id_number=d["new_tenant_idnum"],
            contract_start_greg=d["new_tenant_start_greg"],
            contract_end_greg=d.get("new_tenant_end_greg"),
            monthly_rent=d["new_tenant_rent"],
            notes=d.get("new_tenant_notes"),
            admin_id=update.effective_user.id,
        )
    except TenantError as e:
        await update.message.reply_text(f"⚠️ {e}")
        context.user_data.clear()
        return

    if doc_file_path:
        tenant_service.attach_document(tenant_id, doc_file_path, doc_file_id, "NATIONAL_ID",
                                        update.effective_user.id)

    await update.message.reply_text(
        f"✅ Tenant added:\n\n"
        f"Shop {shop_service.get_shop(d['new_tenant_shop_id'])['shop_number']}\n"
        f"Tenant: {d['new_tenant_name']}\n"
        f"ID: {mask_id_number(d['new_tenant_idnum'])}\n"
        f"Phone: {d['new_tenant_phone']}"
    )
    context.user_data.clear()


async def addtenant_doc_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo_or_doc = update.message.photo[-1] if update.message.photo else update.message.document
    if not photo_or_doc:
        await update.message.reply_text("Please send a photo or document, or /skip.")
        return ADDT_DOC

    file = await photo_or_doc.get_file()
    ext = ".jpg" if update.message.photo else Path(update.message.document.file_name or "id").suffix or ".dat"
    filename = f"{uuid.uuid4().hex}{ext}"
    dest_path = config.DOCUMENTS_DIR / filename
    await file.download_to_drive(custom_path=str(dest_path))

    await _finalize_tenant(update, context, doc_file_path=str(dest_path), doc_file_id=photo_or_doc.file_id)
    return ConversationHandler.END


async def addtenant_doc_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _finalize_tenant(update, context)
    return ConversationHandler.END


addtenant_conversation = ConversationHandler(
    entry_points=[CallbackQueryHandler(addtenant_start, pattern=r"^addtenant:\d+$"),
                  CommandHandler("addtenant", addtenant_command)],
    states={
        ADDT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, addtenant_name)],
        ADDT_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, addtenant_phone)],
        ADDT_IDTYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, addtenant_idtype)],
        ADDT_IDNUM: [MessageHandler(filters.TEXT & ~filters.COMMAND, addtenant_idnum)],
        ADDT_START: [MessageHandler(filters.TEXT & ~filters.COMMAND, addtenant_start_date)],
        ADDT_END: [MessageHandler(filters.TEXT & ~filters.COMMAND, addtenant_end_date)],
        ADDT_RENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, addtenant_rent)],
        ADDT_NOTES: [MessageHandler(filters.TEXT & ~filters.COMMAND, addtenant_notes)],
        ADDT_DOC: [
            MessageHandler(filters.PHOTO | filters.Document.ALL, addtenant_doc_received),
            CommandHandler("skip", addtenant_doc_skip),
        ],
    },
    fallbacks=CANCEL_FALLBACKS,
)


# ---------- View ID document (admin-only, access logged) ----------

@admin_only
async def view_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from services.audit import log_action
    query = update.callback_query
    await query.answer()
    tenant_id = int(query.data.split(":")[1])
    docs = tenant_service.list_documents(tenant_id)
    if not docs:
        await query.answer("No ID document on file for this tenant.", show_alert=True)
        return
    doc = docs[0]
    log_action(update.effective_user.id, "TENANT_DOCUMENT_VIEWED", "tenant_documents", doc["id"],
               f"tenant_id={tenant_id}")
    try:
        if doc["telegram_file_id"]:
            await context.bot.send_photo(chat_id=update.effective_user.id, photo=doc["telegram_file_id"],
                                          caption="🔒 Confidential tenant ID document.")
        else:
            with open(doc["file_path"], "rb") as f:
                await context.bot.send_document(chat_id=update.effective_user.id, document=f,
                                                 caption="🔒 Confidential tenant ID document.")
    except Exception:
        await query.answer("Could not send document.", show_alert=True)


# ---------- /edittenant ----------

TENANT_EDITABLE = {
    "name": ("full_name", "Full name"),
    "phone": ("phone", "Phone number"),
    "idtype": ("id_type", "ID type"),
    "idnum": ("id_number", "ID number"),
    "notes": ("notes", "Notes"),
}


@admin_only
async def edittenant_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Usage: /edittenant <shop_number>"""
    if not context.args:
        await update.message.reply_text("Usage: /edittenant <shop_number>")
        return ConversationHandler.END
    shop = shop_service.get_shop_by_number(context.args[0])
    tenant = tenant_service.get_active_tenant_for_shop(shop["id"]) if shop else None
    if not tenant:
        await update.message.reply_text("No active tenant found for that shop.")
        return ConversationHandler.END
    context.user_data["edit_tenant_id"] = tenant["id"]
    rows = [[InlineKeyboardButton(label, callback_data=f"edittenantfield:{key}")]
            for key, (_, label) in TENANT_EDITABLE.items()]
    rows.append([InlineKeyboardButton("⬅️ Cancel", callback_data="cancel")])
    await update.message.reply_text("What would you like to edit?", reply_markup=InlineKeyboardMarkup(rows))
    return EDITT_FIELD


@admin_only
async def edittenant_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tenant_id = int(query.data.split(":")[1])
    context.user_data["edit_tenant_id"] = tenant_id
    rows = [[InlineKeyboardButton(label, callback_data=f"edittenantfield:{key}")]
            for key, (_, label) in TENANT_EDITABLE.items()]
    rows.append([InlineKeyboardButton("⬅️ Cancel", callback_data="cancel")])
    await query.edit_message_text("What would you like to edit?", reply_markup=InlineKeyboardMarkup(rows))
    return EDITT_FIELD


async def edittenant_field_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    field = query.data.split(":")[1]
    context.user_data["edit_tenant_field"] = field
    _, label = TENANT_EDITABLE[field]
    await query.edit_message_text(f"Enter new {label}:")
    return EDITT_VALUE


async def edittenant_value_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    field = context.user_data.get("edit_tenant_field")
    column, label = TENANT_EDITABLE[field]
    value = update.message.text.strip()
    if field == "phone":
        try:
            value = validate_phone(value)
        except ValidationError as e:
            await update.message.reply_text(f"⚠️ {e}")
            return EDITT_VALUE
    tenant_id = context.user_data["edit_tenant_id"]
    kwargs = {("full_name" if column == "full_name" else
               "phone" if column == "phone" else
               "id_type" if column == "id_type" else
               "id_number" if column == "id_number" else "notes"): value}
    try:
        tenant_service.update_tenant(tenant_id, update.effective_user.id, **kwargs)
    except TenantError as e:
        await update.message.reply_text(f"⚠️ {e}")
        return ConversationHandler.END
    await update.message.reply_text(f"✅ {label} updated.")
    context.user_data.clear()
    return ConversationHandler.END


edittenant_conversation = ConversationHandler(
    entry_points=[CallbackQueryHandler(edittenant_start, pattern=r"^edittenant:\d+$"),
                  CommandHandler("edittenant", edittenant_command)],
    states={
        EDITT_FIELD: [CallbackQueryHandler(edittenant_field_chosen, pattern=r"^edittenantfield:")],
        EDITT_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, edittenant_value_received)],
    },
    fallbacks=CANCEL_FALLBACKS,
)


# ---------- /deletetenant ----------

@admin_only
async def deletetenant_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Usage: /deletetenant <shop_number>"""
    if not context.args:
        await update.message.reply_text("Usage: /deletetenant <shop_number>")
        return
    shop = shop_service.get_shop_by_number(context.args[0])
    tenant = tenant_service.get_active_tenant_for_shop(shop["id"]) if shop else None
    if not tenant:
        await update.message.reply_text("No active tenant found for that shop.")
        return
    await update.message.reply_text(
        f"Remove tenant '{tenant['full_name']}' from shop {shop['shop_number']}? "
        "The shop will become vacant.",
        reply_markup=confirm_cancel(f"deltenantdo:{tenant['id']}", "cancel"),
    )


@admin_only
async def deltenant_confirm_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tenant_id = int(query.data.split(":")[1])
    tenant = tenant_service.get_tenant(tenant_id)
    await query.edit_message_text(
        f"Remove tenant '{tenant['full_name']}' from their shop? The shop will become vacant.",
        reply_markup=confirm_cancel(f"deltenantdo:{tenant_id}", "cancel"),
    )


@admin_only
async def deltenant_do(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tenant_id = int(query.data.split(":")[1])
    try:
        tenant_service.deactivate_tenant(tenant_id, update.effective_user.id)
        await query.edit_message_text("✅ Tenant removed. Shop marked vacant.")
    except TenantError as e:
        await query.edit_message_text(f"⚠️ {e}")
