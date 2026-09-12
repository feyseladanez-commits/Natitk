"""
handlers/admin_expenses.py
------------------------------
/expenses - record building operating expenses (electricity, water,
cleaning, security, maintenance, other) used to compute net income.
"""

from datetime import date

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (ContextTypes, ConversationHandler, MessageHandler, filters,
                           CommandHandler, CallbackQueryHandler)

from config import config
from utils.auth import admin_only
from utils.validators import validate_positive_number, validate_non_empty, ValidationError
from services import expense_service
from handlers.common import CANCEL_FALLBACKS

(EXP_DESCRIPTION, EXP_AMOUNT, EXP_RECEIPT) = range(20, 23)

CATEGORY_LABELS = {
    "ELECTRICITY": "⚡ Electricity",
    "WATER": "🚰 Water",
    "CLEANING": "🧹 Cleaning",
    "SECURITY": "🛡 Security",
    "MAINTENANCE": "🛠 Maintenance",
    "OTHER": "❗ Other",
}


def _category_menu():
    rows = [[InlineKeyboardButton(label, callback_data=f"expensecat:{key}")]
            for key, label in CATEGORY_LABELS.items()]
    rows.append([InlineKeyboardButton("📋 Recent Expenses", callback_data="expenselist")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="back:main")])
    return InlineKeyboardMarkup(rows)


@admin_only
async def show_expenses_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total = expense_service.total_expenses()
    text = f"💸 EXPENSES\n\nTotal recorded: {total:,.0f} {config.CURRENCY}\n\nRecord a new expense:"
    await update.callback_query.edit_message_text(text, reply_markup=_category_menu())


@admin_only
async def expenses_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total = expense_service.total_expenses()
    await update.message.reply_text(
        f"💸 EXPENSES\n\nTotal recorded: {total:,.0f} {config.CURRENCY}\n\nRecord a new expense:",
        reply_markup=_category_menu(),
    )


@admin_only
async def expenses_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    rows = expense_service.list_expenses()[:15]
    if not rows:
        text = "No expenses recorded yet."
    else:
        lines = ["💸 RECENT EXPENSES", ""]
        for r in rows:
            lines.append(
                f"{r['expense_date_greg']} — {CATEGORY_LABELS.get(r['category'], r['category'])} — "
                f"{r['amount']:,.0f} {config.CURRENCY}"
            )
            if r["description"]:
                lines.append(f"  {r['description']}")
        text = "\n".join(lines)
    await query.edit_message_text(
        text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="menu:expenses")]])
    )


async def expensecat_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    category = query.data.split(":")[1]
    context.user_data["expense_category"] = category
    await query.edit_message_text(f"{CATEGORY_LABELS.get(category, category)}\n\nEnter a short description:")
    return EXP_DESCRIPTION


async def expense_description_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        desc = validate_non_empty(update.message.text, "Description")
    except ValidationError as e:
        await update.message.reply_text(f"⚠️ {e}")
        return EXP_DESCRIPTION
    context.user_data["expense_description"] = desc
    await update.message.reply_text(f"Amount ({config.CURRENCY}):")
    return EXP_AMOUNT


async def expense_amount_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = validate_positive_number(update.message.text, "Amount")
    except ValidationError as e:
        await update.message.reply_text(f"⚠️ {e}")
        return EXP_AMOUNT
    context.user_data["expense_amount"] = amount
    await update.message.reply_text(
        "Attach a receipt photo/document if you have one, or send /skip."
    )
    return EXP_RECEIPT


async def _finalize_expense(update: Update, context: ContextTypes.DEFAULT_TYPE, receipt_file_id=None):
    d = context.user_data
    expense_service.add_expense(
        category=d["expense_category"],
        description=d["expense_description"],
        amount=d["expense_amount"],
        expense_date_greg=date.today().isoformat(),
        receipt_file_id=receipt_file_id,
        notes=None,
        admin_id=update.effective_user.id,
    )
    await update.message.reply_text(
        f"✅ Expense recorded: {d['expense_description']} — {d['expense_amount']:,.0f} {config.CURRENCY}"
    )
    context.user_data.clear()


async def expense_receipt_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo_or_doc = update.message.photo[-1] if update.message.photo else update.message.document
    file_id = photo_or_doc.file_id if photo_or_doc else None
    await _finalize_expense(update, context, receipt_file_id=file_id)
    return ConversationHandler.END


async def expense_receipt_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _finalize_expense(update, context)
    return ConversationHandler.END


expense_conversation = ConversationHandler(
    entry_points=[CallbackQueryHandler(expensecat_chosen, pattern=r"^expensecat:")],
    states={
        EXP_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, expense_description_received)],
        EXP_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, expense_amount_received)],
        EXP_RECEIPT: [
            MessageHandler(filters.PHOTO | filters.Document.ALL, expense_receipt_received),
            CommandHandler("skip", expense_receipt_skip),
        ],
    },
    fallbacks=CANCEL_FALLBACKS,
)
