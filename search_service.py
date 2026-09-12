"""
services/search_service.py
-----------------------------
Unified search across shops, tenants, phone numbers, and payment references,
used by /search.
"""

from database import get_connection


def search_all(query: str) -> dict:
    conn = get_connection()
    q = f"%{query}%"

    shops = conn.execute(
        """SELECT s.*, f.name AS floor_name FROM shops s
           JOIN floors f ON f.id = s.floor_id
           WHERE s.shop_number LIKE ?""",
        (q,),
    ).fetchall()

    tenants = conn.execute(
        """SELECT t.*, s.shop_number FROM tenants t
           JOIN shops s ON s.id = t.shop_id
           WHERE t.active = 1 AND (t.full_name LIKE ? OR t.phone LIKE ?)""",
        (q, q),
    ).fetchall()

    payments = conn.execute(
        """SELECT p.*, s.shop_number FROM payments p
           JOIN shops s ON s.id = p.shop_id
           WHERE p.reference LIKE ?
           ORDER BY p.created_at DESC""",
        (q,),
    ).fetchall()

    return {"shops": shops, "tenants": tenants, "payments": payments}
