"""
handlers/admin_reports.py
-----------------------------
/report - Daily / Monthly / Yearly / Custom period reports, with
CSV (always available) and Excel (openpyxl) export, displayed using
Ethiopian-calendar dates.
"""

from telegram import Update
from telegram.ext import (ContextTypes, ConversationHandler, MessageHandler, filters,
                           CommandHandler, CallbackQueryHandler)

from config import config
from utils.auth import admin_only
from services import report_service
from calendar_utils.ethiopian import gregorian_to_ethiopian
from datetime import date
from keyboards.keyboards import report_period_menu, report_export_menu
from handlers.common import CANCEL_FALLBACKS

CUSTOM_START, CUSTOM_END = range(40, 42)


def _format_report_text(report: dict) -> str:
    start_e = gregorian_to_ethiopian(date.fromisoformat(report["start"]))
    end_e = gregorian_to_ethiopian(date.fromisoformat(report["end"]))
    return (
        f"📄 {report['period'].title()} Report\n"
        f"{start_e.display()} → {end_e.display()}\n\n"
        f"Expected Rent: {report['expected']:,.0f} {config.CURRENCY}\n"
        f"Collected Rent: {report['collected']:,.0f} {config.CURRENCY}\n"
        f"Outstanding Rent: {report['outstanding']:,.0f} {config.CURRENCY}\n\n"
        f"Paid Shops: {report['paid_shops']}\n"
        f"Unpaid Shops: {report['unpaid_shops']}\n"
        f"Vacant Shops: {report['vacant_shops']}\n\n"
        f"Total Expenses: {report['expenses']:,.0f} {config.CURRENCY}\n"
        f"Net Income: {report['net_income']:,.0f} {config.CURRENCY}"
    )


@admin_only
async def show_reports_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.edit_message_text(
        "📄 REPORTS\n\nSelect a period:", reply_markup=report_period_menu()
    )


@admin_only
async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📄 REPORTS\n\nSelect a period:", reply_markup=report_period_menu())


@admin_only
async def report_period_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    period = query.data.split(":")[1]
    if period == "CUSTOM":
        await query.edit_message_text(
            "Enter the start date in Ethiopian calendar format (YYYY MM DD), e.g. 2018 1 1:"
        )
        return CUSTOM_START
    report = report_service.build_report(period)
    context.user_data["last_report"] = report
    await query.edit_message_text(
        _format_report_text(report),
        reply_markup=report_export_menu(report["period"], report["start"], report["end"]),
    )
    return ConversationHandler.END


async def custom_start_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from calendar_utils.ethiopian import parse_ethiopian_input, ethiopian_to_gregorian
    try:
        e_date = parse_ethiopian_input(update.message.text)
        g_date = ethiopian_to_gregorian(e_date)
    except ValueError as e:
        await update.message.reply_text(f"⚠️ {e}")
        return CUSTOM_START
    context.user_data["report_custom_start"] = g_date.isoformat()
    await update.message.reply_text("Enter the end date in Ethiopian calendar format (YYYY MM DD):")
    return CUSTOM_END


async def custom_end_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from calendar_utils.ethiopian import parse_ethiopian_input, ethiopian_to_gregorian
    try:
        e_date = parse_ethiopian_input(update.message.text)
        g_date = ethiopian_to_gregorian(e_date)
    except ValueError as e:
        await update.message.reply_text(f"⚠️ {e}")
        return CUSTOM_END
    start = context.user_data.pop("report_custom_start")
    end = g_date.isoformat()
    report = report_service.build_report("CUSTOM", custom_start=start, custom_end=end)
    context.user_data["last_report"] = report
    await update.message.reply_text(
        _format_report_text(report),
        reply_markup=report_export_menu(report["period"], report["start"], report["end"]),
    )
    return ConversationHandler.END


report_conversation = ConversationHandler(
    entry_points=[CallbackQueryHandler(report_period_chosen, pattern=r"^report:")],
    states={
        CUSTOM_START: [MessageHandler(filters.TEXT & ~filters.COMMAND, custom_start_received)],
        CUSTOM_END: [MessageHandler(filters.TEXT & ~filters.COMMAND, custom_end_received)],
    },
    fallbacks=CANCEL_FALLBACKS,
)


@admin_only
async def report_export_csv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, period, start, end = query.data.split(":")
    report = context.user_data.get("last_report") or report_service.build_report(
        period, custom_start=start, custom_end=end
    )
    path = report_service.export_report_csv(report)
    with open(path, "rb") as f:
        await context.bot.send_document(chat_id=update.effective_user.id, document=f)


@admin_only
async def report_export_excel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, period, start, end = query.data.split(":")
    report = context.user_data.get("last_report") or report_service.build_report(
        period, custom_start=start, custom_end=end
    )
    try:
        path = report_service.export_report_excel(report)
    except RuntimeError as e:
        await query.answer(str(e), show_alert=True)
        return
    with open(path, "rb") as f:
        await context.bot.send_document(chat_id=update.effective_user.id, document=f)
