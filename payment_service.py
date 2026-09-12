"""
services/payment_service.py
-----------------------------
Handles payment submission, duplicate-reference protection, manual
verification workflow, reversal, and receipt generation triggers.

Critical safety properties implemented here:
  * The `payments.reference` column has a UNIQUE constraint at the DB
    level (see models/schema.sql) - this is the ultimate guard.
  * Every submission runs inside a BEGIN IMMEDIATE transaction
    (database.transaction()) so two tenants submitting the same
    reference number at nearly the same time cannot both pass the
    pre-check: SQLite serializes writers, so the second submission
    will see the first one's row (or hit the UNIQUE constraint) before
    it can commit.
  * A receipt upload never auto-verifies a payment. Extraction (OCR) is
    a best-effort pluggable step; anything it cannot confidently read
    is routed to MANUAL_REVIEW for a human admin decision.
"""

from database import get_connection, transaction
from services.audit import log_action
from services import rent_service


class PaymentError(Exception):
    pass


class DuplicateReferenceError(PaymentError):
    def __init__(self, reference, existing_shop_number):
        self.reference = reference
        self.existing_shop_number = existing_shop_number
        super().__init__(
            f"Reference {reference} has already been used for shop {existing_shop_number}."
        )


def reference_already_used(reference: str):
    """Returns the existing payment_references row if this reference was
    ever used (and is still locked), else None."""
    conn = get_connection()
    return conn.execute(
        """SELECT pr.*, s.shop_number FROM payment_references pr
           JOIN shops s ON s.id = pr.shop_id
           WHERE pr.reference = ? AND pr.locked = 1""",
        (reference,),
    ).fetchone()


def submit_payment(shop_id: int, tenant_id: int, rent_month_key: str, amount: float,
                    reference: str, payment_date_greg: str, receipt_file_path: str,
                    telegram_file_id: str, extracted_data_json: str,
                    submitted_by: int, confident_extraction: bool) -> dict:
    """
    Record a tenant's payment submission. Returns a dict describing the
    resulting status: {'status': 'MANUAL_REVIEW'|'DUPLICATE', 'payment_id': int, ...}

    Even when extraction is confident, the payment starts as PENDING /
    MANUAL_REVIEW and always requires an explicit admin VERIFY action -
    nothing here marks a payment VERIFIED automatically, per spec.
    """
    reference = reference.strip()
    with transaction() as conn:
        rent_record = conn.execute(
            "SELECT * FROM rent_records WHERE shop_id = ? AND rent_month_key = ?",
            (shop_id, rent_month_key),
        ).fetchone()
        if not rent_record:
            raise PaymentError("No rent record exists for that month yet.")
        if rent_record["status"] == "PAID":
            raise PaymentError(
                "That rent month is already marked as PAID. Contact the administrator "
                "if this is a mistake."
            )

        dup = conn.execute(
            """SELECT pr.*, s.shop_number FROM payment_references pr
               JOIN shops s ON s.id = pr.shop_id
               WHERE pr.reference = ? AND pr.locked = 1""",
            (reference,),
        ).fetchone()
        if dup:
            # Record the rejected attempt for audit purposes, but do NOT touch
            # payment_references (that ledger entry belongs to the original payment).
            cur = conn.execute(
                """INSERT INTO payments (shop_id, tenant_id, rent_record_id, rent_month_key,
                                          amount, reference, payment_date_greg, receipt_file_path,
                                          telegram_file_id, extracted_data_json, status,
                                          submitted_by, rejection_reason)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'DUPLICATE', ?, ?)""",
                (shop_id, tenant_id, rent_record["id"], rent_month_key, amount,
                 reference + f"__dup_attempt_{rent_record['id']}", payment_date_greg,
                 receipt_file_path, telegram_file_id, extracted_data_json, submitted_by,
                 f"Reference already used for shop {dup['shop_number']}"),
            )
            raise DuplicateReferenceError(reference, dup["shop_number"])

        status = "PENDING" if confident_extraction else "MANUAL_REVIEW"

        cur = conn.execute(
            """INSERT INTO payments (shop_id, tenant_id, rent_record_id, rent_month_key,
                                      amount, reference, payment_date_greg, receipt_file_path,
                                      telegram_file_id, extracted_data_json, status, submitted_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (shop_id, tenant_id, rent_record["id"], rent_month_key, amount, reference,
             payment_date_greg, receipt_file_path, telegram_file_id, extracted_data_json,
             status, submitted_by),
        )
        payment_id = cur.lastrowid

        # Reference is provisionally reserved the moment it's submitted (not just on
        # verification) so two tenants can never race each other with the same reference
        # while the first is still pending review.
        conn.execute(
            """INSERT INTO payment_references (reference, payment_id, shop_id, locked)
               VALUES (?, ?, ?, 1)""",
            (reference, payment_id, shop_id),
        )

        log_action(submitted_by, "PAYMENT_SUBMITTED", "payments", payment_id,
                   f"shop_id={shop_id} ref={reference} amount={amount} status={status}", conn=conn)

        return {"status": status, "payment_id": payment_id}


def get_payment(payment_id: int):
    conn = get_connection()
    return conn.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone()


def pending_payments():
    conn = get_connection()
    return conn.execute(
        """SELECT p.*, s.shop_number FROM payments p
           JOIN shops s ON s.id = p.shop_id
           WHERE p.status IN ('PENDING','MANUAL_REVIEW')
           ORDER BY p.created_at"""
    ).fetchall()


def verify_payment(payment_id: int, admin_id: int):
    with transaction() as conn:
        payment = conn.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone()
        if not payment:
            raise PaymentError("Payment not found.")
        if payment["status"] == "VERIFIED":
            raise PaymentError("Payment is already verified.")
        if payment["status"] not in ("PENDING", "MANUAL_REVIEW"):
            raise PaymentError(f"Cannot verify a payment with status {payment['status']}.")

        conn.execute(
            """UPDATE payments SET status = 'VERIFIED', verified_by = ?, verified_at = datetime('now')
               WHERE id = ?""",
            (admin_id, payment_id),
        )
        if payment["rent_record_id"]:
            rent_service.mark_rent_paid(conn, payment["rent_record_id"])

        log_action(admin_id, "PAYMENT_VERIFIED", "payments", payment_id,
                   f"ref={payment['reference']} amount={payment['amount']}", conn=conn)
        # Re-fetch so callers (receipt PDF, notifications) see the final
        # VERIFIED status/verified_by/verified_at rather than the pre-update row.
        return conn.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone()


def reject_payment(payment_id: int, admin_id: int, reason: str):
    with transaction() as conn:
        payment = conn.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone()
        if not payment:
            raise PaymentError("Payment not found.")
        if payment["status"] == "VERIFIED":
            raise PaymentError("Cannot reject an already-verified payment; use Reverse instead.")

        conn.execute(
            """UPDATE payments SET status = 'REJECTED', verified_by = ?, verified_at = datetime('now'),
                                    rejection_reason = ? WHERE id = ?""",
            (admin_id, reason, payment_id),
        )
        # Release the reference lock so a corrected receipt can be resubmitted,
        # since a rejected payment was never legitimately fulfilled.
        conn.execute(
            "UPDATE payment_references SET locked = 0 WHERE payment_id = ?", (payment_id,)
        )
        log_action(admin_id, "PAYMENT_REJECTED", "payments", payment_id,
                   f"ref={payment['reference']} reason={reason}", conn=conn)
        return payment


def reverse_payment(payment_id: int, admin_id: int, reason: str, release_reference: bool = False):
    """
    Reverse a previously VERIFIED payment. This never deletes history -
    it flips status to REVERSED and puts the rent month back to UNPAID,
    fully logged. The reference stays locked unless the admin explicitly
    chooses to release it (release_reference=True), per spec.
    """
    with transaction() as conn:
        payment = conn.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone()
        if not payment:
            raise PaymentError("Payment not found.")
        if payment["status"] != "VERIFIED":
            raise PaymentError("Only a VERIFIED payment can be reversed.")

        conn.execute(
            """UPDATE payments SET status = 'REVERSED', rejection_reason = ? WHERE id = ?""",
            (reason, payment_id),
        )
        if payment["rent_record_id"]:
            rent_service.mark_rent_unpaid(conn, payment["rent_record_id"])

        if release_reference:
            conn.execute(
                "UPDATE payment_references SET locked = 0 WHERE payment_id = ?", (payment_id,)
            )

        log_action(admin_id, "PAYMENT_REVERSED", "payments", payment_id,
                   f"ref={payment['reference']} reason={reason} released_ref={release_reference}",
                   conn=conn)
        return payment


def payment_history(shop_id: int):
    conn = get_connection()
    return conn.execute(
        """SELECT * FROM payments WHERE shop_id = ? ORDER BY rent_month_key""",
        (shop_id,),
    ).fetchall()


def search_by_reference(reference: str):
    conn = get_connection()
    return conn.execute(
        """SELECT p.*, s.shop_number FROM payments p
           JOIN shops s ON s.id = p.shop_id
           WHERE p.reference LIKE ? ORDER BY p.created_at DESC""",
        (f"%{reference}%",),
    ).fetchall()


def used_references(search: str = None):
    conn = get_connection()
    if search:
        return conn.execute(
            """SELECT pr.reference, s.shop_number, p.amount, p.rent_month_key,
                      p.payment_date_greg, p.status
               FROM payment_references pr
               JOIN payments p ON p.id = pr.payment_id
               JOIN shops s ON s.id = pr.shop_id
               WHERE pr.reference LIKE ?
               ORDER BY pr.created_at DESC""",
            (f"%{search}%",),
        ).fetchall()
    return conn.execute(
        """SELECT pr.reference, s.shop_number, p.amount, p.rent_month_key,
                  p.payment_date_greg, p.status
           FROM payment_references pr
           JOIN payments p ON p.id = pr.payment_id
           JOIN shops s ON s.id = pr.shop_id
           ORDER BY pr.created_at DESC LIMIT 100"""
    ).fetchall()
