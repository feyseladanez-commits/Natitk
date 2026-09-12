"""
services/floor_service.py
--------------------------
CRUD operations for building floors.
"""

from database import get_connection, transaction
from services.audit import log_action


class FloorError(Exception):
    pass


def list_floors():
    conn = get_connection()
    return conn.execute("SELECT * FROM floors ORDER BY sort_order, id").fetchall()


def get_floor(floor_id: int):
    conn = get_connection()
    return conn.execute("SELECT * FROM floors WHERE id = ?", (floor_id,)).fetchone()


def get_floor_by_name(name: str):
    conn = get_connection()
    return conn.execute("SELECT * FROM floors WHERE name = ?", (name,)).fetchone()


def add_floor(name: str, admin_id: int) -> int:
    name = name.strip()
    if not name:
        raise FloorError("Floor name cannot be empty.")
    with transaction() as conn:
        existing = conn.execute("SELECT 1 FROM floors WHERE name = ?", (name,)).fetchone()
        if existing:
            raise FloorError(f"A floor named '{name}' already exists.")
        max_order = conn.execute("SELECT COALESCE(MAX(sort_order), 0) FROM floors").fetchone()[0]
        cur = conn.execute(
            "INSERT INTO floors (name, sort_order) VALUES (?, ?)", (name, max_order + 1)
        )
        floor_id = cur.lastrowid
        log_action(admin_id, "FLOOR_CREATED", "floors", floor_id, f"name={name}", conn=conn)
        return floor_id


def rename_floor(floor_id: int, new_name: str, admin_id: int):
    new_name = new_name.strip()
    if not new_name:
        raise FloorError("Floor name cannot be empty.")
    with transaction() as conn:
        floor = conn.execute("SELECT * FROM floors WHERE id = ?", (floor_id,)).fetchone()
        if not floor:
            raise FloorError("Floor not found.")
        dup = conn.execute(
            "SELECT 1 FROM floors WHERE name = ? AND id != ?", (new_name, floor_id)
        ).fetchone()
        if dup:
            raise FloorError(f"A floor named '{new_name}' already exists.")
        old_name = floor["name"]
        conn.execute("UPDATE floors SET name = ? WHERE id = ?", (new_name, floor_id))
        log_action(admin_id, "FLOOR_RENAMED", "floors", floor_id,
                   f"{old_name} -> {new_name}", conn=conn)


def delete_floor(floor_id: int, admin_id: int):
    with transaction() as conn:
        floor = conn.execute("SELECT * FROM floors WHERE id = ?", (floor_id,)).fetchone()
        if not floor:
            raise FloorError("Floor not found.")
        shop_count = conn.execute(
            "SELECT COUNT(*) FROM shops WHERE floor_id = ?", (floor_id,)
        ).fetchone()[0]
        if shop_count > 0:
            raise FloorError(
                f"Cannot delete '{floor['name']}': it still has {shop_count} shop(s). "
                "Reassign or delete those shops first."
            )
        conn.execute("DELETE FROM floors WHERE id = ?", (floor_id,))
        log_action(admin_id, "FLOOR_DELETED", "floors", floor_id, f"name={floor['name']}", conn=conn)
