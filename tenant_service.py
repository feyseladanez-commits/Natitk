"""
services/tenant_service.py
---------------------------
Tenant CRUD, document attachment, and shop <-> tenant linking.
"""

from database import get_connection, transaction
from services.audit import log_action
from services.rent_service import generate_rent_schedule


class TenantError(Exception):
    pass


def get_tenant(tenant_id: int):
    conn = get_connection()
    return conn.execute("SELECT * FROM tenants WHERE id = ?", (tenant_id,)).fetchone()


def get_active_tenant_for_shop(shop_id: int):
    conn = get_connection()
    return conn.execute(
        "SELECT * FROM tenants WHERE shop_id = ? AND active = 1", (shop_id,)
    ).fetchone()


def get_tenant_by_telegram_id(telegram_id: int):
    conn = get_connection()
    return conn.execute(
        "SELECT * FROM tenants WHERE telegram_id = ? AND active = 1", (telegram_id,)
    ).fetchone()


def add_tenant(shop_id: int, full_name: str, phone: str, id_type: str, id_number: str,
               contract_start_greg: str, contract_end_greg: str, monthly_rent: float,
               notes: str, admin_id: int, allow_multi_shop: bool = False) -> int:
    with transaction() as conn:
        shop = conn.execute("SELECT * FROM shops WHERE id = ?", (shop_id,)).fetchone()
        if not shop:
            raise TenantError("Shop not found.")

        existing = conn.execute(
            "SELECT 1 FROM tenants WHERE shop_id = ? AND active = 1", (shop_id,)
        ).fetchone()
        if existing:
            raise TenantError(
                "This shop already has an active tenant. Remove/replace the existing "
                "tenant before adding a new one."
            )

        if not allow_multi_shop:
            other = conn.execute(
                """SELECT s.shop_number FROM tenants t
                   JOIN shops s ON s.id = t.shop_id
                   WHERE t.full_name = ? AND t.phone = ? AND t.active = 1""",
                (full_name, phone),
            ).fetchone()
            if other:
                raise TenantError(
                    f"A tenant with this name/phone already occupies shop {other['shop_number']}. "
                    "Multi-shop tenants are disabled in settings."
                )

        cur = conn.execute(
            """INSERT INTO tenants (shop_id, full_name, phone, id_type, id_number,
                                     contract_start, contract_end, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (shop_id, full_name, phone, id_type, id_number,
             contract_start_greg, contract_end_greg, notes),
        )
        tenant_id = cur.lastrowid

        conn.execute(
            "UPDATE shops SET status = 'OCCUPIED', updated_at = datetime('now') WHERE id = ?",
            (shop_id,),
        )

        log_action(admin_id, "TENANT_ADDED", "tenants", tenant_id,
                   f"shop={shop['shop_number']} name={full_name}", conn=conn)

        # Generate the rent schedule for this tenant going forward from contract start
        generate_rent_schedule(conn, shop_id, tenant_id, monthly_rent, contract_start_greg)

        return tenant_id


def update_tenant(tenant_id: int, admin_id: int, **fields):
    """fields may include: full_name, phone, id_type, id_number,
    contract_start_greg, contract_end_greg, notes"""
    allowed = {
        "full_name": "full_name", "phone": "phone", "id_type": "id_type",
        "id_number": "id_number", "contract_start_greg": "contract_start",
        "contract_end_greg": "contract_end", "notes": "notes",
    }
    with transaction() as conn:
        tenant = conn.execute("SELECT * FROM tenants WHERE id = ?", (tenant_id,)).fetchone()
        if not tenant:
            raise TenantError("Tenant not found.")

        set_clauses, values, changes = [], [], []
        for key, column in allowed.items():
            if key in fields and fields[key] is not None:
                set_clauses.append(f"{column} = ?")
                values.append(fields[key])
                changes.append(f"{column} updated")

        if not set_clauses:
            return

        set_clauses.append("updated_at = datetime('now')")
        values.append(tenant_id)
        conn.execute(f"UPDATE tenants SET {', '.join(set_clauses)} WHERE id = ?", values)
        log_action(admin_id, "TENANT_EDITED", "tenants", tenant_id, "; ".join(changes), conn=conn)


def deactivate_tenant(tenant_id: int, admin_id: int, mark_shop_vacant: bool = True):
    with transaction() as conn:
        tenant = conn.execute("SELECT * FROM tenants WHERE id = ?", (tenant_id,)).fetchone()
        if not tenant:
            raise TenantError("Tenant not found.")
        conn.execute(
            "UPDATE tenants SET active = 0, updated_at = datetime('now') WHERE id = ?",
            (tenant_id,),
        )
        if mark_shop_vacant:
            conn.execute(
                "UPDATE shops SET status = 'VACANT', updated_at = datetime('now') WHERE id = ?",
                (tenant["shop_id"],),
            )
        log_action(admin_id, "TENANT_DELETED", "tenants", tenant_id,
                   f"name={tenant['full_name']}", conn=conn)


def attach_document(tenant_id: int, file_path: str, telegram_file_id: str,
                     doc_type: str, admin_id: int) -> int:
    with transaction() as conn:
        tenant = conn.execute("SELECT * FROM tenants WHERE id = ?", (tenant_id,)).fetchone()
        if not tenant:
            raise TenantError("Tenant not found.")
        cur = conn.execute(
            """INSERT INTO tenant_documents (tenant_id, file_path, telegram_file_id, doc_type, uploaded_by)
               VALUES (?, ?, ?, ?, ?)""",
            (tenant_id, file_path, telegram_file_id, doc_type, admin_id),
        )
        log_action(admin_id, "TENANT_DOCUMENT_ATTACHED", "tenant_documents", cur.lastrowid,
                   f"tenant_id={tenant_id} type={doc_type}", conn=conn)
        return cur.lastrowid


def list_documents(tenant_id: int):
    conn = get_connection()
    return conn.execute(
        "SELECT * FROM tenant_documents WHERE tenant_id = ? ORDER BY uploaded_at DESC",
        (tenant_id,),
    ).fetchall()
