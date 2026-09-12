"""
services/announcement_service.py
-----------------------------------
Building-wide notices sent to all registered, active tenants.
"""

from database import get_connection, transaction
from services.audit import log_action


def active_tenant_telegram_ids():
    conn = get_connection()
    rows = conn.execute(
        "SELECT telegram_id FROM tenants WHERE active = 1 AND telegram_id IS NOT NULL"
    ).fetchall()
    return [r["telegram_id"] for r in rows]


def record_announcement(message: str, admin_id: int, recipients_count: int) -> int:
    with transaction() as conn:
        cur = conn.execute(
            "INSERT INTO announcements (message, sent_by, recipients_count) VALUES (?, ?, ?)",
            (message, admin_id, recipients_count),
        )
        log_action(admin_id, "ANNOUNCEMENT_SENT", "announcements", cur.lastrowid,
                   f"recipients={recipients_count}", conn=conn)
        return cur.lastrowid


def list_announcements(limit: int = 20):
    conn = get_connection()
    return conn.execute(
        "SELECT * FROM announcements ORDER BY sent_at DESC LIMIT ?", (limit,)
    ).fetchall()
