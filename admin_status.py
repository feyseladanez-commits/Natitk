"""
handlers/admin_status.py
----------------------------
/status, /floorstatus, /shopstatus, /occupied, /vacant, /paid, /unpaid,
/paymentstatus, /rentstatus
"""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler

from config import config
from utils.auth import admin_only
from services import shop_service, floor_service, rent_service
from keyboards.keyboards import floors_menu


@admin_only
async def show_status_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await render_building_status(update, context)


@admin_only
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await render_building_status(update, context)


async def render_building_status(update, context):
    counts = shop_service.counts_summary()
    rent = rent_service.building_rent_status()
    overdue_count = 0
    conn_rows = rent_service.unpaid_shops()
    # unpaid_shops() already filters UNPAID/OVERDUE; split for display
    overdue_count = sum(1 for r in conn_rows if r["status"] == "OVERDUE")
    due_count = sum(1 for r in conn_rows if r["status"] == "UNPAID")

    text = (
        "🏢 BUILDING STATUS\n\n"
        f"Total Shops: {counts['total']}\n"
        f"🟢 Occupied: {counts['occupied']}\n"
        f"⚪ Vacant: {counts['vacant']}\n"
        f"✅ Paid: {rent['paid_shops']}\n"
        f"⚠️ Payment Due: {due_count}\n"
        f"🔴 Overdue: {overdue_count}"
    )
    floors = floor_service.list_floors()
    markup = floors_menu(floors, prefix="statusfloor", extra_back="back:main") if floors else None
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=markup)
    else:
        await update.message.reply_text(text, reply_markup=markup)


@admin_only
async def status_floor_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    floor_id = int(query.data.split(":")[1])
    floor = floor_service.get_floor(floor_id)
    shops = shop_service.list_shops(floor_id)
    current_key_shops = rent_service.unpaid_shops()
    unpaid_ids = {r["id"] for r in current_key_shops}

    lines = [floor["name"].upper(), ""]
    for s in shops:
        if s["status"] == "VACANT":
            dot = "⚪"
        elif s["id"] in unpaid_ids:
            dot = "🔴"
        else:
            dot = "🟢"
        lines.append(f"{dot} Shop {s['shop_number']} — {s['size_sqm']:.0f} m²")
    if not shops:
        lines.append("No shops on this floor.")

    rows = [[InlineKeyboardButton("⬅️ Back", callback_data="menu:status")]]
    await query.edit_message_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(rows))


@admin_only
async def floorstatus_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    floors = floor_service.list_floors()
    if not floors:
        await update.message.reply_text("No floors registered yet.")
        return
    blocks = []
    for f in floors:
        fs = rent_service.floor_status(f["id"])
        blocks.append(
            f"{f['name'].upper()}\n"
            f"Total shops: {fs['total']}\n"
            f"Occupied: {fs['occupied']}\n"
            f"Vacant: {fs['vacant']}\n"
            f"Paid: {fs['paid']}\n"
            f"Unpaid: {fs['unpaid']}"
        )
    await update.message.reply_text("\n\n".join(blocks))


@admin_only
async def shopstatus_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /shopstatus <shop_number>")
        return
    shop = shop_service.get_shop_by_number(context.args[0])
    if not shop:
        await update.message.reply_text("Shop not found.")
        return
    rows = rent_service.shop_rent_rows(shop["id"])
    lines = [f"Shop {shop['shop_number']} — Rent Status", ""]
    for r in rows:
        status_label = {"PAID": "PAID", "UNPAID": "UNPAID", "OVERDUE": "OVERDUE",
                         "UPCOMING": "UPCOMING"}[r["status"]]
        year, month = r["rent_month_key"].split("-")
        lines.append(f"{year} {int(month)} — {r['amount_due']:,.0f} ETB — {status_label}")
    await update.message.reply_text("\n".join(lines))


@admin_only
async def occupied_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    shops = rent_service.occupied_shops()
    if not shops:
        await update.message.reply_text("No occupied shops.")
        return
    lines = ["🟢 OCCUPIED SHOPS", ""]
    for s in shops:
        lines.append(f"Shop {s['shop_number']} — {s['tenant_name'] or 'N/A'} — "
                      f"{s['monthly_rent']:,.0f} ETB/month")
    await update.message.reply_text("\n".join(lines))


@admin_only
async def vacant_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    shops = rent_service.vacant_shops()
    if not shops:
        await update.message.reply_text("No vacant shops.")
        return
    lines = ["⚪ VACANT SHOPS", ""]
    for s in shops:
        lines.append(f"Shop {s['shop_number']} — {s['size_sqm']:.0f} m²")
    await update.message.reply_text("\n".join(lines))


@admin_only
async def paid_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    shops = rent_service.paid_shops()
    if not shops:
        await update.message.reply_text("No shops have paid this month yet.")
        return
    lines = ["✅ PAID SHOPS (current month)", ""]
    for s in shops:
        lines.append(f"Shop {s['shop_number']}")
    await update.message.reply_text("\n".join(lines))


@admin_only
async def unpaid_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = rent_service.unpaid_shops()
    if not rows:
        await update.message.reply_text("No unpaid shops this month. 🎉")
        return
    lines = ["🔴 UNPAID RENT", ""]
    total = 0
    rows_by_shop = {}
    for r in rows:
        rows_by_shop.setdefault(r["shop_number"], 0)
        rows_by_shop[r["shop_number"]] += r["amount_due"]
        total += r["amount_due"]
    for shop_number, amount in rows_by_shop.items():
        lines.append(f"Shop {shop_number} — {amount:,.0f} ETB")
    lines.append("")
    lines.append(f"Total outstanding:\n{total:,.0f} ETB")

    rows_kb = [[InlineKeyboardButton(f"🔔 Remind Shop {r['shop_number']}",
                                      callback_data=f"remind:{r['id']}")] for r in rows[:10]]
    await update.message.reply_text("\n".join(lines),
                                     reply_markup=InlineKeyboardMarkup(rows_kb) if rows_kb else None)


@admin_only
async def paymentstatus_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await rentstatus_command(update, context)


@admin_only
async def rentstatus_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    r = rent_service.building_rent_status()
    text = (
        "🏢 BUILDING RENT STATUS\n\n"
        f"Expected: {r['expected']:,.0f} {config.CURRENCY}\n"
        f"Collected: {r['collected']:,.0f} {config.CURRENCY}\n"
        f"Outstanding: {r['outstanding']:,.0f} {config.CURRENCY}\n\n"
        f"Paid: {r['paid_shops']} shops\n"
        f"Unpaid: {r['unpaid_shops']} shops\n"
        f"Vacant: {r['vacant_shops']} shops"
    )
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back:main")]])
        )
    else:
        await update.message.reply_text(text)


@admin_only
async def show_rent_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await rentstatus_command(update, context)


@admin_only
async def remind_shop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    rent_record_id = int(query.data.split(":")[1])
    from database import get_connection
    conn = get_connection()
    row = conn.execute(
        """SELECT r.*, s.shop_number, t.telegram_id FROM rent_records r
           JOIN shops s ON s.id = r.shop_id
           LEFT JOIN tenants t ON t.shop_id = s.id AND t.active = 1
           WHERE r.id = ?""",
        (rent_record_id,),
    ).fetchone()
    if not row:
        await query.answer("Record not found.", show_alert=True)
        return
    if not row["telegram_id"]:
        await query.answer("Tenant has not linked their Telegram account yet.", show_alert=True)
        return
    from calendar_utils.ethiopian import format_month_label
    year, month = (int(x) for x in row["rent_month_key"].split("-"))
    label = format_month_label(year, month)
    try:
        await context.bot.send_message(
            chat_id=row["telegram_id"],
            text=(f"🔔 RENT REMINDER\n\nShop {row['shop_number']}\n\n"
                  f"Your rent for {label} is {'overdue' if row['status']=='OVERDUE' else 'due'}.\n\n"
                  f"Amount: {row['amount_due']:,.0f} {config.CURRENCY}"),
        )
        await query.answer("Reminder sent.")
    except Exception:
        await query.answer("Could not send reminder (tenant may have blocked the bot).", show_alert=True)
