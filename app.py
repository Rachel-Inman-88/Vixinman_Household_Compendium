"""Job Creator — internal tool for Vixinman Designs.

Piece 1: Flask skeleton backed by SQLite; home page lists client profiles.
Piece 2: "New client" form and individual client profile pages.
Piece 3: job profiles stored under each client.
Piece 4: rules engine — job selections resolve to required licenses,
permits, and compliance items; service tickets; exportable job report.

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

from bpmn_export import build_job_bpmn
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

# The columns a user can fill in on the client form, in display order.
# Piece 15: addresses are entered as separate parts (fewer typos). The parts
# are stored, and the full mailing_address / billing_address strings are
# composed from them so search, the roster, and job pre-fill keep working.
MAILING_PARTS = ["mailing_street", "mailing_city", "mailing_state", "mailing_zip"]
BILLING_PARTS = ["billing_street", "billing_city", "billing_state", "billing_zip"]
CLIENT_SIMPLE_FIELDS = ["name", "phone", "email", "referral_source", "notes",
                        "assigned_rep_id"]
# What the form posts (everything the user types).
CLIENT_FORM_FIELDS = CLIENT_SIMPLE_FIELDS + MAILING_PARTS + BILLING_PARTS
# Every stored column, including the two composed full-address strings.
CLIENT_FIELDS = CLIENT_FORM_FIELDS + ["mailing_address", "billing_address"]

# Human labels for change-history and error messages.
CLIENT_FIELD_LABELS = {
    "name": "Client name", "phone": "Phone number", "email": "Email address",
    "referral_source": "Referral source", "notes": "Notes",
    "assigned_rep_id": "Assigned sales rep",
    "mailing_street": "Mailing street", "mailing_city": "Mailing city",
    "mailing_state": "Mailing state", "mailing_zip": "Mailing ZIP",
    "billing_street": "Billing street", "billing_city": "Billing city",
    "billing_state": "Billing state", "billing_zip": "Billing ZIP",
    "mailing_address": "Mailing address", "billing_address": "Billing address",
}

# Fields that must not be blank, with the labels shown in error messages.
REQUIRED_CLIENT_FIELDS = {
    "name": "Client name",
    "phone": "Phone number",
    "mailing_street": "Mailing street address",
    "mailing_city": "Mailing city",
    "mailing_state": "Mailing state",
    "mailing_zip": "Mailing ZIP code",
    "billing_street": "Billing street address",
    "billing_city": "Billing city",
    "billing_state": "Billing state",
    "billing_zip": "Billing ZIP code",
}


def compose_address(street, city, state, zip_code):
    """Build a single-line address from its parts, skipping blank pieces."""
    region = " ".join(p for p in (state, zip_code) if p)
    return ", ".join(p for p in (street, city, region) if p)


def read_client_form():
    """Pull the posted client fields and compose the full address strings."""
    values = {f: request.form.get(f, "").strip() for f in CLIENT_FORM_FIELDS}
    values["mailing_address"] = compose_address(
        values["mailing_street"], values["mailing_city"],
        values["mailing_state"], values["mailing_zip"])
    values["billing_address"] = compose_address(
        values["billing_street"], values["billing_city"],
        values["billing_state"], values["billing_zip"])
    return values


# ------------------------------------------------------------ lead lifecycle
def ensure_lead_followups(db):
    """Create any follow-up rows that have come due for active leads (7 days /
    2 weeks / 1 month after the client was created). Idempotent."""
    today = datetime.now().strftime("%Y-%m-%d")
    leads = db.execute(
        "SELECT id, assigned_rep_id, created_at FROM clients"
        " WHERE lead_status = 'Lead'").fetchall()
    made = False
    for lead in leads:
        base = (lead["created_at"] or "")[:10]
        if not base:
            continue
        try:
            base_date = datetime.strptime(base, "%Y-%m-%d")
        except ValueError:
            continue
        existing = {r["milestone"] for r in db.execute(
            "SELECT milestone FROM lead_followups WHERE client_id = ?",
            (lead["id"],))}
        for days, milestone in LEAD_FOLLOWUP_SCHEDULE:
            due = (base_date + timedelta(days=days)).strftime("%Y-%m-%d")
            if due <= today and milestone not in existing:
                db.execute(
                    "INSERT INTO lead_followups (client_id, rep_id, milestone,"
                    " due_date, status) VALUES (?, ?, ?, ?, 'Open')",
                    (lead["id"], lead["assigned_rep_id"], milestone, due))
                made = True
    if made:
        db.commit()


def due_followups(db):
    """Open, due-or-overdue follow-ups with client + rep names (for the home
    page and task board)."""
    today = datetime.now().strftime("%Y-%m-%d")
    return db.execute(
        "SELECT f.*, c.name AS client_name, c.phone AS client_phone,"
        " e.name AS rep_name FROM lead_followups f"
        " JOIN clients c ON c.id = f.client_id"
        " LEFT JOIN employees e ON e.id = f.rep_id"
        " WHERE f.status = 'Open' AND f.due_date <= ?"
        " AND c.lead_status = 'Lead'"
        " ORDER BY f.due_date, c.name", (today,)).fetchall()


COLD_LEAD_FIELDS = [
    "name", "phone", "email", "referral_source", "notes",
    "mailing_street", "mailing_city", "mailing_state", "mailing_zip",
    "billing_street", "billing_city", "billing_state", "billing_zip",
    "mailing_address", "billing_address", "assigned_rep_id",
]


def crew_list():
    """Employees for the assigned-rep picker on the client form."""
    return get_db().execute(
        "SELECT id, name FROM employees ORDER BY name").fetchall()

# Job profile columns (products is stored as a comma-separated list).
JOB_FIELDS = [
    "job_name", "site_location", "county", "electric_loads", "utility_provider",
    "warranty_type", "cost_method", "tax_credit", "expand_option", "products",
    "pv_utility_connection", "pv_mounting_type", "pv_manufactured_house",
    "generator_utility_connection", "battery_utility_connection", "service_type",
    "property_type",
]

# Labels used on the report and anywhere a field needs a human name.
JOB_FIELD_LABELS = {
    "job_name": "Job name", "site_location": "Site location",
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
EMPLOYEE_FIELDS = ["name", "first_name", "last_name", "nickname",
                   "roles", "schedule"]
# Piece 13: an employee becomes a login by gaining a username + password +
# access level. Kept off the plain-text EMPLOYEE_FIELDS above and handled
# separately so a normal profile edit never touches account data by accident.
EMPLOYEE_AUTH_FIELDS = ["username", "password_hash", "access_level"]
ACCESS_LEVELS = ["Standard", "Admin"]

# Piece 17: the tools/functions a General Manager can grant to an individual
# (with an optional expiry). GM ⇒ all of these automatically; Admin ⇒ every
# tool below except "delete"; Standard ⇒ only what's granted.
PERMISSIONS = {
    "rules.manage": "Manage rules",
    "catalog.manage": "Manage catalog (appliances & components)",
    "inventory.manage": "Manage inventory (add/edit items, tools, stock)",
    "inventory.register": "Register & print inventory tags (barcodes)",
    "employees.manage": "Manage employees & accounts",
    "approvals": "Approve field work",
    "audit.view": "View the audit log",
    "leads.manage": "Manage cold leads",
    "clients.history": "View client change history",
    "delete": "Delete data (sends it to the trash)",
}
# Piece 24.6: department/role-scoped access. Holding a role confers its module
# permissions automatically, so access follows the org chart instead of needing
# a per-person grant for everyone. A person's effective permissions are the
# union of these role defaults and any explicit grants; the GM still has
# everything, and 'delete' is deliberately never role-conferred (it stays
# GM-or-explicit-grant, preserving the soft-delete safety model).
ROLE_PERMISSIONS = {
    "Operations Manager": {"inventory.manage", "approvals", "audit.view"},
    # The warehouse manager owns tag registration/printing (Piece 26.1); the GM
    # can also grant "inventory.register" to whoever fills that role via /access.
    "Inventory Manager": {"inventory.manage", "inventory.register"},
    "Purchasing Agent": {"inventory.manage"},
    "Warehouse Assistant": {"inventory.manage"},
    "Designer": {"inventory.manage"},          # actions the stale-stock queue
    "Sales & Marketing Manager": {"leads.manage", "clients.history"},
    "Outside Sales Rep": {"leads.manage"},
    "Inside Sales Rep": {"leads.manage"},
    "Administration Manager": {"employees.manage"},
    "Human Resources Manager": {"employees.manage"},
    "Finance Manager": {"approvals", "clients.history"},
    "Research & Development Manager": {"rules.manage", "catalog.manage"},
    "Process Developer": {"rules.manage", "catalog.manage"},
    "Software Developer": {"rules.manage", "catalog.manage"},
}


def roles_of(user):
    """The set of role names a user holds (comma-separated in employees.roles)."""
    if user is None:
        return set()
    return {r.strip() for r in (user["roles"] or "").split(",") if r.strip()}


def permissions_from_roles(user):
    """The permissions a user gets purely from the roles they hold."""
    held = roles_of(user)
    out = set()
    for role in held:
        out |= ROLE_PERMISSIONS.get(role, set())
    return out
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

# Piece 29.2: default new-employee onboarding checklist (title, description,
# category). Seeded once into onboarding_steps; fully editable afterwards.
ONBOARDING_SEED = [
    ("Complete new-hire paperwork", "I-9, W-4, direct-deposit and signed offer letter on file.", "HR"),
    ("Add to payroll & benefits", "Set up in payroll; enrol in health/PTO and set the base wage.", "HR"),
    ("Collect emergency contacts", "Emergency contact and any medical notes recorded.", "HR"),
    ("Create Compendium login & assign roles", "Give a username/password and set their org-chart roles and access.", "IT"),
    ("Review licenses & certifications", "Record any electrical/PV/EPA licenses with expiry dates.", "HR"),
    ("Safety orientation", "Ladder, fall-protection and PPE basics; site-safety expectations.", "Safety"),
    ("Electrical & jobsite safety review", "OSHA-10 / lockout-tagout / arc-flash awareness as applicable.", "Safety"),
    ("Vehicle & driving policy", "Company-vehicle assignment, driving record and fuel-card rules.", "Operations"),
    ("Tool issue & barcode-tag training", "Issue tools; show how to scan/register inventory tags.", "Operations"),
    ("Walk through job workflow & Work Bag", "How jobs flow through the pipeline and how to use the field Work Bag.", "Operations"),
    ("Assign a mentor & first-week schedule", "Pair with an experienced installer and set the first-week plan.", "Operations"),
]


def seed_onboarding_steps(db):
    """Populate the default onboarding checklist once (meta-guarded), so every
    install has a starting template that HR can then tailor."""
    if db.execute("SELECT 1 FROM meta WHERE key = 'onboarding_seeded'").fetchone():
        return
    if db.execute("SELECT COUNT(*) FROM onboarding_steps").fetchone()[0] == 0:
        for order, (title, desc, cat) in enumerate(ONBOARDING_SEED):
            db.execute(
                "INSERT INTO onboarding_steps (title, description, category,"
                " sort_order) VALUES (?, ?, ?, ?)", (title, desc, cat, order))
    db.execute("INSERT INTO meta (key, value) VALUES ('onboarding_seeded', '1')"
               " ON CONFLICT(key) DO UPDATE SET value = excluded.value")


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
        # Align the per-job travel $/mile with the Vehicle Trips line (direct SQL:
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
# "expiring soon" on the employee and job pages.
EXPIRY_SOON_DAYS = 60
# Vixinman's roles, grouped by department (Piece 16.1) so the employee form's role
# picker reads like the org chart. An employee may hold any number; roles are
# stored comma-separated, like the job form's products. EMPLOYEE_ROLES is the
# flat list derived from the groups, so the two never drift apart.
# Piece 30.9: the org chart as a hierarchy (matches the finance team's outline).
# This single tree drives the New Employee "Roles" picker (rendered as an indented
# org tree) and, flattened, the list of valid roles.
ROLE_TREE = [
    {"role": "General Manager", "children": [
        {"role": "Sales & Marketing Manager", "children": [
            {"role": "Marketing Associate"},
            {"role": "Inside Sales Rep"},
            {"role": "Outside Sales Rep"},
        ]},
        {"role": "Operations Manager", "children": [
            {"role": "Designer"},
            {"role": "Inventory Manager", "children": [
                {"role": "Purchasing Agent"},
                {"role": "Warehouse Assistant"},
            ]},
            {"role": "Permit Coordinator"},
            {"role": "Scheduling Coordinator"},
            {"role": "Lead Installer", "children": [
                {"role": "Installer"},
            ]},
            {"role": "Service Technician"},
        ]},
        {"role": "Administration Manager", "children": [
            {"role": "Facilities Manager"},
            {"role": "Human Resources Manager", "children": [
                {"role": "Hiring and Performance Coordinator"},
                {"role": "Payroll Manager", "children": [
                    {"role": "Payroll Administrator"},
                ]},
            ]},
            {"role": "Administrative Assistant"},
        ]},
        {"role": "Finance Manager", "children": [
            {"role": "Bookkeeper"},
        ]},
        {"role": "Research & Development Manager", "children": [
            {"role": "Product Portfolio Manager"},
            {"role": "Process Developer"},
            {"role": "Software Developer"},
        ]},
    ]},
]


def _flatten_roles(nodes):
    out = []
    for n in nodes:
        out.append(n["role"])
        out.extend(_flatten_roles(n.get("children", [])))
    return out


EMPLOYEE_ROLES = _flatten_roles(ROLE_TREE)
# Piece 30.9: legacy role name → current name, for a one-time migration of the
# employees.roles text (and back-compat when reading old data).
ROLE_RENAMES = {
    "Sales and Marketing Manager": "Sales & Marketing Manager",
    "Research and Development Manager": "Research & Development Manager",
    "Warehouse Associate": "Warehouse Assistant",
    "HR Manager": "Human Resources Manager",
}

# Piece 16.1: Vixinman's org chart as a one-time employee seed (matched from the
# provided diagram). Each person may hold many roles.
ORG_CHART_TEAM = [
    ("Cary", ["General Manager", "Sales & Marketing Manager",
              "Administration Manager", "Finance Manager",
              "Research & Development Manager", "Marketing Associate",
              "Inside Sales Rep", "Outside Sales Rep", "Designer",
              "Inventory Manager", "Purchasing Agent", "Scheduling Coordinator",
              "Lead Installer", "Installer", "Service Technician",
              "Human Resources Manager", "Product Portfolio Manager",
              "Process Developer"]),
    ("Will", ["Operations Manager", "Purchasing Agent", "Scheduling Coordinator",
              "Lead Installer", "Installer", "Service Technician"]),
    ("Rachel", ["Marketing Associate", "Process Developer"]),
    ("Louie", ["Inside Sales Rep", "Outside Sales Rep", "Scheduling Coordinator",
               "Installer"]),
    ("Trish", ["Permit Coordinator", "Purchasing Agent", "Warehouse Assistant",
               "Facilities Manager", "Administrative Assistant"]),
    ("Si", ["Purchasing Agent", "Lead Installer", "Installer",
            "Service Technician"]),
    ("Lisa", ["Payroll Manager", "Payroll Administrator"]),
    ("Vanessa", ["Bookkeeper", "Payroll Administrator"]),
    ("Brady", ["Process Developer", "Software Developer"]),
]

UTILITY_CONNECTIONS = ["Off-grid", "Grid-tie", "Backup system"]
MOUNTING_TYPES = ["Roof mounted", "Ground mount"]
SERVICE_TYPES = ["General service", "Warranty service"]
PROPERTY_TYPES = ["Residential", "Commercial"]

# Which variant fields belong to which product — used by the rule
# directory so filtering by job type also scopes its variants.
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

# Standard documents every job collects, shown as their own upload slots on the
# Documents tab (Piece 20.9) alongside the job's resolved requirements. Format
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
# Piece 31.8: how the customer pays for the job (the job form's "Payment" field,
# stored in cost_method). Two choices — pay the full amount up front, or finance.
PAYMENT_TERMS = ["Pay in full", "Financing"]

# Piece 21.5: source-document type for a ledger entry, so scanned/received
# paperwork feeds the QuickBooks reports under the right account flow:
#   Invoice — money we bill a customer (A/R, Income)
#   Bill    — money a vendor bills us (A/P, Expense)
#   Receipt — proof of a payment already made (an expense paid at the counter)
# A blank doc type is a plain ledger note with no paperwork behind it.
DOC_TYPES = ["Receipt", "Invoice", "Bill"]

# Piece 27.3: progress-billing ("50 / 40 / 10") schedule used to generate customer
# invoices from a job's contract + BOM. (name, percent-of-contract, plain-language
# hint). Materials added to the BOM AFTER the deposit invoice are billed to the
# customer on top of the contract, split 80/20 across the Progress and Final
# invoices (the Final trues up so the total billed = contract + all added materials).
INVOICE_MILESTONES = [
    ("Deposit", 50, "Collected upfront at contract signing."),
    ("Progress", 40, "Billed once materials are ordered and the project is underway."),
    ("Final", 10, "Billed on completion / at commissioning."),
]
# Plain-language description of the pay scheme — shown as a callout to Sales and
# Finance (and on the customer invoice) so everyone explains it the same way.
PAYMENT_SCHEME_NOTE = (
    "Vixinman bills every install on a 50 / 40 / 10 schedule: <strong>50%</strong> due at "
    "contract signing, <strong>40%</strong> once the project is underway, and the final "
    "<strong>10%</strong> at completion. Any materials added after the deposit (change "
    "orders) are added to the remaining balance and split across the 40% and 10% invoices."
)
# Remit-to block printed on customer invoices. Fill in Vixinman's real details here.
COMPANY_INFO = {
    "name": "Vixinman Designs",
    "address": "1212 Railroad Ave",
    "city_state_zip": "Las Vegas, NM 87701",
    "phone": "(505) 454-0614",
    "email": "rachel@vixinmandesigns.com",
    "terms_days": 15,   # net terms for the Progress / Final invoices
}
# New Mexico gross-receipts tax on the customer invoice. The rate is per job
# (it varies by the install location), defaulting to 0% because Vixinman's solar
# systems are GRT-deductible (see the "GRT Exemption on Invoice" rule); Finance
# sets a rate on the Billing tab where any receipts are taxable. The exemption
# citation prints on every invoice per NMSA 7-9-112, as Vixinman's own rule requires.
GRT_DEFAULT_RATE = 0.0
GRT_EXEMPTION_CITE = ("NMSA 7-9-112 (3.2.247 NMAC) — NM solar-energy-system "
                      "gross-receipts deduction")
# Piece 29.6: the 33 New Mexico counties, seeded (at 0%) into county_tax_rates
# so Finance can enter each county's current GRT rate. A job's GRT rate
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
# the whole job subtotal. Seeded once; fully editable on the Cost Model page.
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

# Piece 21.2: payroll pay-type calculation. A type is either a "multiplier" on
# the employee's base wage (so it's per-employee automatically) or a "flat"
# $/hr. Seeded once; fully editable, and each employee can override any type's
# value. Vixinman's real numbers get entered in Payroll → Settings.
PAY_METHODS = ["multiplier", "flat"]
PAY_TYPE_SEED = [
    # (name, method, default value, sort_order). Overtime is NOT a logged type —
    # it's applied automatically past the weekly threshold (see OT_* below).
    ("Regular", "multiplier", 1.0, 0),
    ("Roof time", "multiplier", 1.25, 1),
    ("Travel time", "flat", 0.0, 2),
    ("Holiday (2x)", "multiplier", 2.0, 3),
    ("PTO", "multiplier", 1.0, 4),
]
# Auto-overtime defaults (editable in Pay settings, stored in `meta`): hours
# over the weekly threshold of OT-eligible time earn the OT multiplier.
OT_THRESHOLD_DEFAULT = 40.0
OT_MULTIPLIER_DEFAULT = 1.5

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
# utility-specific interconnection links keyed on the job's utility
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


# Utility-specific portals become Link rules keyed on the job's utility
# provider (both utilities appear in the document).
SEED_RULES_V7 = [
    ("utility_provider", "PNM", "equals", "Link",
     "PNM — Solar Interconnection & Net Metering", "", "", "", "equals"),
    ("utility_provider", "Kit Carson Electric Cooperative", "equals", "Link",
     "Kit Carson Electric Cooperative", "", "", "", "equals"),
]

# Canonical values suggested on the job form so free-typed utilities and
# counties actually match the rules below.
UTILITIES = UTILITIES_ALL

# These products share one utility-connection choice on the job form.
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
    # --- Utility contacts & forms (fire on the job's utility provider) ---
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
    # --- AHJ building/structural permits (fire on the job's county) ---
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

# Vixinman's main products/services — the multi-select on the job form.
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
VERSION = "0.1"

UPLOADS_DIR = DATA_DIR / "uploads"
ALLOWED_EXTENSIONS = {
    "pdf", "png", "jpg", "jpeg", "heic", "gif", "doc", "docx", "xls", "xlsx",
    "csv", "txt", "kmz", "kml", "zip", "bpmn",
}
# Piece 21.7: field crews snap job photos from the Work Bag. Photos are stored
# as job_files tagged with FIELD_PHOTO_LABEL and the originating task.
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
# Piece 12: categories for client-level documents (distinct from a job's
# requirement categories — these describe the client relationship).
CLIENT_FILE_CATEGORIES = ["Contracts", "Correspondence", "Intake", "Photos", "Other"]
# Piece 16: job pipeline stages, redefined to match Vixinman's process phases.
# (Leads/Cold are a client-level state — see lead_status — because a lead has
# no job yet; a job exists from Proposal onward.)
JOB_STATUSES = ["Proposal", "Job Prep", "Installation", "Inspections",
                "Closing", "Complete", "Lost"]
JOB_STATUS_CLASS = {
    "Proposal": "neutral", "Job Prep": "warn", "Installation": "warn",
    "Inspections": "warn", "Closing": "warn", "Complete": "", "Lost": "danger",
}
DEFAULT_JOB_STATUS = "Proposal"
# Piece 18: which department governs each pipeline status, the functions that
# staff it (each resolved to its head via best_assignee_for_lane on the BPMN
# lane), and the exit criteria to advance. Kept standardized but flexible —
# the rules engine still drives which job-specific steps actually apply.
STATUS_OWNERSHIP = {
    "Proposal": {"dept": "Sales", "exit": "Sales signs the contract.",
                 "team": [("Sales", "Sales"), ("Design", "Design")]},
    "Job Prep": {"dept": "Operations — parallel functions",
                 "exit": "All permits filed and an install date set "
                         "(setting the install date advances the job).",
                 "team": [("Permits", "Permits"),
                          ("Finance", "Finance"),
                          ("Purchasing", "Purchasing"),
                          ("Install prep", "Installation")]},
    "Installation": {"dept": "Service & Technician", "exit": "Install complete.",
                     "team": [("Install", "Installation")]},
    "Inspections": {"dept": "Operations — same team as Job Prep",
                    "exit": "Inspection passed and signed off.",
                    "team": [("Permits", "Permits"),
                             ("Fixes", "Installation")]},
    "Closing": {"dept": "All departments — one final task each",
                "exit": "Final invoice, walkthrough, and paperwork done.",
                "team": [("Finance", "Finance"),
                         ("Sales", "Sales"), ("Sign-off", "Executive")]},
    "Complete": {"dept": "—", "exit": "Job closed.", "team": []},
    "Lost": {"dept": "—", "exit": "", "team": []},
}
# The linear advance path (Lost is an off-path terminal state).
STAGE_ORDER = ["Proposal", "Job Prep", "Installation", "Inspections",
               "Closing", "Complete"]
# Short labels for the tight per-job progress widget (Piece 20.2).
STAGE_SHORT = {"Proposal": "Proposal", "Job Prep": "Prep",
               "Installation": "Install", "Inspections": "Inspect",
               "Closing": "Closing", "Complete": "Done"}
# Piece 21.6: the stages a crew physically works on site. The Work Bag and the
# Foreman's "My tasks" show only these — office/scheduling steps stay on the
# dashboards where they belong.
FIELD_STAGES = {"Installation", "Inspections"}


def next_stage(status):
    try:
        i = STAGE_ORDER.index(status)
        return STAGE_ORDER[i + 1] if i + 1 < len(STAGE_ORDER) else None
    except ValueError:
        return None


# Piece 19: role-based My Dashboard. A person belongs to a department if they
# hold one of its roles; the dashboard stacks a section per department they're
# in (with a mode switch to focus on one). `stages` are the pipeline statuses
# whose active jobs that department needs to work.
DASHBOARD_DEPARTMENTS = {
    "Sales": {"icon": "💬", "stages": ["Proposal"],
              "roles": {"Sales & Marketing Manager", "Outside Sales Rep",
                        "Inside Sales Rep", "Marketing Associate"}},
    "Design": {"icon": "📐", "stages": ["Proposal"], "roles": {"Designer"}},
    "Permits": {"icon": "📋", "stages": ["Job Prep", "Inspections"],
                "roles": {"Permit Coordinator"}},
    "Finance": {"icon": "💵", "stages": ["Job Prep", "Installation", "Closing"],
                "roles": {"Finance Manager", "Bookkeeper", "Payroll Manager",
                          "Payroll Administrator"}},
    "Purchasing": {"icon": "📦", "stages": ["Job Prep"],
                   "roles": {"Inventory Manager", "Purchasing Agent",
                             "Warehouse Assistant"}},
    "Installation": {"icon": "🔧", "stages": ["Installation", "Inspections"],
                     "roles": {"Lead Installer", "Installer",
                               "Service Technician", "Scheduling Coordinator"}},
    "Operations": {"icon": "🛠️", "stages": ["Job Prep", "Installation", "Inspections"],
                   "roles": {"Operations Manager"}},
    "Administration": {"icon": "🗂️", "stages": [],
                       "roles": {"Administration Manager", "Administrative Assistant",
                                 "Facilities Manager", "Human Resources Manager"}},
    "Executive": {"icon": "⭐", "stages": STAGE_ORDER[:-1],
                  "roles": {"General Manager"}},
}


# Piece 29.5: departments that never appear as a dashboard "mode". Administration
# has no pipeline stages of its own, so its dashboard view was redundant — the
# department stays for role grouping/permissions, it just isn't a focus tab.
DASHBOARD_MODE_EXCLUDE = {"Administration"}

# Piece 30.5: a virtual dashboard mode. Sales sees the pipeline's tail as
# "Closing" (final walkthrough, final invoice, balance due) rather than the
# install-crew "Installation" view — so for anyone holding a Sales role, their
# Installation mode is presented as Closing (see _viewer_modes). MODE_CONFIG is
# DASHBOARD_DEPARTMENTS plus this Closing mode, used when rendering the switcher.
MODE_CONFIG = dict(DASHBOARD_DEPARTMENTS)
MODE_CONFIG["Closing"] = {"icon": "🏁", "stages": ["Closing"], "roles": set()}
SALES_ROLES = DASHBOARD_DEPARTMENTS["Sales"]["roles"]


def _holds_sales_role(user):
    if user is None:
        return False
    held = {r.strip() for r in (user["roles"] or "").split(",") if r.strip()}
    return bool(held & SALES_ROLES)


def user_departments(user):
    """Departments the user belongs to (holds a role for), in config order.
    Excludes departments that aren't offered as a dashboard mode."""
    if user is None:
        return []
    held = {r.strip() for r in (user["roles"] or "").split(",") if r.strip()}
    return [d for d, cfg in DASHBOARD_DEPARTMENTS.items()
            if held & cfg["roles"] and d not in DASHBOARD_MODE_EXCLUDE]


def _viewer_modes(user):
    """The dashboard modes to offer this viewer — like user_departments, but for
    a Sales-role holder the 'Installation' mode is presented as 'Closing'
    (Piece 30.5). The GM is exempt — a General Manager keeps every mode as-is,
    including Installation (Piece 30.6)."""
    depts = user_departments(user)
    if (_holds_sales_role(user) and not _has_gm_role(user)
            and "Installation" in depts):
        depts = ["Closing" if d == "Installation" else d for d in depts]
    return depts
# Migrate Piece 12.1 statuses to the Piece 16 phases so existing jobs survive.
OLD_TO_NEW_STATUS = {
    "Lead": "Proposal", "Quoted": "Proposal", "Sold": "Job Prep",
    "Permitting": "Job Prep", "Scheduled": "Installation",
    "Installed": "Inspections", "Closed": "Complete",
}
# Piece 16: lead follow-up cadence (days after the client is created) and the
# age at which a cold lead is flagged for an admin to purge.
LEAD_FOLLOWUP_SCHEDULE = [(7, "7-day"), (14, "2-week"), (30, "1-month")]
COLD_LEAD_STALE_DAYS = 182  # ~6 months
# Piece 10: per-job task assignment.
TASK_STATUSES = ["To do", "In progress", "Blocked", "Done"]
# Piece 10.2 / 24.5: map each BPMN lane (now a functional department) to the
# real Vixinman role(s) that own its steps, so a step auto-assigns to the person who
# holds that role (first match = highest priority). Lanes not listed (Compendium
# System, Authorities (CID), Utility Company) are external/automated and never
# auto-assign. The legacy generic labels (Foreman, System Designer, …) are kept
# as aliases so tasks generated before the 24.5 lane rename still resolve.
LANE_TO_ROLES = {
    "Sales": ["Outside Sales Rep", "Inside Sales Rep", "Sales & Marketing Manager"],
    "Design": ["Designer"],
    "Permits": ["Permit Coordinator"],
    "Purchasing": ["Purchasing Agent", "Inventory Manager", "Warehouse Assistant"],
    "Installation": ["Lead Installer", "Installer", "Scheduling Coordinator",
                     "Service Technician"],
    "Finance": ["Finance Manager", "Bookkeeper", "Payroll Manager"],
    "Executive": ["General Manager"],
}
# Legacy lane labels → their new department lane's roles (back-compat for
# already-generated task notes like "Process step · Foreman").
LANE_TO_ROLES.update({
    "Sales Rep": LANE_TO_ROLES["Sales"],
    "System Designer": LANE_TO_ROLES["Design"],
    "Permit Coordinator": LANE_TO_ROLES["Permits"],
    "Warehouse Assistant": LANE_TO_ROLES["Purchasing"],
    "Foreman": LANE_TO_ROLES["Installation"],
    "Finance Department": LANE_TO_ROLES["Finance"],
    "General Manager": LANE_TO_ROLES["Executive"],
})
# Days between consecutive generated tasks when a target install date is
# given — a rough schedule anchored on the Site Installation step.
TASK_DUE_SPACING_DAYS = 2
# Piece 20.1: a task's *default* deadline is 7 days after the previous step
# was completed (for the very first step there's nothing completed yet, so it
# counts from the day the steps are generated). When a step is marked Done we
# re-default the next open step to this many days out. Rough on purpose —
# meant to be tightened by hand per job.
TASK_DEFAULT_LEAD_DAYS = 7

# Piece 17.2: for tasks that don't carry a process lane in their notes (the
# demo/hand-added ones), infer the responsible lane from keywords in the
# title, so they can be role-assigned too. First match wins. (Rough — meant
# to be standardized later.)
TITLE_LANE_KEYWORDS = [
    ("interconnection", "Permits"),
    ("plan review", "Permits"),
    ("permit", "Permits"),
    ("inspection", "Permits"),
    ("zoning", "Permits"),
    ("credit", "Finance"),
    ("invoice", "Finance"),
    ("deposit", "Finance"),
    ("payment", "Finance"),
    ("design", "Design"),
    ("order", "Purchasing"),
    ("material", "Purchasing"),
    ("component", "Purchasing"),
    ("install", "Installation"),
    ("walkthrough", "Installation"),
    ("monitoring", "Installation"),
    ("doc tube", "Installation"),
    ("contract", "Sales"),
    ("site visit", "Sales"),
    ("questionnaire", "Sales"),
    ("proposal", "Sales"),
    ("paperwork", "Executive"),
]

# Piece 18.1: infer a pipeline stage for an existing (un-tagged) task from its
# title, so current jobs show stage progress. Order matters — specific first.
TITLE_STATUS_KEYWORDS = [
    ("sales walkthrough", "Closing"), ("client review", "Closing"),
    ("final 10%", "Closing"), ("final invoice", "Closing"),
    ("final paperwork", "Closing"),
    ("meter set", "Inspections"), ("inspection", "Inspections"),
    ("sticker", "Inspections"), ("letter of compliance", "Inspections"),
    ("install walkthrough", "Installation"), ("site installation", "Installation"),
    ("doc tube", "Installation"), ("monitoring", "Installation"),
    ("40%", "Installation"),
    ("site visit", "Proposal"), ("questionnaire", "Proposal"),
    ("draft", "Proposal"), ("finalize", "Proposal"), ("design", "Proposal"),
    ("contract", "Job Prep"), ("deposit", "Job Prep"), ("50%", "Job Prep"),
    ("permit", "Job Prep"), ("interconnection", "Job Prep"),
    ("order", "Job Prep"), ("credit", "Job Prep"),
    ("installation date", "Job Prep"), ("plan review", "Job Prep"),
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
# system_type presets auto-fill sizing fields on the job page; system_type
# reverts to "custom" on manual edit of a preset-controlled field.
SYSTEM_TYPE_PRESETS = {
    "offgrid": {"derate_pct": 70, "autonomy_days": 3},
    "gridtie": {"derate_pct": 80, "autonomy_days": 1.5},
}
UI_MODES = ["sales", "designer"]


def loads_view_mode(user):
    """Piece 26.4: the Loads & Sizing view mode for this viewer. A per-session
    toggle wins; otherwise it defaults from their department — Designers get
    Designer mode, Sales gets Sales mode (Design wins for someone who is both,
    like Cary). It's a view preference, not access control."""
    m = session.get("loads_ui_mode")
    if m in UI_MODES:
        return m
    depts = set(user_departments(user)) if user else set()
    if "Design" in depts:
        return "designer"
    if "Sales" in depts:
        return "sales"
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
    "new_client": "Create client", "new_job": "Create job",
    "edit_job": "Edit job", "add_rule": "Add rule", "delete_rule": "Delete rule",
    "new_employee": "Add employee", "edit_employee": "Edit employee",
    "delete_employee": "Delete employee", "upload_file": "Upload job document",
    "generate_tasks": "Generate tasks from process",
    "set_task_status": "Change task status", "set_task_assignee": "Reassign task",
    "set_task_due": "Change task due date", "set_ui_mode": "Change sizing view mode",
    "update_sizing": "Update system sizing",
    "cancel_job": "Cancel job (mark Lost)", "reopen_job": "Reopen job",
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
    """True once at least one employee has a usable login. Until then the
    app runs in open mode (no login wall) so nothing locks up and setup is
    possible."""
    row = get_db().execute(
        "SELECT COUNT(*) FROM employees"
        " WHERE COALESCE(username,'') != '' AND COALESCE(password_hash,'') != ''"
    ).fetchone()
    return row[0] > 0


def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    return get_db().execute(
        "SELECT * FROM employees WHERE id = ?", (uid,)).fetchone()


def _has_gm_role(user):
    """A General Manager is anyone whose roles include 'General Manager'
    (Piece 17 — GM access is derived from the org-chart role)."""
    if user is None:
        return False
    return "General Manager" in [r.strip() for r in (user["roles"] or "").split(",")]


def is_gm():
    """GM tier — unfettered access. Open mode counts as GM so the very first
    account can be set up."""
    if not accounts_exist():
        return True
    return _has_gm_role(current_user())


def _is_admin():
    """GM or Admin, OR open mode (no accounts yet) so setup can happen."""
    if not accounts_exist():
        return True
    user = current_user()
    return user is not None and (
        _has_gm_role(user) or user["access_level"] == "Admin")


def _has_grant(user, perm):
    """A live (unexpired) permission grant for this user."""
    if user is None:
        return False
    today = datetime.now().strftime("%Y-%m-%d")
    return get_db().execute(
        "SELECT 1 FROM permission_grants WHERE employee_id = ? AND permission = ?"
        " AND (COALESCE(expires_on, '') = '' OR expires_on >= ?) LIMIT 1",
        (user["id"], perm, today)).fetchone() is not None


def _is_supervisor(user):
    """Piece 29.0: a Supervisor is a non-GM given the emergency access-control
    power (revoke / reinstate a teammate's access). The GM designates them."""
    if user is None:
        return False
    return str(user["is_supervisor"] if "is_supervisor" in user.keys() else "") == "1"


def can_control_access():
    """Who may emergency-revoke or reinstate access: the GM (always) or a
    designated Supervisor. Open mode (no accounts yet) can't lock anyone out."""
    if not accounts_exist():
        return False
    user = current_user()
    return _has_gm_role(user) or _is_supervisor(user)


def is_access_revoked(user):
    """True while this employee's access is under an emergency lockout."""
    if user is None:
        return False
    val = user["access_revoked"] if "access_revoked" in user.keys() else ""
    return str(val or "") == "1"


def notify_employees(db, recipient_ids, message, link="", kind=""):
    """Piece 29.3: drop an in-app notification to each recipient employee id."""
    for rid in dict.fromkeys(recipient_ids):   # de-dupe, preserve order
        db.execute(
            "INSERT INTO notifications (recipient_id, message, link, kind)"
            " VALUES (?, ?, ?, ?)", (rid, message, link, kind))


def supervisors_or_gm_ids(db, exclude_id=None):
    """Recipients for a supervisor-level alert: everyone flagged Supervisor
    (with a login); if there are none, fall back to the General Manager(s).
    Any exclude_id (e.g. the affected employee) is dropped."""
    sups = [r["id"] for r in db.execute(
        "SELECT id FROM employees WHERE is_supervisor = '1'"
        " AND COALESCE(username,'') != ''").fetchall()]
    if not sups:
        sups = [r["id"] for r in db.execute(
            "SELECT id FROM employees WHERE roles LIKE '%General Manager%'"
            " AND COALESCE(username,'') != ''").fetchall()]
    return [i for i in sups if i != exclude_id]


def job_involved_ids(db, job, exclude_id=None):
    """Piece 30.3: employees involved in a job so far — anyone assigned a task on
    it, anyone who logged time to it, and the client's assigned sales rep. Only
    those with a login (who can read an inbox); the given id is dropped."""
    ids = set()
    for r in db.execute("SELECT DISTINCT employee_id FROM job_tasks"
                        " WHERE job_id = ? AND employee_id IS NOT NULL",
                        (job["id"],)).fetchall():
        ids.add(r["employee_id"])
    for r in db.execute("SELECT DISTINCT employee_id FROM time_entries"
                        " WHERE job_id = ? AND employee_id IS NOT NULL",
                        (job["id"],)).fetchall():
        ids.add(r["employee_id"])
    rep = db.execute("SELECT assigned_rep_id FROM clients WHERE id = ?",
                     (job["client_id"],)).fetchone()
    if rep and rep["assigned_rep_id"]:
        ids.add(rep["assigned_rep_id"])
    ids.discard(None)
    ids.discard(exclude_id)
    if not ids:
        return []
    ph = ",".join("?" * len(ids))
    return [r["id"] for r in db.execute(
        f"SELECT id FROM employees WHERE id IN ({ph})"
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


def department_employee_ids(db, dept_names):
    """Piece 29.4: the signed-in employees whose roles place them in any of the
    given departments (used to notify the team a job just turned over to)."""
    roles = set()
    for d in dept_names:
        roles |= DASHBOARD_DEPARTMENTS.get(d, {}).get("roles", set())
    if not roles:
        return []
    ids = []
    for e in db.execute(
            "SELECT id, roles FROM employees WHERE COALESCE(username,'') != ''"
            " AND COALESCE(access_revoked,'') != '1'").fetchall():
        held = {r.strip() for r in (e["roles"] or "").split(",") if r.strip()}
        if held & roles:
            ids.append(e["id"])
    return ids


def notify_stage_turnover(db, job, new_status, exclude_id=None):
    """Piece 29.4: when a job turns over to a pipeline stage, notify the
    department(s) that own that stage. The recipient's copy clears once they
    open it (or open the job). The person who triggered the move is skipped."""
    own = STATUS_OWNERSHIP.get(new_status)
    if not own:
        return
    team = own.get("team", [])
    depts = [dept for _label, dept in team]
    recipients = [i for i in department_employee_ids(db, depts) if i != exclude_id]
    if not recipients:
        return
    client = db.execute("SELECT name FROM clients WHERE id = ?",
                        (job["client_id"],)).fetchone()
    cname = client["name"] if client else ""
    jobname = job["job_name"] or f"Job #{job['id']}"
    labels = ", ".join(dict.fromkeys(label for label, _dept in team))
    notify_employees(
        db, recipients,
        f"📋 {jobname}{(' · ' + cname) if cname else ''} turned over to "
        f"{new_status}{(' — ' + labels + ' up next') if labels else ''}.",
        link=url_for("job_detail", job_id=job["id"]), kind="stage")


def security_questions_enrolled(employee_id):
    """The security questions this employee has set up (for the reset flow)."""
    return get_db().execute(
        "SELECT * FROM security_answers WHERE employee_id = ?"
        " ORDER BY sort_order, id", (employee_id,)).fetchall()


def onboarding_overview(db, employee_id):
    """Piece 29.2: each active checklist step joined with this employee's
    completion, plus (done, total) counts. New steps show as not-done."""
    rows = db.execute(
        "SELECT s.id AS step_id, s.title, s.description, s.category,"
        " COALESCE(eo.done,'') AS done, COALESCE(eo.done_at,'') AS done_at,"
        " COALESCE(eo.done_by,'') AS done_by, COALESCE(eo.note,'') AS note"
        " FROM onboarding_steps s"
        " LEFT JOIN employee_onboarding eo"
        "   ON eo.step_id = s.id AND eo.employee_id = ?"
        " WHERE s.active = '1'"
        " ORDER BY s.sort_order, s.id", (employee_id,)).fetchall()
    done = sum(1 for r in rows if r["done"] == "1")
    return rows, done, len(rows)


def onboarding_owner_candidates(db):
    """Piece 31.2: who may be put on the hook for finishing a new hire's
    onboarding — the General Manager(s) and any designated Supervisor, all of
    whom must have a login so they can actually act. GM(s) first."""
    return db.execute(
        "SELECT id, name FROM employees"
        " WHERE COALESCE(username,'') != ''"
        "   AND (roles LIKE '%General Manager%' OR is_supervisor = '1')"
        " ORDER BY (roles LIKE '%General Manager%') DESC, name").fetchall()


def default_onboarding_owner_id(db):
    """Default accountable person for a new hire's onboarding: the first
    General Manager with a login, else the first Supervisor, else nobody."""
    row = db.execute(
        "SELECT id FROM employees WHERE roles LIKE '%General Manager%'"
        " AND COALESCE(username,'') != '' ORDER BY name LIMIT 1").fetchone()
    if row:
        return str(row["id"])
    row = db.execute(
        "SELECT id FROM employees WHERE is_supervisor = '1'"
        " AND COALESCE(username,'') != '' ORDER BY name LIMIT 1").fetchone()
    return str(row["id"]) if row else ""


def can_revoke_target(actor, target):
    """May `actor` emergency-revoke `target`? Guards the hierarchy: nobody
    revokes themselves; a GM can act on anyone else; a Supervisor can act on
    ordinary employees but not on a GM or a fellow Supervisor (no peer/
    upward lockouts)."""
    if actor is None or target is None or actor["id"] == target["id"]:
        return False
    if _has_gm_role(actor):
        return True
    if not _is_supervisor(actor):
        return False
    return not _has_gm_role(target) and not _is_supervisor(target)


def has_permission(perm):
    """Central access check. GM ⇒ everything. 'delete' is GM-or-granted only
    (never automatic for Admin). Other tools: Admin ⇒ yes, else a live grant.
    perm=None is the generic Admin/GM gate."""
    if not accounts_exist():
        return True
    user = current_user()
    if user is None:
        return False
    if _has_gm_role(user):
        return True
    if perm == "delete":
        return _has_grant(user, "delete")   # never role-conferred (safety)
    if perm is None:
        return user["access_level"] == "Admin"
    if user["access_level"] == "Admin":
        return True
    # Piece 24.6: a role the user holds may confer this permission (org-chart
    # scoped access), else fall back to an explicit per-person grant.
    if perm in permissions_from_roles(user):
        return True
    return _has_grant(user, perm)


# Which permission each admin-gated view needs (Piece 17). Views not listed
# fall back to the generic Admin/GM gate (perm=None).
VIEW_PERMISSION = {
    "client_history": "clients.history",
    "cold_leads_page": "leads.manage",
    "restore_cold_lead": "leads.manage",
    "purge_cold_lead": "leads.manage",
    "add_appliance_catalog": "catalog.manage",
    "delete_appliance_catalog": "catalog.manage",
    "add_component_catalog": "catalog.manage",
    "delete_component_catalog": "catalog.manage",
    "submissions_page": "approvals",
    "approve_submission": "approvals",
    "reject_submission": "approvals",
    "add_rule": "rules.manage",
    "delete_rule": "rules.manage",
    "accounts_page": "employees.manage",
    "approve_password_change": "employees.manage",
    "reject_password_change": "employees.manage",
    "new_employee": "employees.manage",
    "edit_employee": "employees.manage",
    "delete_employee": "employees.manage",
    "add_credential": "employees.manage",
    "update_credential": "employees.manage",
    "delete_credential": "employees.manage",
    "upload_employee_file": "employees.manage",
    "delete_employee_file": "employees.manage",
    # Piece 29.2: onboarding checklist management + per-employee progress.
    "onboarding_checklist": "employees.manage",
    "onboarding_step_add": "employees.manage",
    "onboarding_step_edit": "employees.manage",
    "onboarding_step_delete": "employees.manage",
    "onboarding_step_move": "employees.manage",
    "employee_onboarding_toggle": "employees.manage",
    "employee_onboarding_owner": "employees.manage",  # Piece 31.2
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
    # job; scanning to load a truck is open to any signed-in worker (Installers
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
    Admin/GM gate). Granting that permission to a Standard user opens exactly
    this tool for them."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not has_permission(VIEW_PERMISSION.get(view.__name__)):
            flash("You don't have access to that. Ask a General Manager.", "error")
            return redirect(url_for("home"))
        return view(*args, **kwargs)
    return wrapped


def gm_required(view):
    """General-Manager-only actions (the access console; trash management)."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not is_gm():
            flash("That's limited to the General Manager.", "error")
            return redirect(url_for("home"))
        return view(*args, **kwargs)
    return wrapped


def _can_payroll():
    """Payroll is Finance work: the General Manager, any Admin, or anyone in
    the Finance department. (Open mode — no logins — allows everyone.)"""
    user = current_user()
    if user is None:
        return True
    return is_gm() or _is_admin() or "Finance" in user_departments(user)


def _can_see_pricing():
    """Piece 29.7: who may see the internal cost/margin pricing breakdown —
    Finance, Admin, GM, and (because they price and design jobs) Sales & Design.
    Deliberately NOT the whole company: it exposes cost and margin."""
    user = current_user()
    if user is None:
        return True
    if is_gm() or _is_admin():
        return True
    return bool({"Finance", "Sales", "Design"} & set(user_departments(user)))


def _can_see_pay_scheme():
    """Piece 31.8: who sees the estimate's customer payment-schedule callout —
    the people who walk a customer through it before signing: Sales and Finance
    (plus GM/Admin). Narrower than pricing (no Design)."""
    user = current_user()
    if user is None:
        return True
    if is_gm() or _is_admin():
        return True
    return bool({"Finance", "Sales"} & set(user_departments(user)))


def _can_edit_pay_rates():
    """Only the GM (Cary) and the Payroll Manager (Lisa) can change pay rates —
    a separation of duties from the people who log/approve/run payroll."""
    user = current_user()
    if user is None:
        return True
    roles = [r.strip() for r in (user["roles"] or "").split(",")]
    return is_gm() or "Payroll Manager" in roles


def payroll_required(view):
    """Guard payroll pages to Finance / Admin / GM."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not _can_payroll():
            flash("Payroll is limited to Finance and management.", "error")
            return redirect(url_for("home"))
        return view(*args, **kwargs)
    return wrapped


def pay_rates_required(view):
    """Guard pay-rate editing to the GM and Payroll Manager only."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not _can_edit_pay_rates():
            flash("Only the General Manager or Payroll Manager can change pay rates.", "error")
            return redirect(url_for("payroll"))
        return view(*args, **kwargs)
    return wrapped


def finance_required(view):
    """Guard finance settings/pages to Finance / Admin / GM (Piece 29.6)."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not _can_payroll():   # GM, Admin, or the Finance department
            flash("That's limited to Finance and management.", "error")
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


def ot_rules(db):
    """Current weekly-overtime settings (threshold hours, multiplier)."""
    return (_to_float(_meta_get(db, "payroll_ot_threshold")) or OT_THRESHOLD_DEFAULT,
            _to_float(_meta_get(db, "payroll_ot_multiplier")) or OT_MULTIPLIER_DEFAULT)


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
            "is_admin": _is_admin(), "is_gm": is_gm(), "can": has_permission,
            "can_payroll": _can_payroll(),
            "can_edit_pay_rates": _can_edit_pay_rates(),
            "can_control_access": can_control_access(),  # Piece 29.0
            "is_supervisor": _is_supervisor(user),
            "unread_notifications": unread_notification_count(user),  # Piece 29.3
            "pending_submissions": pending}


@app.route("/access")
@gm_required
def access_console():
    """GM console: grant individual tools to people (with optional expiry)."""
    db = get_db()
    people = db.execute(
        "SELECT * FROM employees WHERE COALESCE(username,'') != '' ORDER BY name"
    ).fetchall()
    grants = {}
    for g in db.execute(
            "SELECT employee_id, permission, expires_on FROM permission_grants"):
        grants.setdefault(g["employee_id"], {})[g["permission"]] = g["expires_on"] or ""
    rows = [{
        "id": p["id"], "name": p["name"], "is_gm": _has_gm_role(p),
        "level": p["access_level"] or "Standard", "grants": grants.get(p["id"], {}),
        # Piece 24.6: permissions this person already gets from their roles —
        # shown as auto-granted (change the role to alter these, not a grant).
        "role_perms": permissions_from_roles(p),
    } for p in people]
    return render_template("access.html", rows=rows, permissions=PERMISSIONS,
                           today=datetime.now().strftime("%Y-%m-%d"))


@app.route("/access/<int:employee_id>", methods=["POST"])
@gm_required
def save_access(employee_id):
    db = get_db()
    emp = db.execute("SELECT * FROM employees WHERE id = ?",
                     (employee_id,)).fetchone()
    if emp is None:
        abort(404)
    gm = current_user()
    granter = gm["name"] if gm else "General Manager"
    db.execute("DELETE FROM permission_grants WHERE employee_id = ?", (employee_id,))
    for key in PERMISSIONS:
        if request.form.get(f"perm_{key}"):
            db.execute(
                "INSERT INTO permission_grants (employee_id, permission,"
                " granted_by, expires_on) VALUES (?, ?, ?, ?)",
                (employee_id, key, granter,
                 request.form.get(f"exp_{key}", "").strip()))
    db.commit()
    flash(f"Access updated for {emp['name']}.")
    return redirect(url_for("access_console", _anchor=f"emp{employee_id}"))


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


def _job_name(db, jid):
    r = db.execute("SELECT job_name FROM jobs WHERE id = ?", (jid,)).fetchone()
    return (r["job_name"] if r and r["job_name"] else f"Job #{jid}")


def _client_name(db, cid):
    r = db.execute("SELECT name FROM clients WHERE id = ?", (cid,)).fetchone()
    return r["name"] if r else f"Client #{cid}"


def _emp_name(db, eid):
    r = db.execute("SELECT name FROM employees WHERE id = ?", (eid,)).fetchone()
    return r["name"] if r else f"Employee #{eid}"


def _component_uses(db, cid):
    uses = []
    n = _count(db, "SELECT COUNT(*) FROM job_bom WHERE component_id = ?", (cid,))
    if n:
        uses.append(f"{n} job bill-of-materials line(s)")
    n = _count(db, "SELECT COUNT(*) FROM job_sizing WHERE selected_battery_id = ?"
               " OR selected_pv_module_id = ?", (cid, cid))
    if n:
        uses.append(f"{n} job sizing selection(s)")
    return uses


def _employee_uses(db, eid):
    uses = []
    n = _count(db, "SELECT COUNT(*) FROM job_tasks WHERE employee_id = ?", (eid,))
    if n:
        uses.append(f"{n} assigned task(s)")
    n = _count(db, "SELECT COUNT(*) FROM clients WHERE assigned_rep_id = ?", (eid,))
    if n:
        uses.append(f"{n} client(s) where they're the sales rep")
    n = _count(db, "SELECT COUNT(*) FROM field_submissions WHERE employee_id = ?", (eid,))
    if n:
        uses.append(f"{n} field-work submission(s)")
    return uses


# entity_type -> how to label it, where it lived, what would block its delete,
# and (for file rows) where its file sits on disk.
TRASH_REGISTRY = {
    "rule": {"table": "resource_rules", "label": lambda r: r["label"],
             "found_in": lambda db, r: "Rules",
             "in_use": lambda db, r: (
                 [f"{_count(db, 'SELECT COUNT(*) FROM job_files WHERE rule_label = ?', (r['label'],))} filed document(s)"]
                 if _count(db, "SELECT COUNT(*) FROM job_files WHERE rule_label = ?", (r["label"],)) else [])},
    "appliance": {"table": "appliance_catalog", "label": lambda r: r["name"],
                  "found_in": lambda db, r: "Appliance catalog",
                  "in_use": lambda db, r: []},
    "component": {"table": "component_catalog", "label": lambda r: r["name"],
                  "found_in": lambda db, r: "Component catalog",
                  "in_use": lambda db, r: _component_uses(db, r["id"])},
    "material": {"table": "job_materials", "label": lambda r: r["item"],
                 "found_in": lambda db, r: f"{_job_name(db, r['job_id'])} — Materials",
                 "in_use": lambda db, r: []},
    "task": {"table": "job_tasks", "label": lambda r: r["title"],
             "found_in": lambda db, r: f"{_job_name(db, r['job_id'])} — Tasks",
             "in_use": lambda db, r: (
                 [f"{_count(db, 'SELECT COUNT(*) FROM field_submission_items WHERE task_id = ?', (r['id'],))} field submission(s)"]
                 if _count(db, "SELECT COUNT(*) FROM field_submission_items WHERE task_id = ?", (r["id"],)) else [])},
    "load_room": {"table": "job_load_rooms", "label": lambda r: r["name"],
                  "found_in": lambda db, r: f"{_job_name(db, r['job_id'])} — Loads",
                  "in_use": lambda db, r: (
                      [f"{_count(db, 'SELECT COUNT(*) FROM job_load_items WHERE room_id = ?', (r['id'],))} appliance(s) in the room"]
                      if _count(db, "SELECT COUNT(*) FROM job_load_items WHERE room_id = ?", (r["id"],)) else [])},
    "load_item": {"table": "job_load_items", "label": lambda r: r["appliance"],
                  "found_in": lambda db, r: f"{_job_name(db, r['job_id'])} — Loads",
                  "in_use": lambda db, r: []},
    "bom": {"table": "job_bom", "label": lambda r: r["component_name"],
            "found_in": lambda db, r: f"{_job_name(db, r['job_id'])} — Components",
            "in_use": lambda db, r: []},
    "job_file": {"table": "job_files", "label": lambda r: r["original_name"],
                 "found_in": lambda db, r: f"{_job_name(db, r['job_id'])} — Documents",
                 "in_use": lambda db, r: [],
                 "file": lambda r: UPLOADS_DIR / f"job_{r['job_id']}" / r["stored_name"]},
    "client_file": {"table": "client_files", "label": lambda r: r["original_name"],
                    "found_in": lambda db, r: f"{_client_name(db, r['client_id'])} — Documents",
                    "in_use": lambda db, r: [],
                    "file": lambda r: UPLOADS_DIR / f"client_{r['client_id']}" / r["stored_name"]},
    "credential": {"table": "employee_credentials", "label": lambda r: r["name"],
                   "found_in": lambda db, r: f"{_emp_name(db, r['employee_id'])} — Credentials",
                   "in_use": lambda db, r: []},
    "employee_file": {"table": "employee_files", "label": lambda r: r["original_name"],
                      "found_in": lambda db, r: f"{_emp_name(db, r['employee_id'])} — Documents",
                      "in_use": lambda db, r: [],
                      "file": lambda r: UPLOADS_DIR / f"employee_{r['employee_id']}" / r["stored_name"]},
    "employee": {"table": "employees", "label": lambda r: r["name"],
                 "found_in": lambda db, r: "Employees",
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
@gm_required
def purge_trash(trash_id):
    """Permanent deletion — General Manager only."""
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
    # Piece 29.0: an emergency access lockout takes effect immediately — sign
    # the person out mid-session and hold them at the login wall.
    if is_access_revoked(user):
        session.clear()
        if request.path.startswith("/api/"):
            return jsonify({"error": "access revoked"}), 403
        flash("Your access has been suspended. Contact a manager to restore it.",
              "error")
        return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user() is not None:
        return redirect(url_for("home"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        # Usernames are matched case-insensitively (passwords stay exact).
        user = get_db().execute(
            "SELECT * FROM employees WHERE LOWER(username) = LOWER(?)"
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
        if ok and is_access_revoked(user):
            # Piece 29.0: correct credentials, but access is under an emergency
            # lockout — refuse the sign-in without hinting the password was wrong.
            flash("Your access has been suspended. Contact a manager to restore it.",
                  "error")
            return render_template("login.html", next=request.args.get("next", ""))
        if ok:
            session["user_id"] = user["id"]
            # Piece 24.8: stamp last activity so the session self-expires after
            # 12 hours of inactivity (the window slides on each request).
            session.permanent = True
            session["last_active"] = datetime.now().isoformat(timespec="seconds")
            flash(f"Signed in as {user['name']}.")
            session.pop("dash_mode", None)  # start on their saved default
            # Honor a deep link (e.g. a specific job someone opened while
            # logged out), but never treat the bare root "/" (Client Profiles)
            # as the landing — everyone should land on their own dashboard.
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


def _lock_account_after_failed_reset(db, user):
    """Piece 29.3: too many wrong reset answers auto-locks the account (the same
    emergency lockout a GM/Supervisor applies) and notifies the Supervisors —
    or the GM(s) if there are none — so a human reviews it."""
    db.execute(
        "UPDATE employees SET access_revoked = '1', access_revoked_at = ?,"
        " access_revoked_by = ?, access_revoked_reason = ? WHERE id = ?",
        (datetime.now().isoformat(timespec="seconds"), "System (auto-lock)",
         "Too many failed password-reset attempts", user["id"]))
    recipients = supervisors_or_gm_ids(db, exclude_id=user["id"])
    notify_employees(
        db, recipients,
        f"🔒 {user['name']}'s account was auto-locked after "
        f"{SECURITY_RESET_MAX_ATTEMPTS} failed password-reset attempts. "
        "Review and reinstate their access if appropriate.",
        link=url_for("employee_detail", employee_id=user["id"]),
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
            "SELECT * FROM employees WHERE LOWER(username) = LOWER(?)"
            " AND COALESCE(username,'') != ''", (username,)).fetchone()
        enrolled = security_questions_enrolled(user["id"]) if user else []
        # Only proceed for a real, active login that has questions enrolled.
        if (user and user["password_hash"] and not is_access_revoked(user)
                and enrolled):
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
    user = db.execute("SELECT * FROM employees WHERE id = ?", (uid,)).fetchone()
    enrolled = {q["id"]: q for q in security_questions_enrolled(uid)} if user else {}
    # The chosen questions, in the order they were picked.
    questions = [enrolled[i] for i in ask if i in enrolled]
    if not user or is_access_revoked(user) or len(questions) != len(ask):
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
                _lock_account_after_failed_reset(db, user)
                _clear_reset_session()
                flash("Too many incorrect answers — for security this account "
                      "has been locked and a supervisor notified. They can "
                      "reinstate your access.", "error")
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
        db.execute("UPDATE employees SET password_hash = ? WHERE id = ?",
                   (generate_password_hash(new, method="pbkdf2:sha256"), uid))
        db.execute("DELETE FROM password_requests WHERE employee_id = ?"
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
        "SELECT * FROM password_requests WHERE employee_id = ? AND status = 'Pending'"
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
                   " WHERE employee_id = ? AND status = 'Pending'", (user["id"],))
        db.execute(
            "INSERT INTO password_requests (employee_id, new_hash) VALUES (?, ?)",
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
               " WHERE employee_id = ? AND status = 'Pending'", (user["id"],))
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
    db.execute("DELETE FROM security_answers WHERE employee_id = ?", (user["id"],))
    for order, (q, a) in enumerate(pairs):
        db.execute(
            "INSERT INTO security_answers (employee_id, question, answer_hash,"
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
    """Piece 16.1: create Vixinman's org-chart team (by name) with their roles.
    Runs once per database (guarded by a meta flag) and skips anyone already
    present, so it populates existing installs without duplicating and never
    resurrects someone who was deleted on purpose."""
    if db.execute("SELECT 1 FROM meta WHERE key = 'org_team_seeded'").fetchone():
        return
    for name, roles in ORG_CHART_TEAM:
        if not db.execute("SELECT 1 FROM employees WHERE name = ?",
                          (name,)).fetchone():
            db.execute("INSERT INTO employees (name, roles) VALUES (?, ?)",
                       (name, ", ".join(roles)))
    # Cary holds every role (he's the GM); default his dashboard to the Executive
    # whole-company overview (Piece 26.8 — was Design).
    db.execute("UPDATE employees SET dashboard_mode = 'Executive'"
               " WHERE name = 'Cary' AND COALESCE(dashboard_mode, '') = ''")
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
    """Create tables if missing, upgrade older databases, and add three
    sample clients (one job each) the first time so the app isn't empty."""
    db = sqlite3.connect(DATABASE)
    db.executescript((BASE_DIR / "schema.sql").read_text())
    # Field renamed after Piece 3.1: carry existing data over.
    client_cols = {row[1] for row in db.execute("PRAGMA table_info(clients)")}
    if "street_address" in client_cols and "mailing_address" not in client_cols:
        db.execute("ALTER TABLE clients RENAME COLUMN street_address TO mailing_address")
    ensure_columns(db, "clients", CLIENT_FIELDS)
    # Piece 16: lead-lifecycle columns that aren't part of the intake form.
    ensure_columns(db, "clients", ["lead_status", "assigned_rep_id", "converted_at"])
    db.execute("UPDATE clients SET lead_status = 'Lead'"
               " WHERE COALESCE(lead_status, '') = ''")
    ensure_columns(db, "jobs", JOB_FIELDS + ["status", "install_date"])
    # Piece 21: contract total for the Finance viewport (dollar amounts).
    ensure_columns(db, "jobs", ["contract_amount"])
    # Piece 21.5: source-document type (Receipt / Invoice / Bill) on ledger rows.
    ensure_columns(db, "job_transactions", ["doc_type"])
    # Piece 27.3: generated-invoice fields on the ledger row + the BOM cutoff the
    # deposit invoice captures (BOM added after it counts as billable extras).
    ensure_columns(db, "job_transactions",
                   ["invoice_number", "milestone", "due_date", "contract_snapshot",
                    "base_amount", "extras_amount", "bom_snapshot",
                    "grt_rate", "grt_amount"])   # Piece 27.4: GRT snapshot per invoice
    ensure_columns(db, "jobs", ["deposit_bom_cutoff_id", "grt_rate"])
    # Piece 27.9: per-task time split by pay type (+ its work date) carried on a
    # field-submission item, so approving a completed task posts Pending payroll
    # entries (one per pay-type segment) for Finance to approve.
    ensure_columns(db, "field_submission_items", ["hours_json", "work_date"])
    # Piece 21.7: tie crew-captured field photos back to the task they document.
    ensure_columns(db, "job_files", ["task_id"])
    # Piece 26.2: link a receipt photo to its ledger transaction (bookkeeping).
    ensure_columns(db, "job_files", ["txn_id"])
    # Piece 26.4: a room's appliance-catalog "type" (Kitchen, Garage, …) so the
    # load-survey picker can default to that room's appliances.
    ensure_columns(db, "job_load_rooms", ["category"])
    # Piece 25.2: per-slot accepted file formats (comma-separated extensions) on
    # a rule, so a document slot can require e.g. PDF only.
    ensure_columns(db, "resource_rules", ["allowed_formats"])
    # Piece 16: migrate Piece 12.1 statuses to the new phases, and default blanks.
    for old, new in OLD_TO_NEW_STATUS.items():
        db.execute("UPDATE jobs SET status = ? WHERE status = ?", (new, old))
    db.execute(f"UPDATE jobs SET status = '{DEFAULT_JOB_STATUS}'"
               f" WHERE COALESCE(status, '') = ''")
    # A client with any job is 'Converted' (a lead has no job yet).
    db.execute("UPDATE clients SET lead_status = 'Converted'"
               " WHERE lead_status = 'Lead'"
               " AND id IN (SELECT DISTINCT client_id FROM jobs)")
    # Piece 14: change-tracking for task sync; seed blanks from created_at.
    ensure_columns(db, "job_tasks", ["updated_at", "pipeline_status"])
    db.execute("UPDATE job_tasks SET updated_at = COALESCE(NULLIF(created_at,''),"
               " datetime('now')) WHERE COALESCE(updated_at,'') = ''")
    ensure_columns(db, "employees", EMPLOYEE_FIELDS + EMPLOYEE_AUTH_FIELDS
                   + ["dashboard_mode", "base_wage"]  # Piece 21.2: hourly base wage
                   # Piece 29.0: supervisor designation + emergency access lockout.
                   + ["is_supervisor", "access_revoked", "access_revoked_at",
                      "access_revoked_by", "access_revoked_reason"]
                   # Piece 31.2: who's accountable for finishing onboarding.
                   + ["onboarding_owner_id"])
    # Piece 30.9: rename roles to the org-chart outline once (meta-guarded).
    # Rewrites each employee's comma-separated roles via ROLE_RENAMES. The
    # init_db connection returns tuples (no Row factory), so index by position.
    if not db.execute("SELECT 1 FROM meta WHERE key = 'role_names_v2'").fetchone():
        for rid, roles in db.execute("SELECT id, roles FROM employees").fetchall():
            parts = [p.strip() for p in (roles or "").split(",") if p.strip()]
            renamed = [ROLE_RENAMES.get(p, p) for p in parts]
            if renamed != parts:
                db.execute("UPDATE employees SET roles = ? WHERE id = ?",
                           (", ".join(renamed), rid))
        db.execute("INSERT INTO meta (key, value) VALUES ('role_names_v2', '1')"
                   " ON CONFLICT(key) DO UPDATE SET value = excluded.value")
    # Piece 26.8: move Cary's default dashboard to the Executive overview. Runs
    # once (meta-guarded) and only flips the old seeded 'Design' default, so it
    # won't override a choice Cary has since made himself.
    if not db.execute("SELECT 1 FROM meta WHERE key = 'cary_exec_default'").fetchone():
        db.execute("UPDATE employees SET dashboard_mode = 'Executive'"
                   " WHERE name = 'Cary' AND COALESCE(dashboard_mode, '') IN ('', 'Design')")
        db.execute("INSERT INTO meta (key, value) VALUES ('cary_exec_default', '1')"
                   " ON CONFLICT(key) DO UPDATE SET value = excluded.value")
    if db.execute("SELECT COUNT(*) FROM pay_types").fetchone()[0] == 0:
        db.executemany(
            "INSERT INTO pay_types (name, method, value, sort_order)"
            " VALUES (?, ?, ?, ?)", PAY_TYPE_SEED)
    # Piece 21.3: OT-eligibility on pay types + approval status on time entries
    # (existing databases created these tables in 21.2 without the columns).
    pt_cols = {r[1] for r in db.execute("PRAGMA table_info(pay_types)")}
    if "ot_eligible" not in pt_cols:
        db.execute("ALTER TABLE pay_types ADD COLUMN ot_eligible INTEGER NOT NULL DEFAULT 1")
    # PTO / Holiday / a manual Overtime type don't count toward the OT threshold.
    db.execute("UPDATE pay_types SET ot_eligible = 0"
               " WHERE name IN ('PTO', 'Holiday (2x)', 'Overtime (1.5x)')")
    # Piece 26.7: mark leave (vacation/PTO/sick) pay types. Leave hours can't be
    # used to push a week over the 40 h cap — they can't earn overtime — unless a
    # GM overrides it on the approval form. Seed PTO/vacation/sick as leave; a
    # meta flag makes the seed run once so hand-edits aren't overwritten.
    if "is_leave" not in pt_cols:
        db.execute("ALTER TABLE pay_types ADD COLUMN is_leave INTEGER NOT NULL DEFAULT 0")
    if not db.execute("SELECT 1 FROM meta WHERE key = 'pay_leave_seeded'").fetchone():
        db.execute("UPDATE pay_types SET is_leave = 1"
                   " WHERE name IN ('PTO', 'Vacation', 'Sick', 'Sick leave',"
                   "                'Paid time off', 'Leave')")
        db.execute("INSERT OR REPLACE INTO meta (key, value)"
                   " VALUES ('pay_leave_seeded', '1')")
    te_cols = {r[1] for r in db.execute("PRAGMA table_info(time_entries)")}
    if "status" not in te_cols:
        db.execute("ALTER TABLE time_entries ADD COLUMN status TEXT NOT NULL DEFAULT 'Pending'")
        db.execute("ALTER TABLE time_entries ADD COLUMN approved_by TEXT DEFAULT ''")
        db.execute("ALTER TABLE time_entries ADD COLUMN approved_at TEXT DEFAULT ''")
        # Hours logged before approvals existed are treated as already approved.
        db.execute("UPDATE time_entries SET status = 'Approved'")
    ensure_columns(db, "resource_rules",
                   ["field_name2", "field_value2", "match_type2", "link_text"])
    # Piece 26.9: verbatim source text for a rule (esp. compliance) — the exact
    # wording from the code/source, shown above the shorthand in the L/P/C Directory.
    ensure_columns(db, "resource_rules", ["source_text"])
    # Piece 30.1: the ⚠ Verify / ⚠ Unverified callout is an explicit editable
    # field now (was inferred from caution words in the notes).
    ensure_columns(db, "resource_rules", ["verify_status"])
    # Piece 27.1: sample client/job seed removed for production. A fresh
    # database now starts with NO clients, jobs, tasks, or sample employees
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
    seed_onboarding_steps(db)  # Piece 29.2: default onboarding checklist
    seed_finance_reference(db)  # Piece 29.6: county GRT + markup categories
    ensure_columns(db, "jobs", ["travel_miles"])       # Piece 29.6
    # Piece 30.2: cancellation (Lost) metadata — reason, who/when, and the stage
    # to restore on reopen.
    ensure_columns(db, "jobs", ["cancel_reason", "cancelled_at", "cancelled_by",
                                "pre_lost_status"])
    ensure_columns(db, "job_bom", ["markup_pct"])      # per-line markup override
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
    assign_tasks_by_role(db)
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


def condition_met(job, field, value, match_type):
    """One rule condition: the job's field equals the value
    (case-insensitive), or — for 'contains' — the value appears in the
    field's comma-separated list (used for products)."""
    if field not in job.keys():
        return False
    actual = str(job[field] or "").strip()
    if not actual:
        return False
    target = value.strip().lower()
    if match_type == "contains":
        return target in [p.strip().lower() for p in actual.split(",")]
    return actual.lower() == target


def match_rules(job, rules):
    """A rule matches when its condition holds — and, for compound rules,
    when the second condition holds too."""
    hits = []
    for rule in rules:
        if not condition_met(job, rule["field_name"], rule["field_value"],
                             rule["match_type"]):
            continue
        if rule["field_name2"] and not condition_met(
                job, rule["field_name2"], rule["field_value2"],
                rule["match_type2"] or "equals"):
            continue
        hits.append(rule)
    return hits


def _instance_label(rule):
    """Human-readable "what triggered this" for the compact instance bullets:
    the job selection(s) behind a requirement (e.g. "PV Systems")."""
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
    """Group matched rules by category in a fixed order. On job pages,
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
    Drives the 'who on staff is licensed' badges on job pages."""
    rows = get_db().execute(
        "SELECT c.rule_label, c.expires, e.name AS emp_name"
        " FROM employee_credentials c"
        " JOIN employees e ON e.id = c.employee_id"
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
def fetch_job_sizing(db, job_id):
    """One job_sizing row always exists once a job's Loads tab is opened;
    create it lazily with defaults from the schema."""
    row = db.execute("SELECT * FROM job_sizing WHERE job_id = ?", (job_id,)).fetchone()
    if row is None:
        db.execute("INSERT INTO job_sizing (job_id) VALUES (?)", (job_id,))
        db.commit()
        row = db.execute("SELECT * FROM job_sizing WHERE job_id = ?", (job_id,)).fetchone()
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
    fit the sized job — PV modules, batteries, and the inverter. For each role
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
    row = db.execute("SELECT COALESCE(username,'') AS u FROM employees WHERE id = ?",
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
    """The Boards list — standalone to-dos not tied to a job or client.
    Filter by assignee (mine / unassigned / a person / all) and open vs. all."""
    db = get_db()
    me = current_user()
    who = request.args.get("who", "mine" if me else "all")
    show = request.args.get("show", "open")
    sql = ("SELECT b.*, e.name AS assignee_name FROM boards b"
           " LEFT JOIN employees e ON e.id = b.assigned_to WHERE 1 = 1")
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
        "SELECT id, name FROM employees ORDER BY name").fetchall()
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
        " LEFT JOIN employees e ON e.id = b.assigned_to WHERE b.id = ?",
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
        "SELECT id, name FROM employees ORDER BY name").fetchall()
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
        "INSERT INTO board_time (board_id, employee_id, who, hours, work_date, note)"
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
    # The creator, the current assignee, or a GM/Admin may remove a board.
    allowed = (is_gm() or _is_admin()
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


@app.route("/")
def home():
    db = get_db()
    ensure_lead_followups(db)
    clients = db.execute(
        "SELECT c.*, e.name AS rep_name FROM clients c"
        " LEFT JOIN employees e ON e.id = c.assigned_rep_id ORDER BY c.name"
    ).fetchall()
    followups = due_followups(db)
    cold_count = db.execute("SELECT COUNT(*) FROM cold_leads").fetchone()[0]
    return render_template("index.html", clients=clients,
                           followups=followups, cold_count=cold_count,
                           today=datetime.now().strftime("%Y-%m-%d"),
                           job_status_class_json=json.dumps(JOB_STATUS_CLASS))


def _closing_worklist(db):
    """Jobs in the Closing stage with balance due and remaining close-out steps —
    the Executive overview's Closing worklist, also the Sales 'Closing' mode."""
    out = []
    for j in db.execute(
            "SELECT j.*, c.name AS client_name FROM jobs j"
            " JOIN clients c ON c.id = j.client_id"
            " WHERE j.status = 'Closing' ORDER BY j.id").fetchall():
        b = job_billing(db, j["id"], j["contract_amount"] or 0.0)
        steps = db.execute(
            "SELECT title, status FROM job_tasks WHERE job_id = ?"
            " AND pipeline_status = 'Closing' ORDER BY sort_order, id",
            (j["id"],)).fetchall()
        open_steps = [s for s in steps if s["status"] != "Done"]
        out.append({
            "job": j, "balance": max(b["contract"] - b["collected"], 0.0),
            "open": len(open_steps), "total": len(steps),
            "next": open_steps[0]["title"] if open_steps else ""})
    return out


@app.route("/dashboard")
def dashboard():
    """Piece 19: role-based My Dashboard — the sign-in landing. Stacks a
    section per department the person belongs to; a mode switch focuses on one.
    """
    user = current_user()
    if user is None:
        return redirect(url_for("home"))
    db = get_db()
    ensure_lead_followups(db)
    depts = _viewer_modes(user)   # Piece 30.5: Sales sees 'Closing', not 'Installation'
    # Mode: ?mode= sets it for the session; else the saved default; else All.
    if request.args.get("mode"):
        session["dash_mode"] = request.args.get("mode")
    saved = user["dashboard_mode"] if "dashboard_mode" in user.keys() else ""
    # No "All" view (Piece 20.8) — always focused on one role at a time.
    mode = session.get("dash_mode") or saved or (depts[0] if depts else "")
    # A Sales-role viewer's saved/linked 'Installation' resolves to 'Closing'.
    if mode == "Installation" and "Closing" in depts:
        mode = "Closing"
    if mode not in depts:
        mode = depts[0] if depts else ""
    shown = [mode] if mode else []

    my_tasks = db.execute(
        "SELECT t.*, j.job_name, j.id AS job_id, c.name AS client_name"
        " FROM job_tasks t JOIN jobs j ON j.id = t.job_id"
        " JOIN clients c ON c.id = j.client_id"
        " WHERE t.employee_id = ? AND t.status != 'Done' AND j.status != 'Lost'"
        " ORDER BY (t.due_date = ''), t.due_date, j.id", (user["id"],)).fetchall()
    # Piece 21.6: on the Installation (Foreman) viewport, My tasks is the crew's
    # punch list — trim it to on-site field work, dropping office/scheduling
    # steps (e.g. Set Installation Date) that live on other dashboards.
    if mode == "Installation":
        my_tasks = [t for t in my_tasks
                    if (t["pipeline_status"] or "") in FIELD_STAGES]
    # Piece 26.7: group My Tasks under each job so the board reads as a banner per
    # job with its tasks beneath, instead of one flat list. First-seen order keeps
    # the overdue/soonest-due job on top (my_tasks is already sorted that way).
    task_groups = []
    _tg_index = {}
    for t in my_tasks:
        jid = t["job_id"]
        if jid not in _tg_index:
            _tg_index[jid] = len(task_groups)
            task_groups.append({
                "job_id": jid, "job_name": t["job_name"],
                "client_name": t["client_name"], "tasks": []})
        task_groups[_tg_index[jid]]["tasks"].append(t)

    sections = []
    for d in shown:
        cfg = MODE_CONFIG[d]
        jobs = []
        if cfg["stages"]:
            placeholders = ", ".join("?" * len(cfg["stages"]))
            jobs = db.execute(
                f"SELECT j.id, j.job_name, j.status, j.install_date,"
                f" j.electric_loads, c.name AS client_name FROM jobs j"
                f" JOIN clients c ON c.id = j.client_id"
                f" WHERE j.status IN ({placeholders})"
                f" ORDER BY j.status, j.id", cfg["stages"]).fetchall()
        sections.append({"name": d, "icon": cfg["icon"], "jobs": jobs,
                         "stages": cfg["stages"]})

    # Progress + loads-recorded status for every job shown across the sections.
    progress_by_job = {}
    loads_by_job = {}
    for sec in sections:
        for j in sec["jobs"]:
            if j["id"] not in progress_by_job:
                progress_by_job[j["id"]] = build_job_progress(db, j)
                loads_by_job[j["id"]] = _loads_recorded(db, j)

    # Permits viewport: permit filing coverage (X/Y) per job on the jobs table.
    show_permits = "Permits" in shown
    permits_by_job = {}
    if show_permits:
        rules = db.execute("SELECT * FROM resource_rules").fetchall()
        for sec in sections:
            if sec["name"] == "Permits":
                for j in sec["jobs"]:
                    full = db.execute("SELECT * FROM jobs WHERE id = ?", (j["id"],)).fetchone()
                    permits_by_job[j["id"]] = job_permit_coverage(db, full, rules)

    # Purchasing viewport: procurement rollup — material counts by status per job.
    show_procurement = "Purchasing" in shown
    procurement = []
    if show_procurement:
        for sec in sections:
            if sec["name"] == "Purchasing":
                for j in sec["jobs"]:
                    counts = {s: 0 for s in MATERIAL_STATUSES}
                    total = 0
                    for m in db.execute(
                            "SELECT status, COUNT(*) AS n FROM job_materials"
                            " WHERE job_id = ? GROUP BY status", (j["id"],)).fetchall():
                        counts[m["status"]] = counts.get(m["status"], 0) + m["n"]
                        total += m["n"]
                    outstanding = (counts.get("Needed", 0) + counts.get("Quoted", 0)
                                   + counts.get("Backordered", 0))
                    procurement.append({"job": j, "counts": counts, "total": total,
                                        "outstanding": outstanding})

    # Piece 30.5: Sales 'Closing' viewport — Closing-stage jobs with balance due
    # and remaining close-out steps (reuses the Executive Closing worklist).
    show_closing = "Closing" in shown
    closing_jobs = _closing_worklist(db) if show_closing else []

    # Piece 21.6: Installation (Foreman) viewport — split the Installation /
    # Inspections jobs by install-date timing so the crew sees what's imminent.
    show_install = "Installation" in shown
    install_buckets = []
    if show_install:
        today_d = datetime.now().date()
        week_end = today_d + timedelta(days=7)

        def _idate(j):
            try:
                return datetime.strptime(j["install_date"], "%Y-%m-%d").date()
            except (ValueError, TypeError):
                return None
        wk, up, other = [], [], []
        for sec in sections:
            if sec["name"] == "Installation":
                for j in sec["jobs"]:
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
             "hint": "installs in the next 7 days", "jobs": _srt(wk)},
            {"key": "upcoming", "label": "📅 Upcoming",
             "hint": "scheduled further out", "jobs": _srt(up)},
            {"key": "other", "label": "🔎 In inspection / unscheduled",
             "hint": "install date passed or not set yet", "jobs": _srt(other)},
        ]

    # Piece 22.3: Executive (GM) overview — a whole-company snapshot: pipeline
    # counts by stage, money in flight, what needs attention, this week's
    # installs, and a Closing worklist (balance due + remaining closing steps).
    show_exec = "Executive" in shown
    gm = None
    if show_exec:
        today_s = datetime.now().date().strftime("%Y-%m-%d")
        exec_stages = STAGE_ORDER[:-1]           # Proposal .. Closing
        counts = {s: 0 for s in exec_stages}
        money = {"contract": 0.0, "collected": 0.0,
                 "outstanding": 0.0, "expense": 0.0}
        for j in db.execute(
                "SELECT id, status, contract_amount FROM jobs"
                " WHERE status != 'Lost'").fetchall():
            if j["status"] in counts:
                counts[j["status"]] += 1
            b = job_billing(db, j["id"], j["contract_amount"] or 0.0)
            for k in money:
                money[k] += b[k]
        overdue = db.execute(
            "SELECT COUNT(*) FROM job_tasks t JOIN jobs j ON j.id = t.job_id"
            " WHERE t.status != 'Done' AND t.due_date != '' AND t.due_date < ?"
            " AND j.status NOT IN ('Lost', 'Complete')", (today_s,)).fetchone()[0]
        # Stalled: active jobs whose newest task activity is over 14 days old
        # (jobs that had movement and then went quiet; brand-new no-task jobs
        # are excluded).
        cutoff = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d %H:%M:%S")
        stalled = db.execute(
            "SELECT j.id, j.job_name, j.status, c.name AS client_name,"
            " MAX(t.updated_at) AS last FROM jobs j"
            " JOIN clients c ON c.id = j.client_id"
            " JOIN job_tasks t ON t.job_id = j.id"
            " WHERE j.status NOT IN ('Lost', 'Complete')"
            " GROUP BY j.id HAVING last IS NOT NULL AND last < ?"
            " ORDER BY last", (cutoff,)).fetchall()
        wk_end = (datetime.now().date() + timedelta(days=7)).strftime("%Y-%m-%d")
        installs_week = db.execute(
            "SELECT j.id, j.job_name, j.status, j.install_date,"
            " c.name AS client_name FROM jobs j JOIN clients c ON c.id = j.client_id"
            " WHERE j.install_date != '' AND j.install_date BETWEEN ? AND ?"
            " AND j.status != 'Lost' ORDER BY j.install_date",
            (today_s, wk_end)).fetchall()
        closing = _closing_worklist(db)
        # Ready for design: Proposal jobs whose load survey is captured (the
        # step before design) but whose design isn't finalized yet — the
        # Sales → Designer hand-off queue.
        ready_design = []
        for j in db.execute(
                "SELECT j.id, j.job_name, j.electric_loads, c.name AS client_name"
                " FROM jobs j JOIN clients c ON c.id = j.client_id"
                " WHERE j.status = 'Proposal' ORDER BY j.id").fetchall():
            if not _loads_recorded(db, j):
                continue
            designed = db.execute(
                "SELECT 1 FROM job_tasks WHERE job_id = ?"
                " AND LOWER(title) LIKE '%finalize%design%' AND status = 'Done'"
                " LIMIT 1", (j["id"],)).fetchone()
            if not designed:
                ready_design.append(j)
        gm = {"counts": [(s, counts[s]) for s in exec_stages], "money": money,
              "approvals": db.execute(
                  "SELECT COUNT(*) FROM field_submissions"
                  " WHERE status = 'Pending'").fetchone()[0],
              "overdue": overdue, "stalled": stalled, "ready_design": ready_design,
              "installs_week": installs_week, "closing": closing}

    # Leads worklist (Piece 20.8): active leads (not yet converted) with their
    # next open follow-up, for the Sales viewport. Replaces the generic Client
    # Profiles list here — converted clients now live under Active Proposals.
    # Finance viewport: Payments table across every active job (all in-flight
    # money — deposits, invoices, expenses), with a QuickBooks export.
    show_payments = "Finance" in shown
    payments = []
    pay_totals = {"contract": 0.0, "collected": 0.0, "outstanding": 0.0,
                  "expense": 0.0, "net": 0.0}
    if show_payments:
        for j in db.execute(
                "SELECT j.id, j.job_name, j.status, j.contract_amount,"
                " c.name AS client_name FROM jobs j"
                " JOIN clients c ON c.id = j.client_id"
                " WHERE j.status != 'Lost' ORDER BY j.status, j.id").fetchall():
            b = job_billing(db, j["id"], j["contract_amount"] or 0.0)
            payments.append({"job": j, "b": b})
            for k in pay_totals:
                pay_totals[k] += b[k]

    show_leads = "Sales" in shown
    leads = []
    if show_leads:
        leads = db.execute(
            "SELECT c.id AS client_id, c.name AS client_name, c.phone AS client_phone,"
            " e.name AS rep_name, f.id AS followup_id, f.milestone AS milestone,"
            " f.due_date AS due_date FROM clients c"
            " LEFT JOIN employees e ON e.id = c.assigned_rep_id"
            " LEFT JOIN lead_followups f ON f.id = ("
            "   SELECT id FROM lead_followups x WHERE x.client_id = c.id"
            "   AND x.status = 'Open' ORDER BY x.due_date LIMIT 1)"
            " WHERE c.lead_status = 'Lead'"
            " ORDER BY (f.due_date IS NULL), f.due_date, c.name").fetchall()
    pending_subs = (db.execute("SELECT COUNT(*) FROM field_submissions"
                               " WHERE status = 'Pending'").fetchone()[0]
                    if "Executive" in shown else 0)
    # Piece 24.4: the stale-stock notice lands on the Designer's dashboard.
    stale_stock = len(stale_stock_items(db)) if "Design" in shown else 0
    # Piece 26.7: payroll reminder on the Finance viewport for whoever runs
    # payroll (Vanessa) — a Tue–Thu nudge until the period is confirmed + exported.
    payroll_reminder = None
    if "Finance" in shown and _can_payroll():
        p_start, p_end = _pay_period()
        payroll_reminder = payroll_status(db, p_start, p_end)
    # Piece 31.8: the 50/40/10 pay-scheme callout moved off the dashboard and
    # into the job Estimate (Sales/Finance only, before the contract is signed).
    return render_template(
        "dashboard.html", user=user, depts=depts, mode=mode, saved_default=saved,
        stale_stock=stale_stock, task_groups=task_groups,
        payroll_reminder=payroll_reminder,
        sections=sections, my_tasks=my_tasks, leads=leads, show_leads=show_leads,
        payments=payments, pay_totals=pay_totals, show_payments=show_payments,
        pending_subs=pending_subs, today=datetime.now().strftime("%Y-%m-%d"),
        dept_icons={d: c["icon"] for d, c in MODE_CONFIG.items()},
        progress_by_job=progress_by_job, loads_by_job=loads_by_job,
        permits_by_job=permits_by_job, show_procurement=show_procurement,
        procurement=procurement, material_statuses=MATERIAL_STATUSES,
        show_install=show_install, install_buckets=install_buckets, gm=gm,
        show_closing=show_closing, closing_jobs=closing_jobs,   # Piece 30.5
        job_status_class=JOB_STATUS_CLASS)


@app.route("/dashboard/default", methods=["POST"])
def set_dashboard_default():
    """Save the current mode as this user's default dashboard (their working
    role) — supports Cary defaulting to Designer, and aids training."""
    user = current_user()
    if user is None:
        return redirect(url_for("home"))
    mode = request.form.get("mode", "All")
    get_db().execute("UPDATE employees SET dashboard_mode = ? WHERE id = ?",
                     (mode, user["id"]))
    get_db().commit()
    session["dash_mode"] = mode
    flash(f"Default dashboard set to {mode}.")
    return redirect(url_for("dashboard"))


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
        job = t["job_name"] or f"Job #{t['job_id']}"
        desc = f"Client: {t['client_name']}\nStatus: {t['status']}"
        if t["pipeline_status"]:
            desc += f"\nStage: {t['pipeline_status']}"
        events.append({"uid": f"compendium-task-{t['id']}@vixinmandesigns",
                       "date": t["due_date"], "summary": f"{t['title']} — {job}",
                       "description": desc})
    return events


@app.route("/calendar/my.ics")
def my_calendar_ics():
    """The signed-in person's task due dates + install dates for their jobs,
    as an importable calendar. In open mode (no login) exports everything."""
    db = get_db()
    user = current_user()
    tsql = ("SELECT t.*, j.job_name, c.name AS client_name FROM job_tasks t"
            " JOIN jobs j ON j.id = t.job_id JOIN clients c ON c.id = j.client_id"
            " WHERE COALESCE(t.due_date, '') != ''")
    jsql = ("SELECT DISTINCT j.id, j.job_name, j.install_date,"
            " c.name AS client_name FROM jobs j JOIN clients c ON c.id = j.client_id"
            " WHERE COALESCE(j.install_date, '') != ''")
    params = []
    if user:
        tsql += " AND t.employee_id = ?"
        jsql += " AND j.id IN (SELECT job_id FROM job_tasks WHERE employee_id = ?)"
        params = [user["id"]]
    events = _task_events(db.execute(tsql, params).fetchall())
    for j in db.execute(jsql, params).fetchall():
        events.append({"uid": f"compendium-install-{j['id']}@vixinmandesigns",
                       "date": j["install_date"],
                       "summary": f"🔧 Install: {j['job_name'] or 'Job #' + str(j['id'])}",
                       "description": f"Client: {j['client_name']}"})
    name = f"Compendium — {user['name']}" if user else "Compendium — due dates"
    return _ics_response(name, events, "compendium-my-dates.ics")


@app.route("/jobs/<int:job_id>/calendar.ics")
def job_calendar_ics(job_id):
    """One job's task due dates + its install date, as an importable calendar."""
    job = fetch_job(job_id)
    db = get_db()
    rows = db.execute(
        "SELECT t.*, ? AS job_name, ? AS client_name FROM job_tasks t"
        " WHERE t.job_id = ? AND COALESCE(t.due_date, '') != ''",
        (job["job_name"], job["client_name"], job_id)).fetchall()
    events = _task_events(rows)
    if job["install_date"]:
        events.append({"uid": f"compendium-install-{job_id}@vixinmandesigns",
                       "date": job["install_date"],
                       "summary": f"🔧 Install: {job['job_name'] or 'Job #' + str(job_id)}",
                       "description": f"Client: {job['client_name']}"})
    label = job["job_name"] or f"Job #{job_id}"
    return _ics_response(f"Compendium — {label}", events, f"compendium-job-{job_id}.ics")


@app.route("/search")
def search():
    """Quick lookup across clients and jobs by name/address/phone/email/
    county."""
    q = (request.args.get("q") or "").strip()
    clients, jobs = [], []
    if q:
        like = f"%{q}%"
        db = get_db()
        clients = db.execute(
            "SELECT * FROM clients"
            " WHERE name LIKE ? OR mailing_address LIKE ? OR billing_address LIKE ?"
            " OR phone LIKE ? OR email LIKE ? ORDER BY name",
            (like, like, like, like, like)).fetchall()
        jobs = db.execute(
            "SELECT j.*, c.name AS client_name FROM jobs j"
            " JOIN clients c ON c.id = j.client_id"
            " WHERE j.job_name LIKE ? OR j.site_location LIKE ? OR j.county LIKE ?"
            " OR j.products LIKE ? OR c.name LIKE ? ORDER BY j.created_at DESC",
            (like, like, like, like, like)).fetchall()
    return render_template("search.html", q=q, clients=clients, jobs=jobs,
                           job_status_class=JOB_STATUS_CLASS)


@app.route("/api/quick-search")
def api_quick_search():
    """Piece 28.4: autocomplete for the nav search — client and job NAMES only.
    Each job result carries its client name so the crew can tell jobs apart."""
    q = (request.args.get("q") or "").strip()
    results = []
    if q:
        like = f"%{q}%"
        db = get_db()
        for c in db.execute(
                "SELECT id, name FROM clients WHERE name LIKE ? ORDER BY name LIMIT 6",
                (like,)).fetchall():
            results.append({"type": "client", "label": c["name"], "sub": "",
                            "url": url_for("client_detail", client_id=c["id"])})
        for j in db.execute(
                "SELECT j.id, j.job_name, c.name AS client_name FROM jobs j"
                " JOIN clients c ON c.id = j.client_id"
                " WHERE j.job_name LIKE ? OR c.name LIKE ?"
                " ORDER BY j.created_at DESC LIMIT 8", (like, like)).fetchall():
            results.append({"type": "job",
                            "label": j["job_name"] or f"Job #{j['id']}",
                            "sub": j["client_name"],
                            "url": url_for("job_detail", job_id=j["id"])})
    return jsonify({"results": results})


@app.route("/clients/new", methods=["GET", "POST"])
def new_client():
    if request.method == "POST":
        values = read_client_form()
        missing = [label for field, label in REQUIRED_CLIENT_FIELDS.items()
                   if not values[field]]
        if missing:
            flash(f"Required: {', '.join(missing)}.", "error")
            return render_template("client_form.html", values=values,
                                   crew=crew_list()), 400
        db = get_db()
        cur = db.execute(
            f"INSERT INTO clients ({', '.join(CLIENT_FIELDS)})"
            f" VALUES ({', '.join('?' * len(CLIENT_FIELDS))})",
            [values[f] for f in CLIENT_FIELDS],
        )
        db.commit()
        flash(f"Client profile created: {values['name']}")
        return redirect(url_for("client_detail", client_id=cur.lastrowid))
    return render_template("client_form.html", values={}, crew=crew_list())


@app.route("/clients/<int:client_id>/edit", methods=["GET", "POST"])
def edit_client(client_id):
    db = get_db()
    client = db.execute(
        "SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()
    if client is None:
        abort(404)
    if request.method == "POST":
        values = read_client_form()
        missing = [label for field, label in REQUIRED_CLIENT_FIELDS.items()
                   if not values[field]]
        if missing:
            flash(f"Required: {', '.join(missing)}.", "error")
            return render_template("client_form.html", values=values,
                                   client_id=client_id, crew=crew_list()), 400
        # Record what changed before overwriting, so the old data is kept
        # (hidden on the profile; admins can open the history).
        changed = [CLIENT_FIELD_LABELS.get(f, f) for f in CLIENT_FORM_FIELDS
                   if (client[f] or "") != values[f]]
        if changed:
            snapshot = {f: client[f] for f in CLIENT_FIELDS}
            version = db.execute(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM client_versions"
                " WHERE client_id = ?", (client_id,)).fetchone()[0]
            editor = current_user()
            db.execute(
                "INSERT INTO client_versions"
                " (client_id, version, data, changed_fields, edited_by)"
                " VALUES (?, ?, ?, ?, ?)",
                (client_id, version, json.dumps(snapshot),
                 json.dumps(changed), editor["name"] if editor else ""),
            )
        db.execute(
            f"UPDATE clients SET {', '.join(f + ' = ?' for f in CLIENT_FIELDS)}"
            " WHERE id = ?",
            [values[f] for f in CLIENT_FIELDS] + [client_id],
        )
        db.commit()
        flash(f"Client profile updated: {values['name']}")
        return redirect(url_for("client_detail", client_id=client_id))
    values = {f: client[f] for f in CLIENT_FORM_FIELDS}
    # Legacy fallback: clients created before the split have only the composed
    # address. Drop it into the street line so nothing is lost when editing.
    if not any(values[p] for p in MAILING_PARTS) and client["mailing_address"]:
        values["mailing_street"] = client["mailing_address"]
    if not any(values[p] for p in BILLING_PARTS) and client["billing_address"]:
        values["billing_street"] = client["billing_address"]
    return render_template("client_form.html", values=values,
                           client_id=client_id, crew=crew_list())


@app.route("/clients/<int:client_id>")
def client_detail(client_id):
    db = get_db()
    client = db.execute(
        "SELECT * FROM clients WHERE id = ?", (client_id,)
    ).fetchone()
    if client is None:
        abort(404)
    jobs = db.execute(
        "SELECT * FROM jobs WHERE client_id = ? ORDER BY created_at DESC",
        (client_id,),
    ).fetchall()
    files = db.execute(
        "SELECT * FROM client_files WHERE client_id = ? ORDER BY id", (client_id,)
    ).fetchall()
    edit_count = db.execute(
        "SELECT COUNT(*) FROM client_versions WHERE client_id = ?", (client_id,)
    ).fetchone()[0]
    last_edit = db.execute(
        "SELECT edited_by, saved_at FROM client_versions"
        " WHERE client_id = ? ORDER BY version DESC LIMIT 1", (client_id,)
    ).fetchone()
    rep = None
    if client["assigned_rep_id"]:
        rep = db.execute("SELECT name FROM employees WHERE id = ?",
                         (client["assigned_rep_id"],)).fetchone()
    followups = db.execute(
        "SELECT * FROM lead_followups WHERE client_id = ?"
        " ORDER BY due_date", (client_id,)).fetchall()
    progress_by_job = {j["id"]: build_job_progress(db, j) for j in jobs}
    return render_template("client_detail.html", client=client, jobs=jobs,
                           files=files, file_categories=CLIENT_FILE_CATEGORIES,
                           job_status_class=JOB_STATUS_CLASS,
                           edit_count=edit_count, last_edit=last_edit,
                           rep=rep, followups=followups,
                           progress_by_job=progress_by_job,
                           today=datetime.now().strftime("%Y-%m-%d"))


@app.route("/clients/<int:client_id>/history")
@admin_required
def client_history(client_id):
    """Admin-only: the hidden older versions of a client profile."""
    db = get_db()
    client = db.execute(
        "SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()
    if client is None:
        abort(404)
    rows = db.execute(
        "SELECT * FROM client_versions WHERE client_id = ?"
        " ORDER BY version DESC", (client_id,)).fetchall()
    versions = []
    for r in rows:
        versions.append({
            "version": r["version"],
            "edited_by": r["edited_by"],
            "saved_at": r["saved_at"],
            "changed": json.loads(r["changed_fields"] or "[]"),
            "data": json.loads(r["data"] or "{}"),
        })
    return render_template("client_history.html", client=client,
                           versions=versions, labels=CLIENT_FIELD_LABELS)


@app.route("/api/search")
def api_search():
    """Live type-ahead preview for the clients landing page: a few matching
    clients and jobs as JSON."""
    q = (request.args.get("q") or "").strip()
    result = {"clients": [], "jobs": []}
    if len(q) >= 1:
        like = f"%{q}%"
        db = get_db()
        for c in db.execute(
                "SELECT id, name, phone, mailing_address FROM clients"
                " WHERE name LIKE ? OR mailing_address LIKE ? OR billing_address"
                " LIKE ? OR phone LIKE ? OR email LIKE ? ORDER BY name LIMIT 6",
                (like, like, like, like, like)).fetchall():
            result["clients"].append({
                "id": c["id"], "name": c["name"], "phone": c["phone"],
                "address": c["mailing_address"]})
        for j in db.execute(
                "SELECT j.id, j.job_name, j.status, c.name AS client_name"
                " FROM jobs j JOIN clients c ON c.id = j.client_id"
                " WHERE j.job_name LIKE ? OR j.site_location LIKE ?"
                " OR j.county LIKE ? OR j.products LIKE ? OR c.name LIKE ?"
                " ORDER BY j.created_at DESC LIMIT 6",
                (like, like, like, like, like)).fetchall():
            result["jobs"].append({
                "id": j["id"], "name": j["job_name"] or f"Job #{j['id']}",
                "status": j["status"] or DEFAULT_JOB_STATUS,
                "client_name": j["client_name"]})
    return jsonify(result)


# ---------------------------------------------------------- lead follow-ups
@app.route("/followups/<int:followup_id>/done", methods=["POST"])
def followup_done(followup_id):
    """Log that a follow-up was made; the next scheduled one still stands."""
    db = get_db()
    db.execute("UPDATE lead_followups SET status = 'Done',"
               " done_at = datetime('now') WHERE id = ?", (followup_id,))
    db.commit()
    flash("Follow-up logged.")
    return redirect(request.form.get("next") or url_for("home"))


@app.route("/clients/<int:client_id>/mark-cold", methods=["POST"])
def mark_cold(client_id):
    """Move a lead out of the active list into the cold_leads table. Only
    leads (no jobs) can go cold."""
    db = get_db()
    client = db.execute("SELECT * FROM clients WHERE id = ?",
                        (client_id,)).fetchone()
    if client is None:
        abort(404)
    if db.execute("SELECT COUNT(*) FROM jobs WHERE client_id = ?",
                  (client_id,)).fetchone()[0] > 0:
        flash("This client has jobs, so it isn't a lead — it can't be marked cold.",
              "error")
        return redirect(url_for("client_detail", client_id=client_id))
    reason = request.form.get("reason", "").strip()
    db.execute(
        f"INSERT INTO cold_leads ({', '.join(COLD_LEAD_FIELDS)},"
        " cold_reason, original_created_at)"
        f" VALUES ({', '.join('?' * len(COLD_LEAD_FIELDS))}, ?, ?)",
        [client[f] for f in COLD_LEAD_FIELDS] + [reason, client["created_at"]],
    )
    db.execute("DELETE FROM lead_followups WHERE client_id = ?", (client_id,))
    db.execute("DELETE FROM client_versions WHERE client_id = ?", (client_id,))
    db.execute("DELETE FROM client_files WHERE client_id = ?", (client_id,))
    db.execute("DELETE FROM clients WHERE id = ?", (client_id,))
    db.commit()
    flash(f"{client['name']} moved to cold leads.")
    nxt = request.form.get("next", "")
    if nxt.startswith("/") and not nxt.startswith("//"):
        return redirect(nxt)
    return redirect(url_for("home"))


@app.route("/cold-leads")
@admin_required
def cold_leads_page():
    db = get_db()
    rows = db.execute(
        "SELECT cl.*, e.name AS rep_name FROM cold_leads cl"
        " LEFT JOIN employees e ON e.id = cl.assigned_rep_id"
        " ORDER BY cl.cold_at DESC").fetchall()
    stale_before = (datetime.now() - timedelta(days=COLD_LEAD_STALE_DAYS)
                    ).strftime("%Y-%m-%d %H:%M:%S")
    return render_template("cold_leads.html", leads=rows,
                           stale_before=stale_before,
                           stale_days=COLD_LEAD_STALE_DAYS)


@app.route("/cold-leads/<int:cold_id>/restore", methods=["POST"])
@admin_required
def restore_cold_lead(cold_id):
    db = get_db()
    cl = db.execute("SELECT * FROM cold_leads WHERE id = ?", (cold_id,)).fetchone()
    if cl is None:
        abort(404)
    db.execute(
        f"INSERT INTO clients ({', '.join(COLD_LEAD_FIELDS)}, lead_status)"
        f" VALUES ({', '.join('?' * len(COLD_LEAD_FIELDS))}, 'Lead')",
        [cl[f] for f in COLD_LEAD_FIELDS],
    )
    db.execute("DELETE FROM cold_leads WHERE id = ?", (cold_id,))
    db.commit()
    flash(f"{cl['name']} restored to active leads.")
    return redirect(url_for("cold_leads_page"))


@app.route("/cold-leads/<int:cold_id>/delete", methods=["POST"])
@delete_required
def purge_cold_lead(cold_id):
    db = get_db()
    cl = db.execute("SELECT name FROM cold_leads WHERE id = ?",
                    (cold_id,)).fetchone()
    if cl is None:
        abort(404)
    db.execute("DELETE FROM cold_leads WHERE id = ?", (cold_id,))
    db.commit()
    flash(f"Deleted cold lead: {cl['name']}.")
    return redirect(url_for("cold_leads_page"))


# ---- client-level documents (contracts, correspondence, intake, photos) ---
def client_upload_dir(client_id):
    directory = UPLOADS_DIR / f"client_{client_id}"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


@app.route("/clients/<int:client_id>/files/upload", methods=["POST"])
def upload_client_file(client_id):
    if get_db().execute("SELECT id FROM clients WHERE id = ?",
                        (client_id,)).fetchone() is None:
        abort(404)
    upload = request.files.get("document")
    if upload is None or not upload.filename:
        flash("Choose a file to upload.", "error")
        return redirect(url_for("client_detail", client_id=client_id, _anchor="documents"))
    extension = upload.filename.rsplit(".", 1)[-1].lower() if "." in upload.filename else ""
    if extension not in ALLOWED_EXTENSIONS:
        flash(f"File type .{extension} is not allowed.", "error")
        return redirect(url_for("client_detail", client_id=client_id, _anchor="documents"))
    category = request.form.get("category", "").strip()
    if category not in CLIENT_FILE_CATEGORIES:
        category = ""
    db = get_db()
    # Piece 25.4: auto-rename to Client_Category_Date.ext for recordkeeping.
    cname = db.execute("SELECT name FROM clients WHERE id = ?",
                       (client_id,)).fetchone()
    friendly = friendly_filename(
        [cname["name"] if cname else "", category or "Document"], extension,
        taken=_taken_names(db, "client_files", "original_name", "client_id", client_id))
    stored = f"{uuid.uuid4().hex[:8]}_{secure_filename(friendly)}"
    upload.save(client_upload_dir(client_id) / stored)
    db.execute(
        "INSERT INTO client_files (client_id, category, stored_name, original_name)"
        " VALUES (?, ?, ?, ?)",
        (client_id, category, stored, friendly),
    )
    db.commit()
    flash(f"Uploaded: {friendly}")
    return redirect(url_for("client_detail", client_id=client_id, _anchor="documents"))


@app.route("/clients/<int:client_id>/files/<int:file_id>/download")
def download_client_file(client_id, file_id):
    record = get_db().execute(
        "SELECT * FROM client_files WHERE id = ? AND client_id = ?",
        (file_id, client_id)).fetchone()
    if record is None:
        abort(404)
    return send_from_directory(
        client_upload_dir(client_id), record["stored_name"],
        as_attachment=True, download_name=record["original_name"])


@app.route("/clients/<int:client_id>/files/<int:file_id>/delete", methods=["POST"])
@delete_required
def delete_client_file(client_id, file_id):
    ok, msg = trash_item("client_file", file_id)
    flash(msg, "" if ok else "error")
    return redirect(url_for("client_detail", client_id=client_id, _anchor="documents"))


@app.route("/clients/<int:client_id>/jobs/new", methods=["GET", "POST"])
def new_job(client_id):
    db = get_db()
    client = db.execute(
        "SELECT * FROM clients WHERE id = ?", (client_id,)
    ).fetchone()
    if client is None:
        abort(404)
    if request.method == "POST":
        values, selected, errors = read_job_form()
        if errors:
            flash(" ".join(errors), "error")
            return render_job_form(client, values, selected,
                                   existing_jobs=True), 400
        cur = db.execute(
            f"INSERT INTO jobs (client_id, {', '.join(JOB_FIELDS)})"
            f" VALUES (?, {', '.join('?' * len(JOB_FIELDS))})",
            [client_id] + [values[f] for f in JOB_FIELDS],
        )
        # Piece 16: entering job details converts a lead — stop its follow-ups.
        if client["lead_status"] == "Lead":
            db.execute("UPDATE clients SET lead_status = 'Converted',"
                       " converted_at = datetime('now') WHERE id = ?", (client_id,))
            db.execute("UPDATE lead_followups SET status = 'Converted'"
                       " WHERE client_id = ? AND status = 'Open'", (client_id,))
        # Piece 29.4: a new job turns over to Proposal — alert Sales & Design.
        new_job_row = {"id": cur.lastrowid, "client_id": client_id,
                       "job_name": values["job_name"]}
        actor = current_user()
        notify_stage_turnover(db, new_job_row,
                              values.get("status") or DEFAULT_JOB_STATUS,
                              exclude_id=actor["id"] if actor else None)
        db.commit()
        flash(f"Job created under {client['name']}: {values['job_name']}")
        return redirect(url_for("job_detail", job_id=cur.lastrowid))
    # For service tickets: optionally pre-fill from a job already on the
    # books for this client.
    values = {"site_location": client["mailing_address"]}
    selected = []
    prefill_id = request.args.get("prefill", type=int)
    if prefill_id:
        source = db.execute(
            "SELECT * FROM jobs WHERE id = ? AND client_id = ?",
            (prefill_id, client_id),
        ).fetchone()
        if source:
            values = {f: source[f] for f in JOB_FIELDS}
            values["utility_connection"] = next(
                (source[f] for f in GRID_CONNECTION_FIELDS.values() if source[f]), "")
            values["job_name"] = f"Service — {source['job_name'] or 'Job #' + str(source['id'])}"
            selected = [p.strip() for p in source["products"].split(",") if p.strip()]
            if "Technician Service" not in selected:
                selected.append("Technician Service")
    return render_job_form(client, values, selected, existing_jobs=True)


def read_job_form():
    """Validate and normalize a submitted job form (create or edit)."""
    values = {f: request.form.get(f, "").strip() for f in JOB_FIELDS}
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
        errors.append("Job name is required.")
    if not values["site_location"]:
        errors.append("Site location is required.")
    if not values["cost_method"]:
        errors.append("Payment is required.")
    if not values["products"]:
        errors.append("Select at least one product/service.")
    if "Technician Service" in selected and not values["service_type"]:
        errors.append("Specify general or warranty service.")
    return values, selected, errors


def render_job_form(client, values, selected, existing_jobs=False,
                    editing_job_id=None):
    jobs_on_books = []
    if existing_jobs and not editing_job_id:
        jobs_on_books = get_db().execute(
            "SELECT id, job_name FROM jobs WHERE client_id = ?",
            (client["id"],)).fetchall()
    return render_template(
        "job_form.html", client=client, values=values, selected=selected,
        products=PRODUCTS, utility_connections=UTILITY_CONNECTIONS,
        mounting_types=MOUNTING_TYPES, service_types=SERVICE_TYPES,
        payment_terms=PAYMENT_TERMS,                       # Piece 31.8
        utilities=UTILITIES, counties=COUNTIES,
        county_utilities_json=json.dumps(COUNTY_UTILITIES),
        utilities_json=json.dumps(UTILITIES),
        existing_jobs=jobs_on_books, editing_job_id=editing_job_id,
    )


@app.route("/jobs/<int:job_id>/edit", methods=["GET", "POST"])
def edit_job(job_id):
    db = get_db()
    job = fetch_job(job_id)
    client = db.execute(
        "SELECT * FROM clients WHERE id = ?", (job["client_id"],)
    ).fetchone()
    if request.method == "POST":
        values, selected, errors = read_job_form()
        if errors:
            flash(" ".join(errors), "error")
            return render_job_form(client, values, selected,
                                   editing_job_id=job_id), 400
        # Keep the outgoing state for recordkeeping before overwriting.
        snapshot = {f: job[f] for f in JOB_FIELDS}
        version = db.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 FROM job_versions"
            " WHERE job_id = ?", (job_id,)).fetchone()[0]
        db.execute(
            "INSERT INTO job_versions (job_id, version, data) VALUES (?, ?, ?)",
            (job_id, version, json.dumps(snapshot)),
        )
        db.execute(
            f"UPDATE jobs SET {', '.join(f + ' = ?' for f in JOB_FIELDS)}"
            " WHERE id = ?",
            [values[f] for f in JOB_FIELDS] + [job_id],
        )
        db.commit()
        flash(f"Job updated — the previous state was kept as version {version}.")
        return redirect(url_for("job_detail", job_id=job_id))
    values = {f: job[f] for f in JOB_FIELDS}
    values["utility_connection"] = next(
        (job[f] for f in GRID_CONNECTION_FIELDS.values() if job[f]), "")
    selected = [p.strip() for p in job["products"].split(",") if p.strip()]
    return render_job_form(client, values, selected, editing_job_id=job_id)


@app.route("/jobs/<int:job_id>/versions/<int:version>")
def job_version(job_id, version):
    job = fetch_job(job_id)
    row = get_db().execute(
        "SELECT * FROM job_versions WHERE job_id = ? AND version = ?",
        (job_id, version),
    ).fetchone()
    if row is None:
        abort(404)
    data = json.loads(row["data"])
    rules = get_db().execute("SELECT * FROM resource_rules").fetchall()
    groups = group_rules(match_rules(data, rules))
    return render_template(
        "job_version.html", job=job, version=row, data=data,
        groups=groups, field_labels=JOB_FIELD_LABELS, job_fields=JOB_FIELDS,
    )


def fetch_job(job_id):
    job = get_db().execute(
        "SELECT jobs.*, clients.name AS client_name"
        " FROM jobs JOIN clients ON clients.id = jobs.client_id"
        " WHERE jobs.id = ?",
        (job_id,),
    ).fetchone()
    if job is None:
        abort(404)
    return job


@app.route("/jobs/<int:job_id>")
def job_detail(job_id):
    job = fetch_job(job_id)
    db = get_db()
    # Piece 29.4: reaching the job clears this user's stage-turnover alerts for
    # it — the notification has served its purpose once they're looking at it.
    me = current_user()
    if me is not None:
        cleared = db.execute(
            "DELETE FROM notifications WHERE recipient_id = ? AND kind = 'stage'"
            " AND link = ?", (me["id"], url_for("job_detail", job_id=job_id)))
        if cleared.rowcount:
            db.commit()
    rules = db.execute("SELECT * FROM resource_rules").fetchall()
    groups = group_rules(match_rules(job, rules))
    versions = db.execute(
        "SELECT version, saved_at FROM job_versions WHERE job_id = ?"
        " ORDER BY version DESC", (job_id,)
    ).fetchall()
    materials = db.execute(
        "SELECT * FROM job_materials WHERE job_id = ? ORDER BY id", (job_id,)
    ).fetchall()
    files = db.execute(
        "SELECT * FROM job_files WHERE job_id = ? ORDER BY id", (job_id,)
    ).fetchall()
    filed_labels = {f["rule_label"] for f in files if f["rule_label"]}
    # Filing coverage per category: how many requirements have a document.
    coverage = {
        heading: sum(1 for r in items if r["label"] in filed_labels)
        for heading, items in groups
    }
    # Filing dropdown, sectioned: generic types first, then the job's
    # requirements grouped by their category headings.
    requirement_groups = [
        (heading, sorted({r["label"] for r in items}))
        for heading, items in groups
    ]

    # Piece 15.1: Loads & Sizing moved to its own page (job_loads); its data
    # is no longer computed here.

    # Piece 10: tasks for this job, plus the crew list for the assignee
    # picker. Assignee name comes along via a LEFT JOIN so unassigned tasks
    # (employee_id NULL) still show.
    tasks = db.execute(
        "SELECT t.*, e.name AS assignee_name FROM job_tasks t"
        " LEFT JOIN employees e ON e.id = t.employee_id"
        " WHERE t.job_id = ? ORDER BY t.sort_order, t.id", (job_id,)
    ).fetchall()
    employees = db.execute("SELECT id, name FROM employees ORDER BY name").fetchall()
    stage = stage_info(db, job, groups, filed_labels)
    progress = build_job_progress(db, job)

    # Saved load-survey results (from the Loads & Sizing page) surfaced here so
    # the numbers Sales captured on the walkthrough are visible in the job
    # details and ready for the Designer — no need to re-open the loads page.
    lrooms = db.execute("SELECT * FROM job_load_rooms WHERE job_id = ?", (job_id,)).fetchall()
    litems = db.execute("SELECT * FROM job_load_items WHERE job_id = ?", (job_id,)).fetchall()
    load_daily_kwh, load_peak_w = compute_load_totals(lrooms, litems)
    load_has_survey = bool(litems)

    # Documents tab: one upload slot per file the job needs — the standard docs
    # plus the job's document-worthy requirements (permits / compliance / doc
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

    billing = job_billing(
        db, job_id, job["contract_amount"] if "contract_amount" in job.keys() else 0.0)

    # Piece 21.9: field notes the crew left from the Work Bag, newest first.
    job_notes = db.execute(
        "SELECT * FROM job_notes WHERE job_id = ? ORDER BY id DESC",
        (job_id,)).fetchall()

    pricing = job_pricing(db, job)
    # Piece 31.8: the estimate's customer payment-schedule callout — shown to
    # Sales/Finance only, and only before the contract is signed (contract_amount
    # still 0), so it disappears once terms are agreed and set.
    pay_scheme_callout = _can_see_pay_scheme() and (pricing["contract"] or 0) <= 0

    return render_template(
        "job_detail.html", job=job, groups=groups, versions=versions,
        job_notes=job_notes,
        materials=materials, files=files, filed_labels=filed_labels,
        coverage=coverage, requirement_groups=requirement_groups,
        material_statuses=MATERIAL_STATUSES, license_staffing=license_staffing(),
        tasks=tasks, employees=employees, task_statuses=TASK_STATUSES,
        job_statuses=JOB_STATUSES, job_status_class=JOB_STATUS_CLASS,
        stage=stage, progress=progress, today=datetime.now().strftime("%Y-%m-%d"),
        load_daily_kwh=load_daily_kwh, load_peak_w=load_peak_w,
        load_has_survey=load_has_survey, doc_sections=doc_sections,
        files_by_label=files_by_label, other_files=other_files,
        formats_by_label=formats_by_label,
        billing=billing, txn_kinds=TXN_KINDS, txn_statuses=TXN_STATUSES,
        income_categories=INCOME_CATEGORIES, expense_categories=EXPENSE_CATEGORIES,
        payment_methods=PAYMENT_METHODS, doc_types=DOC_TYPES,
        invoices=invoice_schedule_view(db, job), payment_scheme=PAYMENT_SCHEME_NOTE,
        pricing=pricing,                                   # Piece 29.6
        pay_scheme_callout=pay_scheme_callout,             # Piece 31.8
        county_grt=county_grt_rate(db, job["county"] if "county" in job.keys() else ""),
        can_see_pricing=_can_see_pricing(),                # Piece 29.7
        estimate_sections=ESTIMATE_SECTIONS,               # Piece 29.9
    )


@app.route("/jobs/<int:job_id>/contract", methods=["POST"])
def set_contract(job_id):
    fetch_job(job_id)
    db = get_db()
    # Piece 27.4: GRT rate is set alongside the contract (both drive invoicing).
    grt = max(_to_float(request.form.get("grt_rate")) or 0.0, 0.0)
    db.execute("UPDATE jobs SET contract_amount = ?, grt_rate = ? WHERE id = ?",
               (_to_float(request.form.get("contract_amount")) or 0.0,
                str(grt), job_id))
    db.commit()
    flash("Billing details updated.")
    return redirect(url_for("job_detail", job_id=job_id, _anchor="billing"))


# ---------------------------------------------------------- per-job estimate
def _estimate_guard(job_id):
    """Estimate editing is limited to who can see pricing (Finance/Sales/Design)."""
    fetch_job(job_id)
    if not _can_see_pricing():
        flash("Pricing is limited to Finance, Sales and Design.", "error")
        return False
    return True


@app.route("/jobs/<int:job_id>/estimate/prefill", methods=["POST"])
def estimate_prefill(job_id):
    """Copy the cost-model default lines (non-equipment sections) into this
    job's estimate, so the estimator starts from Vixinman's template. Skips sections
    already present, so it won't duplicate."""
    if not _estimate_guard(job_id):
        return redirect(url_for("job_detail", job_id=job_id, _anchor="estimate"))
    db = get_db()
    have = {r["section"] for r in db.execute(
        "SELECT DISTINCT section FROM job_estimate_lines WHERE job_id = ?",
        (job_id,)).fetchall()}
    nxt = db.execute("SELECT COALESCE(MAX(sort_order), -1) + 1"
                     " FROM job_estimate_lines WHERE job_id = ?", (job_id,)).fetchone()[0]
    added = 0
    for r in db.execute(
            "SELECT * FROM cost_model_lines WHERE active = '1'"
            " ORDER BY sort_order, id").fetchall():
        if r["section"] not in ESTIMATE_SECTIONS or r["section"] in have:
            continue
        db.execute(
            "INSERT INTO job_estimate_lines (job_id, section, item, unit, qty,"
            " unit_cost, markup_pct, sort_order) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (job_id, r["section"], r["item"], r["unit"] or "",
             r["default_qty"] or 0, r["unit_cost"] or 0, r["markup_pct"] or 0, nxt))
        nxt += 1
        added += 1
    db.commit()
    flash(f"Added {added} line(s) from the cost model." if added
          else "Those sections are already on the estimate.")
    return redirect(url_for("job_detail", job_id=job_id, _anchor="estimate"))


@app.route("/jobs/<int:job_id>/estimate/add", methods=["POST"])
def estimate_add_line(job_id):
    if not _estimate_guard(job_id):
        return redirect(url_for("job_detail", job_id=job_id, _anchor="estimate"))
    section = request.form.get("section", "")
    item = request.form.get("item", "").strip()
    if section not in ESTIMATE_SECTIONS or not item:
        flash("Pick a section and name the line.", "error")
        return redirect(url_for("job_detail", job_id=job_id, _anchor="estimate"))
    db = get_db()
    nxt = db.execute("SELECT COALESCE(MAX(sort_order), -1) + 1"
                     " FROM job_estimate_lines WHERE job_id = ?", (job_id,)).fetchone()[0]
    db.execute(
        "INSERT INTO job_estimate_lines (job_id, section, item, unit, qty,"
        " unit_cost, markup_pct, sort_order) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (job_id, section, item, request.form.get("unit", "").strip(),
         max(_to_float(request.form.get("qty")) or 0.0, 0.0),
         max(_to_float(request.form.get("cost")) or 0.0, 0.0),
         max(_to_float(request.form.get("markup")) or 0.0, 0.0), nxt))
    db.commit()
    flash(f"Added “{item}”.")
    return redirect(url_for("job_detail", job_id=job_id, _anchor="estimate"))


@app.route("/jobs/<int:job_id>/estimate/save", methods=["POST"])
def estimate_save(job_id):
    if not _estimate_guard(job_id):
        return redirect(url_for("job_detail", job_id=job_id, _anchor="estimate"))
    db = get_db()
    for r in db.execute("SELECT id FROM job_estimate_lines WHERE job_id = ?",
                        (job_id,)).fetchall():
        i = r["id"]
        if f"qty_{i}" not in request.form:
            continue
        db.execute(
            "UPDATE job_estimate_lines SET qty = ?, unit_cost = ?, markup_pct = ?"
            " WHERE id = ? AND job_id = ?",
            (max(_to_float(request.form.get(f"qty_{i}")) or 0.0, 0.0),
             max(_to_float(request.form.get(f"cost_{i}")) or 0.0, 0.0),
             max(_to_float(request.form.get(f"markup_{i}")) or 0.0, 0.0), i, job_id))
    db.commit()
    flash("Estimate saved.")
    return redirect(url_for("job_detail", job_id=job_id, _anchor="estimate"))


@app.route("/jobs/<int:job_id>/estimate/<int:line_id>/delete", methods=["POST"])
def estimate_delete_line(job_id, line_id):
    if not _estimate_guard(job_id):
        return redirect(url_for("job_detail", job_id=job_id, _anchor="estimate"))
    db = get_db()
    db.execute("DELETE FROM job_estimate_lines WHERE id = ? AND job_id = ?",
               (line_id, job_id))
    db.commit()
    flash("Line removed.")
    return redirect(url_for("job_detail", job_id=job_id, _anchor="estimate"))


@app.route("/jobs/<int:job_id>/estimate/to-contract", methods=["POST"])
def estimate_to_contract(job_id):
    """Set the contract total to the estimate's suggested price."""
    job = fetch_job(job_id)
    if not _estimate_guard(job_id):
        return redirect(url_for("job_detail", job_id=job_id, _anchor="estimate"))
    db = get_db()
    suggested = job_pricing(db, job)["suggested"]
    db.execute("UPDATE jobs SET contract_amount = ? WHERE id = ?",
               (suggested, job_id))
    db.commit()
    flash(f"Contract total set to the suggested price — ${suggested:,.2f}.")
    return redirect(url_for("job_detail", job_id=job_id, _anchor="billing"))


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


@app.route("/jobs/<int:job_id>/transactions/add", methods=["POST"])
def add_transaction(job_id):
    fetch_job(job_id)
    kind = request.form.get("kind", "Expense")
    kind = kind if kind in TXN_KINDS else "Expense"
    status = request.form.get("status", "Outstanding")
    status = status if status in TXN_STATUSES else "Outstanding"
    doc_type = request.form.get("doc_type", "").strip()
    doc_type = doc_type if doc_type in DOC_TYPES else ""
    who = current_user()
    db = get_db()
    cur = db.execute(
        "INSERT INTO job_transactions"
        " (job_id, kind, category, description, amount, txn_date, status,"
        "  party, reference, method, doc_type, created_by)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (job_id, kind, request.form.get("category", "").strip(),
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
    # shows the 📎 link in the ledger and lands on the job's document record.
    upload = request.files.get("document")
    if upload is not None and upload.filename:
        ext = upload.filename.rsplit(".", 1)[-1].lower() if "." in upload.filename else ""
        if ext in (PHOTO_EXTENSIONS | {"pdf"}):
            info = db.execute(
                "SELECT j.job_name, c.name AS client_name FROM jobs j"
                " JOIN clients c ON c.id = j.client_id WHERE j.id = ?", (job_id,)).fetchone()
            label = doc_type or "Billing"
            friendly = friendly_filename(
                [info["client_name"], info["job_name"], label], ext,
                taken=_taken_names(db, "job_files", "original_name", "job_id", job_id))
            stored = f"{uuid.uuid4().hex[:8]}_{secure_filename(friendly)}"
            upload.save(job_upload_dir(job_id) / stored)
            db.execute(
                "INSERT INTO job_files"
                " (job_id, rule_label, stored_name, original_name, txn_id)"
                " VALUES (?, ?, ?, ?, ?)", (job_id, label, stored, friendly, txn_id))
        else:
            flash("Attachment skipped — it must be a photo (JPG/PNG/HEIC) or a PDF.", "error")
    db.commit()
    flash(f"{doc_type or kind} recorded.")
    return redirect(url_for("job_detail", job_id=job_id, _anchor="billing"))


@app.route("/jobs/<int:job_id>/transactions/<int:txn_id>/paid", methods=["POST"])
def toggle_transaction_paid(job_id, txn_id):
    db = get_db()
    row = db.execute("SELECT status FROM job_transactions WHERE id = ? AND job_id = ?",
                     (txn_id, job_id)).fetchone()
    if row:
        db.execute("UPDATE job_transactions SET status = ? WHERE id = ? AND job_id = ?",
                   ("Outstanding" if row["status"] == "Paid" else "Paid", txn_id, job_id))
        db.commit()
    return redirect(url_for("job_detail", job_id=job_id, _anchor="billing"))


@app.route("/jobs/<int:job_id>/transactions/<int:txn_id>/delete", methods=["POST"])
def delete_transaction(job_id, txn_id):
    db = get_db()
    db.execute("DELETE FROM job_transactions WHERE id = ? AND job_id = ?",
               (txn_id, job_id))
    db.commit()
    flash("Transaction deleted.")
    return redirect(url_for("job_detail", job_id=job_id, _anchor="billing"))


# --- Piece 27.3: 50/40/10 invoice generation -------------------------------
def _norm_county(name):
    """Normalise a county name for matching: drop a trailing 'County', lower."""
    n = (name or "").strip()
    if n.lower().endswith(" county"):
        n = n[:-7].strip()
    return n.lower()


def county_grt_rate(db, county):
    """The GRT rate on file for a job's install county, or None if unknown."""
    key = _norm_county(county)
    if not key:
        return None
    for r in db.execute("SELECT county, grt_rate FROM county_tax_rates").fetchall():
        if _norm_county(r["county"]) == key:
            return float(r["grt_rate"] or 0)
    return None


def markup_map(db):
    """{equipment category (lower): markup percent} from the Cost Model's
    Equipment Inventory section (Piece 29.8)."""
    return {(r["item"] or "").strip().lower(): float(r["markup_pct"] or 0)
            for r in db.execute(
                "SELECT item, markup_pct FROM cost_model_lines"
                " WHERE section = 'Equipment Inventory' AND active = '1'").fetchall()}


def travel_rate(db):
    """Per-job travel $/mile — the Cost Model's Travel → Vehicle Trips line is
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
    """Total overhead (G&A) percent applied to the whole job subtotal."""
    return sum(float(r["markup_pct"] or 0) for r in db.execute(
        "SELECT markup_pct FROM cost_model_lines"
        " WHERE section = 'Overhead' AND active = '1'").fetchall())


def cost_model_rollup(db):
    """A default 'standard job' estimate straight from the model: each line is
    qty × cost × (1 + markup) for Non-Inventory / Labor / Travel / Adders, then
    G&A overhead on the subtotal (Piece 29.8). Equipment Inventory is excluded —
    it prices the actual per-job BOM, not a default quantity."""
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


def bom_pricing(db, job_id, mmap, after_id=None):
    """Cost and marked-up customer price for a job's BOM (optionally only rows
    added after `after_id`, for change-order extras). Per-line markup override
    wins over the category default."""
    sql = ("SELECT id, component_name, category, COALESCE(qty,0) AS qty,"
           " COALESCE(unit_cost,0) AS cost, markup_pct FROM job_bom"
           " WHERE job_id = ?")
    args = [job_id]
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


def job_travel_charge(db, job):
    miles = _to_float(job["travel_miles"] if "travel_miles" in job.keys() else 0) or 0.0
    return round(max(miles, 0.0) * travel_rate(db), 2), max(miles, 0.0)


def job_pricing(db, job):
    """Internal Finance breakdown for a job: equipment cost vs marked-up price,
    travel, a suggested contract price, and the contract Finance actually set."""
    mmap = markup_map(db)
    bom = bom_pricing(db, job["id"], mmap)
    est = estimate_pricing(db, job["id"])             # Piece 29.9: the job estimate
    subtotal = round(bom["price_total"] + est["total"], 2)
    ov = overhead_pct(db)                              # G&A on the whole subtotal
    overhead_amt = round(subtotal * ov / 100.0, 2)
    suggested = round(subtotal + overhead_amt, 2)
    contract = _to_float(job["contract_amount"] if "contract_amount" in job.keys()
                         else 0) or 0.0
    return {"equipment_cost": bom["cost_total"],
            "equipment_price": bom["price_total"],
            "markup_amount": round(bom["price_total"] - bom["cost_total"], 2),
            "estimate_by_section": est["by_section"],
            "estimate_total": est["total"], "estimate_lines": est["lines"],
            "subtotal": subtotal, "overhead_pct": ov, "overhead_amount": overhead_amt,
            "suggested": suggested, "contract": contract, "lines": bom["lines"]}


# Piece 29.9: the cost-model sections that make up a per-job estimate (Equipment
# Inventory is priced from the BOM; Overhead is applied on top, not entered).
ESTIMATE_SECTIONS = ["Equipment Non-Inventory", "Labor", "Travel", "Adders"]


def estimate_lines(db, job_id):
    return db.execute(
        "SELECT * FROM job_estimate_lines WHERE job_id = ?"
        " ORDER BY sort_order, id", (job_id,)).fetchall()


def estimate_pricing(db, job_id):
    """Per-section and total for a job's estimate lines: qty × cost × (1+markup)."""
    by_section = {s: 0.0 for s in ESTIMATE_SECTIONS}
    lines = []
    for r in estimate_lines(db, job_id):
        lt = (r["qty"] or 0) * (r["unit_cost"] or 0) * (1 + (r["markup_pct"] or 0) / 100.0)
        by_section[r["section"]] = by_section.get(r["section"], 0.0) + lt
        d = dict(r)
        d["line_total"] = round(lt, 2)
        lines.append(d)
    by_section = {k: round(v, 2) for k, v in by_section.items()}
    return {"by_section": by_section, "total": round(sum(by_section.values()), 2),
            "lines": lines}


def _post_deposit_bom_total(db, job_id, cutoff_id):
    """Marked-up customer price of BOM lines added AFTER the deposit invoice —
    rows whose id is greater than the cutoff captured when the deposit was
    generated. These change-order materials are billed at the customer price
    (cost + markup, Piece 29.6), not raw cost."""
    try:
        cutoff_id = int(cutoff_id or 0)
    except (ValueError, TypeError):
        cutoff_id = 0
    return bom_pricing(db, job_id, markup_map(db), after_id=cutoff_id)["price_total"]


def _milestone_pct(name):
    for n, pct, _hint in INVOICE_MILESTONES:
        if n == name:
            return pct
    return 0


def _generated_invoices(db, job_id):
    """Generated milestone invoices for a job, keyed by milestone name."""
    return {t["milestone"]: t for t in db.execute(
        "SELECT * FROM job_transactions WHERE job_id = ?"
        "   AND COALESCE(milestone,'') != '' ORDER BY id", (job_id,)).fetchall()}


def _job_cutoff(job):
    try:
        return int(job["deposit_bom_cutoff_id"]) if ("deposit_bom_cutoff_id" in job.keys()
                   and job["deposit_bom_cutoff_id"]) else 0
    except (ValueError, TypeError):
        return 0


def projected_invoice(db, job):
    """The next ungenerated milestone and the amount it would bill right now.
    Deposit = 50% of contract; Progress = 40% + 80% of post-deposit BOM extras;
    Final = a true-up so the total billed equals contract + all added materials.
    Returns (milestone_name, amount, extras) or (None, 0, 0)."""
    job_id = job["id"]
    contract = _to_float(job["contract_amount"] if "contract_amount" in job.keys() else 0) or 0.0
    gen = _generated_invoices(db, job_id)
    nxt = next((n for n, _p, _h in INVOICE_MILESTONES if n not in gen), None)
    if nxt is None or contract <= 0:
        return None, 0.0, 0.0
    if nxt == "Deposit":
        return "Deposit", round(0.5 * contract, 2), 0.0
    extras = _post_deposit_bom_total(db, job_id, _job_cutoff(job))
    if nxt == "Progress":
        return "Progress", round(0.4 * contract + 0.8 * extras, 2), extras
    dep = _to_float(gen["Deposit"]["amount"]) if "Deposit" in gen else 0.0
    prog = _to_float(gen["Progress"]["amount"]) if "Progress" in gen else 0.0
    return "Final", round((contract + extras) - dep - prog, 2), extras


def invoice_schedule_view(db, job):
    """Per-milestone state for the Billing tab: the generated invoice (or None)
    for each of the three milestones, plus which one is next and its amount."""
    gen = _generated_invoices(db, job["id"])
    nxt, amount, extras = projected_invoice(db, job)
    rows = [{"name": n, "pct": p, "hint": h, "txn": gen.get(n), "is_next": n == nxt}
            for n, p, h in INVOICE_MILESTONES]
    return {"rows": rows, "next": nxt, "next_amount": amount, "next_extras": extras,
            "contract": _to_float(job["contract_amount"] if "contract_amount" in job.keys() else 0) or 0.0}


@app.route("/jobs/<int:job_id>/invoice/generate", methods=["POST"])
def generate_invoice(job_id):
    """Generate the next 50/40/10 customer invoice from the contract + BOM."""
    job = fetch_job(job_id)
    db = get_db()
    nxt, amount, extras = projected_invoice(db, job)
    if nxt is None:
        flash("Set a contract total first (all invoices may already be generated).", "error")
        return redirect(url_for("job_detail", job_id=job_id, _anchor="billing"))
    if request.form.get("milestone") != nxt:
        flash(f"The {nxt} invoice is next in the schedule.", "error")
        return redirect(url_for("job_detail", job_id=job_id, _anchor="billing"))
    pct = _milestone_pct(nxt)
    contract = _to_float(job["contract_amount"]) or 0.0
    base = round(pct / 100.0 * contract, 2)
    number = f"INV-{int(_meta_get(db, 'invoice_seq', '0') or '0') + 1:05d}"
    _meta_set(db, "invoice_seq", int(_meta_get(db, "invoice_seq", "0") or "0") + 1)
    today = datetime.now().date()
    due = today if nxt == "Deposit" else today + timedelta(days=COMPANY_INFO["terms_days"])
    bom_rows = db.execute(
        "SELECT component_name, qty FROM job_bom WHERE job_id = ? ORDER BY id",
        (job_id,)).fetchall()
    bom_snapshot = json.dumps([{"name": b["component_name"], "qty": b["qty"]}
                               for b in bom_rows])
    desc = f"{nxt} invoice — {pct}% of contract"
    if extras and nxt != "Deposit":
        desc += f" + ${extras:,.2f} added materials"
    # Piece 27.4: snapshot the job's GRT rate + the tax on this invoice's subtotal.
    grt_rate = max(_to_float(job["grt_rate"] if "grt_rate" in job.keys() else 0) or 0.0, 0.0)
    grt_amount = round(grt_rate / 100.0 * amount, 2)
    who = current_user()
    db.execute(
        "INSERT INTO job_transactions"
        " (job_id, kind, category, description, amount, txn_date, status, party,"
        "  reference, method, doc_type, created_by, invoice_number, milestone,"
        "  due_date, contract_snapshot, base_amount, extras_amount, bom_snapshot,"
        "  grt_rate, grt_amount)"
        " VALUES (?, 'Income', ?, ?, ?, ?, 'Outstanding', '', ?, '', 'Invoice', ?,"
        "         ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (job_id, f"{pct}% {nxt}", desc, amount, today.strftime("%Y-%m-%d"),
         number, who["name"] if who else "", number, nxt,
         due.strftime("%Y-%m-%d"), contract, base, round(amount - base, 2), bom_snapshot,
         str(grt_rate), grt_amount))
    if nxt == "Deposit":
        maxid = db.execute("SELECT COALESCE(MAX(id), 0) AS m FROM job_bom"
                           " WHERE job_id = ?", (job_id,)).fetchone()["m"]
        db.execute("UPDATE jobs SET deposit_bom_cutoff_id = ? WHERE id = ?",
                   (str(maxid), job_id))
    db.commit()
    flash(f"{nxt} invoice {number} generated — ${amount:,.2f}.")
    return redirect(url_for("job_detail", job_id=job_id, _anchor="billing"))


@app.route("/jobs/<int:job_id>/invoice/<int:txn_id>")
def view_invoice(job_id, txn_id):
    """Printable customer copy of a generated milestone invoice: the overall
    contract, the amount due for this milestone, and the equipment (BOM) list —
    no per-line pricing (the itemized expenses stay on the internal Billing tab)."""
    job = fetch_job(job_id)
    db = get_db()
    inv = db.execute(
        "SELECT * FROM job_transactions WHERE id = ? AND job_id = ?"
        "   AND COALESCE(milestone,'') != ''", (txn_id, job_id)).fetchone()
    if inv is None:
        abort(404)
    client = db.execute("SELECT * FROM clients WHERE id = ?",
                        (job["client_id"],)).fetchone()
    try:
        bom = json.loads(inv["bom_snapshot"] or "[]")
    except (ValueError, TypeError):
        bom = []
    gen = _generated_invoices(db, job_id)
    schedule = []
    for name, pct, hint in INVOICE_MILESTONES:
        t = gen.get(name)
        schedule.append({"name": name, "pct": pct, "hint": hint,
                         "amount": _to_float(t["amount"]) if t else None,
                         "status": t["status"] if t else None,
                         "current": t is not None and t["id"] == inv["id"]})
    grt_rate = _to_float(inv["grt_rate"] if "grt_rate" in inv.keys() else 0) or 0.0
    grt_amount = _to_float(inv["grt_amount"] if "grt_amount" in inv.keys() else 0) or 0.0
    return render_template(
        "invoice.html", job=job, client=client, inv=inv, bom=bom,
        schedule=schedule, company=COMPANY_INFO, payment_scheme=PAYMENT_SCHEME_NOTE,
        contract=_to_float(inv["contract_snapshot"]) or 0.0,
        grt_rate=grt_rate, grt_amount=grt_amount, grt_cite=GRT_EXEMPTION_CITE)


@app.route("/finance/quickbooks.csv")
def quickbooks_export():
    """Export every job transaction as a QuickBooks-importable CSV. The first
    three columns (Date, Description, Amount) map directly onto QuickBooks
    Online's bank/transaction import; the remaining columns carry the detail.
    Pass ?doc=Invoice|Bill|Receipt to export only that paperwork type — handy
    because QuickBooks imports invoices (A/R), bills (A/P) and receipts through
    separate flows."""
    import csv
    import io
    db = get_db()
    doc_filter = request.args.get("doc", "").strip()
    doc_filter = doc_filter if doc_filter in DOC_TYPES else ""
    # Piece 27.2: the export lives on each job's Billing tab now, so scope to one
    # job when ?job= is passed; with no job it still exports every job (company-wide).
    job_filter = request.args.get("job", type=int)
    sql = ("SELECT t.*, j.job_name, j.id AS jid, c.name AS client_name"
           " FROM job_transactions t JOIN jobs j ON j.id = t.job_id"
           " JOIN clients c ON c.id = j.client_id")
    where, params = [], []
    if doc_filter:
        where.append("t.doc_type = ?")
        params.append(doc_filter)
    if job_filter:
        where.append("t.job_id = ?")
        params.append(job_filter)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY t.txn_date, t.id"
    rows = db.execute(sql, tuple(params)).fetchall()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Date", "Description", "Amount", "Type", "Document", "Customer",
                "Job", "Category", "Status", "Reference", "Method"])
    for r in rows:
        job_label = r["job_name"] or f"Job #{r['jid']}"
        signed = (r["amount"] or 0.0) if r["kind"] == "Income" else -(r["amount"] or 0.0)
        doc_type = r["doc_type"] if "doc_type" in r.keys() else ""
        desc = " · ".join(p for p in (r["client_name"], job_label,
                                      r["category"], r["description"]) if p)
        w.writerow([r["txn_date"], desc, f"{signed:.2f}", r["kind"], doc_type,
                    r["client_name"], job_label, r["category"], r["status"],
                    r["reference"], r["method"]])
    parts = []
    if job_filter:
        parts.append(f"job{job_filter}")
    if doc_filter:
        parts.append(f"{doc_filter.lower()}s")
    suffix = ("_" + "_".join(parts)) if parts else ""
    return Response(buf.getvalue(), mimetype="text/csv", headers={
        "Content-Disposition": f"attachment; filename=compendium_quickbooks{suffix}.csv"})


def _pay_period():
    """Default pay period: the most recent full **Sunday → Saturday** week — the
    one that ended on the latest Saturday (today included when today is Saturday).
    Pay periods run Sunday to Saturday. Overridable via ?start/?end."""
    today = datetime.now().date()
    # weekday(): Mon=0 … Sat=5, Sun=6 → step back to the most recent Saturday.
    days_since_sat = (today.weekday() - 5) % 7
    default_end = today - timedelta(days=days_since_sat)   # a Saturday
    default_start = default_end - timedelta(days=6)        # the Sunday before it
    end = request.args.get("end") or default_end.strftime("%Y-%m-%d")
    start = request.args.get("start") or default_start.strftime("%Y-%m-%d")
    return start, end


# Payroll runs Tuesday–Thursday each week (weekday() 1,2,3).
PAYROLL_DAYS = (1, 2, 3)
_WEEKDAY_ABBR = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def payroll_status(db, start, end):
    """Piece 26.7: the state of this pay period for the Finance dashboard's
    payroll reminder. Two steps must both be done before payroll is put to bed:
    (1) hours *confirmed* — nothing left awaiting approval in the period — and
    (2) *exported* to QuickBooks. The export is only counted as current if it
    happened after the newest approval, so approving more hours re-opens it. The
    reminder nags Tuesday–Thursday until both are done."""
    pending = db.execute(
        "SELECT COUNT(*) FROM time_entries WHERE status = 'Pending'"
        " AND work_date >= ? AND work_date <= ?", (start, end)).fetchone()[0]
    approved = db.execute(
        "SELECT COUNT(*) FROM time_entries WHERE status = 'Approved'"
        " AND work_date >= ? AND work_date <= ?", (start, end)).fetchone()[0]
    last_approved = db.execute(
        "SELECT MAX(approved_at) FROM time_entries WHERE status = 'Approved'"
        " AND work_date >= ? AND work_date <= ?", (start, end)).fetchone()[0]
    exported_at = _meta_get(db, f"payroll_exported:{start}..{end}", "")
    confirmed = pending == 0
    exported = bool(exported_at) and (not last_approved or exported_at >= last_approved)
    today = datetime.now()
    weekday = today.weekday()
    return {
        "start": start, "end": end, "pending": pending, "approved": approved,
        "confirmed": confirmed, "exported": exported, "exported_at": exported_at,
        "in_window": weekday in PAYROLL_DAYS, "today_abbr": _WEEKDAY_ABBR[weekday],
        "days": [_WEEKDAY_ABBR[d] for d in PAYROLL_DAYS],
        "done": confirmed and exported,
    }


@app.route("/payroll")
@payroll_required
def payroll():
    db = get_db()
    start, end = _pay_period()
    types, rollup, totals = payroll_summary(db, start, end)
    entries = db.execute(
        "SELECT te.*, e.name AS emp_name, pt.name AS type_name, j.job_name"
        " FROM time_entries te"
        " JOIN employees e ON e.id = te.employee_id"
        " LEFT JOIN pay_types pt ON pt.id = te.pay_type_id"
        " LEFT JOIN jobs j ON j.id = te.job_id"
        " WHERE te.work_date >= ? AND te.work_date <= ? AND te.status = 'Approved'"
        " ORDER BY te.work_date DESC, te.id DESC", (start, end)).fetchall()
    # Supervisor approval queue: hours employees logged that await review.
    pending = db.execute(
        "SELECT te.*, e.name AS emp_name, pt.name AS type_name,"
        " pt.is_leave AS is_leave, j.job_name"
        " FROM time_entries te"
        " JOIN employees e ON e.id = te.employee_id"
        " LEFT JOIN pay_types pt ON pt.id = te.pay_type_id"
        " LEFT JOIN jobs j ON j.id = te.job_id"
        " WHERE te.status = 'Pending' ORDER BY te.work_date, e.name").fetchall()
    ot_threshold, ot_mult = ot_rules(db)
    return render_template(
        "payroll.html", start=start, end=end, types=types, rollup=rollup,
        totals=totals, entries=entries, pending=pending,
        ot_threshold=ot_threshold, ot_mult=ot_mult,
        can_edit_rates=_can_edit_pay_rates(),
        today=datetime.now().strftime("%Y-%m-%d"))


@app.route("/payroll/time/add", methods=["POST"])
@payroll_required
def add_time_entry():
    db = get_db()
    emp_id = request.form.get("employee_id", "")
    if not emp_id.isdigit():
        flash("Pick an employee for the time entry.", "error")
        return redirect(url_for("payroll"))
    who = current_user()
    db.execute(
        "INSERT INTO time_entries"
        " (employee_id, work_date, job_id, pay_type_id, hours, note, created_by)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (int(emp_id), request.form.get("work_date", "").strip(),
         int(request.form["job_id"]) if request.form.get("job_id", "").isdigit() else None,
         int(request.form["pay_type_id"]) if request.form.get("pay_type_id", "").isdigit() else None,
         _to_float(request.form.get("hours")) or 0.0,
         request.form.get("note", "").strip(), who["name"] if who else ""))
    db.commit()
    flash("Hours logged.")
    return redirect(url_for("payroll", start=request.form.get("start"),
                            end=request.form.get("end")))


@app.route("/payroll/time/<int:entry_id>/delete", methods=["POST"])
@payroll_required
def delete_time_entry(entry_id):
    db = get_db()
    db.execute("DELETE FROM time_entries WHERE id = ?", (entry_id,))
    db.commit()
    flash("Time entry deleted.")
    return redirect(url_for("payroll", start=request.form.get("start"),
                            end=request.form.get("end")))


@app.route("/payroll/time/<int:entry_id>/approve", methods=["POST"])
@payroll_required
def approve_time_entry(entry_id):
    who = current_user()
    db = get_db()
    entry = db.execute(
        "SELECT te.*, pt.is_leave AS is_leave, pt.name AS type_name"
        " FROM time_entries te LEFT JOIN pay_types pt ON pt.id = te.pay_type_id"
        " WHERE te.id = ?", (entry_id,)).fetchone()
    if entry is None:
        abort(404)
    # Piece 26.7: the leave/vacation cap. Leave hours (PTO/vacation/sick) can't be
    # used to take a week past the weekly OT threshold — no one earns overtime on
    # leave. Approving a leave entry that would push the employee's already-approved
    # hours for that ISO week over the cap is blocked, UNLESS a GM ticks the manual
    # override on this form. Worked hours are untouched (they still earn OT).
    override = bool(request.form.get("gm_override")) and is_gm()
    if entry["is_leave"] and not override:
        threshold, _mult = ot_rules(db)
        wk = _iso_week(entry["work_date"])
        already = 0.0
        if wk is not None:
            for r in db.execute(
                    "SELECT work_date, hours FROM time_entries"
                    " WHERE employee_id = ? AND status = 'Approved' AND id != ?",
                    (entry["employee_id"], entry_id)).fetchall():
                if _iso_week(r["work_date"]) == wk:
                    already += r["hours"] or 0.0
        add = entry["hours"] or 0.0
        if already + add > threshold + 1e-9:
            room = max(threshold - already, 0.0)
            emp = db.execute("SELECT name FROM employees WHERE id = ?",
                             (entry["employee_id"],)).fetchone()
            flash(
                f"{(emp['name'] if emp else 'This employee')} already has "
                f"{already:.2f} approved hours that week — approving {add:.2f} h of "
                f"{entry['type_name'] or 'leave'} would pass the {threshold:.0f} h weekly "
                f"cap (leave can't earn overtime). Only {room:.2f} h of leave fit; reduce "
                f"the hours, or the GM can override on this row.", "error")
            return redirect(url_for("payroll"))
    db.execute("UPDATE time_entries SET status = 'Approved', approved_by = ?,"
               " approved_at = datetime('now') WHERE id = ?",
               (who["name"] if who else "", entry_id))
    db.commit()
    if entry["is_leave"] and override:
        flash("Hours approved — GM override applied (leave beyond the weekly cap).")
    else:
        flash("Hours approved.")
    return redirect(url_for("payroll"))


@app.route("/payroll/time/<int:entry_id>/reject", methods=["POST"])
@payroll_required
def reject_time_entry(entry_id):
    db = get_db()
    db.execute("DELETE FROM time_entries WHERE id = ? AND status = 'Pending'", (entry_id,))
    db.commit()
    flash("Time entry rejected — the employee can re-submit it.")
    return redirect(url_for("payroll"))


@app.route("/payroll/ot-rules", methods=["POST"])
@pay_rates_required
def save_ot_rules():
    db = get_db()
    _meta_set(db, "payroll_ot_threshold",
              _to_float(request.form.get("ot_threshold")) or OT_THRESHOLD_DEFAULT)
    _meta_set(db, "payroll_ot_multiplier",
              _to_float(request.form.get("ot_multiplier")) or OT_MULTIPLIER_DEFAULT)
    db.commit()
    flash("Overtime rules saved.")
    return redirect(url_for("payroll_settings"))


def _workbag_redirect(anchor=None):
    """Piece 27.7: Work-Bag POSTs now come from a job's own page, so return
    there (using the form's job_id) instead of the landing. Falls back to the
    landing when no job is on the form."""
    jid = request.form.get("job_id", "")
    if jid.isdigit():
        return redirect(url_for("work_bag_job", job_id=int(jid), _anchor=anchor))
    return redirect(url_for("work_bag"))


@app.route("/work-bag/hours", methods=["POST"])
def log_my_hours():
    """An employee logs their own hours from the Work Bag — saved as Pending
    until a supervisor approves them for payroll."""
    user = current_user()
    if user is None:
        abort(403)
    db = get_db()
    db.execute(
        "INSERT INTO time_entries (employee_id, work_date, job_id, pay_type_id,"
        " hours, note, status, created_by) VALUES (?, ?, ?, ?, ?, ?, 'Pending', ?)",
        (user["id"], request.form.get("work_date", "").strip(),
         int(request.form["job_id"]) if request.form.get("job_id", "").isdigit() else None,
         int(request.form["pay_type_id"]) if request.form.get("pay_type_id", "").isdigit() else None,
         _to_float(request.form.get("hours")) or 0.0,
         request.form.get("note", "").strip(), user["name"]))
    db.commit()
    flash("Hours submitted for approval.")
    return _workbag_redirect(anchor="hours")


@app.route("/work-bag/hours/<int:entry_id>/delete", methods=["POST"])
def delete_my_hours(entry_id):
    user = current_user()
    if user is None:
        abort(403)
    db = get_db()
    db.execute("DELETE FROM time_entries WHERE id = ? AND employee_id = ?"
               " AND status = 'Pending'", (entry_id, user["id"]))
    db.commit()
    return _workbag_redirect(anchor="hours")


# ---------------------- Piece 25.1: timesheets --------------------------------
def build_timesheet(db, start, end, employee_ids=None):
    """A per-employee timesheet for [start, end]: every logged time entry
    (Approved and Pending) grouped by employee, then by work date, with day
    subtotals and per-person Approved / Pending / total hours. `employee_ids`
    None means everyone; a list scopes it (used to lock a worker to their own)."""
    q = ("SELECT te.*, pt.name AS type_name, j.job_name, e.name AS emp_name"
         " FROM time_entries te JOIN employees e ON e.id = te.employee_id"
         " LEFT JOIN pay_types pt ON pt.id = te.pay_type_id"
         " LEFT JOIN jobs j ON j.id = te.job_id"
         " WHERE te.work_date >= ? AND te.work_date <= ?")
    params = [start, end]
    if employee_ids is not None:
        if not employee_ids:
            return [], {"approved": 0.0, "pending": 0.0, "total": 0.0}
        q += " AND te.employee_id IN (%s)" % ",".join("?" * len(employee_ids))
        params += list(employee_ids)
    q += " ORDER BY e.name, te.work_date, te.id"
    rows = db.execute(q, params).fetchall()

    def weekday(d):
        try:
            return datetime.strptime(d, "%Y-%m-%d").strftime("%a")
        except (ValueError, TypeError):
            return ""

    sheets = {}
    for r in rows:
        sh = sheets.setdefault(r["employee_id"], {
            "employee_id": r["employee_id"], "name": r["emp_name"],
            "days": {}, "approved": 0.0, "pending": 0.0, "total": 0.0})
        day = sh["days"].setdefault(r["work_date"], {
            "date": r["work_date"], "weekday": weekday(r["work_date"]),
            "rows": [], "hours": 0.0})
        hrs = r["hours"] or 0.0
        day["rows"].append(r)
        day["hours"] += hrs
        sh["total"] += hrs
        sh[("approved" if r["status"] == "Approved" else "pending")] += hrs
    out = []
    for sh in sorted(sheets.values(), key=lambda s: s["name"].lower()):
        sh["days"] = [sh["days"][d] for d in sorted(sh["days"])]
        out.append(sh)
    totals = {"approved": sum(s["approved"] for s in out),
              "pending": sum(s["pending"] for s in out),
              "total": sum(s["total"] for s in out)}
    return out, totals


def _timesheet_scope():
    """Resolve (start, end, employee_ids, manager, selected) for the timesheet
    from the request. Managers may pick any employee or 'all'; everyone else is
    locked to their own hours."""
    user = current_user()
    start, end = _pay_period()
    manager = _can_payroll()
    selected = request.args.get("employee", "all" if manager else "")
    if manager:
        emp_ids = [int(selected)] if selected.isdigit() else None
    else:
        emp_ids = [user["id"]] if user else []
    return start, end, emp_ids, manager, selected


@app.route("/timesheet")
def timesheet():
    """A printable hours timesheet built from logged time entries. Any signed-in
    worker sees their own; payroll (Finance / Admin / GM) can view anyone or all."""
    db = get_db()
    start, end, emp_ids, manager, selected = _timesheet_scope()
    sheets, totals = build_timesheet(db, start, end, emp_ids)
    employees = (db.execute("SELECT id, name FROM employees WHERE COALESCE(name,'')"
                            " != '' ORDER BY name").fetchall() if manager else [])
    user = current_user()
    return render_template(
        "timesheet.html", sheets=sheets, totals=totals, start=start, end=end,
        manager=manager, employees=employees, selected=selected,
        self_name=user["name"] if user else "")


@app.route("/timesheet.csv")
def timesheet_csv():
    """CSV export of the same timesheet (payroll-ready)."""
    db = get_db()
    start, end, emp_ids, _manager, _sel = _timesheet_scope()
    sheets, _totals = build_timesheet(db, start, end, emp_ids)
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Employee", "Date", "Weekday", "Job", "Pay type", "Hours",
                "Status", "Note"])
    for sh in sheets:
        for day in sh["days"]:
            for r in day["rows"]:
                w.writerow([sh["name"], r["work_date"], day["weekday"],
                            r["job_name"] or "", r["type_name"] or "",
                            r["hours"] or 0, r["status"], r["note"] or ""])
    fname = f"timesheet_{start}_to_{end}.csv"
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={fname}"})


@app.route("/work-bag/notes", methods=["POST"])
def add_job_note():
    """Piece 21.9: jot a free-form note about a job from the Work Bag. Each note
    keeps its own timestamp (datetime('now'), the same clock the audit log uses)
    and author, so the office can read the field's notes later."""
    user = current_user()
    if user is None:
        abort(403)
    db = get_db()
    job_id = request.form.get("job_id", "")
    note = request.form.get("note", "").strip()
    if not job_id.isdigit() or not note:
        flash("Pick a job and type a note.", "error")
        return _workbag_redirect(anchor="notes")
    db.execute("INSERT INTO job_notes (job_id, note, author) VALUES (?, ?, ?)",
               (int(job_id), note, user["name"]))
    db.commit()
    flash("Note saved for the office.")
    return _workbag_redirect(anchor="notes")


@app.route("/work-bag/receipt", methods=["POST"])
def add_receipt():
    """Piece 26.2: capture a receipt from the field — a photo plus date, total,
    vendor, reference, and expense category. Records a paid Expense/Receipt on the
    job's ledger (so it flows into bookkeeping) and files the photo against that
    transaction."""
    user = current_user()
    if user is None:
        abort(403)
    db = get_db()
    job_raw = request.form.get("job_id", "")
    if not job_raw.isdigit():
        flash("Pick a job for the receipt.", "error")
        return _workbag_redirect(anchor="receipts")
    job = db.execute(
        "SELECT j.id, j.job_name, c.name AS client_name FROM jobs j"
        " JOIN clients c ON c.id = j.client_id WHERE j.id = ?",
        (int(job_raw),)).fetchone()
    if job is None:
        flash("That job wasn't found.", "error")
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
    job_id = job["id"]
    # 1) Ledger entry: a paid expense, tagged as a Receipt.
    cur = db.execute(
        "INSERT INTO job_transactions (job_id, kind, category, description, amount,"
        " txn_date, status, party, reference, method, doc_type, created_by)"
        " VALUES (?, 'Expense', ?, ?, ?, ?, 'Paid', ?, ?, '', 'Receipt', ?)",
        (job_id, category, (f"Receipt — {vendor}" if vendor else "Receipt"),
         total, date, vendor, reference, user["name"]))
    txn_id = cur.lastrowid
    # 2) File the photo against the job + that transaction (auto-renamed).
    friendly = friendly_filename(
        [job["client_name"], job["job_name"], "Receipt", vendor], ext,
        taken=_taken_names(db, "job_files", "original_name", "job_id", job_id))
    stored = f"{uuid.uuid4().hex[:8]}_{secure_filename(friendly)}"
    upload.save(job_upload_dir(job_id) / stored)
    db.execute(
        "INSERT INTO job_files (job_id, rule_label, stored_name, original_name, txn_id)"
        " VALUES (?, 'Receipt', ?, ?, ?)", (job_id, stored, friendly, txn_id))
    db.commit()
    flash(f"Receipt saved: ${total:,.2f}{(' · ' + vendor) if vendor else ''}.")
    return _workbag_redirect(anchor="receipts")


@app.route("/work-bag/notes/<int:note_id>/delete", methods=["POST"])
def delete_job_note(note_id):
    """Remove a note — scoped to the author who wrote it."""
    user = current_user()
    if user is None:
        abort(403)
    db = get_db()
    db.execute("DELETE FROM job_notes WHERE id = ? AND author = ?",
               (note_id, user["name"]))
    db.commit()
    flash("Note removed.")
    return _workbag_redirect(anchor="notes")


@app.route("/payroll/settings", methods=["GET"])
@pay_rates_required
def payroll_settings():
    db = get_db()
    types = db.execute("SELECT * FROM pay_types ORDER BY sort_order, id").fetchall()
    employees = db.execute(
        "SELECT id, name, base_wage FROM employees ORDER BY name").fetchall()
    rates = {}
    for r in db.execute("SELECT employee_id, pay_type_id, value FROM pay_rates").fetchall():
        rates[(r["employee_id"], r["pay_type_id"])] = r["value"]
    ot_threshold, ot_mult = ot_rules(db)
    return render_template("payroll_settings.html", types=types,
                           employees=employees, rates=rates, pay_methods=PAY_METHODS,
                           ot_threshold=ot_threshold, ot_mult=ot_mult)


@app.route("/payroll/paytype/save", methods=["POST"])
@pay_rates_required
def save_pay_type():
    db = get_db()
    name = request.form.get("name", "").strip()
    method = request.form.get("method", "multiplier")
    method = method if method in PAY_METHODS else "multiplier"
    value = _to_float(request.form.get("value")) or 0.0
    ot_eligible = 1 if request.form.get("ot_eligible") else 0
    is_leave = 1 if request.form.get("is_leave") else 0
    tid = request.form.get("id", "")
    if not name:
        flash("A pay type needs a name.", "error")
    elif tid.isdigit():
        db.execute("UPDATE pay_types SET name = ?, method = ?, value = ?,"
                   " ot_eligible = ?, is_leave = ? WHERE id = ?",
                   (name, method, value, ot_eligible, is_leave, int(tid)))
        db.commit()
        flash("Pay type updated.")
    else:
        nxt = db.execute("SELECT COALESCE(MAX(sort_order), -1) + 1 FROM pay_types").fetchone()[0]
        db.execute("INSERT INTO pay_types (name, method, value, sort_order, ot_eligible, is_leave)"
                   " VALUES (?, ?, ?, ?, ?, ?)", (name, method, value, nxt, ot_eligible, is_leave))
        db.commit()
        flash("Pay type added.")
    return redirect(url_for("payroll_settings"))


@app.route("/payroll/paytype/<int:type_id>/delete", methods=["POST"])
@pay_rates_required
def delete_pay_type(type_id):
    db = get_db()
    db.execute("UPDATE pay_types SET active = 0 WHERE id = ?", (type_id,))
    db.commit()
    flash("Pay type removed.")
    return redirect(url_for("payroll_settings"))


@app.route("/payroll/employee/<int:employee_id>/rates", methods=["POST"])
@pay_rates_required
def save_employee_rates(employee_id):
    db = get_db()
    db.execute("UPDATE employees SET base_wage = ? WHERE id = ?",
               (_to_float(request.form.get("base_wage")) or 0.0, employee_id))
    # Per-type overrides: a blank field means "use the pay type's default".
    for t in db.execute("SELECT id FROM pay_types WHERE active = 1").fetchall():
        raw = request.form.get(f"rate_{t['id']}", "").strip()
        db.execute("DELETE FROM pay_rates WHERE employee_id = ? AND pay_type_id = ?",
                   (employee_id, t["id"]))
        if raw != "":
            db.execute("INSERT INTO pay_rates (employee_id, pay_type_id, value)"
                       " VALUES (?, ?, ?)", (employee_id, t["id"], _to_float(raw) or 0.0))
    db.commit()
    flash("Pay rates saved.")
    return redirect(url_for("payroll_settings"))


@app.route("/payroll/quickbooks.csv")
@payroll_required
def payroll_quickbooks_export():
    """Payroll register for the pay period as a QuickBooks-importable CSV — one
    row per employee per pay type, amounts negative (money out)."""
    import csv
    import io
    db = get_db()
    start, end = _pay_period()
    types, rollup, _totals = payroll_summary(db, start, end)
    type_name = {t["id"]: t["name"] for t in types}
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Date", "Description", "Amount", "Type", "Employee", "Pay Type",
                "Hours", "Period Start", "Period End"])
    for r in rollup:
        for tid, cell in r["by_type"].items():
            if not cell["hours"] and not cell["pay"]:
                continue
            w.writerow([end, f"Payroll · {r['employee']['name']} · {type_name.get(tid, '')}",
                        f"{-cell['pay']:.2f}", "Expense", r["employee"]["name"],
                        type_name.get(tid, ""), f"{cell['hours']:.2f}", start, end])
    # Piece 26.7: stamp when this period was exported so Vanessa's payroll
    # reminder can show "exported ✓" and stop nagging (see payroll_status()).
    _meta_set(db, f"payroll_exported:{start}..{end}",
              datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    db.commit()
    return Response(buf.getvalue(), mimetype="text/csv", headers={
        "Content-Disposition": "attachment; filename=compendium_payroll.csv"})


@app.route("/jobs/<int:job_id>/loads")
def job_loads(job_id):
    """Piece 15.1: Electric loads & system sizing — its own page (was a tab
    on the job detail page)."""
    job = fetch_job(job_id)
    db = get_db()
    rooms = db.execute(
        "SELECT * FROM job_load_rooms WHERE job_id = ? ORDER BY sort_order, id",
        (job_id,),
    ).fetchall()
    load_items = db.execute(
        "SELECT * FROM job_load_items WHERE job_id = ? ORDER BY id", (job_id,)
    ).fetchall()
    items_by_room = {}
    for it in load_items:
        items_by_room.setdefault(it["room_id"], []).append(it)
    sizing = fetch_job_sizing(db, job_id)
    bom = db.execute(
        "SELECT * FROM job_bom WHERE job_id = ? ORDER BY id", (job_id,)
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
        "job_loads.html", job=job, locked=_loads_locked(job),
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
def _loads_locked(job):
    """Piece 22.2: Loads & Sizing is a Proposal-phase tool. Once the job
    advances past Proposal (the contract is signed), the editor locks — the
    recorded figures stay visible on the job and in Design, but no one re-opens
    the tool to change them. Lost jobs (outside the normal stage order) are left
    editable in case one is revived."""
    status = job["status"] if "status" in job.keys() else ""
    return status in STAGE_ORDER and STAGE_ORDER.index(status) > 0


LOADS_LOCK_MSG = ("Loads & Sizing locks once the contract is signed — the "
                  "recorded figures are final and view-only from here.")


def loads_unlocked(view):
    """Guard a loads-editing POST: refuse the write once the job is past
    Proposal, so the locked figures can't be changed from anywhere."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if _loads_locked(fetch_job(kwargs["job_id"])):
            flash(LOADS_LOCK_MSG, "error")
            return redirect(url_for("job_loads", job_id=kwargs["job_id"]))
        return view(*args, **kwargs)
    return wrapped


@app.route("/jobs/<int:job_id>/loads/rooms/add", methods=["POST"])
@loads_unlocked
def add_load_room(job_id):
    fetch_job(job_id)
    name = request.form.get("name", "").strip()
    room_type = request.form.get("room_type", "standard")
    if room_type not in ROOM_TYPES:
        room_type = "standard"
    if not name:
        flash("Room name is required.", "error")
        return redirect(url_for("job_loads", job_id=job_id))
    category = request.form.get("category", "").strip()
    db = get_db()
    next_order = db.execute(
        "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM job_load_rooms WHERE job_id = ?",
        (job_id,),
    ).fetchone()[0]
    db.execute(
        "INSERT INTO job_load_rooms (job_id, name, room_type, category, sort_order)"
        " VALUES (?, ?, ?, ?, ?)",
        (job_id, name, room_type, category, next_order),
    )
    db.commit()
    return redirect(url_for("job_loads", job_id=job_id))


@app.route("/jobs/<int:job_id>/loads/rooms/<int:room_id>/toggle", methods=["POST"])
@loads_unlocked
def toggle_load_room(job_id, room_id):
    db = get_db()
    db.execute(
        "UPDATE job_load_rooms SET enabled = 1 - enabled WHERE id = ? AND job_id = ?",
        (room_id, job_id),
    )
    db.commit()
    return redirect(url_for("job_loads", job_id=job_id))


@app.route("/jobs/<int:job_id>/loads/rooms/<int:room_id>/edit", methods=["POST"])
@loads_unlocked
def update_load_room(job_id, room_id):
    fetch_job(job_id)
    db = get_db()
    if db.execute("SELECT 1 FROM job_load_rooms WHERE id = ? AND job_id = ?",
                  (room_id, job_id)).fetchone() is None:
        abort(404)
    name = request.form.get("name", "").strip()
    if not name:
        flash("The room needs a name.", "error")
        return redirect(url_for("job_loads", job_id=job_id, edit_room=room_id))
    room_type = request.form.get("room_type", "standard").strip() or "standard"
    category = request.form.get("category", "").strip()
    db.execute("UPDATE job_load_rooms SET name = ?, room_type = ?, category = ?"
               " WHERE id = ?", (name, room_type, category, room_id))
    db.commit()
    flash("Room updated.")
    return redirect(url_for("job_loads", job_id=job_id))


@app.route("/jobs/<int:job_id>/loads/rooms/<int:room_id>/delete", methods=["POST"])
@delete_required
@loads_unlocked
def delete_load_room(job_id, room_id):
    ok, msg = trash_item("load_room", room_id)
    flash(msg, "" if ok else "error")
    return redirect(url_for("job_loads", job_id=job_id))


@app.route("/jobs/<int:job_id>/loads/items/add", methods=["POST"])
@loads_unlocked
def add_load_item(job_id):
    fetch_job(job_id)
    db = get_db()
    room_id = request.form.get("room_id", type=int)
    room = db.execute(
        "SELECT * FROM job_load_rooms WHERE id = ? AND job_id = ?", (room_id, job_id)
    ).fetchone()
    if not room:
        flash("Pick a room before adding an appliance.", "error")
        return redirect(url_for("job_loads", job_id=job_id))

    catalog_id = request.form.get("catalog_id", type=int)
    if catalog_id:
        appliance = db.execute(
            "SELECT * FROM appliance_catalog WHERE id = ?", (catalog_id,)
        ).fetchone()
        if not appliance:
            flash("Appliance not found in the catalog.", "error")
            return redirect(url_for("job_loads", job_id=job_id))
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
            return redirect(url_for("job_loads", job_id=job_id))

    qty = _float(request.form.get("qty"), 1) or 1
    # Allow overriding hrs/day from the form even for a catalog pick.
    hrs_override = request.form.get("hrs")
    if hrs_override not in (None, ""):
        hrs = _float(hrs_override, hrs)

    db.execute(
        "INSERT INTO job_load_items"
        " (job_id, room_id, appliance, watts, qty, hrs, usage_type)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (job_id, room_id, name, watts, qty, hrs, usage_type),
    )
    db.commit()
    return redirect(url_for("job_loads", job_id=job_id))


@app.route("/jobs/<int:job_id>/loads/items/<int:item_id>/edit", methods=["POST"])
@loads_unlocked
def update_load_item(job_id, item_id):
    fetch_job(job_id)
    db = get_db()
    if db.execute("SELECT 1 FROM job_load_items WHERE id = ? AND job_id = ?",
                  (item_id, job_id)).fetchone() is None:
        abort(404)
    name = request.form.get("appliance", "").strip()
    if not name:
        flash("The appliance needs a name.", "error")
        return redirect(url_for("job_loads", job_id=job_id, edit_item=item_id))
    db.execute(
        "UPDATE job_load_items SET appliance = ?, watts = ?, qty = ?, hrs = ?,"
        " usage_type = ? WHERE id = ?",
        (name, _float(request.form.get("watts")),
         _float(request.form.get("qty"), 1) or 1, _float(request.form.get("hrs")),
         request.form.get("usage_type", "").strip(), item_id))
    db.commit()
    flash("Appliance updated.")
    return redirect(url_for("job_loads", job_id=job_id))


@app.route("/jobs/<int:job_id>/loads/items/<int:item_id>/delete", methods=["POST"])
@delete_required
@loads_unlocked
def delete_load_item(job_id, item_id):
    ok, msg = trash_item("load_item", item_id)
    flash(msg, "" if ok else "error")
    return redirect(url_for("job_loads", job_id=job_id))


@app.route("/jobs/<int:job_id>/loads/bom/add", methods=["POST"])
@loads_unlocked
def add_bom_item(job_id):
    fetch_job(job_id)
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
            return redirect(url_for("job_loads", job_id=job_id))
        # Adding the same component again increments quantity instead of
        # creating a duplicate row.
        existing = db.execute(
            "SELECT * FROM job_bom WHERE job_id = ? AND component_id = ?",
            (job_id, component_id),
        ).fetchone()
        if existing:
            db.execute("UPDATE job_bom SET qty = qty + ? WHERE id = ?",
                       (qty, existing["id"]))
        else:
            db.execute(
                "INSERT INTO job_bom"
                " (job_id, component_id, component_name, category, qty,"
                "  unit_cost, notes)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (job_id, component_id, comp["name"], comp["category"], qty,
                 comp["cost"], notes),
            )
    else:
        name = request.form.get("custom_name", "").strip()
        category = request.form.get("custom_category", "").strip()
        cost = request.form.get("custom_cost")
        if not name:
            flash("Give the custom component a name.", "error")
            return redirect(url_for("job_loads", job_id=job_id))
        db.execute(
            "INSERT INTO job_bom"
            " (job_id, component_id, component_name, category, qty,"
            "  unit_cost, notes)"
            " VALUES (?, NULL, ?, ?, ?, ?, ?)",
            (job_id, name, category, qty, _float(cost, None) if cost else None, notes),
        )
    db.commit()
    return redirect(url_for("job_loads", job_id=job_id))


@app.route("/jobs/<int:job_id>/loads/bom/suggest", methods=["POST"])
@loads_unlocked
def accept_suggested_component(job_id):
    """Piece 26.5: one-click accept of an auto-suggested inventory component.
    Drops the picked item into the BOM at the sized quantity, at its inventory
    cost. Inventory items aren't catalog components, so component_id stays NULL;
    accepting the same item again tops up its quantity instead of duplicating."""
    fetch_job(job_id)
    db = get_db()
    name = request.form.get("name", "").strip()
    category = request.form.get("category", "").strip()
    qty = _float(request.form.get("qty"), 1) or 1
    cost = request.form.get("unit_cost")
    unit_cost = _float(cost, None) if cost not in (None, "") else None
    if not name:
        flash("Nothing to add.", "error")
        return redirect(url_for("job_loads", job_id=job_id))
    existing = db.execute(
        "SELECT id FROM job_bom WHERE job_id = ? AND component_id IS NULL"
        "   AND component_name = ? AND category = ?",
        (job_id, name, category)).fetchone()
    if existing:
        db.execute("UPDATE job_bom SET qty = ? WHERE id = ?", (qty, existing["id"]))
    else:
        db.execute(
            "INSERT INTO job_bom"
            " (job_id, component_id, component_name, category, qty, unit_cost, notes)"
            " VALUES (?, NULL, ?, ?, ?, ?, ?)",
            (job_id, name, category, qty, unit_cost, "Suggested from inventory"))
    db.commit()
    flash(f"Added {name} to the BOM.")
    return redirect(url_for("job_loads", job_id=job_id))


@app.route("/jobs/<int:job_id>/loads/bom/<int:bom_id>/edit", methods=["POST"])
@loads_unlocked
def update_bom_item(job_id, bom_id):
    fetch_job(job_id)
    db = get_db()
    if db.execute("SELECT 1 FROM job_bom WHERE id = ? AND job_id = ?",
                  (bom_id, job_id)).fetchone() is None:
        abort(404)
    name = request.form.get("component_name", "").strip()
    if not name:
        flash("The component needs a name.", "error")
        return redirect(url_for("job_loads", job_id=job_id, edit_bom=bom_id))
    cost = request.form.get("unit_cost")
    # Piece 29.6: optional per-line markup override (blank = use category default).
    mk_raw = request.form.get("markup_pct", "")
    markup = "" if mk_raw.strip() == "" else str(max(_to_float(mk_raw) or 0.0, 0.0))
    db.execute(
        "UPDATE job_bom SET component_name = ?, category = ?, qty = ?,"
        " unit_cost = ?, notes = ?, markup_pct = ? WHERE id = ?",
        (name, request.form.get("category", "").strip(),
         _float(request.form.get("qty"), 1) or 1,
         _float(cost, None) if cost not in (None, "") else None,
         request.form.get("notes", "").strip(), markup, bom_id))
    db.commit()
    flash("Component updated.")
    return redirect(url_for("job_loads", job_id=job_id))


@app.route("/jobs/<int:job_id>/loads/bom/<int:bom_id>/delete", methods=["POST"])
@delete_required
@loads_unlocked
def delete_bom_item(job_id, bom_id):
    ok, msg = trash_item("bom", bom_id)
    flash(msg, "" if ok else "error")
    return redirect(url_for("job_loads", job_id=job_id))


@app.route("/jobs/<int:job_id>/loads/sizing", methods=["POST"])
@loads_unlocked
def update_sizing(job_id):
    fetch_job(job_id)
    db = get_db()
    fetch_job_sizing(db, job_id)  # ensure the row exists

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
        "UPDATE job_sizing SET ui_mode = ?, system_type = ?, sun_hours = ?,"
        " derate_pct = ?, autonomy_days = ?, solar_fraction_pct = ?,"
        " panel_watts = ?, dod_pct = ?, round_trip_eff_pct = ?,"
        " inverter_eff_pct = ?, max_input_v = ?, record_low_temp_f = ?,"
        " backup_daily_kwh = ?, selected_battery_id = ?, selected_pv_module_id = ?,"
        " updated_at = datetime('now')"
        " WHERE job_id = ?",
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
            selected_battery_id, selected_pv_module_id, job_id,
        ),
    )
    db.commit()
    return redirect(url_for("job_loads", job_id=job_id))


@app.route("/jobs/<int:job_id>/loads/mode", methods=["POST"])
def set_ui_mode(job_id):
    # Piece 26.4: the view mode is now a per-viewer session preference (the
    # default comes from their department), not a per-job stored value.
    ui_mode = request.form.get("ui_mode", "designer")
    session["loads_ui_mode"] = ui_mode if ui_mode in UI_MODES else "designer"
    return redirect(url_for("job_loads", job_id=job_id))


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


def apply_stock_txn(db, item_id, kind, delta, job_id=None, note="", user_name=""):
    """Write one stock-ledger row and update the item's cached balance. `delta`
    is the signed change to `available` (received > 0, used < 0, count = target −
    current). A 'used' movement stamps last_used = today, which the stale-stock
    notice keys off. This is the single choke-point every stock change flows
    through — the later BOM auto-deduct will call it too."""
    db.execute(
        "INSERT INTO inventory_txns (item_id, kind, qty, job_id, note, created_by)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (item_id, kind, delta, job_id, note, user_name))
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
        " FROM inventory_txns t LEFT JOIN jobs j ON j.id = t.job_id"
        " WHERE t.item_id = ? ORDER BY t.id DESC LIMIT 10", (item_id,)).fetchall()
    jobs = db.execute(
        "SELECT j.id, j.job_name, c.name AS client_name FROM jobs j"
        " JOIN clients c ON c.id = j.client_id WHERE j.status != 'Lost'"
        " ORDER BY j.id DESC").fetchall()
    return render_template(
        "inventory_item_form.html", item=item, category=item["category"],
        spec_fields=inventory_category_specs().get(item["category"], []),
        categories=INVENTORY_CAT_ORDER, txns=txns, jobs=jobs,
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
    through the ledger. 'Used' can be tied to a job and stamps last_used."""
    db = get_db()
    row = db.execute("SELECT available FROM inventory_items WHERE id = ?",
                     (item_id,)).fetchone()
    if row is None:
        abort(404)
    kind = request.form.get("kind", "used")
    qty = int(_to_float(request.form.get("qty")) or 0)
    job_raw = request.form.get("job_id", "")
    job_id = int(job_raw) if job_raw.isdigit() else None
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
    apply_stock_txn(db, item_id, kind, delta, job_id, note,
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
           " LEFT JOIN jobs j ON j.id = a.job_id WHERE 1=1")
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
        " LEFT JOIN jobs j ON j.id = a.job_id WHERE UPPER(a.serial) = ?",
        (serial,)).fetchone()


@app.route("/inventory/scan")
def inventory_scan():
    """Scan (or type) a serial to check it in / out. Keyboard-wedge friendly."""
    db = get_db()
    code = request.args.get("code", "")
    asset = _resolve_serial(db, code) if code else None
    not_found = bool(code) and asset is None
    jobs = db.execute(
        "SELECT j.id, j.job_name, c.name AS client_name FROM jobs j"
        " JOIN clients c ON c.id = j.client_id"
        " WHERE j.status NOT IN ('Complete', 'Lost') ORDER BY j.id DESC").fetchall()
    return render_template("inventory_scan.html", code=code, asset=asset,
                           not_found=not_found, jobs=jobs)


@app.route("/inventory/assets/<int:asset_id>/checkout", methods=["POST"])
def inventory_asset_checkout(asset_id):
    db = get_db()
    a = db.execute("SELECT * FROM inventory_assets WHERE id = ?",
                   (asset_id,)).fetchone()
    if a is None:
        abort(404)
    job_raw = request.form.get("job_id", "")
    job_id = int(job_raw) if job_raw.isdigit() else None
    user = current_user()
    who = user["name"] if user else ""
    if a["kind"] == "consumable":
        # Scanning a consumable out records a 'used' stock movement on its item.
        qty = int(_to_float(request.form.get("qty")) or 1)
        apply_stock_txn(db, a["entity_id"], "used", -abs(qty), job_id,
                        f"Scanned out ({a['serial']})", who)
        db.execute("UPDATE inventory_assets SET last_action = ?,"
                   " last_action_by = ?, last_action_at = datetime('now') WHERE id = ?",
                   (f"Issued {qty} to job", who, asset_id))
        db.commit()
        flash(f"Recorded {qty} × {a['label']} used" +
              (" on the job." if job_id else "."))
    else:
        db.execute("UPDATE inventory_assets SET status = 'Out', job_id = ?,"
                   " last_action = 'Checked out', last_action_by = ?,"
                   " last_action_at = datetime('now') WHERE id = ?",
                   (job_id, who, asset_id))
        db.commit()
        flash(f"{a['label']} checked out" + (" to the job." if job_id else "."))
    return redirect(url_for("inventory_scan"))


@app.route("/inventory/assets/<int:asset_id>/checkin", methods=["POST"])
def inventory_asset_checkin(asset_id):
    db = get_db()
    a = db.execute("SELECT * FROM inventory_assets WHERE id = ?",
                   (asset_id,)).fetchone()
    if a is None:
        abort(404)
    user = current_user()
    db.execute("UPDATE inventory_assets SET status = 'In stock', job_id = NULL,"
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
    db.execute("UPDATE inventory_assets SET status = 'Retired', job_id = NULL,"
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
    """Piece 26.1: rapid truck-loading. A crew picks the job once, then scans
    tags with the phone camera (or a scanner) to load them out — open to any
    signed-in worker so two Installers can load the same job in parallel."""
    db = get_db()
    job_id = request.args.get("job_id", type=int)
    jobs = db.execute(
        "SELECT j.id, j.job_name, c.name AS client_name FROM jobs j"
        " JOIN clients c ON c.id = j.client_id"
        " WHERE j.status NOT IN ('Complete', 'Lost') ORDER BY j.id DESC").fetchall()
    job = None
    if job_id:
        job = db.execute("SELECT j.id, j.job_name, c.name AS client_name FROM jobs j"
                         " JOIN clients c ON c.id = j.client_id WHERE j.id = ?",
                         (job_id,)).fetchone()
    return render_template("inventory_load.html", jobs=jobs, job=job)


@app.route("/api/inventory/scan-out", methods=["POST"])
def api_scan_out():
    """JSON check-out for the continuous-scan loading flow. Non-consumables go
    Out (to the job); consumables record a 'used' stock movement. Open to any
    signed-in worker (crews load their own trucks)."""
    user = current_user()
    if user is None:
        return jsonify({"ok": False, "error": "Please sign in."}), 401
    db = get_db()
    data = request.get_json(silent=True) or request.form
    serial = (data.get("serial") or "").strip()
    job_raw = str(data.get("job_id") or "")
    job_id = int(job_raw) if job_raw.isdigit() else None
    qty = int(_to_float(data.get("qty")) or 1) or 1
    a = _resolve_serial(db, serial)
    if a is None:
        return jsonify({"ok": False, "error": f"Unknown tag {serial}"})
    if a["status"] == "Retired":
        return jsonify({"ok": False, "label": a["label"],
                        "error": f"{a['label']} is retired"})
    who = user["name"]
    if a["kind"] == "consumable":
        apply_stock_txn(db, a["entity_id"], "used", -abs(qty), job_id,
                        f"Loaded ({a['serial']})", who)
        db.execute("UPDATE inventory_assets SET last_action = ?,"
                   " last_action_by = ?, last_action_at = datetime('now') WHERE id = ?",
                   (f"Loaded {qty} to job", who, a["id"]))
        db.commit()
        return jsonify({"ok": True, "label": a["label"], "serial": a["serial"],
                        "action": f"loaded ×{qty}"})
    if a["status"] == "Out":
        return jsonify({"ok": True, "warn": True, "label": a["label"],
                        "serial": a["serial"], "action": "already out"})
    db.execute("UPDATE inventory_assets SET status = 'Out', job_id = ?,"
               " last_action = 'Loaded', last_action_by = ?,"
               " last_action_at = datetime('now') WHERE id = ?",
               (job_id, who, a["id"]))
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
    # job BOM line or sizing selection; otherwise it goes to the trash.
    ok, msg = trash_item("component", component_id)
    flash(msg, "" if ok else "error")
    return redirect(url_for("catalog_page"))


@app.route("/jobs/<int:job_id>/status", methods=["POST"])
def set_job_status(job_id):
    job = fetch_job(job_id)
    status = request.form.get("status", "")
    if status == "Lost":
        # Piece 30.2: cancelling goes through the reason flow, never the plain
        # stage dropdown.
        flash("Use “Cancel job” to mark a job Lost (a reason is required).", "error")
        return redirect(url_for("job_detail", job_id=job_id))
    if status in JOB_STATUSES:
        db = get_db()
        # Flexible guardrail: if advancing to the next stage before the current
        # one is complete, allow it but note what was still pending.
        cur = job["status"] or DEFAULT_JOB_STATUS
        warn = ""
        if status == next_stage(cur):
            rules = db.execute("SELECT * FROM resource_rules").fetchall()
            groups = group_rules(match_rules(job, rules))
            filed = {f["rule_label"] for f in db.execute(
                "SELECT rule_label FROM job_files WHERE job_id = ?", (job_id,))
                if f["rule_label"]}
            info = stage_info(db, job, groups, filed)
            if not info["ready"]:
                warn = " · ".join(info["pending"])
        db.execute("UPDATE jobs SET status = ? WHERE id = ?", (status, job_id))
        # Piece 29.4: on a forward turnover, alert the stage's department(s).
        moved_forward = (status != cur and status in STAGE_ORDER
                         and (cur not in STAGE_ORDER
                              or STAGE_ORDER.index(status) > STAGE_ORDER.index(cur)))
        gen_added = 0
        if moved_forward:
            actor = current_user()
            notify_stage_turnover(db, job, status,
                                  exclude_id=actor["id"] if actor else None)
            # Piece 31.5: auto-fill and assign the tasks the job just moved into,
            # so the receiving department lands with its to-dos already populated.
            # Only the entered stage's steps are generated (role-assigned, dated);
            # existing tasks are skipped, so this never duplicates the manual
            # "Generate tasks" button. Complete has no work of its own.
            if status != "Complete":
                job_row = fetch_job(job_id)  # re-read so scheduling sees new status
                install_raw = (job_row["install_date"]
                               if "install_date" in job_row.keys() else "") or ""
                gen_added, _a, _s = _generate_job_tasks(
                    db, job_row, install_raw, only_status=status)
        db.commit()
        if warn:
            flash(f"Advanced to {status} with {cur} still pending: {warn}.", "error")
        if gen_added:
            flash(f"Auto-added {gen_added} {status} task"
                  f"{'s' if gen_added != 1 else ''}, assigned by role where possible.")
    return redirect(url_for("job_detail", job_id=job_id))


@app.route("/jobs/<int:job_id>/cancel", methods=["POST"])
def cancel_job(job_id):
    """Piece 30.2: cancel a job — mark it Lost with a required reason (captured
    in the audit log), remembering the current stage so it can be reopened.
    The job's open tasks stop showing in My Tasks / the board / Work Bag while
    it's Lost, but nothing is deleted."""
    job = fetch_job(job_id)
    reason = request.form.get("reason", "").strip()
    if not reason:
        flash("A reason is required to cancel a job.", "error")
        return redirect(url_for("job_detail", job_id=job_id))
    if (job["status"] or "") == "Lost":
        flash("This job is already cancelled.")
        return redirect(url_for("job_detail", job_id=job_id))
    db = get_db()
    who = current_user()
    db.execute(
        "UPDATE jobs SET pre_lost_status = ?, status = 'Lost', cancel_reason = ?,"
        " cancelled_at = ?, cancelled_by = ? WHERE id = ?",
        (job["status"] or DEFAULT_JOB_STATUS, reason,
         datetime.now().isoformat(timespec="seconds"),
         who["name"] if who else "", job_id))
    # Piece 30.3: tell everyone who was involved in the job up to this point.
    recipients = job_involved_ids(db, job, exclude_id=who["id"] if who else None)
    if recipients:
        client = db.execute("SELECT name FROM clients WHERE id = ?",
                            (job["client_id"],)).fetchone()
        cname = client["name"] if client else ""
        jobname = job["job_name"] or f"Job #{job['id']}"
        notify_employees(
            db, recipients,
            f"🚫 {jobname}{(' · ' + cname) if cname else ''} was cancelled "
            f"(Lost). Reason: “{reason}”.",
            link=url_for("job_detail", job_id=job["id"]), kind="job_cancelled")
    db.commit()
    flash(f"Job cancelled (Lost). Reason recorded: “{reason}”."
          + (f" {len(recipients)} team member(s) notified." if recipients else ""))
    return redirect(url_for("job_detail", job_id=job_id))


@app.route("/jobs/<int:job_id>/reopen", methods=["POST"])
def reopen_job(job_id):
    """Piece 30.2: reopen a cancelled job — restore the stage it was at before
    it was marked Lost (its tasks reappear) and clear the cancellation info."""
    job = fetch_job(job_id)
    if (job["status"] or "") != "Lost":
        flash("Only a cancelled (Lost) job can be reopened.", "error")
        return redirect(url_for("job_detail", job_id=job_id))
    prev = (job["pre_lost_status"] if "pre_lost_status" in job.keys() else "") or ""
    restore = prev if prev in STAGE_ORDER else DEFAULT_JOB_STATUS
    db = get_db()
    db.execute(
        "UPDATE jobs SET status = ?, cancel_reason = '', cancelled_at = '',"
        " cancelled_by = '', pre_lost_status = '' WHERE id = ?", (restore, job_id))
    db.commit()
    flash(f"Job reopened at {restore}.")
    return redirect(url_for("job_detail", job_id=job_id))


@app.route("/closed-jobs")
@admin_required
def closed_jobs_page():
    """Piece 30.3: management review of closed jobs — cancelled (Lost) jobs with
    their reason and a reopen action, plus completed jobs — the way cold leads
    are reviewed. Gated to Admin / GM."""
    db = get_db()
    cancelled = db.execute(
        "SELECT j.*, c.name AS client_name FROM jobs j"
        " JOIN clients c ON c.id = j.client_id WHERE j.status = 'Lost'"
        " ORDER BY (j.cancelled_at = ''), j.cancelled_at DESC, j.id DESC").fetchall()
    completed = db.execute(
        "SELECT j.*, c.name AS client_name FROM jobs j"
        " JOIN clients c ON c.id = j.client_id WHERE j.status = 'Complete'"
        " ORDER BY j.id DESC").fetchall()
    return render_template("closed_jobs.html", cancelled=cancelled,
                           completed=completed)


@app.route("/jobs/<int:job_id>/install-date", methods=["POST"])
def set_install_date(job_id):
    """Set the job's install date; in Job Prep, advancing it to Installation
    once all permits are filed (Piece 18 — the install-date setter triggers
    the hand-off)."""
    job = fetch_job(job_id)
    db = get_db()
    date = request.form.get("install_date", "").strip()
    db.execute("UPDATE jobs SET install_date = ? WHERE id = ?", (date, job_id))
    advanced = False
    if date and (job["status"] or DEFAULT_JOB_STATUS) == "Job Prep":
        rules = db.execute("SELECT * FROM resource_rules").fetchall()
        groups = group_rules(match_rules(job, rules))
        filed = {f["rule_label"] for f in db.execute(
            "SELECT rule_label FROM job_files WHERE job_id = ?", (job_id,))
            if f["rule_label"]}
        if stage_info(db, job, groups, filed)["permits_ok"]:
            db.execute("UPDATE jobs SET status = 'Installation' WHERE id = ?", (job_id,))
            advanced = True
            actor = current_user()  # Piece 29.4: alert the Installation team
            notify_stage_turnover(db, job, "Installation",
                                  exclude_id=actor["id"] if actor else None)
    db.commit()
    if advanced:
        flash("Install date set and all permits filed — advanced to Installation.")
    elif date:
        flash("Install date saved. Job Prep stays open until all permits are filed.")
    else:
        flash("Install date cleared.")
    return redirect(url_for("job_detail", job_id=job_id))


# ---------------------------------------------------------------- materials
@app.route("/jobs/<int:job_id>/materials/add", methods=["POST"])
def add_material(job_id):
    fetch_job(job_id)
    item = request.form.get("item", "").strip()
    if not item:
        flash("Material item name is required.", "error")
        return redirect(url_for("job_detail", job_id=job_id, _anchor="materials"))
    db = get_db()
    db.execute(
        "INSERT INTO job_materials (job_id, item, quantity, unit, supplier, notes)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (job_id, item,
         request.form.get("quantity", "").strip(),
         request.form.get("unit", "").strip(),
         request.form.get("supplier", "").strip(),
         request.form.get("notes", "").strip()),
    )
    db.commit()
    return redirect(url_for("job_detail", job_id=job_id, _anchor="materials"))


@app.route("/jobs/<int:job_id>/materials/<int:material_id>/status", methods=["POST"])
def update_material_status(job_id, material_id):
    status = request.form.get("status", "")
    if status in MATERIAL_STATUSES:
        db = get_db()
        db.execute(
            "UPDATE job_materials SET status = ? WHERE id = ? AND job_id = ?",
            (status, material_id, job_id),
        )
        db.commit()
    return redirect(url_for("job_detail", job_id=job_id, _anchor="materials"))


@app.route("/jobs/<int:job_id>/materials/<int:material_id>/edit", methods=["POST"])
def edit_material(job_id, material_id):
    item = request.form.get("item", "").strip()
    if not item:
        flash("Material item name is required.", "error")
        return redirect(url_for("job_detail", job_id=job_id, _anchor="materials"))
    db = get_db()
    db.execute(
        "UPDATE job_materials SET item = ?, quantity = ?, unit = ?, supplier = ?,"
        " notes = ? WHERE id = ? AND job_id = ?",
        (item, request.form.get("quantity", "").strip(),
         request.form.get("unit", "").strip(),
         request.form.get("supplier", "").strip(),
         request.form.get("notes", "").strip(), material_id, job_id))
    db.commit()
    return redirect(url_for("job_detail", job_id=job_id, _anchor="materials"))


@app.route("/jobs/<int:job_id>/materials/<int:material_id>/delete", methods=["POST"])
@delete_required
def delete_material(job_id, material_id):
    ok, msg = trash_item("material", material_id)
    flash(msg, "" if ok else "error")
    return redirect(url_for("job_detail", job_id=job_id, _anchor="materials"))


# -------------------------------------------------------------------- tasks
def _task_assignee(job_id):
    """Read and validate an employee_id from the form: blank means
    unassigned, a real employee id is kept, anything else is rejected."""
    raw = request.form.get("employee_id", "").strip()
    if not raw:
        return None
    emp = get_db().execute(
        "SELECT id FROM employees WHERE id = ?", (raw,)).fetchone()
    return emp["id"] if emp else None


@app.route("/jobs/<int:job_id>/tasks/add", methods=["POST"])
def add_task(job_id):
    fetch_job(job_id)
    title = request.form.get("title", "").strip()
    if not title:
        flash("A task needs a title.", "error")
        return redirect(url_for("job_detail", job_id=job_id, _anchor="tasks"))
    status = request.form.get("status", "To do")
    if status not in TASK_STATUSES:
        status = "To do"
    db = get_db()
    next_order = db.execute(
        "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM job_tasks WHERE job_id = ?",
        (job_id,)).fetchone()[0]
    db.execute(
        "INSERT INTO job_tasks"
        " (job_id, employee_id, title, status, due_date, notes, sort_order,"
        "  completed_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, strftime('%Y-%m-%d %H:%M:%f', 'now'))",
        (job_id, _task_assignee(job_id), title, status,
         request.form.get("due_date", "").strip(),
         request.form.get("notes", "").strip(), next_order,
         datetime.now().strftime("%Y-%m-%d") if status == "Done" else ""),
    )
    db.commit()
    return redirect(url_for("job_detail", job_id=job_id, _anchor="tasks"))


def best_assignee_for_lane(lane, employees):
    """The most sensible employee to own a step in this lane (Piece 17.2).
    Among everyone who holds a role mapped to the lane, prefer: a non-GM over
    the General Manager (who holds many roles), then the better-matching role
    (LANE_TO_ROLES is in priority order), then the most specialized person
    (fewest roles). Deterministic; None if no one holds a mapped role."""
    roles = LANE_TO_ROLES.get(lane, [])
    if not roles:
        return None
    priority = {r.lower(): i for i, r in enumerate(roles)}
    best_key = best_id = None
    for e in employees:
        emp_roles = [r.strip().lower() for r in (e["roles"] or "").split(",") if r.strip()]
        matched = [priority[r] for r in emp_roles if r in priority]
        if not matched:
            continue
        name = e["name"] if "name" in e.keys() else ""
        # Prefer real staff over the demo employees, then a specialist over the
        # General Manager, then the better-matching role, then fewest roles.
        key = ("(sample)" in (name or ""), "general manager" in emp_roles,
               min(matched), len(emp_roles), e["id"])
        if best_key is None or key < best_key:
            best_key, best_id = key, e["id"]
    return best_id


def _auto_assignee(lane, employees):
    """Assignee for a generated step — the most sensible role-holder."""
    return best_assignee_for_lane(lane, employees)


def _permit_coverage(groups, filed_labels):
    """(filed, total) for the job's Permit-category requirements."""
    total = filed = 0
    for heading, items in groups:
        if heading.lower().startswith("permit"):
            total += len(items)
            filed += sum(1 for r in items if r["label"] in filed_labels)
    return filed, total


def job_permit_coverage(db, job, rules):
    """(filed, total) permits for a job — its resolved permit requirements vs.
    the permit documents already filed. For the Permits dashboard column."""
    groups = group_rules(match_rules(job, rules))
    filed_labels = {f["rule_label"] for f in db.execute(
        "SELECT rule_label FROM job_files WHERE job_id = ?", (job["id"],)).fetchall()
        if f["rule_label"]}
    return _permit_coverage(groups, filed_labels)


def _loads_recorded(db, job):
    """True once the walkthrough loads have been captured for a job — either
    the structured Loads & Sizing worksheet has line items, or the free-text
    loads summary on the job is filled. Used to gate the Proposal stage."""
    if (job["electric_loads"] if "electric_loads" in job.keys() else "").strip():
        return True
    n = db.execute("SELECT COUNT(*) FROM job_load_items WHERE job_id = ?",
                   (job["id"],)).fetchone()[0]
    return n > 0


def stage_info(db, job, groups, filed_labels):
    """Piece 18: who governs the job's current stage (department + the head of
    each staffing function), the exit criteria, and Job-Prep prerequisites."""
    status = job["status"] or DEFAULT_JOB_STATUS
    spec = STATUS_OWNERSHIP.get(status, {"dept": "—", "exit": "", "team": []})
    emps = db.execute("SELECT id, name, roles FROM employees").fetchall()
    name_by_id = {e["id"]: e["name"] for e in emps}
    team = [(label, name_by_id.get(best_assignee_for_lane(lane, emps), "— unassigned —"))
            for label, lane in spec["team"]]
    filed, total = _permit_coverage(groups, filed_labels)
    permits_ok = filed >= total
    install_date = job["install_date"] if "install_date" in job.keys() else ""
    # Loads are collected during the walkthrough, not at job creation — the
    # Proposal stage requires them recorded before it can advance. "Recorded"
    # means either the structured Loads & Sizing worksheet has entries or the
    # free-text loads summary is filled.
    loads_ok = _loads_recorded(db, job)
    # Progress: this stage's own tasks (tagged with pipeline_status = status).
    tdone, ttotal = db.execute(
        "SELECT COALESCE(SUM(status = 'Done'), 0), COUNT(*) FROM job_tasks"
        " WHERE job_id = ? AND pipeline_status = ?", (job["id"], status)).fetchone()
    # Ready to advance? All this stage's tasks done; Proposal also needs the
    # loads collected; Job Prep also needs permits filed + an install date.
    ready = (ttotal == 0 or tdone >= ttotal)
    pending = []
    if ttotal and tdone < ttotal:
        pending.append(f"{ttotal - tdone} task(s) still open")
    if status == "Proposal":
        if not loads_ok:
            pending.append("electric loads not recorded")
        ready = ready and loads_ok
    if status == "Job Prep":
        if not permits_ok:
            pending.append(f"{total - filed} permit(s) not filed")
        if not install_date:
            pending.append("no install date set")
        ready = ready and permits_ok and bool(install_date)
    return {
        "status": status, "dept": spec["dept"], "exit": spec["exit"], "team": team,
        "permits_filed": filed, "permits_total": total, "permits_ok": permits_ok,
        "install_date": install_date, "tasks_done": tdone, "tasks_total": ttotal,
        "loads_ok": loads_ok,
        "ready": ready, "pending": pending, "next": next_stage(status),
    }


def build_job_progress(db, job):
    """Piece 20.2: compact pipeline snapshot for the per-job progress widget.
    Returns the ordered pipeline stages each tagged done / current / upcoming
    (or skip when the job is Lost), an overall percent across the pipeline, and
    the single next actionable step — so a glance at the bar tells anyone where
    a job stands and what happens next. Safe for any job row; two small
    queries."""
    status = job["status"] or DEFAULT_JOB_STATUS
    lost = (status == "Lost")
    complete = (status == "Complete")
    order = STAGE_ORDER  # Proposal .. Complete
    idx = order.index(status) if status in order else 0

    # Current-stage task progress drives the fractional fill of the bar.
    cur_done = cur_total = 0
    if not lost and not complete:
        cur_done, cur_total = db.execute(
            "SELECT COALESCE(SUM(status = 'Done'), 0), COUNT(*) FROM job_tasks"
            " WHERE job_id = ? AND pipeline_status = ?",
            (job["id"], status)).fetchone()

    # The next actionable step: lowest-sort_order task that isn't Done.
    nxt = None
    if not lost and not complete:
        nxt = db.execute(
            "SELECT t.title, e.name AS who FROM job_tasks t"
            " LEFT JOIN employees e ON e.id = t.employee_id"
            " WHERE t.job_id = ? AND t.status != 'Done'"
            " ORDER BY t.sort_order, t.id LIMIT 1", (job["id"],)).fetchone()

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

    # Overall percent: the working stages are Proposal..Closing (5 transitions
    # before Complete); Complete is 100%. Task completion within the current
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
        next_label, next_who = "Marked Lost", None
    elif complete:
        next_label, next_who = "Job complete", None
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


def job_billing(db, job_id, contract_amount=0.0):
    """Piece 21: financial rollup for a job — income collected/outstanding,
    expenses, and the balance — plus the raw transactions. Drives the Finance
    Payments table and the per-job Billing tab."""
    txns = db.execute(
        "SELECT t.*, (SELECT f.id FROM job_files f WHERE f.txn_id = t.id LIMIT 1)"
        " AS receipt_file_id FROM job_transactions t WHERE t.job_id = ?"
        " ORDER BY t.txn_date, t.id", (job_id,)).fetchall()
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


def _rate_dollars(base_wage, method, value):
    """Resolve a pay type to a $/hr rate for an employee: a multiplier type is
    the base wage times the multiplier; a flat type is the value itself."""
    base = _to_float(base_wage) or 0.0
    v = value or 0.0
    return base * v if method == "multiplier" else v


def payroll_pay_types(db):
    return db.execute("SELECT * FROM pay_types WHERE active = 1"
                      " ORDER BY sort_order, id").fetchall()


def _iso_week(date_str):
    try:
        y, w, _d = datetime.strptime(date_str, "%Y-%m-%d").isocalendar()
        return (y, w)
    except (ValueError, TypeError):
        return None


def payroll_summary(db, start, end):
    """Per-employee payroll rollup for a pay period [start, end]: hours and
    dollars per pay type, plus auto-overtime (hours over the weekly threshold of
    OT-eligible time earn the OT premium). Only *approved* time entries count.
    Uses each person's base wage and any per-type rate overrides."""
    types = payroll_pay_types(db)
    type_by_id = {t["id"]: t for t in types}
    overrides = {}   # (employee_id, pay_type_id) -> value
    for r in db.execute("SELECT employee_id, pay_type_id, value FROM pay_rates").fetchall():
        overrides[(r["employee_id"], r["pay_type_id"])] = r["value"]
    ot_threshold, ot_mult = ot_rules(db)
    entries = db.execute(
        "SELECT * FROM time_entries WHERE work_date >= ? AND work_date <= ?"
        " AND status = 'Approved' ORDER BY work_date, id", (start, end)).fetchall()
    emp = {}   # employee_id -> rollup
    week_elig = {}   # (employee_id, isoweek) -> OT-eligible hours
    for e in entries:
        pt = type_by_id.get(e["pay_type_id"])
        if pt is None:
            continue
        row = emp.get(e["employee_id"])
        if row is None:
            who = db.execute("SELECT id, name, base_wage FROM employees WHERE id = ?",
                             (e["employee_id"],)).fetchone()
            if who is None:
                continue
            row = {"employee": who, "hours": 0.0, "pay": 0.0,
                   "by_type": {t["id"]: {"hours": 0.0, "pay": 0.0} for t in types},
                   "ot_hours": 0.0, "ot_pay": 0.0}
            emp[e["employee_id"]] = row
        hrs = e["hours"] or 0.0
        val = overrides.get((e["employee_id"], e["pay_type_id"]), pt["value"])
        rate = _rate_dollars(row["employee"]["base_wage"], pt["method"], val)
        row["hours"] += hrs
        row["pay"] += hrs * rate
        cell = row["by_type"].setdefault(e["pay_type_id"], {"hours": 0.0, "pay": 0.0})
        cell["hours"] += hrs
        cell["pay"] += hrs * rate
        if pt["ot_eligible"]:
            wk = _iso_week(e["work_date"])
            if wk is not None:
                week_elig[(e["employee_id"], wk)] = week_elig.get((e["employee_id"], wk), 0.0) + hrs
    # Auto-overtime: per employee per ISO week, hours over the threshold earn the
    # OT premium (extra multiplier − 1) on the base wage, added on top.
    for (emp_id, _wk), elig in week_elig.items():
        if elig > ot_threshold and emp_id in emp:
            row = emp[emp_id]
            ot_h = elig - ot_threshold
            base = _to_float(row["employee"]["base_wage"]) or 0.0
            prem = ot_h * base * (ot_mult - 1.0)
            row["ot_hours"] += ot_h
            row["ot_pay"] += prem
            row["pay"] += prem
    rollup = sorted(emp.values(), key=lambda r: r["employee"]["name"].lower())
    totals = {"hours": sum(r["hours"] for r in rollup),
              "ot_hours": sum(r["ot_hours"] for r in rollup),
              "pay": sum(r["pay"] for r in rollup)}
    return types, rollup, totals


def _lane_from_task(notes, title):
    """The responsible lane for an existing task: from its 'Process step ·
    <lane>' note if present, else inferred from title keywords."""
    n = (notes or "").strip()
    if "·" in n and n.lower().startswith("process step"):
        return n.split("·", 1)[1].strip()
    t = (title or "").lower()
    for keyword, lane in TITLE_LANE_KEYWORDS:
        if keyword in t:
            return lane
    return None


def assign_tasks_by_role(db):
    """One-time (Piece 17.2): give every existing task a sensible assignee by
    role. Runs once per DB; leaves tasks already assigned to real staff alone,
    and (re)assigns unassigned or sample-assigned tasks."""
    if db.execute("SELECT 1 FROM meta WHERE key = 'tasks_role_assigned'").fetchone():
        return
    db.row_factory = sqlite3.Row  # init_db's connection isn't Row-based
    employees = db.execute("SELECT id, name, roles FROM employees").fetchall()
    if employees:
        tasks = db.execute(
            "SELECT t.id, t.title, t.notes, t.employee_id, e.name AS assignee"
            " FROM job_tasks t LEFT JOIN employees e ON e.id = t.employee_id"
        ).fetchall()
        for t in tasks:
            if t["employee_id"] and t["assignee"] and "(sample)" not in (t["assignee"] or ""):
                continue  # keep deliberate assignments to real staff
            lane = _lane_from_task(t["notes"], t["title"])
            aid = best_assignee_for_lane(lane, employees) if lane else None
            if aid:
                db.execute(
                    "UPDATE job_tasks SET employee_id = ?,"
                    " updated_at = strftime('%Y-%m-%d %H:%M:%f', 'now') WHERE id = ?",
                    (aid, t["id"]))
    db.execute("INSERT INTO meta (key, value) VALUES ('tasks_role_assigned', '1')"
               " ON CONFLICT(key) DO UPDATE SET value = excluded.value")
    db.commit()


def _status_from_title(title):
    t = (title or "").lower()
    for keyword, status in TITLE_STATUS_KEYWORDS:
        if keyword in t:
            return status
    return ""


def tag_tasks_by_stage(db):
    """One-time (Piece 18.1): give existing tasks a pipeline_status so current
    jobs show stage progress. Newly generated tasks are tagged at creation."""
    if db.execute("SELECT 1 FROM meta WHERE key = 'tasks_stage_tagged'").fetchone():
        return
    db.row_factory = sqlite3.Row
    for t in db.execute("SELECT id, title FROM job_tasks"
                        " WHERE COALESCE(pipeline_status, '') = ''").fetchall():
        status = _status_from_title(t["title"])
        if status:
            db.execute("UPDATE job_tasks SET pipeline_status = ? WHERE id = ?",
                       (status, t["id"]))
    db.execute("INSERT INTO meta (key, value) VALUES ('tasks_stage_tagged', '1')"
               " ON CONFLICT(key) DO UPDATE SET value = excluded.value")
    db.commit()


def _generate_job_tasks(db, job, install_date_raw="", only_status=None):
    """Piece 31.5: core of the task auto-generator — materialize a job's process
    steps into To-do tasks, auto-assigned by role/lane and scheduled, skipping
    steps already on the list (safe to re-run). When `only_status` is given,
    only steps tagged for that pipeline stage are inserted (used to auto-fill the
    stage a job just entered); otherwise every actionable step is generated.
    Returns (added, assigned, scheduled). Does not commit."""
    job_id = job["id"]
    rules = db.execute("SELECT * FROM resource_rules").fetchall()
    _xml, details = build_job_bpmn(job, match_rules(job, rules))
    employees = db.execute("SELECT id, name, roles FROM employees").fetchall()

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
        "SELECT title FROM job_tasks WHERE job_id = ?", (job_id,)).fetchall()}
    base = db.execute(
        "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM job_tasks WHERE job_id = ?",
        (job_id,)).fetchone()[0]
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
        assignee = _auto_assignee(step["lane"], employees)
        due = ""
        if base_date is not None and install_idx is not None:
            offset = (pos - install_idx) * TASK_DUE_SPACING_DAYS
            due = (base_date + timedelta(days=offset)).strftime("%Y-%m-%d")
        else:
            default_seq += 1
            due = (chain_start + timedelta(
                days=default_seq * TASK_DEFAULT_LEAD_DAYS)).strftime("%Y-%m-%d")
        db.execute(
            "INSERT INTO job_tasks"
            " (job_id, employee_id, title, status, due_date, notes, sort_order,"
            "  pipeline_status, updated_at)"
            " VALUES (?, ?, ?, 'To do', ?, ?, ?, ?, strftime('%Y-%m-%d %H:%M:%f', 'now'))",
            (job_id, assignee, title, due, note, base + added,
             step.get("status", "")))
        existing.add(title.lower())
        added += 1
        if assignee:
            assigned += 1
        if due:
            scheduled += 1
    return added, assigned, scheduled


@app.route("/jobs/<int:job_id>/tasks/generate", methods=["POST"])
def generate_tasks(job_id):
    """Pre-load a job's task list from its process: run the same per-job
    BPMN the Process chart uses, then turn each workflow step (skipping
    start/end events and gateways) into a To-do task, in order. Each step
    auto-assigns to the employee whose role matches its lane (when
    unambiguous), and — if a target install date is given — gets a due date
    spaced around the Site Installation step. Skips steps already on the
    list, so it's safe to re-run after the job's fields change."""
    job = fetch_job(job_id)
    db = get_db()
    raw_install = request.form.get("install_date", "").strip()
    added, assigned, scheduled = _generate_job_tasks(db, job, raw_install)
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
        flash(f"Added {added} task{'s' if added != 1 else ''} from the job's process{detail}.")
    else:
        flash("No new tasks — the process steps are already on the list.")
    return redirect(url_for("job_detail", job_id=job_id, _anchor="tasks"))


def _redefault_next_due(db, job_id, completed_date):
    """A step just became Done — default the next still-open step's deadline
    to TASK_DEFAULT_LEAD_DAYS (7) days after that completion. "Next" is the
    lowest sort_order among the job's not-Done tasks, i.e. the step that just
    became the one to work on. Must be called after the completed task's
    status is written so it's excluded here. Rough default; hand-editable."""
    if not completed_date:
        return
    try:
        base = datetime.strptime(completed_date, "%Y-%m-%d").date()
    except ValueError:
        return
    nxt = db.execute(
        "SELECT id FROM job_tasks WHERE job_id = ? AND status != 'Done'"
        " ORDER BY sort_order, id LIMIT 1", (job_id,)).fetchone()
    if nxt is None:
        return
    due = (base + timedelta(days=TASK_DEFAULT_LEAD_DAYS)).strftime("%Y-%m-%d")
    db.execute(
        "UPDATE job_tasks SET due_date = ?,"
        " updated_at = strftime('%Y-%m-%d %H:%M:%f', 'now') WHERE id = ?",
        (due, nxt["id"]))


@app.route("/jobs/<int:job_id>/tasks/<int:task_id>/status", methods=["POST"])
def set_task_status(job_id, task_id):
    status = request.form.get("status", "")
    if status in TASK_STATUSES:
        db = get_db()
        # Stamp (or clear) the completion date as the task enters/leaves Done.
        completed = datetime.now().strftime("%Y-%m-%d") if status == "Done" else ""
        db.execute(
            "UPDATE job_tasks SET status = ?, completed_at = ?,"
            " updated_at = strftime('%Y-%m-%d %H:%M:%f', 'now') WHERE id = ? AND job_id = ?",
            (status, completed, task_id, job_id))
        # Completing a step re-anchors the next open step's default deadline.
        if status == "Done":
            _redefault_next_due(db, job_id, completed)
        db.commit()
    # A dashboard passes ?next= so the status change returns there; only
    # same-site relative paths are honored.
    nxt = request.form.get("next", "")
    if nxt.startswith("/") and not nxt.startswith("//"):
        return redirect(nxt)
    return redirect(url_for("job_detail", job_id=job_id, _anchor="tasks"))


@app.route("/jobs/<int:job_id>/tasks/<int:task_id>/assign", methods=["POST"])
def set_task_assignee(job_id, task_id):
    db = get_db()
    db.execute("UPDATE job_tasks SET employee_id = ?, updated_at = strftime('%Y-%m-%d %H:%M:%f', 'now')"
               " WHERE id = ? AND job_id = ?",
               (_task_assignee(job_id), task_id, job_id))
    db.commit()
    return redirect(url_for("job_detail", job_id=job_id, _anchor="tasks"))


@app.route("/jobs/<int:job_id>/tasks/<int:task_id>/due", methods=["POST"])
def set_task_due(job_id, task_id):
    db = get_db()
    db.execute("UPDATE job_tasks SET due_date = ?, updated_at = strftime('%Y-%m-%d %H:%M:%f', 'now')"
               " WHERE id = ? AND job_id = ?",
               (request.form.get("due_date", "").strip(), task_id, job_id))
    db.commit()
    return redirect(url_for("job_detail", job_id=job_id, _anchor="tasks"))


@app.route("/jobs/<int:job_id>/tasks/<int:task_id>/edit", methods=["POST"])
def edit_task(job_id, task_id):
    title = request.form.get("title", "").strip()
    if not title:
        flash("A task needs a title.", "error")
        return redirect(url_for("job_detail", job_id=job_id, _anchor="tasks"))
    db = get_db()
    db.execute("UPDATE job_tasks SET title = ?, notes = ?,"
               " updated_at = strftime('%Y-%m-%d %H:%M:%f', 'now') WHERE id = ? AND job_id = ?",
               (title, request.form.get("notes", "").strip(), task_id, job_id))
    db.commit()
    return redirect(url_for("job_detail", job_id=job_id, _anchor="tasks"))


@app.route("/jobs/<int:job_id>/tasks/<int:task_id>/delete", methods=["POST"])
@delete_required
def delete_task(job_id, task_id):
    ok, msg = trash_item("task", task_id)
    flash(msg, "" if ok else "error")
    return redirect(url_for("job_detail", job_id=job_id, _anchor="tasks"))


@app.route("/tasks")
def tasks_dashboard():
    """Cross-job task board: every task in one place, filterable to one
    person (or the unassigned pile) and to open vs. all. The home for
    'what am I supposed to be doing' across every job."""
    db = get_db()
    employees = db.execute("SELECT id, name FROM employees ORDER BY name").fetchall()
    ensure_lead_followups(db)
    followups = due_followups(db)
    who = request.args.get("employee", "")   # "" (all) / "unassigned" / an id
    show = request.args.get("show", "open")  # open / all
    sql = ("SELECT t.*, j.job_name, j.id AS job_id, c.name AS client_name,"
           " e.name AS assignee_name FROM job_tasks t"
           " JOIN jobs j ON j.id = t.job_id"
           " JOIN clients c ON c.id = j.client_id"
           " LEFT JOIN employees e ON e.id = t.employee_id"
           " WHERE j.status != 'Lost'")   # Piece 30.2: hide cancelled-job tasks
    params = []
    if who == "unassigned":
        sql += " AND t.employee_id IS NULL"
    elif who.isdigit():
        sql += " AND t.employee_id = ?"
        params.append(int(who))
    if show == "open":
        sql += " AND t.status != 'Done'"
    # Open first, then soonest due (blank dues last), then by job.
    sql += (" ORDER BY (t.status = 'Done'), (t.due_date = ''), t.due_date,"
            " j.id, t.sort_order, t.id")
    tasks = db.execute(sql, params).fetchall()
    counts = {}
    for t in tasks:
        counts[t["status"]] = counts.get(t["status"], 0) + 1
    today = datetime.now().strftime("%Y-%m-%d")
    overdue = sum(1 for t in tasks
                  if t["due_date"] and t["due_date"] < today and t["status"] != "Done")
    # Piece 26.3: group the flat list under each job so the board reads as
    # "everything this job needs" at a glance. Tasks arrive already sorted
    # (open first, soonest due), so each group keeps that order.
    grouped = {}
    for t in tasks:
        g = grouped.get(t["job_id"])
        if g is None:
            g = grouped[t["job_id"]] = {
                "job_id": t["job_id"], "job_name": t["job_name"],
                "client_name": t["client_name"], "tasks": [],
                "open": 0, "overdue": 0}
        g["tasks"].append(t)
        if t["status"] != "Done":
            g["open"] += 1
            if t["due_date"] and t["due_date"] < today:
                g["overdue"] += 1

    def _group_key(g):
        open_dues = [t["due_date"] for t in g["tasks"]
                     if t["status"] != "Done" and t["due_date"]]
        soonest = min(open_dues) if open_dues else "9999-99-99"
        # Jobs with overdue work first, then by soonest due date, then name.
        return (0 if g["overdue"] else 1, soonest, (g["job_name"] or "").lower())
    groups = sorted(grouped.values(), key=_group_key)
    return render_template(
        "tasks.html", groups=groups, task_total=len(tasks), employees=employees,
        who=who, show=show, task_statuses=TASK_STATUSES, counts=counts,
        overdue=overdue, today=today, followups=followups)


# ------------------------------------------- Piece 14: Work Bag (offline sync)
def _my_tasks_rows(db, employee_id):
    # Piece 21.6: also surface pipeline_status + install_date so the Work Bag
    # can group tasks by job (with the install date) and show only field work.
    return db.execute(
        "SELECT t.id, t.title, t.status, t.due_date, t.notes, t.updated_at,"
        " t.pipeline_status, j.id AS job_id, j.job_name, j.install_date,"
        " c.name AS client_name"
        " FROM job_tasks t JOIN jobs j ON j.id = t.job_id"
        " JOIN clients c ON c.id = j.client_id"
        " WHERE t.employee_id = ? AND j.status != 'Lost'"   # Piece 30.2
        " ORDER BY (t.status = 'Done'), (j.install_date = ''), j.install_date,"
        " j.id, (t.due_date = ''), t.due_date, t.id",
        (employee_id,)).fetchall()


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


@app.route("/work-bag")
def work_bag():
    """Piece 27.7: the Work Bag landing — just the jobs in the worker's bag.
    Tapping a job opens its own page (work_bag_job) with that job's tasks, hours,
    receipts and notes. The job list is rendered in the browser from the same
    cached /api/my-tasks data, so the landing keeps working offline."""
    return render_template("work_bag.html")


@app.route("/work-bag/job/<int:job_id>")
def work_bag_job(job_id):
    """A single job's Work Bag page: its field tasks plus hours / receipt / note
    capture scoped to this job. Task data still flows through the /api endpoints
    (offline-capable); the capture forms and recent lists are pinned to the job."""
    db = get_db()
    job = fetch_job(job_id)
    user = current_user()
    pay_types = payroll_pay_types(db)
    client = db.execute("SELECT name FROM clients WHERE id = ?",
                        (job["client_id"],)).fetchone()
    my_entries = my_notes = my_receipts = []
    if user is not None:
        my_entries = db.execute(
            "SELECT te.*, pt.name AS type_name FROM time_entries te"
            " LEFT JOIN pay_types pt ON pt.id = te.pay_type_id"
            " WHERE te.employee_id = ? AND te.job_id = ?"
            " ORDER BY te.work_date DESC, te.id DESC LIMIT 12",
            (user["id"], job_id)).fetchall()
        my_notes = db.execute(
            "SELECT n.* FROM job_notes n WHERE n.author = ? AND n.job_id = ?"
            " ORDER BY n.id DESC LIMIT 12", (user["name"], job_id)).fetchall()
        my_receipts = db.execute(
            "SELECT t.*, f.id AS file_id FROM job_transactions t"
            " LEFT JOIN job_files f ON f.txn_id = t.id"
            " WHERE t.doc_type = 'Receipt' AND t.created_by = ? AND t.job_id = ?"
            " ORDER BY t.id DESC LIMIT 10", (user["name"], job_id)).fetchall()
    return render_template(
        "work_bag_job.html", job=job,
        client_name=client["name"] if client else "",
        task_statuses=TASK_STATUSES, today=datetime.now().strftime("%Y-%m-%d"),
        pay_types=pay_types,
        pay_types_js=[{"id": t["id"], "name": t["name"]} for t in pay_types],
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
        " WHERE s.employee_id = ? AND s.status = 'Pending'", (user["id"],)).fetchall()
    subs = db.execute(
        "SELECT id, work_date, reported_hours, approved_hours, status, submitted_at,"
        " reviewed_at FROM field_submissions WHERE employee_id = ?"
        " ORDER BY id DESC LIMIT 8", (user["id"],)).fetchall()
    # Piece 21.7: attach any field photos already on file for photo-steps, plus
    # the link to each photo step's capture page.
    photo_task_ids = [r["id"] for r in rows if _is_photo_step(r["title"])]
    photos_by_task = {}
    if photo_task_ids:
        ph = ", ".join("?" * len(photo_task_ids))
        for f in db.execute(
                f"SELECT id, job_id, task_id FROM job_files WHERE rule_label = ?"
                f" AND task_id IN ({ph}) ORDER BY id DESC",
                (FIELD_PHOTO_LABEL, *[str(t) for t in photo_task_ids])).fetchall():
            photos_by_task.setdefault(str(f["task_id"]), []).append(
                {"id": f["id"],
                 "url": url_for("view_file", job_id=f["job_id"], file_id=f["id"])})
    tasks_out = []
    for r in rows:
        d = dict(r)
        d["is_photo_step"] = _is_photo_step(r["title"])
        d["photos_url"] = url_for("task_photos", task_id=r["id"])
        d["photos"] = photos_by_task.get(str(r["id"]), [])
        tasks_out.append(d)
    # Piece 22.0: the materials list for each job on the board, so installers can
    # load the truck before they leave. Keyed by job so the Work Bag can show it
    # under each job's banner.
    materials_by_job = {}
    job_ids = {r["job_id"] for r in rows}
    if job_ids:
        ph = ", ".join("?" * len(job_ids))
        for m in db.execute(
                f"SELECT job_id, item, quantity, unit, status FROM job_materials"
                f" WHERE job_id IN ({ph}) ORDER BY id", tuple(job_ids)).fetchall():
            materials_by_job.setdefault(str(m["job_id"]), []).append({
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


def _validated_segments(db, segs, pt_names=None):
    """Piece 27.9/28.0: clean a list of {pay_type_id, hours} time segments —
    keep only active pay types with positive hours, and attach the pay-type name
    for display. Shared by the Work Bag submit API and the photo-step completion."""
    if pt_names is None:
        pt_names = {t["id"]: t["name"] for t in payroll_pay_types(db)}
    out = []
    for seg in (segs or []):
        try:
            pid = int(seg.get("pay_type_id"))
        except (TypeError, ValueError):
            continue
        hrs = _to_float(seg.get("hours"))
        if pid not in pt_names or not hrs or hrs <= 0:
            continue
        out.append({"pay_type_id": pid, "pay_type_name": pt_names[pid],
                    "hours": round(hrs, 2)})
    return out


@app.route("/api/work-bag/submit", methods=["POST"])
def api_work_bag_submit():
    """Save the worker's completed field work as a PENDING submission — a
    copy in the database that does NOT change the authoritative task data or
    count as hours until a manager approves it."""
    user = current_user()
    if user is None:
        return jsonify({"error": "not signed in"}), 401
    payload = request.get_json(silent=True) or {}
    db = get_db()
    # Piece 27.9: each change is a completed (or blocked) task, optionally with
    # the time it took split by pay type. Validate segments against active pay
    # types; store them on the item so approval can post payroll entries.
    pt_names = {t["id"]: t["name"] for t in payroll_pay_types(db)}
    valid = []
    total_hours = 0.0
    for ch in payload.get("changes", []) or []:
        row = db.execute(
            "SELECT * FROM job_tasks WHERE id = ? AND employee_id = ?",
            (ch.get("id"), user["id"])).fetchone()
        if row is None:
            continue
        status = ch.get("status", row["status"])
        if status not in TASK_STATUSES:
            status = row["status"]
        segments = _validated_segments(db, ch.get("segments"), pt_names)
        total_hours += sum(s["hours"] for s in segments)
        work_date = (ch.get("work_date") or payload.get("work_date") or "").strip()
        valid.append((row["id"], row["title"], status,
                      ch.get("notes", row["notes"]), ch.get("base_updated_at") or "",
                      json.dumps(segments), work_date))
    reported_hours = _to_float(payload.get("reported_hours"))
    if reported_hours is None and total_hours > 0:
        reported_hours = round(total_hours, 2)
    if not valid and reported_hours is None:
        return jsonify({"error": "nothing to submit"}), 400
    cur = db.execute(
        "INSERT INTO field_submissions (employee_id, work_date, reported_hours, note)"
        " VALUES (?, ?, ?, ?)",
        (user["id"], (payload.get("work_date") or "").strip(), reported_hours,
         (payload.get("note") or "").strip()))
    sub_id = cur.lastrowid
    for task_id, title, status, notes, base, hours_json, work_date in valid:
        db.execute(
            "INSERT INTO field_submission_items"
            " (submission_id, task_id, task_title, new_status, new_notes,"
            "  base_updated_at, hours_json, work_date)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (sub_id, task_id, title, status, notes, base, hours_json, work_date))
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
        " JOIN employees e ON e.id = s.employee_id"
        f" {where} ORDER BY (s.status='Pending') DESC, s.id DESC LIMIT 100"
    ).fetchall()
    items_by_sub = {}
    ids = [s["id"] for s in subs]
    if ids:
        q = ("SELECT * FROM field_submission_items WHERE submission_id IN (%s)"
             " ORDER BY id" % ",".join("?" * len(ids)))
        for it in db.execute(q, ids).fetchall():
            d = dict(it)
            try:
                d["segments"] = json.loads(it["hours_json"]) if ("hours_json" in it.keys()
                                and it["hours_json"]) else []
            except (ValueError, TypeError):
                d["segments"] = []
            items_by_sub.setdefault(it["submission_id"], []).append(d)
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
        row = db.execute("SELECT * FROM job_tasks WHERE id = ?",
                         (it["task_id"],)).fetchone()
        if row is None:
            continue
        status = it["new_status"] if it["new_status"] in TASK_STATUSES else row["status"]
        completed = datetime.now().strftime("%Y-%m-%d") if status == "Done" else ""
        db.execute(
            "UPDATE job_tasks SET status = ?, notes = ?, completed_at = ?,"
            " updated_at = strftime('%Y-%m-%d %H:%M:%f', 'now') WHERE id = ?",
            (status, it["new_notes"], completed, it["task_id"]))
        # Field-approved completions re-anchor the next open step's deadline too.
        if status == "Done" and row["status"] != "Done":
            _redefault_next_due(db, row["job_id"], completed)
        # Piece 27.9: post the task's time (split by pay type) as PENDING payroll
        # entries for this job — Finance approves them on the payroll page. Two
        # sign-offs: the supervisor confirms the work here, Finance approves pay.
        segments = []
        if "hours_json" in it.keys() and it["hours_json"]:
            try:
                segments = json.loads(it["hours_json"])
            except (ValueError, TypeError):
                segments = []
        wd = (it["work_date"] if "work_date" in it.keys() and it["work_date"]
              else sub["work_date"] or datetime.now().strftime("%Y-%m-%d"))
        for seg in segments:
            hrs = _to_float(seg.get("hours"))
            pid = seg.get("pay_type_id")
            if not hrs or hrs <= 0 or pid is None:
                continue
            db.execute(
                "INSERT INTO time_entries (employee_id, work_date, job_id,"
                " pay_type_id, hours, note, status, created_by)"
                " VALUES (?, ?, ?, ?, ?, ?, 'Pending', ?)",
                (sub["employee_id"], wd, row["job_id"], pid, round(hrs, 2),
                 f"Field: {it['task_title']}", who["name"] if who else ""))
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
def job_upload_dir(job_id):
    directory = UPLOADS_DIR / f"job_{job_id}"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


@app.route("/jobs/<int:job_id>/files/upload", methods=["POST"])
def upload_file(job_id):
    fetch_job(job_id)
    upload = request.files.get("document")
    if upload is None or not upload.filename:
        flash("Choose a file to upload.", "error")
        return redirect(url_for("job_detail", job_id=job_id, _anchor="documents"))
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
        return redirect(url_for("job_detail", job_id=job_id, _anchor="documents"))
    # Piece 25.4: auto-rename to Client_Job_Slot_Date.ext for recordkeeping.
    who = db.execute(
        "SELECT j.job_name, c.name AS client_name FROM jobs j"
        " JOIN clients c ON c.id = j.client_id WHERE j.id = ?", (job_id,)).fetchone()
    friendly = friendly_filename(
        [who["client_name"] if who else "", who["job_name"] if who else "",
         label or "Document"], extension,
        taken=_taken_names(db, "job_files", "original_name", "job_id", job_id))
    stored = f"{uuid.uuid4().hex[:8]}_{secure_filename(friendly)}"
    upload.save(job_upload_dir(job_id) / stored)
    db.execute(
        "INSERT INTO job_files (job_id, rule_label, stored_name, original_name)"
        " VALUES (?, ?, ?, ?)",
        (job_id, label, stored, friendly),
    )
    db.commit()
    flash(f"Uploaded: {friendly}")
    return redirect(url_for("job_detail", job_id=job_id, _anchor="documents"))


@app.route("/jobs/<int:job_id>/files/<int:file_id>/download")
def download_file(job_id, file_id):
    record = get_db().execute(
        "SELECT * FROM job_files WHERE id = ? AND job_id = ?",
        (file_id, job_id),
    ).fetchone()
    if record is None:
        abort(404)
    return send_from_directory(
        job_upload_dir(job_id), record["stored_name"], as_attachment=True,
        download_name=record["original_name"],
    )


@app.route("/jobs/<int:job_id>/files/<int:file_id>/delete", methods=["POST"])
@delete_required
def delete_file(job_id, file_id):
    ok, msg = trash_item("job_file", file_id)
    flash(msg, "" if ok else "error")
    return redirect(url_for("job_detail", job_id=job_id, _anchor="documents"))


@app.route("/jobs/<int:job_id>/files/<int:file_id>/view")
def view_file(job_id, file_id):
    """Serve a stored file inline (not as an attachment) — used for photo
    thumbnails and lightbox previews."""
    record = get_db().execute(
        "SELECT * FROM job_files WHERE id = ? AND job_id = ?",
        (file_id, job_id)).fetchone()
    if record is None:
        abort(404)
    return send_from_directory(
        job_upload_dir(job_id), record["stored_name"], as_attachment=False,
        download_name=record["original_name"])


@app.route("/work-bag/tasks/<int:task_id>/photos", methods=["GET", "POST"])
def task_photos(task_id):
    """Piece 21.7: the Work Bag's photo page for a single task — take/upload
    job photos from a phone and see the ones already on file. Photos are stored
    as job_files (tagged FIELD_PHOTO_LABEL + this task) so they also surface on
    the job record."""
    db = get_db()
    task = db.execute(
        "SELECT t.id, t.title, j.id AS job_id, j.job_name, j.install_date,"
        " c.name AS client_name FROM job_tasks t JOIN jobs j ON j.id = t.job_id"
        " JOIN clients c ON c.id = j.client_id WHERE t.id = ?", (task_id,)).fetchone()
    if task is None:
        abort(404)
    job_id = task["job_id"]
    if request.method == "POST":
        saved = 0
        # Piece 25.4: auto-rename photos to Client_Job_Task_Date.ext (a numeric
        # suffix keeps a burst of shots on one day distinct).
        taken = _taken_names(db, "job_files", "original_name", "job_id", job_id)
        for up in request.files.getlist("photos"):
            if not up or not up.filename:
                continue
            ext = up.filename.rsplit(".", 1)[-1].lower() if "." in up.filename else ""
            if ext not in PHOTO_EXTENSIONS:
                continue
            friendly = friendly_filename(
                [task["client_name"], task["job_name"], task["title"] or "Photo"],
                ext, taken=taken)
            taken.add(friendly)
            stored = f"{uuid.uuid4().hex[:8]}_{secure_filename(friendly)}"
            up.save(job_upload_dir(job_id) / stored)
            db.execute(
                "INSERT INTO job_files"
                " (job_id, rule_label, stored_name, original_name, task_id)"
                " VALUES (?, ?, ?, ?, ?)",
                (job_id, FIELD_PHOTO_LABEL, stored, friendly, str(task_id)))
            saved += 1
        db.commit()
        flash(f"Added {saved} photo(s)." if saved
              else "No photos added — choose image files.", "" if saved else "error")
        return redirect(url_for("task_photos", task_id=task_id))
    photos = db.execute(
        "SELECT * FROM job_files WHERE job_id = ? AND rule_label = ? AND task_id = ?"
        " ORDER BY id DESC", (job_id, FIELD_PHOTO_LABEL, str(task_id))).fetchall()
    pay_types = payroll_pay_types(db)
    return render_template(
        "work_bag_photos.html", task=task, photos=photos,
        today=datetime.now().strftime("%Y-%m-%d"),
        pay_types_js=[{"id": t["id"], "name": t["name"]} for t in pay_types])


@app.route("/work-bag/tasks/<int:task_id>/complete", methods=["POST"])
def complete_photo_task(task_id):
    """Piece 28.0: finish a photo step from its dedicated screen — record the
    photos already uploaded plus (optionally) the time it took, submit the task
    for the supervisor's approval, and return to the job's Work Bag page."""
    user = current_user()
    if user is None:
        abort(403)
    db = get_db()
    task = db.execute("SELECT * FROM job_tasks WHERE id = ? AND employee_id = ?",
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
            "SELECT COUNT(*) AS c FROM job_files WHERE task_id = ? AND rule_label = ?",
            (str(task_id), FIELD_PHOTO_LABEL)).fetchone()["c"]
        if not n:
            flash("Take at least one photo before submitting this step as done.", "error")
            return redirect(url_for("task_photos", task_id=task_id))
    if status == "Blocked" and not notes:
        flash("Add a note about what's blocking it.", "error")
        return redirect(url_for("task_photos", task_id=task_id))
    try:
        raw_segs = json.loads(request.form.get("segments") or "[]")
    except (ValueError, TypeError):
        raw_segs = []
    segments = _validated_segments(db, raw_segs) if status == "Done" else []
    total = sum(s["hours"] for s in segments)
    cur = db.execute(
        "INSERT INTO field_submissions (employee_id, work_date, reported_hours, note)"
        " VALUES (?, ?, ?, ?)",
        (user["id"], work_date, round(total, 2) if total else None, ""))
    sub_id = cur.lastrowid
    db.execute(
        "INSERT INTO field_submission_items"
        " (submission_id, task_id, task_title, new_status, new_notes,"
        "  base_updated_at, hours_json, work_date)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (sub_id, task_id, task["title"], status, notes,
         task["updated_at"] or "", json.dumps(segments), work_date))
    db.commit()
    flash(f"“{task['title']}” submitted for approval."
          if status == "Done" else f"“{task['title']}” flagged as blocked for the office.")
    return redirect(url_for("work_bag_job", job_id=task["job_id"]))


@app.route("/work-bag/photos/<int:file_id>/delete", methods=["POST"])
def delete_task_photo(file_id):
    """Remove a field photo the crew took (scoped to FIELD_PHOTO_LABEL, so this
    can't touch requirement documents — those stay GM-only via delete_file)."""
    db = get_db()
    rec = db.execute("SELECT * FROM job_files WHERE id = ? AND rule_label = ?",
                     (file_id, FIELD_PHOTO_LABEL)).fetchone()
    if rec is None:
        abort(404)
    try:
        (job_upload_dir(rec["job_id"]) / rec["stored_name"]).unlink()
    except OSError:
        pass
    db.execute("DELETE FROM job_files WHERE id = ?", (file_id,))
    db.commit()
    flash("Photo removed.")
    back = int(rec["task_id"]) if str(rec["task_id"]).isdigit() else 0
    return redirect(url_for("task_photos", task_id=back) if back
                    else url_for("work_bag"))


@app.route("/jobs/<int:job_id>/report")
def job_report(job_id):
    """Download a plain-text checklist report of the job's selections and
    every license, permit, and compliance item they resolve to."""
    job = fetch_job(job_id)
    rules = get_db().execute("SELECT * FROM resource_rules").fetchall()
    groups = group_rules(match_rules(job, rules))

    lines = [
        f"JOB REPORT — {job['job_name'] or 'Job #' + str(job['id'])}",
        f"Client: {job['client_name']}",
        f"Created: {job['created_at']}   Report generated: {datetime.now():%Y-%m-%d %H:%M}",
        "=" * 64,
        "",
        "JOB DETAILS",
        "-" * 64,
    ]
    for field in JOB_FIELDS:
        value = str(job[field] or "").strip()
        if value:
            lines.append(f"{JOB_FIELD_LABELS[field] + ':':34}{value}")
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
        "SELECT * FROM job_materials WHERE job_id = ? ORDER BY id", (job_id,)
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
        "SELECT * FROM job_files WHERE job_id = ? ORDER BY id", (job_id,)
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
                 f"attachment; filename=job_{job_id}_report.txt"},
    )


@app.route("/jobs/<int:job_id>/bpmn")
def job_bpmn(job_id):
    """Download this job's process as a BPMN 2.0 file: the master
    pipeline instantiated with the job's resolved permits and variables."""
    job = fetch_job(job_id)
    rules = get_db().execute("SELECT * FROM resource_rules").fetchall()
    materials, files, materials_note, docs_note = job_progress_extras(job_id)
    xml, _details = build_job_bpmn(job, match_rules(job, rules),
                                   materials_note, docs_note)
    return Response(
        xml, mimetype="application/xml",
        headers={"Content-Disposition":
                 f"attachment; filename=job_{job_id}_process.bpmn"},
    )


def job_progress_extras(job_id):
    """Materials and documents for a job, plus one-line summaries used
    as annotations in the exported BPMN."""
    db = get_db()
    materials = db.execute(
        "SELECT * FROM job_materials WHERE job_id = ? ORDER BY id", (job_id,)
    ).fetchall()
    files = db.execute(
        "SELECT * FROM job_files WHERE job_id = ? ORDER BY id", (job_id,)
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


@app.route("/jobs/<int:job_id>/bpmn/view")
def job_bpmn_view(job_id):
    job = fetch_job(job_id)
    rules = get_db().execute("SELECT * FROM resource_rules").fetchall()
    materials, files, materials_note, docs_note = job_progress_extras(job_id)
    _xml, details = build_job_bpmn(job, match_rules(job, rules),
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
        "bpmn_view.html", job=job, steps=steps,
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
    # When reached from a job page, offer a way back to that job.
    from_job = None
    from_job_id = request.args.get("from_job", type=int)
    if from_job_id:
        from_job = db.execute(
            "SELECT id, job_name FROM jobs WHERE id = ?", (from_job_id,)
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
        job_fields=[f for f in JOB_FIELDS if f != "job_name"],
        field_labels=JOB_FIELD_LABELS, categories=RULE_CATEGORIES,
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
    if field_name not in JOB_FIELDS or not field_value or not label:
        flash("A rule needs a job field, a value to match, and a label.", "error")
        return redirect(url_for("rules_page", from_job=from_job))
    if field_name2 and (field_name2 not in JOB_FIELDS or not field_value2):
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
    if field_name not in JOB_FIELDS or not field_value or not label:
        flash("A rule needs a job field, a value to match, and a label.", "error")
        return redirect(url_for("rules_page", from_job=from_job, edit=rule_id))
    if field_name2 and (field_name2 not in JOB_FIELDS or not field_value2):
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
    """Read-only, browsable view of every rule, filterable by job type
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
            # job type (its product row or one of its variant fields).
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
        field_labels=JOB_FIELD_LABELS,
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


# ---------------------------------------------------------------- employees
def read_employee_form():
    """Validate and normalize a submitted employee form (create or edit).
    Names come in as first/last (+ optional nickname) and compose into `name`;
    roles come in as checkboxes plus an optional free-typed 'other' field."""
    first = request.form.get("first_name", "").strip()
    last = request.form.get("last_name", "").strip()
    values = {
        "first_name": first, "last_name": last,
        "nickname": request.form.get("nickname", "").strip(),
        "name": (first + " " + last).strip(),
        "schedule": request.form.get("schedule", "").strip(),
    }
    selected = request.form.getlist("roles")
    roles = [r for r in EMPLOYEE_ROLES if r in selected]
    for extra in request.form.get("roles_other", "").split(","):
        extra = extra.strip()
        if extra and extra not in roles:
            roles.append(extra)
    values["roles"] = ", ".join(roles)
    errors = []
    if not first:
        errors.append("First name is required.")
    return values, errors


def render_employee_form(values, employee_id=None, username="", access_level="",
                         duplicate_warning=None, is_supervisor="",
                         onboarding_owner_id=None):
    """Render the shared new/edit form, splitting stored roles back into
    the known checkbox roles and any free-typed extras. Legacy fallback: an
    existing employee with no first/last gets its `name` split into the fields."""
    values = dict(values)
    if not values.get("first_name") and values.get("name"):
        parts = values["name"].split(" ", 1)
        values["first_name"] = parts[0]
        values["last_name"] = parts[1] if len(parts) > 1 else ""
    stored = [ROLE_RENAMES.get(r.strip(), r.strip())
              for r in (values.get("roles") or "").split(",") if r.strip()]
    selected = [r for r in stored if r in EMPLOYEE_ROLES]
    roles_other = ", ".join(r for r in stored if r not in EMPLOYEE_ROLES)
    # Piece 31.2: onboarding is initiated inside the New-employee form. Show the
    # checklist preview + who's accountable only when creating (edit keeps it on
    # the profile). Default owner = the GM.
    db = get_db()
    onboarding_preview, owner_candidates = [], []
    if employee_id is None:
        onboarding_preview = db.execute(
            "SELECT title, description, category FROM onboarding_steps"
            " WHERE active = '1' ORDER BY sort_order, id").fetchall()
        owner_candidates = onboarding_owner_candidates(db)
        if onboarding_owner_id is None:
            onboarding_owner_id = default_onboarding_owner_id(db)
    return render_template(
        "employee_form.html", values=values, roles=EMPLOYEE_ROLES,
        role_tree=ROLE_TREE,
        selected=selected, roles_other=roles_other, employee_id=employee_id,
        username=username, access_level=access_level, access_levels=ACCESS_LEVELS,
        duplicate_warning=duplicate_warning,
        supervisor_checked=(str(is_supervisor or "") == "1"),
        onboarding_preview=onboarding_preview,
        onboarding_owner_candidates=owner_candidates,
        onboarding_owner_id=str(onboarding_owner_id or ""),
    )


@app.route("/employees")
def employees_page():
    db = get_db()
    employees = db.execute("SELECT * FROM employees ORDER BY name").fetchall()
    # Per-employee credential tally, with expiry warnings, for the list.
    summary = {}
    for c in db.execute(
            "SELECT employee_id, expires FROM employee_credentials").fetchall():
        s = summary.setdefault(c["employee_id"],
                               {"count": 0, "expired": 0, "soon": 0})
        s["count"] += 1
        state, _ = credential_status(c["expires"])
        if state == "expired":
            s["expired"] += 1
        elif state == "soon":
            s["soon"] += 1
    return render_template("employees.html", employees=employees, summary=summary)


@app.route("/accounts")
@admin_required
def accounts_page():
    """Admin roster of who can sign in and at what level, the employees
    who don't have a login yet, and any pending password-change requests."""
    db = get_db()
    employees = db.execute(
        "SELECT id, name, username, access_level, COALESCE(password_hash,'') AS pw"
        " FROM employees ORDER BY name").fetchall()
    with_login = [e for e in employees if (e["username"] or "")]
    without_login = [e for e in employees if not (e["username"] or "")]
    admin_count = sum(1 for e in with_login if e["access_level"] == "Admin")
    pending = db.execute(
        "SELECT pr.*, e.name AS emp_name, e.username FROM password_requests pr"
        " JOIN employees e ON e.id = pr.employee_id"
        " WHERE pr.status = 'Pending' ORDER BY pr.requested_at").fetchall()
    # Piece 19.2: flag usernames that collide case-insensitively — now that
    # login ignores case, two such accounts would be ambiguous.
    by_lower = {}
    for e in with_login:
        by_lower.setdefault((e["username"] or "").lower(), []).append(e)
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
        db.execute("UPDATE employees SET password_hash = ? WHERE id = ?",
                   (req["new_hash"], req["employee_id"]))
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


def _apply_employee_auth(db, employee_id):
    """Set or clear this employee's login from the form's Login & access
    fields. A blank/None level or blank username removes the login; the
    password hash is rewritten only when a new password is supplied, so
    editing other fields never disturbs an existing password. Guards against
    leaving accounts configured with no admin (which would lock everyone out
    of admin functions)."""
    level = request.form.get("access_level", "").strip()
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    setting_login = level in ACCESS_LEVELS and bool(username)

    if setting_login:
        # Case-insensitive uniqueness so "Trish" and "trish" can't both exist.
        clash = db.execute(
            "SELECT id FROM employees WHERE LOWER(username) = LOWER(?) AND id != ?",
            (username, employee_id)).fetchone()
        if clash:
            flash(f"Username “{username}” is already taken — login unchanged.", "error")
            return

    existing_hash = db.execute(
        "SELECT COALESCE(password_hash,'') FROM employees WHERE id = ?",
        (employee_id,)).fetchone()[0]
    this_usable = setting_login and (bool(password) or bool(existing_hash))
    this_admin = this_usable and level == "Admin"
    other_accounts = db.execute(
        "SELECT COUNT(*) FROM employees WHERE id != ?"
        " AND COALESCE(username,'') != '' AND COALESCE(password_hash,'') != ''",
        (employee_id,)).fetchone()[0]
    other_admins = db.execute(
        "SELECT COUNT(*) FROM employees WHERE id != ? AND access_level = 'Admin'"
        " AND COALESCE(username,'') != '' AND COALESCE(password_hash,'') != ''",
        (employee_id,)).fetchone()[0]
    total_accounts = other_accounts + (1 if this_usable else 0)
    total_admins = other_admins + (1 if this_admin else 0)
    if total_accounts > 0 and total_admins == 0:
        flash("Keep at least one admin account — or remove every login to go"
              " back to open access. Login unchanged.", "error")
        return

    if setting_login:
        db.execute("UPDATE employees SET username = ?, access_level = ? WHERE id = ?",
                   (username, level, employee_id))
        if password:
            db.execute("UPDATE employees SET password_hash = ? WHERE id = ?",
                       (generate_password_hash(password, method="pbkdf2:sha256"), employee_id))
        elif not existing_hash:
            flash("Login saved — set a password to activate it.", "error")
    else:
        db.execute(
            "UPDATE employees SET username = '', password_hash = '', access_level = ''"
            " WHERE id = ?", (employee_id,))


@app.route("/employees/new", methods=["GET", "POST"])
@admin_required
def new_employee():
    if request.method == "POST":
        values, errors = read_employee_form()
        username = request.form.get("username", "").strip()
        access_level = request.form.get("access_level", "").strip()
        if errors:
            flash(" ".join(errors), "error")
            return render_employee_form(values, username=username,
                                        access_level=access_level), 400
        db = get_db()
        # Guard against accidental duplicates: same composed name already on the
        # roster. Allow it only when the user confirms it's a different person.
        dup = db.execute("SELECT name FROM employees WHERE LOWER(name) = LOWER(?)",
                         (values["name"],)).fetchone()
        if dup and not request.form.get("confirm_duplicate"):
            return render_employee_form(values, username=username,
                                        access_level=access_level,
                                        duplicate_warning=values["name"]), 400
        cur = db.execute(
            f"INSERT INTO employees ({', '.join(EMPLOYEE_FIELDS)})"
            f" VALUES ({', '.join('?' * len(EMPLOYEE_FIELDS))})",
            [values[f] for f in EMPLOYEE_FIELDS],
        )
        _apply_employee_auth(db, cur.lastrowid)
        if is_gm():  # only the GM designates Supervisors (Piece 29.0)
            db.execute("UPDATE employees SET is_supervisor = ? WHERE id = ?",
                       ("1" if request.form.get("is_supervisor") else "",
                        cur.lastrowid))
        # Piece 31.2: put someone on the hook for finishing onboarding. Use the
        # chosen owner if it's a valid GM/Supervisor, else fall back to the GM.
        chosen_owner = request.form.get("onboarding_owner_id", "")
        owner_id, owner_rejected = _resolve_onboarding_owner(db, chosen_owner)
        db.execute("UPDATE employees SET onboarding_owner_id = ? WHERE id = ?",
                   (owner_id, cur.lastrowid))
        db.commit()
        if owner_rejected:
            _flash_owner_override(db, chosen_owner, owner_id)
        if owner_id:
            _, done, total = onboarding_overview(db, cur.lastrowid)
            notify_employees(
                db, [int(owner_id)],
                f"You're responsible for onboarding {values['name']} — "
                f"{total} step{'s' if total != 1 else ''} to complete.",
                link=url_for("employee_detail", employee_id=cur.lastrowid,
                             welcome=1, _anchor="onboarding"),
                kind="onboarding")
            db.commit()
        flash(f"Employee added: {values['name']} — now complete their onboarding.")
        return redirect(url_for("employee_detail", employee_id=cur.lastrowid,
                                welcome=1, _anchor="onboarding"))
    return render_employee_form({})


def _resolve_onboarding_owner(db, raw):
    """Validate a submitted onboarding-owner id: it must be a current GM or
    Supervisor with a login. Returns (owner_id, rejected) — `rejected` is True
    only when a specific person was chosen but doesn't qualify, so callers can
    tell the user their choice wasn't applied. A blank choice (no selection) or
    an already-valid one is not a rejection. Invalid/blank falls back to the
    default owner (the GM)."""
    valid = {str(r["id"]) for r in onboarding_owner_candidates(db)}
    raw = str(raw or "").strip()
    if raw in valid:
        return raw, False
    return default_onboarding_owner_id(db), bool(raw)


def _flash_owner_override(db, chosen_raw, owner_id):
    """Piece 31.2: warn that a submitted onboarding owner was overridden.
    Names both the rejected pick (if we can still find them) and who ended up
    responsible, so the notice is actionable."""
    chosen = db.execute("SELECT name FROM employees WHERE id = ?",
                        (chosen_raw,)).fetchone() if str(chosen_raw).strip() else None
    who = chosen["name"] if chosen else "That person"
    if owner_id:
        landed = db.execute("SELECT name FROM employees WHERE id = ?",
                            (owner_id,)).fetchone()
        landed_name = landed["name"] if landed else "the General Manager"
        flash(f"{who} can't be made responsible for onboarding — only a General "
              f"Manager or a Supervisor can. Responsibility went to {landed_name} "
              "instead; reassign it on the Onboarding tab if that's not right.",
              "error")
    else:
        flash(f"{who} can't be made responsible for onboarding — only a General "
              "Manager or a Supervisor can, and none is set up yet. No one is "
              "assigned; set up a Supervisor or GM, then assign it on the "
              "Onboarding tab.", "error")


@app.route("/employees/<int:employee_id>")
def employee_detail(employee_id):
    db = get_db()
    employee = db.execute(
        "SELECT * FROM employees WHERE id = ?", (employee_id,)
    ).fetchone()
    if employee is None:
        abort(404)
    roles = [r.strip() for r in (employee["roles"] or "").split(",") if r.strip()]
    files = db.execute(
        "SELECT * FROM employee_files WHERE employee_id = ? ORDER BY id",
        (employee_id,)
    ).fetchall()
    documented = {f["credential_name"] for f in files if f["credential_name"]}
    credentials = []
    for c in db.execute(
            "SELECT * FROM employee_credentials WHERE employee_id = ?"
            " ORDER BY name", (employee_id,)).fetchall():
        state, text = credential_status(c["expires"])
        credentials.append({"row": c, "state": state, "status_text": text,
                            "documented": c["name"] in documented})
    # License requirement labels, for the "satisfies requirement" dropdown.
    license_labels = [r["label"] for r in db.execute(
        "SELECT DISTINCT label FROM resource_rules WHERE category = 'License'"
        " ORDER BY label").fetchall()]
    # Piece 10: everything assigned to this person, across all jobs. Open
    # (not-Done) tasks first, then by due date, so what's pending is on top.
    assigned_tasks = db.execute(
        "SELECT t.*, j.job_name, j.id AS job_id, c.name AS client_name"
        " FROM job_tasks t"
        " JOIN jobs j ON j.id = t.job_id"
        " JOIN clients c ON c.id = j.client_id"
        " WHERE t.employee_id = ?"
        " ORDER BY (t.status = 'Done'), (t.due_date = ''), t.due_date, t.id",
        (employee_id,)).fetchall()
    onboarding_rows, onboarding_done, onboarding_total = onboarding_overview(
        db, employee_id)  # Piece 29.2
    # Piece 31.2: who's accountable for finishing this person's onboarding.
    owner_id = str(employee["onboarding_owner_id"]
                   if "onboarding_owner_id" in employee.keys() else "") or ""
    onboarding_owner = None
    if owner_id:
        onboarding_owner = db.execute(
            "SELECT id, name FROM employees WHERE id = ?", (owner_id,)).fetchone()
    # Piece 25.0: in-place edit — ?edit_credential pre-fills the add form.
    edit_credential = None
    if request.args.get("edit_credential", type=int):
        edit_credential = db.execute(
            "SELECT * FROM employee_credentials WHERE id = ? AND employee_id = ?",
            (request.args.get("edit_credential", type=int), employee_id)).fetchone()
    return render_template(
        "employee_detail.html", employee=employee, roles=roles,
        credentials=credentials, files=files, license_labels=license_labels,
        cred_names=[c["row"]["name"] for c in credentials],
        assigned_tasks=assigned_tasks, task_statuses=TASK_STATUSES,
        edit_credential=edit_credential,
        today=datetime.now().strftime("%Y-%m-%d"),
        access_revoked=is_access_revoked(employee),  # Piece 29.0
        can_revoke_this=can_revoke_target(current_user(), employee),
        onboarding=onboarding_rows, onboarding_done=onboarding_done,  # Piece 29.2
        onboarding_total=onboarding_total,
        onboarding_owner=onboarding_owner,  # Piece 31.2
        onboarding_owner_candidates=onboarding_owner_candidates(db),
        onboarding_owner_id=owner_id,
        onboarding_just_created=bool(request.args.get("welcome")),
    )


@app.route("/employees/<int:employee_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_employee(employee_id):
    db = get_db()
    employee = db.execute(
        "SELECT * FROM employees WHERE id = ?", (employee_id,)
    ).fetchone()
    if employee is None:
        abort(404)
    if request.method == "POST":
        values, errors = read_employee_form()
        if errors:
            flash(" ".join(errors), "error")
            return render_employee_form(values, employee_id=employee_id), 400
        db.execute(
            f"UPDATE employees SET {', '.join(f + ' = ?' for f in EMPLOYEE_FIELDS)}"
            " WHERE id = ?",
            [values[f] for f in EMPLOYEE_FIELDS] + [employee_id],
        )
        _apply_employee_auth(db, employee_id)
        if is_gm():  # only the GM designates Supervisors (Piece 29.0)
            db.execute("UPDATE employees SET is_supervisor = ? WHERE id = ?",
                       ("1" if request.form.get("is_supervisor") else "",
                        employee_id))
        db.commit()
        flash(f"Employee updated: {values['name']}")
        return redirect(url_for("employee_detail", employee_id=employee_id))
    values = {f: employee[f] for f in EMPLOYEE_FIELDS}
    return render_employee_form(
        values, employee_id=employee_id,
        username=employee["username"] or "",
        access_level=employee["access_level"] or "",
        is_supervisor=(employee["is_supervisor"]
                       if "is_supervisor" in employee.keys() else ""))


@app.route("/employees/<int:employee_id>/revoke-access", methods=["POST"])
def revoke_employee_access(employee_id):
    """Piece 29.0: emergency lockout. A GM or Supervisor instantly suspends all
    of this person's access — they're signed out and can't sign back in until
    reinstated. The account, login and data are left intact."""
    db = get_db()
    target = db.execute("SELECT * FROM employees WHERE id = ?",
                        (employee_id,)).fetchone()
    if target is None:
        abort(404)
    actor = current_user()
    if not can_control_access() or not can_revoke_target(actor, target):
        flash("You can't suspend this person's access.", "error")
        return redirect(url_for("employee_detail", employee_id=employee_id))
    if not (target["username"] or ""):
        flash(f"{target['name']} has no login to suspend.", "error")
        return redirect(url_for("employee_detail", employee_id=employee_id))
    if is_access_revoked(target):
        flash(f"{target['name']}'s access is already suspended.")
        return redirect(url_for("employee_detail", employee_id=employee_id))
    reason = request.form.get("reason", "").strip()
    db.execute(
        "UPDATE employees SET access_revoked = '1', access_revoked_at = ?,"
        " access_revoked_by = ?, access_revoked_reason = ? WHERE id = ?",
        (datetime.now().isoformat(timespec="seconds"),
         actor["name"] if actor else "", reason, employee_id))
    db.commit()
    flash(f"⛔ Emergency lockout applied — {target['name']} is signed out and "
          "can't sign in until reinstated.")
    return redirect(url_for("employee_detail", employee_id=employee_id))


@app.route("/employees/<int:employee_id>/reinstate-access", methods=["POST"])
def reinstate_employee_access(employee_id):
    """Piece 29.0: lift an emergency lockout, restoring the person's access."""
    db = get_db()
    target = db.execute("SELECT * FROM employees WHERE id = ?",
                        (employee_id,)).fetchone()
    if target is None:
        abort(404)
    actor = current_user()
    if not can_control_access() or not can_revoke_target(actor, target):
        flash("You can't change this person's access.", "error")
        return redirect(url_for("employee_detail", employee_id=employee_id))
    db.execute(
        "UPDATE employees SET access_revoked = '', access_revoked_at = '',"
        " access_revoked_by = '', access_revoked_reason = '' WHERE id = ?",
        (employee_id,))
    db.commit()
    flash(f"✓ Access reinstated — {target['name']} can sign in again.")
    return redirect(url_for("employee_detail", employee_id=employee_id))


@app.route("/onboarding")
@admin_required
def onboarding_checklist():
    """Piece 29.2: the company-wide new-hire checklist template editor."""
    db = get_db()
    steps = db.execute(
        "SELECT * FROM onboarding_steps WHERE active = '1'"
        " ORDER BY sort_order, id").fetchall()
    edit_id = request.args.get("edit", type=int)
    return render_template("onboarding_steps.html", steps=steps, edit_id=edit_id)


@app.route("/onboarding/steps/add", methods=["POST"])
@admin_required
def onboarding_step_add():
    title = request.form.get("title", "").strip()
    if not title:
        flash("Give the onboarding step a title.", "error")
        return redirect(url_for("onboarding_checklist"))
    db = get_db()
    nxt = db.execute(
        "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM onboarding_steps").fetchone()[0]
    db.execute(
        "INSERT INTO onboarding_steps (title, description, category, sort_order)"
        " VALUES (?, ?, ?, ?)",
        (title, request.form.get("description", "").strip(),
         request.form.get("category", "").strip(), nxt))
    db.commit()
    flash("Onboarding step added.")
    return redirect(url_for("onboarding_checklist"))


@app.route("/onboarding/steps/<int:step_id>/edit", methods=["POST"])
@admin_required
def onboarding_step_edit(step_id):
    title = request.form.get("title", "").strip()
    if not title:
        flash("Give the onboarding step a title.", "error")
        return redirect(url_for("onboarding_checklist"))
    db = get_db()
    db.execute(
        "UPDATE onboarding_steps SET title = ?, description = ?, category = ?"
        " WHERE id = ?",
        (title, request.form.get("description", "").strip(),
         request.form.get("category", "").strip(), step_id))
    db.commit()
    flash("Onboarding step updated.")
    return redirect(url_for("onboarding_checklist"))


@app.route("/onboarding/steps/<int:step_id>/delete", methods=["POST"])
@admin_required
def onboarding_step_delete(step_id):
    # Archive (keep past completion history intact) rather than hard-delete.
    db = get_db()
    db.execute("UPDATE onboarding_steps SET active = '' WHERE id = ?", (step_id,))
    db.commit()
    flash("Onboarding step removed from the checklist.")
    return redirect(url_for("onboarding_checklist"))


@app.route("/onboarding/steps/<int:step_id>/move", methods=["POST"])
@admin_required
def onboarding_step_move(step_id):
    db = get_db()
    ids = [r["id"] for r in db.execute(
        "SELECT id FROM onboarding_steps WHERE active = '1'"
        " ORDER BY sort_order, id").fetchall()]
    if step_id in ids:
        i = ids.index(step_id)
        j = i - 1 if request.form.get("dir") == "up" else i + 1
        if 0 <= j < len(ids):
            ids[i], ids[j] = ids[j], ids[i]
            for order, sid in enumerate(ids):
                db.execute("UPDATE onboarding_steps SET sort_order = ? WHERE id = ?",
                           (order, sid))
            db.commit()
    return redirect(url_for("onboarding_checklist"))


@app.route("/employees/<int:employee_id>/onboarding/<int:step_id>/toggle",
           methods=["POST"])
@admin_required
def employee_onboarding_toggle(employee_id, step_id):
    """Check / uncheck one onboarding step for one employee, stamping who and
    when. An optional note rides along with the toggle."""
    db = get_db()
    if not db.execute("SELECT 1 FROM employees WHERE id = ?",
                      (employee_id,)).fetchone():
        abort(404)
    if not db.execute("SELECT 1 FROM onboarding_steps WHERE id = ?",
                      (step_id,)).fetchone():
        abort(404)
    row = db.execute(
        "SELECT * FROM employee_onboarding WHERE employee_id = ? AND step_id = ?",
        (employee_id, step_id)).fetchone()
    now_done = not (row and row["done"] == "1")
    who = current_user()
    stamp = datetime.now().isoformat(timespec="seconds") if now_done else ""
    by = (who["name"] if who else "") if now_done else ""
    note = request.form.get("note", "").strip()
    if row:
        db.execute(
            "UPDATE employee_onboarding SET done = ?, done_at = ?, done_by = ?,"
            " note = ? WHERE id = ?",
            ("1" if now_done else "", stamp, by, note, row["id"]))
    else:
        db.execute(
            "INSERT INTO employee_onboarding (employee_id, step_id, done, done_at,"
            " done_by, note) VALUES (?, ?, ?, ?, ?, ?)",
            (employee_id, step_id, "1" if now_done else "", stamp, by, note))
    db.commit()
    return redirect(url_for("employee_detail", employee_id=employee_id,
                            _anchor="onboarding"))


@app.route("/employees/<int:employee_id>/onboarding/owner", methods=["POST"])
@admin_required
def employee_onboarding_owner(employee_id):
    """Piece 31.2: reassign who's accountable for finishing this person's
    onboarding. Only a current GM/Supervisor is accepted; the new owner is
    notified of what's still outstanding."""
    db = get_db()
    emp = db.execute("SELECT id, name FROM employees WHERE id = ?",
                     (employee_id,)).fetchone()
    if not emp:
        abort(404)
    chosen_owner = request.form.get("onboarding_owner_id", "")
    owner_id, owner_rejected = _resolve_onboarding_owner(db, chosen_owner)
    db.execute("UPDATE employees SET onboarding_owner_id = ? WHERE id = ?",
               (owner_id, employee_id))
    db.commit()
    if owner_id:  # notify whoever ended up responsible — keeps accountability held
        _, done, total = onboarding_overview(db, employee_id)
        notify_employees(
            db, [int(owner_id)],
            f"You're now responsible for onboarding {emp['name']} — "
            f"{done}/{total} steps complete.",
            link=url_for("employee_detail", employee_id=employee_id,
                         _anchor="onboarding"),
            kind="onboarding")
        db.commit()
    if owner_rejected:
        _flash_owner_override(db, chosen_owner, owner_id)
    elif owner_id:
        flash("Onboarding responsibility updated.")
    return redirect(url_for("employee_detail", employee_id=employee_id,
                            _anchor="onboarding"))


@app.route("/employees/<int:employee_id>/delete", methods=["GET", "POST"])
@admin_required
def delete_employee(employee_id):
    """Piece 19.4: admin offboarding. GET shows a confirmation page that asks
    for a reason (captured in the audit log); POST detaches their live work
    (unassigns tasks, clears sales-rep/follow-up assignments), removes their
    login / access grants / licenses / documents, then sends them to the Trash
    (a GM can restore or permanently delete). Blocked if they have field-work
    submissions on record, so approved-hours history isn't lost."""
    db = get_db()
    emp = db.execute("SELECT * FROM employees WHERE id = ?",
                     (employee_id,)).fetchone()
    if emp is None:
        abort(404)
    task_count = _count(db, "SELECT COUNT(*) FROM job_tasks WHERE employee_id = ?", (employee_id,))
    rep_count = _count(db, "SELECT COUNT(*) FROM clients WHERE assigned_rep_id = ?", (employee_id,))
    sub_count = _count(db, "SELECT COUNT(*) FROM field_submissions WHERE employee_id = ?", (employee_id,))
    if request.method == "POST":
        reason = request.form.get("reason", "").strip()
        if not reason:
            flash("A reason is required to remove an employee.", "error")
            return render_template("employee_remove.html", employee=emp,
                                   task_count=task_count, rep_count=rep_count,
                                   sub_count=sub_count), 400
        if sub_count:
            flash("This employee has field-work submissions on record (approved "
                  "hours) — handle those first. Removal cancelled.", "error")
            return redirect(url_for("employee_detail", employee_id=employee_id))
        db.execute("UPDATE job_tasks SET employee_id = NULL,"
                   " updated_at = strftime('%Y-%m-%d %H:%M:%f','now')"
                   " WHERE employee_id = ?", (employee_id,))
        db.execute("UPDATE clients SET assigned_rep_id = NULL WHERE assigned_rep_id = ?", (employee_id,))
        db.execute("UPDATE lead_followups SET rep_id = NULL WHERE rep_id = ?", (employee_id,))
        db.execute("DELETE FROM permission_grants WHERE employee_id = ?", (employee_id,))
        db.execute("DELETE FROM password_requests WHERE employee_id = ?", (employee_id,))
        db.execute("DELETE FROM security_answers WHERE employee_id = ?", (employee_id,))
        db.execute("DELETE FROM employee_onboarding WHERE employee_id = ?", (employee_id,))
        for f in db.execute("SELECT stored_name FROM employee_files"
                            " WHERE employee_id = ?", (employee_id,)).fetchall():
            (employee_upload_dir(employee_id) / f["stored_name"]).unlink(missing_ok=True)
        db.execute("DELETE FROM employee_files WHERE employee_id = ?", (employee_id,))
        db.execute("DELETE FROM employee_credentials WHERE employee_id = ?", (employee_id,))
        db.execute("UPDATE employees SET username = '', password_hash = '',"
                   " access_level = '' WHERE id = ?", (employee_id,))
        db.commit()
        ok, msg = trash_item("employee", employee_id)  # tasks/rep detached above
        flash(f"{emp['name']} removed — reason recorded in the audit log. {msg}"
              if ok else msg, "" if ok else "error")
        return redirect(url_for("employees_page") if ok
                        else url_for("employee_detail", employee_id=employee_id))
    return render_template("employee_remove.html", employee=emp,
                           task_count=task_count, rep_count=rep_count,
                           sub_count=sub_count)


# ---- employee licenses & certifications (structured, with expiry) --------
@app.route("/employees/<int:employee_id>/credentials/add", methods=["POST"])
@admin_required
def add_credential(employee_id):
    if get_db().execute("SELECT id FROM employees WHERE id = ?",
                        (employee_id,)).fetchone() is None:
        abort(404)
    name = request.form.get("name", "").strip()
    if not name:
        flash("A license/certification needs a name.", "error")
        return redirect(url_for("employee_detail", employee_id=employee_id, _anchor="licenses"))
    db = get_db()
    db.execute(
        "INSERT INTO employee_credentials"
        " (employee_id, name, rule_label, number, issued, expires, notes)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (employee_id, name,
         request.form.get("rule_label", "").strip(),
         request.form.get("number", "").strip(),
         request.form.get("issued", "").strip(),
         request.form.get("expires", "").strip(),
         request.form.get("notes", "").strip()),
    )
    db.commit()
    flash(f"Added license/certification: {name}")
    return redirect(url_for("employee_detail", employee_id=employee_id, _anchor="licenses"))


@app.route("/employees/<int:employee_id>/credentials/<int:credential_id>/edit",
           methods=["POST"])
@admin_required
def update_credential(employee_id, credential_id):
    db = get_db()
    if db.execute("SELECT 1 FROM employee_credentials WHERE id = ?"
                  " AND employee_id = ?", (credential_id, employee_id)).fetchone() is None:
        abort(404)
    name = request.form.get("name", "").strip()
    if not name:
        flash("A license/certification needs a name.", "error")
        return redirect(url_for("employee_detail", employee_id=employee_id,
                                edit_credential=credential_id, _anchor="licenses"))
    db.execute(
        "UPDATE employee_credentials SET name = ?, rule_label = ?, number = ?,"
        " issued = ?, expires = ?, notes = ? WHERE id = ?",
        (name, request.form.get("rule_label", "").strip(),
         request.form.get("number", "").strip(),
         request.form.get("issued", "").strip(),
         request.form.get("expires", "").strip(),
         request.form.get("notes", "").strip(), credential_id))
    db.commit()
    flash(f"Updated license/certification: {name}")
    return redirect(url_for("employee_detail", employee_id=employee_id, _anchor="licenses"))


@app.route("/employees/<int:employee_id>/credentials/<int:credential_id>/delete",
           methods=["POST"])
@delete_required
def delete_credential(employee_id, credential_id):
    ok, msg = trash_item("credential", credential_id)
    flash(msg, "" if ok else "error")
    return redirect(url_for("employee_detail", employee_id=employee_id, _anchor="licenses"))


# ---- employee documents (copies of certifications, etc.) -----------------
def employee_upload_dir(employee_id):
    directory = UPLOADS_DIR / f"employee_{employee_id}"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


@app.route("/employees/<int:employee_id>/files/upload", methods=["POST"])
@admin_required
def upload_employee_file(employee_id):
    if get_db().execute("SELECT id FROM employees WHERE id = ?",
                        (employee_id,)).fetchone() is None:
        abort(404)
    upload = request.files.get("document")
    if upload is None or not upload.filename:
        flash("Choose a file to upload.", "error")
        return redirect(url_for("employee_detail", employee_id=employee_id, _anchor="documents"))
    extension = upload.filename.rsplit(".", 1)[-1].lower() if "." in upload.filename else ""
    if extension not in ALLOWED_EXTENSIONS:
        flash(f"File type .{extension} is not allowed.", "error")
        return redirect(url_for("employee_detail", employee_id=employee_id, _anchor="documents"))
    db = get_db()
    credential_name = request.form.get("credential_name", "").strip()
    # Piece 25.4: auto-rename to Employee_Credential_Date.ext for recordkeeping.
    ename = db.execute("SELECT name FROM employees WHERE id = ?",
                       (employee_id,)).fetchone()
    friendly = friendly_filename(
        [ename["name"] if ename else "", credential_name or "Document"], extension,
        taken=_taken_names(db, "employee_files", "original_name",
                           "employee_id", employee_id))
    stored = f"{uuid.uuid4().hex[:8]}_{secure_filename(friendly)}"
    upload.save(employee_upload_dir(employee_id) / stored)
    db.execute(
        "INSERT INTO employee_files"
        " (employee_id, credential_name, stored_name, original_name)"
        " VALUES (?, ?, ?, ?)",
        (employee_id, credential_name, stored, friendly),
    )
    db.commit()
    flash(f"Uploaded: {friendly}")
    return redirect(url_for("employee_detail", employee_id=employee_id, _anchor="documents"))


@app.route("/employees/<int:employee_id>/files/<int:file_id>/download")
def download_employee_file(employee_id, file_id):
    record = get_db().execute(
        "SELECT * FROM employee_files WHERE id = ? AND employee_id = ?",
        (file_id, employee_id)).fetchone()
    if record is None:
        abort(404)
    return send_from_directory(
        employee_upload_dir(employee_id), record["stored_name"],
        as_attachment=True, download_name=record["original_name"])


@app.route("/employees/<int:employee_id>/files/<int:file_id>/delete",
           methods=["POST"])
@delete_required
def delete_employee_file(employee_id, file_id):
    ok, msg = trash_item("employee_file", file_id)
    flash(msg, "" if ok else "error")
    return redirect(url_for("employee_detail", employee_id=employee_id, _anchor="documents"))


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
        ensure_lead_followups(conn)
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
    "You are the Compendium Assistant, a helpful internal aide for Vixinman Designs, a "
    "residential & commercial solar installer in New Mexico. You answer staff "
    "questions about the company's jobs, clients, tasks and schedule.\n\n"
    "You are given a COMPENDIUM DATA snapshot for quick orientation, plus a set of "
    "read-only tools to look things up live. Use the tools whenever the answer "
    "needs specifics beyond the snapshot (a particular job, filtered lists, a "
    "client's history, someone's tasks). Prefer tools over guessing, and you may "
    "call several in a row to narrow things down.\n\n"
    "Everything you can see — snapshot and tools alike — is already limited to "
    "what THIS signed-in user is permitted to see. Never invent jobs, names, "
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
    roles = (user["roles"] or "") if user else ""
    lines.append(f"Signed-in user: {name} — roles: {roles or 'none'}.")
    can_price = _can_see_pricing()
    can_pay = _can_payroll()
    lines.append("Viewer may see internal pricing/margins: "
                 f"{'yes' if can_price else 'no'}. Payroll: "
                 f"{'yes' if can_pay else 'no'}.")
    today = datetime.now().strftime("%Y-%m-%d")
    lines.append(f"Today is {today}.")

    # Jobs by pipeline stage (visible to everyone).
    by_stage = db.execute(
        "SELECT status, COUNT(*) c FROM jobs GROUP BY status").fetchall()
    if by_stage:
        counts = ", ".join(f"{r['status'] or 'Unset'}: {r['c']}" for r in by_stage)
        lines.append(f"Jobs by stage — {counts}.")

    # Active (non-terminal) jobs, capped for token budget.
    active = db.execute(
        "SELECT j.job_name, j.status, j.install_date, c.name AS client,"
        "  COALESCE(e.name,'') AS rep"
        " FROM jobs j JOIN clients c ON c.id = j.client_id"
        " LEFT JOIN employees e ON e.id = c.assigned_rep_id"
        " WHERE j.status NOT IN ('Complete','Lost')"
        " ORDER BY (j.install_date = ''), j.install_date, j.id LIMIT 40"
    ).fetchall()
    if active:
        lines.append("Active jobs (job — client — stage — install date — rep):")
        for r in active:
            lines.append(
                f"  • {r['job_name'] or 'Job'} — {r['client']} — {r['status']}"
                f" — install {r['install_date'] or 'TBD'}"
                f"{(' — ' + r['rep']) if r['rep'] else ''}")

    # This user's own open tasks.
    if user:
        mine = db.execute(
            "SELECT t.title, t.status, t.due_date, j.job_name, c.name AS client"
            " FROM job_tasks t JOIN jobs j ON j.id = t.job_id"
            " JOIN clients c ON c.id = j.client_id"
            " WHERE t.employee_id = ? AND t.status != 'Done' AND j.status != 'Lost'"
            " ORDER BY (t.due_date = ''), t.due_date LIMIT 25", (user["id"],)
        ).fetchall()
        if mine:
            lines.append(f"{name}'s open tasks (task — job — client — due):")
            for r in mine:
                lines.append(
                    f"  • {r['title']} — {r['job_name'] or 'Job'} — {r['client']}"
                    f" — due {r['due_date'] or 'no date'} [{r['status']}]")
        else:
            lines.append(f"{name} has no open tasks assigned.")

    # Overdue open tasks across the company (status is not sensitive).
    overdue = db.execute(
        "SELECT COUNT(*) FROM job_tasks t JOIN jobs j ON j.id = t.job_id"
        " WHERE t.status != 'Done' AND j.status != 'Lost'"
        " AND COALESCE(t.due_date,'') != '' AND t.due_date < ?", (today,)
    ).fetchone()[0]
    lines.append(f"Company-wide overdue open tasks: {overdue}.")

    # Contract totals only for pricing-cleared viewers.
    if can_price:
        row = db.execute(
            "SELECT COUNT(*) n, COALESCE(SUM(contract_amount),0) t FROM jobs"
            " WHERE status NOT IN ('Complete','Lost')"
            " AND COALESCE(contract_amount,0) > 0").fetchone()
        if row and row["n"]:
            lines.append(
                f"Active jobs with a contract total: {row['n']}, "
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

    def find_jobs(args):
        text = (args.get("text") or "").strip()
        stage = (args.get("stage") or "").strip()
        county = (args.get("county") or "").strip()
        rep = (args.get("assigned_rep") or "").strip()
        overdue_only = bool(args.get("overdue_only"))
        try:
            limit = min(int(args.get("limit") or 25), 50)
        except (TypeError, ValueError):
            limit = 25
        where, params = ["1=1"], []
        if text:
            where.append("(j.job_name LIKE ? OR c.name LIKE ?)")
            params += [f"%{text}%", f"%{text}%"]
        if stage:
            where.append("j.status = ?"); params.append(stage)
        if county:
            where.append("j.county LIKE ?"); params.append(f"%{county}%")
        if rep:
            where.append("e.name LIKE ?"); params.append(f"%{rep}%")
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
                "EXISTS (SELECT 1 FROM job_tasks t WHERE t.job_id = j.id"
                " AND t.status != 'Done' AND COALESCE(t.due_date,'') != ''"
                " AND t.due_date < ?)")
            params.append(today)
        rows = db.execute(
            "SELECT j.id, j.job_name, j.status, j.install_date, j.county,"
            "  COALESCE(j.contract_amount,0) AS amt, c.name AS client,"
            "  COALESCE(e.name,'') AS rep"
            " FROM jobs j JOIN clients c ON c.id = j.client_id"
            " LEFT JOIN employees e ON e.id = c.assigned_rep_id"
            f" WHERE {' AND '.join(where)}"
            " ORDER BY (j.install_date = ''), j.install_date, j.id LIMIT ?",
            params + [limit]).fetchall()
        if not rows:
            return "No jobs match those filters."
        out = [f"{len(rows)} job(s):"]
        for r in rows:
            line = (f"#{r['id']} {r['job_name'] or 'Job'} — {r['client']} — "
                    f"{r['status']} — install {r['install_date'] or 'TBD'}"
                    f"{' — ' + r['county'] if r['county'] else ''}"
                    f"{' — rep ' + r['rep'] if r['rep'] else ''}")
            if can_price and r["amt"]:
                line += f" — contract {_assist_money(r['amt'])}"
            out.append("• " + line)
        return "\n".join(out)

    def job_details(args):
        ident = (args.get("job") or "").strip()
        if not ident:
            return "Provide a job name or #id."
        row = None
        if ident.lstrip("#").isdigit():
            row = db.execute(
                "SELECT j.*, c.name AS client, COALESCE(e.name,'') AS rep"
                " FROM jobs j JOIN clients c ON c.id = j.client_id"
                " LEFT JOIN employees e ON e.id = c.assigned_rep_id"
                " WHERE j.id = ?", (int(ident.lstrip("#")),)).fetchone()
        if row is None:
            row = db.execute(
                "SELECT j.*, c.name AS client, COALESCE(e.name,'') AS rep"
                " FROM jobs j JOIN clients c ON c.id = j.client_id"
                " LEFT JOIN employees e ON e.id = c.assigned_rep_id"
                " WHERE j.job_name LIKE ? ORDER BY j.id LIMIT 1",
                (f"%{ident}%",)).fetchone()
        if row is None:
            return f"No job found matching '{ident}'."
        out = [f"Job #{row['id']}: {row['job_name'] or 'Job'} — client {row['client']}",
               f"Stage: {row['status']}",
               f"Install date: {row['install_date'] or 'TBD'}",
               f"County: {row['county'] or '—'}",
               f"Payment: {row['cost_method'] or '—'}",
               f"Assigned rep: {row['rep'] or '—'}"]
        if can_price and (row["contract_amount"] or 0):
            out.append(f"Contract total: {_assist_money(row['contract_amount'])}")
        if (row["status"] or "") == "Lost" and (row["cancel_reason"] or ""):
            out.append(f"Cancelled — reason: {row['cancel_reason']}")
        tasks = db.execute(
            "SELECT title, status, due_date, COALESCE(pipeline_status,'') AS ps"
            " FROM job_tasks WHERE job_id = ? AND status != 'Done'"
            " ORDER BY (due_date=''), due_date LIMIT 20", (row["id"],)).fetchall()
        if tasks:
            out.append(f"Open tasks ({len(tasks)}):")
            for t in tasks:
                out.append(f"  • {t['title']} — due {t['due_date'] or 'no date'}"
                           f" [{t['status']}{'/' + t['ps'] if t['ps'] else ''}]")
        else:
            out.append("No open tasks.")
        mats = db.execute(
            "SELECT status, COUNT(*) c FROM job_materials WHERE job_id = ?"
            " GROUP BY status", (row["id"],)).fetchall()
        if mats:
            out.append("Materials: " + ", ".join(f"{m['status'] or '—'}: {m['c']}"
                                                  for m in mats))
        notes = db.execute(
            "SELECT note, created_at FROM job_notes WHERE job_id = ?"
            " ORDER BY id DESC LIMIT 3", (row["id"],)).fetchall()
        if notes:
            out.append("Recent field notes:")
            for n in notes:
                out.append(f"  • {(n['created_at'] or '')[:10]}: {n['note']}")
        return "\n".join(out)

    def find_clients(args):
        text = (args.get("text") or "").strip()
        status = (args.get("status") or "").strip()
        try:
            limit = min(int(args.get("limit") or 25), 50)
        except (TypeError, ValueError):
            limit = 25
        where, params = ["1=1"], []
        if text:
            where.append("c.name LIKE ?"); params.append(f"%{text}%")
        if status:
            where.append("c.lead_status LIKE ?"); params.append(f"%{status}%")
        rows = db.execute(
            "SELECT c.id, c.name, COALESCE(c.lead_status,'') AS status,"
            "  COALESCE(c.phone,'') AS phone, COALESCE(e.name,'') AS rep,"
            "  (SELECT COUNT(*) FROM jobs j WHERE j.client_id = c.id) AS jobs"
            " FROM clients c LEFT JOIN employees e ON e.id = c.assigned_rep_id"
            f" WHERE {' AND '.join(where)} ORDER BY c.name LIMIT ?",
            params + [limit]).fetchall()
        if not rows:
            return "No clients match."
        out = [f"{len(rows)} client(s):"]
        for r in rows:
            out.append(f"• {r['name']} — {r['status'] or 'no status'}"
                       f"{' — rep ' + r['rep'] if r['rep'] else ''}"
                       f"{' — ' + r['phone'] if r['phone'] else ''}"
                       f" — {r['jobs']} job(s)")
        return "\n".join(out)

    def list_tasks(args):
        assignee = (args.get("assignee") or "").strip()
        overdue_only = bool(args.get("overdue_only"))
        stage = (args.get("stage") or "").strip()
        try:
            limit = min(int(args.get("limit") or 30), 60)
        except (TypeError, ValueError):
            limit = 30
        where = ["t.status != 'Done'", "j.status != 'Lost'"]
        params = []
        if assignee.lower() in ("me", "mine") and user:
            where.append("t.employee_id = ?"); params.append(user["id"])
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
            "  c.name AS client, COALESCE(e.name,'') AS who"
            " FROM job_tasks t JOIN jobs j ON j.id = t.job_id"
            " JOIN clients c ON c.id = j.client_id"
            " LEFT JOIN employees e ON e.id = t.employee_id"
            f" WHERE {' AND '.join(where)}"
            " ORDER BY (t.due_date=''), t.due_date LIMIT ?",
            params + [limit]).fetchall()
        if not rows:
            return "No matching open tasks."
        out = [f"{len(rows)} task(s):"]
        for r in rows:
            out.append(f"• {r['title']} — {r['job_name'] or 'Job'} ({r['client']})"
                       f" — due {r['due_date'] or 'no date'}"
                       f"{' — ' + r['who'] if r['who'] else ' — unassigned'}")
        return "\n".join(out)

    def staff_directory(args):
        role = (args.get("role") or "").strip()
        where, params = ["1=1"], []
        if role:
            where.append("roles LIKE ?"); params.append(f"%{role}%")
        rows = db.execute(
            f"SELECT name, COALESCE(roles,'') AS roles FROM employees"
            f" WHERE {' AND '.join(where)} ORDER BY name LIMIT 60", params).fetchall()
        if not rows:
            return "No staff match."
        return "\n".join(f"• {r['name']} — {r['roles'] or 'no roles'}" for r in rows)

    stages = ", ".join(JOB_STATUSES)
    return [
        {"name": "find_jobs",
         "description": ("Search jobs with optional filters. Use for questions like "
                         "'jobs in Job Prep', 'jobs in Bernalillo county', 'overdue "
                         "jobs', or a client/job name search."),
         "parameters": {"type": "object", "properties": {
             "text": {"type": "string", "description": "match job or client name"},
             "stage": {"type": "string", "description": f"pipeline stage; one of: {stages}"},
             "county": {"type": "string", "description": "NM county name"},
             "assigned_rep": {"type": "string", "description": "assigned sales rep name"},
             "overdue_only": {"type": "boolean", "description": "only jobs with an overdue task"},
             "min_contract": {"type": "number", "description": "minimum contract total (only honored for pricing-cleared users)"},
             "limit": {"type": "integer", "description": "max rows (default 25)"}}},
         "run": find_jobs},
        {"name": "job_details",
         "description": ("Full detail for one job by name or #id: stage, install "
                         "date, rep, payment, open tasks, materials, recent notes "
                         "(and contract total if you may see pricing)."),
         "parameters": {"type": "object", "properties": {
             "job": {"type": "string", "description": "job name or #id"}},
             "required": ["job"]},
         "run": job_details},
        {"name": "find_clients",
         "description": "Search clients by name/status. Returns rep, phone, job count.",
         "parameters": {"type": "object", "properties": {
             "text": {"type": "string", "description": "match client name"},
             "status": {"type": "string", "description": "client status filter"},
             "limit": {"type": "integer", "description": "max rows (default 25)"}}},
         "run": find_clients},
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
         "description": "List employees and their roles (no pay info). Optional role filter.",
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
