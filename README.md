# Commercial Building Bot

A production-ready Telegram bot for managing **one commercial building with 30 shops**:
floors, shops, tenants, rent (tracked per Ethiopian-calendar month), payments with
duplicate-reference protection, maintenance requests, expenses, announcements,
reports, backups, and a full audit trail.

Built with `python-telegram-bot` (v21, async), SQLite (structured so PostgreSQL can
be swapped in later), and inline keyboards as the primary interface — commands exist
for every action, but buttons are how the bot is meant to be used day-to-day.

---

## 1. Features at a glance

- **Building structure**: Floors → Shops → Tenants, fully admin-managed (`/addfloor`,
  `/addshop`, `/bulkshops`, `/editshop`, `/deleteshop`).
- **Tenants**: one active tenant per shop, national ID document stored securely and
  masked in listings, only visible to admins via an explicit "View ID Document" button.
- **Rent tracked per Ethiopian month** — never as a single balance. Every shop has one
  `rent_records` row per Ethiopian month (`2019-01`, `2019-02`, ...) with its own
  amount, due date, and status (`UPCOMING` / `UNPAID` / `OVERDUE` / `PAID`).
- **Payments**:
  - Tenant selects the month, attaches a receipt (photo/PDF).
  - Best-effort extraction of the reference/amount from the receipt caption (and OCR
    if you install `pytesseract` + `Pillow` — see `services/receipt_extraction.py`).
  - **A payment is never auto-verified.** If extraction isn't fully confident, the
    tenant is asked to type the reference/amount, and either way the payment sits as
    `PENDING`/`MANUAL_REVIEW` until an administrator taps **VERIFY** or **REJECT**.
  - Duplicate reference numbers are rejected immediately, with a `UNIQUE` constraint
    at the database level (not just a Python check) plus `BEGIN IMMEDIATE`
    transactions so two near-simultaneous submissions can't both slip through.
  - Verified payments generate a PDF receipt (Ethiopian dates) and are sent to the
    tenant automatically.
  - Admins can **Reverse** a wrongly-verified payment (never silently deleted — it's
    flipped to `REVERSED` with a reason and a full audit entry) or **Reject** a
    pending one.
- **Status & reports**: `/status`, `/floorstatus`, `/shopstatus`, `/occupied`,
  `/vacant`, `/paid`, `/unpaid`, `/rentstatus`, and `/report` (Daily/Monthly/Yearly/
  Custom, exportable to CSV always, and Excel if `openpyxl` is installed).
- **Maintenance**: tenants report issues by category with photo/video; admins track
  status (New → In Progress → Completed/Rejected) and tenants are notified.
- **Expenses**: category, amount, receipt, notes — rolled into report Net Income.
- **Announcements**: admin writes once, confirms, it's broadcast to every linked
  tenant.
- **Search**: `/search <shop number | tenant name | phone | reference>`.
- **Backups**: `/backup` creates an on-demand SQLite backup via SQLite's own online
  backup API (safe even while the bot is writing).
- **Audit log**: every important admin action (shop/tenant edits, payment
  verify/reject/reverse, expense added, announcement sent, settings changed) is
  recorded with who/when/what.
- **Ethiopian calendar throughout the UI** (`calendar_utils/ethiopian.py`), while
  everything is stored internally as ISO Gregorian dates for reliable computation.
- **Security**: only Telegram IDs in `ADMIN_IDS` (env) or the `admins` table can use
  admin functions; tenants only ever see their own shop's data; ID documents and
  phone numbers are never exposed to other tenants; ID numbers are masked in listings.

---

## 2. Project structure

```
commercial_building_bot/
│
├── bot.py                  # Entry point: wires handlers together, runs polling
├── config.py                # Loads .env, exposes a single `config` object
├── database.py               # SQLite connection + transaction helpers, init_db()
├── requirements.txt
├── .env.example               # Copy to .env and fill in real values
├── .gitignore
│
├── models/
│   └── schema.sql            # Full relational schema (see section 6)
│
├── calendar_utils/
│   └── ethiopian.py          # Ethiopian <-> Gregorian date conversion
│
├── services/                 # All business logic (no Telegram objects in here)
│   ├── floor_service.py
│   ├── shop_service.py
│   ├── tenant_service.py
│   ├── rent_service.py
│   ├── payment_service.py
│   ├── receipt_extraction.py # Best-effort receipt reading (never auto-verifies)
│   ├── receipt_pdf.py        # PDF receipt generation (reportlab)
│   ├── maintenance_service.py
│   ├── expense_service.py
│   ├── announcement_service.py
│   ├── report_service.py     # CSV/Excel report export
│   ├── search_service.py
│   ├── backup_service.py
│   ├── settings_service.py   # Admin-configurable reminder timing etc.
│   ├── reminder_service.py   # Scheduled rent reminders + rollover
│   └── audit.py              # Append-only audit trail
│
├── keyboards/
│   └── keyboards.py          # Every inline keyboard builder lives here
│
├── handlers/                  # Telegram-facing logic only
│   ├── common.py             # /start dispatch, menu router, back/cancel
│   ├── admin_floors.py
│   ├── admin_shops.py
│   ├── admin_tenants.py
│   ├── admin_payments.py
│   ├── admin_status.py
│   ├── admin_maintenance.py
│   ├── admin_expenses.py
│   ├── admin_announcement.py
│   ├── admin_reports.py
│   ├── admin_misc.py         # /search, /backup, /settings
│   ├── tenant_menu.py        # Tenant self-service menu
│   ├── tenant_payment.py     # "Make Payment" flow
│   └── tenant_maintenance.py # "Report Maintenance" flow
│
├── utils/
│   ├── auth.py                # admin_only decorator, masking helpers
│   └── validators.py         # Input validation, bulk-shop parsing
│
└── storage/                   # Created automatically; kept out of git
    ├── documents/             # Tenant ID documents (private, admin-only)
    ├── receipts/              # Uploaded payment receipts + generated PDFs
    ├── backups/               # Database backups + exported reports
    └── attachments/           # Maintenance/expense attachments
```

---

## 3. Requirements

- Python 3.10+
- A Telegram bot token from **@BotFather**
- (Optional) `tesseract-ocr` installed on the host + `pip install pytesseract pillow`
  if you want automatic text extraction from receipt **images** rather than just
  captions. Without it, image-only receipts with no caption text correctly fall back
  to `MANUAL_REVIEW` — nothing is ever silently mis-verified.

---

## 4. Getting a bot token (BotFather)

1. Open Telegram and start a chat with **@BotFather**.
2. Send `/newbot`.
3. Choose a display name (e.g. "Merkato Building Manager") and a unique username
   ending in `bot` (e.g. `merkato_building_bot`).
4. BotFather replies with an API token that looks like
   `123456789:AAExxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` — copy it.
5. (Optional but recommended) Send `/setprivacy` to BotFather, select your bot, and
   choose **Disable** so the bot only needs to react to commands/buttons it's given
   (not required for this bot since it doesn't read group chats, but harmless).
6. Find your own numeric Telegram ID by messaging **@userinfobot** — you'll need this
   for `ADMIN_IDS`.

---

## 5. Installation

```bash
# 1. Clone/copy the project, then enter it
cd commercial_building_bot

# 2. Create a virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env:
#   BOT_TOKEN=<token from BotFather>
#   ADMIN_IDS=<your numeric Telegram ID, comma-separated for multiple admins>

# 5. Run the bot
python bot.py
```

The database (`storage/building.db`) and all `storage/` subfolders are created
automatically on first run — no manual migration step needed for the initial
SQLite version.

Send `/start` to your bot from the admin's Telegram account to see the admin
dashboard.

### Linking a tenant's Telegram account

The bot links tenants to shops by Telegram numeric ID, not by phone number (Telegram
doesn't expose a tenant's phone number to the bot). The simplest flow:

1. Ask the tenant to message the bot with `/start`. The bot will reply with their
   Telegram ID (since it doesn't yet recognize them) and ask them to share it with
   the administrator.
2. As admin, when running `/addtenant` (or the "➕ Add Tenant" button), the tenant
   record is created with the shop/name/phone/ID details you enter. To link their
   Telegram account so they can use the tenant menu, update the tenant's
   `telegram_id` column — either extend `/edittenant` with a "Link Telegram ID"
   field (the field list in `handlers/admin_tenants.py` → `TENANT_EDITABLE` is a
   good place to add it) or set it directly once during onboarding. This is called
   out here because the "tenant self-service" side of the spec assumes tenants have
   already been linked; the building admin controls exactly when/how that happens.

---

## 6. Database schema

SQLite is used for the initial version, but all SQL lives behind `database.py` and
`services/*.py` — swapping to PostgreSQL later means changing `get_connection()` in
`database.py` (e.g. to `psycopg2`/`asyncpg`) and adjusting the few SQLite-specific
bits in `models/schema.sql` (`AUTOINCREMENT`, `datetime('now')`). No handler or
service code talks to the database with raw SQL scattered around — it's centralized.

Key tables (see `models/schema.sql` for full DDL):

| Table | Purpose |
|---|---|
| `admins` | Additional admin Telegram IDs beyond `ADMIN_IDS` in `.env` |
| `floors` | Building floors |
| `shops` | Shop number (unique), floor, size, rent, status |
| `tenants` | One active tenant per shop (enforced by a partial unique index) |
| `tenant_documents` | Scanned ID documents, admin-only access |
| `rent_records` | One row per (shop, Ethiopian month) — never a running balance |
| `payments` | Linked to shop, tenant, rent month, with a **UNIQUE** reference |
| `payment_references` | Reference-lock table backing the duplicate-payment check |
| `maintenance_requests` | Tenant-reported issues + status lifecycle |
| `expenses` | Building operating expenses |
| `announcements` | Sent building-wide notices, with recipient counts |
| `audit_logs` | Append-only log of every important admin action |
| `settings` | Admin-configurable values (reminder timing, etc.) |

Race-condition safety: `database.transaction()` uses `BEGIN IMMEDIATE`, so when two
tenants submit the same payment reference at nearly the same instant, SQLite forces
the second writer to wait for the first transaction to finish — the first commits,
the second then sees the reference already exists and is correctly rejected. This is
backed by a database-level `UNIQUE` constraint, not just an application-level check.

---

## 7. Ethiopian calendar

`calendar_utils/ethiopian.py` implements the standard Amete Mihret Ethiopian
calendar conversion (13 months, leap-year rule tied to the Gregorian leap cycle).
Dates are **stored internally as Gregorian ISO strings** (`YYYY-MM-DD`) for reliable
arithmetic and sorting, and converted to Ethiopian only for display — so date math
(due dates, "3 months ahead", overdue checks) never has to reason in the Ethiopian
system directly, but everything the tenant/admin actually reads is in Ethiopian
dates, e.g. `2019 Meskerem 02`.

---

## 8. Admin commands

All of these also have an equivalent inline-keyboard button reachable from `/admin`.

```
/start /admin
/addfloor /floors
/addshop /editshop /deleteshop /shops /shopinfo /bulkshops
/addtenant /edittenant /deletetenant /tenantinfo
/status /floorstatus /shopstatus /occupied /vacant /paid /unpaid /paymentstatus
/usedrefs /addpayment /paymenthistory /rentstatus
/maintenance /expenses /report /announcement /search /backup /settings
/cancel   (works both as a command and via the "❌ Cancel" button, at any step)
```

Tenant menu (via `/start`, once linked): 🏪 My Shop · 💰 My Rent · 📜 Rent History ·
🧾 My Receipts · 💳 Make Payment · 🛠 Report Maintenance · 📢 Building Notices ·
📞 Contact Management.

---

## 9. Scheduled jobs

`bot.py` registers two background jobs on the `python-telegram-bot` `JobQueue`
(backed by APScheduler, installed via the `job-queue` extra in `requirements.txt`):

- **Rollover** (every 6 hours): keeps overdue statuses accurate and pre-creates the
  next few months of rent records for every active tenant.
- **Reminders** (once a day): sends a 🔔 rent reminder to any tenant whose rent due
  date is exactly `reminder_days_before` days away (configurable via `/settings`,
  default from `REMINDER_DAYS_BEFORE` in `.env`) — once per due date, not every day.

---

## 10. Security notes

- Admin-only handlers are wrapped with the `@admin_only` decorator
  (`utils/auth.py`), checked against `ADMIN_IDS` in `.env` plus the `admins` table.
- Tenant ID documents are stored under `storage/documents/` (excluded from git via
  `.gitignore`) and are only ever sent back to a Telegram chat when an admin taps
  "View ID Document" — never shown to other tenants, never included in normal
  listings (which show a masked ID like `******789`).
- Payment receipts and generated PDFs live under `storage/receipts/`, also
  git-ignored.
- Change `SECRET_KEY` in `.env` before any real deployment.
- `.env` itself must never be committed — it's already in `.gitignore`.

---

## 11. Backups

Run `/backup` at any time (or wire up a cron job / systemd timer calling
`services.backup_service.create_backup()` on a schedule) to get a timestamped copy
of the database in `storage/backups/`. Because it uses SQLite's own online backup
API, it's safe to run while the bot is live and writing.

---

## 12. Extending

- **PostgreSQL later**: replace `sqlite3.connect(...)` in `database.py` with your
  driver of choice, keep `get_connection()`/`transaction()` returning the same
  cursor-like interface, and update the handful of SQLite-specific SQL bits in
  `models/schema.sql`. Nothing in `services/` or `handlers/` needs to change if you
  keep the same row-mapping (`sqlite3.Row` → dict-like access by column name).
- **Real OCR**: install `pytesseract` + `Pillow` and the `tesseract-ocr` system
  package; `services/receipt_extraction.py` already has the extension point wired
  in and will use it automatically once available — payments still only ever
  auto-populate fields, never auto-verify.
- **Multiple admins**: add rows to the `admins` table (or extend `ADMIN_IDS` in
  `.env`) — no code changes needed.

---

## 13. Known follow-ups worth doing before a production launch

- Add a "link Telegram ID" step to `/edittenant` so admins don't need to touch the
  database directly to connect a tenant's Telegram account (see section 5).
- Wire `services/backup_service.create_backup()` into an OS-level scheduler
  (cron/systemd timer) if you want automatic (not just on-demand) backups.
- If you expect heavy concurrent write load, consider moving from SQLite/WAL to
  PostgreSQL sooner rather than later — the code is already structured for that
  migration (see section 12).
