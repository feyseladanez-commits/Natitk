"""
services/receipt_extraction.py
--------------------------------
Best-effort extraction of payment details (amount, reference number,
date, payer name) from an uploaded receipt image/PDF.

IMPORTANT SAFETY RULE (per specification):
Never automatically mark a payment as VERIFIED just because a receipt
was uploaded or because extraction "succeeded". This module only ever
*proposes* values; a human administrator always makes the final
VERIFY/REJECT decision (see handlers/admin_payments.py).

This ships with a lightweight, dependency-free heuristic extractor that
works on the *caption/text* the tenant sends alongside the receipt
(many Ethiopian bank/telebirr confirmation screenshots are forwarded
with the confirmation SMS text, or the tenant can simply type the
reference and amount). If OCR libraries (pytesseract + Pillow, or a
cloud OCR API) are installed/configured, plug them in at the marked
extension point below - until then, image-only receipts with no
readable text are correctly routed to MANUAL_REVIEW instead of being
guessed at.
"""

import re
import json
from dataclasses import dataclass, asdict
from typing import Optional


REFERENCE_PATTERNS = [
    r"\b([A-Z]{2}\d{8,15})\b",       # e.g. FT123456789 (common bank transfer format)
    r"\bRef(?:erence)?[:\s]*([A-Za-z0-9\-]{6,20})\b",
    r"\bTxn(?:\s*ID)?[:\s]*([A-Za-z0-9\-]{6,20})\b",
]

AMOUNT_PATTERNS = [
    r"\b(?:ETB|Birr)\s?([\d,]+(?:\.\d{1,2})?)\b",
    r"\b([\d,]+(?:\.\d{1,2})?)\s?(?:ETB|Birr)\b",
    r"\bAmount[:\s]*([\d,]+(?:\.\d{1,2})?)\b",
]


@dataclass
class ExtractionResult:
    reference: Optional[str] = None
    amount: Optional[float] = None
    payer_name: Optional[str] = None
    payment_date_text: Optional[str] = None
    confident: bool = False
    raw_text: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self))


def extract_from_text(text: str) -> ExtractionResult:
    """Heuristic extraction from a plain-text caption or forwarded SMS."""
    result = ExtractionResult(raw_text=text or "")
    if not text:
        return result

    for pattern in REFERENCE_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            result.reference = m.group(1).upper()
            break

    for pattern in AMOUNT_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            try:
                result.amount = float(m.group(1).replace(",", ""))
            except ValueError:
                pass
            break

    # Confident only if we found BOTH a plausible reference and an amount.
    result.confident = bool(result.reference and result.amount)
    return result


def extract_from_file(file_path: str) -> ExtractionResult:
    """
    Extension point for real OCR (pytesseract, cloud Vision API, etc).
    Without an OCR engine configured, we cannot reliably read numbers out
    of an image, so we deliberately return an unconfident, empty result -
    this guarantees the payment goes to MANUAL_REVIEW rather than being
    incorrectly auto-approved.

    To enable OCR later:
        1. pip install pytesseract pillow
        2. Install the tesseract binary on the host OS.
        3. Replace the body below with an actual OCR call, then run the
           extracted text through `extract_from_text()`.
    """
    try:
        import pytesseract  # type: ignore
        from PIL import Image  # type: ignore

        if file_path.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            text = pytesseract.image_to_string(Image.open(file_path))
            return extract_from_text(text)
    except Exception:
        pass

    return ExtractionResult(confident=False, raw_text="")


def combine(*results: ExtractionResult) -> ExtractionResult:
    """Merge several extraction attempts, preferring the first confident hit."""
    for r in results:
        if r.confident:
            return r
    # Return the most complete unconfident guess for the admin's reference,
    # without ever flipping confident=True ourselves.
    merged = ExtractionResult()
    for r in results:
        merged.reference = merged.reference or r.reference
        merged.amount = merged.amount or r.amount
        merged.payer_name = merged.payer_name or r.payer_name
        merged.raw_text = merged.raw_text or r.raw_text
    merged.confident = False
    return merged
