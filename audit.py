"""
services/audit.py
------------------
Append-only audit trail for important administrative actions, as
required: shop created/edited, tenant added/edited, payment
verified/rejected/reversed, rent changed, expense added, announcement sent.
"""

from database import get_connection


def log_action(admin_telegram_id, action: str, related_table: str = None,
                related_id: int = None, details: str = None, conn=None):
    """
    Record an audit entry. Pass `conn` when called from inside an existing
    transaction() block so the log write is part of the same atomic unit;
    otherwise a connection is grabbed and the write auto-commits.
    """
    own_conn = conn is None
    c = conn or get_connection()
    c.execute(
        """INSERT INTO audit_logs (admin_telegram_id, action, related_table, related_id, details)
           VALUES (?, ?, ?, ?, ?)""",
        (admin_telegram_id, action, related_table, related_id, details),
    )
    # if we grabbed our own connection (autocommit mode), nothing more to do
    if own_conn:
        pass


def recent_logs(limit: int = 50):
    conn = get_connection()
    return conn.execute(
        "SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
