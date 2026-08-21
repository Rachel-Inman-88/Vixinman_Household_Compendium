-- Household Compendium database schema.
-- Household Compendium: Vixinman household task/project manager (Piece 2, revised).
-- Projects: project profiles belonging to the household (Piece 3, renamed Piece 34).
-- Resource rules arrive in Piece 4.

-- Piece 33: household idea backlog. Replaces the old multi-client lead
-- pipeline (clients/cold_leads/lead_followups) now that this app manages one
-- household directly — a single table with a status field instead of moving
-- rows between two tables. status is 'Backlog' (not started), 'Started' (a
-- real project now exists, see started_project_id), or 'Abandoned' (kept for
-- reference, not deleted). reminder_date is an optional per-idea custom
-- reminder on top of the monthly whole-backlog review nudge.
CREATE TABLE IF NOT EXISTS household_ideas (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    name               TEXT NOT NULL,
    notes              TEXT DEFAULT '',
    target_date        TEXT DEFAULT '',
    proposed_by        INTEGER REFERENCES household_members(id),
    budget_estimate    REAL DEFAULT 0,
    status             TEXT NOT NULL DEFAULT 'Backlog',
    reminder_date      TEXT DEFAULT '',
    reminder_sent      TEXT DEFAULT '',
    started_project_id INTEGER REFERENCES projects(id),
    created_at         TEXT NOT NULL DEFAULT (datetime('now')),
    started_at         TEXT DEFAULT '',
    abandoned_at       TEXT DEFAULT ''
);

-- Piece 17.1: soft-delete trash. A deleted row is snapshotted here (full
-- original row as JSON, plus its origin table + a "where it was" label) and
-- removed from its own table, so it can be restored to exactly where it came
-- from or permanently purged by an admin.
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

-- Piece 17 (revised Piece 35): a specific permission granted to one non-admin
-- household member (admins already have everything except Delete — see
-- household_members.is_admin). Each row = "this member has this permission",
-- no expiry.
CREATE TABLE IF NOT EXISTS permission_grants (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    household_member_id  INTEGER NOT NULL REFERENCES household_members(id),
    permission           TEXT NOT NULL,
    granted_by           TEXT DEFAULT '',
    granted_at           TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Piece 41: the solar-sale fields that used to live here (county/
-- electric_loads/utility_provider/warranty_type/cost_method/tax_credit/
-- expand_option/products + PV/Generator/Battery variants/service_type/
-- property_type) are gone -- see the meta-guarded drop in init_db().
-- project_category/project_type (Piece 38) are added dynamically via
-- ensure_columns() rather than declared here.
CREATE TABLE IF NOT EXISTS projects (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    job_name         TEXT DEFAULT '',   -- the name used in bookkeeping records
    site_location    TEXT DEFAULT '',   -- optional -- where the project is happening
    status           TEXT NOT NULL DEFAULT 'Planning',  -- Piece 16 pipeline stage (renamed Piece 34)
    install_date     TEXT DEFAULT '',   -- Piece 18: optional target/completion date (de-gated Piece 41)
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Piece 4 (revised Piece 38): the requirements engine. Each row either:
--  - is project-triggered — "when project.<field_name> matches <field_value>,
--    this project needs <label>" — or
--  - is standalone/recurring (field_name = '', recurrence_days set) — an
--    internal household obligation not tied to any project (taxes, homeschool
--    registration), reminded the same way Chores are.
-- Categories group the output (Certification / Permit / Prerequisite / Link /
-- Phone / Doc). match_type 'contains' is for list fields like products;
-- 'equals' for single values.
-- Prior states of edited projects, kept for recordkeeping. data is a JSON
-- snapshot of every project field at the moment it was replaced.
CREATE TABLE IF NOT EXISTS project_versions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    version  INTEGER NOT NULL,
    data     TEXT NOT NULL,
    saved_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Piece 7: material list per project.
CREATE TABLE IF NOT EXISTS project_materials (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    item       TEXT NOT NULL,
    quantity   TEXT DEFAULT '',
    unit       TEXT DEFAULT '',
    supplier   TEXT DEFAULT '',
    status     TEXT NOT NULL DEFAULT 'Needed',  -- Needed/Ordered/Received/Installed
    notes      TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Piece 7: uploaded documents per project; optionally tied to a requirement
-- label so the requirements panel can show filing coverage.
CREATE TABLE IF NOT EXISTS project_files (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id    INTEGER NOT NULL REFERENCES projects(id),
    rule_label    TEXT DEFAULT '',   -- requirement this document satisfies
    stored_name   TEXT NOT NULL,     -- name on disk (uploads/job_<id>/)
    original_name TEXT NOT NULL,
    task_id       TEXT DEFAULT '',   -- Piece 21.7: field photos tie back to a task
    uploaded_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Piece 21.9: free-form field notes on a project, jotted from the Work Bag for
-- the office to read later. Each note carries its own timestamp (same clock as
-- the audit log) and author.
CREATE TABLE IF NOT EXISTS project_notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    note       TEXT NOT NULL DEFAULT '',
    author     TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- App metadata (e.g. which rule seed batches have been applied).
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- Piece 8 (revised Piece 35): the household member directory. Each row
-- records who the person is (name), their household role ('Parent', 'Child',
-- or 'Assistant' — see HOUSEHOLD_ROLES in app.py), whether they're an admin
-- (full access by default for Parents, but set explicitly per person — see
-- is_admin), the licenses/certifications they hold, and their schedule.
-- username/password_hash are blank until the person is given a login.
CREATE TABLE IF NOT EXISTS household_members (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    name                    TEXT NOT NULL,     -- composed display name "First Last"
    first_name              TEXT DEFAULT '',   -- Piece 19.3
    last_name               TEXT DEFAULT '',
    nickname                TEXT DEFAULT '',
    role                    TEXT NOT NULL DEFAULT 'Parent',  -- Parent / Child / Assistant
    licenses_certifications TEXT DEFAULT '',   -- legacy free-text (Piece 8.0)
    schedule                TEXT DEFAULT '',
    username                TEXT DEFAULT '',
    password_hash           TEXT DEFAULT '',
    is_admin                TEXT NOT NULL DEFAULT '',  -- '1' = full access except Delete
    dashboard_mode          TEXT DEFAULT '',   -- personal default-view preference
    created_at              TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Piece 8.1: each license/certification a household member holds as its own
-- row, so expiry can be tracked and flagged. rule_label optionally ties the
-- credential to a Certification requirement in resource_rules, which lets a
-- project page show whether someone in the household holds the certs it requires.
CREATE TABLE IF NOT EXISTS household_member_credentials (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    household_member_id  INTEGER NOT NULL REFERENCES household_members(id),
    name                 TEXT NOT NULL,
    rule_label           TEXT DEFAULT '',   -- License requirement this satisfies
    number               TEXT DEFAULT '',
    issued                TEXT DEFAULT '',   -- YYYY-MM-DD
    expires               TEXT DEFAULT '',   -- YYYY-MM-DD; blank = no expiry
    notes                TEXT DEFAULT '',
    created_at           TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Piece 8.1: uploaded copies of a household member's credentials/documents;
-- optionally tied to one credential by name. Files live on disk in
-- uploads/employee_<id>/ (internal path, deliberately left unrenamed), not
-- in the database.
CREATE TABLE IF NOT EXISTS household_member_files (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    household_member_id  INTEGER NOT NULL REFERENCES household_members(id),
    credential_name      TEXT DEFAULT '',   -- credential this documents (optional)
    stored_name          TEXT NOT NULL,     -- name on disk
    original_name        TEXT NOT NULL,
    uploaded_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS resource_rules (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    field_name  TEXT NOT NULL,
    field_value TEXT NOT NULL,
    match_type  TEXT NOT NULL DEFAULT 'equals',
    category    TEXT NOT NULL DEFAULT 'Prerequisite',
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

-- Piece 10 (revised Piece 35): per-project tasks, each optionally assigned to
-- a household member. The assignee is a nullable reference (NULL =
-- unassigned — generated tasks land unassigned by default since Piece 35
-- dropped role-based auto-assignment); deleting a household member unassigns
-- their tasks rather than removing the work. Drives the "Tasks" tab on a
-- project and the "assigned to me" list on a household member.
CREATE TABLE IF NOT EXISTS project_tasks (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id           INTEGER NOT NULL REFERENCES projects(id),
    household_member_id  INTEGER REFERENCES household_members(id),   -- NULL = unassigned
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
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    household_member_id  INTEGER NOT NULL REFERENCES household_members(id),
    new_hash     TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'Pending',  -- Pending / Approved / Rejected
    requested_at TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_at  TEXT DEFAULT '',
    resolved_by  TEXT DEFAULT ''
);

-- Piece 29.1: self-service password reset. Each household member may enrol a
-- few security questions; the answer is stored only as a salted hash
-- (normalised to lower-case/trimmed before hashing). Answering them correctly
-- lets the person set a new password themselves from the login page, with no
-- admin approval. One row per question; replacing the set deletes and
-- re-inserts.
CREATE TABLE IF NOT EXISTS security_answers (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    household_member_id  INTEGER NOT NULL REFERENCES household_members(id),
    question     TEXT NOT NULL,
    answer_hash  TEXT NOT NULL,
    sort_order   INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);


-- Piece 29.3: lightweight in-app notifications (an inbox + nav bell). One
-- row per recipient.
-- Piece 30.8: "Boards" — standalone to-dos not tied to any project
-- (clean the bathroom, call X, …). Each can be assigned to a household
-- member, carry a running notes log, and log time spent.
CREATE TABLE IF NOT EXISTS boards (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT NOT NULL,
    details      TEXT DEFAULT '',
    assigned_to  INTEGER REFERENCES household_members(id),   -- NULL = unassigned
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
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    board_id             INTEGER NOT NULL REFERENCES boards(id),
    household_member_id  INTEGER REFERENCES household_members(id),
    who         TEXT DEFAULT '',
    hours       REAL NOT NULL DEFAULT 0,
    work_date   TEXT DEFAULT '',
    note        TEXT DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
-- Piece 37: "Chores" — recurring household tasks, not tied to any project.
-- A row is one recurring chore definition; completing it advances next_due
-- by recurrence_days rather than generating a new row per occurrence.
CREATE TABLE IF NOT EXISTS routine_tasks (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    title                TEXT NOT NULL,
    notes                TEXT DEFAULT '',
    household_member_id  INTEGER REFERENCES household_members(id),   -- NULL = unassigned
    recurrence_days      INTEGER NOT NULL DEFAULT 7,
    next_due             TEXT NOT NULL DEFAULT '',       -- YYYY-MM-DD
    last_completed_at    TEXT DEFAULT '',
    last_completed_by    TEXT DEFAULT '',
    reminder_sent        TEXT DEFAULT '',                -- '1' once notified for the current next_due
    created_by           TEXT DEFAULT '',
    created_at           TEXT NOT NULL DEFAULT (datetime('now'))
);
-- Piece 42: Appointments -- a scheduled date+time, not tied to a project and
-- not always-recurring like Chores. recurrence_days NULL/0 = one-time (marks
-- completed_at when done); a positive value advances when_date the same way
-- a Chore's next_due advances.
CREATE TABLE IF NOT EXISTS appointments (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    title                TEXT NOT NULL,
    location             TEXT DEFAULT '',
    notes                TEXT DEFAULT '',
    household_member_id  INTEGER REFERENCES household_members(id),  -- NULL = whole-household
    external_helper_id   INTEGER REFERENCES external_helpers(id),  -- Piece 43: NULL = not linked to a contact
    when_date            TEXT NOT NULL DEFAULT '',   -- YYYY-MM-DD
    when_time            TEXT DEFAULT '',            -- HH:MM 24h, optional
    recurrence_days      INTEGER,                    -- NULL/0 = one-time
    completed_at         TEXT DEFAULT '',
    completed_by         TEXT DEFAULT '',
    reminder_sent        TEXT DEFAULT '',
    created_by           TEXT DEFAULT '',
    created_at           TEXT NOT NULL DEFAULT (datetime('now'))
);
-- Piece 45: a per-household-member wishlist. Submitted by anyone, sitting
-- as Pending until a Parent/Admin approves or rejects it (the same
-- oversight gate as the Work Bag's field_submissions) -- approval does
-- nothing automatic, it just flips status; someone still adds it to
-- Inventory manually once actually bought, same as everything else there.
-- All three link columns are optional and independent of each other.
CREATE TABLE IF NOT EXISTS wishlist_items (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    household_member_id  INTEGER NOT NULL REFERENCES household_members(id),
    title                TEXT NOT NULL,
    description          TEXT DEFAULT '',
    estimated_cost       REAL,
    purchase_url         TEXT DEFAULT '',
    inventory_item_id    INTEGER REFERENCES inventory_items(id),   -- NULL = not "more of this"
    project_id           INTEGER REFERENCES projects(id),          -- NULL = not for a project
    external_helper_id   INTEGER REFERENCES external_helpers(id),  -- NULL = no contact
    status               TEXT NOT NULL DEFAULT 'Pending',  -- Pending / Approved / Rejected
    reviewed_by          TEXT DEFAULT '',
    reviewed_at          TEXT DEFAULT '',
    created_at           TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS notifications (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    recipient_id INTEGER NOT NULL REFERENCES household_members(id),
    message      TEXT NOT NULL,
    link         TEXT DEFAULT '',
    kind         TEXT DEFAULT '',
    is_read      TEXT NOT NULL DEFAULT '',   -- '1' once read
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Piece 12 (revised Piece 33): household-wide document storage — files that
-- aren't tied to one specific project (insurance policies, warranties,
-- general correspondence), kept separate from a project's requirement documents.
-- No owner FK needed: there's exactly one household. Files on disk in
-- uploads/household/, only metadata here.
CREATE TABLE IF NOT EXISTS household_files (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    category      TEXT DEFAULT '',   -- Insurance / Warranty / Correspondence / Other
    stored_name   TEXT NOT NULL,
    original_name TEXT NOT NULL,
    uploaded_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Piece 35 (broadened Piece 43): "Contacts" -- a contractor, tutor, or coach
-- (kind='Person') or an organization like a subscription service, co-op, or
-- utility (kind='Organization') who touches the household but isn't a
-- household member (no login, not in household_members). A reusable
-- roster, not tied to any specific project. The org-only fields
-- (website/account_number/contact_person/contact_phone/contact_email/
-- renewal_date) are blank and unused for a Person entry.
CREATE TABLE IF NOT EXISTS external_helpers (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,
    kind           TEXT NOT NULL DEFAULT 'Person',  -- 'Person' | 'Organization'
    phone          TEXT DEFAULT '',
    email          TEXT DEFAULT '',
    specialty      TEXT DEFAULT '',   -- trade/role or service type, e.g. "Electrician", "Grocery co-op"
    notes          TEXT DEFAULT '',
    website        TEXT DEFAULT '',
    account_number TEXT DEFAULT '',   -- membership/account/customer number
    contact_person TEXT DEFAULT '',   -- the org's main point of contact
    contact_phone  TEXT DEFAULT '',
    contact_email  TEXT DEFAULT '',
    renewal_date   TEXT DEFAULT '',   -- YYYY-MM-DD, e.g. membership/subscription renewal
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Piece 14.1: field work submissions. When a worker syncs completed work
-- from the field, it is saved here as a PENDING copy (with their reported
-- hours) — it does NOT change the authoritative task data until an admin
-- approves it. On approval the item changes are applied to project_tasks.
-- reported_hours/approved_hours are recorded for reference but don't feed
-- anything downstream since payroll was cut (Piece 35).
CREATE TABLE IF NOT EXISTS field_submissions (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    household_member_id  INTEGER NOT NULL REFERENCES household_members(id),
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
    task_id         INTEGER NOT NULL REFERENCES project_tasks(id),
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
    entity   TEXT DEFAULT '',       -- JSON of URL params (project_id, ...)
    detail   TEXT DEFAULT '',       -- JSON of submitted fields
    status   INTEGER,
    ip       TEXT DEFAULT ''
);

-- Piece 21: per-project financial ledger — income (deposits/invoices/rebates)
-- and expenses (materials, permits, labor, subs). Drives the Finance
-- viewport's Payments table and the QuickBooks CSV export. Dollar amounts
-- stored as REAL.
CREATE TABLE IF NOT EXISTS project_transactions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES projects(id),
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

-- Piece 23.2 (rehauled Piece 41): household inventory. Category is free text
-- (no fixed list, no per-category spec system -- that machinery only ever
-- served the original solar-parts catalog). "Vendor" is a plain optional
-- purchased_from text field rather than a managed entity -- see
-- inventory_vendors_removed_v1 in init_db() for the table/column drop.
CREATE TABLE IF NOT EXISTS inventory_items (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    category         TEXT NOT NULL DEFAULT '',
    make             TEXT DEFAULT '',
    model            TEXT DEFAULT '',
    description      TEXT DEFAULT '',
    purchased_from   TEXT DEFAULT '',
    cost             REAL,
    purchase_url     TEXT DEFAULT '',         -- where to buy
    manual_url       TEXT DEFAULT '',         -- datasheet / user manual
    quantity         INTEGER NOT NULL DEFAULT 0,
    notes            TEXT DEFAULT '',
    active           INTEGER NOT NULL DEFAULT 1,
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
    purchased_from TEXT DEFAULT '',
    cost         REAL,
    purchase_url TEXT DEFAULT '',
    manual_url   TEXT DEFAULT '',
    notes        TEXT DEFAULT '',
    active       INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Piece 23.2: vehicles (car, truck, mower, ...), each with an optional nickname.
CREATE TABLE IF NOT EXISTS inventory_vehicles (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL DEFAULT '',
    nickname     TEXT DEFAULT '',
    category     TEXT DEFAULT '',
    make         TEXT DEFAULT '',
    model        TEXT DEFAULT '',
    year         TEXT DEFAULT '',
    description  TEXT DEFAULT '',
    purchased_from TEXT DEFAULT '',
    cost         REAL,
    purchase_url TEXT DEFAULT '',
    manual_url   TEXT DEFAULT '',
    notes        TEXT DEFAULT '',
    active       INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
