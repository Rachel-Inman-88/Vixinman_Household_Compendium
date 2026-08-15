# 🧰 Compendium — Project Handoff (historical — see root HANDOFF.md for current status)

**Repo:** `rain-solar/job-creator-app` (private, proprietary — see LICENSE)
**For:** Vixinman Designs (Rachel, redfox.inman@gmail.com) — solar installer, statewide New Mexico
**Current build:** **v0.3** (footer shows it plainly as "Version 0.3" — the "did my pull work?" check).
This file predates the household reorg (was last updated at Piece 28.5) and everything
below still describes the app in its old solar-business shape (clients, jobs) — it's kept
as historical build-log detail, not current status. For what the app is now and what's
been done in the household reorg (client removal, jobs→projects, pipeline stages), see the
root-level `HANDOFF.md`.

**Piece 28.5 — Stock Audit (scan-and-reconcile).** New **🧮 Audit stock** button in the
Inventory toolbar (`inventory.manage`). An audit session scans the physical Code-128 tags
(camera-continuous via BarcodeDetector, or keyboard-wedge/manual) and reconciles the
scanned serials against the **registered assets** (`inventory_assets`) the DB expects
**In stock**, optionally scoped to one **category/type**. New tables `stock_audits` +
`stock_audit_scans` (schema.sql). Routes: `inventory_audit` (hub — start + history),
`inventory_audit_start`, `inventory_audit_session` (AJAX `.../scan` logs each scan and
returns its live flag + progress), `.../scan/<id>/delete`, `.../finish`, `.../report`,
`.../report.csv`. `audit_report()` classifies: **accounted**, **unaccounted** (expected
In-stock not scanned), **unexpected** (scanned but Out/Retired or out of scope),
**unknown** tags (serial doesn't resolve), **duplicates**. An asset's audit category comes
from `_assets_with_category` (component category, else "Tools"/"Vehicles"). The report page
shows summary tiles + per-discrepancy tables and an **Export CSV**. Verified end-to-end
(full + category-scoped audits: exact accounted/unaccounted/unexpected/unknown/duplicate
counts; CSV; finish closes) + screenshots. README + build history updated.

**Piece 28.4 — Two search bars: nav (clients & jobs) + inventory.**
(1) **Nav search** in the header (shown when logged in / open mode): an autocomplete over
**client + job NAMES only** backed by `/api/quick-search` (`{results:[{type,label,sub,url}]}`).
The dropdown lists clients (🗂) and jobs (📋); **every job result shows its client name**
beneath. Click a suggestion → its client/job page; Enter with none highlighted →
the existing `/search?q=` results page; arrow keys navigate the menu. Styled in base.html
(`.navsearch*`); the job query also matches the client name so typing a client surfaces
their jobs. (2) **Inventory search** on `/inventory`, placed **under the explanation, above
the collapsible tables**: a client-side filter over **every** item (products, tools,
vehicles) matching each row's full text (make/model/description/vendor/specs). Matching
sections auto-open, empty ones hide, a live "N items match" hint shows, and clearing
restores the default (first section open). Verified end-to-end (API returns client+job
with client names; nav dropdown + navigation; inventory filter + auto-open + count) +
screenshots.

**Piece 28.3 — Job Detail button/stage reorg.** Reorganized the header controls. The
job-**stage dropdown** moved out of the button row into the **Pipeline stage** panel: it
now shows as plain text (`Pipeline stage · <status>`) with an **✎** that reveals the
`set_job_status` dropdown in place (a `stage_editor()` Jinja macro with self-contained
inline JS; an `{% else %}` fallback card keeps the stage editable on Complete/Lost jobs
where the panel is hidden). The button row is now left-aligned **📅 Calendar → Process
chart → ✎ Edit job**, with **← Client profile** pushed to the far right
(`margin-left:auto`). Verified (no select in the button row; stage text+pencil toggles the
dropdown; Complete job keeps an editable stage line) + screenshots.

**Piece 28.2 — Job Detail: bold L/P/C item labels + Billing file upload.**
(1) In the job's **L/P/C tab**, the requirement **label is now bold** (`<strong>`) in all
three groups (Permits, Technician Licenses, Compliance Notes) so the item stands out from
the muted free-text note and the hyperlink. (2) The **Billing** transaction form gained an
optional **Attach file** input (`multipart/form-data`, `accept="image/*,application/pdf"`,
no forced camera so it's a device file-picker on mobile + desktop). `add_transaction` saves
the upload (photo/PDF), auto-renames it (`friendly_filename`, tagged with the doc type or
"Billing"), and files it against the transaction via `job_files.txn_id` — so the existing
📎 link in the ledger (`job_billing` LEFT JOINs `txn_id`) surfaces it and it lands on the
job's document record. Bad file types are skipped with a warning; the transaction still
records. Verified (bold labels; upload attaches + 📎 shows; bad type skipped).

**Piece 28.1 — README brought current (Pieces 22–28).** Docs-only. The README's
"Features & capabilities" was frozen at Piece 21; updated every section to reflect
everything since — the inventory database + stock ledger/stale-stock + barcode/asset
registry, Rules Editor / L/P/C Directory (consolidation + verbatim source text) and the
Calculator Catalog rename, Loads survey tweaks + component auto-suggest + colour-coded
eras, the Work Bag redesign (jobs landing → per-job page, Submit-as-done with time by
pay type + timeline, photo steps on their own screen), field receipts / grouped task
board / offline service worker / background scheduler, 12-hour auto-logout, 50/40/10
invoice generation + NM GRT + remit-to + pay-scheme callouts, Sun→Sat pay periods,
per-job QuickBooks exports, payroll reminder + leave-can't-earn-OT, timesheets, and
in-place editing / auto-renamed uploads. Added Build-history bands for Pieces 22–28.

**Piece 28.0 — Photo steps complete on their own screen.** Any task `_is_photo_step`
(site visit/installation, install walkthrough, meter set, doc tube, re-inspect, or any
"photo"/"picture" step) no longer shows the inline time form on the per-job Work Bag
page — instead a prominent **📷 Take, review & submit photos →** button (with thumbnails)
opens the dedicated photo screen (`work_bag_photos.html`, now a 3-step layout: **1 Take/
upload → 2 Review → 3 Submit & mark done**). Step 3 carries a Notes field, work date, the
same **time-by-pay-type segments + timeline**, and **✓ Submit & mark done** / **⚠ Can't
finish**. Submitting posts to the new **`complete_photo_task`** route, which requires at
least one photo on file for a "done", creates the field submission (Done/Blocked + segments
via the shared `_validated_segments` helper), and **redirects back to the job's Work Bag
page** — where the task shows "submitted — awaiting approval" and, once the supervisor
approves, flips to Done and posts Pending payroll by pay type (same two-sign-off flow as
27.9). Verified end-to-end (done-needs-a-photo guard, photo upload, done-with-time,
blocked-needs-a-note, approval → 2 Pending payroll entries) + headless shots of both screens.

**Piece 27.9 — Per-task "Submit as done" with time by pay type (merged tasks + submit).**
On the per-job Work Bag page each field task lost the status dropdown + global "submit
completed work" card; instead every task has its own **✓ Submit as done** (and **⚠ Can't
finish** → Blocked, note required). Submitting captures the **time it took split by pay
type** — one or more `[pay type][hours]` segments (＋ Add time type), shown live on a
**colour-coded proportional timeline** with a legend/total. Flow (two sign-offs, per the
decision): the crew submit → a `field_submission` whose items now carry `hours_json`
(segments) + `work_date` → **supervisor approves** (`approve_submission`) which marks the
task Done AND posts one **Pending** `time_entries` row per segment (by pay type, for the
job/date) → **Finance approves** those on the payroll page. `api_work_bag_submit` validates
segments against active pay types and stores them; the submissions review page shows the
per-task pay-type breakdown. Offline model intact (localStorage queue keyed by task, with
segments; flushes on reconnect / "Submit now"). Section 5 kept but relabeled **"Log other
hours"** for time not tied to a task. New columns: `field_submission_items.hours_json,
work_date`. Verified end-to-end (submit 8+1+2 h → approve → 3 Pending payroll entries;
blocked path; + a headless run of the segment UI + timeline). *(Blocked kept per the
decision; per-task time = the payroll hours.)*

**Piece 27.8 — Removed Load truck from the Work Bag landing.** The 🚚 Load truck button
is gone from the landing toolbar (loading out is per-job — the packing list is always
different by job). It stays on the per-job page (`work_bag_job`), where it will be wired
to the specific job when that screen is refined.

**Piece 27.7 — Work Bag split into a jobs landing + per-job page (part 1).** The Work
Bag landing (`/work-bag`) now shows **only the jobs** in the worker's bag — one tappable
card each (job name, client, install date, open-task count, unsubmitted badge), rendered
client-side from the same cached `/api/my-tasks` data so it still works offline. Tapping a
card opens the new **`/work-bag/job/<id>`** page (`work_bag_job`), which holds the rest —
that job's field tasks + packing list, submit-for-approval, log-hours, add-receipt, and
job-notes — all scoped to the job (hidden `job_id`, no job pickers; recent lists filtered
to the job). The capture routes (`log_my_hours`, `add_receipt`, `add_job_note`, and the two
deletes) now redirect back to the per-job page via `_workbag_redirect()`. Submit only sends
the queued changes for the current job (shared localStorage queue, filtered by `JOB_ID`).
Verified with the test client (routes render, redirects) + a headless run (landing shows 2
job cards and no task list; clicking opens the per-job page with its tasks). **NOTE:** the
user will refine this per-job screen next.

**Piece 27.6 — Dropped the email from the customer invoice.** Removed the old
company-domain personal email from both the invoice header remit-to block and
the footer remit line (the personal email shouldn't go out on customer
copies). Address + phone still print;
`COMPANY_INFO["email"]` is left in place (unused on the invoice now).

**Piece 27.5 — Vixinman remit-to details on invoices.** Filled in `COMPANY_INFO` with
Vixinman's real address (1212 Railroad Ave, Las Vegas, NM 87701) and phone
((505) 454-0614), so the customer invoice header now prints the full remit-to block
(name, address, city/state/zip, phone, email) instead of name + email only.

**Piece 27.4 — NM gross-receipts-tax line on customer invoices.** Each customer
invoice now carries a GRT line. The rate is **per job** (`jobs.grt_rate`, set beside
the contract total on the Billing tab) because it varies by install location, and it
**defaults to 0%** — Vixinman's solar systems are GRT-deductible, per their own "GRT
Exemption on Invoice" rule. At generation the invoice snapshots `grt_rate` +
`grt_amount` (= rate × the invoice subtotal) on the `job_transactions` row; the
transaction `amount` stays the **pre-tax** subtotal so the internal contract/rollup
math is unchanged (GRT is a pass-through, not revenue). The printable customer copy
shows **Subtotal → NM Gross Receipts Tax (rate%) → Amount due**; when the rate is 0 it
prints "Solar deduction applied — {{ GRT_EXEMPTION_CITE }}" (`NMSA 7-9-112 / 3.2.247
NMAC`) so every invoice carries the citation Vixinman's compliance rule requires. Rates
render to 4 decimals (NM rates like 7.9375%). Verified both paths: 7.9375% on a
$12,000 deposit → $952.50 tax / $12,952.50 due, and the 0% exemption line with the
NMSA citation (+ screenshot). *(GRT is not yet broken out as its own QuickBooks export
column — the invoice shows/records it; revisit if the books need a separate tax line.)*

**Piece 27.3 — 50/40/10 invoice generation + pay-scheme callouts.** Generate
customer invoices from a job's contract + BOM (Path A — self-contained, no QB needed).
- **Model** (`INVOICE_MILESTONES`, `projected_invoice`): **Deposit = 50%** of contract
  (collected at signing; generating it snapshots `jobs.deposit_bom_cutoff_id` = current
  max `job_bom.id`). **Progress = 40% of contract + 80% of post-deposit BOM extras**
  (`_post_deposit_bom_total` = Σ qty×unit_cost of BOM rows with id > cutoff). **Final =
  a true-up** so total billed = contract + all post-deposit BOM (= 10% + remaining 20%
  of extras). Sequential, guarded order; global invoice numbers `INV-00001…` via
  `meta.invoice_seq`.
- **Storage**: each generated invoice is an `Income`/`Invoice` `job_transactions` row
  (so it flows into the existing billing rollup + mark-paid + QB export), with new
  columns `invoice_number, milestone, due_date, contract_snapshot, base_amount,
  extras_amount, bom_snapshot`.
- **Customer copy** (`view_invoice` → standalone printable `invoice.html`): Vixinman remit-to
  (`COMPANY_INFO`), bill-to, the 50/40/10 schedule, amount-due box, and the BOM as a
  plain **equipment list with NO per-item pricing**; the itemized expenses stay on the
  internal Billing tab. Route `/jobs/<id>/invoice/generate` + `/jobs/<id>/invoice/<txn_id>`.
- **Billing tab**: a "🧾 Customer invoices · 50/40/10" card with per-milestone state and
  a Generate button for the next one.
- **Pay-scheme callouts** (`PAYMENT_SCHEME_NOTE`): a plain-language 50/40/10 callout on
  the **Sales and Finance** dashboards, on the Billing tab, and on the invoice itself, so
  everyone communicates it to customers the same way.
- **NOTE**: fill in `COMPANY_INFO` (Vixinman address/phone) — the invoice remit-to currently
  shows name + email only. Verified end-to-end (exact amounts 12000/11600/2900 on a
  24000 contract + 2500 extras; true-up; no price leak; callouts) + a screenshot.

**Piece 27.2 — Pay periods run Sunday→Saturday; QuickBooks exports moved to Billing.**
(1) **Pay period fix.** `_pay_period()` used to default to a rolling *last-14-days*
window (not week-aligned). It now returns the most recent full **Sunday→Saturday
week** — the one ending on the latest Saturday (today included when today is a
Saturday), still overridable via `?start/?end`. This is a **weekly** period (7 days),
matching the weekly Tue–Thu payroll cadence; it drives payroll, the timesheet, the
QuickBooks payroll export, and the Finance payroll reminder. *(If Vixinman actually pays
biweekly, this is the one knob to revisit — make the window 14 days back from the
Saturday.)*
(2) **QuickBooks exports relocated.** Removed the four export buttons (⬇ All CSV ·
Receipts · Invoices · Bills) from the Finance dashboard's Payments card (replaced
with a one-line pointer) and put them on each job's **💵 Billing tab**. `quickbooks_export`
gained an optional `?job=<id>` scope (still company-wide with no job param), so the
Billing-tab buttons export **that job's** transactions (filename `…_job<id>…`); the
`?doc=` type filter still stacks on top. Verified: `_pay_period` is Sun→Sat/7-day
for every weekday, the dashboard buttons are gone, the Billing tab has all four, and
a job-scoped export returns only that job's rows (+ screenshot).

**Piece 27.1 — Removed the sample client/job seed (clean production data).**
Deleted the `if clients == 0:` demo-seed block in `init_db` that created three
sample clients, three sample jobs, five sample tasks, and two sample employees
("Daniel Ortiz (sample)" / "Maria Sandoval (sample)") + their credentials. A fresh
database now starts with **no clients, jobs, or tasks** — only the reference
databases seed: the real staff roster (`seed_org_team` — Cary, Will, Rachel, Louie,
Trish, Si, Lisa, Vanessa, Brady), inventory (439 items / 49 tools / 11 vehicles / 52
vendors), the Calculator Catalog (379 appliances / 62 components), the 145 resource
rules, and the 5 pay types. **Scope note:** this only affects *new* databases — an
already-seeded install keeps whatever data it has (the old guard was `clients == 0`,
now the block is simply gone), which is exactly right for shipping a clean packaged
exe. Verified a fresh DB: all client/job/task/sample-employee tables at 0, every
reference table intact, and all key pages (home, dashboards, tasks, inventory,
catalog, rules, directory, payroll, employees) render 200 with no clients/jobs.

**Piece 27.0 — Calculator Catalog rename.** Renamed the load-calculator's
"Appliance & component catalog" to **"Calculator Catalog"** — the page `<title>`,
the H1 (now "🔌 Calculator Catalog"), and the Databases nav entry. Route
(`/catalog`, `catalog_page`), tables (`appliance_catalog` / `component_catalog`),
and behavior are unchanged; purely a display rename.

**Piece 26.9 — L/P/C Directory consolidation + verbatim source text; renames.**
Four changes to the two rule pages.
(1) **Consolidated the Directory**: `consolidate_rules(rules)` collapses every rule
sharing a `(category, label)` into ONE entry, listing each triggering **scenario as
a bullet** beneath it (with that scenario's own note) — so e.g. "EE-98 Contractor
License" shows once with its scenarios, not a fresh listing per scenario. The entry
carries a representative source (first non-empty url/link/phone) and escalated verify
flag (unverified > verify). The count now reads "N requirements".
(2) **Verbatim source text**: new `resource_rules.source_text` column (+ a "Verbatim
source text" textarea in the Rules Editor, saved by add/update_rule). In the
Directory each entry renders, top-to-bottom: **verbatim quote** (when present, esp.
compliance) → **shorthand label + source hyperlink/phone** → **scenario bullets**.
Existing rules have no verbatim yet — it's entered per rule in the editor; the block
is simply omitted when empty.
(3) **Renamed** the Directory "Rule Directory" → **"L/P/C Directory"** (title, H1,
nav) — Licenses/Permits/Compliance.
(4) **Renamed** the editor "Requirement & Resource Rules" → **"Rules Editor"**
(title, H1, nav). Reciprocal cross-links updated to the new names. Verified via test
client (verbatim saves + renders, EE-98 appears once with its scenario bullets,
renames present) + a screenshot.

**Piece 26.8 — Cary defaults to Executive; Rules/Directory tidy-up.**
(1) **Cary's default dashboard is now the Executive overview** (was Design). The
org seed sets `dashboard_mode='Executive'`, and a one-time meta-guarded migration
(`cary_exec_default`) flips existing installs — but only from the old seeded
`Design`/blank, so a default Cary has since chosen himself is left alone.
(2) **Rules vs Directory — confirmed not redundant, cleaned up.** They're two views
of the same `resource_rules` table with distinct jobs: **`/rules`** is the *editor*
(admin add/edit/delete), **`/directory`** is the *read-only* lookup filtered by job
type with the ⚠ verify/unverified flags. Data has **zero duplicate rules** (145
rows, no exact dupes). Changes: the Rules editor's flat "Current rules" table is now
**grouped by category** (reusing `group_rules(dedupe=False)`, same headings as the
Directory) with a readable "when the job … includes X" column and the same ⚠ verify
chips; both pages gained **reciprocal cross-links** ("Browse in the Directory →" /
"Edit in Rules →") and clarified intros so the edit-vs-browse split is obvious.
Verified via test client (both render, cross-links present, category headings) + a
duplicate-rule query + screenshots.

**Piece 26.7 — Payroll reminder, leave-can't-earn-OT rule, grouped My Tasks.**
Three dashboard/payroll changes.
(1) **Payroll reminder** on the Finance viewport (for whoever runs payroll, e.g.
Vanessa): a collapsible "💵 Payroll" card **above My Tasks**, showing a **Tue–Thu**
cadence (chips with today highlighted) and a two-step checklist — **1 Confirm hours**
(no time entries left `Pending` in the period) and **2 Export to QuickBooks**. It
nags (opens + amber) Tue/Wed/Thu until both are done, then collapses green ("up to
date"). Driven by `payroll_status(db, start, end)`; the QuickBooks export now stamps
`meta['payroll_exported:<start>..<end>']`, and the export only counts as current if
its timestamp is ≥ the newest approval in the period (approving more hours re-opens
"Export"). Card only renders for `"Finance" in shown and _can_payroll()`.
(2) **Leave can't earn overtime.** New `pay_types.is_leave` flag (seeded on
PTO/Vacation/Sick via a `pay_leave_seeded` meta guard; editable in Pay settings as a
"Leave" column). At approval (`approve_time_entry`), approving a **leave** entry that
would push the employee's already-approved hours **for that ISO week past the OT
threshold (40 h)** is **blocked** with a message showing how much leave fits —
**unless a GM ticks a per-row "GM override"** (only shown to `is_gm` on leave rows,
and only honoured when `is_gm()`). Worked hours are untouched (they still earn OT);
leave under the cap approves normally.
(3) **My Tasks grouped by job** on the dashboard: the flat table is now a **banner
per job** (job name + client + task count) with its tasks as **bullet points**
beneath (title, pipeline badge, due/overdue, status). Built in the route as
`task_groups` (first-seen order preserves the overdue/soonest-due job on top).
Verified end-to-end via the test client (reminder states, the 40 h leave block +
GM override + leave-under-cap pass-through, and the grouped banners) plus a headless
screenshot of the Finance dashboard.

**Piece 26.6 — Colour-coded appliance-era tags.** The Modern/Vintage distinction
had faded to plain "(Modern)/(Vintage)" text in the 26.4 picker's option labels.
Now the load-survey appliance picker shows a bold **colour-coded era badge** beside
the selected appliance — **green = Modern, orange = Vintage** (`.era-tag` /
`.era-modern` / `.era-vintage` in job_loads.html's local `<style>`). A JS
`updateEra()` reads the selected option's appliance era and swaps the badge text +
class on every `change` and after each `fill()`; option text is also tinted the
same green/orange where the browser honours per-`<option>` colour (Firefox / some
Chrome). The "(Modern)/(Vintage)" suffix stays in the option text as the native-
dropdown fallback. Verified with a headless Chromium test: selecting a Modern
appliance shows the green badge, switching to a Vintage one flips it to orange
(background colour confirmed to change).

**Piece 26.5 — Component auto-suggest from inventory specs.** Once a load
survey has produced sizing figures, the Loads page reads the specs on **Active**
`inventory_items` and proposes the components that fit the job. `suggest_components(db,
array_kw, peak_w, battery_kwh_needed)` builds three roles — **PV modules** (fit by
nameplate `Rating` W → panel count for the array kW), **Batteries** (fit by
`Capacity` kWh → units for the backup bank), and the **Inverter** (smallest unit
whose `Pout Rated (kW)` still carries the peak). Each role ranks its candidates by
the tidiest fit (fewest panels/units, or least-oversized inverter), with in-stock
(`available > 0`) as the tie-breaker and cost last, then returns the top three: a
primary **Recommended** pick plus up to two **Alternate** 2nd/3rd choices, each
with the sized quantity, cost, and a short "why". Only computed in **Designer
mode** and only when a survey exists (`ui_mode == "designer" and load_items`). The
job_loads route passes `suggestions`; job_loads.html renders a green "✨ Suggested
components" panel above the BOM with a one-click **✓ Accept** button per card. Accept
posts to `accept_suggested_component` (`/jobs/<id>/loads/bom/suggest`, guarded by
`loads_unlocked`), which drops the item into `job_bom` at the sized qty/inventory
cost (`component_id` NULL, note "Suggested from inventory"); re-accepting the same
item **sets** its qty rather than duplicating the row. Helpers `_spec_num()` (first
numeric among spec keys) and `_rank_role()` (sort + label top three) sit by
`compute_voc`. Verified end-to-end via the test client (Designer login → panel
renders → recommended pick is a sensible 12×710 W ≈ 8.5 kW array → accept inserts
the BOM line → re-accept dedupes).

**Piece 26.4 — Loads & Sizing survey tweaks.** Four changes to the load-survey
page. (1) **Removed** the BPMN "Process chart" button from the page toolbar.
(2) The **Sales/Designer view mode is now a per-viewer default** from their
department (`loads_view_mode`): Design → Designer, Sales → Sales (Design wins for
someone in both, e.g. Cary); the toggle is now a per-session preference
(`session["loads_ui_mode"]`) instead of a per-job stored value, so two people
viewing the same job see their own default. (3) **Room-aware appliance picker**:
rooms gain a `category` ("type" like Kitchen/Garage from the appliance-catalog
categories, set on the add/edit room form); the load-item picker defaults to that
room's appliances, with a **search box that filters the whole catalog** (e.g. a
keyboard kept in the kitchen) — driven client-side from a `tojson` of the catalog.
(4) **Custom fields hide behind a "Custom appliance" toggle** — checking it swaps
the catalog picker for free-text name/watts/usage (and disables the inactive
side so only one submits). Verified end-to-end incl. a browser test of the
picker (Kitchen shows 35 items, "keyboard" search finds the whole-catalog match,
custom toggle reveals the fields).

**Piece 26.3 — Task board grouped by job.** The cross-job task board was a flat
list; it now **groups tasks under each job** (a collapsible card per job with the
job name + client + open count, and a red border + overdue badge when a job has
overdue work). Group order surfaces urgency: jobs with overdue tasks first, then
by soonest open due date, then name; within a group tasks keep the open-first /
soonest-due order. The redundant per-row "Job" column is gone; the summary now
reads "N tasks across M jobs". Filters (Who / Open-vs-all) and the status
dropdowns are unchanged. Route builds the groups; `tasks.html` renders them.

**Piece 26.2 — Work Bag receipt capture.** A new **🧾 Add a receipt** card on the
Work Bag lets the crew photograph a receipt (`capture="environment"` opens the
phone camera) and log **date, total, vendor, reference #, and expense category**
(`RECEIPT_CATEGORIES` = Materials / Meals / Tools and Supplies / Overhead). One
submit (`/work-bag/receipt`) does two things: records a **paid Expense with
doc_type='Receipt'** on the job's ledger (so it flows into Finance/bookkeeping and
the QuickBooks export unchanged) and files the photo as a `job_file`
(auto-renamed `Client_Job_Receipt_Vendor_Date`, tagged "Receipt", linked to the
txn via a new `job_files.txn_id`). The Work Bag lists the crew's recent receipts
with a 📎 view link, and the job's **Billing tab** shows a 📎 next to each
transaction that has a filed receipt. Validates a required photo (image/PDF) +
total. Verified end-to-end.

**Piece 26.1 — phone-camera scanning + crew truck-loading + tighter tag perms.**
Three parts. (1) **Camera scanning**: the scan page and a new **Load-a-truck**
page (`/inventory/load`) scan with the phone camera via the browser-native
`BarcodeDetector` API (Code 128) — feature-detected, with a graceful fallback to
the manual/USB-scanner box where unsupported. NB: needs a supporting browser
(Chrome/Android; not iOS Safari — no CDN access here to vendor a JS decoder) and
the app served over **HTTPS** (camera = secure-context only); USB/Bluetooth
wedge scanners work everywhere as the fallback. (2) **Crew loading**: `/inventory/load`
picks a job once, then continuously scans tags out to it via a JSON endpoint
`/api/inventory/scan-out` (consumable → 'used' stock move; non-consumable → Out),
so **two Installers can load the same job in parallel from their own phones** —
every scan is an independent request. Both `/inventory/load`, `/inventory/scan`,
and the check-out/in routes are **open to any signed-in worker** (no permission).
(3) **Tag permissions**: new **`inventory.register`** permission (registering &
printing tags + retiring) defaults to the **Inventory Manager** role — the
warehouse manager — and the GM can grant it to whoever fills that role via
`/access`; the register form hides for everyone else. Verified end-to-end
(warehouse-mgr-only register, installer-open scan/load, parallel scan-out,
consumable decrement, auth 401).

**Piece 26.0 — barcode / asset registry (generate, print, scan).** New
`inventory_assets` table + a dependency-free **Code 128-B** SVG encoder
(`barcodes.py`, validated byte-for-byte against `python-barcode`; ships stdlib-
only so it works offline). Each asset is a printed, scannable label with a
unique serial (`VXM-000123`) tied to an inventory entity. **Register from
scratch** on `/inventory/assets` (pick a component/tool/vehicle; non-consumables
mint one tag per physical unit, a consumable gets one SKU label), which redirects
to a **print sheet** (`/inventory/assets/labels`) of barcodes. **Scan**
(`/inventory/scan`) is keyboard-wedge friendly (scanner types serial + Enter →
auto-submit): a **consumable** scan-out records a `used` stock movement through
the Piece 24.4 ledger (qty + optional job); a **non-consumable** toggles In
stock ↔ Out (with the job it's out on), plus **Retire**. Helpers:
`register_asset`, `_resolve_serial`, `_asset_entity_label`. All routes gated by
`inventory.manage`; links (📷 Scan / 🏷 Barcodes) added to the Inventory header.
Verified end-to-end incl. a real-browser screenshot of printed labels + scan.
**This closes the last deferred inventory item.**

**Piece 25.4 — auto-rename uploads for recordkeeping.** Every uploaded file is
renamed on upload to a consistent, self-describing **Name_What_Date** scheme so
records read cleanly and nobody hand-renames: job docs →
`Client_Job_Slot_YYYY-MM-DD.ext`, client files → `Client_Category_Date`,
employee files → `Employee_Credential_Date`, field photos → `Client_Job_Task_Date`
(a `-2/-3` suffix keeps same-slot/same-day files distinct). `friendly_filename()`
(+ `_slug()`, `_taken_names()`) builds it; the friendly name becomes
`original_name` (the shown + download name) while the on-disk `stored_name` stays
uuid-prefixed and collision-safe, so downloads/thumbnails are unaffected. Applied
across all four upload paths (job/client/employee/field-photo). New uploads only —
existing files untouched per direction.

**Piece 25.3 — background scheduler for follow-up generation.** Lead follow-ups
used to be generated only when someone loaded the home / dashboard / task pages.
A daemon-thread timer (`start_scheduler`, `run_maintenance`, every 15 min via
`SCHEDULER_INTERVAL_SECONDS`) now runs that generation off the request path, so
it keeps up even when the app sits unattended. It's lazy-started on the first
request (a `before_request` hook — works under `python app.py`, the debug
reloader, and any WSGI server; only the serving process ever starts it) and
guarded to start once per process. `run_maintenance` opens its own Row-factory
connection since the request-scoped `get_db` isn't available in a bare thread,
and any error is logged without killing the timer. The existing on-page-load
`ensure_lead_followups` calls remain as a cheap, idempotent immediacy fallback.
Future periodic jobs just extend `run_maintenance`.

**Piece 25.2 — per-slot document format restrictions.** Each document upload
slot can now require specific file formats (was: one global allow-list for
everything). Rule-based slots carry an editable **`allowed_formats`** (new column
on `resource_rules`, comma-separated exts, blank = any) set on the Rules add/edit
form; the standard slots use built-in defaults (`STANDARD_DOC_FORMATS`: Signed
Contract → pdf/doc/docx, Site Photos → images, Design/One-Line → pdf/png/jpg,
Site Plan → kmz/kml). `allowed_formats_for_label()` resolves a slot's accepted
set (else falls back to the global `ALLOWED_EXTENSIONS`); `upload_file` enforces
it server-side with a clear message, and the job Documents tab sets each file
input's `accept=` and shows an "Accepts PDF, JPG only" hint. `_parse_formats()`
normalizes input (strips dots, lowercases). Verified end-to-end (rule store/edit,
standard + rule resolution, accept/reject on upload, hints render).

**Piece 25.1 — timesheets.** A printable per-employee hours **timesheet** built
from the logged time entries (the same ones the Work Bag submits and payroll
approves). `/timesheet` groups entries by employee → work date with day
subtotals and per-person Approved / Pending / total hours; `build_timesheet()`
is the shared roll-up and `/timesheet.csv` exports it (payroll-ready).
**Self-service + scoped:** any signed-in worker sees their own hours; payroll
(GM / Admin / Finance, via `_can_payroll`) can pick any employee or "everyone" —
non-managers are locked to themselves even if they pass `?employee=`. Date range
defaults to the pay period (`?start`/`?end`). Linked from the Payroll header
(🕒 Timesheet) and the Work Bag (🕒 My full timesheet); print CSS hides the
controls. Complements the existing payroll dollar rollup, which is unchanged.

**Piece 25.0 — in-place edit for the add/delete-only records.** The six record
families that were previously add-then-delete-to-change now have an **✎ edit**:
rules, appliance catalog, component catalog, credentials, load items, rooms, and
BOM lines. Pattern: reference records (rules/catalog/credentials) use a JS-free
`?edit=<id>` query that pre-fills their existing add form (heading → "Edit …",
Save/Cancel), matched by a new `update_*` POST route under the same permission
gate as the add (catalog.manage / rules.manage / employees.manage). The
job-scoped loads records (items/rooms/BOM) edit **inline on the loads page** via
`?edit_item` / `?edit_room` / `?edit_bom`, honoring `@loads_unlocked` so a signed
contract still locks them. Delete-to-trash is unchanged. Verified end-to-end for
all seven via the test client.

**Piece 24.9 — service worker for offline cold-start.** The app now installs a
service worker (`/sw.js`, served at root with `Service-Worker-Allowed: /`) so
field crews can open the app with no signal. Since all CSS is inlined, the "app
shell" is just the HTML: the SW caches each page the user visits (network-first)
and, when offline, serves the last-seen copy — falling back to a friendly
`/offline` page (📴). Dynamic `/api/` calls and POSTs are never cached (the Work
Bag still hydrates from its own on-device store). Cache names are stamped with
VERSION, so a deploy's `activate` clears the old caches. Registered from
`base.html`; when a viewer is logged out it posts `clear-pages` to the SW so a
shared device won't serve cached authenticated pages. `require_login` exempts
`service_worker` + `offline_page` so they load pre-auth. **Verified in a real
headless Chromium** (Playwright): SW registers/activates/controls, an offline
reload of the Work Bag serves from cache, and an offline hit on an unvisited page
shows the offline fallback. This resolves the deferred "no service worker" item.

**Piece 24.8 — auto-logout is now a 12-hour *inactivity* window.** Changed the
24.7 absolute-from-login limit to a sliding idle window: `require_login` refreshes
`session["last_active"]` on every authenticated request, and `_session_expired()`
drops a session only when its last activity was 12+ hours ago. Active users stay
signed in indefinitely; an idle session (or a left-open tab — the Work Bag /
search only hit the server on user action, not a background timer) is dropped 12h
after the last action. Cookie slides with it; server stamp is authoritative;
unstamped/tampered sessions still count as expired.

**Piece 24.7 — 12-hour auto-logout.** A sign-in now lasts at most
`SESSION_MAX_HOURS = 12`, measured **absolutely from login** (not from last
activity). Login stamps `session["auth_at"]`; the `require_login` before-request
hook drops any session past the limit (`_session_expired()`), clears it, and
redirects to the login page with a security notice (API paths get a 401 instead)
— preserving the deep link so re-login lands where they were. The cookie is also
capped to 12h (`permanent_session_lifetime`) as a second layer, but the
server-side stamp is authoritative. Sessions with no stamp (pre-24.7 or tampered)
count as expired. `logout` now fully clears the session. No DB change.

**Piece 24.6 — Roles/permissions overhaul (part 2 of the workflow/roles
restructure).** Access now flows from the org chart. New `ROLE_PERMISSIONS`
(role → default permissions) is folded into `has_permission`: a person's
effective permissions = their role defaults ∪ explicit grants (GM still gets
everything; **'delete' is never role-conferred** — it stays GM-or-explicit-grant
for the soft-delete safety model). E.g. Designer / Purchasing Agent / Inventory
Mgr / Warehouse / Ops Mgr → `inventory.manage`; Sales roles → `leads.manage`;
R&D → `rules.manage` + `catalog.manage`; HR/Admin Mgr → `employees.manage`. New
permission **`inventory.manage`** gates the inventory editing built in 24.1–24.4
(item/tool/vehicle add-edit, stock adjust, the stale-stock queue) via
`VIEW_PERMISSION` + `@admin_required`; viewing the catalog stays open to all, and
the New/edit/stale controls are hidden in the template for users without it. The
**access console** now marks role-conferred tools as *via role* (checked +
disabled — change the role, not a grant). No migration; existing grants keep
working. Verified end-to-end (a Permit Coordinator is blocked + sees no edit
controls; a Designer gets full inventory access through their role alone).

**Piece 24.5 — BPMN lanes aligned to the org (part 1 of the workflow/roles
restructure).** The process swim-lanes were legacy generic labels (Foreman,
System Designer, Sales Rep, Finance Department, Warehouse Associate) bridged to
real roles. They're now the company's **functional departments** — Sales,
Design, Permits, Purchasing, Installation, Finance, Executive (+ the external
Authorities (CID) / Utility Company and Compendium System) — matching
DASHBOARD_DEPARTMENTS. Renamed `bpmn_export.LANES` + every step's lane, plus
`STATUS_OWNERSHIP` team lanes and `TITLE_LANE_KEYWORDS` in app.py. `LANE_TO_ROLES`
now keys on the department lanes → real Vixinman roles (Design→Designer,
Installation→Lead Installer/Installer/Scheduling/Service Tech, Purchasing→
Purchasing Agent/Inventory Mgr/Warehouse, Finance→Finance Mgr/Bookkeeper,
Executive→GM) **and keeps the old labels as aliases** so tasks generated before
the rename (whose notes say e.g. "Process step · Foreman") still auto-assign — no
migration needed. **Next (part 2): the roles/permissions overhaul.**

**Piece 24.4 — Inventory usage tracking + stale-stock notice.** New stock ledger
`inventory_txns` (item_id, kind = received/used/count/adjust, signed qty, optional
job_id, note, who, when). `apply_stock_txn()` is the single choke-point every
movement flows through — it writes a ledger row, updates the cached
`inventory_items.available`, and (for 'used') stamps `last_used = today`; the
future **BOM auto-deduct** will just call this same function (manual-now,
auto-later per direction). The item **edit page** gains a "Stock movement" panel
(Received + / Used − with an optional job link / Count correction) and a recent-
activity table. The **stale-stock rule** (`stale_stock_items`, STALE_MONTHS = 6):
Active items at zero on hand whose last *actual use* was 6+ months ago (never-used
items aren't flagged until the ledger has runway). It surfaces two ways per
direction: a **review queue** at `/inventory/stale` (Keep active → re-check in 6
mo / Discontinue / Move to trash) linked with a count badge from the Inventory
header, and a **card on the Designer dashboard** (mode "Design"). New column
`stock_reviewed_on` records a "keep" dismissal. This closes the deferred
stale-stock notice; **barcode registration is still the open inventory item.**

**Piece 24.3 — Inventory cleanup + Tools/Vehicles edit UI.** Two parts.
(a) `cleanup_inventory()` (meta `inv_cleanup_v`, INV_CLEANUP_VERSION; runs after
the research passes since it changes category/model): moves the 4 Schneider
PDP / connection / breaker-kit accessories **Inverter → Electrical**; splits the
two AP Smart rows that shared one model into **RSD Transmitter** (part 300-00252)
and **RSD Push Button** (part 300-00253) — they were different devices mislabeled
alike; and **flags** (does not delete) the genuine duplicate line-pairs
(IronRidge XR-1000-210M, MidNite MNTRANSFER-60A) that carry two different
recorded costs, for hand reconciliation. NOTE: the other "duplicate" groups
(Pytes cables, MNPV12) turned out to be distinct SKUs with different part
numbers — left as-is. (b) Full **add / edit / delete-to-trash** for the Tools
and Vehicles tables (`inventory_tool_*`, `inventory_vehicle_*` routes + two form
templates; `＋ New tool` / `＋ New unit` buttons and a ✎ edit link per row;
TRASH_REGISTRY gains `inventory_tool` + `inventory_vehicle`). Workbook synced:
Schneider rows moved to the Electrical sheet, AP Smart rows renamed, duplicate
pairs flagged.

**Piece 24.2 — Tool kit priced with big-box listings.** New `TOOLS_RESEARCH`
(`inventory_research.py`, keyed by tool name) + `apply_tools_research()` (meta
`tools_research_v`, TOOLS_RESEARCH_VERSION) enrich all 49 seeded tools (which had
only name + category) with a standard make/model, a store listing URL, and an
**approx price flagged for verification**. Mixed tier per direction: pro/
contractor-grade for daily-abuse, accuracy, and safety (Milwaukee M18 FUEL,
DeWalt, Klein, Fluke, Werner, Guardian) and budget/Harbor Freight for occasional
hand tools & consumables. ~15 are exact Home Depot `/p/` product pages; the rest
are Home Depot `/s/` search-listings for the named SKU; MC4 tooling + irradiance
meter are flagged solar-specialty (not big-box). Prices are approx (retail price
fetch is proxy-blocked) — never fabricated as exact. The in-app Tools table now
shows Cost (with ~ for approx), a 🛒 listing link, and an ℹ️ tier/source note;
`apply_tools_research` only fills rows still blank so later edits survive. New
**Tools sheet** added to the workbook. NOTE: the commodity sheets (Racking, Wire,
Electrical, Enclosure, etc.) are intentionally NOT re-priced from big-box — they
already carry Vixinman's quoted costs, have no spec fields, and are solar-specialty
vendors (IronRidge, Cobra, MidNite) not stocked at big-box.

**Piece 24.1 — Remaining spec-gap completions (Generator / Charge Controller /
Optimizer / Breaker).** RESEARCH_VERSION 6. Closed every genuine spec gap on the
four spec-bearing sheets that still had blanks: Generator ratings (Briggs PP18+
= 18kW/80A from its siblings; the two 200A ATS units = 200A); Charge Controller
**Max Solar (Watts)** at 48V from each datasheet (Morningstar TS-MPPT-60/60M =
3200W, Outback FlexMax 80 = 4000W, Victron SmartSolar 150/70 = 4000W); Optimizer
electricals for SolarEdge S440/S500B (rated power, 60V max input, 15A, plus
SolarEdge NA single-phase string-design constants — datasheet PDF fetch was
policy-blocked, so Isc/output detail is flagged to confirm) and the AP Smart
RSD-S single (mirrored from its RSD-S-PLC sibling, variant flagged); Breaker
ratings decoded from the model number (MNEPV20-600RT = 20A, Square D HOM280 =
80A). Nine non-rated items (maintenance kits, gaskets, control/AVR boards,
disconnect kit, PLC/RSS transmitters) are **flagged as accessories** rather than
given invented specs — all four sheets are now gap-free (every remaining blank
is a flagged accessory). Workbook: those 21 rows highlighted with specs + Flags.
**Next: tool + standard-hardware listings (big-box: Home Depot / Lowe's /
Harbor Freight) — brand tier TBD.**

**Piece 24.0 — Current-PV purchase URLs (final purchase-URL pass).**
RESEARCH_VERSION 5. Added product-page purchase links for the seven high-use
current PV modules — Q-Cells Q.PEAK DUO BLK ML-G10+ 400/405/410 and
XL-G10.3/BFG 480 (Solar Electric Supply), Mission Solar MSX10-435HNOB and
Hyundai HiS-S400YH(BK) (US Solar Supplier / Greentech Renewables), Canadian
Solar CS6.2-66TB-630H (US Solar Supplier — closest listed bin is 625H, flagged
to confirm). Every link is a reference-retail product page (listed vendors are
wholesale, no public per-item pages); prices stay "on request" — retail sites
block automated price fetch, so no price is fabricated. **This closes the
purchase-URL work per direction ("Current PV only, then stop"): inverter/battery
variants remain at brand-page level and are not expanded further.** Workbook
PV sheet patched (yellow highlight, Purchase URL + Flags on those rows).

**Piece 23.9 — Purchase URLs for current-install gear (batch 1).**
RESEARCH_VERSION 4. Brand/reference-retail purchase pages for flagship live
gear: Pytes V5/V10/V16 batteries, Sol-Ark SA-15K/8K/12K/18K (Current Connected
/ Solar Electric Supply brand page, FCC ID# pending), SolarEdge SE7600H, Solis
S6-EH1P10K, plus SOK S24V100. Prices on request throughout.

**Piece 23.8 — Make standardization (catalog cleanup).** `standardize_makes()`
(meta `make_std_v`, runs before research so keys stay valid) consolidates
manufacturer spellings: MidNite/Midnite Solar → **MidNite Solar**, Outback →
**Outback Power**, Schneider → **Schneider Electric**, Solar Rackworks →
**Solar Rack Works**, Solar World → **SolarWorld**, Calb → **CALB**, plus
model-text-in-Make fixes (Vicrton→Victron, MILBANK…→Milbank). 15 rows whose Make
holds a part type/description (Fuse, Surge Protector, MTWC-…, "Structural Pipe",
"Single Swivel Socket", etc.) are **flagged** for review rather than guessed. Two
research keys updated to canonical makes (Calb→CALB, Outback→Outback Power). The
no-spec commodity sheets (Breaker Panel, Controls, Electrical, Wire, Monitoring,
Enclosure, Pumping, Racking) have no specs to complete — this cleanup is their
"completion". Workbook regenerated with vendor + make normalization. **Next:
purchase URLs for active inventory.**

**Piece 23.7 — Vendor standardization.** `standardize_vendors()` (meta
`vendor_std_v`, VENDOR_STD_VERSION) folds the canonical list 54→52: renames
**Magerevo → Megarevo** (the actual brand; make column already spelled it so),
**merges Battery Systems (1487) → Continental Battery Systems (2000)** —
reassigning its items — per the verified Dec-2021 merger, and drops the stray
combined **"Summit/Graybar" (1804)** entry (0 items; Summit + Graybar stay
separate). Item free-text VendorId typos were already normalized at seed time;
the updated workbook now also rewrites its VendorId cells to canonical (52 cells)
and cleans the Vendors sheet. **Next: finish the catalog sheet list, then
purchase URLs for active inventory.**

**Piece 23.6 — Inverter research.** RESEARCH_VERSION 3, +24 Inverter entries.
Verified the current **string/hybrid** inverters' **Vin Max** (the calculator's
cold-temp string-sizing input) + Pout from datasheets: Sol-Ark 15K (500V/15kW),
SMA Sunny Boy US (600V), GoodWe MS-US (600V), Solis 1P9K (600V); SMA SBSE hybrids
set to 600V "verify". Deterministic flags: 4 Schneider rows are **NOT inverters**
(PDP/connection/breaker kits → recategorize to Electrical); 9 **battery-based
inverter/chargers** (Magnum, Outback Radian, Samlex, Victron) flagged "no PV MPPT
— PV Vin Max n/a". Workbook now covers PV + Battery + Inverter. **Remaining
inverters (SolarEdge, Schneider XW battery, Solis/Victron variants, Megarevo,
Emporia) + the other sheets still pending; FCC IDs are a later phase.**

**Piece 23.5 — Battery research (calculator capacities).** `inventory_research.py`
→ RESEARCH_VERSION 2, +19 Battery entries. The Battery **Capacity** column was
badly broken (Wh-vs-kWh unit errors like SOK 2400, Trojan 2220; 0.8 placeholders
where the description said 5.12 kWh). Fixed **deterministically, no web guessing**:
Capacity = the manufacturer kWh stated in the description when present, else
Voltage × Ah ÷ 1000 (nameplate) — this is the value the sizing calculator reads.
BYD-HVL-3 flagged (350V×80Ah=28 vs stated 12 kWh — V/Ah suspect). Rows missing
V/Ah (Absolyte 100G17, C&D AES-100LC17, Continental CBEV-24, generic O'Reilly)
flagged "needs datasheet". Updated workbook now carries PV + Battery changes +
the Standardization Flags sheet. **Next calculator sheet: Inverter.**

**Piece 23.4 — Inventory table redesign + in-app management + inverter FCC ID#.**
Table: Stock leads, Description second; a top **Stock = Available/Needed/On PO**
legend; **⚙ Show specs** toggle (spec columns hidden by default — Trish's view;
Cary reveals them); a **top-mounted horizontal scrollbar** synced to the table
(JS); bordered/larger 🛒/📄 **Docs** chips; a **＋ New product** button per
category. New routes `inventory_item_new` / `inventory_item_edit` (shared
`inventory_item_form.html`, dynamic per-category spec inputs) and
`inventory_item_delete` → trash (new `inventory_item` TRASH_REGISTRY entry).
Inverters get an (empty) **FCC ID#** spec column + a "FCC ID# pending" flag,
seeded once (meta `inv_fcc_flagged`); researched later. `last_used` column added
as groundwork for the stale-stock notice. **DEFERRED (need usage tracking):** the
"zero stock + unused 6 mo → notify Designer → trash" rule and the barcode
registration are next-phase — they light up once inventory is linked to job
material usage. **Research still to do: Inverter + Battery next (calculator).**

**Piece 23.3 — Inventory Phase B, PV calibration.** `inventory_research.py`
(`RESEARCH` keyed "Category||Make||Model", `RESEARCH_VERSION`) holds web-research
overrides; `apply_inventory_research()` folds them into `inventory_items` on
launch (re-applies when the version bumps; never touches Cost). New `status`
column (Active/Discontinued) + a `⚠️` flag tooltip + Discontinued badge in the
inventory table. Calibration batch = 4 PV rows proving every case: CS6P-260 spec
CORRECTION (Vmp17/Voc20→30.4/37.5), ET-250 spec COMPLETION, CS7N-710 "verify
Voc" flag (bifacial STC vs sheet), Mission MSE410 wholesale-vendor→retail-listing.
Confirmed constraints from the pass: most PV items are DISCONTINUED (datasheets
verifiable, no live price), listed vendors are largely WHOLESALE (no public
per-item URL), and retail sites BLOCK automated price fetch (403) — so web_price
is often left blank + flagged rather than fabricated. Updated workbook
(`Inventory_respec_UPDATED.xlsx`) carries the PV changes + a Standardization
Flags sheet. **Remaining PV rows + the other 14 sheets pending user OK on format.**

**Piece 23.2 — Inventory database, Phase A (structural import).** New tables
`inventory_vendors` / `inventory_items` (core fields + specs JSON + web_price/
purchase_url/manual_url) / `inventory_tools` / `inventory_vehicles` (with
`nickname`). `inventory_seed.py` (generated from `Inventory_respec.xlsx`) holds
54 vendors, 439 items, a 49-tool kit, and 11 vehicles; `seed_inventory()` loads
them once (meta flag `inventory_seeded`). Vendor names in the workbook's free-text
`VendorId` were normalized to canonical vendors via a typo map (e.g. "northern
Arizona Wind and Sun"→"Northern Arizona Wind and Sun", "BayWare…"→"BayWa r.e.…",
"Gnerac"→"Generac"). `/inventory` now renders the real data grouped by category
(collapsible, per-category spec columns) + Tools + Vehicles. **Phase B (per-sheet
web research: purchase/manual URLs, price verification, spec completion, and
wiring specs into the calculator) is still to do — starting with PV.**
Standardization flags captured in-session: Make-field typos (Vicrton→Victron,
MidNite/Midnite), model/desc text in the Make column (Wire, Racking), header
typos (Min Inpute, Battery Volatge), and the Summit/Graybar/Summit-Graybar and
Megavero/Megarevo/Magerevo naming questions.

**Piece 23.1 — nav order + stacked account.** Header order is now (left→right)
My Dashboard · Tasks · Work Bag · Approvals · Team · Databases · Admin. The
`margin-left:auto` that right-aligns the cluster rides on My Dashboard when
signed in, else on the first block item (Tasks) in open mode. The account name +
Log out button are wrapped in a flex-column div so they stack vertically at the
far right.

**Piece 23.0 — "Admin" nav dropdown (Log / Trash / Access).** The three
admin-gated links now group under a **🔧 Admin** `navdrop`. Each has its own
permission (`can('audit.view')`, `can('delete')`, `is_gm`), so the template
counts how many the user can reach: `adm_count > 1` → dropdown of just those;
`== 1` → a single plain link (no one-item menu); `0` → nothing. Approvals stays
a top-level link (it carries the pending-count badge).

**Piece 22.9 — "Team" nav dropdown (Employees + Payroll).** Employees and Payroll
now sit under a **👥 Team** `navdrop` — but only when `can_payroll` is true (so
the dropdown always has ≥2 items); users without payroll access get the plain
👥 Employees link as before. Same JS-free `<details>` pattern as Databases.

**Piece 22.8 — "Databases" nav dropdown + Inventory placeholder.** Header nav is
tidied: Client Profiles, Rules, Directory, Inventory, and Catalog now live inside
a single **🗄 Databases** dropdown (JS-free `<details class="navdrop">` +
`.navdrop-menu` CSS in base.html). New `/inventory` route → `inventory.html`, a
"coming soon" placeholder for the seed inventory DB (future designer →
procurement auto-fill). The dropdown carries the `margin-left:auto` in open mode
(previously on the Directory link). Employees/Tasks/Work Bag/Payroll/Approvals/
Log/Trash/Access stay as top-level links.

**Piece 22.7 — bolder headings on the installs & Closing panels.** "This week's
installs" and "Closing" get a heavier title (font-weight 800, 1.1rem) and a
larger tagline (0.92rem) for readability; other panels unchanged. (Structural
rework of these two tables still to come.)

**Piece 22.6 — "Ready for design" panel.** New Company-overview panel (under
Needs attention) listing the Sales→Designer hand-off queue: `gm["ready_design"]`
= Proposal jobs where `_loads_recorded()` is true (load survey captured — the
step before design) AND no Done task matching `LIKE '%finalize%design%'` (design
not finalized). Each row links to the job and to its Loads & Sizing page.

**Piece 22.5 — separate the Company-overview sub-sections.** Each of the five
sub-sections (Pipeline, Money in flight, Needs attention, This week's installs,
Closing) is now wrapped in its own `<section>` panel (`background:var(--bg)`,
border, radius, padding) so they read as distinct blocks; the count/money tiles
were given a white (`var(--card)`) fill so they pop against the panel. Shared
`panel`/`panelh`/`tile` inline-style vars set at the top of the block. Content
and column structure unchanged (installs + closing tables revisited next).

**Piece 22.4 — drop the Executive flat job list.** The generic "jobs in your
stages" section is now skipped on the Executive viewport
(`{% if s.stages and not (gm and s.name == "Executive") %}` in dashboard.html) —
it listed every active job and was redundant with the Company overview's
pipeline counts, this-week installs, and Closing worklist. Other viewports are
unchanged. (It was never an install-date window, despite the reading — it showed
all active jobs in Proposal..Closing.)

**Piece 22.3 — Executive (GM) company overview (Screen 6).** The dashboard route
builds a `gm` dict when `mode == "Executive"`: pipeline `counts` per stage
(Proposal..Closing), `money` totals (contract/collected/outstanding/expense via
`job_billing` over non-Lost jobs), `approvals` (pending field submissions),
`overdue` task count (open tasks past due on active jobs), `stalled` jobs (active
jobs whose newest `job_tasks.updated_at` is >14 days old — no-task jobs
excluded), `installs_week` (install_date in the next 7 days), and a `closing`
worklist (each Closing job's balance due = contract − collected, plus open/total
close-out steps and the next one). `dashboard.html` renders a ⭐ **Company
overview** card (tiles + tables) above the generic sections; the old standalone
Manager approvals card is suppressed when `gm` is present (folded in).

**Piece 22.2 — Loads & Sizing locks past Proposal.** Implements the 22.1 note.
`_loads_locked(job)` = job status is in `STAGE_ORDER` beyond Proposal (Lost, off
the normal order, stays editable). New `loads_unlocked` decorator (fetch_job +
lock check → flash + redirect) guards all eight loads-editing POSTs
(rooms/items/bom add+delete+toggle, sizing) — the view-only `set_ui_mode` toggle
stays open. `job_loads` passes `locked` to the template: a 🔒 lock banner shows,
the add/delete/toggle forms are hidden, and the sizing form is wrapped in a
`<fieldset disabled>` (values stay visible + greyed) with its Save button hidden.
Load survey, summary, and computed sizing outputs remain fully visible — and the
figures still surface read-only on the job General tab + in Design. Enforced both
UI-side and server-side.

**Piece 22.1 — "Packing list" rename.** The Work Bag materials list is now
labelled **📦 Packing list** (was "Load list") to avoid confusion with the
electrical **Loads & Sizing** tool.

**Piece 22.0 — Work Bag packing list.** `/api/my-tasks` returns
`materials_by_job` (item/quantity/unit/status for every job on the board); the
Work Bag JS renders a collapsible **📦 Packing list** under each job banner,
colour-coded by readiness via `matClass()` (Backordered→danger, Needed/Quoted→
warn, On hand/Received→green). Cached in `localStorage` (LS_MATS) so it works
offline. Lets installers pack the truck before leaving.

**Piece 21.9 — Work Bag field notes.** New `job_notes` table (job_id, note,
author, `created_at` default `datetime('now')` — the same clock as
`audit_log.ts`); each note is independently timestamped. `POST /work-bag/notes`
adds one (job + text required), `POST /work-bag/notes/<id>/delete` removes it
(author-scoped). A standard **📝 Job notes** card in `work_bag.html` (job picker +
textarea + the author's recent notes); the job's notes render newest-first as a
**📝 Field notes** card on the job_detail General tab (`job_notes` passed from the
route) so the office can read them later.

**Piece 21.8 — photo capture on every photo-requiring step.** `_is_photo_step`
now matches `PHOTO_STEP_KEYWORDS = ("photo", "picture", "site visit", "site
installation", "install walkthrough", "doc tube", "meter set", "re-inspect")`
instead of just "photo"/"picture", so the Work Bag camera button covers the
whole set of BPMN steps that need pictures: Site Visit, Site Installation, Crew
Install Walkthrough, Doc Tube and Pictures, Correct & Re-inspect, Meter set, and
Photograph Final Inspection Sticker. Keywords are deliberately specific
("install walkthrough"/"re-inspect" not bare "walkthrough"/"inspect") so the
Sales *Final Client Walkthrough* and the *Final CID Inspection* don't get a
camera they don't need. Retroactive — no schema/data change, purely detection.

**Piece 21.7 — Work Bag photo capture.** Any task whose title matches
`_is_photo_step()` ("photo"/"picture") grows a 📷 button in the Work Bag that
opens `work_bag_photos.html` (`GET/POST /work-bag/tasks/<id>/photos`) — a
phone-camera page (`<input accept="image/*" capture="environment" multiple>`,
auto-submits on pick). Uploads are stored as `job_files` tagged
`rule_label = FIELD_PHOTO_LABEL` ("Field Photo") + `task_id` (new TEXT column;
schema.sql + `ensure_columns`), image extensions only (`PHOTO_EXTENSIONS`).
New inline server route `GET /jobs/<job>/files/<id>/view` (as_attachment=False)
backs thumbnails; `/api/my-tasks` attaches `is_photo_step`, `photos_url` and a
`photos` list per task so the bag shows a live thumbnail strip. Field crews can
delete their own shots via `POST /work-bag/photos/<id>/delete` (scoped to
FIELD_PHOTO_LABEL, so it can't touch requirement docs — those stay GM-only).

**Piece 21.6 — Foreman / Installation viewport (Screen 5).** `FIELD_STAGES =
{"Installation", "Inspections"}`. Dashboard route: when `mode == "Installation"`
it builds `install_buckets` (This week / Upcoming / In inspection·unscheduled)
from the Installation section's jobs by parsing `install_date` against today,
and trims `my_tasks` to `FIELD_STAGES` (drops office steps like Set Installation
Date). `dashboard.html` renders the Installation section as three date-bucketed
tables (Install date · Client · Job · Progress) instead of the flat table.
Work Bag: `_my_tasks_rows` now also selects `pipeline_status`, `install_date`
and orders by install_date; `work_bag.html` JS filters to `FIELD_STAGES` and
clusters tasks **by job** under a header showing job · client · 🔧 install date
(office/scheduling tasks no longer clutter the crew's bag).

**Piece 21.5 — Receipts / invoices / bills.** New `doc_type` column on
`job_transactions` (`DOC_TYPES = ["Receipt", "Invoice", "Bill"]`; schema.sql
CREATE + `ensure_columns` upgrade for existing DBs; blank = plain ledger note).
`add_transaction` captures & validates it. Billing tab (`job_detail.html`) gains
a **Document** selector on the add form — picking one nudges Type/Status via
`txnDoc()` JS defaults (Invoice→Income/Outstanding, Bill→Expense/Outstanding,
Receipt→Expense/Paid, all still editable), a **Doc** column in the ledger table,
and a **paperwork-on-file** tally (`billing["docs"]` = per-type count+amount from
`job_billing`). `quickbooks_export` adds a **Document** column and an optional
`?doc=Receipt|Invoice|Bill` filter (validated; filename suffixed, e.g.
`compendium_quickbooks_bills.csv`); the Finance dashboard Payments section links the
three per-document exports beside the full export. Rationale: QuickBooks imports
invoices (A/R), bills (A/P) and receipts through separate flows.

**Piece 21.4 — Permits/Warehouse viewport.** Permits dashboard jobs table gains a
**Permits X/Y** column (`permits_by_job` from `job_permit_coverage`, shown when
`s.name == "Permits"`). Purchasing dashboard gains a **Procurement** rollup
(`procurement`, material counts per status per Job-Prep job; Needed/Quoted/
Backordered highlighted) — placeholder for the future designer→inventory-sheet
auto-fill. `MATERIAL_STATUSES` expanded to Needed/Quoted/Ordered/Backordered/
Received/On hand/Installed. Job **L/P/C tab** reordered: Permits (+ portals/
phones) first and open, with an **inline per-permit file-upload slot** (merges
the requirement with filing); **Technician Licenses + Compliance collapsed at the
bottom** (Lead Installer owns those, not the Permit Coordinator).

**Piece 21.3 — payroll: self-log + approval + auto-OT + rate lock.** Employees
log their own hours from the Work Bag (`/work-bag/hours`, status Pending);
supervisors approve on the Payroll page (`approve_time_entry`/`reject_time_entry`)
— only Approved entries count in `payroll_summary`. Auto-overtime: `pay_types`
gains `ot_eligible`; per employee per ISO week, hours over the threshold earn the
OT premium (`ot_h × base × (mult−1)`). OT threshold + multiplier live in `meta`
(`_meta_get/_meta_set`, `ot_rules`), editable in Pay settings. The manual
"Overtime" pay type is gone from the seed; existing DBs set it/PTO/Holiday to
`ot_eligible=0`. `time_entries` gains `status/approved_by/approved_at` (existing
rows migrated to Approved). Rate editing (Pay settings + all save routes) gated
by `pay_rates_required` = `_can_edit_pay_rates` (GM or "Payroll Manager" role =
Cary + Lisa; exposed as `can_edit_pay_rates`). Payroll view stays
`payroll_required` (Finance/Admin/GM).

**Piece 21.2 — Payroll / hour tracking.** Tables `pay_types` (name, method
[multiplier/flat], value, sort, active), `pay_rates` (per-employee per-type
override), `time_entries` (employee, date, job, pay type, hours). Employee
`base_wage` column (ensure_columns, TEXT — coerce with `_to_float`). Pay math:
multiplier type → base_wage × value; flat type → value; per-employee override
beats the type default. `payroll_summary(db, start, end)` rolls up hours/$ per
employee per type. Pages: `/payroll` (period summary + log-hours form + entries)
and `/payroll/settings` (pay types + per-employee wages/overrides), gated by
`payroll_required` (`_can_payroll` = GM/Admin/Finance; exposed to templates as
`can_payroll` for the header link). `/payroll/quickbooks.csv` exports the period
as negative expense lines. Seeded pay types have placeholder values — Vixinman sets
real numbers in Pay settings.

**Piece 21.1:** login no longer treats the bare root "/" (Client Profiles) as a
post-login `next`, so everyone reliably lands on their own dashboard; real deep
links are still honored.
**Stack:** Flask + SQLite + Jinja templates. No JS framework. Pure Python; raw SQL (no ORM).
**Branch/workflow:** develop on `main`; bump the `VERSION` string in `app.py` each change;
commit + push after each feature so Rachel can pull (GitHub Desktop on Windows).

> Rachel is non-technical but competent. Explain the "why," give exact
> click-by-click steps, and **confirm the footer version after each update.**

## How to run
- **Dev:** `python -m pip install -r requirements.txt` then `python app.py` → http://127.0.0.1:5000
- **Desktop app (for the team):** `desktop/Build-Compendium-Windows.bat` (built on Windows)
  produces a double-click `Compendium.exe`; see `desktop/README-DESKTOP.md`. A known
  "exe flashes then closes" issue has its own guide: `desktop/DESKTOP_TROUBLESHOOTING_HANDOFF.md`.
- First run creates `job_creator.db` with 3 sample clients (one job each), 2 sample
  employees, sample tasks, and the full NM rule set + appliance/component catalogs.
- **Backups must include BOTH `job_creator.db` AND `uploads/`** (files live on disk).

---

# 1) Complete feature list, by page

Global chrome (`base.html`): green header with the **☀️ Compendium** home link and a
top-right nav. Nav shows **📖 Directory · 🔌 Catalog · ⚙️ Rules · 👥 Employees ·
🏠 My Dashboard · ✅ Tasks · 🎒 Work Bag** for signed-in users, plus **🕗 Approvals (N) · 🧾 Log** for admins,
and the signed-in user's name (links to My account) + Log out. Every page has a
footer with the build version. Flash messages render at the top of `main`.

### My Dashboard — `/dashboard` (`dashboard.html`, Piece 19) — the sign-in landing
- Role-based home. Login redirects here. A person **belongs to a department** if they
  hold one of its roles (`DASHBOARD_DEPARTMENTS` / `user_departments`); the dashboard
  **stacks a section per department** they're in, plus a top **✅ My tasks** list
  (their open assigned tasks, stage-tagged) and — for Sales — **follow-ups due**, and
  — for Executive/GM — a **field-work approvals** callout.
- **Mode switch** (only if multi-department): **All** or focus on one department;
  the choice persists in the session, and **★ Make this my default** saves it to
  `employees.dashboard_mode` (the person's "working role"). Cary (holds every role)
  is seeded to default to **Design**; the GM keeps the full overview when in All.
- Each department section lists the **jobs currently in the stages that department
  works** (Permits → Job Prep/Inspections, Finance → Job Prep/Installation/Closing, …).
- Only active with logins on (needs a signed-in user). "All clients" link → Home.

### Home / Clients — `/` (`index.html`)
- Lists all client profiles (name → profile, phone, mailing address, referral);
  active **Leads** carry a "Lead" badge.
- **Search box** (clients + jobs) and a **＋ New client** button; admins see a
  **❄ Cold leads (N)** button.
- **Live search preview (Piece 15):** as you type, a dropdown previews matching
  clients and jobs (via `/api/search`); Enter still runs the full search page.
- **🔔 Follow-ups due (Piece 16):** leads on the 7-day / 2-week / 1-month cadence
  whose follow-up is due/overdue, each with **Enter job details** (convert),
  **✓ Logged**, and **❄ Cold** actions.

### Search — `/search` (`search.html`)
- One box searches **clients** (name/address/phone/email) and **jobs**
  (name/site/county/products/client). Results link through; jobs show a status badge.

### Client profile — `/clients/<id>` (`client_detail.html`, tabbed)
- **✎ Edit client information** button (Piece 13.3).
- **Overview tab:** contact/address/referral/notes/"client since"; **Jobs** table
  (each with a **status badge**) + **＋ New job**.
- **Change note (Piece 15):** if the profile has been edited, a note shows how
  many times + last editor/date. Older values are hidden; **admins** get a
  **🔒 View change history** button (non-admins just see the note).
- **Documents tab (Piece 12):** client-level files (Contracts / Correspondence /
  Intake / Photos / Other), upload/download/delete — kept separate from job docs.

### New / Edit client — `/clients/new`, `/clients/<id>/edit` (`client_form.html`)
- All Vixinman intake fields, plus an **assigned sales rep** (Piece 16). **Addresses
  are separate fields (Piece 15):** street /
  city / state (defaults NM) / ZIP for mailing and billing, with a "same as
  mailing address" helper that mirrors all four billing parts. The parts compose
  into the stored full-address strings used by search/roster/job pre-fill.
- Editing snapshots the outgoing values into `client_versions` (only when
  something actually changed); legacy single-line addresses drop into the street
  line so nothing is lost on first edit.

### Client change history — `/clients/<id>/history` (`client_history.html`, **admin**)
- The hidden older versions of a profile: each edit's prior values (full snapshot)
  with the changed-field labels flagged, who edited, and when. Newest first.

### Cold leads — `/cold-leads` (`cold_leads.html`, **admin**, Piece 16)
- Leads marked cold, moved out of the active client list into a separate table.
  Rows older than **182 days (~6 months)** are flagged **purge?**; nothing
  auto-deletes. Actions: **↩ Restore** (back to active leads) / **✕ Delete**.

### Lead lifecycle (Piece 16, cross-cutting)
- Clients carry a `lead_status`: **Lead** (new prospect, in the follow-up cadence)
  → **Converted** (first job created) or moved to **Cold** (separate `cold_leads`
  table). An **assigned sales rep** owns the follow-ups. Follow-ups are generated
  on demand (home + task board load) at 7/14/30 days after creation; creating a
  job converts the lead and closes its open follow-ups.

### Job profile — `/jobs/<id>` (`job_detail.html`, tabbed)
- Header buttons: **status picker** (Piece 16: Proposal→Job Prep→Installation→Inspections→Closing→Complete, or Lost),
  **✎ Edit job**, **⚡ Loads & Sizing** (own page, Piece 15.1), **Process chart**,
  **← Client profile**.
- **Pipeline stage panel (Piece 18 / 18.1):** shows the current stage's **owning
  department** and the **head of each staffing function** (resolved live via
  `best_assignee_for_lane` from `STATUS_OWNERSHIP`), the **exit criteria**, a
  **stage-tasks progress** count (this stage's own tasks done / total), and an
  **✓ Advance to <next>** button (green when ready; a warned override otherwise).
  In **Job Prep** it also shows **permits filed (N/M)** + an **install-date** control;
  setting the install date once all permits are filed **auto-advances to Installation**.
  Every transition is soft-gated (`stage_info` → `ready`/`pending`, `next_stage`): the
  manual picker and the button both work, but advancing early flashes what's pending.
- **Standardized step→stage tagging (Piece 18.1):** each BPMN step carries a
  `pipeline_status` (`bpmn_export.STEP_STATUS`), so generated tasks are tagged by
  stage (`job_tasks.pipeline_status`) and each stage gates on *its own* tasks being
  Done. A one-time migration (`tag_tasks_by_stage`, `meta.tasks_stage_tagged`)
  back-fills existing tasks from title keywords (`TITLE_STATUS_KEYWORDS`).
- **Tabs (5):** General details · **LPC** · Materials · Documents · Tasks.
  ("LPC" is the abbreviated Licenses/Permits/Compliance tab, Piece 15.1; hover
  shows the full name.)
- **General details tab:** all job fields + **version history** (JSON snapshot per edit).
- **LPC tab (Licenses, Permits & Compliance):** requirements resolved live from the
  rules engine, grouped (Technician licenses / Permits / Compliance / Online Portals /
  Phone / Documents), each linked to its NM source + phone. **📎 filing-coverage
  badges** (N/M on file). License items show **👷 who on staff holds it** (green/amber/
  red by credential expiry) or **⚠ no one on staff holds this**. **⬇ Export report**.
- **Materials tab:** per-job material list — **fully inline-editable** rows
  (item/qty/unit/supplier/notes + Save), status dropdown, add, delete.
- **Documents tab:** upload/download/delete job files, optionally filed under a
  requirement (drives the coverage badges).
- **Tasks tab (Piece 10):** per-job tasks — inline-editable title/notes (Save),
  inline assignee/status/due (auto-save), overdue flag, add, delete. **⚙ Generate
  from process** (with optional install date) auto-creates the job's process-step
  checklist, **auto-assigned to the most sensible role-holder** and due-dated around
  the install.
- **Role-based assignment (Piece 17.2):** `best_assignee_for_lane` maps a step's
  BPMN lane (via `LANE_TO_ROLES`) to the best person — preferring a real (non-demo),
  non-GM specialist with the fewest roles. A one-time migration (`assign_tasks_by_role`,
  `meta.tasks_role_assigned`) back-filled existing tasks: lane from the task's note,
  or inferred from title keywords (`TITLE_LANE_KEYWORDS`) for hand-added ones. It
  leaves tasks already assigned to real staff alone. Provisional — to be standardized.

### Calendar export (.ics) — Piece 20.0
- **`/calendar/my.ics`** (dashboard → *📅 Add my dates to calendar*): the signed-in
  person's task **due dates** + **install dates** for their jobs, as an all-day
  `.ics` calendar. In open mode exports everything.
- **`/jobs/<id>/calendar.ics`** (job header → *📅 Calendar*): that job's due dates +
  install date.
- Hand-rolled RFC-5545 builder (`build_ics`, no new deps); **stable UIDs**
  (`compendium-task-<id>` / `compendium-install-<id>`) so re-importing updates instead of
  duplicating. Import in Google Calendar via Settings → Import & export. Deliberately
  a **one-time import** for the desktop app; live two-way sync / availability waits
  for the hosted version + Workspace OAuth (see next steps).

### Finance viewport: billing ledger + QuickBooks — Piece 21.0
- New `job_transactions` table (schema.sql) + `jobs.contract_amount`
  (ensure_columns, TEXT affinity — coerce with `_to_float`). Constants
  `TXN_KINDS`, `TXN_STATUSES`, `INCOME_CATEGORIES`, `EXPENSE_CATEGORIES`,
  `PAYMENT_METHODS`. Helper `job_billing(db, job_id, contract)` → collected /
  outstanding / invoiced / uninvoiced / expense / net rollup + raw txns.
- Routes: `set_contract`, `add_transaction`, `toggle_transaction_paid`,
  `delete_transaction`, and `quickbooks_export` (`/finance/quickbooks.csv` —
  Date/Description/Amount first, signed +income/−expense, then detail columns).
- Job detail: **💵 Billing tab** (contract total, summary tiles, transaction
  table with paid toggle, add-transaction form with JS-swapped income/expense
  categories). Route passes `billing` + the txn constants.
- Finance dashboard: **Payments table** (all non-Lost jobs: contract / collected
  / outstanding / expenses / net + totals row + QuickBooks export button), gated
  on `show_payments = "Finance" in shown`. "jobs in your stages" progress column
  moved to the **rightmost** position for non-Proposal sections.

### Designer viewport + job-page overhaul — Piece 20.9
- **Dashboard:** Active Proposals gains a **Loads** column (✅/⬜ from
  `_loads_recorded`, via `loads_by_job`) so the Designer sees which proposals
  have loads recorded; Designer still sees all pending proposals.
- **Job detail restructure:** header is now job name → progress bar → a buttons
  row (status, Edit job, Process chart, Calendar, Client profile). **Loads &
  Sizing moved into the pipeline-stage panel**, next to the electric-loads
  indicator (prominent in Proposal, secondary elsewhere). **LPC tab renamed
  L/P/C.** General-details tab now surfaces the **saved load-survey summary**
  (daily kWh / peak W from `compute_load_totals`, `load_has_survey`).
- **Documents tab:** one **upload slot per needed file** — `STANDARD_JOB_DOCS`
  (Signed Contract, Site Photos, Design/One-Line, Site Plan) + the job's
  document-worthy requirements (Permit/Compliance/Doc only — licenses, portals,
  phones excluded). Each slot shows filed/needed status + filed files; an
  "Other documents" catch-all remains. Route passes `doc_sections`,
  `files_by_label`, `other_files`. (Per-slot format restrictions: TODO later.)
- **Loads & Sizing:** Load survey, Summary, System sizing are now collapsible
  `<details class="card sect">`. The load survey (job_load_rooms/items) already
  persists per job, so Sales' walkthrough numbers flow into the Designer's
  sizing math automatically.

### Sales dashboard tuning #2 — Piece 20.8
- Mode switch: **"All" removed** — always one role at a time. Route default mode
  is now `depts[0]` (no All view); `shown = [mode]`.
- Proposal-only jobs section reads **"Active Proposals"**; columns reordered to
  **Progress · Client (smaller) · Job · Install date**.
- **Client Profiles** dashboard section replaced by a **Leads** table (the
  landing-page follow-up/leads table): active `lead_status='Lead'` clients with
  their next open follow-up + rep + actions (Enter job details / ✓ Logged /
  ❄ Cold). Gated to the Sales viewport (`show_leads = "Sales" in shown`). The
  old separate "follow-ups due" card is folded into this. `mark_cold` now honors
  a `next` param so the action returns to the dashboard.

### Dashboard viewport pass #1 (Sales) — Piece 20.7
Working through each role's viewport in job-flow order; Sales first.
- Header nav gains a **🗂 Client Profiles** button (→ home). "All clients" button
  removed from the dashboard toolbar; **Make this my default** removed (route
  `set_dashboard_default` left in place, just unlinked).
- Dashboard sections are now **collapsible** (`<details class="card sect">` +
  `.sect` summary CSS in base.html). Reordered: department jobs → follow-ups →
  manager → **Client Profiles** → **My tasks (moved to the bottom)**.
- New **Client Profiles** list on the dashboard (`client_profiles` from the
  `dashboard` route): clients with a job in one of the viewer's stages, plus
  fresh leads (no job) when Proposal is in-scope. A client drops off once all
  their jobs move past the viewer's stages — so a Sales rep stops seeing a client
  once their job passes Proposal. Filter is stage-driven, so it generalizes to
  other roles as we tune their viewports.
- Sign-in already lands on the role dashboard (`login` → `dashboard`).

### BPMN process refinement, stage by stage — Piece 20.6
Reworked the per-job process in `bpmn_export.py` (reviewed against the maximal
job: commercial, all 6 products, roof/manufactured, grid-tie, Santa Fe + JMEC).
- **Proposal** now ends at the signed contract: `collect` renamed *Client Intake
  & Questionnaire* (old `quest` node removed/merged); new `loads` step *Record
  Electric Loads / Load Calculation* (Sales Rep) after the site visit; `contract`
  + `dep50` moved into Proposal (STEP_STATUS updated). Matches the loads gate and
  the "Sales signs the contract" exit criteria.
- **Job Prep**: the `compendium` serviceTask stays on the chart but is excluded from
  generated tasks (generate_tasks now skips `serviceTask`). New conditional
  `finance` step *Confirm financing / rebate paperwork* (Finance) on a parallel
  branch when financed OR tax_credit=Yes OR grid-tied.
- **Installation**: `walkthrough` → *Crew Install Walkthrough*; `monitoring`
  (*Set up Monitoring*) only added when PV or Battery is on the job.
- **Inspections**: **meter-set moved to after the CID inspection passes** (real
  interconnection order) — the Yes branch is now meterset (grid-tie) → JMEC LoC
  (JMEC) → sticker; `fix` → *Correct & Re-inspect*; sticker → *Photograph Final
  Inspection Sticker*.
- **Closing**: *Sales Walkthrough* → *Final Client Walkthrough (Sales)*; *Client
  Review* → *Client Review & Sign-off*; end → *Close Out & Submit Final Paperwork*.

### Electric loads → proposal step, not creation — Piece 20.5
- `electric_loads` removed from the **new-job** form (shown only when
  `editing_job_id`); the create form carries a note pointing to Loads & Sizing.
  Column and JOB_FIELDS unchanged — new jobs just post it empty.
- New Proposal-stage gate: `_loads_recorded(db, job)` is True when the
  structured Loads & Sizing worksheet has items (job_load_items) OR the
  free-text `electric_loads` summary is filled. `stage_info` adds `loads_ok`,
  puts "electric loads not recorded" in `pending`, and folds it into `ready`
  for Proposal — so the Advance button warns until loads are in. Stage panel
  shows a "⬜ Electric loads recorded · Record loads" indicator linking to the
  loads page. Existing jobs that already have a loads summary pass the gate.

### County → utility auto-matching — Piece 20.4
- `COUNTY_UTILITIES` in `nm_directory.py` (from doc 03's verified "Utility by
  County" table, canonical UTILITIES_ALL names, all 33 counties). Passed to the
  job form as `county_utilities_json` + `utilities_json`.
- `job_form.html`: the utility field is now a `<select>` filtered by county via
  JS — single serving utility auto-selects, multiple are all listed to pick
  from, and a **Manual override** button toggles to the full statewide list.
  Editing preserves a saved out-of-map value (`data-current`). `N/A` always
  available (off-grid / no utility); the field is intentionally kept for
  off-grid jobs since the meter ties to the provider. No schema change — still
  posts the `utility_provider` field.

### Rules display: compaction + verification callouts — Piece 20.3
- `group_rules(matched, dedupe=True)` now collapses a shared requirement into
  one entry carrying `instances` (the triggering selections, e.g. PV + Battery)
  and `alert_kind`/`alert_text` (from `_rule_alert()` scanning the note for
  ⚠ verify/unverified/confirm). Entries are dicts now, not Rows — drop-in for
  templates. Shown on the job LPC tab, the rule directory, and the text report.
  Instances only render when >1; `_instance_label()` builds the bullet text.
- Verification chips + a legend (`.flag`, `.verify-legend`, `ul.instances` CSS
  in base.html). Directory page carries the legend at top.
- **Data reconciliation (nm_directory `CORRECTIONS_V11`, seed batch 11):** the
  V10 batch had carried ~a dozen county in-city phones from doc 04's "could not
  verify" list; V11 replaces them with doc 02's verified-body numbers (Clovis,
  Fort Sumner, Artesia, Grant/Planning, McKinley Navajo codes 928-871-6380,
  Cloudcroft, Moriarty/Estancia, Clayton, Belen/Los Lunas, Lincoln, San Juan)
  and promotes items docs 01-03 now show verified (Continental Divide domain,
  Gallup city-hall line, KCEC hub). Keyed on (label, field_value); applies to
  existing beta DBs via the batch-SQL migration. Uploaded .docx == the repo's
  `docs/reference/*.md`, so no other values changed.

### Per-job progress widget — Piece 20.2
- `build_job_progress(db, job)` → dict with the ordered pipeline `stages`
  (each `done` / `current` / `upcoming` / `skip`), an overall `pct`, and the
  single `next_label`/`next_who` (lowest-sort_order not-Done task, else "Move
  to <next stage>"). Lost = all `skip`; Complete = all `done`, 100%.
- Rendered by the `job_progress(p, compact=false)` macro in
  `templates/_widgets.html` — a segmented bar (one segment per stage) with the
  current stage striped/highlighted and a "▶ Next: …" caption. CSS lives in
  `base.html` (`.jobprog*`). `compact=true` drops segment labels for table rows.
- Wired into **job_detail** (full, in its own card under the header),
  **client_detail** (compact, in the job list), and the **dashboard** (compact,
  in each department's job rows). Routes pass `progress` / `progress_by_job`.

### Default task deadlines — Piece 20.1
- Every task generated for a job now gets a **default deadline of 7 days after the
  previous step** (`TASK_DEFAULT_LEAD_DAYS = 7`). With nothing completed yet, the
  first generated step is due 7 days out, the next 7 days after that, and so on —
  a simple weekly cadence so no task is left without a date.
- When a step is marked **Done**, the next still-open step (lowest `sort_order`
  among not-Done tasks) is **re-defaulted to 7 days after that completion**
  (`_redefault_next_due`). Wired into both completion paths: the job page
  (`set_task_status`) and field-work approvals (`approve_submission`).
- Rough on purpose — meant to be tightened by hand per job. Setting a target
  **install date** at generation still uses the tighter install-anchored spacing
  (`TASK_DUE_SPACING_DAYS`) instead of the 7-day default.

### Loads & Sizing — `/jobs/<id>/loads` (`job_loads.html`, Piece 9; own page since 15.1)
- Reached from the **⚡ Loads & Sizing** button on the job header. Sales/Designer
  mode toggle; room-nested load survey (from the appliance catalog or custom);
  live daily-kWh/peak summary; **System Sizing** (off-grid/grid-tie presets → array
  kW/panel count, battery kWh/units, NEC 690.7 cold-temp Voc string sizing);
  **Components / bill of materials**.

### New / Edit job — `/clients/<id>/jobs/new`, `/jobs/<id>/edit` (`job_form.html`)
- All product/variant fields; service-ticket pre-fill from an existing job.

### Process chart — `/jobs/<id>/bpmn/view` (`bpmn_view.html`) + `/jobs/<id>/bpmn` download
- Per-job process as an ordered step list; downloadable BPMN 2.0 (bpmn.io/Camunda).

### Job report — `/jobs/<id>/report` — plain-text checklist download.
### Job version — `/jobs/<id>/versions/<v>` (`job_version.html`) — a prior snapshot + its resolved requirements.

### Rule directory — `/directory` (`directory.html`) — read-only, filterable rule browser (everyone).
### Rules manager — `/rules` (`rules.html`) — add/delete rules (**admin**); read-only for others.
### Catalog — `/catalog` (`catalog.html`) — appliance (379) + component (62) reference tables, add/delete (**admin**).

### Employees — `/employees` (`employees.html`)
- Roster with roles, credential tally + expiry warnings, schedule. **admin:**
  **🔑 Accounts** and **＋ New employee** buttons.

### Employee profile — `/employees/<id>` (`employee_detail.html`, tabbed)
- **Details** (roles, schedule); **Tasks** (assigned across all jobs); **Licenses &
  Certifications** (structured rows w/ expiry badges, "satisfies requirement" link,
  "copy on file"); **Documents** (credential copies). Edit/Delete + all add/delete
  controls are **admin-only**.

### New / Edit employee — `/employees/new`, `/employees/<id>/edit` (`employee_form.html`)
- **First name (required) / Last name / Nickname (Piece 19.3):** these compose the
  stored `name` ("First Last"); the nickname shows in quotes on the roster/profile.
  Creating an employee whose composed name already exists is **blocked** with a
  "different person? — add anyway" confirm checkbox, to stop accidental duplicates.
  Legacy single-name records split their `name` into the first/last fields on edit.
- **Remove employee (offboarding, Piece 19.4, admin):** the profile's **Remove
  employee** button opens a confirm page (`employee_remove.html`) that requires a
  **reason** (captured in the audit log). On confirm it **unassigns their tasks**,
  clears their sales-rep / follow-up assignments, removes their login / access grants
  / licenses / documents, then sends them to the **Trash** (GM can restore or purge).
  **Blocked** if they have field-work submissions on record (protects approved hours).
  Gated by `employees.manage` (so Admins can offboard — permanent purge stays GM-only).
- **Role checkboxes grouped by department** (Piece 16.1): 27 Vixinman roles in
  six collapsible department groups (Executive / Sales & Marketing / Operations /
  Administration / Finance / R&D) — a group opens automatically when it holds a
  selected role. Plus an "other" free-text field, schedule, and a **Login & access**
  section (admin): username, password, access level (Standard/Admin).
- `ROLE_DEPARTMENTS` in `app.py` is the source of truth; `EMPLOYEE_ROLES` (the flat
  list used for validation) is derived from it so the two never drift.
- **Org-chart team seeded (Piece 16.1):** Vixinman's real team (Cary, Will, Rachel,
  Louie, Trish, Si, Lisa, Vanessa, Brady) with their multi-role assignments is
  seeded once per DB via a `meta.org_team_seeded` flag (`seed_org_team`), skipping
  anyone already present — so existing installs get them without duplicates. The two
  "(sample)" employees remain for the credential/expiry demo; delete them for a clean
  roster.

### Accounts — `/accounts` (`accounts.html`, **admin**)
- Who can sign in + access level + password-set status; employees without a login;
  and **⏳ Pending password changes** (approve/reject self-service requests).

### Access console — `/access` (`access.html`, **GM only**, Piece 17)
- The General Manager grants individual tools to people who sign in, each with an
  optional **expiry date** (temporary access lapses on its own). GMs show "Full
  access"; Admin rows note "Admin already has this" (except Delete). One save form
  per person writes `permission_grants`.

### Access model (Piece 17, cross-cutting)
- **GM = anyone holding the "General Manager" role** (`_has_gm_role`) — unfettered
  access + the console + (delegatable) delete. **Admin** keeps every tool below GM
  **except Delete**. **Standard** gets only granted tools. Central check is
  `has_permission(perm)`; `admin_required` maps each gated view to a permission via
  `VIEW_PERMISSION`, and templates gate UI with `can('<perm>')`. Permissions catalog
  lives in `PERMISSIONS`; grants (with expiry) in `permission_grants`.
- **Deletion & trash (Piece 17.1, done):** every UI delete now requires the **delete**
  permission (`@delete_required`) → runs an **in-use check** (blocks with an error
  listing what references it) → otherwise **soft-deletes to the `trash` table** (full
  original row as JSON + origin table + a "found in" label). The `TRASH_REGISTRY`
  defines each entity's label / found-in / in-use rules (+ file path for uploads).
  Restore re-inserts the row to its origin table (original id preserved when free);
  **permanent purge is GM-only** (`gm_required`) and unlinks any on-disk file. Delete
  buttons are hidden unless `can('delete')`.

### Trash — `/trash` (`trash.html`, delete-permission holders; purge = GM only)
- Deleted items with what they were and where they lived; **↩ Restore** or (GM only)
  **🗑 Delete permanently**. In-use items never reach here — they're blocked at delete
  time. Cold-lead purge is also delete-gated (its own graveyard, not the trash).

### Task board — `/tasks` (`tasks.html`)
- Every task across all jobs; filter by person/unassigned and open/all; status tally +
  overdue count; inline status change; link to **🎒 My Work Bag**.

### Work Bag — `/work-bag` (`work_bag.html`) — the offline field page (Piece 14)
- The signed-in worker's assigned tasks, editable **offline** (saved in the browser);
  online/offline indicator; **Submit completed work** (work date + hours + note) →
  creates a **pending submission** for manager approval; tasks show "awaiting
  approval"; recent-submissions history. (No service worker yet — see limitations.)

### Field work approvals — `/submissions` (`submissions.html`, **admin**)
- Review Work Bag submissions: worker, work date, reported hours, note, the task
  changes; **confirm hours** then **Approve** (applies task changes + logs hours as
  authoritative) or **Reject** (applies nothing). Pending/All toggle.

### Audit log — `/audit` (`audit.html`, **admin**) — every state-changing request
(who/what/when/details/result), filterable by action. Passwords are redacted.

### My account — `/account` (`account.html`) — the signed-in user's page: **🎒 Work Bag**
link and **Change password** (submits for admin approval).

### Login — `/login` (`login.html`) — appears once at least one account exists.

---

# 2) Callouts already in the UI / code

**Access & accounts**
- Open-mode banner (until the first account exists): *"🔓 No logins set up. Anyone can
  access everything…"* with a link to Accounts.
- Last-admin safeguard: changing accounts can't leave the system with accounts but no
  admin — *"Keep at least one admin account — or remove every login to go back to open
  access."*
- Password self-service is admin-approved; the account page notes *"Forgot your
  password and can't sign in? An admin can reset it directly from your employee profile."*

**Work Bag / offline / approvals**
- Work Bag: *"Keep this page open while you're offline"* (reflects the no-service-worker
  limitation) and *"held for your manager to approve before it counts."*
- Approvals: *"Nothing here counts in the system until you approve it."*

**Rules engine / NM data (point-of-use warnings carried into rule `notes`)**
- Verification flags from the July 2026 Manual Review Log surface as "verify" notes
  (e.g., unverified utility domains/contacts, *"verify per project,"* *"verify current
  terms"*).
- Tax-credit / incentive caution in rule notes: SMDTC tier *"not confirmed — do not
  quote until verified with EMNRD"*; federal ITC note *"25D EXPIRED for expenditures
  after 12/31/2025 … consult a tax professional."*
- Situational rules carry qualifiers (*"if reinforcement needed," "confirm with AHJ,"
  "situational," "per tech on site"*).

**Loads & sizing**
- Sizing method note: NEC 690.7 cold-temp Voc + peak-sun-hour method, *"northern New
  Mexico design values — confirm against the specific site."*
- Component prices are planning estimates, not quotes (a few specs are engineering
  estimates — spot-check before a stamped design). Sales/Designer mode is labeled a
  *"view toggle, not access control."*

**Client change history (Piece 15)**
- Profile note: *"This profile has been changed N times…"* — for non-admins,
  *"Earlier information is hidden; an admin can review it."* The old values live
  only on the admin-only history page.

**Data / migration**
- Employee profile shows any pre-Piece-8.1 free-text credentials under *"Earlier
  free-text entry (from before structured tracking)"* with a nudge to re-enter as rows.
- Service tickets render the install pipeline provisionally with a caveat annotation
  in the BPMN.

**Desktop packaging** (`desktop/README-DESKTOP.md`)
- Expected Windows SmartScreen warning ("More info → Run anyway"); antivirus may flag
  an unsigned exe; the whole `Compendium` folder (with `_internal`) must travel together;
  backups must include `job_creator.db` + `uploads/`.

---

# 3) Architecture essentials

- **Rules engine is data, not code.** Each row in `resource_rules` says "when job
  field X = value Y, the job needs Z (category License/Permit/Compliance/Link/Phone/
  Doc)." Rules may carry a second AND condition. `match_rules`/`group_rules` in
  `app.py` resolve them; editable in-app at `/rules`, browsable at `/directory`.
- **Seed batches** ship rule data in versioned batches applied once per DB (tracked by
  `meta.seed_version`). `SEED_RULES` (batch 1), `SEED_BATCHES` (2–10, with 10 =
  `NEW_RULES_V10` from `nm_directory.py`), and `SEED_BATCH_SQL` (one-off corrections).
  **Never edit a shipped batch — add a new number.** 145 rules at seed_version 10.
- **Self-upgrading DB:** `init_db()` runs `schema.sql` (all `CREATE TABLE IF NOT
  EXISTS`), `ensure_columns()` adds missing columns, and applies unseen batches — so
  existing databases upgrade in place. **Never require deleting `job_creator.db`.**
- **Auth (Piece 13):** logins live on the `employees` table (username/password_hash/
  access_level). Login is OFF until the first account exists (open mode). A
  `before_request` wall enforces login when active (401 JSON for `/api/*`);
  `@admin_required` guards shared-data + account + approval + audit routes. Admin vs
  Standard; passwords via werkzeug hashing.
- **Audit (Piece 11):** an `after_request` hook logs every POST/PUT/PATCH/DELETE
  centrally (actor once logged in; passwords redacted).
- **Work Bag / offline (Piece 14):** `job_tasks.updated_at` (ms) tracks changes;
  `/api/my-tasks` pulls, `/api/work-bag/submit` records a **pending** `field_submissions`
  (+ `field_submission_items`) copy without touching authoritative data; admin approval
  applies items to `job_tasks` and logs `approved_hours`. Client offline state is in
  `localStorage`.
- **Key files:** `app.py` (~2900 lines: config, routes, rules engine, auth, audit,
  sync); `nm_directory.py` (NM utility/AHJ data = batch 10 + pick-lists);
  `loads_seed.py` (379 appliances + 62 components); `bpmn_export.py`;
  `templates/` (Jinja; `base.html` holds styling + tab CSS + nav);
  `docs/reference/00–04*.md` (verified July-2026 NM permit/AHJ/utility source set).
- **Tables (35+):** clients, client_versions, lead_followups, cold_leads, permission_grants, trash, jobs,
  job_versions, job_materials, job_files, job_tasks, job_notes, resource_rules, meta,
  employees, employee_credentials, employee_files, client_files,
  appliance_catalog, component_catalog, job_load_rooms, job_load_items, job_bom,
  job_sizing, password_requests, field_submissions, field_submission_items,
  audit_log, time_entries, pay_types, pay_rates,
  inventory_vendors, inventory_items, inventory_tools, inventory_vehicles,
  inventory_txns, inventory_assets.

# 4) Working conventions
- Bump `VERSION` in `app.py` per change; verify with a running server (curl + Playwright
  via bundled Chromium at `/opt/pw-browsers`) before committing.
- Test the seed-batch upgrade path on any rule change (simulate an older seed_version).
- Commit + push after each feature. Kill stray servers with `fuser -k 5000/tcp`.

# 5) Known limitations / deferred / next steps
- **Auto-rename uploads (Piece 25.4)** — every upload is now renamed to a
  self-describing **Name_What_Date** scheme via `friendly_filename()` /`_slug()`:
  job docs → `Client_Job_Slot_YYYY-MM-DD.ext`, client files →
  `Client_Category_Date`, employee files → `Employee_Credential_Date`, field
  photos → `Client_Job_Task_Date` (a `-2/-3` suffix de-dupes same-slot/day). The
  friendly name is stored as `original_name` (what shows + the download name);
  the on-disk `stored_name` stays uuid-prefixed and collision-safe. New uploads
  only — existing files were intentionally left as-is (no backfill).
- **Service worker (Piece 24.9)** — the app now cold-starts offline: the SW caches
  visited pages (network-first) and serves them, or a `/offline` page, without a
  signal. Still worth a real field test on crew devices before relying on it, and
  note it caches whole pages per device (cleared on logout via `clear-pages`).
- **"Manager" = Admin** for approvals; a specific manager→worker relationship is a
  future add.
- **In-place edit (Piece 25.0)** — rules, appliance & component catalog, credentials,
  load items, rooms, and BOM lines now all have an ✎ edit that pre-fills the record
  for saving back over the original (was add/delete-only). Same permission gates as
  their add actions; the loads records edit inline on the page.
- **No client/job delete** (intentional — would cascade). Cold leads (job-less)
  *can* be deleted from the admin cold-leads page.
- **BPMN process is still hard-coded** in `bpmn_export.py`. Piece 16 redefined the
  *status phases* (Leads/Proposal/Job Prep/Installation/Inspections/Closing) and the
  lead lifecycle, but **editing the BPMN step contents and reassigning role lanes
  by department is deferred** — the agreed next workflow task. Roles/permissions
  overhaul is also still pending.
- **Background scheduler (Piece 25.3)** — a daemon-thread timer
  (`start_scheduler` / `run_maintenance`, every `SCHEDULER_INTERVAL_SECONDS` = 15
  min) now runs lead-follow-up generation off the request path, so it keeps
  working while the app sits unattended. Lazy-started on the first request (works
  under `python app.py` incl. the debug reloader, and any WSGI server) and
  idempotent; the on-page-load `ensure_lead_followups` calls stay as an immediacy
  fallback. `run_maintenance` uses its own Row-factory connection. Add future
  periodic jobs by extending `run_maintenance`.
- All previously-suggested app-wide items are now done (BPMN/role restructure
  24.5–24.6, service worker 24.9, rule + record edit 25.0, timesheet 25.1,
  per-slot document formats 25.2, background scheduler 25.3). Remaining wishlist
  lives above (e.g. the deferred **auto-rename uploads** placeholder).
