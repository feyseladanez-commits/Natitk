"""
services/shop_service.py
-------------------------
CRUD and query operations for shops.
"""

from database import get_connection, transaction
from services.audit import log_action


class ShopError(Exception):
    pass


def list_shops(floor_id: int = None):
    conn = get_connection()
    if floor_id:
        return conn.execute(
            """SELECT s.*, f.name AS floor_name FROM shops s
               JOIN floors f ON f.id = s.floor_id
               WHERE s.floor_id = ?
               ORDER BY s.shop_number""",
            (floor_id,),
        ).fetchall()
    return conn.execute(
        """SELECT s.*, f.name AS floor_name FROM shops s
           JOIN floors f ON f.id = s.floor_id
           ORDER BY f.sort_order, s.shop_number"""
    ).fetchall()


def get_shop(shop_id: int):
    conn = get_connection()
    return conn.execute(
        """SELECT s.*, f.name AS floor_name FROM shops s
           JOIN floors f ON f.id = s.floor_id
           WHERE s.id = ?""",
        (shop_id,),
    ).fetchone()


def get_shop_by_number(shop_number: str):
    conn = get_connection()
    return conn.execute(
        """SELECT s.*, f.name AS floor_name FROM shops s
           JOIN floors f ON f.id = s.floor_id
           WHERE s.shop_number = ?""",
        (shop_number,),
    ).fetchone()


def add_shop(shop_number: str, floor_id: int, size_sqm: float, monthly_rent: float,
             status: str, admin_id: int) -> int:
    with transaction() as conn:
        floor = conn.execute("SELECT * FROM floors WHERE id = ?", (floor_id,)).fetchone()
        if not floor:
            raise ShopError("Selected floor does not exist.")
        dup = conn.execute("SELECT 1 FROM shops WHERE shop_number = ?", (shop_number,)).fetchone()
        if dup:
            raise ShopError(f"Shop number '{shop_number}' already exists.")
        cur = conn.execute(
            """INSERT INTO shops (shop_number, floor_id, size_sqm, monthly_rent, status)
               VALUES (?, ?, ?, ?, ?)""",
            (shop_number, floor_id, size_sqm, monthly_rent, status),
        )
        shop_id = cur.lastrowid
        log_action(admin_id, "SHOP_CREATED", "shops", shop_id,
                   f"number={shop_number} floor={floor['name']} size={size_sqm} rent={monthly_rent}",
                   conn=conn)
        return shop_id


def bulk_add_shops(entries: list, admin_id: int) -> int:
    """
    entries: list of dicts {"floor": name, "shop_number": str, "size_sqm": float, "monthly_rent": float}
    Creates any missing floors automatically, validates uniqueness, and inserts everything
    atomically - either all shops are created or none are (on validation failure).
    """
    with transaction() as conn:
        created = 0
        floor_cache = {}
        for e in entries:
            floor_name = e["floor"]
            if floor_name not in floor_cache:
                row = conn.execute("SELECT * FROM floors WHERE name = ?", (floor_name,)).fetchone()
                if row is None:
                    max_order = conn.execute(
                        "SELECT COALESCE(MAX(sort_order), 0) FROM floors"
                    ).fetchone()[0]
                    cur = conn.execute(
                        "INSERT INTO floors (name, sort_order) VALUES (?, ?)",
                        (floor_name, max_order + 1),
                    )
                    floor_id = cur.lastrowid
                    log_action(admin_id, "FLOOR_CREATED", "floors", floor_id,
                               f"name={floor_name} (via bulkshops)", conn=conn)
                else:
                    floor_id = row["id"]
                floor_cache[floor_name] = floor_id
            floor_id = floor_cache[floor_name]

            dup = conn.execute(
                "SELECT 1 FROM shops WHERE shop_number = ?", (e["shop_number"],)
            ).fetchone()
            if dup:
                raise ShopError(f"Shop number '{e['shop_number']}' already exists.")

            cur = conn.execute(
                """INSERT INTO shops (shop_number, floor_id, size_sqm, monthly_rent, status)
                   VALUES (?, ?, ?, ?, 'VACANT')""",
                (e["shop_number"], floor_id, e["size_sqm"], e["monthly_rent"]),
            )
            log_action(admin_id, "SHOP_CREATED", "shops", cur.lastrowid,
                       f"number={e['shop_number']} floor={floor_name} (via bulkshops)", conn=conn)
            created += 1
        return created


def update_shop(shop_id: int, admin_id: int, floor_id=None, shop_number=None,
                 size_sqm=None, monthly_rent=None, status=None):
    with transaction() as conn:
        shop = conn.execute("SELECT * FROM shops WHERE id = ?", (shop_id,)).fetchone()
        if not shop:
            raise ShopError("Shop not found.")

        changes = []
        fields, values = [], []

        if shop_number and shop_number != shop["shop_number"]:
            dup = conn.execute(
                "SELECT 1 FROM shops WHERE shop_number = ? AND id != ?", (shop_number, shop_id)
            ).fetchone()
            if dup:
                raise ShopError(f"Shop number '{shop_number}' already exists.")
            fields.append("shop_number = ?")
            values.append(shop_number)
            changes.append(f"number {shop['shop_number']}->{shop_number}")

        if floor_id and floor_id != shop["floor_id"]:
            floor = conn.execute("SELECT * FROM floors WHERE id = ?", (floor_id,)).fetchone()
            if not floor:
                raise ShopError("Selected floor does not exist.")
            fields.append("floor_id = ?")
            values.append(floor_id)
            changes.append(f"floor->{floor['name']}")

        if size_sqm and size_sqm != shop["size_sqm"]:
            fields.append("size_sqm = ?")
            values.append(size_sqm)
            changes.append(f"size {shop['size_sqm']}->{size_sqm}")

        if monthly_rent and monthly_rent != shop["monthly_rent"]:
            fields.append("monthly_rent = ?")
            values.append(monthly_rent)
            changes.append(f"rent {shop['monthly_rent']}->{monthly_rent}")

        if status and status != shop["status"]:
            fields.append("status = ?")
            values.append(status)
            changes.append(f"status {shop['status']}->{status}")

        if not fields:
            return  # nothing changed

        fields.append("updated_at = datetime('now')")
        values.append(shop_id)
        conn.execute(f"UPDATE shops SET {', '.join(fields)} WHERE id = ?", values)
        log_action(admin_id, "SHOP_EDITED", "shops", shop_id, "; ".join(changes), conn=conn)


def delete_shop(shop_id: int, admin_id: int):
    with transaction() as conn:
        shop = conn.execute("SELECT * FROM shops WHERE id = ?", (shop_id,)).fetchone()
        if not shop:
            raise ShopError("Shop not found.")
        active_tenant = conn.execute(
            "SELECT 1 FROM tenants WHERE shop_id = ? AND active = 1", (shop_id,)
        ).fetchone()
        if active_tenant:
            raise ShopError("Cannot delete a shop that has an active tenant. Remove the tenant first.")
        conn.execute("DELETE FROM shops WHERE id = ?", (shop_id,))
        log_action(admin_id, "SHOP_DELETED", "shops", shop_id,
                   f"number={shop['shop_number']}", conn=conn)


def counts_summary():
    conn = get_connection()
    row = conn.execute(
        """SELECT
             COUNT(*) AS total,
             SUM(CASE WHEN status='OCCUPIED' THEN 1 ELSE 0 END) AS occupied,
             SUM(CASE WHEN status='VACANT' THEN 1 ELSE 0 END) AS vacant
           FROM shops"""
    ).fetchone()
    return {
        "total": row["total"] or 0,
        "occupied": row["occupied"] or 0,
        "vacant": row["vacant"] or 0,
    }
