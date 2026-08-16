"""Compendium — household task/project manager for the Vixinman household.

Piece 1: Flask skeleton backed by SQLite; home page lists client profiles.
Piece 2: "New client" form and individual client profile pages.
Piece 3: project profiles stored under each client.
Piece 4: rules engine — project selections resolve to required licenses,
permits, and compliance items; service tickets; exportable project report.
Piece 33: the multi-client model (Pieces 1-3 above) was removed — projects
belong to the household directly now; the home page is the dashboard.

Run it:
    python -m pip install -r requirements.txt
    python app.py
then open http://127.0.0.1:5000 in your browser.
"""

import json
import math
import os
import random
import re
import sqlite3
import sys
import threading
import uuid
from datetime import datetime, timedelta, date
from pathlib import Path

from functools import wraps

from flask import (
    Flask, Response, abort, flash, g, jsonify, redirect, render_template,
    request, session, send_from_directory, url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from bpmn_export import build_project_bpmn
from nm_directory import (
    COUNTIES_ALL, CORRECTIONS_V10, CORRECTIONS_V11, COUNTY_UTILITIES,
    NEW_RULES_V10, UTILITIES_ALL,
)
from loads_seed import APPLIANCE_SEED, COMPONENT_SEED
from inventory_seed import (
    INVENTORY_VENDORS, INVENTORY_CATEGORY_SPECS, INVENTORY_ITEMS,
    INVENTORY_TOOLS, INVENTORY_VEHICLES,
)
from inventory_research import (
    RESEARCH, RESEARCH_VERSION, TOOLS_RESEARCH, TOOLS_RESEARCH_VERSION,
)
import barcodes
import ai_assistant  # Piece 32.0: Compendium AI assistant (Claude / Gemini)

# Code assets (schema.sql, templates) sit next to this file — except under
# a PyInstaller desktop build, where they're unpacked into sys._MEIPASS.
BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
# The writable data (database + uploaded files) lives in DATA_DIR. Normally
# that's the same folder; the desktop launcher points COMPENDIUM_DATA_DIR at a
# stable per-user folder so a packaged app doesn't lose data on update.
DATA_DIR = Path(os.environ.get("COMPENDIUM_DATA_DIR", BASE_DIR))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DATABASE = DATA_DIR / "job_creator.db"

# ------------------------------------------------------- household idea backlog
def ensure_backlog_reminders(db):
    """Piece 33: reminders for the household idea backlog, replacing the old
    lead follow-up cadence. Two independent, idempotent nudges through the
    existing notifications inbox: (1) once a month, a single "review your
    backlog" notice if anything is still sitting in Backlog; (2) per-idea, an
    optional custom reminder_date fires once. Called both on dashboard load
    and from the background scheduler (run_maintenance) — the latter has no
    request/app context, so this builds plain link paths, not url_for."""
    recipients = [r["id"] for r in db.execute(
        "SELECT id FROM household_members WHERE COALESCE(username,'') != ''").fetchall()]
    if not recipients:
        return
    made = False
    today = datetime.now().strftime("%Y-%m-%d")
    this_month = today[:7]
    backlog_count = db.execute(
        "SELECT COUNT(*) FROM household_ideas WHERE status = 'Backlog'").fetchone()[0]
    if backlog_count:
        last_sent = db.execute(
            "SELECT value FROM meta WHERE key = 'backlog_review_last_sent'").fetchone()
        if not last_sent or last_sent["value"] != this_month:
            notify_employees(
                db, recipients,
                f"🗂 Time to review the household idea backlog"
                f" ({backlog_count} waiting).",
                link="/backlog", kind="backlog_review")
            db.execute(
                "INSERT INTO meta (key, value) VALUES"
                " ('backlog_review_last_sent', ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (this_month,))
            made = True
    for idea in db.execute(
            "SELECT id, name FROM household_ideas WHERE status = 'Backlog'"
            " AND reminder_date != '' AND reminder_date <= ?"
            " AND COALESCE(reminder_sent, '') != '1'", (today,)).fetchall():
        notify_employees(
            db, recipients, f"💡 Reminder: {idea['name']}",
            link=f"/backlog/{idea['id']}", kind="backlog_idea")
        db.execute("UPDATE household_ideas SET reminder_sent = '1' WHERE id = ?",
                   (idea["id"],))
        made = True
    if made:
        db.commit()


# Project profile columns (products is stored as a comma-separated list).
PROJECT_FIELDS = [
    "job_name", "site_location", "county", "electric_loads", "utility_provider",
    "warranty_type", "cost_method", "tax_credit", "expand_option", "products",
    "pv_utility_connection", "pv_mounting_type", "pv_manufactured_house",
    "generator_utility_connection", "battery_utility_connection", "service_type",
    "property_type",
]

# Labels used on the report and anywhere a field needs a human name.
PROJECT_FIELD_LABELS = {
    "job_name": "Project name", "site_location": "Site location",
    "county": "County", "electric_loads": "Electric loads",
    "utility_provider": "Utility provider", "warranty_type": "Warranty type",
    "cost_method": "Payment", "tax_credit": "Tax credit",
    "expand_option": "Expand option", "products": "Products / services",
    "pv_utility_connection": "PV — utility connection",
    "pv_mounting_type": "PV — mounting type",
    "pv_manufactured_house": "PV — manufactured house",
    "generator_utility_connection": "Generator — utility connection",
    "battery_utility_connection": "Battery bank — utility connection",
    "service_type": "Service type",
    "property_type": "Property type",
}

# Employee directory (Piece 8). The core fields on a person's record:
# who they are, what they do, and when they work. Their licenses and
# certifications are structured rows in employee_credentials (Piece 8.1),
# managed on the profile page.
# Piece 19.3: names are entered as first/last (+ optional nickname); `name`
# is the composed "First Last" display value kept for everything that reads it.
HOUSEHOLD_MEMBER_FIELDS = ["name", "first_name", "last_name", "nickname",
                           "role", "schedule"]

# Piece 17 (revised Piece 35): the tools/functions an admin can grant to a
# non-admin household member. Admin ⇒ all of these automatically except
# "delete"; everyone else ⇒ only what's explicitly granted.
PERMISSIONS = {
    "rules.manage": "Manage rules",
    "catalog.manage": "Manage catalog (appliances & components)",
    "inventory.manage": "Manage inventory (add/edit items, tools, stock)",
    "inventory.register": "Register & print inventory tags (barcodes)",
    "household.manage": "Manage household members & accounts",
    "approvals": "Approve field work",
    "audit.view": "View the audit log",
    "delete": "Delete data (sends it to the trash)",
}
PASSWORD_MIN_LEN = 6
# Piece 29.1: self-service password reset. A menu of security questions to
# choose from (plus a free-typed "own question" option in the form). Enrolling
# a few lets someone reset their own password from the login page.
SECURITY_QUESTIONS = [
    "What was the name of your first pet?",
    "What street did you grow up on?",
    "What was the make of your first vehicle?",
    "What city were you born in?",
    "What was your childhood nickname?",
    # Piece 31.4: harder-to-phish, Vixinman-flavored questions replacing the classic
    # maiden-name / sports-team / first-school prompts (too easy to research).
    "What's your coffee order?",
    "What's your favorite Thanksgiving dish?",
    "Red or green chili?",
]
SECURITY_QUESTIONS_REQUIRED = 3   # how many must be enrolled
SECURITY_QUESTIONS_ASK = 2        # how many (randomly chosen) to answer on reset
SECURITY_RESET_MAX_ATTEMPTS = 5   # wrong tries before the account auto-locks


def seed_finance_reference(db):
    """Piece 29.6/29.8: seed the NM county list (at 0% GRT) and Vixinman's Cost Model
    Defaults. Counties are inserted if missing (rates preserved). The cost model
    is seeded once (meta-guarded) with the finance team's real figures; after
    that it's edited on the Cost Model page and never re-seeded."""
    for c in NM_COUNTIES:
        db.execute("INSERT OR IGNORE INTO county_tax_rates (county, grt_rate)"
                   " VALUES (?, 0)", (c,))
    if not db.execute("SELECT 1 FROM meta WHERE key = 'cost_model_seeded'").fetchone():
        order = 0
        for section in COST_MODEL_SECTIONS:
            for item, unit, qty, cost, markup in COST_MODEL_SEED.get(section, []):
                db.execute(
                    "INSERT INTO cost_model_lines (section, item, unit,"
                    " default_qty, unit_cost, markup_pct, sort_order)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (section, item, unit, qty, cost, markup, order))
                order += 1
        db.execute("INSERT INTO meta (key, value) VALUES ('cost_model_seeded','1')"
                   " ON CONFLICT(key) DO UPDATE SET value = excluded.value")
        # Align the per-project travel $/mile with the Vehicle Trips line (direct SQL:
        # init_db's connection has no Row factory, so avoid _meta_get/_meta_set).
        if not db.execute("SELECT 1 FROM meta WHERE key = 'travel_rate_per_mile'"
                          ).fetchone():
            db.execute("INSERT INTO meta (key, value)"
                       " VALUES ('travel_rate_per_mile', '1.0')")
EMPLOYEE_FIELD_LABELS = {
    "name": "Name", "first_name": "First name", "last_name": "Last name",
    "nickname": "Nickname", "roles": "Roles", "schedule": "Schedule",
}
# Columns a user fills in when adding a license/certification.
CREDENTIAL_FIELDS = ["name", "rule_label", "number", "issued", "expires", "notes"]
# A credential within this many days of its expiry date is flagged
# "expiring soon" on the employee and project pages.
EXPIRY_SOON_DAYS = 60
# Piece 35: the household's role set, replacing the 28-role solar org chart.
# A household member holds exactly one role (was comma-separated multiple
# roles under the old model). Parent/Child map to HANDOFF.md's original
# Adult/Kid concept under friendlier names; Assistant is a household member
# with their own login who isn't a Parent (not auto-admin) — distinct from
# an External helper (external_helpers table), who isn't a household member
# at all.
HOUSEHOLD_ROLES = ["Parent", "Child", "Assistant"]

# Piece 16.1 (revised Piece 35): the household's roster as a one-time seed
# for a fresh install — (name, role, is_admin).
HOUSEHOLD_ROSTER = [
    ("Jacob", "Parent", True),
    ("Rachel", "Parent", True),
    ("Victor", "Child", False),
    ("Dmitri", "Child", False),
    ("Gremory", "Assistant", False),
]

UTILITY_CONNECTIONS = ["Off-grid", "Grid-tie", "Backup system"]
MOUNTING_TYPES = ["Roof mounted", "Ground mount"]
SERVICE_TYPES = ["General service", "Warranty service"]
PROPERTY_TYPES = ["Residential", "Commercial"]

# Which variant fields belong to which product — used by the rule
# directory so filtering by project type also scopes its variants.
VARIANT_OWNERS = {
    "pv_utility_connection": "PV Systems",
    "pv_mounting_type": "PV Systems",
    "pv_manufactured_house": "PV Systems",
    "generator_utility_connection": "Generators",
    "battery_utility_connection": "Battery Banks",
    "service_type": "Technician Service",
}
CONNECTION_FIELDS = {
    "pv_utility_connection", "generator_utility_connection",
    "battery_utility_connection",
}

# Standard documents every project collects, shown as their own upload slots on the
# Documents tab (Piece 20.9) alongside the project's resolved requirements. Format
# restrictions per slot to be added later.
STANDARD_JOB_DOCS = [
    "Signed Contract", "Site Photos", "Design / One-Line", "Site Plan (KMZ/KML)",
]
# Piece 25.2: built-in accepted formats for the standard slots (rule-based slots
# carry their own `allowed_formats`). A slot with no restriction accepts any of
# the globally-allowed types.
STANDARD_DOC_FORMATS = {
    "Signed Contract": {"pdf", "doc", "docx"},
    "Site Photos": {"png", "jpg", "jpeg", "heic", "gif"},
    "Design / One-Line": {"pdf", "png", "jpg", "jpeg"},
    "Site Plan (KMZ/KML)": {"kmz", "kml"},
}


def _parse_formats(raw):
    """Normalize a comma/space-separated format string to a lowercase set of bare
    extensions (no dots): 'PDF, .jpg png' -> {'pdf','jpg','png'}."""
    out = set()
    for tok in re.split(r"[,\s]+", (raw or "").strip().lower()):
        tok = tok.lstrip(".")
        if tok:
            out.add(tok)
    return out


def allowed_formats_for_label(db, label):
    """Accepted extension set for a document slot, or None to fall back to the
    global ALLOWED_EXTENSIONS. Standard slots use STANDARD_DOC_FORMATS; a
    rule-based slot uses its rule's `allowed_formats` (first non-empty match)."""
    if not label:
        return None
    if label in STANDARD_DOC_FORMATS:
        return STANDARD_DOC_FORMATS[label]
    row = db.execute(
        "SELECT allowed_formats FROM resource_rules"
        " WHERE label = ? AND COALESCE(allowed_formats, '') != ''"
        " ORDER BY id LIMIT 1", (label,)).fetchone()
    if row:
        return _parse_formats(row["allowed_formats"]) or None
    return None


# ---- Piece 25.4: auto-rename uploads for recordkeeping (Name_What_Date) -------
def _slug(text, maxlen=48):
    """A filename-safe slug: letters/digits kept, runs of anything else become a
    single hyphen. Trimmed to maxlen so names stay reasonable."""
    s = re.sub(r"[^A-Za-z0-9]+", "-", (text or "").strip()).strip("-")
    return s[:maxlen].strip("-")


def friendly_filename(parts, ext, taken=None):
    """Build 'Part1_Part2_…_YYYY-MM-DD.ext' from meaningful parts (each slugged,
    blanks dropped) so uploads are self-describing. `taken` is a set of display
    names already used in the same place — a numeric suffix avoids collisions."""
    slugs = [s for s in (_slug(p) for p in parts) if s]
    slugs.append(datetime.now().strftime("%Y-%m-%d"))
    base = "_".join(slugs) or "Document"
    ext = (ext or "").lower().lstrip(".")
    name = f"{base}.{ext}" if ext else base
    n = 2
    while taken and name in taken:
        name = f"{base}-{n}.{ext}" if ext else f"{base}-{n}"
        n += 1
    return name


def _ext_of(filename):
    return filename.rsplit(".", 1)[-1].lower() if "." in (filename or "") else ""


def _taken_names(db, table, column, id_col, id_val):
    """Existing display names filed against the same owner (for de-duping)."""
    rows = db.execute(
        f"SELECT original_name FROM {table} WHERE {id_col} = ?", (id_val,)).fetchall()
    return {r["original_name"] for r in rows if r["original_name"]}

# Piece 21: Finance ledger vocabulary. Income = money in (deposits, invoices,
# rebates); Expense = money out (materials, permits, labor, subs). Categories
# map cleanly onto QuickBooks income/expense accounts on export.
TXN_KINDS = ["Income", "Expense"]
TXN_STATUSES = ["Outstanding", "Paid"]
INCOME_CATEGORIES = [
    "50% Deposit", "40% Deposit", "Final 10% Invoice", "Financing / Rebate",
    "Change Order", "Other Income",
]
EXPENSE_CATEGORIES = [
    "Materials", "Equipment", "Permit / Fees", "Labor", "Subcontractor",
    "Fuel / Travel", "Other Expense",
]
# Piece 26.2: expense categories offered on the Work Bag receipt capture.
RECEIPT_CATEGORIES = ["Materials", "Meals", "Tools and Supplies", "Overhead"]
PAYMENT_METHODS = ["", "Cash", "Check", "Card", "ACH", "Financing"]
# Piece 31.8: how the customer pays for the project (the project form's "Payment" field,
# stored in cost_method). Two choices — pay the full amount up front, or finance.
PAYMENT_TERMS = ["Pay in full", "Financing"]

# Piece 21.5: source-document type for a ledger entry, so scanned/received
# paperwork feeds the QuickBooks reports under the right account flow:
#   Invoice — money we bill a customer (A/R, Income)
#   Bill    — money a vendor bills us (A/P, Expense)
#   Receipt — proof of a payment already made (an expense paid at the counter)
# A blank doc type is a plain ledger note with no paperwork behind it.
DOC_TYPES = ["Receipt", "Invoice", "Bill"]

# New Mexico gross-receipts tax. The rate is per project (it varies by the install
# location), defaulting to 0% because Vixinman's solar systems are
# GRT-deductible (see the "GRT Exemption on Invoice" rule); Finance sets a
# rate on the Billing tab where any receipts are taxable.
GRT_DEFAULT_RATE = 0.0
# Piece 29.6: the 33 New Mexico counties, seeded (at 0%) into county_tax_rates
# so Finance can enter each county's current GRT rate. A project's GRT rate
# auto-fills from its install county. Rates change biannually — enter the
# current NM TRD figures; they are NOT bundled to avoid shipping stale tax data.
NM_COUNTIES = [
    "Bernalillo", "Catron", "Chaves", "Cibola", "Colfax", "Curry", "De Baca",
    "Doña Ana", "Eddy", "Grant", "Guadalupe", "Harding", "Hidalgo", "Lea",
    "Lincoln", "Los Alamos", "Luna", "McKinley", "Mora", "Otero", "Quay",
    "Rio Arriba", "Roosevelt", "Sandoval", "San Juan", "San Miguel", "Santa Fe",
    "Sierra", "Socorro", "Taos", "Torrance", "Union", "Valencia",
]
# Piece 29.6: equipment-markup categories seeded (at 0%) when none exist, so the
# per-category markup table is useful out of the box. Finance sets real margins.
MARKUP_SEED_CATEGORIES = [
    "Panel", "Inverter", "Battery", "Racking", "Electrical", "Monitoring",
    "Generator", "Well Pump", "Mini Split", "Other",
]
# Default travel reimbursement, $ per (round-trip) mile — stored in meta as
# 'travel_rate_per_mile' and edited on Finance Settings. 0 until Finance sets it.
TRAVEL_RATE_DEFAULT = 0.0
# Piece 29.8: Vixinman's Cost Model Defaults (from the finance team's estimating
# sheet). Sections in display order; each line = (item, unit, default_qty,
# unit_cost, markup_pct). Equipment Inventory rows carry only a markup (they
# price the BOM). Overhead rows carry a percent (in the markup slot) applied to
# the whole project subtotal. Seeded once; fully editable on the Cost Model page.
COST_MODEL_SECTIONS = ["Equipment Inventory", "Equipment Non-Inventory",
                       "Labor", "Travel", "Adders", "Overhead"]
COST_MODEL_SEED = {
    "Equipment Inventory": [
        ("Battery", "", None, None, 30), ("Breaker", "", None, None, 50),
        ("Breaker Panel", "", None, None, 50), ("Charge Controller", "", None, None, 30),
        ("Controls", "", None, None, 50), ("Electrical", "", None, None, 30),
        ("Enclosure", "", None, None, 30), ("Generator", "", None, None, 30),
        ("Inverter", "", None, None, 50), ("mc4", "", None, None, 0),
        ("Monitoring", "", None, None, 50), ("Office Supplies", "", None, None, 0),
        ("Optimizer", "", None, None, 50), ("Pumping", "", None, None, 40),
        ("PV Module", "", None, None, 50), ("Racking", "", None, None, 50),
        ("Wire", "", None, None, 50),
    ],
    "Equipment Non-Inventory": [
        ("Ground PV Mount", "Watts", None, 0.8, 30),
        ("Direct Roof PV Mount", "Watts", None, 0.18, 30),
        ("Pergola PV Mount", "Watts", None, 1.1, 30),
        ("Ballasted Roof PV Mount", "Watts", None, 0.5, 30),
        ("Direct Roof on Shingles Mount", "Watts", None, 0.22, 30),
    ],
    "Labor": [
        ("Hours", "", 100, 40, 100),
        ("Panels", "Panels", None, 40, 100),
    ],
    "Travel": [
        ("Vehicle Trips", "Mile", 7, 1, 0),
        ("Person Trips", "Hour", 21, 30, 100),
    ],
    "Adders": [
        ("Trench", "", 1, 1000, 0),
        ("Permits", "", 1, 1000, 0),
        ("Propane Line Installation", "", 1, 2500, 30),
    ],
    "Overhead": [
        ("G&A", "", None, None, 22),
    ],
}

RULE_CATEGORIES = ["License", "Permit", "Compliance", "Link", "Phone", "Doc"]
CATEGORY_HEADINGS = {
    "License": "Technician licenses",
    "Permit": "Permits",
    "Compliance": "Compliance notes",
    "Link": "Online Portals",
    "Phone": "Phone numbers",
    "Doc": "Documents",
}

# Vixinman's requirement rules, seeded once into the editable resource_rules
# table: (field_name, field_value, match_type, category, label, notes).
SEED_RULES = [
    # Mini Split Air Conditioners
    ("products", "Mini Split Air Conditioners", "contains", "License", "MM-2 or MM-3 Contractor License", ""),
    ("products", "Mini Split Air Conditioners", "contains", "License", "Journeyman HVAC (JH) Certificate", ""),
    ("products", "Mini Split Air Conditioners", "contains", "License", "EPA Section 608 — Type II or Universal", ""),
    ("products", "Mini Split Air Conditioners", "contains", "Permit", "Mechanical permit", ""),
    ("products", "Mini Split Air Conditioners", "contains", "Permit", "Electrical permit", ""),
    ("products", "Mini Split Air Conditioners", "contains", "Compliance", "AIM Act refrigerant (R-454B or R-32)", ""),
    ("products", "Mini Split Air Conditioners", "contains", "Compliance", "Rough-in Inspection", ""),
    ("products", "Mini Split Air Conditioners", "contains", "Compliance", "Final Inspection", ""),
    # Generators
    ("products", "Generators", "contains", "License", "EE-98 or ER-1 Electrical License", ""),
    ("products", "Generators", "contains", "Permit", "Electrical permit", ""),
    ("products", "Generators", "contains", "Compliance", "Rough-in Inspection", ""),
    ("products", "Generators", "contains", "Compliance", "Final Inspection", ""),
    # Well Pumps
    ("products", "Well Pumps", "contains", "License", "ES-10R Contractor License", ""),
    ("products", "Well Pumps", "contains", "License", "ES-10RJ Journeyman", "per tech"),
    ("products", "Well Pumps", "contains", "Permit", "Electrical permit", ""),
    ("products", "Well Pumps", "contains", "Compliance", "Electrical Inspection", ""),
    # PV Systems
    ("products", "PV Systems", "contains", "License", "EE-98 Contractor License", ""),
    ("products", "PV Systems", "contains", "License", "EE-98J Journeyman", "per tech on site"),
    ("products", "PV Systems", "contains", "Permit", "Electrical permit", ""),
    ("products", "PV Systems", "contains", "Compliance", "Full NEC 690 One-Line Package", ""),
    # Battery Banks
    ("products", "Battery Banks", "contains", "License", "EE-98 Contractor License", ""),
    ("products", "Battery Banks", "contains", "License", "EE-98J Journeyman", "per tech on site"),
    ("products", "Battery Banks", "contains", "Permit", "Electrical permit", ""),
    ("products", "Battery Banks", "contains", "Compliance", "Updated One-Line w/ ESS Disconnect", ""),
    ("products", "Battery Banks", "contains", "Compliance", "UL 9540 Equipment Listing", ""),
    ("products", "Battery Banks", "contains", "Compliance", "NEC 706 Disconnect + Labeling", ""),
    ("products", "Battery Banks", "contains", "Compliance", "Exterior Emergency Shutdown", ""),
    ("products", "Battery Banks", "contains", "Compliance", "IFC Chapter 12 / Fire Code", ""),
    ("products", "Battery Banks", "contains", "Compliance", "NFPA 855 Clearances + Spacing", ""),
    ("products", "Battery Banks", "contains", "Compliance", "Ventilation Plan", ""),
    ("products", "Battery Banks", "contains", "Compliance", "Smoke/Heat Detection (if enclosed)", ""),
]

# Batch 2 — PV Systems variant matrix (roof/ground × grid-tie/off-grid).
# Seed batches are applied once per database via the meta.seed_version key,
# so existing databases pick up new batches without duplicating rules.
SEED_RULES_V2 = [
    # All PV variants
    ("products", "PV Systems", "contains", "Compliance", "SMDTC Application", "client files"),
    ("products", "PV Systems", "contains", "Compliance", "GRT Exemption on Invoice", ""),
    # Roof mounted
    ("pv_mounting_type", "Roof mounted", "equals", "Compliance", "Rapid Shutdown (NEC 690.12)", ""),
    ("pv_mounting_type", "Roof mounted", "equals", "Compliance", "Structural Analysis / NM PE Letter", "situational"),
    ("pv_mounting_type", "Roof mounted", "equals", "Permit", "Building Permit (structural)", "if reinforcement needed"),
    ("pv_mounting_type", "Roof mounted", "equals", "Compliance", "Fire Code Roof Access Clearances", ""),
    # Roof mounted on a manufactured house
    ("pv_manufactured_house", "Yes", "equals", "Permit", "MHD Permit", "manufactured homes"),
    # Ground mount
    ("pv_mounting_type", "Ground mount", "equals", "Compliance", "Rapid Shutdown (NEC 690.12) — exception", "ground mounts typically qualify for the exception"),
    ("pv_mounting_type", "Ground mount", "equals", "Compliance", "Structural Analysis / NM PE Letter", ""),
    ("pv_mounting_type", "Ground mount", "equals", "Permit", "Building Permit (structural)", ""),
    ("pv_mounting_type", "Ground mount", "equals", "Compliance", "Underground Wiring Plan + Depths", ""),
    # Grid-tie (either mounting)
    ("pv_utility_connection", "Grid-tie", "equals", "Permit", "Utility Interconnection Application", ""),
    ("pv_utility_connection", "Grid-tie", "equals", "Compliance", "IEEE 1547-2018 Inverter Listing", ""),
    ("pv_utility_connection", "Grid-tie", "equals", "Compliance", "Lockable Load-Break Disconnect", ""),
    ("pv_utility_connection", "Grid-tie", "equals", "Compliance", "Signed Interconnection Agreement", ""),
    ("pv_utility_connection", "Grid-tie", "equals", "Compliance", "Utility Final Inspection + Anti-Island", ""),
]

# Batch 3 — backup systems follow grid-tie rules (per Vixinman general rule;
# specifics to be refined later, hence the note on each).
SEED_RULES_V3 = [
    ("pv_utility_connection", "Backup system", "equals", "Permit", "Utility Interconnection Application", "follows grid-tie rules for now"),
    ("pv_utility_connection", "Backup system", "equals", "Compliance", "IEEE 1547-2018 Inverter Listing", "follows grid-tie rules for now"),
    ("pv_utility_connection", "Backup system", "equals", "Compliance", "Lockable Load-Break Disconnect", "follows grid-tie rules for now"),
    ("pv_utility_connection", "Backup system", "equals", "Compliance", "Signed Interconnection Agreement", "follows grid-tie rules for now"),
    ("pv_utility_connection", "Backup system", "equals", "Compliance", "Utility Final Inspection + Anti-Island", "follows grid-tie rules for now"),
]

# Batch 4 — Battery Banks matrix (Res. Solar+Bat / Off-Grid / Grid-Tied /
# Commercial). 9-item rows carry a second AND condition. Backup system
# mirrors grid-tie per the Vixinman general rule (battery table has no
# standby column).
SEED_RULES_V4 = [
    ("products", "Battery Banks", "contains", "Compliance", "Fire Authority Plan Review", "situational", "property_type", "Residential", "equals"),
    ("products", "Battery Banks", "contains", "Compliance", "Fire Authority Plan Review", "likely required", "property_type", "Commercial", "equals"),
    ("products", "Battery Banks", "contains", "Compliance", "Hazard Mitigation Analysis (HMA)", "confirm with AHJ", "property_type", "Residential", "equals"),
    ("products", "Battery Banks", "contains", "Compliance", "Hazard Mitigation Analysis (HMA)", "likely required", "property_type", "Commercial", "equals"),
    ("battery_utility_connection", "Grid-tie", "equals", "Compliance", "Utility Interconnection Update", "if export"),
    ("battery_utility_connection", "Backup system", "equals", "Compliance", "Utility Interconnection Update", "if export; follows grid-tie rules for now"),
    ("battery_utility_connection", "Grid-tie", "equals", "Compliance", "NEC 705 Interconnection (multi-source)", ""),
    ("battery_utility_connection", "Backup system", "equals", "Compliance", "NEC 705 Interconnection (multi-source)", "follows grid-tie rules for now"),
    ("battery_utility_connection", "Off-grid", "equals", "Compliance", "NEC 705 Interconnection (multi-source)", "if generator coupled"),
    ("battery_utility_connection", "Grid-tie", "equals", "Compliance", "Arc Flash Label", "commercial"),
    ("battery_utility_connection", "Backup system", "equals", "Compliance", "Arc Flash Label", "commercial; follows grid-tie rules for now"),
    ("products", "Battery Banks", "contains", "Compliance", "Arc Flash Label", "", "property_type", "Commercial", "equals"),
    ("products", "Battery Banks", "contains", "Compliance", "SMDTC 20% Credit", "client files; if with solar", "products", "PV Systems", "contains"),
    ("battery_utility_connection", "Grid-tie", "equals", "Compliance", "GRT Exemption on Invoice", "confirm"),
]

# Batch 5 — Generators matrix (Off-Grid / Standby / Grid-Tied). Their
# "Standby" is our "Backup system". Note: per the table, standby
# generators do NOT get the grid-tie interconnection items — the table
# overrides the backup-follows-grid-tie general rule for generators.
SEED_RULES_V5 = [
    ("products", "Generators", "contains", "License", "LP-4/LP-5 or MM-2 Gas License", "if gas-fueled"),
    ("products", "Generators", "contains", "Compliance", "NFPA 37 Clearances", ""),
    ("generator_utility_connection", "Backup system", "equals", "Compliance", "Transfer Switch (NEC 702)", ""),
    ("generator_utility_connection", "Grid-tie", "equals", "Compliance", "Transfer Switch (NEC 702)", ""),
    ("generator_utility_connection", "Grid-tie", "equals", "Permit", "Utility Interconnection Application", ""),
    ("generator_utility_connection", "Grid-tie", "equals", "Compliance", "NMPRC Rule 568 Compliance", ""),
    ("generator_utility_connection", "Grid-tie", "equals", "Compliance", "Utility-Accessible Lockable Disconnect", ""),
    ("generator_utility_connection", "Grid-tie", "equals", "Compliance", "Signed Interconnection Agreement", ""),
    ("generator_utility_connection", "Grid-tie", "equals", "Compliance", "NM PE Stamp", "if >10 kVA grid-tied"),
    ("generator_utility_connection", "Grid-tie", "equals", "Compliance", "Utility Interconnection Inspection", ""),
]

# Batch 6 — corrections per Vixinman: Arc Flash is commercial-only, and the
# two SMDTC rules merge into one.
SEED_RULES_V6 = [
    ("products", "PV Systems", "contains", "Compliance", "SMDTC 20% Credit Application",
     "client files; batteries qualify when paired with solar"),
]

# Batch 7 — authoritative links from the "NM Solar Contractor Website
# Reference List" (June 2026), attached to the rules they support, plus
# utility-specific interconnection links keyed on the project's utility
# provider. The source document contains no phone numbers.
_CID_LICENSING = "https://www.rld.nm.gov/construction-industries-public-works/construction-industries/"
_CID_PORTAL = "https://nmrld.my.site.com/MHD/s/"
_NEC = "https://www.nfpa.org/codes-and-standards/nfpa-70-standard-for-electrical-installations/70"
_IFC = "https://codes.iccsafe.org/content/IFC2021"
_NFPA855 = "https://www.nfpa.org/codes-and-standards/all-codes-and-standards/list-of-codes-and-standards/detail?code=855"
_PE_BOARD = "https://www.rld.nm.gov/engineering-and-land-surveying/"
_PNM_SOLAR = "https://www.pnm.com/solar"
_PNM_INTERCONNECT = "https://www.pnm.com/interconnection"

# (label, url, optional field_name filter for labels shared across products)
RULE_LINKS = [
    ("MM-2 or MM-3 Contractor License", _CID_LICENSING, None),
    ("Journeyman HVAC (JH) Certificate", _CID_LICENSING, None),
    ("EE-98 or ER-1 Electrical License", _CID_LICENSING, None),
    ("ES-10R Contractor License", _CID_LICENSING, None),
    ("ES-10RJ Journeyman", _CID_LICENSING, None),
    ("EE-98 Contractor License", _CID_LICENSING, None),
    ("EE-98J Journeyman", _CID_LICENSING, None),
    ("LP-4/LP-5 or MM-2 Gas License", "https://www.rld.nm.gov/lp-gas/", None),
    ("EPA Section 608 — Type II or Universal", "https://www.epa.gov/section608", None),
    ("AIM Act refrigerant (R-454B or R-32)", "https://www.epa.gov/climate-hfcs-reduction", None),
    ("Mechanical permit", _CID_PORTAL, None),
    ("Electrical permit", _CID_PORTAL, None),
    ("Building Permit (structural)", _CID_PORTAL, None),
    ("Rough-in Inspection", _CID_PORTAL, None),
    ("Final Inspection", _CID_PORTAL, None),
    ("Electrical Inspection", _CID_PORTAL, None),
    ("MHD Permit", "https://www.rld.nm.gov/manufactured-housing/", None),
    ("Transfer Switch (NEC 702)", _NEC, None),
    ("NFPA 37 Clearances", "https://www.nfpa.org/codes-and-standards/all-codes-and-standards/list-of-codes-and-standards/detail?code=37", None),
    ("Full NEC 690 One-Line Package", _NEC, None),
    ("Rapid Shutdown (NEC 690.12)", _NEC, None),
    ("Rapid Shutdown (NEC 690.12) — exception", _NEC, None),
    ("Underground Wiring Plan + Depths", _NEC, None),
    ("Updated One-Line w/ ESS Disconnect", _NEC, None),
    ("NEC 706 Disconnect + Labeling", _NEC, None),
    ("Exterior Emergency Shutdown", _NEC, None),
    ("NEC 705 Interconnection (multi-source)", _NEC, None),
    ("Arc Flash Label", _NEC, None),
    ("Structural Analysis / NM PE Letter", _PE_BOARD, None),
    ("NM PE Stamp", _PE_BOARD, None),
    ("Fire Code Roof Access Clearances", _IFC, None),
    ("IFC Chapter 12 / Fire Code", _IFC, None),
    ("Smoke/Heat Detection (if enclosed)", _IFC, None),
    ("NFPA 855 Clearances + Spacing", _NFPA855, None),
    ("Ventilation Plan", _NFPA855, None),
    ("Hazard Mitigation Analysis (HMA)", _NFPA855, None),
    ("Fire Authority Plan Review", "https://www.dhsem.nm.gov/state-fire-marshal/", None),
    ("UL 9540 Equipment Listing", "https://www.ul.com/resources/ul-9540-standard-for-energy-storage-systems-and-equipment", None),
    ("IEEE 1547-2018 Inverter Listing", "https://standards.ieee.org/ieee/1547/6341/", None),
    ("NMPRC Rule 568 Compliance", "https://www.nmprc.state.nm.us/utilities/elec.html", None),
    ("SMDTC 20% Credit Application", "https://www.emnrd.nm.gov/sed/renewable-energy/solar-market-development-tax-credit/", None),
    ("GRT Exemption on Invoice", "https://www.tax.newmexico.gov/businesses/gross-receipts-tax/", None),
    # Shared labels: PV items point at PNM's solar program, generator
    # items at PNM's general interconnection page (per the document).
    ("Utility Interconnection Application", _PNM_SOLAR, "pv_utility_connection"),
    ("Signed Interconnection Agreement", _PNM_SOLAR, "pv_utility_connection"),
    ("Lockable Load-Break Disconnect", _PNM_SOLAR, "pv_utility_connection"),
    ("Utility Final Inspection + Anti-Island", _PNM_SOLAR, "pv_utility_connection"),
    ("Utility Interconnection Application", _PNM_INTERCONNECT, "generator_utility_connection"),
    ("Signed Interconnection Agreement", _PNM_INTERCONNECT, "generator_utility_connection"),
    ("Utility-Accessible Lockable Disconnect", _PNM_INTERCONNECT, "generator_utility_connection"),
    ("Utility Interconnection Inspection", _PNM_INTERCONNECT, "generator_utility_connection"),
    ("Utility Interconnection Update", _PNM_INTERCONNECT, "battery_utility_connection"),
]


def _link_sql(label, url, field=None):
    where = f"label = '{label}'"
    if field:
        where += f" AND field_name = '{field}'"
    return f"UPDATE resource_rules SET url = '{url}' WHERE {where}"


# Utility-specific portals become Link rules keyed on the project's utility
# provider (both utilities appear in the document).
SEED_RULES_V7 = [
    ("utility_provider", "PNM", "equals", "Link",
     "PNM — Solar Interconnection & Net Metering", "", "", "", "equals"),
    ("utility_provider", "Kit Carson Electric Cooperative", "equals", "Link",
     "Kit Carson Electric Cooperative", "", "", "", "equals"),
]

# Canonical values suggested on the project form so free-typed utilities and
# counties actually match the rules below.
UTILITIES = UTILITIES_ALL

# These products share one utility-connection choice on the project form.
GRID_PRODUCTS = ["PV Systems", "Battery Banks", "Generators"]
GRID_CONNECTION_FIELDS = {
    "PV Systems": "pv_utility_connection",
    "Generators": "generator_utility_connection",
    "Battery Banks": "battery_utility_connection",
}
COUNTIES = COUNTIES_ALL

# Batch 8 — from the Utility Interconnection Forms & AHJ Building Permit
# Forms documents (June 2026): per-utility forms/contacts and quirks,
# per-county AHJ permits, and new-well drilling subcontract notes.
SEED_RULES_V8 = [
    # --- Utility contacts & forms (fire on the project's utility provider) ---
    dict(field_name="utility_provider", field_value="MSMEC", category="Link",
         label="MSMEC — Interconnection Forms Hub",
         url="https://morasanmiguel.coop/forms",
         phone="575-383-4270 / 800-421-6773",
         notes="two tiers (≤10 kW / >10 kW); customer signs; approval before construction; rebates: thernandez@morasanmiguel.coop"),
    dict(field_name="utility_provider", field_value="KCEC", category="Compliance",
         label="KCEC Solar Net-Metering Pre-Screening — required FIRST",
         url="https://kitcarson.com/solar-net-metering-pre-screening-application",
         phone="575-758-2258",
         notes="mandatory first gate before the full application; systems >25 kW: email rmartinez@kitcarson.com"),
    dict(field_name="utility_provider", field_value="KCEC", category="Link",
         label="KCEC — Net-Metering Hub & Applications",
         url="https://kitcarson.com/electric/electric-info/net-metering/",
         phone="575-758-2258",
         notes="full application after pre-screening approval; NM Interconnection Manual p.24"),
    dict(field_name="utility_provider", field_value="Springer Electric", category="Link",
         label="Springer Electric — Forms Hub",
         url="https://www.springercoop.com/service-application-and-forms",
         phone="575-483-2421 / 800-288-1353",
         notes="submit by mail (PO Box 698, Springer) or fax 575-483-2692; closed Fridays; site blocks automated access — navigate from hub"),
    dict(field_name="utility_provider", field_value="JMEC", category="Link",
         label="JMEC — Solar Applications & Requirements Packet",
         url="https://www.jemezcoop.org/sites/default/files/2025-07/solar-applications-and-requirements.pdf",
         phone="505-753-2105 / 888-755-2105",
         notes="all-in-one packet; net metering up to 30 kW, April settle-up"),
    dict(field_name="utility_provider", field_value="JMEC", category="Compliance",
         label="JMEC Letter of Compliance (electrician closeout)",
         url="https://www.jemezcoop.org/forms",
         phone="888-755-2105",
         notes="JMEC-specific: licensed electrician's letter required before written authorization"),
    dict(field_name="utility_provider", field_value="PNM", category="Compliance",
         label="PNM portal application — customer-signed, $50 fee (<100 kW)",
         url="https://www.pnm.com/interconnection",
         phone="888-342-5766",
         notes="visible-air-gap lockable disconnect required (breakers/software modes do not qualify); permanent weatherproof one-line at point of service"),
    # --- AHJ building/structural permits (fire on the project's county) ---
    dict(field_name="county", field_value="Santa Fe County", category="Permit",
         label="Santa Fe County Development Permit (PV Solar)",
         url="https://www.santafecountynm.gov/growth-management/building-development/permitpackets",
         phone="505-986-6225",
         notes="unincorporated county: required for PV even without structural work; online via geocivix; expedited ~5 days; David Ruiz 505-986-6371",
         field_name2="products", field_value2="PV Systems", match_type2="contains"),
    dict(field_name="county", field_value="Taos County", category="Permit",
         label="Taos County Solar Array Zoning Clearance — FIRST",
         url="https://www.taoscounty.org/DocumentCenter/View/1914/Solar--Building-Permit-Application",
         phone="575-737-6300",
         notes="unincorporated county: required before the building permit; call office after online submittal; $80 re-inspection fee",
         field_name2="products", field_value2="PV Systems", match_type2="contains"),
    dict(field_name="county", field_value="Taos County", category="Permit",
         label="Taos County Building Permit (after zoning clearance)",
         url="https://www.taoscounty.org/DocumentCenter/View/2927/Building-Permit-Application",
         phone="575-737-6300",
         notes="use the 2024 revision",
         field_name2="products", field_value2="PV Systems", match_type2="contains"),
    dict(field_name="county", field_value="Rio Arriba County", category="Permit",
         label="Rio Arriba County Development Permit",
         url="https://www.rio-arriba.org/Departments/Departments-Divisions/Planning-and-Zoning/Forms-and-Permit-Applications",
         phone="505-685-8000",
         notes="single form covers solar/residential; 3–5 days; site visit arranged; NMDOT access permit if state road involved"),
] + [
    dict(field_name="county", field_value=county, category="Link",
         label="CID is your AHJ — structural permits via CID portal",
         url="https://nmrld.my.site.com/MHD/s/",
         phone="505-476-4700 / 877-CID-0979",
         notes="unincorporated areas; within city limits confirm the municipal building dept (Las Vegas 505-454-1401, Raton 575-445-9551)")
    for county in ("Mora County", "San Miguel County", "Colfax County",
                   "Harding County", "Guadalupe County")
] + [
    # --- New wells: drilling is subcontracted, outside Vixinman scope ---
    dict(field_name="products", field_value="Well Pumps", match_type="contains",
         category="Compliance",
         label="New well? OSE well drilling permit — SUBCONTRACT",
         url="https://www.ose.nm.gov/WR/well_drilling.php",
         notes="well drilling is outside Vixinman scope — subcontract to an OSE-licensed driller; applies to new wells only, not pump replacement"),
    dict(field_name="products", field_value="Well Pumps", match_type="contains",
         category="Compliance",
         label="New well? NMED water quality testing — subcontracted scope",
         url="https://www.env.nm.gov/drinking-water/",
         notes="new wells only; belongs to the drilling contractor's scope"),
]

# Batch 9 — named link sources, and state-run pages preferred: NEC and
# IFC rules point at New Mexico's own code-adoption pages (NMAC) instead
# of the publishers; standards bodies (UL/IEEE/NFPA) and utility/county
# sites remain the original sources.
_NMAC_NEC = "https://www.srca.nm.gov/parts/title14/14.010.0004.htm"
_NMAC_IFC = "https://www.srca.nm.gov/parts/title10/10.025.0005.htm"

LINK_TEXTS = {
    _CID_LICENSING: "NM CID — Contractor & Journeyman Licensing",
    _CID_PORTAL: "NM CID Online Permit Portal",
    "https://www.rld.nm.gov/lp-gas/": "NM RLD — LP Gas Bureau",
    "https://www.epa.gov/section608": "EPA Section 608 Certification",
    "https://www.epa.gov/climate-hfcs-reduction": "EPA AIM Act — HFC Phasedown",
    "https://www.rld.nm.gov/manufactured-housing/": "NM Manufactured Housing Division",
    _NMAC_NEC: "NMAC 14.10.4 — NM Adoption of NEC 2020",
    _NMAC_IFC: "NMAC 10.25.5 — NM Adoption of IFC 2021",
    "https://www.nfpa.org/codes-and-standards/all-codes-and-standards/list-of-codes-and-standards/detail?code=37": "NFPA 37 — Stationary Combustion Engines",
    _NFPA855: "NFPA 855 — Stationary Energy Storage Systems",
    _PE_BOARD: "NM PE Board — Engineering & Surveying",
    "https://www.dhsem.nm.gov/state-fire-marshal/": "NM State Fire Marshal Office",
    "https://www.ul.com/resources/ul-9540-standard-for-energy-storage-systems-and-equipment": "UL 9540 — Energy Storage Systems Standard",
    "https://standards.ieee.org/ieee/1547/6341/": "IEEE 1547-2018 Standard",
    "https://www.nmprc.state.nm.us/utilities/elec.html": "NMPRC — Electric Utility Rules (17.9.568)",
    "https://www.emnrd.nm.gov/sed/renewable-energy/solar-market-development-tax-credit/": "NM EMNRD — Solar Market Development Tax Credit",
    "https://www.tax.newmexico.gov/businesses/gross-receipts-tax/": "NM Taxation & Revenue — Gross Receipts Tax",
    _PNM_SOLAR: "PNM — Solar & Net Metering",
    _PNM_INTERCONNECT: "PNM Interconnection Portal",
    "https://www.kitcarson.com": "Kit Carson Electric Cooperative",
    "https://morasanmiguel.coop/forms": "MSMEC Forms Hub",
    "https://kitcarson.com/solar-net-metering-pre-screening-application": "KCEC Pre-Screening Application",
    "https://kitcarson.com/electric/electric-info/net-metering/": "KCEC Net-Metering Hub",
    "https://www.springercoop.com/service-application-and-forms": "Springer Electric Forms Hub",
    "https://www.jemezcoop.org/sites/default/files/2025-07/solar-applications-and-requirements.pdf": "JMEC Solar Applications Packet (PDF)",
    "https://www.jemezcoop.org/forms": "JMEC Forms Hub",
    "https://www.santafecountynm.gov/growth-management/building-development/permitpackets": "Santa Fe County Permit Packets",
    "https://www.taoscounty.org/DocumentCenter/View/1914/Solar--Building-Permit-Application": "Taos County Zoning Clearance Application (PDF)",
    "https://www.taoscounty.org/DocumentCenter/View/2927/Building-Permit-Application": "Taos County Building Permit Application (PDF)",
    "https://www.rio-arriba.org/Departments/Departments-Divisions/Planning-and-Zoning/Forms-and-Permit-Applications": "Rio Arriba County Planning & Zoning Forms",
    "https://www.ose.nm.gov/WR/well_drilling.php": "NM OSE — Well Drilling & Licensing",
    "https://www.env.nm.gov/drinking-water/": "NMED Drinking Water Bureau",
}

SEED_BATCHES = {2: SEED_RULES_V2, 3: SEED_RULES_V3, 4: SEED_RULES_V4,
                5: SEED_RULES_V5, 6: SEED_RULES_V6, 7: SEED_RULES_V7,
                8: SEED_RULES_V8, 9: [], 10: NEW_RULES_V10, 11: []}

# One-off SQL applied alongside a batch (same once-only guarantee).
SEED_BATCH_SQL = {
    # Exterior Emergency Shutdown is residential-only per the battery
    # matrix; scope the original unconditional rule.
    4: ["UPDATE resource_rules SET field_name2 = 'property_type',"
        " field_value2 = 'Residential', match_type2 = 'equals'"
        " WHERE field_name = 'products' AND field_value = 'Battery Banks'"
        " AND label = 'Exterior Emergency Shutdown' AND field_name2 = ''"],
    # Residential grid-tie needs no Arc Flash Label (commercial-only
    # compound rule remains); old SMDTC rules replaced by the merged one.
    6: ["DELETE FROM resource_rules WHERE label = 'Arc Flash Label'"
        " AND field_name = 'battery_utility_connection'",
        "DELETE FROM resource_rules WHERE label = 'SMDTC Application'",
        "DELETE FROM resource_rules WHERE label = 'SMDTC 20% Credit'"],
    # Attach the June 2026 reference-list links to their rules.
    7: [_link_sql(label, url, field) for label, url, field in RULE_LINKS] + [
        _link_sql("PNM — Solar Interconnection & Net Metering", _PNM_SOLAR),
        _link_sql("Kit Carson Electric Cooperative", "https://www.kitcarson.com"),
    ],
    # The generic interconnection rules were PNM-linked but apply to all
    # six providers: point them at governing NMPRC Rule 568 instead; the
    # serving utility's own forms come from the utility_provider rules.
    # Also normalize the batch-7 utility Link rules to canonical values.
    8: [_link_sql(label, "https://www.nmprc.state.nm.us/utilities/elec.html")
        for label in ("Utility Interconnection Application",
                      "Signed Interconnection Agreement",
                      "Lockable Load-Break Disconnect",
                      "Utility-Accessible Lockable Disconnect",
                      "Utility Final Inspection + Anti-Island",
                      "Utility Interconnection Inspection",
                      "Utility Interconnection Update")] + [
        "UPDATE resource_rules SET field_value = 'KCEC', phone = '575-758-2258'"
        " WHERE label = 'Kit Carson Electric Cooperative'",
        "UPDATE resource_rules SET phone = '888-342-5766'"
        " WHERE label = 'PNM — Solar Interconnection & Net Metering'",
    ],
    # State-run code pages replace publisher links, then every known url
    # gets its display name.
    9: [f"UPDATE resource_rules SET url = '{_NMAC_NEC}' WHERE url = '{_NEC}'",
        f"UPDATE resource_rules SET url = '{_NMAC_IFC}' WHERE url = '{_IFC}'"] + [
        f"UPDATE resource_rules SET link_text = '{text}' WHERE url = '{url}'"
        for url, text in LINK_TEXTS.items()
    ],
    # July 2026 verified reference set: corrections from the Manual
    # Review Log (dead NMPRC domain, EMNRD path, phones, SMDTC tier...).
    10: CORRECTIONS_V10,
    # Reconcile against the verified body of docs 01-03: county phones from
    # doc 02, and promote items the docs now show verified.
    11: CORRECTIONS_V11,
}

# Vixinman's main products/services — the multi-select on the project form.
PRODUCTS = [
    "PV Systems",
    "Generators",
    "Battery Banks",
    "Well Pumps",
    "Mini Split Air Conditioners",
    "Technician Service",
]

# Shown in the footer of every page so it's always obvious which build
# is running. Bumped with each update. Reset to semantic versioning
# (starting at 0.1) with the Vixinman household rebrand, replacing the
# old solar-business "Piece N.N" build counter.
VERSION = "0.3"

UPLOADS_DIR = DATA_DIR / "uploads"
ALLOWED_EXTENSIONS = {
    "pdf", "png", "jpg", "jpeg", "heic", "gif", "doc", "docx", "xls", "xlsx",
    "csv", "txt", "kmz", "kml", "zip", "bpmn",
}
# Piece 21.7: field crews snap project photos from the Work Bag. Photos are stored
# as project_files tagged with FIELD_PHOTO_LABEL and the originating task.
PHOTO_EXTENSIONS = {"png", "jpg", "jpeg", "heic", "gif"}
FIELD_PHOTO_LABEL = "Field Photo"
# Piece 21.8: every pipeline step that requires photographic documentation gets
# the Work Bag camera button — not only the ones with "photo"/"picture" in the
# name. These substrings are chosen to hit exactly the photo steps in the BPMN
# process and nothing else: the site visit, the install itself, the crew
# walkthrough, doc tube, the meter set, and the re-inspection of corrections
# ("install walkthrough" and "re-inspect" are used, rather than bare
# "walkthrough"/"inspect", so the Sales final walkthrough and the CID inspection
# don't get a camera they don't need).
PHOTO_STEP_KEYWORDS = (
    "photo", "picture", "site visit", "site installation",
    "install walkthrough", "doc tube", "meter set", "re-inspect",
)


def _is_photo_step(title):
    t = (title or "").lower()
    return any(k in t for k in PHOTO_STEP_KEYWORDS)
MATERIAL_STATUSES = ["Needed", "Quoted", "Ordered", "Backordered",
                     "Received", "On hand", "Installed"]
# Piece 12 (revised Piece 33): categories for household-wide documents
# (distinct from a project's requirement categories — these aren't tied to a
# specific project).
HOUSEHOLD_FILE_CATEGORIES = ["Insurance", "Warranty", "Correspondence", "Other"]
# Piece 16: project pipeline stages, redefined to match Vixinman's process phases.
# (Renaming these stages to fit the household model is a separate future piece.)
# Piece 34: pipeline stages renamed for the household reorg. Inspections and
# Closing (two solar-installer-specific back-half stages) merge into one
# Wrap-up stage — that's a genuine merge, not a 1:1 rename, so STAGE_ORDER
# drops from 6 stages to 5.
PROJECT_STATUSES = ["Planning", "Prep", "In Progress", "Wrap-up",
                "Done", "Abandoned"]
PROJECT_STATUS_CLASS = {
    "Planning": "neutral", "Prep": "warn", "In Progress": "warn",
    "Wrap-up": "warn", "Done": "", "Abandoned": "danger",
}
DEFAULT_PROJECT_STATUS = "Planning"
# Piece 18 (revised Piece 35): the exit criteria to advance each pipeline
# status. Used to be role/department-staffed (the "team" key, resolved via
# best_assignee_for_lane on the BPMN lane) — a household doesn't have
# per-stage staffing, so that's gone; `dept` is now just descriptive text.
STATUS_OWNERSHIP = {
    "Planning": {"dept": "Sales", "exit": "Sales signs the contract."},
    "Prep": {"dept": "Prep work",
                 "exit": "All permits filed and an install date set "
                         "(setting the install date advances the project)."},
    "In Progress": {"dept": "Installation", "exit": "Install complete."},
    # Piece 34: merged from the old Inspections + Closing stages.
    "Wrap-up": {"dept": "Wrap-up — sign-off, then one final task each",
                "exit": "Inspection passed and signed off; final invoice,"
                        " walkthrough, and paperwork done."},
    "Done": {"dept": "—", "exit": "Project closed."},
    "Abandoned": {"dept": "—", "exit": ""},
}
# The linear advance path (Abandoned is an off-path terminal state).
STAGE_ORDER = ["Planning", "Prep", "In Progress", "Wrap-up", "Done"]
# Short labels for the tight per-project progress widget (Piece 20.2).
STAGE_SHORT = {"Planning": "Plan", "Prep": "Prep",
               "In Progress": "Progress", "Wrap-up": "Wrap-up", "Done": "Done"}
# Piece 21.6: the stages a crew physically works on site. The Work Bag and the
# Foreman's "My tasks" show only these — office/scheduling steps stay on the
# dashboards where they belong. Wrap-up stays included post-merge: it still
# holds genuine field work (inspection sign-off, meter-set fixes) alongside
# office tasks; my_tasks is already scoped to the viewer's own assignments
# first, so this doesn't leak unrelated work onto an installer's list.
FIELD_STAGES = {"In Progress", "Wrap-up"}


def next_stage(status):
    try:
        i = STAGE_ORDER.index(status)
        return STAGE_ORDER[i + 1] if i + 1 < len(STAGE_ORDER) else None
    except ValueError:
        return None


# Migrate Piece 12.1 statuses to the Piece 16 phases (renamed Piece 34) so
# existing projects survive.
OLD_TO_NEW_STATUS = {
    "Lead": "Planning", "Quoted": "Planning", "Sold": "Prep",
    "Permitting": "Prep", "Scheduled": "In Progress",
    "Installed": "Wrap-up", "Closed": "Done",
}
# Piece 34: the Piece-16-vocabulary -> household-vocabulary stage migration
# map, applied once to any existing project rows by the projects_rename_v1
# block in init_db(). Inspections and Closing both collapse into Wrap-up.
OLD_TO_NEW_STAGE = {
    "Proposal": "Planning", "Job Prep": "Prep", "Installation": "In Progress",
    "Inspections": "Wrap-up", "Closing": "Wrap-up", "Complete": "Done",
    "Lost": "Abandoned",
}
# Piece 10: per-project task assignment.
TASK_STATUSES = ["To do", "In progress", "Blocked", "Done"]
# Days between consecutive generated tasks when a target install date is
# given — a rough schedule anchored on the Site Installation step.
TASK_DUE_SPACING_DAYS = 2
# Piece 20.1: a task's *default* deadline is 7 days after the previous step
# was completed (for the very first step there's nothing completed yet, so it
# counts from the day the steps are generated). When a step is marked Done we
# re-default the next open step to this many days out. Rough on purpose —
# meant to be tightened by hand per project.
TASK_DEFAULT_LEAD_DAYS = 7

# Piece 18.1: infer a pipeline stage for an existing (un-tagged) task from its
# title, so current projects show stage progress. Order matters — specific
# first. Piece 34: the old Inspections and Closing keyword groups both now
# map to the merged Wrap-up stage.
TITLE_STATUS_KEYWORDS = [
    ("sales walkthrough", "Wrap-up"), ("client review", "Wrap-up"),
    ("final 10%", "Wrap-up"), ("final invoice", "Wrap-up"),
    ("final paperwork", "Wrap-up"),
    ("meter set", "Wrap-up"), ("inspection", "Wrap-up"),
    ("sticker", "Wrap-up"), ("letter of compliance", "Wrap-up"),
    ("install walkthrough", "In Progress"), ("site installation", "In Progress"),
    ("doc tube", "In Progress"), ("monitoring", "In Progress"),
    ("40%", "In Progress"),
    ("site visit", "Planning"), ("questionnaire", "Planning"),
    ("draft", "Planning"), ("finalize", "Planning"), ("design", "Planning"),
    ("contract", "Prep"), ("deposit", "Prep"), ("50%", "Prep"),
    ("permit", "Prep"), ("interconnection", "Prep"),
    ("order", "Prep"), ("credit", "Prep"),
    ("installation date", "Prep"), ("plan review", "Prep"),
]

# Piece 9: Electric Loads Calculator / System Sizing config (ported from
# the standalone loads_calculator.html field tool). Catalogs themselves
# live in appliance_catalog / component_catalog (seeded from loads_seed.py).
LOAD_USAGE_TYPES = ["Always-on", "Daily", "Occasional", "Seasonal"]
LOAD_ERAS = ["Modern", "Vintage"]
ROOM_TYPES = ["standard", "scenario"]
# Piece 29.9: kept identical to the Cost Model's Equipment Inventory items so a
# BOM line's category always matches an equipment-markup rate.
COMPONENT_CATEGORIES = [
    "Battery", "Breaker", "Breaker Panel", "Charge Controller", "Controls",
    "Electrical", "Enclosure", "Generator", "Inverter", "mc4", "Monitoring",
    "Office Supplies", "Optimizer", "Pumping", "PV Module", "Racking", "Wire",
]
# system_type presets auto-fill sizing fields on the project page; system_type
# reverts to "custom" on manual edit of a preset-controlled field.
SYSTEM_TYPE_PRESETS = {
    "offgrid": {"derate_pct": 70, "autonomy_days": 3},
    "gridtie": {"derate_pct": 80, "autonomy_days": 1.5},
}
UI_MODES = ["sales", "designer"]


def loads_view_mode(user):
    """Piece 26.4 (revised Piece 35): the Loads & Sizing view mode for this
    viewer. A per-session toggle wins; otherwise defaults to designer mode.
    It's a view preference, not access control."""
    m = session.get("loads_ui_mode")
    if m in UI_MODES:
        return m
    return "designer"


app = Flask(__name__, template_folder=str(BASE_DIR / "templates"))
# Needed for flash messages; fine as a constant for an internal single-box tool.
app.secret_key = "vixinman-home-compendium"
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024  # 25 MB per upload
# Piece 24.7 / 24.8: a sign-in lasts at most this many hours of INACTIVITY — the
# window slides forward on every request, so an active user stays signed in and
# an idle one is dropped 12 hours after their last activity. The cookie also
# slides with the same window as a second layer, but the server-side stamp
# (session["last_active"]) is the authority.
SESSION_MAX_HOURS = 12
app.permanent_session_lifetime = timedelta(hours=SESSION_MAX_HOURS)


# Piece 30.0: money formatting with a thousands separator (comma shows for
# amounts >= 1,000). `money` → 2 decimals, `money0` → whole dollars.
@app.template_filter("money")
def _fmt_money(v):
    try:
        return "{:,.2f}".format(float(v or 0))
    except (ValueError, TypeError):
        return v


@app.template_filter("money0")
def _fmt_money0(v):
    try:
        return "{:,.0f}".format(float(v or 0))
    except (ValueError, TypeError):
        return v


@app.context_processor
def inject_version():
    # `version` keeps the internal build name ("Piece 14.1"); `version_number`
    # is the plain, beta-tester-facing number ("14.1") shown in the footer.
    version_number = VERSION.split(" ", 1)[-1] if VERSION.startswith("Piece ") else VERSION
    return {"version": VERSION, "version_number": version_number}


def get_db():
    """One database connection per request; rows behave like dicts."""
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


# ------------------------------------------------------------- audit log
# Friendlier names for a few endpoints; everything else is prettified from
# the view function name (e.g. delete_component_catalog -> "Delete component
# catalog"), so new routes are logged readably without extra wiring.
ACTION_LABELS = {
    "new_project": "Create project",
    "edit_project": "Edit project", "add_rule": "Add rule", "delete_rule": "Delete rule",
    "backlog_new": "Add backlog idea", "backlog_edit": "Edit backlog idea",
    "backlog_start": "Start idea as a project", "backlog_delete": "Delete backlog idea",
    "new_employee": "Add employee", "edit_employee": "Edit employee",
    "delete_employee": "Delete employee", "upload_file": "Upload project document",
    "generate_tasks": "Generate tasks from process",
    "set_task_status": "Change task status", "set_task_assignee": "Reassign task",
    "set_task_due": "Change task due date", "set_ui_mode": "Change sizing view mode",
    "update_sizing": "Update system sizing",
    "cancel_project": "Cancel project (mark Abandoned)", "reopen_project": "Reopen project",
}
# Endpoints whose POSTs are not user data changes worth logging.
AUDIT_SKIP_ENDPOINTS = set()


def _audit_action(endpoint):
    if not endpoint:
        return "Request"
    return ACTION_LABELS.get(endpoint, endpoint.replace("_", " ").capitalize())


def _audit_detail():
    """A compact JSON snapshot of the submitted fields (the 'input'),
    excluding the redirect helper and truncating long values; uploaded
    file names are noted too."""
    data = {}
    for key in request.form:
        if key == "next":
            continue
        if "password" in key.lower():
            data[key] = "***"          # never log secrets
            continue
        vals = request.form.getlist(key)
        val = vals if len(vals) > 1 else (vals[0] if vals else "")
        if isinstance(val, str) and len(val) > 300:
            val = val[:300] + "…"
        data[key] = val
    names = [f.filename for f in request.files.values() if f and f.filename]
    if names:
        data["_files"] = names
    return json.dumps(data, ensure_ascii=False)[:2000]


@app.after_request
def audit(response):
    """Record every state-changing request. Central by design: nothing a
    feature does can bypass it. Never allowed to break a real request."""
    try:
        if (request.method in ("POST", "PUT", "PATCH", "DELETE")
                and request.endpoint and request.endpoint not in AUDIT_SKIP_ENDPOINTS):
            db = get_db()
            user = current_user()
            db.execute(
                "INSERT INTO audit_log"
                " (actor, action, endpoint, method, path, entity, detail, status, ip)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (user["name"] if user else "", _audit_action(request.endpoint),
                 request.endpoint,
                 request.method, request.path,
                 json.dumps(request.view_args or {}, ensure_ascii=False),
                 _audit_detail(), response.status_code, request.remote_addr or ""),
            )
            db.commit()
    except Exception:
        pass
    return response


# --------------------------------------------------------------- auth (Piece 13)
def accounts_exist():
    """True once at least one household member has a usable login. Until then
    the app runs in open mode (no login wall) so nothing locks up and setup is
    possible."""
    row = get_db().execute(
        "SELECT COUNT(*) FROM household_members"
        " WHERE COALESCE(username,'') != '' AND COALESCE(password_hash,'') != ''"
    ).fetchone()
    return row[0] > 0


def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    return get_db().execute(
        "SELECT * FROM household_members WHERE id = ?", (uid,)).fetchone()


def _is_admin():
    """Admin flag on the household_members row, OR open mode (no accounts yet)
    so the very first account can be set up."""
    if not accounts_exist():
        return True
    user = current_user()
    return user is not None and str(user["is_admin"] or "") == "1"


def _has_grant(user, perm):
    """A standing permission grant for this user."""
    if user is None:
        return False
    return get_db().execute(
        "SELECT 1 FROM permission_grants WHERE household_member_id = ?"
        " AND permission = ? LIMIT 1", (user["id"], perm)).fetchone() is not None


def notify_employees(db, recipient_ids, message, link="", kind=""):
    """Piece 29.3: drop an in-app notification to each recipient household
    member id."""
    for rid in dict.fromkeys(recipient_ids):   # de-dupe, preserve order
        db.execute(
            "INSERT INTO notifications (recipient_id, message, link, kind)"
            " VALUES (?, ?, ?, ?)", (rid, message, link, kind))


def project_involved_ids(db, project, exclude_id=None):
    """Piece 30.3: household members involved in a project so far — anyone
    assigned a task on it. Only those with a login (who can read an inbox);
    the given id is dropped."""
    ids = set()
    for r in db.execute("SELECT DISTINCT household_member_id FROM project_tasks"
                        " WHERE project_id = ? AND household_member_id IS NOT NULL",
                        (project["id"],)).fetchall():
        ids.add(r["household_member_id"])
    ids.discard(None)
    ids.discard(exclude_id)
    if not ids:
        return []
    ph = ",".join("?" * len(ids))
    return [r["id"] for r in db.execute(
        f"SELECT id FROM household_members WHERE id IN ({ph})"
        " AND COALESCE(username,'') != ''", tuple(ids)).fetchall()]


def unread_notification_count(user):
    if user is None:
        return 0
    try:
        return get_db().execute(
            "SELECT COUNT(*) FROM notifications WHERE recipient_id = ?"
            " AND COALESCE(is_read,'') != '1'", (user["id"],)).fetchone()[0]
    except Exception:
        return 0


def household_member_ids_with_login(db, exclude_id=None):
    """Piece 35: everyone who can sign in — the audience for a shared
    household notification, now that there's no department roster to target."""
    return [r["id"] for r in db.execute(
        "SELECT id FROM household_members WHERE COALESCE(username,'') != ''"
        ).fetchall() if r["id"] != exclude_id]


def notify_stage_turnover(db, project, new_status, exclude_id=None):
    """Piece 29.4 (revised Piece 35): when a project turns over to a pipeline
    stage, notify every household member with a login. The recipient's copy
    clears once they open it (or open the project). The person who triggered
    the move is skipped."""
    own = STATUS_OWNERSHIP.get(new_status)
    if not own:
        return
    recipients = household_member_ids_with_login(db, exclude_id=exclude_id)
    if not recipients:
        return
    jobname = project["job_name"] or f"Project #{project['id']}"
    notify_employees(
        db, recipients, f"📋 {jobname} turned over to {new_status}.",
        link=url_for("project_detail", project_id=project["id"]), kind="stage")


def security_questions_enrolled(household_member_id):
    """The security questions this household member has set up (for the
    reset flow)."""
    return get_db().execute(
        "SELECT * FROM security_answers WHERE household_member_id = ?"
        " ORDER BY sort_order, id", (household_member_id,)).fetchall()


def has_permission(perm):
    """Central access check. Admin ⇒ everything except 'delete', which stays
    grant-only even for admins (the soft-delete safety rail). Everyone else
    needs an explicit grant. perm=None is the generic admin gate."""
    if not accounts_exist():
        return True
    user = current_user()
    if user is None:
        return False
    if perm == "delete":
        return _has_grant(user, "delete")   # never automatic, even for admins
    if perm is None:
        return _is_admin()
    if _is_admin():
        return True
    return _has_grant(user, perm)


# Which permission each admin-gated view needs (Piece 17). Views not listed
# fall back to the generic admin gate (perm=None).
VIEW_PERMISSION = {
    "add_appliance_catalog": "catalog.manage",
    "delete_appliance_catalog": "catalog.manage",
    "add_component_catalog": "catalog.manage",
    "delete_component_catalog": "catalog.manage",
    "submissions_page": "approvals",
    "approve_submission": "approvals",
    "reject_submission": "approvals",
    "add_rule": "rules.manage",
    "delete_rule": "rules.manage",
    "accounts_page": "household.manage",
    "approve_password_change": "household.manage",
    "reject_password_change": "household.manage",
    "new_household_member": "household.manage",
    "edit_household_member": "household.manage",
    "delete_household_member": "household.manage",
    "add_credential": "household.manage",
    "update_credential": "household.manage",
    "delete_credential": "household.manage",
    "upload_household_member_file": "household.manage",
    "delete_household_member_file": "household.manage",
    "audit_log_page": "audit.view",
    # Piece 24.6: inventory editing is scoped to inventory.manage (viewing the
    # catalog stays open to any signed-in user).
    "inventory_item_new": "inventory.manage",
    "inventory_item_edit": "inventory.manage",
    "inventory_item_adjust": "inventory.manage",
    "inventory_tool_new": "inventory.manage",
    "inventory_tool_edit": "inventory.manage",
    "inventory_vehicle_new": "inventory.manage",
    "inventory_vehicle_edit": "inventory.manage",
    "inventory_stale": "inventory.manage",
    "inventory_stale_keep": "inventory.manage",
    "inventory_stale_discontinue": "inventory.manage",
    "inventory_toggle_stale": "inventory.manage",   # Piece 30.4
    # Piece 26.0/26.1: registering & printing tags is the warehouse manager's
    # project; scanning to load a truck is open to any signed-in worker (Installers
    # included) so a crew can load in parallel — those routes are NOT listed here.
    "inventory_assets": "inventory.manage",
    "inventory_asset_register": "inventory.register",
    "inventory_asset_labels": "inventory.manage",
    "inventory_asset_retire": "inventory.register",
    # Piece 28.5: stock audits are warehouse-manager work.
    "inventory_audit": "inventory.manage",
    "inventory_audit_start": "inventory.manage",
    "inventory_audit_session": "inventory.manage",
    "inventory_audit_scan": "inventory.manage",
    "inventory_audit_finish": "inventory.manage",
    "inventory_audit_report": "inventory.manage",
    "inventory_audit_report_csv": "inventory.manage",
    "inventory_audit_scan_delete": "inventory.manage",
}


def admin_required(view):
    """Guard a shared-data view by the permission it maps to (or the generic
    admin gate). Granting that permission to a non-admin opens exactly this
    tool for them."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not has_permission(VIEW_PERMISSION.get(view.__name__)):
            flash("You don't have access to that. Ask an admin.", "error")
            return redirect(url_for("home"))
        return view(*args, **kwargs)
    return wrapped


def _can_see_pricing():
    """Piece 29.7 (revised Piece 35): who may see the internal cost/margin
    pricing breakdown — admins only. Deliberately narrow: it exposes cost and
    margin."""
    return _is_admin()


def finance_required(view):
    """Guard the surviving cost-model/GRT-rate settings pages to admins."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not _is_admin():
            flash("That's limited to admins.", "error")
            return redirect(url_for("home"))
        return view(*args, **kwargs)
    return wrapped


def _meta_get(db, key, default=""):
    row = db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def _meta_set(db, key, value):
    db.execute("INSERT INTO meta (key, value) VALUES (?, ?)"
               " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
               (key, str(value)))


@app.context_processor
def inject_auth():
    user = current_user()
    pending = 0
    if has_permission("approvals"):
        try:
            pending = get_db().execute(
                "SELECT COUNT(*) FROM field_submissions WHERE status = 'Pending'"
            ).fetchone()[0]
        except Exception:
            pending = 0
    return {"current_user": user, "login_active": accounts_exist(),
            "is_admin": _is_admin(), "can": has_permission,
            "unread_notifications": unread_notification_count(user),  # Piece 29.3
            "pending_submissions": pending}


@app.route("/access")
@admin_required
def access_console():
    """Admin console: grant individual tools to household members."""
    db = get_db()
    people = db.execute(
        "SELECT * FROM household_members WHERE COALESCE(username,'') != '' ORDER BY name"
    ).fetchall()
    grants = {}
    for g in db.execute("SELECT household_member_id, permission FROM permission_grants"):
        grants.setdefault(g["household_member_id"], set()).add(g["permission"])
    rows = [{
        "id": p["id"], "name": p["name"],
        "is_admin": str(p["is_admin"] or "") == "1",
        "grants": grants.get(p["id"], set()),
    } for p in people]
    return render_template("access.html", rows=rows, permissions=PERMISSIONS)


@app.route("/access/<int:member_id>", methods=["POST"])
@admin_required
def save_access(member_id):
    db = get_db()
    member = db.execute("SELECT * FROM household_members WHERE id = ?",
                        (member_id,)).fetchone()
    if member is None:
        abort(404)
    who = current_user()
    granter = who["name"] if who else ""
    db.execute("DELETE FROM permission_grants WHERE household_member_id = ?", (member_id,))
    for key in PERMISSIONS:
        if request.form.get(f"perm_{key}"):
            db.execute(
                "INSERT INTO permission_grants (household_member_id, permission,"
                " granted_by) VALUES (?, ?, ?)", (member_id, key, granter))
    db.commit()
    flash(f"Access updated for {member['name']}.")
    return redirect(url_for("access_console", _anchor=f"member{member_id}"))


# ===================== Piece 17.1: soft-delete / trash / in-use checks ======
def delete_required(view):
    """Deletion is GM-only or granted (the 'delete' permission)."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not has_permission("delete"):
            flash("Deleting is limited to the General Manager (or staff granted "
                  "the Delete permission).", "error")
            return redirect(request.referrer or url_for("home"))
        return view(*args, **kwargs)
    return wrapped


def _count(db, sql, params):
    return db.execute(sql, params).fetchone()[0]


def _project_name(db, jid):
    r = db.execute("SELECT job_name FROM projects WHERE id = ?", (jid,)).fetchone()
    return (r["job_name"] if r and r["job_name"] else f"Project #{jid}")


def _emp_name(db, eid):
    r = db.execute("SELECT name FROM household_members WHERE id = ?", (eid,)).fetchone()
    return r["name"] if r else f"Household member #{eid}"


def _component_uses(db, cid):
    uses = []
    n = _count(db, "SELECT COUNT(*) FROM project_bom WHERE component_id = ?", (cid,))
    if n:
        uses.append(f"{n} project bill-of-materials line(s)")
    n = _count(db, "SELECT COUNT(*) FROM project_sizing WHERE selected_battery_id = ?"
               " OR selected_pv_module_id = ?", (cid, cid))
    if n:
        uses.append(f"{n} project sizing selection(s)")
    return uses


def _employee_uses(db, eid):
    uses = []
    n = _count(db, "SELECT COUNT(*) FROM project_tasks WHERE household_member_id = ?", (eid,))
    if n:
        uses.append(f"{n} assigned task(s)")
    n = _count(db, "SELECT COUNT(*) FROM field_submissions WHERE household_member_id = ?", (eid,))
    if n:
        uses.append(f"{n} field-work submission(s)")
    return uses


# entity_type -> how to label it, where it lived, what would block its delete,
# and (for file rows) where its file sits on disk.
TRASH_REGISTRY = {
    "rule": {"table": "resource_rules", "label": lambda r: r["label"],
             "found_in": lambda db, r: "Rules",
             "in_use": lambda db, r: (
                 [f"{_count(db, 'SELECT COUNT(*) FROM project_files WHERE rule_label = ?', (r['label'],))} filed document(s)"]
                 if _count(db, "SELECT COUNT(*) FROM project_files WHERE rule_label = ?", (r["label"],)) else [])},
    "appliance": {"table": "appliance_catalog", "label": lambda r: r["name"],
                  "found_in": lambda db, r: "Appliance catalog",
                  "in_use": lambda db, r: []},
    "component": {"table": "component_catalog", "label": lambda r: r["name"],
                  "found_in": lambda db, r: "Component catalog",
                  "in_use": lambda db, r: _component_uses(db, r["id"])},
    "material": {"table": "project_materials", "label": lambda r: r["item"],
                 "found_in": lambda db, r: f"{_project_name(db, r['project_id'])} — Materials",
                 "in_use": lambda db, r: []},
    "task": {"table": "project_tasks", "label": lambda r: r["title"],
             "found_in": lambda db, r: f"{_project_name(db, r['project_id'])} — Tasks",
             "in_use": lambda db, r: (
                 [f"{_count(db, 'SELECT COUNT(*) FROM field_submission_items WHERE task_id = ?', (r['id'],))} field submission(s)"]
                 if _count(db, "SELECT COUNT(*) FROM field_submission_items WHERE task_id = ?", (r["id"],)) else [])},
    "load_room": {"table": "project_load_rooms", "label": lambda r: r["name"],
                  "found_in": lambda db, r: f"{_project_name(db, r['project_id'])} — Loads",
                  "in_use": lambda db, r: (
                      [f"{_count(db, 'SELECT COUNT(*) FROM project_load_items WHERE room_id = ?', (r['id'],))} appliance(s) in the room"]
                      if _count(db, "SELECT COUNT(*) FROM project_load_items WHERE room_id = ?", (r["id"],)) else [])},
    "load_item": {"table": "project_load_items", "label": lambda r: r["appliance"],
                  "found_in": lambda db, r: f"{_project_name(db, r['project_id'])} — Loads",
                  "in_use": lambda db, r: []},
    "bom": {"table": "project_bom", "label": lambda r: r["component_name"],
            "found_in": lambda db, r: f"{_project_name(db, r['project_id'])} — Components",
            "in_use": lambda db, r: []},
    "project_file": {"table": "project_files", "label": lambda r: r["original_name"],
                 "found_in": lambda db, r: f"{_project_name(db, r['project_id'])} — Documents",
                 "in_use": lambda db, r: [],
                 "file": lambda r: UPLOADS_DIR / f"job_{r['project_id']}" / r["stored_name"]},
    "household_file": {"table": "household_files", "label": lambda r: r["original_name"],
                       "found_in": lambda db, r: "Household Files",
                       "in_use": lambda db, r: [],
                       "file": lambda r: UPLOADS_DIR / "household" / r["stored_name"]},
    "household_idea": {"table": "household_ideas", "label": lambda r: r["name"],
                       "found_in": lambda db, r: "Backlog",
                       "in_use": lambda db, r: []},
    "external_helper": {"table": "external_helpers", "label": lambda r: r["name"],
                        "found_in": lambda db, r: "External Helpers",
                        "in_use": lambda db, r: []},
    "credential": {"table": "household_member_credentials", "label": lambda r: r["name"],
                   "found_in": lambda db, r: f"{_emp_name(db, r['household_member_id'])} — Credentials",
                   "in_use": lambda db, r: []},
    "employee_file": {"table": "household_member_files", "label": lambda r: r["original_name"],
                      "found_in": lambda db, r: f"{_emp_name(db, r['household_member_id'])} — Documents",
                      "in_use": lambda db, r: [],
                      "file": lambda r: UPLOADS_DIR / f"employee_{r['household_member_id']}" / r["stored_name"]},
    "employee": {"table": "household_members", "label": lambda r: r["name"],
                 "found_in": lambda db, r: "Household Members",
                 "in_use": lambda db, r: _employee_uses(db, r["id"])},
    "inventory_item": {"table": "inventory_items",
                       "label": lambda r: f"{r['make']} {r['model']}".strip() or r["category"],
                       "found_in": lambda db, r: f"Inventory — {r['category']}",
                       "in_use": lambda db, r: []},
    "inventory_tool": {"table": "inventory_tools",
                       "label": lambda r: r["name"] or "Tool",
                       "found_in": lambda db, r: "Inventory — Tools",
                       "in_use": lambda db, r: []},
    "inventory_vehicle": {"table": "inventory_vehicles",
                          "label": lambda r: r["name"] or "Vehicle",
                          "found_in": lambda db, r: "Inventory — Vehicles",
                          "in_use": lambda db, r: []},
}


def trash_item(entity_type, row_id):
    """Move a row to the trash if it isn't in use. Returns (ok, message)."""
    cfg = TRASH_REGISTRY[entity_type]
    db = get_db()
    row = db.execute(f"SELECT * FROM {cfg['table']} WHERE id = ?", (row_id,)).fetchone()
    if row is None:
        return False, "That item no longer exists."
    blockers = cfg["in_use"](db, row)
    if blockers:
        return False, (f"Can't delete “{cfg['label'](row)}” — it's still in use by "
                       + "; ".join(blockers) + ". Remove those first.")
    user = current_user()
    db.execute(
        "INSERT INTO trash (entity_type, origin_table, original_id, found_in,"
        " label, payload, deleted_by) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (entity_type, cfg["table"], row_id, cfg["found_in"](db, row),
         cfg["label"](row), json.dumps({k: row[k] for k in row.keys()}),
         user["name"] if user else ""))
    db.execute(f"DELETE FROM {cfg['table']} WHERE id = ?", (row_id,))
    db.commit()
    return True, f"Moved to trash: {cfg['label'](row)}. Restore it from the Trash page."


@app.route("/trash")
@delete_required
def trash_page():
    db = get_db()
    rows = db.execute("SELECT * FROM trash ORDER BY deleted_at DESC").fetchall()
    return render_template("trash.html", rows=rows)


@app.route("/trash/<int:trash_id>/restore", methods=["POST"])
@delete_required
def restore_trash(trash_id):
    db = get_db()
    t = db.execute("SELECT * FROM trash WHERE id = ?", (trash_id,)).fetchone()
    if t is None:
        abort(404)
    payload = json.loads(t["payload"])
    cols = list(payload.keys())
    placeholders = ", ".join("?" * len(cols))
    try:
        db.execute(f"INSERT INTO {t['origin_table']} ({', '.join(cols)})"
                   f" VALUES ({placeholders})", [payload[c] for c in cols])
    except sqlite3.IntegrityError:
        # Original id was taken since deletion — restore under a fresh id.
        cols = [c for c in cols if c != "id"]
        placeholders = ", ".join("?" * len(cols))
        db.execute(f"INSERT INTO {t['origin_table']} ({', '.join(cols)})"
                   f" VALUES ({placeholders})", [payload[c] for c in cols])
    db.execute("DELETE FROM trash WHERE id = ?", (trash_id,))
    db.commit()
    flash(f"Restored: {t['label']} (back in {t['found_in']}).")
    return redirect(url_for("trash_page"))


@app.route("/trash/<int:trash_id>/purge", methods=["POST"])
@admin_required
def purge_trash(trash_id):
    """Permanent deletion — admin only."""
    db = get_db()
    t = db.execute("SELECT * FROM trash WHERE id = ?", (trash_id,)).fetchone()
    if t is None:
        abort(404)
    cfg = TRASH_REGISTRY.get(t["entity_type"], {})
    if "file" in cfg:
        try:
            cfg["file"](json.loads(t["payload"])).unlink(missing_ok=True)
        except Exception:
            pass
    db.execute("DELETE FROM trash WHERE id = ?", (trash_id,))
    db.commit()
    flash(f"Permanently deleted: {t['label']}.")
    return redirect(url_for("trash_page"))


def _session_expired():
    """True when the last activity on this sign-in was more than
    SESSION_MAX_HOURS ago (a sliding idle window). A session with no stamp
    (pre-24.7, or tampered) counts as expired so it can't outlive the policy."""
    if "user_id" not in session:
        return False
    ts = session.get("last_active")
    if not ts:
        return True
    try:
        seen = datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return True
    return datetime.now() - seen >= timedelta(hours=SESSION_MAX_HOURS)


@app.before_request
def require_login():
    """Once logins are configured, every page needs one (except the login
    page itself and static files). In open mode this does nothing."""
    if not accounts_exist():
        return
    # The service worker and its offline fallback must load without a session
    # (the whole point is offline / pre-auth cold-start).
    if request.endpoint in ("login", "static", "service_worker",
                            "offline_page", "forgot_password",
                            "forgot_password_verify", None):
        return
    # Piece 24.8: drop a sign-in idle past the limit; otherwise slide the
    # inactivity window forward so active users stay signed in.
    if "user_id" in session:
        if _session_expired():
            session.clear()
            if request.path.startswith("/api/"):
                return jsonify({"error": "session expired"}), 401
            flash(f"Signed out after {SESSION_MAX_HOURS} hours of inactivity for "
                  "security. Please sign in again.")
            nxt = request.path if request.method == "GET" else None
            return redirect(url_for("login", next=nxt))
        session["last_active"] = datetime.now().isoformat(timespec="seconds")
    user = current_user()
    if user is None:
        if request.path.startswith("/api/"):
            return jsonify({"error": "not signed in"}), 401
        nxt = request.path if request.method == "GET" else None
        return redirect(url_for("login", next=nxt))


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user() is not None:
        return redirect(url_for("home"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        # Usernames are matched case-insensitively (passwords stay exact).
        user = get_db().execute(
            "SELECT * FROM household_members WHERE LOWER(username) = LOWER(?)"
            " AND COALESCE(username,'') != ''",
            (username,)).fetchone()
        try:
            ok = bool(user and user["password_hash"] and check_password_hash(
                user["password_hash"], password))
        except Exception:  # e.g. scrypt hashing backend unavailable in a frozen build
            ok = False
            flash("This account's password can't be verified on this machine "
                  "(hashing backend unavailable). Ask a manager to reset it, or "
                  "reset the local database.", "error")
            return render_template("login.html", next=request.args.get("next", ""))
        if ok:
            session["user_id"] = user["id"]
            # Piece 24.8: stamp last activity so the session self-expires after
            # 12 hours of inactivity (the window slides on each request).
            session.permanent = True
            session["last_active"] = datetime.now().isoformat(timespec="seconds")
            flash(f"Signed in as {user['name']}.")
            # Honor a deep link (e.g. a specific project someone opened while
            # logged out). "/" and "/dashboard" are the same view now, so the
            # nxt != "/" exclusion below is just a no-op landing normalization.
            nxt = request.form.get("next") or ""
            if nxt.startswith("/") and not nxt.startswith("//") and nxt != "/":
                return redirect(nxt)
            return redirect(url_for("dashboard"))
        flash("Wrong username or password.", "error")
    return render_template("login.html", next=request.args.get("next", ""))


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("Signed out.")
    return redirect(url_for("login"))


def _notify_failed_reset(db, user):
    """Piece 29.3 (revised Piece 35): too many wrong reset answers notifies
    every admin with a login, so a human reviews it and resets the password
    directly (there's no emergency-lockout mechanism to auto-apply anymore)."""
    recipients = [r["id"] for r in db.execute(
        "SELECT id FROM household_members WHERE is_admin = '1'"
        " AND COALESCE(username,'') != '' AND id != ?", (user["id"],)).fetchall()]
    notify_employees(
        db, recipients,
        f"🔒 {user['name']} had {SECURITY_RESET_MAX_ATTEMPTS} failed"
        " password-reset attempts. They'll need their password reset directly.",
        link=url_for("household_member_detail", household_member_id=user["id"]),
        kind="security")
    db.commit()


def _clear_reset_session():
    for k in ("pwreset_uid", "pwreset_attempts", "pwreset_ask"):
        session.pop(k, None)


@app.route("/forgot", methods=["GET", "POST"])
def forgot_password():
    """Piece 29.1/29.3: step 1 of self-service reset — identify the account. If
    it has security questions enrolled (and isn't suspended), pick a random
    subset to ask and move to the answer step; otherwise send them to a manager,
    without confirming whether the username exists."""
    if current_user() is not None:
        return redirect(url_for("home"))
    generic = ("If that account has security questions set up, you'll be asked "
               "some of them next. If not, ask a manager to reset your password.")
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        user = get_db().execute(
            "SELECT * FROM household_members WHERE LOWER(username) = LOWER(?)"
            " AND COALESCE(username,'') != ''", (username,)).fetchone()
        enrolled = security_questions_enrolled(user["id"]) if user else []
        # Only proceed for a real, active login that has questions enrolled.
        if user and user["password_hash"] and enrolled:
            ids = [q["id"] for q in enrolled]
            # Randomly choose which questions to ask this time (2 of 3).
            ask = random.sample(ids, min(SECURITY_QUESTIONS_ASK, len(ids)))
            session["pwreset_uid"] = user["id"]
            session["pwreset_attempts"] = 0
            session["pwreset_ask"] = ask
            return redirect(url_for("forgot_password_verify"))
        flash(generic)
        return redirect(url_for("forgot_password"))
    return render_template("forgot.html")


@app.route("/forgot/verify", methods=["GET", "POST"])
def forgot_password_verify():
    """Piece 29.1/29.3: step 2 — answer the randomly-chosen questions (matched
    exactly, case-sensitive) and set a new password directly. Too many wrong
    tries auto-locks the account and notifies a supervisor."""
    if current_user() is not None:
        return redirect(url_for("home"))
    uid = session.get("pwreset_uid")
    ask = session.get("pwreset_ask") or []
    if not uid or not ask:
        return redirect(url_for("forgot_password"))
    db = get_db()
    user = db.execute("SELECT * FROM household_members WHERE id = ?", (uid,)).fetchone()
    enrolled = {q["id"]: q for q in security_questions_enrolled(uid)} if user else {}
    # The chosen questions, in the order they were picked.
    questions = [enrolled[i] for i in ask if i in enrolled]
    if not user or len(questions) != len(ask):
        _clear_reset_session()
        flash("That reset is no longer valid. Ask a manager for help.", "error")
        return redirect(url_for("login"))
    if request.method == "POST":
        # Case-sensitive exact match, like a password.
        all_ok = all(
            check_password_hash(q["answer_hash"],
                                request.form.get(f"answer_{q['id']}", ""))
            for q in questions)
        new = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")
        if not all_ok:
            session["pwreset_attempts"] = session.get("pwreset_attempts", 0) + 1
            if session["pwreset_attempts"] >= SECURITY_RESET_MAX_ATTEMPTS:
                _notify_failed_reset(db, user)
                _clear_reset_session()
                flash("Too many incorrect answers — for security, an admin has "
                      "been notified and will need to reset your password "
                      "directly.", "error")
                return redirect(url_for("login"))
            left = SECURITY_RESET_MAX_ATTEMPTS - session["pwreset_attempts"]
            flash(f"One or more answers were incorrect. {left} attempt(s) left "
                  "before the account is locked.", "error")
            return render_template("forgot_verify.html", questions=questions)
        if len(new) < PASSWORD_MIN_LEN:
            flash(f"New password must be at least {PASSWORD_MIN_LEN} characters.",
                  "error")
            return render_template("forgot_verify.html", questions=questions)
        if new != confirm:
            flash("New password and confirmation don't match.", "error")
            return render_template("forgot_verify.html", questions=questions)
        db.execute("UPDATE household_members SET password_hash = ? WHERE id = ?",
                   (generate_password_hash(new, method="pbkdf2:sha256"), uid))
        db.execute("DELETE FROM password_requests WHERE household_member_id = ?"
                   " AND status = 'Pending'", (uid,))
        db.commit()
        _clear_reset_session()
        flash("✓ Password reset. Sign in with your new password.")
        return redirect(url_for("login"))
    return render_template("forgot_verify.html", questions=questions)


@app.route("/notifications")
def notifications_page():
    """Piece 29.3: the signed-in user's in-app inbox."""
    user = current_user()
    if user is None:
        return redirect(url_for("login"))
    items = get_db().execute(
        "SELECT * FROM notifications WHERE recipient_id = ?"
        " ORDER BY (COALESCE(is_read,'') = '1'), id DESC", (user["id"],)).fetchall()
    return render_template("notifications.html", items=items)


@app.route("/notifications/clear-all", methods=["POST"])
def notifications_clear_all():
    user = current_user()
    if user is None:
        return redirect(url_for("login"))
    db = get_db()
    db.execute("DELETE FROM notifications WHERE recipient_id = ?", (user["id"],))
    db.commit()
    return redirect(url_for("notifications_page"))


@app.route("/notifications/<int:note_id>/open")
def notification_open(note_id):
    """Piece 29.4: accessing a notification CLEARS it for that user (deletes
    their copy), then follows its link (or returns to the inbox)."""
    user = current_user()
    if user is None:
        return redirect(url_for("login"))
    db = get_db()
    note = db.execute(
        "SELECT * FROM notifications WHERE id = ? AND recipient_id = ?",
        (note_id, user["id"])).fetchone()
    if note is None:
        abort(404)
    dest = note["link"] or url_for("notifications_page")
    if not (dest.startswith("/") and not dest.startswith("//")):
        dest = url_for("notifications_page")
    db.execute("DELETE FROM notifications WHERE id = ?", (note_id,))
    db.commit()
    return redirect(dest)


@app.route("/sw.js")
def service_worker():
    """Piece 24.9: the service worker, served from root so it controls the whole
    app. Caches visited pages for offline cold-start (Work Bag in the field)."""
    resp = Response(render_template("service_worker.js", version=VERSION),
                    mimetype="application/javascript")
    resp.headers["Service-Worker-Allowed"] = "/"
    resp.headers["Cache-Control"] = "no-cache"   # always revalidate the SW itself
    return resp


@app.route("/offline")
def offline_page():
    """Offline fallback shown by the service worker when a page isn't cached."""
    return render_template("offline.html")


@app.route("/account")
def account():
    """The signed-in user's own page: change your password (with admin
    approval) and see any pending request."""
    user = current_user()
    if user is None:
        return redirect(url_for("home"))
    pending = get_db().execute(
        "SELECT * FROM password_requests WHERE household_member_id = ? AND status = 'Pending'"
        " ORDER BY id DESC LIMIT 1", (user["id"],)).fetchone()
    enrolled = security_questions_enrolled(user["id"])
    return render_template("account.html", user=user, pending=pending,
                           security_questions=SECURITY_QUESTIONS,
                           enrolled=enrolled,
                           questions_required=SECURITY_QUESTIONS_REQUIRED,
                           questions_answered=SECURITY_QUESTIONS_ASK)


@app.route("/account/password", methods=["POST"])
def request_password_change():
    """Verify the current password, hash the proposed one, and queue it for
    admin approval. The new password is stored only as a hash."""
    user = current_user()
    if user is None:
        return redirect(url_for("home"))
    current = request.form.get("current_password", "")
    new = request.form.get("new_password", "")
    confirm = request.form.get("confirm_password", "")
    if not user["password_hash"] or not check_password_hash(user["password_hash"], current):
        flash("Your current password is incorrect.", "error")
    elif len(new) < PASSWORD_MIN_LEN:
        flash(f"New password must be at least {PASSWORD_MIN_LEN} characters.", "error")
    elif new != confirm:
        flash("New password and confirmation don't match.", "error")
    else:
        db = get_db()
        # One pending request at a time — a new one supersedes the old.
        db.execute("DELETE FROM password_requests"
                   " WHERE household_member_id = ? AND status = 'Pending'", (user["id"],))
        db.execute(
            "INSERT INTO password_requests (household_member_id, new_hash) VALUES (?, ?)",
            (user["id"], generate_password_hash(new, method="pbkdf2:sha256")))
        db.commit()
        flash("Password change submitted — it takes effect once an admin approves it.")
    return redirect(url_for("account"))


@app.route("/account/password/cancel", methods=["POST"])
def cancel_password_change():
    user = current_user()
    if user is None:
        return redirect(url_for("home"))
    db = get_db()
    db.execute("DELETE FROM password_requests"
               " WHERE household_member_id = ? AND status = 'Pending'", (user["id"],))
    db.commit()
    flash("Password request cancelled.")
    return redirect(url_for("account"))


@app.route("/account/security-questions", methods=["POST"])
def save_security_questions():
    """Piece 29.1: enrol (or replace) the signed-in user's security questions
    for self-service password reset. Answers are normalised and stored only as
    salted hashes. Requires SECURITY_QUESTIONS_REQUIRED distinct questions with
    non-blank answers; verifying the current password guards enrolment."""
    user = current_user()
    if user is None:
        return redirect(url_for("home"))
    current = request.form.get("current_password", "")
    if not user["password_hash"] or not check_password_hash(
            user["password_hash"], current):
        flash("Enter your current password to save security questions.", "error")
        return redirect(url_for("account"))
    pairs, seen = [], set()
    for i in range(SECURITY_QUESTIONS_REQUIRED):
        q = request.form.get(f"question_{i}", "").strip()
        a = request.form.get(f"answer_{i}", "")
        # Answers are matched exactly (case-sensitive, like a password); only a
        # wholly blank answer is rejected.
        if not q or not a.strip():
            flash(f"Fill in all {SECURITY_QUESTIONS_REQUIRED} questions and "
                  "answers.", "error")
            return redirect(url_for("account"))
        key = q.lower()
        if key in seen:
            flash("Please choose a different question for each answer.", "error")
            return redirect(url_for("account"))
        seen.add(key)
        pairs.append((q, a))
    db = get_db()
    db.execute("DELETE FROM security_answers WHERE household_member_id = ?", (user["id"],))
    for order, (q, a) in enumerate(pairs):
        db.execute(
            "INSERT INTO security_answers (household_member_id, question, answer_hash,"
            " sort_order) VALUES (?, ?, ?, ?)",
            (user["id"], q,
             generate_password_hash(a, method="pbkdf2:sha256"), order))
    db.commit()
    flash("✓ Security questions saved — you can now reset your own password if "
          "you're ever locked out.")
    return redirect(url_for("account"))


def ensure_columns(db, table, columns):
    """Auto-upgrade an existing database: add any columns the table is
    missing. Lets the schema evolve piece by piece without anyone having
    to delete their job_creator.db."""
    existing = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
    for column in columns:
        if column not in existing:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT DEFAULT ''")


def seed_org_team(db):
    """Piece 16.1 (revised Piece 35): create the household's roster (by name)
    with their role and admin status. Runs once per database (guarded by a
    meta flag) and skips anyone already present, so it populates a fresh
    install without duplicating and never resurrects someone who was deleted
    on purpose."""
    if db.execute("SELECT 1 FROM meta WHERE key = 'org_team_seeded'").fetchone():
        return
    for name, role, admin in HOUSEHOLD_ROSTER:
        if not db.execute("SELECT 1 FROM household_members WHERE name = ?",
                          (name,)).fetchone():
            db.execute("INSERT INTO household_members (name, role, is_admin)"
                       " VALUES (?, ?, ?)", (name, role, "1" if admin else ""))
    db.execute("INSERT INTO meta (key, value) VALUES ('org_team_seeded', '1')"
               " ON CONFLICT(key) DO UPDATE SET value = excluded.value")
    db.commit()


def seed_inventory(db):
    """Piece 23.2: load Vixinman's seed inventory (vendors, 439 items, a standard
    tool kit, and the vehicle/heavy-equipment list) once per database. Guarded
    by a meta flag so it never duplicates or resurrects deleted rows."""
    if db.execute("SELECT 1 FROM meta WHERE key = 'inventory_seeded'").fetchone():
        return
    for vid, name in INVENTORY_VENDORS:
        db.execute("INSERT OR IGNORE INTO inventory_vendors (id, name) VALUES (?, ?)",
                   (vid, name))
    for it in INVENTORY_ITEMS:
        db.execute(
            "INSERT INTO inventory_items"
            " (category, make, model, description, vendor_id, vendor_number,"
            "  cost, specs) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (it["category"], it["make"], it["model"], it["description"],
             it["vendor_id"], it["vendor_number"], it["cost"],
             json.dumps(it["specs"], default=str)))
    for name, cat in INVENTORY_TOOLS:
        db.execute("INSERT INTO inventory_tools (name, category) VALUES (?, ?)",
                   (name, cat))
    for name, cat, nick in INVENTORY_VEHICLES:
        db.execute("INSERT INTO inventory_vehicles (name, category, nickname)"
                   " VALUES (?, ?, ?)", (name, cat, nick))
    db.execute("INSERT INTO meta (key, value) VALUES ('inventory_seeded', '1')"
               " ON CONFLICT(key) DO UPDATE SET value = excluded.value")
    db.commit()


# Piece 23.7: vendor standardization. Rename to canonical spelling; merge true
# duplicates (reassigning their items to the survivor); drop stray combined
# entries. Bump VENDOR_STD_VERSION to re-run after adding more.
VENDOR_STD_VERSION = 1
VENDOR_RENAME = {2446: "Megarevo"}          # Magerevo/Megavero typo -> brand
VENDOR_MERGE = {1487: 2000}                 # Battery Systems -> Continental Battery Systems (2021 merger)
VENDOR_REMOVE = {1804}                       # "Summit/Graybar" stray combined entry (0 items)

# Piece 23.8: make (manufacturer) standardization. Runs before research so the
# research keys reference canonical makes.
MAKE_STD_VERSION = 1
MAKE_FIX = {
    "MidNite": "MidNite Solar", "Midnite Solar": "MidNite Solar",
    "Outback": "Outback Power", "Schneider": "Schneider Electric",
    "Solar Rackworks": "Solar Rack Works",
    "Solar Rack Works Top of Pole": "Solar Rack Works",
    "Solar World": "SolarWorld", "Calb": "CALB",
    "Vicrton BlueSolar MPPT 150-60--Tr": "Victron",
    "MILBANK U7021-RL-TG-200 1PH": "Milbank", "Milbank or Equivalent": "Milbank",
}
MAKE_FLAG = {  # Make column holds a part type/description, not a manufacturer.
    "MTWC-0000-BLK": "Make column holds a part number, not a manufacturer — assign the real make.",
    "MTWC-0000-Red": "Make column holds a part number, not a manufacturer — assign the real make.",
    'Single Swivel Socket - 2"': "Make column holds a description, not a manufacturer — review.",
    "Structural Pipe": "Make column holds a generic part type, not a manufacturer — review.",
    "Fuse": "Make column holds a generic part type, not a manufacturer — review.",
    "Surge Protector": "Make column holds a generic part type, not a manufacturer — review.",
    "O'Reilly's or equivalent": "Generic placeholder — specify the actual make.",
    "Y/T Branch Connectors": "Make column holds a description, not a manufacturer — review.",
    "Snap It Small EMP Suppressors": "Make column holds a description, not a manufacturer — review.",
    "Vicrton BlueSolar MPPT 150-60--Tr": "Make had model text; set to Victron — move 'BlueSolar MPPT 150/60' to Model.",
}


def standardize_makes(db):
    """Consolidate manufacturer-name spellings and flag rows whose Make column
    actually holds a part type/description. Runs once (or on version bump)."""
    _mv = db.execute("SELECT value FROM meta WHERE key = 'make_std_v'").fetchone()
    if _mv and int(_mv[0] or 0) >= MAKE_STD_VERSION:
        return
    for mk, flag in MAKE_FLAG.items():   # flag by original make, before rename
        db.execute("UPDATE inventory_items SET flags = ?"
                   " WHERE make = ? AND COALESCE(flags, '') = ''", (flag, mk))
    for old, new in MAKE_FIX.items():
        db.execute("UPDATE inventory_items SET make = ? WHERE make = ?", (new, old))
    db.execute("INSERT INTO meta (key, value) VALUES ('make_std_v', ?)"
               " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
               (str(MAKE_STD_VERSION),))
    db.commit()


def standardize_vendors(db):
    """Fold vendor duplicates/typos into a canonical supplier list once (or when
    VENDOR_STD_VERSION bumps). Item vendor_ids on merged vendors are reassigned
    to the survivor before the duplicate is removed."""
    _sv = db.execute("SELECT value FROM meta WHERE key = 'vendor_std_v'").fetchone()
    if _sv and int(_sv[0] or 0) >= VENDOR_STD_VERSION:
        return
    for vid, name in VENDOR_RENAME.items():
        db.execute("UPDATE inventory_vendors SET name = ? WHERE id = ?", (name, vid))
    for old, survivor in VENDOR_MERGE.items():
        for tbl in ("inventory_items", "inventory_tools", "inventory_vehicles"):
            db.execute(f"UPDATE {tbl} SET vendor_id = ? WHERE vendor_id = ?",
                       (survivor, old))
        db.execute("DELETE FROM inventory_vendors WHERE id = ?", (old,))
    for vid in VENDOR_REMOVE:
        used = db.execute(
            "SELECT (SELECT COUNT(*) FROM inventory_items WHERE vendor_id = ?)"
            " + (SELECT COUNT(*) FROM inventory_tools WHERE vendor_id = ?)"
            " + (SELECT COUNT(*) FROM inventory_vehicles WHERE vendor_id = ?)",
            (vid, vid, vid)).fetchone()[0]
        if used == 0:
            db.execute("DELETE FROM inventory_vendors WHERE id = ?", (vid,))
    db.execute("INSERT INTO meta (key, value) VALUES ('vendor_std_v', ?)"
               " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
               (str(VENDOR_STD_VERSION),))
    db.commit()


def apply_inventory_research(db):
    """Piece 23.3: fold web-research overrides (inventory_research.py) into the
    seeded items — corrected/completed specs, datasheet + purchase URLs, web
    price, Active/Discontinued, and flags. Never touches Cost. Re-applies whenever
    RESEARCH_VERSION increases (so each research batch flows into existing DBs),
    matched by category+make+model."""
    _rv = db.execute("SELECT value FROM meta WHERE key = 'inventory_research_v'").fetchone()
    if _rv and int(_rv[0] or 0) >= RESEARCH_VERSION:
        return
    for key, upd in RESEARCH.items():
        cat, make, model = key.split("||")
        for rid, raw_specs in db.execute(
                "SELECT id, specs FROM inventory_items"
                " WHERE category = ? AND make = ? AND model = ?",
                (cat, make, model)).fetchall():
            try:
                specs = json.loads(raw_specs or "{}")
            except (ValueError, TypeError):
                specs = {}
            specs.update(upd.get("specs", {}))
            db.execute(
                "UPDATE inventory_items SET specs = ?,"
                " manual_url = COALESCE(NULLIF(?, ''), manual_url),"
                " purchase_url = COALESCE(NULLIF(?, ''), purchase_url),"
                " web_price = COALESCE(?, web_price),"
                " price_checked_on = COALESCE(NULLIF(?, ''), price_checked_on),"
                " status = COALESCE(NULLIF(?, ''), status),"
                " flags = ? WHERE id = ?",
                (json.dumps(specs, default=str), upd.get("manual_url", ""),
                 upd.get("purchase_url", ""), upd.get("web_price"),
                 upd.get("price_checked_on", ""), upd.get("status", ""),
                 upd.get("flags", ""), rid))
    db.execute("INSERT INTO meta (key, value) VALUES ('inventory_research_v', ?)"
               " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
               (str(RESEARCH_VERSION),))
    db.commit()


def apply_tools_research(db):
    """Piece 24.2: enrich the seeded tool kit (INVENTORY_TOOLS was seeded with
    only name + category) with a standard make/model, a store listing URL, and
    an approx price flagged for verification. Matched by tool name. Re-applies
    whenever TOOLS_RESEARCH_VERSION increases. Only fills rows still blank
    (make = '') so any later in-app edits are preserved."""
    _tv = db.execute("SELECT value FROM meta WHERE key = 'tools_research_v'").fetchone()
    if _tv and int(_tv[0] or 0) >= TOOLS_RESEARCH_VERSION:
        return
    for name, upd in TOOLS_RESEARCH.items():
        db.execute(
            "UPDATE inventory_tools SET"
            " make = ?, model = ?, purchase_url = ?, notes = ?,"
            " cost = COALESCE(cost, ?)"
            " WHERE name = ? AND COALESCE(make, '') = ''",
            (upd.get("make", ""), upd.get("model", ""), upd.get("purchase_url", ""),
             upd.get("notes", ""), upd.get("cost"), name))
    db.execute("INSERT INTO meta (key, value) VALUES ('tools_research_v', ?)"
               " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
               (str(TOOLS_RESEARCH_VERSION),))
    db.commit()


INV_CLEANUP_VERSION = 1


def cleanup_inventory(db):
    """Piece 24.3: catalog cleanup that changes category/model (so it can't live
    in apply_inventory_research, which matches on those). Runs once per version:
    (1) recategorize the Schneider PDP / connection / breaker-kit accessories out
    of Inverter into Electrical; (2) disambiguate the two AP Smart rows that were
    mislabeled with an identical model — one is the RSD transmitter, the other a
    RSD push-button; (3) flag the genuine duplicate line-pairs (same model, two
    entries at different recorded costs) for reconciliation rather than deleting
    real purchase history. Plain sqlite3 connection here — no row factory."""
    _cv = db.execute("SELECT value FROM meta WHERE key = 'inv_cleanup_v'").fetchone()
    if _cv and int(_cv[0] or 0) >= INV_CLEANUP_VERSION:
        return
    # (1) Schneider accessories: Inverter -> Electrical.
    schneider_models = (
        "Breaker Kit for Conext XW+PDP #RNW865121501",
        "XW Connection kit for Inverter 2 (RNW865102002",
        "XW+ mini Power Distribution Panel RNW865101301",
        "XW+ POWER DISTIBUTION PANEL (RNW865101501)",
    )
    for model in schneider_models:
        db.execute(
            "UPDATE inventory_items SET category = 'Electrical',"
            " flags = 'Recategorized from Inverter to Electrical — accessory (PDP /"
            " connection kit / breaker kit), not an inverter.'"
            " WHERE category = 'Inverter' AND make = 'Schneider Electric'"
            " AND model = ?", (model,))
    # (2) AP Smart: the two rows share model 'APsmart transmitter APS 406001 Single
    #     Core' but are different devices; split them by vendor part number.
    db.execute(
        "UPDATE inventory_items SET model = 'APsmart RSD Transmitter (APS 406001)',"
        " flags = 'PLC rapid-shutdown transmitter — one per array; not a per-module"
        " optimizer.' WHERE make = 'AP Smart' AND vendor_number = '300-00252'")
    db.execute(
        "UPDATE inventory_items SET model = 'APsmart RSD Push Button (APS 406001)',"
        " flags = 'Rapid-shutdown initiation push-button (NO/NC contacts) — not a"
        " transmitter or optimizer; model corrected (was mislabeled as the"
        " transmitter).' WHERE make = 'AP Smart' AND vendor_number = '300-00253'")
    # (3) Genuine duplicate line-pairs: flag, don't delete (they carry different
    #     recorded costs = real purchase history to reconcile by hand).
    db.execute(
        "UPDATE inventory_items SET flags = 'Possible duplicate line — two"
        " XR-1000-210M rail entries at different recorded costs; reconcile qty &"
        " price, then trash one.' WHERE make = 'IronRidge' AND model = 'XR-1000-210M'")
    db.execute(
        "UPDATE inventory_items SET flags = 'Possible duplicate line — two"
        " MNTRANSFER-60A entries at different recorded costs; reconcile, then trash"
        " one.' WHERE make = 'MidNite Solar' AND model = 'MNTRANSFER-60A'")
    db.execute("INSERT INTO meta (key, value) VALUES ('inv_cleanup_v', ?)"
               " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
               (str(INV_CLEANUP_VERSION),))
    db.commit()


def init_db():
    """Create tables if missing and upgrade older databases."""
    db = sqlite3.connect(DATABASE)
    # Piece 34: if this is a pre-rename database (still has a "jobs" table),
    # rename it and its child tables/columns to the new project_* names
    # *before* running schema.sql below — schema.sql's CREATE TABLE IF NOT
    # EXISTS would otherwise create a fresh empty "projects" table first and
    # block this rename with a "table already exists" conflict. The literal
    # old-name strings below are intentional and must stay exactly as
    # written — they're what makes this block able to find a database from
    # before this piece.
    legacy_tables = {row[0] for row in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    if "jobs" in legacy_tables:
        db.execute("ALTER TABLE jobs RENAME TO projects")
        for old, new in (
            ("job_versions", "project_versions"), ("job_materials", "project_materials"),
            ("job_files", "project_files"), ("job_notes", "project_notes"),
            ("job_load_rooms", "project_load_rooms"), ("job_load_items", "project_load_items"),
            ("job_bom", "project_bom"), ("job_sizing", "project_sizing"),
            ("job_tasks", "project_tasks"), ("job_estimate_lines", "project_estimate_lines"),
            ("job_transactions", "project_transactions"),
        ):
            db.execute(f"ALTER TABLE {old} RENAME TO {new}")
        for t in ("project_versions", "project_materials", "project_files",
                  "project_notes", "project_load_rooms", "project_load_items",
                  "project_bom", "project_sizing", "project_tasks",
                  "project_estimate_lines", "project_transactions",
                  "time_entries", "inventory_txns", "inventory_assets"):
            cols = {r[1] for r in db.execute(f"PRAGMA table_info({t})")}
            if "job_id" in cols:
                db.execute(f"ALTER TABLE {t} RENAME COLUMN job_id TO project_id")
        hi_cols = {r[1] for r in db.execute("PRAGMA table_info(household_ideas)")}
        if "started_job_id" in hi_cols:
            db.execute("ALTER TABLE household_ideas"
                       " RENAME COLUMN started_job_id TO started_project_id")
        db.commit()
    # Piece 35: same reasoning, for a pre-reorg database that still has an
    # "employees" table — rename it and its child tables/columns to the new
    # household_members-based names before schema.sql runs.
    if "employees" in legacy_tables:
        db.execute("ALTER TABLE employees RENAME TO household_members")
        db.execute("ALTER TABLE household_members RENAME COLUMN roles TO role")
        for old, new in (
            ("employee_credentials", "household_member_credentials"),
            ("employee_files", "household_member_files"),
        ):
            db.execute(f"ALTER TABLE {old} RENAME TO {new}")
        for t in ("household_member_credentials", "household_member_files",
                  "permission_grants", "password_requests", "security_answers",
                  "project_tasks", "board_time", "field_submissions"):
            cols = {r[1] for r in db.execute(f"PRAGMA table_info({t})")}
            if "employee_id" in cols:
                db.execute(f"ALTER TABLE {t} RENAME COLUMN employee_id TO household_member_id")
        db.commit()
    db.executescript((BASE_DIR / "schema.sql").read_text())
    # Piece 33: the multi-client model is gone (household_ideas/household_files
    # replace clients/cold_leads/lead_followups/client_versions/client_files).
    # One-time cleanup for any local DB from before this piece; a no-op on a
    # genuinely fresh database.
    if not db.execute("SELECT 1 FROM meta WHERE key = 'clients_removed_v1'").fetchone():
        for legacy_table in ("clients", "cold_leads", "lead_followups",
                              "client_versions", "client_files"):
            db.execute(f"DROP TABLE IF EXISTS {legacy_table}")
        job_cols = {row[1] for row in db.execute("PRAGMA table_info(projects)")}
        if "client_id" in job_cols:
            db.execute("ALTER TABLE projects DROP COLUMN client_id")
        db.execute("INSERT INTO meta (key, value) VALUES ('clients_removed_v1', '1')"
                   " ON CONFLICT(key) DO UPDATE SET value = excluded.value")
    ensure_columns(db, "projects", PROJECT_FIELDS + ["status", "install_date"])
    # Piece 21: contract total for the Finance viewport (dollar amounts).
    ensure_columns(db, "projects", ["contract_amount"])
    # Piece 21.5: source-document type (Receipt / Invoice / Bill) on ledger rows.
    ensure_columns(db, "project_transactions", ["doc_type"])
    # Piece 27.3: generated-invoice fields on the ledger row + the BOM cutoff the
    # deposit invoice captures (BOM added after it counts as billable extras).
    ensure_columns(db, "project_transactions",
                   ["invoice_number", "milestone", "due_date", "contract_snapshot",
                    "base_amount", "extras_amount", "bom_snapshot",
                    "grt_rate", "grt_amount"])   # Piece 27.4: GRT snapshot per invoice
    ensure_columns(db, "projects", ["deposit_bom_cutoff_id", "grt_rate"])
    # Piece 27.9: per-task time split by pay type (+ its work date) carried on a
    # field-submission item, so approving a completed task posts Pending payroll
    # entries (one per pay-type segment) for Finance to approve.
    ensure_columns(db, "field_submission_items", ["hours_json", "work_date"])
    # Piece 21.7: tie crew-captured field photos back to the task they document.
    ensure_columns(db, "project_files", ["task_id"])
    # Piece 26.2: link a receipt photo to its ledger transaction (bookkeeping).
    ensure_columns(db, "project_files", ["txn_id"])
    # Piece 26.4: a room's appliance-catalog "type" (Kitchen, Garage, …) so the
    # load-survey picker can default to that room's appliances.
    ensure_columns(db, "project_load_rooms", ["category"])
    # Piece 25.2: per-slot accepted file formats (comma-separated extensions) on
    # a rule, so a document slot can require e.g. PDF only.
    ensure_columns(db, "resource_rules", ["allowed_formats"])
    # Piece 16: migrate Piece 12.1 statuses to the new phases, and default blanks.
    for old, new in OLD_TO_NEW_STATUS.items():
        db.execute("UPDATE projects SET status = ? WHERE status = ?", (new, old))
    db.execute(f"UPDATE projects SET status = '{DEFAULT_PROJECT_STATUS}'"
               f" WHERE COALESCE(status, '') = ''")
    # Piece 14: change-tracking for task sync; seed blanks from created_at.
    ensure_columns(db, "project_tasks", ["updated_at", "pipeline_status"])
    db.execute("UPDATE project_tasks SET updated_at = COALESCE(NULLIF(created_at,''),"
               " datetime('now')) WHERE COALESCE(updated_at,'') = ''")
    # Piece 35: a table renamed from "employees" (not freshly created) skips
    # schema.sql's CREATE TABLE, so columns baked into the new household_members
    # shape that the old employees table never had must be added explicitly —
    # plus the transitional "access_level" column, kept just long enough for
    # the is_admin backfill below, then dropped.
    ensure_columns(db, "household_members",
                   ["is_admin", "licenses_certifications", "access_level"])
    if not db.execute("SELECT 1 FROM meta WHERE key = 'household_reorg_v1'").fetchone():
        # Backfill is_admin from the old access_level/GM-role signal *before*
        # the role remap below overwrites the role text it reads here.
        db.execute("UPDATE household_members SET is_admin = '1'"
                   " WHERE access_level = 'Admin' OR role LIKE '%General Manager%'")
        # No signal in old data tells an adult from a kid — any pre-existing
        # role text implied a job-title-holding adult, so default to Parent.
        db.execute("UPDATE household_members SET role = 'Parent'"
                   " WHERE role NOT IN ('Parent', 'Child', 'Assistant')")
        db.execute("UPDATE permission_grants SET permission = 'household.manage'"
                   " WHERE permission = 'employees.manage'")
        for legacy_table in ("onboarding_steps", "employee_onboarding",
                              "pay_types", "pay_rates", "time_entries"):
            db.execute(f"DROP TABLE IF EXISTS {legacy_table}")
        for col in ("access_level", "is_supervisor", "access_revoked",
                    "access_revoked_at", "access_revoked_by",
                    "access_revoked_reason", "onboarding_owner_id", "base_wage"):
            try:
                db.execute(f"ALTER TABLE household_members DROP COLUMN {col}")
            except sqlite3.OperationalError:
                pass
        db.execute("INSERT INTO meta (key, value) VALUES ('household_reorg_v1', '1')"
                   " ON CONFLICT(key) DO UPDATE SET value = excluded.value")
    db.commit()
    ensure_columns(db, "resource_rules",
                   ["field_name2", "field_value2", "match_type2", "link_text"])
    # Piece 26.9: verbatim source text for a rule (esp. compliance) — the exact
    # wording from the code/source, shown above the shorthand in the L/P/C Directory.
    ensure_columns(db, "resource_rules", ["source_text"])
    # Piece 30.1: the ⚠ Verify / ⚠ Unverified callout is an explicit editable
    # field now (was inferred from caution words in the notes).
    ensure_columns(db, "resource_rules", ["verify_status"])
    # Piece 27.1: sample client/project seed removed for production. A fresh
    # database now starts with NO clients, projects, tasks, or sample employees
    # — only the reference databases (staff roster, inventory, calculator
    # catalog, rules, pay types) seed. (History has the old demo data.)
    if db.execute("SELECT COUNT(*) FROM resource_rules").fetchone()[0] == 0:
        insert_seed_rules(db, SEED_RULES)
        db.commit()
    # Later rule batches apply exactly once per database, so existing
    # installs receive new rules without duplicates — and rules someone
    # deleted on purpose don't come back on restart.
    row = db.execute("SELECT value FROM meta WHERE key = 'seed_version'").fetchone()
    seed_version = int(row[0]) if row else 1
    for batch_number in sorted(SEED_BATCHES):
        if batch_number > seed_version:
            insert_seed_rules(db, SEED_BATCHES[batch_number])
            for statement in SEED_BATCH_SQL.get(batch_number, []):
                db.execute(statement)
            seed_version = batch_number
    db.execute(
        "INSERT INTO meta (key, value) VALUES ('seed_version', ?)"
        " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(seed_version),),
    )
    # Piece 30.1: one-time backfill of verify_status from the old text convention,
    # so existing callouts persist as explicit values that a human can now edit.
    if not db.execute("SELECT 1 FROM meta WHERE key = 'rule_verify_backfilled'").fetchone():
        for rid, notes, label in db.execute(
                "SELECT id, notes, label FROM resource_rules").fetchall():
            db.execute("UPDATE resource_rules SET verify_status = ? WHERE id = ?",
                       (_infer_verify_from_text(notes, label), rid))
        db.execute("INSERT INTO meta (key, value) VALUES"
                   " ('rule_verify_backfilled', '1')"
                   " ON CONFLICT(key) DO UPDATE SET value = excluded.value")
    db.commit()
    # Piece 9: appliance + component catalogs seed once, the same way the
    # sample clients above do — not via the rule-style batch system, since
    # they're reference tables of their own rather than resource_rules rows.
    if db.execute("SELECT COUNT(*) FROM appliance_catalog").fetchone()[0] == 0:
        db.executemany(
            "INSERT INTO appliance_catalog"
            " (name, category, era, low_w, high_w, avg_w, hrs_per_day,"
            "  usage_type, notes)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            APPLIANCE_SEED,
        )
        db.commit()
    if db.execute("SELECT COUNT(*) FROM component_catalog").fetchone()[0] == 0:
        db.executemany(
            "INSERT INTO component_catalog"
            " (name, category, manufacturer, model, specs, watts, voc, vmp,"
            "  temp_coef_voc, capacity_kwh_nameplate, dod, max_input_v,"
            "  continuous_w, inverter_eff, cost, notes)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            COMPONENT_SEED,
        )
        db.commit()
    seed_org_team(db)
    seed_finance_reference(db)  # Piece 29.6: county GRT + markup categories
    ensure_columns(db, "projects", ["travel_miles"])       # Piece 29.6
    # Piece 30.2: cancellation (Abandoned) metadata — reason, who/when, and the
    # stage to restore on reopen.
    ensure_columns(db, "projects", ["cancel_reason", "cancelled_at", "cancelled_by",
                                    "pre_lost_status"])
    ensure_columns(db, "project_bom", ["markup_pct"])      # per-line markup override
    # Piece 34: remap old pipeline-stage values (Proposal/Job Prep/Installation/
    # Inspections/Closing/Complete/Lost) to the new household vocabulary on any
    # rows still carrying them — a no-op on a genuinely fresh database. Runs
    # once; guarded by the same meta key as the table rename above.
    if not db.execute("SELECT 1 FROM meta WHERE key = 'projects_rename_v1'").fetchone():
        proj_cols = {r[1] for r in db.execute("PRAGMA table_info(projects)")}
        for old, new in OLD_TO_NEW_STAGE.items():
            db.execute("UPDATE projects SET status = ? WHERE status = ?", (new, old))
            if "pre_lost_status" in proj_cols:
                db.execute("UPDATE projects SET pre_lost_status = ?"
                           " WHERE pre_lost_status = ?", (new, old))
        db.execute("INSERT INTO meta (key, value) VALUES ('projects_rename_v1', '1')"
                   " ON CONFLICT(key) DO UPDATE SET value = excluded.value")
    db.commit()
    ensure_columns(db, "inventory_items", ["status", "last_used", "stock_reviewed_on"])
    ensure_columns(db, "inventory_items", ["stale_flag"])   # Piece 30.4: manual "stale" mark
    db.execute("UPDATE inventory_items SET status = 'Active'"
               " WHERE COALESCE(status, '') = ''")
    seed_inventory(db)
    standardize_vendors(db)
    standardize_makes(db)
    apply_inventory_research(db)
    apply_tools_research(db)
    cleanup_inventory(db)
    # Piece 23.4: inverters get an (empty) FCC ID# spec + a flag, once. Values
    # are researched in a later phase; blank ones stay flagged.
    if not db.execute("SELECT 1 FROM meta WHERE key = 'inv_fcc_flagged'").fetchone():
        for rid, raw in db.execute(
                "SELECT id, specs FROM inventory_items"
                " WHERE category = 'Inverter'").fetchall():
            try:
                sp = json.loads(raw or "{}")
            except (ValueError, TypeError):
                sp = {}
            if not sp.get("FCC ID#"):
                sp["FCC ID#"] = ""
                db.execute(
                    "UPDATE inventory_items SET specs = ?,"
                    " flags = CASE WHEN COALESCE(flags,'') = '' THEN"
                    " 'FCC ID# pending (later phase)' ELSE flags END WHERE id = ?",
                    (json.dumps(sp, default=str), rid))
        db.execute("INSERT INTO meta (key, value) VALUES ('inv_fcc_flagged', '1')"
                   " ON CONFLICT(key) DO UPDATE SET value = excluded.value")
        db.commit()
    tag_tasks_by_stage(db)
    db.close()


RULE_COLUMNS = ["field_name", "field_value", "match_type", "category", "label",
                "notes", "url", "phone", "field_name2", "field_value2",
                "match_type2", "link_text"]


def insert_seed_rules(db, rows):
    """Insert seed rows. Tuples: 6 items = single condition, 9 items =
    compound. Dicts may set any rule column (url, phone, ...)."""
    normalized = []
    for row in rows:
        if isinstance(row, dict):
            r = [row.get(c, "") for c in RULE_COLUMNS]
        else:
            row = list(row)
            if len(row) == 6:
                row += ["", "", "equals"]
            r = row[:6] + ["", ""] + row[6:]
        while len(r) < len(RULE_COLUMNS):
            r.append("")
        if not r[2]:
            r[2] = "equals"
        if not r[10]:
            r[10] = "equals"
        normalized.append(r)
    db.executemany(
        f"INSERT INTO resource_rules ({', '.join(RULE_COLUMNS)})"
        f" VALUES ({', '.join('?' * len(RULE_COLUMNS))})",
        normalized,
    )


def condition_met(project, field, value, match_type):
    """One rule condition: the project's field equals the value
    (case-insensitive), or — for 'contains' — the value appears in the
    field's comma-separated list (used for products)."""
    if field not in project.keys():
        return False
    actual = str(project[field] or "").strip()
    if not actual:
        return False
    target = value.strip().lower()
    if match_type == "contains":
        return target in [p.strip().lower() for p in actual.split(",")]
    return actual.lower() == target


def match_rules(project, rules):
    """A rule matches when its condition holds — and, for compound rules,
    when the second condition holds too."""
    hits = []
    for rule in rules:
        if not condition_met(project, rule["field_name"], rule["field_value"],
                             rule["match_type"]):
            continue
        if rule["field_name2"] and not condition_met(
                project, rule["field_name2"], rule["field_value2"],
                rule["match_type2"] or "equals"):
            continue
        hits.append(rule)
    return hits


def _instance_label(rule):
    """Human-readable "what triggered this" for the compact instance bullets:
    the project selection(s) behind a requirement (e.g. "PV Systems")."""
    fv = (rule["field_value"] or "").strip()
    fv2 = (rule["field_value2"] or "").strip() if rule["field_name2"] else ""
    return f"{fv} + {fv2}" if fv2 else fv


# Piece 30.1: the verification callout is an explicit, human-editable field on
# each rule (verify_status) rather than magic words in the notes. Labels:
VERIFY_LABELS = {"verify": "⚠ Verify", "unverified": "⚠ Unverified"}


def _infer_verify_from_text(notes, label):
    """One-time backfill helper: read the old convention (caution words in the
    notes/label) into the new explicit verify_status field."""
    text = ((notes or "") + " " + (label or "")).lower()
    if "unverified" in text:
        return "unverified"
    if "verify" in text or "confirm" in text:
        return "verify"
    return ""


def _clean_verify_status(raw):
    """Validate a submitted verify_status to '', 'verify', or 'unverified'."""
    v = (raw or "").strip().lower()
    return v if v in VERIFY_LABELS else ""


def _rule_alert(rule):
    """The rule's verification callout, from its explicit verify_status field.
    Returns (kind, short_label) or (None, None)."""
    vs = (rule["verify_status"] if "verify_status" in rule.keys() else "") or ""
    vs = vs.strip().lower()
    if vs in VERIFY_LABELS:
        return (vs, VERIFY_LABELS[vs])
    return (None, None)


def group_rules(matched, dedupe=True):
    """Group matched rules by category in a fixed order. On project pages,
    de-duplicate shared requirements (e.g. PV and Battery both need EE-98) and
    collapse them into one entry that carries the list of triggering selections
    (`instances`), so a requirement shows once with its instances beneath it
    instead of repeating. The directory (dedupe=False) keeps every rule so each
    trigger is editable on its own row. Every entry also carries `alert_kind`/
    `alert_text` for the verification callout chip."""
    groups = {}          # category -> list of dict entries (dedupe order)
    index = {}           # (category, label_lc) -> entry, for merging instances
    for rule in matched:
        cat = rule["category"]
        label_lc = rule["label"].strip().lower()
        inst = _instance_label(rule)
        existing = index.get((cat, label_lc)) if dedupe else None
        if existing is not None:
            if inst and inst not in existing["instances"]:
                existing["instances"].append(inst)
            continue
        entry = {k: rule[k] for k in rule.keys()}
        entry["instances"] = [inst] if inst else []
        entry["alert_kind"], entry["alert_text"] = _rule_alert(rule)
        groups.setdefault(cat, []).append(entry)
        index[(cat, label_lc)] = entry
    ordered = []
    for category in RULE_CATEGORIES:
        if category in groups:
            ordered.append((CATEGORY_HEADINGS.get(category, category),
                            groups.pop(category)))
    for category in sorted(groups):
        ordered.append((CATEGORY_HEADINGS.get(category, category),
                        groups[category]))
    return ordered


def consolidate_rules(rules):
    """Piece 26.9: the L/P/C Directory view. Collapse every rule that shares a
    (category, label) into ONE entry, listing each triggering scenario as a
    bullet beneath it — so a requirement like "EE-98 Contractor License" shows
    once with all its scenarios, instead of a fresh listing per scenario. The
    entry carries a representative source (link/phone) and, for compliance, the
    verbatim source text; verification flags escalate (unverified > verify)."""
    order = []
    index = {}
    for r in rules:
        cat = r["category"]
        key = (cat, (r["label"] or "").strip().lower())
        entry = index.get(key)
        if entry is None:
            entry = {"category": cat, "label": r["label"], "url": "",
                     "link_text": "", "phone": "", "source_text": "",
                     "alert_kind": None, "alert_text": None, "scenarios": []}
            index[key] = entry
            order.append(entry)
        # Representative source fields: first non-empty across the merged rules.
        if not entry["url"] and r["url"]:
            entry["url"] = r["url"]
        if not entry["link_text"] and r["link_text"]:
            entry["link_text"] = r["link_text"]
        if not entry["phone"] and r["phone"]:
            entry["phone"] = r["phone"]
        st = r["source_text"] if "source_text" in r.keys() else ""
        if not entry["source_text"] and st:
            entry["source_text"] = st
        kind, text = _rule_alert(r)
        if kind == "unverified" or (kind == "verify" and entry["alert_kind"] is None):
            entry["alert_kind"], entry["alert_text"] = kind, text
        entry["scenarios"].append({
            "field_name": r["field_name"], "field_value": r["field_value"],
            "match_type": r["match_type"], "field_name2": r["field_name2"],
            "field_value2": r["field_value2"], "match_type2": r["match_type2"],
            "notes": r["notes"]})
    by_cat = {}
    for e in order:
        by_cat.setdefault(e["category"], []).append(e)
    ordered = []
    for c in RULE_CATEGORIES:
        if c in by_cat:
            ordered.append((CATEGORY_HEADINGS.get(c, c), by_cat.pop(c)))
    for c in sorted(by_cat):
        ordered.append((CATEGORY_HEADINGS.get(c, c), by_cat[c]))
    return ordered


def credential_status(expires):
    """Classify a credential by its expiry date: returns (state, text)
    where state is expired / soon / ok / none, and text is a short label
    for display."""
    expires = (expires or "").strip()
    if not expires:
        return ("none", "no expiry")
    try:
        exp = datetime.strptime(expires, "%Y-%m-%d").date()
    except ValueError:
        return ("none", expires)
    days = (exp - datetime.now().date()).days
    if days < 0:
        return ("expired", f"expired {expires}")
    if days <= EXPIRY_SOON_DAYS:
        return ("soon", f"expires {expires} ({days} d)")
    return ("ok", f"expires {expires}")


def license_staffing():
    """For each License requirement label, the employees who hold a
    matching credential (tied via rule_label), each with its expiry state.
    Drives the 'who on staff is licensed' badges on project pages."""
    rows = get_db().execute(
        "SELECT c.rule_label, c.expires, e.name AS emp_name"
        " FROM household_member_credentials c"
        " JOIN household_members e ON e.id = c.household_member_id"
        " WHERE c.rule_label != ''"
        " ORDER BY e.name"
    ).fetchall()
    staffing = {}
    for r in rows:
        state, _ = credential_status(r["expires"])
        staffing.setdefault(r["rule_label"], []).append(
            {"name": r["emp_name"], "state": state})
    return staffing


# ------------------------------------------------------- Piece 9: loads/sizing
def fetch_job_sizing(db, project_id):
    """One project_sizing row always exists once a project's Loads tab is opened;
    create it lazily with defaults from the schema."""
    row = db.execute("SELECT * FROM project_sizing WHERE project_id = ?", (project_id,)).fetchone()
    if row is None:
        db.execute("INSERT INTO project_sizing (project_id) VALUES (?)", (project_id,))
        db.commit()
        row = db.execute("SELECT * FROM project_sizing WHERE project_id = ?", (project_id,)).fetchone()
    return row


def compute_load_totals(rooms, items):
    """Daily kWh and peak watts across every ENABLED room only — a
    disabled scenario room's items are excluded without being deleted."""
    enabled = {r["id"] for r in rooms if r["enabled"]}
    daily_kwh = 0.0
    peak_w = 0.0
    for it in items:
        if it["room_id"] not in enabled:
            continue
        w = (it["watts"] or 0) * (it["qty"] or 0)
        peak_w += w
        daily_kwh += w * (it["hrs"] or 0) / 1000.0
    return daily_kwh, peak_w


def compute_array(daily_kwh, sun_hours, derate_pct, solar_fraction_pct, panel_watts):
    """Array sizing: daily kWh (scaled by the solar fraction) divided by
    peak sun hours and the derate factor gives array kW; panel count is
    that array size divided by a single panel's wattage, rounded up."""
    derate = (derate_pct or 0) / 100.0
    frac = (solar_fraction_pct or 100) / 100.0
    if not sun_hours or sun_hours <= 0 or derate <= 0:
        return 0.0, 0
    array_kw = (daily_kwh * frac) / (sun_hours * derate)
    panel_count = math.ceil((array_kw * 1000) / panel_watts) if panel_watts else 0
    return array_kw, panel_count


def compute_battery_kwh(backup_daily_kwh, autonomy_days, dod_pct,
                         round_trip_eff_pct, inverter_eff_pct):
    """Usable backup load over the autonomy window, grossed up for
    depth-of-discharge and round-trip/inverter losses, gives the
    nameplate battery kWh needed."""
    dod = (dod_pct or 0) / 100.0
    rte = (round_trip_eff_pct or 100) / 100.0
    inv = (inverter_eff_pct or 100) / 100.0
    if dod <= 0 or rte <= 0 or inv <= 0:
        return 0.0
    return (backup_daily_kwh or 0) * (autonomy_days or 0) / dod / (rte * inv)


def compute_voc(voc_rated, temp_coef_pct, record_low_temp_f, max_input_v):
    """NEC 690.7 Method 1 cold-temperature Voc correction: correct the
    module's rated Voc to the site's record low, then divide the inverter/
    charge controller's max input voltage by that to get the longest
    allowed string length."""
    if not voc_rated or temp_coef_pct is None:
        return None, None
    tmin_c = ((record_low_temp_f or 32) - 32) * 5.0 / 9.0
    voc_corrected = voc_rated * (1 + (temp_coef_pct / 100.0) * (tmin_c - 25))
    max_modules = math.floor(max_input_v / voc_corrected) if voc_corrected > 0 and max_input_v else 0
    return voc_corrected, max_modules


# --- Piece 26.5: component auto-suggest from live inventory specs ------------
def _spec_num(specs, *keys):
    """First numeric value among the given spec keys, or None. Specs are the
    per-item JSON blobs (e.g. {'Rating': 630.0, 'Voc': 48.8})."""
    for k in keys:
        v = specs.get(k)
        if v not in (None, ""):
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    return None


def _rank_role(label, unit, cands):
    """Take the fitting candidates for one role (already carrying a private
    `_sort` key), order them best-first, and label the top three: the first is
    the "Recommended" pick, the next two are "Alternate" 2nd/3rd choices."""
    cands.sort(key=lambda c: c.pop("_sort"))
    top = cands[:3]
    tags = ["Recommended", "Alternate", "Alternate"]
    for i, c in enumerate(top):
        c["rank"] = i + 1
        c["tag"] = tags[i]
    return {"label": label, "unit": unit, "suggestions": top}


def suggest_components(db, array_kw, peak_w, battery_kwh_needed):
    """Read the specs on ACTIVE inventory items and propose the components that
    fit the sized project — PV modules, batteries, and the inverter. For each role
    the fitting items are ranked (in-stock first, then the tidiest fit and the
    lower cost) and the top three are returned: a primary "Recommended" pick
    plus up to two "Alternate" 2nd/3rd choices, each with the quantity needed
    and a short "why", so the Designer can accept one with a single click."""
    rows = db.execute(
        "SELECT id, category, make, model, cost, available, specs"
        " FROM inventory_items WHERE active = 1 AND status = 'Active'"
        "   AND category IN ('PV Module', 'Battery', 'Inverter')"
    ).fetchall()
    parsed = []
    for it in rows:
        try:
            sp = json.loads(it["specs"] or "{}")
        except (ValueError, TypeError):
            sp = {}
        parsed.append((it, sp))

    def _name(it):
        return " ".join(p for p in (it["make"], it["model"]) if p) or it["model"] or "—"

    def _cost_key(it):
        return it["cost"] if it["cost"] not in (None, "") else float("inf")

    roles = []

    # PV modules — fit by nameplate wattage ("Rating") to reach the array size.
    if array_kw and array_kw > 0:
        cands = []
        for it, sp in parsed:
            if it["category"] != "PV Module":
                continue
            watts = _spec_num(sp, "Rating")
            if not watts or watts <= 0:
                continue
            qty = math.ceil((array_kw * 1000) / watts)
            in_stock = (it["available"] or 0) > 0
            cands.append({
                "item_id": it["id"], "name": _name(it), "category": "PV Module",
                "qty": qty, "unit_cost": it["cost"], "in_stock": in_stock,
                "why": f"{watts:g} W module — {qty} panels reach the {array_kw:.2f} kW array",
                "_sort": (qty, 0 if in_stock else 1, _cost_key(it)),
            })
        roles.append(_rank_role("PV modules", "panels", cands))

    # Batteries — fit by usable capacity ("Capacity", kWh) for the backup bank.
    if battery_kwh_needed and battery_kwh_needed > 0:
        cands = []
        for it, sp in parsed:
            if it["category"] != "Battery":
                continue
            cap = _spec_num(sp, "Capacity")
            if not cap or cap <= 0:
                continue
            qty = math.ceil(battery_kwh_needed / cap)
            in_stock = (it["available"] or 0) > 0
            cands.append({
                "item_id": it["id"], "name": _name(it), "category": "Battery",
                "qty": qty, "unit_cost": it["cost"], "in_stock": in_stock,
                "why": f"{cap:g} kWh each — {qty} for the {battery_kwh_needed:.1f} kWh bank",
                "_sort": (qty, 0 if in_stock else 1, _cost_key(it)),
            })
        roles.append(_rank_role("Batteries", "units", cands))

    # Inverter — the smallest unit whose rated power ("Pout Rated (kW)") still
    # carries the peak load; oversizing is the tie-breaker, then cost.
    if peak_w and peak_w > 0:
        peak_kw = peak_w / 1000.0
        cands = []
        for it, sp in parsed:
            if it["category"] != "Inverter":
                continue
            pout = _spec_num(sp, "Pout Rated (kW)")
            if not pout or pout <= 0 or pout + 1e-9 < peak_kw:
                continue
            in_stock = (it["available"] or 0) > 0
            cands.append({
                "item_id": it["id"], "name": _name(it), "category": "Inverter",
                "qty": 1, "unit_cost": it["cost"], "in_stock": in_stock,
                "why": f"{pout:g} kW rated — covers the {peak_kw:.1f} kW peak",
                "_sort": (round(pout, 3), 0 if in_stock else 1, _cost_key(it)),
            })
        roles.append(_rank_role("Inverter", "unit", cands))

    return [r for r in roles if r["suggestions"]]


@app.route("/help")
def help_page():
    """Piece 30.7: in-app tutorials / FAQ covering every feature."""
    return render_template("help.html")


# ---------------------------------------------------------- Boards (Piece 30.8)
BOARD_PRIORITIES = ["", "Low", "Normal", "High"]


def _notify_board_assignee(db, board_id, title, assignee_id, actor):
    """Tell a teammate a to-do was sent to them (skip self / login-less)."""
    if not assignee_id or (actor and actor["id"] == assignee_id):
        return
    row = db.execute("SELECT COALESCE(username,'') AS u FROM household_members WHERE id = ?",
                     (assignee_id,)).fetchone()
    if not row or not row["u"]:
        return
    notify_employees(
        db, [assignee_id],
        f"📋 To-do sent to you: “{title}”"
        + (f" — from {actor['name']}" if actor else "") + ".",
        link=url_for("board_detail", board_id=board_id), kind="board")


@app.route("/boards")
def boards_page():
    """The Boards list — standalone to-dos not tied to a project.
    Filter by assignee (mine / unassigned / a person / all) and open vs. all."""
    db = get_db()
    me = current_user()
    who = request.args.get("who", "mine" if me else "all")
    show = request.args.get("show", "open")
    sql = ("SELECT b.*, e.name AS assignee_name FROM boards b"
           " LEFT JOIN household_members e ON e.id = b.assigned_to WHERE 1 = 1")
    params = []
    if who == "mine" and me:
        sql += " AND b.assigned_to = ?"
        params.append(me["id"])
    elif who == "unassigned":
        sql += " AND b.assigned_to IS NULL"
    elif who.isdigit():
        sql += " AND b.assigned_to = ?"
        params.append(int(who))
    if show == "open":
        sql += " AND b.status != 'Done'"
    sql += (" ORDER BY (b.status = 'Done'), (b.due_date = ''), b.due_date,"
            " b.id DESC")
    boards = db.execute(sql, params).fetchall()
    employees = db.execute(
        "SELECT id, name FROM household_members ORDER BY name").fetchall()
    open_count = db.execute(
        "SELECT COUNT(*) FROM boards WHERE status != 'Done'").fetchone()[0]
    return render_template("boards.html", boards=boards, employees=employees,
                           who=who, show=show, task_statuses=TASK_STATUSES,
                           priorities=BOARD_PRIORITIES, open_count=open_count,
                           today=datetime.now().strftime("%Y-%m-%d"))


@app.route("/boards/new", methods=["POST"])
def board_new():
    title = request.form.get("title", "").strip()
    if not title:
        flash("A board needs a title.", "error")
        return redirect(url_for("boards_page"))
    db = get_db()
    me = current_user()
    assignee = request.form.get("assigned_to", "")
    assignee_id = int(assignee) if assignee.isdigit() else None
    priority = request.form.get("priority", "")
    priority = priority if priority in BOARD_PRIORITIES else ""
    cur = db.execute(
        "INSERT INTO boards (title, details, assigned_to, priority, due_date,"
        " created_by) VALUES (?, ?, ?, ?, ?, ?)",
        (title, request.form.get("details", "").strip(), assignee_id, priority,
         request.form.get("due_date", "").strip(), me["name"] if me else ""))
    _notify_board_assignee(db, cur.lastrowid, title, assignee_id, me)
    db.commit()
    flash(f"Board added: {title}"
          + (" — sent to a teammate." if assignee_id and (not me or me["id"] != assignee_id) else ""))
    return redirect(url_for("board_detail", board_id=cur.lastrowid))


@app.route("/boards/<int:board_id>")
def board_detail(board_id):
    db = get_db()
    board = db.execute(
        "SELECT b.*, e.name AS assignee_name FROM boards b"
        " LEFT JOIN household_members e ON e.id = b.assigned_to WHERE b.id = ?",
        (board_id,)).fetchone()
    if board is None:
        abort(404)
    notes = db.execute(
        "SELECT * FROM board_notes WHERE board_id = ? ORDER BY id DESC",
        (board_id,)).fetchall()
    times = db.execute(
        "SELECT * FROM board_time WHERE board_id = ? ORDER BY id DESC",
        (board_id,)).fetchall()
    total_hours = db.execute(
        "SELECT COALESCE(SUM(hours), 0) FROM board_time WHERE board_id = ?",
        (board_id,)).fetchone()[0]
    employees = db.execute(
        "SELECT id, name FROM household_members ORDER BY name").fetchall()
    return render_template("board_detail.html", board=board, notes=notes,
                           times=times, total_hours=total_hours,
                           employees=employees, task_statuses=TASK_STATUSES,
                           priorities=BOARD_PRIORITIES,
                           today=datetime.now().strftime("%Y-%m-%d"))


@app.route("/boards/<int:board_id>/edit", methods=["POST"])
def board_edit(board_id):
    db = get_db()
    if db.execute("SELECT 1 FROM boards WHERE id = ?", (board_id,)).fetchone() is None:
        abort(404)
    title = request.form.get("title", "").strip()
    if not title:
        flash("A board needs a title.", "error")
        return redirect(url_for("board_detail", board_id=board_id))
    priority = request.form.get("priority", "")
    priority = priority if priority in BOARD_PRIORITIES else ""
    db.execute(
        "UPDATE boards SET title = ?, details = ?, priority = ?, due_date = ?"
        " WHERE id = ?",
        (title, request.form.get("details", "").strip(), priority,
         request.form.get("due_date", "").strip(), board_id))
    db.commit()
    flash("Board updated.")
    return redirect(url_for("board_detail", board_id=board_id))


@app.route("/boards/<int:board_id>/status", methods=["POST"])
def board_status(board_id):
    status = request.form.get("status", "")
    if status not in TASK_STATUSES:
        return redirect(url_for("board_detail", board_id=board_id))
    db = get_db()
    who = current_user()
    if status == "Done":
        db.execute("UPDATE boards SET status = ?, completed_at = ?, completed_by = ?"
                   " WHERE id = ?",
                   (status, datetime.now().isoformat(timespec="seconds"),
                    who["name"] if who else "", board_id))
    else:
        db.execute("UPDATE boards SET status = ?, completed_at = '',"
                   " completed_by = '' WHERE id = ?", (status, board_id))
    db.commit()
    nxt = request.form.get("next", "")
    if nxt.startswith("/") and not nxt.startswith("//"):
        return redirect(nxt)
    return redirect(url_for("board_detail", board_id=board_id))


@app.route("/boards/<int:board_id>/assign", methods=["POST"])
def board_assign(board_id):
    """Send a to-do to another team member (or unassign)."""
    db = get_db()
    board = db.execute("SELECT * FROM boards WHERE id = ?", (board_id,)).fetchone()
    if board is None:
        abort(404)
    assignee = request.form.get("assigned_to", "")
    assignee_id = int(assignee) if assignee.isdigit() else None
    db.execute("UPDATE boards SET assigned_to = ? WHERE id = ?",
               (assignee_id, board_id))
    me = current_user()
    if assignee_id and assignee_id != (board["assigned_to"] or None):
        _notify_board_assignee(db, board_id, board["title"], assignee_id, me)
    db.commit()
    flash("To-do sent." if assignee_id else "Board unassigned.")
    return redirect(url_for("board_detail", board_id=board_id))


@app.route("/boards/<int:board_id>/note", methods=["POST"])
def board_note(board_id):
    note = request.form.get("note", "").strip()
    if not note:
        return redirect(url_for("board_detail", board_id=board_id))
    db = get_db()
    if db.execute("SELECT 1 FROM boards WHERE id = ?", (board_id,)).fetchone() is None:
        abort(404)
    who = current_user()
    db.execute("INSERT INTO board_notes (board_id, author, note) VALUES (?, ?, ?)",
               (board_id, who["name"] if who else "", note))
    db.commit()
    flash("Note added.")
    return redirect(url_for("board_detail", board_id=board_id))


@app.route("/boards/<int:board_id>/time", methods=["POST"])
def board_time_add(board_id):
    hours = _to_float(request.form.get("hours"))
    db = get_db()
    if db.execute("SELECT 1 FROM boards WHERE id = ?", (board_id,)).fetchone() is None:
        abort(404)
    if not hours or hours <= 0:
        flash("Enter the hours worked (a positive number).", "error")
        return redirect(url_for("board_detail", board_id=board_id))
    who = current_user()
    db.execute(
        "INSERT INTO board_time (board_id, household_member_id, who, hours, work_date, note)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (board_id, who["id"] if who else None, who["name"] if who else "",
         round(hours, 2),
         request.form.get("work_date", "").strip()
         or datetime.now().strftime("%Y-%m-%d"),
         request.form.get("note", "").strip()))
    db.commit()
    flash(f"Logged {hours:g} h.")
    return redirect(url_for("board_detail", board_id=board_id))


@app.route("/boards/<int:board_id>/delete", methods=["POST"])
def board_delete(board_id):
    db = get_db()
    board = db.execute("SELECT * FROM boards WHERE id = ?", (board_id,)).fetchone()
    if board is None:
        abort(404)
    me = current_user()
    # The creator, the current assignee, or an admin may remove a board.
    allowed = (_is_admin()
               or (me and board["assigned_to"] == me["id"])
               or (me and (board["created_by"] or "") == me["name"]))
    if not allowed:
        flash("Only the creator, assignee, or a manager can delete this board.", "error")
        return redirect(url_for("board_detail", board_id=board_id))
    db.execute("DELETE FROM board_notes WHERE board_id = ?", (board_id,))
    db.execute("DELETE FROM board_time WHERE board_id = ?", (board_id,))
    db.execute("DELETE FROM boards WHERE id = ?", (board_id,))
    db.commit()
    flash("Board deleted.")
    return redirect(url_for("boards_page"))


def _closing_worklist(db):
    """Projects in the Wrap-up stage with balance due and remaining close-out
    steps — the Executive overview's Wrap-up worklist, also the Sales
    'Wrap-up' mode."""
    out = []
    for p in db.execute(
            "SELECT * FROM projects"
            " WHERE status = 'Wrap-up' ORDER BY id").fetchall():
        b = project_billing(db, p["id"], p["contract_amount"] or 0.0)
        steps = db.execute(
            "SELECT title, status FROM project_tasks WHERE project_id = ?"
            " AND pipeline_status = 'Wrap-up' ORDER BY sort_order, id",
            (p["id"],)).fetchall()
        open_steps = [s for s in steps if s["status"] != "Done"]
        out.append({
            "project": p, "balance": max(b["contract"] - b["collected"], 0.0),
            "open": len(open_steps), "total": len(steps),
            "next": open_steps[0]["title"] if open_steps else ""})
    return out


STAGE_ICON = {"Planning": "💬", "Prep": "📦", "In Progress": "🔧", "Wrap-up": "🏁"}


@app.route("/dashboard")
@app.route("/", endpoint="home")
def dashboard():
    """Piece 19 (revised Piece 35): the household's single shared dashboard —
    the sign-in landing and the bare "/" root, both served by this one view.
    Every section below renders unconditionally for every signed-in member;
    there's no more per-role mode switcher. In open mode (no accounts set up
    yet) user is None — the personal sections just render empty."""
    user = current_user()
    db = get_db()
    ensure_backlog_reminders(db)

    my_tasks = []
    if user is not None:
        my_tasks = db.execute(
            "SELECT t.*, p.job_name, p.id AS project_id"
            " FROM project_tasks t JOIN projects p ON p.id = t.project_id"
            " WHERE t.household_member_id = ? AND t.status != 'Done' AND p.status != 'Abandoned'"
            " ORDER BY (t.due_date = ''), t.due_date, p.id", (user["id"],)).fetchall()
    # Piece 26.7: group My Tasks under each project so the board reads as a banner per
    # project with its tasks beneath, instead of one flat list. First-seen order keeps
    # the overdue/soonest-due project on top (my_tasks is already sorted that way).
    task_groups = []
    _tg_index = {}
    for t in my_tasks:
        jid = t["project_id"]
        if jid not in _tg_index:
            _tg_index[jid] = len(task_groups)
            task_groups.append({
                "project_id": jid, "job_name": t["job_name"], "tasks": []})
        task_groups[_tg_index[jid]]["tasks"].append(t)

    # Active-projects overview: every non-terminal project, grouped by stage
    # (replaces the old per-department project lists).
    active_projects = db.execute(
        "SELECT id, job_name, status, install_date, electric_loads"
        " FROM projects WHERE status NOT IN ('Abandoned', 'Done')"
        " ORDER BY status, id").fetchall()
    by_stage = {}
    for j in active_projects:
        by_stage.setdefault(j["status"], []).append(j)
    sections = [{"name": stage, "icon": STAGE_ICON.get(stage, "📋"),
                 "projects": by_stage[stage]}
                for stage in STAGE_ORDER[:-1] if stage in by_stage]

    # Progress + loads-recorded status for every active project.
    progress_by_job = {}
    loads_by_job = {}
    for j in active_projects:
        progress_by_job[j["id"]] = build_project_progress(db, j)
        loads_by_job[j["id"]] = _loads_recorded(db, j)

    # Permits-filed coverage (X/Y) for projects where it matters — Prep and Wrap-up.
    rules = db.execute("SELECT * FROM resource_rules").fetchall()
    permits_by_job = {}
    for j in active_projects:
        if j["status"] in ("Prep", "Wrap-up"):
            full = db.execute("SELECT * FROM projects WHERE id = ?", (j["id"],)).fetchone()
            permits_by_job[j["id"]] = project_permit_coverage(db, full, rules)

    # Materials/procurement rollup — material counts by status, Prep-stage projects.
    procurement = []
    for j in active_projects:
        if j["status"] == "Prep":
            counts = {s: 0 for s in MATERIAL_STATUSES}
            total = 0
            for m in db.execute(
                    "SELECT status, COUNT(*) AS n FROM project_materials"
                    " WHERE project_id = ? GROUP BY status", (j["id"],)).fetchall():
                counts[m["status"]] = counts.get(m["status"], 0) + m["n"]
                total += m["n"]
            outstanding = (counts.get("Needed", 0) + counts.get("Quoted", 0)
                           + counts.get("Backordered", 0))
            procurement.append({"project": j, "counts": counts, "total": total,
                                "outstanding": outstanding})

    # Install-date buckets — In Progress / Wrap-up projects split by timing.
    today_d = datetime.now().date()
    week_end = today_d + timedelta(days=7)

    def _idate(j):
        try:
            return datetime.strptime(j["install_date"], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return None
    wk, up, other = [], [], []
    for j in active_projects:
        if j["status"] in ("In Progress", "Wrap-up"):
            d = _idate(j)
            if d and today_d <= d <= week_end:
                wk.append((d, j))
            elif d and d > week_end:
                up.append((d, j))
            else:
                other.append((d, j))

    def _srt(rows):
        return [j for _d, j in sorted(
            rows, key=lambda x: (x[0] is None, x[0] or date.max))]
    install_buckets = [
        {"key": "week", "label": "🔨 This week",
         "hint": "installs in the next 7 days", "projects": _srt(wk)},
        {"key": "upcoming", "label": "📅 Upcoming",
         "hint": "scheduled further out", "projects": _srt(up)},
        {"key": "other", "label": "🔎 Wrap-up / unscheduled",
         "hint": "install date passed or not set yet", "projects": _srt(other)},
    ]

    # Piece 22.3 (revised Piece 35): Executive company-overview — a whole-
    # household snapshot: pipeline counts, money in flight, what needs
    # attention, this week's installs, and a Wrap-up worklist. Shown to
    # every signed-in member now, not admin-gated.
    today_s = today_d.strftime("%Y-%m-%d")
    exec_stages = STAGE_ORDER[:-1]           # Planning .. Wrap-up
    counts = {s: 0 for s in exec_stages}
    money = {"contract": 0.0, "collected": 0.0,
             "outstanding": 0.0, "expense": 0.0}
    for j in db.execute(
            "SELECT id, status, contract_amount FROM projects"
            " WHERE status != 'Abandoned'").fetchall():
        if j["status"] in counts:
            counts[j["status"]] += 1
        b = project_billing(db, j["id"], j["contract_amount"] or 0.0)
        for k in money:
            money[k] += b[k]
    overdue = db.execute(
        "SELECT COUNT(*) FROM project_tasks t JOIN projects j ON j.id = t.project_id"
        " WHERE t.status != 'Done' AND t.due_date != '' AND t.due_date < ?"
        " AND j.status NOT IN ('Abandoned', 'Done')", (today_s,)).fetchone()[0]
    # Stalled: active projects whose newest task activity is over 14 days
    # old (projects that had movement and then went quiet; brand-new
    # no-task projects are excluded).
    cutoff = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d %H:%M:%S")
    stalled = db.execute(
        "SELECT j.id, j.job_name, j.status,"
        " MAX(t.updated_at) AS last FROM projects j"
        " JOIN project_tasks t ON t.project_id = j.id"
        " WHERE j.status NOT IN ('Abandoned', 'Done')"
        " GROUP BY j.id HAVING last IS NOT NULL AND last < ?"
        " ORDER BY last", (cutoff,)).fetchall()
    wk_end = (today_d + timedelta(days=7)).strftime("%Y-%m-%d")
    installs_week = db.execute(
        "SELECT id, job_name, status, install_date FROM projects"
        " WHERE install_date != '' AND install_date BETWEEN ? AND ?"
        " AND status != 'Abandoned' ORDER BY install_date",
        (today_s, wk_end)).fetchall()
    closing_jobs = _closing_worklist(db)
    # Ready for design: Planning-stage projects whose load survey is
    # captured (the step before design) but whose design isn't finalized yet.
    ready_design = []
    for j in db.execute(
            "SELECT id, job_name, electric_loads FROM projects"
            " WHERE status = 'Planning' ORDER BY id").fetchall():
        if not _loads_recorded(db, j):
            continue
        designed = db.execute(
            "SELECT 1 FROM project_tasks WHERE project_id = ?"
            " AND LOWER(title) LIKE '%finalize%design%' AND status = 'Done'"
            " LIMIT 1", (j["id"],)).fetchone()
        if not designed:
            ready_design.append(j)
    gm = {"counts": [(s, counts[s]) for s in exec_stages], "money": money,
          "approvals": db.execute(
              "SELECT COUNT(*) FROM field_submissions"
              " WHERE status = 'Pending'").fetchone()[0],
          "overdue": overdue, "stalled": stalled, "ready_design": ready_design,
          "installs_week": installs_week, "closing": closing_jobs}

    # Payments/Finance table across every active project (all in-flight
    # money — deposits, invoices, expenses).
    payments = []
    pay_totals = {"contract": 0.0, "collected": 0.0, "outstanding": 0.0,
                  "expense": 0.0, "net": 0.0}
    for j in db.execute(
            "SELECT id, job_name, status, contract_amount FROM projects"
            " WHERE status != 'Abandoned' ORDER BY status, id").fetchall():
        b = project_billing(db, j["id"], j["contract_amount"] or 0.0)
        payments.append({"project": j, "b": b})
        for k in pay_totals:
            pay_totals[k] += b[k]

    backlog_worklist = db.execute(
        "SELECT i.*, e.name AS proposed_by_name FROM household_ideas i"
        " LEFT JOIN household_members e ON e.id = i.proposed_by"
        " WHERE i.status = 'Backlog'"
        " ORDER BY (i.reminder_date = ''), i.reminder_date, i.created_at"
    ).fetchall()
    stale_stock = len(stale_stock_items(db))
    return render_template(
        "dashboard.html", user=user,
        stale_stock=stale_stock, task_groups=task_groups,
        sections=sections, my_tasks=my_tasks, backlog_worklist=backlog_worklist,
        payments=payments, pay_totals=pay_totals,
        today=today_s,
        progress_by_job=progress_by_job, loads_by_job=loads_by_job,
        permits_by_job=permits_by_job,
        procurement=procurement, material_statuses=MATERIAL_STATUSES,
        install_buckets=install_buckets, gm=gm, closing_jobs=closing_jobs,
        job_status_class=PROJECT_STATUS_CLASS)


# ---------------------------- Piece 20: calendar (.ics) export ------------
def _ics_escape(text):
    return ((text or "").replace("\\", "\\\\").replace("\n", "\\n")
            .replace(",", "\\,").replace(";", "\\;"))


def _ics_fold(line):
    """Fold long lines to <=74 chars per RFC 5545 (continuations start with a space)."""
    out = []
    while len(line) > 74:
        out.append(line[:74])
        line = " " + line[74:]
    out.append(line)
    return "\r\n".join(out)


def build_ics(calname, events):
    """Build a VCALENDAR of all-day events. Each event: {uid, date (YYYY-MM-DD),
    summary, description}. Stable UIDs let a re-import update instead of dupe."""
    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0",
             "PRODID:-//Vixinman Designs//Compendium//EN", "CALSCALE:GREGORIAN",
             "METHOD:PUBLISH", _ics_fold("X-WR-CALNAME:" + _ics_escape(calname))]
    for e in events:
        try:
            start = datetime.strptime(e["date"], "%Y-%m-%d")
        except (ValueError, TypeError):
            continue
        end = (start + timedelta(days=1)).strftime("%Y%m%d")
        lines += ["BEGIN:VEVENT", f"UID:{e['uid']}", f"DTSTAMP:{stamp}",
                  f"DTSTART;VALUE=DATE:{start.strftime('%Y%m%d')}",
                  f"DTEND;VALUE=DATE:{end}",
                  _ics_fold("SUMMARY:" + _ics_escape(e["summary"]))]
        if e.get("description"):
            lines.append(_ics_fold("DESCRIPTION:" + _ics_escape(e["description"])))
        lines += ["TRANSP:TRANSPARENT", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def _ics_response(calname, events, filename):
    return Response(build_ics(calname, events), mimetype="text/calendar",
                    headers={"Content-Disposition": f"attachment; filename={filename}"})


def _task_events(rows):
    events = []
    for t in rows:
        project = t["job_name"] or f"Project #{t['project_id']}"
        desc = f"Status: {t['status']}"
        if t["pipeline_status"]:
            desc += f"\nStage: {t['pipeline_status']}"
        events.append({"uid": f"compendium-task-{t['id']}@vixinmandesigns",
                       "date": t["due_date"], "summary": f"{t['title']} — {project}",
                       "description": desc})
    return events


@app.route("/calendar/my.ics")
def my_calendar_ics():
    """The signed-in person's task due dates + install dates for their projects,
    as an importable calendar. In open mode (no login) exports everything."""
    db = get_db()
    user = current_user()
    tsql = ("SELECT t.*, j.job_name FROM project_tasks t"
            " JOIN projects j ON j.id = t.project_id"
            " WHERE COALESCE(t.due_date, '') != ''")
    jsql = ("SELECT DISTINCT id, job_name, install_date FROM projects"
            " WHERE COALESCE(install_date, '') != ''")
    params = []
    if user:
        tsql += " AND t.household_member_id = ?"
        jsql += " AND id IN (SELECT project_id FROM project_tasks WHERE household_member_id = ?)"
        params = [user["id"]]
    events = _task_events(db.execute(tsql, params).fetchall())
    for j in db.execute(jsql, params).fetchall():
        events.append({"uid": f"compendium-install-{j['id']}@vixinmandesigns",
                       "date": j["install_date"],
                       "summary": f"🔧 Install: {j['job_name'] or 'Project #' + str(j['id'])}",
                       "description": ""})
    name = f"Compendium — {user['name']}" if user else "Compendium — due dates"
    return _ics_response(name, events, "compendium-my-dates.ics")


@app.route("/projects/<int:project_id>/calendar.ics")
def project_calendar_ics(project_id):
    """One project's task due dates + its install date, as an importable calendar."""
    project = fetch_project(project_id)
    db = get_db()
    rows = db.execute(
        "SELECT t.*, ? AS job_name FROM project_tasks t"
        " WHERE t.project_id = ? AND COALESCE(t.due_date, '') != ''",
        (project["job_name"], project_id)).fetchall()
    events = _task_events(rows)
    if project["install_date"]:
        events.append({"uid": f"compendium-install-{project_id}@vixinmandesigns",
                       "date": project["install_date"],
                       "summary": f"🔧 Install: {project['job_name'] or 'Project #' + str(project_id)}",
                       "description": ""})
    label = project["job_name"] or f"Project #{project_id}"
    return _ics_response(f"Compendium — {label}", events, f"compendium-project-{project_id}.ics")


@app.route("/search")
def search():
    """Quick lookup across projects (site/county/products) and the household idea
    backlog (name/notes)."""
    q = (request.args.get("q") or "").strip()
    projects, ideas = [], []
    if q:
        like = f"%{q}%"
        db = get_db()
        projects = db.execute(
            "SELECT * FROM projects"
            " WHERE job_name LIKE ? OR site_location LIKE ? OR county LIKE ?"
            " OR products LIKE ? ORDER BY created_at DESC",
            (like, like, like, like)).fetchall()
        ideas = db.execute(
            "SELECT * FROM household_ideas"
            " WHERE name LIKE ? OR notes LIKE ? ORDER BY created_at DESC",
            (like, like)).fetchall()
    return render_template("search.html", q=q, projects=projects, ideas=ideas,
                           job_status_class=PROJECT_STATUS_CLASS)


@app.route("/api/quick-search")
def api_quick_search():
    """Piece 28.4 (revised 33): autocomplete for the nav search — project and
    household-idea NAMES only."""
    q = (request.args.get("q") or "").strip()
    results = []
    if q:
        like = f"%{q}%"
        db = get_db()
        for j in db.execute(
                "SELECT id, job_name FROM projects WHERE job_name LIKE ?"
                " ORDER BY created_at DESC LIMIT 8", (like,)).fetchall():
            results.append({"type": "project",
                            "label": j["job_name"] or f"Project #{j['id']}",
                            "sub": "",
                            "url": url_for("project_detail", project_id=j["id"])})
        for i in db.execute(
                "SELECT id, name FROM household_ideas WHERE name LIKE ?"
                " ORDER BY created_at DESC LIMIT 6", (like,)).fetchall():
            results.append({"type": "idea", "label": i["name"], "sub": "",
                            "url": url_for("backlog_detail", idea_id=i["id"])})
    return jsonify({"results": results})


BACKLOG_STATUSES = ["Backlog", "Started", "Abandoned"]


@app.route("/backlog")
def backlog_page():
    """The household idea backlog — someday/maybe projects. Filter by status
    (open = Backlog, defaults to that; or all)."""
    db = get_db()
    show = request.args.get("show", "open")
    sql = ("SELECT i.*, e.name AS proposed_by_name FROM household_ideas i"
           " LEFT JOIN household_members e ON e.id = i.proposed_by WHERE 1 = 1")
    if show == "open":
        sql += " AND i.status = 'Backlog'"
    sql += " ORDER BY (i.reminder_date = ''), i.reminder_date, i.created_at DESC"
    ideas = db.execute(sql).fetchall()
    employees = db.execute(
        "SELECT id, name FROM household_members ORDER BY name").fetchall()
    open_count = db.execute(
        "SELECT COUNT(*) FROM household_ideas WHERE status = 'Backlog'"
    ).fetchone()[0]
    return render_template("backlog.html", ideas=ideas, employees=employees,
                           show=show, statuses=BACKLOG_STATUSES,
                           open_count=open_count,
                           today=datetime.now().strftime("%Y-%m-%d"))


@app.route("/backlog/new", methods=["POST"])
def backlog_new():
    name = request.form.get("name", "").strip()
    if not name:
        flash("An idea needs a name.", "error")
        return redirect(url_for("backlog_page"))
    db = get_db()
    proposer = request.form.get("proposed_by", "")
    proposer_id = int(proposer) if proposer.isdigit() else None
    cur = db.execute(
        "INSERT INTO household_ideas (name, notes, target_date, proposed_by,"
        " budget_estimate, reminder_date) VALUES (?, ?, ?, ?, ?, ?)",
        (name, request.form.get("notes", "").strip(),
         request.form.get("target_date", "").strip(), proposer_id,
         _to_float(request.form.get("budget_estimate")) or 0,
         request.form.get("reminder_date", "").strip()))
    db.commit()
    flash(f"Added to the backlog: {name}")
    return redirect(url_for("backlog_detail", idea_id=cur.lastrowid))


@app.route("/backlog/<int:idea_id>")
def backlog_detail(idea_id):
    db = get_db()
    idea = db.execute(
        "SELECT i.*, e.name AS proposed_by_name FROM household_ideas i"
        " LEFT JOIN household_members e ON e.id = i.proposed_by WHERE i.id = ?",
        (idea_id,)).fetchone()
    if idea is None:
        abort(404)
    employees = db.execute(
        "SELECT id, name FROM household_members ORDER BY name").fetchall()
    return render_template("backlog_detail.html", idea=idea,
                           employees=employees, statuses=BACKLOG_STATUSES)


@app.route("/backlog/<int:idea_id>/edit", methods=["POST"])
def backlog_edit(idea_id):
    db = get_db()
    if db.execute("SELECT 1 FROM household_ideas WHERE id = ?",
                  (idea_id,)).fetchone() is None:
        abort(404)
    name = request.form.get("name", "").strip()
    if not name:
        flash("An idea needs a name.", "error")
        return redirect(url_for("backlog_detail", idea_id=idea_id))
    proposer = request.form.get("proposed_by", "")
    proposer_id = int(proposer) if proposer.isdigit() else None
    db.execute(
        "UPDATE household_ideas SET name = ?, notes = ?, target_date = ?,"
        " proposed_by = ?, budget_estimate = ?, reminder_date = ?,"
        " reminder_sent = '' WHERE id = ?",
        (name, request.form.get("notes", "").strip(),
         request.form.get("target_date", "").strip(), proposer_id,
         _to_float(request.form.get("budget_estimate")) or 0,
         request.form.get("reminder_date", "").strip(), idea_id))
    db.commit()
    flash("Idea updated.")
    return redirect(url_for("backlog_detail", idea_id=idea_id))


@app.route("/backlog/<int:idea_id>/status", methods=["POST"])
def backlog_status(idea_id):
    status = request.form.get("status", "")
    if status not in BACKLOG_STATUSES:
        return redirect(url_for("backlog_detail", idea_id=idea_id))
    db = get_db()
    if status == "Abandoned":
        db.execute("UPDATE household_ideas SET status = ?, abandoned_at = ?"
                   " WHERE id = ?",
                   (status, datetime.now().isoformat(timespec="seconds"), idea_id))
    else:
        db.execute("UPDATE household_ideas SET status = ?, abandoned_at = ''"
                   " WHERE id = ?", (status, idea_id))
    db.commit()
    flash(f"Marked {status}.")
    return redirect(url_for("backlog_detail", idea_id=idea_id))


@app.route("/backlog/<int:idea_id>/start", methods=["POST"])
def backlog_start(idea_id):
    """Turn an idea into a real project/project — a bare row the user fills in
    via the normal project form."""
    db = get_db()
    idea = db.execute("SELECT * FROM household_ideas WHERE id = ?",
                      (idea_id,)).fetchone()
    if idea is None:
        abort(404)
    cur = db.execute(
        "INSERT INTO projects (job_name, site_location) VALUES (?, ?)",
        (idea["name"], ""))
    db.execute(
        "UPDATE household_ideas SET status = 'Started', started_project_id = ?,"
        " started_at = ? WHERE id = ?",
        (cur.lastrowid, datetime.now().isoformat(timespec="seconds"), idea_id))
    db.commit()
    flash(f"Started: {idea['name']} — fill in the rest below.")
    return redirect(url_for("edit_project", project_id=cur.lastrowid))


@app.route("/backlog/<int:idea_id>/delete", methods=["POST"])
@delete_required
def backlog_delete(idea_id):
    ok, msg = trash_item("household_idea", idea_id)
    flash(msg, "" if ok else "error")
    return redirect(url_for("backlog_page"))


# --------------------------------------------------------------- Piece 35: external helpers
@app.route("/external-helpers")
def external_helpers_page():
    """A reusable contact roster for people who help the household but aren't
    a household member — a contractor, tutor, coach, etc."""
    db = get_db()
    helpers = db.execute("SELECT * FROM external_helpers ORDER BY name").fetchall()
    edit_id = request.args.get("edit", type=int)
    edit_helper = db.execute(
        "SELECT * FROM external_helpers WHERE id = ?", (edit_id,)
    ).fetchone() if edit_id else None
    return render_template("external_helpers.html", helpers=helpers,
                           edit_helper=edit_helper)


@app.route("/external-helpers/new", methods=["POST"])
def new_external_helper():
    name = request.form.get("name", "").strip()
    if not name:
        flash("A name is required.", "error")
        return redirect(url_for("external_helpers_page"))
    db = get_db()
    db.execute(
        "INSERT INTO external_helpers (name, phone, email, specialty, notes)"
        " VALUES (?, ?, ?, ?, ?)",
        (name, request.form.get("phone", "").strip(),
         request.form.get("email", "").strip(),
         request.form.get("specialty", "").strip(),
         request.form.get("notes", "").strip()))
    db.commit()
    flash(f"Added: {name}")
    return redirect(url_for("external_helpers_page"))


@app.route("/external-helpers/<int:helper_id>/edit", methods=["POST"])
def edit_external_helper(helper_id):
    db = get_db()
    if db.execute("SELECT 1 FROM external_helpers WHERE id = ?",
                  (helper_id,)).fetchone() is None:
        abort(404)
    name = request.form.get("name", "").strip()
    if not name:
        flash("A name is required.", "error")
        return redirect(url_for("external_helpers_page", edit=helper_id))
    db.execute(
        "UPDATE external_helpers SET name = ?, phone = ?, email = ?,"
        " specialty = ?, notes = ? WHERE id = ?",
        (name, request.form.get("phone", "").strip(),
         request.form.get("email", "").strip(),
         request.form.get("specialty", "").strip(),
         request.form.get("notes", "").strip(), helper_id))
    db.commit()
    flash(f"Updated: {name}")
    return redirect(url_for("external_helpers_page"))


@app.route("/external-helpers/<int:helper_id>/delete", methods=["POST"])
@delete_required
def delete_external_helper(helper_id):
    ok, msg = trash_item("external_helper", helper_id)
    flash(msg, "" if ok else "error")
    return redirect(url_for("external_helpers_page"))


# ------------------------------------------------- household-wide documents
def household_upload_dir():
    directory = UPLOADS_DIR / "household"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


@app.route("/household-files")
def household_files_page():
    files = get_db().execute(
        "SELECT * FROM household_files ORDER BY id DESC").fetchall()
    return render_template("household_files.html", files=files,
                           file_categories=HOUSEHOLD_FILE_CATEGORIES)


@app.route("/household-files/upload", methods=["POST"])
def upload_household_file():
    upload = request.files.get("document")
    if upload is None or not upload.filename:
        flash("Choose a file to upload.", "error")
        return redirect(url_for("household_files_page"))
    extension = upload.filename.rsplit(".", 1)[-1].lower() if "." in upload.filename else ""
    if extension not in ALLOWED_EXTENSIONS:
        flash(f"File type .{extension} is not allowed.", "error")
        return redirect(url_for("household_files_page"))
    category = request.form.get("category", "").strip()
    if category not in HOUSEHOLD_FILE_CATEGORIES:
        category = ""
    db = get_db()
    friendly = friendly_filename(
        [category or "Document"], extension,
        taken={r["original_name"] for r in db.execute(
            "SELECT original_name FROM household_files").fetchall()
            if r["original_name"]})
    stored = f"{uuid.uuid4().hex[:8]}_{secure_filename(friendly)}"
    upload.save(household_upload_dir() / stored)
    db.execute(
        "INSERT INTO household_files (category, stored_name, original_name)"
        " VALUES (?, ?, ?)", (category, stored, friendly))
    db.commit()
    flash(f"Uploaded: {friendly}")
    return redirect(url_for("household_files_page"))


@app.route("/household-files/<int:file_id>/download")
def download_household_file(file_id):
    record = get_db().execute(
        "SELECT * FROM household_files WHERE id = ?", (file_id,)).fetchone()
    if record is None:
        abort(404)
    return send_from_directory(
        household_upload_dir(), record["stored_name"],
        as_attachment=True, download_name=record["original_name"])


@app.route("/household-files/<int:file_id>/delete", methods=["POST"])
@delete_required
def delete_household_file(file_id):
    ok, msg = trash_item("household_file", file_id)
    flash(msg, "" if ok else "error")
    return redirect(url_for("household_files_page"))


@app.route("/projects/new", methods=["GET", "POST"])
def new_project():
    db = get_db()
    if request.method == "POST":
        values, selected, errors = read_project_form()
        if errors:
            flash(" ".join(errors), "error")
            return render_project_form(values, selected, existing_jobs=True), 400
        cur = db.execute(
            f"INSERT INTO projects ({', '.join(PROJECT_FIELDS)})"
            f" VALUES ({', '.join('?' * len(PROJECT_FIELDS))})",
            [values[f] for f in PROJECT_FIELDS],
        )
        # Piece 29.4: a new project turns over to Proposal — alert Sales & Design.
        new_job_row = {"id": cur.lastrowid, "job_name": values["job_name"]}
        actor = current_user()
        notify_stage_turnover(db, new_job_row,
                              values.get("status") or DEFAULT_PROJECT_STATUS,
                              exclude_id=actor["id"] if actor else None)
        db.commit()
        flash(f"Project created: {values['job_name']}")
        return redirect(url_for("project_detail", project_id=cur.lastrowid))
    # For service tickets: optionally pre-fill from a project already on the books.
    values = {"site_location": ""}
    selected = []
    prefill_id = request.args.get("prefill", type=int)
    if prefill_id:
        source = db.execute(
            "SELECT * FROM projects WHERE id = ?", (prefill_id,),
        ).fetchone()
        if source:
            values = {f: source[f] for f in PROJECT_FIELDS}
            values["utility_connection"] = next(
                (source[f] for f in GRID_CONNECTION_FIELDS.values() if source[f]), "")
            values["job_name"] = f"Service — {source['job_name'] or 'Project #' + str(source['id'])}"
            selected = [p.strip() for p in source["products"].split(",") if p.strip()]
            if "Technician Service" not in selected:
                selected.append("Technician Service")
    return render_project_form(values, selected, existing_jobs=True)


def read_project_form():
    """Validate and normalize a submitted project form (create or edit)."""
    values = {f: request.form.get(f, "").strip() for f in PROJECT_FIELDS}
    selected = request.form.getlist("products")
    values["products"] = ", ".join(p for p in PRODUCTS if p in selected)
    # One shared utility-connection choice covers PV, Battery, and
    # Generators; it lands in each selected system's own column (which
    # the rules engine matches on), blank for unselected systems.
    shared = request.form.get("utility_connection", "").strip()
    for product, field in GRID_CONNECTION_FIELDS.items():
        values[field] = shared if product in selected else ""
    values["utility_connection"] = shared  # for form re-render only
    # Product-specific options only apply when their product is selected
    # (the browser hides the sections, but never trust hidden inputs).
    if "PV Systems" not in selected:
        values["pv_mounting_type"] = ""
    if values["pv_mounting_type"] != "Roof mounted":
        values["pv_manufactured_house"] = ""
    if "Technician Service" not in selected:
        values["service_type"] = ""
    errors = []
    if not values["job_name"]:
        errors.append("Project name is required.")
    if not values["site_location"]:
        errors.append("Site location is required.")
    if not values["cost_method"]:
        errors.append("Payment is required.")
    if not values["products"]:
        errors.append("Select at least one product/service.")
    if "Technician Service" in selected and not values["service_type"]:
        errors.append("Specify general or warranty service.")
    return values, selected, errors


def render_project_form(values, selected, existing_jobs=False,
                    editing_job_id=None):
    jobs_on_books = []
    if existing_jobs and not editing_job_id:
        jobs_on_books = get_db().execute(
            "SELECT id, job_name FROM projects ORDER BY created_at DESC").fetchall()
    return render_template(
        "project_form.html", values=values, selected=selected,
        products=PRODUCTS, utility_connections=UTILITY_CONNECTIONS,
        mounting_types=MOUNTING_TYPES, service_types=SERVICE_TYPES,
        payment_terms=PAYMENT_TERMS,                       # Piece 31.8
        utilities=UTILITIES, counties=COUNTIES,
        county_utilities_json=json.dumps(COUNTY_UTILITIES),
        utilities_json=json.dumps(UTILITIES),
        existing_jobs=jobs_on_books, editing_job_id=editing_job_id,
    )


@app.route("/projects/<int:project_id>/edit", methods=["GET", "POST"])
def edit_project(project_id):
    db = get_db()
    project = fetch_project(project_id)
    if request.method == "POST":
        values, selected, errors = read_project_form()
        if errors:
            flash(" ".join(errors), "error")
            return render_project_form(values, selected,
                                   editing_job_id=project_id), 400
        # Keep the outgoing state for recordkeeping before overwriting.
        snapshot = {f: project[f] for f in PROJECT_FIELDS}
        version = db.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 FROM project_versions"
            " WHERE project_id = ?", (project_id,)).fetchone()[0]
        db.execute(
            "INSERT INTO project_versions (project_id, version, data) VALUES (?, ?, ?)",
            (project_id, version, json.dumps(snapshot)),
        )
        db.execute(
            f"UPDATE projects SET {', '.join(f + ' = ?' for f in PROJECT_FIELDS)}"
            " WHERE id = ?",
            [values[f] for f in PROJECT_FIELDS] + [project_id],
        )
        db.commit()
        flash(f"Project updated — the previous state was kept as version {version}.")
        return redirect(url_for("project_detail", project_id=project_id))
    values = {f: project[f] for f in PROJECT_FIELDS}
    values["utility_connection"] = next(
        (project[f] for f in GRID_CONNECTION_FIELDS.values() if project[f]), "")
    selected = [p.strip() for p in project["products"].split(",") if p.strip()]
    return render_project_form(values, selected, editing_job_id=project_id)


@app.route("/projects/<int:project_id>/versions/<int:version>")
def project_version(project_id, version):
    project = fetch_project(project_id)
    row = get_db().execute(
        "SELECT * FROM project_versions WHERE project_id = ? AND version = ?",
        (project_id, version),
    ).fetchone()
    if row is None:
        abort(404)
    data = json.loads(row["data"])
    rules = get_db().execute("SELECT * FROM resource_rules").fetchall()
    groups = group_rules(match_rules(data, rules))
    return render_template(
        "project_version.html", project=project, version=row, data=data,
        groups=groups, field_labels=PROJECT_FIELD_LABELS, job_fields=PROJECT_FIELDS,
    )


def fetch_project(project_id):
    project = get_db().execute(
        "SELECT * FROM projects WHERE id = ?",
        (project_id,),
    ).fetchone()
    if project is None:
        abort(404)
    return project


@app.route("/projects/<int:project_id>")
def project_detail(project_id):
    project = fetch_project(project_id)
    db = get_db()
    # Piece 29.4: reaching the project clears this user's stage-turnover alerts for
    # it — the notification has served its purpose once they're looking at it.
    me = current_user()
    if me is not None:
        cleared = db.execute(
            "DELETE FROM notifications WHERE recipient_id = ? AND kind = 'stage'"
            " AND link = ?", (me["id"], url_for("project_detail", project_id=project_id)))
        if cleared.rowcount:
            db.commit()
    rules = db.execute("SELECT * FROM resource_rules").fetchall()
    groups = group_rules(match_rules(project, rules))
    versions = db.execute(
        "SELECT version, saved_at FROM project_versions WHERE project_id = ?"
        " ORDER BY version DESC", (project_id,)
    ).fetchall()
    materials = db.execute(
        "SELECT * FROM project_materials WHERE project_id = ? ORDER BY id", (project_id,)
    ).fetchall()
    files = db.execute(
        "SELECT * FROM project_files WHERE project_id = ? ORDER BY id", (project_id,)
    ).fetchall()
    filed_labels = {f["rule_label"] for f in files if f["rule_label"]}
    # Filing coverage per category: how many requirements have a document.
    coverage = {
        heading: sum(1 for r in items if r["label"] in filed_labels)
        for heading, items in groups
    }
    # Filing dropdown, sectioned: generic types first, then the project's
    # requirements grouped by their category headings.
    requirement_groups = [
        (heading, sorted({r["label"] for r in items}))
        for heading, items in groups
    ]

    # Piece 15.1: Loads & Sizing moved to its own page (project_loads); its data
    # is no longer computed here.

    # Piece 10: tasks for this project, plus the crew list for the assignee
    # picker. Assignee name comes along via a LEFT JOIN so unassigned tasks
    # (household_member_id NULL) still show.
    tasks = db.execute(
        "SELECT t.*, e.name AS assignee_name FROM project_tasks t"
        " LEFT JOIN household_members e ON e.id = t.household_member_id"
        " WHERE t.project_id = ? ORDER BY t.sort_order, t.id", (project_id,)
    ).fetchall()
    employees = db.execute("SELECT id, name FROM household_members ORDER BY name").fetchall()
    stage = stage_info(db, project, groups, filed_labels)
    progress = build_project_progress(db, project)

    # Saved load-survey results (from the Loads & Sizing page) surfaced here so
    # the numbers Sales captured on the walkthrough are visible in the project
    # details and ready for the Designer — no need to re-open the loads page.
    lrooms = db.execute("SELECT * FROM project_load_rooms WHERE project_id = ?", (project_id,)).fetchall()
    litems = db.execute("SELECT * FROM project_load_items WHERE project_id = ?", (project_id,)).fetchall()
    load_daily_kwh, load_peak_w = compute_load_totals(lrooms, litems)
    load_has_survey = bool(litems)

    # Documents tab: one upload slot per file the project needs — the standard docs
    # plus the project's document-worthy requirements (permits / compliance / doc
    # items; licenses, portals and phone numbers aren't files, so they're
    # excluded). files_by_label maps a slot to the files filed under it;
    # other_files are anything filed outside those slots.
    doc_req_groups = [
        (heading, sorted({r["label"] for r in items}))
        for heading, items in groups
        if items and items[0]["category"] in ("Permit", "Compliance", "Doc")
    ]
    doc_sections = [("General", STANDARD_JOB_DOCS)] + doc_req_groups
    needed_labels = set(STANDARD_JOB_DOCS)
    for _heading, labels in doc_req_groups:
        needed_labels.update(labels)
    files_by_label = {}
    for f in files:
        files_by_label.setdefault(f["rule_label"] or "", []).append(f)
    other_files = [f for f in files if (f["rule_label"] or "") not in needed_labels]

    # Piece 25.2: accepted formats per document slot (label -> sorted ext list, or
    # None = any allowed type). Covers standard slots and every requirement label.
    slot_labels = set(needed_labels)
    for _heading, items in groups:
        for r in items:
            slot_labels.add(r["label"])
    formats_by_label = {}
    for lbl in slot_labels:
        fmts = allowed_formats_for_label(db, lbl)
        formats_by_label[lbl] = sorted(fmts) if fmts else None

    billing = project_billing(
        db, project_id, project["contract_amount"] if "contract_amount" in project.keys() else 0.0)

    # Piece 21.9: field notes the crew left from the Work Bag, newest first.
    project_notes = db.execute(
        "SELECT * FROM project_notes WHERE project_id = ? ORDER BY id DESC",
        (project_id,)).fetchall()

    pricing = project_pricing(db, project)

    return render_template(
        "project_detail.html", project=project, groups=groups, versions=versions,
        project_notes=project_notes,
        materials=materials, files=files, filed_labels=filed_labels,
        coverage=coverage, requirement_groups=requirement_groups,
        material_statuses=MATERIAL_STATUSES, license_staffing=license_staffing(),
        tasks=tasks, employees=employees, task_statuses=TASK_STATUSES,
        job_statuses=PROJECT_STATUSES, job_status_class=PROJECT_STATUS_CLASS,
        stage=stage, progress=progress, today=datetime.now().strftime("%Y-%m-%d"),
        load_daily_kwh=load_daily_kwh, load_peak_w=load_peak_w,
        load_has_survey=load_has_survey, doc_sections=doc_sections,
        files_by_label=files_by_label, other_files=other_files,
        formats_by_label=formats_by_label,
        billing=billing, txn_kinds=TXN_KINDS, txn_statuses=TXN_STATUSES,
        income_categories=INCOME_CATEGORIES, expense_categories=EXPENSE_CATEGORIES,
        payment_methods=PAYMENT_METHODS, doc_types=DOC_TYPES,
        pricing=pricing,                                   # Piece 29.6
        can_see_pricing=_can_see_pricing(),                # Piece 29.7
        estimate_sections=ESTIMATE_SECTIONS,               # Piece 29.9
    )


@app.route("/projects/<int:project_id>/contract", methods=["POST"])
def set_contract(project_id):
    fetch_project(project_id)
    db = get_db()
    # Piece 27.4: GRT rate is set alongside the contract (both drive invoicing).
    grt = max(_to_float(request.form.get("grt_rate")) or 0.0, 0.0)
    db.execute("UPDATE projects SET contract_amount = ?, grt_rate = ? WHERE id = ?",
               (_to_float(request.form.get("contract_amount")) or 0.0,
                str(grt), project_id))
    db.commit()
    flash("Billing details updated.")
    return redirect(url_for("project_detail", project_id=project_id, _anchor="billing"))


# ---------------------------------------------------------- per-project estimate
def _estimate_guard(project_id):
    """Estimate editing is limited to who can see pricing (Finance/Sales/Design)."""
    fetch_project(project_id)
    if not _can_see_pricing():
        flash("Pricing is limited to Finance, Sales and Design.", "error")
        return False
    return True


@app.route("/projects/<int:project_id>/estimate/prefill", methods=["POST"])
def estimate_prefill(project_id):
    """Copy the cost-model default lines (non-equipment sections) into this
    project's estimate, so the estimator starts from Vixinman's template. Skips sections
    already present, so it won't duplicate."""
    if not _estimate_guard(project_id):
        return redirect(url_for("project_detail", project_id=project_id, _anchor="estimate"))
    db = get_db()
    have = {r["section"] for r in db.execute(
        "SELECT DISTINCT section FROM project_estimate_lines WHERE project_id = ?",
        (project_id,)).fetchall()}
    nxt = db.execute("SELECT COALESCE(MAX(sort_order), -1) + 1"
                     " FROM project_estimate_lines WHERE project_id = ?", (project_id,)).fetchone()[0]
    added = 0
    for r in db.execute(
            "SELECT * FROM cost_model_lines WHERE active = '1'"
            " ORDER BY sort_order, id").fetchall():
        if r["section"] not in ESTIMATE_SECTIONS or r["section"] in have:
            continue
        db.execute(
            "INSERT INTO project_estimate_lines (project_id, section, item, unit, qty,"
            " unit_cost, markup_pct, sort_order) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (project_id, r["section"], r["item"], r["unit"] or "",
             r["default_qty"] or 0, r["unit_cost"] or 0, r["markup_pct"] or 0, nxt))
        nxt += 1
        added += 1
    db.commit()
    flash(f"Added {added} line(s) from the cost model." if added
          else "Those sections are already on the estimate.")
    return redirect(url_for("project_detail", project_id=project_id, _anchor="estimate"))


@app.route("/projects/<int:project_id>/estimate/add", methods=["POST"])
def estimate_add_line(project_id):
    if not _estimate_guard(project_id):
        return redirect(url_for("project_detail", project_id=project_id, _anchor="estimate"))
    section = request.form.get("section", "")
    item = request.form.get("item", "").strip()
    if section not in ESTIMATE_SECTIONS or not item:
        flash("Pick a section and name the line.", "error")
        return redirect(url_for("project_detail", project_id=project_id, _anchor="estimate"))
    db = get_db()
    nxt = db.execute("SELECT COALESCE(MAX(sort_order), -1) + 1"
                     " FROM project_estimate_lines WHERE project_id = ?", (project_id,)).fetchone()[0]
    db.execute(
        "INSERT INTO project_estimate_lines (project_id, section, item, unit, qty,"
        " unit_cost, markup_pct, sort_order) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (project_id, section, item, request.form.get("unit", "").strip(),
         max(_to_float(request.form.get("qty")) or 0.0, 0.0),
         max(_to_float(request.form.get("cost")) or 0.0, 0.0),
         max(_to_float(request.form.get("markup")) or 0.0, 0.0), nxt))
    db.commit()
    flash(f"Added “{item}”.")
    return redirect(url_for("project_detail", project_id=project_id, _anchor="estimate"))


@app.route("/projects/<int:project_id>/estimate/save", methods=["POST"])
def estimate_save(project_id):
    if not _estimate_guard(project_id):
        return redirect(url_for("project_detail", project_id=project_id, _anchor="estimate"))
    db = get_db()
    for r in db.execute("SELECT id FROM project_estimate_lines WHERE project_id = ?",
                        (project_id,)).fetchall():
        i = r["id"]
        if f"qty_{i}" not in request.form:
            continue
        db.execute(
            "UPDATE project_estimate_lines SET qty = ?, unit_cost = ?, markup_pct = ?"
            " WHERE id = ? AND project_id = ?",
            (max(_to_float(request.form.get(f"qty_{i}")) or 0.0, 0.0),
             max(_to_float(request.form.get(f"cost_{i}")) or 0.0, 0.0),
             max(_to_float(request.form.get(f"markup_{i}")) or 0.0, 0.0), i, project_id))
    db.commit()
    flash("Estimate saved.")
    return redirect(url_for("project_detail", project_id=project_id, _anchor="estimate"))


@app.route("/projects/<int:project_id>/estimate/<int:line_id>/delete", methods=["POST"])
def estimate_delete_line(project_id, line_id):
    if not _estimate_guard(project_id):
        return redirect(url_for("project_detail", project_id=project_id, _anchor="estimate"))
    db = get_db()
    db.execute("DELETE FROM project_estimate_lines WHERE id = ? AND project_id = ?",
               (line_id, project_id))
    db.commit()
    flash("Line removed.")
    return redirect(url_for("project_detail", project_id=project_id, _anchor="estimate"))


@app.route("/projects/<int:project_id>/estimate/to-contract", methods=["POST"])
def estimate_to_contract(project_id):
    """Set the contract total to the estimate's suggested price."""
    project = fetch_project(project_id)
    if not _estimate_guard(project_id):
        return redirect(url_for("project_detail", project_id=project_id, _anchor="estimate"))
    db = get_db()
    suggested = project_pricing(db, project)["suggested"]
    db.execute("UPDATE projects SET contract_amount = ? WHERE id = ?",
               (suggested, project_id))
    db.commit()
    flash(f"Contract total set to the suggested price — ${suggested:,.2f}.")
    return redirect(url_for("project_detail", project_id=project_id, _anchor="billing"))


@app.route("/finance/settings")
@finance_required
def finance_settings():
    """Piece 29.6/29.8: the Cost Model Defaults (equipment, labor, travel,
    adders, overhead) plus the NM county GRT rate table."""
    db = get_db()
    counties = db.execute(
        "SELECT * FROM county_tax_rates ORDER BY county").fetchall()
    return render_template(
        "finance_settings.html", counties=counties,
        sections=cost_model_by_section(db), section_order=COST_MODEL_SECTIONS,
        rollup=cost_model_rollup(db))


@app.route("/finance/settings/counties", methods=["POST"])
@finance_required
def finance_save_counties():
    db = get_db()
    for c in db.execute("SELECT id FROM county_tax_rates").fetchall():
        val = request.form.get(f"county_{c['id']}")
        if val is not None:
            db.execute("UPDATE county_tax_rates SET grt_rate = ?, updated_at = ?"
                       " WHERE id = ?",
                       (max(_to_float(val) or 0.0, 0.0),
                        datetime.now().strftime("%Y-%m-%d"), c["id"]))
    db.commit()
    flash("County GRT rates saved.")
    return redirect(url_for("finance_settings"))


def _cost_line_num(raw):
    """Parse an optional numeric cost-model field: blank stays NULL."""
    if raw is None or str(raw).strip() == "":
        return None
    v = _to_float(raw)
    return max(v, 0.0) if v is not None else None


@app.route("/finance/settings/cost-model", methods=["POST"])
@finance_required
def finance_save_cost_model():
    """Bulk-save every cost-model line's qty / cost / markup."""
    db = get_db()
    for r in db.execute("SELECT id FROM cost_model_lines WHERE active = '1'").fetchall():
        i = r["id"]
        if f"markup_{i}" not in request.form:
            continue
        db.execute(
            "UPDATE cost_model_lines SET default_qty = ?, unit_cost = ?,"
            " unit = ?, markup_pct = ? WHERE id = ?",
            (_cost_line_num(request.form.get(f"qty_{i}")),
             _cost_line_num(request.form.get(f"cost_{i}")),
             request.form.get(f"unit_{i}", "").strip(),
             max(_to_float(request.form.get(f"markup_{i}")) or 0.0, 0.0), i))
    db.commit()
    flash("Cost model saved.")
    return redirect(url_for("finance_settings"))


@app.route("/finance/settings/cost-model/add", methods=["POST"])
@finance_required
def finance_add_cost_line():
    db = get_db()
    section = request.form.get("section", "")
    item = request.form.get("item", "").strip()
    if section not in COST_MODEL_SECTIONS or not item:
        flash("Pick a section and name the line.", "error")
        return redirect(url_for("finance_settings"))
    nxt = db.execute("SELECT COALESCE(MAX(sort_order), -1) + 1"
                     " FROM cost_model_lines").fetchone()[0]
    db.execute(
        "INSERT INTO cost_model_lines (section, item, unit, default_qty,"
        " unit_cost, markup_pct, sort_order) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (section, item, request.form.get("unit", "").strip(),
         _cost_line_num(request.form.get("qty")),
         _cost_line_num(request.form.get("cost")),
         max(_to_float(request.form.get("markup")) or 0.0, 0.0), nxt))
    db.commit()
    flash(f"Added “{item}” to {section}.")
    return redirect(url_for("finance_settings"))


@app.route("/finance/settings/cost-model/<int:line_id>/delete", methods=["POST"])
@finance_required
def finance_delete_cost_line(line_id):
    db = get_db()
    db.execute("UPDATE cost_model_lines SET active = '' WHERE id = ?", (line_id,))
    db.commit()
    flash("Line removed.")
    return redirect(url_for("finance_settings"))


@app.route("/projects/<int:project_id>/transactions/add", methods=["POST"])
def add_transaction(project_id):
    fetch_project(project_id)
    kind = request.form.get("kind", "Expense")
    kind = kind if kind in TXN_KINDS else "Expense"
    status = request.form.get("status", "Outstanding")
    status = status if status in TXN_STATUSES else "Outstanding"
    doc_type = request.form.get("doc_type", "").strip()
    doc_type = doc_type if doc_type in DOC_TYPES else ""
    who = current_user()
    db = get_db()
    cur = db.execute(
        "INSERT INTO project_transactions"
        " (project_id, kind, category, description, amount, txn_date, status,"
        "  party, reference, method, doc_type, created_by)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (project_id, kind, request.form.get("category", "").strip(),
         request.form.get("description", "").strip(),
         _to_float(request.form.get("amount")) or 0.0,
         request.form.get("txn_date", "").strip(), status,
         request.form.get("party", "").strip(),
         request.form.get("reference", "").strip(),
         request.form.get("method", "").strip(), doc_type,
         who["name"] if who else ""))
    txn_id = cur.lastrowid
    # Piece 28.2: optionally attach a source document (receipt / invoice / bill)
    # uploaded from the device — filed against this transaction (txn_id) so it
    # shows the 📎 link in the ledger and lands on the project's document record.
    upload = request.files.get("document")
    if upload is not None and upload.filename:
        ext = upload.filename.rsplit(".", 1)[-1].lower() if "." in upload.filename else ""
        if ext in (PHOTO_EXTENSIONS | {"pdf"}):
            info = db.execute(
                "SELECT job_name FROM projects WHERE id = ?", (project_id,)).fetchone()
            label = doc_type or "Billing"
            friendly = friendly_filename(
                [info["job_name"], label], ext,
                taken=_taken_names(db, "project_files", "original_name", "project_id", project_id))
            stored = f"{uuid.uuid4().hex[:8]}_{secure_filename(friendly)}"
            upload.save(project_upload_dir(project_id) / stored)
            db.execute(
                "INSERT INTO project_files"
                " (project_id, rule_label, stored_name, original_name, txn_id)"
                " VALUES (?, ?, ?, ?, ?)", (project_id, label, stored, friendly, txn_id))
        else:
            flash("Attachment skipped — it must be a photo (JPG/PNG/HEIC) or a PDF.", "error")
    db.commit()
    flash(f"{doc_type or kind} recorded.")
    return redirect(url_for("project_detail", project_id=project_id, _anchor="billing"))


@app.route("/projects/<int:project_id>/transactions/<int:txn_id>/paid", methods=["POST"])
def toggle_transaction_paid(project_id, txn_id):
    db = get_db()
    row = db.execute("SELECT status FROM project_transactions WHERE id = ? AND project_id = ?",
                     (txn_id, project_id)).fetchone()
    if row:
        db.execute("UPDATE project_transactions SET status = ? WHERE id = ? AND project_id = ?",
                   ("Outstanding" if row["status"] == "Paid" else "Paid", txn_id, project_id))
        db.commit()
    return redirect(url_for("project_detail", project_id=project_id, _anchor="billing"))


@app.route("/projects/<int:project_id>/transactions/<int:txn_id>/delete", methods=["POST"])
def delete_transaction(project_id, txn_id):
    db = get_db()
    db.execute("DELETE FROM project_transactions WHERE id = ? AND project_id = ?",
               (txn_id, project_id))
    db.commit()
    flash("Transaction deleted.")
    return redirect(url_for("project_detail", project_id=project_id, _anchor="billing"))


# --- Piece 27.3: 50/40/10 invoice generation -------------------------------
def _norm_county(name):
    """Normalise a county name for matching: drop a trailing 'County', lower."""
    n = (name or "").strip()
    if n.lower().endswith(" county"):
        n = n[:-7].strip()
    return n.lower()


def markup_map(db):
    """{equipment category (lower): markup percent} from the Cost Model's
    Equipment Inventory section (Piece 29.8)."""
    return {(r["item"] or "").strip().lower(): float(r["markup_pct"] or 0)
            for r in db.execute(
                "SELECT item, markup_pct FROM cost_model_lines"
                " WHERE section = 'Equipment Inventory' AND active = '1'").fetchall()}


def travel_rate(db):
    """Per-project travel $/mile — the Cost Model's Travel → Vehicle Trips line is
    the single source of truth (falls back to the stored meta rate)."""
    r = db.execute(
        "SELECT unit_cost FROM cost_model_lines WHERE section = 'Travel'"
        " AND item = 'Vehicle Trips' AND active = '1' LIMIT 1").fetchone()
    if r and r["unit_cost"] is not None:
        return float(r["unit_cost"] or 0)
    return _to_float(_meta_get(db, "travel_rate_per_mile",
                               str(TRAVEL_RATE_DEFAULT))) or 0.0


def cost_model_by_section(db):
    """Active cost-model lines grouped by section, in display order."""
    out = {s: [] for s in COST_MODEL_SECTIONS}
    for r in db.execute("SELECT * FROM cost_model_lines WHERE active = '1'"
                        " ORDER BY sort_order, id").fetchall():
        out.setdefault(r["section"], []).append(r)
    return out


def overhead_pct(db):
    """Total overhead (G&A) percent applied to the whole project subtotal."""
    return sum(float(r["markup_pct"] or 0) for r in db.execute(
        "SELECT markup_pct FROM cost_model_lines"
        " WHERE section = 'Overhead' AND active = '1'").fetchall())


def cost_model_rollup(db):
    """A default 'standard project' estimate straight from the model: each line is
    qty × cost × (1 + markup) for Non-Inventory / Labor / Travel / Adders, then
    G&A overhead on the subtotal (Piece 29.8). Equipment Inventory is excluded —
    it prices the actual per-project BOM, not a default quantity."""
    sections = cost_model_by_section(db)
    section_totals, subtotal = {}, 0.0
    for s in ["Equipment Non-Inventory", "Labor", "Travel", "Adders"]:
        st = 0.0
        for r in sections.get(s, []):
            qty = float(r["default_qty"] or 0)
            cost = float(r["unit_cost"] or 0)
            st += qty * cost * (1 + float(r["markup_pct"] or 0) / 100.0)
        section_totals[s] = round(st, 2)
        subtotal += st
    ov = overhead_pct(db)
    overhead_amt = round(subtotal * ov / 100.0, 2)
    return {"section_totals": section_totals, "subtotal": round(subtotal, 2),
            "overhead_pct": ov, "overhead_amount": overhead_amt,
            "total": round(subtotal + overhead_amt, 2)}


def _effective_markup(category, line_markup, mmap):
    """A BOM line's markup %: its own override if set, else the category default."""
    if line_markup not in (None, ""):
        v = _to_float(line_markup)
        if v is not None:
            return max(v, 0.0)
    return mmap.get((category or "").strip().lower(), 0.0)


def bom_pricing(db, project_id, mmap, after_id=None):
    """Cost and marked-up customer price for a project's BOM (optionally only rows
    added after `after_id`, for change-order extras). Per-line markup override
    wins over the category default."""
    sql = ("SELECT id, component_name, category, COALESCE(qty,0) AS qty,"
           " COALESCE(unit_cost,0) AS cost, markup_pct FROM project_bom"
           " WHERE project_id = ?")
    args = [project_id]
    if after_id is not None:
        sql += " AND id > ?"
        args.append(int(after_id or 0))
    sql += " ORDER BY id"
    lines, cost_total, price_total = [], 0.0, 0.0
    for r in db.execute(sql, args).fetchall():
        mk = _effective_markup(r["category"],
                               r["markup_pct"] if "markup_pct" in r.keys() else "",
                               mmap)
        line_cost = (r["qty"] or 0) * (r["cost"] or 0)
        line_price = line_cost * (1 + mk / 100.0)
        cost_total += line_cost
        price_total += line_price
        lines.append({"id": r["id"], "name": r["component_name"],
                      "category": r["category"], "qty": r["qty"],
                      "cost": r["cost"], "markup": mk,
                      "line_cost": round(line_cost, 2),
                      "line_price": round(line_price, 2)})
    return {"lines": lines, "cost_total": round(cost_total, 2),
            "price_total": round(price_total, 2)}


def project_travel_charge(db, project):
    miles = _to_float(project["travel_miles"] if "travel_miles" in project.keys() else 0) or 0.0
    return round(max(miles, 0.0) * travel_rate(db), 2), max(miles, 0.0)


def project_pricing(db, project):
    """Internal Finance breakdown for a project: equipment cost vs marked-up price,
    travel, a suggested contract price, and the contract Finance actually set."""
    mmap = markup_map(db)
    bom = bom_pricing(db, project["id"], mmap)
    est = estimate_pricing(db, project["id"])             # Piece 29.9: the project estimate
    subtotal = round(bom["price_total"] + est["total"], 2)
    ov = overhead_pct(db)                              # G&A on the whole subtotal
    overhead_amt = round(subtotal * ov / 100.0, 2)
    suggested = round(subtotal + overhead_amt, 2)
    contract = _to_float(project["contract_amount"] if "contract_amount" in project.keys()
                         else 0) or 0.0
    return {"equipment_cost": bom["cost_total"],
            "equipment_price": bom["price_total"],
            "markup_amount": round(bom["price_total"] - bom["cost_total"], 2),
            "estimate_by_section": est["by_section"],
            "estimate_total": est["total"], "estimate_lines": est["lines"],
            "subtotal": subtotal, "overhead_pct": ov, "overhead_amount": overhead_amt,
            "suggested": suggested, "contract": contract, "lines": bom["lines"]}


# Piece 29.9: the cost-model sections that make up a per-project estimate (Equipment
# Inventory is priced from the BOM; Overhead is applied on top, not entered).
ESTIMATE_SECTIONS = ["Equipment Non-Inventory", "Labor", "Travel", "Adders"]


def estimate_lines(db, project_id):
    return db.execute(
        "SELECT * FROM project_estimate_lines WHERE project_id = ?"
        " ORDER BY sort_order, id", (project_id,)).fetchall()


def estimate_pricing(db, project_id):
    """Per-section and total for a project's estimate lines: qty × cost × (1+markup)."""
    by_section = {s: 0.0 for s in ESTIMATE_SECTIONS}
    lines = []
    for r in estimate_lines(db, project_id):
        lt = (r["qty"] or 0) * (r["unit_cost"] or 0) * (1 + (r["markup_pct"] or 0) / 100.0)
        by_section[r["section"]] = by_section.get(r["section"], 0.0) + lt
        d = dict(r)
        d["line_total"] = round(lt, 2)
        lines.append(d)
    by_section = {k: round(v, 2) for k, v in by_section.items()}
    return {"by_section": by_section, "total": round(sum(by_section.values()), 2),
            "lines": lines}


def _workbag_redirect(anchor=None):
    """Piece 27.7: Work-Bag POSTs now come from a project's own page, so return
    there (using the form's project_id) instead of the landing. Falls back to the
    landing when no project is on the form."""
    jid = request.form.get("project_id", "")
    if jid.isdigit():
        return redirect(url_for("work_bag_job", project_id=int(jid), _anchor=anchor))
    return redirect(url_for("work_bag"))


@app.route("/work-bag/notes", methods=["POST"])
def add_project_note():
    """Piece 21.9: jot a free-form note about a project from the Work Bag. Each note
    keeps its own timestamp (datetime('now'), the same clock the audit log uses)
    and author, so the office can read the field's notes later."""
    user = current_user()
    if user is None:
        abort(403)
    db = get_db()
    project_id = request.form.get("project_id", "")
    note = request.form.get("note", "").strip()
    if not project_id.isdigit() or not note:
        flash("Pick a project and type a note.", "error")
        return _workbag_redirect(anchor="notes")
    db.execute("INSERT INTO project_notes (project_id, note, author) VALUES (?, ?, ?)",
               (int(project_id), note, user["name"]))
    db.commit()
    flash("Note saved for the office.")
    return _workbag_redirect(anchor="notes")


@app.route("/work-bag/receipt", methods=["POST"])
def add_receipt():
    """Piece 26.2: capture a receipt from the field — a photo plus date, total,
    vendor, reference, and expense category. Records a paid Expense/Receipt on the
    project's ledger (so it flows into bookkeeping) and files the photo against that
    transaction."""
    user = current_user()
    if user is None:
        abort(403)
    db = get_db()
    job_raw = request.form.get("project_id", "")
    if not job_raw.isdigit():
        flash("Pick a project for the receipt.", "error")
        return _workbag_redirect(anchor="receipts")
    project = db.execute(
        "SELECT id, job_name FROM projects WHERE id = ?",
        (int(job_raw),)).fetchone()
    if project is None:
        flash("That project wasn't found.", "error")
        return _workbag_redirect(anchor="receipts")
    upload = request.files.get("photo")
    if upload is None or not upload.filename:
        flash("Take or attach a photo of the receipt.", "error")
        return _workbag_redirect(anchor="receipts")
    ext = upload.filename.rsplit(".", 1)[-1].lower() if "." in upload.filename else ""
    if ext not in (PHOTO_EXTENSIONS | {"pdf"}):
        flash("Receipts should be a photo (JPG/PNG/HEIC) or a PDF.", "error")
        return _workbag_redirect(anchor="receipts")
    total = _to_float(request.form.get("total"))
    if not total:
        flash("Enter the receipt total.", "error")
        return _workbag_redirect(anchor="receipts")
    vendor = request.form.get("vendor", "").strip()
    reference = request.form.get("reference", "").strip()
    category = request.form.get("category", "").strip()
    date = request.form.get("date", "").strip() or datetime.now().strftime("%Y-%m-%d")
    project_id = project["id"]
    # 1) Ledger entry: a paid expense, tagged as a Receipt.
    cur = db.execute(
        "INSERT INTO project_transactions (project_id, kind, category, description, amount,"
        " txn_date, status, party, reference, method, doc_type, created_by)"
        " VALUES (?, 'Expense', ?, ?, ?, ?, 'Paid', ?, ?, '', 'Receipt', ?)",
        (project_id, category, (f"Receipt — {vendor}" if vendor else "Receipt"),
         total, date, vendor, reference, user["name"]))
    txn_id = cur.lastrowid
    # 2) File the photo against the project + that transaction (auto-renamed).
    friendly = friendly_filename(
        [project["job_name"], "Receipt", vendor], ext,
        taken=_taken_names(db, "project_files", "original_name", "project_id", project_id))
    stored = f"{uuid.uuid4().hex[:8]}_{secure_filename(friendly)}"
    upload.save(project_upload_dir(project_id) / stored)
    db.execute(
        "INSERT INTO project_files (project_id, rule_label, stored_name, original_name, txn_id)"
        " VALUES (?, 'Receipt', ?, ?, ?)", (project_id, stored, friendly, txn_id))
    db.commit()
    flash(f"Receipt saved: ${total:,.2f}{(' · ' + vendor) if vendor else ''}.")
    return _workbag_redirect(anchor="receipts")


@app.route("/work-bag/notes/<int:note_id>/delete", methods=["POST"])
def delete_project_note(note_id):
    """Remove a note — scoped to the author who wrote it."""
    user = current_user()
    if user is None:
        abort(403)
    db = get_db()
    db.execute("DELETE FROM project_notes WHERE id = ? AND author = ?",
               (note_id, user["name"]))
    db.commit()
    flash("Note removed.")
    return _workbag_redirect(anchor="notes")


@app.route("/projects/<int:project_id>/loads")
def project_loads(project_id):
    """Piece 15.1: Electric loads & system sizing — its own page (was a tab
    on the project detail page)."""
    project = fetch_project(project_id)
    db = get_db()
    rooms = db.execute(
        "SELECT * FROM project_load_rooms WHERE project_id = ? ORDER BY sort_order, id",
        (project_id,),
    ).fetchall()
    load_items = db.execute(
        "SELECT * FROM project_load_items WHERE project_id = ? ORDER BY id", (project_id,)
    ).fetchall()
    items_by_room = {}
    for it in load_items:
        items_by_room.setdefault(it["room_id"], []).append(it)
    sizing = fetch_job_sizing(db, project_id)
    bom = db.execute(
        "SELECT * FROM project_bom WHERE project_id = ? ORDER BY id", (project_id,)
    ).fetchall()
    appliances = db.execute(
        "SELECT * FROM appliance_catalog ORDER BY category, name"
    ).fetchall()
    components = db.execute(
        "SELECT * FROM component_catalog ORDER BY category, name"
    ).fetchall()
    appliances_by_category = {}
    for a in appliances:
        appliances_by_category.setdefault(a["category"] or "Other", []).append(a)
    # Piece 26.4: flat catalog (for the room-filtered picker + whole-catalog
    # search) and the list of room "types" to choose from.
    all_appliances = [
        {"id": a["id"], "name": a["name"], "category": a["category"] or "Other",
         "watts": int(a["avg_w"] or 0), "era": a["era"] or ""} for a in appliances]
    appliance_categories = sorted(appliances_by_category.keys())
    components_by_category = {}
    for c in components:
        components_by_category.setdefault(c["category"] or "Other", []).append(c)

    daily_kwh, peak_w = compute_load_totals(rooms, load_items)
    array_kw, panel_count = compute_array(
        daily_kwh, sizing["sun_hours"], sizing["derate_pct"],
        sizing["solar_fraction_pct"], sizing["panel_watts"],
    )
    battery_kwh_needed = compute_battery_kwh(
        sizing["backup_daily_kwh"], sizing["autonomy_days"], sizing["dod_pct"],
        sizing["round_trip_eff_pct"], sizing["inverter_eff_pct"],
    )
    selected_battery = None
    battery_units_needed = None
    if sizing["selected_battery_id"]:
        selected_battery = db.execute(
            "SELECT * FROM component_catalog WHERE id = ?",
            (sizing["selected_battery_id"],),
        ).fetchone()
        if selected_battery and selected_battery["capacity_kwh_nameplate"]:
            battery_units_needed = math.ceil(
                battery_kwh_needed / selected_battery["capacity_kwh_nameplate"]
            )
    selected_pv_module = None
    voc_corrected = max_modules = None
    if sizing["selected_pv_module_id"]:
        selected_pv_module = db.execute(
            "SELECT * FROM component_catalog WHERE id = ?",
            (sizing["selected_pv_module_id"],),
        ).fetchone()
        if selected_pv_module:
            voc_corrected, max_modules = compute_voc(
                selected_pv_module["voc"], selected_pv_module["temp_coef_voc"],
                sizing["record_low_temp_f"], sizing["max_input_v"],
            )
    bom_total = sum((b["qty"] or 0) * (b["unit_cost"] or 0) for b in bom)

    # Piece 26.5: once the load survey has produced sizing figures, read the
    # live inventory specs and auto-suggest the components that fit. Only
    # meaningful in Designer mode and once there's a real survey to size from.
    ui_mode = loads_view_mode(current_user())
    suggestions = []
    if ui_mode == "designer" and load_items and (array_kw or battery_kwh_needed or peak_w):
        suggestions = suggest_components(db, array_kw, peak_w, battery_kwh_needed)

    return render_template(
        "project_loads.html", project=project, locked=_loads_locked(project),
        rooms=rooms, items_by_room=items_by_room, sizing=sizing, bom=bom,
        bom_total=bom_total, appliances_by_category=appliances_by_category,
        components_by_category=components_by_category,
        component_categories=COMPONENT_CATEGORIES,
        # Piece 25.0: which room / load-item / BOM row is being edited in place.
        edit_room=request.args.get("edit_room", type=int),
        edit_item=request.args.get("edit_item", type=int),
        edit_bom=request.args.get("edit_bom", type=int),
        load_usage_types=LOAD_USAGE_TYPES, load_eras=LOAD_ERAS,
        ui_mode=ui_mode, suggestions=suggestions,
        all_appliances=all_appliances, appliance_categories=appliance_categories,
        daily_kwh=daily_kwh, peak_w=peak_w, array_kw=array_kw,
        panel_count=panel_count, battery_kwh_needed=battery_kwh_needed,
        selected_battery=selected_battery, battery_units_needed=battery_units_needed,
        selected_pv_module=selected_pv_module, voc_corrected=voc_corrected,
        max_modules=max_modules,
    )


def _float(val, default=0.0):
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


# ------------------------------------------------------------ loads & sizing
def _loads_locked(project):
    """Piece 22.2: Loads & Sizing is a Proposal-phase tool. Once the project
    advances past Proposal (the contract is signed), the editor locks — the
    recorded figures stay visible on the project and in Design, but no one re-opens
    the tool to change them. Lost projects (outside the normal stage order) are left
    editable in case one is revived."""
    status = project["status"] if "status" in project.keys() else ""
    return status in STAGE_ORDER and STAGE_ORDER.index(status) > 0


LOADS_LOCK_MSG = ("Loads & Sizing locks once the contract is signed — the "
                  "recorded figures are final and view-only from here.")


def loads_unlocked(view):
    """Guard a loads-editing POST: refuse the write once the project is past
    Proposal, so the locked figures can't be changed from anywhere."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if _loads_locked(fetch_project(kwargs["project_id"])):
            flash(LOADS_LOCK_MSG, "error")
            return redirect(url_for("project_loads", project_id=kwargs["project_id"]))
        return view(*args, **kwargs)
    return wrapped


@app.route("/projects/<int:project_id>/loads/rooms/add", methods=["POST"])
@loads_unlocked
def add_load_room(project_id):
    fetch_project(project_id)
    name = request.form.get("name", "").strip()
    room_type = request.form.get("room_type", "standard")
    if room_type not in ROOM_TYPES:
        room_type = "standard"
    if not name:
        flash("Room name is required.", "error")
        return redirect(url_for("project_loads", project_id=project_id))
    category = request.form.get("category", "").strip()
    db = get_db()
    next_order = db.execute(
        "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM project_load_rooms WHERE project_id = ?",
        (project_id,),
    ).fetchone()[0]
    db.execute(
        "INSERT INTO project_load_rooms (project_id, name, room_type, category, sort_order)"
        " VALUES (?, ?, ?, ?, ?)",
        (project_id, name, room_type, category, next_order),
    )
    db.commit()
    return redirect(url_for("project_loads", project_id=project_id))


@app.route("/projects/<int:project_id>/loads/rooms/<int:room_id>/toggle", methods=["POST"])
@loads_unlocked
def toggle_load_room(project_id, room_id):
    db = get_db()
    db.execute(
        "UPDATE project_load_rooms SET enabled = 1 - enabled WHERE id = ? AND project_id = ?",
        (room_id, project_id),
    )
    db.commit()
    return redirect(url_for("project_loads", project_id=project_id))


@app.route("/projects/<int:project_id>/loads/rooms/<int:room_id>/edit", methods=["POST"])
@loads_unlocked
def update_load_room(project_id, room_id):
    fetch_project(project_id)
    db = get_db()
    if db.execute("SELECT 1 FROM project_load_rooms WHERE id = ? AND project_id = ?",
                  (room_id, project_id)).fetchone() is None:
        abort(404)
    name = request.form.get("name", "").strip()
    if not name:
        flash("The room needs a name.", "error")
        return redirect(url_for("project_loads", project_id=project_id, edit_room=room_id))
    room_type = request.form.get("room_type", "standard").strip() or "standard"
    category = request.form.get("category", "").strip()
    db.execute("UPDATE project_load_rooms SET name = ?, room_type = ?, category = ?"
               " WHERE id = ?", (name, room_type, category, room_id))
    db.commit()
    flash("Room updated.")
    return redirect(url_for("project_loads", project_id=project_id))


@app.route("/projects/<int:project_id>/loads/rooms/<int:room_id>/delete", methods=["POST"])
@delete_required
@loads_unlocked
def delete_load_room(project_id, room_id):
    ok, msg = trash_item("load_room", room_id)
    flash(msg, "" if ok else "error")
    return redirect(url_for("project_loads", project_id=project_id))


@app.route("/projects/<int:project_id>/loads/items/add", methods=["POST"])
@loads_unlocked
def add_load_item(project_id):
    fetch_project(project_id)
    db = get_db()
    room_id = request.form.get("room_id", type=int)
    room = db.execute(
        "SELECT * FROM project_load_rooms WHERE id = ? AND project_id = ?", (room_id, project_id)
    ).fetchone()
    if not room:
        flash("Pick a room before adding an appliance.", "error")
        return redirect(url_for("project_loads", project_id=project_id))

    catalog_id = request.form.get("catalog_id", type=int)
    if catalog_id:
        appliance = db.execute(
            "SELECT * FROM appliance_catalog WHERE id = ?", (catalog_id,)
        ).fetchone()
        if not appliance:
            flash("Appliance not found in the catalog.", "error")
            return redirect(url_for("project_loads", project_id=project_id))
        name = appliance["name"]
        watts = appliance["avg_w"]
        hrs = appliance["hrs_per_day"]
        usage_type = appliance["usage_type"]
    else:
        name = request.form.get("custom_name", "").strip()
        watts = _float(request.form.get("custom_watts"))
        hrs = _float(request.form.get("custom_hrs"))
        usage_type = request.form.get("custom_usage_type", "").strip()
        if not name:
            flash("Give the custom appliance a name.", "error")
            return redirect(url_for("project_loads", project_id=project_id))

    qty = _float(request.form.get("qty"), 1) or 1
    # Allow overriding hrs/day from the form even for a catalog pick.
    hrs_override = request.form.get("hrs")
    if hrs_override not in (None, ""):
        hrs = _float(hrs_override, hrs)

    db.execute(
        "INSERT INTO project_load_items"
        " (project_id, room_id, appliance, watts, qty, hrs, usage_type)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (project_id, room_id, name, watts, qty, hrs, usage_type),
    )
    db.commit()
    return redirect(url_for("project_loads", project_id=project_id))


@app.route("/projects/<int:project_id>/loads/items/<int:item_id>/edit", methods=["POST"])
@loads_unlocked
def update_load_item(project_id, item_id):
    fetch_project(project_id)
    db = get_db()
    if db.execute("SELECT 1 FROM project_load_items WHERE id = ? AND project_id = ?",
                  (item_id, project_id)).fetchone() is None:
        abort(404)
    name = request.form.get("appliance", "").strip()
    if not name:
        flash("The appliance needs a name.", "error")
        return redirect(url_for("project_loads", project_id=project_id, edit_item=item_id))
    db.execute(
        "UPDATE project_load_items SET appliance = ?, watts = ?, qty = ?, hrs = ?,"
        " usage_type = ? WHERE id = ?",
        (name, _float(request.form.get("watts")),
         _float(request.form.get("qty"), 1) or 1, _float(request.form.get("hrs")),
         request.form.get("usage_type", "").strip(), item_id))
    db.commit()
    flash("Appliance updated.")
    return redirect(url_for("project_loads", project_id=project_id))


@app.route("/projects/<int:project_id>/loads/items/<int:item_id>/delete", methods=["POST"])
@delete_required
@loads_unlocked
def delete_load_item(project_id, item_id):
    ok, msg = trash_item("load_item", item_id)
    flash(msg, "" if ok else "error")
    return redirect(url_for("project_loads", project_id=project_id))


@app.route("/projects/<int:project_id>/loads/bom/add", methods=["POST"])
@loads_unlocked
def add_bom_item(project_id):
    fetch_project(project_id)
    db = get_db()
    component_id = request.form.get("component_id", type=int)
    qty = _float(request.form.get("qty"), 1) or 1
    notes = request.form.get("notes", "").strip()
    if component_id:
        comp = db.execute(
            "SELECT * FROM component_catalog WHERE id = ?", (component_id,)
        ).fetchone()
        if not comp:
            flash("Component not found in the catalog.", "error")
            return redirect(url_for("project_loads", project_id=project_id))
        # Adding the same component again increments quantity instead of
        # creating a duplicate row.
        existing = db.execute(
            "SELECT * FROM project_bom WHERE project_id = ? AND component_id = ?",
            (project_id, component_id),
        ).fetchone()
        if existing:
            db.execute("UPDATE project_bom SET qty = qty + ? WHERE id = ?",
                       (qty, existing["id"]))
        else:
            db.execute(
                "INSERT INTO project_bom"
                " (project_id, component_id, component_name, category, qty,"
                "  unit_cost, notes)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (project_id, component_id, comp["name"], comp["category"], qty,
                 comp["cost"], notes),
            )
    else:
        name = request.form.get("custom_name", "").strip()
        category = request.form.get("custom_category", "").strip()
        cost = request.form.get("custom_cost")
        if not name:
            flash("Give the custom component a name.", "error")
            return redirect(url_for("project_loads", project_id=project_id))
        db.execute(
            "INSERT INTO project_bom"
            " (project_id, component_id, component_name, category, qty,"
            "  unit_cost, notes)"
            " VALUES (?, NULL, ?, ?, ?, ?, ?)",
            (project_id, name, category, qty, _float(cost, None) if cost else None, notes),
        )
    db.commit()
    return redirect(url_for("project_loads", project_id=project_id))


@app.route("/projects/<int:project_id>/loads/bom/suggest", methods=["POST"])
@loads_unlocked
def accept_suggested_component(project_id):
    """Piece 26.5: one-click accept of an auto-suggested inventory component.
    Drops the picked item into the BOM at the sized quantity, at its inventory
    cost. Inventory items aren't catalog components, so component_id stays NULL;
    accepting the same item again tops up its quantity instead of duplicating."""
    fetch_project(project_id)
    db = get_db()
    name = request.form.get("name", "").strip()
    category = request.form.get("category", "").strip()
    qty = _float(request.form.get("qty"), 1) or 1
    cost = request.form.get("unit_cost")
    unit_cost = _float(cost, None) if cost not in (None, "") else None
    if not name:
        flash("Nothing to add.", "error")
        return redirect(url_for("project_loads", project_id=project_id))
    existing = db.execute(
        "SELECT id FROM project_bom WHERE project_id = ? AND component_id IS NULL"
        "   AND component_name = ? AND category = ?",
        (project_id, name, category)).fetchone()
    if existing:
        db.execute("UPDATE project_bom SET qty = ? WHERE id = ?", (qty, existing["id"]))
    else:
        db.execute(
            "INSERT INTO project_bom"
            " (project_id, component_id, component_name, category, qty, unit_cost, notes)"
            " VALUES (?, NULL, ?, ?, ?, ?, ?)",
            (project_id, name, category, qty, unit_cost, "Suggested from inventory"))
    db.commit()
    flash(f"Added {name} to the BOM.")
    return redirect(url_for("project_loads", project_id=project_id))


@app.route("/projects/<int:project_id>/loads/bom/<int:bom_id>/edit", methods=["POST"])
@loads_unlocked
def update_bom_item(project_id, bom_id):
    fetch_project(project_id)
    db = get_db()
    if db.execute("SELECT 1 FROM project_bom WHERE id = ? AND project_id = ?",
                  (bom_id, project_id)).fetchone() is None:
        abort(404)
    name = request.form.get("component_name", "").strip()
    if not name:
        flash("The component needs a name.", "error")
        return redirect(url_for("project_loads", project_id=project_id, edit_bom=bom_id))
    cost = request.form.get("unit_cost")
    # Piece 29.6: optional per-line markup override (blank = use category default).
    mk_raw = request.form.get("markup_pct", "")
    markup = "" if mk_raw.strip() == "" else str(max(_to_float(mk_raw) or 0.0, 0.0))
    db.execute(
        "UPDATE project_bom SET component_name = ?, category = ?, qty = ?,"
        " unit_cost = ?, notes = ?, markup_pct = ? WHERE id = ?",
        (name, request.form.get("category", "").strip(),
         _float(request.form.get("qty"), 1) or 1,
         _float(cost, None) if cost not in (None, "") else None,
         request.form.get("notes", "").strip(), markup, bom_id))
    db.commit()
    flash("Component updated.")
    return redirect(url_for("project_loads", project_id=project_id))


@app.route("/projects/<int:project_id>/loads/bom/<int:bom_id>/delete", methods=["POST"])
@delete_required
@loads_unlocked
def delete_bom_item(project_id, bom_id):
    ok, msg = trash_item("bom", bom_id)
    flash(msg, "" if ok else "error")
    return redirect(url_for("project_loads", project_id=project_id))


@app.route("/projects/<int:project_id>/loads/sizing", methods=["POST"])
@loads_unlocked
def update_sizing(project_id):
    fetch_project(project_id)
    db = get_db()
    fetch_job_sizing(db, project_id)  # ensure the row exists

    ui_mode = request.form.get("ui_mode", "designer")
    if ui_mode not in UI_MODES:
        ui_mode = "designer"
    system_type = request.form.get("system_type", "custom")
    if system_type not in ("offgrid", "gridtie", "custom"):
        system_type = "custom"

    derate_pct = _float(request.form.get("derate_pct"), 75)
    autonomy_days = _float(request.form.get("autonomy_days"), 2)
    # A preset system type overrides derate/autonomy with its fixed values,
    # mirroring the standalone tool's auto-fill-then-revert-on-edit behavior.
    if system_type in SYSTEM_TYPE_PRESETS:
        preset = SYSTEM_TYPE_PRESETS[system_type]
        derate_pct = preset["derate_pct"]
        autonomy_days = preset["autonomy_days"]

    selected_battery_id = request.form.get("selected_battery_id", type=int) or None
    selected_pv_module_id = request.form.get("selected_pv_module_id", type=int) or None

    db.execute(
        "UPDATE project_sizing SET ui_mode = ?, system_type = ?, sun_hours = ?,"
        " derate_pct = ?, autonomy_days = ?, solar_fraction_pct = ?,"
        " panel_watts = ?, dod_pct = ?, round_trip_eff_pct = ?,"
        " inverter_eff_pct = ?, max_input_v = ?, record_low_temp_f = ?,"
        " backup_daily_kwh = ?, selected_battery_id = ?, selected_pv_module_id = ?,"
        " updated_at = datetime('now')"
        " WHERE project_id = ?",
        (
            ui_mode, system_type,
            _float(request.form.get("sun_hours"), 5.5),
            derate_pct, autonomy_days,
            _float(request.form.get("solar_fraction_pct"), 100),
            _float(request.form.get("panel_watts"), 400),
            _float(request.form.get("dod_pct"), 80),
            _float(request.form.get("round_trip_eff_pct"), 92),
            _float(request.form.get("inverter_eff_pct"), 96),
            _float(request.form.get("max_input_v"), 600),
            _float(request.form.get("record_low_temp_f"), 5),
            _float(request.form.get("backup_daily_kwh"), 0),
            selected_battery_id, selected_pv_module_id, project_id,
        ),
    )
    db.commit()
    return redirect(url_for("project_loads", project_id=project_id))


@app.route("/projects/<int:project_id>/loads/mode", methods=["POST"])
def set_ui_mode(project_id):
    # Piece 26.4: the view mode is now a per-viewer session preference (the
    # default comes from their department), not a per-project stored value.
    ui_mode = request.form.get("ui_mode", "designer")
    session["loads_ui_mode"] = ui_mode if ui_mode in UI_MODES else "designer"
    return redirect(url_for("project_loads", project_id=project_id))


# ------------------------------------------------------------------ catalog
@app.route("/catalog")
def catalog_page():
    db = get_db()
    appliances = db.execute(
        "SELECT * FROM appliance_catalog ORDER BY category, name"
    ).fetchall()
    components = db.execute(
        "SELECT * FROM component_catalog ORDER BY category, name"
    ).fetchall()
    appliance_categories = sorted({a["category"] for a in appliances if a["category"]})
    # Piece 25.0: in-place edit — ?edit_appliance / ?edit_component pre-fills the
    # add form with that row so it can be saved back over the original.
    edit_appliance = edit_component = None
    if request.args.get("edit_appliance", type=int):
        edit_appliance = db.execute(
            "SELECT * FROM appliance_catalog WHERE id = ?",
            (request.args.get("edit_appliance", type=int),)).fetchone()
    if request.args.get("edit_component", type=int):
        edit_component = db.execute(
            "SELECT * FROM component_catalog WHERE id = ?",
            (request.args.get("edit_component", type=int),)).fetchone()
    return render_template(
        "catalog.html", appliances=appliances, components=components,
        appliance_categories=appliance_categories,
        component_categories=COMPONENT_CATEGORIES, load_eras=LOAD_ERAS,
        load_usage_types=LOAD_USAGE_TYPES,
        edit_appliance=edit_appliance, edit_component=edit_component,
    )


INVENTORY_CAT_ORDER = [
    "PV Module", "Inverter", "Battery", "Charge Controller", "Optimizer",
    "Generator", "Breaker", "Breaker Panel", "Controls", "Electrical", "Wire",
    "Monitoring", "Enclosure", "Pumping", "Racking",
]
# Piece 23.4: category -> spec fields that should always exist even when no
# seeded item carries them yet. FCC ID# is inverter-only and brand-new (blank
# for now, researched later), so it shows as a column and gets flagged.
INVENTORY_EXTRA_SPECS = {"Inverter": ["FCC ID#"]}


def inventory_category_specs():
    """Ordered spec-field names per category, unioned from the seed's category
    map (keyed by sheet) plus the always-present extras. Sheet 'PV' maps to the
    'PV Module' category value; others match their sheet name."""
    out = {}
    for sheet, fields in INVENTORY_CATEGORY_SPECS.items():
        cat = "PV Module" if sheet == "PV" else sheet
        out[cat] = list(fields)
    for cat, extra in INVENTORY_EXTRA_SPECS.items():
        out.setdefault(cat, [])
        for f in extra:
            if f not in out[cat]:
                out[cat].append(f)
    return out


# --- Stock ledger + stale-stock rule (Piece 24.4) ----------------------------
STALE_MONTHS = 6


def apply_stock_txn(db, item_id, kind, delta, project_id=None, note="", user_name=""):
    """Write one stock-ledger row and update the item's cached balance. `delta`
    is the signed change to `available` (received > 0, used < 0, count = target −
    current). A 'used' movement stamps last_used = today, which the stale-stock
    notice keys off. This is the single choke-point every stock change flows
    through — the later BOM auto-deduct will call it too."""
    db.execute(
        "INSERT INTO inventory_txns (item_id, kind, qty, project_id, note, created_by)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (item_id, kind, delta, project_id, note, user_name))
    db.execute("UPDATE inventory_items SET available = MAX(0, COALESCE(available, 0) + ?)"
               " WHERE id = ?", (delta, item_id))
    if kind == "used":
        db.execute("UPDATE inventory_items SET last_used = date('now') WHERE id = ?",
                   (item_id,))
    db.commit()


def stale_stock_items(db):
    """Items the stale-stock rule flags for the Designer: Active, zero on hand,
    and last actually used more than STALE_MONTHS ago — excluding any dismissed
    ('kept') within that window. Items never used aren't flagged yet (no usage
    history to judge; they surface once the ledger has real runway)."""
    win = f"-{STALE_MONTHS} months"
    # Piece 30.4: an item is stale if it was manually flagged (stale_flag), OR it
    # meets the automatic rule (zero on hand + unused 6+ months, not recently kept).
    return db.execute(
        "SELECT i.*, v.name AS vendor_name FROM inventory_items i"
        " LEFT JOIN inventory_vendors v ON v.id = i.vendor_id"
        " WHERE i.active = 1 AND i.status = 'Active' AND ("
        "   COALESCE(i.stale_flag, '') = '1'"
        "   OR (COALESCE(i.available, 0) <= 0"
        "       AND COALESCE(i.last_used, '') != '' AND date(i.last_used) <= date('now', ?)"
        "       AND (COALESCE(i.stock_reviewed_on, '') = ''"
        "            OR date(i.stock_reviewed_on) <= date('now', ?)))"
        " ) ORDER BY (COALESCE(i.stale_flag,'') = '1') DESC, i.last_used",
        (win, win)).fetchall()


@app.route("/inventory")
def inventory_page():
    """Piece 23.2: the inventory database — Vixinman's seeded stock of PV/electrical
    components (grouped by category, with per-category specs), plus the tool kit
    and the vehicle/heavy-equipment list. Feeds the Loads & Sizing calculator
    and (later) the designer → procurement auto-fill."""
    db = get_db()
    vendors = {v["id"]: v["name"]
               for v in db.execute("SELECT id, name FROM inventory_vendors").fetchall()}
    items = db.execute(
        "SELECT * FROM inventory_items WHERE active = 1"
        " ORDER BY category, make, model").fetchall()
    by_cat = {}
    for it in items:
        by_cat.setdefault(it["category"], []).append(it)
    cat_specs = inventory_category_specs()
    sections = []
    for cat in sorted(by_cat, key=lambda c: (INVENTORY_CAT_ORDER.index(c)
                      if c in INVENTORY_CAT_ORDER else 99, c)):
        rows = []
        # Start with the category's canonical spec order (so blank-but-expected
        # fields like the inverter FCC ID# still appear), then add any extras
        # seen on actual items.
        spec_order = list(cat_specs.get(cat, []))
        for it in by_cat[cat]:
            try:
                sp = json.loads(it["specs"] or "{}")
            except (ValueError, TypeError):
                sp = {}
            for k in sp:
                if k not in spec_order:
                    spec_order.append(k)
            d = dict(it)
            d["specs"] = sp
            d["vendor_name"] = vendors.get(it["vendor_id"], "")
            rows.append(d)
        sections.append({"category": cat, "specs": spec_order, "items": rows,
                         "count": len(rows)})
    tools = db.execute("SELECT t.*, v.name AS vendor_name FROM inventory_tools t"
                       " LEFT JOIN inventory_vendors v ON v.id = t.vendor_id"
                       " WHERE t.active = 1 ORDER BY t.category, t.name").fetchall()
    vehicles = db.execute("SELECT v.*, ve.name AS vendor_name FROM inventory_vehicles v"
                          " LEFT JOIN inventory_vendors ve ON ve.id = v.vendor_id"
                          " WHERE v.active = 1 ORDER BY v.category, v.name").fetchall()
    vendor_list = db.execute(
        "SELECT id, name FROM inventory_vendors ORDER BY name").fetchall()
    return render_template(
        "inventory.html", sections=sections, tools=tools, vehicles=vehicles,
        item_total=len(items), vendor_count=len(vendors),
        stale_count=len(stale_stock_items(db)),
        vendor_list=vendor_list, cat_specs=inventory_category_specs())


def _inventory_form_values():
    """Pull an inventory item's core fields + specs out of the POSTed form."""
    cat = request.form.get("category", "").strip()
    spec_fields = inventory_category_specs().get(cat, [])
    specs = {}
    for name in spec_fields:
        val = request.form.get(f"spec__{name}", "").strip()
        if val:
            num = _to_float(val)
            specs[name] = num if num is not None else val
    vid = request.form.get("vendor_id", "")
    return {
        "category": cat,
        "make": request.form.get("make", "").strip(),
        "model": request.form.get("model", "").strip(),
        "description": request.form.get("description", "").strip(),
        "vendor_id": int(vid) if vid.isdigit() else None,
        "vendor_number": request.form.get("vendor_number", "").strip(),
        "cost": _to_float(request.form.get("cost")),
        "purchase_url": request.form.get("purchase_url", "").strip(),
        "manual_url": request.form.get("manual_url", "").strip(),
        "needed": int(_to_float(request.form.get("needed")) or 0),
        "available": int(_to_float(request.form.get("available")) or 0),
        "on_po": int(_to_float(request.form.get("on_po")) or 0),
        "status": request.form.get("status", "Active").strip() or "Active",
        "flags": request.form.get("flags", "").strip(),
        "specs": json.dumps(specs, default=str),
    }


@app.route("/inventory/items/new", methods=["GET", "POST"])
@admin_required
def inventory_item_new():
    """Piece 23.4: add a new inventory item from inside the app (the per-category
    'New product' button preselects the category)."""
    db = get_db()
    if request.method == "POST":
        v = _inventory_form_values()
        if not v["category"] or not (v["make"] or v["model"]):
            flash("Category and a make or model are required.", "error")
            return redirect(url_for("inventory_item_new", category=v["category"]))
        db.execute(
            "INSERT INTO inventory_items (category, make, model, description,"
            " vendor_id, vendor_number, cost, purchase_url, manual_url, needed,"
            " available, on_po, status, flags, specs)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (v["category"], v["make"], v["model"], v["description"],
             v["vendor_id"], v["vendor_number"], v["cost"], v["purchase_url"],
             v["manual_url"], v["needed"], v["available"], v["on_po"],
             v["status"], v["flags"], v["specs"]))
        db.commit()
        flash(f"Added {v['make']} {v['model']}.".strip())
        return redirect(url_for("inventory_page", _anchor=v["category"]))
    category = request.args.get("category", "")
    return render_template(
        "inventory_item_form.html", item=None, category=category,
        spec_fields=inventory_category_specs().get(category, []),
        categories=INVENTORY_CAT_ORDER,
        vendor_list=db.execute("SELECT id, name FROM inventory_vendors"
                               " ORDER BY name").fetchall())


@app.route("/inventory/items/<int:item_id>/edit", methods=["GET", "POST"])
@admin_required
def inventory_item_edit(item_id):
    """Piece 23.4: update an existing inventory item in place."""
    db = get_db()
    row = db.execute("SELECT * FROM inventory_items WHERE id = ?",
                     (item_id,)).fetchone()
    if row is None:
        abort(404)
    if request.method == "POST":
        v = _inventory_form_values()
        db.execute(
            "UPDATE inventory_items SET category = ?, make = ?, model = ?,"
            " description = ?, vendor_id = ?, vendor_number = ?, cost = ?,"
            " purchase_url = ?, manual_url = ?, needed = ?, available = ?,"
            " on_po = ?, status = ?, flags = ?, specs = ? WHERE id = ?",
            (v["category"], v["make"], v["model"], v["description"],
             v["vendor_id"], v["vendor_number"], v["cost"], v["purchase_url"],
             v["manual_url"], v["needed"], v["available"], v["on_po"],
             v["status"], v["flags"], v["specs"], item_id))
        db.commit()
        flash("Item updated.")
        return redirect(url_for("inventory_page", _anchor=v["category"]))
    item = dict(row)
    try:
        item["specs"] = json.loads(row["specs"] or "{}")
    except (ValueError, TypeError):
        item["specs"] = {}
    txns = db.execute(
        "SELECT t.kind, t.qty, t.note, t.created_by, t.created_at, j.job_name"
        " FROM inventory_txns t LEFT JOIN projects j ON j.id = t.project_id"
        " WHERE t.item_id = ? ORDER BY t.id DESC LIMIT 10", (item_id,)).fetchall()
    projects = db.execute(
        "SELECT id, job_name FROM projects WHERE status != 'Abandoned'"
        " ORDER BY id DESC").fetchall()
    return render_template(
        "inventory_item_form.html", item=item, category=item["category"],
        spec_fields=inventory_category_specs().get(item["category"], []),
        categories=INVENTORY_CAT_ORDER, txns=txns, projects=projects,
        vendor_list=db.execute("SELECT id, name FROM inventory_vendors"
                               " ORDER BY name").fetchall())


@app.route("/inventory/items/<int:item_id>/delete", methods=["POST"])
@delete_required
def inventory_item_delete(item_id):
    """Send an inventory item to the trash (restorable, GM-only)."""
    ok, msg = trash_item("inventory_item", item_id)
    flash(msg, "" if ok else "error")
    return redirect(url_for("inventory_page"))


@app.route("/inventory/items/<int:item_id>/adjust", methods=["POST"])
@admin_required
def inventory_item_adjust(item_id):
    """Piece 24.4: record a stock movement (received / used / count correction)
    through the ledger. 'Used' can be tied to a project and stamps last_used."""
    db = get_db()
    row = db.execute("SELECT available FROM inventory_items WHERE id = ?",
                     (item_id,)).fetchone()
    if row is None:
        abort(404)
    kind = request.form.get("kind", "used")
    qty = int(_to_float(request.form.get("qty")) or 0)
    job_raw = request.form.get("project_id", "")
    project_id = int(job_raw) if job_raw.isdigit() else None
    note = request.form.get("note", "").strip()
    cur = row["available"] or 0
    if kind == "received":
        delta = abs(qty)
    elif kind == "used":
        delta = -abs(qty)
    elif kind == "count":
        delta = qty - cur          # qty is the counted on-hand total
    else:
        delta = qty
    if delta == 0 and kind != "count":
        flash("Enter a quantity to record.", "error")
        return redirect(url_for("inventory_item_edit", item_id=item_id))
    user = current_user()
    apply_stock_txn(db, item_id, kind, delta, project_id, note,
                    user["name"] if user else "")
    flash({"received": "Stock received.", "used": "Usage recorded.",
           "count": "Count updated."}.get(kind, "Stock adjusted."))
    return redirect(url_for("inventory_item_edit", item_id=item_id))


@app.route("/inventory/stale")
@admin_required
def inventory_stale():
    """Piece 24.4: the Designer's stale-stock review queue — zero on hand and
    unused for 6+ months. Keep active / Discontinue / Move to trash."""
    db = get_db()
    items = [dict(r) for r in stale_stock_items(db)]
    return render_template("inventory_stale.html", items=items, months=STALE_MONTHS)


@app.route("/inventory/stale/<int:item_id>/keep", methods=["POST"])
@admin_required
def inventory_stale_keep(item_id):
    """Dismiss a stale-stock flag: mark reviewed today (re-checks in 6 months)."""
    db = get_db()
    db.execute("UPDATE inventory_items SET stock_reviewed_on = date('now'),"
               " stale_flag = '' WHERE id = ?", (item_id,))   # clears a manual mark too
    db.commit()
    flash("Kept active — cleared the stale mark (auto re-checks in 6 months).")
    return redirect(url_for("inventory_stale"))


@app.route("/inventory/stale/<int:item_id>/discontinue", methods=["POST"])
@admin_required
def inventory_stale_discontinue(item_id):
    """Soft-retire a stale item: mark Discontinued (keeps the record)."""
    db = get_db()
    db.execute("UPDATE inventory_items SET status = 'Discontinued',"
               " stock_reviewed_on = date('now'), stale_flag = '' WHERE id = ?",
               (item_id,))
    db.commit()
    flash("Marked Discontinued.")
    return redirect(url_for("inventory_stale"))


@app.route("/inventory/<int:item_id>/toggle-stale", methods=["POST"])
@admin_required
def inventory_toggle_stale(item_id):
    """Piece 30.4: manually flag (or unflag) an inventory item as stale, from the
    inventory listing — independent of the automatic zero-on-hand/unused rule.
    Flagged items show a Stale badge and appear in the stale review queue."""
    db = get_db()
    row = db.execute("SELECT stale_flag, description, make, model FROM inventory_items"
                     " WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        abort(404)
    now_stale = (row["stale_flag"] or "") != "1"
    db.execute("UPDATE inventory_items SET stale_flag = ? WHERE id = ?",
               ("1" if now_stale else "", item_id))
    db.commit()
    name = row["description"] or (f"{row['make']} {row['model']}").strip() or "Item"
    flash(f"“{name}” marked stale." if now_stale else f"“{name}” is no longer stale.")
    return redirect(url_for("inventory_page"))


@app.route("/inventory/stale/<int:item_id>/trash", methods=["POST"])
@delete_required
def inventory_stale_trash(item_id):
    """Retire a stale item to the trash (restorable, GM-only)."""
    ok, msg = trash_item("inventory_item", item_id)
    flash(msg, "" if ok else "error")
    return redirect(url_for("inventory_stale"))


# --- Tools CRUD (Piece 24.3) -------------------------------------------------
def _tool_form_values():
    """Pull a tool's fields out of the POSTed form."""
    vid = request.form.get("vendor_id", "")
    return {
        "name": request.form.get("name", "").strip(),
        "category": request.form.get("category", "").strip(),
        "make": request.form.get("make", "").strip(),
        "model": request.form.get("model", "").strip(),
        "description": request.form.get("description", "").strip(),
        "vendor_id": int(vid) if vid.isdigit() else None,
        "cost": _to_float(request.form.get("cost")),
        "purchase_url": request.form.get("purchase_url", "").strip(),
        "manual_url": request.form.get("manual_url", "").strip(),
        "needed": int(_to_float(request.form.get("needed")) or 0),
        "available": int(_to_float(request.form.get("available")) or 0),
        "notes": request.form.get("notes", "").strip(),
    }


@app.route("/inventory/tools/new", methods=["GET", "POST"])
@admin_required
def inventory_tool_new():
    """Add a tool to the kit from inside the app."""
    db = get_db()
    if request.method == "POST":
        v = _tool_form_values()
        if not v["name"]:
            flash("A tool name is required.", "error")
            return redirect(url_for("inventory_tool_new"))
        db.execute(
            "INSERT INTO inventory_tools (name, category, make, model, description,"
            " vendor_id, cost, purchase_url, manual_url, needed, available, notes)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (v["name"], v["category"], v["make"], v["model"], v["description"],
             v["vendor_id"], v["cost"], v["purchase_url"], v["manual_url"],
             v["needed"], v["available"], v["notes"]))
        db.commit()
        flash(f"Added tool: {v['name']}.")
        return redirect(url_for("inventory_page", _anchor="tools"))
    return render_template(
        "inventory_tool_form.html", tool=None,
        vendor_list=db.execute("SELECT id, name FROM inventory_vendors"
                               " ORDER BY name").fetchall())


@app.route("/inventory/tools/<int:tool_id>/edit", methods=["GET", "POST"])
@admin_required
def inventory_tool_edit(tool_id):
    """Update a tool in place."""
    db = get_db()
    row = db.execute("SELECT * FROM inventory_tools WHERE id = ?", (tool_id,)).fetchone()
    if row is None:
        abort(404)
    if request.method == "POST":
        v = _tool_form_values()
        db.execute(
            "UPDATE inventory_tools SET name = ?, category = ?, make = ?, model = ?,"
            " description = ?, vendor_id = ?, cost = ?, purchase_url = ?,"
            " manual_url = ?, needed = ?, available = ?, notes = ? WHERE id = ?",
            (v["name"], v["category"], v["make"], v["model"], v["description"],
             v["vendor_id"], v["cost"], v["purchase_url"], v["manual_url"],
             v["needed"], v["available"], v["notes"], tool_id))
        db.commit()
        flash("Tool updated.")
        return redirect(url_for("inventory_page", _anchor="tools"))
    return render_template(
        "inventory_tool_form.html", tool=dict(row),
        vendor_list=db.execute("SELECT id, name FROM inventory_vendors"
                               " ORDER BY name").fetchall())


@app.route("/inventory/tools/<int:tool_id>/delete", methods=["POST"])
@delete_required
def inventory_tool_delete(tool_id):
    """Send a tool to the trash (restorable, GM-only)."""
    ok, msg = trash_item("inventory_tool", tool_id)
    flash(msg, "" if ok else "error")
    return redirect(url_for("inventory_page", _anchor="tools"))


# --- Vehicles CRUD (Piece 24.3) ----------------------------------------------
def _vehicle_form_values():
    """Pull a vehicle/heavy-equipment unit's fields out of the POSTed form."""
    vid = request.form.get("vendor_id", "")
    return {
        "name": request.form.get("name", "").strip(),
        "nickname": request.form.get("nickname", "").strip(),
        "category": request.form.get("category", "").strip(),
        "make": request.form.get("make", "").strip(),
        "model": request.form.get("model", "").strip(),
        "year": request.form.get("year", "").strip(),
        "description": request.form.get("description", "").strip(),
        "vendor_id": int(vid) if vid.isdigit() else None,
        "cost": _to_float(request.form.get("cost")),
        "purchase_url": request.form.get("purchase_url", "").strip(),
        "manual_url": request.form.get("manual_url", "").strip(),
        "notes": request.form.get("notes", "").strip(),
    }


@app.route("/inventory/vehicles/new", methods=["GET", "POST"])
@admin_required
def inventory_vehicle_new():
    """Add a vehicle / heavy-equipment unit."""
    db = get_db()
    if request.method == "POST":
        v = _vehicle_form_values()
        if not v["name"]:
            flash("A unit name is required.", "error")
            return redirect(url_for("inventory_vehicle_new"))
        db.execute(
            "INSERT INTO inventory_vehicles (name, nickname, category, make, model,"
            " year, description, vendor_id, cost, purchase_url, manual_url, notes)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (v["name"], v["nickname"], v["category"], v["make"], v["model"],
             v["year"], v["description"], v["vendor_id"], v["cost"],
             v["purchase_url"], v["manual_url"], v["notes"]))
        db.commit()
        flash(f"Added unit: {v['name']}.")
        return redirect(url_for("inventory_page", _anchor="vehicles"))
    return render_template(
        "inventory_vehicle_form.html", vehicle=None,
        vendor_list=db.execute("SELECT id, name FROM inventory_vendors"
                               " ORDER BY name").fetchall())


@app.route("/inventory/vehicles/<int:vehicle_id>/edit", methods=["GET", "POST"])
@admin_required
def inventory_vehicle_edit(vehicle_id):
    """Update a vehicle / heavy-equipment unit in place."""
    db = get_db()
    row = db.execute("SELECT * FROM inventory_vehicles WHERE id = ?",
                     (vehicle_id,)).fetchone()
    if row is None:
        abort(404)
    if request.method == "POST":
        v = _vehicle_form_values()
        db.execute(
            "UPDATE inventory_vehicles SET name = ?, nickname = ?, category = ?,"
            " make = ?, model = ?, year = ?, description = ?, vendor_id = ?,"
            " cost = ?, purchase_url = ?, manual_url = ?, notes = ? WHERE id = ?",
            (v["name"], v["nickname"], v["category"], v["make"], v["model"],
             v["year"], v["description"], v["vendor_id"], v["cost"],
             v["purchase_url"], v["manual_url"], v["notes"], vehicle_id))
        db.commit()
        flash("Unit updated.")
        return redirect(url_for("inventory_page", _anchor="vehicles"))
    return render_template(
        "inventory_vehicle_form.html", vehicle=dict(row),
        vendor_list=db.execute("SELECT id, name FROM inventory_vendors"
                               " ORDER BY name").fetchall())


@app.route("/inventory/vehicles/<int:vehicle_id>/delete", methods=["POST"])
@delete_required
def inventory_vehicle_delete(vehicle_id):
    """Send a vehicle / heavy-equipment unit to the trash (restorable, GM-only)."""
    ok, msg = trash_item("inventory_vehicle", vehicle_id)
    flash(msg, "" if ok else "error")
    return redirect(url_for("inventory_page", _anchor="vehicles"))


# ================= Piece 26.0: barcode / asset registry ======================
# Each asset is a printed, scannable label (unique serial) tied to an inventory
# entity. Consumables (components) decrement stock through the ledger when
# scanned out; non-consumables (tools / PPE / vehicles) toggle In stock ↔ Out.
ASSET_ENTITY_TABLES = {
    "inventory_item": ("inventory_items", "consumable"),
    "inventory_tool": ("inventory_tools", "non_consumable"),
    "inventory_vehicle": ("inventory_vehicles", "non_consumable"),
}


def _asset_entity_label(db, entity_type, entity_id):
    """Human description for an asset's linked inventory entity."""
    if entity_type == "inventory_item":
        r = db.execute("SELECT make, model, category FROM inventory_items"
                       " WHERE id = ?", (entity_id,)).fetchone()
        if r:
            return f"{r['make']} {r['model']}".strip() or r["category"] or "Item"
    elif entity_type == "inventory_tool":
        r = db.execute("SELECT name, make, model FROM inventory_tools"
                       " WHERE id = ?", (entity_id,)).fetchone()
        if r:
            return r["name"] or f"{r['make']} {r['model']}".strip() or "Tool"
    elif entity_type == "inventory_vehicle":
        r = db.execute("SELECT name, nickname FROM inventory_vehicles"
                       " WHERE id = ?", (entity_id,)).fetchone()
        if r:
            return r["name"] + (f" ({r['nickname']})" if r["nickname"] else "")
    return ""


def register_asset(db, entity_type, entity_id, user_name=""):
    """Mint one asset tag (insert, then set serial Vixinman-<id>). Returns its id."""
    cfg = ASSET_ENTITY_TABLES.get(entity_type)
    if not cfg:
        return None
    _table, kind = cfg
    if db.execute(f"SELECT 1 FROM {_table} WHERE id = ?", (entity_id,)).fetchone() is None:
        return None
    label = _asset_entity_label(db, entity_type, entity_id)
    cur = db.execute(
        "INSERT INTO inventory_assets (serial, kind, entity_type, entity_id,"
        " label, registered_by, last_action, last_action_by, last_action_at)"
        " VALUES ('', ?, ?, ?, ?, ?, 'Registered', ?, datetime('now'))",
        (kind, entity_type, entity_id, label, user_name, user_name))
    aid = cur.lastrowid
    db.execute("UPDATE inventory_assets SET serial = ? WHERE id = ?",
               (f"VXM-{aid:06d}", aid))
    return aid


def _asset_entity_choices(db):
    """(value, group, label) options for the register picker, value = 'type:id'."""
    out = []
    for it in db.execute("SELECT id, make, model, category FROM inventory_items"
                         " WHERE active = 1 ORDER BY category, make, model"):
        out.append((f"inventory_item:{it['id']}", "Components (consumable)",
                    f"{it['make']} {it['model']}".strip() or it["category"]))
    for t in db.execute("SELECT id, name FROM inventory_tools WHERE active = 1"
                        " ORDER BY category, name"):
        out.append((f"inventory_tool:{t['id']}", "Tools & PPE (non-consumable)",
                    t["name"]))
    for v in db.execute("SELECT id, name, nickname FROM inventory_vehicles"
                        " WHERE active = 1 ORDER BY name"):
        lbl = v["name"] + (f" ({v['nickname']})" if v["nickname"] else "")
        out.append((f"inventory_vehicle:{v['id']}", "Vehicles (non-consumable)", lbl))
    return out


@app.route("/inventory/assets")
@admin_required
def inventory_assets():
    """The barcode/asset registry: register tags, print labels, see what's out."""
    db = get_db()
    q = (request.args.get("q") or "").strip()
    status = request.args.get("status") or ""
    sql = ("SELECT a.*, j.job_name FROM inventory_assets a"
           " LEFT JOIN projects j ON j.id = a.project_id WHERE 1=1")
    params = []
    if q:
        sql += " AND (a.serial LIKE ? OR a.label LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]
    if status in ("In stock", "Out", "Retired"):
        sql += " AND a.status = ?"
        params.append(status)
    sql += " ORDER BY a.id DESC"
    assets = db.execute(sql, params).fetchall()
    out_count = db.execute("SELECT COUNT(*) FROM inventory_assets"
                           " WHERE status = 'Out'").fetchone()[0]
    return render_template(
        "inventory_assets.html", assets=assets, choices=_asset_entity_choices(db),
        q=q, status=status, out_count=out_count, total=len(assets))


@app.route("/inventory/assets/register", methods=["POST"])
@admin_required
def inventory_asset_register():
    db = get_db()
    entity = request.form.get("entity", "")
    qty = int(_to_float(request.form.get("qty")) or 1)
    qty = max(1, min(qty, 200))            # sane bound for a print run
    if ":" not in entity:
        flash("Pick something to tag.", "error")
        return redirect(url_for("inventory_assets"))
    entity_type, _, eid = entity.partition(":")
    if not eid.isdigit() or entity_type not in ASSET_ENTITY_TABLES:
        flash("That item can't be tagged.", "error")
        return redirect(url_for("inventory_assets"))
    # A consumable is one SKU label; non-consumables mint one tag per unit.
    if ASSET_ENTITY_TABLES[entity_type][1] == "consumable":
        qty = 1
    user = current_user()
    new_ids = []
    for _ in range(qty):
        aid = register_asset(db, entity_type, int(eid),
                             user["name"] if user else "")
        if aid:
            new_ids.append(aid)
    db.commit()
    if not new_ids:
        flash("Couldn't register that item.", "error")
        return redirect(url_for("inventory_assets"))
    flash(f"Registered {len(new_ids)} label(s). Print them below.")
    return redirect(url_for("inventory_asset_labels",
                            ids=",".join(str(i) for i in new_ids)))


def _load_assets(db, ids):
    ids = [int(i) for i in ids if str(i).isdigit()]
    if not ids:
        return []
    rows = db.execute(
        "SELECT * FROM inventory_assets WHERE id IN (%s)"
        % ",".join("?" * len(ids)), ids).fetchall()
    by_id = {r["id"]: r for r in rows}
    return [by_id[i] for i in ids if i in by_id]


@app.route("/inventory/assets/labels")
@admin_required
def inventory_asset_labels():
    """A print sheet of one or more labels (each with its Code 128 barcode)."""
    db = get_db()
    assets = _load_assets(db, (request.args.get("ids") or "").split(","))
    labels = [{"a": a, "svg": barcodes.code128b_svg(a["serial"])} for a in assets]
    return render_template("asset_labels.html", labels=labels)


def _resolve_serial(db, serial):
    serial = (serial or "").strip().upper()
    if not serial:
        return None
    return db.execute(
        "SELECT a.*, j.job_name FROM inventory_assets a"
        " LEFT JOIN projects j ON j.id = a.project_id WHERE UPPER(a.serial) = ?",
        (serial,)).fetchone()


@app.route("/inventory/scan")
def inventory_scan():
    """Scan (or type) a serial to check it in / out. Keyboard-wedge friendly."""
    db = get_db()
    code = request.args.get("code", "")
    asset = _resolve_serial(db, code) if code else None
    not_found = bool(code) and asset is None
    projects = db.execute(
        "SELECT id, job_name FROM projects"
        " WHERE status NOT IN ('Done', 'Abandoned') ORDER BY id DESC").fetchall()
    return render_template("inventory_scan.html", code=code, asset=asset,
                           not_found=not_found, projects=projects)


@app.route("/inventory/assets/<int:asset_id>/checkout", methods=["POST"])
def inventory_asset_checkout(asset_id):
    db = get_db()
    a = db.execute("SELECT * FROM inventory_assets WHERE id = ?",
                   (asset_id,)).fetchone()
    if a is None:
        abort(404)
    job_raw = request.form.get("project_id", "")
    project_id = int(job_raw) if job_raw.isdigit() else None
    user = current_user()
    who = user["name"] if user else ""
    if a["kind"] == "consumable":
        # Scanning a consumable out records a 'used' stock movement on its item.
        qty = int(_to_float(request.form.get("qty")) or 1)
        apply_stock_txn(db, a["entity_id"], "used", -abs(qty), project_id,
                        f"Scanned out ({a['serial']})", who)
        db.execute("UPDATE inventory_assets SET last_action = ?,"
                   " last_action_by = ?, last_action_at = datetime('now') WHERE id = ?",
                   (f"Issued {qty} to project", who, asset_id))
        db.commit()
        flash(f"Recorded {qty} × {a['label']} used" +
              (" on the project." if project_id else "."))
    else:
        db.execute("UPDATE inventory_assets SET status = 'Out', project_id = ?,"
                   " last_action = 'Checked out', last_action_by = ?,"
                   " last_action_at = datetime('now') WHERE id = ?",
                   (project_id, who, asset_id))
        db.commit()
        flash(f"{a['label']} checked out" + (" to the project." if project_id else "."))
    return redirect(url_for("inventory_scan"))


@app.route("/inventory/assets/<int:asset_id>/checkin", methods=["POST"])
def inventory_asset_checkin(asset_id):
    db = get_db()
    a = db.execute("SELECT * FROM inventory_assets WHERE id = ?",
                   (asset_id,)).fetchone()
    if a is None:
        abort(404)
    user = current_user()
    db.execute("UPDATE inventory_assets SET status = 'In stock', project_id = NULL,"
               " last_action = 'Checked in', last_action_by = ?,"
               " last_action_at = datetime('now') WHERE id = ?",
               (user["name"] if user else "", asset_id))
    db.commit()
    flash(f"{a['label']} checked back in.")
    return redirect(url_for("inventory_scan"))


@app.route("/inventory/assets/<int:asset_id>/retire", methods=["POST"])
@admin_required
def inventory_asset_retire(asset_id):
    db = get_db()
    a = db.execute("SELECT * FROM inventory_assets WHERE id = ?",
                   (asset_id,)).fetchone()
    if a is None:
        abort(404)
    user = current_user()
    db.execute("UPDATE inventory_assets SET status = 'Retired', project_id = NULL,"
               " last_action = 'Retired', last_action_by = ?,"
               " last_action_at = datetime('now') WHERE id = ?",
               (user["name"] if user else "", asset_id))
    db.commit()
    flash(f"Retired {a['serial']}.")
    return redirect(url_for("inventory_assets"))


# --- Piece 28.5: stock audits (scan the shelf, reconcile against the DB) ------
def _assets_with_category(db, rows):
    """Attach a scope 'category' to each asset row: a component's own category,
    or the broad type for tools / vehicles."""
    item_cat = {r["id"]: (r["category"] or "Uncategorized")
                for r in db.execute("SELECT id, category FROM inventory_items").fetchall()}
    out = []
    for a in rows:
        d = dict(a)
        et = a["entity_type"]
        d["category"] = (item_cat.get(a["entity_id"], "Uncategorized")
                         if et == "inventory_item"
                         else "Tools" if et == "inventory_tool"
                         else "Vehicles" if et == "inventory_vehicle" else "Other")
        out.append(d)
    return out


def audit_scope_categories(db):
    """The categories/types an audit can be scoped to (from registered assets)."""
    return sorted({a["category"] for a in _assets_with_category(
        db, db.execute("SELECT entity_type, entity_id FROM inventory_assets").fetchall())})


def _audit_in_scope(audit, category):
    return (audit["scope_kind"] or "all") == "all" or category == (audit["scope"] or "")


def audit_report(db, audit):
    """Reconcile an audit's scans against the assets the DB expects In stock in
    scope: what's accounted for, what's unaccounted (missing), what was scanned
    but shouldn't have been (Out/Retired or out of scope), unknown tags, and
    duplicate scans."""
    all_assets = _assets_with_category(
        db, db.execute("SELECT * FROM inventory_assets").fetchall())
    by_id = {a["id"]: a for a in all_assets}
    expected = [a for a in all_assets
                if a["status"] == "In stock" and _audit_in_scope(audit, a["category"])]
    expected_ids = {a["id"] for a in expected}
    scan_counts, scanned_ids, unknown = {}, set(), {}
    for s in db.execute("SELECT * FROM stock_audit_scans WHERE audit_id = ? ORDER BY id",
                        (audit["id"],)).fetchall():
        scan_counts[s["serial"]] = scan_counts.get(s["serial"], 0) + 1
        if s["asset_id"]:
            scanned_ids.add(s["asset_id"])
        else:
            unknown[s["serial"]] = unknown.get(s["serial"], 0) + 1
    accounted = [a for a in expected if a["id"] in scanned_ids]
    unaccounted = [a for a in expected if a["id"] not in scanned_ids]
    unexpected = []
    for aid in scanned_ids:
        a = by_id.get(aid)
        if a is None:
            continue
        if a["status"] != "In stock":
            unexpected.append({**a, "reason": f"system shows {a['status']}"})
        elif not _audit_in_scope(audit, a["category"]):
            unexpected.append({**a, "reason": f"outside this audit ({a['category']})"})
    return {
        "expected": expected, "accounted": accounted, "unaccounted": unaccounted,
        "unexpected": unexpected,
        "unknown": [{"serial": s, "count": n} for s, n in unknown.items()],
        "duplicates": [{"serial": s, "count": n} for s, n in scan_counts.items() if n > 1],
        "counts": {"expected": len(expected), "accounted": len(accounted),
                   "unaccounted": len(unaccounted), "unexpected": len(unexpected),
                   "unknown": len(unknown),
                   "duplicates": sum(1 for n in scan_counts.values() if n > 1),
                   "scans": sum(scan_counts.values())},
    }


@app.route("/inventory/audit")
@admin_required
def inventory_audit():
    """Stock-audit hub: past sessions + start a new one (all stock or by category)."""
    db = get_db()
    audits = db.execute(
        "SELECT a.*, (SELECT COUNT(*) FROM stock_audit_scans s WHERE s.audit_id = a.id)"
        " AS scans FROM stock_audits a ORDER BY a.id DESC LIMIT 50").fetchall()
    registered = db.execute("SELECT COUNT(*) FROM inventory_assets").fetchone()[0]
    return render_template("inventory_audit.html", audits=audits,
                           categories=audit_scope_categories(db), registered=registered)


@app.route("/inventory/audit/start", methods=["POST"])
@admin_required
def inventory_audit_start():
    db = get_db()
    scope = (request.form.get("scope") or "").strip()
    scope_kind = "category" if scope else "all"
    user = current_user()
    cur = db.execute(
        "INSERT INTO stock_audits (scope_kind, scope, started_by) VALUES (?, ?, ?)",
        (scope_kind, scope, user["name"] if user else ""))
    db.commit()
    return redirect(url_for("inventory_audit_session", audit_id=cur.lastrowid))


def _fetch_audit(db, audit_id):
    a = db.execute("SELECT * FROM stock_audits WHERE id = ?", (audit_id,)).fetchone()
    if a is None:
        abort(404)
    return a


@app.route("/inventory/audit/<int:audit_id>")
@admin_required
def inventory_audit_session(audit_id):
    db = get_db()
    audit = _fetch_audit(db, audit_id)
    rows = _assets_with_category(db, db.execute(
        "SELECT s.*, a.label, a.status AS asset_status, a.entity_type, a.entity_id"
        " FROM stock_audit_scans s LEFT JOIN inventory_assets a ON a.id = s.asset_id"
        " WHERE s.audit_id = ? ORDER BY s.id", (audit_id,)).fetchall())
    seen = set()
    for r in rows:
        if r["asset_id"] is None:
            r["flag"], r["reason"] = "unknown", "no matching tag"
        elif r["asset_id"] in seen:
            r["flag"], r["reason"] = "duplicate", "already scanned"
        else:
            seen.add(r["asset_id"])
            if r["asset_status"] != "In stock":
                r["flag"], r["reason"] = "should_be_out", f"system shows {r['asset_status']}"
            elif not _audit_in_scope(audit, r["category"]):
                r["flag"], r["reason"] = "out_of_scope", f"outside this audit ({r['category']})"
            else:
                r["flag"], r["reason"] = "ok", r["category"]
    scans = list(reversed(rows))
    return render_template("inventory_audit_session.html", audit=audit, scans=scans,
                           report=audit_report(db, audit))


@app.route("/inventory/audit/<int:audit_id>/scan", methods=["POST"])
@admin_required
def inventory_audit_scan(audit_id):
    """Record one scan (AJAX). Resolves the serial, logs it, and returns how it
    reconciles so the session page can flag it live."""
    db = get_db()
    audit = _fetch_audit(db, audit_id)
    if audit["status"] != "Open":
        return jsonify({"error": "This audit is closed."}), 400
    serial = (request.form.get("serial") or "").strip().upper()
    if not serial:
        return jsonify({"error": "empty"}), 400
    asset = _resolve_serial(db, serial)
    user = current_user()
    cur = db.execute(
        "INSERT INTO stock_audit_scans (audit_id, serial, asset_id, scanned_by)"
        " VALUES (?, ?, ?, ?)",
        (audit_id, serial, asset["id"] if asset else None,
         user["name"] if user else ""))
    new_id = cur.lastrowid
    if asset is None:
        flag, label, reason = "unknown", "", "no tag with this serial"
    else:
        cat = _assets_with_category(db, [asset])[0]["category"]
        prior = db.execute(
            "SELECT COUNT(*) AS c FROM stock_audit_scans WHERE audit_id = ?"
            " AND asset_id = ? AND id <> ?", (audit_id, asset["id"], new_id)).fetchone()["c"]
        label = asset["label"] or asset["serial"]
        if prior:
            flag, reason = "duplicate", "already scanned in this audit"
        elif asset["status"] != "In stock":
            flag, reason = "should_be_out", f"system shows {asset['status']}"
        elif not _audit_in_scope(audit, cat):
            flag, reason = "out_of_scope", f"outside this audit ({cat})"
        else:
            flag, reason = "ok", cat
    db.commit()
    c = audit_report(db, audit)["counts"]
    return jsonify({"scan_id": new_id, "serial": serial, "label": label,
                    "flag": flag, "reason": reason,
                    "accounted": c["accounted"], "expected": c["expected"],
                    "unknown": c["unknown"], "duplicates": c["duplicates"]})


@app.route("/inventory/audit/<int:audit_id>/scan/<int:scan_id>/delete", methods=["POST"])
@admin_required
def inventory_audit_scan_delete(audit_id, scan_id):
    db = get_db()
    _fetch_audit(db, audit_id)
    db.execute("DELETE FROM stock_audit_scans WHERE id = ? AND audit_id = ?",
               (scan_id, audit_id))
    db.commit()
    return redirect(url_for("inventory_audit_session", audit_id=audit_id))


@app.route("/inventory/audit/<int:audit_id>/finish", methods=["POST"])
@admin_required
def inventory_audit_finish(audit_id):
    db = get_db()
    _fetch_audit(db, audit_id)
    db.execute("UPDATE stock_audits SET status = 'Closed', closed_at = datetime('now')"
               " WHERE id = ? AND status = 'Open'", (audit_id,))
    db.commit()
    return redirect(url_for("inventory_audit_report", audit_id=audit_id))


@app.route("/inventory/audit/<int:audit_id>/report")
@admin_required
def inventory_audit_report(audit_id):
    db = get_db()
    audit = _fetch_audit(db, audit_id)
    return render_template("inventory_audit_report.html", audit=audit,
                           report=audit_report(db, audit))


@app.route("/inventory/audit/<int:audit_id>/report.csv")
@admin_required
def inventory_audit_report_csv(audit_id):
    import csv
    import io
    db = get_db()
    audit = _fetch_audit(db, audit_id)
    r = audit_report(db, audit)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Result", "Serial", "Item", "Category", "System status", "Note"])
    for a in r["accounted"]:
        w.writerow(["Accounted for", a["serial"], a["label"], a["category"], a["status"], ""])
    for a in r["unaccounted"]:
        w.writerow(["UNACCOUNTED (not found)", a["serial"], a["label"], a["category"],
                    a["status"], "expected In stock but not scanned"])
    for a in r["unexpected"]:
        w.writerow(["Unexpected (found)", a["serial"], a["label"], a["category"],
                    a["status"], a.get("reason", "")])
    for u in r["unknown"]:
        w.writerow(["Unknown tag", u["serial"], "", "", "", f"scanned {u['count']}×, no matching asset"])
    for d in r["duplicates"]:
        w.writerow(["Duplicate scan", d["serial"], "", "", "", f"scanned {d['count']}×"])
    scope = audit["scope"] if audit["scope"] else "all-stock"
    return Response(buf.getvalue(), mimetype="text/csv", headers={
        "Content-Disposition": f"attachment; filename=stock_audit_{audit_id}_{_slug(scope)}.csv"})


@app.route("/inventory/load")
def inventory_load():
    """Piece 26.1: rapid truck-loading. A crew picks the project once, then scans
    tags with the phone camera (or a scanner) to load them out — open to any
    signed-in worker so two Installers can load the same project in parallel."""
    db = get_db()
    project_id = request.args.get("project_id", type=int)
    projects = db.execute(
        "SELECT id, job_name FROM projects"
        " WHERE status NOT IN ('Done', 'Abandoned') ORDER BY id DESC").fetchall()
    project = None
    if project_id:
        project = db.execute("SELECT id, job_name FROM projects WHERE id = ?",
                         (project_id,)).fetchone()
    return render_template("inventory_load.html", projects=projects, project=project)


@app.route("/api/inventory/scan-out", methods=["POST"])
def api_scan_out():
    """JSON check-out for the continuous-scan loading flow. Non-consumables go
    Out (to the project); consumables record a 'used' stock movement. Open to any
    signed-in worker (crews load their own trucks)."""
    user = current_user()
    if user is None:
        return jsonify({"ok": False, "error": "Please sign in."}), 401
    db = get_db()
    data = request.get_json(silent=True) or request.form
    serial = (data.get("serial") or "").strip()
    job_raw = str(data.get("project_id") or "")
    project_id = int(job_raw) if job_raw.isdigit() else None
    qty = int(_to_float(data.get("qty")) or 1) or 1
    a = _resolve_serial(db, serial)
    if a is None:
        return jsonify({"ok": False, "error": f"Unknown tag {serial}"})
    if a["status"] == "Retired":
        return jsonify({"ok": False, "label": a["label"],
                        "error": f"{a['label']} is retired"})
    who = user["name"]
    if a["kind"] == "consumable":
        apply_stock_txn(db, a["entity_id"], "used", -abs(qty), project_id,
                        f"Loaded ({a['serial']})", who)
        db.execute("UPDATE inventory_assets SET last_action = ?,"
                   " last_action_by = ?, last_action_at = datetime('now') WHERE id = ?",
                   (f"Loaded {qty} to project", who, a["id"]))
        db.commit()
        return jsonify({"ok": True, "label": a["label"], "serial": a["serial"],
                        "action": f"loaded ×{qty}"})
    if a["status"] == "Out":
        return jsonify({"ok": True, "warn": True, "label": a["label"],
                        "serial": a["serial"], "action": "already out"})
    db.execute("UPDATE inventory_assets SET status = 'Out', project_id = ?,"
               " last_action = 'Loaded', last_action_by = ?,"
               " last_action_at = datetime('now') WHERE id = ?",
               (project_id, who, a["id"]))
    db.commit()
    return jsonify({"ok": True, "label": a["label"], "serial": a["serial"],
                    "action": "loaded"})


@app.route("/catalog/appliances/add", methods=["POST"])
@admin_required
def add_appliance_catalog():
    name = request.form.get("name", "").strip()
    if not name:
        flash("Appliance name is required.", "error")
        return redirect(url_for("catalog_page"))
    db = get_db()
    db.execute(
        "INSERT INTO appliance_catalog"
        " (name, category, era, low_w, high_w, avg_w, hrs_per_day, usage_type, notes)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            name, request.form.get("category", "").strip(),
            request.form.get("era", "").strip(),
            _float(request.form.get("low_w"), 0),
            _float(request.form.get("high_w"), 0),
            _float(request.form.get("avg_w"), 0),
            _float(request.form.get("hrs_per_day"), 0),
            request.form.get("usage_type", "").strip(),
            request.form.get("notes", "").strip(),
        ),
    )
    db.commit()
    flash(f"Added {name} to the appliance catalog.")
    return redirect(url_for("catalog_page"))


@app.route("/catalog/appliances/<int:appliance_id>/edit", methods=["POST"])
@admin_required
def update_appliance_catalog(appliance_id):
    name = request.form.get("name", "").strip()
    db = get_db()
    if db.execute("SELECT 1 FROM appliance_catalog WHERE id = ?",
                  (appliance_id,)).fetchone() is None:
        abort(404)
    if not name:
        flash("Appliance name is required.", "error")
        return redirect(url_for("catalog_page", edit_appliance=appliance_id,
                                _anchor="appliances"))
    db.execute(
        "UPDATE appliance_catalog SET name = ?, category = ?, era = ?, low_w = ?,"
        " high_w = ?, avg_w = ?, hrs_per_day = ?, usage_type = ?, notes = ?"
        " WHERE id = ?",
        (name, request.form.get("category", "").strip(),
         request.form.get("era", "").strip(),
         _float(request.form.get("low_w"), 0), _float(request.form.get("high_w"), 0),
         _float(request.form.get("avg_w"), 0),
         _float(request.form.get("hrs_per_day"), 0),
         request.form.get("usage_type", "").strip(),
         request.form.get("notes", "").strip(), appliance_id))
    db.commit()
    flash(f"Updated {name}.")
    return redirect(url_for("catalog_page", _anchor="appliances"))


@app.route("/catalog/appliances/<int:appliance_id>/delete", methods=["POST"])
@delete_required
def delete_appliance_catalog(appliance_id):
    ok, msg = trash_item("appliance", appliance_id)
    flash(msg, "" if ok else "error")
    return redirect(url_for("catalog_page"))


@app.route("/catalog/components/add", methods=["POST"])
@admin_required
def add_component_catalog():
    name = request.form.get("name", "").strip()
    if not name:
        flash("Component name is required.", "error")
        return redirect(url_for("catalog_page"))

    def opt_float(field):
        val = request.form.get(field)
        return _float(val, None) if val not in (None, "") else None

    db = get_db()
    db.execute(
        "INSERT INTO component_catalog"
        " (name, category, manufacturer, model, specs, watts, voc, vmp,"
        "  temp_coef_voc, capacity_kwh_nameplate, dod, max_input_v,"
        "  continuous_w, inverter_eff, cost, notes)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            name, request.form.get("category", "").strip(),
            request.form.get("manufacturer", "").strip(),
            request.form.get("model", "").strip(),
            request.form.get("specs", "").strip(),
            opt_float("watts"), opt_float("voc"), opt_float("vmp"),
            opt_float("temp_coef_voc"), opt_float("capacity_kwh_nameplate"),
            opt_float("dod"), opt_float("max_input_v"), opt_float("continuous_w"),
            opt_float("inverter_eff"), opt_float("cost"),
            request.form.get("notes", "").strip(),
        ),
    )
    db.commit()
    flash(f"Added {name} to the component catalog.")
    return redirect(url_for("catalog_page"))


@app.route("/catalog/components/<int:component_id>/edit", methods=["POST"])
@admin_required
def update_component_catalog(component_id):
    name = request.form.get("name", "").strip()
    db = get_db()
    if db.execute("SELECT 1 FROM component_catalog WHERE id = ?",
                  (component_id,)).fetchone() is None:
        abort(404)
    if not name:
        flash("Component name is required.", "error")
        return redirect(url_for("catalog_page", edit_component=component_id,
                                _anchor="components"))

    def opt_float(field):
        val = request.form.get(field)
        return _float(val, None) if val not in (None, "") else None

    db.execute(
        "UPDATE component_catalog SET name = ?, category = ?, manufacturer = ?,"
        " model = ?, specs = ?, watts = ?, voc = ?, vmp = ?, temp_coef_voc = ?,"
        " capacity_kwh_nameplate = ?, dod = ?, max_input_v = ?, continuous_w = ?,"
        " inverter_eff = ?, cost = ?, notes = ? WHERE id = ?",
        (name, request.form.get("category", "").strip(),
         request.form.get("manufacturer", "").strip(),
         request.form.get("model", "").strip(),
         request.form.get("specs", "").strip(),
         opt_float("watts"), opt_float("voc"), opt_float("vmp"),
         opt_float("temp_coef_voc"), opt_float("capacity_kwh_nameplate"),
         opt_float("dod"), opt_float("max_input_v"), opt_float("continuous_w"),
         opt_float("inverter_eff"), opt_float("cost"),
         request.form.get("notes", "").strip(), component_id))
    db.commit()
    flash(f"Updated {name}.")
    return redirect(url_for("catalog_page", _anchor="components"))


@app.route("/catalog/components/<int:component_id>/delete", methods=["POST"])
@delete_required
def delete_component_catalog(component_id):
    # Piece 17.1: blocked (with an error) if the component is still used by any
    # project BOM line or sizing selection; otherwise it goes to the trash.
    ok, msg = trash_item("component", component_id)
    flash(msg, "" if ok else "error")
    return redirect(url_for("catalog_page"))


@app.route("/projects/<int:project_id>/status", methods=["POST"])
def set_project_status(project_id):
    project = fetch_project(project_id)
    status = request.form.get("status", "")
    if status == "Abandoned":
        # Piece 30.2: cancelling goes through the reason flow, never the plain
        # stage dropdown.
        flash("Use “Cancel project” to mark a project Abandoned (a reason is required).", "error")
        return redirect(url_for("project_detail", project_id=project_id))
    if status in PROJECT_STATUSES:
        db = get_db()
        # Flexible guardrail: if advancing to the next stage before the current
        # one is complete, allow it but note what was still pending.
        cur = project["status"] or DEFAULT_PROJECT_STATUS
        warn = ""
        if status == next_stage(cur):
            rules = db.execute("SELECT * FROM resource_rules").fetchall()
            groups = group_rules(match_rules(project, rules))
            filed = {f["rule_label"] for f in db.execute(
                "SELECT rule_label FROM project_files WHERE project_id = ?", (project_id,))
                if f["rule_label"]}
            info = stage_info(db, project, groups, filed)
            if not info["ready"]:
                warn = " · ".join(info["pending"])
        db.execute("UPDATE projects SET status = ? WHERE id = ?", (status, project_id))
        # Piece 29.4: on a forward turnover, alert the stage's department(s).
        moved_forward = (status != cur and status in STAGE_ORDER
                         and (cur not in STAGE_ORDER
                              or STAGE_ORDER.index(status) > STAGE_ORDER.index(cur)))
        gen_added = 0
        if moved_forward:
            actor = current_user()
            notify_stage_turnover(db, project, status,
                                  exclude_id=actor["id"] if actor else None)
            # Piece 31.5: auto-fill and assign the tasks the project just moved into,
            # so the receiving department lands with its to-dos already populated.
            # Only the entered stage's steps are generated (role-assigned, dated);
            # existing tasks are skipped, so this never duplicates the manual
            # "Generate tasks" button. Done has no work of its own.
            if status != "Done":
                job_row = fetch_project(project_id)  # re-read so scheduling sees new status
                install_raw = (job_row["install_date"]
                               if "install_date" in job_row.keys() else "") or ""
                gen_added, _a, _s = _generate_project_tasks(
                    db, job_row, install_raw, only_status=status)
        db.commit()
        if warn:
            flash(f"Advanced to {status} with {cur} still pending: {warn}.", "error")
        if gen_added:
            flash(f"Auto-added {gen_added} {status} task"
                  f"{'s' if gen_added != 1 else ''}, assigned by role where possible.")
    return redirect(url_for("project_detail", project_id=project_id))


@app.route("/projects/<int:project_id>/cancel", methods=["POST"])
def cancel_project(project_id):
    """Piece 30.2: cancel a project — mark it Abandoned with a required reason
    (captured in the audit log), remembering the current stage so it can be
    reopened. The project's open tasks stop showing in My Tasks / the board /
    Work Bag while it's Abandoned, but nothing is deleted."""
    project = fetch_project(project_id)
    reason = request.form.get("reason", "").strip()
    if not reason:
        flash("A reason is required to cancel a project.", "error")
        return redirect(url_for("project_detail", project_id=project_id))
    if (project["status"] or "") == "Abandoned":
        flash("This project is already cancelled.")
        return redirect(url_for("project_detail", project_id=project_id))
    db = get_db()
    who = current_user()
    db.execute(
        "UPDATE projects SET pre_lost_status = ?, status = 'Abandoned', cancel_reason = ?,"
        " cancelled_at = ?, cancelled_by = ? WHERE id = ?",
        (project["status"] or DEFAULT_PROJECT_STATUS, reason,
         datetime.now().isoformat(timespec="seconds"),
         who["name"] if who else "", project_id))
    # Piece 30.3: tell everyone who was involved in the project up to this point.
    recipients = project_involved_ids(db, project, exclude_id=who["id"] if who else None)
    if recipients:
        jobname = project["job_name"] or f"Project #{project['id']}"
        notify_employees(
            db, recipients,
            f"🚫 {jobname} was cancelled (Abandoned). Reason: “{reason}”.",
            link=url_for("project_detail", project_id=project["id"]), kind="job_cancelled")
    db.commit()
    flash(f"Project cancelled (Abandoned). Reason recorded: “{reason}”."
          + (f" {len(recipients)} team member(s) notified." if recipients else ""))
    return redirect(url_for("project_detail", project_id=project_id))


@app.route("/projects/<int:project_id>/reopen", methods=["POST"])
def reopen_project(project_id):
    """Piece 30.2: reopen a cancelled project — restore the stage it was at before
    it was marked Abandoned (its tasks reappear) and clear the cancellation
    info."""
    project = fetch_project(project_id)
    if (project["status"] or "") != "Abandoned":
        flash("Only a cancelled (Abandoned) project can be reopened.", "error")
        return redirect(url_for("project_detail", project_id=project_id))
    prev = (project["pre_lost_status"] if "pre_lost_status" in project.keys() else "") or ""
    restore = prev if prev in STAGE_ORDER else DEFAULT_PROJECT_STATUS
    db = get_db()
    db.execute(
        "UPDATE projects SET status = ?, cancel_reason = '', cancelled_at = '',"
        " cancelled_by = '', pre_lost_status = '' WHERE id = ?", (restore, project_id))
    db.commit()
    flash(f"Project reopened at {restore}.")
    return redirect(url_for("project_detail", project_id=project_id))


@app.route("/closed-jobs")
@admin_required
def closed_jobs_page():
    """Piece 30.3: management review of closed projects — cancelled (Abandoned)
    projects with their reason and a reopen action, plus completed projects — the way
    cold leads are reviewed. Gated to Admin / GM."""
    db = get_db()
    cancelled = db.execute(
        "SELECT * FROM projects WHERE status = 'Abandoned'"
        " ORDER BY (cancelled_at = ''), cancelled_at DESC, id DESC").fetchall()
    completed = db.execute(
        "SELECT * FROM projects WHERE status = 'Done'"
        " ORDER BY id DESC").fetchall()
    return render_template("closed_jobs.html", cancelled=cancelled,
                           completed=completed)


@app.route("/projects")
def projects_list():
    """Piece 34: browse every active project — there's been no way to see them
    all in one place since the client→project-list path went away with the
    clients table (Piece 33)."""
    db = get_db()
    projects = db.execute(
        "SELECT id, job_name, status, install_date FROM projects"
        " ORDER BY (status = 'Done'), (status = 'Abandoned'), id DESC").fetchall()
    return render_template("projects_list.html", projects=projects,
                           job_status_class=PROJECT_STATUS_CLASS)


@app.route("/projects/<int:project_id>/install-date", methods=["POST"])
def set_install_date(project_id):
    """Set the project's install date; in Prep, advancing it to In Progress once
    all permits are filed (Piece 18 — the install-date setter triggers the
    hand-off)."""
    project = fetch_project(project_id)
    db = get_db()
    date = request.form.get("install_date", "").strip()
    db.execute("UPDATE projects SET install_date = ? WHERE id = ?", (date, project_id))
    advanced = False
    if date and (project["status"] or DEFAULT_PROJECT_STATUS) == "Prep":
        rules = db.execute("SELECT * FROM resource_rules").fetchall()
        groups = group_rules(match_rules(project, rules))
        filed = {f["rule_label"] for f in db.execute(
            "SELECT rule_label FROM project_files WHERE project_id = ?", (project_id,))
            if f["rule_label"]}
        if stage_info(db, project, groups, filed)["permits_ok"]:
            db.execute("UPDATE projects SET status = 'In Progress' WHERE id = ?", (project_id,))
            advanced = True
            actor = current_user()  # Piece 29.4: alert the Installation team
            notify_stage_turnover(db, project, "In Progress",
                                  exclude_id=actor["id"] if actor else None)
    db.commit()
    if advanced:
        flash("Install date set and all permits filed — advanced to In Progress.")
    elif date:
        flash("Install date saved. Prep stays open until all permits are filed.")
    else:
        flash("Install date cleared.")
    return redirect(url_for("project_detail", project_id=project_id))


# ---------------------------------------------------------------- materials
@app.route("/projects/<int:project_id>/materials/add", methods=["POST"])
def add_material(project_id):
    fetch_project(project_id)
    item = request.form.get("item", "").strip()
    if not item:
        flash("Material item name is required.", "error")
        return redirect(url_for("project_detail", project_id=project_id, _anchor="materials"))
    db = get_db()
    db.execute(
        "INSERT INTO project_materials (project_id, item, quantity, unit, supplier, notes)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (project_id, item,
         request.form.get("quantity", "").strip(),
         request.form.get("unit", "").strip(),
         request.form.get("supplier", "").strip(),
         request.form.get("notes", "").strip()),
    )
    db.commit()
    return redirect(url_for("project_detail", project_id=project_id, _anchor="materials"))


@app.route("/projects/<int:project_id>/materials/<int:material_id>/status", methods=["POST"])
def update_material_status(project_id, material_id):
    status = request.form.get("status", "")
    if status in MATERIAL_STATUSES:
        db = get_db()
        db.execute(
            "UPDATE project_materials SET status = ? WHERE id = ? AND project_id = ?",
            (status, material_id, project_id),
        )
        db.commit()
    return redirect(url_for("project_detail", project_id=project_id, _anchor="materials"))


@app.route("/projects/<int:project_id>/materials/<int:material_id>/edit", methods=["POST"])
def edit_material(project_id, material_id):
    item = request.form.get("item", "").strip()
    if not item:
        flash("Material item name is required.", "error")
        return redirect(url_for("project_detail", project_id=project_id, _anchor="materials"))
    db = get_db()
    db.execute(
        "UPDATE project_materials SET item = ?, quantity = ?, unit = ?, supplier = ?,"
        " notes = ? WHERE id = ? AND project_id = ?",
        (item, request.form.get("quantity", "").strip(),
         request.form.get("unit", "").strip(),
         request.form.get("supplier", "").strip(),
         request.form.get("notes", "").strip(), material_id, project_id))
    db.commit()
    return redirect(url_for("project_detail", project_id=project_id, _anchor="materials"))


@app.route("/projects/<int:project_id>/materials/<int:material_id>/delete", methods=["POST"])
@delete_required
def delete_material(project_id, material_id):
    ok, msg = trash_item("material", material_id)
    flash(msg, "" if ok else "error")
    return redirect(url_for("project_detail", project_id=project_id, _anchor="materials"))


# -------------------------------------------------------------------- tasks
def _task_assignee(project_id):
    """Read and validate an household_member_id from the form: blank means
    unassigned, a real employee id is kept, anything else is rejected."""
    raw = request.form.get("household_member_id", "").strip()
    if not raw:
        return None
    emp = get_db().execute(
        "SELECT id FROM household_members WHERE id = ?", (raw,)).fetchone()
    return emp["id"] if emp else None


@app.route("/projects/<int:project_id>/tasks/add", methods=["POST"])
def add_task(project_id):
    fetch_project(project_id)
    title = request.form.get("title", "").strip()
    if not title:
        flash("A task needs a title.", "error")
        return redirect(url_for("project_detail", project_id=project_id, _anchor="tasks"))
    status = request.form.get("status", "To do")
    if status not in TASK_STATUSES:
        status = "To do"
    db = get_db()
    next_order = db.execute(
        "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM project_tasks WHERE project_id = ?",
        (project_id,)).fetchone()[0]
    db.execute(
        "INSERT INTO project_tasks"
        " (project_id, household_member_id, title, status, due_date, notes, sort_order,"
        "  completed_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, strftime('%Y-%m-%d %H:%M:%f', 'now'))",
        (project_id, _task_assignee(project_id), title, status,
         request.form.get("due_date", "").strip(),
         request.form.get("notes", "").strip(), next_order,
         datetime.now().strftime("%Y-%m-%d") if status == "Done" else ""),
    )
    db.commit()
    return redirect(url_for("project_detail", project_id=project_id, _anchor="tasks"))


def _permit_coverage(groups, filed_labels):
    """(filed, total) for the project's Permit-category requirements."""
    total = filed = 0
    for heading, items in groups:
        if heading.lower().startswith("permit"):
            total += len(items)
            filed += sum(1 for r in items if r["label"] in filed_labels)
    return filed, total


def project_permit_coverage(db, project, rules):
    """(filed, total) permits for a project — its resolved permit requirements vs.
    the permit documents already filed. For the Permits dashboard column."""
    groups = group_rules(match_rules(project, rules))
    filed_labels = {f["rule_label"] for f in db.execute(
        "SELECT rule_label FROM project_files WHERE project_id = ?", (project["id"],)).fetchall()
        if f["rule_label"]}
    return _permit_coverage(groups, filed_labels)


def _loads_recorded(db, project):
    """True once the walkthrough loads have been captured for a project — either
    the structured Loads & Sizing worksheet has line items, or the free-text
    loads summary on the project is filled. Used to gate the Planning stage."""
    if (project["electric_loads"] if "electric_loads" in project.keys() else "").strip():
        return True
    n = db.execute("SELECT COUNT(*) FROM project_load_items WHERE project_id = ?",
                   (project["id"],)).fetchone()[0]
    return n > 0


def stage_info(db, project, groups, filed_labels):
    """Piece 18 (revised Piece 35): the project's current stage, its exit
    criteria, and Project-Prep prerequisites."""
    status = project["status"] or DEFAULT_PROJECT_STATUS
    spec = STATUS_OWNERSHIP.get(status, {"dept": "—", "exit": ""})
    filed, total = _permit_coverage(groups, filed_labels)
    permits_ok = filed >= total
    install_date = project["install_date"] if "install_date" in project.keys() else ""
    # Loads are collected during the walkthrough, not at project creation — the
    # Planning stage requires them recorded before it can advance. "Recorded"
    # means either the structured Loads & Sizing worksheet has entries or the
    # free-text loads summary is filled.
    loads_ok = _loads_recorded(db, project)
    # Progress: this stage's own tasks (tagged with pipeline_status = status).
    tdone, ttotal = db.execute(
        "SELECT COALESCE(SUM(status = 'Done'), 0), COUNT(*) FROM project_tasks"
        " WHERE project_id = ? AND pipeline_status = ?", (project["id"], status)).fetchone()
    # Ready to advance? All this stage's tasks done; Planning also needs the
    # loads collected; Prep also needs permits filed + an install date.
    ready = (ttotal == 0 or tdone >= ttotal)
    pending = []
    if ttotal and tdone < ttotal:
        pending.append(f"{ttotal - tdone} task(s) still open")
    if status == "Planning":
        if not loads_ok:
            pending.append("electric loads not recorded")
        ready = ready and loads_ok
    if status == "Prep":
        if not permits_ok:
            pending.append(f"{total - filed} permit(s) not filed")
        if not install_date:
            pending.append("no install date set")
        ready = ready and permits_ok and bool(install_date)
    return {
        "status": status, "dept": spec["dept"], "exit": spec["exit"],
        "permits_filed": filed, "permits_total": total, "permits_ok": permits_ok,
        "install_date": install_date, "tasks_done": tdone, "tasks_total": ttotal,
        "loads_ok": loads_ok,
        "ready": ready, "pending": pending, "next": next_stage(status),
    }


def build_project_progress(db, project):
    """Piece 20.2: compact pipeline snapshot for the per-project progress widget.
    Returns the ordered pipeline stages each tagged done / current / upcoming
    (or skip when the project is Abandoned), an overall percent across the
    pipeline, and the single next actionable step — so a glance at the bar
    tells anyone where a project stands and what happens next. Safe for any project
    row; two small queries."""
    status = project["status"] or DEFAULT_PROJECT_STATUS
    lost = (status == "Abandoned")
    complete = (status == "Done")
    order = STAGE_ORDER  # Planning .. Done
    idx = order.index(status) if status in order else 0

    # Current-stage task progress drives the fractional fill of the bar.
    cur_done = cur_total = 0
    if not lost and not complete:
        cur_done, cur_total = db.execute(
            "SELECT COALESCE(SUM(status = 'Done'), 0), COUNT(*) FROM project_tasks"
            " WHERE project_id = ? AND pipeline_status = ?",
            (project["id"], status)).fetchone()

    # The next actionable step: lowest-sort_order task that isn't Done.
    nxt = None
    if not lost and not complete:
        nxt = db.execute(
            "SELECT t.title, e.name AS who FROM project_tasks t"
            " LEFT JOIN household_members e ON e.id = t.household_member_id"
            " WHERE t.project_id = ? AND t.status != 'Done'"
            " ORDER BY t.sort_order, t.id LIMIT 1", (project["id"],)).fetchone()

    stages = []
    for i, s in enumerate(order):
        if lost:
            state = "skip"
        elif complete or i < idx:
            state = "done"
        elif i == idx:
            state = "current"
        else:
            state = "upcoming"
        stages.append({"name": s, "short": STAGE_SHORT.get(s, s), "state": state})

    # Overall percent: the working stages are Planning..Wrap-up (4 transitions
    # before Done); Done is 100%. Task completion within the current
    # stage adds a fraction so the bar creeps forward as work gets done.
    working = len(order) - 1
    if lost:
        pct = 0
    elif complete:
        pct = 100
    else:
        frac = (cur_done / cur_total) if cur_total else 0.0
        pct = int(round(min(idx + frac, working) / working * 100))

    if lost:
        next_label, next_who = "Marked Abandoned", None
    elif complete:
        next_label, next_who = "Project complete", None
    elif nxt:
        next_label, next_who = nxt["title"], nxt["who"]
    else:
        ns = next_stage(status)
        next_label = f"Move to {ns}" if ns else "Wrap up & close"
        next_who = None

    return {
        "status": status, "stages": stages, "pct": pct,
        "next_label": next_label, "next_who": next_who,
        "lost": lost, "complete": complete,
        "cur_done": cur_done, "cur_total": cur_total,
    }


def project_billing(db, project_id, contract_amount=0.0):
    """Piece 21: financial rollup for a project — income collected/outstanding,
    expenses, and the balance — plus the raw transactions. Drives the Finance
    Payments table and the per-project Billing tab."""
    txns = db.execute(
        "SELECT t.*, (SELECT f.id FROM project_files f WHERE f.txn_id = t.id LIMIT 1)"
        " AS receipt_file_id FROM project_transactions t WHERE t.project_id = ?"
        " ORDER BY t.txn_date, t.id", (project_id,)).fetchall()
    def total(kind, paid=None):
        return sum(t["amount"] or 0 for t in txns if t["kind"] == kind
                   and (paid is None or (t["status"] == "Paid") == paid))
    collected = total("Income", paid=True)
    outstanding = total("Income", paid=False)
    expense = total("Expense")
    expense_paid = total("Expense", paid=True)
    # contract_amount is stored with TEXT affinity (added via ensure_columns),
    # so coerce it to a number before any arithmetic.
    contract = _to_float(contract_amount) or 0.0
    # Piece 21.5: roll up the source paperwork (Receipt / Invoice / Bill) so the
    # Billing tab can show how many of each are on file and their totals.
    def _doc(dt):
        rows = [t for t in txns if (t["doc_type"] if "doc_type" in t.keys() else "") == dt]
        return {"count": len(rows), "amount": sum(t["amount"] or 0 for t in rows)}
    docs = {dt: _doc(dt) for dt in DOC_TYPES}
    return {
        "txns": txns, "contract": contract,
        "collected": collected, "outstanding": outstanding,
        "invoiced": collected + outstanding,
        "uninvoiced": max(contract - (collected + outstanding), 0.0),
        "expense": expense, "expense_paid": expense_paid,
        "expense_out": expense - expense_paid,
        "net": collected - expense_paid,          # cash in hand vs. cash out
        "net_accrual": (collected + outstanding) - expense,
        "docs": docs,
    }


def _status_from_title(title):
    t = (title or "").lower()
    for keyword, status in TITLE_STATUS_KEYWORDS:
        if keyword in t:
            return status
    return ""


def tag_tasks_by_stage(db):
    """One-time (Piece 18.1): give existing tasks a pipeline_status so current
    projects show stage progress. Newly generated tasks are tagged at creation."""
    if db.execute("SELECT 1 FROM meta WHERE key = 'tasks_stage_tagged'").fetchone():
        return
    db.row_factory = sqlite3.Row
    for t in db.execute("SELECT id, title FROM project_tasks"
                        " WHERE COALESCE(pipeline_status, '') = ''").fetchall():
        status = _status_from_title(t["title"])
        if status:
            db.execute("UPDATE project_tasks SET pipeline_status = ? WHERE id = ?",
                       (status, t["id"]))
    db.execute("INSERT INTO meta (key, value) VALUES ('tasks_stage_tagged', '1')"
               " ON CONFLICT(key) DO UPDATE SET value = excluded.value")
    db.commit()


def _generate_project_tasks(db, project, install_date_raw="", only_status=None):
    """Piece 31.5 (revised Piece 35): core of the task auto-generator —
    materialize a project's process steps into To-do tasks, scheduled and
    left unassigned (Piece 35 dropped role-based auto-assignment — a human
    picks who does it), skipping steps already on the list (safe to re-run).
    When `only_status` is given, only steps tagged for that pipeline stage
    are inserted (used to auto-fill the stage a project just entered);
    otherwise every actionable step is generated. Returns
    (added, assigned, scheduled) — `assigned` is always 0 now, kept in the
    return shape so call sites don't need to change. Does not commit."""
    project_id = project["id"]
    rules = db.execute("SELECT * FROM resource_rules").fetchall()
    _xml, details = build_project_bpmn(project, match_rules(project, rules))

    # Actionable workflow steps in order (no start/end events, gateways, or
    # automatic system steps like "Compendium generates tasks" — those stay on the
    # chart but never become a to-do).
    task_steps = [
        s for s in sorted(details.values(), key=lambda d: d["order"])
        if not (s["kind"].endswith("Event") or s["kind"].endswith("Gateway"))
        and s["kind"] != "serviceTask"
        and (s["name"] or "").strip()
    ]
    # Optional schedule anchored on Site Installation.
    base_date = None
    raw_install = (install_date_raw or "").strip()
    if raw_install:
        try:
            base_date = datetime.strptime(raw_install, "%Y-%m-%d").date()
        except ValueError:
            base_date = None
    install_idx = next((i for i, s in enumerate(task_steps)
                        if s["name"].strip().lower().startswith("site installation")),
                       None)

    existing = {r["title"].strip().lower() for r in db.execute(
        "SELECT title FROM project_tasks WHERE project_id = ?", (project_id,)).fetchall()}
    base = db.execute(
        "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM project_tasks WHERE project_id = ?",
        (project_id,)).fetchone()[0]
    # Default chain anchor: with no completed step yet, the first generated
    # step is due 7 days out, the next 7 days after that, and so on. As steps
    # actually get marked Done, set_task_status re-defaults the next open step
    # to 7 days after that completion.
    chain_start = datetime.now().date()
    default_seq = 0
    added = assigned = scheduled = 0
    for pos, step in enumerate(task_steps):
        # When filling a single stage, skip steps that belong to other stages —
        # without touching the default-deadline chain for the ones we keep.
        if only_status is not None and step.get("status", "") != only_status:
            continue
        title = step["name"].strip()
        if title.lower() in existing:
            continue
        note = f"Process step · {step['lane']}" if step.get("lane") else "Process step"
        assignee = None
        due = ""
        if base_date is not None and install_idx is not None:
            offset = (pos - install_idx) * TASK_DUE_SPACING_DAYS
            due = (base_date + timedelta(days=offset)).strftime("%Y-%m-%d")
        else:
            default_seq += 1
            due = (chain_start + timedelta(
                days=default_seq * TASK_DEFAULT_LEAD_DAYS)).strftime("%Y-%m-%d")
        db.execute(
            "INSERT INTO project_tasks"
            " (project_id, household_member_id, title, status, due_date, notes, sort_order,"
            "  pipeline_status, updated_at)"
            " VALUES (?, ?, ?, 'To do', ?, ?, ?, ?, strftime('%Y-%m-%d %H:%M:%f', 'now'))",
            (project_id, assignee, title, due, note, base + added,
             step.get("status", "")))
        existing.add(title.lower())
        added += 1
        if assignee:
            assigned += 1
        if due:
            scheduled += 1
    return added, assigned, scheduled


@app.route("/projects/<int:project_id>/tasks/generate", methods=["POST"])
def generate_tasks(project_id):
    """Pre-load a project's task list from its process: run the same per-project
    BPMN the Process chart uses, then turn each workflow step (skipping
    start/end events and gateways) into a To-do task, in order, left
    unassigned. If a target install date is given, each task gets a due date
    spaced around the Site Installation step. Skips steps already on the
    list, so it's safe to re-run after the project's fields change."""
    project = fetch_project(project_id)
    db = get_db()
    raw_install = request.form.get("install_date", "").strip()
    added, assigned, scheduled = _generate_project_tasks(db, project, raw_install)
    db.commit()
    if added:
        extra = []
        if assigned:
            extra.append(f"{assigned} auto-assigned by role")
        if scheduled:
            if raw_install:
                extra.append(f"due dates set around {raw_install}")
            else:
                extra.append("default deadlines set 7 days apart")
        detail = f" ({'; '.join(extra)})" if extra else ""
        flash(f"Added {added} task{'s' if added != 1 else ''} from the project's process{detail}.")
    else:
        flash("No new tasks — the process steps are already on the list.")
    return redirect(url_for("project_detail", project_id=project_id, _anchor="tasks"))


def _redefault_next_due(db, project_id, completed_date):
    """A step just became Done — default the next still-open step's deadline
    to TASK_DEFAULT_LEAD_DAYS (7) days after that completion. "Next" is the
    lowest sort_order among the project's not-Done tasks, i.e. the step that just
    became the one to work on. Must be called after the completed task's
    status is written so it's excluded here. Rough default; hand-editable."""
    if not completed_date:
        return
    try:
        base = datetime.strptime(completed_date, "%Y-%m-%d").date()
    except ValueError:
        return
    nxt = db.execute(
        "SELECT id FROM project_tasks WHERE project_id = ? AND status != 'Done'"
        " ORDER BY sort_order, id LIMIT 1", (project_id,)).fetchone()
    if nxt is None:
        return
    due = (base + timedelta(days=TASK_DEFAULT_LEAD_DAYS)).strftime("%Y-%m-%d")
    db.execute(
        "UPDATE project_tasks SET due_date = ?,"
        " updated_at = strftime('%Y-%m-%d %H:%M:%f', 'now') WHERE id = ?",
        (due, nxt["id"]))


@app.route("/projects/<int:project_id>/tasks/<int:task_id>/status", methods=["POST"])
def set_task_status(project_id, task_id):
    status = request.form.get("status", "")
    if status in TASK_STATUSES:
        db = get_db()
        # Stamp (or clear) the completion date as the task enters/leaves Done.
        completed = datetime.now().strftime("%Y-%m-%d") if status == "Done" else ""
        db.execute(
            "UPDATE project_tasks SET status = ?, completed_at = ?,"
            " updated_at = strftime('%Y-%m-%d %H:%M:%f', 'now') WHERE id = ? AND project_id = ?",
            (status, completed, task_id, project_id))
        # Completing a step re-anchors the next open step's default deadline.
        if status == "Done":
            _redefault_next_due(db, project_id, completed)
        db.commit()
    # A dashboard passes ?next= so the status change returns there; only
    # same-site relative paths are honored.
    nxt = request.form.get("next", "")
    if nxt.startswith("/") and not nxt.startswith("//"):
        return redirect(nxt)
    return redirect(url_for("project_detail", project_id=project_id, _anchor="tasks"))


@app.route("/projects/<int:project_id>/tasks/<int:task_id>/assign", methods=["POST"])
def set_task_assignee(project_id, task_id):
    db = get_db()
    db.execute("UPDATE project_tasks SET household_member_id = ?, updated_at = strftime('%Y-%m-%d %H:%M:%f', 'now')"
               " WHERE id = ? AND project_id = ?",
               (_task_assignee(project_id), task_id, project_id))
    db.commit()
    return redirect(url_for("project_detail", project_id=project_id, _anchor="tasks"))


@app.route("/projects/<int:project_id>/tasks/<int:task_id>/due", methods=["POST"])
def set_task_due(project_id, task_id):
    db = get_db()
    db.execute("UPDATE project_tasks SET due_date = ?, updated_at = strftime('%Y-%m-%d %H:%M:%f', 'now')"
               " WHERE id = ? AND project_id = ?",
               (request.form.get("due_date", "").strip(), task_id, project_id))
    db.commit()
    return redirect(url_for("project_detail", project_id=project_id, _anchor="tasks"))


@app.route("/projects/<int:project_id>/tasks/<int:task_id>/edit", methods=["POST"])
def edit_task(project_id, task_id):
    title = request.form.get("title", "").strip()
    if not title:
        flash("A task needs a title.", "error")
        return redirect(url_for("project_detail", project_id=project_id, _anchor="tasks"))
    db = get_db()
    db.execute("UPDATE project_tasks SET title = ?, notes = ?,"
               " updated_at = strftime('%Y-%m-%d %H:%M:%f', 'now') WHERE id = ? AND project_id = ?",
               (title, request.form.get("notes", "").strip(), task_id, project_id))
    db.commit()
    return redirect(url_for("project_detail", project_id=project_id, _anchor="tasks"))


@app.route("/projects/<int:project_id>/tasks/<int:task_id>/delete", methods=["POST"])
@delete_required
def delete_task(project_id, task_id):
    ok, msg = trash_item("task", task_id)
    flash(msg, "" if ok else "error")
    return redirect(url_for("project_detail", project_id=project_id, _anchor="tasks"))


@app.route("/tasks")
def tasks_dashboard():
    """Cross-project task board: every task in one place, filterable to one
    person (or the unassigned pile) and to open vs. all. The home for
    'what am I supposed to be doing' across every project."""
    db = get_db()
    employees = db.execute("SELECT id, name FROM household_members ORDER BY name").fetchall()
    who = request.args.get("employee", "")   # "" (all) / "unassigned" / an id
    show = request.args.get("show", "open")  # open / all
    sql = ("SELECT t.*, j.job_name, j.id AS project_id,"
           " e.name AS assignee_name FROM project_tasks t"
           " JOIN projects j ON j.id = t.project_id"
           " LEFT JOIN household_members e ON e.id = t.household_member_id"
           " WHERE j.status != 'Abandoned'")   # Piece 30.2: hide cancelled-project tasks
    params = []
    if who == "unassigned":
        sql += " AND t.household_member_id IS NULL"
    elif who.isdigit():
        sql += " AND t.household_member_id = ?"
        params.append(int(who))
    if show == "open":
        sql += " AND t.status != 'Done'"
    # Open first, then soonest due (blank dues last), then by project.
    sql += (" ORDER BY (t.status = 'Done'), (t.due_date = ''), t.due_date,"
            " j.id, t.sort_order, t.id")
    tasks = db.execute(sql, params).fetchall()
    counts = {}
    for t in tasks:
        counts[t["status"]] = counts.get(t["status"], 0) + 1
    today = datetime.now().strftime("%Y-%m-%d")
    overdue = sum(1 for t in tasks
                  if t["due_date"] and t["due_date"] < today and t["status"] != "Done")
    # Piece 26.3: group the flat list under each project so the board reads as
    # "everything this project needs" at a glance. Tasks arrive already sorted
    # (open first, soonest due), so each group keeps that order.
    grouped = {}
    for t in tasks:
        g = grouped.get(t["project_id"])
        if g is None:
            g = grouped[t["project_id"]] = {
                "project_id": t["project_id"], "job_name": t["job_name"],
                "tasks": [], "open": 0, "overdue": 0}
        g["tasks"].append(t)
        if t["status"] != "Done":
            g["open"] += 1
            if t["due_date"] and t["due_date"] < today:
                g["overdue"] += 1

    def _group_key(g):
        open_dues = [t["due_date"] for t in g["tasks"]
                     if t["status"] != "Done" and t["due_date"]]
        soonest = min(open_dues) if open_dues else "9999-99-99"
        # Projects with overdue work first, then by soonest due date, then name.
        return (0 if g["overdue"] else 1, soonest, (g["job_name"] or "").lower())
    groups = sorted(grouped.values(), key=_group_key)
    return render_template(
        "tasks.html", groups=groups, task_total=len(tasks), employees=employees,
        who=who, show=show, task_statuses=TASK_STATUSES, counts=counts,
        overdue=overdue, today=today)


# ------------------------------------------- Piece 14: Work Bag (offline sync)
def _my_tasks_rows(db, household_member_id):
    # Piece 21.6: also surface pipeline_status + install_date so the Work Bag
    # can group tasks by project (with the install date) and show only field work.
    return db.execute(
        "SELECT t.id, t.title, t.status, t.due_date, t.notes, t.updated_at,"
        " t.pipeline_status, j.id AS project_id, j.job_name, j.install_date"
        " FROM project_tasks t JOIN projects j ON j.id = t.project_id"
        " WHERE t.household_member_id = ? AND j.status != 'Abandoned'"   # Piece 30.2
        " ORDER BY (t.status = 'Done'), (j.install_date = ''), j.install_date,"
        " j.id, (t.due_date = ''), t.due_date, t.id",
        (household_member_id,)).fetchall()


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


@app.route("/work-bag")
def work_bag():
    """Piece 27.7: the Work Bag landing — just the projects in the worker's bag.
    Tapping a project opens its own page (work_bag_job) with that project's tasks, hours,
    receipts and notes. The project list is rendered in the browser from the same
    cached /api/my-tasks data, so the landing keeps working offline."""
    return render_template("work_bag.html")


@app.route("/work-bag/job/<int:project_id>")
def work_bag_job(project_id):
    """A single project's Work Bag page: its field tasks plus hours / receipt / note
    capture scoped to this project. Task data still flows through the /api endpoints
    (offline-capable); the capture forms and recent lists are pinned to the project."""
    db = get_db()
    project = fetch_project(project_id)
    user = current_user()
    my_entries = my_notes = my_receipts = []
    if user is not None:
        my_entries = db.execute(
            "SELECT * FROM field_submissions WHERE household_member_id = ?"
            " ORDER BY id DESC LIMIT 12", (user["id"],)).fetchall()
        my_notes = db.execute(
            "SELECT n.* FROM project_notes n WHERE n.author = ? AND n.project_id = ?"
            " ORDER BY n.id DESC LIMIT 12", (user["name"], project_id)).fetchall()
        my_receipts = db.execute(
            "SELECT t.*, f.id AS file_id FROM project_transactions t"
            " LEFT JOIN project_files f ON f.txn_id = t.id"
            " WHERE t.doc_type = 'Receipt' AND t.created_by = ? AND t.project_id = ?"
            " ORDER BY t.id DESC LIMIT 10", (user["name"], project_id)).fetchall()
    return render_template(
        "work_bag_job.html", project=project,
        task_statuses=TASK_STATUSES, today=datetime.now().strftime("%Y-%m-%d"),
        my_entries=my_entries, my_notes=my_notes,
        my_receipts=my_receipts, receipt_categories=RECEIPT_CATEGORIES)


@app.route("/api/my-tasks")
def api_my_tasks():
    """The worker's assigned tasks, their still-pending field edits, and a
    short submission history — as JSON for the Work Bag."""
    user = current_user()
    if user is None:
        return jsonify({"error": "not signed in"}), 401
    db = get_db()
    rows = _my_tasks_rows(db, user["id"])
    pend = db.execute(
        "SELECT i.task_id, i.new_status, i.new_notes"
        " FROM field_submission_items i"
        " JOIN field_submissions s ON s.id = i.submission_id"
        " WHERE s.household_member_id = ? AND s.status = 'Pending'", (user["id"],)).fetchall()
    subs = db.execute(
        "SELECT id, work_date, reported_hours, approved_hours, status, submitted_at,"
        " reviewed_at FROM field_submissions WHERE household_member_id = ?"
        " ORDER BY id DESC LIMIT 8", (user["id"],)).fetchall()
    # Piece 21.7: attach any field photos already on file for photo-steps, plus
    # the link to each photo step's capture page.
    photo_task_ids = [r["id"] for r in rows if _is_photo_step(r["title"])]
    photos_by_task = {}
    if photo_task_ids:
        ph = ", ".join("?" * len(photo_task_ids))
        for f in db.execute(
                f"SELECT id, project_id, task_id FROM project_files WHERE rule_label = ?"
                f" AND task_id IN ({ph}) ORDER BY id DESC",
                (FIELD_PHOTO_LABEL, *[str(t) for t in photo_task_ids])).fetchall():
            photos_by_task.setdefault(str(f["task_id"]), []).append(
                {"id": f["id"],
                 "url": url_for("view_file", project_id=f["project_id"], file_id=f["id"])})
    tasks_out = []
    for r in rows:
        d = dict(r)
        d["is_photo_step"] = _is_photo_step(r["title"])
        d["photos_url"] = url_for("task_photos", task_id=r["id"])
        d["photos"] = photos_by_task.get(str(r["id"]), [])
        tasks_out.append(d)
    # Piece 22.0: the materials list for each project on the board, so installers can
    # load the truck before they leave. Keyed by project so the Work Bag can show it
    # under each project's banner.
    materials_by_job = {}
    job_ids = {r["project_id"] for r in rows}
    if job_ids:
        ph = ", ".join("?" * len(job_ids))
        for m in db.execute(
                f"SELECT project_id, item, quantity, unit, status FROM project_materials"
                f" WHERE project_id IN ({ph}) ORDER BY id", tuple(job_ids)).fetchall():
            materials_by_job.setdefault(str(m["project_id"]), []).append({
                "item": m["item"], "quantity": m["quantity"], "unit": m["unit"],
                "status": m["status"]})
    return jsonify({
        "server_time": datetime.now().isoformat(timespec="seconds"),
        "user": user["name"],
        "tasks": tasks_out,
        "materials_by_job": materials_by_job,
        "pending_items": [dict(r) for r in pend],
        "submissions": [dict(r) for r in subs],
    })


@app.route("/api/work-bag/submit", methods=["POST"])
def api_work_bag_submit():
    """Save the worker's completed field work as a PENDING submission — a
    copy in the database that does NOT change the authoritative task data
    until a manager approves it. Hours are a single self-reported total
    (display-only once approved — Piece 35 dropped the pay-type breakdown
    along with payroll)."""
    user = current_user()
    if user is None:
        return jsonify({"error": "not signed in"}), 401
    payload = request.get_json(silent=True) or {}
    db = get_db()
    valid = []
    for ch in payload.get("changes", []) or []:
        row = db.execute(
            "SELECT * FROM project_tasks WHERE id = ? AND household_member_id = ?",
            (ch.get("id"), user["id"])).fetchone()
        if row is None:
            continue
        status = ch.get("status", row["status"])
        if status not in TASK_STATUSES:
            status = row["status"]
        work_date = (ch.get("work_date") or payload.get("work_date") or "").strip()
        valid.append((row["id"], row["title"], status,
                      ch.get("notes", row["notes"]), ch.get("base_updated_at") or "",
                      work_date))
    reported_hours = _to_float(payload.get("reported_hours"))
    if not valid and reported_hours is None:
        return jsonify({"error": "nothing to submit"}), 400
    cur = db.execute(
        "INSERT INTO field_submissions (household_member_id, work_date, reported_hours, note)"
        " VALUES (?, ?, ?, ?)",
        (user["id"], (payload.get("work_date") or "").strip(), reported_hours,
         (payload.get("note") or "").strip()))
    sub_id = cur.lastrowid
    for task_id, title, status, notes, base, work_date in valid:
        db.execute(
            "INSERT INTO field_submission_items"
            " (submission_id, task_id, task_title, new_status, new_notes,"
            "  base_updated_at, work_date)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (sub_id, task_id, title, status, notes, base, work_date))
    db.commit()
    return jsonify({"submission_id": sub_id, "status": "Pending",
                    "items": len(valid)})


@app.route("/submissions")
@admin_required
def submissions_page():
    """Manager review of field-work submissions: confirm hours and approve
    (applies the task changes + logs hours) or reject."""
    db = get_db()
    show = request.args.get("show", "pending")
    where = "WHERE s.status = 'Pending'" if show == "pending" else ""
    subs = db.execute(
        "SELECT s.*, e.name AS emp_name FROM field_submissions s"
        " JOIN household_members e ON e.id = s.household_member_id"
        f" {where} ORDER BY (s.status='Pending') DESC, s.id DESC LIMIT 100"
    ).fetchall()
    items_by_sub = {}
    ids = [s["id"] for s in subs]
    if ids:
        q = ("SELECT * FROM field_submission_items WHERE submission_id IN (%s)"
             " ORDER BY id" % ",".join("?" * len(ids)))
        for it in db.execute(q, ids).fetchall():
            items_by_sub.setdefault(it["submission_id"], []).append(dict(it))
    return render_template("submissions.html", subs=subs, items_by_sub=items_by_sub,
                           show=show)


@app.route("/submissions/<int:sub_id>/approve", methods=["POST"])
@admin_required
def approve_submission(sub_id):
    db = get_db()
    sub = db.execute(
        "SELECT * FROM field_submissions WHERE id = ? AND status = 'Pending'",
        (sub_id,)).fetchone()
    if sub is None:
        flash("Submission not found or already reviewed.", "error")
        return redirect(url_for("submissions_page"))
    approved_hours = _to_float(request.form.get("approved_hours"))
    if approved_hours is None:
        approved_hours = sub["reported_hours"]
    who = current_user()
    # Now — and only now — apply the field edits to the authoritative tasks.
    for it in db.execute(
            "SELECT * FROM field_submission_items WHERE submission_id = ?",
            (sub_id,)).fetchall():
        row = db.execute("SELECT * FROM project_tasks WHERE id = ?",
                         (it["task_id"],)).fetchone()
        if row is None:
            continue
        status = it["new_status"] if it["new_status"] in TASK_STATUSES else row["status"]
        completed = datetime.now().strftime("%Y-%m-%d") if status == "Done" else ""
        db.execute(
            "UPDATE project_tasks SET status = ?, notes = ?, completed_at = ?,"
            " updated_at = strftime('%Y-%m-%d %H:%M:%f', 'now') WHERE id = ?",
            (status, it["new_notes"], completed, it["task_id"]))
        # Field-approved completions re-anchor the next open step's deadline too.
        if status == "Done" and row["status"] != "Done":
            _redefault_next_due(db, row["project_id"], completed)
    db.execute(
        "UPDATE field_submissions SET status = 'Approved', approved_hours = ?,"
        " reviewed_by = ?, reviewed_at = datetime('now') WHERE id = ?",
        (approved_hours, who["name"] if who else "", sub_id))
    db.commit()
    flash("Submission approved — task changes applied and hours logged.")
    return redirect(url_for("submissions_page"))


@app.route("/submissions/<int:sub_id>/reject", methods=["POST"])
@admin_required
def reject_submission(sub_id):
    who = current_user()
    db = get_db()
    db.execute(
        "UPDATE field_submissions SET status = 'Rejected', reviewed_by = ?,"
        " reviewed_at = datetime('now') WHERE id = ? AND status = 'Pending'",
        (who["name"] if who else "", sub_id))
    db.commit()
    flash("Submission rejected — no changes were applied.")
    return redirect(url_for("submissions_page"))


# -------------------------------------------------------------------- files
def project_upload_dir(project_id):
    directory = UPLOADS_DIR / f"job_{project_id}"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


@app.route("/projects/<int:project_id>/files/upload", methods=["POST"])
def upload_file(project_id):
    fetch_project(project_id)
    upload = request.files.get("document")
    if upload is None or not upload.filename:
        flash("Choose a file to upload.", "error")
        return redirect(url_for("project_detail", project_id=project_id, _anchor="documents"))
    extension = upload.filename.rsplit(".", 1)[-1].lower() if "." in upload.filename else ""
    db = get_db()
    label = request.form.get("rule_label", "").strip()
    # Piece 25.2: a slot may restrict its accepted formats; otherwise the global
    # allow-list applies.
    allowed = allowed_formats_for_label(db, label) or ALLOWED_EXTENSIONS
    if extension not in allowed:
        where = f"“{label}” accepts" if label else "This upload accepts"
        flash(f"{where} only: {', '.join('.' + e for e in sorted(allowed))}. "
              f"You picked .{extension or '(no extension)'}.", "error")
        return redirect(url_for("project_detail", project_id=project_id, _anchor="documents"))
    # Piece 25.4 (revised 33): auto-rename to Job_Slot_Date.ext for recordkeeping.
    who = db.execute(
        "SELECT job_name FROM projects WHERE id = ?", (project_id,)).fetchone()
    friendly = friendly_filename(
        [who["job_name"] if who else "", label or "Document"], extension,
        taken=_taken_names(db, "project_files", "original_name", "project_id", project_id))
    stored = f"{uuid.uuid4().hex[:8]}_{secure_filename(friendly)}"
    upload.save(project_upload_dir(project_id) / stored)
    db.execute(
        "INSERT INTO project_files (project_id, rule_label, stored_name, original_name)"
        " VALUES (?, ?, ?, ?)",
        (project_id, label, stored, friendly),
    )
    db.commit()
    flash(f"Uploaded: {friendly}")
    return redirect(url_for("project_detail", project_id=project_id, _anchor="documents"))


@app.route("/projects/<int:project_id>/files/<int:file_id>/download")
def download_file(project_id, file_id):
    record = get_db().execute(
        "SELECT * FROM project_files WHERE id = ? AND project_id = ?",
        (file_id, project_id),
    ).fetchone()
    if record is None:
        abort(404)
    return send_from_directory(
        project_upload_dir(project_id), record["stored_name"], as_attachment=True,
        download_name=record["original_name"],
    )


@app.route("/projects/<int:project_id>/files/<int:file_id>/delete", methods=["POST"])
@delete_required
def delete_file(project_id, file_id):
    ok, msg = trash_item("project_file", file_id)
    flash(msg, "" if ok else "error")
    return redirect(url_for("project_detail", project_id=project_id, _anchor="documents"))


@app.route("/projects/<int:project_id>/files/<int:file_id>/view")
def view_file(project_id, file_id):
    """Serve a stored file inline (not as an attachment) — used for photo
    thumbnails and lightbox previews."""
    record = get_db().execute(
        "SELECT * FROM project_files WHERE id = ? AND project_id = ?",
        (file_id, project_id)).fetchone()
    if record is None:
        abort(404)
    return send_from_directory(
        project_upload_dir(project_id), record["stored_name"], as_attachment=False,
        download_name=record["original_name"])


@app.route("/work-bag/tasks/<int:task_id>/photos", methods=["GET", "POST"])
def task_photos(task_id):
    """Piece 21.7: the Work Bag's photo page for a single task — take/upload
    project photos from a phone and see the ones already on file. Photos are stored
    as project_files (tagged FIELD_PHOTO_LABEL + this task) so they also surface on
    the project record."""
    db = get_db()
    task = db.execute(
        "SELECT t.id, t.title, j.id AS project_id, j.job_name, j.install_date"
        " FROM project_tasks t JOIN projects j ON j.id = t.project_id WHERE t.id = ?",
        (task_id,)).fetchone()
    if task is None:
        abort(404)
    project_id = task["project_id"]
    if request.method == "POST":
        saved = 0
        # Piece 25.4 (revised 33): auto-rename photos to Job_Task_Date.ext (a
        # numeric suffix keeps a burst of shots on one day distinct).
        taken = _taken_names(db, "project_files", "original_name", "project_id", project_id)
        for up in request.files.getlist("photos"):
            if not up or not up.filename:
                continue
            ext = up.filename.rsplit(".", 1)[-1].lower() if "." in up.filename else ""
            if ext not in PHOTO_EXTENSIONS:
                continue
            friendly = friendly_filename(
                [task["job_name"], task["title"] or "Photo"],
                ext, taken=taken)
            taken.add(friendly)
            stored = f"{uuid.uuid4().hex[:8]}_{secure_filename(friendly)}"
            up.save(project_upload_dir(project_id) / stored)
            db.execute(
                "INSERT INTO project_files"
                " (project_id, rule_label, stored_name, original_name, task_id)"
                " VALUES (?, ?, ?, ?, ?)",
                (project_id, FIELD_PHOTO_LABEL, stored, friendly, str(task_id)))
            saved += 1
        db.commit()
        flash(f"Added {saved} photo(s)." if saved
              else "No photos added — choose image files.", "" if saved else "error")
        return redirect(url_for("task_photos", task_id=task_id))
    photos = db.execute(
        "SELECT * FROM project_files WHERE project_id = ? AND rule_label = ? AND task_id = ?"
        " ORDER BY id DESC", (project_id, FIELD_PHOTO_LABEL, str(task_id))).fetchall()
    return render_template(
        "work_bag_photos.html", task=task, photos=photos,
        today=datetime.now().strftime("%Y-%m-%d"))


@app.route("/work-bag/tasks/<int:task_id>/complete", methods=["POST"])
def complete_photo_task(task_id):
    """Piece 28.0: finish a photo step from its dedicated screen — record the
    photos already uploaded plus (optionally) the time it took, submit the task
    for the supervisor's approval, and return to the project's Work Bag page."""
    user = current_user()
    if user is None:
        abort(403)
    db = get_db()
    task = db.execute("SELECT * FROM project_tasks WHERE id = ? AND household_member_id = ?",
                      (task_id, user["id"])).fetchone()
    if task is None:
        flash("That task isn't in your bag.", "error")
        return redirect(url_for("work_bag"))
    action = request.form.get("action", "done")
    status = "Blocked" if action == "blocked" else "Done"
    notes = request.form.get("notes", "").strip()
    work_date = request.form.get("work_date", "").strip()
    if status == "Done":
        n = db.execute(
            "SELECT COUNT(*) AS c FROM project_files WHERE task_id = ? AND rule_label = ?",
            (str(task_id), FIELD_PHOTO_LABEL)).fetchone()["c"]
        if not n:
            flash("Take at least one photo before submitting this step as done.", "error")
            return redirect(url_for("task_photos", task_id=task_id))
    if status == "Blocked" and not notes:
        flash("Add a note about what's blocking it.", "error")
        return redirect(url_for("task_photos", task_id=task_id))
    reported_hours = _to_float(request.form.get("hours"))
    cur = db.execute(
        "INSERT INTO field_submissions (household_member_id, work_date, reported_hours, note)"
        " VALUES (?, ?, ?, ?)",
        (user["id"], work_date, reported_hours, ""))
    sub_id = cur.lastrowid
    db.execute(
        "INSERT INTO field_submission_items"
        " (submission_id, task_id, task_title, new_status, new_notes,"
        "  base_updated_at, work_date)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (sub_id, task_id, task["title"], status, notes,
         task["updated_at"] or "", work_date))
    db.commit()
    flash(f"“{task['title']}” submitted for approval."
          if status == "Done" else f"“{task['title']}” flagged as blocked for the office.")
    return redirect(url_for("work_bag_job", project_id=task["project_id"]))


@app.route("/work-bag/photos/<int:file_id>/delete", methods=["POST"])
def delete_task_photo(file_id):
    """Remove a field photo the crew took (scoped to FIELD_PHOTO_LABEL, so this
    can't touch requirement documents — those stay GM-only via delete_file)."""
    db = get_db()
    rec = db.execute("SELECT * FROM project_files WHERE id = ? AND rule_label = ?",
                     (file_id, FIELD_PHOTO_LABEL)).fetchone()
    if rec is None:
        abort(404)
    try:
        (project_upload_dir(rec["project_id"]) / rec["stored_name"]).unlink()
    except OSError:
        pass
    db.execute("DELETE FROM project_files WHERE id = ?", (file_id,))
    db.commit()
    flash("Photo removed.")
    back = int(rec["task_id"]) if str(rec["task_id"]).isdigit() else 0
    return redirect(url_for("task_photos", task_id=back) if back
                    else url_for("work_bag"))


@app.route("/projects/<int:project_id>/report")
def project_report(project_id):
    """Download a plain-text checklist report of the project's selections and
    every license, permit, and compliance item they resolve to."""
    project = fetch_project(project_id)
    rules = get_db().execute("SELECT * FROM resource_rules").fetchall()
    groups = group_rules(match_rules(project, rules))

    lines = [
        f"PROJECT REPORT — {project['job_name'] or 'Project #' + str(project['id'])}",
        f"Created: {project['created_at']}   Report generated: {datetime.now():%Y-%m-%d %H:%M}",
        "=" * 64,
        "",
        "PROJECT DETAILS",
        "-" * 64,
    ]
    for field in PROJECT_FIELDS:
        value = str(project[field] or "").strip()
        if value:
            lines.append(f"{PROJECT_FIELD_LABELS[field] + ':':34}{value}")
    for heading, items in groups:
        lines += ["", f"{heading.upper()} ({len(items)} ITEM{'S' if len(items) != 1 else ''})", "-" * 64]
        for rule in items:
            entry = f"[ ] {rule['label']}"
            if rule.get("alert_text"):
                entry += f"  {rule['alert_text']}"
            if rule["notes"]:
                entry += f"  ({rule['notes']})"
            lines.append(entry)
            if len(rule.get("instances", [])) > 1:
                for inst in rule["instances"]:
                    lines.append(f"        - {inst}")
            if rule["url"]:
                source = rule["link_text"] or ""
                lines.append(f"      {source + ': ' if source else 'link:  '}{rule['url']}")
            if rule["phone"]:
                lines.append(f"      phone: {rule['phone']}")
    if not groups:
        lines += ["", "No license/permit/compliance requirements matched."]
    materials = get_db().execute(
        "SELECT * FROM project_materials WHERE project_id = ? ORDER BY id", (project_id,)
    ).fetchall()
    if materials:
        lines += ["", f"MATERIAL LIST ({len(materials)} ITEMS)", "-" * 64]
        for m in materials:
            entry = f"[{m['status']:>9}] {m['item']}"
            if m["quantity"]:
                entry += f" — {m['quantity']} {m['unit']}".rstrip()
            if m["supplier"]:
                entry += f" ({m['supplier']})"
            lines.append(entry)
    files = get_db().execute(
        "SELECT * FROM project_files WHERE project_id = ? ORDER BY id", (project_id,)
    ).fetchall()
    if files:
        lines += ["", f"DOCUMENTS ON FILE ({len(files)})", "-" * 64]
        for f in files:
            entry = f"- {f['original_name']} ({f['uploaded_at'][:10]})"
            if f["rule_label"]:
                entry += f" -> {f['rule_label']}"
            lines.append(entry)
    lines.append("")
    return Response(
        "\n".join(lines),
        mimetype="text/plain",
        headers={"Content-Disposition":
                 f"attachment; filename=job_{project_id}_report.txt"},
    )


@app.route("/projects/<int:project_id>/bpmn")
def project_bpmn(project_id):
    """Download this project's process as a BPMN 2.0 file: the master
    pipeline instantiated with the project's resolved permits and variables."""
    project = fetch_project(project_id)
    rules = get_db().execute("SELECT * FROM resource_rules").fetchall()
    materials, files, materials_note, docs_note = project_progress_extras(project_id)
    xml, _details = build_project_bpmn(project, match_rules(project, rules),
                                   materials_note, docs_note)
    return Response(
        xml, mimetype="application/xml",
        headers={"Content-Disposition":
                 f"attachment; filename=job_{project_id}_process.bpmn"},
    )


def project_progress_extras(project_id):
    """Materials and documents for a project, plus one-line summaries used
    as annotations in the exported BPMN."""
    db = get_db()
    materials = db.execute(
        "SELECT * FROM project_materials WHERE project_id = ? ORDER BY id", (project_id,)
    ).fetchall()
    files = db.execute(
        "SELECT * FROM project_files WHERE project_id = ? ORDER BY id", (project_id,)
    ).fetchall()
    materials_note = ""
    if materials:
        counts = {}
        for m in materials:
            counts[m["status"]] = counts.get(m["status"], 0) + 1
        breakdown = ", ".join(f"{n} {s}" for s, n in counts.items())
        materials_note = f"Materials: {len(materials)} items — {breakdown}"
    docs_note = ""
    if files:
        covered = len({f["rule_label"] for f in files if f["rule_label"]})
        docs_note = (f"Documents on file: {len(files)}"
                     + (f" ({covered} requirements covered)" if covered else ""))
    return materials, files, materials_note, docs_note


@app.route("/projects/<int:project_id>/bpmn/view")
def project_bpmn_view(project_id):
    project = fetch_project(project_id)
    rules = get_db().execute("SELECT * FROM resource_rules").fetchall()
    materials, files, materials_note, docs_note = project_progress_extras(project_id)
    _xml, details = build_project_bpmn(project, match_rules(project, rules),
                                   materials_note, docs_note)
    steps = sorted(details.values(), key=lambda d: d["order"])
    files_by_label = {}
    for f in files:
        if f["rule_label"]:
            files_by_label.setdefault(f["rule_label"], []).append(f)
    material_counts = {}
    for m in materials:
        material_counts[m["status"]] = material_counts.get(m["status"], 0) + 1
    return render_template(
        "bpmn_view.html", project=project, steps=steps,
        files_by_label=files_by_label, materials=materials,
        material_counts=material_counts,
    )


@app.route("/rules")
def rules_page():
    db = get_db()
    rules = db.execute(
        "SELECT * FROM resource_rules"
        " ORDER BY field_name, field_value, category, label"
    ).fetchall()
    # When reached from a project page, offer a way back to that project.
    from_job = None
    from_job_id = request.args.get("from_job", type=int)
    if from_job_id:
        from_job = db.execute(
            "SELECT id, job_name FROM projects WHERE id = ?", (from_job_id,)
        ).fetchone()
    # Piece 25.0: in-place edit — ?edit pre-fills the add form with that rule.
    edit_rule = None
    if request.args.get("edit", type=int):
        edit_rule = db.execute("SELECT * FROM resource_rules WHERE id = ?",
                               (request.args.get("edit", type=int),)).fetchone()
    # Piece 26.8: group the editor by category (same helper the Directory uses),
    # so the long flat list reads by section and carries the same ⚠ verify chips.
    groups = group_rules(rules, dedupe=False)
    return render_template(
        "rules.html", rules=rules, groups=groups, from_job=from_job,
        edit_rule=edit_rule, category_headings=CATEGORY_HEADINGS,
        job_fields=[f for f in PROJECT_FIELDS if f != "job_name"],
        field_labels=PROJECT_FIELD_LABELS, categories=RULE_CATEGORIES,
    )


@app.route("/rules/new", methods=["POST"])
@admin_required
def add_rule():
    field_name = request.form.get("field_name", "").strip()
    field_value = request.form.get("field_value", "").strip()
    label = request.form.get("label", "").strip()
    from_job = request.form.get("from_job") or None
    field_name2 = request.form.get("field_name2", "").strip()
    field_value2 = request.form.get("field_value2", "").strip()
    if field_name not in PROJECT_FIELDS or not field_value or not label:
        flash("A rule needs a project field, a value to match, and a label.", "error")
        return redirect(url_for("rules_page", from_job=from_job))
    if field_name2 and (field_name2 not in PROJECT_FIELDS or not field_value2):
        flash("The second condition needs both a field and a value.", "error")
        return redirect(url_for("rules_page", from_job=from_job))
    db = get_db()
    db.execute(
        "INSERT INTO resource_rules"
        " (field_name, field_value, match_type, category, label, url, phone, notes,"
        "  field_name2, field_value2, match_type2, link_text, allowed_formats,"
        "  source_text, verify_status)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (field_name, field_value,
         "contains" if field_name == "products" else "equals",
         request.form.get("category", "Compliance"),
         label,
         request.form.get("url", "").strip(),
         request.form.get("phone", "").strip(),
         request.form.get("notes", "").strip(),
         field_name2, field_value2,
         "contains" if field_name2 == "products" else "equals",
         request.form.get("link_text", "").strip(),
         ",".join(sorted(_parse_formats(request.form.get("allowed_formats")))),
         request.form.get("source_text", "").strip(),
         _clean_verify_status(request.form.get("verify_status"))),
    )
    db.commit()
    flash(f"Rule added: {label}")
    return redirect(url_for("rules_page", from_job=from_job))


@app.route("/rules/<int:rule_id>/edit", methods=["POST"])
@admin_required
def update_rule(rule_id):
    db = get_db()
    if db.execute("SELECT 1 FROM resource_rules WHERE id = ?",
                  (rule_id,)).fetchone() is None:
        abort(404)
    field_name = request.form.get("field_name", "").strip()
    field_value = request.form.get("field_value", "").strip()
    label = request.form.get("label", "").strip()
    from_job = request.form.get("from_job") or None
    field_name2 = request.form.get("field_name2", "").strip()
    field_value2 = request.form.get("field_value2", "").strip()
    if field_name not in PROJECT_FIELDS or not field_value or not label:
        flash("A rule needs a project field, a value to match, and a label.", "error")
        return redirect(url_for("rules_page", from_job=from_job, edit=rule_id))
    if field_name2 and (field_name2 not in PROJECT_FIELDS or not field_value2):
        flash("The second condition needs both a field and a value.", "error")
        return redirect(url_for("rules_page", from_job=from_job, edit=rule_id))
    db.execute(
        "UPDATE resource_rules SET field_name = ?, field_value = ?, match_type = ?,"
        " category = ?, label = ?, url = ?, phone = ?, notes = ?, field_name2 = ?,"
        " field_value2 = ?, match_type2 = ?, link_text = ?, allowed_formats = ?,"
        " source_text = ?, verify_status = ? WHERE id = ?",
        (field_name, field_value,
         "contains" if field_name == "products" else "equals",
         request.form.get("category", "Compliance"), label,
         request.form.get("url", "").strip(),
         request.form.get("phone", "").strip(),
         request.form.get("notes", "").strip(),
         field_name2, field_value2,
         "contains" if field_name2 == "products" else "equals",
         request.form.get("link_text", "").strip(),
         ",".join(sorted(_parse_formats(request.form.get("allowed_formats")))),
         request.form.get("source_text", "").strip(),
         _clean_verify_status(request.form.get("verify_status")),
         rule_id))
    db.commit()
    flash(f"Rule updated: {label}")
    return redirect(url_for("rules_page", from_job=from_job))


@app.route("/directory")
def rule_directory():
    """Read-only, browsable view of every rule, filterable by project type
    and by the product variants. No editing happens here."""
    product = request.args.get("product", "")
    connection = request.args.get("connection", "")
    mounting = request.args.get("mounting", "")
    manufactured = request.args.get("manufactured", "")
    service = request.args.get("service", "")
    property_type = request.args.get("property", "")

    def value_ok(field, value):
        """One condition against the variant filters."""
        value = value.strip().lower()
        if connection and field in CONNECTION_FIELDS and value != connection.lower():
            return False
        if mounting and field == "pv_mounting_type" and value != mounting.lower():
            return False
        if manufactured and field == "pv_manufactured_house" and value != manufactured.lower():
            return False
        if service and field == "service_type" and value != service.lower():
            return False
        if property_type and field == "property_type" and value != property_type.lower():
            return False
        return True

    def visible(rule):
        conditions = [(rule["field_name"], rule["field_value"])]
        if rule["field_name2"]:
            conditions.append((rule["field_name2"], rule["field_value2"]))
        if not all(value_ok(f, v) for f, v in conditions):
            return False
        if product:
            # At least one condition must tie the rule to the chosen
            # project type (its product row or one of its variant fields).
            tied = any(
                (f == "products" and v.strip().lower() == product.lower())
                or (f in VARIANT_OWNERS and VARIANT_OWNERS[f] == product)
                for f, v in conditions)
            if not tied:
                return False
        return True

    rules = [r for r in get_db().execute(
        "SELECT * FROM resource_rules ORDER BY category, label"
    ).fetchall() if visible(r)]
    groups = consolidate_rules(rules)
    total = sum(len(items) for _, items in groups)   # consolidated requirements
    return render_template(
        "directory.html", groups=groups, total=total,
        field_labels=PROJECT_FIELD_LABELS,
        products=PRODUCTS, utility_connections=UTILITY_CONNECTIONS,
        mounting_types=MOUNTING_TYPES, service_types=SERVICE_TYPES,
        property_types=PROPERTY_TYPES,
        filters={"product": product, "connection": connection,
                 "mounting": mounting, "manufactured": manufactured,
                 "service": service, "property": property_type},
        filtering=any([product, connection, mounting, manufactured,
                       service, property_type]),
    )


@app.route("/rules/<int:rule_id>/delete", methods=["POST"])
@delete_required
def delete_rule(rule_id):
    ok, msg = trash_item("rule", rule_id)
    flash(msg, "" if ok else "error")
    return redirect(url_for("rules_page",
                            from_job=request.form.get("from_job") or None))


# ---------------------------------------------------------- household members
def read_household_member_form():
    """Validate and normalize a submitted household member form (create or
    edit). Names come in as first/last (+ optional nickname) and compose
    into `name`; role is a single Parent/Child/Assistant selection."""
    first = request.form.get("first_name", "").strip()
    last = request.form.get("last_name", "").strip()
    role = request.form.get("role", "").strip()
    values = {
        "first_name": first, "last_name": last,
        "nickname": request.form.get("nickname", "").strip(),
        "name": (first + " " + last).strip(),
        "schedule": request.form.get("schedule", "").strip(),
        "role": role if role in HOUSEHOLD_ROLES else "Parent",
    }
    errors = []
    if not first:
        errors.append("First name is required.")
    return values, errors


def render_household_member_form(values, household_member_id=None, username="",
                                  is_admin_checked="", duplicate_warning=None):
    """Render the shared new/edit form. Legacy fallback: an existing member
    with no first/last gets its `name` split into the fields."""
    values = dict(values)
    if not values.get("first_name") and values.get("name"):
        parts = values["name"].split(" ", 1)
        values["first_name"] = parts[0]
        values["last_name"] = parts[1] if len(parts) > 1 else ""
    return render_template(
        "employee_form.html", values=values, roles=HOUSEHOLD_ROLES,
        household_member_id=household_member_id, username=username,
        is_admin_checked=(str(is_admin_checked or "") == "1"),
        duplicate_warning=duplicate_warning,
    )


@app.route("/household-members")
def household_members_page():
    db = get_db()
    members = db.execute("SELECT * FROM household_members ORDER BY name").fetchall()
    # Per-member credential tally, with expiry warnings, for the list.
    summary = {}
    for c in db.execute(
            "SELECT household_member_id, expires FROM household_member_credentials").fetchall():
        s = summary.setdefault(c["household_member_id"],
                               {"count": 0, "expired": 0, "soon": 0})
        s["count"] += 1
        state, _ = credential_status(c["expires"])
        if state == "expired":
            s["expired"] += 1
        elif state == "soon":
            s["soon"] += 1
    return render_template("employees.html", employees=members, summary=summary)


@app.route("/accounts")
@admin_required
def accounts_page():
    """Admin roster of who can sign in and who's an admin, the household
    members who don't have a login yet, and any pending password-change
    requests."""
    db = get_db()
    members = db.execute(
        "SELECT id, name, username, is_admin, COALESCE(password_hash,'') AS pw"
        " FROM household_members ORDER BY name").fetchall()
    with_login = [m for m in members if (m["username"] or "")]
    without_login = [m for m in members if not (m["username"] or "")]
    admin_count = sum(1 for m in with_login if str(m["is_admin"] or "") == "1")
    pending = db.execute(
        "SELECT pr.*, m.name AS emp_name, m.username FROM password_requests pr"
        " JOIN household_members m ON m.id = pr.household_member_id"
        " WHERE pr.status = 'Pending' ORDER BY pr.requested_at").fetchall()
    # Piece 19.2: flag usernames that collide case-insensitively — now that
    # login ignores case, two such accounts would be ambiguous.
    by_lower = {}
    for m in with_login:
        by_lower.setdefault((m["username"] or "").lower(), []).append(m)
    dup_usernames = [group for group in by_lower.values() if len(group) > 1]
    return render_template("accounts.html", with_login=with_login,
                           without_login=without_login, admin_count=admin_count,
                           pending=pending, dup_usernames=dup_usernames)


@app.route("/accounts/password-requests/<int:req_id>/approve", methods=["POST"])
@admin_required
def approve_password_change(req_id):
    db = get_db()
    req = db.execute(
        "SELECT * FROM password_requests WHERE id = ? AND status = 'Pending'",
        (req_id,)).fetchone()
    if req:
        db.execute("UPDATE household_members SET password_hash = ? WHERE id = ?",
                   (req["new_hash"], req["household_member_id"]))
        who = current_user()
        db.execute(
            "UPDATE password_requests SET status = 'Approved',"
            " resolved_at = datetime('now'), resolved_by = ? WHERE id = ?",
            (who["name"] if who else "", req_id))
        db.commit()
        flash("Password change approved and applied.")
    return redirect(url_for("accounts_page"))


@app.route("/accounts/password-requests/<int:req_id>/reject", methods=["POST"])
@admin_required
def reject_password_change(req_id):
    db = get_db()
    who = current_user()
    db.execute(
        "UPDATE password_requests SET status = 'Rejected',"
        " resolved_at = datetime('now'), resolved_by = ?"
        " WHERE id = ? AND status = 'Pending'",
        (who["name"] if who else "", req_id))
    db.commit()
    flash("Password change rejected.")
    return redirect(url_for("accounts_page"))


def _apply_household_member_auth(db, household_member_id):
    """Set or clear this household member's login from the form's Login
    fields, and their is_admin flag. A blank username removes the login; the
    password hash is rewritten only when a new password is supplied, so
    editing other fields never disturbs an existing password. Guards against
    leaving accounts configured with no admin (which would lock everyone out
    of admin functions)."""
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    is_admin_flag = "1" if request.form.get("is_admin") else ""
    setting_login = bool(username)

    if setting_login:
        # Case-insensitive uniqueness so "Trish" and "trish" can't both exist.
        clash = db.execute(
            "SELECT id FROM household_members WHERE LOWER(username) = LOWER(?) AND id != ?",
            (username, household_member_id)).fetchone()
        if clash:
            flash(f"Username “{username}” is already taken — login unchanged.", "error")
            return

    existing_hash = db.execute(
        "SELECT COALESCE(password_hash,'') FROM household_members WHERE id = ?",
        (household_member_id,)).fetchone()[0]
    this_usable = setting_login and (bool(password) or bool(existing_hash))
    this_admin = this_usable and is_admin_flag == "1"
    other_accounts = db.execute(
        "SELECT COUNT(*) FROM household_members WHERE id != ?"
        " AND COALESCE(username,'') != '' AND COALESCE(password_hash,'') != ''",
        (household_member_id,)).fetchone()[0]
    other_admins = db.execute(
        "SELECT COUNT(*) FROM household_members WHERE id != ? AND is_admin = '1'"
        " AND COALESCE(username,'') != '' AND COALESCE(password_hash,'') != ''",
        (household_member_id,)).fetchone()[0]
    total_accounts = other_accounts + (1 if this_usable else 0)
    total_admins = other_admins + (1 if this_admin else 0)
    if total_accounts > 0 and total_admins == 0:
        flash("Keep at least one admin account — or remove every login to go"
              " back to open access. Login unchanged.", "error")
        return

    db.execute("UPDATE household_members SET is_admin = ? WHERE id = ?",
               (is_admin_flag, household_member_id))
    if setting_login:
        db.execute("UPDATE household_members SET username = ? WHERE id = ?",
                   (username, household_member_id))
        if password:
            db.execute("UPDATE household_members SET password_hash = ? WHERE id = ?",
                       (generate_password_hash(password, method="pbkdf2:sha256"), household_member_id))
        elif not existing_hash:
            flash("Login saved — set a password to activate it.", "error")
    else:
        db.execute(
            "UPDATE household_members SET username = '', password_hash = ''"
            " WHERE id = ?", (household_member_id,))


@app.route("/household-members/new", methods=["GET", "POST"])
@admin_required
def new_household_member():
    if request.method == "POST":
        values, errors = read_household_member_form()
        username = request.form.get("username", "").strip()
        if errors:
            flash(" ".join(errors), "error")
            return render_household_member_form(values, username=username), 400
        db = get_db()
        # Guard against accidental duplicates: same composed name already on the
        # roster. Allow it only when the user confirms it's a different person.
        dup = db.execute("SELECT name FROM household_members WHERE LOWER(name) = LOWER(?)",
                         (values["name"],)).fetchone()
        if dup and not request.form.get("confirm_duplicate"):
            return render_household_member_form(
                values, username=username, duplicate_warning=values["name"]), 400
        cur = db.execute(
            f"INSERT INTO household_members ({', '.join(HOUSEHOLD_MEMBER_FIELDS)})"
            f" VALUES ({', '.join('?' * len(HOUSEHOLD_MEMBER_FIELDS))})",
            [values[f] for f in HOUSEHOLD_MEMBER_FIELDS],
        )
        _apply_household_member_auth(db, cur.lastrowid)
        db.commit()
        flash(f"Household member added: {values['name']}")
        return redirect(url_for("household_member_detail", household_member_id=cur.lastrowid))
    return render_household_member_form({})


@app.route("/household-members/<int:household_member_id>")
def household_member_detail(household_member_id):
    db = get_db()
    member = db.execute(
        "SELECT * FROM household_members WHERE id = ?", (household_member_id,)
    ).fetchone()
    if member is None:
        abort(404)
    files = db.execute(
        "SELECT * FROM household_member_files WHERE household_member_id = ? ORDER BY id",
        (household_member_id,)
    ).fetchall()
    documented = {f["credential_name"] for f in files if f["credential_name"]}
    credentials = []
    for c in db.execute(
            "SELECT * FROM household_member_credentials WHERE household_member_id = ?"
            " ORDER BY name", (household_member_id,)).fetchall():
        state, text = credential_status(c["expires"])
        credentials.append({"row": c, "state": state, "status_text": text,
                            "documented": c["name"] in documented})
    # License requirement labels, for the "satisfies requirement" dropdown.
    license_labels = [r["label"] for r in db.execute(
        "SELECT DISTINCT label FROM resource_rules WHERE category = 'License'"
        " ORDER BY label").fetchall()]
    # Piece 10: everything assigned to this person, across all projects. Open
    # (not-Done) tasks first, then by due date, so what's pending is on top.
    assigned_tasks = db.execute(
        "SELECT t.*, j.job_name, j.id AS project_id"
        " FROM project_tasks t"
        " JOIN projects j ON j.id = t.project_id"
        " WHERE t.household_member_id = ?"
        " ORDER BY (t.status = 'Done'), (t.due_date = ''), t.due_date, t.id",
        (household_member_id,)).fetchall()
    # Piece 25.0: in-place edit — ?edit_credential pre-fills the add form.
    edit_credential = None
    if request.args.get("edit_credential", type=int):
        edit_credential = db.execute(
            "SELECT * FROM household_member_credentials WHERE id = ? AND household_member_id = ?",
            (request.args.get("edit_credential", type=int), household_member_id)).fetchone()
    return render_template(
        "employee_detail.html", employee=member, role=member["role"],
        credentials=credentials, files=files, license_labels=license_labels,
        cred_names=[c["row"]["name"] for c in credentials],
        assigned_tasks=assigned_tasks, task_statuses=TASK_STATUSES,
        edit_credential=edit_credential,
        today=datetime.now().strftime("%Y-%m-%d"),
    )


@app.route("/household-members/<int:household_member_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_household_member(household_member_id):
    db = get_db()
    member = db.execute(
        "SELECT * FROM household_members WHERE id = ?", (household_member_id,)
    ).fetchone()
    if member is None:
        abort(404)
    if request.method == "POST":
        values, errors = read_household_member_form()
        if errors:
            flash(" ".join(errors), "error")
            return render_household_member_form(values, household_member_id=household_member_id), 400
        db.execute(
            f"UPDATE household_members SET {', '.join(f + ' = ?' for f in HOUSEHOLD_MEMBER_FIELDS)}"
            " WHERE id = ?",
            [values[f] for f in HOUSEHOLD_MEMBER_FIELDS] + [household_member_id],
        )
        _apply_household_member_auth(db, household_member_id)
        db.commit()
        flash(f"Household member updated: {values['name']}")
        return redirect(url_for("household_member_detail", household_member_id=household_member_id))
    values = {f: member[f] for f in HOUSEHOLD_MEMBER_FIELDS}
    return render_household_member_form(
        values, household_member_id=household_member_id,
        username=member["username"] or "",
        is_admin_checked=member["is_admin"] or "")


@app.route("/household-members/<int:household_member_id>/delete", methods=["GET", "POST"])
@admin_required
def delete_household_member(household_member_id):
    """Admin offboarding. GET shows a confirmation page that asks for a
    reason (captured in the audit log); POST detaches their live work
    (unassigns tasks), removes their login / access grants / licenses /
    documents, then sends them to the Trash (an admin can restore or
    permanently delete). Blocked if they have field-work submissions on
    record, so approved-hours history isn't lost."""
    db = get_db()
    member = db.execute("SELECT * FROM household_members WHERE id = ?",
                        (household_member_id,)).fetchone()
    if member is None:
        abort(404)
    task_count = _count(db, "SELECT COUNT(*) FROM project_tasks WHERE household_member_id = ?", (household_member_id,))
    sub_count = _count(db, "SELECT COUNT(*) FROM field_submissions WHERE household_member_id = ?", (household_member_id,))
    if request.method == "POST":
        reason = request.form.get("reason", "").strip()
        if not reason:
            flash("A reason is required to remove a household member.", "error")
            return render_template("employee_remove.html", employee=member,
                                   task_count=task_count,
                                   sub_count=sub_count), 400
        if sub_count:
            flash("This household member has field-work submissions on record "
                  "(approved hours) — handle those first. Removal cancelled.", "error")
            return redirect(url_for("household_member_detail", household_member_id=household_member_id))
        db.execute("UPDATE project_tasks SET household_member_id = NULL,"
                   " updated_at = strftime('%Y-%m-%d %H:%M:%f','now')"
                   " WHERE household_member_id = ?", (household_member_id,))
        db.execute("DELETE FROM permission_grants WHERE household_member_id = ?", (household_member_id,))
        db.execute("DELETE FROM password_requests WHERE household_member_id = ?", (household_member_id,))
        db.execute("DELETE FROM security_answers WHERE household_member_id = ?", (household_member_id,))
        for f in db.execute("SELECT stored_name FROM household_member_files"
                            " WHERE household_member_id = ?", (household_member_id,)).fetchall():
            (household_member_upload_dir(household_member_id) / f["stored_name"]).unlink(missing_ok=True)
        db.execute("DELETE FROM household_member_files WHERE household_member_id = ?", (household_member_id,))
        db.execute("DELETE FROM household_member_credentials WHERE household_member_id = ?", (household_member_id,))
        db.execute("UPDATE household_members SET username = '', password_hash = '',"
                   " is_admin = '' WHERE id = ?", (household_member_id,))
        db.commit()
        ok, msg = trash_item("employee", household_member_id)  # tasks detached above
        flash(f"{member['name']} removed — reason recorded in the audit log. {msg}"
              if ok else msg, "" if ok else "error")
        return redirect(url_for("household_members_page") if ok
                        else url_for("household_member_detail", household_member_id=household_member_id))
    return render_template("employee_remove.html", employee=member,
                           task_count=task_count,
                           sub_count=sub_count)


# ---- household member licenses & certifications (structured, with expiry) ----
@app.route("/household-members/<int:household_member_id>/credentials/add", methods=["POST"])
@admin_required
def add_credential(household_member_id):
    if get_db().execute("SELECT id FROM household_members WHERE id = ?",
                        (household_member_id,)).fetchone() is None:
        abort(404)
    name = request.form.get("name", "").strip()
    if not name:
        flash("A license/certification needs a name.", "error")
        return redirect(url_for("household_member_detail", household_member_id=household_member_id, _anchor="licenses"))
    db = get_db()
    db.execute(
        "INSERT INTO household_member_credentials"
        " (household_member_id, name, rule_label, number, issued, expires, notes)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (household_member_id, name,
         request.form.get("rule_label", "").strip(),
         request.form.get("number", "").strip(),
         request.form.get("issued", "").strip(),
         request.form.get("expires", "").strip(),
         request.form.get("notes", "").strip()),
    )
    db.commit()
    flash(f"Added license/certification: {name}")
    return redirect(url_for("household_member_detail", household_member_id=household_member_id, _anchor="licenses"))


@app.route("/household-members/<int:household_member_id>/credentials/<int:credential_id>/edit",
           methods=["POST"])
@admin_required
def update_credential(household_member_id, credential_id):
    db = get_db()
    if db.execute("SELECT 1 FROM household_member_credentials WHERE id = ?"
                  " AND household_member_id = ?", (credential_id, household_member_id)).fetchone() is None:
        abort(404)
    name = request.form.get("name", "").strip()
    if not name:
        flash("A license/certification needs a name.", "error")
        return redirect(url_for("household_member_detail", household_member_id=household_member_id,
                                edit_credential=credential_id, _anchor="licenses"))
    db.execute(
        "UPDATE household_member_credentials SET name = ?, rule_label = ?, number = ?,"
        " issued = ?, expires = ?, notes = ? WHERE id = ?",
        (name, request.form.get("rule_label", "").strip(),
         request.form.get("number", "").strip(),
         request.form.get("issued", "").strip(),
         request.form.get("expires", "").strip(),
         request.form.get("notes", "").strip(), credential_id))
    db.commit()
    flash(f"Updated license/certification: {name}")
    return redirect(url_for("household_member_detail", household_member_id=household_member_id, _anchor="licenses"))


@app.route("/household-members/<int:household_member_id>/credentials/<int:credential_id>/delete",
           methods=["POST"])
@delete_required
def delete_credential(household_member_id, credential_id):
    ok, msg = trash_item("credential", credential_id)
    flash(msg, "" if ok else "error")
    return redirect(url_for("household_member_detail", household_member_id=household_member_id, _anchor="licenses"))


# ---- household member documents (copies of certifications, etc.) ---------
def household_member_upload_dir(household_member_id):
    directory = UPLOADS_DIR / f"employee_{household_member_id}"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


@app.route("/household-members/<int:household_member_id>/files/upload", methods=["POST"])
@admin_required
def upload_household_member_file(household_member_id):
    if get_db().execute("SELECT id FROM household_members WHERE id = ?",
                        (household_member_id,)).fetchone() is None:
        abort(404)
    upload = request.files.get("document")
    if upload is None or not upload.filename:
        flash("Choose a file to upload.", "error")
        return redirect(url_for("household_member_detail", household_member_id=household_member_id, _anchor="documents"))
    extension = upload.filename.rsplit(".", 1)[-1].lower() if "." in upload.filename else ""
    if extension not in ALLOWED_EXTENSIONS:
        flash(f"File type .{extension} is not allowed.", "error")
        return redirect(url_for("household_member_detail", household_member_id=household_member_id, _anchor="documents"))
    db = get_db()
    credential_name = request.form.get("credential_name", "").strip()
    # Piece 25.4: auto-rename to Member_Credential_Date.ext for recordkeeping.
    mname = db.execute("SELECT name FROM household_members WHERE id = ?",
                       (household_member_id,)).fetchone()
    friendly = friendly_filename(
        [mname["name"] if mname else "", credential_name or "Document"], extension,
        taken=_taken_names(db, "household_member_files", "original_name",
                           "household_member_id", household_member_id))
    stored = f"{uuid.uuid4().hex[:8]}_{secure_filename(friendly)}"
    upload.save(household_member_upload_dir(household_member_id) / stored)
    db.execute(
        "INSERT INTO household_member_files"
        " (household_member_id, credential_name, stored_name, original_name)"
        " VALUES (?, ?, ?, ?)",
        (household_member_id, credential_name, stored, friendly),
    )
    db.commit()
    flash(f"Uploaded: {friendly}")
    return redirect(url_for("household_member_detail", household_member_id=household_member_id, _anchor="documents"))


@app.route("/household-members/<int:household_member_id>/files/<int:file_id>/download")
def download_household_member_file(household_member_id, file_id):
    record = get_db().execute(
        "SELECT * FROM household_member_files WHERE id = ? AND household_member_id = ?",
        (file_id, household_member_id)).fetchone()
    if record is None:
        abort(404)
    return send_from_directory(
        household_member_upload_dir(household_member_id), record["stored_name"],
        as_attachment=True, download_name=record["original_name"])


@app.route("/household-members/<int:household_member_id>/files/<int:file_id>/delete",
           methods=["POST"])
@delete_required
def delete_household_member_file(household_member_id, file_id):
    ok, msg = trash_item("employee_file", file_id)
    flash(msg, "" if ok else "error")
    return redirect(url_for("household_member_detail", household_member_id=household_member_id, _anchor="documents"))


@app.route("/audit")
@admin_required
def audit_log_page():
    """Read-only view of the system audit log, newest first, filterable by
    action. Admin-oriented — will sit behind role access once logins land."""
    db = get_db()
    action = request.args.get("action", "")
    sql = "SELECT * FROM audit_log"
    params = []
    if action:
        sql += " WHERE action = ?"
        params.append(action)
    sql += " ORDER BY id DESC LIMIT 300"
    entries = []
    for e in db.execute(sql, params).fetchall():
        try:
            entity = json.loads(e["entity"] or "{}")
        except ValueError:
            entity = {}
        try:
            detail = json.loads(e["detail"] or "{}")
        except ValueError:
            detail = {}
        entries.append({
            "ts": e["ts"], "actor": e["actor"], "action": e["action"],
            "path": e["path"], "status": e["status"], "ip": e["ip"],
            "entity": entity, "detail": detail,
        })
    actions = [r["action"] for r in db.execute(
        "SELECT DISTINCT action FROM audit_log ORDER BY action").fetchall()]
    total = db.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    return render_template("audit.html", entries=entries, actions=actions,
                           action=action, total=total)


# ---------------------- Piece 25.3: background scheduler ----------------------
# Time-based generation (lead follow-ups) used to run only when someone opened
# the home / dashboard / task pages. This daemon timer runs the same maintenance
# every SCHEDULER_INTERVAL regardless, so nothing stalls while the app sits
# unattended. The on-page-load calls stay as a cheap immediacy fallback — every
# step here is idempotent, so running it both ways is harmless.
SCHEDULER_INTERVAL_SECONDS = 15 * 60
_scheduler_started = False
_scheduler_lock = threading.Lock()


def run_maintenance():
    """One maintenance pass, off the request path. Uses its own connection with
    a Row factory (the request-scoped get_db isn't available in a bare thread)."""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    try:
        ensure_backlog_reminders(conn)
    finally:
        conn.close()


def _scheduler_tick():
    try:
        run_maintenance()
    except Exception as exc:            # never let a bad pass kill the timer
        app.logger.warning("scheduler maintenance failed: %s", exc)
    finally:
        _arm_timer()


def _arm_timer():
    timer = threading.Timer(SCHEDULER_INTERVAL_SECONDS, _scheduler_tick)
    timer.daemon = True                # dies with the process; never blocks exit
    timer.start()


def start_scheduler():
    """Start the background maintenance timer once per process (idempotent)."""
    global _scheduler_started
    with _scheduler_lock:
        if _scheduler_started:
            return
        _scheduler_started = True
    _arm_timer()


@app.before_request
def _lazy_start_scheduler():
    # Start on first request so it works under `python app.py` (incl. the debug
    # reloader — only the serving child gets requests) and any WSGI server.
    if not _scheduler_started:
        start_scheduler()


# ============================================================================
# Piece 32.0: Compendium AI assistant — a read-only, permission-scoped chat over the
# business data. Uses Claude and/or Gemini (selectable); keys live in `meta`.
# Online-only: the model is called live, so it degrades gracefully offline.
# ============================================================================
ASSISTANT_SYSTEM_PROMPT = (
    "You are the Compendium Assistant, a helpful internal aide for the Vixinman "
    "household. You answer questions about the household's projects, tasks, "
    "the idea backlog, and schedule.\n\n"
    "You are given a COMPENDIUM DATA snapshot for quick orientation, plus a set of "
    "read-only tools to look things up live. Use the tools whenever the answer "
    "needs specifics beyond the snapshot (a particular project, filtered lists, "
    "someone's tasks). Prefer tools over guessing, and you may "
    "call several in a row to narrow things down.\n\n"
    "Everything you can see — snapshot and tools alike — is already limited to "
    "what THIS signed-in user is permitted to see. Never invent projects, names, "
    "numbers, or dates; if the tools don't return something, say so plainly and "
    "suggest where in Compendium to look. Be concise and specific; use short lists "
    "for multiple items. You are read-only: you cannot change data, so if asked "
    "to do something, explain how the user can do it in Compendium."
)


def assistant_settings(db):
    """Current AI-assistant configuration, read from `meta`."""
    return {
        "default_provider": _meta_get(db, "ai_default_provider", "claude") or "claude",
        "claude_key": _meta_get(db, "ai_claude_key", ""),
        "claude_model": _meta_get(db, "ai_claude_model",
                                  ai_assistant.CLAUDE_DEFAULT_MODEL)
                        or ai_assistant.CLAUDE_DEFAULT_MODEL,
        "gemini_key": _meta_get(db, "ai_gemini_key", ""),
        "gemini_model": _meta_get(db, "ai_gemini_model",
                                  ai_assistant.GEMINI_DEFAULT_MODEL)
                        or ai_assistant.GEMINI_DEFAULT_MODEL,
    }


def _provider_configured(cfg, provider):
    return bool((cfg["gemini_key"] if provider == "gemini" else cfg["claude_key"]).strip())


def assistant_available_providers(cfg):
    """Which providers have a key set, so the UI only offers usable ones."""
    out = []
    if _provider_configured(cfg, "claude"):
        out.append("claude")
    if _provider_configured(cfg, "gemini"):
        out.append("gemini")
    return out


def build_assistant_snapshot(db, user):
    """A compact, permission-scoped snapshot of the current business state, given
    to the model as grounding context. Respects what THIS user may see — pricing
    and payroll figures are only included for those who can already view them."""
    lines = []
    name = user["name"] if user else "the user"
    role = (user["role"] or "") if user else ""
    lines.append(f"Signed-in user: {name} — role: {role or 'none'}.")
    can_price = _can_see_pricing()
    lines.append("Viewer may see internal pricing/margins: "
                 f"{'yes' if can_price else 'no'}.")
    today = datetime.now().strftime("%Y-%m-%d")
    lines.append(f"Today is {today}.")

    # Projects by pipeline stage (visible to everyone).
    by_stage = db.execute(
        "SELECT status, COUNT(*) c FROM projects GROUP BY status").fetchall()
    if by_stage:
        counts = ", ".join(f"{r['status'] or 'Unset'}: {r['c']}" for r in by_stage)
        lines.append(f"Projects by stage — {counts}.")

    # Active (non-terminal) projects, capped for token budget.
    active = db.execute(
        "SELECT job_name, status, install_date FROM projects"
        " WHERE status NOT IN ('Done','Abandoned')"
        " ORDER BY (install_date = ''), install_date, id LIMIT 40"
    ).fetchall()
    if active:
        lines.append("Active projects (project — stage — install date):")
        for r in active:
            lines.append(
                f"  • {r['job_name'] or 'Project'} — {r['status']}"
                f" — install {r['install_date'] or 'TBD'}")

    # This user's own open tasks.
    if user:
        mine = db.execute(
            "SELECT t.title, t.status, t.due_date, j.job_name"
            " FROM project_tasks t JOIN projects j ON j.id = t.project_id"
            " WHERE t.household_member_id = ? AND t.status != 'Done' AND j.status != 'Abandoned'"
            " ORDER BY (t.due_date = ''), t.due_date LIMIT 25", (user["id"],)
        ).fetchall()
        if mine:
            lines.append(f"{name}'s open tasks (task — project — due):")
            for r in mine:
                lines.append(
                    f"  • {r['title']} — {r['job_name'] or 'Project'}"
                    f" — due {r['due_date'] or 'no date'} [{r['status']}]")
        else:
            lines.append(f"{name} has no open tasks assigned.")

    # Overdue open tasks across the company (status is not sensitive).
    overdue = db.execute(
        "SELECT COUNT(*) FROM project_tasks t JOIN projects j ON j.id = t.project_id"
        " WHERE t.status != 'Done' AND j.status != 'Abandoned'"
        " AND COALESCE(t.due_date,'') != '' AND t.due_date < ?", (today,)
    ).fetchone()[0]
    lines.append(f"Company-wide overdue open tasks: {overdue}.")

    # Contract totals only for pricing-cleared viewers.
    if can_price:
        row = db.execute(
            "SELECT COUNT(*) n, COALESCE(SUM(contract_amount),0) t FROM projects"
            " WHERE status NOT IN ('Done','Abandoned')"
            " AND COALESCE(contract_amount,0) > 0").fetchone()
        if row and row["n"]:
            lines.append(
                f"Active projects with a contract total: {row['n']}, "
                f"summing ${row['t']:,.0f}.")

    return "\n".join(lines)


@app.route("/assistant")
def assistant_page():
    db = get_db()
    cfg = assistant_settings(db)
    providers = assistant_available_providers(cfg)
    default = cfg["default_provider"] if cfg["default_provider"] in providers else (
        providers[0] if providers else "claude")
    return render_template(
        "assistant.html", providers=providers, default_provider=default,
        is_admin=_is_admin())


def _assist_money(n):
    try:
        return f"${float(n or 0):,.0f}"
    except (TypeError, ValueError):
        return "$0"


def build_assistant_tools(db, user):
    """Piece 32.1: read-only, permission-scoped tools the assistant may call to
    look data up live. Every tool respects what the signed-in user may see —
    pricing/contract figures are withheld from non-pricing viewers, and no tool
    exposes pay. Each returns a compact text block for the model to read."""
    can_price = _can_see_pricing()

    def find_projects(args):
        text = (args.get("text") or "").strip()
        stage = (args.get("stage") or "").strip()
        county = (args.get("county") or "").strip()
        overdue_only = bool(args.get("overdue_only"))
        try:
            limit = min(int(args.get("limit") or 25), 50)
        except (TypeError, ValueError):
            limit = 25
        where, params = ["1=1"], []
        if text:
            where.append("j.job_name LIKE ?"); params.append(f"%{text}%")
        if stage:
            where.append("j.status = ?"); params.append(stage)
        if county:
            where.append("j.county LIKE ?"); params.append(f"%{county}%")
        # min_contract only applies for pricing-cleared viewers; silently ignored
        # otherwise so the filter can't be used to probe hidden figures.
        if can_price and args.get("min_contract") not in (None, ""):
            try:
                where.append("COALESCE(j.contract_amount,0) >= ?")
                params.append(float(args.get("min_contract")))
            except (TypeError, ValueError):
                pass
        today = datetime.now().strftime("%Y-%m-%d")
        if overdue_only:
            where.append(
                "EXISTS (SELECT 1 FROM project_tasks t WHERE t.project_id = j.id"
                " AND t.status != 'Done' AND COALESCE(t.due_date,'') != ''"
                " AND t.due_date < ?)")
            params.append(today)
        rows = db.execute(
            "SELECT id, job_name, status, install_date, county,"
            "  COALESCE(contract_amount,0) AS amt"
            " FROM projects j"
            f" WHERE {' AND '.join(where)}"
            " ORDER BY (install_date = ''), install_date, id LIMIT ?",
            params + [limit]).fetchall()
        if not rows:
            return "No projects match those filters."
        out = [f"{len(rows)} project(s):"]
        for r in rows:
            line = (f"#{r['id']} {r['job_name'] or 'Project'} — "
                    f"{r['status']} — install {r['install_date'] or 'TBD'}"
                    f"{' — ' + r['county'] if r['county'] else ''}")
            if can_price and r["amt"]:
                line += f" — contract {_assist_money(r['amt'])}"
            out.append("• " + line)
        return "\n".join(out)

    def project_details(args):
        ident = (args.get("project") or "").strip()
        if not ident:
            return "Provide a project name or #id."
        row = None
        if ident.lstrip("#").isdigit():
            row = db.execute(
                "SELECT * FROM projects WHERE id = ?",
                (int(ident.lstrip("#")),)).fetchone()
        if row is None:
            row = db.execute(
                "SELECT * FROM projects WHERE job_name LIKE ? ORDER BY id LIMIT 1",
                (f"%{ident}%",)).fetchone()
        if row is None:
            return f"No project found matching '{ident}'."
        out = [f"Project #{row['id']}: {row['job_name'] or 'Project'}",
               f"Stage: {row['status']}",
               f"Install date: {row['install_date'] or 'TBD'}",
               f"County: {row['county'] or '—'}",
               f"Payment: {row['cost_method'] or '—'}"]
        if can_price and (row["contract_amount"] or 0):
            out.append(f"Contract total: {_assist_money(row['contract_amount'])}")
        if (row["status"] or "") == "Abandoned" and (row["cancel_reason"] or ""):
            out.append(f"Cancelled — reason: {row['cancel_reason']}")
        tasks = db.execute(
            "SELECT title, status, due_date, COALESCE(pipeline_status,'') AS ps"
            " FROM project_tasks WHERE project_id = ? AND status != 'Done'"
            " ORDER BY (due_date=''), due_date LIMIT 20", (row["id"],)).fetchall()
        if tasks:
            out.append(f"Open tasks ({len(tasks)}):")
            for t in tasks:
                out.append(f"  • {t['title']} — due {t['due_date'] or 'no date'}"
                           f" [{t['status']}{'/' + t['ps'] if t['ps'] else ''}]")
        else:
            out.append("No open tasks.")
        mats = db.execute(
            "SELECT status, COUNT(*) c FROM project_materials WHERE project_id = ?"
            " GROUP BY status", (row["id"],)).fetchall()
        if mats:
            out.append("Materials: " + ", ".join(f"{m['status'] or '—'}: {m['c']}"
                                                  for m in mats))
        notes = db.execute(
            "SELECT note, created_at FROM project_notes WHERE project_id = ?"
            " ORDER BY id DESC LIMIT 3", (row["id"],)).fetchall()
        if notes:
            out.append("Recent field notes:")
            for n in notes:
                out.append(f"  • {(n['created_at'] or '')[:10]}: {n['note']}")
        return "\n".join(out)

    def list_tasks(args):
        assignee = (args.get("assignee") or "").strip()
        overdue_only = bool(args.get("overdue_only"))
        stage = (args.get("stage") or "").strip()
        try:
            limit = min(int(args.get("limit") or 30), 60)
        except (TypeError, ValueError):
            limit = 30
        where = ["t.status != 'Done'", "j.status != 'Abandoned'"]
        params = []
        if assignee.lower() in ("me", "mine") and user:
            where.append("t.household_member_id = ?"); params.append(user["id"])
        elif assignee:
            where.append("e.name LIKE ?"); params.append(f"%{assignee}%")
        if stage:
            where.append("t.pipeline_status = ?"); params.append(stage)
        today = datetime.now().strftime("%Y-%m-%d")
        if overdue_only:
            where.append("COALESCE(t.due_date,'') != '' AND t.due_date < ?")
            params.append(today)
        rows = db.execute(
            "SELECT t.title, t.status, t.due_date, j.job_name,"
            "  COALESCE(e.name,'') AS who"
            " FROM project_tasks t JOIN projects j ON j.id = t.project_id"
            " LEFT JOIN household_members e ON e.id = t.household_member_id"
            f" WHERE {' AND '.join(where)}"
            " ORDER BY (t.due_date=''), t.due_date LIMIT ?",
            params + [limit]).fetchall()
        if not rows:
            return "No matching open tasks."
        out = [f"{len(rows)} task(s):"]
        for r in rows:
            out.append(f"• {r['title']} — {r['job_name'] or 'Project'}"
                       f" — due {r['due_date'] or 'no date'}"
                       f"{' — ' + r['who'] if r['who'] else ' — unassigned'}")
        return "\n".join(out)

    def staff_directory(args):
        role = (args.get("role") or "").strip()
        where, params = ["1=1"], []
        if role:
            where.append("role LIKE ?"); params.append(f"%{role}%")
        rows = db.execute(
            f"SELECT name, COALESCE(role,'') AS role FROM household_members"
            f" WHERE {' AND '.join(where)} ORDER BY name LIMIT 60", params).fetchall()
        if not rows:
            return "No household members match."
        return "\n".join(f"• {r['name']} — {r['role'] or 'no role'}" for r in rows)

    stages = ", ".join(PROJECT_STATUSES)
    return [
        {"name": "find_projects",
         "description": ("Search projects with optional filters. Use for questions like "
                         "'projects in Prep', 'projects in Bernalillo county', 'overdue "
                         "projects', or a project name search."),
         "parameters": {"type": "object", "properties": {
             "text": {"type": "string", "description": "match project name"},
             "stage": {"type": "string", "description": f"pipeline stage; one of: {stages}"},
             "county": {"type": "string", "description": "NM county name"},
             "overdue_only": {"type": "boolean", "description": "only projects with an overdue task"},
             "min_contract": {"type": "number", "description": "minimum contract total (only honored for pricing-cleared users)"},
             "limit": {"type": "integer", "description": "max rows (default 25)"}}},
         "run": find_projects},
        {"name": "project_details",
         "description": ("Full detail for one project by name or #id: stage, install "
                         "date, payment, open tasks, materials, recent notes "
                         "(and contract total if you may see pricing)."),
         "parameters": {"type": "object", "properties": {
             "project": {"type": "string", "description": "project name or #id"}},
             "required": ["project"]},
         "run": project_details},
        {"name": "list_tasks",
         "description": ("List open tasks. assignee 'me' for the current user, or a "
                         "name; optional overdue_only and stage filters."),
         "parameters": {"type": "object", "properties": {
             "assignee": {"type": "string", "description": "'me' or a person's name"},
             "overdue_only": {"type": "boolean"},
             "stage": {"type": "string", "description": f"pipeline stage; one of: {stages}"},
             "limit": {"type": "integer", "description": "max rows (default 30)"}}},
         "run": list_tasks},
        {"name": "staff_directory",
         "description": "List household members and their role. Optional role filter"
                        " (Parent/Child/Assistant).",
         "parameters": {"type": "object", "properties": {
             "role": {"type": "string", "description": "filter by role name"}}},
         "run": staff_directory},
    ]


@app.route("/assistant/ask", methods=["POST"])
def assistant_ask():
    db = get_db()
    cfg = assistant_settings(db)
    question = (request.form.get("question", "") or "").strip()
    provider = request.form.get("provider", cfg["default_provider"]) or "claude"
    if provider not in ("claude", "gemini"):
        provider = "claude"
    if not question:
        return jsonify({"error": "Ask a question first."}), 400
    if not _provider_configured(cfg, provider):
        return jsonify({"error": f"No API key is set for {provider.title()}. "
                        "An admin can add one under AI settings."}), 400
    user = current_user()
    snapshot = build_assistant_snapshot(db, user)
    prompt = (f"COMPENDIUM DATA (only what {user['name'] if user else 'this user'} "
              f"may see):\n{snapshot}\n\nQUESTION: {question}")
    key = cfg["gemini_key"] if provider == "gemini" else cfg["claude_key"]
    model = cfg["gemini_model"] if provider == "gemini" else cfg["claude_model"]
    tools = build_assistant_tools(db, user)
    try:
        answer = ai_assistant.run_agent(provider, key, model,
                                        ASSISTANT_SYSTEM_PROMPT, prompt, tools)
    except ai_assistant.AssistantError as e:
        return jsonify({"error": str(e)}), 502
    return jsonify({"answer": answer, "provider": provider})


@app.route("/assistant/settings", methods=["GET", "POST"])
@admin_required
def assistant_settings_page():
    db = get_db()
    if request.method == "POST":
        _meta_set(db, "ai_default_provider",
                  request.form.get("default_provider", "claude") or "claude")
        _meta_set(db, "ai_claude_model",
                  request.form.get("claude_model", "").strip()
                  or ai_assistant.CLAUDE_DEFAULT_MODEL)
        _meta_set(db, "ai_gemini_model",
                  request.form.get("gemini_model", "").strip()
                  or ai_assistant.GEMINI_DEFAULT_MODEL)
        # Only overwrite a key when a new value is typed (blank = keep existing).
        for field, meta_key in (("claude_key", "ai_claude_key"),
                                ("gemini_key", "ai_gemini_key")):
            val = request.form.get(field, "")
            if val.strip():
                _meta_set(db, meta_key, val.strip())
            elif request.form.get(f"clear_{field}"):
                _meta_set(db, meta_key, "")
        db.commit()
        flash("AI assistant settings saved.")
        return redirect(url_for("assistant_settings_page"))
    cfg = assistant_settings(db)
    return render_template(
        "assistant_settings.html", cfg=cfg, claude_models=ai_assistant.CLAUDE_MODELS,
        gemini_default=ai_assistant.GEMINI_DEFAULT_MODEL)


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
