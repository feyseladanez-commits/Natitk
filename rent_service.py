"""
services/rent_service.py
--------------------------
Generates and maintains per-Ethiopian-month rent records for each shop,
and computes building-wide / floor-wide / shop-wide rent status.

Rent is tracked one row per (shop, Ethiopian rent month) - never as a
single running "balance" - per the specification.
"""

from datetime import date

from database import get_connection, transaction
from calendar_utils.ethiopian import (
    EthiopianDate, gregorian_to_ethiopian, ethiopian_to_gregorian,
    add_ethiopian_months, today_ethiopian, format_month_label,
)
from config import config

MONTHS_TO_GENERATE_AHEAD = 3  # how many upcoming months to always keep visible


def _due_date_for_month(e_year: int, e_month: int) -> date:
    due_day = min(config.RENT_DUE_DAY, 30 if e_month != 13 else 5)
    return ethiopian_to_gregorian(EthiopianDate(e_year, e_month, due_day))


def generate_rent_schedule(conn, shop_id: int, tenant_id: int, monthly_rent: float,
                            contract_start_greg: str):
    """
    Create rent_records rows starting at the contract start month through
    MONTHS_TO_GENERATE_AHEAD months beyond the current Ethiopian month.
    Safe to call again later (e.g. monthly rollover) - uses INSERT OR IGNORE
    thanks to the UNIQUE(shop_id, rent_month_key) constraint.
    """
    start_greg = date.fromisoformat(contract_start_greg)
    start_e = gregorian_to_ethiopian(start_greg)
    current_e = today_ethiopian()
    end_e = add_ethiopian_months(current_e, MONTHS_TO_GENERATE_AHEAD)

    cursor_e = EthiopianDate(start_e.year, start_e.month, 1)
    while (cursor_e.year, cursor_e.month) <= (end_e.year, end_e.month):
        month_key = cursor_e.month_key()
        due_date = _due_date_for_month(cursor_e.year, cursor_e.month)
        status = "UPCOMING" if (cursor_e.year, cursor_e.month) > (current_e.year, current_e.month) else "UNPAID"
        conn.execute(
            """INSERT OR IGNORE INTO rent_records
               (shop_id, tenant_id, rent_month_key, amount_due, due_date_greg, status)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (shop_id, tenant_id, month_key, monthly_rent, due_date.isoformat(), status),
        )
        cursor_e = add_ethiopian_months(cursor_e, 1)


def extend_all_schedules(admin_id: int = None):
    """Roll every active tenant's rent schedule forward. Intended to run on a
    scheduled job (e.g. daily) so upcoming months are always pre-created and
    overdue statuses stay accurate."""
    with transaction() as conn:
        tenants = conn.execute(
            """SELECT t.id AS tenant_id, t.shop_id, t.contract_start, s.monthly_rent
               FROM tenants t JOIN shops s ON s.id = t.shop_id
               WHERE t.active = 1"""
        ).fetchall()
        for t in tenants:
            generate_rent_schedule(conn, t["shop_id"], t["tenant_id"], t["monthly_rent"], t["contract_start"])
        refresh_overdue_statuses(conn)


def refresh_overdue_statuses(conn=None):
    """Flip UNPAID rows whose due date has passed into OVERDUE, and
    UPCOMING rows whose month has arrived into UNPAID."""
    own = conn is None
    c = conn or get_connection()
    today_iso = date.today().isoformat()
    c.execute(
        "UPDATE rent_records SET status = 'OVERDUE' WHERE status = 'UNPAID' AND due_date_greg < ?",
        (today_iso,),
    )
    current_key = today_ethiopian().month_key()
    c.execute(
        """UPDATE rent_records SET status = 'UNPAID'
           WHERE status = 'UPCOMING' AND rent_month_key <= ?""",
        (current_key,),
    )


def shop_rent_rows(shop_id: int):
    conn = get_connection()
    refresh_overdue_statuses(conn)
    return conn.execute(
        "SELECT * FROM rent_records WHERE shop_id = ? ORDER BY rent_month_key",
        (shop_id,),
    ).fetchall()


def shop_outstanding_amount(shop_id: int) -> float:
    conn = get_connection()
    row = conn.execute(
        """SELECT COALESCE(SUM(amount_due), 0) AS total FROM rent_records
           WHERE shop_id = ? AND status IN ('UNPAID','OVERDUE')""",
        (shop_id,),
    ).fetchone()
    return row["total"]


def mark_rent_paid(conn, rent_record_id: int):
    conn.execute("UPDATE rent_records SET status = 'PAID' WHERE id = ?", (rent_record_id,))


def mark_rent_unpaid(conn, rent_record_id: int):
    conn.execute("UPDATE rent_records SET status = 'UNPAID' WHERE id = ?", (rent_record_id,))


def get_rent_record(shop_id: int, rent_month_key: str):
    conn = get_connection()
    return conn.execute(
        "SELECT * FROM rent_records WHERE shop_id = ? AND rent_month_key = ?",
        (shop_id, rent_month_key),
    ).fetchone()


def building_rent_status():
    """Aggregate expected/collected/outstanding for the current Ethiopian month."""
    conn = get_connection()
    refresh_overdue_statuses(conn)
    current_key = today_ethiopian().month_key()

    shops = conn.execute("SELECT * FROM shops").fetchall()
    expected = sum(s["monthly_rent"] for s in shops if s["status"] == "OCCUPIED")

    rows = conn.execute(
        "SELECT status, SUM(amount_due) AS total, COUNT(*) AS n FROM rent_records "
        "WHERE rent_month_key = ? GROUP BY status",
        (current_key,),
    ).fetchall()

    collected = 0.0
    outstanding = 0.0
    paid_count = 0
    unpaid_count = 0
    for r in rows:
        if r["status"] == "PAID":
            collected += r["total"] or 0
            paid_count += r["n"]
        elif r["status"] in ("UNPAID", "OVERDUE"):
            outstanding += r["total"] or 0
            unpaid_count += r["n"]

    vacant_count = sum(1 for s in shops if s["status"] == "VACANT")

    return {
        "expected": expected,
        "collected": collected,
        "outstanding": outstanding,
        "paid_shops": paid_count,
        "unpaid_shops": unpaid_count,
        "vacant_shops": vacant_count,
        "month_label": format_month_label(*[int(x) for x in current_key.split("-")]),
    }


def floor_status(floor_id: int):
    conn = get_connection()
    current_key = today_ethiopian().month_key()
    shops = conn.execute("SELECT * FROM shops WHERE floor_id = ?", (floor_id,)).fetchall()
    total = len(shops)
    occupied = sum(1 for s in shops if s["status"] == "OCCUPIED")
    vacant = total - occupied
    paid = 0
    unpaid = 0
    for s in shops:
        if s["status"] != "OCCUPIED":
            continue
        r = conn.execute(
            "SELECT status FROM rent_records WHERE shop_id = ? AND rent_month_key = ?",
            (s["id"], current_key),
        ).fetchone()
        if r and r["status"] == "PAID":
            paid += 1
        elif r:
            unpaid += 1
    return {"total": total, "occupied": occupied, "vacant": vacant, "paid": paid, "unpaid": unpaid}


def unpaid_shops():
    conn = get_connection()
    refresh_overdue_statuses(conn)
    current_key = today_ethiopian().month_key()
    return conn.execute(
        """SELECT s.id, s.shop_number, r.amount_due, r.status
           FROM rent_records r JOIN shops s ON s.id = r.shop_id
           WHERE r.rent_month_key = ? AND r.status IN ('UNPAID','OVERDUE')
           ORDER BY s.shop_number""",
        (current_key,),
    ).fetchall()


def vacant_shops():
    conn = get_connection()
    return conn.execute(
        "SELECT * FROM shops WHERE status = 'VACANT' ORDER BY shop_number"
    ).fetchall()


def occupied_shops():
    conn = get_connection()
    return conn.execute(
        """SELECT s.*, t.full_name AS tenant_name, t.phone AS tenant_phone
           FROM shops s
           LEFT JOIN tenants t ON t.shop_id = s.id AND t.active = 1
           WHERE s.status = 'OCCUPIED'
           ORDER BY s.shop_number"""
    ).fetchall()


def paid_shops():
    conn = get_connection()
    current_key = today_ethiopian().month_key()
    return conn.execute(
        """SELECT s.id, s.shop_number FROM rent_records r
           JOIN shops s ON s.id = r.shop_id
           WHERE r.rent_month_key = ? AND r.status = 'PAID'
           ORDER BY s.shop_number""",
        (current_key,),
    ).fetchall()
