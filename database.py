"""
database.py
-----------
SQLite connection management and schema initialization.

All raw SQL lives behind this module and services/*.py so that migrating
to PostgreSQL later only requires changing `get_connection()` and any
SQLite-specific syntax (AUTOINCREMENT, `datetime('now')`, etc.) in
models/schema.sql. Business logic in services/ and handlers/ talks to
the database only through parameterized queries here.
"""

import sqlite3
import contextlib
import threading
from pathlib import Path

from config import config

_local = threading.local()


def get_connection() -> sqlite3.Connection:
    """
    Return a connection scoped to the current thread.
    python-telegram-bot's default executor uses a small thread pool, so a
    thread-local connection is a simple, safe way to avoid SQLite's
    "not created in this thread" errors while still getting real
    transactional behaviour (BEGIN IMMEDIATE) for race-condition safety.
    """
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(
            config.sqlite_path,
            timeout=30,
            isolation_level=None,  # autocommit; we manage transactions explicitly
            check_same_thread=True,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA busy_timeout = 30000;")
        _local.conn = conn
    return conn


@contextlib.contextmanager
def transaction():
    """
    Context manager providing a safe, exclusive write transaction.

    Uses BEGIN IMMEDIATE so that two near-simultaneous payment submissions
    (the exact race condition called out in the spec — duplicate payment
    references) cannot both proceed past the uniqueness check before
    either commits. SQLite will make the second caller wait for the lock,
    then its own UNIQUE constraint / pre-check will correctly reject the
    duplicate.
    """
    conn = get_connection()
    conn.execute("BEGIN IMMEDIATE;")
    try:
        yield conn
        conn.execute("COMMIT;")
    except Exception:
        conn.execute("ROLLBACK;")
        raise


def init_db():
    """Create all tables if they do not already exist."""
    schema_path = Path(__file__).resolve().parent / "models" / "schema.sql"
    sql = schema_path.read_text(encoding="utf-8")
    conn = get_connection()
    conn.executescript(sql)


def close_all():
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None
