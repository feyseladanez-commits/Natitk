"""
services/backup_service.py
-----------------------------
Creates a point-in-time copy of the SQLite database using SQLite's own
online backup API (safe even while the bot is writing to the DB).
"""

import sqlite3
from datetime import datetime
from pathlib import Path

from config import config
from database import get_connection


def create_backup() -> str:
    config.BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest_path = config.BACKUPS_DIR / f"building_backup_{timestamp}.db"

    src_conn = get_connection()
    dest_conn = sqlite3.connect(str(dest_path))
    with dest_conn:
        src_conn.backup(dest_conn)
    dest_conn.close()
    return str(dest_path)


def list_backups():
    if not config.BACKUPS_DIR.exists():
        return []
    return sorted(
        [p for p in config.BACKUPS_DIR.glob("building_backup_*.db")],
        reverse=True,
    )
