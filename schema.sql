-- =========================================================
-- Commercial Building Bot - Database Schema (SQLite)
-- Written in plain, portable SQL so migrating to PostgreSQL
-- later mainly requires swapping AUTOINCREMENT / PRAGMA lines.
-- =========================================================

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------
-- admins: authorized administrator Telegram accounts
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS admins (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id     INTEGER NOT NULL UNIQUE,
    full_name       TEXT,
    is_super_admin  INTEGER NOT NULL DEFAULT 0,
    added_at        TEXT NOT NULL DEFAULT (datetime('now')),
    active          INTEGER NOT NULL DEFAULT 1
);

-- ---------------------------------------------------------
-- floors
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS floors (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------
-- shops
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS shops (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_number  TEXT NOT NULL UNIQUE,
    floor_id     INTEGER NOT NULL REFERENCES floors(id) ON DELETE RESTRICT,
    size_sqm     REAL NOT NULL CHECK (size_sqm > 0),
    monthly_rent REAL NOT NULL CHECK (monthly_rent > 0),
    status       TEXT NOT NULL DEFAULT 'VACANT' CHECK (status IN ('VACANT','OCCUPIED')),
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------
-- tenants (one active tenant per shop, enforced in code + partial index)
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS tenants (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id             INTEGER NOT NULL REFERENCES shops(id) ON DELETE RESTRICT,
    full_name           TEXT NOT NULL,
    phone               TEXT NOT NULL,
    telegram_id         INTEGER UNIQUE,           -- linked once tenant starts the bot & is verified
    id_type             TEXT,
    id_number           TEXT,                     -- stored full; always masked on display
    contract_start      TEXT NOT NULL,             -- Gregorian ISO date (YYYY-MM-DD)
    contract_end        TEXT,                      -- Gregorian ISO date (YYYY-MM-DD), nullable
    notes               TEXT,
    active              INTEGER NOT NULL DEFAULT 1,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Only one ACTIVE tenant allowed per shop at a time
CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_tenant_per_shop
    ON tenants(shop_id) WHERE active = 1;

-- ---------------------------------------------------------
-- tenant_documents: securely stored ID scans (admin-only access)
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS tenant_documents (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id     INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    file_path     TEXT NOT NULL,       -- path under storage/documents (never a public folder)
    telegram_file_id TEXT,             -- Telegram's own file_id for quick re-send
    doc_type      TEXT NOT NULL DEFAULT 'NATIONAL_ID',
    uploaded_by   INTEGER,             -- admin telegram_id who uploaded/attached it
    uploaded_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------
-- rent_records: one row per shop per Ethiopian rent month
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS rent_records (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id         INTEGER NOT NULL REFERENCES shops(id) ON DELETE RESTRICT,
    tenant_id       INTEGER REFERENCES tenants(id) ON DELETE SET NULL,
    rent_month_key  TEXT NOT NULL,      -- Ethiopian month key e.g. '2019-01'
    amount_due      REAL NOT NULL CHECK (amount_due >= 0),
    due_date_greg   TEXT NOT NULL,      -- Gregorian ISO date the rent is due
    status          TEXT NOT NULL DEFAULT 'UNPAID' CHECK (status IN ('UNPAID','PAID','UPCOMING','OVERDUE')),
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (shop_id, rent_month_key)
);

-- ---------------------------------------------------------
-- payments
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS payments (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id             INTEGER NOT NULL REFERENCES shops(id) ON DELETE RESTRICT,
    tenant_id           INTEGER REFERENCES tenants(id) ON DELETE SET NULL,
    rent_record_id      INTEGER REFERENCES rent_records(id) ON DELETE SET NULL,
    rent_month_key      TEXT NOT NULL,
    amount              REAL NOT NULL CHECK (amount > 0),
    reference           TEXT NOT NULL UNIQUE,   -- UNIQUE at the DB level (critical requirement)
    payment_date_greg   TEXT,                   -- Gregorian ISO date of the payment
    receipt_file_path   TEXT,                   -- uploaded receipt image/pdf
    telegram_file_id    TEXT,
    extracted_data_json TEXT,                   -- raw OCR/extraction output, for audit
    status              TEXT NOT NULL DEFAULT 'PENDING'
                         CHECK (status IN ('PENDING','VERIFIED','REJECTED','MANUAL_REVIEW','DUPLICATE','REVERSED')),
    submitted_by        INTEGER,                -- telegram_id of submitter (tenant)
    verified_by         INTEGER,                -- telegram_id of admin who verified/rejected
    verified_at         TEXT,
    rejection_reason    TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------
-- payment_references: append-only ledger of every reference ever used,
-- kept even if a payment is later reversed, for full traceability.
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS payment_references (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    reference    TEXT NOT NULL UNIQUE,
    payment_id   INTEGER NOT NULL REFERENCES payments(id) ON DELETE RESTRICT,
    shop_id      INTEGER NOT NULL REFERENCES shops(id) ON DELETE RESTRICT,
    locked       INTEGER NOT NULL DEFAULT 1,   -- 1 = cannot be reused; released only via explicit admin action
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------
-- maintenance_requests
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS maintenance_requests (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id      INTEGER NOT NULL REFERENCES shops(id) ON DELETE RESTRICT,
    tenant_id    INTEGER REFERENCES tenants(id) ON DELETE SET NULL,
    category     TEXT NOT NULL,   -- ELECTRICITY / WATER / TOILET / DOOR_WINDOW / DAMAGE / CLEANING / OTHER
    description  TEXT,
    photo_file_id TEXT,
    video_file_id TEXT,
    status       TEXT NOT NULL DEFAULT 'NEW' CHECK (status IN ('NEW','IN_PROGRESS','COMPLETED','REJECTED')),
    reported_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------
-- expenses
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS expenses (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    category     TEXT NOT NULL,   -- ELECTRICITY / WATER / CLEANING / SECURITY / MAINTENANCE / OTHER
    description  TEXT,
    amount       REAL NOT NULL CHECK (amount > 0),
    expense_date_greg TEXT NOT NULL,
    receipt_file_id   TEXT,
    notes        TEXT,
    recorded_by  INTEGER,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------
-- announcements
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS announcements (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    message      TEXT NOT NULL,
    sent_by      INTEGER,
    recipients_count INTEGER NOT NULL DEFAULT 0,
    sent_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------
-- audit_logs: append-only log of every important admin action
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_logs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_telegram_id INTEGER,
    action         TEXT NOT NULL,
    related_table  TEXT,
    related_id     INTEGER,
    details        TEXT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------
-- settings: simple key/value store for configurable behaviour
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS settings (
    key    TEXT PRIMARY KEY,
    value  TEXT
);

INSERT OR IGNORE INTO settings (key, value) VALUES ('reminder_days_before', '3');
INSERT OR IGNORE INTO settings (key, value) VALUES ('rent_due_day', '5');
INSERT OR IGNORE INTO settings (key, value) VALUES ('allow_multi_shop_tenant', '0');

CREATE INDEX IF NOT EXISTS idx_shops_floor ON shops(floor_id);
CREATE INDEX IF NOT EXISTS idx_tenants_shop ON tenants(shop_id);
CREATE INDEX IF NOT EXISTS idx_rent_records_shop ON rent_records(shop_id);
CREATE INDEX IF NOT EXISTS idx_payments_shop ON payments(shop_id);
CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status);
CREATE INDEX IF NOT EXISTS idx_maintenance_shop ON maintenance_requests(shop_id);
