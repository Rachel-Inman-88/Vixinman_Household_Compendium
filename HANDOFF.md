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

**NOT done yet:**
- **Visual theme.** `templates/base.html` still uses the original green
  (`--brand: #1a6e3c`, `--brand-dark: #12522c`). The target aesthetic is
  **parchment / illuminated-manuscript**: natural paper-fiber background, ornate
  borders, accent colors in blue, green, red, gold/brass, and black ("burnt wood"). This
  is real visual design work (textures, border art, probably a different typeface), not
  a CSS-variable swap — treat as its own phase, explicitly deferred by the user until
  **after every feature/file/database reorg piece is done**, not incrementally per
  piece.
- **A manual browser click-through** — verification so far is automated
  (Flask test-client route sweeps + POST flows); no one has clicked through
  the new household-member/dashboard/access/inventory/requirements/
  Project-form UI in a real browser yet.

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