"""
keyboards/keyboards.py
-------------------------
All inline keyboard builders live here so handlers stay focused on logic.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

PAGE_SIZE = 8


def admin_main_menu():
    rows = [
        [InlineKeyboardButton("🏪 Shops", callback_data="menu:shops"),
         InlineKeyboardButton("👥 Tenants", callback_data="menu:tenants")],
        [InlineKeyboardButton("💰 Rent", callback_data="menu:rent"),
         InlineKeyboardButton("💳 Payments", callback_data="menu:payments")],
        [InlineKeyboardButton("📊 Status", callback_data="menu:status"),
         InlineKeyboardButton("🛠 Maintenance", callback_data="menu:maintenance")],
        [InlineKeyboardButton("💸 Expenses", callback_data="menu:expenses"),
         InlineKeyboardButton("📢 Announcements", callback_data="menu:announce")],
        [InlineKeyboardButton("📄 Reports", callback_data="menu:reports"),
         InlineKeyboardButton("🔍 Search", callback_data="menu:search")],
        [InlineKeyboardButton("💾 Backup", callback_data="menu:backup"),
         InlineKeyboardButton("⚙️ Settings", callback_data="menu:settings")],
    ]
    return InlineKeyboardMarkup(rows)


def tenant_main_menu():
    rows = [
        [InlineKeyboardButton("🏪 My Shop", callback_data="t:myshop")],
        [InlineKeyboardButton("💰 My Rent", callback_data="t:myrent"),
         InlineKeyboardButton("📜 Rent History", callback_data="t:history")],
        [InlineKeyboardButton("🧾 My Receipts", callback_data="t:receipts"),
         InlineKeyboardButton("💳 Make Payment", callback_data="t:pay")],
        [InlineKeyboardButton("🛠 Report Maintenance", callback_data="t:maintenance")],
        [InlineKeyboardButton("📢 Building Notices", callback_data="t:notices"),
         InlineKeyboardButton("📞 Contact Management", callback_data="t:contact")],
    ]
    return InlineKeyboardMarkup(rows)


def back_cancel(back_cb="back:main", include_cancel=True):
    row = [InlineKeyboardButton("⬅️ Back", callback_data=back_cb)]
    if include_cancel:
        row.append(InlineKeyboardButton("❌ Cancel", callback_data="cancel"))
    return InlineKeyboardMarkup([row])


def confirm_cancel(confirm_cb="confirm", cancel_cb="cancel"):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ CONFIRM", callback_data=confirm_cb),
         InlineKeyboardButton("❌ CANCEL", callback_data=cancel_cb)]
    ])


def floors_menu(floors, prefix="floor", extra_back="back:main"):
    rows = [[InlineKeyboardButton(f["name"], callback_data=f"{prefix}:{f['id']}")] for f in floors]
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=extra_back)])
    return InlineKeyboardMarkup(rows)


def shops_list_menu(shops, page=0, prefix="shop", back_cb="back:main"):
    start = page * PAGE_SIZE
    page_items = shops[start:start + PAGE_SIZE]
    rows = []
    for s in page_items:
        status_dot = "🟢" if s["status"] == "OCCUPIED" else "⚪"
        rows.append([InlineKeyboardButton(
            f"{status_dot} Shop {s['shop_number']}", callback_data=f"{prefix}:{s['id']}"
        )])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"{prefix}page:{page-1}"))
    if start + PAGE_SIZE < len(shops):
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"{prefix}page:{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=back_cb)])
    return InlineKeyboardMarkup(rows)


def shop_detail_menu(shop_id, has_tenant: bool):
    rows = [
        [InlineKeyboardButton("📜 Rent History", callback_data=f"renthist:{shop_id}"),
         InlineKeyboardButton("💳 Payments", callback_data=f"shoppay:{shop_id}")],
    ]
    if has_tenant:
        rows.append([InlineKeyboardButton("👤 Tenant", callback_data=f"tenantview:{shop_id}")])
    else:
        rows.append([InlineKeyboardButton("➕ Add Tenant", callback_data=f"addtenant:{shop_id}")])
    rows.append([InlineKeyboardButton("🛠 Maintenance", callback_data=f"shopmaint:{shop_id}"),
                 InlineKeyboardButton("✏️ Edit Shop", callback_data=f"editshop:{shop_id}")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="menu:shops")])
    return InlineKeyboardMarkup(rows)


def yes_no(yes_cb, no_cb):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("YES", callback_data=yes_cb),
         InlineKeyboardButton("CANCEL", callback_data=no_cb)]
    ])


def payment_review_actions(payment_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ VERIFY", callback_data=f"payverify:{payment_id}"),
         InlineKeyboardButton("❌ REJECT", callback_data=f"payreject:{payment_id}")],
        [InlineKeyboardButton("🔁 REQUEST NEW RECEIPT", callback_data=f"payrenew:{payment_id}")],
    ])


def maintenance_categories():
    from services.maintenance_service import CATEGORIES
    rows = [[InlineKeyboardButton(label, callback_data=f"maintcat:{key}")]
            for key, label in CATEGORIES.items()]
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="back:tenant_main")])
    return InlineKeyboardMarkup(rows)


def maintenance_status_actions(request_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟡 In Progress", callback_data=f"maintstatus:{request_id}:IN_PROGRESS"),
         InlineKeyboardButton("🟢 Completed", callback_data=f"maintstatus:{request_id}:COMPLETED")],
        [InlineKeyboardButton("❌ Rejected", callback_data=f"maintstatus:{request_id}:REJECTED")],
    ])


def report_period_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Daily", callback_data="report:DAILY"),
         InlineKeyboardButton("Monthly", callback_data="report:MONTHLY")],
        [InlineKeyboardButton("Yearly", callback_data="report:YEARLY"),
         InlineKeyboardButton("Custom Period", callback_data="report:CUSTOM")],
        [InlineKeyboardButton("⬅️ Back", callback_data="back:main")],
    ])


def report_export_menu(period, start, end):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📄 Export CSV", callback_data=f"reportcsv:{period}:{start}:{end}"),
         InlineKeyboardButton("📊 Export Excel", callback_data=f"reportxlsx:{period}:{start}:{end}")],
        [InlineKeyboardButton("⬅️ Back", callback_data="menu:reports")],
    ])
