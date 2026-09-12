"""
services/receipt_pdf.py
--------------------------
Generates a PDF rent receipt after a payment is verified, using
Ethiopian-calendar dates throughout, per specification.
"""

from datetime import date
from pathlib import Path

from calendar_utils.ethiopian import gregorian_to_ethiopian, format_month_label
from config import config


def generate_receipt_pdf(payment_row, shop_row, tenant_row) -> str:
    """
    payment_row / shop_row / tenant_row: sqlite3.Row objects (or dict-likes)
    with the relevant columns already joined by the caller.
    Returns the filesystem path of the generated PDF.
    """
    try:
        from reportlab.lib.pagesizes import A5
        from reportlab.pdfgen import canvas
        from reportlab.lib.units import mm
    except ImportError as exc:
        raise RuntimeError("reportlab is not installed - run `pip install reportlab`.") from exc

    out_dir = config.RECEIPTS_DIR / "generated"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"receipt_{payment_row['id']}.pdf"

    payment_date_e = None
    if payment_row["payment_date_greg"]:
        payment_date_e = gregorian_to_ethiopian(date.fromisoformat(payment_row["payment_date_greg"]))

    year, month = (int(x) for x in payment_row["rent_month_key"].split("-"))
    rent_month_label = format_month_label(year, month)

    c = canvas.Canvas(str(out_path), pagesize=A5)
    width, height = A5
    y = height - 20 * mm

    def line(text, size=11, bold=False, gap=7 * mm):
        nonlocal y
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        c.drawString(15 * mm, y, text)
        y -= gap

    line("COMMERCIAL BUILDING RENT RECEIPT", 13, bold=True, gap=10 * mm)
    line(config.BUILDING_NAME, 10)
    y -= 3 * mm

    line(f"Shop Number: {shop_row['shop_number']}")
    line(f"Floor: {shop_row['floor_name']}")
    line(f"Tenant Name: {tenant_row['full_name'] if tenant_row else 'N/A'}")
    line(f"Rent Month: {rent_month_label}")
    line(f"Amount: {payment_row['amount']:,.2f} {config.CURRENCY}")
    line(f"Payment Reference: {payment_row['reference']}")
    line(f"Payment Date: {payment_date_e.display() if payment_date_e else 'N/A'}")
    line(f"Verification Status: {payment_row['status']}")
    y -= 5 * mm
    line("Thank you.", 10)

    c.showPage()
    c.save()
    return str(out_path)
