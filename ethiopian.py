"""
calendar_utils/ethiopian.py
---------------------------
Ethiopian <-> Gregorian calendar conversion.

The Ethiopian calendar has 13 months: 12 months of 30 days plus a
13th month (Pagume) of 5 days (6 in an Ethiopian leap year).
The Ethiopian year starts on Meskerem 1, which normally falls on
September 11th of the Gregorian calendar (September 12th before a
Gregorian leap year).

All internal storage (database) uses standard Gregorian ISO dates
(YYYY-MM-DD) so that date arithmetic, sorting, and comparisons remain
reliable and library-agnostic. Conversion to/from Ethiopian dates only
happens at the display/input boundary (Telegram messages).

This implementation does not depend on the user's phone/OS calendar
settings; it is a pure, deterministic algorithm.
"""

from dataclasses import dataclass
from datetime import date, timedelta

ETHIOPIAN_MONTHS = [
    "Meskerem", "Tikimt", "Hidar", "Tahsas", "Tir", "Yekatit",
    "Megabit", "Miazia", "Ginbot", "Sene", "Hamle", "Nehase", "Pagume",
]

JD_EPOCH_OFFSET_AMETE_MIHRET = 1723856  # Julian day number of Ethiopian epoch (Meskerem 1, year 1 EC)


def _is_gregorian_leap(year: int) -> bool:
    return (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)


def _is_ethiopian_leap(year: int) -> bool:
    # Ethiopian leap years occur every 4 years, offset so that the year
    # before a Gregorian leap year is an Ethiopian leap year.
    return year % 4 == 3


@dataclass(frozen=True)
class EthiopianDate:
    year: int
    month: int  # 1-13
    day: int

    def month_name(self) -> str:
        return ETHIOPIAN_MONTHS[self.month - 1]

    def __str__(self) -> str:
        return f"{self.year} {self.month:02d} {self.day:02d}"

    def display(self) -> str:
        """Human friendly display, e.g. '2019 Tir 05'."""
        return f"{self.year} {self.month_name()} {self.day:02d}"

    def short(self) -> str:
        """Compact numeric display, e.g. '2019/05/05'."""
        return f"{self.year}/{self.month:02d}/{self.day:02d}"

    def month_key(self) -> str:
        """Stable key identifying a rent month, e.g. '2019-05'."""
        return f"{self.year}-{self.month:02d}"


def gregorian_to_ethiopian(g_date: date) -> EthiopianDate:
    """Convert a Python `date` (Gregorian) to an EthiopianDate."""
    year, month, day = g_date.year, g_date.month, g_date.day

    # Determine the Gregorian date on which the current Ethiopian year began.
    # Ethiopian new year (Meskerem 1) falls on Sept 11 of the Gregorian
    # calendar, or Sept 12 if the *following* Gregorian year is a leap year.
    new_year_greg_year = year if (month, day) >= (9, 11) else year - 1
    # New Year's Day shifts by one when the next Gregorian Feb has a leap day
    if _is_gregorian_leap(new_year_greg_year + 1):
        new_year_month_day = (9, 12)
    else:
        new_year_month_day = (9, 11)

    ethiopian_new_year = date(new_year_greg_year, *new_year_month_day)

    days_since_new_year = (g_date - ethiopian_new_year).days

    # The Ethiopian year that begins on `ethiopian_new_year` (a Gregorian
    # date in year `new_year_greg_year`) is Gregorian year minus 7.
    ethiopian_year = new_year_greg_year - 7

    month_index = days_since_new_year // 30
    day_index = days_since_new_year % 30

    e_month = month_index + 1
    e_day = day_index + 1

    return EthiopianDate(ethiopian_year, e_month, e_day)


def ethiopian_to_gregorian(e_date: EthiopianDate) -> date:
    """Convert an EthiopianDate to a Python `date` (Gregorian)."""
    ethiopian_year = e_date.year
    # The Gregorian year in which this Ethiopian year begins (Meskerem 1)
    new_year_greg_year = ethiopian_year + 7

    if _is_gregorian_leap(new_year_greg_year + 1):
        new_year_month_day = (9, 12)
    else:
        new_year_month_day = (9, 11)

    ethiopian_new_year = date(new_year_greg_year, *new_year_month_day)

    days_offset = (e_date.month - 1) * 30 + (e_date.day - 1)
    return ethiopian_new_year + timedelta(days=days_offset)


def today_ethiopian() -> EthiopianDate:
    return gregorian_to_ethiopian(date.today())


def days_in_ethiopian_month(year: int, month: int) -> int:
    if month == 13:
        return 6 if _is_ethiopian_leap(year) else 5
    return 30


def parse_ethiopian_input(text: str) -> EthiopianDate:
    """
    Parse a user-entered Ethiopian date from flexible text formats:
      '2019 1 5', '2019/1/5', '2019-01-05', '2019 01 05'
    Raises ValueError on invalid input.
    """
    cleaned = text.strip().replace("/", " ").replace("-", " ")
    parts = [p for p in cleaned.split() if p]
    if len(parts) != 3:
        raise ValueError("Expected format: YYYY MM DD (e.g. 2019 1 5)")
    year, month, day = (int(p) for p in parts)
    if not (1 <= month <= 13):
        raise ValueError("Month must be between 1 and 13")
    max_day = days_in_ethiopian_month(year, month)
    if not (1 <= day <= max_day):
        raise ValueError(f"Day must be between 1 and {max_day} for month {month}")
    return EthiopianDate(year, month, day)


def format_month_label(year: int, month: int, with_name: bool = True) -> str:
    if with_name:
        return f"{year} {ETHIOPIAN_MONTHS[month - 1]}"
    return f"{year} {month:02d}"


def add_ethiopian_months(e_date: EthiopianDate, months: int) -> EthiopianDate:
    """Add N Ethiopian months to a date, clamping day to the target month length."""
    total = (e_date.month - 1) + months
    year = e_date.year + total // 13
    month = total % 13 + 1
    if month < 1:
        month += 13
        year -= 1
    max_day = days_in_ethiopian_month(year, month)
    day = min(e_date.day, max_day)
    return EthiopianDate(year, month, day)
