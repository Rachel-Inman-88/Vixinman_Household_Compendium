-- Job Creator database schema.
-- Clients: Vixinman Designs' intake fields (Piece 2, revised).
-- Jobs: job profiles stored under a client (Piece 3).
-- Resource rules arrive in Piece 4.

CREATE TABLE IF NOT EXISTS clients (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    phone           TEXT DEFAULT '',
    -- Piece 15: addresses are captured as separate fields to reduce typos.
    -- mailing_address / billing_address stay as the composed full strings
    -- (used by search, the roster, and job pre-fill) built from the parts.
    mailing_street  TEXT DEFAULT '',
    mailing_city    TEXT DEFAULT '',
    mailing_state   TEXT DEFAULT '',
    mailing_zip     TEXT DEFAULT '',
    billing_street  TEXT DEFAULT '',
    billing_city    TEXT DEFAULT '',
    billing_state   TEXT DEFAULT '',
    billing_zip     TEXT DEFAULT '',
    mailing_address TEXT DEFAULT '',
    billing_address TEXT DEFAULT '',
    email           TEXT DEFAULT '',
    referral_source TEXT DEFAULT '',
    notes           TEXT DEFAULT '',
    -- Piece 16: lead lifecycle. lead_status is 'Lead' (new prospect, in the
    -- follow-up cadence), 'Converted' (has a job), or 'Cold' (only used on the
    -- cold_leads table). assigned_rep_id owns the follow-ups.
    lead_status     TEXT DEFAULT 'Lead',
    assigned_rep_id INTEGER,
    converted_at    TEXT DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Piece 17.1: soft-delete trash. A deleted row is snapshotted here (full
-- original row as JSON, plus its origin table + a "where it was" label) and
-- removed from its own table, so it can be restored to exactly where it came
-- from or permanently purged by the General Manager.
CREATE TABLE IF NOT EXISTS trash (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type  TEXT NOT NULL,
    origin_table TEXT NOT NULL,
    original_id  INTEGER,
    found_in     TEXT DEFAULT '',
    label        TEXT DEFAULT '',
    payload      TEXT NOT NULL,
    deleted_by   TEXT DEFAULT '',
    deleted_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Piece 17: granular per-employee access grants handed out by the General
-- Manager. Each row = "this employee has this permission until expires_on"
-- (blank expires_on = no expiry).
CREATE TABLE IF NOT EXISTS permission_grants (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    permission  TEXT NOT NULL,
    granted_by  TEXT DEFAULT '',
    granted_at  TEXT NOT NULL DEFAULT (datetime('now')),
    expires_on  TEXT DEFAULT ''
);

-- Piece 16: scheduled follow-ups for a new lead (7 days / 2 weeks / 1 month).
-- Generated on demand; surfaced on the home page and the task board.
CREATE TABLE IF NOT EXISTS lead_followups (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id  INTEGER NOT NULL REFERENCES clients(id),
    rep_id     INTEGER,
    milestone  TEXT NOT NULL,            -- '7-day' / '2-week' / '1-month'
    due_date   TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'Open',  -- Open / Done / Converted / Cold
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    done_at    TEXT DEFAULT ''
);

-- Piece 16: leads marked "cold" are moved out of clients into here (they have
-- no jobs). Kept for reference; flagged stale after 6 months for admin purge.
CREATE TABLE IF NOT EXISTS cold_leads (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT NOT NULL,
    phone             TEXT DEFAULT '',
    email             TEXT DEFAULT '',
    referral_source   TEXT DEFAULT '',
    notes             TEXT DEFAULT '',
    mailing_street    TEXT DEFAULT '',
    mailing_city      TEXT DEFAULT '',
    mailing_state     TEXT DEFAULT '',
    mailing_zip       TEXT DEFAULT '',
    billing_street    TEXT DEFAULT '',
    billing_city      TEXT DEFAULT '',
    billing_state     TEXT DEFAULT '',
    billing_zip       TEXT DEFAULT '',
    mailing_address   TEXT DEFAULT '',
    billing_address   TEXT DEFAULT '',
    assigned_rep_id   INTEGER,
    cold_reason       TEXT DEFAULT '',
    original_created_at TEXT DEFAULT '',
    cold_at           TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Piece 15: prior-version history for client profiles. Each edit snapshots
-- the outgoing values (JSON) plus the list of changed-field labels. The old
-- data is hidden from the profile; only admins can open the history.
CREATE TABLE IF NOT EXISTS client_versions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id      INTEGER NOT NULL REFERENCES clients(id),
    version        INTEGER NOT NULL,
    data           TEXT NOT NULL,          -- JSON snapshot of the old values
    changed_fields TEXT NOT NULL DEFAULT '[]',  -- JSON list of changed labels
    edited_by      TEXT DEFAULT '',
    saved_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS jobs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id        INTEGER NOT NULL REFERENCES clients(id),
    job_name         TEXT DEFAULT '',   -- the name used in bookkeeping records
    site_location    TEXT DEFAULT '',   -- address or GPS coordinates; .kmz link planned
    county           TEXT DEFAULT '',
    electric_loads   TEXT DEFAULT '',
    utility_provider TEXT DEFAULT '',
    warranty_type    TEXT DEFAULT '',
    cost_method      TEXT DEFAULT '',
    tax_credit       TEXT DEFAULT 'No',
    expand_option    TEXT DEFAULT 'No',
    products         TEXT DEFAULT '',   -- comma-separated selections
    -- Product-specific options; blank unless the product is selected.
    pv_utility_connection        TEXT DEFAULT '',  -- Off-grid / Grid-tie / Backup system
    pv_mounting_type             TEXT DEFAULT '',  -- Roof mounted / Ground mount
    pv_manufactured_house        TEXT DEFAULT '',  -- Yes when roof mounted on a manufactured house
    generator_utility_connection TEXT DEFAULT '',  -- Off-grid / Grid-tie / Backup system
    battery_utility_connection   TEXT DEFAULT '',  -- Off-grid / Grid-tie / Backup system
    service_type     TEXT DEFAULT '',   -- General service / Warranty service
    property_type    TEXT DEFAULT 'Residential',  -- Residential / Commercial
    status           TEXT NOT NULL DEFAULT 'Proposal',  -- Piece 16 pipeline stage
    install_date     TEXT DEFAULT '',   -- Piece 18: set in Job Prep; gates Installation
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Piece 4: the rules engine. Each row: "when job.<field_name> matches
-- <field_value>, this job needs <label>". Categories group the output
-- (License / Permit / Compliance / Link / Phone / Doc). match_type
-- 'contains' is for list fields like products; 'equals' for single values.
-- Prior states of edited jobs, kept for recordkeeping. data is a JSON
-- snapshot of every job field at the moment it was replaced.
CREATE TABLE IF NOT EXISTS job_versions (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id   INTEGER NOT NULL REFERENCES jobs(id),
    version  INTEGER NOT NULL,
    data     TEXT NOT NULL,
    saved_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Piece 7: material list per job.
CREATE TABLE IF NOT EXISTS job_materials (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id     INTEGER NOT NULL REFERENCES jobs(id),
    item       TEXT NOT NULL,
    quantity   TEXT DEFAULT '',
    unit       TEXT DEFAULT '',
    supplier   TEXT DEFAULT '',
    status     TEXT NOT NULL DEFAULT 'Needed',  -- Needed/Ordered/Received/Installed
    notes      TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Piece 7: uploaded documents per job; optionally tied to a requirement
-- label so the requirements panel can show filing coverage.
CREATE TABLE IF NOT EXISTS job_files (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id        INTEGER NOT NULL REFERENCES jobs(id),
    rule_label    TEXT DEFAULT '',   -- requirement this document satisfies
    stored_name   TEXT NOT NULL,     -- name on disk (uploads/job_<id>/)
    original_name TEXT NOT NULL,
    task_id       TEXT DEFAULT '',   -- Piece 21.7: field photos tie back to a task
    uploaded_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Piece 21.9: free-form field notes on a job, jotted from the Work Bag for the
-- office to read later. Each note carries its own timestamp (same clock as the
-- audit log) and author.
CREATE TABLE IF NOT EXISTS job_notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id     INTEGER NOT NULL REFERENCES jobs(id),
    note       TEXT NOT NULL DEFAULT '',
    author     TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- App metadata (e.g. which rule seed batches have been applied).
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- Piece 8: the employee directory. Vixinman's crew, kept separate from
-- clients/jobs. Each row records who the person is (name), what they do
-- (roles — comma-separated selections), the licenses and certifications
-- they hold, and their working schedule.
CREATE TABLE IF NOT EXISTS employees (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    name                    TEXT NOT NULL,     -- composed display name "First Last"
    first_name              TEXT DEFAULT '',   -- Piece 19.3
    last_name               TEXT DEFAULT '',
    nickname                TEXT DEFAULT '',
    roles                   TEXT DEFAULT '',   -- comma-separated selections
    licenses_certifications TEXT DEFAULT '',   -- legacy free-text (Piece 8.0)
    schedule                TEXT DEFAULT '',
    created_at              TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Piece 8.1: each license/certification an employee holds as its own row,
-- so expiry can be tracked and flagged. rule_label optionally ties the
-- credential to a License requirement in resource_rules, which lets a job
-- page show whether someone on staff holds the licenses it requires.
CREATE TABLE IF NOT EXISTS employee_credentials (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    name        TEXT NOT NULL,
    rule_label  TEXT DEFAULT '',   -- License requirement this satisfies
    number      TEXT DEFAULT '',
    issued      TEXT DEFAULT '',   -- YYYY-MM-DD
    expires     TEXT DEFAULT '',   -- YYYY-MM-DD; blank = no expiry
    notes       TEXT DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Piece 8.1: uploaded copies of an employee's credentials/documents;
-- optionally tied to one credential by name. Files live on disk in
-- uploads/employee_<id>/, not in the database.
CREATE TABLE IF NOT EXISTS employee_files (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id     INTEGER NOT NULL REFERENCES employees(id),
    credential_name TEXT DEFAULT '',   -- credential this documents (optional)
    stored_name     TEXT NOT NULL,     -- name on disk
    original_name   TEXT NOT NULL,
    uploaded_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Piece 9: Electric Loads Calculator / System Sizing, ported from the
-- standalone loads_calculator.html field tool. Catalogs are global
-- reference data (shared across every job, editable at /catalog);
-- the survey, bill of materials, and sizing inputs are per-job.
CREATE TABLE IF NOT EXISTS appliance_catalog (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    category    TEXT DEFAULT '',
    era         TEXT DEFAULT '',   -- Modern / Vintage / '' (era-agnostic)
    low_w       REAL DEFAULT 0,
    high_w      REAL DEFAULT 0,
    avg_w       REAL DEFAULT 0,
    hrs_per_day REAL DEFAULT 0,
    usage_type  TEXT DEFAULT '',
    notes       TEXT DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS component_catalog (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    name                   TEXT NOT NULL,
    category               TEXT DEFAULT '',
    manufacturer           TEXT DEFAULT '',
    model                  TEXT DEFAULT '',
    specs                  TEXT DEFAULT '',
    watts                  REAL,
    voc                    REAL,
    vmp                    REAL,
    temp_coef_voc          REAL,
    capacity_kwh_nameplate REAL,
    dod                    REAL,
    max_input_v            REAL,
    continuous_w           REAL,
    inverter_eff           REAL,
    cost                   REAL,
    notes                  TEXT DEFAULT '',
    created_at             TEXT NOT NULL DEFAULT (datetime('now'))
);

-- A room in a job's load survey. room_type 'scenario' marks a custom
-- use-case room (seasonal/unusual load) that can be excluded from
-- totals via `enabled` without deleting the data.
CREATE TABLE IF NOT EXISTS job_load_rooms (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id     INTEGER NOT NULL REFERENCES jobs(id),
    name       TEXT NOT NULL,
    room_type  TEXT NOT NULL DEFAULT 'standard',  -- standard / scenario
    enabled    INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS job_load_items (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id     INTEGER NOT NULL REFERENCES jobs(id),
    room_id    INTEGER NOT NULL REFERENCES job_load_rooms(id),
    appliance  TEXT NOT NULL,
    watts      REAL NOT NULL DEFAULT 0,
    qty        REAL NOT NULL DEFAULT 1,
    hrs        REAL NOT NULL DEFAULT 0,
    usage_type TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Bill of materials per job, pulled from component_catalog (component_id
-- set) or hand-entered (component_id NULL). Name/category/cost are
-- snapshotted at add-time so catalog price edits don't rewrite history.
CREATE TABLE IF NOT EXISTS job_bom (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id         INTEGER NOT NULL REFERENCES jobs(id),
    component_id   INTEGER REFERENCES component_catalog(id),
    component_name TEXT NOT NULL,
    category       TEXT DEFAULT '',
    qty            REAL NOT NULL DEFAULT 1,
    unit_cost      REAL,
    notes          TEXT DEFAULT '',
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

-- One row per job: System Sizing inputs + the Sales/Designer view mode.
-- Outputs (array kW, panel count, battery kWh, Voc string...) are
-- computed on the fly from these inputs plus the load survey, not stored.
CREATE TABLE IF NOT EXISTS job_sizing (
    job_id              INTEGER PRIMARY KEY REFERENCES jobs(id),
    ui_mode             TEXT NOT NULL DEFAULT 'designer',  -- sales / designer
    system_type         TEXT NOT NULL DEFAULT 'custom',    -- offgrid / gridtie / custom
    sun_hours           REAL DEFAULT 5.5,
    derate_pct          REAL DEFAULT 75,
    autonomy_days       REAL DEFAULT 2,
    solar_fraction_pct  REAL DEFAULT 100,
    panel_watts         REAL DEFAULT 400,
    dod_pct             REAL DEFAULT 80,
    round_trip_eff_pct  REAL DEFAULT 92,
    inverter_eff_pct    REAL DEFAULT 96,
    max_input_v         REAL DEFAULT 600,
    record_low_temp_f   REAL DEFAULT 5,
    backup_daily_kwh    REAL DEFAULT 0,
    selected_battery_id INTEGER REFERENCES component_catalog(id),
    selected_pv_module_id INTEGER REFERENCES component_catalog(id),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS resource_rules (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    field_name  TEXT NOT NULL,
    field_value TEXT NOT NULL,
    match_type  TEXT NOT NULL DEFAULT 'equals',
    category    TEXT NOT NULL DEFAULT 'Compliance',
    label       TEXT NOT NULL,
    url         TEXT DEFAULT '',
    phone       TEXT DEFAULT '',
    notes       TEXT DEFAULT '',
    -- Optional second condition (AND): e.g. products includes Battery Banks
    -- AND property_type is Commercial.
    field_name2  TEXT DEFAULT '',
    field_value2 TEXT DEFAULT '',
    match_type2  TEXT DEFAULT 'equals',
    link_text    TEXT DEFAULT '',      -- display name for the url

    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Piece 10: per-job tasks, each optionally assigned to an employee. The
-- assignee is a nullable reference (NULL = unassigned); deleting an
-- employee unassigns their tasks rather than removing the work. Drives the
-- "Tasks" tab on a job and the "assigned to me" list on an employee.
CREATE TABLE IF NOT EXISTS job_tasks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id       INTEGER NOT NULL REFERENCES jobs(id),
    employee_id  INTEGER REFERENCES employees(id),   -- NULL = unassigned
    title        TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'To do',      -- To do/In progress/Blocked/Done
    due_date     TEXT DEFAULT '',                    -- YYYY-MM-DD; blank = none
    notes        TEXT DEFAULT '',
    sort_order   INTEGER NOT NULL DEFAULT 0,
    completed_at TEXT DEFAULT '',
    pipeline_status TEXT DEFAULT '',                    -- Piece 18.1: which stage this step belongs to
    updated_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),  -- Piece 14: sync
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Piece 13.2: password self-service. A signed-in user proposes a new
-- password (stored already-hashed, never plaintext); an admin approves or
-- rejects it, and only on approval is it applied to the account.
CREATE TABLE IF NOT EXISTS password_requests (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id  INTEGER NOT NULL REFERENCES employees(id),
    new_hash     TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'Pending',  -- Pending / Approved / Rejected
    requested_at TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_at  TEXT DEFAULT '',
    resolved_by  TEXT DEFAULT ''
);

-- Piece 29.1: self-service password reset. Each employee may enrol a few
-- security questions; the answer is stored only as a salted hash (normalised
-- to lower-case/trimmed before hashing). Answering them correctly lets the
-- person set a new password themselves from the login page, with no admin
-- approval. One row per question; replacing the set deletes and re-inserts.
CREATE TABLE IF NOT EXISTS security_answers (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id  INTEGER NOT NULL REFERENCES employees(id),
    question     TEXT NOT NULL,
    answer_hash  TEXT NOT NULL,
    sort_order   INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Piece 29.2: new-employee onboarding. `onboarding_steps` is the company-wide
-- checklist template (editable by anyone who can manage employees); it's seeded
-- once with a sensible default set. Per-employee completion is tracked in
-- `employee_onboarding` (one row per step the person has been marked on). A new
-- step added later simply shows as "not done" for everyone until checked.
CREATE TABLE IF NOT EXISTS onboarding_steps (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    description TEXT DEFAULT '',
    category    TEXT DEFAULT '',       -- optional grouping (HR, Safety, IT, …)
    sort_order  INTEGER NOT NULL DEFAULT 0,
    active      TEXT NOT NULL DEFAULT '1',   -- '1' active, '' archived
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
-- Piece 29.6: Finance reference data. NM gross-receipts-tax rate per county
-- (jobs auto-fill their GRT rate from the install county), and the default
-- equipment markup % per catalog category (turns Vixinman's cost into the customer
-- price). Both are seeded once and edited on the Finance Settings page.
CREATE TABLE IF NOT EXISTS county_tax_rates (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    county    TEXT NOT NULL UNIQUE,      -- bare county name, e.g. "Santa Fe"
    grt_rate  REAL NOT NULL DEFAULT 0,   -- percent, e.g. 7.9375
    updated_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS markup_categories (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    category   TEXT NOT NULL UNIQUE,
    markup_pct REAL NOT NULL DEFAULT 0   -- percent added to unit cost
);

-- Piece 29.8: Vixinman's Cost Model Defaults — the estimating template behind job
-- pricing. One row per line, grouped by section (Equipment Inventory, Equipment
-- Non-Inventory, Labor, Travel, Adders, Overhead). Equipment Inventory rows are
-- the per-category equipment markups (feed the BOM); other sections carry a
-- default qty, unit cost, unit label, and markup. Overhead rows are a percent
-- (in markup_pct) applied to the whole job subtotal. Seeded once, then edited
-- on the Cost Model page.
CREATE TABLE IF NOT EXISTS cost_model_lines (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    section     TEXT NOT NULL,
    item        TEXT NOT NULL,
    unit        TEXT DEFAULT '',      -- e.g. Watts, Panels, Mile, Hour
    default_qty REAL,                 -- nullable
    unit_cost   REAL,                 -- nullable
    markup_pct  REAL NOT NULL DEFAULT 0,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    active      TEXT NOT NULL DEFAULT '1'
);

-- Piece 29.9: a job's estimate — quantities against the cost-model lines for
-- the non-equipment sections (Equipment Non-Inventory, Labor, Travel, Adders).
-- Each row is a snapshot (item/unit/cost/markup copied from the cost model when
-- added, then adjustable for this job) with the job-specific qty. Equipment
-- Inventory is priced from the job's BOM, not here; overhead is applied on top.
CREATE TABLE IF NOT EXISTS job_estimate_lines (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      INTEGER NOT NULL REFERENCES jobs(id),
    section     TEXT NOT NULL,
    item        TEXT NOT NULL,
    unit        TEXT DEFAULT '',
    qty         REAL NOT NULL DEFAULT 0,
    unit_cost   REAL NOT NULL DEFAULT 0,
    markup_pct  REAL NOT NULL DEFAULT 0,
    sort_order  INTEGER NOT NULL DEFAULT 0
);

-- Piece 29.3: lightweight in-app notifications (an inbox + nav bell). Used so
-- far to alert Supervisors/GM when a reset auto-locks an account, but general
-- purpose. One row per recipient.
-- Piece 30.8: "Boards" — standalone to-dos not tied to any job or client
-- (clean the bathroom, call X, …). Each can be assigned to a team member, carry
-- a running notes log, and log time spent.
CREATE TABLE IF NOT EXISTS boards (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT NOT NULL,
    details      TEXT DEFAULT '',
    assigned_to  INTEGER REFERENCES employees(id),   -- NULL = unassigned
    status       TEXT NOT NULL DEFAULT 'To do',       -- To do / In progress / Blocked / Done
    priority     TEXT DEFAULT '',                     -- '' / Low / Normal / High
    due_date     TEXT DEFAULT '',
    created_by   TEXT DEFAULT '',
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT DEFAULT '',
    completed_by TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS board_notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    board_id   INTEGER NOT NULL REFERENCES boards(id),
    author     TEXT DEFAULT '',
    note       TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS board_time (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    board_id    INTEGER NOT NULL REFERENCES boards(id),
    employee_id INTEGER REFERENCES employees(id),
    who         TEXT DEFAULT '',
    hours       REAL NOT NULL DEFAULT 0,
    work_date   TEXT DEFAULT '',
    note        TEXT DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS notifications (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    recipient_id INTEGER NOT NULL REFERENCES employees(id),
    message      TEXT NOT NULL,
    link         TEXT DEFAULT '',
    kind         TEXT DEFAULT '',
    is_read      TEXT NOT NULL DEFAULT '',   -- '1' once read
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS employee_onboarding (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    step_id     INTEGER NOT NULL REFERENCES onboarding_steps(id),
    done        TEXT NOT NULL DEFAULT '',    -- '1' complete
    done_at     TEXT DEFAULT '',
    done_by     TEXT DEFAULT '',
    note        TEXT DEFAULT '',
    UNIQUE(employee_id, step_id)
);

-- Piece 12: client-level document storage — files that belong to the
-- client across all their jobs (contracts, correspondence, intake, photos),
-- kept separate from a job's requirement documents. Files on disk in
-- uploads/client_<id>/, only metadata here.
CREATE TABLE IF NOT EXISTS client_files (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id     INTEGER NOT NULL REFERENCES clients(id),
    category      TEXT DEFAULT '',   -- Contracts / Correspondence / Intake / Photos / Other
    stored_name   TEXT NOT NULL,
    original_name TEXT NOT NULL,
    uploaded_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Piece 14.1: field work submissions. When a worker syncs completed work
-- from the field, it is saved here as a PENDING copy (with their reported
-- hours) — it does NOT change the authoritative task data or count as hours
-- until a manager (admin) approves it. On approval the item changes are
-- applied to job_tasks and approved_hours becomes the authoritative record.
CREATE TABLE IF NOT EXISTS field_submissions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id    INTEGER NOT NULL REFERENCES employees(id),
    work_date      TEXT DEFAULT '',       -- YYYY-MM-DD
    reported_hours REAL,                  -- hours the worker reported
    approved_hours REAL,                  -- hours the manager confirmed
    note           TEXT DEFAULT '',
    status         TEXT NOT NULL DEFAULT 'Pending',  -- Pending/Approved/Rejected
    submitted_at   TEXT NOT NULL DEFAULT (datetime('now')),
    reviewed_by    TEXT DEFAULT '',
    reviewed_at    TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS field_submission_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    submission_id   INTEGER NOT NULL REFERENCES field_submissions(id),
    task_id         INTEGER NOT NULL REFERENCES job_tasks(id),
    task_title      TEXT DEFAULT '',       -- snapshot, for the review screen
    new_status      TEXT DEFAULT '',
    new_notes       TEXT DEFAULT '',
    base_updated_at TEXT DEFAULT ''        -- task version the field edit was based on
);

-- Piece 11: system-wide audit log. Every state-changing request (POST) is
-- recorded centrally so nothing slips through. `actor` stays blank until
-- logins land (Piece 8 backlog); `entity` holds the URL parameters (which
-- record) and `detail` the submitted fields, both as JSON.
CREATE TABLE IF NOT EXISTS audit_log (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts       TEXT NOT NULL DEFAULT (datetime('now')),
    actor    TEXT DEFAULT '',       -- who (filled once logins exist)
    action   TEXT NOT NULL DEFAULT '',
    endpoint TEXT DEFAULT '',
    method   TEXT DEFAULT '',
    path     TEXT DEFAULT '',
    entity   TEXT DEFAULT '',       -- JSON of URL params (job_id, ...)
    detail   TEXT DEFAULT '',       -- JSON of submitted fields
    status   INTEGER,
    ip       TEXT DEFAULT ''
);

-- Piece 21: per-job financial ledger — income (deposits/invoices/rebates) and
-- expenses (materials, permits, labor, subs). Drives the Finance viewport's
-- Payments table and the QuickBooks CSV export. Dollar amounts stored as REAL.
CREATE TABLE IF NOT EXISTS job_transactions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      INTEGER NOT NULL REFERENCES jobs(id),
    kind        TEXT NOT NULL DEFAULT 'Expense',      -- Income / Expense
    category    TEXT DEFAULT '',                      -- 50% Deposit, Materials, Permit / Fees, ...
    description TEXT DEFAULT '',
    amount      REAL NOT NULL DEFAULT 0,
    txn_date    TEXT DEFAULT '',                      -- YYYY-MM-DD
    status      TEXT NOT NULL DEFAULT 'Outstanding',  -- Outstanding / Paid
    party       TEXT DEFAULT '',                      -- customer (income) or vendor (expense)
    reference   TEXT DEFAULT '',                      -- invoice / check / PO number
    method      TEXT DEFAULT '',                      -- Cash / Check / Card / ACH / Financing
    doc_type    TEXT DEFAULT '',                      -- Piece 21.5: Receipt / Invoice / Bill (source paperwork)
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    created_by  TEXT DEFAULT ''
);

-- Piece 21.2: payroll. pay_types is the calculation schema (each type is a
-- multiplier on the employee's base wage, or a flat $/hr). pay_rates holds
-- per-employee overrides of a type's value; time_entries are logged hours.
CREATE TABLE IF NOT EXISTS pay_types (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL DEFAULT '',
    method      TEXT NOT NULL DEFAULT 'multiplier',  -- multiplier / flat
    value       REAL NOT NULL DEFAULT 0,             -- default multiplier or flat $/hr
    sort_order  INTEGER NOT NULL DEFAULT 0,
    active      INTEGER NOT NULL DEFAULT 1,
    ot_eligible INTEGER NOT NULL DEFAULT 1           -- counts toward the weekly OT threshold
);
CREATE TABLE IF NOT EXISTS pay_rates (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    pay_type_id INTEGER NOT NULL REFERENCES pay_types(id),
    value       REAL NOT NULL DEFAULT 0             -- this person's multiplier or flat $/hr
);
CREATE TABLE IF NOT EXISTS time_entries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    work_date   TEXT DEFAULT '',                    -- YYYY-MM-DD
    job_id      INTEGER,                            -- optional job the hours were on
    pay_type_id INTEGER REFERENCES pay_types(id),
    hours       REAL NOT NULL DEFAULT 0,
    note        TEXT DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'Pending',    -- Pending / Approved (supervisor review)
    approved_by TEXT DEFAULT '',
    approved_at TEXT DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    created_by  TEXT DEFAULT ''
);

-- Piece 23.2: Inventory database (seeded from Vixinman's Inventory_respec workbook).
-- Vendors are the canonical supplier list; items carry the shared core fields
-- plus per-category specs as JSON. web_price/price_checked_on hold web-verified
-- pricing alongside (not replacing) the quoted Cost.
CREATE TABLE IF NOT EXISTS inventory_vendors (
    id   INTEGER PRIMARY KEY,      -- canonical vendor id from the workbook
    name TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS inventory_items (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    category         TEXT NOT NULL DEFAULT '',
    make             TEXT DEFAULT '',
    model            TEXT DEFAULT '',
    description      TEXT DEFAULT '',
    vendor_id        INTEGER REFERENCES inventory_vendors(id),
    vendor_number    TEXT DEFAULT '',
    cost             REAL,                    -- Vixinman's quoted/paid price
    web_price        REAL,                    -- web-verified price (Phase B)
    price_checked_on TEXT DEFAULT '',         -- YYYY-MM-DD of the web check
    purchase_url     TEXT DEFAULT '',         -- where to buy (from research)
    manual_url       TEXT DEFAULT '',         -- datasheet / user manual
    needed           INTEGER NOT NULL DEFAULT 0,
    available        INTEGER NOT NULL DEFAULT 0,
    on_po            INTEGER NOT NULL DEFAULT 0,
    active           INTEGER NOT NULL DEFAULT 1,
    status           TEXT NOT NULL DEFAULT 'Active',  -- Active / Discontinued (Piece 23.3)
    last_used        TEXT DEFAULT '',              -- Piece 23.4: last time used on a job (for the stale-stock notice)
    specs            TEXT NOT NULL DEFAULT '{}',   -- JSON of category-specific specs
    flags            TEXT DEFAULT '',              -- standardization / research notes
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Piece 23.2: hand/install tools (multimeter, pipe cutter, drill, ...).
CREATE TABLE IF NOT EXISTS inventory_tools (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL DEFAULT '',
    category     TEXT DEFAULT '',
    make         TEXT DEFAULT '',
    model        TEXT DEFAULT '',
    description  TEXT DEFAULT '',
    vendor_id    INTEGER REFERENCES inventory_vendors(id),
    cost         REAL,
    purchase_url TEXT DEFAULT '',
    manual_url   TEXT DEFAULT '',
    needed       INTEGER NOT NULL DEFAULT 0,
    available    INTEGER NOT NULL DEFAULT 0,
    notes        TEXT DEFAULT '',
    active       INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Piece 23.2: heavy equipment & vehicles (lift truck, ditch witch, ...), each
-- with a shop nickname.
CREATE TABLE IF NOT EXISTS inventory_vehicles (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL DEFAULT '',
    nickname     TEXT DEFAULT '',
    category     TEXT DEFAULT '',
    make         TEXT DEFAULT '',
    model        TEXT DEFAULT '',
    year         TEXT DEFAULT '',
    description  TEXT DEFAULT '',
    vendor_id    INTEGER REFERENCES inventory_vendors(id),
    cost         REAL,
    purchase_url TEXT DEFAULT '',
    manual_url   TEXT DEFAULT '',
    notes        TEXT DEFAULT '',
    active       INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Piece 24.4: stock ledger — every inventory movement (received / used / count
-- correction / adjust) writes a dated, signed row here. `inventory_items.available`
-- stays a cached running balance the ledger updates; `last_used` is the date of
-- the most recent 'used' row, which drives the stale-stock notice.
CREATE TABLE IF NOT EXISTS inventory_txns (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id     INTEGER NOT NULL REFERENCES inventory_items(id),
    kind        TEXT NOT NULL DEFAULT 'used',   -- received | used | count | adjust
    qty         INTEGER NOT NULL DEFAULT 0,      -- signed delta applied to available
    job_id      INTEGER REFERENCES jobs(id),     -- optional, for 'used' on a job
    note        TEXT DEFAULT '',
    created_by  TEXT DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_inventory_txns_item ON inventory_txns(item_id);

-- Piece 26.0: barcode/asset registry. Each row is a printed, scannable label
-- (unique serial) tied to an inventory entity. Non-consumables (tools / PPE /
-- vehicles) get one tag per physical unit and track In stock / Out; consumables
-- (components / hardware) get a SKU label whose scan-out records a 'used' stock
-- movement against the item + job (the inventory_txns ledger from Piece 24.4).
CREATE TABLE IF NOT EXISTS inventory_assets (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    serial         TEXT UNIQUE NOT NULL,
    kind           TEXT NOT NULL DEFAULT 'non_consumable',  -- consumable | non_consumable
    entity_type    TEXT NOT NULL,        -- inventory_item | inventory_tool | inventory_vehicle
    entity_id      INTEGER NOT NULL,
    label          TEXT DEFAULT '',       -- cached human description for the tag
    status         TEXT NOT NULL DEFAULT 'In stock',  -- In stock | Out | Retired
    job_id         INTEGER REFERENCES jobs(id),        -- current checkout (non-consumables)
    registered_by  TEXT DEFAULT '',
    registered_at  TEXT NOT NULL DEFAULT (datetime('now')),
    last_action    TEXT DEFAULT '',
    last_action_by TEXT DEFAULT '',
    last_action_at TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_inventory_assets_serial ON inventory_assets(serial);

-- Piece 28.5: stock-audit sessions. An audit scans the physical serials on the
-- shelf and reconciles them against the registered assets (inventory_assets) the
-- database expects to be "In stock" — optionally scoped to one category/type.
CREATE TABLE IF NOT EXISTS stock_audits (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    scope_kind  TEXT NOT NULL DEFAULT 'all',   -- all | category
    scope       TEXT DEFAULT '',                -- '' for all, else the category/type
    status      TEXT NOT NULL DEFAULT 'Open',   -- Open | Closed
    started_by  TEXT DEFAULT '',
    started_at  TEXT NOT NULL DEFAULT (datetime('now')),
    closed_at   TEXT DEFAULT '',
    notes       TEXT DEFAULT ''
);
-- One row per physical scan during a session (its raw serial + the asset it
-- resolved to, or NULL when the tag is unknown).
CREATE TABLE IF NOT EXISTS stock_audit_scans (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    audit_id    INTEGER NOT NULL REFERENCES stock_audits(id),
    serial      TEXT DEFAULT '',
    asset_id    INTEGER,                         -- resolved inventory_assets.id, or NULL
    scanned_by  TEXT DEFAULT '',
    scanned_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_stock_audit_scans_audit ON stock_audit_scans(audit_id);
