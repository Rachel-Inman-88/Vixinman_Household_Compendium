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

**Piece 56 (v0.33): LAN-reachable dev server, for Pixel 9a beta-testing —
done.** First half of "getting the app reachable from the phone" (one of
the 3 beta-test-readiness blockers noted below). `python app.py`'s
`if __name__ == "__main__":` block now reads `COMPENDIUM_HOST`/
`COMPENDIUM_PORT` env vars (default `127.0.0.1`/`5000`, unchanged from
before — plain `python app.py` behaves identically). Setting
`COMPENDIUM_HOST=0.0.0.0` binds to the machine's LAN address so a phone on
the same WiFi can reach it. Werkzeug's interactive debugger (`debug=True`)
now only turns on when `host == "127.0.0.1"` — leaving it on while
reachable from other devices on the network is a real remote-code-execution
risk (the debugger's console can execute arbitrary Python from anyone who
can reach the error page). Verified live: connected a real
Pixel 9a to `http://192.168.1.25:5000` over home WiFi and successfully
logged in — the phone browser's first attempt failed with "can't provide a
secure connection" (it tried `https://` automatically for the bare IP),
resolved by typing `http://` explicitly.

**Piece 57 (v0.34): 💬 Assistant retry button — done.** First real beta-test
feedback, from Jacob: a failed AI question shouldn't require retyping or
copy/pasting it back in. `templates/assistant.html`'s JS refactored so the
actual send logic lives in one `send(q, provider, isRetry)` function; on
failure, `showError()` renders the error message plus a "🔁 Retry" button
that resends the last-attempted `{q, provider}` pair, tracked in a
`lastAttempt` JS variable (cleared on success). `isRetry` suppresses
re-adding a "You" chat bubble, so retrying doesn't duplicate the question
in the visible transcript. Verified against a live scratch server: forced
`fetch` to reject (simulating a dropped connection), confirmed the Retry
button appears with no duplicate bubble; then mocked `fetch` to succeed and
confirmed clicking Retry resent the *exact* original request body — no
duplicate "You" bubble, error cleared, answer rendered correctly.
- **Same gap exists in the 🧠 Plan tab's chat** (`project_plan_ask()` /
  `templates/project_detail.html`'s inline Plan-tab JS) but was
  deliberately **not** fixed this piece — the user's request named "the
  assistant" specifically, and the Plan tab's backend persists the user's
  message to `project_plan_messages` **before** calling the AI (a
  deliberate Piece 48 choice, so a typed message survives a failed AI
  call). A naive resend-on-retry there would insert a second, duplicate
  user-turn row for the same question. The correct fix needs the backend
  to distinguish "resend this already-saved message" from "save a new
  one" (e.g. an optional `retry_of=<message id>` param that skips the
  INSERT and reuses the existing row) — a small but real addition, not
  just a copy of the assistant.html fix. Pick this up if Jacob (or anyone)
  hits the same complaint on the Plan tab specifically.

**Piece 58 (v0.35): Board collaborators + a due time — done.** User:
"Moving to Boards, I want to add a collaborator option along with the
family member to assign it to... not as robust of a feature as Projects,
just a more detailed version of a to-do checkmark." Confirmed via
AskUserQuestion: multiple collaborators (not just one), notified the same
way an assignee is. Mid-review, the user added a second ask: an optional
due *time* ("Tuesday, 4pm"), not just a date.
- **Real finding that shaped the design**: none of `boards_page`/
  `board_new`/`board_detail`/`board_edit`/`board_status`/`board_assign`
  have any permission gate — any signed-in member can already view/edit/
  status-change any board regardless of assignee (`board_delete` is the
  one exception, an inline creator/assignee/admin check, left untouched —
  a collaborator does not get delete rights this piece). So "collaborate
  together" was a **visibility and notification** gap, not an access-
  control one: a collaborator just needed to show up under "Mine," get
  notified, and be visible on the card — the ability to actually check a
  board off was already there for anyone.
- New `board_collaborators` join table (`board_id`, `household_member_id`,
  `added_by`/`added_at`) — a plain many-to-many, no `UNIQUE` constraint
  (app-level dedup, matching `permission_grants`' own precedent). New
  `_notify_board_collaborator()` mirrors `_notify_board_assignee()`
  exactly (skip-self, skip login-less). Two new routes
  (`board_collaborator_add`/`_remove`); `boards_page()`'s "Mine" filter and
  its specific-person filter (`who=<id>`) both extended to match a board
  where the person is the assignee **or** a collaborator; `board_detail()`
  fetches and renders the list; `board_delete` now also cleans up
  `board_collaborators` rows alongside its existing `board_notes`/
  `board_time` cleanup.
- **`due_time`**: added by mirroring `appointments.when_time` exactly —
  optional `HH:MM`, `<input type="time">`, displayed as
  `{{ due_date }} · {{ due_time }}`, sorted `due_date, due_time`. The
  **overdue badge deliberately stays date-only** (verified against
  `appointments.html`'s own overdue calc, which does the same) — a board
  due today at a past time is not marked overdue, consistent with every
  other due-date calculation in this app. New column added via
  `ensure_columns(db, "boards", ["due_time"])` in `init_db()` — the first
  time `boards` (stable since Piece 26/30.8) has ever needed a post-hoc
  column migration.
- Verified via compile, a full Jinja parse sweep, a fresh-DB boot, a
  13-step test-client script (`piece58_boards_test.py` — due_time
  round-trips through create and edit; overdue confirmed date-only in
  both directions, a board due today at 00:01 stays clean while one due
  yesterday at 23:59 still shows overdue; collaborator add/notify,
  duplicate-add is a no-op not a second row, self-add doesn't self-notify,
  both "Mine" and the specific-person filter include a collaborator-only
  board, the detail page renders the list, remove works, and deleting a
  board leaves no orphaned `board_collaborators` rows), the standard
  40-route sweep, and — since this piece adds a real schema migration — a
  boot against a **copy** of the real household database (never the
  original), confirming `due_time`/`board_collaborators` both land cleanly
  with zero row-count drift on the real 8 existing boards, idempotent on a
  second boot, and both `/boards` and a real board's detail page render
  200 against the actual data.

**Piece 59 (v0.36): "Load Bag" — Work Bag membership independent of task
assignment — done.** User: "I've noticed there's no easy way to load tasks
and projects into the Work Bag feature from any UI point... a 'load bag'
button (a toggle so we can see if it's in there)... load all member-specific
tasks and unassigned tasks from that project to the user's Work Bag."
Confirmed via 3 rounds of AskUserQuestion (all "Recommended"): (1) the
toggle is a genuinely new, explicit per-person "project is in my bag"
membership record, independent of task assignment — a task not owned by the
bag-holder still shows up but keeps its real assignee; (2) the bulk-load
action only reassigns currently-*unassigned* tasks to the loading user —
tasks already assigned to someone else are left untouched; (3) the button
lives on the dashboard's per-stage project-listing cards.
- **A real risk found during research, driving the design**:
  `api_work_bag_submit`'s per-task ownership check
  (`WHERE id = ? AND household_member_id = ?`) **silently drops** any queued
  submission for a task not assigned to the submitter — no error surfaced.
  Making a bagged project's other-people's-tasks look actionable in the Work
  Bag UI would mean tapping Submit/Mark-done on them silently did nothing.
  **Resolved by making those tasks read-only/reference-only client-side**
  (title, status, "Assigned to `<name>` — view only") rather than touching
  `api_work_bag_submit`'s authorization — zero server-side risk introduced,
  and the endpoint's existing own-tasks-only behavior stays exactly as it
  was for every other caller.
- New `work_bag_members` table (`project_id`, `household_member_id`,
  `added_at`) — plain many-to-many, no `UNIQUE` constraint, same
  app-level-dedup convention as `permission_grants`/`board_collaborators`.
  New `_work_bag_task_rows()` (a strict superset of the existing
  `_my_tasks_rows()`, which stays untouched — it still powers the
  dashboard's own assignment-only "My tasks" card) LEFT JOINs
  `household_members` for the assignee's name and adds an `OR project_id IN
  (SELECT ... FROM work_bag_members ...)` branch to the WHERE clause; for
  a member with zero bagged projects the two functions return identical
  results. `/api/my-tasks` now serves `_work_bag_task_rows()` and adds two
  new per-task fields, `assigned_to_me` (bool) and `assignee_name`.
- Two new POST routes: `/work-bag/<id>/toggle` (add/remove bag membership)
  and `/work-bag/<id>/load-tasks` (ensures membership, then claims every
  currently-`NULL`-assignee task on the project for the caller — a plain
  `UPDATE ... WHERE household_member_id IS NULL`, so an already-assigned
  task is structurally untouchable by this route regardless of who it's
  assigned to). Both redirect back to `request.referrer` so they work the
  same from the dashboard today or from `work_bag_job.html` later.
  `dashboard()` gained a `my_bag_project_ids` set (mirrors the existing
  `child_project_ids` pattern) so the per-stage project table can render
  the 🎒 toggle in the right on/off state; `delete_household_member()`
  gained a `work_bag_members` cleanup line alongside its existing
  `permission_grants`/`password_requests`/`security_answers` deletes.
- `templates/work_bag_job.html`'s `taskCard()` gates on `assigned_to_me`:
  `=== false` (an explicit check, not a truthy/falsy one) renders the
  read-only reference card; a task from an older cached copy predating this
  field (`assigned_to_me` undefined) is treated as actionable, matching the
  API's pre-Piece-59 own-tasks-only behavior. `work_bag.html`'s project
  grouping needed **no code change** — since `_work_bag_task_rows()` is a
  strict superset, a bagged project with only unassigned/other-people's
  tasks simply appears in the existing grouped list.
- Verified via compile, a full Jinja parse sweep, a fresh-DB boot, an
  11-step test-client script (`piece59_workbag_test.py` — with zero bagged
  projects `/api/my-tasks` exactly matches the old `_my_tasks_rows()`
  output; toggle add/remove round-trips with no duplicate row; a bagged
  project's unassigned/other-person's/own tasks all report the correct
  `assigned_to_me`/`assignee_name`; `api_work_bag_submit` still silently
  rejects a change to a non-owned task, confirming the read-only-UI
  decision needed no matching server change; bulk-load claims only the
  unassigned task and leaves the other person's assignment untouched;
  the claimed task becomes actionable afterward; the dashboard renders the
  bag column; deleting a household member leaves no orphaned
  `work_bag_members` rows), the standard 40-route sweep, and — since this
  piece adds a real schema migration — a boot against a **copy** of the
  real household database (never the original), confirming
  `work_bag_members` lands cleanly with zero row-count drift across every
  existing table, and the toggle route round-trips cleanly against a real
  project and a real household member with no residue left behind.

**Piece 60 (v0.37): Loans/Savings/Budget UI polish — done.** The 4th of
the 4 finance workstreams queued since Piece 54, with no specific
complaints — scoped via AskUserQuestion into 3 concrete gaps found by
direct inspection: `savings_accounts.goal_amount` was captured on the form
but never compared against the running balance anywhere; Loan/Savings
account detail pages had 3-4 flat stat tiles and a plain entry table, no
trend visibility (unlike Budget's 4 Piece-55 charts); the Loans/Savings
list pages had no aggregate total, unlike Budget's Income/Expenses/Net
summary.
- New `_balance_history_geometry(entries, starting_balance, deltas)` (near
  `_bar_series_geometry()`) — a hand-rolled SVG line-chart geometry
  function, same "no charting library anywhere in this app" convention as
  Piece 55's pie/bar helpers. One function serves both Loans (`deltas =
  {"Charge": 1, "Payment": -1}`) and Savings (`{"Deposit": 1, "Withdrawal":
  -1}`) since `loan_balance()`/`savings_balance()` already return
  `entries` sorted oldest-first — only the sign convention differs.
  Deliberately always folds `0` into the value range so a loan payoff or
  a savings account going negative is visible on the chart's axis, not
  just an off-screen edge case.
- `loan_account_detail()`/`savings_account_detail()` each gained one
  `history` computation, rendered as a new chart card (polyline + dots +
  a dashed zero-line) between the stat tiles and the entries table.
- Savings account detail: the goal tile became a real progress bar
  (mirrors Budget's category progress-bar markup exactly) — clamped both
  directions (a withdrawal-heavy account can show a negative balance) and
  intentionally **not** colored as a warning past 100%, since exceeding a
  savings goal is a good outcome, unlike Budget's over-budget red.
- `loans_page()`/`savings_page()` each gained a `total_balance` (Savings
  also `total_goal`) summary card above the accounts table — omitted
  entirely on an empty account list rather than showing a $0 tile.
- No schema changes, no new routes — purely additive read-side rendering
  over data that already existed.
- Verified via compile, a full Jinja parse sweep, a fresh-DB boot, unit
  checks on `_balance_history_geometry()` against hand-computed running
  balances (including an exact payoff landing precisely on the zero-line
  and a 0/1-entry account not crashing on the geometry's span/step math),
  a test-client cycle (list-page summary tiles match a hand-summed total;
  the goal progress bar reads 50%/"reached"/clamped-at-0% correctly across
  three balance scenarios; an account with no goal renders no progress
  bar at all — a real regression check against the prior unconditional-
  looking `{% if %}`), the standard 40-route sweep, and a boot + render
  check against a **copy** of the real household database (never the
  original) — confirmed the real db currently has 0 loan/savings accounts
  (so this piece is zero-risk there either way), then added scratch
  accounts/entries to the copy to confirm the new chart and progress-bar
  UI actually render against real-shaped data, not just synthetic tests.

**Piece 61 (v0.38): Dashboard "Productivity Overview" card + a Month
Calendar — done.** User supplied a mockup: consolidate the dashboard's
Appointments/Chores/Tasks (previously 3 separate standalone cards) plus a
new Boards section into one "Productivity Overview" card, alongside a
Month Calendar. Confirmed via 2 AskUserQuestion rounds: (1) the
appointment tiers reuse the exact Today/Tomorrow/Next-2-weeks split
already built for the Child dashboard's `_bucket_schedule()` widget
(`app.py`); (2) the Month Calendar is a real functional grid with markers,
not a placeholder; (3) a board counts as "mine" if I'm the assignee **or**
a collaborator, matching Boards' own existing "Mine" filter; (4) unlike
`_bucket_schedule()`'s drop-overdue behavior (built for a brief glance),
an overdue appointment here folds into "Today" with its badge instead of
disappearing from the list.
- New `_bucket_appointments_with_overdue()` (near `_bucket_schedule()`,
  which stays completely unchanged — still used by the Child dashboard)
  and `_build_month_calendar()` — a Sunday-start month grid using stdlib
  `calendar.Calendar(firstweekday=6).monthdayscalendar()`, first `import
  calendar` use in this codebase. `dashboard()` gained a `my_boards` query
  that mirrors `boards_page()`'s "Mine" filter SQL exactly, an
  `items_by_date` index built from tasks/chores/appointments/boards (any
  item with a date, unwindowed — the full month, not just the 14-day
  glance horizon), and `?cal=YYYY-MM` month navigation reusing
  `_household_month_bounds()` (validation/default) and
  `_recent_months()`/`_forward_months()` (Piece 55) for prev/next-month
  arithmetic instead of hand-rolling year-rollover math a third time.
- `templates/dashboard.html`: the old "✅ My tasks"/"🔁 My
  chores"/"📅 Upcoming appointments" cards are gone, replaced by one
  "🗂 Productivity Overview" card (gated to the non-Child dashboard, same
  as Backlog/Procurement) with a two-pane flex layout — a compact list
  pane (Appointments in 3 tiers, then flat Chores/Boards/Tasks lists) and
  a calendar pane (prev/next nav, a "This month" jump-back link, a 7-
  column week table with up to 3 item markers + a "+N more" overflow per
  day, today's cell highlighted). `flex-wrap: wrap` drops the calendar
  below the list on narrow viewports with no separate media query needed.
  "📋 My requirements" keeps its own separate card, untouched, right after.
- **Real bug caught during verification**: a dict cell's `"items"` key
  collided with Python's `dict.items` **method** under Jinja's default
  attribute-then-item lookup — `cell.items` in the template silently
  resolved to the bound method (`TypeError: 'builtin_function_or_method'
  object is not subscriptable` the moment `[:3]` was applied), not the
  list. Fixed by using explicit `cell['items']` instead of `cell.items`
  everywhere in the calendar cell markup. **Worth remembering for any
  future template touching a plain dict with common-name keys** (`items`,
  `keys`, `values`, `get`, `update` — any actual `dict` method name) —
  Jinja's dot-attribute sugar isn't safe there; use bracket access.
- Verified via compile, a full Jinja parse sweep, a fresh-DB boot, unit
  checks (`_build_month_calendar()` against a known non-leap February —
  correct day count, `is_today` on exactly one cell, an item landing on
  its exact date; `_bucket_appointments_with_overdue()` — an overdue
  appointment folds into "today" with its flag set, same-day/tomorrow/
  10-days-out land in the right tiers, a 20-days-out one is dropped from
  every bucket), a test-client cycle (old card headings gone/new card
  present; a board assigned to me, one where I'm only a collaborator, and
  one assigned to someone else with me uninvolved — confirmed the first
  two show under Boards and the third doesn't; `?cal=` prev/next links
  correctly cross a December→January year boundary; Child dashboard
  unaffected — still shows its own "🗓 My schedule," no Productivity
  Overview card; "📋 My requirements" still renders), the standard
  40-route sweep, a boot + several `?cal=` variations against a **copy**
  of the real household database (never the original), and — since this
  was mockup-driven — a live manual browser check (seeded a scratch DB
  with realistic tasks/chores/appointments/an overdue appointment/a
  board, signed in, and inspected the actual rendered DOM: both panes lay
  out side-by-side at desktop width and correctly stack on a 375px mobile
  viewport, today's calendar cell gets its highlight, and every item type
  shows up on its correct calendar date including the overdue one on its
  real past date). `computer` screenshot still fails in this environment
  ("Browser pane is not displayed") — `get_page_text()` + `javascript_tool`
  DOM/`getBoundingClientRect()` inspection was the working substitute
  again, same established fallback as Pieces 49/55/57.

**v0.39: moved the Productivity Overview card — done.** Immediate
follow-up feedback right after Piece 61 shipped: "place the Productivity
Overview card directly beneath the Household overview card" (was further
down the page, after Backlog). Pure template reorder in
`dashboard.html` — cut the whole card block and reinserted it right after
Household overview's closing `{% endif %}`, before the Child "🗓 My
schedule" branch. No Python/logic change. Verified via the existing
Piece 61 test suite (unaffected) plus a position check
(`body.index('🏠 Household overview') < body.index('🗂 Productivity
Overview') < body.index('💵 Payments')`, scoped to `<main>` to avoid a
false match against the nav bar's own "🗂 Backlog" quick-link, which
uses the same emoji and comes earlier in the page — a false alarm caught
and fixed in the verification script itself, not a real bug) and the
standard 40-route sweep.

**Piece 62 (v0.40): "💰 Money" nav consolidation + a financial overview
page — done.** Mid-Piece-61, the user asked for a follow-up: under the
🏠 Household nav dropdown, collapse the separate Savings/Loans/Budget
links into one "💰 Money" button opening a new financial dashboard page.
Scoped via 2 AskUserQuestion rounds (multiSelect + a custom addition):
the page should look like this session's other overview cards — summary
tiles, Budget's existing charts, a needs-attention row, and (the user's
own addition) the dashboard's Payments table too, not just a page of
links out to the 3 existing pages. Nav routing: a new `/money` route,
not a repurposed `/budget`.
- **Two small extractions from `dashboard()`**, so the new page can reuse
  the exact same numbers with zero duplication risk:
  `_household_money_snapshot(db)` (the "Money in flight" tile
  computation — unpaid expenses/loans/income/savings/money-in-projects/
  estimate-vs-actual, Piece 54) and `_payments_summary(db)` (the
  Payments table/totals loop, Piece 22.3). `dashboard()` calls both
  instead of inlining the loops — same behavior, confirmed via a
  before/after regression check comparing rendered tile values.
- New `/money` route, gated exactly like `/budget`
  (`@admin_required` + `VIEW_PERMISSION["money_page"] = "finances.manage"`
  — viewing is gated too, not just editing, same Child-can't-see-finances
  rule as Budget/Loans/Savings). New `templates/money.html`: the same
  Household-overview tile/panel markup fed by `_household_money_snapshot()`;
  a combined savings-goal progress bar (`total_savings_balance` /
  `total_savings_goal` summed across every account with a goal set, same
  clamped-both-directions bar as Piece 60's per-account one); a
  needs-attention row (over-budget categories this month, a count of
  Outstanding household transactions); Budget's expense-pie and
  cash-flow-projection charts (Piece 55's exact geometry functions
  reused, fixed 3-month horizon here — no `<select>`, the full adjustable
  controls stay on the dedicated Budget page); and the Payments table,
  reusing `_payments_summary()`. Toolbar links out to the full
  Budget/Loans/Savings pages — none of those three pages changed,
  moved, or lost any functionality; `/money` sits in front of them.
- **Interpretation flagged for the user to correct if wrong**: "Payments
  should also be included" was read as *duplicated* onto `/money`, not
  moved off the dashboard — the dashboard's own Payments card stays
  exactly where it is. If the intent was actually to move it, that's a
  one-line deletion from `dashboard.html`, not a re-plan.
- `templates/base.html`'s 🏠 Household dropdown: the 3 separate
  `<a href="...">💵 Budget</a>` / `💳 Loans` / `🐷 Savings` links became
  one `{% if can('finances.manage') %}<a href="{{ url_for('money_page')
  }}">💰 Money</a>{% endif %}`. `help.html`'s 3 existing Budget/Loans/
  Savings tutorials had their nav-path instructions updated (now
  "🏠 Household → 💰 Money → 💵 Budget" etc.) plus a new FAQ item
  explaining what the Money page is.
- Verified via compile, a full Jinja parse sweep, a fresh-DB boot, a
  regression check that the extraction changed nothing about the
  dashboard's own rendered numbers, a test-client cycle (`/money` renders
  for a `finances.manage` user and is denied for a Child with the exact
  same flash `/budget` already uses; seeded a loan account, a savings
  account with a goal, an over-spent budget category, an Outstanding
  transaction, and a billed project — confirmed loan/savings totals match
  a hand sum, the goal bar and its percentage/"reached" text are correct,
  the over-budget badge and unpaid-bills count both appear, and the
  Payments table matches the dashboard's own numbers exactly; the nav
  shows exactly one "💰 Money" link with no leftover Budget/Loans/Savings
  entries), the standard 40-route sweep (now including `/money`), and a
  boot + render check against a **copy** of the real household database
  (never the original) confirming both `/money` and the dashboard still
  render 200 with the money tiles/Payments table intact. **A live
  browser check was attempted but abandoned as inconclusive**: a scratch
  dev server on a throwaway port returned a bare 500 with zero matching
  request-log lines in the process's own output for either page load —
  the exact same code and seeded data confirmed working via the Flask
  test client moments earlier, so this reads as a local port/proxy
  environment glitch in this session, not a real app bug; not worth
  chasing further given the test-client suite already covers the same
  ground. Worth a real manual phone/browser check next time the app is
  actually being used, if anyone wants extra confidence on the visual
  layout specifically.

**Piece 63 (v0.41): dashboard's Payments table replaced with "Upcoming
payments" — done.** Immediate follow-up after Piece 62 shipped: "Remove
payments from dash, but include any upcoming (one month out or less)
payments for projects... that upcoming payment display should live in
the household overview card." Confirmed via AskUserQuestion: "upcoming
payment" means Outstanding **expenses** only (bills you owe), not
Outstanding income too — the everyday sense of "payment due."
- Removed the full "💵 Payments" `<details>` card from `dashboard.html`
  entirely (it's still on the 💰 Money page, Piece 62, untouched there).
  `dashboard()` no longer calls `_payments_summary()` or passes
  `payments`/`pay_totals` to the template — that function stays, still
  used by `money_page()`.
- New query in `dashboard()`: `project_transactions` rows where
  `kind = 'Expense' AND status = 'Outstanding'`, a non-blank `txn_date`
  `<=` today+30 days, on a project not `Abandoned`/`Done` — no lower
  bound, so an overdue bill is even more "upcoming" than one due later
  this month, same overdue-folds-in-not-dropped precedent applied twice
  already this session (Piece 61's appointment tiers). A blank `txn_date`
  is excluded (no due date to sort/show meaningfully), unlike
  `_cash_flow_projection()`'s own bucket-0 catch-all for blank dates —
  a deliberate, narrower choice for a due-date-sorted list specifically.
- New "Upcoming payments" panel inside the Household overview card
  (`dashboard.html`), right after "Money in flight" and before "Needs
  attention" — same `finances.manage` gate, same panel/table styling as
  the rest of that card. Shows project, description/category, amount,
  and due date with an overdue badge when past due.
- Verified via compile, a full Jinja parse sweep, a fresh-DB boot, a
  test-client cycle confirming the Payments card is gone and the new
  panel exactly matches the filter spec across 7 seeded scenarios
  (overdue-included, due-in-20-days-included, due-in-45-days-excluded,
  Outstanding-Income-excluded, Paid-excluded, blank-date-excluded, and a
  bill on an Abandoned project excluded), the overdue badge rendering
  correctly, `/money`'s own Payments table confirmed unaffected, the
  standard 40-route sweep, and a boot + render check against a **copy**
  of the real household database (never the original).

**Piece 64 (v0.42): Household overview's Pipeline tiles → per-family-
member project breakdown — done.** User: "As a parent I'd like to review
the projects of everyone across the board at a glance... I'd prefer to
have the top row of tables only split out by family member and more
visually read out — perhaps color-coded or icon-coded." Confirmed via 3
rounds of AskUserQuestion (all "Recommended"): (1) a project counts for
someone if they have any task assigned on it — the exact same rule
already used for the Child-visibility filter a few lines below in the
same function; (2) one row per person, their active projects shown as
small chips icon/color-coded by pipeline stage; (3) this **replaces** the
old whole-household stage-count tiles entirely, not sits alongside them.
- Removed `exec_stages`/`counts` (the loop building `gm["counts"]`,
  confirmed via grep it fed nowhere else) and replaced it with a
  `member_project_map` query — `project_tasks` joined to `projects`,
  grouped by `household_member_id`, restricted to non-Abandoned/Done
  projects. A project with zero assignees lands in its own "Unassigned"
  row (colored neutral gray) instead of silently vanishing from what the
  old aggregate tiles used to count.
- **Color, reused rather than invented**: `_assign_category_colors()`
  (Piece 55's deterministic name→color mapping, already used for the
  Budget page's category pie/trend charts) assigns each member a
  consistent color, shown as a circular initial avatar per row — the
  same function, no new palette. **Icon+color per project chip, also
  reused**: `STAGE_ICON`/`PROJECT_STATUS_CLASS` (both pre-existing
  module-level dicts, previously used only for the per-stage project-
  listing cards further down the same page) are now also passed into
  `dashboard.html`, so a chip's icon/color language matches what's
  already established elsewhere on the same page rather than introducing
  a third visual vocabulary.
- Members with zero active projects don't get an empty row — keeps the
  section scannable rather than a wall of "nothing here" rows.
- Verified via compile, a full Jinja parse sweep, a fresh-DB boot, a
  test-client cycle (seeded 2 projects for one member + 1 for another +
  1 unassigned + 1 Abandoned-with-an-assignee; confirmed exactly the
  right rows appear, the Abandoned one appears nowhere, a member with
  two projects gets two separate chips under one row not deduped away,
  zero-project members get no row, stage icons render correctly, and the
  rest of Household overview — Money in flight/Upcoming payments/Needs
  attention/Wrap-up — is completely unchanged), the standard 40-route
  sweep, and a boot + render check against a **copy** of the real
  household database (never the original).

**Piece 65 (v0.43): "Estimated cost" relabeled "Money invested / budget" —
done.** User: "In the Create Project form, there's a field for a dollar
amount estimating how much it will cost. I want to explicitly relabel it
something along the line of 'money investment/budget.'" A simple, direct
text change — no Plan Mode needed. Updated every place the label
appears: `PROJECT_FIELD_LABELS["estimated_cost"]` (app.py — feeds the
Requirements Editor's field picker and version-history diffs),
`project_form.html`'s Create/Edit Project field label, and
`project_detail.html`'s General details tab. Deliberately **not**
touched: `wishlist_items.estimated_cost` (Wishlist's own "Estimated
cost" field) and `resource_rules.est_cost` (Requirements Editor's
descriptive cost note) — both coincidentally share the old label text but
are unrelated fields on unrelated tables, not this one. No schema/data
change — `projects.estimated_cost` itself is untouched, purely a display
label. Verified via a full Jinja parse sweep, a test-client cycle (the
new label renders on both the Create Project form and the saved
project's detail page, the old text is gone from both, and the value
itself round-trips correctly), and the standard 40-route sweep.

**Piece 66 (v0.44): the 🧠 Plan tab's chat gets the 🔁 Retry button too —
done.** User: "Jake is talking to the assistant in a project, but we
can't find the retry button." Confirmed the report was about the
per-project **Plan** tab, not the global Assistant page — the exact gap
flagged as future work at the end of Piece 57's entry above: that chat
persists the user's turn to `project_plan_messages` *before* calling the
AI (so a typed message survives a failed call), which means a naive
resend-on-retry would insert a duplicate row.
- `project_plan_ask()` now accepts an optional `retry_of=<project_plan_
  messages id>` form field. When present and it resolves to a real
  `role='user'` row belonging to *this* project, the route reuses that
  row's saved `content`/`author` instead of inserting a new one — the
  "type a message first" validation is skipped too, since a retry always
  has content already. A `retry_of` for a different project (or a bogus
  id) is silently ignored and falls back to the normal insert-a-new-row
  path — never reuses another project's row. Both the "no API key
  configured" error and the `AssistantError` (provider failure) response
  now include the saved row's id as `"message_id"`, which the client
  needs in order to retry correctly.
- `project_detail.html`'s Plan-tab JS gained the same `lastAttempt`/
  `showError()`/Retry-button pattern already used on `assistant.html`
  (Piece 57) — factored the inline submit handler into a named
  `doSend(q, provider, isRetry, retryMessageId)` so the Retry button's
  click handler can call it directly. Retrying suppresses re-adding a
  duplicate "You" bubble (matching the assistant.html pattern) and sends
  `retry_of` in the POST body when a saved message id is known.
- **One accepted, minor edge case, not worth solving**: if the *original*
  `fetch()` itself fails before any HTTP response arrives (e.g. the
  network drops mid-request), the client never learns whether the server
  actually completed the INSERT before the connection broke. A bare retry
  in that case has no `retry_of` to send and falls back to inserting a
  fresh row — in the rare case the first insert *did* land, this could
  leave one duplicate row. This mirrors the same category of uncertainty
  already accepted for `assistant.html`'s own network-failure branch;
  adding real request idempotency to solve it would be over-engineering
  for how rarely it'd actually happen.
- Verified via compile, a full Jinja parse sweep, a fresh-DB boot, a
  test-client cycle against a stubbed `ai_assistant.run_agent` (fails
  once then succeeds) — confirmed exactly one `project_plan_messages`
  user row exists after the failure, retrying with the returned
  `message_id` succeeds and still leaves exactly one user row (no
  duplicate), a `retry_of` pointing at a different project's message is
  correctly ignored and falls back to a normal fresh insert, and the
  ordinary non-retry flow is unchanged — plus the standard 40-route
  sweep.

**Piece 67 (v0.47, merged to `main` in Piece 71 below): Repeat prompt + AI
task-flagging + Section→Subtask hierarchy — done.** User bundled three
related asks; per explicit instruction this entire piece lived on its own
branch (`feature/plan-tab-and-task-sections`), not `main`, until a
separate merge decision (now made — see Piece 71). Confirmed via 4 rounds
of AskUserQuestion: (1) "repeat" means always-available (not
failure-gated) resend of the last question, a genuinely new turn each
time; (2) task flagging is a hybrid — an inline clickable chat reference
AND a real, persisted Tasks-tab indicator, human-confirmed either way;
(3) a Section is independent of pipeline stage, purely an organizational
label; (4) plan and scope all three together, even though they'd very
likely ship as separate verified commits.
- **🔁 Repeat last** (`assistant.html` + `project_detail.html`'s Plan
  tab): needed **no backend change at all** — unlike Retry (Piece 66),
  repeating is just a normal fresh send with the same text, so for the
  Plan tab it correctly inserts a brand-new `project_plan_messages` row
  every time (confirmed via test: two repeats of the same question leave
  two distinct rows, not a duplicate). A `lastQuestion` var (separate
  from Retry's `lastAttempt`, which only tracks failures and clears on
  success) is set at the start of every send. The Plan tab's version is
  pre-populated from the last rendered `.plan-bubble[data-role="user"]`
  already in the DOM on page load, so it works immediately after a
  reload — `assistant.html` has no persisted history, so its button
  simply starts disabled each load.
- **AI task-flagging**: `build_project_plan_context()` now includes each
  task's id (`[<id>] <title> — ...`, previously id-less) so the model can
  cite one precisely via a new `FLAG: <id> | <title>` line convention
  (`PROJECT_PLAN_SYSTEM_PROMPT` rewritten to teach all three marker
  formats together). A new `flagged_in_plan` column (`ensure_columns()`,
  a plain `'1'`-flag boolean like `is_admin`/`is_read`) and a
  `toggle_task_flag()` route (a plain toggle, mirroring `set_task_assignee`'s
  shape) serve both the Plan tab's one-click "🚩 Flag: `<title>`" chat
  suggestion and a manual toggle button now on every Tasks-tab row —
  real and persisted, visible even after navigating away, exactly what
  was asked ("easier to verify both are talking about the same part of
  the project").
- **Section → Subtask hierarchy, one level deep**: new
  `project_task_sections` table (`project_id`, `title`, `sort_order`) and
  a `project_tasks.section_id` FK. **Real gotcha applied correctly**:
  `section_id` needed an explicit typed `ALTER TABLE` in `init_db()`
  (wrapped in the standard `try/except sqlite3.OperationalError`), not
  `ensure_columns()`, which always adds a `TEXT` column — the Piece 41
  `quantity`-as-INTEGER lesson, applied again here for a real FK column.
  Deleting a section detaches its tasks (`section_id` → NULL) rather than
  deleting them, and skips `trash_item()` entirely — a section is a
  lightweight organizational label, not real content, same precedent as
  `board_collaborators`. Five new/extended routes: `add_section` (returns
  JSON when `Accept: application/json`, for the Plan tab's fetch-based
  "➕ Add section" button, or flash+redirect for the classic Tasks-tab
  form — one route serves both), `edit_section`, `delete_section`,
  `set_task_section` (mirrors `set_task_assignee` exactly), and `add_task`
  gaining an optional `section_id` field (same additive-field precedent
  as Piece 48's `pipeline_status` addition — blank/absent is unchanged
  behavior).
  - **Tasks tab restructure**: `project_detail()` groups tasks by section
    in Python (same style as `dashboard()`'s `by_stage` grouping); the
    template wraps the existing 6-column task table in a local Jinja
    `{% macro task_table(rows) %}` (called once per section plus once
    for a trailing "Ungrouped" bucket) so the row markup isn't
    duplicated, and gains two columns (🚩 flag toggle, Section
    reassignment `<select>`). Each section is its own collapsible
    `<details class="card">` with inline rename/delete controls.
  - **Plan tab suggestion rendering, made "visually clear and concise"
    per the ask**: `extractTasks()` replaced with `parseSuggestions()`, a
    line-based parser recognizing `TASK:`/`SECTION:`/`FLAG:` — a `TASK:`
    line before any `SECTION:` stays flat (Piece 48's original behavior,
    confirmed unchanged by a regression test). Each suggested section
    renders as its own bordered block (header + "➕ Add section" button,
    subtasks indented beneath each with their own "➕ Add"); clicking a
    subtask's Add button **lazily creates the parent section first**
    (memoized per block, via the JSON-returning route) if it doesn't
    exist yet, so a human never has to click "Add section" separately
    just to add one subtask.
- Verified via compile, a full Jinja parse sweep, a fresh-DB boot, a
  test-client cycle covering all three features together (section
  create/rename/delete-detaches-not-deletes, task-into-section and
  move-between-sections, flag toggle on/off with the indicator rendering
  correctly, `build_project_plan_context()` including task ids and
  section structure, two repeats creating two distinct rows not a
  duplicate, and a flat-`TASK:`-only regression check), a live-browser
  check of the actual rendered Repeat button/disabled state and the
  `parseSuggestions()` regex logic against a realistic multi-marker
  sample (confirmed correct flat/grouped/flagged split), the standard
  40-route sweep, and a migration + render check against a **copy** of
  the real household database (never the original) — confirmed zero
  row-count drift on its real 7 projects/53 tasks, both new columns land
  correctly, and a real project's page still renders 200.

**Piece 68 (v0.48, merged to `main` in Piece 71 below): Projects get a
real Owner — done.** User: "Right now there doesn't seem to be a way to
assign a person to a project if it was not assigned at creation. Let's
fix that." Investigation found the actual gap was bigger than the
phrasing suggested: `projects` had **no assignee-like field at all**, not
even at creation — unlike Boards, which has had one since Piece 30.8.
Confirmed via AskUserQuestion: a real **"Owner"** label (not "assigned
to") — defaults to whoever creates the project, reassignable anytime —
and it should feed into the Piece 64 dashboard breakdown alongside (not
instead of) task assignment, so a parent can "balance members who own a
larger project vs. members on the team assigned to smaller tasks inside."
- New `projects.owner_id` (nullable FK) — same explicit-typed-`ALTER
  TABLE` pattern as Piece 67's `project_tasks.section_id` (a real INTEGER
  FK needs this, not `ensure_columns()`, which always adds `TEXT`).
  Existing real projects have no `created_by` field to backfill from, so
  they land with `owner_id` NULL (no owner) after migration — correct,
  not a bug; nothing is fabricated.
- **Deliberately kept outside `PROJECT_FIELDS`/the generic edit-project
  form and version-snapshot machinery** — same precedent as
  `contract_amount`, which already gets its own dedicated route
  (`set_contract`) rather than living in the shared field list. A new
  `set_project_owner()` route (`projects.manage`-gated, matching
  New/Edit/Cancel/Reopen project) handles reassignment as its own small
  action.
- `new_project()`: owner defaults to the current signed-in user when the
  create form's Owner field is left blank; picking someone else (e.g. a
  Parent creating a project on a Child's behalf) is honored as typed. The
  Owner field only appears on the **create** form, not the edit form —
  reassigning afterward happens via a dropdown on the project's General
  tab instead (visible to everyone who can view the project; only
  `projects.manage` can actually change it).
- **Piece 64's dashboard breakdown updated to merge both signals**: a
  project now counts for someone if they **own** it OR have a **task**
  on it — the same project can appear under both its owner and a team
  member working a piece of it (a project owned by one person with a
  task assigned to someone else shows under both rows). An owned chip
  gets a 👑 marker so ownership visually stands out from mere task
  participation. The "Unassigned" bucket's definition tightened
  accordingly: neither an owner nor any task-assignee.
- Verified via compile, a full Jinja parse sweep, a fresh-DB boot, a
  test-client cycle (create form shows the Owner field; blank defaults to
  creator; an explicit different owner at creation is honored; the
  dedicated reassign route works and can also clear the owner back to
  none; the General tab shows the dropdown to a `projects.manage` user;
  a project owned-but-taskless shows under its owner with the crown
  marker; a project owned by one person with a task assigned to another
  shows correctly under both; a project with neither shows in
  Unassigned), regression runs of the Piece 64 and Piece 67 test suites
  (zero breakage from either), the standard 40-route sweep, and a
  migration + render check against a **copy** of the real household
  database (never the original) — confirmed zero row-count drift on its
  real 7 projects/53 tasks, `owner_id` lands correctly, and the
  dashboard/project-detail/new-project pages all still render 200.

**Piece 69 (v0.45): production hosting scaffolding + security hardening —
done, on branch `deploy/production-hosting-security` (off `main` at v0.44,
independent of the still-unmerged `feature/plan-tab-and-task-sections`
branch carrying Pieces 67-68).** User: "I want to begin detailing how we
can get this app working live as intended... I need to keep it secure and
running a machine all day locally should be considered a backup option."
Confirmed via AskUserQuestion: a small VPS the household administers
itself (not a managed platform), on a fresh branch off `main` (not the
unmerged feature branch, not `main` directly).
- **Real, pre-existing security gap found and fixed**: `app.secret_key`
  was a hardcoded literal string committed to the repo — since Flask
  signs (but doesn't encrypt) session cookies with this key, anyone who
  could read the source could forge a valid login session for any
  account, including an admin. Harmless while the LAN itself was the
  trust boundary; a real problem once internet-facing. Now a real random
  key, generated once via `secrets.token_hex(32)` and persisted to
  `DATA_DIR/secret_key.txt` (already-gitignored, alongside the database)
  so restarts don't invalidate every session — or set explicitly via a
  `COMPENDIUM_SECRET_KEY` env var, which the VPS setup uses so a
  redeploy/reclone doesn't need the file to survive.
- **A second real gap: `init_db()` only ever ran inside `if __name__ ==
  "__main__":`** — under `gunicorn app:app` (the planned production WSGI
  server), that block never executes, so the database would never get
  created or migrated at all. The codebase had already solved this exact
  class of problem once, for the background maintenance scheduler
  (`_lazy_start_scheduler()`'s own comment: "works under `python app.py`
  ... and any WSGI server") — applied the same fix: `init_db()` now runs
  unconditionally at module-import time. It has to sit at the *bottom* of
  the module rather than right after its own `def`, since it calls
  `insert_seed_rules`/`tag_tasks_by_stage`, both defined later in the
  file — confirmed by an actual `NameError` on the first attempt when
  placed too early, not assumed.
- **Login rate-limiting, built on data already being collected.** The
  existing `audit_log`'s `audit()` after_request hook already recorded
  every `/login` POST with ip/status/ts, passwords already redacted. A
  failed login re-renders the form (200); a success redirects (302) — so
  counting recent 200s per IP *is* the failed-attempt count, needing zero
  new schema. `LOGIN_MAX_ATTEMPTS = 8` / `LOGIN_WINDOW_MINUTES = 15`; the
  9th failed attempt from the same IP within the window gets a **429**
  (deliberately not 200, so the lockout response itself never counts as
  another failure). Verified per-IP, not global: a different IP succeeds
  normally during the same window.
- **Reverse-proxy trust, gated behind a new env var.** A new
  `COMPENDIUM_BEHIND_PROXY` setting (set only in the VPS's systemd
  environment file, never on the LAN setup) applies
  `werkzeug.middleware.proxy_fix.ProxyFix` so Flask sees the real client
  IP and original protocol through Caddy, and flips
  `SESSION_COOKIE_SECURE` on — unconditionally trusting
  `X-Forwarded-For`/`X-Forwarded-Proto` without a real proxy in front
  would let any LAN client spoof its own IP or protocol, so this stays
  off by default. `SESSION_COOKIE_HTTPONLY=True` and
  `SESSION_COOKIE_SAMESITE="Lax"` are set unconditionally.
- **New `requirements-server.txt`** (`gunicorn` — doesn't run on Windows
  at all, so it's kept out of the main, Windows-safe `requirements.txt`,
  which now pins `flask==3.1.3`, the version actually installed/tested).
- **New `deploy/` directory**: `compendium.service` (a systemd unit
  running gunicorn, `Restart=on-failure`, reads secrets from an
  `EnvironmentFile=`), `Caddyfile` (a minimal `reverse_proxy` block —
  Caddy's automatic Let's-Encrypt HTTPS is why it was picked over
  nginx), `backup_db.py` (uses SQLite's **online backup API**, not a raw
  file copy, so a snapshot is never taken mid-write; timestamped
  snapshots with keep-last-N retention). New `DEPLOY.md` walks through
  the rest of a fresh VPS setup — explicitly scoped to start only once
  already SSH'd into a provisioned box; provisioning the account,
  payment, and domain/DNS are the household's own steps, not something
  done on their behalf.
- **Explicitly out of scope, flagged rather than silently decided**: this
  app has no CSRF token protection anywhere (no Flask-WTF, no manual
  tokens) across its ~100+ POST forms — a full retrofit is judged too
  large for this piece. `SESSION_COOKIE_SAMESITE=Lax` is a partial
  mitigation in the meantime (blocks the cookie riding along on most
  cross-site requests in modern browsers) but isn't equivalent to real
  CSRF tokens. Tracked below under "NOT done yet."
- Verified via: a plain `import app` (no `__main__` execution) against
  both the real database and a genuinely fresh scratch data dir,
  confirming the WSGI-compatible boot creates all 43 tables and seed
  data from nothing; secret-key persistence across two successive
  imports (same key both times) plus env-var override; the login
  rate-limiter's per-IP 8-then-429 behavior via a Flask test client;
  `SESSION_COOKIE_SECURE`/`ProxyFix` on vs. off by env var; `backup_db.py`
  run 3x with `--keep 2` against a scratch DB (confirmed exactly 2
  snapshots survive and the newest one's data matches the source exactly,
  not just that a file appeared); and the standard ~46-route sweep
  (unchanged — this piece changes no request-handling behavior for a
  normal signed-in user). Real deployment itself (VPS provisioning, DNS,
  starting the systemd service) is **not** verified here — that happens
  when the household works through `DEPLOY.md` on their own VPS.

**Piece 70 (v0.46): one-time LAN→VPS data migration + automatic one-way
VPS→LAN backup pull — done, same `deploy/production-hosting-security`
branch.** Right after Piece 69's VPS went live, the user pointed out the
two copies of the app didn't talk to each other at all, and asked for
either real two-way sync or, failing that, "VPS by default, LAN as
backup." Recommended against two-way sync (conflict resolution for a
household app is real complexity for little payoff) and for the
one-way version instead — confirmed by the user, then walked through
live end-to-end on the real VPS and the real LAN machine (not simulated).

- **One-time migration**: the VPS had only just been created and held
  fresh seed data (5 default household members, 0 real projects); the
  LAN's `job_creator.db` held the household's actual data (7 projects,
  53 tasks, 5 members). Two decisions confirmed via AskUserQuestion
  first, since one directly conflicted with something the user had
  already done: (1) **full database replace** (not a selective
  per-table copy) — chosen deliberately over a partial merge specifically
  because a partial copy risks silently mismatching foreign-key IDs
  between the two databases (a task assigned to `household_member_id=3`
  meaning a different actual person on each side) if the two rosters
  ever drifted, even slightly; the accepted cost is that the user's own
  already-separate VPS password (deliberately different from their LAN
  one) gets overwritten back to match the LAN's and needs re-setting
  right after — a real, known trade-off, not an oversight; (2) also
  migrate `uploads/` — turned out moot, no `uploads/` folder existed on
  the LAN checkout at all (no real uploaded files yet). Executed
  directly via SSH/SCP from the LAN machine (`ssh`/`scp` already
  available from `DEPLOY.md`'s own setup): stopped the VPS's
  `compendium` service, backed up its pre-migration database to
  `job_creator.db.pre-migration.bak` (kept, in case ever worth
  checking), `scp`'d the LAN's database up, verified an exact `md5sum`
  match on both ends before proceeding, fixed ownership, restarted, and
  confirmed via a direct SQL count (7 projects / 53 tasks / 5 members)
  that real data — not stale seed data — was live.
- **Ongoing one-way backup** (`deploy/pull_vps_backup.py`, new): rather
  than a live/bidirectional sync, a scheduled task pulls the VPS's
  **already-produced nightly snapshot** (Piece 69's `backup_db.py`
  output — safe to copy since it's a finished, SQLite-online-backup-API
  file, never the live database mid-write) down to the LAN machine's new
  `lan_backups/` folder (gitignored — real household data). One
  direction only, by design, matching the user's own "VPS by default,
  LAN as backup" framing exactly — no merge/conflict logic exists or is
  needed. The script takes `--host`/`--keep`/`--local-dir` as arguments
  rather than hardcoding this household's specific VPS address, keeping
  it portable/reusable.
- **A real, multi-round Windows debugging chain, worth remembering for
  any future Windows-side automation on this project**:
  1. `schtasks /create`'s `/tr` value cannot reliably hold two separate
     quoted paths back-to-back (a quoted `python.exe` path immediately
     followed by a quoted script path, both containing spaces) —
     regardless of correct PowerShell-vs-cmd quote-escaping (backtick vs
     backslash), `schtasks.exe` itself chokes on this specific pattern.
     Fixed by wrapping the real invocation in a small `.bat` file (which
     `cmd.exe` parses correctly at run time) and pointing `/tr` at that
     one single, simply-quoted path instead.
  2. Even after that fix, the task ran but failed with
     `-2147024891`/`0x80070005` ("Access is denied") — reproduced
     identically after recreating the task with `/rl highest`
     (eliminating a UAC-filtered-token theory) and after confirming via a
     disposable trivial task that Task Scheduler itself worked fine
     against a plain non-OneDrive path. Root cause: this repo lives under
     **OneDrive**, and something about how OneDrive's sync client
     interacts with a background/non-interactive process caused reads to
     fail there specifically — the exact same script always ran fine
     interactively. **Fixed by relocating**, not by fighting OneDrive:
     a plain copy of `pull_vps_backup.py` (and its `.bat` launcher) now
     lives at `C:\CompendiumOps\`, entirely outside OneDrive, invoked
     via the new `--local-dir` argument so pulled backups still land
     back in the repo's `lan_backups/` for the user to find where
     expected. Documented in `OPERATIONS.md` with an explicit reminder:
     if `deploy/pull_vps_backup.py` is ever edited, the
     `C:\CompendiumOps\` copy needs a manual re-copy — it will not
     update itself, since it's deliberately outside git's reach.
  3. `schtasks`'s own `267009` result code is not an error (it's
     `SCHED_S_TASK_RUNNING` — "still running, check again shortly") —
     easy to misread as a new failure mid-debugging; worth remembering
     for any future scheduled-task work.
- **New `OPERATIONS.md`** (repo root, alongside `DEPLOY.md`): a from-
  scratch reference doc the user explicitly asked for ("I'm still
  learning these skills and want to keep records for later study"),
  covering the full LAN/VPS architecture (with an explicit "the two
  databases are independent and don't sync" warning, plus a live "as of
  this writing, both happen to sit on the same branch — check
  `git branch --show-current`, don't assume" branch-state note), the
  update routine for each side, a VPS file/system glossary, and a
  troubleshooting playbook built directly from every real issue hit
  across both this piece and Piece 69's live setup — not a generic
  troubleshooting template. Also published as a **designed HTML
  Artifact** (IBM Plex Sans/Mono, a hand-built architecture diagram, a
  pine/brass/rust callout system) for the user's own easier reading,
  kept in sync with the same content as the repo's plain-Markdown copy.
- Verified via: direct execution against the real VPS and real LAN
  machine (not a simulated/scratch environment, since this piece's whole
  point was operating on the household's actual data) — `md5sum` match
  pre/post transfer, a live SQL row-count check post-migration, three
  full pull-script test cycles (direct run, idempotent re-run correctly
  skipping an already-had file, and a fresh `backup_db.py` trigger +
  re-pull to replace a stale pre-migration snapshot with a real
  post-migration one), and the scheduled task itself confirmed via
  `Last Result: 0` after working through the OneDrive relocation fix.

**Piece 71 (v0.48): closed a real drafts gap on `set_project_owner`, then
merged `feature/plan-tab-and-task-sections` → `main` → `deploy/
production-hosting-security`.** User: "Let's get security and that
feature work back up and running... we need to review where we are with
that project Owner before we push it to the web version." Reviewed
Piece 68's actual code (not from memory) before touching anything.
- **Real gap found on review**: `set_project_owner` shipped with
  `@admin_required` but no `@draftable`, unlike its sibling `set_contract`
  (same "own small route" pattern, same `projects.manage` permission
  level). Piece 52 established that every write an Assistant-role
  account makes across all 7 permission areas becomes a draft for a
  Parent to approve — `projects.manage` is one of those areas, so this
  was a real, if narrow, hole: an Assistant account could have reassigned
  a project's owner directly, no human review. Never actually
  exploitable in practice, since this branch was never merged/deployed
  until now — caught before it could be, not a live incident.
- Fixed by splitting the route into `_capture_project_owner`/
  `_apply_set_project_owner` (matching `set_contract`'s exact shape) and
  registering a new `"project.owner"` `DRAFT_KINDS` entry. Verified: an
  Assistant's owner change now creates a Pending draft instead of
  applying directly, approving that draft correctly reassigns the owner,
  and a normal admin's change still applies immediately with no draft —
  plus a full re-run of the existing Piece 67/68 test suites (zero
  breakage) and the standard 46-route sweep.
- **Merge sequence**: `feature/plan-tab-and-task-sections` → `main`
  merged cleanly (main hadn't changed since the branches diverged, so no
  conflicts) — main jumps straight from v0.44 to v0.46 in one step, now
  carrying Pieces 67/68/71. Then `main` → `deploy/production-hosting-
  security` **did** conflict, for an interesting reason: both branches
  had independently reached the string `"0.46"` for their own `VERSION`
  bump, describing completely different work (Piece 68's Owner feature
  vs. Piece 70's LAN backup pull). Resolved by renumbering the
  newly-merged content forward (v0.47/v0.48) rather than picking one
  side arbitrarily, so the combined branch reads as one coherent
  timeline; `README.md`/`HANDOFF.md`'s own conflicting build-history
  insertions were resolved the same way — both sides' content kept,
  reordered by piece number, no content silently dropped.
- Verified the final merged `deploy/production-hosting-security` state
  via compile, the standard route sweep, the Piece 67/68/71 test suites,
  and a migration smoke test against a **copy** of the real household
  database (never the original) — confirmed the schema migration is a
  clean no-op there, since the real db already picked up `owner_id`/
  `section_id`/`flagged_in_plan` from earlier local testing under this
  exact code, well before this merge.
- **Deliberately not done this piece**: merging `deploy/production-
  hosting-security`'s own unique content (Pieces 69-70: hosting/security
  scaffolding, the LAN backup pull) back into `main` — **update: done
  immediately after, per the user's explicit "let's merge everything
  now."** `deploy/production-hosting-security` was already an ancestor
  of nothing and a strict descendant of `main`, so `main` fast-forwarded
  cleanly to match it exactly — **all three branches
  (`main`/`feature/plan-tab-and-task-sections`/`deploy/production-
  hosting-security`) point at the identical commit as of right after
  this piece.**
- **CSRF retrofit intentionally deferred**, per explicit user instruction
  ("We'll scope the CSRF retrofit after") — see Piece 72, immediately
  below, where it was actually built.

**Piece 72 (v0.49): CSRF protection via Flask-WTF — done.** User: "Let's
use Flask-WTF then," after a direct conversation (not AskUserQuestion,
dismissed once and re-asked as a plain question) weighing Flask-WTF's
`CSRFProtect` against a hand-rolled token scheme. Recommended and chosen:
Flask-WTF — CSRF is a security-critical primitive where a subtle
self-made mistake (missed timing-safe comparison, no token rotation at
login, one missed `fetch()` call site) creates false confidence rather
than real protection, unlike this app's other "no dependency" choices
(ORM, JS framework, charting library), which were about convenience, not
correctness. Built on a fresh `feature/csrf-protection` branch per the
new post-Piece-71 branching rule.
- **Real scope, grepped not estimated**: 119 `<form ...method="post"...>`
  occurrences across 40 templates (no shared form macro exists anywhere
  in this app — genuinely one insertion per form, done via a one-off
  local script, verified afterward with an independent multi-line-safe
  scan confirming all 119 forms have a token and none were missed by a
  form tag spanning multiple lines) and 8 `fetch()`-based POST calls
  across 3 files (`assistant.html`, `project_detail.html`'s six Plan-tab
  actions, `work_bag_job.html`'s offline-queue flush).
- **A real interaction caught by connecting two pieces of context, not
  discovered after the fact**: Flask-WTF's default `WTF_CSRF_TIME_LIMIT`
  is 1 hour. This app's Work Bag (Piece 26) is explicitly offline-capable
  — its JS queues submissions in `localStorage` and only `fetch()`s them
  once `navigator.onLine` again, which could be hours later for a crew
  off-grid. A 1-hour token expiry would have silently reintroduced a real
  regression against a feature this app specifically built and documents.
  Set `WTF_CSRF_TIME_LIMIT = None` instead, tying it to the session's
  already-deliberate 12-hour lifetime.
- `templates/base.html` (the one shared template every page extends)
  gained a `<meta name="csrf-token">` tag and a one-line
  `window.CSRF_TOKEN` assignment, so every fetch() call site reads it
  once rather than re-querying the DOM.
- **Testing**: Flask-WTF does not auto-disable itself under
  `app.testing` — every existing scratch regression test needed a
  sibling `WTF_CSRF_ENABLED = False` line next to its `TESTING = True`
  one. **Caught one real miss during this exact update**: one test
  script used `app.testing = True` (a different, valid Flask idiom)
  instead of `app.config["TESTING"] = True` — the batch fix's regex only
  matched the latter form, so that one file's logins all started failing
  with 400s the first time it was re-run. Diagnosed correctly as CSRF
  actually working as intended (proof the protection is live), not a
  bug, then fixed by hand. A new dedicated test deliberately leaves CSRF
  enabled (every other test disables it) to prove the protection itself
  works: rejects a POST with no token, rejects one with a bogus token,
  accepts one with a real token via the form field, and — separately,
  closing a gap the first pass of that test missed — accepts one via the
  `X-CSRFToken` header alone with no form field at all, the exact
  mechanism every `fetch()` call in this app actually uses.
- Verified via: the mechanical form/token-count-match scan; every
  existing Piece 58-71 regression script re-run with CSRF disabled (all
  still pass unchanged); the new dedicated CSRF-enforcement test (both
  the form-field and header paths); a migration/boot smoke test against
  a **copy** of the real household database; and a genuine live-browser
  check via a scratch dev server — a real login form submission and a
  real Tasks-tab flag-toggle both round-tripped correctly with CSRF
  fully enabled, not just the Flask test client.
- Merged `feature/csrf-protection` → `main`; since `main` and
  `deploy/production-hosting-security` were already identical (Piece
  71's unification), fast-forwarded the deploy branch to match rather
  than a real merge. Deployed to the live VPS and verified there too.
  **`main` and `deploy/production-hosting-security` are still identical
  after this piece** (both fast-forwarded together) — the "main is
  missing Pieces 69-70" asymmetry noted after Piece 71 no longer applies.

**Piece 73 (v0.50): removed the legacy "Contract" concept — done.** User:
"let's check the legacy 'Contract' field cleanup and then move onto UI."
Investigated fresh rather than trusting the old Piece 54 inventory as
still-current: re-grepped every touchpoint, re-read `project_billing()`'s
actual current code, and — critically — **queried the real household
database before recommending anything**: all 7 real projects had
`contract_amount` blank, and zero Income transactions had ever been
logged. That's concrete proof, not inference, that the concept was never
used once. Confirmed with the user to remove it outright rather than
rename it, then scoped and built via Plan Mode given the real multi-file
size (comparable to Piece 41's de-solarize work).
- **What actually fed what, worth remembering**: `project_billing()`'s
  `collected`/`outstanding`/`expense`/`net` were already computed
  entirely from the real `project_transactions` ledger — `contract_amount`
  only ever fed one derived figure, `uninvoiced` (contract minus
  invoiced), which was therefore mathematically guaranteed to always be
  `$0` given contract was always 0. Removing it left every other billing
  figure completely intact and correct.
- **A real bug caught by re-reading `init_db()` closely, not assumed
  away**: `ensure_columns(db, "projects", ["contract_amount"])` ran
  *earlier* in `init_db()` than the new drop-column migration. Left
  as-is, this would have silently re-added the column on every
  subsequent server restart after the first (`ensure_columns` doesn't
  know about the later meta-guard), completely undoing the removal one
  restart after it shipped. Caught during implementation, not after —
  removed the stale `ensure_columns` call outright.
- **Also removed, since they only ever existed to support Contract**:
  the dedicated `set_contract` route (with its own `_capture_contract`/
  `_apply_set_contract`/`DRAFT_KINDS` entry — the request would have
  404'd harmlessly if left, but leaving a route with nothing behind it
  is its own kind of clutter), the "Money in projects" dashboard/Money-
  page tile (removed outright rather than repurposed from
  `estimated_cost`, since that would have just duplicated the existing
  "Anticipated spending" tile's own estimate half), and the Wrap-up
  worklist's "balance due" column (`_closing_worklist`) — which, doing
  the math, had never once shown a nonzero figure for any real project
  either, for the identical reason `uninvoiced` never had.
- **Explicitly found and deliberately deferred, not touched this
  piece**: `TITLE_STATUS_KEYWORDS`/`_status_from_title`/
  `tag_tasks_by_stage` — a much larger, separate solar-installation-
  jargon artifact ("meter set", "doc tube", "interconnection", milestone
  percentages) that happens to include the word "contract" as one of
  ~30 keywords, built for auto-tagging tasks the BPMN engine (removed
  Piece 40) used to generate. Its own one-time migration guard suggests
  it's already fully inert on the real database. Also left untouched:
  `project_transactions.contract_snapshot` and its sibling invoice-
  generation columns (Piece 27.3) and the "Signed Contract" document-
  upload-slot category (`project_detail.html`'s Documents tab) — both
  genuinely different "contract" concepts (a generated-invoice snapshot;
  a document category) than the dollar-figure field this piece removed,
  out of scope for this specific cleanup.
- Verified via: a fresh-DB boot confirming the column never gets
  created; a full Jinja parse sweep; a dedicated test-client script
  (Billing tab renders with none of the removed elements while
  Collected/Expenses stay correct; the Money page and dashboard render
  with no "Money in projects" tile; Closed Projects renders with no
  Contract column; the old `/projects/<id>/contract` route now 404s;
  the AI assistant's `find_projects`/`project_details` tools no longer
  mention contract at all); regression re-runs of the money-adjacent
  Piece 60/62/63 suites (`piece62_money_test.py` updated to match the
  new shape) plus Piece 69/71/72's suites, all unchanged; the standard
  46-route sweep; and a migration test against a **copy** of the real
  household database — confirmed the column actually drops and all 7
  real projects survive with every other field intact.
- Also swept a stale build-history claim discovered along the way:
  README's own "Finance & billing" and "💬 AI Assistant" sections still
  described Contract as a current feature (not just historical build-
  history entries, which stay untouched by this project's own
  convention) — updated both, and caught an unrelated pre-existing
  staleness in the same paragraph (a "find projects by
  stage/county/overdue/contract" line still mentioning `county`, a
  filter removed back in Piece 41) while already there.
- Merged `feature/remove-contract-field` → `main` → fast-forwarded
  `deploy/production-hosting-security` to match; deployed to the live
  VPS and confirmed there too.

**Piece 74 (v0.51): full legacy-artifact sweep — done.** User: "let's take
the time to clean up those legacy artifacts and any others you find so
they're truly done and over with," explicitly asking to go beyond the two
items Piece 73 had already flagged and deferred. Ran a 3-way parallel
Explore-agent audit (dead code in `app.py`, orphaned schema in
`schema.sql`, stale UI text in `templates/`) rather than guessing at scope,
then verified the riskiest findings against the real household database
before committing to a plan.
- **A genuine, previously-unnoticed bug, found during the audit**:
  `household_members.access_level` was being silently re-added by an
  unconditional `ensure_columns()` call on *every single app restart*,
  immediately ahead of the one-time `household_reorg_v1`-guarded migration
  that was supposed to have dropped it for good back in Piece 35 — moved
  the `ensure_columns()` call to inside that guard, right before the
  column is read/dropped in the same pass.
- **A second, deeper layer of the same bug, caught only by testing against
  a copy of the real database, not just a fresh one**: the real household
  database already has `household_reorg_v1` permanently set from years
  ago, so the relocated fix alone never re-runs there — the guard is
  already satisfied, meaning `access_level` (already resurrected by the
  old bug) would have stayed resurrected forever on that specific
  database. Fixed by adding a second, independent, unconditional
  `ALTER TABLE household_members DROP COLUMN access_level` to the new
  `legacy_artifact_sweep_v1` migration block, which runs once regardless
  of the old flag's state. Re-verified against a **fresh copy** of the
  real database (the first copy had already consumed the new migration
  flag, which would have masked a re-test) — confirmed the column drops
  and stays dropped across two successive `init_db()` calls, all 5 real
  household members and 7 real projects intact.
- **Other dead code removed**: the unused `GRT_DEFAULT_RATE` constant; the
  dead `"products"`-field special-case in `_rule_form_values()` and the
  now-unreachable `match_type == "contains"` branch in `condition_met()`
  (confirmed safe via grep — no `<select name="match_type">` exists
  anywhere, so it's never user-submitted — and the real database has zero
  `resource_rules` rows at all); `TITLE_STATUS_KEYWORDS`/
  `_status_from_title()`/`tag_tasks_by_stage()`, the BPMN-era task
  auto-tagger flagged as deferred at the end of Piece 73, removed entirely
  along with its call site in `init_db()` (already permanently inert via
  its own `tasks_stage_tagged` meta guard); two stale PV/Battery/EE-98
  docstring examples in `group_rules()`/`consolidate_rules()`.
- **Schema cleanup**: a new `legacy_artifact_sweep_v1` migration drops
  `project_transactions.invoice_number/milestone/due_date/
  contract_snapshot/base_amount/extras_amount/bom_snapshot` (Piece 27.3
  invoice-generation remnants, the other half of Piece 73's deferred item)
  and `field_submission_items.hours_json/work_date` (Piece 27.9 payroll
  remnants) — required also fixing two live INSERT statements
  (`api_work_bag_submit` and the photo-task-completion route) that were
  still writing to `work_date`.
- **Billing tab overhaul, per two explicit user decisions**: income
  categories changed from a fixed dropdown (the literal solar 50/40/10
  progress-billing structure — `HANDOFF.md` had claimed this was "cut
  entirely" after the invoice-PDF route was removed, but the vocabulary
  itself had survived) to a free-text field with suggestions
  (`INCOME_CATEGORY_SUGGESTIONS`), matching Household Budget's own
  existing `<datalist>` pattern — confirmed via the real database that
  zero Income transactions have ever been logged, so nothing was ever
  actually exercising the old fixed list either. Expense categories stay
  an untouched fixed dropdown (still reasonable for a household ledger;
  only income was in scope). The three solar-specific document-upload
  slots (`"Signed Contract"`, `"Design / One-Line"`, `"Site Plan
  (KMZ/KML)"`) were removed outright, leaving just `"Site Photos"` —
  confirmed via the real database that `project_files` has zero rows, so
  nothing was orphaned. Party label relabeled "Customer"/"Payer" for
  Income mode.
- **Wording sweep**: ~20 instances of stale business vocabulary ("the
  office," "supervisor," "crew," "on staff," "install date") replaced
  with plain household language across 10 templates — mechanical,
  no behavior change.
- Verified via: a fresh-DB boot across two successive `init_db()` calls
  confirming the schema stays clean; the new `piece74_legacy_sweep_test.py`
  (Documents tab shows only Site Photos, Billing tab renders income as
  free text with a working datalist while expense stays a dropdown, an
  arbitrary non-suggested income category saves fine, the old
  `/projects/<id>/contract` route still 404s, a `field_name="products"`
  rule is still rejected); a full Jinja parse sweep across every touched
  template; the full regression suite (Pieces 58-73) re-run unchanged; the
  standard 46-route sweep; and — the most important check — a migration
  test against a **fresh copy** of the real household database, which is
  what actually caught the second `access_level` layer described above.
- Also swept README's "Finance & billing" current-feature section for the
  now-outdated income-category description.
- Merged `feature/legacy-artifact-sweep` → `main` → fast-forwarded
  `deploy/production-hosting-security` to match; deployed to the live
  VPS and confirmed there too.

**Piece 75 (v0.52): mobile-responsive UI audit — done.** User: "let's
move onto UI," picking up the long-deferred mobile-responsive pass this
same NOT-done-yet list had been carrying since Piece 56. Rather than
assume the app needed a ground-up responsive retrofit (the old framing:
"never had a real small-screen check"), actually ran the app on real
phone-width viewports and checked, since the previous framing was never
itself re-verified against current code — same lesson as
`feedback-scope-assumptions-vs-user-intent`.
- **Method**: a scratch copy of the real household database (never the
  original) behind a throwaway dev-server config, driven headlessly at
  375px/330px/320px viewports. Since this environment's browser pane
  doesn't composite screenshots, verification used the DOM directly — a
  small injected script measuring `document.documentElement.scrollWidth`
  against the viewport (flagging real horizontal page overflow, not
  false positives from legitimately-scrollable containers or off-screen
  `.rstack`-collapsed table headers) — the same technique Piece 31.6
  originally used ("verified with headless Chromium... no horizontal
  page overflow"), just without a visual screenshot layer.
- **Checked ~30 pages/tabs/forms**: dashboard, every project-detail tab
  (General/Plan/Requirements/Materials/Documents/Tasks/Billing) on both
  an empty project and one with 49 tasks + injected test transactions,
  Tasks, Boards, Work Bag + a job detail view, Household Members + a
  profile, Money, Approvals, Drafts, Requirements Editor + Library,
  Inventory, Wishlist, Contacts, Household Files, Backlog, Closed
  Projects, Appointments, Chores, Notifications, Audit Log, Access
  console, Assistant + its settings, Help, Account, Budget, and New
  Project. **All but one came back completely clean** — the existing
  Piece 31.6/31.7 foundation (hamburger nav, table auto-wrap/restack,
  `repeat(auto-fit, minmax(...))` form grids, ≥16px inputs) turned out to
  already cover nearly the entire app correctly, including every feature
  built since the original pass (Chores, Appointments, Budget, Wishlist,
  Contacts, the Plan tab, Piece 74's new Billing category fields) with
  zero page-specific work needed — it's genuinely global CSS/JS, not
  something that has to be re-applied per new page.
- **One real, verified bug found and fixed**: the dashboard's month-
  calendar (a 7-column Sun–Sat grid, `dashboard.html`) has a `<thead>`
  with 3+ columns, so base.html's generic table-auto-tagger script
  (built for dense *data* tables — Billing ledgers, the audit log, etc.)
  was tagging it `rstack` too. At ≤560px that collapses a table into
  labelled `data-label: cell` rows — appropriate for a data table, but
  for a date grid it destroyed the calendar into 6 stacked "cards," each
  just a vertical list of "Sun: —", "Mon: —", ... "Sat: 1" — confirmed
  live via the DOM (`display: block/flex` instead of `table/table-cell`
  before the fix). Fixed by giving the calendar table a `no-rstack`
  class and teaching the auto-tagger to skip any table carrying it — a
  new, narrow opt-out, not a change to how any other table behaves.
  Confirmed via grep this is the app's *only* calendar-grid-shaped table
  (no `["Sun","Mon",...]` pattern anywhere else).
- Verified via: a new `piece75_mobile_calendar_test.py` (the rendered
  dashboard HTML carries the `no-rstack` class on the calendar table); a
  live DOM check confirming the calendar now stays `table`/`table-cell`
  at 375px while the dashboard's other two `rstack` tables are unaffected
  and still restack correctly; a re-check that overall page overflow is
  still zero at 375px, 330px, and 320px; a Jinja parse check on both
  touched templates; and the full Piece 69/71/72/73/74 regression suite
  re-run unchanged.
- Merged `feature/mobile-responsive-ui` → `main` → fast-forwarded
  `deploy/production-hosting-security` to match; deployed to the live
  VPS and confirmed there too.
- **This closes item (1) of the Pixel 9a beta-test readiness list
  below** — items (2) and (3) there are unaffected and still open.

**Piece 76 (v0.53): Parent UI review pass — done.** User: "let's review the
buttons and layout of all screens, beginning with the Parent Dashboard,"
then clarified this would be a manual, screenshot-driven session (the user
clicking through the live production site and sending screenshots for
context) rather than another automated audit — the goal being to rearrange
buttons/icons and build toward a style guide for future custom UI art.
Every change below was made in direct response to one screenshot + a
specific request, verified against a scratch copy of the real household
database, never the live site directly, then shipped together as one
piece once the user said the Parent-UI round was done.
- **Dashboard**: every `<details>` section (Household overview,
  Productivity Overview, Orders and Deliveries, each pipeline stage,
  My schedule) now starts **collapsed** on load — all were hardcoded
  `open` before. "Procurement" relabeled "Orders and Deliveries."
  **Backlog** and **My requirements** cards removed from the dashboard
  entirely (the underlying `/backlog` and standalone-requirements
  features are untouched, still reachable from their own nav entries) —
  `backlog_worklist`/`my_requirements` were also removed from
  `dashboard()` since nothing else used them, avoiding a compute-only
  orphan. The Planning stage's card shows the **next to-do** in place of
  the (almost-never-populated) Requirements column, and its Progress bar
  no longer repeats that same text — a new `show_next` parameter on the
  shared `job_progress()` macro handles this without touching the
  Progress widget's other 20+ call sites' behavior. Every Productivity
  Overview item (Appointments, Chores, Boards, Tasks) now has a one-tap
  ✓ — Boards and Tasks needed the button added; Chores and Appointments
  already had one but, caught in the process, it silently redirected
  away to `/chores`/`/appointments` instead of staying on the dashboard
  (`chore_done`/`appointment_done` didn't honor a `next=` param the way
  `set_task_status`/`board_status` already did) — fixed to match.
- **Projects list**: redesigned from a flat table into per-project cards —
  a real bold header (project name, linked) with its category where the
  name used to sit as a plain value, and the existing Stage/Target date
  columns followed by a new Progress column, which — via the same
  rstack restacking every dense table already gets — lands as the last
  (bottom) row of each card, exactly as asked.
- **Task board**: the intro blurb and the Who/Show filter are gone from
  the top (filter tucked into a collapsed `🔍 Filter` section); every
  project group starts collapsed with a one-line **next-to-do preview**
  visible even while collapsed (previously nothing showed until
  expanded); the signed-in user's own projects now sort first, ahead of
  the overdue/soonest-due ordering that used to be the only factor.
- **Boards**: blurb removed; the Who and Status filter rows are now
  color-coded (Who = a new `--accent2` blue, Status = the existing brand
  green) so the two independent filters read as separate controls; every
  row gained a ✓ to mark done in place (redirects back to `/boards` with
  whatever filter was active, via the existing `board_status` route's
  `next=` support).
- **Chores**: notes moved out of the Chore cell into their own column at
  the end of the table (lands at the bottom on mobile, same restacking
  trick as Projects' Progress column); chores now group into collapsible
  **Daily/Weekly/Monthly/Quarterly/Yearly** buckets by recurrence
  interval (a new `_chore_recurrence_bucket()` helper, boundaries picked
  at the log-scale midpoint between each nominal value); "＋ New chore"
  moved from an inline form at the bottom of the list to a toolbar button
  at the top, linking to a genuinely new page (`chore_form.html` +
  `chore_new_form`/`chore_edit_form` GET routes) instead of the old
  `?edit=<id>` inline-card pattern, which is now fully retired.
- **Notifications**: a persistent 🔔 bell with an unread-count badge now
  sits directly in the mobile header, always visible — previously the
  count was only visible after opening the hamburger menu and then the
  "To-do" dropdown inside it.
- **Appointments**: Who/Show filter rows color-coded the same way as
  Boards; intro blurb removed.
- **Money**: the Budget/Loans/Savings toolbar buttons were wrapping onto
  two rows on a phone (default-sized `.btn`/`.btn-secondary`) — given the
  same compact sizing every other page's toolbar buttons already use, all
  three now fit on one row at both 375px and 320px.
- **Household Files**: added Category and Format filters (color-coded
  the same way), where Format is a new `HOUSEHOLD_FILE_FORMATS` bucket
  scheme (PDF/Images/Office docs/Other) derived live from each file's own
  extension — no new column, so it can never drift out of sync with the
  actual file.
- **Contacts**: split into "👤 Individuals" / "🏢 Organizations" tabs
  (reusing `project_detail.html`'s existing `.tab-bar`/`.tab-panel`
  pattern) instead of one flat table with a redundant Type column now
  that the tab itself conveys it.
- **Inventory**: fixed a real, previously-unnoticed bug — there was **no
  way to add the very first inventory item**, since the "＋ New item"
  button only ever rendered inside an already-existing category section
  (which requires an item to exist first). Added a global "＋ New item"
  button to the main toolbar. Custom collapsible categories already
  worked once items exist (confirmed live). Added an optional
  `subcategory` field — a category with 2+ distinct subcategories in use
  (the user's own example: Hobbies → Sewing/Clay/Beading) automatically
  nests into its own collapsible groups; a category with none stays a
  plain flat table, unchanged. **A real bug caught before shipping**: the
  first implementation used `s.items`/`g.items` (dot notation) on plain
  dicts, which Jinja resolves to the dict's own built-in `.items()`
  *method* rather than the `"items"` key — a classic Jinja/dict pitfall
  (the original code already used bracket access, `s['items']`, for
  exactly this reason; the refactor into a macro accidentally
  reintroduced dot notation) — caused a real 500 on `/inventory` once any
  item existed, caught immediately via a live click-through, fixed by
  switching every reference back to bracket notation.
- **AI Assistant — Gemini removed entirely** (user: "I don't need it at
  all"): every `Gemini`/provider-selector code path removed from
  `ai_assistant.py` (the whole `_gemini_agent`, `build_gemini_request`,
  `parse_gemini_response`), `app.py` (`assistant_available_providers`,
  `_provider_configured`, every `provider=` form field and branch),
  and all three templates that had a provider dropdown
  (`assistant_settings.html`, `assistant.html`, `project_detail.html`'s
  Plan tab) — `ask()`/`run_agent()` in `ai_assistant.py` dropped the
  `provider` parameter outright rather than keeping an always-"claude"
  vestige. A new one-time cleanup deletes the now-dead
  `ai_default_provider`/`ai_gemini_key`/`ai_gemini_model` meta rows.
- **AI Assistant — 5-conversation rolling history** (user: "up to 5
  slots... no more than 5 can be held in memory to encourage using the
  actual app features"): two new tables, `assistant_conversations` and
  `assistant_messages`, scoped per household member. A strip of up to 5
  saved conversations (auto-titled from each one's first question) sits
  above the chat; switching or starting fresh is a plain `?conversation=`
  link, matching every other filter-via-query-param page in this app.
  Starting a 6th conversation drops the oldest (its rows) first — a new
  `_rotate_assistant_conversations()` helper, called from `assistant_ask()`
  only when no valid `conversation_id` was posted. Follow-up questions in
  the same conversation fold the last 20 prior turns into the prompt,
  identical to the Plan tab's own existing history-capping convention.
- **AI Assistant — propose-a-project drafts** (user: "projects or other
  templateable work is discussed, the Assistant can send a draft to be
  approved"): `ASSISTANT_SYSTEM_PROMPT` teaches a new
  `NEW_PROJECT: <name> | <category> | <subcategory>` line convention
  (mirroring the Plan tab's existing `TASK:`/`SECTION:`/`FLAG:` lines),
  parsed client-side into a "Send as draft" button. Clicking it hits a
  new `/assistant/draft-project` route that inserts directly into the
  **existing** `drafts` table using the exact payload shape
  `_apply_new_project()` (Piece 51/52) already expects — so the
  **existing** Drafts page approve/discard flow needed zero changes.
  Any signed-in person can propose one (not gated to the Assistant
  household role) since the real safety gate is the Parent-approval step
  that already exists on every draft, regardless of kind. **A real bug
  caught by the test before shipping**: the first version of the payload
  hardcoded only `job_name`/`project_category`/`project_type`/
  `site_location`, missing `estimated_cost` (a `PROJECT_FIELDS` member
  added since this payload shape was last touched) — `_apply_new_project`
  raised `KeyError` on approval. Fixed by building the payload's values
  dict from `PROJECT_FIELDS` directly instead of a hardcoded literal, so
  it can't drift out of sync with that list again.
- **A separate, pre-existing bug found and deliberately NOT fixed here**
  (flagged as its own background task instead): `DRAFT_KINDS["project.new"]`
  and `["project.edit"]`'s own `"capture"` lambdas
  (`lambda **_: read_project_form()`) produce a flat values dict, but
  `_apply_new_project`/`_apply_edit_project` both expect
  `payload["values"]` — meaning a real Assistant-role household account
  submitting a new/edited project through the *existing* Piece 51/52
  draft-interception path (not the new chat-proposal path above, which
  builds its own correctly-shaped payload) would hit `KeyError: 'values'`
  on approval. Never hit in practice since no Assistant-role account has
  tried it yet, but genuinely reachable given Assistant's confirmed
  `projects.manage` grant (Piece 51).
- Verified via: a new `piece76_assistant_test.py` (Gemini fully absent
  from settings/assistant pages; a stubbed `ai_assistant.run_agent` proves
  a first message creates a conversation with the right title, a
  follow-up reuses it and includes prior-turn history, six conversations
  in a row correctly rotate down to 5, a `NEW_PROJECT:` proposal creates
  a real Pending draft, approving it creates the real project via the
  *existing* apply logic, and a bogus category/subcategory is sanitized
  rather than stored); a fresh-DB boot across two `init_db()` calls; a
  migration test against a **fresh copy** of the real household database
  (all 5 members and 7 projects intact, `subcategory` column and both new
  `assistant_*` tables present, old Gemini meta rows gone); a live
  DOM/overflow check at 375px/320px across every touched page; and the
  full Piece 69/71-75 regression suite re-run unchanged throughout.
- Merged `feature/dashboard-ui-cleanup` → `main` → fast-forwarded
  `deploy/production-hosting-security` to match; deployed to the live
  VPS and confirmed there too.

**Piece 77 (v0.54): fixed duplicate reminder notifications — done.**
User: "the daily chore of making dinner rang twice for not being marked
done, and after I looked at the notifications they didn't clear - I had
to click through the now nonexistent chores to clear them. for daily
chores, don't stack the notification."
- **Root cause**: `ensure_routine_task_reminders()` (and its three
  siblings — `ensure_appointment_reminders`, `ensure_requirement_reminders`,
  `ensure_backlog_reminders`) all used a check-then-act pattern: `SELECT`
  rows where `reminder_sent != '1'`, loop over them calling
  `notify_employees()`, THEN `UPDATE ... SET reminder_sent = '1'` at the
  end of the loop (one batched commit for the whole pass). This app runs
  **2 gunicorn worker processes** in production, plus a periodic
  background scheduler thread (`run_maintenance` / `_scheduler_tick`) —
  both of these functions are explicitly called from both the dashboard
  route AND the scheduler. Two callers landing close enough together
  (e.g. a dashboard load racing a scheduler tick, on different
  connections/processes) could both pass the `reminder_sent != '1'`
  check before either one's UPDATE had committed, both firing a
  notification for the same due chore — exactly the "rang twice"
  symptom. The "didn't clear" half of the report was very likely a
  direct consequence, not a separate bug: `notification_open()` (the
  route behind every "Open"/"Dismiss" button) already correctly deletes
  a notification and redirects — but with two duplicates stacked, the
  user had to click through it twice, each time landing on the general
  `/chores` page rather than anything specific to resolve, which reads
  exactly like "clicking through nonexistent chores to clear them."
- **Fix**: the `UPDATE`/`INSERT ... ON CONFLICT` that flips
  `reminder_sent` is now the atomic claim, run and committed *before*
  `notify_employees()` is ever called, and gated on its own `rowcount`.
  SQLite serializes writes at the file level, so only whichever caller's
  UPDATE actually flips the flag from unset to `'1'` (rowcount 1) goes on
  to notify; a caller that loses the race sees rowcount 0 on its own
  UPDATE (the row was already claimed) and skips notifying entirely, no
  matter how close together the two calls land. Applied identically to
  all four reminder functions since they share the exact same shape and
  the exact same dashboard+scheduler dual-caller exposure — chores was
  just the one that got reported and reproduced first.
- The idea-backlog function has a second, meta-table-based nudge (the
  monthly "review your backlog" notice, keyed by `backlog_review_last_sent`)
  using the same check-then-act shape against a different table — fixed
  with the equivalent atomic pattern: `INSERT ... ON CONFLICT(key) DO
  UPDATE SET value = excluded.value WHERE meta.value != excluded.value`,
  gated on `rowcount` the same way. Verified this exact SQLite UPSERT-
  with-WHERE idiom reports `rowcount = 0` when the conflicting row's
  value already matches (i.e., "someone already claimed this month") and
  `rowcount = 1` only on a genuine change, via a small isolated script
  before wiring it in.
- Verified via a new `piece77_reminder_race_test.py`: a manual two-
  connection interleaving that reproduces the actual race (both
  connections see the row as unclaimed before either writes), proving
  only one connection's claim succeeds; a real end-to-end call of
  `ensure_routine_task_reminders()` confirming exactly one notification
  lands and a second call doesn't stack a duplicate; and the same
  single-fire check repeated for appointments, standalone requirements,
  and both backlog nudges. Full Piece 69/71-76 regression suite re-run
  unchanged.
- Merged `feature/reminder-dedup-fix` → `main` → fast-forwarded
  `deploy/production-hosting-security` to match; deployed to the live
  VPS and confirmed there too.

**Piece 78 (v0.55): Habit Tracker — done.** User: "I also want to add a
Habit Tracker into the app in a way that makes sense. it would be a good
jumping off point for me before going to the Child account UI." Scoped via
3 questions before writing anything:
- **A new, separate feature from Chores**, not an extension of it — a
  chore is task-oriented (do it, it's due again later); a habit is about
  **consistency over time**, tracked as a streak + short history instead
  of a single next-due date.
- **Simple daily yes/no check-in**, no notes-per-check-in — a streak
  counter plus a compact 14-day "contribution graph" strip is enough to
  see consistency at a glance.
- **Shared like Chores**, not personal-by-default (the recommended
  option) — same nullable `household_member_id` model as `routine_tasks`:
  assign to one person, or leave unassigned and visible to anyone with a
  login.
- New `habits` / `habit_checkins` tables. `habit_checkins` deliberately
  has **no FK `REFERENCES` enforcement** on `habit_id` (matches this
  schema's existing convention for log-shaped child tables like
  `project_versions`, rather than introducing a never-before-used
  cascade-delete pattern) — `habit_delete()` explicitly clears a habit's
  own check-ins first. A `UNIQUE (habit_id, checkin_date)` constraint
  makes a repeat check-in for the same day a harmless no-op by
  construction, rather than needing a Piece-77-style fix later.
- **Streak and 14-day history are computed live** from `habit_checkins`
  every call (`_habit_streak()` / `_habit_recent_days()`), never stored —
  matches this app's general preference for deriving values on read (e.g.
  project progress bars) so they can't drift out of sync. A streak
  doesn't reset just because today isn't over yet: it counts backward
  from today if today's already checked in, or from yesterday otherwise,
  and only actually breaks on a real missed day.
- **Deliberately no reminder/notification system** for habits in this
  first build — a call I made, not something asked for, specifically to
  avoid reintroducing the exact class of race-condition bug just fixed in
  Piece 77, and because habit-tracker UX conventions typically show
  streak state visually rather than nagging with due-reminders the way
  Chores/Appointments/Requirements do.
- New `/habits` list page (per-habit card: title, streak, 14-day strip,
  ✓ check-in / edit / delete) and a standalone `/habits/new` /
  `/habits/<id>/edit` form, mirroring Chores' own dedicated-form pattern
  from Piece 76. A new "🔥 Habits" card on the dashboard's Productivity
  Overview lists today's not-yet-checked-in habits with a one-tap ✓,
  matching the existing Chores/Boards widgets there exactly (including
  the `next=` hidden field so checking in stays on the dashboard).
- **Caught and corrected a workflow gap before shipping**: work started
  directly on `deploy/production-hosting-security` (left checked out from
  Piece 77's deploy cycle) instead of a fresh branch off `main` — moved
  onto a proper `feature/habit-tracker` branch (carrying the uncommitted
  work with it) before committing, restoring the standing "every piece
  gets its own branch" workflow.
- Verified via a fresh-DB double-boot (schema idempotent, both new tables
  present), a migration test against a **copy** of the real household
  database (never the original — confirmed all 5 real household members
  survive untouched), a dedicated `piece78_habit_tracker_test.py` covering
  streak math (including the today-not-yet-checked-but-yesterday-was case
  and a gap correctly breaking a streak), the 14-day strip's exact
  contents, and deletion leaving no orphaned check-ins; and a Flask
  `test_client()`-driven, real-data-copy route test
  (`piece78_route_test.py`) exercising every new route end-to-end —
  create, list, check in (including the no-op repeat), the dashboard
  widget rendering, edit, and delete (confirmed delete stays a
  grant-only action, matching this app's soft-delete safety rail — not
  automatic even for admins).
- Merged `feature/habit-tracker` → `main` → fast-forwarded
  `deploy/production-hosting-security` to match; deployed to the live
  VPS and confirmed there too.

**Piece 79 (v0.56): Child/Assistant UI review — done.** User's original
request (Piece 76): "beginning with the Parent Dashboard... after a
complete run through of the parent UI, we'll verify the Child and
Assistant UIs respectively." This is that round — a continuous
screenshot-driven session on `feature/child-ui-review`, same "one branch,
ship when the user says they're done" pattern as Piece 76.
- **Child dashboard reworked**: the old day-by-day "🗓 My schedule" glance
  (Piece 53) is replaced by two cards, per the user's explicit request —
  a personal **"🙋 My Overview"** card (Appointments, Chores, Habits,
  Tasks, their own field Notes, Wishlist, all reusing data the dashboard
  route already computed for other roles) and full visibility into
  **every active household project** by stage, not just ones they have a
  task on (Piece 53's original restriction, explicitly lifted after
  confirming via AskUserQuestion). Appointments were folded into My
  Overview on my own call (not asked) since removing My schedule would
  otherwise have silently dropped a Child's only view of upcoming
  appointments.
- **Notifications scoped to what's actually a Child's**: reported via a
  screenshot of a Child's notification inbox full of pipeline-turnover
  and chore-due pings for things they had no stake in. `notify_stage_
  turnover()` now only includes a Child recipient if they have a task on
  that specific project; `ensure_routine_task_reminders`/`ensure_
  appointment_reminders`/`ensure_requirement_reminders` now exclude Child
  accounts from the "notify everyone" broadcast fallback for an
  *unassigned* item (a Child assigned directly to the item still gets
  notified — that's genuinely theirs). Household idea Backlog reminders
  were deliberately left alone — no per-item assignment concept for a
  Child to be "added to" there either way.
- **AI Assistant: a parent-safety notification.** When a Child talks to
  the assistant (global 💬 Assistant page or a project's 🧠 Plan tab) and
  the conversation goes idle 15+ minutes, every Parent gets one
  notification: hours spent (floored at 1 per the user's own call — a
  coarse signal, not a precise timer), message count, and which page.
  Child-only, confirmed via AskUserQuestion (not Parent/Assistant-role
  usage). Runs from the same dashboard+scheduler cadence as every other
  `ensure_*` reminder function, with a `safety_reported` flag per message
  so a conversation is never folded into two notifications.
- **AI Assistant: a persistent draft panel**, reworking Piece 76's
  one-off inline "Send as draft" bubble — now a single always-visible
  panel above the chat showing the current project proposal, updated as
  the conversation refines it and rehydrated from conversation history on
  page load (a new `_extract_new_project_proposal()` helper mirrors the
  front-end regex). Lets a Child working through an idea with the
  assistant (planning a science project, say) see what's been captured
  so far. The Drafts page's `project.new` summary now also shows
  category/subcategory, not just the bare project name, so a parent isn't
  approving blind.
- **Habit Tracker: Child self-assignment lock.** A Child creating or
  editing a habit gets no assignment dropdown at all — `_habit_form_
  values()` forces `household_member_id` to the Child's own id server-side
  regardless of what's submitted, closing off a spoofed-form path to
  assigning a habit to someone else.
- **Habit Tracker: interval tracking.** A habit's `frequency_type` is now
  `daily` (unchanged), `count` (a target number of check-ins per day —
  each tap adds one, capped server-side at the target), or `times` (a
  fixed list of specific times, each its own checkable slot). New
  `habit_interval_checkins` table (kept separate from the original
  `habit_checkins` rather than reshaping its UNIQUE constraint, which
  would have needed a full-table-rebuild migration against real,
  already-shipped Piece 78 data). A `times` habit shows a next-up/overdue
  indicator computed live — confirmed via AskUserQuestion this is
  **visual only, no push notification**, keeping Piece 78's original
  no-reminders design intact. `_habit_streak()`/`_habit_recent_days()`
  were consolidated into one `_habit_progress()` that handles all three
  types; verified the original plain-daily edge cases (today-not-yet-
  checked-but-yesterday-was, a gap breaking a streak) still hold exactly
  after the refactor.
- **Child nav lockdown**: the whole 🏠 Household dropdown (everything
  inside it was already permission-gated to things a Child never has by
  default, so it only ever showed up empty for them) plus Backlog and
  Contacts under 🗄 Databases are hidden from a Child — and genuinely
  blocked at the route level via a new `@child_forbidden` decorator
  (redirects with a flash message), not just a hidden nav link, matching
  this app's existing pattern for Family/Household Files/Requirements
  Editor (Piece 53).
- **Wishlist locked to a Child's own requests** — `wishlist_page()` forces
  `who = "mine"` server-side for a Child regardless of a tampered
  `?who=all`, and the "Whose" filter toggle doesn't render for them at
  all.
- **Inventory's top blurb removed** (for everyone, not Child-specific) —
  a small decluttering ask alongside the rest of this round.
- **Piece-numbering note**: several sub-features above were drafted under
  provisional piece numbers (80/81/82) while the review was still
  in-progress and their final scope wasn't yet settled; once the whole
  round shipped as one piece (matching the Piece 76 precedent — one
  continuous review session ships as one version bump), every code
  comment was swept back to **Piece 79** for consistency. If a future
  session finds a stray "Piece 80/81/82" reference anywhere, it's a
  leftover that should read 79.
- **Mid-deploy discovery, handled the same careful way as Piece 78**: a
  previously-flagged background task's uncommitted `DRAFT_KINDS` payload-
  shape fix (see Piece 76's note) surfaced again mid-session in the
  shared working tree. Isolated it out via targeted reverts before
  committing this piece's own changes, confirmed the diff was clean, then
  restored it untouched on `main` afterward — still not this piece's to
  commit.
- Verified via five dedicated test scripts against **copies** of the real
  household database (`piece79_child_dashboard_test.py`,
  `piece80_assistant_safety_test.py` — Assistant safety notifications +
  draft panel + Drafts summary, `piece81_habit_child_lock_test.py`,
  `piece81_interval_habits_test.py`, `piece82_child_nav_lockdown_test.py`
  — all still named for their provisional numbers, all still valid), a
  fresh-DB double-boot, and a migration test against a copy of the real
  household database confirming all 5 real household members and all 7
  real projects survive untouched with the new columns/tables present.
- Merged `feature/child-ui-review` → `main` → fast-forwarded
  `deploy/production-hosting-security` to match; deployed to the live
  VPS and confirmed there too.

**Piece 80 (v0.57): weekday recurrence, a project note-add fix, and
Assistant timeout/truncation fixes — done.** Four items in one user
message: a weekday-of-recurrence picker for Chores/Habits/"Personal
schedules" (clarified via AskUserQuestion to mean Appointments, plus a
broader "anything that recurs on this basis" mandate that also picked up
standalone Requirements), an investigation into a reported AI Assistant
response-length/timeout issue, a missing add-note button on a project's
own page, and a feasibility question about phone home-screen widgets.
- **Weekday recurrence**: a new shared `recurrence_weekdays` column
  (comma-separated day abbreviations, e.g. "Tue,Thu") on `routine_tasks`,
  `appointments`, `resource_rules`, and `habits`, plus one shared
  `_advance_recurrence()` used by `chore_done()`/`appointment_done()`/
  `requirement_done()` — when weekdays are set, finds the next matching
  weekday after today; otherwise falls back to the plain day-interval
  this app has always used. Each of the three forms gained a "Repeats:
  every N days / specific days of the week" toggle. **Habits gained a
  4th frequency_type, 'weekly'** — still a plain per-day check-in
  (reuses `habit_checkins`, no new table needed), but only scheduled
  weekdays are "eligible": an off-day is neither done nor missed (a
  distinct third visual state on the history strip), and the streak only
  counts actual scheduled occurrences, walking back through off-days
  without either counting or breaking on them. Verified the trickiest
  case directly: a missed day that *is* scheduled correctly breaks the
  streak, confirmed via a dedicated test.
- **AI Assistant timeout/truncation, root-caused not guessed**: the live
  gunicorn service had **no `--timeout` flag** at all, meaning gunicorn's
  **default 30-second worker timeout** applied — a multi-step tool-
  calling Assistant reply (up to `MAX_AGENT_STEPS=6` round-trips to
  Claude) can easily exceed that even when nothing is actually wrong,
  and gunicorn kills the worker mid-request. Fixed with `--timeout 180`
  in both the **live** `/etc/systemd/system/compendium.service` (edited
  directly, confirmed via AskUserQuestion first since it's outside the
  normal git-deploy pipeline) and the **repo's own**
  `deploy/compendium.service` — caught via a direct re-read of
  `OPERATIONS.md` that a live-only edit would've been silently
  overwritten by the next `cp deploy/compendium.service
  /etc/systemd/system/` a future session might run, per that doc's own
  documented gotcha. Separately, `ai_assistant.py`'s `max_tokens` was
  hardcoded to 1024 (~750 words) on every Claude call (both the plain
  `ask()` path and both call sites inside the `run_agent()` tool-calling
  loop) — raised to 4096, since a legitimately long, detailed answer
  could get silently truncated mid-sentence even on a call that
  succeeded well within any timeout.
- **Project note-add fix**: a project's own "📝 Field notes" card was
  read-only — its own empty-state text literally said "Crews can add
  them from the 🎒 Work Bag," confirming there was never a direct way to
  add one from the project page itself. `add_project_note()`
  (`/work-bag/notes`) previously always redirected back to the Work Bag
  via `_workbag_redirect()`; gave it an optional `next=` override (same
  pattern `chore_done`/`habit_checkin`/etc. already use) so the new
  inline form on the project page stays there instead of jumping away —
  the Work Bag's own existing call site is unaffected (no `next=`, same
  redirect as before).
- **Phone home-screen widgets: answered, not built.** A PWA can't
  provide real OS-level home-screen widgets on iOS or Android — that's
  native-app-only on both platforms. Recommended staying with the
  existing PWA-install + deep-link path rather than taking on separate
  native iOS/Android apps, which would be a large, ongoing commitment
  distinct from this project.
- **Piece-numbering note, same lesson as Piece 79**: sub-features were
  drafted under provisional numbers (83, 84) before the batch's full
  scope was known; swept back to a single **Piece 80** via `sed` once
  everything was ready to ship (confirmed via `git diff` that every
  occurrence was newly-added this session first). The two new test
  script filenames (`piece83_project_note_form_test.py`,
  `piece84_weekday_recurrence_test.py`) were **not** renamed — they're
  still valid, just named for their provisional numbers, same situation
  Piece 79 left behind for its own five scripts.
- **Mid-deploy discovery, expected but re-checked anyway**: re-verified
  before switching branches that the previously-flagged background
  task's `DRAFT_KINDS` payload-shape fix (see Piece 76's note) wasn't
  sitting uncommitted in the shared working tree again — it wasn't, this
  time. Same stash-or-isolate playbook is ready if it resurfaces.
- Verified via a new `piece84_weekday_recurrence_test.py` (7 checks
  including `_advance_recurrence()`'s weekday-wraparound math, Chores/
  Appointments/standalone-Requirements mark-done advancing correctly, an
  appointment with `recurrence_days=0` but weekdays set still being
  treated as recurring rather than one-time, and the weekly-habit
  streak-gap edge case), a new `piece83_project_note_form_test.py` (5
  checks including that the Work Bag's own flow is unchanged), a
  fresh-DB double-boot, and a migration test against a copy of the real
  household database confirming all 5 real household members and all 7
  real projects survive untouched with the new column present on all
  four tables. The full accumulated regression suite from Pieces 79-80
  (7 scripts) was re-run clean before shipping.
- Merged `feature/recurrence-notes-timeout-fixes` → `main` → fast-forwarded
  `deploy/production-hosting-security` to match; deployed to the live
  VPS (including the systemd reload for the gunicorn timeout change) and
  confirmed there too.

**Piece 81 (v0.58): Assistant drafting expanded beyond new projects —
done.** User: Jake ("just ask the AI to make appointments and stuff for
me") wants the Assistant able to draft anything he can do himself, not
just propose a new project. Scoped via AskUserQuestion to Appointments +
Chores + Wishlist items in this first batch (the most common "just add
this for me" asks), keeping the existing propose-then-confirm-then-
approve shape unchanged rather than granting any kind of direct write.
- **Generalized, not four separate one-offs**: `ASSISTANT_SYSTEM_PROMPT`
  now teaches `NEW_APPOINTMENT:`/`NEW_CHORE:`/`NEW_WISHLIST:` line
  conventions alongside the existing `NEW_PROJECT:` one (still ALONE on
  its own line, still at most one per reply). `_extract_draft_proposal()`
  (renamed/generalized from Piece 79's `_extract_new_project_proposal()`)
  and `assistant.html`'s JS both check all 4 patterns and keep whichever
  is LAST in the text, tagged with a `kind` — the persistent draft panel
  (Piece 79) already had the right shape for "one current proposal,
  whatever it is," it just needed the kind threaded through to know which
  endpoint/label to use.
- **New DRAFT_KINDS entries** (`appointment.new`/`chore.new`/
  `wishlist.new`) with their own `_apply_new_appointment`/`_apply_new_
  chore`/`_apply_new_wishlist` functions (same `payload["values"]`
  contract as `_apply_new_project`) and three new `/assistant/draft-*`
  routes mirroring `assistant_draft_project()` exactly — any signed-in
  person can chat-draft one (not gated to the Assistant-role account),
  same as the existing project flow. Chat-drafted appointments/chores
  default to unassigned (visible to the whole household); a wishlist item
  defaults to the person chatting, since `wishlist_items.household_
  member_id` is required (whose want-list this is for) unlike the other
  two's optional assignment.
- **Real bug caught and fixed while wiring this in**: `approve_draft()`'s
  `is_recommendation` check (which decides whether `reviewed_by` credits
  the approving parent vs. the original proposer) used `draft["kind"].
  startswith("wishlist.")` — the new `wishlist.new` kind would have
  matched that prefix too, even though creating a new wishlist item is
  nothing like approving/rejecting an existing one. `_apply_new_wishlist`
  never reads `actor_name` so this was harmless in practice, but fixed
  properly anyway (an explicit `("wishlist.approve", "wishlist.reject")`
  tuple) rather than leaving a landmine for the next kind added under
  that prefix.
- Verified via a new `piece81_assistant_draft_expansion_test.py` (6
  checks: proposal-parsing across mixed kinds keeps the textually-last
  one, all three new draft routes accept a Child's request and store the
  right payload shape, a Parent approving each creates the real
  appointment/chore/wishlist row correctly, and — the regression check
  that actually matters here — the existing `wishlist.approve`/`reject`
  recommendation flow still attributes `reviewed_by` to the approving
  parent exactly as before the `is_recommendation` fix). Full accumulated
  regression suite from Pieces 79-81 (8 scripts) re-run clean before
  shipping.
- Merged `feature/assistant-draft-expansion` → `main` → fast-forwarded
  `deploy/production-hosting-security` to match; deployed to the live
  VPS and confirmed there too.

**Piece 84 (v0.61): live VPS dates a day ahead in the evening — done.**
User, as a side note while discussing home-screen widgets: "I found a bug
where the app clock seems to be set a day ahead." Root-caused directly
rather than guessed at: `app.py` has **zero** timezone logic — every
"today"/"this month" calculation across all 67 `datetime.now()` call
sites (chores due today, the dashboard date, appointments, budget month
boundaries, etc.) is plain server-local time. `timedatectl` on the VPS
confirmed the box was on DigitalOcean's default `Etc/UTC`, several hours
ahead of the household's real Mountain Time — so once it passed roughly
6pm local, the server's calendar day had already rolled to tomorrow.
Confirmed via AskUserQuestion this is genuinely Mountain Time (an old NM
county-directory reference from Piece 38-41's now-fully-purged solar
seed data hinted at it, but that's stale historical context, not
something to assume from without asking).
- **Fixed at the server-config level, not in code**: rewriting 67 call
  sites (or introducing timezone-aware `datetime` objects that then have
  to interoperate with every existing naive-datetime SQLite string
  comparison in the app) would have been a much larger, much riskier
  change for a problem that's actually just "the server's clock is set
  to the wrong zone." `timedatectl set-timezone America/Denver` on the
  VPS, confirmed via a direct Python `datetime.now()` check inside the
  app's own venv (correctly returned local Mountain time, not UTC) —
  zero application code touched.
- **Also pinned at the systemd-service level, not just the OS level** —
  `Environment=TZ=America/Denver` added to `deploy/compendium.service`
  (and synced to the live `/etc/systemd/system/compendium.service` copy,
  per this repo's own documented sync pattern from Section 4/6 of
  `OPERATIONS.md`). This is deliberate defense-in-depth: a future VPS
  rebuild or restored snapshot would default back to `Etc/UTC` at the OS
  level, but the gunicorn process itself would still run correct as long
  as the repo's service file gets deployed normally — the one-time
  `timedatectl` step doesn't have to be remembered and re-applied by
  hand.
- Documented in `OPERATIONS.md`: a new Section 6 troubleshooting entry
  ("Dates in the app look a day off, especially in the evening") with
  the exact fix commands, and a new Section 4 glossary row calling out
  the VPS's timezone as a thing to check after any reprovision.
- Confirmed no cron jobs or systemd timers on the VPS are app-specific or
  timezone-sensitive (checked directly — only stock Ubuntu maintenance
  timers exist), so this fix has no other scheduling side effects to
  worry about.
- No schema or `app.py` changes this piece — purely server config +
  docs. Branch `feature/vps-timezone-fix`, off `main` at v0.60.

**Piece 83 (v0.60): "New [item]" buttons + back-links, consistency pass —
done.** User: "On any page that has an empty form on the bottom to submit a
new item (Boards, Chores, etc.) use a 'New [item]' button located at the top
that navigates to the creation form. Always make sure any page can easily be
backed out with a 'back' button if it's nested (i.e. Savings account back to
Savings back to Money but not the Project Assistant to the General
Assistant)." Two parts:
- **Part 1 — inline bottom-of-page forms → dedicated pages.** Audited every
  top-level list page for the Chores (Piece 76) / Habits (Piece 78) pattern
  — a standalone `_form.html` reached via a "＋ New X" toolbar button,
  instead of an inline card with its own anchor at the bottom of the list.
  Converted **9 forms across 7 pages**: Boards, Appointments, Wishlist,
  Contacts (External Helpers), Idea Backlog, and — the two-form page —
  Household Budget (transactions **and** budget categories separately),
  plus Loans and Savings account pages. Each conversion follows the same
  shape: a new GET route (`_new_form`/`_edit_form`) rendering the extracted
  template; the existing POST create/edit routes' validation-error
  redirects retargeted from the old `?edit=<id>#anchor` pattern on the list
  page to the new dedicated edit-form route; the list page's inline
  `<form>` block and its `#anchor` removed; empty-state and "add one below"
  text changed to link to the new page. Three stale `external_helpers_page
  (edit=...)` links elsewhere in the app (Appointments, Household Budget's
  Contact column, Wishlist) were caught and fixed the same way — that route
  no longer accepts an `edit` query param at all. Household Budget's
  `edit_txn`/`edit_budget` query-param handling was the most involved
  since those two POST routes (unlike the other 8) already carry
  `@draftable(...)` for the Assistant-role write-interception system
  (Piece 51/52) — confirmed that decorator only intercepts POST, so the
  new GET routes needed no changes there at all.
- **Deliberately excluded from Part 1, now told to the user rather than
  left as a silent gap**: the **Rules / Requirements Editor**
  (`rules.html`). Its own form already sits at the **top** of the page, not
  the bottom, so it doesn't match the literal complaint; it also carries a
  `from_job` deep-link (a job's "add a requirement" button lands here
  pre-filled) plus interlocking JS (standalone/recurring toggle, a
  recurrence-mode toggle, datalist value-suggestions) that would be
  meaningfully riskier to relocate for a page that wasn't actually the
  problem. Left as-is. **Also deliberately left inline, by design, not by
  oversight**: contextual "add a related record to this one specific
  parent" forms — a Loan/Savings account's own "add an entry," a project's
  own "add a note" (Piece 80), Work Bag's receipts/notes, Household Files'
  upload form. Only top-level "add a brand-new record" list-page forms were
  in scope; a form that's already scoped to one already-open record isn't
  the "empty form at the bottom of a list" pattern the user described.
- **Part 2 — back-links.** Audited every detail/nested page; most already
  had a correct "← Back to X" link (Loan/Savings account detail, Board/
  Backlog/Employee detail, Work Bag job/photos, project version history —
  all confirmed via grep, none touched). Gaps found and fixed: Household
  Budget, Loans, and Savings pages — reachable only via Money's own links,
  had no way back — each gained a "← Money" link; `project_form.html` had
  no back-link at all — now links to that project (editing) or the
  Dashboard (creating). Two minor drive-by fixes caught during the audit:
  Closed Jobs' back-link carried a stale `mode='Executive'` query param, a
  leftover from the pre-Piece-35 department mode-switcher removed long
  ago (harmless — `dashboard()` ignores unknown args — but stale); AI
  Settings' back-link still read "← Back to Assistant" after Piece 82
  renamed the global chat to "General Assistant."
- Verified with a new scratch test script (not committed — matching this
  session's established pattern of throwaway `test_client()`-based
  verification rather than a persisted suite) run against an **isolated
  copy** of the real household database: every new dedicated form route
  (new + edit) returns 200, a bogus edit id 404s, a real edit id from the
  actual data 200s, each list page's HTML contains its new button and no
  longer contains the old inline-form anchor, a validation-error POST
  redirects to the new dedicated edit route (not the old query-param URL),
  and the three drive-by fixes render correctly (48 checks, all passing).
  Also ran a broad smoke sweep of all 58 parameterless GET routes in the
  app against the same real-data copy — zero 5xx errors, confirming this
  piece didn't collaterally break anything elsewhere.
- No schema changes this piece — every conversion was routes + templates
  only.
- Branch `feature/ui-consistency-new-buttons`, off `main` at v0.59.

**Piece 82 (v0.59): Assistant workflow overhaul — done.** User (via
`/remote control`, which isn't available in this environment — the rest
of the message was a real request, acted on): "there's too much runaround
the site to approve drafts and continue work efficiently," plus a fully
spelled-out 3-modal flow, a request to also make Habits/Boards
chat-draftable, a request to distinguish the two Assistant surfaces by
name, and a request for manual draft editing. Two scoping questions
first: whether "view/edit manually" should cover all ~25 draft kinds or
just the chat-draftable ones (answer expanded chat-drafting itself to
also cover Habits/Boards, i.e. "anything trackable and markable done,"
while confirming edit scope stays to the chat-draftable set); whether the
Project Assistant tab's own label should change too (yes — "Project
Assistant," mirroring "General Assistant" exactly).
- **Approve-from-chat, skipping the Drafts-page trip**: "Save as X" on
  the draft panel now asks **"Do you want to approve this as a real
  X?"** (Yes / No, keep as draft) — but only for someone who could
  actually approve a draft at all (`has_permission("approvals")`); a
  Child never sees this choice, "Save as X" just sends it as Pending
  exactly like Piece 76-81 already did. **Yes** applies it for real in
  the same request via a new `_assistant_submit_draft()` helper (insert
  the draft, then immediately call the same `_approve_draft_row()` the
  Drafts page's own Approve button uses — pulled out of `approve_draft()`
  specifically so there's exactly one apply-and-mark-approved code path,
  not two that could drift). Approving a **project** this way follows up
  with a second dialog — "keep brainstorming here or work on something
  else" — routing to that project's own 🧠 Project Assistant tab
  (`/projects/<id>#plan`) or staying put; staying then offers a third
  dialog, **keep or dump the conversation** (a new
  `/assistant/conversations/<id>/delete` route). Built as a single
  reusable native `<dialog>` element repopulated per question (resolves a
  Promise per click) rather than three different popups — this app had no
  existing custom-modal pattern to follow, native `<dialog>` gives a
  focus-trapped, backdrop-dimmed prompt for free with custom button
  labels, which `confirm()` can't do.
- **Habits and Boards added to the chat-draftable set** (now six: project/
  appointment/chore/wishlist/habit/board), via the exact same
  `NEW_X:`-line + DRAFT_KINDS-entry + `/assistant/draft-X` pattern Piece
  81 established — `_apply_new_habit`/`_apply_new_board` mirror the
  existing four exactly. A chat-drafted habit from a Child defaults to
  assigned-to-themselves, matching Piece 81's own Habit-form Child-lock
  (checked directly rather than assumed).
- **Manual draft editing**, scoped to those same six kinds per the user's
  own answer — a new `/drafts/<id>/edit` page (`draft_edit.html`, one
  template with a conditional field block per kind) lets a Pending
  draft's payload be corrected by hand — fix a typo, adjust a date —
  without discarding it and re-asking the assistant. Deliberately a
  smaller field set than each kind's real New/Edit form (e.g. a project
  draft's edit form skips `estimated_cost` — chat-drafted projects never
  set it anyway); every other existing draft kind (budget entries, loans,
  rules, inventory, etc.) keeps today's summary-only view, per the user's
  explicit scoping answer, not a generic edit-everything system.
- **General Assistant vs. Project Assistant naming**: the global chat's
  nav link, page `<h1>`/title, and every current-state README mention
  renamed from bare "Assistant" to "General Assistant"; the per-project
  chat's tab button and heading renamed from "Plan" to "Project
  Assistant" (confirmed via AskUserQuestion — the internal route/
  function/anchor names (`plan`, `project_plan_ask`, etc.) are untouched,
  matching this app's established "internal name stays, label changes"
  convention, e.g. Chores staying `routine_tasks`).
- **A real latent bug caught and fixed while wiring the habit/board apply
  functions in**: none this time beyond what Piece 81 already fixed — the
  `is_recommendation` tuple fix from that piece already covers the new
  kinds correctly (`habit.new`/`board.new` don't start with `"wishlist."`
  or `"submission."`, so they were never at risk).
- **Environment note, not a code issue**: the Browser pane's click
  automation was too unreliable to interactively exercise the 3-modal
  chain live (a recurring limitation this whole session, documented
  earlier) — verified via a thorough manual code review of the JS instead
  (each state transition, the `conversationId` guard, the `approve_now`
  gating) plus full route-level coverage of every underlying endpoint the
  modals call. This piece's interactive click-path itself is the one part
  of this session's work that rests on code review rather than an
  executed test — worth a real human click-through the next time someone
  is at a keyboard with this app open.
- Verified via a new `piece82_assistant_workflow_test.py` (11 checks:
  relabeling on both surfaces, the two new chat-draftable kinds, the
  immediate-approve path for an approver, confirmation that a Child's
  `approve_now=1` is silently ignored server-side and the record does
  NOT get created, a Child's chat-drafted habit self-assigning, manual
  draft edit + its own blank-title validation + that approving an edited
  draft uses the edited values not the original, a non-chat-draftable
  kind correctly refusing the edit page, and conversation delete
  including that you can't delete someone else's). Full accumulated
  regression suite from Pieces 79-82 (9 scripts) re-run clean before
  shipping. No schema changes this piece.
- **Piece-numbering note, same as Pieces 79-80**: the two newest test
  scripts are correctly named `piece82_assistant_workflow_test.py`, but
  an EARLIER Piece 79 sub-feature test also happens to be named
  `piece82_child_nav_lockdown_test.py` (a leftover provisional number
  from before that whole round shipped as Piece 79) — two genuinely
  different, unrelated test files both starting with "piece82" is a
  real, if harmless, naming collision worth knowing about if either ever
  needs to be found by filename alone.
- Merged `feature/assistant-workflow-overhaul` → `main` → fast-forwarded
  `deploy/production-hosting-security` to match; deployed to the live
  VPS and confirmed there too.

**NOT done yet:**
- **Mobile search bar reported missing, not reproduced.** User: "On
  mobile the search bar disappeared." Investigated directly: re-read
  every base.html/inventory.html diff since it was last confirmed
  working (Piece 79's screenshot round) — nothing touches the nav search
  bar or its CSS. Reproduced the exact live code on a mobile-emulated
  (375×812) local dev server against a real-data copy and confirmed the
  search bar renders and opens correctly inside the hamburger menu. Also
  ruled out a stale service-worker cache as the cause — `service_worker.
  js` is **network-first** (always fetches fresh online, only falls back
  to cache when offline), so a stale cached page can't explain a
  persistently missing element for someone who's online. Genuinely
  couldn't reproduce this from the code — next step is a screenshot from
  the user's actual phone (which page, hamburger open or closed, logged
  in or not) before guessing further.
- **STT/TTS for the Assistant: answered as a feasibility question, not
  built.** User: "if we can figure out STT and TTS communication that
  would also be a bonus" (both on Pixel 9a / GrapheneOS). **TTS** is
  low-risk — the standard `SpeechSynthesis` Web API uses whatever TTS
  engine is installed on-device, no Google Play Services required; a
  "🔊 read aloud" button on an assistant reply would be a small, safe
  addition whenever it's wanted. **STT is a real open question**: the
  `SpeechRecognition` Web API on Chromium-based browsers (including
  Vanadium, GrapheneOS's default) has traditionally routed through
  Google's cloud speech backend, which GrapheneOS deliberately omits by
  default (no Google Play Services unless the user sandboxes it in
  themselves) — this may simply not work on their exact phones without
  the user first choosing to install that layer, and needs testing on
  the actual hardware before committing to build anything, not assumed
  to just work because it's "a standard Web API."
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
- **Assistant-role account UI review — not started.** User's original
  request (start of Piece 76): "beginning with the Parent Dashboard...
  after a complete run through of the parent UI, we'll verify the Child
  and Assistant UIs respectively." The Parent round (Piece 76) and the
  Child round (Piece 79, above) are both done. **Piece 79 improved the AI
  Assistant chat feature itself** (parent-safety notifications, the
  persistent draft panel) but that's a different thing from reviewing
  what an **Assistant-role household member's own account** looks like —
  logging in as one (Gremory, the real household's Assistant-role
  account) and screenshot-reviewing their dashboard/nav/gated-tab
  experience has not happened yet. Expect this to surface its own
  findings distinct from both the Parent and Child rounds, given
  Assistant's fairly narrow permission bundle (`rules.manage`/
  `inventory.manage`/`approvals`/`projects.manage`, see Piece 51) and the
  drafts-based write-interception layer that role uniquely goes through.
- **Budget reporting — 2 more items still open.** Piece 55 built the pie
  chart, cash-flow projection, and both trend charts the user asked for by
  name; the user's own "among others" phrasing implied more might be
  wanted — nothing further has been specified. Ask before assuming what's
  still missing.
- **Pixel 9a beta-test readiness** — 2 of the 3 original blockers are
  done now (Piece 56: LAN reachability, `COMPENDIUM_HOST=0.0.0.0`; Piece
  75: the mobile-responsive UI audit, see above). Still open: a real-data
  readiness check on `job_creator.db` itself before starting an actual
  project in it. Note: this app already has some PWA/offline infrastructure
  (`/sw.js`, `/offline`, Work Bag's offline support since Piece 26) —
  check what already works there before assuming more offline support
  needs building from scratch. **Also still open**: Jacob (household
  roster, no login credentials yet) needs a username + password set
  before he can actually sign in and beta-test — an admin (household.manage)
  sets this via Family → his profile → edit; not something to set on his
  behalf without him choosing the password directly.
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
- **Home-screen widgets — scoped, not started, no path chosen yet
  (2026-08-30).** User wants productivity widgets on the household's
  phone home screens. Confirmed: **all-Android** household, so a
  sideloaded APK (no Play Store) is acceptable — matters since the Pixel
  9a runs GrapheneOS with no Google Play Services by default. A **real,
  always-visible home-screen tile is an explicit long-term/stretch
  goal**, not the immediate ask. Two approaches compared:
  - **PWA tier** (small, days of work, no new tech stack): add a proper
    Web App Manifest — none exists today, so "Add to Home Screen"
    currently just makes a browser bookmark, not a real standalone-app
    icon — plus Android's manifest `shortcuts` array (long-press menu →
    jump straight to "mark a chore done," "add appointment," etc.) plus
    Web Push notifications wired to the existing notifications inbox.
    Gets an installable icon, quick-action shortcuts, and proactive
    nudges — but nothing glanceable shows without at least a tap.
  - **Native widget app** (large, a genuinely separate Kotlin/Android
    Studio project, realistically weeks): the only way to get an actual
    always-on home-screen tile. Requires building a real authenticated
    JSON API in `app.py` first (today it's server-rendered HTML over
    session cookies, nothing a native client can poll) — that API work
    is needed regardless of which native-app approach is chosen. No
    Play Store auto-update since it's sideloaded — every widget-app
    change means manually rebuilding and reinstalling the APK on each
    phone. A real second codebase to maintain going forward.
  - **Not mutually exclusive**: the PWA tier is worth having either way
    (better full-screen phone experience on its own), and a future
    widget app would sit on top of the same JSON API rather than
    replace the PWA work. Realistic sequencing, if/when picked up: PWA
    tier first, native widget later as its own scoped project. **No
    decision made yet on when/whether to start either** — this is
    purely a saved note, not a commitment to build.

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