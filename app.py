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
import shutil
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


# ------------------------------------------------------------------- chores
def ensure_routine_task_reminders(db):
    """Piece 37: due-date reminders for recurring chores (routine_tasks),
    through the same notifications inbox as ensure_backlog_reminders. Each
    chore reminds once per cycle (reminder_sent flag), to whoever it's
    assigned to — or every member with a login, if unassigned. Called both
    on dashboard load and from the background scheduler (run_maintenance)."""
    today = datetime.now().strftime("%Y-%m-%d")
    all_members = [r["id"] for r in db.execute(
        "SELECT id FROM household_members WHERE COALESCE(username,'') != ''").fetchall()]
    made = False
    for chore in db.execute(
            "SELECT * FROM routine_tasks WHERE next_due != '' AND next_due <= ?"
            " AND COALESCE(reminder_sent, '') != '1'", (today,)).fetchall():
        recipients = ([chore["household_member_id"]] if chore["household_member_id"]
                      else all_members)
        if not recipients:
            continue
        notify_employees(
            db, recipients, f"🔁 Chore due: {chore['title']}",
            link="/chores", kind="chore")
        db.execute("UPDATE routine_tasks SET reminder_sent = '1' WHERE id = ?",
                   (chore["id"],))
        made = True
    if made:
        db.commit()


# --------------------------------------------------------------- appointments
def ensure_appointment_reminders(db):
    """Piece 42: due-date reminders for appointments, through the same
    notifications inbox as ensure_routine_task_reminders. Each appointment
    reminds once per when_date (reminder_sent flag), to whoever it's
    assigned to — or every member with a login, if unassigned. Called both
    on dashboard load and from the background scheduler (run_maintenance)."""
    today = datetime.now().strftime("%Y-%m-%d")
    all_members = [r["id"] for r in db.execute(
        "SELECT id FROM household_members WHERE COALESCE(username,'') != ''").fetchall()]
    made = False
    for appt in db.execute(
            "SELECT * FROM appointments WHERE when_date != '' AND when_date <= ?"
            " AND COALESCE(completed_at, '') = '' AND COALESCE(reminder_sent, '') != '1'",
            (today,)).fetchall():
        recipients = ([appt["household_member_id"]] if appt["household_member_id"]
                      else all_members)
        if not recipients:
            continue
        when = appt["when_date"] + (f" {appt['when_time']}" if appt["when_time"] else "")
        notify_employees(
            db, recipients, f"📅 Appointment: {appt['title']} ({when})",
            link="/appointments", kind="appointment")
        db.execute("UPDATE appointments SET reminder_sent = '1' WHERE id = ?",
                   (appt["id"],))
        made = True
    if made:
        db.commit()


# ------------------------------------------------- Piece 38: standalone requirements
def ensure_requirement_reminders(db):
    """Due-date reminders for standalone recurring requirements (resource_rules
    rows with no project field_name) — the same mechanics as
    ensure_routine_task_reminders, just against a different table. Called both
    on dashboard load and from the background scheduler (run_maintenance)."""
    today = datetime.now().strftime("%Y-%m-%d")
    all_members = [r["id"] for r in db.execute(
        "SELECT id FROM household_members WHERE COALESCE(username,'') != ''").fetchall()]
    made = False
    for req in db.execute(
            "SELECT * FROM resource_rules WHERE field_name = '' AND next_due != ''"
            " AND next_due <= ? AND COALESCE(reminder_sent, '') != '1'",
            (today,)).fetchall():
        recipients = ([req["household_member_id"]] if req["household_member_id"]
                      else all_members)
        if not recipients:
            continue
        notify_employees(
            db, recipients, f"📋 Requirement due: {req['label']}",
            link="/rules", kind="requirement")
        db.execute("UPDATE resource_rules SET reminder_sent = '1' WHERE id = ?",
                   (req["id"],))
        made = True
    if made:
        db.commit()


# Project profile columns. Piece 38: project_category/project_type are the
# household-appropriate fields a Requirements Engine rule matches against
# (Home Improvement / Personal Improvement projects). Piece 41: the solar-sale
# fields that used to live here (county/electric_loads/utility_provider/
# warranty_type/cost_method/tax_credit/expand_option/products + PV-Generator-
# Battery variants/service_type/property_type) are gone — nothing left to
# serve them once the install-job pipeline gating and the 145 solar-permit
# resource_rules that matched on them were both cut. A generic household
# project just needs a name, category, type, and (optional) location.
PROJECT_FIELDS = ["job_name", "project_category", "project_type", "site_location",
                  "estimated_cost"]

# Piece 38: the two household project kinds the user actually undertakes —
# home-improvement work and personal-improvement pursuits (a skill, a
# certification, a course). project_type is free text describing the specific
# project within whichever category.
PROJECT_CATEGORIES = ["Home Improvement", "Personal Improvement"]

# Piece 44: each category's fixed subcategory list -- project_type (below)
# is now a controlled value cascading from whichever category is picked,
# not free text. A known, fixed vocabulary is also what makes project_type
# useful for the Requirements Engine to match on reliably.
PROJECT_SUBCATEGORIES = {
    "Home Improvement": ["Building", "Landscaping", "Gardening", "Maintenance & Repair"],
    "Personal Improvement": ["Education", "Health", "Habit", "Relationship", "Misc"],
}

# Labels used on the report and anywhere a field needs a human name.
PROJECT_FIELD_LABELS = {
    "job_name": "Project name",
    "project_category": "Project category",
    "project_type": "Subcategory",
    "site_location": "Site location",
    "estimated_cost": "Estimated cost",
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
    "inventory.manage": "Manage inventory (add/edit items, tools, stock)",
    "household.manage": "Manage household members & accounts",
    "approvals": "Approve field work & wishlist requests",
    "audit.view": "View the audit log",
    "finances.manage": "Manage household & project finances (Budget, project billing) — hidden entirely without it",
    "projects.manage": "Create, edit, cancel, and reopen projects",
    "help.full_access": "See every Help/FAQ section, including ones about tools you don't have access to",
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

# Piece 51: each role's default permission bundle, materialized as real
# permission_grants rows (see _seed_role_default_grants) rather than checked
# live -- has_permission()/_has_grant() need no new code path. Admin (the
# separate is_admin flag) already bypasses this entirely except "delete".
# Piece 52: Assistant's bundle now matches Parent (everything but delete) --
# this is the account an AI agent runs under. Every write it makes through
# any of these 7 permissions is intercepted by @draftable and becomes a
# Pending row in `drafts` instead of a real write; a Parent/Admin approves
# (applies for real) or discards it from /drafts. See DRAFT_KINDS below.
# Piece 53: help.full_access added -- Parent/Assistant get it by default
# (they already have the underlying permission each locked FAQ section
# documents anyway); Child does not. See HELP_SECTION_PERMISSION below.
ROLE_DEFAULT_PERMISSIONS = {
    "Parent": ["rules.manage", "inventory.manage", "household.manage",
               "approvals", "audit.view", "finances.manage", "projects.manage",
               "help.full_access"],
    "Assistant": ["rules.manage", "inventory.manage", "household.manage",
                  "approvals", "audit.view", "finances.manage", "projects.manage",
                  "help.full_access"],
    "Child": [],
}

# Piece 16.1 (revised Piece 35): the household's roster as a one-time seed
# for a fresh install — (name, role, is_admin).
HOUSEHOLD_ROSTER = [
    ("Jacob", "Parent", True),
    ("Rachel", "Parent", True),
    ("Victor", "Child", False),
    ("Dmitri", "Child", False),
    ("Gremory", "Assistant", False),
]

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

# Piece 21.5: source-document type for a ledger entry, so scanned/received
# paperwork feeds the QuickBooks reports under the right account flow:
#   Invoice — money we bill a customer (A/R, Income)
#   Bill    — money a vendor bills us (A/P, Expense)
#   Receipt — proof of a payment already made (an expense paid at the counter)
# A blank doc type is a plain ledger note with no paperwork behind it.
DOC_TYPES = ["Receipt", "Invoice", "Bill"]

# Piece 54: Household Budget's category fields are free text (unlike project
# billing's hard <select>) -- these are suggestions via a <datalist>, not a
# fixed vocabulary; a household can always type something else.
HOUSEHOLD_BUDGET_CATEGORIES = ["Groceries", "Utilities", "Subscriptions",
                               "Discretionary Spending", "Other"]

# New Mexico gross-receipts tax. The rate is per project (it varies by the install
# location), defaulting to 0% because Vixinman's solar systems are
# GRT-deductible (see the "GRT Exemption on Invoice" rule); Finance sets a
# rate on the Billing tab where any receipts are taxable.
GRT_DEFAULT_RATE = 0.0
# Piece 38: renamed from the solar-shop taxonomy (License/Compliance) to fit
# household requirements — a cert earned for a personal-improvement project,
# a prerequisite/inspection a home-improvement project needs before it can
# proceed. Permit/Link/Phone/Doc carry over unchanged.
RULE_CATEGORIES = ["Certification", "Permit", "Prerequisite", "Link", "Phone", "Doc"]
CATEGORY_HEADINGS = {
    "Certification": "Certifications",
    "Permit": "Permits",
    "Prerequisite": "Prerequisites",
    "Link": "Online Portals",
    "Phone": "Phone numbers",
    "Doc": "Documents",
}

# Piece 38: the solar-shop seed content that used to live here (License/
# Permit/Compliance rules for PV/generator/battery/well-pump installs, NM
# county AHJ contacts, utility interconnection links) is gone -- none of it
# describes a household project. A fresh install now starts with an empty
# Requirements Engine; seed_version watermarking means an existing database
# that already ran these batches is unaffected, and any rule rows it still
# has are left in place for the user to review/delete via the Requirements Editor.
SEED_RULES = []
SEED_BATCHES = {}
SEED_BATCH_SQL = {}

# Shown in the footer of every page so it's always obvious which build
# is running. Bumped with each update. Reset to semantic versioning
# (starting at 0.1) with the Vixinman household rebrand, replacing the
# old solar-business "Piece N.N" build counter.
VERSION = "0.31"

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
# Piece 18 (revised Piece 35, de-gated Piece 41): the exit criteria to advance
# each pipeline status. `dept` is a boolean sentinel used by project_detail.html
# ("—" means no advance panel is shown, e.g. Done/Abandoned) — its text is
# never displayed. `exit` is displayed ("To advance: ...") and is now generic,
# not install-job-specific — no stage has a hard-coded permits/install-date/
# electric-loads requirement anymore (Piece 41 dropped that gating entirely).
STATUS_OWNERSHIP = {
    "Planning": {"dept": "Planning", "exit": "Move to Prep once you're ready to start on it."},
    "Prep": {"dept": "Prep", "exit": "Move to In Progress once prep work is done."},
    "In Progress": {"dept": "In Progress", "exit": "Move to Wrap-up once the work itself is complete."},
    "Wrap-up": {"dept": "Wrap-up",
                "exit": "Mark Done once any final paperwork or cleanup is finished."},
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
# the view function name (e.g. delete_rule -> "Delete rule"), so new routes
# are logged readably without extra wiring.
ACTION_LABELS = {
    "new_project": "Create project",
    "edit_project": "Edit project", "add_rule": "Add rule", "delete_rule": "Delete rule",
    "backlog_new": "Add backlog idea", "backlog_edit": "Edit backlog idea",
    "backlog_start": "Start idea as a project", "backlog_delete": "Delete backlog idea",
    "new_employee": "Add employee", "edit_employee": "Edit employee",
    "delete_employee": "Delete employee", "upload_file": "Upload project document",
    "set_task_status": "Change task status", "set_task_assignee": "Reassign task",
    "set_task_due": "Change task due date",
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


def _seed_role_default_grants(db, member_id, role):
    """Piece 51: materialize a role's default permission bundle as real
    permission_grants rows. Additive only -- never revokes an existing
    grant, even if the member's role later changes to a smaller bundle
    (matches this app's "nothing destructive without an explicit action"
    pattern; an admin can still manually uncheck anything on the Access
    console)."""
    existing = {r["permission"] for r in db.execute(
        "SELECT permission FROM permission_grants WHERE household_member_id = ?",
        (member_id,)).fetchall()}
    for perm in ROLE_DEFAULT_PERMISSIONS.get(role, []):
        if perm not in existing:
            db.execute(
                "INSERT INTO permission_grants (household_member_id, permission,"
                " granted_by) VALUES (?, ?, ?)", (member_id, perm, "role default"))


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


def _can_see_project_files(project_id, user=None):
    """Piece 53: a Child needs >=1 task assigned on THIS project to see its
    filed documents; everyone else (open mode, admin, Parent, Assistant)
    always can. A Child still sees everything else about the project
    regardless of assignment -- only filed documents are hidden."""
    if not accounts_exist() or _is_admin():
        return True
    if user is None:
        user = current_user()
    if user is None:
        return False
    if user["role"] != "Child":
        return True
    return get_db().execute(
        "SELECT 1 FROM project_tasks WHERE project_id = ?"
        " AND household_member_id = ? LIMIT 1", (project_id, user["id"])
    ).fetchone() is not None


def _file_route_allowed(project_id, record=None):
    """Piece 53: gate for upload_file/download_file/view_file. A field
    photo (task_id set) or billing receipt (txn_id set) is exempt -- those
    are already scoped to whoever legitimately filed them and shouldn't be
    re-gated by project-wide task assignment (e.g. a Child's own already-
    filed photo shouldn't vanish just because their task was reassigned)."""
    if record is not None and (record["task_id"] or record["txn_id"]):
        return True
    return _can_see_project_files(project_id)


# Piece 53: which permission (if any) each Help/FAQ section documents. None
# = no gate, always shown. "admin" is a sentinel for the generic admin gate
# (used only by #managers, which has no PERMISSIONS key of its own).
HELP_SECTION_PERMISSION = {
    "rules": "rules.manage",
    "finance": "finances.manage",
    "budget-help": "finances.manage",
    "loans-help": "finances.manage",
    "savings-help": "finances.manage",
    "people": "household.manage",
    "managers": "admin",
}


def help_section_unlocked(section_id):
    """Jinja global: True if the signed-in user should see this Help
    section's real content rather than a locked placeholder. help.full_access
    always unlocks everything; a section absent from HELP_SECTION_PERMISSION
    is always open; otherwise it's open to anyone who already holds (or is
    admin for) the permission it documents -- never MORE restrictive than
    the feature itself, just hides the explanation of something you can't
    use anyway."""
    required = HELP_SECTION_PERMISSION.get(section_id)
    if required is None or has_permission("help.full_access"):
        return True
    return _is_admin() if required == "admin" else has_permission(required)


# Which permission each admin-gated view needs (Piece 17). Views not listed
# fall back to the generic admin gate (perm=None).
VIEW_PERMISSION = {
    "submissions_page": "approvals",
    "approve_submission": "approvals",
    "reject_submission": "approvals",
    "wishlist_approve": "approvals",
    "wishlist_reject": "approvals",
    "add_rule": "rules.manage",
    "update_rule": "rules.manage",
    "delete_rule": "rules.manage",
    # Piece 53: the Requirements Editor's own view was ungated -- a Child
    # could reach it directly even though the write routes above already
    # required rules.manage.
    "rules_page": "rules.manage",
    "accounts_page": "household.manage",
    "approve_password_change": "household.manage",
    "reject_password_change": "household.manage",
    "new_household_member": "household.manage",
    "edit_household_member": "household.manage",
    "delete_household_member": "household.manage",
    # Piece 53: Family (the household-members roster) and Household Files
    # were both fully open to any signed-in user -- neither viewing nor the
    # write routes were gated. household.manage is the closest existing fit
    # ("manage household members & accounts"); reused here rather than
    # inventing a permission for one shared-document page.
    "household_members_page": "household.manage",
    "household_member_detail": "household.manage",
    "household_files_page": "household.manage",
    "upload_household_file": "household.manage",
    "download_household_file": "household.manage",
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
    "inventory_tool_new": "inventory.manage",
    "inventory_tool_edit": "inventory.manage",
    "inventory_vehicle_new": "inventory.manage",
    "inventory_vehicle_edit": "inventory.manage",
    # Piece 51: household Budget + a project's own billing ledger are
    # finances.manage -- viewing is gated too (not just editing), since a
    # Child must not see finances at all, unlike every other .manage
    # permission above (which only gates editing; viewing stays open).
    "household_budget_page": "finances.manage",
    "household_txn_new": "finances.manage",
    "household_txn_edit": "finances.manage",
    "household_txn_delete": "finances.manage",
    "download_household_receipt": "finances.manage",
    "household_txn_toggle_paid": "finances.manage",
    "household_budget_new": "finances.manage",
    "household_budget_edit": "finances.manage",
    "household_budget_delete": "finances.manage",
    # Piece 54: Loans and Savings accounts -- reuse finances.manage, the
    # same all-or-nothing "see all money" gate as Budget/project billing.
    "loans_page": "finances.manage",
    "loan_account_new": "finances.manage",
    "loan_account_edit": "finances.manage",
    "loan_account_delete": "finances.manage",
    "loan_account_detail": "finances.manage",
    "loan_entry_new": "finances.manage",
    "loan_entry_delete": "finances.manage",
    "download_loan_statement": "finances.manage",
    "savings_page": "finances.manage",
    "savings_account_new": "finances.manage",
    "savings_account_edit": "finances.manage",
    "savings_account_delete": "finances.manage",
    "savings_account_detail": "finances.manage",
    "savings_entry_new": "finances.manage",
    "savings_entry_delete": "finances.manage",
    "download_savings_statement": "finances.manage",
    "set_contract": "finances.manage",
    "add_transaction": "finances.manage",
    "toggle_transaction_paid": "finances.manage",
    "delete_transaction": "finances.manage",
    # Piece 51: creating/editing/cancelling/reopening a project. Viewing
    # (project_detail, projects_list, project_version) stays open, matching
    # the inventory.manage precedent.
    "new_project": "projects.manage",
    "edit_project": "projects.manage",
    "set_project_status": "projects.manage",
    "cancel_project": "projects.manage",
    "reopen_project": "projects.manage",
    "set_install_date": "projects.manage",
    # Piece 52: the Drafts oversight page -- reuses "approvals" (the same
    # "parental oversight of pending stuff" concept as Wishlist/Work Bag).
    "drafts_page": "approvals",
    "approve_draft": "approvals",
    "discard_draft": "approvals",
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


def draftable(kind, ref_id_kwarg=None):
    """Piece 52: stacks under @admin_required. If this is a POST and the
    signed-in user's role is "Assistant" (the account an AI agent runs
    under), capture it as a Pending row in `drafts` instead of writing for
    real -- validating first (via the kind's own capture()) so a clearly-bad
    submission bounces back with the same error a live user would get,
    never becoming a junk draft. Everyone else (and every GET) goes straight
    through to the real view, unchanged."""
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = current_user()
            if request.method == "POST" and user is not None and user["role"] == "Assistant":
                spec = DRAFT_KINDS[kind]
                payload, errors = spec["capture"](**kwargs)
                if errors:
                    flash(" ".join(errors), "error")
                    return redirect(request.referrer or url_for("home"))
                ref_id = kwargs.get(ref_id_kwarg) if ref_id_kwarg else None
                stored_file = spec["save_file"]() if spec.get("save_file") else None
                db = get_db()
                db.execute(
                    "INSERT INTO drafts (kind, ref_id, payload, file_stored_name, created_by)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (kind, ref_id, json.dumps(payload), stored_file, user["id"]))
                db.commit()
                flash("Submitted for review — a parent will approve or discard it on the 🗒 Drafts page.")
                return redirect(url_for("drafts_page"))
            return view(*args, **kwargs)
        return wrapped
    return decorator


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
    pending_drafts = 0
    if has_permission("approvals"):
        try:
            db = get_db()
            pending = db.execute(
                "SELECT COUNT(*) FROM field_submissions WHERE status = 'Pending'"
            ).fetchone()[0]
            # Piece 45: the same "approvals" permission now also covers
            # wishlist requests, so the nav badge reflects both.
            pending += db.execute(
                "SELECT COUNT(*) FROM wishlist_items WHERE status = 'Pending'"
            ).fetchone()[0]
            # Piece 52: Assistant-role drafts, reviewed under the same
            # "approvals" permission but shown as their own nav badge/link.
            pending_drafts = db.execute(
                "SELECT COUNT(*) FROM drafts WHERE status = 'Pending'"
            ).fetchone()[0]
        except Exception:
            pending = 0
            pending_drafts = 0
    return {"current_user": user, "login_active": accounts_exist(),
            "is_admin": _is_admin(), "can": has_permission,
            "help_unlocked": help_section_unlocked,  # Piece 53
            "unread_notifications": unread_notification_count(user),  # Piece 29.3
            "pending_submissions": pending, "pending_drafts": pending_drafts}


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
        "id": p["id"], "name": p["name"], "role": p["role"],
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


def _employee_uses(db, eid):
    uses = []
    n = _count(db, "SELECT COUNT(*) FROM project_tasks WHERE household_member_id = ?", (eid,))
    if n:
        uses.append(f"{n} assigned task(s)")
    n = _count(db, "SELECT COUNT(*) FROM field_submissions WHERE household_member_id = ?", (eid,))
    if n:
        uses.append(f"{n} field-work submission(s)")
    return uses


def _contact_uses(db, hid):
    """Piece 43/45/46: every real FK pointing at a Contact -- this app runs
    with PRAGMA foreign_keys=ON, so deleting a Contact still referenced
    anywhere would raise a raw IntegrityError instead of a friendly
    message. Keep this in sync with every table that gets an
    external_helper_id column."""
    uses = []
    n = _count(db, "SELECT COUNT(*) FROM appointments WHERE external_helper_id = ?", (hid,))
    if n:
        uses.append(f"{n} appointment(s)")
    n = _count(db, "SELECT COUNT(*) FROM wishlist_items WHERE external_helper_id = ?", (hid,))
    if n:
        uses.append(f"{n} wishlist item(s)")
    n = _count(db, "SELECT COUNT(*) FROM household_transactions WHERE external_helper_id = ?", (hid,))
    if n:
        uses.append(f"{n} household transaction(s)")
    return uses


def _inventory_item_uses(db, item_id):
    """Piece 45: wishlist_items.inventory_item_id is a real FK -- same
    FK-safety reasoning as _contact_uses()."""
    n = _count(db, "SELECT COUNT(*) FROM wishlist_items WHERE inventory_item_id = ?", (item_id,))
    return [f"{n} wishlist item(s)"] if n else []


def _loan_account_uses(db, account_id):
    """Piece 54: loan_entries.account_id is a real FK -- same FK-safety
    reasoning as _contact_uses()."""
    n = _count(db, "SELECT COUNT(*) FROM loan_entries WHERE account_id = ?", (account_id,))
    return [f"{n} ledger entr{'y' if n == 1 else 'ies'}"] if n else []


def _savings_account_uses(db, account_id):
    n = _count(db, "SELECT COUNT(*) FROM savings_entries WHERE account_id = ?", (account_id,))
    return [f"{n} ledger entr{'y' if n == 1 else 'ies'}"] if n else []


# entity_type -> how to label it, where it lived, what would block its delete,
# and (for file rows) where its file sits on disk.
TRASH_REGISTRY = {
    "rule": {"table": "resource_rules", "label": lambda r: r["label"],
             "found_in": lambda db, r: "Rules",
             "in_use": lambda db, r: (
                 [f"{_count(db, 'SELECT COUNT(*) FROM project_files WHERE rule_label = ?', (r['label'],))} filed document(s)"]
                 if _count(db, "SELECT COUNT(*) FROM project_files WHERE rule_label = ?", (r["label"],)) else [])},
    "material": {"table": "project_materials", "label": lambda r: r["item"],
                 "found_in": lambda db, r: f"{_project_name(db, r['project_id'])} — Materials",
                 "in_use": lambda db, r: []},
    "task": {"table": "project_tasks", "label": lambda r: r["title"],
             "found_in": lambda db, r: f"{_project_name(db, r['project_id'])} — Tasks",
             "in_use": lambda db, r: (
                 [f"{_count(db, 'SELECT COUNT(*) FROM field_submission_items WHERE task_id = ?', (r['id'],))} field submission(s)"]
                 if _count(db, "SELECT COUNT(*) FROM field_submission_items WHERE task_id = ?", (r["id"],)) else [])},
    "project_file": {"table": "project_files", "label": lambda r: r["original_name"],
                 "found_in": lambda db, r: f"{_project_name(db, r['project_id'])} — Documents",
                 "in_use": lambda db, r: [],
                 "file": lambda r: UPLOADS_DIR / f"job_{r['project_id']}" / r["stored_name"]},
    "household_file": {"table": "household_files", "label": lambda r: r["original_name"],
                       "found_in": lambda db, r: "Household Files",
                       "in_use": lambda db, r: [],
                       "file": lambda r: UPLOADS_DIR / "household" / r["stored_name"]},
    "household_transaction": {"table": "household_transactions",
                              "label": lambda r: r["description"] or r["category"] or r["kind"],
                              "found_in": lambda db, r: "Budget",
                              "in_use": lambda db, r: [],
                              # receipt_filename may be blank (no receipt attached) --
                              # unlink(missing_ok=True) on purge_trash() no-ops fine either way.
                              "file": lambda r: UPLOADS_DIR / "household" / (r["receipt_filename"] or "")},
    "loan_account": {"table": "loan_accounts", "label": lambda r: r["name"],
                     "found_in": lambda db, r: "Loans",
                     "in_use": lambda db, r: _loan_account_uses(db, r["id"])},
    "loan_entry": {"table": "loan_entries", "label": lambda r: r["description"] or r["kind"],
                  "found_in": lambda db, r: "Loans", "in_use": lambda db, r: [],
                  "file": lambda r: UPLOADS_DIR / "household" / (r["statement_filename"] or "")},
    "savings_account": {"table": "savings_accounts", "label": lambda r: r["name"],
                        "found_in": lambda db, r: "Savings",
                        "in_use": lambda db, r: _savings_account_uses(db, r["id"])},
    "savings_entry": {"table": "savings_entries", "label": lambda r: r["description"] or r["kind"],
                      "found_in": lambda db, r: "Savings", "in_use": lambda db, r: [],
                      "file": lambda r: UPLOADS_DIR / "household" / (r["statement_filename"] or "")},
    "household_budget": {"table": "household_budgets", "label": lambda r: r["category"],
                        "found_in": lambda db, r: "Budget",
                        "in_use": lambda db, r: []},
    "household_idea": {"table": "household_ideas", "label": lambda r: r["name"],
                       "found_in": lambda db, r: "Backlog",
                       "in_use": lambda db, r: []},
    "routine_task": {"table": "routine_tasks", "label": lambda r: r["title"],
                     "found_in": lambda db, r: "Chores",
                     "in_use": lambda db, r: []},
    "appointment": {"table": "appointments", "label": lambda r: r["title"],
                    "found_in": lambda db, r: "Appointments",
                    "in_use": lambda db, r: []},
    "wishlist_item": {"table": "wishlist_items", "label": lambda r: r["title"],
                      "found_in": lambda db, r: "Wishlist",
                      "in_use": lambda db, r: []},
    "external_helper": {"table": "external_helpers", "label": lambda r: r["name"],
                        "found_in": lambda db, r: "Contacts",
                        "in_use": lambda db, r: _contact_uses(db, r["id"])},
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
                       "in_use": lambda db, r: _inventory_item_uses(db, r["id"])},
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
            cur = db.execute("INSERT INTO household_members (name, role, is_admin)"
                             " VALUES (?, ?, ?)", (name, role, "1" if admin else ""))
            _seed_role_default_grants(db, cur.lastrowid, role)
    db.execute("INSERT INTO meta (key, value) VALUES ('org_team_seeded', '1')"
               " ON CONFLICT(key) DO UPDATE SET value = excluded.value")
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
                    "base_amount", "extras_amount", "bom_snapshot"])
    # Piece 27.9: per-task time split by pay type (+ its work date) carried on a
    # field-submission item, so approving a completed task posts Pending payroll
    # entries (one per pay-type segment) for Finance to approve.
    ensure_columns(db, "field_submission_items", ["hours_json", "work_date"])
    # Piece 21.7: tie crew-captured field photos back to the task they document.
    ensure_columns(db, "project_files", ["task_id"])
    # Piece 26.2: link a receipt photo to its ledger transaction (bookkeeping).
    ensure_columns(db, "project_files", ["txn_id"])
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
    # Piece 53: help.full_access is new to ROLE_DEFAULT_PERMISSIONS --
    # _seed_role_default_grants only fires at member-creation/role-change
    # time, so an already-existing Parent/Assistant needs a one-time
    # backfill. Additive-only, like _seed_role_default_grants itself; a
    # no-op on a fresh database (no members yet).
    if not db.execute("SELECT 1 FROM meta WHERE key = 'help_full_access_v1'").fetchone():
        # init_db()'s connection is a plain sqlite3.connect() with no
        # row_factory (unlike get_db()'s per-request connection) -- rows
        # here are bare tuples, not Row objects (see legacy_tables/row[0]
        # above), so _seed_role_default_grants (which expects Row-style
        # access) can't be called directly; its additive-only logic is
        # duplicated here in tuple-safe form instead.
        for member_id, role in db.execute(
                "SELECT id, role FROM household_members"
                " WHERE role IN ('Parent', 'Assistant')").fetchall():
            existing = {row[0] for row in db.execute(
                "SELECT permission FROM permission_grants"
                " WHERE household_member_id = ?", (member_id,)).fetchall()}
            for perm in ROLE_DEFAULT_PERMISSIONS.get(role, []):
                if perm not in existing:
                    db.execute(
                        "INSERT INTO permission_grants (household_member_id, permission,"
                        " granted_by) VALUES (?, ?, ?)", (member_id, perm, "role default"))
        db.execute("INSERT INTO meta (key, value) VALUES ('help_full_access_v1', '1')"
                   " ON CONFLICT(key) DO UPDATE SET value = excluded.value")
        db.commit()
    # Piece 54: a real Outstanding/Paid status on household_transactions
    # (matching project_transactions' exact vocabulary) so "unpaid expenses"
    # can combine both ledgers. Added directly (not via ensure_columns(),
    # which always defaults a new column to '') -- existing rows default to
    # 'Paid' so nothing already logged retroactively becomes "unpaid". A
    # fresh install's schema.sql-created table already has this column, so
    # this is a no-op there (caught by the except).
    try:
        db.execute("ALTER TABLE household_transactions ADD COLUMN status"
                   " TEXT NOT NULL DEFAULT 'Paid'")
    except sqlite3.OperationalError:
        pass
    ensure_columns(db, "resource_rules",
                   ["field_name2", "field_value2", "match_type2", "link_text"])
    # Piece 26.9: verbatim source text for a rule (esp. a prerequisite) — the exact
    # wording from the code/source, shown above the shorthand in the Requirements Library.
    ensure_columns(db, "resource_rules", ["source_text"])
    # Piece 30.1: the ⚠ Verify / ⚠ Unverified callout is an explicit editable
    # field now (was inferred from caution words in the notes).
    ensure_columns(db, "resource_rules", ["verify_status"])
    # Piece 38: optional descriptive fields (time/cost/upkeep, informational
    # only) plus the columns a "standalone" requirement needs — one with no
    # project field_name, reminded on its own recurrence like a Chore.
    ensure_columns(db, "resource_rules",
                   ["est_cost", "est_time", "maintenance_note",
                    "household_member_id", "recurrence_days", "next_due",
                    "last_completed_at", "last_completed_by", "reminder_sent"])
    # Piece 38: License/Compliance were the solar-shop's category names;
    # remap any pre-existing rows so they land under a heading that still
    # exists (RULE_CATEGORIES no longer has "License"/"Compliance").
    if not db.execute(
            "SELECT 1 FROM meta WHERE key = 'rule_category_relabel_v1'").fetchone():
        db.execute("UPDATE resource_rules SET category = 'Certification'"
                   " WHERE category = 'License'")
        db.execute("UPDATE resource_rules SET category = 'Prerequisite'"
                   " WHERE category = 'Compliance'")
        db.execute("INSERT INTO meta (key, value) VALUES"
                   " ('rule_category_relabel_v1', '1')"
                   " ON CONFLICT(key) DO UPDATE SET value = excluded.value")
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
    seed_org_team(db)
    # Piece 30.2: cancellation (Abandoned) metadata — reason, who/when, and the
    # stage to restore on reopen.
    ensure_columns(db, "projects", ["cancel_reason", "cancelled_at", "cancelled_by",
                                    "pre_lost_status"])
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
    # Piece 36: barcode/asset-tag scanning is cut (built for a multi-person crew
    # truck-loading parts — doesn't fit household scale). Drop its tables from
    # any existing database; a no-op on a genuinely fresh one.
    if not db.execute("SELECT 1 FROM meta WHERE key = 'barcode_scanning_removed_v1'").fetchone():
        for legacy_table in ("inventory_assets", "stock_audits", "stock_audit_scans"):
            db.execute(f"DROP TABLE IF EXISTS {legacy_table}")
        db.execute("INSERT INTO meta (key, value) VALUES ('barcode_scanning_removed_v1', '1')"
                   " ON CONFLICT(key) DO UPDATE SET value = excluded.value")
        db.commit()
    # Piece 40 Part B: Loads & Sizing (a PV/battery/inverter electrical-sizing
    # calculator) and the Cost Model/GRT pricing system both priced/sized a job
    # for the original solar business — cut entirely; a household budget just
    # needs the plain contract-total + income/expense ledger that survives.
    # Drop their tables from any existing database; a no-op on a fresh one.
    if not db.execute("SELECT 1 FROM meta WHERE key = 'loads_and_cost_model_removed_v1'").fetchone():
        for legacy_table in ("appliance_catalog", "component_catalog",
                              "project_load_rooms", "project_load_items",
                              "project_bom", "project_sizing", "county_tax_rates",
                              "markup_categories", "cost_model_lines",
                              "project_estimate_lines"):
            db.execute(f"DROP TABLE IF EXISTS {legacy_table}")
        for col in ("grt_rate", "deposit_bom_cutoff_id", "travel_miles"):
            try:
                db.execute(f"ALTER TABLE projects DROP COLUMN {col}")
            except sqlite3.OperationalError:
                pass
        for col in ("grt_rate", "grt_amount"):
            try:
                db.execute(f"ALTER TABLE project_transactions DROP COLUMN {col}")
            except sqlite3.OperationalError:
                pass
        db.execute("INSERT INTO meta (key, value) VALUES"
                   " ('loads_and_cost_model_removed_v1', '1')"
                   " ON CONFLICT(key) DO UPDATE SET value = excluded.value")
        db.commit()
    # Piece 41 Part B: the Project form's remaining solar-sale fields (county/
    # electric_loads/utility_provider/warranty_type/cost_method/tax_credit/
    # expand_option/products + PV-Generator-Battery variants/service_type/
    # property_type) had nothing left to serve once Part A dropped the
    # install-job pipeline gating and the 145 solar-permit resource_rules
    # keyed to them were slated for a Part C purge — drop the columns from
    # any existing database; a no-op on a fresh one.
    if not db.execute("SELECT 1 FROM meta WHERE key = 'project_solar_fields_removed_v1'").fetchone():
        for col in ("county", "electric_loads", "utility_provider",
                    "warranty_type", "cost_method", "tax_credit", "expand_option",
                    "products", "pv_utility_connection", "pv_mounting_type",
                    "pv_manufactured_house", "generator_utility_connection",
                    "battery_utility_connection", "service_type", "property_type"):
            try:
                db.execute(f"ALTER TABLE projects DROP COLUMN {col}")
            except sqlite3.OperationalError:
                pass
        db.execute("INSERT INTO meta (key, value) VALUES"
                   " ('project_solar_fields_removed_v1', '1')"
                   " ON CONFLICT(key) DO UPDATE SET value = excluded.value")
        db.commit()
    # Piece 41 Part C: purge resource_rules left over from the original solar
    # business — permit/interconnection rules keyed to the fields Part B just
    # dropped (county/utility_provider/products/property_type/PV-Generator-
    # Battery variants/etc.). Confirmed every existing rule in the household's
    # database matched one of these fields (100% solar-permit data, none of
    # it relevant to a household project) — purge outright rather than leave
    # dead rows an admin has to notice and clean up by hand. A rule the
    # household adds later against project_category/project_type/site_location
    # is untouched (this only ever runs once, gated by the meta key below).
    if not db.execute("SELECT 1 FROM meta WHERE key = 'legacy_solar_rules_purged_v1'").fetchone():
        legacy_fields = (
            "county", "electric_loads", "utility_provider", "warranty_type",
            "cost_method", "tax_credit", "expand_option", "products",
            "pv_utility_connection", "pv_mounting_type", "pv_manufactured_house",
            "generator_utility_connection", "battery_utility_connection",
            "service_type", "property_type",
        )
        placeholders = ",".join("?" * len(legacy_fields))
        db.execute(
            f"DELETE FROM resource_rules WHERE field_name IN ({placeholders})"
            f" OR field_name2 IN ({placeholders})",
            legacy_fields + legacy_fields)
        db.execute("INSERT INTO meta (key, value) VALUES"
                   " ('legacy_solar_rules_purged_v1', '1')"
                   " ON CONFLICT(key) DO UPDATE SET value = excluded.value")
        db.commit()
    # Piece 41 Part D: Inventory rehaul. The categories/spec-field system
    # (INVENTORY_CATEGORY_SPECS), the needed/available/on-PO stock model, the
    # inventory_txns ledger, and the managed inventory_vendors entity all
    # existed to serve the original solar-parts catalog and a crew consuming
    # parts across jobs -- a household just wants "I have this or I don't."
    # Purge the legacy catalog (confirmed every row is 0-available/0-needed
    # solar-business reference data, not real household stock -- 439 items /
    # 49 tools / 11 vehicles / 52 vendors in the household's real database),
    # add the new minimal columns, and drop the old ones + the ledger/vendor
    # tables. A no-op on a fresh install.
    if not db.execute("SELECT 1 FROM meta WHERE key = 'inventory_rehaul_v1'").fetchone():
        for tbl in ("inventory_items", "inventory_tools", "inventory_vehicles"):
            db.execute(f"DELETE FROM {tbl}")
        ensure_columns(db, "inventory_items", ["purchased_from", "notes"])
        # quantity is numeric -- add it directly rather than via
        # ensure_columns() (which always adds TEXT columns, which would make
        # every quantity value a string on a migrated database).
        try:
            db.execute(
                "ALTER TABLE inventory_items ADD COLUMN quantity"
                " INTEGER NOT NULL DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        ensure_columns(db, "inventory_tools", ["purchased_from"])
        ensure_columns(db, "inventory_vehicles", ["purchased_from"])
        for col in ("vendor_id", "vendor_number", "web_price", "price_checked_on",
                    "needed", "available", "on_po", "status", "last_used",
                    "specs", "flags", "stock_reviewed_on", "stale_flag"):
            try:
                db.execute(f"ALTER TABLE inventory_items DROP COLUMN {col}")
            except sqlite3.OperationalError:
                pass
        for col in ("vendor_id", "needed", "available"):
            try:
                db.execute(f"ALTER TABLE inventory_tools DROP COLUMN {col}")
            except sqlite3.OperationalError:
                pass
        try:
            db.execute("ALTER TABLE inventory_vehicles DROP COLUMN vendor_id")
        except sqlite3.OperationalError:
            pass
        db.execute("DROP TABLE IF EXISTS inventory_txns")
        db.execute("DROP TABLE IF EXISTS inventory_vendors")
        db.execute("INSERT INTO meta (key, value) VALUES"
                   " ('inventory_rehaul_v1', '1')"
                   " ON CONFLICT(key) DO UPDATE SET value = excluded.value")
        db.commit()
    # Piece 43: broaden external_helpers ("Contacts") to also cover
    # organizations, and let an appointment link to a contact. Purely
    # additive -- no meta guard needed, ensure_columns() is already
    # idempotent and the FK column below just needs its own try/except.
    ensure_columns(db, "external_helpers",
                   ["kind", "website", "account_number", "contact_person",
                    "contact_phone", "contact_email", "renewal_date"])
    db.execute("UPDATE external_helpers SET kind = 'Person'"
               " WHERE COALESCE(kind, '') = ''")
    try:
        db.execute("ALTER TABLE appointments ADD COLUMN external_helper_id INTEGER")
    except sqlite3.OperationalError:
        pass
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
    """Piece 26.9: the Requirements Library view. Collapse every rule that shares a
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


# ------------------------------------------------------------------- Piece 37: chores
CHORE_RECURRENCE_PRESETS = [(1, "Daily"), (7, "Weekly"), (14, "Every 2 weeks"),
                            (30, "Monthly")]


def _notify_chore_assignee(db, title, assignee_id, actor):
    """Tell a household member a chore was assigned to them (skip self / login-less)."""
    if not assignee_id or (actor and actor["id"] == assignee_id):
        return
    row = db.execute("SELECT COALESCE(username,'') AS u FROM household_members WHERE id = ?",
                     (assignee_id,)).fetchone()
    if not row or not row["u"]:
        return
    notify_employees(
        db, [assignee_id],
        f"🔁 Chore assigned to you: “{title}”"
        + (f" — from {actor['name']}" if actor else "") + ".",
        link=url_for("chores_page"), kind="chore")


@app.route("/chores")
def chores_page():
    """The Chores list — recurring household tasks, not tied to a project.
    Filter by assignee (mine / unassigned / a person / all)."""
    db = get_db()
    me = current_user()
    who = request.args.get("who", "mine" if me else "all")
    sql = ("SELECT c.*, e.name AS assignee_name FROM routine_tasks c"
           " LEFT JOIN household_members e ON e.id = c.household_member_id WHERE 1 = 1")
    params = []
    if who == "mine" and me:
        sql += " AND c.household_member_id = ?"
        params.append(me["id"])
    elif who == "unassigned":
        sql += " AND c.household_member_id IS NULL"
    elif who.isdigit():
        sql += " AND c.household_member_id = ?"
        params.append(int(who))
    sql += " ORDER BY (c.next_due = ''), c.next_due, c.id"
    chores = db.execute(sql, params).fetchall()
    employees = db.execute(
        "SELECT id, name FROM household_members ORDER BY name").fetchall()
    edit_id = request.args.get("edit", type=int)
    edit_chore = db.execute(
        "SELECT * FROM routine_tasks WHERE id = ?", (edit_id,)
    ).fetchone() if edit_id else None
    return render_template("chores.html", chores=chores, employees=employees,
                           who=who, edit_chore=edit_chore,
                           recurrence_presets=CHORE_RECURRENCE_PRESETS,
                           today=datetime.now().strftime("%Y-%m-%d"))


def _chore_form_values():
    assignee = request.form.get("household_member_id", "")
    days = int(_to_float(request.form.get("recurrence_days")) or 7)
    return {
        "title": request.form.get("title", "").strip(),
        "notes": request.form.get("notes", "").strip(),
        "household_member_id": int(assignee) if assignee.isdigit() else None,
        "recurrence_days": max(1, days),
        "next_due": request.form.get("next_due", "").strip()
                   or datetime.now().strftime("%Y-%m-%d"),
    }


@app.route("/chores/new", methods=["POST"])
def chore_new():
    values = _chore_form_values()
    if not values["title"]:
        flash("A chore needs a title.", "error")
        return redirect(url_for("chores_page"))
    db = get_db()
    me = current_user()
    cur = db.execute(
        "INSERT INTO routine_tasks (title, notes, household_member_id,"
        " recurrence_days, next_due, created_by) VALUES (?, ?, ?, ?, ?, ?)",
        (values["title"], values["notes"], values["household_member_id"],
         values["recurrence_days"], values["next_due"], me["name"] if me else ""))
    _notify_chore_assignee(db, values["title"], values["household_member_id"], me)
    db.commit()
    flash(f"Chore added: {values['title']}")
    return redirect(url_for("chores_page"))


@app.route("/chores/<int:chore_id>/edit", methods=["POST"])
def chore_edit(chore_id):
    db = get_db()
    chore = db.execute("SELECT * FROM routine_tasks WHERE id = ?",
                       (chore_id,)).fetchone()
    if chore is None:
        abort(404)
    values = _chore_form_values()
    if not values["title"]:
        flash("A chore needs a title.", "error")
        return redirect(url_for("chores_page", edit=chore_id))
    me = current_user()
    db.execute(
        "UPDATE routine_tasks SET title = ?, notes = ?, household_member_id = ?,"
        " recurrence_days = ?, next_due = ? WHERE id = ?",
        (values["title"], values["notes"], values["household_member_id"],
         values["recurrence_days"], values["next_due"], chore_id))
    if values["household_member_id"] != chore["household_member_id"]:
        _notify_chore_assignee(db, values["title"], values["household_member_id"], me)
    db.commit()
    flash(f"Chore updated: {values['title']}")
    return redirect(url_for("chores_page"))


@app.route("/chores/<int:chore_id>/done", methods=["POST"])
def chore_done(chore_id):
    db = get_db()
    chore = db.execute("SELECT * FROM routine_tasks WHERE id = ?",
                       (chore_id,)).fetchone()
    if chore is None:
        abort(404)
    me = current_user()
    today = datetime.now()
    next_due = (today + timedelta(days=chore["recurrence_days"])).strftime("%Y-%m-%d")
    db.execute(
        "UPDATE routine_tasks SET last_completed_at = ?, last_completed_by = ?,"
        " next_due = ?, reminder_sent = '' WHERE id = ?",
        (today.strftime("%Y-%m-%d"), me["name"] if me else "", next_due, chore_id))
    db.commit()
    flash(f"Marked done: {chore['title']} — next due {next_due}.")
    return redirect(url_for("chores_page"))


@app.route("/chores/<int:chore_id>/delete", methods=["POST"])
@delete_required
def chore_delete(chore_id):
    ok, msg = trash_item("routine_task", chore_id)
    flash(msg, "" if ok else "error")
    return redirect(url_for("chores_page"))


# ------------------------------------------------------------- appointments
# Piece 42: a scheduled date+time, not tied to a project and not always-
# recurring like Chores. "One-time" (0 days) is the default — most
# appointments happen once; recurring ones (checkups, etc.) use the same
# mark-done-advances-the-date cadence Chores already use.
APPOINTMENT_RECURRENCE_PRESETS = [
    (0, "One-time"), (1, "Daily"), (7, "Weekly"), (30, "Monthly"),
    (182, "Every 6 months"), (365, "Yearly"),
]


def _notify_appointment_assignee(db, title, assignee_id, actor):
    """Tell a household member an appointment was assigned to them (skip self / login-less)."""
    if not assignee_id or (actor and actor["id"] == assignee_id):
        return
    row = db.execute("SELECT COALESCE(username,'') AS u FROM household_members WHERE id = ?",
                     (assignee_id,)).fetchone()
    if not row or not row["u"]:
        return
    notify_employees(db, [assignee_id], f"📅 Appointment assigned to you: {title}",
                     link="/appointments", kind="appointment")


@app.route("/appointments")
def appointments_page():
    """The Appointments list — scheduled dates/times, not tied to a project.
    Filter by assignee (mine / unassigned / a person / all) and by
    upcoming-vs-all (one-time appointments drop off the upcoming view once
    marked done). ?prefill_contact=<id> pre-fills the add form from a
    Contact's "＋ Add appointment" quick-link."""
    db = get_db()
    me = current_user()
    who = request.args.get("who", "mine" if me else "all")
    show = request.args.get("show", "upcoming")
    sql = ("SELECT a.*, e.name AS assignee_name, h.name AS contact_name"
           " FROM appointments a"
           " LEFT JOIN household_members e ON e.id = a.household_member_id"
           " LEFT JOIN external_helpers h ON h.id = a.external_helper_id"
           " WHERE 1 = 1")
    params = []
    if who == "mine" and me:
        sql += " AND a.household_member_id = ?"
        params.append(me["id"])
    elif who == "unassigned":
        sql += " AND a.household_member_id IS NULL"
    elif who.isdigit():
        sql += " AND a.household_member_id = ?"
        params.append(int(who))
    if show != "all":
        sql += " AND COALESCE(a.completed_at, '') = ''"
    sql += " ORDER BY (a.when_date = ''), a.when_date, a.when_time, a.id"
    appointments = db.execute(sql, params).fetchall()
    employees = db.execute(
        "SELECT id, name FROM household_members ORDER BY name").fetchall()
    contacts = db.execute(
        "SELECT id, name FROM external_helpers ORDER BY name").fetchall()
    edit_id = request.args.get("edit", type=int)
    edit_appt = db.execute(
        "SELECT * FROM appointments WHERE id = ?", (edit_id,)
    ).fetchone() if edit_id else None
    prefill = None
    prefill_contact_id = request.args.get("prefill_contact", type=int)
    if prefill_contact_id and not edit_appt:
        contact = db.execute("SELECT * FROM external_helpers WHERE id = ?",
                             (prefill_contact_id,)).fetchone()
        if contact:
            prefill = {"title": f"Appointment — {contact['name']}",
                      "external_helper_id": contact["id"]}
    return render_template(
        "appointments.html", appointments=appointments, employees=employees,
        contacts=contacts, who=who, show=show, edit_appt=edit_appt,
        prefill=prefill, recurrence_presets=APPOINTMENT_RECURRENCE_PRESETS,
        today=datetime.now().strftime("%Y-%m-%d"))


def _appointment_form_values():
    assignee = request.form.get("household_member_id", "")
    contact = request.form.get("external_helper_id", "")
    days = int(_to_float(request.form.get("recurrence_days")) or 0)
    return {
        "title": request.form.get("title", "").strip(),
        "location": request.form.get("location", "").strip(),
        "notes": request.form.get("notes", "").strip(),
        "household_member_id": int(assignee) if assignee.isdigit() else None,
        "external_helper_id": int(contact) if contact.isdigit() else None,
        "recurrence_days": max(0, days),
        "when_date": request.form.get("when_date", "").strip()
                    or datetime.now().strftime("%Y-%m-%d"),
        "when_time": request.form.get("when_time", "").strip(),
    }


@app.route("/appointments/new", methods=["POST"])
def appointment_new():
    values = _appointment_form_values()
    if not values["title"]:
        flash("An appointment needs a title.", "error")
        return redirect(url_for("appointments_page"))
    db = get_db()
    me = current_user()
    db.execute(
        "INSERT INTO appointments (title, location, notes, household_member_id,"
        " external_helper_id, recurrence_days, when_date, when_time, created_by)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (values["title"], values["location"], values["notes"],
         values["household_member_id"], values["external_helper_id"],
         values["recurrence_days"], values["when_date"], values["when_time"],
         me["name"] if me else ""))
    _notify_appointment_assignee(db, values["title"], values["household_member_id"], me)
    db.commit()
    flash(f"Appointment added: {values['title']}")
    return redirect(url_for("appointments_page"))


@app.route("/appointments/<int:appt_id>/edit", methods=["POST"])
def appointment_edit(appt_id):
    db = get_db()
    appt = db.execute("SELECT * FROM appointments WHERE id = ?",
                      (appt_id,)).fetchone()
    if appt is None:
        abort(404)
    values = _appointment_form_values()
    if not values["title"]:
        flash("An appointment needs a title.", "error")
        return redirect(url_for("appointments_page", edit=appt_id))
    me = current_user()
    db.execute(
        "UPDATE appointments SET title = ?, location = ?, notes = ?,"
        " household_member_id = ?, external_helper_id = ?, recurrence_days = ?,"
        " when_date = ?, when_time = ? WHERE id = ?",
        (values["title"], values["location"], values["notes"],
         values["household_member_id"], values["external_helper_id"],
         values["recurrence_days"], values["when_date"], values["when_time"],
         appt_id))
    if values["household_member_id"] != appt["household_member_id"]:
        _notify_appointment_assignee(db, values["title"], values["household_member_id"], me)
    db.commit()
    flash(f"Appointment updated: {values['title']}")
    return redirect(url_for("appointments_page"))


@app.route("/appointments/<int:appt_id>/done", methods=["POST"])
def appointment_done(appt_id):
    db = get_db()
    appt = db.execute("SELECT * FROM appointments WHERE id = ?",
                      (appt_id,)).fetchone()
    if appt is None:
        abort(404)
    me = current_user()
    today = datetime.now()
    if appt["recurrence_days"]:
        next_due = (today + timedelta(days=appt["recurrence_days"])).strftime("%Y-%m-%d")
        db.execute(
            "UPDATE appointments SET when_date = ?, reminder_sent = '' WHERE id = ?",
            (next_due, appt_id))
        db.commit()
        flash(f"Marked done: {appt['title']} — next due {next_due}.")
    else:
        db.execute(
            "UPDATE appointments SET completed_at = ?, completed_by = ? WHERE id = ?",
            (today.strftime("%Y-%m-%d"), me["name"] if me else "", appt_id))
        db.commit()
        flash(f"Marked done: {appt['title']}.")
    return redirect(url_for("appointments_page"))


@app.route("/appointments/<int:appt_id>/delete", methods=["POST"])
@delete_required
def appointment_delete(appt_id):
    ok, msg = trash_item("appointment", appt_id)
    flash(msg, "" if ok else "error")
    return redirect(url_for("appointments_page"))


# ------------------------------------------------------------------ wishlist
# Piece 45: a per-household-member wishlist. Submitted by anyone, sitting as
# Pending until a Parent/Admin (the "approvals" permission -- the same one
# that already gates Work Bag field-submission approvals) approves or
# rejects it. Approval does nothing automatic; it's purely a household
# "yes, go ahead and buy this" signal.
@app.route("/wishlist")
def wishlist_page():
    """The Wishlist — filter by whose list (mine/all/unassigned/a person)
    and by pending-vs-all (approved/rejected items drop off the default
    pending view). ?prefill_item=<id> pre-fills the add form from an
    Inventory item's "🎁 Add to wishlist" quick-link."""
    db = get_db()
    me = current_user()
    who = request.args.get("who", "mine" if me else "all")
    show = request.args.get("show", "pending")
    sql = ("SELECT w.*, e.name AS assignee_name, i.category AS inv_category,"
           " i.make AS inv_make, i.model AS inv_model,"
           " p.job_name AS project_name, h.name AS contact_name"
           " FROM wishlist_items w"
           " LEFT JOIN household_members e ON e.id = w.household_member_id"
           " LEFT JOIN inventory_items i ON i.id = w.inventory_item_id"
           " LEFT JOIN projects p ON p.id = w.project_id"
           " LEFT JOIN external_helpers h ON h.id = w.external_helper_id"
           " WHERE 1 = 1")
    params = []
    if who == "mine" and me:
        sql += " AND w.household_member_id = ?"
        params.append(me["id"])
    elif who.isdigit():
        sql += " AND w.household_member_id = ?"
        params.append(int(who))
    if show != "all":
        sql += " AND w.status = 'Pending'"
    sql += " ORDER BY (w.status = 'Pending') DESC, w.created_at DESC"
    items = db.execute(sql, params).fetchall()
    employees = db.execute(
        "SELECT id, name FROM household_members ORDER BY name").fetchall()
    inventory_items = db.execute(
        "SELECT id, category, make, model FROM inventory_items"
        " WHERE active = 1 ORDER BY category, make, model").fetchall()
    projects = db.execute(
        "SELECT id, job_name FROM projects WHERE status != 'Abandoned'"
        " ORDER BY id DESC").fetchall()
    contacts = db.execute(
        "SELECT id, name FROM external_helpers ORDER BY name").fetchall()
    edit_id = request.args.get("edit", type=int)
    edit_item = db.execute(
        "SELECT * FROM wishlist_items WHERE id = ?", (edit_id,)
    ).fetchone() if edit_id else None
    prefill = None
    prefill_item_id = request.args.get("prefill_item", type=int)
    if prefill_item_id and not edit_item:
        src = db.execute("SELECT * FROM inventory_items WHERE id = ?",
                          (prefill_item_id,)).fetchone()
        if src:
            label = (f"{src['make']} {src['model']}".strip()
                      or src["category"] or "item")
            prefill = {"title": f"More {label}",
                       "inventory_item_id": src["id"]}
    return render_template(
        "wishlist.html", items=items, employees=employees,
        inventory_items=inventory_items, projects=projects, contacts=contacts,
        who=who, show=show, edit_item=edit_item, prefill=prefill)


def _wishlist_form_values():
    assignee = request.form.get("household_member_id", "")
    inv = request.form.get("inventory_item_id", "")
    proj = request.form.get("project_id", "")
    contact = request.form.get("external_helper_id", "")
    me = current_user()
    return {
        "title": request.form.get("title", "").strip(),
        "description": request.form.get("description", "").strip(),
        "estimated_cost": _to_float(request.form.get("estimated_cost")),
        "purchase_url": request.form.get("purchase_url", "").strip(),
        "household_member_id": int(assignee) if assignee.isdigit()
                              else (me["id"] if me else None),
        "inventory_item_id": int(inv) if inv.isdigit() else None,
        "project_id": int(proj) if proj.isdigit() else None,
        "external_helper_id": int(contact) if contact.isdigit() else None,
    }


@app.route("/wishlist/new", methods=["POST"])
def wishlist_new():
    v = _wishlist_form_values()
    if not v["title"]:
        flash("A wishlist item needs a title.", "error")
        return redirect(url_for("wishlist_page"))
    if not v["household_member_id"]:
        flash("Sign in to add to a wishlist.", "error")
        return redirect(url_for("wishlist_page"))
    db = get_db()
    db.execute(
        "INSERT INTO wishlist_items (household_member_id, title, description,"
        " estimated_cost, purchase_url, inventory_item_id, project_id,"
        " external_helper_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (v["household_member_id"], v["title"], v["description"],
         v["estimated_cost"], v["purchase_url"], v["inventory_item_id"],
         v["project_id"], v["external_helper_id"]))
    db.commit()
    flash(f"Added to the wishlist: {v['title']}")
    return redirect(url_for("wishlist_page"))


@app.route("/wishlist/<int:item_id>/edit", methods=["POST"])
def wishlist_edit(item_id):
    db = get_db()
    if db.execute("SELECT 1 FROM wishlist_items WHERE id = ?",
                  (item_id,)).fetchone() is None:
        abort(404)
    v = _wishlist_form_values()
    if not v["title"]:
        flash("A wishlist item needs a title.", "error")
        return redirect(url_for("wishlist_page", edit=item_id))
    db.execute(
        "UPDATE wishlist_items SET household_member_id = ?, title = ?,"
        " description = ?, estimated_cost = ?, purchase_url = ?,"
        " inventory_item_id = ?, project_id = ?, external_helper_id = ?"
        " WHERE id = ?",
        (v["household_member_id"], v["title"], v["description"],
         v["estimated_cost"], v["purchase_url"], v["inventory_item_id"],
         v["project_id"], v["external_helper_id"], item_id))
    db.commit()
    flash(f"Updated: {v['title']}")
    return redirect(url_for("wishlist_page"))


def _apply_wishlist_review(db, payload, ref_id, actor_name, draft_file_stored_name=None, exclude_id=None):
    cur = db.execute(
        "UPDATE wishlist_items SET status = ?, reviewed_by = ?, reviewed_at = datetime('now')"
        " WHERE id = ? AND status = 'Pending'", (payload["status"], actor_name, ref_id))
    if cur.rowcount == 0:
        return False, "That wishlist item is no longer pending.", None
    return True, f"Wishlist item {payload['status'].lower()}.", None


@app.route("/wishlist/<int:item_id>/approve", methods=["POST"])
@admin_required
@draftable("wishlist.approve", ref_id_kwarg="item_id")
def wishlist_approve(item_id):
    db = get_db()
    who = current_user()
    ok, message, _ = _apply_wishlist_review(
        db, {"status": "Approved"}, item_id, who["name"] if who else "")
    db.commit()
    flash(message, "" if ok else "error")
    return redirect(url_for("wishlist_page"))


@app.route("/wishlist/<int:item_id>/reject", methods=["POST"])
@admin_required
@draftable("wishlist.reject", ref_id_kwarg="item_id")
def wishlist_reject(item_id):
    db = get_db()
    who = current_user()
    ok, message, _ = _apply_wishlist_review(
        db, {"status": "Rejected"}, item_id, who["name"] if who else "")
    db.commit()
    flash(message, "" if ok else "error")
    return redirect(url_for("wishlist_page"))


@app.route("/wishlist/<int:item_id>/delete", methods=["POST"])
@delete_required
def wishlist_delete(item_id):
    ok, msg = trash_item("wishlist_item", item_id)
    flash(msg, "" if ok else "error")
    return redirect(url_for("wishlist_page"))


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


def _bucket_schedule(my_tasks, my_chores, my_appointments, today_d):
    """Piece 53: Child-dashboard widget. Merges this signed-in member's own
    open tasks, chores, and appointments (already fetched + already
    filtered to them by dashboard()'s existing queries) into Today /
    Tomorrow / Next 2 weeks buckets by due/next-due/when date. Undated
    items and anything outside that 14-day window are dropped -- this is a
    glance, not a worklist; the My tasks/My chores/My appointments cards
    below still show everything, including overdue."""
    tomorrow_d = today_d + timedelta(days=1)
    horizon_d = today_d + timedelta(days=14)
    buckets = {"today": [], "tomorrow": [], "soon": []}

    def _add(date_str, icon, kind, title, href, subtitle=""):
        if not date_str:
            return
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return
        if d < today_d or d > horizon_d:
            return
        bucket = "today" if d == today_d else "tomorrow" if d == tomorrow_d else "soon"
        buckets[bucket].append({"date": date_str, "icon": icon, "kind": kind,
                                 "title": title, "href": href, "subtitle": subtitle})

    for t in my_tasks:
        _add(t["due_date"], "✅", "Task", t["title"],
             url_for("project_detail", project_id=t["project_id"], _anchor="tasks"),
             t["job_name"] or "")
    for c in my_chores:
        _add(c["next_due"], "🔁", "Chore", c["title"], url_for("chores_page"))
    for a in my_appointments:
        _add(a["when_date"], "📅", "Appointment", a["title"],
             url_for("appointments_page"), a["location"] or "")
    for key in buckets:
        buckets[key].sort(key=lambda i: i["date"])
    return buckets


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
    today_d = datetime.now().date()
    today_s = today_d.strftime("%Y-%m-%d")
    ensure_backlog_reminders(db)
    ensure_routine_task_reminders(db)
    ensure_requirement_reminders(db)
    ensure_appointment_reminders(db)

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

    # Piece 37: this member's recurring chores, soonest-due first.
    my_chores = []
    if user is not None:
        my_chores = db.execute(
            "SELECT * FROM routine_tasks WHERE household_member_id = ?"
            " ORDER BY (next_due = ''), next_due", (user["id"],)).fetchall()

    # Piece 38: this member's standalone recurring requirements, soonest-due first.
    my_requirements = []
    if user is not None:
        my_requirements = db.execute(
            "SELECT * FROM resource_rules WHERE field_name = ''"
            " AND household_member_id = ?"
            " ORDER BY (next_due = ''), next_due", (user["id"],)).fetchall()

    # Piece 42: this member's upcoming appointments (assigned to them or
    # whole-household), soonest first.
    my_appointments = []
    if user is not None:
        my_appointments = db.execute(
            "SELECT * FROM appointments WHERE COALESCE(completed_at, '') = ''"
            " AND (household_member_id = ? OR household_member_id IS NULL)"
            " ORDER BY (when_date = ''), when_date, when_time", (user["id"],)).fetchall()

    # Piece 53: Child-only day-by-day schedule widget, replacing the
    # household-wide overview on their dashboard.
    schedule_buckets = _bucket_schedule(my_tasks, my_chores, my_appointments, today_d)

    # Active-projects overview: every non-terminal project, grouped by stage
    # (replaces the old per-department project lists).
    active_projects = db.execute(
        "SELECT id, job_name, status, install_date"
        " FROM projects WHERE status NOT IN ('Abandoned', 'Done')"
        " ORDER BY status, id").fetchall()
    by_stage = {}
    for j in active_projects:
        by_stage.setdefault(j["status"], []).append(j)
    sections = [{"name": stage, "icon": STAGE_ICON.get(stage, "📋"),
                 "projects": by_stage[stage]}
                for stage in STAGE_ORDER[:-1] if stage in by_stage]
    # Piece 53: a Child only sees stage-listing cards for projects they
    # actually have a task on -- everyone else sees every active project.
    if user is not None and user["role"] == "Child":
        child_project_ids = {r["project_id"] for r in db.execute(
            "SELECT DISTINCT project_id FROM project_tasks"
            " WHERE household_member_id = ?", (user["id"],)).fetchall()}
        for s in sections:
            s["projects"] = [j for j in s["projects"] if j["id"] in child_project_ids]

    # Progress for every active project.
    progress_by_job = {}
    for j in active_projects:
        progress_by_job[j["id"]] = build_project_progress(db, j)

    # Requirements-filed coverage (X/Y) — Piece 41: shown for any active
    # project with 1+ applicable rules, not gated to a particular stage
    # (that gating was an install-job assumption; a household project can
    # need a permit/certification filed at any stage).
    rules = db.execute("SELECT * FROM resource_rules").fetchall()
    permits_by_job = {}
    for j in active_projects:
        full = db.execute("SELECT * FROM projects WHERE id = ?", (j["id"],)).fetchone()
        permits_by_job[j["id"]] = project_permit_coverage(db, full, rules)

    # Materials/procurement rollup — Piece 41: shown for any active project
    # with 1+ materials on file, not gated to the Prep stage.
    procurement = []
    for j in active_projects:
        counts = {s: 0 for s in MATERIAL_STATUSES}
        total = 0
        for m in db.execute(
                "SELECT status, COUNT(*) AS n FROM project_materials"
                " WHERE project_id = ? GROUP BY status", (j["id"],)).fetchall():
            counts[m["status"]] = counts.get(m["status"], 0) + m["n"]
            total += m["n"]
        if total:
            outstanding = (counts.get("Needed", 0) + counts.get("Quoted", 0)
                           + counts.get("Backordered", 0))
            procurement.append({"project": j, "counts": counts, "total": total,
                                "outstanding": outstanding})

    # Piece 22.3 (revised Piece 35, de-install-ified Piece 41): whole-household
    # snapshot — pipeline counts, money in flight, what needs attention, and a
    # Wrap-up worklist. Shown to every signed-in member, not admin-gated.
    exec_stages = STAGE_ORDER[:-1]           # Planning .. Wrap-up
    counts = {s: 0 for s in exec_stages}
    # Piece 54: reworked from Contract/Collected/Outstanding/Expenses into
    # unpaid expenses/loans/income/savings/money in projects (+ an
    # estimate-vs-actual variance), rolling up both the project and
    # household ledgers -- see the dashboard template for tile rendering.
    money = {"unpaid_expenses": 0.0, "loans": 0.0, "income": 0.0,
             "savings": 0.0, "projects": 0.0,
             "estimated": 0.0, "actual_expense": 0.0}
    for j in db.execute(
            "SELECT id, status, contract_amount, estimated_cost FROM projects"
            " WHERE status != 'Abandoned'").fetchall():
        if j["status"] in counts:
            counts[j["status"]] += 1
        b = project_billing(db, j["id"], j["contract_amount"] or 0.0)
        money["unpaid_expenses"] += b["expense_out"]
        money["income"] += b["collected"]
        money["projects"] += b["contract"]
        money["estimated"] += _to_float(j["estimated_cost"]) or 0.0
        money["actual_expense"] += b["expense"]
    # Fold in the whole-household ledger (lifetime totals, matching
    # project_billing()'s own lifetime -- not month-scoped -- nature; the
    # Budget page's separate current-month view is untouched) and the
    # Loans/Savings accounts' live-computed balances.
    for r in db.execute(
            "SELECT kind, status, COALESCE(SUM(amount), 0) AS total"
            " FROM household_transactions GROUP BY kind, status").fetchall():
        if r["kind"] == "Income":
            money["income"] += r["total"]
        elif r["kind"] == "Expense" and r["status"] == "Outstanding":
            money["unpaid_expenses"] += r["total"]
    for a in db.execute("SELECT id, original_amount FROM loan_accounts").fetchall():
        money["loans"] += loan_balance(db, a["id"], a["original_amount"])["balance"]
    for a in db.execute("SELECT id FROM savings_accounts").fetchall():
        money["savings"] += savings_balance(db, a["id"])["balance"]
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
    closing_jobs = _closing_worklist(db)
    gm = {"counts": [(s, counts[s]) for s in exec_stages], "money": money,
          "approvals": db.execute(
              "SELECT COUNT(*) FROM field_submissions"
              " WHERE status = 'Pending'").fetchone()[0],
          "overdue": overdue, "stalled": stalled, "closing": closing_jobs}

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
    return render_template(
        "dashboard.html", user=user,
        task_groups=task_groups, my_chores=my_chores,
        my_requirements=my_requirements, my_appointments=my_appointments,
        sections=sections, my_tasks=my_tasks, backlog_worklist=backlog_worklist,
        payments=payments, pay_totals=pay_totals,
        today=today_s,
        progress_by_job=progress_by_job,
        permits_by_job=permits_by_job,
        procurement=procurement, material_statuses=MATERIAL_STATUSES,
        gm=gm, closing_jobs=closing_jobs,
        schedule_buckets=schedule_buckets,
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
    """Build a VCALENDAR. Each event: {uid, date (YYYY-MM-DD), summary,
    description}, plus an optional "time" (HH:MM 24h) -- present, it becomes
    a timed VEVENT (a 60-minute default duration, floating local time, no
    TZID/Z -- consistent with every other date in this app being naive/
    local); absent, it stays an all-day event like before. Stable UIDs let a
    re-import update instead of dupe."""
    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0",
             "PRODID:-//Vixinman Designs//Compendium//EN", "CALSCALE:GREGORIAN",
             "METHOD:PUBLISH", _ics_fold("X-WR-CALNAME:" + _ics_escape(calname))]
    for e in events:
        try:
            start = datetime.strptime(e["date"], "%Y-%m-%d")
        except (ValueError, TypeError):
            continue
        time_str = e.get("time")
        dt_lines = []
        if time_str:
            try:
                start = datetime.strptime(f"{e['date']} {time_str}", "%Y-%m-%d %H:%M")
                end_dt = start + timedelta(minutes=60)
                dt_lines = [f"DTSTART:{start.strftime('%Y%m%dT%H%M%S')}",
                            f"DTEND:{end_dt.strftime('%Y%m%dT%H%M%S')}"]
            except ValueError:
                time_str = None   # fall through to all-day below
        if not time_str:
            end = (start + timedelta(days=1)).strftime("%Y%m%d")
            dt_lines = [f"DTSTART;VALUE=DATE:{start.strftime('%Y%m%d')}",
                        f"DTEND;VALUE=DATE:{end}"]
        lines += ["BEGIN:VEVENT", f"UID:{e['uid']}", f"DTSTAMP:{stamp}"] + dt_lines
        lines.append(_ics_fold("SUMMARY:" + _ics_escape(e["summary"])))
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
    """The signed-in person's task due dates, install dates for their
    projects, and their appointments, as an importable calendar. In open
    mode (no login) exports everything."""
    db = get_db()
    user = current_user()
    tsql = ("SELECT t.*, j.job_name FROM project_tasks t"
            " JOIN projects j ON j.id = t.project_id"
            " WHERE COALESCE(t.due_date, '') != ''")
    jsql = ("SELECT DISTINCT id, job_name, install_date FROM projects"
            " WHERE COALESCE(install_date, '') != ''")
    asql = ("SELECT * FROM appointments"
            " WHERE COALESCE(when_date, '') != '' AND COALESCE(completed_at, '') = ''")
    params = []
    if user:
        tsql += " AND t.household_member_id = ?"
        jsql += " AND id IN (SELECT project_id FROM project_tasks WHERE household_member_id = ?)"
        asql += " AND (household_member_id = ? OR household_member_id IS NULL)"
        params = [user["id"]]
    events = _task_events(db.execute(tsql, params).fetchall())
    for j in db.execute(jsql, params).fetchall():
        events.append({"uid": f"compendium-install-{j['id']}@vixinmandesigns",
                       "date": j["install_date"],
                       "summary": f"🔧 Install: {j['job_name'] or 'Project #' + str(j['id'])}",
                       "description": ""})
    for a in db.execute(asql, params).fetchall():
        events.append({"uid": f"compendium-appt-{a['id']}@vixinmandesigns",
                       "date": a["when_date"], "time": a["when_time"] or None,
                       "summary": f"📅 {a['title']}",
                       "description": a["location"] or ""})
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
    """Quick lookup across projects (name/site location) and the household idea
    backlog (name/notes)."""
    q = (request.args.get("q") or "").strip()
    projects, ideas = [], []
    if q:
        like = f"%{q}%"
        db = get_db()
        projects = db.execute(
            "SELECT * FROM projects"
            " WHERE job_name LIKE ? OR site_location LIKE ?"
            " ORDER BY created_at DESC",
            (like, like)).fetchall()
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


# --------------------------------------------------------------- Piece 35: Contacts
# (broadened Piece 43 to also cover organizations, and linked to Appointments)
def _helper_form_values():
    """Pull a contact's fields out of the POSTed form. kind is 'Person' or
    'Organization'; the org-only fields are simply blank for a Person."""
    return {
        "name": request.form.get("name", "").strip(),
        "kind": "Organization" if request.form.get("kind") == "Organization" else "Person",
        "phone": request.form.get("phone", "").strip(),
        "email": request.form.get("email", "").strip(),
        "specialty": request.form.get("specialty", "").strip(),
        "notes": request.form.get("notes", "").strip(),
        "website": request.form.get("website", "").strip(),
        "account_number": request.form.get("account_number", "").strip(),
        "contact_person": request.form.get("contact_person", "").strip(),
        "contact_phone": request.form.get("contact_phone", "").strip(),
        "contact_email": request.form.get("contact_email", "").strip(),
        "renewal_date": request.form.get("renewal_date", "").strip(),
    }


@app.route("/external-helpers")
def external_helpers_page():
    """Contacts: a reusable roster for people (a contractor, tutor, coach) and
    organizations (a subscription service, co-op, utility) that touch the
    household but aren't a household member."""
    db = get_db()
    helpers = [dict(h) for h in
               db.execute("SELECT * FROM external_helpers ORDER BY name").fetchall()]
    # Upcoming-appointment count + soonest date per contact, folded in here
    # rather than templated as a live query per row.
    upcoming = {}
    for row in db.execute(
            "SELECT external_helper_id, COUNT(*) AS n, MIN(when_date) AS next_date"
            " FROM appointments WHERE external_helper_id IS NOT NULL"
            " AND COALESCE(completed_at, '') = '' GROUP BY external_helper_id"):
        upcoming[row["external_helper_id"]] = {"n": row["n"], "next_date": row["next_date"]}
    for h in helpers:
        u = upcoming.get(h["id"])
        h["upcoming_count"] = u["n"] if u else 0
        h["upcoming_next"] = u["next_date"] if u else ""
    edit_id = request.args.get("edit", type=int)
    edit_helper = db.execute(
        "SELECT * FROM external_helpers WHERE id = ?", (edit_id,)
    ).fetchone() if edit_id else None
    return render_template("external_helpers.html", helpers=helpers,
                           edit_helper=edit_helper)


@app.route("/external-helpers/new", methods=["POST"])
def new_external_helper():
    v = _helper_form_values()
    if not v["name"]:
        flash("A name is required.", "error")
        return redirect(url_for("external_helpers_page"))
    db = get_db()
    db.execute(
        "INSERT INTO external_helpers (name, kind, phone, email, specialty, notes,"
        " website, account_number, contact_person, contact_phone, contact_email,"
        " renewal_date) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (v["name"], v["kind"], v["phone"], v["email"], v["specialty"], v["notes"],
         v["website"], v["account_number"], v["contact_person"], v["contact_phone"],
         v["contact_email"], v["renewal_date"]))
    db.commit()
    flash(f"Added: {v['name']}")
    return redirect(url_for("external_helpers_page"))


@app.route("/external-helpers/<int:helper_id>/edit", methods=["POST"])
def edit_external_helper(helper_id):
    db = get_db()
    if db.execute("SELECT 1 FROM external_helpers WHERE id = ?",
                  (helper_id,)).fetchone() is None:
        abort(404)
    v = _helper_form_values()
    if not v["name"]:
        flash("A name is required.", "error")
        return redirect(url_for("external_helpers_page", edit=helper_id))
    db.execute(
        "UPDATE external_helpers SET name = ?, kind = ?, phone = ?, email = ?,"
        " specialty = ?, notes = ?, website = ?, account_number = ?,"
        " contact_person = ?, contact_phone = ?, contact_email = ?,"
        " renewal_date = ? WHERE id = ?",
        (v["name"], v["kind"], v["phone"], v["email"], v["specialty"], v["notes"],
         v["website"], v["account_number"], v["contact_person"], v["contact_phone"],
         v["contact_email"], v["renewal_date"], helper_id))
    db.commit()
    flash(f"Updated: {v['name']}")
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


# ------------------------------------------------------- Piece 52: drafts
def draft_upload_dir():
    directory = UPLOADS_DIR / "drafts"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _save_draft_file(field_name):
    """Save an Assistant's upload into draft-only holding, using the same
    stored-name scheme as a live upload so Approve can move it verbatim."""
    upload = request.files.get(field_name)
    if upload is None or not upload.filename:
        return None
    ext = upload.filename.rsplit(".", 1)[-1].lower() if "." in upload.filename else ""
    if ext not in (PHOTO_EXTENSIONS | {"pdf"}):
        flash("Attachments should be a photo (JPG/PNG/HEIC) or a PDF — draft saved without it.", "error")
        return None
    stored = f"{uuid.uuid4().hex[:8]}_{secure_filename(upload.filename)}"
    upload.save(draft_upload_dir() / stored)
    return stored


def _move_draft_file(stored_name, dest_dir, dest_name=None):
    """Approve-time: move a pending draft file into its real destination."""
    src = draft_upload_dir() / stored_name
    if not src.exists():
        return None
    final_name = dest_name or stored_name
    shutil.move(str(src), str(dest_dir / final_name))
    return final_name


def _discard_draft_file(stored_name):
    try:
        (draft_upload_dir() / stored_name).unlink(missing_ok=True)
    except OSError:
        pass


@app.route("/household-files")
@admin_required
def household_files_page():
    files = get_db().execute(
        "SELECT * FROM household_files ORDER BY id DESC").fetchall()
    return render_template("household_files.html", files=files,
                           file_categories=HOUSEHOLD_FILE_CATEGORIES)


@app.route("/household-files/upload", methods=["POST"])
@admin_required
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
@admin_required
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


# ------------------------------------------------------------- household budget
# Piece 46: a household-wide (not tied to a project) income/expense ledger
# and category budgets, alongside the existing untouched per-project
# Billing tab / project_transactions ledger.
def _household_month_bounds(month_str=None):
    """(month_str, human label) for the month to summarize -- defaults to
    the current calendar month. month_str is 'YYYY-MM'."""
    month_str = month_str or datetime.now().strftime("%Y-%m")
    try:
        label = datetime.strptime(month_str, "%Y-%m").strftime("%B %Y")
    except ValueError:
        month_str = datetime.now().strftime("%Y-%m")
        label = datetime.now().strftime("%B %Y")
    return month_str, label


# -------------------------------------------------- Piece 55: Budget reporting
def _recent_months(n, ending=None):
    """The last n calendar months (oldest first) as [(month_str, label), ...],
    'YYYY-MM' ending at `ending` (default: current month). Hand-rolled month
    walk -- no dateutil/relativedelta anywhere in this app, stdlib only."""
    end_dt = datetime.strptime(ending, "%Y-%m") if ending else datetime.now()
    y, m = end_dt.year, end_dt.month
    months = []
    for _ in range(n):
        months.append((f"{y:04d}-{m:02d}", datetime(y, m, 1).strftime("%B %Y")))
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    months.reverse()
    return months


def _forward_months(n, starting=None):
    """Mirror of _recent_months, walking forward (soonest first)."""
    start_dt = datetime.strptime(starting, "%Y-%m") if starting else datetime.now()
    y, m = start_dt.year, start_dt.month
    months = []
    for _ in range(n):
        months.append((f"{y:04d}-{m:02d}", datetime(y, m, 1).strftime("%B %Y")))
        m += 1
        if m == 13:
            m, y = 1, y + 1
    return months


def _combined_month_totals(db, month_str):
    """Combined household + project income/expense totals and expense-by-
    category breakdown for ONE month, across BOTH ledgers, all statuses
    (matches household_budget_page()'s own existing unfiltered 'totals'
    block). Backs the pie chart and both trend charts -- one shared query
    shape instead of 4 hand-duplicated versions. `table` is interpolated
    from a fixed 2-item internal tuple, never request data."""
    totals = {"Income": 0.0, "Expense": 0.0}
    by_category = {}
    for table in ("household_transactions", "project_transactions"):
        for r in db.execute(
                f"SELECT kind, category, COALESCE(SUM(amount), 0) AS total"
                f" FROM {table} WHERE substr(txn_date, 1, 7) = ?"
                f" GROUP BY kind, category", (month_str,)).fetchall():
            if r["kind"] in totals:
                totals[r["kind"]] += r["total"]
            if r["kind"] == "Expense":
                cat = r["category"] or "Uncategorized"
                by_category[cat] = by_category.get(cat, 0.0) + r["total"]
    return {"income": totals["Income"], "expense": totals["Expense"],
            "net": totals["Income"] - totals["Expense"], "by_category": by_category}


def _category_breakdown_series(month_data, top_n=5):
    """Per-month expense-by-category series from month_data (a list of
    (month_str, label, _combined_month_totals()-dict)), capped to the top_n
    categories by total spend across the whole window + an 'Other' bucket.
    Pure function, no db access."""
    grand_totals = {}
    for _, _, mt in month_data:
        for cat, amt in mt["by_category"].items():
            grand_totals[cat] = grand_totals.get(cat, 0.0) + amt
    top_cats = [c for c, _ in sorted(grand_totals.items(), key=lambda kv: -kv[1])[:top_n]]
    series = {cat: [] for cat in top_cats}
    other_vals, has_other = [], False
    for _, _, mt in month_data:
        for cat in top_cats:
            series[cat].append(mt["by_category"].get(cat, 0.0))
        other = sum(a for c, a in mt["by_category"].items() if c not in top_cats)
        other_vals.append(other)
        has_other = has_other or other > 0
    if has_other:
        series["Other"] = other_vals
    return {"labels": [lbl for _, lbl, _ in month_data], "series": series}


def _cash_flow_projection(db, horizon_months=3):
    """Forward-looking net cash flow -- project + household Outstanding
    transactions plus household_budgets recurring targets, bucketed by
    calendar month. NOT a running account balance (no starting-balance
    concept exists anywhere in this app) -- nets expected-in vs.
    expected-out per future bucket only.

    Bucket 0 = the rest of the current month; an Outstanding row with a
    blank txn_date or one on/before today lands in bucket 0 regardless of
    how overdue (there's no earlier bucket, and it's actionable today). A
    txn_date beyond the horizon clamps into the last bucket instead of
    being dropped. household_budgets rows project a recurring Expense into
    every bucket: bucket 0 gets only the REMAINING target (monthly_amount
    minus what's already recorded this month in that category); future
    whole months get the full monthly_amount."""
    today_s = datetime.now().strftime("%Y-%m-%d")
    months = _forward_months(horizon_months)
    month_strs = [ms for ms, _ in months]
    idx = {ms: i for i, ms in enumerate(month_strs)}
    last_idx = len(months) - 1
    buckets = [{"month": ms, "label": lbl, "income": 0.0, "expense": 0.0,
                "budget_expense": 0.0} for ms, lbl in months]

    def _bucket_for(txn_date):
        if not txn_date or txn_date <= today_s:
            return 0
        ms = txn_date[:7]
        return idx.get(ms, last_idx if ms > month_strs[-1] else 0)

    for table in ("project_transactions", "household_transactions"):
        for r in db.execute(
                f"SELECT kind, amount, txn_date FROM {table}"
                f" WHERE status = 'Outstanding'").fetchall():
            b = buckets[_bucket_for(r["txn_date"])]
            if r["kind"] == "Income":
                b["income"] += r["amount"] or 0.0
            elif r["kind"] == "Expense":
                b["expense"] += r["amount"] or 0.0

    budgets = db.execute("SELECT category, monthly_amount FROM household_budgets").fetchall()
    if budgets:
        spent_this_month = {r["category"]: r["total"] for r in db.execute(
            "SELECT category, COALESCE(SUM(amount), 0) AS total"
            " FROM household_transactions WHERE kind = 'Expense'"
            " AND substr(txn_date, 1, 7) = ? GROUP BY category", (month_strs[0],)).fetchall()}
        for row in budgets:
            target = row["monthly_amount"] or 0.0
            remaining = max(target - spent_this_month.get(row["category"], 0.0), 0.0)
            buckets[0]["budget_expense"] += remaining
            for b in buckets[1:]:
                b["budget_expense"] += target

    for b in buckets:
        b["total_expense"] = b["expense"] + b["budget_expense"]
        b["net"] = b["income"] - b["total_expense"]
    return {"buckets": buckets, "horizon_months": horizon_months}


CATEGORY_PALETTE = ["#1a6e3c", "#8a5a00", "#b02a2a", "#4a6fa5", "#7a4fa5", "#12522c"]


def _assign_category_colors(names):
    """Deterministic category -> color (alphabetical over CATEGORY_PALETTE)
    so the same category is the same color in the pie AND category trend.
    'Other' is always neutral gray."""
    colors = {}
    for i, n in enumerate(sorted(n for n in names if n != "Other")):
        colors[n] = CATEGORY_PALETTE[i % len(CATEGORY_PALETTE)]
    if "Other" in names:
        colors["Other"] = "#9ca3af"
    return colors


def _pie_geometry(by_category, color_map, size=160, stroke=28):
    """Donut-chart slice geometry (category->amount, already capped to
    top-N+Other) -- the classic multi-<circle> stroke-dasharray/
    stroke-dashoffset technique, computed server-side."""
    r = (size - stroke) / 2
    circumference = 2 * math.pi * r
    total = sum(by_category.values())
    if total <= 0:
        return {"slices": [], "total": 0.0, "size": size, "r": r, "stroke": stroke}
    slices, offset = [], 0.0
    for cat, amt in sorted(by_category.items(), key=lambda kv: -kv[1]):
        pct = amt / total
        dash = pct * circumference
        slices.append({"category": cat, "amount": amt, "pct": round(pct * 100, 1),
                       "color": color_map.get(cat, "#9ca3af"),
                       "dasharray": f"{dash:.2f} {circumference - dash:.2f}",
                       "dashoffset": f"{-offset:.2f}"})
        offset += dash
    return {"slices": slices, "total": total, "size": size, "r": r, "stroke": stroke}


def _bar_series_geometry(labels, series, color_map, height=120, bar_width=16,
                         gap=4, group_gap=20):
    """Generic grouped-bar geometry, shared by all 3 bar charts. `series` is
    name->list-of-non-negative-floats, all the same length as `labels` --
    signed values (net flow) are shown as text, not bar height. Guards
    against an all-zero dataset (max_val-or-1.0)."""
    names = list(series.keys())
    max_val = max((v for vals in series.values() for v in vals), default=0.0) or 1.0
    group_width = len(names) * bar_width + max(len(names) - 1, 0) * gap
    groups, x = [], 0
    for gi, label in enumerate(labels):
        bars = []
        for bi, name in enumerate(names):
            val = series[name][gi]
            h = (val / max_val) * height
            bars.append({"name": name, "value": val, "x": x + bi * (bar_width + gap),
                        "y": height - h, "width": bar_width, "height": h,
                        "color": color_map.get(name, "#9ca3af")})
        groups.append({"label": label, "x_center": x + group_width / 2, "bars": bars})
        x += group_width + group_gap
    return {"groups": groups, "width": x - group_gap if groups else 0, "height": height,
            "names": names, "colors": {n: color_map.get(n, "#9ca3af") for n in names}}


@app.route("/budget")
@admin_required
def household_budget_page():
    db = get_db()
    month_str, month_label = _household_month_bounds(request.args.get("month"))
    show = request.args.get("show", "month")

    budgets = db.execute(
        "SELECT * FROM household_budgets ORDER BY category").fetchall()
    spent_by_category = {r["category"]: r["spent"] for r in db.execute(
        "SELECT category, COALESCE(SUM(amount), 0) AS spent"
        " FROM household_transactions"
        " WHERE kind = 'Expense' AND substr(txn_date, 1, 7) = ?"
        " GROUP BY category", (month_str,)).fetchall()}
    budget_rows = [{"category": b["category"], "budget": b["monthly_amount"],
                    "spent": spent_by_category.get(b["category"], 0.0),
                    "id": b["id"]} for b in budgets]

    sql = ("SELECT t.*, h.name AS contact_name FROM household_transactions t"
           " LEFT JOIN external_helpers h ON h.id = t.external_helper_id"
           " WHERE 1 = 1")
    params = []
    if show != "all":
        sql += " AND substr(t.txn_date, 1, 7) = ?"
        params.append(month_str)
    sql += " ORDER BY (t.txn_date = ''), t.txn_date DESC, t.id DESC"
    transactions = db.execute(sql, params).fetchall()

    # Totals always reflect the summarized month, independent of whether
    # the transaction list below is showing just this month or everything.
    totals = {"Income": 0.0, "Expense": 0.0}
    for t in db.execute(
            "SELECT kind, amount FROM household_transactions"
            " WHERE substr(txn_date, 1, 7) = ?", (month_str,)).fetchall():
        if t["kind"] in totals:
            totals[t["kind"]] += t["amount"]

    edit_id = request.args.get("edit", type=int)
    edit_txn = db.execute(
        "SELECT * FROM household_transactions WHERE id = ?", (edit_id,)
    ).fetchone() if edit_id else None
    edit_budget_id = request.args.get("edit_budget", type=int)
    edit_budget = db.execute(
        "SELECT * FROM household_budgets WHERE id = ?", (edit_budget_id,)
    ).fetchone() if edit_budget_id else None
    contacts = db.execute(
        "SELECT id, name FROM external_helpers ORDER BY name").fetchall()

    # Piece 55: at-a-glance reporting -- pie chart of expenses, a forward
    # cash-flow projection, and two historical trend charts, all combining
    # both the household and project ledgers.
    trend_months = min(max(request.args.get("trend_months", type=int) or 6, 3), 24)
    horizon_months = min(max(request.args.get("horizon_months", type=int) or 3, 1), 12)

    months = _recent_months(trend_months, ending=month_str)
    month_data = [(ms, lbl, _combined_month_totals(db, ms)) for ms, lbl in months]
    cat_series = _category_breakdown_series(month_data, top_n=5)
    cash_flow = _cash_flow_projection(db, horizon_months=horizon_months)

    color_names = set(cat_series["series"]) | set(month_data[-1][2]["by_category"])
    color_map = _assign_category_colors(color_names)
    expense_pie = _pie_geometry(month_data[-1][2]["by_category"], color_map)

    short_labels = [datetime.strptime(ms, "%Y-%m").strftime("%b '%y") for ms, _, _ in month_data]
    income_expense_trend = _bar_series_geometry(
        short_labels,
        {"Income": [d["income"] for _, _, d in month_data],
         "Expense": [d["expense"] for _, _, d in month_data]},
        {"Income": "#1a6e3c", "Expense": "#b02a2a"})
    category_trend = _bar_series_geometry(short_labels, cat_series["series"], color_map)

    cf_labels = [datetime.strptime(b["month"], "%Y-%m").strftime("%b '%y")
                for b in cash_flow["buckets"]]
    cash_flow_bars = _bar_series_geometry(
        cf_labels,
        {"Income": [b["income"] for b in cash_flow["buckets"]],
         "Expense": [b["total_expense"] for b in cash_flow["buckets"]]},
        {"Income": "#1a6e3c", "Expense": "#b02a2a"})

    return render_template(
        "household_budget.html", budget_rows=budget_rows,
        transactions=transactions, totals=totals, contacts=contacts,
        month=month_str, month_label=month_label, show=show,
        edit_txn=edit_txn, edit_budget=edit_budget,
        payment_methods=PAYMENT_METHODS, txn_statuses=TXN_STATUSES,
        household_budget_categories=HOUSEHOLD_BUDGET_CATEGORIES,
        trend_months=trend_months, horizon_months=horizon_months,
        expense_pie=expense_pie, cash_flow=cash_flow, cash_flow_bars=cash_flow_bars,
        income_expense_trend=income_expense_trend, category_trend=category_trend,
        today=datetime.now().strftime("%Y-%m-%d"))


def _household_txn_form_values():
    contact = request.form.get("external_helper_id", "")
    return {
        "kind": "Income" if request.form.get("kind") == "Income" else "Expense",
        "category": request.form.get("category", "").strip(),
        "description": request.form.get("description", "").strip(),
        "amount": _to_float(request.form.get("amount")) or 0.0,
        "txn_date": request.form.get("txn_date", "").strip()
                   or datetime.now().strftime("%Y-%m-%d"),
        # Piece 54: defaults to Paid -- an already-happened purchase is
        # normally already paid; flip to Outstanding for a bill not yet
        # settled. Matches the household_transactions.status migration's
        # own safe default for pre-existing rows.
        "status": request.form.get("status") if request.form.get("status") in TXN_STATUSES else "Paid",
        "party": request.form.get("party", "").strip(),
        "external_helper_id": int(contact) if contact.isdigit() else None,
        "reference": request.form.get("reference", "").strip(),
        "method": request.form.get("method", "").strip(),
    }


def _save_household_upload(field_name, existing_filename=""):
    """Optional photo/PDF upload into household_upload_dir() -- generalized
    from the original _save_household_receipt() (Piece 46) so it's reused
    for Budget receipts and Loan/Savings entry statements alike. Not
    required (unlike Work Bag's add_receipt(), Piece 26.2) since not every
    entry has a physical document worth keeping. Returns the stored
    filename to save (existing one kept if no new file was chosen)."""
    upload = request.files.get(field_name)
    if upload is None or not upload.filename:
        return existing_filename
    ext = upload.filename.rsplit(".", 1)[-1].lower() if "." in upload.filename else ""
    if ext not in (PHOTO_EXTENSIONS | {"pdf"}):
        flash("Attachments should be a photo (JPG/PNG/HEIC) or a PDF — kept the previous one.", "error")
        return existing_filename
    stored = f"{uuid.uuid4().hex[:8]}_{secure_filename(upload.filename)}"
    upload.save(household_upload_dir() / stored)
    return stored


def _save_household_receipt(existing_filename=""):
    return _save_household_upload("receipt", existing_filename)


def _capture_household_txn(**_):
    v = _household_txn_form_values()
    return {"values": v}, ([] if v["amount"] else ["Enter an amount."])


def _apply_household_txn(db, payload, ref_id, actor_name, draft_file_stored_name=None, exclude_id=None):
    """`payload["receipt_filename"]`, if present, is a filename ALREADY saved
    into household_upload_dir() by a live caller (via _save_household_receipt).
    Otherwise, if draft_file_stored_name is set, it's moved here from
    draft_upload_dir() (an Assistant's draft being approved)."""
    v = payload["values"]
    if ref_id is None:
        if draft_file_stored_name:
            receipt = _move_draft_file(draft_file_stored_name, household_upload_dir())
        else:
            receipt = payload.get("receipt_filename", "")
        db.execute(
            "INSERT INTO household_transactions (kind, category, description, amount,"
            " txn_date, status, party, external_helper_id, reference, method,"
            " receipt_filename, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (v["kind"], v["category"], v["description"], v["amount"], v["txn_date"],
             v["status"], v["party"], v["external_helper_id"], v["reference"], v["method"],
             receipt, actor_name))
        return True, f"{v['kind']} recorded: ${v['amount']:,.2f}", None
    txn = db.execute("SELECT receipt_filename FROM household_transactions WHERE id = ?",
                     (ref_id,)).fetchone()
    if txn is None:
        return False, "That transaction no longer exists.", None
    if draft_file_stored_name:
        receipt = _move_draft_file(draft_file_stored_name, household_upload_dir())
    else:
        receipt = payload.get("receipt_filename", txn["receipt_filename"] or "")
    db.execute(
        "UPDATE household_transactions SET kind = ?, category = ?, description = ?,"
        " amount = ?, txn_date = ?, status = ?, party = ?, external_helper_id = ?,"
        " reference = ?, method = ?, receipt_filename = ? WHERE id = ?",
        (v["kind"], v["category"], v["description"], v["amount"], v["txn_date"],
         v["status"], v["party"], v["external_helper_id"], v["reference"], v["method"],
         receipt, ref_id))
    return True, "Transaction updated.", None


@app.route("/budget/transactions/new", methods=["POST"])
@admin_required
@draftable("household_txn.new")
def household_txn_new():
    payload, errors = _capture_household_txn()
    if errors:
        flash(" ".join(errors), "error")
        return redirect(url_for("household_budget_page"))
    db = get_db()
    payload["receipt_filename"] = _save_household_receipt()
    me = current_user()
    ok, message, _ = _apply_household_txn(db, payload, None, me["name"] if me else "")
    db.commit()
    flash(message, "" if ok else "error")
    return redirect(url_for("household_budget_page"))


@app.route("/budget/transactions/<int:txn_id>/edit", methods=["POST"])
@admin_required
@draftable("household_txn.edit", ref_id_kwarg="txn_id")
def household_txn_edit(txn_id):
    db = get_db()
    txn = db.execute("SELECT * FROM household_transactions WHERE id = ?",
                     (txn_id,)).fetchone()
    if txn is None:
        abort(404)
    payload, errors = _capture_household_txn()
    if errors:
        flash(" ".join(errors), "error")
        return redirect(url_for("household_budget_page", edit=txn_id))
    payload["receipt_filename"] = _save_household_receipt(txn["receipt_filename"])
    actor = current_user()
    ok, message, _ = _apply_household_txn(db, payload, txn_id, actor["name"] if actor else "")
    db.commit()
    flash(message, "" if ok else "error")
    return redirect(url_for("household_budget_page"))


@app.route("/budget/transactions/<int:txn_id>/delete", methods=["POST"])
@delete_required
@admin_required
def household_txn_delete(txn_id):
    ok, msg = trash_item("household_transaction", txn_id)
    flash(msg, "" if ok else "error")
    return redirect(url_for("household_budget_page"))


@app.route("/budget/transactions/<int:txn_id>/receipt")
@admin_required
def download_household_receipt(txn_id):
    txn = get_db().execute(
        "SELECT receipt_filename FROM household_transactions WHERE id = ?",
        (txn_id,)).fetchone()
    if txn is None or not txn["receipt_filename"]:
        abort(404)
    return send_from_directory(household_upload_dir(), txn["receipt_filename"])


def _apply_household_txn_toggle_paid(db, payload, ref_id, actor_name, draft_file_stored_name=None, exclude_id=None):
    row = db.execute("SELECT status FROM household_transactions WHERE id = ?", (ref_id,)).fetchone()
    if row is None:
        return False, "That transaction no longer exists.", None
    db.execute("UPDATE household_transactions SET status = ? WHERE id = ?",
               ("Outstanding" if row["status"] == "Paid" else "Paid", ref_id))
    return True, "Payment status updated.", None


@app.route("/budget/transactions/<int:txn_id>/paid", methods=["POST"])
@admin_required
@draftable("household_txn.toggle_paid", ref_id_kwarg="txn_id")
def household_txn_toggle_paid(txn_id):
    db = get_db()
    actor = current_user()
    ok, _, _ = _apply_household_txn_toggle_paid(db, {}, txn_id, actor["name"] if actor else "")
    if ok:
        db.commit()
    return redirect(url_for("household_budget_page", _anchor="txn-form"))


def _capture_household_budget(**_):
    category = request.form.get("category", "").strip()
    amount = _to_float(request.form.get("monthly_amount")) or 0.0
    payload = {"category": category, "monthly_amount": amount}
    return payload, ([] if category else ["A budget category needs a name."])


def _apply_household_budget(db, payload, ref_id, actor_name, draft_file_stored_name=None, exclude_id=None):
    category, amount = payload["category"], payload["monthly_amount"]
    if ref_id is None:
        db.execute(
            "INSERT INTO household_budgets (category, monthly_amount) VALUES (?, ?)",
            (category, amount))
        return True, f"Budget added: {category} — ${amount:,.2f}/month", None
    if db.execute("SELECT 1 FROM household_budgets WHERE id = ?", (ref_id,)).fetchone() is None:
        return False, "That budget category no longer exists.", None
    db.execute(
        "UPDATE household_budgets SET category = ?, monthly_amount = ? WHERE id = ?",
        (category, amount, ref_id))
    return True, "Budget updated.", None


@app.route("/budget/categories/new", methods=["POST"])
@admin_required
@draftable("household_budget.new")
def household_budget_new():
    payload, errors = _capture_household_budget()
    if errors:
        flash(" ".join(errors), "error")
        return redirect(url_for("household_budget_page"))
    db = get_db()
    actor = current_user()
    ok, message, _ = _apply_household_budget(db, payload, None, actor["name"] if actor else "")
    db.commit()
    flash(message, "" if ok else "error")
    return redirect(url_for("household_budget_page"))


@app.route("/budget/categories/<int:budget_id>/edit", methods=["POST"])
@admin_required
@draftable("household_budget.edit", ref_id_kwarg="budget_id")
def household_budget_edit(budget_id):
    db = get_db()
    if db.execute("SELECT 1 FROM household_budgets WHERE id = ?",
                  (budget_id,)).fetchone() is None:
        abort(404)
    payload, errors = _capture_household_budget()
    if errors:
        flash(" ".join(errors), "error")
        return redirect(url_for("household_budget_page", edit_budget=budget_id))
    actor = current_user()
    ok, message, _ = _apply_household_budget(db, payload, budget_id, actor["name"] if actor else "")
    db.commit()
    flash(message, "" if ok else "error")
    return redirect(url_for("household_budget_page"))


@app.route("/budget/categories/<int:budget_id>/delete", methods=["POST"])
@delete_required
@admin_required
def household_budget_delete(budget_id):
    ok, msg = trash_item("household_budget", budget_id)
    flash(msg, "" if ok else "error")
    return redirect(url_for("household_budget_page"))


# ------------------------------------------------------- Piece 54: loans/savings
def _loan_account_form_values():
    return {
        "name": request.form.get("name", "").strip(),
        "lender": request.form.get("lender", "").strip(),
        "original_amount": _to_float(request.form.get("original_amount")) or 0.0,
        "interest_rate": _to_float(request.form.get("interest_rate")) or 0.0,
        "opened_date": request.form.get("opened_date", "").strip(),
        "notes": request.form.get("notes", "").strip(),
    }


def _capture_loan_account(**_):
    v = _loan_account_form_values()
    return {"values": v}, ([] if v["name"] else ["Give this loan account a name."])


def _apply_loan_account(db, payload, ref_id, actor_name, draft_file_stored_name=None, exclude_id=None):
    v = payload["values"]
    if ref_id is None:
        cur = db.execute(
            "INSERT INTO loan_accounts (name, lender, original_amount, interest_rate,"
            " opened_date, notes, created_by) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (v["name"], v["lender"], v["original_amount"], v["interest_rate"],
             v["opened_date"], v["notes"], actor_name))
        return True, f"Loan account added: {v['name']}", cur.lastrowid
    if db.execute("SELECT 1 FROM loan_accounts WHERE id = ?", (ref_id,)).fetchone() is None:
        return False, "That loan account no longer exists.", None
    db.execute(
        "UPDATE loan_accounts SET name = ?, lender = ?, original_amount = ?,"
        " interest_rate = ?, opened_date = ?, notes = ? WHERE id = ?",
        (v["name"], v["lender"], v["original_amount"], v["interest_rate"],
         v["opened_date"], v["notes"], ref_id))
    return True, "Loan account updated.", None


def _loan_entry_form_values():
    return {
        "kind": "Charge" if request.form.get("kind") == "Charge" else "Payment",
        "amount": _to_float(request.form.get("amount")) or 0.0,
        "entry_date": request.form.get("entry_date", "").strip()
                      or datetime.now().strftime("%Y-%m-%d"),
        "description": request.form.get("description", "").strip(),
        "method": request.form.get("method", "").strip(),
        "reference": request.form.get("reference", "").strip(),
    }


def _capture_loan_entry(**_):
    v = _loan_entry_form_values()
    return {"values": v}, ([] if v["amount"] else ["Enter an amount."])


def _apply_loan_entry(db, payload, ref_id, actor_name, draft_file_stored_name=None, exclude_id=None):
    """ref_id is the account_id -- this kind only ever creates a new row,
    same reasoning as _apply_project_transaction()."""
    v = payload["values"]
    if db.execute("SELECT 1 FROM loan_accounts WHERE id = ?", (ref_id,)).fetchone() is None:
        return False, "That loan account no longer exists.", None
    statement = (_move_draft_file(draft_file_stored_name, household_upload_dir())
                 if draft_file_stored_name else payload.get("statement_filename", ""))
    db.execute(
        "INSERT INTO loan_entries (account_id, kind, amount, entry_date, description,"
        " method, reference, statement_filename, created_by)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (ref_id, v["kind"], v["amount"], v["entry_date"], v["description"],
         v["method"], v["reference"], statement, actor_name))
    return True, f"{v['kind']} recorded: ${v['amount']:,.2f}", None


@app.route("/loans")
@admin_required
def loans_page():
    db = get_db()
    accounts = [{"row": a, "balance": loan_balance(db, a["id"], a["original_amount"])["balance"]}
                for a in db.execute("SELECT * FROM loan_accounts ORDER BY name").fetchall()]
    edit_id = request.args.get("edit", type=int)
    edit_account = db.execute(
        "SELECT * FROM loan_accounts WHERE id = ?", (edit_id,)).fetchone() if edit_id else None
    return render_template("loans.html", accounts=accounts, edit_account=edit_account)


@app.route("/loans/new", methods=["POST"])
@admin_required
@draftable("loan_account.new")
def loan_account_new():
    payload, errors = _capture_loan_account()
    if errors:
        flash(" ".join(errors), "error")
        return redirect(url_for("loans_page"))
    db = get_db()
    actor = current_user()
    ok, message, _ = _apply_loan_account(db, payload, None, actor["name"] if actor else "")
    db.commit()
    flash(message, "" if ok else "error")
    return redirect(url_for("loans_page"))


@app.route("/loans/<int:account_id>/edit", methods=["POST"])
@admin_required
@draftable("loan_account.edit", ref_id_kwarg="account_id")
def loan_account_edit(account_id):
    db = get_db()
    if db.execute("SELECT 1 FROM loan_accounts WHERE id = ?", (account_id,)).fetchone() is None:
        abort(404)
    payload, errors = _capture_loan_account()
    if errors:
        flash(" ".join(errors), "error")
        return redirect(url_for("loans_page", edit=account_id))
    actor = current_user()
    ok, message, _ = _apply_loan_account(db, payload, account_id, actor["name"] if actor else "")
    db.commit()
    flash(message, "" if ok else "error")
    return redirect(url_for("loans_page"))


@app.route("/loans/<int:account_id>/delete", methods=["POST"])
@delete_required
@admin_required
def loan_account_delete(account_id):
    ok, msg = trash_item("loan_account", account_id)
    flash(msg, "" if ok else "error")
    return redirect(url_for("loans_page"))


@app.route("/loans/<int:account_id>")
@admin_required
def loan_account_detail(account_id):
    db = get_db()
    account = db.execute("SELECT * FROM loan_accounts WHERE id = ?", (account_id,)).fetchone()
    if account is None:
        abort(404)
    balance = loan_balance(db, account_id, account["original_amount"])
    return render_template("loan_account_detail.html", account=account, balance=balance,
                           today=datetime.now().strftime("%Y-%m-%d"))


@app.route("/loans/<int:account_id>/entries/new", methods=["POST"])
@admin_required
@draftable("loan_entry.new", ref_id_kwarg="account_id")
def loan_entry_new(account_id):
    if get_db().execute("SELECT 1 FROM loan_accounts WHERE id = ?", (account_id,)).fetchone() is None:
        abort(404)
    payload, errors = _capture_loan_entry()
    if errors:
        flash(" ".join(errors), "error")
        return redirect(url_for("loan_account_detail", account_id=account_id))
    db = get_db()
    payload["statement_filename"] = _save_household_upload("statement")
    actor = current_user()
    ok, message, _ = _apply_loan_entry(db, payload, account_id, actor["name"] if actor else "")
    db.commit()
    flash(message, "" if ok else "error")
    return redirect(url_for("loan_account_detail", account_id=account_id))


@app.route("/loans/entries/<int:entry_id>/delete", methods=["POST"])
@delete_required
@admin_required
def loan_entry_delete(entry_id):
    entry = get_db().execute("SELECT account_id FROM loan_entries WHERE id = ?", (entry_id,)).fetchone()
    ok, msg = trash_item("loan_entry", entry_id)
    flash(msg, "" if ok else "error")
    return redirect(url_for("loan_account_detail", account_id=entry["account_id"]) if entry else url_for("loans_page"))


@app.route("/loans/entries/<int:entry_id>/statement")
@admin_required
def download_loan_statement(entry_id):
    entry = get_db().execute(
        "SELECT statement_filename FROM loan_entries WHERE id = ?", (entry_id,)).fetchone()
    if entry is None or not entry["statement_filename"]:
        abort(404)
    return send_from_directory(household_upload_dir(), entry["statement_filename"])


def _savings_account_form_values():
    return {
        "name": request.form.get("name", "").strip(),
        "institution": request.form.get("institution", "").strip(),
        "goal_amount": _to_float(request.form.get("goal_amount")) or 0.0,
        "opened_date": request.form.get("opened_date", "").strip(),
        "notes": request.form.get("notes", "").strip(),
    }


def _capture_savings_account(**_):
    v = _savings_account_form_values()
    return {"values": v}, ([] if v["name"] else ["Give this savings account a name."])


def _apply_savings_account(db, payload, ref_id, actor_name, draft_file_stored_name=None, exclude_id=None):
    v = payload["values"]
    if ref_id is None:
        cur = db.execute(
            "INSERT INTO savings_accounts (name, institution, goal_amount,"
            " opened_date, notes, created_by) VALUES (?, ?, ?, ?, ?, ?)",
            (v["name"], v["institution"], v["goal_amount"], v["opened_date"],
             v["notes"], actor_name))
        return True, f"Savings account added: {v['name']}", cur.lastrowid
    if db.execute("SELECT 1 FROM savings_accounts WHERE id = ?", (ref_id,)).fetchone() is None:
        return False, "That savings account no longer exists.", None
    db.execute(
        "UPDATE savings_accounts SET name = ?, institution = ?, goal_amount = ?,"
        " opened_date = ?, notes = ? WHERE id = ?",
        (v["name"], v["institution"], v["goal_amount"], v["opened_date"], v["notes"], ref_id))
    return True, "Savings account updated.", None


def _savings_entry_form_values():
    return {
        "kind": "Withdrawal" if request.form.get("kind") == "Withdrawal" else "Deposit",
        "amount": _to_float(request.form.get("amount")) or 0.0,
        "entry_date": request.form.get("entry_date", "").strip()
                      or datetime.now().strftime("%Y-%m-%d"),
        "description": request.form.get("description", "").strip(),
        "method": request.form.get("method", "").strip(),
        "reference": request.form.get("reference", "").strip(),
    }


def _capture_savings_entry(**_):
    v = _savings_entry_form_values()
    return {"values": v}, ([] if v["amount"] else ["Enter an amount."])


def _apply_savings_entry(db, payload, ref_id, actor_name, draft_file_stored_name=None, exclude_id=None):
    v = payload["values"]
    if db.execute("SELECT 1 FROM savings_accounts WHERE id = ?", (ref_id,)).fetchone() is None:
        return False, "That savings account no longer exists.", None
    statement = (_move_draft_file(draft_file_stored_name, household_upload_dir())
                 if draft_file_stored_name else payload.get("statement_filename", ""))
    db.execute(
        "INSERT INTO savings_entries (account_id, kind, amount, entry_date, description,"
        " method, reference, statement_filename, created_by)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (ref_id, v["kind"], v["amount"], v["entry_date"], v["description"],
         v["method"], v["reference"], statement, actor_name))
    return True, f"{v['kind']} recorded: ${v['amount']:,.2f}", None


@app.route("/savings")
@admin_required
def savings_page():
    db = get_db()
    accounts = [{"row": a, "balance": savings_balance(db, a["id"])["balance"]}
                for a in db.execute("SELECT * FROM savings_accounts ORDER BY name").fetchall()]
    edit_id = request.args.get("edit", type=int)
    edit_account = db.execute(
        "SELECT * FROM savings_accounts WHERE id = ?", (edit_id,)).fetchone() if edit_id else None
    return render_template("savings.html", accounts=accounts, edit_account=edit_account)


@app.route("/savings/new", methods=["POST"])
@admin_required
@draftable("savings_account.new")
def savings_account_new():
    payload, errors = _capture_savings_account()
    if errors:
        flash(" ".join(errors), "error")
        return redirect(url_for("savings_page"))
    db = get_db()
    actor = current_user()
    ok, message, _ = _apply_savings_account(db, payload, None, actor["name"] if actor else "")
    db.commit()
    flash(message, "" if ok else "error")
    return redirect(url_for("savings_page"))


@app.route("/savings/<int:account_id>/edit", methods=["POST"])
@admin_required
@draftable("savings_account.edit", ref_id_kwarg="account_id")
def savings_account_edit(account_id):
    db = get_db()
    if db.execute("SELECT 1 FROM savings_accounts WHERE id = ?", (account_id,)).fetchone() is None:
        abort(404)
    payload, errors = _capture_savings_account()
    if errors:
        flash(" ".join(errors), "error")
        return redirect(url_for("savings_page", edit=account_id))
    actor = current_user()
    ok, message, _ = _apply_savings_account(db, payload, account_id, actor["name"] if actor else "")
    db.commit()
    flash(message, "" if ok else "error")
    return redirect(url_for("savings_page"))


@app.route("/savings/<int:account_id>/delete", methods=["POST"])
@delete_required
@admin_required
def savings_account_delete(account_id):
    ok, msg = trash_item("savings_account", account_id)
    flash(msg, "" if ok else "error")
    return redirect(url_for("savings_page"))


@app.route("/savings/<int:account_id>")
@admin_required
def savings_account_detail(account_id):
    db = get_db()
    account = db.execute("SELECT * FROM savings_accounts WHERE id = ?", (account_id,)).fetchone()
    if account is None:
        abort(404)
    balance = savings_balance(db, account_id)
    return render_template("savings_account_detail.html", account=account, balance=balance,
                           today=datetime.now().strftime("%Y-%m-%d"))


@app.route("/savings/<int:account_id>/entries/new", methods=["POST"])
@admin_required
@draftable("savings_entry.new", ref_id_kwarg="account_id")
def savings_entry_new(account_id):
    if get_db().execute("SELECT 1 FROM savings_accounts WHERE id = ?", (account_id,)).fetchone() is None:
        abort(404)
    payload, errors = _capture_savings_entry()
    if errors:
        flash(" ".join(errors), "error")
        return redirect(url_for("savings_account_detail", account_id=account_id))
    db = get_db()
    payload["statement_filename"] = _save_household_upload("statement")
    actor = current_user()
    ok, message, _ = _apply_savings_entry(db, payload, account_id, actor["name"] if actor else "")
    db.commit()
    flash(message, "" if ok else "error")
    return redirect(url_for("savings_account_detail", account_id=account_id))


@app.route("/savings/entries/<int:entry_id>/delete", methods=["POST"])
@delete_required
@admin_required
def savings_entry_delete(entry_id):
    entry = get_db().execute("SELECT account_id FROM savings_entries WHERE id = ?", (entry_id,)).fetchone()
    ok, msg = trash_item("savings_entry", entry_id)
    flash(msg, "" if ok else "error")
    return redirect(url_for("savings_account_detail", account_id=entry["account_id"]) if entry else url_for("savings_page"))


@app.route("/savings/entries/<int:entry_id>/statement")
@admin_required
def download_savings_statement(entry_id):
    entry = get_db().execute(
        "SELECT statement_filename FROM savings_entries WHERE id = ?", (entry_id,)).fetchone()
    if entry is None or not entry["statement_filename"]:
        abort(404)
    return send_from_directory(household_upload_dir(), entry["statement_filename"])


def read_project_form():
    """Validate and normalize a submitted project form (create or edit)."""
    values = {f: request.form.get(f, "").strip() for f in PROJECT_FIELDS}
    errors = []
    if not values["job_name"]:
        errors.append("Project name is required.")
    return values, errors


def render_project_form(values, editing_job_id=None):
    return render_template(
        "project_form.html", values=values,
        project_categories=PROJECT_CATEGORIES,
        project_subcategories=PROJECT_SUBCATEGORIES,
        editing_job_id=editing_job_id,
    )


def _apply_new_project(db, payload, ref_id, actor_name, draft_file_stored_name=None, exclude_id=None):
    values = payload["values"]
    cur = db.execute(
        f"INSERT INTO projects ({', '.join(PROJECT_FIELDS)})"
        f" VALUES ({', '.join('?' * len(PROJECT_FIELDS))})",
        [values[f] for f in PROJECT_FIELDS])
    notify_stage_turnover(db, {"id": cur.lastrowid, "job_name": values["job_name"]},
                          DEFAULT_PROJECT_STATUS, exclude_id=exclude_id)
    return True, f"Project created: {values['job_name']}", cur.lastrowid


def _apply_edit_project(db, payload, ref_id, actor_name, draft_file_stored_name=None, exclude_id=None):
    values = payload["values"]
    project = db.execute("SELECT * FROM projects WHERE id = ?", (ref_id,)).fetchone()
    if project is None:
        return False, "That project no longer exists.", None
    snapshot = {f: project[f] for f in PROJECT_FIELDS}
    version = db.execute(
        "SELECT COALESCE(MAX(version), 0) + 1 FROM project_versions"
        " WHERE project_id = ?", (ref_id,)).fetchone()[0]
    db.execute(
        "INSERT INTO project_versions (project_id, version, data) VALUES (?, ?, ?)",
        (ref_id, version, json.dumps(snapshot)))
    db.execute(
        f"UPDATE projects SET {', '.join(f + ' = ?' for f in PROJECT_FIELDS)}"
        " WHERE id = ?", [values[f] for f in PROJECT_FIELDS] + [ref_id])
    return True, f"Project updated — the previous state was kept as version {version}.", ref_id


@app.route("/projects/new", methods=["GET", "POST"])
@admin_required
@draftable("project.new")
def new_project():
    db = get_db()
    if request.method == "POST":
        values, errors = read_project_form()
        if errors:
            flash(" ".join(errors), "error")
            return render_project_form(values), 400
        actor = current_user()
        ok, message, new_id = _apply_new_project(
            db, {"values": values}, None, actor["name"] if actor else "",
            exclude_id=actor["id"] if actor else None)
        db.commit()
        flash(message, "" if ok else "error")
        return redirect(url_for("project_detail", project_id=new_id))
    return render_project_form({})


@app.route("/projects/<int:project_id>/edit", methods=["GET", "POST"])
@admin_required
@draftable("project.edit", ref_id_kwarg="project_id")
def edit_project(project_id):
    db = get_db()
    project = fetch_project(project_id)
    if request.method == "POST":
        values, errors = read_project_form()
        if errors:
            flash(" ".join(errors), "error")
            return render_project_form(values, editing_job_id=project_id), 400
        actor = current_user()
        ok, message, _ = _apply_edit_project(
            db, {"values": values}, project_id, actor["name"] if actor else "")
        db.commit()
        flash(message, "" if ok else "error")
        return redirect(url_for("project_detail", project_id=project_id))
    values = {f: project[f] for f in PROJECT_FIELDS}
    return render_project_form(values, editing_job_id=project_id)


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
    # Piece 53: a Child only sees this project's filed documents if they
    # have a task assigned on it -- everything else on the page stays open.
    can_see_files = _can_see_project_files(project_id, me)
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

    # Documents tab: one upload slot per file the project needs — the standard docs
    # plus the project's document-worthy requirements (permits / compliance / doc
    # items; licenses, portals and phone numbers aren't files, so they're
    # excluded). files_by_label maps a slot to the files filed under it;
    # other_files are anything filed outside those slots.
    doc_req_groups = [
        (heading, sorted({r["label"] for r in items}))
        for heading, items in groups
        if items and items[0]["category"] in ("Permit", "Prerequisite", "Doc")
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

    # Piece 48: the "🧠 Plan" tab's brainstorm chat -- config + saved history.
    plan_cfg = assistant_settings(db)
    plan_providers = assistant_available_providers(plan_cfg)
    plan_default_provider = plan_cfg["default_provider"] if plan_cfg["default_provider"] in plan_providers else (
        plan_providers[0] if plan_providers else "claude")
    plan_messages = db.execute(
        "SELECT * FROM project_plan_messages WHERE project_id = ? ORDER BY id",
        (project_id,)).fetchall()

    return render_template(
        "project_detail.html", project=project, groups=groups, versions=versions,
        project_notes=project_notes, can_see_files=can_see_files,
        materials=materials, files=files, filed_labels=filed_labels,
        coverage=coverage, requirement_groups=requirement_groups,
        material_statuses=MATERIAL_STATUSES, license_staffing=license_staffing(),
        tasks=tasks, employees=employees, task_statuses=TASK_STATUSES,
        job_statuses=PROJECT_STATUSES, job_status_class=PROJECT_STATUS_CLASS,
        stage=stage, progress=progress, today=datetime.now().strftime("%Y-%m-%d"),
        doc_sections=doc_sections,
        files_by_label=files_by_label, other_files=other_files,
        formats_by_label=formats_by_label,
        billing=billing, txn_kinds=TXN_KINDS, txn_statuses=TXN_STATUSES,
        income_categories=INCOME_CATEGORIES, expense_categories=EXPENSE_CATEGORIES,
        payment_methods=PAYMENT_METHODS, doc_types=DOC_TYPES,
        plan_providers=plan_providers, plan_default_provider=plan_default_provider,
        plan_messages=plan_messages,
    )


def _capture_contract(**_):
    return {"contract_amount": _to_float(request.form.get("contract_amount")) or 0.0}, []


def _apply_set_contract(db, payload, ref_id, actor_name, draft_file_stored_name=None, exclude_id=None):
    project = db.execute("SELECT 1 FROM projects WHERE id = ?", (ref_id,)).fetchone()
    if project is None:
        return False, "That project no longer exists.", None
    db.execute("UPDATE projects SET contract_amount = ? WHERE id = ?",
               (payload["contract_amount"], ref_id))
    return True, "Billing details updated.", None


@app.route("/projects/<int:project_id>/contract", methods=["POST"])
@admin_required
@draftable("project.contract", ref_id_kwarg="project_id")
def set_contract(project_id):
    fetch_project(project_id)
    db = get_db()
    actor = current_user()
    ok, message, _ = _apply_set_contract(
        db, _capture_contract()[0], project_id, actor["name"] if actor else "")
    db.commit()
    flash(message, "" if ok else "error")
    return redirect(url_for("project_detail", project_id=project_id, _anchor="billing"))


def _capture_project_transaction(**_):
    kind = request.form.get("kind", "Expense")
    status = request.form.get("status", "Outstanding")
    doc_type = request.form.get("doc_type", "").strip()
    payload = {
        "kind": kind if kind in TXN_KINDS else "Expense",
        "status": status if status in TXN_STATUSES else "Outstanding",
        "doc_type": doc_type if doc_type in DOC_TYPES else "",
        "category": request.form.get("category", "").strip(),
        "description": request.form.get("description", "").strip(),
        "amount": _to_float(request.form.get("amount")) or 0.0,
        "txn_date": request.form.get("txn_date", "").strip(),
        "party": request.form.get("party", "").strip(),
        "reference": request.form.get("reference", "").strip(),
        "method": request.form.get("method", "").strip(),
    }
    return payload, []


def _apply_project_transaction(db, payload, ref_id, actor_name, draft_file_stored_name=None, exclude_id=None):
    """ref_id is the project_id -- this kind only ever creates a new row.
    A live call's document (if any) is read straight from request.files (the
    same request that's calling this); a draft-approval call instead moves
    the file that was set aside in draft_upload_dir() at draft-creation time."""
    project = db.execute("SELECT job_name FROM projects WHERE id = ?", (ref_id,)).fetchone()
    if project is None:
        return False, "That project no longer exists.", None
    kind, status, doc_type = payload["kind"], payload["status"], payload["doc_type"]
    cur = db.execute(
        "INSERT INTO project_transactions"
        " (project_id, kind, category, description, amount, txn_date, status,"
        "  party, reference, method, doc_type, created_by)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (ref_id, kind, payload["category"], payload["description"], payload["amount"],
         payload["txn_date"], status, payload["party"], payload["reference"],
         payload["method"], doc_type, actor_name))
    txn_id = cur.lastrowid
    label = doc_type or "Billing"

    def _file_project_files(stored, friendly):
        db.execute(
            "INSERT INTO project_files (project_id, rule_label, stored_name, original_name, txn_id)"
            " VALUES (?, ?, ?, ?, ?)", (ref_id, label, stored, friendly, txn_id))

    if draft_file_stored_name:
        ext = draft_file_stored_name.rsplit(".", 1)[-1].lower() if "." in draft_file_stored_name else ""
        friendly = friendly_filename(
            [project["job_name"], label], ext,
            taken=_taken_names(db, "project_files", "original_name", "project_id", ref_id))
        new_stored = f"{uuid.uuid4().hex[:8]}_{secure_filename(friendly)}"
        _move_draft_file(draft_file_stored_name, project_upload_dir(ref_id), new_stored)
        _file_project_files(new_stored, friendly)
    else:
        # Piece 28.2: optionally attach a source document (receipt / invoice /
        # bill) uploaded from the device — filed against this transaction
        # (txn_id) so it shows the 📎 link in the ledger.
        upload = request.files.get("document")
        if upload is not None and upload.filename:
            ext = upload.filename.rsplit(".", 1)[-1].lower() if "." in upload.filename else ""
            if ext in (PHOTO_EXTENSIONS | {"pdf"}):
                friendly = friendly_filename(
                    [project["job_name"], label], ext,
                    taken=_taken_names(db, "project_files", "original_name", "project_id", ref_id))
                stored = f"{uuid.uuid4().hex[:8]}_{secure_filename(friendly)}"
                upload.save(project_upload_dir(ref_id) / stored)
                _file_project_files(stored, friendly)
            else:
                flash("Attachment skipped — it must be a photo (JPG/PNG/HEIC) or a PDF.", "error")
    return True, f"{doc_type or kind} recorded.", None


@app.route("/projects/<int:project_id>/transactions/add", methods=["POST"])
@admin_required
@draftable("project_txn.add", ref_id_kwarg="project_id")
def add_transaction(project_id):
    fetch_project(project_id)
    payload, _errors = _capture_project_transaction()
    db = get_db()
    actor = current_user()
    ok, message, _ = _apply_project_transaction(
        db, payload, project_id, actor["name"] if actor else "")
    db.commit()
    flash(message, "" if ok else "error")
    return redirect(url_for("project_detail", project_id=project_id, _anchor="billing"))


def _capture_toggle_paid(project_id=None, **_):
    return {"project_id": project_id}, []


def _apply_toggle_transaction_paid(db, payload, ref_id, actor_name, draft_file_stored_name=None, exclude_id=None):
    project_id = payload["project_id"]
    row = db.execute("SELECT status FROM project_transactions WHERE id = ? AND project_id = ?",
                     (ref_id, project_id)).fetchone()
    if row is None:
        return False, "That transaction no longer exists.", None
    db.execute("UPDATE project_transactions SET status = ? WHERE id = ? AND project_id = ?",
               ("Outstanding" if row["status"] == "Paid" else "Paid", ref_id, project_id))
    return True, "Payment status updated.", None


@app.route("/projects/<int:project_id>/transactions/<int:txn_id>/paid", methods=["POST"])
@admin_required
@draftable("project_txn.toggle_paid", ref_id_kwarg="txn_id")
def toggle_transaction_paid(project_id, txn_id):
    db = get_db()
    actor = current_user()
    ok, message, _ = _apply_toggle_transaction_paid(
        db, {"project_id": project_id}, txn_id, actor["name"] if actor else "")
    if ok:
        db.commit()
    return redirect(url_for("project_detail", project_id=project_id, _anchor="billing"))


@app.route("/projects/<int:project_id>/transactions/<int:txn_id>/delete", methods=["POST"])
@admin_required
def delete_transaction(project_id, txn_id):
    db = get_db()
    db.execute("DELETE FROM project_transactions WHERE id = ? AND project_id = ?",
               (txn_id, project_id))
    db.commit()
    flash("Transaction deleted.")
    return redirect(url_for("project_detail", project_id=project_id, _anchor="billing"))


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


@app.route("/inventory")
def inventory_page():
    """Piece 23.2 (revised Piece 36, rehauled Piece 41): the household's own
    inventory — items grouped by free-text category, plus the tool kit and
    the vehicle list."""
    db = get_db()
    items = db.execute(
        "SELECT * FROM inventory_items WHERE active = 1"
        " ORDER BY category, make, model").fetchall()
    by_cat = {}
    for it in items:
        by_cat.setdefault(it["category"] or "Uncategorized", []).append(it)
    sections = [{"category": cat, "items": rows, "count": len(rows)}
                for cat, rows in sorted(by_cat.items())]
    tools = db.execute(
        "SELECT * FROM inventory_tools WHERE active = 1"
        " ORDER BY category, name").fetchall()
    vehicles = db.execute(
        "SELECT * FROM inventory_vehicles WHERE active = 1"
        " ORDER BY category, name").fetchall()
    return render_template(
        "inventory.html", sections=sections, tools=tools, vehicles=vehicles,
        item_total=len(items))


def _inventory_category_choices(db):
    return [r[0] for r in db.execute(
        "SELECT DISTINCT category FROM inventory_items"
        " WHERE COALESCE(category, '') != '' ORDER BY category").fetchall()]


def _inventory_form_values():
    """Pull an inventory item's fields out of the POSTed form."""
    return {
        "category": request.form.get("category", "").strip(),
        "make": request.form.get("make", "").strip(),
        "model": request.form.get("model", "").strip(),
        "description": request.form.get("description", "").strip(),
        "purchased_from": request.form.get("purchased_from", "").strip(),
        "cost": _to_float(request.form.get("cost")),
        "purchase_url": request.form.get("purchase_url", "").strip(),
        "manual_url": request.form.get("manual_url", "").strip(),
        "quantity": int(_to_float(request.form.get("quantity")) or 0),
        "notes": request.form.get("notes", "").strip(),
    }


def _capture_inventory_item(**_):
    v = _inventory_form_values()
    errors = [] if (v["category"] and (v["make"] or v["model"])) else \
        ["Category and a make or model are required."]
    return {"values": v}, errors


def _apply_inventory_item(db, payload, ref_id, actor_name, draft_file_stored_name=None, exclude_id=None):
    v = payload["values"]
    if ref_id is None:
        db.execute(
            "INSERT INTO inventory_items (category, make, model, description,"
            " purchased_from, cost, purchase_url, manual_url, quantity, notes)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (v["category"], v["make"], v["model"], v["description"],
             v["purchased_from"], v["cost"], v["purchase_url"], v["manual_url"],
             v["quantity"], v["notes"]))
        return True, f"Added {v['make']} {v['model']}.".strip(), None
    if db.execute("SELECT 1 FROM inventory_items WHERE id = ?", (ref_id,)).fetchone() is None:
        return False, "That inventory item no longer exists.", None
    db.execute(
        "UPDATE inventory_items SET category = ?, make = ?, model = ?,"
        " description = ?, purchased_from = ?, cost = ?, purchase_url = ?,"
        " manual_url = ?, quantity = ?, notes = ? WHERE id = ?",
        (v["category"], v["make"], v["model"], v["description"],
         v["purchased_from"], v["cost"], v["purchase_url"], v["manual_url"],
         v["quantity"], v["notes"], ref_id))
    return True, "Item updated.", None


@app.route("/inventory/items/new", methods=["GET", "POST"])
@admin_required
@draftable("inventory.item.new")
def inventory_item_new():
    """Add a new inventory item (the per-category "New item" button preselects
    the category)."""
    db = get_db()
    if request.method == "POST":
        payload, errors = _capture_inventory_item()
        if errors:
            flash(" ".join(errors), "error")
            return redirect(url_for("inventory_item_new", category=payload["values"]["category"]))
        actor = current_user()
        ok, message, _ = _apply_inventory_item(db, payload, None, actor["name"] if actor else "")
        db.commit()
        flash(message, "" if ok else "error")
        return redirect(url_for("inventory_page", _anchor=payload["values"]["category"]))
    category = request.args.get("category", "")
    return render_template(
        "inventory_item_form.html", item=None, category=category,
        categories=_inventory_category_choices(db))


@app.route("/inventory/items/<int:item_id>/edit", methods=["GET", "POST"])
@admin_required
@draftable("inventory.item.edit", ref_id_kwarg="item_id")
def inventory_item_edit(item_id):
    """Update an existing inventory item in place."""
    db = get_db()
    row = db.execute("SELECT * FROM inventory_items WHERE id = ?",
                     (item_id,)).fetchone()
    if row is None:
        abort(404)
    if request.method == "POST":
        v = _inventory_form_values()
        actor = current_user()
        ok, message, _ = _apply_inventory_item(
            db, {"values": v}, item_id, actor["name"] if actor else "")
        db.commit()
        flash(message, "" if ok else "error")
        return redirect(url_for("inventory_page", _anchor=v["category"]))
    return render_template(
        "inventory_item_form.html", item=dict(row), category=row["category"],
        categories=_inventory_category_choices(db))


@app.route("/inventory/items/<int:item_id>/delete", methods=["POST"])
@delete_required
def inventory_item_delete(item_id):
    """Send an inventory item to the trash (restorable, GM-only)."""
    ok, msg = trash_item("inventory_item", item_id)
    flash(msg, "" if ok else "error")
    return redirect(url_for("inventory_page"))


# --- Tools CRUD (Piece 24.3) -------------------------------------------------
def _tool_form_values():
    """Pull a tool's fields out of the POSTed form."""
    return {
        "name": request.form.get("name", "").strip(),
        "category": request.form.get("category", "").strip(),
        "make": request.form.get("make", "").strip(),
        "model": request.form.get("model", "").strip(),
        "description": request.form.get("description", "").strip(),
        "purchased_from": request.form.get("purchased_from", "").strip(),
        "cost": _to_float(request.form.get("cost")),
        "purchase_url": request.form.get("purchase_url", "").strip(),
        "manual_url": request.form.get("manual_url", "").strip(),
        "notes": request.form.get("notes", "").strip(),
    }


def _capture_inventory_tool(**_):
    v = _tool_form_values()
    return {"values": v}, ([] if v["name"] else ["A tool name is required."])


def _apply_inventory_tool(db, payload, ref_id, actor_name, draft_file_stored_name=None, exclude_id=None):
    v = payload["values"]
    if ref_id is None:
        db.execute(
            "INSERT INTO inventory_tools (name, category, make, model, description,"
            " purchased_from, cost, purchase_url, manual_url, notes)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (v["name"], v["category"], v["make"], v["model"], v["description"],
             v["purchased_from"], v["cost"], v["purchase_url"], v["manual_url"],
             v["notes"]))
        return True, f"Added tool: {v['name']}.", None
    if db.execute("SELECT 1 FROM inventory_tools WHERE id = ?", (ref_id,)).fetchone() is None:
        return False, "That tool no longer exists.", None
    db.execute(
        "UPDATE inventory_tools SET name = ?, category = ?, make = ?, model = ?,"
        " description = ?, purchased_from = ?, cost = ?, purchase_url = ?,"
        " manual_url = ?, notes = ? WHERE id = ?",
        (v["name"], v["category"], v["make"], v["model"], v["description"],
         v["purchased_from"], v["cost"], v["purchase_url"], v["manual_url"],
         v["notes"], ref_id))
    return True, "Tool updated.", None


@app.route("/inventory/tools/new", methods=["GET", "POST"])
@admin_required
@draftable("inventory.tool.new")
def inventory_tool_new():
    """Add a tool to the kit from inside the app."""
    db = get_db()
    if request.method == "POST":
        payload, errors = _capture_inventory_tool()
        if errors:
            flash(" ".join(errors), "error")
            return redirect(url_for("inventory_tool_new"))
        actor = current_user()
        ok, message, _ = _apply_inventory_tool(db, payload, None, actor["name"] if actor else "")
        db.commit()
        flash(message, "" if ok else "error")
        return redirect(url_for("inventory_page", _anchor="tools"))
    return render_template("inventory_tool_form.html", tool=None)


@app.route("/inventory/tools/<int:tool_id>/edit", methods=["GET", "POST"])
@admin_required
@draftable("inventory.tool.edit", ref_id_kwarg="tool_id")
def inventory_tool_edit(tool_id):
    """Update a tool in place."""
    db = get_db()
    row = db.execute("SELECT * FROM inventory_tools WHERE id = ?", (tool_id,)).fetchone()
    if row is None:
        abort(404)
    if request.method == "POST":
        v = _tool_form_values()
        actor = current_user()
        ok, message, _ = _apply_inventory_tool(
            db, {"values": v}, tool_id, actor["name"] if actor else "")
        db.commit()
        flash(message, "" if ok else "error")
        return redirect(url_for("inventory_page", _anchor="tools"))
    return render_template("inventory_tool_form.html", tool=dict(row))


@app.route("/inventory/tools/<int:tool_id>/delete", methods=["POST"])
@delete_required
def inventory_tool_delete(tool_id):
    """Send a tool to the trash (restorable, GM-only)."""
    ok, msg = trash_item("inventory_tool", tool_id)
    flash(msg, "" if ok else "error")
    return redirect(url_for("inventory_page", _anchor="tools"))


# --- Vehicles CRUD (Piece 24.3) ----------------------------------------------
def _vehicle_form_values():
    """Pull a vehicle's fields out of the POSTed form."""
    return {
        "name": request.form.get("name", "").strip(),
        "nickname": request.form.get("nickname", "").strip(),
        "category": request.form.get("category", "").strip(),
        "make": request.form.get("make", "").strip(),
        "model": request.form.get("model", "").strip(),
        "year": request.form.get("year", "").strip(),
        "description": request.form.get("description", "").strip(),
        "purchased_from": request.form.get("purchased_from", "").strip(),
        "cost": _to_float(request.form.get("cost")),
        "purchase_url": request.form.get("purchase_url", "").strip(),
        "manual_url": request.form.get("manual_url", "").strip(),
        "notes": request.form.get("notes", "").strip(),
    }


def _capture_inventory_vehicle(**_):
    v = _vehicle_form_values()
    return {"values": v}, ([] if v["name"] else ["A vehicle name is required."])


def _apply_inventory_vehicle(db, payload, ref_id, actor_name, draft_file_stored_name=None, exclude_id=None):
    v = payload["values"]
    if ref_id is None:
        db.execute(
            "INSERT INTO inventory_vehicles (name, nickname, category, make, model,"
            " year, description, purchased_from, cost, purchase_url, manual_url, notes)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (v["name"], v["nickname"], v["category"], v["make"], v["model"],
             v["year"], v["description"], v["purchased_from"], v["cost"],
             v["purchase_url"], v["manual_url"], v["notes"]))
        return True, f"Added: {v['name']}.", None
    if db.execute("SELECT 1 FROM inventory_vehicles WHERE id = ?", (ref_id,)).fetchone() is None:
        return False, "That vehicle no longer exists.", None
    db.execute(
        "UPDATE inventory_vehicles SET name = ?, nickname = ?, category = ?,"
        " make = ?, model = ?, year = ?, description = ?, purchased_from = ?,"
        " cost = ?, purchase_url = ?, manual_url = ?, notes = ? WHERE id = ?",
        (v["name"], v["nickname"], v["category"], v["make"], v["model"],
         v["year"], v["description"], v["purchased_from"], v["cost"],
         v["purchase_url"], v["manual_url"], v["notes"], ref_id))
    return True, "Vehicle updated.", None


@app.route("/inventory/vehicles/new", methods=["GET", "POST"])
@admin_required
@draftable("inventory.vehicle.new")
def inventory_vehicle_new():
    """Add a vehicle to the household's registry."""
    db = get_db()
    if request.method == "POST":
        payload, errors = _capture_inventory_vehicle()
        if errors:
            flash(" ".join(errors), "error")
            return redirect(url_for("inventory_vehicle_new"))
        actor = current_user()
        ok, message, _ = _apply_inventory_vehicle(db, payload, None, actor["name"] if actor else "")
        db.commit()
        flash(message, "" if ok else "error")
        return redirect(url_for("inventory_page", _anchor="vehicles"))
    return render_template("inventory_vehicle_form.html", vehicle=None)


@app.route("/inventory/vehicles/<int:vehicle_id>/edit", methods=["GET", "POST"])
@admin_required
@draftable("inventory.vehicle.edit", ref_id_kwarg="vehicle_id")
def inventory_vehicle_edit(vehicle_id):
    """Update a vehicle in place."""
    db = get_db()
    row = db.execute("SELECT * FROM inventory_vehicles WHERE id = ?",
                     (vehicle_id,)).fetchone()
    if row is None:
        abort(404)
    if request.method == "POST":
        v = _vehicle_form_values()
        actor = current_user()
        ok, message, _ = _apply_inventory_vehicle(
            db, {"values": v}, vehicle_id, actor["name"] if actor else "")
        db.commit()
        flash(message, "" if ok else "error")
        return redirect(url_for("inventory_page", _anchor="vehicles"))
    return render_template("inventory_vehicle_form.html", vehicle=dict(row))


@app.route("/inventory/vehicles/<int:vehicle_id>/delete", methods=["POST"])
@delete_required
def inventory_vehicle_delete(vehicle_id):
    """Send a vehicle to the trash (restorable, GM-only)."""
    ok, msg = trash_item("inventory_vehicle", vehicle_id)
    flash(msg, "" if ok else "error")
    return redirect(url_for("inventory_page", _anchor="vehicles"))

def _capture_project_status(**_):
    status = request.form.get("status", "")
    if status == "Abandoned":
        return None, ["Use “Cancel project” to mark a project Abandoned (a reason is required)."]
    if status not in PROJECT_STATUSES:
        return None, ["Not a valid stage."]
    return {"status": status}, []


def _apply_set_project_status(db, payload, ref_id, actor_name, draft_file_stored_name=None, exclude_id=None):
    project = db.execute("SELECT * FROM projects WHERE id = ?", (ref_id,)).fetchone()
    if project is None:
        return False, "That project no longer exists.", None
    status = payload["status"]
    cur = project["status"] or DEFAULT_PROJECT_STATUS
    warn = ""
    if status == next_stage(cur):
        rules = db.execute("SELECT * FROM resource_rules").fetchall()
        groups = group_rules(match_rules(project, rules))
        filed = {f["rule_label"] for f in db.execute(
            "SELECT rule_label FROM project_files WHERE project_id = ?", (ref_id,))
            if f["rule_label"]}
        info = stage_info(db, project, groups, filed)
        if not info["ready"]:
            warn = " · ".join(info["pending"])
    db.execute("UPDATE projects SET status = ? WHERE id = ?", (status, ref_id))
    moved_forward = (status != cur and status in STAGE_ORDER
                     and (cur not in STAGE_ORDER
                          or STAGE_ORDER.index(status) > STAGE_ORDER.index(cur)))
    if moved_forward:
        notify_stage_turnover(db, project, status, exclude_id=exclude_id)
    if warn:
        return True, f"Advanced to {status} with {cur} still pending: {warn}.", None
    return True, f"Advanced to {status}.", None


@app.route("/projects/<int:project_id>/status", methods=["POST"])
@admin_required
@draftable("project.status", ref_id_kwarg="project_id")
def set_project_status(project_id):
    fetch_project(project_id)
    payload, errors = _capture_project_status()
    if errors:
        flash(" ".join(errors), "error")
        return redirect(url_for("project_detail", project_id=project_id))
    db = get_db()
    actor = current_user()
    ok, message, _ = _apply_set_project_status(
        db, payload, project_id, actor["name"] if actor else "",
        exclude_id=actor["id"] if actor else None)
    db.commit()
    if not ok or "still pending" in message:
        flash(message, "" if ok else "error")
    return redirect(url_for("project_detail", project_id=project_id))


def _capture_cancel_project(**_):
    reason = request.form.get("reason", "").strip()
    if not reason:
        return None, ["A reason is required to cancel a project."]
    return {"reason": reason}, []


def _apply_cancel_project(db, payload, ref_id, actor_name, draft_file_stored_name=None, exclude_id=None):
    """Piece 30.2: cancel a project — mark it Abandoned with a required
    reason, remembering the current stage so it can be reopened."""
    project = db.execute("SELECT * FROM projects WHERE id = ?", (ref_id,)).fetchone()
    if project is None:
        return False, "That project no longer exists.", None
    if (project["status"] or "") == "Abandoned":
        return True, "This project is already cancelled.", None
    reason = payload["reason"]
    db.execute(
        "UPDATE projects SET pre_lost_status = ?, status = 'Abandoned', cancel_reason = ?,"
        " cancelled_at = ?, cancelled_by = ? WHERE id = ?",
        (project["status"] or DEFAULT_PROJECT_STATUS, reason,
         datetime.now().isoformat(timespec="seconds"), actor_name, ref_id))
    recipients = project_involved_ids(db, project, exclude_id=exclude_id)
    if recipients:
        jobname = project["job_name"] or f"Project #{project['id']}"
        notify_employees(
            db, recipients,
            f"🚫 {jobname} was cancelled (Abandoned). Reason: “{reason}”.",
            link=url_for("project_detail", project_id=project["id"]), kind="job_cancelled")
    return True, (f"Project cancelled (Abandoned). Reason recorded: “{reason}”."
                 + (f" {len(recipients)} team member(s) notified." if recipients else "")), None


@app.route("/projects/<int:project_id>/cancel", methods=["POST"])
@admin_required
@draftable("project.cancel", ref_id_kwarg="project_id")
def cancel_project(project_id):
    fetch_project(project_id)
    payload, errors = _capture_cancel_project()
    if errors:
        flash(" ".join(errors), "error")
        return redirect(url_for("project_detail", project_id=project_id))
    db = get_db()
    actor = current_user()
    ok, message, _ = _apply_cancel_project(
        db, payload, project_id, actor["name"] if actor else "",
        exclude_id=actor["id"] if actor else None)
    db.commit()
    flash(message, "" if ok else "error")
    return redirect(url_for("project_detail", project_id=project_id))


def _apply_reopen_project(db, payload, ref_id, actor_name, draft_file_stored_name=None, exclude_id=None):
    """Piece 30.2: reopen a cancelled project — restore the stage it was at
    before it was marked Abandoned and clear the cancellation info."""
    project = db.execute("SELECT * FROM projects WHERE id = ?", (ref_id,)).fetchone()
    if project is None:
        return False, "That project no longer exists.", None
    if (project["status"] or "") != "Abandoned":
        return False, "Only a cancelled (Abandoned) project can be reopened.", None
    prev = (project["pre_lost_status"] if "pre_lost_status" in project.keys() else "") or ""
    restore = prev if prev in STAGE_ORDER else DEFAULT_PROJECT_STATUS
    db.execute(
        "UPDATE projects SET status = ?, cancel_reason = '', cancelled_at = '',"
        " cancelled_by = '', pre_lost_status = '' WHERE id = ?", (restore, ref_id))
    return True, f"Project reopened at {restore}.", None


@app.route("/projects/<int:project_id>/reopen", methods=["POST"])
@admin_required
@draftable("project.reopen", ref_id_kwarg="project_id")
def reopen_project(project_id):
    fetch_project(project_id)
    db = get_db()
    actor = current_user()
    ok, message, _ = _apply_reopen_project(
        db, {}, project_id, actor["name"] if actor else "")
    db.commit()
    flash(message, "" if ok else "error")
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


def _capture_install_date(**_):
    return {"install_date": request.form.get("install_date", "").strip()}, []


def _apply_set_install_date(db, payload, ref_id, actor_name, draft_file_stored_name=None, exclude_id=None):
    project = db.execute("SELECT 1 FROM projects WHERE id = ?", (ref_id,)).fetchone()
    if project is None:
        return False, "That project no longer exists.", None
    date = payload["install_date"]
    db.execute("UPDATE projects SET install_date = ? WHERE id = ?", (date, ref_id))
    return True, ("Target date saved." if date else "Target date cleared."), None


@app.route("/projects/<int:project_id>/install-date", methods=["POST"])
@admin_required
@draftable("project.install_date", ref_id_kwarg="project_id")
def set_install_date(project_id):
    """Set (or clear) the project's target/completion date. Piece 41: this used
    to auto-advance Prep -> In Progress once permits were filed too (an
    install-job-specific handoff) — that gating is gone, so this just saves
    the date."""
    fetch_project(project_id)
    db = get_db()
    actor = current_user()
    ok, message, _ = _apply_set_install_date(
        db, _capture_install_date()[0], project_id, actor["name"] if actor else "")
    db.commit()
    flash(message, "" if ok else "error")
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
    # Piece 48: an optional stage tag, so a task added from the "🧠 Plan" tab's
    # suggestions counts toward stage_info()'s ready-count for that stage. The
    # generic Tasks-tab form never sends this, so its behavior is unchanged.
    pipeline_status = request.form.get("pipeline_status", "").strip()
    db = get_db()
    next_order = db.execute(
        "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM project_tasks WHERE project_id = ?",
        (project_id,)).fetchone()[0]
    db.execute(
        "INSERT INTO project_tasks"
        " (project_id, household_member_id, title, status, due_date, notes, sort_order,"
        "  pipeline_status, completed_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, strftime('%Y-%m-%d %H:%M:%f', 'now'))",
        (project_id, _task_assignee(project_id), title, status,
         request.form.get("due_date", "").strip(),
         request.form.get("notes", "").strip(), next_order, pipeline_status,
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


def stage_info(db, project, groups, filed_labels):
    """Piece 18 (revised Piece 35, de-gated Piece 41): the project's current
    stage, its exit criteria, and requirements-filed coverage. No stage has a
    hard-coded install-job requirement anymore (no permits/install-date/
    electric-loads gate) — advancing just needs this stage's own tasks done.
    permits_filed/permits_total/permits_ok are still returned for the
    informational Requirements-coverage badge shown on the dashboard and
    project page; they no longer affect `ready`."""
    status = project["status"] or DEFAULT_PROJECT_STATUS
    spec = STATUS_OWNERSHIP.get(status, {"dept": "—", "exit": ""})
    filed, total = _permit_coverage(groups, filed_labels)
    permits_ok = filed >= total
    install_date = project["install_date"] if "install_date" in project.keys() else ""
    # Progress: this stage's own tasks (tagged with pipeline_status = status).
    tdone, ttotal = db.execute(
        "SELECT COALESCE(SUM(status = 'Done'), 0), COUNT(*) FROM project_tasks"
        " WHERE project_id = ? AND pipeline_status = ?", (project["id"], status)).fetchone()
    ready = (ttotal == 0 or tdone >= ttotal)
    pending = []
    if ttotal and tdone < ttotal:
        pending.append(f"{ttotal - tdone} task(s) still open")
    return {
        "status": status, "dept": spec["dept"], "exit": spec["exit"],
        "permits_filed": filed, "permits_total": total, "permits_ok": permits_ok,
        "install_date": install_date, "tasks_done": tdone, "tasks_total": ttotal,
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


def loan_balance(db, account_id, original_amount=0.0):
    """Piece 54: running balance for a loan account, computed live from its
    entry ledger -- same reasoning as project_billing()."""
    entries = db.execute(
        "SELECT * FROM loan_entries WHERE account_id = ? ORDER BY entry_date, id",
        (account_id,)).fetchall()
    def total(kind):
        return sum(e["amount"] or 0 for e in entries if e["kind"] == kind)
    paid, charged = total("Payment"), total("Charge")
    original = _to_float(original_amount) or 0.0
    return {"entries": entries, "original": original, "paid": paid,
            "charged": charged, "balance": original + charged - paid}


def savings_balance(db, account_id):
    """Piece 54: running balance for a savings account, computed live."""
    entries = db.execute(
        "SELECT * FROM savings_entries WHERE account_id = ? ORDER BY entry_date, id",
        (account_id,)).fetchall()
    def total(kind):
        return sum(e["amount"] or 0 for e in entries if e["kind"] == kind)
    deposited, withdrawn = total("Deposit"), total("Withdrawal")
    return {"entries": entries, "deposited": deposited, "withdrawn": withdrawn,
            "balance": deposited - withdrawn}


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


def _capture_submission_approval(**_):
    return {"approved_hours": _to_float(request.form.get("approved_hours"))}, []


def _apply_submission_approval(db, payload, ref_id, actor_name, draft_file_stored_name=None, exclude_id=None):
    sub = db.execute("SELECT * FROM field_submissions WHERE id = ? AND status = 'Pending'",
                     (ref_id,)).fetchone()
    if sub is None:
        return False, "Submission not found or already reviewed.", None
    approved_hours = payload.get("approved_hours")
    if approved_hours is None:
        approved_hours = sub["reported_hours"]
    # Now — and only now — apply the field edits to the authoritative tasks.
    for it in db.execute(
            "SELECT * FROM field_submission_items WHERE submission_id = ?",
            (ref_id,)).fetchall():
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
        (approved_hours, actor_name, ref_id))
    return True, "Submission approved — task changes applied and hours logged.", None


@app.route("/submissions/<int:sub_id>/approve", methods=["POST"])
@admin_required
@draftable("submission.approve", ref_id_kwarg="sub_id")
def approve_submission(sub_id):
    db = get_db()
    payload, _errors = _capture_submission_approval()
    who = current_user()
    ok, message, _ = _apply_submission_approval(
        db, payload, sub_id, who["name"] if who else "")
    db.commit()
    flash(message, "" if ok else "error")
    return redirect(url_for("submissions_page"))


def _apply_submission_rejection(db, payload, ref_id, actor_name, draft_file_stored_name=None, exclude_id=None):
    cur = db.execute(
        "UPDATE field_submissions SET status = 'Rejected', reviewed_by = ?,"
        " reviewed_at = datetime('now') WHERE id = ? AND status = 'Pending'", (actor_name, ref_id))
    if cur.rowcount == 0:
        return False, "Submission not found or already reviewed.", None
    return True, "Submission rejected — no changes were applied.", None


@app.route("/submissions/<int:sub_id>/reject", methods=["POST"])
@admin_required
@draftable("submission.reject", ref_id_kwarg="sub_id")
def reject_submission(sub_id):
    who = current_user()
    db = get_db()
    ok, message, _ = _apply_submission_rejection(db, {}, sub_id, who["name"] if who else "")
    db.commit()
    flash(message, "" if ok else "error")
    return redirect(url_for("submissions_page"))


# -------------------------------------------------------------------- files
def project_upload_dir(project_id):
    directory = UPLOADS_DIR / f"job_{project_id}"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


@app.route("/projects/<int:project_id>/files/upload", methods=["POST"])
def upload_file(project_id):
    fetch_project(project_id)
    if not _file_route_allowed(project_id):
        abort(403)
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
    if not _file_route_allowed(project_id, record):
        abort(403)
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
    if not _file_route_allowed(project_id, record):
        abort(403)
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
    for an admin's approval, and return to the project's Work Bag page."""
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


@app.route("/rules")
@admin_required
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
    project_rules = [r for r in rules if r["field_name"]]
    groups = group_rules(project_rules, dedupe=False)
    # Piece 38: standalone recurring requirements — not tied to any project,
    # reminded on their own interval (household paperwork like taxes,
    # homeschool registration). Distinguished by having no field_name.
    recurring = db.execute(
        "SELECT r.*, e.name AS assignee_name FROM resource_rules r"
        " LEFT JOIN household_members e ON e.id = r.household_member_id"
        " WHERE r.field_name = '' AND COALESCE(r.recurrence_days, '') != ''"
        " ORDER BY (r.next_due = ''), r.next_due"
    ).fetchall()
    employees = db.execute(
        "SELECT id, name FROM household_members ORDER BY name").fetchall()
    # Piece 41 (fixed-vocabulary Piece 44): suggest real values for the
    # "…matches this value" field instead of leaving it blind free text.
    # project_type is now a controlled subcategory list -- show the full
    # known vocabulary rather than only what's been used in real projects
    # so far (which is empty on a fresh install).
    distinct_types = sorted({s for lst in PROJECT_SUBCATEGORIES.values() for s in lst})
    distinct_locations = [r[0] for r in db.execute(
        "SELECT DISTINCT site_location FROM projects"
        " WHERE COALESCE(site_location, '') != '' ORDER BY site_location").fetchall()]
    return render_template(
        "rules.html", rules=project_rules, groups=groups, from_job=from_job,
        edit_rule=edit_rule, category_headings=CATEGORY_HEADINGS,
        job_fields=[f for f in PROJECT_FIELDS if f != "job_name"],
        field_labels=PROJECT_FIELD_LABELS, categories=RULE_CATEGORIES,
        recurring=recurring, employees=employees,
        project_categories=PROJECT_CATEGORIES, distinct_types=distinct_types,
        distinct_locations=distinct_locations,
        today=datetime.now().strftime("%Y-%m-%d"),
    )


def _rule_form_values():
    """Shared parsing for the rule form: either a project-triggered condition
    (field_name/field_value, optionally AND'd with a second) or a standalone
    recurring requirement (no project field — reminded on its own interval,
    the way a Chore is)."""
    standalone = request.form.get("standalone") == "1"
    values = {
        "label": request.form.get("label", "").strip(),
        "category": request.form.get("category", "Prerequisite"),
        "url": request.form.get("url", "").strip(),
        "phone": request.form.get("phone", "").strip(),
        "notes": request.form.get("notes", "").strip(),
        "link_text": request.form.get("link_text", "").strip(),
        "source_text": request.form.get("source_text", "").strip(),
        "verify_status": _clean_verify_status(request.form.get("verify_status")),
        "est_cost": request.form.get("est_cost", "").strip(),
        "est_time": request.form.get("est_time", "").strip(),
        "maintenance_note": request.form.get("maintenance_note", "").strip(),
    }
    if standalone:
        assignee = request.form.get("household_member_id", "")
        days = int(_to_float(request.form.get("recurrence_days")) or 7)
        values.update(
            field_name="", field_value="", match_type="equals",
            field_name2="", field_value2="", match_type2="equals",
            allowed_formats="",
            household_member_id=int(assignee) if assignee.isdigit() else None,
            recurrence_days=max(1, days),
            next_due=request.form.get("next_due", "").strip()
                     or datetime.now().strftime("%Y-%m-%d"),
        )
    else:
        field_name = request.form.get("field_name", "").strip()
        field_name2 = request.form.get("field_name2", "").strip()
        values.update(
            field_name=field_name,
            field_value=request.form.get("field_value", "").strip(),
            match_type="contains" if field_name == "products" else "equals",
            field_name2=field_name2,
            field_value2=request.form.get("field_value2", "").strip(),
            match_type2="contains" if field_name2 == "products" else "equals",
            allowed_formats=",".join(sorted(_parse_formats(
                request.form.get("allowed_formats")))),
            household_member_id=None, recurrence_days=None, next_due="",
        )
    return standalone, values


def _rule_form_errors(standalone, v):
    if not v["label"]:
        return "A rule needs a label."
    if standalone:
        return None
    if v["field_name"] not in PROJECT_FIELDS or not v["field_value"]:
        return "A rule needs a project field and a value to match."
    if v["field_name2"] and (v["field_name2"] not in PROJECT_FIELDS
                              or not v["field_value2"]):
        return "The second condition needs both a field and a value."
    return None


_RULE_COLUMNS = [
    "field_name", "field_value", "match_type", "category", "label", "url",
    "phone", "notes", "field_name2", "field_value2", "match_type2",
    "link_text", "allowed_formats", "source_text", "verify_status",
    "est_cost", "est_time", "maintenance_note", "household_member_id",
    "recurrence_days", "next_due",
]


def _capture_rule(**_):
    standalone, v = _rule_form_values()
    error = _rule_form_errors(standalone, v)
    return {"values": v}, ([error] if error else [])


def _apply_rule(db, payload, ref_id, actor_name, draft_file_stored_name=None, exclude_id=None):
    v = payload["values"]
    if ref_id is None:
        db.execute(
            f"INSERT INTO resource_rules ({', '.join(_RULE_COLUMNS)})"
            f" VALUES ({', '.join('?' * len(_RULE_COLUMNS))})",
            [v[c] for c in _RULE_COLUMNS])
        return True, f"Rule added: {v['label']}", None
    if db.execute("SELECT 1 FROM resource_rules WHERE id = ?", (ref_id,)).fetchone() is None:
        return False, "That rule no longer exists.", None
    db.execute(
        f"UPDATE resource_rules SET {', '.join(c + ' = ?' for c in _RULE_COLUMNS)} WHERE id = ?",
        [v[c] for c in _RULE_COLUMNS] + [ref_id])
    return True, f"Rule updated: {v['label']}", None


@app.route("/rules/new", methods=["POST"])
@admin_required
@draftable("rule.new")
def add_rule():
    from_job = request.form.get("from_job") or None
    payload, errors = _capture_rule()
    if errors:
        flash(" ".join(errors), "error")
        return redirect(url_for("rules_page", from_job=from_job))
    db = get_db()
    actor = current_user()
    ok, message, _ = _apply_rule(db, payload, None, actor["name"] if actor else "")
    db.commit()
    flash(message, "" if ok else "error")
    return redirect(url_for("rules_page", from_job=from_job))


@app.route("/rules/<int:rule_id>/edit", methods=["POST"])
@admin_required
@draftable("rule.edit", ref_id_kwarg="rule_id")
def update_rule(rule_id):
    db = get_db()
    if db.execute("SELECT 1 FROM resource_rules WHERE id = ?",
                  (rule_id,)).fetchone() is None:
        abort(404)
    from_job = request.form.get("from_job") or None
    payload, errors = _capture_rule()
    if errors:
        flash(" ".join(errors), "error")
        return redirect(url_for("rules_page", from_job=from_job, edit=rule_id))
    actor = current_user()
    ok, message, _ = _apply_rule(db, payload, rule_id, actor["name"] if actor else "")
    db.commit()
    flash(message, "" if ok else "error")
    return redirect(url_for("rules_page", from_job=from_job))


@app.route("/directory")
def rule_directory():
    """Read-only, browsable view of every rule, filterable by project
    category and type. No editing happens here."""
    category = request.args.get("category", "")
    ptype = request.args.get("type", "").strip()

    def visible(rule):
        conditions = [(rule["field_name"], rule["field_value"])]
        if rule["field_name2"]:
            conditions.append((rule["field_name2"], rule["field_value2"]))
        if category:
            tied = any(f == "project_category" and v.strip().lower() == category.lower()
                       for f, v in conditions)
            if not tied:
                return False
        if ptype:
            tied = any(f == "project_type" and ptype.lower() in v.strip().lower()
                       for f, v in conditions)
            if not tied:
                return False
        return True

    db = get_db()
    rules = [r for r in db.execute(
        "SELECT * FROM resource_rules ORDER BY category, label"
    ).fetchall() if visible(r)]
    groups = consolidate_rules(rules)
    total = sum(len(items) for _, items in groups)   # consolidated requirements
    # Piece 44: project_type is now a fixed subcategory list -- narrow the
    # type filter's options to the chosen category's subcategories (or the
    # full known vocabulary when no category is picked yet).
    all_subcats = sorted({s for lst in PROJECT_SUBCATEGORIES.values() for s in lst})
    type_options = PROJECT_SUBCATEGORIES.get(category, all_subcats)
    return render_template(
        "directory.html", groups=groups, total=total,
        field_labels=PROJECT_FIELD_LABELS,
        project_categories=PROJECT_CATEGORIES, type_options=type_options,
        filters={"category": category, "type": ptype},
        filtering=bool(category or ptype),
    )


@app.route("/rules/<int:rule_id>/delete", methods=["POST"])
@delete_required
def delete_rule(rule_id):
    ok, msg = trash_item("rule", rule_id)
    flash(msg, "" if ok else "error")
    return redirect(url_for("rules_page",
                            from_job=request.form.get("from_job") or None))


@app.route("/rules/<int:rule_id>/done", methods=["POST"])
def requirement_done(rule_id):
    """Mark a standalone recurring requirement done — advances next_due by
    its recurrence_days, mirroring chore_done()."""
    db = get_db()
    rule = db.execute("SELECT * FROM resource_rules WHERE id = ?",
                      (rule_id,)).fetchone()
    if rule is None or rule["field_name"] or not rule["recurrence_days"]:
        abort(404)
    me = current_user()
    today = datetime.now()
    next_due = (today + timedelta(days=int(rule["recurrence_days"]))).strftime("%Y-%m-%d")
    db.execute(
        "UPDATE resource_rules SET last_completed_at = ?, last_completed_by = ?,"
        " next_due = ?, reminder_sent = '' WHERE id = ?",
        (today.strftime("%Y-%m-%d"), me["name"] if me else "", next_due, rule_id))
    db.commit()
    flash(f"Marked done: {rule['label']} — next due {next_due}.")
    return redirect(url_for("rules_page"))


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
@admin_required
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


def _apply_household_member_auth(db, household_member_id, username, password, is_admin_flag):
    """Set or clear this household member's login from the given Login
    fields, and their is_admin flag. A blank username removes the login; the
    password hash is rewritten only when a new password is supplied, so
    editing other fields never disturbs an existing password. Guards against
    leaving accounts configured with no admin (which would lock everyone out
    of admin functions). Piece 52: parameterized (was request.form-reading)
    so it can run identically for a live edit or a draft's stored payload."""
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


def _capture_household_member(**_):
    values, errors = read_household_member_form()
    payload = {
        "values": values,
        "auth": {
            "username": request.form.get("username", "").strip(),
            "password": request.form.get("password", ""),
            "is_admin": "1" if request.form.get("is_admin") else "",
        },
        "confirm_duplicate": bool(request.form.get("confirm_duplicate")),
    }
    return payload, errors


def _apply_household_member(db, payload, ref_id, actor_name, draft_file_stored_name=None, exclude_id=None):
    values, auth = payload["values"], payload["auth"]
    if ref_id is None:
        dup = db.execute("SELECT 1 FROM household_members WHERE LOWER(name) = LOWER(?)",
                         (values["name"],)).fetchone()
        if dup and not payload.get("confirm_duplicate"):
            return False, (f"“{values['name']}” already exists on the roster — "
                           "discard this draft or have it resubmitted with the duplicate confirmed."), None
        cur = db.execute(
            f"INSERT INTO household_members ({', '.join(HOUSEHOLD_MEMBER_FIELDS)})"
            f" VALUES ({', '.join('?' * len(HOUSEHOLD_MEMBER_FIELDS))})",
            [values[f] for f in HOUSEHOLD_MEMBER_FIELDS])
        member_id, prior_role = cur.lastrowid, None
    else:
        member = db.execute("SELECT * FROM household_members WHERE id = ?", (ref_id,)).fetchone()
        if member is None:
            return False, "That household member no longer exists.", None
        db.execute(
            f"UPDATE household_members SET {', '.join(f + ' = ?' for f in HOUSEHOLD_MEMBER_FIELDS)}"
            " WHERE id = ?", [values[f] for f in HOUSEHOLD_MEMBER_FIELDS] + [ref_id])
        member_id, prior_role = ref_id, member["role"]
    _apply_household_member_auth(db, member_id, auth["username"], auth["password"], auth["is_admin"])
    if prior_role is None or values["role"] != prior_role:
        _seed_role_default_grants(db, member_id, values["role"])
    return True, f"Household member saved: {values['name']}", member_id


@app.route("/household-members/new", methods=["GET", "POST"])
@admin_required
@draftable("household_member.new")
def new_household_member():
    if request.method == "POST":
        payload, errors = _capture_household_member()
        username = payload["auth"]["username"]
        if errors:
            flash(" ".join(errors), "error")
            return render_household_member_form(payload["values"], username=username), 400
        db = get_db()
        # Guard against accidental duplicates: same composed name already on the
        # roster. Allow it only when the user confirms it's a different person.
        dup = db.execute("SELECT name FROM household_members WHERE LOWER(name) = LOWER(?)",
                         (payload["values"]["name"],)).fetchone()
        if dup and not payload["confirm_duplicate"]:
            return render_household_member_form(
                payload["values"], username=username,
                duplicate_warning=payload["values"]["name"]), 400
        actor = current_user()
        ok, message, member_id = _apply_household_member(
            db, payload, None, actor["name"] if actor else "")
        db.commit()
        flash(message, "" if ok else "error")
        return redirect(url_for("household_member_detail", household_member_id=member_id))
    return render_household_member_form({})


@app.route("/household-members/<int:household_member_id>")
@admin_required
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
    # Certification requirement labels, for the "satisfies requirement" dropdown.
    license_labels = [r["label"] for r in db.execute(
        "SELECT DISTINCT label FROM resource_rules WHERE category = 'Certification'"
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
@draftable("household_member.edit", ref_id_kwarg="household_member_id")
def edit_household_member(household_member_id):
    db = get_db()
    member = db.execute(
        "SELECT * FROM household_members WHERE id = ?", (household_member_id,)
    ).fetchone()
    if member is None:
        abort(404)
    if request.method == "POST":
        payload, errors = _capture_household_member()
        if errors:
            flash(" ".join(errors), "error")
            return render_household_member_form(
                payload["values"], household_member_id=household_member_id), 400
        actor = current_user()
        ok, message, _ = _apply_household_member(
            db, payload, household_member_id, actor["name"] if actor else "")
        db.commit()
        flash(message, "" if ok else "error")
        return redirect(url_for("household_member_detail", household_member_id=household_member_id))
    values = {f: member[f] for f in HOUSEHOLD_MEMBER_FIELDS}
    return render_household_member_form(
        values, household_member_id=household_member_id,
        username=member["username"] or "",
        is_admin_checked=member["is_admin"] or "")

# ------------------------------------------------------------------- drafts
# Piece 52: every kind an Assistant-role account can write, and how to (a)
# capture what it submitted and (b) apply it for real once a Parent/Admin
# approves. "recommendation" kinds (wishlist/submission review) act on an
# existing row via ref_id instead of creating a new one.
DRAFT_KINDS = {
    "project.new": {
        "label": "New project", "capture": lambda **_: read_project_form(),
        "apply": _apply_new_project,
        "summarize": lambda p: p["values"]["job_name"] or "(untitled project)"},
    "project.edit": {
        "label": "Project edit", "capture": lambda **_: read_project_form(),
        "apply": _apply_edit_project,
        "summarize": lambda p: p["values"]["job_name"] or "(untitled project)"},
    "project.status": {
        "label": "Project stage change", "capture": _capture_project_status,
        "apply": _apply_set_project_status,
        "summarize": lambda p: f"Advance to {p['status']}"},
    "project.cancel": {
        "label": "Cancel project", "capture": _capture_cancel_project,
        "apply": _apply_cancel_project,
        "summarize": lambda p: f"Reason: {p['reason']}"},
    "project.reopen": {
        "label": "Reopen project", "capture": lambda **_: ({}, []),
        "apply": _apply_reopen_project,
        "summarize": lambda p: "Reopen this project"},
    "project.install_date": {
        "label": "Project target date", "capture": _capture_install_date,
        "apply": _apply_set_install_date,
        "summarize": lambda p: p["install_date"] or "(cleared)"},
    "project.contract": {
        "label": "Project contract total", "capture": _capture_contract,
        "apply": _apply_set_contract,
        "summarize": lambda p: f"${p['contract_amount']:,.2f}"},
    "rule.new": {
        "label": "New requirement rule", "capture": _capture_rule,
        "apply": _apply_rule, "summarize": lambda p: p["values"]["label"]},
    "rule.edit": {
        "label": "Requirement rule edit", "capture": _capture_rule,
        "apply": _apply_rule, "summarize": lambda p: p["values"]["label"]},
    "inventory.item.new": {
        "label": "New inventory item", "capture": _capture_inventory_item,
        "apply": _apply_inventory_item,
        "summarize": lambda p: (p["values"]["make"] + " " + p["values"]["model"]).strip()
                     or p["values"]["category"]},
    "inventory.item.edit": {
        "label": "Inventory item edit", "capture": _capture_inventory_item,
        "apply": _apply_inventory_item,
        "summarize": lambda p: (p["values"]["make"] + " " + p["values"]["model"]).strip()
                     or p["values"]["category"]},
    "inventory.tool.new": {
        "label": "New tool", "capture": _capture_inventory_tool,
        "apply": _apply_inventory_tool, "summarize": lambda p: p["values"]["name"]},
    "inventory.tool.edit": {
        "label": "Tool edit", "capture": _capture_inventory_tool,
        "apply": _apply_inventory_tool, "summarize": lambda p: p["values"]["name"]},
    "inventory.vehicle.new": {
        "label": "New vehicle", "capture": _capture_inventory_vehicle,
        "apply": _apply_inventory_vehicle, "summarize": lambda p: p["values"]["name"]},
    "inventory.vehicle.edit": {
        "label": "Vehicle edit", "capture": _capture_inventory_vehicle,
        "apply": _apply_inventory_vehicle, "summarize": lambda p: p["values"]["name"]},
    "household_member.new": {
        "label": "New household member", "capture": _capture_household_member,
        "apply": _apply_household_member, "summarize": lambda p: p["values"]["name"]},
    "household_member.edit": {
        "label": "Household member edit", "capture": _capture_household_member,
        "apply": _apply_household_member, "summarize": lambda p: p["values"]["name"]},
    "household_txn.new": {
        "label": "New household transaction", "capture": _capture_household_txn,
        "apply": _apply_household_txn, "save_file": lambda: _save_draft_file("receipt"),
        "summarize": lambda p: (f"{p['values']['kind']}: ${p['values']['amount']:,.2f}"
                                f" ({p['values']['category'] or '—'})")},
    "household_txn.edit": {
        "label": "Household transaction edit", "capture": _capture_household_txn,
        "apply": _apply_household_txn, "save_file": lambda: _save_draft_file("receipt"),
        "summarize": lambda p: (f"{p['values']['kind']}: ${p['values']['amount']:,.2f}"
                                f" ({p['values']['category'] or '—'})")},
    "household_budget.new": {
        "label": "New budget category", "capture": _capture_household_budget,
        "apply": _apply_household_budget,
        "summarize": lambda p: f"{p['category']}: ${p['monthly_amount']:,.2f}/mo"},
    "household_budget.edit": {
        "label": "Budget category edit", "capture": _capture_household_budget,
        "apply": _apply_household_budget,
        "summarize": lambda p: f"{p['category']}: ${p['monthly_amount']:,.2f}/mo"},
    "household_txn.toggle_paid": {
        "label": "Toggle Budget transaction paid/outstanding", "capture": lambda **_: ({}, []),
        "apply": _apply_household_txn_toggle_paid, "summarize": lambda p: "Toggle paid/outstanding"},
    "loan_account.new": {
        "label": "New loan account", "capture": _capture_loan_account,
        "apply": _apply_loan_account, "summarize": lambda p: p["values"]["name"]},
    "loan_account.edit": {
        "label": "Loan account edit", "capture": _capture_loan_account,
        "apply": _apply_loan_account, "summarize": lambda p: p["values"]["name"]},
    "loan_entry.new": {
        "label": "New loan entry", "capture": _capture_loan_entry,
        "apply": _apply_loan_entry, "save_file": lambda: _save_draft_file("statement"),
        "summarize": lambda p: f"{p['values']['kind']}: ${p['values']['amount']:,.2f}"},
    "savings_account.new": {
        "label": "New savings account", "capture": _capture_savings_account,
        "apply": _apply_savings_account, "summarize": lambda p: p["values"]["name"]},
    "savings_account.edit": {
        "label": "Savings account edit", "capture": _capture_savings_account,
        "apply": _apply_savings_account, "summarize": lambda p: p["values"]["name"]},
    "savings_entry.new": {
        "label": "New savings entry", "capture": _capture_savings_entry,
        "apply": _apply_savings_entry, "save_file": lambda: _save_draft_file("statement"),
        "summarize": lambda p: f"{p['values']['kind']}: ${p['values']['amount']:,.2f}"},
    "project_txn.add": {
        "label": "New project transaction", "capture": _capture_project_transaction,
        "apply": _apply_project_transaction, "save_file": lambda: _save_draft_file("document"),
        "summarize": lambda p: f"{p['doc_type'] or p['kind']}: ${p['amount']:,.2f}"},
    "project_txn.toggle_paid": {
        "label": "Transaction payment status", "capture": _capture_toggle_paid,
        "apply": _apply_toggle_transaction_paid,
        "summarize": lambda p: "Toggle paid/outstanding"},
    "wishlist.approve": {
        "label": "Wishlist recommendation", "capture": lambda **_: ({"status": "Approved"}, []),
        "apply": _apply_wishlist_review, "summarize": lambda p: "Recommend: Approve"},
    "wishlist.reject": {
        "label": "Wishlist recommendation", "capture": lambda **_: ({"status": "Rejected"}, []),
        "apply": _apply_wishlist_review, "summarize": lambda p: "Recommend: Reject"},
    "submission.approve": {
        "label": "Work Bag submission recommendation", "capture": _capture_submission_approval,
        "apply": _apply_submission_approval, "summarize": lambda p: "Recommend: Approve"},
    "submission.reject": {
        "label": "Work Bag submission recommendation", "capture": lambda **_: ({}, []),
        "apply": _apply_submission_rejection, "summarize": lambda p: "Recommend: Reject"},
}


@app.route("/drafts")
@admin_required
def drafts_page():
    db = get_db()
    show = request.args.get("show", "pending")
    where = "WHERE d.status = 'Pending'" if show == "pending" else ""
    rows = db.execute(
        "SELECT d.*, m.name AS proposer_name FROM drafts d"
        " JOIN household_members m ON m.id = d.created_by"
        f" {where} ORDER BY (d.status='Pending') DESC, d.id DESC LIMIT 200").fetchall()
    drafts = []
    for r in rows:
        spec = DRAFT_KINDS.get(r["kind"], {})
        payload = json.loads(r["payload"])
        try:
            summary = spec["summarize"](payload) if "summarize" in spec else ""
        except Exception:
            summary = ""
        drafts.append({
            "row": r, "label": spec.get("label", r["kind"]),
            "summary": summary, "has_file": bool(r["file_stored_name"]),
        })
    return render_template("drafts.html", drafts=drafts, show=show)


@app.route("/drafts/<int:draft_id>/approve", methods=["POST"])
@admin_required
def approve_draft(draft_id):
    db = get_db()
    draft = db.execute("SELECT * FROM drafts WHERE id = ? AND status = 'Pending'", (draft_id,)).fetchone()
    if draft is None:
        flash("Draft not found or already reviewed.", "error")
        return redirect(url_for("drafts_page"))
    spec = DRAFT_KINDS[draft["kind"]]
    proposer = db.execute("SELECT name FROM household_members WHERE id = ?",
                          (draft["created_by"],)).fetchone()
    who = current_user()
    # Recommendation-style kinds (approve/reject a pending item someone else
    # submitted) attribute reviewed_by to whoever actually exercised the
    # review judgment -- the approving Parent, not the Assistant that only
    # flagged a recommendation. Every other kind keeps the proposer's name.
    is_recommendation = draft["kind"].startswith(("wishlist.", "submission."))
    actor_name = (who["name"] if who else "") if is_recommendation \
        else (proposer["name"] if proposer else "Assistant")
    ok, message, _new_id = spec["apply"](
        db, json.loads(draft["payload"]), draft["ref_id"], actor_name,
        draft_file_stored_name=draft["file_stored_name"] or None,
        exclude_id=who["id"] if who else None)
    if not ok:
        flash(message, "error")
        return redirect(url_for("drafts_page"))
    db.execute(
        "UPDATE drafts SET status = 'Approved', reviewed_by = ?, reviewed_at = datetime('now')"
        " WHERE id = ?", (who["name"] if who else "", draft_id))
    db.commit()
    flash(message)
    return redirect(url_for("drafts_page"))


@app.route("/drafts/<int:draft_id>/discard", methods=["POST"])
@admin_required
def discard_draft(draft_id):
    db = get_db()
    draft = db.execute("SELECT * FROM drafts WHERE id = ? AND status = 'Pending'", (draft_id,)).fetchone()
    if draft is None:
        flash("Draft not found or already reviewed.", "error")
        return redirect(url_for("drafts_page"))
    if draft["file_stored_name"]:
        _discard_draft_file(draft["file_stored_name"])
    who = current_user()
    db.execute(
        "UPDATE drafts SET status = 'Discarded', reviewed_by = ?, reviewed_at = datetime('now')"
        " WHERE id = ?", (who["name"] if who else "", draft_id))
    db.commit()
    flash("Draft discarded.")
    return redirect(url_for("drafts_page"))



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
        ensure_routine_task_reminders(conn)
        ensure_requirement_reminders(conn)
        ensure_appointment_reminders(conn)
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

# Piece 48: a second, project-scoped system prompt for the "🧠 Plan" tab's
# brainstorm chat -- same read-only design as the assistant above (no
# write-tools exist for either), but it may propose concrete next-step tasks
# via a fixed "TASK: " line convention that the Plan tab's JS parses into an
# "➕ Add to project" button. The human still has to click it -- nothing is
# ever saved by the model itself.
PROJECT_PLAN_SYSTEM_PROMPT = (
    "You are a project-planning brainstorming aide inside the Compendium Assistant, "
    "scoped to ONE household project. Help the user think through how to complete "
    "THIS project — break down remaining work, surface risks or blockers, ask "
    "clarifying questions, and suggest a rough plan tailored to its category and "
    "subcategory.\n\n"
    "You are given PROJECT CONTEXT (category/subcategory, stage, existing tasks, "
    "recent field notes) plus the same read-only household tools as the general "
    "assistant, for extra grounding if needed. You are read-only: you cannot save "
    "anything yourself. If a concrete, addable next-step task occurs to you, put it "
    "alone on its own line in EXACTLY this form (nothing else on that line):\n"
    "TASK: <short task title>\n"
    "Use this sparingly, only for genuinely actionable next steps — not for every "
    "idea. Never use this line format for anything else. Everything else is normal "
    "conversational prose. Be concise and specific to this project; don't repeat "
    "tasks or notes that already exist."
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
    """A compact snapshot of the current household state, given to the model as
    grounding context."""
    lines = []
    name = user["name"] if user else "the user"
    role = (user["role"] or "") if user else ""
    lines.append(f"Signed-in user: {name} — role: {role or 'none'}.")
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

    # Piece 51: contract/financial figures are finances.manage-gated
    # everywhere else in the app (Budget page, Billing tab, dashboard money
    # tiles) -- the assistant must respect the same gate, or a Child could
    # just ask the AI for numbers the UI otherwise hides entirely.
    if has_permission("finances.manage"):
        row = db.execute(
            "SELECT COUNT(*) n, COALESCE(SUM(contract_amount),0) t FROM projects"
            " WHERE status NOT IN ('Done','Abandoned')"
            " AND COALESCE(contract_amount,0) > 0").fetchone()
        if row and row["n"]:
            lines.append(
                f"Active projects with a contract total: {row['n']}, "
                f"summing ${row['t']:,.0f}.")

    return "\n".join(lines)


def build_project_plan_context(db, project):
    """Piece 48: compact, project-scoped grounding for the "🧠 Plan" tab's
    brainstorm chat -- mirrors build_assistant_snapshot's compactness above,
    but scoped to ONE project instead of the whole household."""
    lines = [f"Project: {project['job_name'] or 'Project #' + str(project['id'])}"]
    cat, sub = project["project_category"] or "", project["project_type"] or ""
    if cat or sub:
        lines.append(f"Category: {cat or '—'}" + (f" · Subcategory: {sub}" if sub else ""))
    lines.append(f"Current stage: {project['status'] or 'Planning'}")
    if project["site_location"]:
        lines.append(f"Site/location: {project['site_location']}")
    lines.append(f"Target/completion date: {project['install_date'] or 'not set'}")

    tasks = db.execute(
        "SELECT title, status, due_date, COALESCE(pipeline_status,'') AS ps"
        " FROM project_tasks WHERE project_id = ? ORDER BY (status='Done'), sort_order LIMIT 40",
        (project["id"],)).fetchall()
    open_tasks = [t for t in tasks if t["status"] != "Done"]
    done_count = sum(1 for t in tasks if t["status"] == "Done")
    if open_tasks:
        lines.append(f"Open tasks ({len(open_tasks)}, {done_count} done):")
        for t in open_tasks:
            lines.append(f"  • {t['title']} — due {t['due_date'] or 'no date'}"
                         f" [{t['status']}{'/' + t['ps'] if t['ps'] else ''}]")
    else:
        lines.append(f"No open tasks yet ({done_count} done).")

    notes = db.execute(
        "SELECT note, created_at FROM project_notes WHERE project_id = ?"
        " ORDER BY id DESC LIMIT 5", (project["id"],)).fetchall()
    total_notes = db.execute(
        "SELECT COUNT(*) FROM project_notes WHERE project_id = ?", (project["id"],)).fetchone()[0]
    if notes:
        lines.append(f"Recent field notes ({total_notes} total):")
        for n in notes:
            lines.append(f"  • {(n['created_at'] or '')[:10]}: {n['note']}")
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
    no tool exposes pay. Each returns a compact text block for the model to read."""
    # Piece 51: contract/financial figures are finances.manage-gated
    # everywhere else in the app -- these tools must match, or a Child could
    # just ask the AI for numbers the UI otherwise hides entirely.
    can_finances = has_permission("finances.manage")

    def find_projects(args):
        text = (args.get("text") or "").strip()
        stage = (args.get("stage") or "").strip()
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
        if can_finances and args.get("min_contract") not in (None, ""):
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
            "SELECT id, job_name, status, install_date,"
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
                    f"{r['status']} — target date {r['install_date'] or 'none set'}")
            if can_finances and r["amt"]:
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
               f"Target date: {row['install_date'] or 'none set'}"]
        if can_finances and (row["contract_amount"] or 0):
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
                         "'projects in Prep', 'overdue projects', or a project name search."),
         "parameters": {"type": "object", "properties": {
             "text": {"type": "string", "description": "match project name"},
             "stage": {"type": "string", "description": f"pipeline stage; one of: {stages}"},
             "overdue_only": {"type": "boolean", "description": "only projects with an overdue task"},
             "min_contract": {"type": "number", "description": "minimum contract total"},
             "limit": {"type": "integer", "description": "max rows (default 25)"}}},
         "run": find_projects},
        {"name": "project_details",
         "description": ("Full detail for one project by name or #id: stage, target "
                         "date, open tasks, materials, recent notes, and contract total."),
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


@app.route("/projects/<int:project_id>/plan/ask", methods=["POST"])
def project_plan_ask(project_id):
    """Piece 48: the "🧠 Plan" tab's brainstorm chat. Same read-only design as
    /assistant/ask -- the model never writes anything; it may only suggest a
    task via a "TASK: " line, which the tab's JS turns into an ➕ Add button
    that a human has to click. The conversation itself is persisted per
    project so it can be reopened/continued later."""
    project = fetch_project(project_id)
    db = get_db()
    cfg = assistant_settings(db)
    message = (request.form.get("message", "") or "").strip()
    provider = request.form.get("provider", cfg["default_provider"]) or "claude"
    if provider not in ("claude", "gemini"):
        provider = "claude"
    if not message:
        return jsonify({"error": "Type a message first."}), 400
    if not _provider_configured(cfg, provider):
        return jsonify({"error": f"No API key is set for {provider.title()}. "
                        "An admin can add one under AI settings."}), 400
    user = current_user()
    author = user["name"] if user else ""

    # Persist the user's turn immediately so it isn't lost if the AI call fails.
    db.execute("INSERT INTO project_plan_messages (project_id, role, author, content)"
               " VALUES (?, 'user', ?, ?)", (project_id, author, message))
    db.commit()

    prior = db.execute(
        "SELECT role, author, content FROM project_plan_messages"
        " WHERE project_id = ? ORDER BY id", (project_id,)).fetchall()
    history_lines = []
    for r in prior[:-1][-20:]:  # last 20 prior turns -- hard cap, no unbounded growth
        who = f"User ({r['author']})" if r["role"] == "user" and r["author"] else (
            "User" if r["role"] == "user" else "Assistant")
        history_lines.append(f"{who}: {r['content']}")
    history_block = ("Previous conversation:\n" + "\n".join(history_lines) + "\n\n") if history_lines else ""

    context = build_project_plan_context(db, project)
    prompt = (f"PROJECT CONTEXT:\n{context}\n\n{history_block}"
              f"NEW MESSAGE from {author or 'the user'}: {message}")
    key = cfg["gemini_key"] if provider == "gemini" else cfg["claude_key"]
    model = cfg["gemini_model"] if provider == "gemini" else cfg["claude_model"]
    tools = build_assistant_tools(db, user)
    try:
        answer = ai_assistant.run_agent(provider, key, model,
                                        PROJECT_PLAN_SYSTEM_PROMPT, prompt, tools)
    except ai_assistant.AssistantError as e:
        return jsonify({"error": str(e)}), 502
    db.execute("INSERT INTO project_plan_messages (project_id, role, author, content)"
               " VALUES (?, 'assistant', '', ?)", (project_id, answer))
    db.commit()
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
