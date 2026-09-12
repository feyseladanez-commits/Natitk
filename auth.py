"""
utils/auth.py
-------------
Authorization helpers. Only Telegram IDs listed in ADMIN_IDS (env config,
mirrored into the `admins` table) may access administrative commands.
Tenants may only ever see data belonging to their own shop.
"""

import functools
from telegram import Update
from telegram.ext import ContextTypes

from config import config
from database import get_connection


def is_admin(telegram_id: int) -> bool:
    if telegram_id in config.ADMIN_IDS:
        return True
    conn = get_connection()
    row = conn.execute(
        "SELECT 1 FROM admins WHERE telegram_id = ? AND active = 1", (telegram_id,)
    ).fetchone()
    return row is not None


def get_tenant_by_telegram_id(telegram_id: int):
    conn = get_connection()
    return conn.execute(
        "SELECT * FROM tenants WHERE telegram_id = ? AND active = 1", (telegram_id,)
    ).fetchone()


def admin_only(handler):
    """Decorator for command/callback handlers restricted to administrators."""

    @functools.wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if not user or not is_admin(user.id):
            if update.callback_query:
                await update.callback_query.answer(
                    "⛔ You are not authorized to use this function.", show_alert=True
                )
            elif update.message:
                await update.message.reply_text("⛔ You are not authorized to use this function.")
            return
        return await handler(update, context, *args, **kwargs)

    return wrapper


def mask_id_number(id_number: str) -> str:
    """Mask a national ID number for normal listings, e.g. '******789'."""
    if not id_number:
        return "N/A"
    digits = str(id_number)
    if len(digits) <= 3:
        return "*" * len(digits)
    return "*" * (len(digits) - 3) + digits[-3:]


def mask_phone(phone: str) -> str:
    """Mask a phone number for contexts where full number shouldn't show."""
    if not phone or len(phone) < 4:
        return "N/A"
    return phone[:4] + "X" * (len(phone) - 6) + phone[-2:]
