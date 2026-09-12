"""
bot.py
------
Main entry point for the Commercial Building Bot.

Run with:  python bot.py

This module only wires things together: it creates the Application,
registers every command / conversation / callback handler, schedules
the recurring background jobs (rent rollover + due-date reminders),
and starts polling. All business logic lives in services/, all
Telegram-facing logic lives in handlers/.
"""

import logging
import sys

from telegram import Update
from telegram.ext import (
    Application, ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    ContextTypes,
)

from config import config
from database import init_db

# ---------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------
from handlers import common
from handlers import admin_floors
from handlers import admin_shops
from handlers import admin_tenants
from handlers import admin_payments
from handlers import admin_status
from handlers import admin_maintenance
from handlers import admin_expenses
from handlers import admin_announcement
from handlers import admin_reports
from handlers import admin_misc
from handlers import tenant_menu
from handlers import tenant_payment
from handlers import tenant_maintenance

from services import reminder_service

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("commercial_building_bot")


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Unhandled exception while processing an update", exc_info=context.error)
    try:
        if isinstance(update, Update):
            if update.callback_query:
                await update.callback_query.answer(
                    "Something went wrong. Please try again.", show_alert=True
                )
            elif update.effective_message:
                await update.effective_message.reply_text(
                    "⚠️ Something went wrong processing that. Please try again, "
                    "or /cancel and start over."
                )
    except Exception:
        pass


async def _daily_rollover_job(context: ContextTypes.DEFAULT_TYPE):
    await reminder_service.rollover_job(context.bot)


async def _reminder_job(context: ContextTypes.DEFAULT_TYPE):
    await reminder_service.send_due_reminders(context.bot)


def build_application() -> Application:
    if not config.BOT_TOKEN:
        logger.error(
            "BOT_TOKEN is not set. Copy .env.example to .env and fill in your "
            "token from @BotFather before running the bot."
        )
        sys.exit(1)

    application = ApplicationBuilder().token(config.BOT_TOKEN).build()

    # ---------------- Command handlers (no conversation) ----------------
    application.add_handler(CommandHandler("start", common.start))
    application.add_handler(CommandHandler("admin", common.admin_command))
    application.add_handler(CommandHandler("cancel", common.cancel_conversation))

    application.add_handler(CommandHandler("floors", admin_floors.list_floors))

    application.add_handler(CommandHandler("shops", admin_shops.shops_command))
    application.add_handler(CommandHandler("shopinfo", admin_shops.shopinfo_command))
    application.add_handler(CommandHandler("deleteshop", admin_shops.deleteshop_command))

    application.add_handler(CommandHandler("tenantinfo", admin_tenants.tenantinfo_command))
    application.add_handler(CommandHandler("deletetenant", admin_tenants.deletetenant_command))

    application.add_handler(CommandHandler("status", admin_status.status_command))
    application.add_handler(CommandHandler("floorstatus", admin_status.floorstatus_command))
    application.add_handler(CommandHandler("shopstatus", admin_status.shopstatus_command))
    application.add_handler(CommandHandler("occupied", admin_status.occupied_command))
    application.add_handler(CommandHandler("vacant", admin_status.vacant_command))
    application.add_handler(CommandHandler("paid", admin_status.paid_command))
    application.add_handler(CommandHandler("unpaid", admin_status.unpaid_command))
    application.add_handler(CommandHandler("paymentstatus", admin_status.paymentstatus_command))
    application.add_handler(CommandHandler("rentstatus", admin_status.rentstatus_command))

    application.add_handler(CommandHandler("usedrefs", admin_payments.usedrefs_command))
    application.add_handler(CommandHandler("paymenthistory", admin_payments.paymenthistory_command))

    application.add_handler(CommandHandler("maintenance", admin_maintenance.maintenance_command))
    application.add_handler(CommandHandler("expenses", admin_expenses.expenses_command))
    application.add_handler(CommandHandler("report", admin_reports.report_command))
    application.add_handler(CommandHandler("search", admin_misc.search_command))
    application.add_handler(CommandHandler("backup", admin_misc.backup_command))
    application.add_handler(CommandHandler("settings", admin_misc.settings_command))

    # ---------------- Conversation handlers ----------------
    # (Each already includes CANCEL_FALLBACKS so both /cancel and the
    #  "❌ Cancel" inline button work at every step.)
    application.add_handler(admin_floors.addfloor_conversation)
    application.add_handler(admin_floors.editfloor_conversation)

    application.add_handler(admin_shops.addshop_conversation)
    application.add_handler(admin_shops.editshop_conversation)
    application.add_handler(admin_shops.bulkshops_conversation)

    application.add_handler(admin_tenants.addtenant_conversation)
    application.add_handler(admin_tenants.edittenant_conversation)

    application.add_handler(admin_payments.addpayment_conversation)
    application.add_handler(admin_payments.payment_reject_conversation)
    application.add_handler(admin_payments.payment_reverse_conversation)

    application.add_handler(admin_announcement.announcement_conversation)
    application.add_handler(admin_expenses.expense_conversation)
    application.add_handler(admin_reports.report_conversation)
    application.add_handler(admin_misc.settings_conversation)

    application.add_handler(tenant_payment.tenant_payment_conversation)
    application.add_handler(tenant_maintenance.tenant_maintenance_conversation)

    # ---------------- Top-level navigation callbacks ----------------
    application.add_handler(CallbackQueryHandler(common.menu_router, pattern=r"^menu:"))
    application.add_handler(CallbackQueryHandler(common.back_to_main, pattern=r"^back:main$"))
    application.add_handler(CallbackQueryHandler(common.back_to_tenant_main, pattern=r"^back:tenant_main$"))
    application.add_handler(CallbackQueryHandler(common.cancel_conversation, pattern=r"^cancel$"))

    # ---------------- Floors ----------------
    application.add_handler(CallbackQueryHandler(admin_floors.floors_list_callback, pattern=r"^floors:list$"))
    application.add_handler(CallbackQueryHandler(admin_floors.floor_delete, pattern=r"^floor:delete:\d+$"))

    # ---------------- Shops (browse / detail / pagination) ----------------
    application.add_handler(CallbackQueryHandler(admin_shops.shops_by_floor, pattern=r"^shopsfloor:\d+$"))
    application.add_handler(CallbackQueryHandler(admin_shops.shop_info_callback, pattern=r"^shopinfo:\d+$"))
    application.add_handler(CallbackQueryHandler(admin_shops.deleteshop_confirm, pattern=r"^deleteshopconfirm:\d+$"))
    application.add_handler(CallbackQueryHandler(admin_shops.bulkshops_confirm, pattern=r"^bulkconfirm$"))
    application.add_handler(
        CallbackQueryHandler(admin_shops.shops_page, pattern=r"^(shopinfo|tenantshop|histshop)page:\d+$")
    )

    # ---------------- Tenants ----------------
    application.add_handler(CallbackQueryHandler(admin_tenants.tenants_by_floor, pattern=r"^tenantsfloor:\d+$"))
    application.add_handler(CallbackQueryHandler(admin_tenants.tenant_view_by_shop, pattern=r"^tenantshop:\d+$"))
    application.add_handler(CallbackQueryHandler(admin_tenants.tenant_view_callback, pattern=r"^tenantview:\d+$"))
    application.add_handler(CallbackQueryHandler(admin_tenants.view_document, pattern=r"^viewdoc:\d+$"))
    application.add_handler(CallbackQueryHandler(admin_tenants.deltenant_confirm_prompt, pattern=r"^deltenant:\d+$"))
    application.add_handler(CallbackQueryHandler(admin_tenants.deltenant_do, pattern=r"^deltenantdo:\d+$"))

    # ---------------- Payments ----------------
    application.add_handler(CallbackQueryHandler(admin_payments.payment_review_open, pattern=r"^payreview:\d+$"))
    application.add_handler(CallbackQueryHandler(admin_payments.payment_verify, pattern=r"^payverify:\d+$"))
    application.add_handler(
        CallbackQueryHandler(admin_payments.payment_request_new_receipt, pattern=r"^payrenew:\d+$")
    )
    application.add_handler(CallbackQueryHandler(admin_payments.paymenthistory_floor, pattern=r"^histfloor:\d+$"))
    application.add_handler(CallbackQueryHandler(admin_payments.paymenthistory_shop, pattern=r"^histshop:\d+$"))
    application.add_handler(CallbackQueryHandler(admin_payments.usedrefs_callback, pattern=r"^usedrefs:0$"))

    # ---------------- Status / rent ----------------
    application.add_handler(CallbackQueryHandler(admin_status.status_floor_detail, pattern=r"^statusfloor:\d+$"))
    application.add_handler(CallbackQueryHandler(admin_status.remind_shop_callback, pattern=r"^remind:\d+$"))

    # ---------------- Maintenance ----------------
    application.add_handler(CallbackQueryHandler(admin_maintenance.maintenance_list_callback, pattern=r"^maintlist:"))
    application.add_handler(CallbackQueryHandler(admin_maintenance.maintenance_view_callback, pattern=r"^maintview:\d+$"))
    application.add_handler(
        CallbackQueryHandler(admin_maintenance.maintenance_status_change, pattern=r"^maintstatus:\d+:\w+$")
    )

    # ---------------- Expenses ----------------
    application.add_handler(CallbackQueryHandler(admin_expenses.expenses_list_callback, pattern=r"^expenselist$"))

    # ---------------- Announcements ----------------
    application.add_handler(CallbackQueryHandler(admin_announcement.announcement_confirm, pattern=r"^announceconfirm$"))

    # ---------------- Reports ----------------
    application.add_handler(CallbackQueryHandler(admin_reports.report_export_csv, pattern=r"^reportcsv:"))
    application.add_handler(CallbackQueryHandler(admin_reports.report_export_excel, pattern=r"^reportxlsx:"))

    # ---------------- Tenant self-service menu ----------------
    application.add_handler(CallbackQueryHandler(tenant_menu.my_shop, pattern=r"^t:myshop$"))
    application.add_handler(CallbackQueryHandler(tenant_menu.my_rent, pattern=r"^t:myrent$"))
    application.add_handler(CallbackQueryHandler(tenant_menu.rent_history, pattern=r"^t:history$"))
    application.add_handler(CallbackQueryHandler(tenant_menu.my_receipts, pattern=r"^t:receipts$"))
    application.add_handler(CallbackQueryHandler(tenant_menu.get_receipt, pattern=r"^getreceipt:\d+$"))
    application.add_handler(CallbackQueryHandler(tenant_menu.notices, pattern=r"^t:notices$"))
    application.add_handler(CallbackQueryHandler(tenant_menu.contact_management, pattern=r"^t:contact$"))

    application.add_error_handler(on_error)

    # ---------------- Scheduled jobs ----------------
    if application.job_queue is not None:
        # Keep rent schedules & overdue statuses fresh every 6 hours (and once at startup).
        application.job_queue.run_repeating(_daily_rollover_job, interval=6 * 3600, first=10)
        # Check for due-date reminders once a day.
        application.job_queue.run_repeating(_reminder_job, interval=24 * 3600, first=30)
    else:
        logger.warning(
            "JobQueue is not available (install the 'job-queue' extra: "
            "pip install \"python-telegram-bot[job-queue]\"). "
            "Automatic rollover and rent reminders will not run."
        )

    return application


def main():
    init_db()
    application = build_application()
    logger.info("%s bot starting (polling)...", config.BUILDING_NAME)
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
