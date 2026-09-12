"""
config.py
---------
Central configuration for the Commercial Building Bot.

All secrets and environment-specific values are loaded from a `.env` file
(never hard-coded). Copy `.env.example` to `.env` and fill in real values
before running the bot.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _get_admin_ids() -> set:
    raw = os.getenv("ADMIN_IDS", "")
    ids = set()
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if chunk.isdigit():
            ids.add(int(chunk))
    return ids


class Config:
    # --- Telegram ---
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    ADMIN_IDS: set = _get_admin_ids()

    # --- Database ---
    # Stored as a SQLite path today. database.py isolates all SQL so that
    # swapping to PostgreSQL later only requires changing that one module.
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///storage/building.db")

    @property
    def sqlite_path(self) -> str:
        # Extract the filesystem path out of a sqlite:/// URL
        if self.DATABASE_URL.startswith("sqlite:///"):
            path = self.DATABASE_URL.replace("sqlite:///", "", 1)
            full = BASE_DIR / path
            full.parent.mkdir(parents=True, exist_ok=True)
            return str(full)
        # Fallback default
        default = BASE_DIR / "storage" / "building.db"
        default.parent.mkdir(parents=True, exist_ok=True)
        return str(default)

    # --- Security ---
    SECRET_KEY: str = os.getenv("SECRET_KEY", "insecure-default-change-me")

    # --- Building ---
    BUILDING_NAME: str = os.getenv("BUILDING_NAME", "Commercial Building")
    TOTAL_SHOPS: int = int(os.getenv("TOTAL_SHOPS", "30"))
    CURRENCY: str = os.getenv("CURRENCY", "ETB")
    RENT_DUE_DAY: int = int(os.getenv("RENT_DUE_DAY", "5"))
    REMINDER_DAYS_BEFORE: int = int(os.getenv("REMINDER_DAYS_BEFORE", "3"))
    TIMEZONE: str = os.getenv("TIMEZONE", "Africa/Addis_Ababa")

    # --- Storage paths ---
    STORAGE_DIR = BASE_DIR / "storage"
    DOCUMENTS_DIR = STORAGE_DIR / "documents"      # tenant ID documents (private)
    RECEIPTS_DIR = STORAGE_DIR / "receipts"        # uploaded payment receipts
    ATTACHMENTS_DIR = STORAGE_DIR / "attachments"  # maintenance/expense attachments
    BACKUPS_DIR = STORAGE_DIR / "backups"

    def ensure_dirs(self):
        for d in (self.DOCUMENTS_DIR, self.RECEIPTS_DIR, self.ATTACHMENTS_DIR, self.BACKUPS_DIR):
            d.mkdir(parents=True, exist_ok=True)


config = Config()
config.ensure_dirs()

if not config.BOT_TOKEN:
    # We don't raise here so that unit-testing modules that only need config
    # doesn't explode, but bot.py checks this before starting polling.
    pass
