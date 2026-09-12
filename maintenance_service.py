"""
services/maintenance_service.py
---------------------------------
Tenant-reported maintenance requests and their admin-side lifecycle.
"""

from database import get_connection, transaction
from services.audit import log_action

CATEGORIES = {
    "ELECTRICITY": "💡 Electricity",
    "WATER": "🚰 Water",
    "TOILET": "🚽 Toilet",
    "DOOR_WINDOW": "🚪 Door/Window",
    "DAMAGE": "🏗 Building Damage",
    "CLEANING": "🧹 Cleaning",
    "OTHER": "❗ Other",
}

STATUS_EMOJI = {
    "NEW": "🔴",
    "IN_PROGRESS": "🟡",
    "COMPLETED": "🟢",
    "REJECTED": "❌",
}


def create_request(shop_id: int, tenant_id: int, category: str, description: str,
                    photo_file_id: str, video_file_id: str) -> int:
    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO maintenance_requests (shop_id, tenant_id, category, description,
                                              photo_file_id, video_file_id)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (shop_id, tenant_id, category, description, photo_file_id, video_file_id),
    )
    return cur.lastrowid


def get_request(request_id: int):
    conn = get_connection()
    return conn.execute("SELECT * FROM maintenance_requests WHERE id = ?", (request_id,)).fetchone()


def list_requests(status: str = None):
    conn = get_connection()
    if status:
        return conn.execute(
            """SELECT m.*, s.shop_number FROM maintenance_requests m
               JOIN shops s ON s.id = m.shop_id
               WHERE m.status = ? ORDER BY m.reported_at DESC""",
            (status,),
        ).fetchall()
    return conn.execute(
        """SELECT m.*, s.shop_number FROM maintenance_requests m
           JOIN shops s ON s.id = m.shop_id
           ORDER BY m.reported_at DESC"""
    ).fetchall()


def list_requests_for_shop(shop_id: int):
    conn = get_connection()
    return conn.execute(
        "SELECT * FROM maintenance_requests WHERE shop_id = ? ORDER BY reported_at DESC",
        (shop_id,),
    ).fetchall()


def update_status(request_id: int, new_status: str, admin_id: int):
    with transaction() as conn:
        req = conn.execute("SELECT * FROM maintenance_requests WHERE id = ?", (request_id,)).fetchone()
        if not req:
            raise ValueError("Maintenance request not found.")
        conn.execute(
            "UPDATE maintenance_requests SET status = ?, updated_at = datetime('now') WHERE id = ?",
            (new_status, request_id),
        )
        log_action(admin_id, "MAINTENANCE_STATUS_CHANGED", "maintenance_requests", request_id,
                   f"{req['status']} -> {new_status}", conn=conn)
