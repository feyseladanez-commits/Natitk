"""
services/expense_service.py
------------------------------
Building operating expenses, used to compute net income in reports.
"""

from database import get_connection, transaction
from services.audit import log_action

CATEGORIES = ["ELECTRICITY", "WATER", "CLEANING", "SECURITY", "MAINTENANCE", "OTHER"]


def add_expense(category: str, description: str, amount: float, expense_date_greg: str,
                 receipt_file_id: str, notes: str, admin_id: int) -> int:
    with transaction() as conn:
        cur = conn.execute(
            """INSERT INTO expenses (category, description, amount, expense_date_greg,
                                      receipt_file_id, notes, recorded_by)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (category, description, amount, expense_date_greg, receipt_file_id, notes, admin_id),
        )
        expense_id = cur.lastrowid
        log_action(admin_id, "EXPENSE_ADDED", "expenses", expense_id,
                   f"category={category} amount={amount}", conn=conn)
        return expense_id


def list_expenses(start_greg: str = None, end_greg: str = None):
    conn = get_connection()
    if start_greg and end_greg:
        return conn.execute(
            """SELECT * FROM expenses WHERE expense_date_greg BETWEEN ? AND ?
               ORDER BY expense_date_greg DESC""",
            (start_greg, end_greg),
        ).fetchall()
    return conn.execute("SELECT * FROM expenses ORDER BY expense_date_greg DESC").fetchall()


def total_expenses(start_greg: str = None, end_greg: str = None) -> float:
    conn = get_connection()
    if start_greg and end_greg:
        row = conn.execute(
            "SELECT COALESCE(SUM(amount),0) AS t FROM expenses WHERE expense_date_greg BETWEEN ? AND ?",
            (start_greg, end_greg),
        ).fetchone()
    else:
        row = conn.execute("SELECT COALESCE(SUM(amount),0) AS t FROM expenses").fetchone()
    return row["t"]
