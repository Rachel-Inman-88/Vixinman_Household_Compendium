# ☀️ Compendium

**Compendium** — the Vixinman household's task/project manager. Create project
profiles directly for the household, and automatically surface the right resources
(licenses, permits, compliance items, links, phone numbers, docs) based on each
project's fields — then run the whole project through a standardized, role-based pipeline.
Someday/maybe ideas live in a household idea backlog until you're ready to start them.

**Proprietary software — see [LICENSE](LICENSE). Do not distribute.**

Built for Vixinman Designs (New Mexico, statewide). Flask + SQLite + Jinja templates,
pure Python, raw SQL (no ORM, no JS framework). Runs from source or as a
packaged desktop app. Offline-capable; the database upgrades itself on launch.

---

## How to run it (every time)

1. Open a terminal in this folder.
2. First time only, install the one dependency:

   ```
   python -m pip install -r requirements.txt
   ```

3. Start the app:

   ```
   python app.py
   ```

4. Open your browser to **http://localhost:5000**

To stop the app, press `Ctrl+C` in the terminal. Your data lives in
`job_creator.db` (created automatically on first run). Delete that file to start
over with a fresh database. **Back up `job_creator.db` *and* the `uploads/`
folder together** — the documents on disk are referenced from the database.

The build number shows plainly in the page footer ("Version N") so beta testers
can confirm a pull/update took effect.

---

## Features & capabilities

> This list is the running record of everything the software does and is kept
> current with each update. When a capability is added or changed, it is logged
> here.

### Household idea backlog
- **Backlog ideas** (`/backlog`) — someday/maybe projects (repairs, builds,
  certifications) with a name, notes, an optional target/someday date, who
  proposed it, and a rough budget estimate, before it's a real project.
- **Lifecycle**: a single `Backlog` / `Started` / `Abandoned` status per idea —
  no separate archive table. Starting an idea creates a real project/project you
  fill in from there; abandoning one keeps it on record, not deleted.
- **Reminders**: a monthly "review your backlog" nudge through the notifications
  inbox if anything's still waiting, plus an optional custom reminder date on a
  specific idea.
- **Household-wide document storage** (`/household-files`) — files not tied to
  one project (insurance, warranties, correspondence), with categories.

### Projects
- **Project profiles** belong to the household directly, with full field capture.
- **Rules engine** — project selections → the licenses, permits, and compliance
  items that apply, across two pages:
  - **Rules Editor** (`/rules`): the editable catalog of resources (links, phone
    numbers, docs, accepted file formats). Grouped by category.
  - **L/P/C Directory** (`/directory`): a read-only lookup filtered by project type.
    Shared requirements are **consolidated** — a requirement needed by more than
    one selection (e.g. EE-98 for PV + Battery) shows **once** with every
    triggering scenario listed beneath, instead of repeating. Compliance rules
    can also carry the **verbatim source text** (the exact code wording), shown
    above the shorthand + source link, above the scenarios it applies to.
- **Verbatim source text** is an editable per-rule field for capturing the exact
  wording from the code/source, surfaced on the L/P/C Directory.
- **Verification callouts**: a rule can carry a visible **⚠ Verify / ⚠ Unverified**
  chip (with a legend) so field staff know what to confirm before relying on it.
  This is an **explicit, editable field** in the Rules Editor (a dropdown:
  none / Verify / Unverified) — a human can add or remove the callout on any
  rule/compliance note at will; existing rules were backfilled from the original
  NM reference-set convention.
- **NM reference data** (statewide licensing, all 33 counties' AHJ contacts,
  every utility's interconnection contacts) is kept reconciled against the
  verified July 2026 reference set.
- **County → utility auto-matching**: picking a county on the project form filters
  the utility-provider dropdown to the providers that serve it (verified doc-03
  table). If one utility serves the county it's auto-selected; if several do,
  they're all listed so you pick the one on the customer's bill. A **Manual
  override** button opens the full statewide list for non-standard cases. The
  utility field is kept even for off-grid projects (the meter/account ties to it).
- **Project edit history / versioning** for recordkeeping.
- **Per-project BPMN process charts**: an in-app viewer plus `.bpmn` export, with
  each step tagged by pipeline status.
- **Loads & Sizing** (`/projects/<id>/loads`): electrical loads and system sizing on
  its own page. Electric loads are **not** entered at project creation (they aren't
  known until the walkthrough) — they're recorded here during the proposal, and
  the **Planning stage can't advance until loads are recorded**. It's a
  **Planning-phase tool**: once the contract is signed (the project moves past
  Planning) the editor **locks** — the recorded figures stay visible here and in
  Design, but no one edits them (enforced in the UI and on the server).
  - **Sales / Designer view modes** default per viewer from their department
    (Design → Designer, Sales → Sales) and are togglable per session.
  - **Room-aware appliance picker**: each survey room has a "type" (Kitchen,
    Garage…) so its picker defaults to that room's appliances, with a search box
    over the whole catalog and a **Custom** toggle for off-catalog items.
  - **Appliance-era tags** are colour-coded — 🟢 Modern / 🟠 Vintage.
  - **Component auto-suggest**: once the survey is recorded, Designer mode reads
    the live inventory specs and proposes the components that fit — **PV modules**
    (by nameplate watts), **batteries** (by usable kWh), and the **inverter** (by
    rated power) — ranked with a Recommended pick plus alternates, each one-click
    addable to the bill of materials at the sized quantity.
- **Calculator Catalog** (🗄 Databases → Calculator Catalog): the appliance +
  component reference data that drives the load survey and the BOM/sizing picker;
  editing it applies everywhere immediately.
- **Materials lists** per project (status: Needed → Quoted → Ordered → Backordered →
  Received → On hand → Installed) and **document upload/storage** with
  per-requirement filing coverage. The project's **L/P/C tab** leads with **Permits**
  — each with an **inline upload slot** so the permit coordinator views the
  requirement and files the document in one place — with licenses and compliance
  collapsed below. The **Permits dashboard** shows a **permits-filed X/Y** column;
  the **Purchasing dashboard** shows a **procurement rollup** of materials by
  status across Prep-stage projects.
- **Per-slot upload formats**: a document slot can restrict its accepted file
  types (e.g. a permit slot to PDF), enforced on upload.
- **Auto-renamed uploads**: every uploaded file is renamed to a self-describing
  `Name_What_Date` scheme for recordkeeping (project docs, household files, employee
  files, and field photos each get their own pattern); the friendly name is what
  shows and downloads, while the on-disk name stays collision-safe.
- **In-place editing** for the add/delete-only records (rules, appliance &
  component catalog, credentials, load items/rooms, BOM lines) — an ✎ edit
  pre-fills the record to save back over the original.
- **Exportable project report**.

### Pipeline, tasks & scheduling
- **Standardized pipeline**: Planning → Prep → In Progress → Wrap-up → Done (plus Abandoned). Each stage is **owned by a department** with
  defined exit criteria; Prep is gated by prerequisites (all permits filed +
  an install date set — setting the install date auto-advances the project).
- **Per-project progress widget** — a segmented progress bar (one per project) that shows
  at a glance where the project sits in the pipeline, with the **next step called
  out**. Appears on the dashboard and each project's header.
- **Pipeline-turnover notifications**: whenever a project advances to a new stage
  (from Planning onward — new projects, manual stage changes, and the install-date
  auto-advance), the department(s) that **own the new stage** are notified in
  their in-app inbox. Each recipient's copy **clears the first time they access
  it** (opening the notification or the project); the person who made the move isn't
  notified, and backward moves don't fire.
- **Project cancellation (Abandoned) with a reason**: a "Cancel this project" control marks it
  **Abandoned** with a **required reason** recorded in the audit log (who/when), and
  remembers the stage it was at. A cancelled project's **open tasks are hidden** from
  My Tasks, the task board, and the Work Bag so they stop nagging the crew —
  nothing is deleted. **Everyone involved so far** (task assignees, time loggers)
  is notified. A **↩ Reopen** action restores the exact prior
  stage and its tasks. ("Abandoned" is removed from the plain stage dropdown so every
  cancellation captures a reason.)
- **Closed projects review** (🗄 Databases → Closed projects, GM/Admin): a management view
  of **cancelled** projects — reason, who/when, prior stage, contract — each
  with a one-click Reopen, plus a list of **completed** projects.
- **Task generation** from a project's process, with each step auto-assigned to the
  role-holder responsible for it.
- **Default task deadlines**: every generated task defaults to **7 days after the
  previous step** (a weekly cadence); when a step is marked Done, the next open
  step is re-defaulted to 7 days after that completion. Hand-editable per project.
- **Calendar export (.ics)**: download your task due dates + install dates
  (`/calendar/my.ics`) or a single project's dates (`/projects/<id>/calendar.ics`) and
  import into Google Calendar (or Outlook/Apple). Stable IDs so re-importing
  updates events instead of duplicating.
- **Work Bag** for field crews — an offline-capable field tool that shows **only
  on-site field work** (install & inspection); office/scheduling steps stay on the
  dashboards. It opens on a **projects landing** that lists just the projects in the
  crew's bag (name, install date, open-task count); tapping a project opens
  its **own page** with that project's tasks, plus hours, receipts, and notes pinned
  to it.
- **Submit-as-done with time by pay type**: instead of a status dropdown, each
  task has a single **✓ Submit as done** (and a **⚠ Can't finish** → Blocked).
  Submitting captures **the time it took, split by pay type** (e.g. 8 h regular +
  1 h travel + 2 h roof) shown live on a **colour-coded timeline**. It flows
  through **two sign-offs**: the supervisor approves the task (marking it Done and
  posting the split hours as **pending payroll** by pay type), then Finance
  approves the hours on the payroll page. All edits are saved on-device and submit
  when back online.
- **Project photos from the field**: every pipeline step that requires photos — the
  site visit, the install itself, the crew walkthrough, doc tube, the meter set,
  and re-inspection of corrections — is completed on its **own dedicated screen**:
  a 3-step **take / review / submit** flow (phone camera, thumbnail review, then
  submit with notes and the time it took). Submitting requires at least one photo,
  marks the task done for approval, and returns to the project's Work Bag page. Photos
  save to the project and appear on the project record; crews can remove their own shots.
- **Packing list**: each project in the Work Bag carries a collapsible **📦 Packing
  list** of its materials (item, qty, status) — colour-coded by readiness (on
  hand / received vs. still-needed vs. backordered) — so installers can pack the
  truck before they leave. (Named "Packing", not "Load", to keep it distinct
  from the electrical **Loads & Sizing** tool.)
- **Field notes**: a standard **📝 Project notes** box in the Work Bag lets crews jot
  free-form notes about a project (access details, on-site changes, callbacks). Each
  note is **individually timestamped** (the same clock as the audit log) with the
  author, and surfaces on the project's record for the office to read later.
- **Field receipts**: crews snap a receipt photo and log the date, total, vendor,
  reference, and expense category from the Work Bag; it's filed on the project and
  recorded as a **paid expense** for bookkeeping.
- **Grouped task board**: the cross-project task board and the dashboard's **My
  Tasks** are **grouped under each project** (a banner per project with its tasks as
  bullets beneath) so everything for a project reads at a glance.
- **Boards** (📋 in the top nav): stand-alone **to-dos not tied to a
  project** (clean the bathroom, call a vendor, …). Each can be **sent to a
  teammate** (who's notified), carries a **time log** (hours + notes, with a
  running total) and a **notes log** you add to over time, and has a
  priority / due date / status. Filter by Mine / All / Unassigned.
- **Offline cold-start (service worker)**: the app caches visited pages and
  serves them — or an offline page — without a signal, so the Work Bag works in
  the field even on a fresh load.
- **Background scheduler**: lead follow-up generation runs off the request path
  on a daemon timer, so it keeps working while the app sits unattended.

### People, roles & permissions
- **Employees** matched to the org chart, with first / last / optional nickname
  (duplicate-name guard on creation).
- **28 roles arranged as the org chart**; the New Employee form's **Roles** picker
  is an **indented org tree** (checkboxes) mirroring Vixinman's reporting structure —
  where a role sits shows who they report to, and rows with direct reports are
  bold. Multi-select, with an "Other role(s)" free-text field for anything off-chart.
- **Licenses & certifications** per employee, with expiry tracking that ties into
  project requirements (a project page can show whether staff hold the licenses it needs
  and warn when a credential has lapsed).
- **New-employee onboarding checklist**: an editable, company-wide step template
  (seeded with sensible defaults; add / edit / reorder / archive), tracked
  per employee on their profile's **Onboarding** tab with a progress bar and
  who/when stamps. Managers check steps off; everyone else sees status read-only.
  Onboarding is **initiated inside the New Employee form** — after the basic
  profile fields you pick **who's responsible** for finishing it (a GM or
  Supervisor, defaulting to the GM) and preview the steps; saving starts the
  checklist, notifies the responsible person, and drops you on the checklist to
  begin. The responsible person is shown on the Onboarding tab and can be
  reassigned there.
- **Emergency access lockout**: a GM — or a new GM-designated **Supervisor** —
  can instantly suspend **all** of an employee's access (they're signed out
  mid-session and blocked at login until reinstated); the account, login and
  data stay intact and a **↩ reinstate** restores it. Hierarchy guards: nobody
  locks out themselves, and a Supervisor can't lock out a GM or a fellow
  Supervisor. The roster flags suspended / supervisor at a glance.
- **In-app notifications**: a nav **🔔 inbox** with an unread badge. Used for
  pipeline turnovers, project cancellations, and security auto-locks; each
  notification **clears when the recipient accesses it**.
- **Role-based "My Dashboard"** — the sign-in landing, one role view at a time
  (mode switch for people who hold multiple roles); each person's **default view
  is remembered** (e.g. the GM defaults to the Executive overview). Every section
  is **collapsible**. The **Sales** viewport shows **In Planning** (projects in
  Planning), a **Leads** worklist (prospects not yet converted, with follow-up
  actions), and My tasks. The **Installation** (Foreman) viewport lists installs
  **bucketed by date** — This week / Upcoming / Wrap-up · unscheduled —
  with the install date leading, and trims **My tasks** to on-site field work.
  For **Sales-role** users that late-stage mode reads **🏁 Wrap-up** instead —
  Wrap-up-stage projects with **balance due** and remaining close-out steps — since
  Sales owns the walkthrough / final-invoice hand-off, not the install (the GM
  is exempt and keeps the Installation mode).
  The **Executive** (GM) viewport opens with a **Company overview**: pipeline
  counts by stage, money-in-flight tiles (contract / collected / outstanding /
  expenses across active projects), an attention row (approvals waiting, overdue
  tasks, stalled projects), a **Ready-for-design** queue (Planning-stage projects whose load
  survey is captured but design isn't finalized — the Sales→Designer hand-off),
  this week's installs, and a **Wrap-up worklist** (each project's balance due and
  remaining close-out steps). Each sub-section sits in its own panel.
- **Inventory database** (🗄 Databases → Inventory): Vixinman's stock of components
  seeded from the inventory workbook — **439 items across 15 categories** (PV,
  inverters, batteries, charge controllers, racking, …) with per-category specs, a
  canonical **~52-vendor** supplier list (names normalized from the workbook's
  typo'd entries), plus a standard **tool kit** (priced with big-box listings) and
  a **vehicles / heavy-equipment** list (each vehicle has a shop **nickname**). The
  table is editable in-app; item specs feed the Loads & Sizing calculator, and a
  `web_price` sits alongside the quoted `Cost` so a price check never overwrites
  your number. Battery, inverter, and PV spec data is research-calibrated, with
  product-page **purchase URLs** on current-install gear.
- **Stock ledger & stale-stock notice**: every stock change (received / used /
  count / adjust) flows through a single ledger that keeps each item's on-hand
  balance; items that go unused past a threshold surface a **stale-stock** notice
  on the Designer's dashboard. Items can also be **manually marked stale at will**
  (a 🕰 toggle in the inventory listing) regardless of the automatic rule —
  hand-flagged items show a **Stale** badge and join the review queue/count, and
  Keep or Discontinue clears the mark.
- **Barcode / asset registry**: generate and print **Code 128** labels, register
  serial numbers for **consumables** (hardware, components) and **non-consumables**
  (tools, PPE, trucks), and **scan** them in/out — including **phone-camera
  scanning** — to load a project's truck (two installers can load the same project from
  their own phones). Only the **Warehouse Manager** can mint new tags; loading a
  project needs no special permission.
- **Stock audit** (🧮 Audit stock): run a counting session — scan every tag on the
  shelf (camera or keyboard-wedge) and Compendium reconciles the scanned serials against
  the assets the database expects to be **In stock**. Audit **all stock** or scope it
  to one **category / type**. It flags — live and in a saved report — everything that
  doesn't line up: **unaccounted-for** items (expected but not scanned), items
  **scanned but unexpected** (checked out, retired, or out of scope), **unknown tags**,
  and **duplicate scans** — with an **exportable CSV** of the whole reconciliation.
  Every scan is logged per session and past audits are kept for reference.
- **Nav grouping**: the reference/data pages — **Backlog, Household Files, Rules
  Editor, L/P/C Directory, Inventory, Calculator Catalog**, plus **Cost model & finance**
  and **Closed projects** — are consolidated under a single **🗄 Databases** dropdown
  in the header; **Employees + Payroll** sit under a **👥 Team** dropdown; and
  **Log / Trash / Access** sit under a **🔧 Admin** dropdown.
  Each grouped dropdown shows only the items the user may reach and collapses to a
  plain link when only one applies. Keeps the top bar tidy.
- **Permissions**: the General Manager (identified by the GM role) has unfettered
  access and can grant individuals access to specific tools/functions **with an
  expiration date**. Admin tier sits below GM; granular grants everywhere else.
- **Deletion & trash**: deletes are GM-only (delegatable), prompt before
  deleting, and are **blocked with an error if the data is in use** elsewhere.
  Deleted items go to a **trash can** for review; permanent purge stays GM-only.
- **Employee offboarding**: admins can remove an employee with a confirm prompt
  that requires a reason for the audit log.
- **Logins**: per-user accounts with hashed passwords (**pbkdf2:sha256**, which
  also works in the packaged desktop build). **Usernames are case-insensitive**
  (passwords stay case-sensitive); the Accounts page scans for case-duplicate
  usernames. Sessions **auto-log-out after 12 hours of inactivity** (a sliding
  window that renews on each request).
- **Self-service password reset**: an employee can enrol **security questions**
  on their account page (answers stored as salted hashes, **case-sensitive**). A
  **"Forgot password?"** flow on the sign-in page asks a **random 2 of the 3**
  and lets them set a new password **with no admin approval**. Wrong answers are
  rate-limited; hitting the limit **auto-locks the account** and notifies the
  Supervisor(s) (or the GM if none). Suspended accounts can't reset here.

### Finance & billing
- **Per-project billing ledger** (💵 Billing tab): set the contract total and record
  every **income** (deposits, invoices, rebates) and **expense** (materials,
  permits, labor, subs) with a dollar amount, date, category, party, reference,
  method, and paid/outstanding status.
- **Receipts, invoices & bills**: each ledger entry can be tagged with the
  **source document** behind it — **Receipt** (proof of a payment made),
  **Invoice** (money billed to a customer, A/R), or **Bill** (money a vendor
  billed us, A/P). Picking one auto-sets the usual accounting flow (Invoice →
  Income/Outstanding, Bill → Expense/Outstanding, Receipt → Expense/Paid, all
  still editable). The Billing tab shows a **paperwork-on-file** tally (count +
  total for each type).
- **Payments table** on the Finance dashboard: every active project with Contract /
  Collected / Outstanding / Expenses / Net and a grand-total row.
- **NM gross-receipts-tax rate**: an optional per-project GRT rate, settable on the
  Billing tab, for projects where receipts are taxable (defaults to 0% for the solar
  deduction). Not tied to any invoice-generation flow — a plain rate field.

Customer-facing invoice generation and the project-transactions QuickBooks export
were removed (Piece 33, household reorg) — this app manages one household
directly, so there's no customer to invoice. The plain income/expense ledger
above still tracks project budgets; only the customer-invoice presentation
layer is gone. (Payroll's own QuickBooks export, unrelated, is unchanged —
see Payroll below.)
- **Cost Model Defaults** (🗄 Databases → Cost model & finance, Finance/Admin/GM):
  Vixinman's estimating template behind project pricing — six editable sections
  (**Equipment Inventory, Equipment Non-Inventory, Labor, Travel, Adders,
  Overhead**), each line **qty × cost × (1 + markup)**, seeded with the finance
  team's real figures and add/edit/delete-able. Equipment-Inventory markups price
  the project BOM; **Overhead (G&A)** applies on the whole subtotal. The page also
  holds the **NM county GRT rate table** (all 33 counties; a project auto-fills its
  GRT from its install county, overridable for the solar deduction) and shows a
  default "standard project" rollup.
- **Per-project estimate** (📐 Estimate tab, Finance/Sales/Design): builds a project's
  price against the cost model — one-click **prefill** pulls the default Labor /
  Travel / Adders / Non-Inventory lines, quantities are set per line, equipment
  comes from the BOM, Overhead applies on top, and a **suggested price** can be
  pushed straight to the contract total.
- **Pricing breakdown** (on the Billing tab): an internal cost-vs-margin summary
  (marked-up equipment, estimate sections, overhead, suggested price) visible to
  **Finance, Sales & Design** only — never on the customer copy. Change-order
  materials added after the deposit bill at the **marked-up customer price**.
- **Money formatting**: dollar amounts show a **thousands separator** everywhere
  (a comma appears for amounts ≥ $1,000).
- **Payroll**: employees **log their own hours** from the 🎒 Work Bag (by date,
  project, and **pay type** — usually captured right on the task they finished);
  supervisors **review and approve** them before they count. The pay schema is
  configurable — each pay type is a **multiplier** on the employee's base wage
  (roof time…) or a **flat $/hr** (travel time…), **overridable per employee**.
  **Overtime is automatic** — hours over the weekly threshold of OT-eligible time
  earn the OT premium (no manual OT entry). Only **Cary (GM)** and **Lisa (Payroll
  Manager)** can change pay rates.
- **Pay periods run Sunday → Saturday** (the default period is the most recent
  full week), overridable by date range.
- **Leave can't earn overtime**: approving vacation/PTO/sick time that would take
  an employee past the weekly cap is **blocked** unless the GM overrides it on the
  approval form (worked hours still earn OT normally).
- **Payroll reminder**: the Finance dashboard shows a **Tuesday–Thursday** nudge
  to run payroll each week until the period's hours are **confirmed and exported**.
- **Timesheets**: a per-employee, printable/CSV timesheet view of logged hours
  (a read-only lens on the same time data; payroll approval/export is unchanged).
- A pay-period summary rolls up hours + dollars per person with a QuickBooks CSV
  export.

### AI Assistant
- **💬 Assistant** (top bar): an in-app, **read-only** AI chat over the household's
  data. Ask about projects, tasks and the schedule and get a grounded answer;
  it can explain and summarize but **never changes anything**.
- **Claude and/or Gemini, selectable.** Add a key for either or both under **AI
  settings** (admin only); when both are set, staff pick the model per question.
- **Grounded, not guessing.** Answers come from a live, permission-scoped view of
  your data — the assistant looks things up with read-only tools (find projects by
  stage/county/overdue/contract, drill into one project, list
  tasks, look up staff) rather than inventing details.
- **Permission-scoped & private.** It only ever sees what the signed-in user is
  already allowed to see (pricing/contract figures are withheld from those who
  can't view pricing; pay is never exposed). **Online-only** — nothing is sent
  until a question is asked, and nothing is sent while offline.
- Setup is below under **[Setting up the AI Assistant](#setting-up-the-ai-assistant)**.

### Help & records
- **In-app Help** (❓ Help in the top bar): tutorials & FAQ for every feature,
  grouped by area with a contents list and expandable questions.
- **Audit log** of all changes (create/update/delete), with password fields
  redacted and never logged in plaintext.
- **NM directory** of authorities/utilities baked in for quick reference.

---

## Setting up the AI Assistant

The 💬 Assistant is **off until an admin adds an API key** — Compendium doesn't ship
with one. It uses your own account with Anthropic (Claude) and/or Google (Gemini),
so **you pay the provider per use** (both are inexpensive for this kind of Q&A).

**1. Get an API key** for whichever provider(s) you want:

- **Claude (Anthropic):** sign in at **console.anthropic.com**, add billing, and
  create an API key under **API Keys** (it looks like `sk-ant-…`).
- **Gemini (Google):** create a key at **aistudio.google.com** (API keys), or in
  your Google Cloud project (it looks like `AIza…`). Note which **model** your
  account offers (e.g. `gemini-2.0-flash`).

**2. Enter it in Compendium.** As an admin, open **💬 Assistant → ⚙️ AI settings** and:

- Paste the Claude key and/or the Gemini key. Pick a **default provider**.
- Choose the **Claude model** (Sonnet is the balanced default; Opus is the most
  capable and priciest; Haiku is the cheapest) and set the **Gemini model** to
  whatever your account provides.
- Save. Keys are stored **on this machine** (in your Compendium data folder), never in
  the program itself, and are only ever sent to the provider you choose.

**3. Ask a question.** Open **💬 Assistant**, type a question (e.g. *"Which projects are
in Project Prep?"*, *"What are my open tasks?"*, *"Bernalillo projects over $30k with an
overdue permit"*), and — if both providers are set up — pick the model to answer.

**What to know:**

- **Online only.** The assistant needs internet. Nothing is sent while offline, and
  nothing is sent until someone actually asks a question.
- **What leaves the building.** When a question is asked, Compendium sends that question
  plus the answer to a set of read-only lookups — **limited to what that person is
  already permitted to see** — to the chosen provider. Both Anthropic and Google
  offer "we don't train on your API data" terms; review them for your account.
- **Read-only.** The assistant can't edit, create, or delete anything.
- **Rotating/removing a key:** re-open AI settings; leave a key field blank to keep
  the saved key, type a new value to replace it, or tick **Remove** to clear it.

---

## Build history (high level)

- **v0.4** — renamed the app's other central entity: `employees` and its
  `employee_credentials`/`employee_files` child tables become
  `household_members`/`household_member_credentials`/`household_member_files`,
  every Python identifier and `/employees/` URL follows suit, and the 28-role
  solar org chart collapses to **Parent / Child / Assistant**. Access control is
  now a flat **`is_admin`** flag plus per-permission grants — no more GM/Admin
  tiers, no more roles auto-conferring permissions, and grants no longer expire.
  **Delete still always needs an explicit grant, even for admins** (that safety
  rail carries over unchanged). **Payroll, the onboarding checklist, and
  emergency access lockout are cut entirely** — a household doesn't run payroll
  or onboard new hires; the Work Bag's hours logging is now a single
  self-reported number, display-only, with no supervisor/Finance two-sign-off
  chain. The **dashboard drops its department mode-switcher** — every section
  (My tasks, active projects grouped by stage, backlog, procurement, permits,
  install-date buckets, company overview, payments) now renders for every
  signed-in member, all the time. Task auto-assignment by role is gone;
  generated tasks land unassigned on a roster small enough to hand-pick from.
  Added a reusable **External Helpers** contact roster (`/external-helpers`) for
  contractors/tutors/coaches who aren't household members. A meta-guarded
  `init_db()` migration upgrades an existing pre-rename database the same way,
  including backfilling `is_admin` from the old access-level/GM-role signal
  before the role text gets overwritten. See `HANDOFF.md` for the remaining
  reorg pieces (the `routine_tasks`/`project_tasks` split, etc.).

- **v0.3** — renamed the app's central entity end-to-end: the `jobs` table and its
  11 `job_*` child tables/14 `job_id` FK columns become `projects`/`project_*`, every
  Python identifier and `/jobs/` URL follows suit, and the pipeline stages are
  relabeled for a household: `Proposal → Job Prep → Installation → Inspections →
  Closing → Complete` (+ `Lost`) becomes `Planning → Prep → In Progress → Wrap-up →
  Done` (+ `Abandoned`) — permit sign-off/inspections/cert exams are steps within
  Wrap-up, not their own stage (the old Inspections and Closing stages merge). A
  meta-guarded `init_db()` migration upgrades an existing pre-rename database the
  same way, including the `pre_lost_status` snapshot used by cancel/reopen. Adds a
  new **`/projects` list page** (there was no way to browse every project since v0.2
  removed the client→job-list path) and its own nav entry. `job_name` (the database
  column) and the on-disk `uploads/job_<id>/` folder naming are deliberately left
  as-is — internal storage detail, not user-facing. See `HANDOFF.md` for the
  remaining reorg pieces — `employees`→`household_members` landed in v0.4.

- **Pieces 1–7** — Flask + SQLite skeleton; clients & jobs; rules engine;
  resource catalog; job versioning; per-job BPMN; materials & document filing.
- **Piece 8+** — search, statuses, logins, and service-ticket refinement.
- **Pieces 9–15** — desktop packaging & versioned footer; live search preview;
  split address fields; client edit history; Loads & Sizing as its own page.
- **Pieces 16–19** — org-chart staffing; roles/permissions (GM grants with
  expiry, Admin tier); trash + in-use checks; task→role assignment; standardized
  department-owned pipeline; role-based dashboards with a mode switch;
  case-insensitive usernames; first/last/nickname; employee offboarding.
- **Piece 20** — calendar (.ics) export; default 7-day task deadlines with a
  completion cascade; per-job pipeline progress widget.
- **Piece 21** — Finance viewport: per-job billing ledger, Payments dashboard,
  QuickBooks CSV; payroll (self-logged hours, approvals, configurable pay types,
  auto-overtime); permits/warehouse tuning; **receipts/invoices/bills** tagging
  feeding the QuickBooks reports; **Foreman/Installation viewport** (installs
  bucketed by date) + a field-focused, job-grouped Work Bag with **on-site photo
  capture** on photo steps, a **packing list**, and **timestamped field
  notes**.
- **Piece 22** — Work Bag packing list; Loads & Sizing **locks past Proposal**;
  **Executive (GM) company overview** (pipeline counts, money-in-flight tiles,
  attention row, Ready-for-design queue, this-week's installs, Closing worklist);
  **Databases / Team / Admin** nav dropdowns.
- **Piece 23** — **Inventory database** (439 items with specs, ~52 canonical
  vendors, tool kit, vehicles), in-app management + table redesign; battery /
  inverter / PV spec research calibration; vendor & make standardization; purchase
  URLs on current-install gear.
- **Piece 24** — inventory cleanup + Tools/Vehicles edit UI; **stock-usage ledger
  + stale-stock notice**; BPMN lanes aligned to real departments + a
  roles/permissions overhaul; **12-hour sliding auto-logout**; **offline service
  worker** (cold-start).
- **Piece 25** — **in-place editing** of add/delete-only records; **timesheets**;
  per-slot document-format restrictions; **background scheduler** for follow-up
  generation; **auto-renamed uploads** (`Name_What_Date`).
- **Piece 26** — **barcode / asset registry** (generate/print/scan, phone camera,
  crew truck-loading); Work Bag **receipt capture**; **grouped task board**; Loads
  survey tweaks + colour-coded appliance eras; **component auto-suggest** from
  inventory specs; **payroll reminder** + **leave-can't-earn-OT** rule + grouped
  My Tasks; **L/P/C Directory** consolidation + verbatim source text; Rules Editor
  / L/P/C Directory renames; GM defaults to the Executive overview.
- **Piece 27** — Calculator Catalog rename; **sample seed data removed** for a
  clean production database; **Sunday→Saturday pay periods**; QuickBooks exports
  moved to **per-job Billing**; **50/40/10 customer invoice generation** + **NM
  gross-receipts-tax** line + Vixinman remit-to + pay-scheme callouts; **Work Bag split**
  into a jobs landing + per-job page; **per-task Submit-as-done** with time by pay
  type + timeline.
- **Piece 28** — **photo steps** completed on their own take / review / submit
  screen (with the time capture), returning to the job's Work Bag when submitted;
  Job-Detail polish (bold L/P/C labels, Billing device file-upload, button/stage
  reorg); a **nav search** over clients & jobs (autocomplete, client name on job
  hits) and an **inventory search**; and a **stock-audit** tool (scan-and-reconcile
  against the registered assets, by category, with a saved/exportable discrepancy
  report).
- **Piece 28.6–28.7** — packaged-exe reliability: password hashing pinned to
  **`pbkdf2:sha256`** (works in a PyInstaller-frozen build, unlike scrypt's
  OpenSSL dependency) with a graceful login fallback; and a **first-launch data
  importer** that adopts an existing `job_creator.db` + `uploads` from a
  drop-in `Compendium-Import` folder (see `desktop/README-DESKTOP.md`).
- **Piece 28.8** — the importer now also runs when `~/Compendium` holds only a
  **blank starter database** (created by an earlier launch), backing that empty
  file aside first, so a prior run no longer blocks bringing in real data.
- **Piece 28.9** — the desktop app now writes any server error (HTTP 500) —
  full traceback + the request that caused it — to `~/Compendium/compendium-error.log`
  and shows a plain-English page pointing to it, so a crash on a teammate's
  machine can be diagnosed instead of vanishing into the console.

- **Piece 29 (Employees)** — three staff-management features:
  **emergency access lockout** (a GM or a new GM-designated *Supervisor* instantly
  suspends all of an employee's access, reinstatable, with hierarchy guards);
  **self-service password reset** via enrolled security questions (answers stored
  as salted hashes; a "Forgot password?" flow lets a locked-out user set a new
  password with no admin approval — suspended accounts excluded); and a
  **new-employee onboarding checklist** (an editable company-wide step template,
  seeded with sensible defaults, tracked per employee with a progress bar on the
  profile's Onboarding tab).
- **Piece 29.3** — password-reset hardening: security answers are now
  **case-sensitive** (matched exactly, like a password); each reset asks a
  **random 2 of the 3** enrolled questions; and hitting the wrong-answer limit
  **auto-locks the account** (the same emergency lockout) and posts an in-app
  **notification** to all Supervisors — or the GM(s) if there are none. Adds a
  lightweight notifications inbox with a nav 🔔 bell + unread badge.
- **Piece 29.4** — **pipeline-turnover notifications**: whenever a job advances
  to a new stage (from Proposal onward — new jobs, manual stage changes, and the
  install-date auto-advance), the department(s) that own the new stage are
  notified in their inbox. Each recipient's copy **clears the first time they
  access it** — either by opening the notification or by opening the job — and
  the person who triggered the move isn't notified.

- **Piece 29.5** — removed the redundant Administration dashboard mode.
- **Piece 29.6 (Finance data)** — a **Finance Settings** page (Finance/Admin/GM)
  holding the reference data invoices/BOM previously lacked: **NM county GRT
  rates** (all 33 counties; a job auto-fills its GRT rate from its install
  county, still overridable for the solar deduction), **equipment markup by
  category** (with an optional per-BOM-line override), and a **travel $/mile
  rate**. The job Billing tab gains a per-job **travel miles** field and an
  internal **pricing breakdown** (equipment cost vs. marked-up price, travel,
  suggested contract price) that never appears on the customer copy; change-order
  materials added after the deposit now bill at the marked-up customer price.

- **Piece 29.7** — the internal pricing breakdown is now visible to Sales &
  Design (who price/design jobs), not just Finance/Admin/GM.
- **Piece 29.8 (Cost Model Defaults)** — Finance Settings becomes a **Cost Model**
  page mirroring Vixinman's estimating sheet: six editable sections (Equipment
  Inventory, Equipment Non-Inventory, Labor, Travel, Adders, Overhead) seeded
  with the finance team's real figures, each line qty × cost × (1 + markup).
  Equipment-Inventory markups price the job BOM; **Overhead (G&A)** applies on
  top of each job's subtotal in the pricing breakdown; the Travel → Vehicle
  Trips line is the per-mile travel rate. The page shows a default "standard
  job" rollup, and the NM county GRT table stays alongside.

- **Piece 29.9 (Per-job estimate)** — a job **Estimate** tab (Finance/Sales/
  Design) builds the price against the cost model: one-click **prefill** pulls
  the default Labor / Travel / Adders / Non-Inventory lines, quantities are set
  per line, and equipment comes from the job BOM. It sums to a subtotal, applies
  **Overhead (G&A)**, and shows a **suggested price** that a button pushes to the
  contract total. `job_pricing` now = BOM equipment + estimate lines + overhead
  (travel moved from a flat per-job field into the estimate's Travel lines);
  catalog categories gained `mc4` so every BOM line maps to an equipment markup.

- **Piece 30.0** — dollar amounts show a **thousands separator** everywhere
  (comma for amounts ≥ $1,000) via `money` / `money0` Jinja filters applied
  across all templates; the **cost-model editor** moved out of the job Estimate
  tab into the **Databases** nav dropdown ("Cost model & finance").

- **Piece 30.1** — the rule **⚠ Verify / ⚠ Unverified** callout is now an
  explicit, human-editable field (a dropdown in the Rules Editor) instead of
  being inferred from caution words in the notes. Existing rules were backfilled
  from the old convention; a person can now add or remove the callout on any
  rule/compliance note directly.

- **Piece 30.2** — proper **job cancellation**: a "Cancel this job" control marks
  it Lost with a **required reason** (recorded in the audit log with who/when),
  and a cancelled job's open tasks are **hidden** from My Tasks, the task board
  and the Work Bag so they stop nagging the crew. A **Reopen** action restores
  the exact pre-Lost stage and its tasks. "Lost" was removed from the plain stage
  dropdown so every cancellation captures a reason.

- **Piece 30.3** — cancelling a job now **notifies everyone involved** so far
  (task assignees, time loggers, and the client's assigned rep) via the in-app
  inbox, and a GM/Admin **Closed jobs** review page (Databases nav) lists
  cancelled jobs with their reason/who/when and a one-click Reopen, plus
  completed jobs — the way cold leads are reviewed.

- **Piece 30.4** — inventory items can be **manually marked stale at will** (a 🕰
  toggle in the listing, `inventory.manage`), independent of the automatic
  zero-on-hand/unused rule. Flagged items show a **🕰 Stale** badge and join the
  stale review queue/count; Keep or Discontinue clears the manual mark.

- **v0.2** — removed the multi-client model entirely (the first piece of the
  household structural reorg): no more client profiles, lead pipeline, or
  cold-leads list — jobs belong to the household directly (`jobs.client_id`
  dropped). Replaced with a **household idea backlog** (`/backlog`) — Backlog /
  Started / Abandoned status, target date, proposed-by, budget estimate, and a
  hybrid reminder (monthly whole-backlog nudge + optional per-idea custom date)
  through the existing notifications inbox. Client-level document storage moved
  to flat **Household Files** (`/household-files`, no owner id needed). Cut
  customer-facing invoice generation (50/40/10) and the job-transactions
  QuickBooks export, since there's no customer to invoice — the plain
  income/expense ledger on each job's Billing tab stays. Home (`/`) merged into
  `/dashboard` (one view, two routes) since there's no more client roster to
  land on. See `HANDOFF.md` for the remaining reorg pieces —
  `jobs`→`projects` landed in v0.3, `employees`→`household_members` in v0.4.

- **v0.1** — reset the footer build counter from the solar-business "Piece N.N" scheme
  to plain semantic versioning, starting at `0.1`, coinciding with the rebrand to
  **Vixinman's Home Compendium** and the repo's move to
  [Rachel-Inman-88/Vixinman_Household_Compendium](https://github.com/Rachel-Inman-88/Vixinman_Household_Compendium).
  Everything below this line is inherited build history from the prior **Solbiz**
  (an unnamed solar installation company) codebase this app was rebranded from —
  kept for context on how the software got to its current structure, not
  describing the household product.

- **Piece 32.1** — the **Compendium Assistant can now look data up live** via read-only
  tools (function-calling), instead of relying only on the snapshot. The model may call
  `find_jobs` (filter by text / stage / county / rep / overdue / min-contract),
  `job_details` (one job's stage, tasks, materials, notes, contract), `find_clients`,
  `list_tasks` (assignee / overdue / stage), and `staff_directory` — chaining several to
  narrow a question (e.g. "Bernalillo jobs over $30k with an overdue permit"). Every tool
  is **permission-scoped** (contract/pricing figures withheld from non-pricing viewers, no
  pay ever exposed) and **read-only**. One tool-loop implementation drives **both Claude
  (tool_use) and Gemini (functionCall)**; tool errors are caught and handed back to the
  model to recover, and the loop is capped at 6 round-trips.

- **Piece 32.0** — **Compendium Assistant** (💬 in the top nav): an in-app, **read-only**
  AI chat over the business data. Ask about jobs, clients, tasks and the schedule and get
  a grounded answer. Highlights:
  - **Claude and/or Gemini, selectable** — add a key for either or both under **AI settings**
    (admin only); staff pick the model per question when both are set. Keys live in the
    local Compendium data folder (`meta` table), never in the exe.
  - **Grounded, not guessing** — each question is answered from a compact snapshot of the
    current state (jobs by stage, active jobs, the user's tasks, overdue counts), so the
    model doesn't invent data; it's told to say when something isn't in view.
  - **Permission-scoped** — the snapshot only ever contains what the **signed-in user is
    already allowed to see**; pricing/contract totals are withheld from anyone who can't
    view pricing, and the assistant can't change anything (read-only).
  - **Online-only, degrades gracefully** — nothing is sent until a question is asked or
    while offline; a missing key or lost connection shows a clear message.
  - Pure-stdlib provider layer (`ai_assistant.py`) so the frozen exe stays light.

- **Piece 31.8** — the **customer payment-schedule (50/40/10) callout** moved off the
  dashboard and into the job **Estimate** tab, where it belongs — shown only to
  **Sales & Finance** (and GM/Admin) and only **before the contract is signed**
  (`contract_amount` still 0), so it disappears once the customer has agreed and terms
  are set. Also, the job form's **Payment** field (formerly the free-text "Cost method")
  is now a dropdown: **Pay in full** or **Financing** (legacy free-text values on existing
  jobs are preserved).

- **Piece 31.7** — dense multi-column tables (cost model, payroll, audit log, estimate/
  billing, etc.) **restack into labelled rows on phones** (≤560px) instead of getting
  their right-hand columns cut off. Each cell is auto-labelled from its own table's
  header by a small script, so no template needed per-cell markup, and only tables with
  3+ columns restack — narrow ones are left alone. Desktop and tablet are unchanged.

- **Piece 31.6** — **responsive layout** for phones and tablets (Windows, Android, iOS),
  with the desktop view unchanged. The top nav collapses behind a **☰ Menu** hamburger
  into a full-width vertical panel below ~820px (dropdowns expand inline there);
  on desktop it stays the same inline row (via `display:contents`, so no markup was
  duplicated). Wide tables are auto-wrapped in a horizontal-scroll container so they
  never stretch the page, images are capped to their container, profile detail grids
  and button rows collapse to one column, and form fields render at ≥16px on mobile to
  stop iOS from zooming on focus. Verified with headless Chromium at 1280px and 390px —
  no horizontal page overflow at either width.

- **Piece 31.5** — moving a job **forward a stage now auto-fills that stage's tasks**.
  When a job turns over (Proposal → Job Prep and onward), Compendium generates the
  entered stage's process steps as To-do tasks, **auto-assigned by role/lane** and
  dated, so the receiving department lands with its work already populated — on top
  of the existing stage-turnover notification. Only the entered stage's steps are
  created, existing tasks are skipped (no duplicates), and Complete adds nothing. The
  manual **Generate tasks** button still produces the whole list at once; both now
  share one generator (`_generate_job_tasks`, with an optional `only_status` filter).

- **Piece 31.4** — swapped the three easiest-to-research **security questions**
  (mother's maiden name, favorite sports team, first school) for harder-to-phish,
  Vixinman-flavored ones (coffee order, favorite Thanksgiving dish, red or green chili).
  Anyone already enrolled keeps their stored questions — resets read each user's
  saved questions, not this menu — so nothing breaks; the change only affects new
  or re-done enrollments.

- **Piece 31.3** — the New Employee / Onboarding-tab owner picker now **says so** when
  a submitted responsible party doesn't qualify (only a GM or Supervisor can), naming
  the rejected pick and who ended up responsible, instead of falling back silently.

- **Piece 31.2** — onboarding is now **initiated inside the New Employee form**:
  after the basic profile fields, a **🚀 Onboarding** section lets you pick who's
  **responsible** for completing it (a GM or Supervisor, defaulting to the GM) and
  previews the steps. Saving the profile starts the checklist, **notifies** the
  responsible person, and lands you on their Onboarding tab. That tab now shows who's
  responsible and lets a manager **reassign** it (`onboarding_owner_id` on employees).
  If a submitted owner doesn't qualify (only a GM or Supervisor can), the app now
  **says so** — a notice names the rejected pick and who ended up responsible
  instead (the GM), rather than falling back silently.

- **Piece 31.1** — in the Calculator Catalog, era badges are colour-coded: **Modern**
  stays green, **Vintage** is now orange, so the two are distinguishable at a glance.

- **Piece 31.0** — on **desktop**, nav dropdowns (Team / Databases / Admin) now close
  when another opens, when you click away, or on Escape — so they can't overlap and
  cause misclicks. **Touch/mobile** keeps the original sticky behaviour (guarded by
  `matchMedia`).

- **Piece 30.9** — the New Employee **Roles** picker is now an **indented org-chart
  tree** (checkboxes) matching the finance team's outline; roles were renamed to
  the outline's exact names (Warehouse **Assistant**, **Human Resources** Manager,
  **Sales &amp; Marketing** / **Research &amp; Development** Manager) with a one-time
  migration of existing employee records, and two roles (**Hiring and Performance
  Coordinator**, **Product Portfolio Manager**) are selectable with no dashboard of
  their own.
- **Piece 30.8** — **Boards** (📋 in the top nav): stand-alone to-dos not tied to
  a job or client (clean the bathroom, call a vendor, …). Assign / **send** one
  to a teammate (they're notified), **log time** on it (with a running total),
  keep a **notes log** you can add to over time, set priority/due/status, and
  filter by Mine / All / Unassigned.
- **Piece 30.7** — an in-app **❓ Help** page (top nav) with a first-draft set of
  **tutorials & FAQ** covering every feature, organized by area with a contents
  list and expandable Q&A.
- **Piece 30.6** — the GM is exempt from the Sales "Closing" relabel (keeps the
  Installation mode).
- **Piece 30.5** — for anyone holding a **Sales** role, the dashboard's
  **Installation** mode is presented as **🏁 Closing** and shows Closing-stage
  work (jobs in Closing with **balance due** and the remaining close-out steps),
  reflecting Sales's real late-pipeline role. Non-Sales users keep the
  install-crew Installation view unchanged. **The GM is exempt** — a General
  Manager keeps the Installation mode even if they also hold a Sales role.

Data lives in `job_creator.db`; uploaded documents live in `uploads/`.
