"""
handlers/admin_misc.py
--------------------------
/search, /backup, /settings - the remaining top-level admin utilities.
"""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (ContextTypes, ConversationHandler, MessageHandler, filters,
                           CommandHandler, CallbackQueryHandler)

from config import config
from utils.auth import admin_only, mask_id_number
from services import search_service, backup_service, settings_service
from utils.validators import validate_positive_number, ValidationError
from handlers.common import CANCEL_FALLBACKS

SEARCH_QUERY = 50
SETTINGS_VALUE = 51


# ---------- /search ----------

@admin_only
async def show_search_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.edit_message_text(
        "🔍 SEARCH\n\nUse /search <term> to look up a shop number, tenant name, "
        "phone number, or payment reference."
    )


@admin_only
async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /search <shop number | tenant name | phone | reference>")
        return
    query_text = " ".join(context.args)
    await _run_search(update, query_text)


async def _run_search(update: Update, query_text: str):
    results = search_service.search_all(query_text)
    lines = [f"🔍 Search results for: {query_text}", ""]

    if results["shops"]:
        lines.append("Shops:")
        for s in results["shops"]:
            lines.append(f"  Shop {s['shop_number']} — {s['floor_name']} — {s['status'].title()}")
        lines.append("")

    if results["tenants"]:
        lines.append("Tenants:")
        for t in results["tenants"]:
            lines.append(f"  {t['full_name']} — Shop {t['shop_number']} — {t['phone']}")
        lines.append("")

    if results["payments"]:
        lines.append("Payments:")
        for p in results["payments"]:
            lines.append(
                f"  {p['reference']} — Shop {p['shop_number']} — {p['amount']:,.0f} {config.CURRENCY} — {p['status']}"
            )
        lines.append("")

    if not any(results.values()):
        lines.append("No matches found.")

    await update.message.reply_text("\n".join(lines))


# ---------- /backup ----------

@admin_only
async def show_backup_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    backups = backup_service.list_backups()
    text = f"💾 BACKUP\n\n{len(backups)} backup(s) on file.\n\nUse /backup to create a new one now."
    await update.callback_query.edit_message_text(text)


@admin_only
async def backup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Creating backup...")
    path = backup_service.create_backup()
    with open(path, "rb") as f:
        await update.message.reply_document(document=f, caption="✅ Database backup created.")


# ---------- /settings ----------

SETTINGS_LABELS = {
    "reminder_days_before": "Reminder days before due date",
    "rent_due_day": "Rent due day of month",
    "allow_multi_shop_tenant": "Allow one tenant to hold multiple shops (0/1)",
}


def _settings_menu():
    current = settings_service.all_settings()
    rows = []
    for key, label in SETTINGS_LABELS.items():
        rows.append([InlineKeyboardButton(f"{label}: {current.get(key)}", callback_data=f"setedit:{key}")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="back:main")])
    return InlineKeyboardMarkup(rows)


@admin_only
async def show_settings_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.edit_message_text("⚙️ SETTINGS\n\nTap a setting to change it:",
                                                    reply_markup=_settings_menu())


@admin_only
async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⚙️ SETTINGS\n\nTap a setting to change it:", reply_markup=_settings_menu())


async def setting_edit_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    key = query.data.split(":")[1]
    context.user_data["editing_setting"] = key
    await query.edit_message_text(f"Enter a new value for '{SETTINGS_LABELS.get(key, key)}':")
    return SETTINGS_VALUE


async def setting_value_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = context.user_data.get("editing_setting")
    value = update.message.text.strip()
    if key in ("reminder_days_before", "rent_due_day"):
        try:
            validate_positive_number(value, SETTINGS_LABELS.get(key, key))
        except ValidationError as e:
            await update.message.reply_text(f"⚠️ {e}")
            return SETTINGS_VALUE
    elif key == "allow_multi_shop_tenant" and value not in ("0", "1"):
        await update.message.reply_text("⚠️ Please enter 0 or 1.")
        return SETTINGS_VALUE

    settings_service.set_setting(key, value, update.effective_user.id)
    await update.message.reply_text(f"✅ '{SETTINGS_LABELS.get(key, key)}' updated to {value}.")
    context.user_data.pop("editing_setting", None)
    return ConversationHandler.END


settings_conversation = ConversationHandler(
    entry_points=[CallbackQueryHandler(setting_edit_start, pattern=r"^setedit:")],
    states={SETTINGS_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, setting_value_received)]},
    fallbacks=CANCEL_FALLBACKS,
)
