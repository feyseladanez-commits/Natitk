"""
handlers/tenant_payment.py
------------------------------
Tenant-side "💳 Make Payment" flow:
  1. Tenant selects the rent month to pay (unpaid/overdue/upcoming).
  2. Tenant attaches a payment receipt (photo or PDF).
  3. The bot attempts best-effort extraction of the reference number
     and amount (services.receipt_extraction). If confident, those
     values are used; otherwise the tenant is asked to type them, and
     the payment is always routed through submit_payment(), which
     NEVER marks anything VERIFIED automatically - an administrator
     must always explicitly VERIFY or REJECT (see admin_payments.py).
  4. Duplicate reference numbers are rejected immediately with a clear
     message, exactly as specified.
"""

import uuid
from datetime import date
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (ContextTypes, ConversationHandler, MessageHandler, filters,
                           CallbackQueryHandler, CommandHandler)

from config import config
from utils.auth import get_tenant_by_telegram_id
from utils.validators import validate_non_empty, validate_positive_number, ValidationError
from services import shop_service, rent_service, payment_service
from services.payment_service import PaymentError, DuplicateReferenceError
from services import receipt_extraction
from handlers.common import CANCEL_FALLBACKS

PAY_RECEIPT, PAY_REF, PAY_AMOUNT = range(60, 63)


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


async def pay_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tenant = await _require_tenant(update)
    if not tenant:
        return ConversationHandler.END
    shop = shop_service.get_shop(tenant["shop_id"])
    rows = rent_service.shop_rent_rows(shop["id"])
    payable = [r for r in rows if r["status"] in ("UNPAID", "OVERDUE", "UPCOMING")]
    if not payable:
        await query.edit_message_text(
            "You have no outstanding or upcoming rent months right now.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back:tenant_main")]]),
        )
        return ConversationHandler.END
    rows_kb = [[InlineKeyboardButton(f"{r['rent_month_key']} — {r['amount_due']:,.0f} {config.CURRENCY} ({r['status']})",
                                      callback_data=f"paymonth:{r['rent_month_key']}")] for r in payable]
    rows_kb.append([InlineKeyboardButton("⬅️ Back", callback_data="back:tenant_main")])
    await query.edit_message_text("Select the rent month you are paying:", reply_markup=InlineKeyboardMarkup(rows_kb))
    return ConversationHandler.END


async def paymonth_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tenant = await _require_tenant(update)
    if not tenant:
        return ConversationHandler.END
    month_key = query.data.split(":")[1]
    context.user_data["pay_month_key"] = month_key
    context.user_data["pay_shop_id"] = tenant["shop_id"]
    context.user_data["pay_tenant_id"] = tenant["id"]
    await query.edit_message_text(
        f"Rent month: {month_key}\n\n"
        "Attach your payment receipt (photo or PDF/document). "
        "If your banking app lets you forward the confirmation text, include it as the caption - "
        "this helps us verify your payment faster."
    )
    return PAY_RECEIPT


async def receipt_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo_or_doc = update.message.photo[-1] if update.message.photo else update.message.document
    if not photo_or_doc:
        await update.message.reply_text("Please attach a photo or a PDF/document of your receipt.")
        return PAY_RECEIPT

    file = await photo_or_doc.get_file()
    ext = ".jpg" if update.message.photo else (Path(update.message.document.file_name or "receipt").suffix or ".dat")
    filename = f"{uuid.uuid4().hex}{ext}"
    dest_path = config.RECEIPTS_DIR / filename
    await file.download_to_drive(custom_path=str(dest_path))

    caption = update.message.caption or ""
    text_result = receipt_extraction.extract_from_text(caption)
    file_result = receipt_extraction.extract_from_file(str(dest_path))
    result = receipt_extraction.combine(text_result, file_result)

    context.user_data["pay_receipt_path"] = str(dest_path)
    context.user_data["pay_receipt_file_id"] = photo_or_doc.file_id
    context.user_data["pay_extraction"] = result.to_json()

    if result.confident:
        context.user_data["pay_reference"] = result.reference
        context.user_data["pay_amount"] = result.amount
        return await _submit(update, context, confident=True)

    await update.message.reply_text(
        "We couldn't automatically read your payment details from that receipt.\n\n"
        "Please type the payment reference / transaction number exactly as shown on your receipt "
        "(e.g. FT123456789):"
    )
    return PAY_REF


async def ref_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        reference = validate_non_empty(update.message.text, "Reference")
    except ValidationError as e:
        await update.message.reply_text(f"⚠️ {e}")
        return PAY_REF
    context.user_data["pay_reference"] = reference
    await update.message.reply_text(f"Amount paid ({config.CURRENCY}):")
    return PAY_AMOUNT


async def amount_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = validate_positive_number(update.message.text, "Amount")
    except ValidationError as e:
        await update.message.reply_text(f"⚠️ {e}")
        return PAY_AMOUNT
    context.user_data["pay_amount"] = amount
    return await _submit(update, context, confident=False)


async def _submit(update: Update, context: ContextTypes.DEFAULT_TYPE, confident: bool):
    d = context.user_data
    message_target = update.message or update.callback_query.message
    try:
        result = payment_service.submit_payment(
            shop_id=d["pay_shop_id"],
            tenant_id=d["pay_tenant_id"],
            rent_month_key=d["pay_month_key"],
            amount=d["pay_amount"],
            reference=d["pay_reference"],
            payment_date_greg=date.today().isoformat(),
            receipt_file_path=d.get("pay_receipt_path"),
            telegram_file_id=d.get("pay_receipt_file_id"),
            extracted_data_json=d.get("pay_extraction"),
            submitted_by=update.effective_user.id,
            confident_extraction=confident,
        )
    except DuplicateReferenceError as e:
        await message_target.reply_text(
            f"❌ PAYMENT REJECTED\n\nThis payment reference has already been used.\n\n"
            f"Reference:\n{e.reference}\n\nPreviously recorded for:\nShop {e.existing_shop_number}\n\n"
            "Please check your receipt and try again with the correct reference, or contact the administrator."
        )
        context.user_data.clear()
        return ConversationHandler.END
    except PaymentError as e:
        await message_target.reply_text(f"⚠️ {e}")
        context.user_data.clear()
        return ConversationHandler.END

    status = result["status"]
    if status == "MANUAL_REVIEW":
        note = "🔍 Your payment has been submitted for manual review by the administrator."
    else:
        note = "🟡 Your payment has been submitted and is pending administrator verification."
    await message_target.reply_text(
        f"{note}\n\nRent Month: {d['pay_month_key']}\nAmount: {d['pay_amount']:,.0f} {config.CURRENCY}\n"
        f"Reference: {d['pay_reference']}\n\nYou'll be notified once it is reviewed."
    )

    # Notify admins that a new payment needs review.
    from config import config as cfg
    for admin_id in cfg.ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=(f"💳 New payment submitted for review.\n\nShop ID: {d['pay_shop_id']}\n"
                      f"Rent Month: {d['pay_month_key']}\nAmount: {d['pay_amount']:,.0f} {cfg.CURRENCY}\n"
                      f"Reference: {d['pay_reference']}\n\nUse the Payments menu to review it."),
            )
        except Exception:
            pass

    context.user_data.clear()
    return ConversationHandler.END


tenant_payment_conversation = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(pay_entry, pattern="^t:pay$"),
        CallbackQueryHandler(paymonth_chosen, pattern=r"^paymonth:"),
    ],
    states={
        PAY_RECEIPT: [MessageHandler(filters.PHOTO | filters.Document.ALL, receipt_received)],
        PAY_REF: [MessageHandler(filters.TEXT & ~filters.COMMAND, ref_received)],
        PAY_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, amount_received)],
    },
    fallbacks=CANCEL_FALLBACKS,
    per_message=False,
)
