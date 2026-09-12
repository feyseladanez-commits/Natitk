"""
handlers/tenant_menu.py
---------------------------
Tenant self-service menu: My Shop, My Rent, Rent History, Receipts,
Building Notices, Contact Management.

A tenant may only ever see information belonging to their own shop -
every query here is scoped by the tenant's own telegram_id.
"""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import config
from utils.auth import get_tenant_by_telegram_id
from services import shop_service, rent_service, payment_service, announcement_service
from calendar_utils.ethiopian import gregorian_to_ethiopian
from datetime import date


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


async def my_shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tenant = await _require_tenant(update)
    if not tenant:
        return
    shop = shop_service.get_shop(tenant["shop_id"])
    outstanding = rent_service.shop_outstanding_amount(shop["id"])
    text = (
        f"🏪 Shop {shop['shop_number']}\n\n"
        f"📍 Floor: {shop['floor_name']}\n"
        f"📐 Size: {shop['size_sqm']:.0f} m²\n"
        f"💰 Monthly Rent: {shop['monthly_rent']:,.0f} {config.CURRENCY}\n"
        f"Outstanding: {outstanding:,.0f} {config.CURRENCY}\n"
        f"Contract: {tenant['contract_start']} → {tenant['contract_end'] or 'open-ended'}"
    )
    rows = [[InlineKeyboardButton("⬅️ Back", callback_data="back:tenant_main")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows))


async def my_rent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tenant = await _require_tenant(update)
    if not tenant:
        return
    shop = shop_service.get_shop(tenant["shop_id"])
    rows = rent_service.shop_rent_rows(shop["id"])
    lines = [f"Shop {shop['shop_number']} — Rent Status", ""]
    for r in rows[-6:]:
        year, month = r["rent_month_key"].split("-")
        lines.append(f"{year} {int(month)} — {r['amount_due']:,.0f} {config.CURRENCY} — {r['status']}")
    kb = [[InlineKeyboardButton("⬅️ Back", callback_data="back:tenant_main")]]
    await query.edit_message_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(kb))


async def rent_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tenant = await _require_tenant(update)
    if not tenant:
        return
    shop = shop_service.get_shop(tenant["shop_id"])
    payments = [p for p in payment_service.payment_history(shop["id"]) if p["status"] == "VERIFIED"]
    if not payments:
        text = "No verified payments on record yet."
    else:
        lines = [f"Shop {shop['shop_number']} — Payment History", ""]
        for p in payments:
            lines.append(f"{p['rent_month_key']} — {p['amount']:,.0f} {config.CURRENCY} — ✅ {p['reference']}")
        text = "\n".join(lines)
    kb = [[InlineKeyboardButton("⬅️ Back", callback_data="back:tenant_main")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))


async def my_receipts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tenant = await _require_tenant(update)
    if not tenant:
        return
    shop = shop_service.get_shop(tenant["shop_id"])
    payments = [p for p in payment_service.payment_history(shop["id"]) if p["status"] == "VERIFIED"]
    if not payments:
        await query.edit_message_text(
            "No receipts available yet.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back:tenant_main")]]),
        )
        return
    rows = [[InlineKeyboardButton(f"{p['rent_month_key']} — {p['amount']:,.0f} {config.CURRENCY}",
                                   callback_data=f"getreceipt:{p['id']}")] for p in payments]
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="back:tenant_main")])
    await query.edit_message_text("Select a payment to get its receipt:", reply_markup=InlineKeyboardMarkup(rows))


async def get_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    payment_id = int(query.data.split(":")[1])
    payment = payment_service.get_payment(payment_id)
    tenant = await _require_tenant(update)
    if not tenant or not payment or payment["shop_id"] != tenant["shop_id"]:
        await query.answer("Not authorized.", show_alert=True)
        return
    shop = shop_service.get_shop(payment["shop_id"])
    try:
        from services.receipt_pdf import generate_receipt_pdf
        path = generate_receipt_pdf(payment, shop, tenant)
        with open(path, "rb") as f:
            await context.bot.send_document(chat_id=update.effective_user.id, document=f)
    except Exception:
        await query.answer("Could not generate receipt right now.", show_alert=True)


async def notices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    anns = announcement_service.list_announcements(limit=5)
    if not anns:
        text = "No building notices yet."
    else:
        lines = ["📢 BUILDING NOTICES", ""]
        for a in anns:
            lines.append(a["message"])
            lines.append("")
        text = "\n".join(lines)
    kb = [[InlineKeyboardButton("⬅️ Back", callback_data="back:tenant_main")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))


async def contact_management(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = (
        "📞 Contact Building Management\n\n"
        "For urgent matters, please contact the building administrator directly.\n"
        "For maintenance issues, use 🛠 Report Maintenance from the main menu."
    )
    kb = [[InlineKeyboardButton("⬅️ Back", callback_data="back:tenant_main")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))
