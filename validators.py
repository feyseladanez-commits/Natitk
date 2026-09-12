"""
utils/validators.py
--------------------
Input validation helpers shared across handlers.
"""

import re


class ValidationError(Exception):
    pass


def validate_positive_number(text: str, field_name: str = "value") -> float:
    try:
        value = float(str(text).replace(",", "").strip())
    except ValueError:
        raise ValidationError(f"{field_name} must be a number.")
    if value <= 0:
        raise ValidationError(f"{field_name} must be greater than zero.")
    return value


def validate_shop_number(text: str) -> str:
    text = text.strip()
    if not text:
        raise ValidationError("Shop number cannot be empty.")
    if not re.match(r"^[A-Za-z0-9\-]{1,10}$", text):
        raise ValidationError("Shop number may only contain letters, numbers and '-' (max 10 chars).")
    return text


def validate_phone(text: str) -> str:
    text = text.strip().replace(" ", "")
    if not re.match(r"^\+?\d{7,15}$", text):
        raise ValidationError("Enter a valid phone number (digits only, 7-15 digits).")
    return text


def validate_non_empty(text: str, field_name: str = "value") -> str:
    text = text.strip()
    if not text:
        raise ValidationError(f"{field_name} cannot be empty.")
    return text


def parse_bulk_shops(text: str):
    """
    Parse the /bulkshops free-text block:

        Ground Floor
        01,32,20000
        02,28,18000

        1st Floor
        04,35,22000

    Returns a list of dicts: [{"floor": str, "shop_number": str,
    "size_sqm": float, "monthly_rent": float}, ...]
    Raises ValidationError with a clear message on the first problem found.
    """
    lines = [ln.rstrip() for ln in text.splitlines()]
    result = []
    current_floor = None
    seen_shop_numbers = set()

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        if "," in line:
            if current_floor is None:
                raise ValidationError(
                    f"Shop line '{line}' appears before any floor name was given."
                )
            parts = [p.strip() for p in line.split(",")]
            if len(parts) != 3:
                raise ValidationError(
                    f"Invalid shop line: '{line}'. Expected: shop_number,size_sqm,monthly_rent"
                )
            shop_number, size_str, rent_str = parts
            shop_number = validate_shop_number(shop_number)
            if shop_number in seen_shop_numbers:
                raise ValidationError(f"Duplicate shop number in input: {shop_number}")
            seen_shop_numbers.add(shop_number)
            size_sqm = validate_positive_number(size_str, f"Size for shop {shop_number}")
            monthly_rent = validate_positive_number(rent_str, f"Rent for shop {shop_number}")
            result.append(
                {
                    "floor": current_floor,
                    "shop_number": shop_number,
                    "size_sqm": size_sqm,
                    "monthly_rent": monthly_rent,
                }
            )
        else:
            # A line with no comma is treated as a floor name
            current_floor = validate_non_empty(line, "Floor name")

    if not result:
        raise ValidationError("No valid shop lines were found in the input.")
    return result
