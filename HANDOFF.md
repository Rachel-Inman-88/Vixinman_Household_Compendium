# Handoff: Vixinman Household Compendium

Context for whoever (whichever Claude) picks this up next. This repo started life as
**Solbiz** — an internal ops tool for an **unnamed solar installation company** (NM solar
installer): clients, jobs, licenses/permits/compliance, inventory, payroll, the works. It's
being converted into a **household** version: routine tasks + ongoing projects (repairs,
builds, certifications) for one household, not a multi-client business.

---

## Status: what's already done

The **text/branding rebrand pass is complete and verified.** Confirmed via repo-wide
search (zero remaining matches for the old company name / `Solbiz`, case-insensitive,
across `.py`/`.html`/`.sql`/`.md`/`.js`/`.txt`, excluding `dist`/`build`/`.git`/screenshots):

- **Product name:** "Solbiz" → **"Compendium"** (short form used in nav/titles/cache
  keys) / **"Vixinman's Home Compendium"** (full display name)
- **Company name:** the old unnamed solar installation company's name →
  **"Vixinman Designs"** — copyright notice, `LICENSE`, code comments, invoice
  remit-to block, `schema.sql` comments, all templates
- **Desktop packaging paths:**
  - `~/Solbiz` → `~/Compendium` (data dir)
  - `Solbiz.exe` → `Compendium.exe`
  - `Solbiz-Import` → `Compendium-Import`
  - `solbiz-error.log` / `solbiz-startup-error.log` → `compendium-error.log` /
    `compendium-startup-error.log`
  - `desktop/run_solbiz.py` → `desktop/run_compendium.py`
  - Env var `SOLBIZ_DATA_DIR` → `COMPENDIUM_DATA_DIR` (verified consistent between
    `desktop/run_compendium.py` and `app.py`'s `DATA_DIR = Path(os.environ.get(...))`)

**The `clients` removal (first piece of the structural reorg, Piece 33 / v0.2) is
done.** `clients`/`cold_leads`/`lead_followups`/`client_versions`/`client_files` are
gone from `schema.sql`; `jobs.client_id` is dropped. Replaced with:
- `household_ideas` — the someday/maybe backlog (`/backlog`), one table with a
  Backlog/Started/Abandoned status, hybrid reminders (monthly nudge + optional
  per-idea custom date) through the notifications inbox.
- `household_files` — flat household-wide document storage (`/household-files`,
  no owner id — single household).
- Home (`/`) merged into `/dashboard` (one view function, two routes — see
  `dashboard()` in `app.py`).
- Customer-facing invoicing (`view_invoice`, `generate_invoice`,
  `quickbooks_export`) and their templates/constants are deleted outright — they
  were hard-blocked by clients going away and were already slated for removal in
  the "Billing → Project budget tracking" section below. The plain
  `job_transactions` income/expense ledger stays.

Verified via `git grep -i client` across `app.py`/`schema.sql`/`templates/` —
remaining hits are historical comments, business-content data (compliance-rule
text, task-title keyword matching), and unrelated identifiers (`ai_assistant.py`'s
"HTTP client" docstring, `bpmn_export.py`'s BPMN node labels, `service_worker.js`'s
browser API) — none are functional dependencies on the removed table. Manually
click-tested against a fresh DB and against a simulated pre-reorg DB (the
`clients_removed_v1` meta-guarded migration in `init_db()` cleans up an existing
local database the same way).

**The `jobs`→`projects` rename + pipeline-stage relabel (second piece of the
structural reorg, Piece 34 / v0.3) is done.** `jobs` and its 11 `job_*` child
tables/14 `job_id` FK columns are now `projects`/`project_*` throughout
`schema.sql`, `app.py`, every template, and `bpmn_export.py`. Pipeline stages:
`Proposal → Job Prep → Installation → Inspections → Closing → Complete` (+ `Lost`)
became `Planning → Prep → In Progress → Wrap-up → Done` (+ `Abandoned`) —
Inspections and Closing merged into one Wrap-up stage. A meta-guarded
`projects_rename_v1` migration in `init_db()` upgrades an existing pre-rename
database the same way (table/column renames run *before* `schema.sql`'s
`executescript()` to avoid a naming collision with its `CREATE TABLE IF NOT
EXISTS projects`; the stage-value remap, including `pre_lost_status`, runs after).
`job_name` (the column) and the on-disk `uploads/job_<id>/` folder naming are
deliberately unchanged — internal detail, not user-facing — as are the
department/dashboard-mode/BPMN-lane names that happen to share stage text (e.g.
`"Installation"` as a department key); disambiguating those is
`employees`→`household_members` territory, not this piece's. Adds a `/projects`
list page (Databases nav) since there was no way to browse every project after
Piece 33 removed the client→job-list path. Verified via a live server
click-through (project creation, all 5 stage transitions, cancel/reopen
exercising `pre_lost_status`, task generation, BPMN view/export, dashboard, task
board, Work Bag, help page) with zero server errors, plus the same fresh-DB +
simulated-pre-rename-DB migration test used for Piece 33.

**The `employees`→`household_members` rename + role/access-control reorg (third
piece of the structural reorg, Piece 35 / v0.4) is done.** `employees` and its
`employee_credentials`/`employee_files` child tables are now `household_members`/
`household_member_credentials`/`household_member_files` throughout `schema.sql`,
`app.py`, and every template. The 28-role solar org chart (`reports_to`
hierarchy, Sales/Design/Warehouse/Install departments) is gone, replaced by a
flat **Parent / Child / Assistant** role — Assistant is a real `household_members`
row with its own login and task assignments, distinct from an **External
helper** (a new `external_helpers` table: name/phone/email/specialty/notes,
reusable contact roster, no FK from tasks). Access control is now a flat
**`is_admin`** flag plus per-permission grants with no expiry and no GM/Admin
tiers — admins get everything except **Delete**, which still always needs an
explicit grant even for admins (unchanged safety rail). **Cut entirely**:
payroll (pay types, rates, time entries, the payroll reminder, QuickBooks
export), the new-member onboarding checklist, and emergency access lockout —
the Work Bag's hours logging is now a single self-reported number,
display-only, with no supervisor/Finance two-sign-off chain. Task
auto-assignment by role is gone (`LANE_TO_ROLES`, `best_assignee_for_lane()`);
generated tasks land unassigned — a 5-person household roster is small enough
to hand-pick from. The **dashboard drops its department mode-switcher
entirely** — every section (My tasks, active projects grouped by stage,
backlog, procurement, permits-filed, install-date buckets, company overview,
payments) now renders unconditionally for every signed-in member, matching the
access-control resolution above (no more role-gated viewports). A
meta-guarded `household_reorg_v1` migration in `init_db()` upgrades an
existing pre-rename database the same way — table/column renames run *before*
`schema.sql`'s `executescript()` (same collision-avoidance reasoning as
Piece 34), and `is_admin` is backfilled from the old `access_level`/GM-role
text *before* the role remap overwrites it. Verified via a Flask test-client
sweep of ~28 routes (fresh DB + a logged-in admin session, zero failures)
plus live create/edit/grant-access/delete POST flows against both a fresh DB
and a simulated pre-reorg DB — not yet a manual browser click-through.

**Inventory's barcode/asset-tag cut + empty starter catalog (fourth piece of
the structural reorg, Piece 36 / v0.5) is done.** The barcode/asset registry
(register/print tags, scan-in/out, checkout/checkin/retire, the truck-loading
scan flow, stock audits) is removed entirely — built for a multi-person crew
truck-loading parts, doesn't fit household scale. Dropped
`inventory_assets`/`stock_audits`/`stock_audit_scans` from `schema.sql`, all
their routes, and the `barcodes.py` Code128-SVG module; a meta-guarded
`barcode_scanning_removed_v1` migration drops the tables from an existing
database. The inventory catalog now ships **empty** on a fresh install
instead of pre-seeding Vixinman's 439-item solar catalog, vendor list, tool
kit, and vehicle fleet (confirmed the vendor list is exclusively
solar-industry wholesalers — none of it is household-relevant). The
category→spec-field definitions the item form still needs
(`INVENTORY_CATEGORY_SPECS`) were kept; the actual seed data rows were cut.
Plain on-hand/needed/ordered inventory tracking, the stock ledger, and the
stale-stock notice all still work exactly as before. Verified via a
fresh-DB boot (zero pre-seeded rows, barcode tables absent), a simulated
pre-cleanup database with populated barcode tables (confirms the migration
drops them), and a Flask test-client route sweep + a live inventory-item
creation POST.

**The `routine_tasks`/`project_tasks` split (fifth piece of the structural
reorg, Piece 37 / v0.6) is done.** Added `routine_tasks` — recurring
household chores not tied to any project — as a new "Chores" feature
(`/chores`); `project_tasks` itself is unchanged. Modeled on `boards`
(nullable assignee, its own routes, an assign→notify helper) rather than
`project_tasks`' BPMN-generated, chain-rescheduled model, since a chore has
no natural "next step" to chain off. Recurrence is a plain day-interval
(`recurrence_days`, with Daily/Weekly/Biweekly/Monthly presets plus custom);
no status workflow — a chore is either due or not, and "Mark done" advances
`next_due` by the interval. Reminders reuse `ensure_backlog_reminders()`'s
exact idempotent pattern (a `reminder_sent` flag against `next_due`, wired
into both `dashboard()` and `run_maintenance()`). A "My chores" dashboard
card sits next to "My tasks." Delete goes through the standard trash flow.
Verified via fresh-DB boot, a full create/edit/mark-done/delete POST cycle
(confirmed `next_due` advances by the right interval and the reminder fires
exactly once per cycle, no duplicates on a second call), delete correctly
blocked until granted, and a ~30-route sweep.

**The Rules Editor → Requirements Engine redesign (sixth piece of the
structural reorg, Piece 38 / v0.7) is done.** This turned out to be much
bigger than "keeps its shape almost exactly" (the framing this doc used to
carry, below) — the user's own words: a household's requirements are mostly
internal paperwork (taxes, homeschool registration) and budgeting, and its
projects split into home-improvement and personal-improvement work, neither
of which the old solar `PROJECT_FIELDS` could describe. Three things landed
together:
- `projects` gained **`project_category`** (Home Improvement / Personal
  Improvement) and free-text **`project_type`**, added to `PROJECT_FIELDS`
  so rules have household-relevant fields to match against. The solar
  fields stay (untouched, just no longer the only option) — ripping them
  out is a separate future "Projects" piece, out of scope here.
- `RULE_CATEGORIES` renamed (License → Certification, Compliance →
  Prerequisite; Permit/Link/Phone/Doc unchanged), with a meta-guarded
  migration remapping existing rows. `resource_rules` gained optional
  descriptive fields (`est_cost`/`est_time`/`maintenance_note` — plain text,
  informational, explicitly **not** a calculator per the user) and the
  columns for a **standalone recurring requirement**: a rule with no
  `field_name` and a `recurrence_days` set is never matched against any
  project (`condition_met()` already no-ops on a blank `field_name` — zero
  code changes needed there) and instead reminds on its own interval via
  `ensure_requirement_reminders()`, mirroring `ensure_routine_task_reminders()`
  from Piece 37. This is the vehicle for household paperwork that isn't tied
  to any project — the user was explicit this should live **inside** the
  Requirements Engine, not extend Chores.
- The solar-specific seed content (`SEED_RULES`/`SEED_RULES_V8`, the NM
  AHJ/utility rule batches sourced from `nm_directory.py`) is gone — a fresh
  install now starts with an empty Requirements Engine. `seed_version`
  watermarking means an existing database is unaffected; any rule rows it
  already has are left in place for review/delete via the Requirements
  Editor, same "don't destroy existing data" precedent as Piece 36's
  inventory cut. `nm_directory.py` itself is untouched beyond dropping the
  now-unused rule-batch import — its AHJ/utility contact data is reserved
  for the still-separate vendor/contractor directory piece below.
- `/rules` and `/directory` keep their URLs, relabeled **Requirements
  Editor** / **Requirements Library** in the nav and page titles.

Verified via compile, a Jinja parse sweep of all 49 templates, fresh-DB
boot (confirms the new columns and zero seeded rules), a migration test
(pre-existing `License`/`Compliance` rows correctly remap, built by
injecting legacy rows before the first-ever `init_db()` call per the Piece
36 lesson), a full Flask test-client cycle (project-triggered rule matching
by `project_category` and correctly *not* matching a different category,
standalone requirement create → reminder fires once → mark-done advances
`next_due` and clears `reminder_sent`, project create/edit round-trips
`project_category`/`project_type`), and a 42-route GET sweep.

**NOT done yet:**
- **Visual theme.** `templates/base.html` still uses the original green
  (`--brand: #1a6e3c`, `--brand-dark: #12522c`). The target aesthetic is
  **parchment / illuminated-manuscript**: natural paper-fiber background, ornate
  borders, accent colors in blue, green, red, gold/brass, and black ("burnt wood"). This
  is real visual design work (textures, border art, probably a different typeface), not
  a CSS-variable swap — treat as its own phase, explicitly deferred by the user until
  **after every feature/file/database reorg piece below is done**, not incrementally
  per piece.
- **The vendor/contractor directory repurpose of `nm_directory.py`** — its
  AHJ/utility contact data (33 counties, every utility) is still sitting
  there unused now that the Requirements Engine no longer imports its rule
  batches. Repurposing it into a household vendor/contractor directory is
  its own not-yet-started piece.
- **A manual browser click-through of Pieces 35–38** — verification so
  far is automated (Flask test-client route sweeps + POST flows); no one has
  clicked through the new household-member/dashboard/access/inventory/
  requirements UI in a real browser yet.

---

## The task: reorg from solar-business shape to household shape

The user chose **Option A**: collapse the `clients` entity entirely (no more
multi-customer model — this manages one household), and **repoint the existing
`employees` infrastructure to represent household members** rather than building
something new from scratch.

### Core entity changes

| Old | New | Notes |
|---|---|---|
| `clients` table | **removed** | No separate customer entity. Projects/tasks belong to the household directly — drop the FK, not just the label. |
| `jobs` table + pipeline | **`projects`** | Keep the shape (versioning, per-job BPMN chart, standardized pipeline with gated stages). Drop `client_id` FK. Rename pipeline stages: `Proposal → Job Prep → Installation → Inspections → Closing → Complete` (+ `Lost`) becomes `Planning → Prep → In Progress → Wrap-up → Done` (+ `Abandoned`) — permit sign-off / inspections / certification exams are steps within Wrap-up, not their own stage (resolved, see Open Questions). |
| `employees` table + org chart | **`household_members`** | Same table shape (name/nickname dup-guard, licenses & certs per person, per-person dashboard) survives. The 28-role org-chart (`reports_to` hierarchy, Sales/Design/Warehouse/Install departments) shrinks to a small role set — see below. |
| Task generation (single stream, job-driven) | **split into `routine_tasks` vs `project_tasks`** | User explicitly wants routine (recurring chores) separate from tasks that are steps within a specific project. Project tasks keep today's job-generated/auto-assigned-by-role behavior, just renamed. Routine tasks are a new, lighter table — recurrence rule, assigned household member, no pipeline stage. |

### Roles — from 28 solar org-chart roles down to:
- Adult / Parent
- Kid / Dependent
- **External helper** — a contractor, tutor, or coach who touches a project but isn't a
  household member. **Resolved: real table** (structured contact info, reusable across
  projects), not a free-text field — see Open Questions.

**Cut as a consequence of the smaller role set**: the new-member onboarding checklist
workflow, payroll pay-type multipliers/overtime rules, and the GM/Admin tiered
permission-grant system with expiration dates. **Resolved (see Open Questions):**
household-level access control survives in a lightweight form — a simple `is_admin`
flag on `household_members` (Parent/Adult = full access by default) plus the ability to
individually grant a specific permission to one non-admin member case-by-case. No
expiration dates, no multi-tier hierarchy beyond that.

### Requirements Engine (was Rules Editor / L/P/C Directory)
**Keeps its shape almost exactly** — this is one of the strongest carryovers. The
"pick a type → the app surfaces what's required" pattern generalizes cleanly from
*permits/licenses/compliance* to *permits/certifications/prerequisites* (e.g., pick
"add a deck" → surfaces building-permit requirement; pick "get EMT certified" →
surfaces prerequisite coursework). Verbatim source-text field, verify/unverified
callouts, and the consolidation-of-shared-requirements behavior all still make sense.

### Inventory / BOM asset registry
**Keeps its shape minus barcode scanning** — on-hand/needed/ordered status, stock
ledger, stale-stock notice all carry over. **Resolved (see Open Questions): barcode
generate/print/scan is cut** — built for a multi-person crew truck-loading parts, doesn't
fit household scale. Swap the 439-item solar catalog (`inventory_seed.py`) for an
**empty household catalog** (resolved: ship empty, no starter set — items get added as
actually needed).

### Cut entirely — no household equivalent
- Payroll, pay types, overtime, pay periods, payroll reminder
- NM statewide reference data — 33 counties' AHJ contacts, utility interconnection
  contacts (`nm_directory.py`). **Resolved (see Open Questions): repurpose** its shape
  as a generic **contractor/vendor directory** (plumber, electrician, warranty phone
  numbers) rather than dropping it.
- Customer-facing invoice generation (50/40/10 progress billing), QuickBooks export, NM
  gross-receipts-tax line
- Work Bag field-crew mode — built for a multi-person install crew in the field. Unless
  the user wants to keep a stripped-down "on-site task" mode for whoever's doing
  yardwork/repairs that day.

### Keeps as-is — already domain-agnostic
AI Assistant (Claude/Gemini chat over the data), in-app Help, audit log, Boards
(standalone to-dos not tied to a project), notifications inbox.

### Billing → Project budget tracking
Keep the ledger *shape* (income/expense entries, dollar/date/category/party/reference,
receipt attach) but repoint it from **customer billing** to **project budget
tracking** — budget vs. actual spend per project. Drop customer invoicing, QuickBooks
export, and the NM tax logic that goes with it (see "cut entirely" above).

---

## Open questions — resolved 2026-08-15

1. **Verify stage:** ~~own pipeline stage, or folded into Prep/Wrap-up?~~ **Folded into
   Wrap-up.** Pipeline becomes `Planning → Prep → In Progress → Wrap-up → Done` (+
   `Abandoned`) — permit sign-off/inspections/cert exams are steps within Wrap-up, not
   their own stage.
2. **External helpers** (contractor, tutor, coach touching a project): ~~real table, or
   just a free-text field?~~ **Real table.** Structured contact info, reusable across
   multiple projects — not just a free-text field.
3. **Household-level access control:** ~~worth keeping any permission tiers, or drop all
   of it?~~ **Keep a lightweight version:** a simple `is_admin`-style flag on
   `household_members` (Parent/Adult = full access by default), *plus* the ability to
   individually grant a specific permission to a single non-admin member on a case-by-case
   basis (e.g. letting one kid edit the budget without making them a full admin). Explicitly
   **not** the old GM/Admin tiered system with expiring grants — no expiration dates, no
   multi-tier hierarchy beyond admin/non-admin + individual overrides.
4. **Vendor/contractor directory:** ~~repurpose `nm_directory.py`'s shape, or cut
   outright?~~ **Repurpose.** Reuse its shape for a household vendor/contractor directory
   (plumber, electrician, warranty numbers) instead of building new.
5. **Barcode/asset scanning:** ~~worth keeping, or overkill?~~ **Cut.** Built for a
   multi-person install crew truck-loading parts — doesn't fit household scale. Plain
   on-hand/needed/ordered inventory tracking survives without it.
6. **Inventory starter catalog:** ~~ship empty, or seed a starter set?~~ **Ship empty.**
   No pre-seeded household catalog — items get added as actually needed.

---

## Practical notes for implementation

- The rebranded file set (this repo's current state) was packaged and handed to the user
  as a zip to unzip over their local clone and push — confirm that landed correctly as a
  first step before making further changes.
- `app.py` is ~11k lines, monolithic (no ORM, raw SQL, Flask + Jinja). Expect
  `client_id` and `employees`/role references scattered widely — this is a search-first,
  not memory-first, task.
- `schema.sql` is the source of truth for the data model; work from there outward when
  planning the `clients`-removal and `employees` → `household_members` migration, since
  foreign keys will cascade into more places than the obvious ones (job versioning/audit
  log, BPMN export, the AI Assistant's read-only query tools in `ai_assistant.py`, etc.).
- Visual/parchment theme work is explicitly out of scope for this pass — don't touch
  `templates/base.html` CSS vars beyond what's needed to keep things functional.