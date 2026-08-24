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

**The `nm_directory.py` vendor/contractor directory repurpose (seventh
reorg piece, Piece 39 / v0.8) is done — turned out to need no new code.**
This doc's own plan (below, "Cut entirely" section) was to repurpose
`nm_directory.py`'s shape into a household vendor/contractor directory.
Investigating before building surfaced that the need was already met: the
**External Helpers** roster from Piece 35 (`external_helpers` — name,
specialty, phone, email, notes) is the identical shape, down to its own
example placeholder being an electrician contact ("Sandia Electric —
Mike"). Confirmed with the user rather than building a duplicate table.
That left `nm_directory.py` itself with nothing worth repurposing:
- Its NM AHJ/utility rule-batch data (`NEW_RULES_V10`, `CORRECTIONS_V10/11`)
  had been dead code since Piece 38 dropped the import.
- Its remaining live use — `COUNTIES_ALL`/`UTILITIES_ALL`/`COUNTY_UTILITIES`
  driving the project form's county→utility auto-match dropdown — was
  solar-business logic for matching a job site's county to its serving
  utility across NM. The user confirmed cutting it: a household has one
  property and one utility, so `utility_provider` is now a plain text
  field, and the matching JS (`mappedUtilities`/`buildUtilOptions`, the
  "Manual override" button) is gone from `project_form.html`.

The county field keeps its NM-county datalist for convenience — that list
is now inlined in `app.py` as `COUNTIES`, the one thing worth keeping.
`nm_directory.py` is deleted outright. Verified via compile, a Jinja parse
sweep, fresh-DB boot, a project create/edit round-trip confirming
free-text `utility_provider` saves and edits exactly as typed (and that no
leftover select/JS remains in the rendered form), and a 42-route sweep.

**Post-reorg staleness audit (2026-08-16): a full-repo sweep — three parallel
passes over schema.sql table liveness, still-live solar-specific code, and
dangling code references — found the "structural reorg is done" status above
was premature.** Four subsystems were still fully wired up and still shaped
for the original solar-installation business, beyond anything already listed
here as deliberately deferred: the BPMN task-generation engine, the Loads &
Sizing electrical calculator, the Cost Model/GRT tax pricing system, and the
Work Bag's field-submission approval flow. Walked through with the user one
at a time; being landed as three parts of **Piece 40**:

- **Part A (v0.9) — cut the BPMN task-generation engine — done.** It was the
  only way any project got tasks, hardcoding the solar sales→install→closeout
  pipeline regardless of project category. Tasks are added manually now (the
  `add_task()` route already existed). Also removed: the per-project BPMN
  chart viewer/export and the auto-trigger that regenerated tasks on every
  stage advance. Verified via compile, Jinja parse sweep, fresh-DB boot, a
  test-client cycle (zero auto-generated tasks on project creation, manual
  add works, stage advance succeeds with no generation flash, all three
  removed routes 404), and a 42-route sweep.
- **Part B (v0.10) — cut Loads & Sizing + Cost Model/GRT tax — done.** Both
  priced/sized a job for the original solar business; this doc's own
  "Billing → Project budget tracking" plan (below) already said to cut the
  cost-model/GRT machinery down to plain budget-vs-actual — never done until
  now. Dropped 10 tables (`appliance_catalog`/`component_catalog`,
  `project_load_rooms`/`project_load_items`/`project_bom`/`project_sizing`,
  `county_tax_rates`/`markup_categories`/`cost_model_lines`/
  `project_estimate_lines`) and the `grt_rate`/`grt_amount`/
  `deposit_bom_cutoff_id`/`travel_miles` columns they fed, via a
  meta-guarded migration; deleted `loads_seed.py`,
  `templates/project_loads.html`, `catalog.html`, `finance_settings.html`
  outright (~2,300 lines total). `can_see_pricing()` is gone too — it only
  gated the margin breakdown being cut; contract totals were already
  visible to everyone on the unified dashboard. Kept: the plain
  `electric_loads` text field (still gates Planning), the Billing tab's
  contract-total field, and the `project_transactions` ledger — the actual
  budget-vs-actual tracking. Also fixed two `ensure_columns()` calls that
  would have crashed a fresh install by referencing now-gone tables, and
  stripped a UTF-8 BOM that had crept into `app.py`/`schema.sql` from an
  earlier PowerShell edit (broke `schema.sql`'s `executescript()`
  outright — caught by the fresh-DB-boot check). Also swept
  `templates/help.html`'s Loads/Sizing/BOM/Cost-Model section (cut
  entirely, sections renumbered) and the same stale department/GM
  references already fixed in `README.md` this session. Verified via
  compile, Jinja parse sweep, fresh-DB boot, a migration test (legacy
  tables/columns correctly dropped), a test-client cycle (contract save
  without GRT, all four removed routes 404, project detail renders clean),
  and a 40-route sweep.
- **Part C (v0.11) — fix a real Work Bag crash bug — done.**
  `templates/work_bag_photos.html` hard-crashed (500) on open, from an
  undefined `pay_types_js` template variable left by dead pay-type UI; the
  `segments` array that UI built was never even read by
  `complete_photo_task()` (it only ever consumed a plain `hours` value), so
  the widget was both broken and, patched, silently discarded. Replaced with
  the single plain-number hours field the route already expects.
  `templates/submissions.html`'s matching dead "Time (by pay type)" column
  (always rendered "—") and its stale "pending payroll... for Finance to
  approve" copy were also cleaned up. The submit→Parent/Admin-approve gate
  itself was **kept unchanged** per the user — it's wanted as real parental
  oversight for Assistant/Child Work Bag submissions, not solar-crew cruft
  to simplify away: a submission still lands as a Pending `field_submissions`
  row and nothing is written permanently until an admin approves or rejects
  it. Also fixed a stale AI Assistant README claim left over from Part B
  about pricing being permission-gated (`can_see_pricing()` is gone; contract
  figures are visible to everyone). Verified via compile, Jinja parse sweep,
  fresh-DB boot, a test-client cycle (Photos screen renders instead of
  500ing, an hours submission lands Pending without touching the task,
  `approve_submission()` still flips the task to Done, `reject_submission()`
  still discards it), and a 40-route sweep with zero 500s.

This closes out the full three-part audit cleanup.

**Post-Piece-40 login incident (2026-08-20): the household's real local
checkout was 15 commits behind `origin/main`** (stuck at Piece 35/v0.4 from
2026-08-15) — Pieces 36-40 had only ever been pushed to GitHub, never pulled
into the folder the app is actually run from
(`Management_App\job-creator-app\Vixinman_Household_Compendium`). This is
what caused a real "my username and password aren't working" report — not a
code bug; the stored credential came through the fast-forward pull
completely intact once the folder was caught up. Fixed by pulling and
resetting the account's password. Worth remembering: **this repo has two
local checkouts** — an old, unrelated one at the sibling
`Management_App\job-creator-app` root (predates the rebrand entirely, still
has `bpmn_export.py`/`loads_seed.py`/`nm_directory.py`, a completely
different lineage, not part of this project) and the real one nested inside
it at `Vixinman_Household_Compendium\` — always verify `git log`/`git status`
in the nested folder before assuming the household's live app reflects the
latest pushed work.

**Piece 41: de-solarize Projects, the Requirements Editor, and Inventory —
done.** The household logged into the live app for the first time
since the structural reorg and found the surviving subsystems still shaped
for the original solar-installation business: the dashboard centered on
"this week's installs," the Project form was a solar-sale intake form, the
Requirements Editor's directory filtered on solar product categories, and
Inventory was a parts catalog. A four-agent audit plus direct verification
against the real household database found **zero live projects** (so the
Project-form/pipeline redesign needs no data migration) but **145
resource_rules — 100% of them keyed to solar fields** (county/
utility_provider/products/property_type/PV-variant columns), and a fully
solar-flavored Inventory (439 items/49 tools/11 vehicles/52 vendors, every
row a catalog/reference entry, not real household stock). Landing as five
parts:
- **Part A (v0.12) — dashboard cleanup + de-gate the pipeline — done.**
  Removed the duplicated "This week's installs" tile and "🔨 Installs"
  bucket table (both keyed off `install_date`). Every pipeline stage now
  advances on "this stage's own tasks are done" only — dropped the Planning
  electric-loads gate, the Prep permits-filed/install-date gate, and the
  auto-advance from Prep to In Progress that used to trigger on its own.
  Requirements-filed coverage and the materials/procurement rollup stay
  (genuinely useful), just no longer restricted to a particular stage.
  Added "＋ New project"/"📁 View projects" buttons to the dashboard (there
  was previously no way to start or browse projects from it). `install_date`
  stays as a plain optional field, relabeled "Target/completion date."
  Verified via compile, Jinja parse sweep, fresh-DB boot, a test-client cycle
  (a project advances through every stage with no permits/install-date/loads
  warning ever appearing), a 40-route sweep, and a boot against the real
  household database.
- **Part B (v0.13) — Project form + data model overhaul — done.** Shrank
  `PROJECT_FIELDS` from 18 columns to 4 (name/category/type/site location —
  site location is now optional). Dropped
  `county`/`electric_loads`/`utility_provider`/`warranty_type`/`cost_method`/
  `tax_credit`/`expand_option`/`products`+PV-Generator-Battery variants/
  `service_type`/`property_type` from the `projects` table via a
  meta-guarded migration (`project_solar_fields_removed_v1`); confirmed a
  pure schema cleanup against the real household database (0 live projects).
  Also cut the "pre-fill a service ticket from an existing project" flow
  entirely — it only ever existed to seed a Technician Service ticket — and
  fixed the AI assistant's `find_projects`/`project_details` tools and
  global search, both of which queried the now-gone `county`/`cost_method`
  columns directly in raw SQL (the Requirements Engine's own rule-matching
  path was already safe via `condition_met()`'s existing `field not in
  project.keys()` guard). `PRODUCTS` and its sibling constants
  (`UTILITY_CONNECTIONS`/`MOUNTING_TYPES`/`SERVICE_TYPES`/`PROPERTY_TYPES`/
  `VARIANT_OWNERS`/`CONNECTION_FIELDS`) are deliberately kept for now — the
  Requirements Library still filters on them until Part C rebuilds that
  filter bar. Verified via compile, Jinja parse sweep, a migration test
  (legacy solar-shaped columns injected before the first-ever `init_db()`
  call, confirmed dropped), a test-client cycle, a direct exercise of the AI
  assistant's project tools, a 40-route sweep, and the actual migration run
  against the real household database.
- **Part C (v0.14) — Requirements Editor overhaul — done.** Purged all 145
  legacy solar-permit `resource_rules` in the live database via a
  meta-guarded migration (`legacy_solar_rules_purged_v1`) — confirmed 145 →
  0 against the real database; every row matched a field Part B had just
  dropped. `field_value` is now a datalist that repopulates via JS off the
  `field_name` dropdown (project_category's two fixed values, or whatever's
  already in use for project_type/site_location) instead of blind free
  text. Rebuilt `/directory`'s filter bar around category + type in place
  of the old product/connection/mounting/manufactured/service/property_type
  filters; dropped the "NM reference set" copy. Removed `PRODUCTS` and its
  sibling constants now that `rule_directory()` was their last consumer.
  Verified via compile, Jinja parse sweep, a migration test, a test-client
  cycle (a new rule against `project_category` matches a real project via
  `match_rules()`), a 40-route sweep, and the actual purge run against the
  real household database.
- **Part D (v0.15) — Inventory rehaul — done.** Purged the 439/49/11/52
  legacy catalog rows via a meta-guarded migration
  (`inventory_rehaul_v1`) — confirmed 0-available/0-needed solar-business
  reference data, not real household stock; 439/49/11/52 → 0 against the
  real database. Categories are now free text with a datalist (no more
  `INVENTORY_CATEGORY_SPECS`/per-category electrical spec fields). Collapsed
  `needed`/`available`/`on_po` to a single `quantity` column; dropped
  `inventory_txns` (the stock ledger) and the whole stale-stock workflow
  (`inventory_stale.html` + 5 routes); dropped `inventory_vendors` entirely
  in favor of a plain `purchased_from` text field on all three tables (there
  was no add-vendor UI anyway — vendors only ever came from dead seed code).
  Deleted `standardize_makes()`/`standardize_vendors()`/
  `apply_inventory_research()`/`apply_tools_research()`/`cleanup_inventory()`
  and their MAKE_*/VENDOR_*/RESEARCH_VERSION constants, plus
  `inventory_seed.py`/`inventory_research.py` outright. Verified via
  compile, Jinja parse sweep, a migration test (confirmed `quantity` lands
  as true INTEGER, not TEXT — `ensure_columns()` always adds TEXT columns,
  so this needed an explicit typed `ALTER TABLE`), a test-client cycle, a
  39-route sweep, and the actual purge run against the real household
  database.
- **Part E (v0.16) — Help/FAQ tutorial sweep — done.** Fixed three stale
  sections in `templates/help.html`: the pipeline tutorial's claim that
  "Prep auto-advances to In Progress once permits are filed and you set an
  install date" (removed in Part A); the Inventory section's entire "mark
  an item stale" tutorial (feature gone — replaced with an "add an item"
  tutorial covering free-text categories and the quantity field); and the
  admin section's "this week's installs" dashboard mention (removed in
  Part A). Docs-only — no `app.py` logic changes. Verified via a Jinja
  parse check and a test-client render of `/help` confirming the stale
  phrases are gone.

**This closes out Piece 41** — five parts (dashboard/pipeline, Project
form, Requirements Editor, Inventory, Help sweep), all committed, verified,
and pushed.

**Piece 42 (v0.17): Appointments — done.** The user asked to make
scheduling/tracking dates and appointments a core function. New
`appointments` table modeled directly on Chores (Piece 37) — same
completion-driven recurrence cadence, same reminder mechanics through the
notifications inbox — plus two real additions Chores never needed: an
optional `when_time` field, and a nullable `recurrence_days` (0/NULL =
one-time; Chores are always recurring, but most appointments aren't).
Marking a one-time appointment done stamps `completed_at` and drops it off
the upcoming list instead of advancing a date. New `/appointments` page
(who=mine/all/unassigned/`<id>` + a new show=upcoming/all toggle), a "📅
Upcoming appointments" dashboard card, and a nav entry next to Chores.
`build_ics()` now emits real timed `VEVENT`s (not just all-day) when an
event carries a time — `my_calendar_ics()` folds in the user's own +
unassigned appointments alongside task due dates and install dates.
Also fixed two stale README claims left over from Piece 41 Part A (the
pipeline description and the turnover-notification list both still
described the install-date auto-advance gating that Part A removed — never
caught since that piece's Help sweep only covered `templates/help.html`).
Verified via compile, Jinja parse sweep, a fresh-DB boot, a test-client
cycle (one-time vs. recurring "done" behavior, reminder fires exactly once,
`build_ics()`'s timed-vs-all-day branching, `my_calendar_ics()` end-to-end),
a 40-route sweep, and a boot against the real household database.

**Piece 43 (v0.18): rework External Helpers into Contacts, link to
Appointments — done.** User asked to broaden External Helpers to also
cover organizations (subscription services, co-ops) and to be able to add
an appointment directly from a contact. Renamed to "Contacts" in every
visible label (page title, nav, `TRASH_REGISTRY`'s `found_in`); internal
names unchanged (`external_helpers` table, `external_helpers_page`/
`new_external_helper`/etc. routes, `/external-helpers` URL — same
precedent as "Chores" staying `routine_tasks`). Added a `kind` column
('Person'/'Organization', existing rows default to Person) plus six
organization-only fields (`website`/`account_number`/`contact_person`/
`contact_phone`/`contact_email`/`renewal_date`), shown/hidden by a Type
selector on the form. `appointments` gained a nullable `external_helper_id`
— the Appointments form gained a "Related contact" dropdown, the list
gained a Contact column, and each Contacts row shows an upcoming-
appointment count + a "＋ Add appointment" quick-link
(`/appointments?prefill_contact=<id>`) that pre-fills a new, linked
appointment. **Bug caught by the test suite before shipping**: this app
runs with `PRAGMA foreign_keys=ON`, so deleting a contact still referenced
by an appointment raised a raw `sqlite3.IntegrityError` instead of a
friendly message — fixed by adding an `in_use` check to
`TRASH_REGISTRY["external_helper"]` (same pattern as every other
in-use-blocked entity) that counts linked appointments and blocks the
delete instead. Migration is purely additive; the real household database
has 0 rows in both tables, so no data was at risk. Verified via compile,
Jinja parse sweep, a migration test (legacy rows survive, new columns get
sane defaults), a test-client cycle (Person/Organization save correctly,
quick-add prefill works, the FK-delete block is correctly enforced then
correctly lifted once unlinked), a 40-route sweep, and a migration run
against the real household database.

**Piece 44 (v0.19): fixed Project subcategories — done.** User wanted real
base categories instead of the free-text "Project type" field. Added
`PROJECT_SUBCATEGORIES` — Home Improvement → Building, Landscaping,
Gardening, Maintenance & Repair; Personal Improvement → Education, Health,
Habit, Relationship, Misc — replacing (not supplementing) the old free
text. No schema change (`project_type` stays the same `TEXT` column);
`PROJECT_FIELD_LABELS["project_type"]` relabeled "Project type" →
"Subcategory". `project_form.html`'s free-text input became a `<select>`
cascading via JS from the category select (same JS-driven-cascade pattern
as Contacts' Type toggle, Piece 43, and the Requirements Editor's
field-value datalist, Piece 41). `rules_page()`/`rule_directory()`'s
"suggest a value" list switched from a live `SELECT DISTINCT` query to the
full fixed vocabulary; the Requirements Library's type filter became a
`<select>` narrowed to the current category filter. Verified via compile,
Jinja parse sweep, a fresh-DB boot, a test-client cycle (both categories'
subcategory sets render, a project saves with a real subcategory value, a
new rule matching `project_type=Building` ties to a real project via
`match_rules()`), a 40-route sweep, and a boot against the real household
database.

**Piece 45 (v0.20): Wishlist — done.** First of two features requested
together (the second, household expense/budget/receipt tracking, is
Piece 46, planned but not yet built). New `wishlist_items` table — anyone
adds something they want, optionally linked to an existing Inventory item
("more of this"), a Project, and/or a Contact, all three independent and
optional. Sits Pending until a Parent/Admin approves or rejects it —
confirmed reuse of the existing `"approvals"` permission (relabeled
"Approve field work & wishlist requests") rather than a new one, and
confirmed approval does nothing automatic (no auto-created Inventory row).
`wishlist_approve()`/`wishlist_reject()` are much simpler than
`approve_submission()` since there's no downstream data to apply. The nav
Approvals badge now also counts pending wishlist items.
**FK-safety fix (the Piece 43 lesson, this app runs with `PRAGMA
foreign_keys=ON`)**: refactored the ad-hoc Contacts in-use check into a
reusable `_contact_uses()` and fixed `TRASH_REGISTRY["inventory_item"]`'s
in-use check, which was hardcoded empty (harmless until a wishlist item
could reference an Inventory row — now genuinely wrong without the fix).
Verified via compile, Jinja parse sweep, a fresh-DB boot, a test-client
cycle (a wishlist item links to a real Inventory item + Project + Contact
simultaneously, approving sets status/reviewed_by/reviewed_at with zero
side effects on the linked Inventory item, deleting a still-referenced
Contact or Inventory item is correctly blocked then deletes cleanly once
unlinked), a 40-route sweep, and a migration run against the real
household database.

**Piece 46 (v0.21): household expense/budget/receipt tracking — done.**
Second of the two features requested together (Wishlist, Piece 45, was the
first). New "💵 Budget" page: a household-wide (not project-tied) income/
expense ledger — `household_transactions` — alongside the existing,
completely untouched per-project `project_transactions` ledger (kept as a
separate table rather than making `project_transactions.project_id`
nullable, since SQLite can't relax a `NOT NULL` column without a full
table rebuild). Each transaction can carry an optional receipt photo/PDF
(reuses `household_files`' exact `household_upload_dir()` pattern, but
optional rather than mandatory like Work Bag's `add_receipt()` — confirmed
not every household expense has a receipt worth keeping) and an optional
Contact link. `household_budgets` holds a monthly target per category,
compared against actual spend for the selected month with a simple
over/under progress bar. Extended `_contact_uses()` (Piece 45's FK-safety
helper) to also count `household_transactions` referencing a Contact.
Verified via compile, Jinja parse sweep, a fresh-DB boot, a test-client
cycle (a budget category and a receipt-bearing, Contact-linked expense
both save correctly, the receipt file is actually written to disk and
downloadable, the month summary reflects real spending, deleting a
still-referenced Contact is correctly blocked then deletes cleanly once
unlinked), a 40-route sweep, and a migration run against the real
household database. **This closes out both features requested together
this session.**

**Piece 47 (v0.22): Wishlist relocated under Inventory + help.html sweep —
done.** User feedback after Piece 46: "Wishlists belong primarily in
Inventory" — the top-level "🎁 Wishlist" nav link (added in Piece 45) was
removed from the main nav bar. Wishlist is now reached from the 📦
Inventory page: a "🎁 Wishlist" button in its toolbar, and a per-row "🎁"
quick-add link on every inventory item that pre-fills the wishlist form
with "More `<make> <model>`" and the item pre-selected (new
`wishlist_page()` `?prefill_item=` param, mirroring Appointments'
`?prefill_contact=` pattern from Piece 43). Wishlist still has a plain
entry in the 🗄 Databases dropdown alongside Inventory. No schema change,
no route removed — `/wishlist` still works exactly as before, only its
discovery path changed. Also swept `templates/help.html`, which hadn't
been touched since the Piece 41 Part E reorg cleanup and had zero
coverage of Chores, Appointments, the Contacts rework, Project
subcategories, Household Budget, or Wishlist: added "5c. Chores", "5d.
Appointments", "6b. Household Budget", and "6c. Contacts" sections, a
Wishlist tutorial folded into the existing "7. Inventory" section (now
"7. Inventory & Wishlist"), and a Category/Subcategory FAQ under "3.
Projects & the pipeline" — all in the existing tutorial+FAQ `<details>`
style, ToC updated to match. Verified via compile, a full Jinja parse
sweep over every template, a fresh-DB boot, a test-client cycle (the
Inventory page renders the Wishlist button and a real per-item
`prefill_item=<id>` link, hitting `/wishlist?prefill_item=<id>` correctly
pre-fills the title and selects the item), `/help` renders with all four
new anchor ids present, a 40-route sweep, and a boot against the real
household database.

**Piece 48 (v0.23): AI-assisted project planning — done.** Right after Piece
47 shipped, the user asked to pause the nav-bar UI cleanup and instead put
more structure around a project's Planning stage, specifically by leaning on
the existing AI chat integration (Piece 32) for a brainstorming session that
helps think through finishing a project and turns that into real tasks —
tailored by the Category/Subcategory vocabulary from Piece 44. Scoped via 3
rounds of AskUserQuestion (all "Recommended" chosen): the feature lives as a
new "🧠 Plan" tab on each project's own page (not the existing global 💬
Assistant page); it's **propose, then confirm** — the AI gets no new
write-tools, it only proposes and a real human click does the actual save,
preserving the assistant's existing read-only design promise; and the
conversation itself is **saved per project** so it can be reopened/continued
later, not just its outputs.
- New `project_plan_messages` table (id/project_id/role/author/content/
  created_at) persists the chat. A new `build_project_plan_context(db,
  project)` (mirrors `build_assistant_snapshot`'s compactness, scoped to one
  project) feeds the model the project's Category/Subcategory, open tasks,
  and recent field notes. A new `PROJECT_PLAN_SYSTEM_PROMPT` instructs the
  model to put any concrete next-step suggestion alone on its own line as
  `TASK: <title>` — a simple, reliably-parseable convention (there's no
  JSON-mode/structured-output path in `ai_assistant.py`'s plain-text
  response), which the tab's JS regex-scans into an inline **➕ Add to
  project** button. Nothing about `ai_assistant.py` itself changed — its
  existing `run_agent()` tool-use loop (Piece 32.1) is reused as-is; since it
  has no multi-turn history parameter, prior turns are folded into the single
  `user_message` string per call, capped to the last 20 turns in the prompt
  (full history still persists in the DB and still renders on reload).
- New route `POST /projects/<id>/plan/ask` mirrors `assistant_ask()` almost
  line-for-line (same `assistant_settings()`/`_provider_configured()`/
  `build_assistant_tools()` reuse — the existing read-only, permission-scoped
  tool registry is reused unchanged for extra grounding, no new AI tools
  added). No new permission — matches `add_task()`/`add_project_note()`'s
  existing "any signed-in household member" policy.
- **A real, latent gap closed along the way**: `add_task()` never set
  `pipeline_status`, so tasks added through the existing generic Tasks-tab
  form never counted toward `stage_info()`'s `WHERE pipeline_status = ?`
  ready-count for advancing a stage — a task could sit on a project forever
  without ever making that stage look "not ready." Gave `add_task()` one
  optional, additive `pipeline_status` form field (falls back to `''`, zero
  behavior change for the existing generic form) so a Plan-tab-suggested
  task's ➕ Add button can tag it to the project's current stage and have it
  actually count.
- **➕ Add to project** and **💾 Save as project note** reuse the existing
  `add_task`/`add_project_note` routes via `fetch()` rather than a plain form
  submit — both routes hard-redirect back with a fixed anchor that would
  otherwise knock the user out of the Plan tab they're actively chatting in.
  Trade-off, called out deliberately: the Tasks tab / field-notes list won't
  visually reflect the new row until the page is next reloaded, consistent
  with this app's general full-reload-on-write pattern everywhere else.
- New "🧠 Plan" tab on `project_detail.html`, added to the existing
  `.tab-bar`/`.tab-panel`/`TABS`-array pattern (confirmed the `TABS` JS array
  gates `activateTab()` — an unrecognized name falls back to `"general"`, so
  updating it was required, not cosmetic). Gated off with the same
  "no AI provider configured" flash `assistant.html` already uses, and with a
  one-line "planning chat is turned off" message for Done/Abandoned projects.
- Verified via compile, a full Jinja parse sweep, a fresh-DB boot (confirms
  `project_plan_messages` exists), a test-client cycle against a stubbed
  `ai_assistant.run_agent` (no real network call) — a message persists both
  turns, a *separate* later request confirms the conversation renders on
  reload, adding a suggested task with `pipeline_status` set lands correctly
  and is confirmed to count toward that stage's ready-count, adding a task
  *without* `pipeline_status` (the existing generic form) is confirmed
  unchanged, no-provider-configured returns the same graceful 400 as the
  global assistant, and a regression check that `/work-bag/notes` still
  inserts into `project_notes` unchanged — plus the standard 40-route sweep
  and a boot against the real household database (0 rows, zero risk).

**Piece 49 (v0.24): nav-bar UI cleanup + header rebrand — done.** The
long-deferred nav-bar cleanup (queued since the end of Piece 47) — the top
bar had grown a link per feature (Tasks/Boards/Chores/Appointments/Budget/
Work Bag/Approvals/Household, plus the Databases and Admin dropdowns and a
standalone 🔔 bell). Regrouped per explicit user instruction into two new
`.navdrop` dropdowns (the same `<details>`-based, JS-free pattern Databases/
Admin already use): **✅ To-do** (Tasks, Boards, Chores, 🔔 Notifications,
Appointments) and **🏠 Household** (Budget, Work Bag, Approvals). The
standalone notification bell (previously its own header icon with a red
count badge, far right near account/logout) moved into the To-do dropdown;
its unread count now renders as `(N)` on the dropdown summary itself instead
of a circular badge, matching how Approvals already showed its pending count
as `(N)` text. The Household dropdown's summary shows the same
pending-approvals count, gated the same `can('approvals')` way the standalone
Approvals link always was.
- **A real naming collision, resolved via AskUserQuestion**: the new "🏠
  Household" dropdown would have collided with the existing "👥 Household"
  nav link (the household-members/roles/accounts page). User picked
  **"👨‍👩‍👧 Family"** as the new label for that page — updated the nav link,
  `README.md`'s People/roles section, and `help.html`'s "add a household
  member" tutorial to match.
- Removed the "Vixinman Designs internal tool" subtitle span from the header
  entirely (plus its now-dead `.sub` CSS rule in both the base and the
  small-screen media query) and swapped the ☀️ logo for 🦊 in the header,
  the login page's heading, and `README.md`'s own masthead — the app's
  `<title>` tag still reads "· Vixinman Designs" (browser tab text, not
  asked about, left as-is). Docs-only branding change, no functional impact.
- Swept `templates/help.html`'s nav-path references (Boards/Chores/
  Appointments now say "✅ To-do → ...", Work Bag/Budget now say "🏠
  Household → ...", the Notifications section explains the bell moved under
  To-do) so the tutorials still match where things actually are.
- Verified via compile, a full Jinja parse sweep, a fresh-DB boot, a
  test-client check of the rendered nav (🦊 present, the old subtitle and ☀️
  gone, exactly one 🔔 in the page — confirming it isn't duplicated between
  the old standalone spot and the new dropdown, all five To-do items and all
  three Household items present, the old "👥 Household" label gone and
  "👨‍👩‍👧 Family" present) plus the login page, a manual browser click-through
  (opened the real dev server against a scratch open-mode database, clicked
  the To-do dropdown open via the actual DOM and confirmed only it opened,
  not Household/Databases/Admin) — the first manual browser verification
  done in this entire project, previously always automated-only — and the
  standard 40-route sweep plus a boot against the real household database.

**Piece 49 correction (v0.25): merge Family into the Household dropdown —
done.** Immediately after Piece 49 shipped, the user reported "you dropped
nav buttons" and, after a clarifying round, corrected the actual bug: **"Budget,
Work Bag, and Approvals get lumped together under Household"** meant all four
(those three plus the renamed household-member roster page) belong inside
**one** 🏠 Household dropdown — not a separate 🏠 Household dropdown *next to*
a standalone 👨‍👩‍👧 Family link, which is what Piece 49 actually built. Fixed
by moving the `<a href="/household-members">👨‍👩‍👧 Family</a>` link inside the
Household dropdown's `.navdrop-menu` (last item, after Approvals) and
deleting the standalone link entirely. Updated the matching `help.html`
nav-path reference ("Add them under 🏠 Household → 👨‍👩‍👧 Family") and
`README.md`'s Nav grouping bullet + build-history to describe one merged
dropdown instead of two separate elements.
- Re-verified with an updated test-client check (regex-extracts the
  Household dropdown's inner HTML and asserts Budget/Work Bag/Family are all
  inside it, plus asserts the `/household-members` href appears exactly
  once in the whole page — proving there's no leftover standalone copy) and
  a second manual browser click-through confirming the dropdown opens and
  contains all four items.
- **A real debugging detour, worth remembering for any future manual
  browser check on this repo**: the first re-verification attempt was
  misleading because a stale `python app.py` process from the *previous*
  piece's manual check was still bound to port 5000 (never fully killed),
  so requests intermittently hit the old process's stale state (pointing at
  the real household DB, hence an unexpected login redirect) instead of the
  freshly-started one. `Get-Process` failed to find the stale PIDs even
  though `netstat` still showed them `LISTENING` — inconsistent enough that
  chasing it further wasn't worth it. Switched to a fresh port (5050) with
  the reloader off (`app.run(port=5050, debug=False)`) to sidestep the
  confusion entirely, which also surfaced a second, smaller gotcha:
  `python -c "import app; app.run(...)"` skips `app.py`'s own
  `if __name__ == "__main__": init_db(); app.run(...)` guard, so the DB
  never gets created (`no such table: household_members`) unless `init_db()`
  is called explicitly first.

**Piece 50 (v0.26): dashboard nav icon changed 🏠→📊 — done.** Small,
cosmetic follow-up: the "📊 My Dashboard" nav link and the new "🏠 Household"
dropdown (Piece 49) sat right next to each other both using 🏠, reading as
duplicates. Scoped with one AskUserQuestion (which of the three 🏠 usages —
nav link / dashboard page heading / "Household overview" section — the user
meant) to avoid guessing wrong on an otherwise-ambiguous "pick a different
image" request; user confirmed just the nav link. Changed only
`templates/base.html`'s "My Dashboard" link and the matching README bullet;
the dashboard page's own 👋 heading and the 🏠 Household overview section
are untouched. Verified via compile, a route sweep, and a signed-in
test-client check (the link only renders once a session exists, so an
open-mode/no-session request never shows it either way — confirmed the new
📊 renders and the old 🏠 variant doesn't).

**Piece 51 (v0.27): roles actually grant access + close finance/project
gaps — done.** User asked to "overhaul the roles and permissions." A
full-codebase audit found `HOUSEHOLD_ROLES = ["Parent", "Child", "Assistant"]`
had zero effect on any `has_permission()`/`_is_admin()`/`admin_required()`
decision anywhere — pure display labels since Piece 35 — and that huge
swaths of the app (creating/editing/cancelling projects; adding/editing
household Budget entries and a project's own billing ledger) had **no
permission gate at all**. Confirmed via AskUserQuestion: (1) roles now grant
a default permission bundle; (2) two new permissions, `finances.manage` and
`projects.manage`; (3) for a Child, finances are hidden **entirely** (not
just edit-locked, unlike every other `.manage` permission — this one gates
viewing too).
- **`ROLE_DEFAULT_PERMISSIONS`** (app.py, near `HOUSEHOLD_ROLES`): Parent =
  everything but `delete`; Assistant = `rules.manage`/`inventory.manage`/
  `approvals`/`projects.manage` (deliberately narrow — see below); Child =
  none. Materialized as real `permission_grants` rows by a new
  `_seed_role_default_grants(db, member_id, role)` helper, called from
  `new_household_member()`, `edit_household_member()` (only when the
  submitted role differs from the row's previous role), and `seed_org_team()`
  (the fresh-install roster seeder — without this, Gremory/Victor/Dmitri
  would have gotten zero grants on a brand-new install, silently defeating
  the whole feature for the app's own starter roster). **Additive only** —
  never revokes an existing grant, even on a role change to a smaller
  bundle, matching this app's "nothing destructive without an explicit
  action" pattern. `has_permission()`/`_has_grant()`/the Access console
  needed zero logic changes — grants are still just rows in
  `permission_grants`, checked exactly as before.
- **Gated the real gaps** with the existing `@admin_required`/
  `VIEW_PERMISSION` pattern: `finances.manage` on `/budget` (view + every
  budget-editing route — viewing is gated too, unlike every other
  `.manage` permission, because "hidden entirely" was the explicit ask) and
  a project's own `set_contract`/`add_transaction`/`toggle_transaction_paid`/
  `delete_transaction` routes; `projects.manage` on `new_project`/
  `edit_project`/`set_project_status`/`cancel_project`/`reopen_project`/
  `set_install_date` (viewing a project stays open). Two already-
  `@delete_required` budget-delete routes got a second, stacked
  `@admin_required` layered on top (both decorators' `@wraps` preserve
  `view.__name__`, so `VIEW_PERMISSION` lookup still resolves correctly for
  both). **A real pre-existing bug fixed along the way**: `delete_transaction`
  had no gate of any kind — not even `@delete_required` — and does a hard
  SQL `DELETE` instead of routing through `trash_item()` like every other
  delete route. Only the missing gate was fixed; the hard-delete mechanism
  itself is a known, deliberately untouched issue (fixing it needs a new
  `TRASH_REGISTRY` entry, a separate piece).
- **Template gating** to match: the Billing tab (button + whole panel) and
  "✎ Edit project"/"↩ Reopen project"/"🚫 Cancel this project" in
  `project_detail.html`; "＋ New project" in `projects_list.html` and
  `dashboard.html`; the dashboard's "Money in flight" tiles and "💵 Payments"
  table; the "💵 Budget" nav link in `base.html` (found unconditional while
  its neighboring "🕗 Approvals" link already correctly checked `can(...)` —
  without this fix a Child would still see "Budget" in the nav and just
  bounce off a flash error on click, undermining "hidden entirely").
- **A real leak found and fixed beyond the plan's own scope, because it
  directly undermined this piece's core promise**: the 💬 Assistant and 🧠
  Plan chat's `build_assistant_snapshot()`, `find_projects` tool, and
  `project_details` tool all included contract-total figures completely
  unconditionally — a Child could have just asked the AI for the exact
  dollar amounts the UI now hides entirely. Gated all three behind
  `has_permission("finances.manage")` (a `can_finances` flag computed once
  in `build_assistant_tools()`). Caught this by reasoning through the
  feature's own stated goal rather than treating the plan's checklist as
  exhaustive.
- **Found, deliberately NOT touched this piece** (tangential to
  roles/permissions specifically): `board_delete`'s ownership-based bypass
  (admin OR assignee OR creator, skipping the `delete` grant entirely);
  `delete_project_note`/`delete_task_photo`'s inline author/label-scoped
  bypasses of `@delete_required`; three dead `VIEW_PERMISSION` entries
  (`delete_rule`/`delete_credential`/`delete_household_member_file` — those
  routes use `@delete_required`, not `@admin_required`, so the dict entries
  never get consulted); Household Files upload being wide open.
- **Assistant's bundle is deliberately narrow for now, not an oversight.**
  Mid-review, the user revealed the real long-term plan for the Assistant
  role: an AI agent under its own Assistant account that reads everything a
  Parent can, but whose writes never land directly — every create/edit/
  approve becomes a **draft** on a new unified Drafts page, only becoming
  real once a Parent signs off, and this should eventually cover every
  permission area consistently (not just projects/budget/approvals).
  Confirmed via AskUserQuestion to ship this piece's baseline first and
  design the drafts system as its **own, separate, larger piece** —
  granting Assistant broad read access now, with no draft-interception
  layer yet built, would let an Assistant-role account write finances/
  household data directly with no human in the loop. **This is the single
  biggest piece of unfinished work from this session** — see the project's
  memory file for the fuller design sketch (a generic `drafts` table, a
  write-interception layer in front of every route an Assistant can reach,
  and "apply this draft for real" logic per kind).
- Verified via compile, a full Jinja parse sweep, a fresh-DB boot (confirms
  `seed_org_team()` gives Gremory exactly the 4-permission Assistant bundle
  and Victor/Dmitri zero grants), a test-client cycle (creating a new
  Child/Assistant/Parent each gets exactly their expected bundle; a Child
  is denied `/budget` and `/projects/new` with the standard "no access"
  flash and sees no Billing tab/money tiles/Payments table/Budget nav link
  in rendered HTML; a Parent/Admin can reach `/budget`, an Assistant
  correctly cannot; changing an existing Child's role to Parent adds the
  new bundle while a pre-existing custom grant survives untouched; `/access`
  still renders and round-trips both new permission checkboxes; the AI
  assistant leak-fix confirmed end-to-end with a stubbed provider call), the
  standard 40-route sweep, and a boot against the real household database
  (confirmed real accounts are unaffected unless an admin explicitly edits
  someone's role or uses the Access console — no retroactive changes to
  real data).

**Piece 52 (v0.28): Drafts/approval system for the Assistant (AI agent)
role — done.** Closes the loop Piece 51 deliberately left open. Confirmed
via three AskUserQuestion rounds: (1) Assistant's bundle expands to match
Parent (everything but `delete`) — every write gated by any of those 7
permissions becomes draftable; (2) a draft's optional file upload saves
immediately into a **separate** draft-only storage folder, Approve moves it
into live storage, Discard deletes it outright with one confirm prompt;
(3) build all ~26 draftable write routes across all 7 permission areas in
this one piece, not a phased subset.
- New `drafts` table (`kind`, `ref_id`, `payload` JSON, `file_stored_name`,
  `created_by`, `status`, `reviewed_by`/`reviewed_at`) — same shape
  precedent as the existing `trash` table's payload-blob pattern. New
  `draft_upload_dir()` (mirrors `household_upload_dir()`) plus
  `_save_draft_file()`/`_move_draft_file()`/`_discard_draft_file()`.
- New `@draftable(kind, ref_id_kwarg=None)` decorator, stacked under the
  existing `@admin_required` on every route in scope: when the signed-in
  user's role is `"Assistant"` and the request is a POST, it validates the
  submission (via the kind's own capture function — reusing each route's
  existing extractor/validator wherever one already existed) and, if valid,
  inserts a Pending `drafts` row instead of calling the real view at all.
  Every other user (and every GET) passes straight through, unchanged.
- Refactored 26 live routes into a `_capture_*`/`_apply_*` pair each (new
  `DRAFT_KINDS` registry maps kind name → capture/apply/summarize), so the
  exact same "do the real write" logic runs for a live user AND for a
  Parent approving a draft later — nothing was reimplemented, just
  extracted. Every `apply` function returns `(ok, message, new_id_or_None)`;
  the live routes are otherwise behaviorally identical to before this piece.
- Two genuinely unique pieces of logic, reproduced in full rather than
  generically: `approve_submission`'s cascade (a Work-Bag submission
  approval re-runs its full per-task status/notes/due-date-recompute
  update across every `field_submission_items` row, not just a status
  flip) and the household-member "3-part bundle" (profile fields + login/
  admin flag + role-default-grant reseeding must apply as one atomic unit —
  `_apply_household_member_auth()` was refactored from reading
  `request.form` internally to taking explicit params, so it works
  identically whether called live or from a draft's stored payload).
- **Attribution rule, a deliberate choice**: a draft's real write is
  attributed to whoever *proposed* it (the Assistant), preserved on
  `created_by`/`cancelled_by`-style columns — except the four
  "recommendation" kinds (Wishlist/Work-Bag approve-or-reject), where
  `reviewed_by` is the *approving Parent* instead, since that's who
  actually exercised the review judgment, not the Assistant that only
  flagged a recommendation.
- **File uploads** (a Budget-transaction receipt; a project-transaction
  document): saved into `draft_upload_dir()` at draft-creation time,
  `Outstanding⇄Paid`-style re-checked against the *live* row's current
  state at apply-time rather than frozen from draft-creation time
  (relevant for `project_txn.toggle_paid` too — it re-derives the target
  status at apply-time, not from whatever was true when the Assistant
  drafted it).
- New `/drafts` (list, `show=pending|all`), `/drafts/<id>/approve`,
  `/drafts/<id>/discard` routes, gated by the existing `"approvals"`
  permission (same "parental oversight of pending stuff" concept as
  Wishlist/Work-Bag approvals — no new permission invented). New
  `templates/drafts.html`. New "🗒 Drafts" nav link inside the 🏠 Household
  dropdown, with its own pending-count badge folded into the dropdown's
  combined total alongside `pending_submissions`.
- **A real, pre-existing bug found and fixed along the way, unrelated to
  this piece's own scope but necessary for it to even be testable**:
  `update_rule` (editing a requirement rule) was **never** registered in
  `VIEW_PERMISSION` — it silently fell back to the generic admin-only gate
  the entire time since Piece 17/35, meaning a non-admin ever granted
  `rules.manage` could add a rule but never edit one. Fixed by adding the
  missing `"update_rule": "rules.manage"` entry (matching its sibling
  `"add_rule"` entry exactly).
- Verified via compile, a full Jinja parse sweep, a fresh-DB boot, and an
  11-step test-client cycle: Gremory (Assistant) gets the full 7-permission
  bundle; an Assistant's POST to one representative route per area (new
  project, rule edit, inventory item, new household member, a budget
  transaction *with a receipt file*, a wishlist approve-recommendation)
  produces a `drafts` row and **zero** change to the real table, with the
  receipt landing in `draft_upload_dir()` not `household_upload_dir()`;
  approving each draft as Jacob (Parent/Admin) produces the exact real-table
  change the live route would have, the receipt file actually moves into
  live storage, and the wishlist item's `reviewed_by` is confirmed to be
  "Jacob" (the approving Parent), not "Gremory"; discarding a draft with an
  attached file deletes the file and leaves the real table untouched; a
  Parent's own direct write is confirmed to create **no** draft row at all
  (regression check); approving a draft whose referenced row was deleted in
  the meantime produces a clean error flash and leaves the draft Pending,
  no crash — plus the standard 40-route sweep and a boot against the real
  household database (0 `drafts` rows, real accounts' existing grants
  untouched).

**Piece 53 (v0.29): Child-role dashboard & visibility restrictions — done.**
Follow-up to Piece 51's permission system: a default Child could still see
almost everything (household-wide dashboard, admin-adjacent nav, every
project's documents, the full FAQ). Confirmed via two AskUserQuestion
rounds (the second one surfacing that the user's initial ask was bigger
than first scoped — a project-file "collaborator" concept, not just a
dashboard reshuffle): dashboard shape = new combined Today/Tomorrow/Next-2-
weeks widget; project-file restriction = task-assignment-based and hides
only documents, not the whole project; Household Files/Requirements Editor
= genuinely restricted; FAQ full-access = its own permission, Parent
default.
- **Dashboard** (`dashboard()`, `templates/dashboard.html`): new
  `_bucket_schedule()` helper merges a signed-in member's already-fetched
  `my_tasks`/`my_chores`/`my_appointments` into Today/Tomorrow/Next-2-weeks
  buckets (no new queries). For a Child specifically, this replaces the
  "🏠 Household overview" block entirely (Parent/Assistant unaffected); the
  Procurement and Backlog cards are hidden outright; and the per-stage
  project-listing cards are filtered server-side to only projects with a
  `project_tasks.household_member_id` match for that Child.
- **Nav** (`templates/base.html`): Work Bag pulled out of the 🏠 Household
  dropdown to a standalone top-level link (a general layout change, not
  Child-specific — it read oddly for it to be nested for some roles and not
  others). Family, Household Files, and Requirements Editor links are now
  wrapped in `{% if can(...) %}`, reusing `household.manage` for the first
  two and `rules.manage` for the third.
- **Real server-side gating to match**, not just hidden links: added
  `@admin_required` + `VIEW_PERMISSION` entries for `rules_page`,
  `household_members_page`, `household_member_detail`,
  `household_files_page`, `upload_household_file`,
  `download_household_file` — all six previously had **zero** gate of any
  kind, reachable by direct URL regardless of role.
- **Project file/document visibility, Child-only, task-assignment-based**:
  new `_can_see_project_files(project_id, user)` (a Child needs ≥1 task on
  that specific project; everyone else always can) and
  `_file_route_allowed(project_id, record)` (exempts a `project_files` row
  tied to a task — a field photo — or a transaction — a billing receipt —
  from the check, since those are already scoped to whoever legitimately
  filed them and shouldn't vanish if a task assignment changes later).
  Applied to `upload_file`/`download_file`/`view_file` (previously
  undecorated) and to `project_detail.html`'s Documents tab (hidden
  entirely, same treatment as the existing Billing-tab gate) and the
  Requirements tab's Permits-only inline file links (`can_file` now also
  requires it). The rest of a project (general info, task list,
  requirements list) stays visible to a Child regardless of assignment —
  only the filed documents are hidden.
- **Help/FAQ locking**: new `help.full_access` permission (Parent/Assistant
  default, Child not) plus a `HELP_SECTION_PERMISSION` mapping + a
  `help_section_unlocked()` Jinja global. Five of the twelve Help sections
  (`#rules`, `#finance`, `#budget-help`, `#people`, `#managers`) show a
  🔒 placeholder instead of their tutorial for anyone lacking both
  `help.full_access` and the specific permission that section documents;
  the other seven stay open to everyone, unchanged. A one-time
  `meta`-gated migration (`help_full_access_v1`, same pattern as
  `household_reorg_v1`) backfills the grant for every *existing*
  Parent/Assistant, since `_seed_role_default_grants` only fires at
  member-creation/role-change time.
- **AI scoping — verified, no code change needed.**
  `build_assistant_snapshot`/`build_assistant_tools`/
  `build_project_plan_context` were re-confirmed to run per-request against
  whoever is actually signed in (`current_user()`/`session["user_id"]`, no
  caching), and none of the four assistant tools query `project_files` at
  all — so a Child chatting with the 💬 Assistant/🧠 Plan tab already only
  gets what they themselves can see, and there's no file-listing leak to
  close (unlike Piece 51's real finances leak — this time the audit came up
  clean).
- **Two real bugs found and fixed along the way:**
  1. `rules_page` (the Requirements Editor's own GET view) had no
     permission check at all — only its write routes (`add_rule`/
     `update_rule`) did, so a Child could already reach the editor UI
     directly by URL even before this piece's nav change, just couldn't
     submit anything from it.
  2. The `help_full_access_v1` migration was originally written calling
     `_seed_role_default_grants(db, m["id"], m["role"])` inside `init_db()`
     — but `init_db()`'s connection is a plain `sqlite3.connect()` with no
     `row_factory` set (unlike `get_db()`'s per-request connection), so
     rows there are bare tuples, not dict-like `Row` objects. This crashed
     immediately against the real household database (`m["id"]` →
     `TypeError`) despite passing every fresh-DB test, because on a fresh
     database `seed_org_team()` (which populates `household_members`) runs
     *after* this migration point, so the loop was silently a no-op there
     and the bug never got exercised. Fixed by duplicating
     `_seed_role_default_grants`'s additive-only logic inline in
     tuple-safe form rather than calling the Row-expecting function
     directly. Caught by testing against the real household database
     before pushing, not by the scratchpad fresh-DB suite alone — worth
     remembering as a category of bug that fresh-DB tests can miss
     entirely when a migration's effect depends on pre-existing rows.
- Verified via compile, a full Jinja parse sweep, a fresh-DB boot, an
  18-step test-client script (role-default grants, migration idempotence,
  dashboard Child-vs-Parent content, nav Child-vs-Parent, server-side
  gating on all six newly-gated routes, project-file access for an
  assigned vs. unassigned Child, the field-photo/receipt exemption after
  reassignment, Help locking including a partial-unlock-after-grant case),
  the standard 40-route sweep (zero 500s), and a boot against the real
  household database (confirmed the `help_full_access_v1` migration
  correctly backfilled Jacob/Rachel Inman/Gremory and correctly left
  Victor/Dmitri untouched, and a second boot confirmed no duplicate
  grants).

**Piece 54 (v0.30): dashboard money-widget rework + Loans/Savings accounts
— done.** User asked to rework the dashboard's 4-tile Money-in-flight
widget (Contract/Collected/Outstanding/Expenses, project-only) into 6 tiles
rolling up BOTH the project and household ledgers, plus asked for Loans and
Savings as new named-account features. Mid-review, two more requests came
in: a project's Planning-phase cost **estimate** vs. actual expenses
(explicitly NOT vs. Contract — see the flag below), and a **Discretionary
Spending** Budget category. Confirmed via 3 AskUserQuestion rounds.
- **6 dashboard tiles**: unpaid expenses, loans, income, savings, money in
  projects, anticipated spending (est. vs. actual) — `dashboard()`'s `money`
  dict rebuilt to sum `project_billing()`'s `expense_out`/`collected`/
  `contract` across projects, `household_transactions` grouped by
  kind/status, and `loan_balance()`/`savings_balance()` across every
  account. "Unpaid expenses" combining both ledgers required adding a real
  `status` column to `household_transactions` (it had none — every logged
  row was implicitly already-settled); added directly via `ALTER TABLE`
  (not `ensure_columns()`, which always defaults to `''`) so every
  pre-existing row defaults to `'Paid'`.
- **Loans/Savings**: `loan_accounts`/`loan_entries` and
  `savings_accounts`/`savings_entries` — new tables modeled directly on
  `project_transactions`/`project_billing()` (the only existing "ledger
  drives a computed total" precedent in this codebase), a running balance
  computed live on every read, never cached. Two new dedicated
  list+detail-page pairs (`loans.html`+`loan_account_detail.html`,
  `savings.html`+`savings_account_detail.html`) — the first genuinely new
  "roster + per-item ledger detail page" shape in this app (every other
  roster entity stops at list+inline-edit). `finances.manage`-gated
  throughout (no new permission — reused, matching how every other money
  feature in this app is already all-or-nothing gated); every write route
  is `@draftable`, same as Budget/project billing, so an Assistant-role
  account's Loan/Savings writes go through Drafts like everything else it
  touches. `_save_household_receipt()` generalized into
  `_save_household_upload(field_name, ...)` so Loan/Savings entry
  statements reuse the exact same optional-photo/PDF upload machinery as a
  Budget receipt, no new upload code.
- **`projects.estimated_cost`**: added to `PROJECT_FIELDS` (flows through
  the existing generic create/edit-form machinery automatically, same as
  `project_category`/`project_type` did in Piece 44 — zero special-casing
  needed). Entered on the general project form (gated by `projects.manage`,
  a Planning-phase detail, not a Billing-tab control); the number itself is
  shown on the General-details tab wrapped in `{% if can('finances.manage') %}`
  (Piece 51's "never show a dollar figure without finances.manage" rule).
- **Discretionary Spending**: new `HOUSEHOLD_BUDGET_CATEGORIES` suggested-
  values list, wired as an HTML5 `<datalist>` on Budget's category fields
  (which were, and remain, plain free text — no backend change needed).
- **Important flag from the user, not something this piece touched**: the
  project **"Contract"** concept (`contract_amount`, `set_contract`, the
  Billing tab's Contract/Not-yet-invoiced tiles, `project_billing()`'s
  `contract`/`uninvoiced` keys) is a leftover from this app's original
  solar-installation-business origins — there's no "customer signs a
  contract" concept for a DIY household project. The user asked for it to
  be flagged everywhere it appears rather than touched now. Full inventory
  (research done via a dedicated Explore pass): 1 column (added via
  `ensure_columns`, not in `schema.sql`'s `CREATE TABLE`), 1 dedicated
  route/form (`set_contract`, `_capture_contract`/`_apply_set_contract`, 1
  `DRAFT_KINDS` entry), `project_billing()`'s `contract`/`uninvoiced` keys
  rippling into `_closing_worklist()` (Wrap-up balance-due),
  the (now-former) dashboard money dict, the Payments table's `pay_totals`,
  and the Billing tab's own tiles; UI labels in `dashboard.html`,
  `closed_jobs.html`, `help.html` (5 FAQ mentions), `project_detail.html`;
  AI-assistant exposure (`find_projects`'s `min_contract` filter,
  `project_details`'s "Contract total" line, tool-schema descriptions); and
  a `TITLE_STATUS_KEYWORDS` task-title auto-tagger keyed on the literal word
  "contract". **This piece's new estimate feature was deliberately built
  independent of all of this** — it compares estimate to actual expenses
  logged, never to `contract_amount` — specifically so it wouldn't deepen
  reliance on a concept flagged for future removal. Whoever picks up the
  Contract-extraction piece should start from this inventory rather than
  re-deriving it.
- Verified via compile, a full Jinja parse sweep, a fresh-DB boot (migration
  idempotence confirmed via a second `init_db()` call), a 15-step
  test-client script (`piece54_loans_savings_test.py` in the session
  scratchpad — Budget status default + explicit-Outstanding round-trip, the
  category datalist, Loan account CRUD including balance math across
  Payment/Charge entries, delete blocked while entries exist then allowed
  once cleared, entry soft-delete with statement-file cleanup, the Savings
  mirror, 6-tile dashboard math against a hand-built scenario spanning both
  ledgers plus a loan and a savings account, `estimated_cost`'s
  `finances.manage`-gated visibility, `VIEW_PERMISSION` gating for every
  new route, the Assistant-drafts-then-Parent-approves path), the standard
  40-route sweep (zero 500s, `/loans`+`/savings` both clean), and — since
  this piece adds a real schema migration — a boot against a **copy** of
  the real household database (never the original) confirming
  `household_transactions.status` and the 4 new tables create cleanly with
  zero pre-existing-table row-count drift, run twice to confirm
  idempotence.

**Piece 55 (v0.31): Household Budget at-a-glance reporting — done.** User:
"Let's refine finances" — the first of 4 identified finance workstreams
(CSV bank import, this reporting piece, the Contract extraction, general
UI polish), sequenced via AskUserQuestion; CSV import was picked first but
is blocked pending a sample export from the user (Navy Federal Credit
Union — flagged, not built, per explicit instruction), so this reporting
piece went next. Scoped across 3 more AskUserQuestion rounds: cash-flow
tracker = forward projection (not historical); scope = household + project
combined (matching the dashboard's own v0.30 rollup); plus income-vs-
expense and category-spending historical trends as the "among others" the
user mentioned.
- **No charting library exists anywhere in this app** (re-confirmed via
  exhaustive grep before building — no Chart.js/D3/`<canvas>`/CDN
  `<script src>` anywhere) — every chart is **hand-rolled inline SVG,
  computed server-side in Python and rendered via Jinja**, matching this
  app's offline-in-the-field requirement (Work Bag's own offline support
  since Piece 26) — no CDN, no vendored JS bundle. `math` was already
  imported, no new dependency.
- **New Python helpers** (`app.py`, between `_household_month_bounds()`
  and `household_budget_page()`): `_recent_months`/`_forward_months`
  (hand-rolled month walk, backward/forward — no `relativedelta` anywhere
  in this app, stdlib only); `_combined_month_totals(db, month_str)` (one
  shared query shape backing all 4 reports, instead of duplicating the
  household+project UNION logic 4 times); `_category_breakdown_series`
  (top-5-by-total + "Other", pure function); `_cash_flow_projection(db,
  horizon_months)` (the real new logic — buckets Outstanding rows from
  both ledgers by their own `txn_date`'s month, clamping anything beyond
  the horizon into the last bucket and anything overdue/undated into
  bucket 0; projects `household_budgets` recurring targets forward, netting
  bucket 0 against this-month's already-recorded spend so only the
  *remaining* target counts as still-anticipated); `_assign_category_colors`
  (deterministic, so a category is the same color in both the pie and the
  category trend); `_pie_geometry` (the classic multi-`<circle>`
  `stroke-dasharray`/`stroke-dashoffset` donut technique) and
  `_bar_series_geometry` (generic grouped-bar geometry, shared by all 3 bar
  charts — cash-flow, income/expense trend, category trend).
- **Explicitly NOT a running bank balance**: this app has no
  starting-balance concept anywhere (re-confirmed via grep — nothing
  tracks "how much cash is actually in the bank"), so the cash-flow
  tracker only ever shows anticipated **net flow per future month**, never
  a fabricated running total. Called out directly in the UI copy so this
  isn't mistaken for real account tracking.
- **4 new cards on `templates/household_budget.html`**: the two
  current-month visuals (pie, cash-flow) placed right after the
  month-picker — "at a glance" before the data-entry workflow; the two
  historical trend visuals placed after the Transactions card, near the
  bottom — deliberately **not** stacked on top of the day-to-day
  add-transaction workflow, since burying it under 4 new cards would hurt
  the page on the small screen this app is about to be field-tested on
  (Pixel 9a). Both a `trend_months` (3–24, default 6) and `horizon_months`
  (1–12, default 3) selector, GET-submitting with the existing
  `month`/`show` state preserved as hidden fields — same pattern the page's
  existing This-month/All toggle already uses.
- **New CSS** (`templates/base.html`, near `.jobprog*`): `.chart-svg`/
  `.chart-legend`/`.swatch` — 4 small rules, no new stylesheet.
- **Verified visually, not just via test-client**: started a real scratch
  dev server, seeded a 6-month realistic scenario (multiple categories,
  an Outstanding transaction, budget targets with partial current-month
  spend), and inspected the actual rendered page — both via
  `get_page_text()` (correct dollar figures, correct category legends,
  "Other" bucketing working, both selectors present) and via
  `javascript_tool` reading the live DOM's `<circle>`/`<rect>` attributes
  directly (confirmed sane, non-NaN, non-negative geometry across all 4
  charts: 6 pie slices with valid dasharray/dashoffset pairs, 6/12/36 bars
  across the three bar charts with correct viewBox scaling). Screenshot
  capture itself failed in this environment (a known, previously-noted
  limitation — the Browser pane doesn't composite frames here) — the DOM
  inspection was the working fallback, same as Piece 49's precedent.
- Also verified via compile, a full Jinja parse sweep, unit-level checks on
  every pure function (month-walk year-boundary correctness, pie/bar
  geometry on an empty/all-zero dataset with no division-by-zero), a
  hand-computed cash-flow scenario (an overdue Outstanding project
  expense landing in bucket 0, an Outstanding household income 2 months
  out landing in bucket 2, a row dated beyond the horizon clamping into
  the last bucket, a partially-spent budget category producing exactly the
  remaining amount in bucket 0 and the full target in future buckets — all
  matched hand-computed expected values exactly), the standard 40-route
  sweep, and an empty-database smoke test (fresh DB, `GET /budget` still
  200, every new card's empty state renders instead of throwing).

**v0.32: bug fix — project task assignment never saved.** User-reported:
"When I attempt to assign a person to it, the field doesn't fill in even
though the due date and status stick." Root cause found in
`templates/project_detail.html`: the Tasks tab's "Assigned to" `<select>`
(both the per-row reassign dropdown and the "add a task" form) still
posted a field named `employee_id` — a leftover from before the Piece 35
`employees`→`household_members` rename — while `_task_assignee()`
(`app.py`, reused by both `add_task()` and `set_task_assignee()`) reads
`request.form.get("household_member_id", ...)`. The name mismatch meant
`raw` was always empty, so every assignment attempt silently saved as
unassigned (`NULL`), no error, no visible failure — exactly matching the
report. **A second, compounding bug in the same block**: the dropdown's
"who's currently selected" check compared against `t["employee_id"]`
(the task row's actual column is `household_member_id`; Jinja's
`foo["bar"]` silently degrades to Undefined on a missing key rather than
raising, so this never crashed, it just never matched) — meaning even a
correctly-saved assignment would never have rendered as selected. Due
date/status are separate small per-field forms with correctly-named
fields, which is exactly why only assignment looked broken. Fixed by
renaming both `<select name="employee_id">` to `household_member_id` and
the two `t["employee_id"]` comparisons to `t["household_member_id"]` —
no backend change needed, `_task_assignee()` was already correct.
Verified via test-client: add-task-with-assignee now persists the right
id, reassigning an existing task persists correctly, the rendered
dropdown shows the right person `selected`, and unassigning (blank
selection) correctly nulls it out — plus the standard 40-route sweep.

**NOT done yet:**
- **CSV bank-statement import, blocked on the user.** User: "refine
  finances," ordered CSV import first among 4 finance workstreams, but has
  no sample export on hand yet. Bank: **Navy Federal Credit Union**.
  Confirmed scope for whenever the sample arrives: imports land in
  **Household Budget only** (`household_transactions`, not project/Loan/
  Savings ledgers); a **staged preview-then-confirm** step (parse → review
  table → edit/uncheck rows → commit), never a direct silent import.
  **Do not guess at Navy Federal's column layout** (varies by account
  type, could be stale info) — wait for a real sample or the exact header
  row, and remind the user to hand it over next time this comes up. Also
  build a flexible column-mapping fallback alongside the NFCU-specific
  matching, so a format change or a second bank doesn't need a rebuild.
- **Budget reporting — 2 more items still open.** Piece 55 built the pie
  chart, cash-flow projection, and both trend charts the user asked for by
  name; the user's own "among others" phrasing implied more might be
  wanted — nothing further has been specified. Ask before assuming what's
  still missing.
- **The "Contract" legacy-code extraction**, flagged by the user (see the
  Piece 54 entry above for the full inventory) — `contract_amount`/
  `set_contract`/the Billing tab's Contract tile are a leftover from this
  app's original solar-installation-business origins and don't really fit a
  household project. Not touched yet by design; a future piece should
  reconsider/rename/replace it using the inventory already gathered.
- **Loans/Savings/Budget UI polish** — queued (4th of the 4 finance
  workstreams), no specific complaints identified yet; needs its own
  scoping pass before starting.
- **Pixel 9a beta-test readiness**, queued right after finance work
  wraps: (1) a mobile-responsive UI pass — this app has never had a
  real small-screen-phone check, only desktop dev-server click-throughs
  (Piece 49) plus automated Flask test-client work; (2) getting the app
  actually reachable from the phone — no deployment story exists anywhere
  in this project (local-network IP? a tunnel? cloud hosting?), needs its
  own conversation; (3) a real-data readiness check on `job_creator.db`
  itself before starting an actual project in it. Note: this app already
  has some PWA/offline infrastructure (`/sw.js`, `/offline`, Work Bag's
  offline support since Piece 26) — check what already works there before
  assuming a phone deployment needs offline support built from scratch.
- **Visual theme.** `templates/base.html` still uses the original green
  (`--brand: #1a6e3c`, `--brand-dark: #12522c`). The target aesthetic is
  **parchment / illuminated-manuscript**: natural paper-fiber background, ornate
  borders, accent colors in blue, green, red, gold/brass, and black ("burnt wood"). This
  is real visual design work (textures, border art, probably a different typeface), not
  a CSS-variable swap — treat as its own phase, explicitly deferred by the user until
  **after every feature/file/database reorg piece is done**, not incrementally per
  piece.
- **A fuller manual browser click-through.** Piece 49 did the first-ever
  manual browser check in this project (the new nav dropdowns, opened in a
  real dev server against a scratch database), but that only covered the
  nav bar itself — the household-member/dashboard/access/inventory/
  requirements/Project-form UI still hasn't had a human click through it in
  a real browser; verification there remains Flask test-client automation
  only.

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