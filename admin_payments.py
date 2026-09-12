"""
handlers/admin_payments.py
-----------------------------
Admin-side payment review queue, /paymenthistory, /usedrefs,
/addpayment (manual/cash entry), verify/reject/reverse actions,
and receipt generation + tenant notification on verification.
"""

from datetime import date

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (ContextTypes, ConversationHandler, MessageHandler, filters,
                           CommandHandler, CallbackQueryHandler)

from config import config
from utils.auth import admin_only
from utils.validators import validate_positive_number, ValidationError
from calendar_utils.ethiopian import gregorian_to_ethiopian, today_ethiopian
from services import payment_service, shop_service, tenant_service, floor_service, rent_service
from services.payment_service import PaymentError, DuplicateReferenceError
from services.audit import log_action
from handlers.common import CANCEL_FALLBACKS
from keyboards.keyboards import (payment_review_actions, floors_menu, shops_list_menu,
                                  confirm_cancel)

(ADDPAY_SHOP, ADDPAY_MONTH, ADDPAY_AMOUNT, ADDPAY_REF) = range(4)
(REJECT_REASON,) = (10,)
(REVERSE_REASON,) = (11,)


@admin_only
async def show_payments_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pending = payment_service.pending_payments()
    if not pending:
        text = "💳 PAYMENTS\n\nNo payments awaiting review."
        rows = [[InlineKeyboardButton("🔍 Used References", callback_data="usedrefs:0")],
                [InlineKeyboardButton("⬅️ Back", callback_data="back:main")]]
    else:
        text = f"💳 PAYMENTS\n\n{len(pending)} awaiting review:"
        rows = [[InlineKeyboardButton(f"Shop {p['shop_number']} — {p['amount']:,.0f} ETB — {p['status']}",
                                       callback_data=f"payreview:{p['id']}")] for p in pending[:15]]
        rows.append([InlineKeyboardButton("🔍 Used References", callback_data="usedrefs:0")])
        rows.append([InlineKeyboardButton("⬅️ Back", callback_data="back:main")])
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows))


def _format_payment_review(p, shop, tenant) -> str:
    return (
        f"🟡 PAYMENT REVIEW\n\n"
        f"Shop: {shop['shop_number']}\n"
        f"Tenant: {tenant['full_name'] if tenant else 'N/A'}\n"
        f"Rent Month: {p['rent_month_key']}\n"
        f"Amount: {p['amount']:,.0f} {config.CURRENCY}\n"
        f"Reference: {p['reference']}\n"
        f"Status: {p['status']}\n"
    )


@admin_only
async def payment_review_open(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    payment_id = int(query.data.split(":")[1])
    payment = payment_service.get_payment(payment_id)
    if not payment:
        await query.edit_message_text("Payment not found.")
        return
    shop = shop_service.get_shop(payment["shop_id"])
    tenant = tenant_service.get_tenant(payment["tenant_id"]) if payment["tenant_id"] else None
    text = _format_payment_review(payment, shop, tenant)

    if payment["receipt_file_path"] or payment["telegram_file_id"]:
        try:
            if payment["telegram_file_id"]:
                await context.bot.send_photo(chat_id=update.effective_user.id,
                                              photo=payment["telegram_file_id"], caption="Attached receipt")
        except Exception:
            pass

    await query.edit_message_text(text, reply_markup=payment_review_actions(payment_id))


@admin_only
async def payment_verify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    payment_id = int(query.data.split(":")[1])
    try:
        payment = payment_service.verify_payment(payment_id, update.effective_user.id)
    except PaymentError as e:
        await query.edit_message_text(f"⚠️ {e}")
        return

    shop = shop_service.get_shop(payment["shop_id"])
    tenant = tenant_service.get_tenant(payment["tenant_id"]) if payment["tenant_id"] else None

    receipt_path = None
    try:
        from services.receipt_pdf import generate_receipt_pdf
        receipt_path = generate_receipt_pdf(payment, shop, tenant)
    except Exception:
        receipt_path = None

    await query.edit_message_text(
        f"✅ Payment VERIFIED for Shop {shop['shop_number']} ({payment['amount']:,.0f} {config.CURRENCY})."
    )

    if tenant and tenant["telegram_id"]:
        try:
            if receipt_path:
                with open(receipt_path, "rb") as f:
                    await context.bot.send_document(
                        chat_id=tenant["telegram_id"], document=f,
                        caption=f"✅ Your payment for {payment['rent_month_key']} has been verified. "
                                f"Receipt attached.",
                    )
            else:
                await context.bot.send_message(
                    chat_id=tenant["telegram_id"],
                    text=f"✅ Your payment for {payment['rent_month_key']} has been verified.",
                )
        except Exception:
            pass


@admin_only
async def payment_reject_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    payment_id = int(query.data.split(":")[1])
    context.user_data["reject_payment_id"] = payment_id
    await query.edit_message_text("Enter a short reason for rejecting this payment:")
    return REJECT_REASON


async def payment_reject_reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    payment_id = context.user_data.get("reject_payment_id")
    reason = update.message.text.strip()
    try:
        payment = payment_service.reject_payment(payment_id, update.effective_user.id, reason)
    except PaymentError as e:
        await update.message.reply_text(f"⚠️ {e}")
        return ConversationHandler.END

    await update.message.reply_text("❌ Payment rejected.")
    tenant = tenant_service.get_tenant(payment["tenant_id"]) if payment["tenant_id"] else None
    if tenant and tenant["telegram_id"]:
        try:
            await context.bot.send_message(
                chat_id=tenant["telegram_id"],
                text=(f"❌ PAYMENT REJECTED\n\nReference: {payment['reference']}\n"
                      f"Reason: {reason}\n\nPlease submit a corrected receipt."),
            )
        except Exception:
            pass
    context.user_data.clear()
    return ConversationHandler.END


payment_reject_conversation = ConversationHandler(
    entry_points=[CallbackQueryHandler(payment_reject_start, pattern=r"^payreject:\d+$")],
    states={REJECT_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, payment_reject_reason)]},
    fallbacks=CANCEL_FALLBACKS,
)


@admin_only
async def payment_request_new_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    payment_id = int(query.data.split(":")[1])
    payment = payment_service.get_payment(payment_id)
    tenant = tenant_service.get_tenant(payment["tenant_id"]) if payment["tenant_id"] else None
    if tenant and tenant["telegram_id"]:
        try:
            await context.bot.send_message(
                chat_id=tenant["telegram_id"],
                text="🔁 Please resend a clearer copy of your payment receipt for "
                     f"{payment['rent_month_key']} using 💳 Make Payment.",
            )
            await query.answer("Tenant notified.")
        except Exception:
            await query.answer("Could not notify tenant.", show_alert=True)
    else:
        await query.answer("Tenant is not linked to Telegram.", show_alert=True)


@admin_only
async def payment_reverse_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    payment_id = int(query.data.split(":")[1])
    context.user_data["reverse_payment_id"] = payment_id
    await query.edit_message_text("Enter reason for reversing this VERIFIED payment:")
    return REVERSE_REASON


async def payment_reverse_reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    payment_id = context.user_data.get("reverse_payment_id")
    reason = update.message.text.strip()
    try:
        payment_service.reverse_payment(payment_id, update.effective_user.id, reason, release_reference=False)
    except PaymentError as e:
        await update.message.reply_text(f"⚠️ {e}")
        return ConversationHandler.END
    await update.message.reply_text(
        "↩️ Payment reversed. The rent month is marked UNPAID again. "
        "The reference remains locked; use an explicit release action if it must be reused."
    )
    context.user_data.clear()
    return ConversationHandler.END


payment_reverse_conversation = ConversationHandler(
    entry_points=[CallbackQueryHandler(payment_reverse_start, pattern=r"^payreverse:\d+$")],
    states={REVERSE_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, payment_reverse_reason)]},
    fallbacks=CANCEL_FALLBACKS,
)


# ---------- /paymenthistory ----------

@admin_only
async def paymenthistory_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    floors = floor_service.list_floors()
    if not floors:
        await update.message.reply_text("No floors registered yet.")
        return
    await update.message.reply_text("Select a floor:", reply_markup=floors_menu(floors, prefix="histfloor"))


@admin_only
async def paymenthistory_floor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    floor_id = int(query.data.split(":")[1])
    shops = shop_service.list_shops(floor_id)
    context.user_data["shops_page_list"] = [s["id"] for s in shops]
    context.user_data["shops_page_prefix"] = "histshop"
    context.user_data["shops_page_back"] = "menu:payments"
    await query.edit_message_text(
        "Select a shop:", reply_markup=shops_list_menu(shops, page=0, prefix="histshop", back_cb="menu:payments")
    )


@admin_only
async def paymenthistory_shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    shop_id = int(query.data.split(":")[1])
    shop = shop_service.get_shop(shop_id)
    rent_rows = {r["rent_month_key"]: r for r in rent_service.shop_rent_rows(shop_id)}
    payments = {p["rent_month_key"]: p for p in payment_service.payment_history(shop_id)
                if p["status"] == "VERIFIED"}

    lines = [f"SHOP {shop['shop_number']} — PAYMENT HISTORY", ""]
    for month_key in sorted(rent_rows.keys()):
        r = rent_rows[month_key]
        year, month = month_key.split("-")
        lines.append(f"{year} {int(month)}")
        lines.append(f"{r['amount_due']:,.0f} ETB")
        if month_key in payments:
            p = payments[month_key]
            lines.append(f"✅ Verified")
            lines.append(f"{p['reference']}")
        elif r["status"] == "UPCOMING":
            lines.append("⏳ Upcoming")
        else:
            lines.append(f"❌ {r['status'].title()}")
        lines.append("")

    await query.edit_message_text("\n".join(lines))


# ---------- /usedrefs ----------

@admin_only
async def usedrefs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query_text = " ".join(context.args) if context.args else None
    rows = payment_service.used_references(query_text)
    await _render_usedrefs(update, rows)


@admin_only
async def usedrefs_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    rows = payment_service.used_references()
    await _render_usedrefs(update, rows, is_callback=True)


async def _render_usedrefs(update, rows, is_callback=False):
    if not rows:
        text = "No payment references recorded yet."
    else:
        lines = []
        for r in rows[:25]:
            lines.append(
                f"{r['reference']}\nShop {r['shop_number']}\n{r['amount']:,.0f} ETB\n"
                f"{r['rent_month_key']}\n{r['status']}\n"
            )
        text = "\n".join(lines)
    if is_callback:
        await update.callback_query.edit_message_text(
            text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="menu:payments")]])
        )
    else:
        await update.message.reply_text(text)


# ---------- /addpayment : admin records a payment manually (e.g. cash) ----------

@admin_only
async def addpayment_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    floors = floor_service.list_floors()
    if not floors:
        await update.message.reply_text("No floors/shops exist yet.")
        return ConversationHandler.END
    await update.message.reply_text("Select a floor:", reply_markup=floors_menu(floors, prefix="addpayfloor", extra_back="cancel"))
    return ADDPAY_SHOP


async def addpayment_floor_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    floor_id = int(query.data.split(":")[1])
    shops = shop_service.list_shops(floor_id)
    occupied = [s for s in shops if s["status"] == "OCCUPIED"]
    context.user_data["shops_page_list"] = [s["id"] for s in occupied]
    context.user_data["shops_page_prefix"] = "addpayshop"
    context.user_data["shops_page_back"] = "cancel"
    await query.edit_message_text("Select a shop:", reply_markup=shops_list_menu(occupied, page=0, prefix="addpayshop", back_cb="cancel"))
    return ADDPAY_SHOP


async def addpayment_shop_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Pagination within the /addpayment shop picker (only needed if an
    occupied floor has more than one page of shops)."""
    from handlers.admin_shops import shops_page
    await shops_page(update, context)
    return ADDPAY_SHOP


async def addpayment_shop_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    shop_id = int(query.data.split(":")[1])
    context.user_data["addpay_shop_id"] = shop_id
    rows = rent_service.shop_rent_rows(shop_id)
    unpaid = [r for r in rows if r["status"] in ("UNPAID", "OVERDUE", "UPCOMING")]
    if not unpaid:
        await query.edit_message_text("No unpaid/upcoming rent months for this shop.")
        return ConversationHandler.END
    kb_rows = [[InlineKeyboardButton(f"{r['rent_month_key']} ({r['status']})",
                                      callback_data=f"addpaymonth:{r['rent_month_key']}")] for r in unpaid]
    await query.edit_message_text("Select rent month:", reply_markup=InlineKeyboardMarkup(kb_rows))
    return ADDPAY_MONTH


async def addpayment_month_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    month_key = query.data.split(":")[1]
    context.user_data["addpay_month"] = month_key
    await query.edit_message_text("Enter amount paid (ETB):")
    return ADDPAY_AMOUNT


async def addpayment_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = validate_positive_number(update.message.text, "Amount")
    except ValidationError as e:
        await update.message.reply_text(f"⚠️ {e}")
        return ADDPAY_AMOUNT
    context.user_data["addpay_amount"] = amount
    await update.message.reply_text("Enter a unique payment reference (e.g. CASH-<date>-<shop>, or bank ref):")
    return ADDPAY_REF


async def addpayment_reference(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reference = update.message.text.strip()
    d = context.user_data
    shop_id = d["addpay_shop_id"]
    tenant = tenant_service.get_active_tenant_for_shop(shop_id)
    try:
        result = payment_service.submit_payment(
            shop_id=shop_id,
            tenant_id=tenant["id"] if tenant else None,
            rent_month_key=d["addpay_month"],
            amount=d["addpay_amount"],
            reference=reference,
            payment_date_greg=date.today().isoformat(),
            receipt_file_path=None,
            telegram_file_id=None,
            extracted_data_json=None,
            submitted_by=update.effective_user.id,
            confident_extraction=True,  # admin-entered manually; still requires explicit VERIFY below
        )
    except DuplicateReferenceError as e:
        await update.message.reply_text(
            f"❌ PAYMENT REJECTED\n\nThis payment reference has already been used.\n\n"
            f"Reference:\n{e.reference}\n\nPreviously recorded for:\nShop {e.existing_shop_number}"
        )
        context.user_data.clear()
        return ConversationHandler.END
    except PaymentError as e:
        await update.message.reply_text(f"⚠️ {e}")
        context.user_data.clear()
        return ConversationHandler.END

    payment_id = result["payment_id"]
    await update.message.reply_text(
        "Payment recorded and pending verification.",
        reply_markup=payment_review_actions(payment_id),
    )
    context.user_data.clear()
    return ConversationHandler.END


addpayment_conversation = ConversationHandler(
    entry_points=[CommandHandler("addpayment", addpayment_start)],
    states={
        ADDPAY_SHOP: [
            CallbackQueryHandler(addpayment_floor_chosen, pattern=r"^addpayfloor:\d+$"),
            CallbackQueryHandler(addpayment_shop_chosen, pattern=r"^addpayshop:\d+$"),
            CallbackQueryHandler(addpayment_shop_page, pattern=r"^addpayshoppage:\d+$"),
        ],
        ADDPAY_MONTH: [CallbackQueryHandler(addpayment_month_chosen, pattern=r"^addpaymonth:")],
        ADDPAY_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, addpayment_amount)],
        ADDPAY_REF: [MessageHandler(filters.TEXT & ~filters.COMMAND, addpayment_reference)],
    },
    fallbacks=CANCEL_FALLBACKS,
)
