"""
services/report_service.py
-----------------------------
Builds Daily / Monthly / Yearly / Custom period reports and exports
them to CSV (always available) and Excel (if openpyxl is installed).
"""

import csv
from datetime import date, timedelta
from pathlib import Path

from database import get_connection
from calendar_utils.ethiopian import gregorian_to_ethiopian, today_ethiopian
from services import expense_service
from config import config


def _period_bounds(period: str, custom_start: str = None, custom_end: str = None):
    today = date.today()
    if period == "DAILY":
        return today.isoformat(), today.isoformat()
    if period == "MONTHLY":
        e_today = gregorian_to_ethiopian(today)
        start = today.replace(day=1)
        return start.isoformat(), today.isoformat()
    if period == "YEARLY":
        start = today - timedelta(days=365)
        return start.isoformat(), today.isoformat()
    if period == "CUSTOM":
        if not (custom_start and custom_end):
            raise ValueError("Custom period requires start and end dates.")
        return custom_start, custom_end
    raise ValueError(f"Unknown period: {period}")


def build_report(period: str, custom_start: str = None, custom_end: str = None) -> dict:
    start, end = _period_bounds(period, custom_start, custom_end)
    conn = get_connection()

    payments_rows = conn.execute(
        """SELECT p.*, s.shop_number FROM payments p
           JOIN shops s ON s.id = p.shop_id
           WHERE p.status = 'VERIFIED' AND p.payment_date_greg BETWEEN ? AND ?
           ORDER BY p.payment_date_greg""",
        (start, end),
    ).fetchall()

    collected = sum(r["amount"] for r in payments_rows)

    shops = conn.execute("SELECT * FROM shops").fetchall()
    expected = sum(s["monthly_rent"] for s in shops if s["status"] == "OCCUPIED")

    outstanding_rows = conn.execute(
        "SELECT COALESCE(SUM(amount_due),0) AS t FROM rent_records WHERE status IN ('UNPAID','OVERDUE')"
    ).fetchone()
    outstanding = outstanding_rows["t"]

    paid_shop_ids = {r["shop_id"] for r in payments_rows}
    unpaid_count = sum(
        1 for s in shops if s["status"] == "OCCUPIED" and s["id"] not in paid_shop_ids
    )
    vacant_count = sum(1 for s in shops if s["status"] == "VACANT")

    expenses_total = expense_service.total_expenses(start, end)
    net_income = collected - expenses_total

    return {
        "period": period,
        "start": start,
        "end": end,
        "expected": expected,
        "collected": collected,
        "outstanding": outstanding,
        "paid_shops": len(paid_shop_ids),
        "unpaid_shops": unpaid_count,
        "vacant_shops": vacant_count,
        "expenses": expenses_total,
        "net_income": net_income,
        "payments": payments_rows,
    }


def export_report_csv(report: dict, out_path: str = None) -> str:
    out_path = out_path or str(config.BACKUPS_DIR / f"report_{report['period']}_{report['start']}_{report['end']}.csv")
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Building Report", config.BUILDING_NAME])
        writer.writerow(["Period", report["period"]])
        writer.writerow(["From", report["start"], "To", report["end"]])
        writer.writerow([])
        writer.writerow(["Expected Rent", report["expected"]])
        writer.writerow(["Collected Rent", report["collected"]])
        writer.writerow(["Outstanding Rent", report["outstanding"]])
        writer.writerow(["Paid Shops", report["paid_shops"]])
        writer.writerow(["Unpaid Shops", report["unpaid_shops"]])
        writer.writerow(["Vacant Shops", report["vacant_shops"]])
        writer.writerow(["Total Expenses", report["expenses"]])
        writer.writerow(["Net Income", report["net_income"]])
        writer.writerow([])
        writer.writerow(["Payments in period"])
        writer.writerow(["Shop", "Rent Month", "Amount", "Reference", "Payment Date", "Status"])
        for p in report["payments"]:
            writer.writerow([p["shop_number"], p["rent_month_key"], p["amount"],
                              p["reference"], p["payment_date_greg"], p["status"]])
    return out_path


def export_report_excel(report: dict, out_path: str = None) -> str:
    try:
        from openpyxl import Workbook
    except ImportError:
        raise RuntimeError("openpyxl is not installed - run `pip install openpyxl` or use CSV export.")

    out_path = out_path or str(config.BACKUPS_DIR / f"report_{report['period']}_{report['start']}_{report['end']}.xlsx")
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws.append(["Building Report", config.BUILDING_NAME])
    ws.append(["Period", report["period"], "From", report["start"], "To", report["end"]])
    ws.append([])
    ws.append(["Expected Rent", report["expected"]])
    ws.append(["Collected Rent", report["collected"]])
    ws.append(["Outstanding Rent", report["outstanding"]])
    ws.append(["Paid Shops", report["paid_shops"]])
    ws.append(["Unpaid Shops", report["unpaid_shops"]])
    ws.append(["Vacant Shops", report["vacant_shops"]])
    ws.append(["Total Expenses", report["expenses"]])
    ws.append(["Net Income", report["net_income"]])

    ws2 = wb.create_sheet("Payments")
    ws2.append(["Shop", "Rent Month", "Amount", "Reference", "Payment Date", "Status"])
    for p in report["payments"]:
        ws2.append([p["shop_number"], p["rent_month_key"], p["amount"],
                    p["reference"], p["payment_date_greg"], p["status"]])

    wb.save(out_path)
    return out_path
