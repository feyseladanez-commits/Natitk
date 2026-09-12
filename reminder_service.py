"""
services/reminder_service.py
-------------------------------
Automatic rent reminders, sent N days before the Ethiopian-calendar due
date (N is configurable by the administrator via /settings, see
services/settings_service.py). Intended to be invoked once a day by a
JobQueue job in bot.py.
"""

from datetime import date, timedelta

from database import get_connection
from config import config
from services import settings_service
from calendar_utils.ethiopian import gregorian_to_ethiopian, format_month_label


async def send_due_reminders(bot):
    """Send a reminder to every tenant whose rent due date is exactly
    `reminder_days_before` days away, so each tenant is reminded once
    per rent month rather than being messaged every single day."""
    days_before = settings_service.get_int("reminder_days_before")
    target_date = (date.today() + timedelta(days=days_before)).isoformat()

    conn = get_connection()
    rows = conn.execute(
        """SELECT r.*, s.shop_number, t.telegram_id, t.full_name
           FROM rent_records r
           JOIN shops s ON s.id = r.shop_id
           LEFT JOIN tenants t ON t.shop_id = s.id AND t.active = 1
           WHERE r.status IN ('UNPAID', 'UPCOMING') AND r.due_date_greg = ?""",
        (target_date,),
    ).fetchall()

    for row in rows:
        if not row["telegram_id"]:
            continue
        year, month = (int(x) for x in row["rent_month_key"].split("-"))
        label = format_month_label(year, month)
        due_e = gregorian_to_ethiopian(date.fromisoformat(row["due_date_greg"]))
        try:
            await bot.send_message(
                chat_id=row["telegram_id"],
                text=(
                    f"🔔 RENT REMINDER\n\n"
                    f"Shop {row['shop_number']}\n\n"
                    f"Your rent for {label} is due on:\n{due_e.display()}\n\n"
                    f"Amount:\n{row['amount_due']:,.0f} {config.CURRENCY}"
                ),
            )
        except Exception:
            continue


async def rollover_job(bot=None):
    """Refresh overdue statuses and pre-create upcoming rent months for
    every active tenant. Safe to run repeatedly (idempotent)."""
    from services import rent_service
    rent_service.extend_all_schedules()
