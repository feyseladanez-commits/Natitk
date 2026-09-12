"""
services/settings_service.py
-------------------------------
Small key/value settings store (see `settings` table in schema.sql),
letting the administrator configure behaviour such as reminder timing
without editing the .env file. Falls back to config.py defaults if a
key has not been set yet.
"""

from database import get_connection, transaction
from services.audit import log_action
from config import config

DEFAULTS = {
    "reminder_days_before": str(config.REMINDER_DAYS_BEFORE),
    "rent_due_day": str(config.RENT_DUE_DAY),
    "allow_multi_shop_tenant": "0",
}


def get_setting(key: str) -> str:
    conn = get_connection()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row is not None and row["value"] is not None:
        return row["value"]
    return DEFAULTS.get(key, "")


def get_int(key: str) -> int:
    try:
        return int(get_setting(key))
    except (TypeError, ValueError):
        return int(DEFAULTS.get(key, 0))


def get_bool(key: str) -> bool:
    return get_setting(key) in ("1", "true", "True")


def set_setting(key: str, value: str, admin_id: int):
    with transaction() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )
        log_action(admin_id, "SETTING_CHANGED", "settings", None, f"{key}={value}", conn=conn)


def all_settings() -> dict:
    conn = get_connection()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    merged = dict(DEFAULTS)
    merged.update({r["key"]: r["value"] for r in rows})
    return merged
