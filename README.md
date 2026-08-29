# 🦊 Compendium

**Compendium** — the Vixinman household's task/project manager. Create project
profiles directly for the household, and automatically surface the right resources
(certifications, permits, prerequisites, links, phone numbers, docs) based on each
project's fields — then run the whole project through a standardized, role-based pipeline.
Recurring internal obligations (taxes, homeschool registration) and someday/maybe
ideas each have their own place, so nothing has to live on a project to be tracked.

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

**To let a phone on the same WiFi reach it** (for beta-testing), set
`COMPENDIUM_HOST=0.0.0.0` before starting it instead of running `python app.py`
plain — then open `http://<this-computer's-LAN-IP>:5000` on the phone (find the
LAN IP with `ipconfig` on Windows, look for the WiFi adapter's IPv4 address).
Type the `http://` explicitly — some phone browsers try `https://` automatically
for a bare IP address and fail with a "can't provide a secure connection" error.

**Running it all day, reachable from anywhere** (not just the home WiFi) is a
separate setup — a small VPS with its own domain and HTTPS — covered in
[DEPLOY.md](DEPLOY.md). The local/LAN setup above still works and is meant to
stay available as a backup even once a VPS is running.

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
- **Project profiles** belong to the household directly, with full field capture,
  including a **project category** (Home Improvement / Personal Improvement) and a
  **Subcategory** dropdown that cascades from it — Home Improvement: Building,
  Landscaping, Gardening, Maintenance & Repair; Personal Improvement: Education,
  Health, Habit, Relationship, Misc — a fixed vocabulary (not free text) so the
  Requirements Engine has something reliable to match rules against.
- **Owner (Piece 68)**: every project has an Owner — defaults to whoever
  creates it, reassignable anytime from the General tab (`projects.manage`
  permission required to change it; everyone who can view the project can
  see who it is). Distinct from task assignment — a project can be
  "owned" by one person while other household members work individual
  tasks on it.
- **Requirements Engine** — project selections → the certifications, permits, and
  prerequisites that apply, across two pages:
  - **Requirements Editor** (`/rules`): the editable catalog of resources (links,
    phone numbers, docs, accepted file formats), grouped by category
    (Certification / Permit / Prerequisite / Link / Phone / Doc). Each rule can
    also carry optional, purely informational **cost / time / maintenance notes**.
  - **Requirements Library** (`/directory`): a read-only lookup filtered by project
    type. Shared requirements are **consolidated** — a requirement needed by more
    than one selection shows **once** with every triggering scenario listed
    beneath, instead of repeating. Prerequisite rules can also carry the
    **verbatim source text**, shown above the shorthand + source link.
  - **Standalone recurring requirements**: a rule can skip the project condition
    entirely and instead repeat on its own interval — for internal household
    obligations that aren't tied to any project (taxes, homeschool registration).
    These show on the Requirements Editor and on the dashboard's **My
    requirements** card, with the same assign/mark-done/reminder mechanics as
    Chores.
- **Verbatim source text** is an editable per-rule field for capturing the exact
  wording from the code/source, surfaced on the Requirements Library.
- **Verification callouts**: a rule can carry a visible **⚠ Verify / ⚠ Unverified**
  chip (with a legend) so anyone using it knows what to confirm before relying on
  it. This is an **explicit, editable field** in the Requirements Editor (a
  dropdown: none / Verify / Unverified) — add or remove the callout on any rule
  at will.
- **Project edit history / versioning** for recordkeeping.
- **Electric loads** is a plain free-text field on the project (e.g. "3-ton AC,
  well pump, shop sub-panel") — the **Planning stage can't advance until it's
  recorded**. (The structured PV/battery/inverter electrical-sizing calculator
  that used to live here — a per-project load survey, a bill of materials, an
  appliance/component catalog — was solar-installation-specific and has been
  cut entirely.)
- **Materials lists** per project (status: Needed → Quoted → Ordered → Backordered →
  Received → On hand → Installed) and **document upload/storage** with
  per-requirement filing coverage. The project's **Requirements tab** leads with
  **Permits** — each with an **inline upload slot** to view the requirement and
  file the document in one place — with certifications and prerequisites
  collapsed below. The **Permits dashboard** shows a **permits-filed X/Y** column;
  the **Purchasing dashboard** shows a **procurement rollup** of materials by
  status across Prep-stage projects.
- **Per-slot upload formats**: a document slot can restrict its accepted file
  types (e.g. a permit slot to PDF), enforced on upload.
- **Auto-renamed uploads**: every uploaded file is renamed to a self-describing
  `Name_What_Date` scheme for recordkeeping (project docs, household files,
  household-member files, and field photos each get their own pattern); the friendly name is what
  shows and downloads, while the on-disk name stays collision-safe.
- **In-place editing** for the add/delete-only records (rules, appliance &
  component catalog, credentials, load items/rooms, BOM lines) — an ✎ edit
  pre-fills the record to save back over the original.
- **Exportable project report**.

### Pipeline, tasks & scheduling
- **Standardized pipeline**: Planning → Prep → In Progress → Wrap-up → Done
  (plus Abandoned) — a stage advances once its own tasks are done; nothing
  auto-advances a project on its own. Requirements-filed coverage (X/Y) and
  the materials/procurement rollup are shown alongside, for any stage that
  has applicable requirements or materials on file.
- **Per-project progress widget** — a segmented progress bar (one per project) that shows
  at a glance where the project sits in the pipeline, with the **next step called
  out**. Appears on the dashboard and each project's header.
- **Pipeline-turnover notifications**: whenever a project advances to a new stage
  (from Planning onward — new projects and manual stage changes), **every
  household member with a login** is notified in their in-app inbox. Each
  recipient's copy **clears the first time they access it** (opening the
  notification or the project); the person who made the move isn't
  notified, and backward moves don't fire.
- **Project cancellation (Abandoned) with a reason**: a "Cancel this project" control marks it
  **Abandoned** with a **required reason** recorded in the audit log (who/when), and
  remembers the stage it was at. A cancelled project's **open tasks are hidden** from
  My Tasks, the task board, and the Work Bag so they stop nagging anyone —
  nothing is deleted. **Everyone involved so far** (task assignees, time loggers)
  is notified. A **↩ Reopen** action restores the exact prior
  stage and its tasks. ("Abandoned" is removed from the plain stage dropdown so every
  cancellation captures a reason.)
- **Closed projects review** (🗄 Databases → Closed projects, Admin): a
  management view of **cancelled** projects — reason, who/when, prior stage
  — each with a one-click Reopen, plus a list of **completed** projects.
- **Tasks are added manually** — there's no auto-generated process/pipeline chain.
  A **+ Add task** form on the project's Tasks tab is the only way tasks appear;
  assign one to a household member (or leave it unassigned) at any point.
- **Sections (Piece 67)**: an optional, one-level-deep grouping for a
  project's tasks — a major phase ("Tow old tractor") containing its own
  smaller subtasks — independent of each task's own pipeline stage.
  Deleting a section detaches its tasks (ungrouped, not deleted). A task
  can also carry a 🚩 flag indicating it's been discussed in the 🧠 Plan
  tab's chat.
- **Default task deadlines**: a new task defaults to **7 days out**; when a task is
  marked Done, the next open task on the project is re-defaulted to 7 days after
  that completion. Hand-editable per task.
- **Calendar export (.ics)**: download your task due dates, install dates, and
  appointments (`/calendar/my.ics`) or a single project's dates
  (`/projects/<id>/calendar.ics`) and import into Google Calendar (or
  Outlook/Apple). Appointments with a time export as real timed events, not
  just all-day placeholders. Stable IDs so re-importing updates events
  instead of duplicating.
- **Appointments** (📅 in the top nav): a scheduled date (and usually time)
  that isn't a recurring Chore and isn't tied to a project — a doctor's
  visit, a delivery window, a trip. Optional location, optional assignment
  to one household member (or left for the whole household), and optional
  **recurrence** (checkups, etc.) using the same completion-driven cadence as
  Chores — mark one done and, if it repeats, the next occurrence is
  auto-computed; if it's one-time, it just drops off the upcoming list.
  Filter by Mine / All / Unassigned and Upcoming / All. A **📅 Upcoming
  appointments** card on the dashboard shows what's coming up, and reminders
  land in the same notifications inbox as Chores and Requirements. Can be
  **linked to a Contact** (a person or organization) — a "＋ Add
  appointment" quick-link on a contact's row starts a new one already
  linked to it.
- **Work Bag** for on-site work — an offline-capable field tool that shows **only
  on-site field work** (install & inspection); office/scheduling steps stay on the
  dashboard. It opens on a **projects landing** that lists just the projects in the
  bag (name, install date, open-task count); tapping a project opens
  its **own page** with that project's tasks, plus hours, receipts, and notes pinned
  to it.
- **"Load Bag"**: every active project's dashboard card carries a **🎒 toggle**
  (add/remove yourself from that project's Work Bag directly, independent of
  whether you have a task assigned on it) and a **⬇ Load tasks** button (claims
  every currently *unassigned* task on the project for you; tasks already
  assigned to someone else are left untouched). A bagged project's other
  people's tasks appear in your Work Bag too, but read-only — no Submit/Mark-
  done controls, since the field-sync endpoint only ever accepts changes to
  your own tasks.
- **Submit-as-done with a single hours total**: instead of a status dropdown, each
  task has a single **✓ Submit as done** (and a **⚠ Can't finish** → Blocked).
  Submitting captures **the time it took** as one number, held for **whoever has
  the "approvals" permission** to approve — a single review step (this same
  permission also covers approving Wishlist requests);
  there's no payroll behind it (display-only recordkeeping). All edits are saved
  on-device and submit when back online.
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
  truck before they leave.
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
  priority / due date (with an **optional time**, e.g. "Tuesday, 4pm" —
  the overdue badge still keys off the date alone, not the exact time) /
  status. Filter by Mine / All / Unassigned.
- **Board collaborators**: beyond the single "sent to" assignee, any number
  of other household members can be added as **collaborators** on a board
  — each is notified when added, shows up under their own "Mine" filter,
  and can see and check off the same card. Lighter-weight than Projects'
  task assignment — just a shared to-do, no separate collaborator
  permissions.
- **Offline cold-start (service worker)**: the app caches visited pages and
  serves them — or an offline page — without a signal, so the Work Bag works in
  the field even on a fresh load.
- **Background scheduler**: lead follow-up generation runs off the request path
  on a daemon timer, so it keeps working while the app sits unattended.

### People, roles & permissions
- **Household members** (👨‍👩‍👧 Family), with first / last / optional nickname
  (duplicate-name guard on creation) and a simple role: **Parent, Child, or
  Assistant** (Assistant = a household member with their own login who isn't a
  Parent — not the same as an **External helper** below, who isn't a household
  member at all). Replaces the original solar-shop's 28-role org chart —
  a household doesn't need a reporting structure.
- **Licenses & certifications** per household member, with expiry tracking that
  ties into the **Requirements Engine** (a project page can show whether anyone
  in the household holds the certifications it needs, and warn when one has
  lapsed).
- **Contacts** (🧰 Databases → Contacts, was "External Helpers"): a reusable
  roster for people (contractors, tutors, coaches) **and organizations**
  (subscription services, co-ops, utilities). A **Type** toggle switches the
  form between the two: a Person keeps the original name/specialty/phone/
  email/notes; an Organization adds website, account/member number, a main
  contact person (name/phone/email), and a renewal date. Each contact can
  have **Appointments linked to it** — a "＋ Add appointment" quick-link on
  its row pre-fills a new appointment and links it, and the row shows its
  upcoming-appointment count + soonest date. Doubles as the household's
  vendor/contractor directory (electricians, plumbers, warranty lines) as
  well as a place to track memberships and subscriptions.
- **In-app notifications**: a nav **🔔 inbox** with an unread badge. Used for
  pipeline turnovers, project cancellations, chore/requirement reminders, and
  security notices; each notification **clears when the recipient accesses it**.
- **One unified dashboard** (📊 My Dashboard) — the sign-in landing. Parent and
  Assistant see a household-wide **overview** (**projects by family
  member** — one row per person, their active projects as icon/color-
  coded chips by pipeline stage, Piece 64; an owned project (Piece 68)
  shows a 👑 marker so ownership stands out from just having a task on
  it — money-in-flight tiles,
  **upcoming payments due within a month**, an attention row, a wrap-up
  worklist), plus **Procurement**, active
  projects grouped by stage, the **Backlog**, a **🗂 Productivity
  Overview** card, and **My requirements**. (The full per-project
  Payments table lives on the **💰 Money** page instead, Piece 62/63.)
  Productivity Overview (Piece 61) consolidates Appointments (split into
  **Today / Tomorrow / Next 2 weeks** tiers — an overdue appointment folds
  into Today with its badge instead of disappearing), Chores, Boards
  (assignee or collaborator), and Tasks into one card, alongside a real
  **Month Calendar** grid with markers for every due date and prev/next
  navigation. **A Child gets a different dashboard instead** (Piece 53):
  the household overview, Procurement, Backlog, and Productivity Overview
  are replaced by a personal **🗓 My schedule** widget (Today / Tomorrow /
  Next 2 weeks, merging their own tasks, chores, and appointments), and
  the stage-listing cards only show projects they actually have a task
  on. Every section is **collapsible**.
- **Inventory database** (🗄 Databases → Inventory): ships **empty** on a fresh
  install — no pre-seeded solar catalog, vendor list, tool kit, or vehicle
  fleet; items get added as the household actually needs them. Per-category
  spec fields still drive the add-item form, and the table is editable in-app.
- **Stock ledger & stale-stock notice**: every stock change (received / used /
  count / adjust) flows through a single ledger that keeps each item's on-hand
  balance; items that go unused past a threshold surface a **stale-stock**
  notice. Items can also be **manually marked stale at will** (a 🕰 toggle in
  the inventory listing) regardless of the automatic rule — hand-flagged items
  show a **Stale** badge and join the review queue/count, and Keep or
  Discontinue clears the mark. (Barcode/asset-tag scanning and stock audits —
  built for a multi-person crew truck-loading parts — were cut; they didn't
  fit household scale.)
- **Nav grouping**: the top nav bar is organized into dropdowns rather than
  one link per feature — **✅ To-do** (Tasks, Boards, Chores, 🔔
  Notifications, Appointments — the unread-notification count shows right on
  the dropdown itself), a standalone **🎒 Work Bag** button (Piece 53: pulled
  out of the Household dropdown so it's one click for everyone, not two),
  **🏠 Household** (💰 Money — a financial overview linking to Budget/
  Loans/Savings, Approvals, Drafts, and 👨‍👩‍👧 Family — the
  household-member roster/roles/accounts page; the pending-approvals count
  shows on the dropdown for anyone who can approve), **🗄 Databases**
  (Projects, Backlog, Household Files, Contacts, Requirements Editor,
  Requirements Library, Inventory, Wishlist, plus admin-only Closed
  projects), and **🔧 Admin** (Log / Trash / Access). Each dropdown shows
  only the items the user may reach and collapses to a plain link when only
  one applies. **Family, Household Files, and the Requirements Editor are
  genuinely gated** (Piece 53), not just hidden links — a Child can't reach
  them by direct URL either.
- **Permissions**: a flat **`is_admin`** flag — admins get every tool except
  **Delete**, which always needs an explicit grant even for an admin.
  Non-admins get only what's individually checked off for them on the
  **🔐 Access** console (manage rules, manage the catalog, manage inventory,
  manage household members & accounts, approve field work, view the audit
  log, manage finances, manage projects, see the full FAQ, or delete).
  **Roles pre-fill a default bundle** (Piece 51): Parent and Assistant both
  get everything but Delete, Child gets none of it by default — set once as
  real grants when a person is added or their role changes, and always
  still editable per person from there afterward (additive only: changing
  someone's role never removes a grant they already had). **Assistant is
  meant for an AI agent's own account** (Piece 52) — it can read everything
  a Parent can, but every write it makes is captured as a **draft** on the
  🗒 Drafts page instead of landing directly; a Parent/Admin reviews each
  one and Approves (applies it for real) or Discards it. No tiers above
  admin, and grants don't expire.
- **Project documents follow task assignment, for a Child** (Piece 53): a
  Child can still view any project's general info and tasks regardless of
  assignment, but a project's filed **Documents** (and the Requirements
  tab's inline permit filings) only show if they have a task on that
  specific project — Parent/Admin/Assistant always see everything. A
  Child's own already-filed field photos and billing receipts stay visible
  to them even if their task assignment changes later.
- **Deletion & trash**: deleting anything needs the explicit **Delete**
  permission (even an admin doesn't have it by default), prompts before
  deleting, and is **blocked with an error if the data is in use** elsewhere.
  Deleted items go to a **trash can** for review; restoring or permanently
  purging also needs Delete.
- **Household member offboarding**: an admin with `household.manage` can
  remove a member with a confirm prompt that requires a reason (captured in
  the audit log). Blocked if they have field-work submissions on record, so
  approved-hours history isn't lost; their tasks are unassigned rather than
  deleted.
- **Logins**: per-user accounts with hashed passwords (**pbkdf2:sha256**, which
  also works in the packaged desktop build). **Usernames are case-insensitive**
  (passwords stay case-sensitive); the Accounts page scans for case-duplicate
  usernames. Sessions **auto-log-out after 12 hours of inactivity** (a sliding
  window that renews on each request).
- **Self-service password reset**: a household member can enrol **security
  questions** on their account page (answers stored as salted hashes,
  **case-sensitive**). A **"Forgot password?"** flow on the sign-in page asks a
  **random 2 of the 3** and lets them set a new password **with no admin
  approval**. Too many wrong answers ends that reset attempt and notifies
  every admin with a login, so one of them can reset the password directly —
  there's no account-level auto-lock (that mechanism went away with the
  emergency-lockout system it used to belong to).

### Wishlist
- **🎁 Wishlist**: anyone can add something they want, with an optional link
  to an existing **Inventory item** ("more of this"), a **Project**, and/or
  a **Contact** — all three independent and optional, all at once if
  wanted. Every item sits as **Pending** until a Parent/Admin (the same
  "approvals" permission the Work Bag's field-work approvals already use)
  approves or rejects it. **Approving doesn't do anything automatic** — no
  Inventory row gets created for you — it just flips status so the
  household knows it's OK to buy. Filter by Mine/All and Pending/All.
- **Lives primarily in Inventory**: Wishlist has no standalone top-level nav
  link. It's reached from the **📦 Inventory** page's toolbar (**🎁 Wishlist**
  button) or per-row (**🎁** next to any item pre-fills "more of this"), plus
  a plain entry in the **🗄 Databases** dropdown — keeping the top nav bar
  from growing a link per feature.

### Finance & billing
- **Per-project billing ledger** (💵 Billing tab): record every **income**
  (reimbursements, rebates, gifts — free text with suggestions, Piece 74)
  and **expense** (materials, permits, labor, subs — a fixed category
  list) with a dollar amount, date, category, party, reference, method,
  and paid/outstanding status.
- **Receipts, invoices & bills**: each ledger entry can be tagged with the
  **source document** behind it — **Receipt** (proof of a payment made),
  **Invoice** (money billed to a customer, A/R), or **Bill** (money a vendor
  billed us, A/P). Picking one auto-sets the usual accounting flow (Invoice →
  Income/Outstanding, Bill → Expense/Outstanding, Receipt → Expense/Paid, all
  still editable). The Billing tab shows a **paperwork-on-file** tally (count +
  total for each type).
- **Payments table** on the **💰 Money** page (Piece 62): every active project
  with Collected / Outstanding / Expenses / Net and a grand-total
  row. **Gated by the `finances.manage` permission (Piece 51)** — a Child has
  none of it by default, so this table (and the project page's whole Billing
  tab) don't render for them at all. The dashboard's own Household overview
  card shows a shorter **Upcoming payments** list instead (Piece 63) —
  Outstanding project expenses due within a month, not the full table.
- **Money invested / budget** (Piece 54, relabeled Piece 65 — was "Estimated
  cost"): a Planning-phase ballpark figure — set on the general project form,
  shown on the General details tab (`finances.manage`-gated like every other
  dollar figure). Compared against actual expenses logged so far on the
  dashboard's "Anticipated spending" tile.
- **Money formatting**: dollar amounts show a **thousands separator** everywhere
  (a comma appears for amounts ≥ $1,000).

Customer-facing invoice generation and the project-transactions QuickBooks export
were removed (Piece 33, household reorg) — this app manages one household
directly, so there's no customer to invoice. **Payroll — pay types, overtime,
pay periods, timesheets, the payroll reminder, and its own QuickBooks export —
was cut entirely** (Piece 35): a household doesn't run payroll. Field hours
logged from the Work Bag are a single self-reported number, held for a
Parent/Admin's approval, with no pay calculation behind it. **The Cost Model
estimator, the NM gross-receipts-tax rate table, and the per-project Estimate
tab were cut entirely** (Piece 40): all of it priced a job for a paying
customer — equipment markup percentages, a 33-county tax table, an internal
cost-vs-margin breakdown — with no household equivalent. What's left is
exactly what a household budget needs: the plain income/expense ledger
above, gated by `finances.manage` (Piece 51) — visible to whoever's granted
it (Parent and Assistant by default, not Child). An Assistant can still see
every figure, but editing anything here goes through a draft first (Piece
52), same as everywhere else it can write. **The project "Contract" concept
itself (a customer's agreed total price) was removed entirely in Piece 73**
— confirmed via the real household data that it had never been used once;
Collected/Outstanding/Expenses/Net were already fully driven by the ledger
above, independent of it the whole time.

### Household Budget
- **💵 Budget**: a household-wide income/expense ledger for spending that
  isn't tied to any project (groceries, utilities, subscriptions) —
  completely separate from each project's own Billing tab. Each transaction
  can carry an **optional receipt photo or PDF** (unlike the Work Bag's
  field receipt capture, a receipt here isn't required — not every household
  expense has one worth keeping) and an **optional link to a Contact**.
  **Budget categories** are a monthly target amount per category, shown
  against actual spending for the selected month with a simple over/under
  progress bar. Filter transactions by This month / All; pick any month to
  review with the month selector.
- **Paid/Outstanding status** (Piece 54): each transaction has a status,
  toggleable with one click, matching the vocabulary the per-project Billing
  ledger already uses — new transactions default to Paid. Feeds the
  dashboard's "Unpaid expenses" tile, which now combines both ledgers.
- **Category suggestions**: the category field is still free text, but now
  offers suggestions (Groceries, Utilities, Subscriptions, **Discretionary
  Spending**, Other) via a browser-native autocomplete list — type anything
  else if none fit.
- **At-a-glance reporting** (Piece 55): four hand-rolled SVG visualizations
  — no charting library anywhere in this app, so every chart is computed
  server-side and rendered as inline SVG (works offline, no CDN). All four
  combine **both** the household Budget ledger and the per-project Billing
  ledger:
  - **Expenses by category** — a donut chart for the currently selected
    month, top 5 categories + an "Other" bucket.
  - **Anticipated cash flow** — a forward-looking projection (default 3
    months, adjustable) combining Outstanding transactions from both
    ledgers with Budget's recurring monthly targets. Shows expected net
    flow per month, not a running account balance — this app has no
    concept of a starting bank balance anywhere.
  - **Income vs. expense trend** and **spending by category over time** —
    historical monthly bar charts, default 6 months back, adjustable.

### Loans
- **💳 Loans**: named loan accounts (a car loan, a mortgage) — each has a
  running balance computed live from its own entry ledger, not typed in as a
  single number. Record a **Payment** (reduces the balance) or a **Charge**
  (increases it — a fee, or an additional draw), each with an optional
  photo/PDF statement attachment. An account with entries can't be deleted
  until they're removed first (same in-use safety rail as everywhere else).
  The account detail page shows a **balance-history chart** (running
  balance over every entry); the list page totals the balance across every
  account.

### Savings
- **🐷 Savings**: named savings accounts (an emergency fund, a vacation
  fund), same shape as Loans — a running balance from **Deposit**/
  **Withdrawal** entries, an optional goal amount. When a goal is set, the
  account detail page shows a **progress bar** toward it (caps visually at
  100% — going over a savings goal is a good thing, not flagged like an
  over-budget category); it also gets the same balance-history chart as
  Loans, and the list page totals both the balance and the goal across
  every account.

### AI Assistant
- **💬 Assistant** (top bar): an in-app, **read-only** AI chat over the household's
  data, powered by **Claude** (Anthropic). Ask about projects, tasks and the
  schedule and get a grounded answer; it can explain and summarize but
  **never changes anything** on its own (see the draft-proposal bullet below
  for the one narrow exception, which still needs a human's approval).
- **Up to 5 saved conversations per person (Piece 76).** A small strip above
  the chat lets you switch between your last 5 conversations (auto-titled
  from each one's first question) or start a fresh one — starting a 6th
  quietly drops the oldest, keeping this a quick-reference tool rather than
  an open-ended chat log.
- **📝 Propose a new project (Piece 76).** If a conversation clearly shapes up
  a real new project, the assistant can suggest creating it; a **Send as
  draft** button appears, and clicking it adds a Pending entry to the same
  🗒 Drafts page described below for a parent to approve or discard — nothing
  is created until then.
- **🔁 Retry on failure.** If a question fails (dropped connection, provider
  hiccup), a Retry button appears next to the error and resends the exact
  same question — no retyping or copy/pasting it back in. The per-project
  **🧠 Plan** tab's chat has the same Retry button (Piece 66) — it reuses
  the already-saved message on retry instead of inserting a duplicate.
- **🔁 Repeat last (Piece 67).** A second, always-available button
  (not gated on a failure) re-asks your most recent question fresh — handy
  after something else changed and you want an updated answer. Each repeat
  is a genuinely new turn, not a resend of a failed one.
- **🧠 Plan tab: sections + task-flagging (Piece 67).** The AI can suggest
  a whole **section** of work — a major phase ("Tow old tractor") with its
  own smaller subtasks nested one level deep — as a single bordered
  suggestion block, alongside plain ungrouped task suggestions as before.
  It can also **flag** an existing task the conversation is discussing; a
  one-click confirm sets a real, persisted 🚩 indicator visible on that
  task in the Tasks tab, even after leaving the Plan tab.
- **Grounded, not guessing.** Answers come from a live, permission-scoped view of
  your data — the assistant looks things up with read-only tools (find projects by
  name/stage/overdue status, drill into one project, list
  tasks, look up staff) rather than inventing details.
- **Permission-scoped & private.** It only ever sees what the signed-in user is
  already allowed to see (Piece 52 closed a real gap here: the assistant
  used to include finance figures unconditionally, a text-based way around
  the Budget/Billing gate); pay/payroll doesn't exist in this app, and the
  project "Contract" concept it used to also report on was removed
  entirely in Piece 73. **Online-only** — nothing is sent until a question
  is asked, and nothing is sent while offline.
- **🧠 Plan tab** (on each project's own page): a project-scoped brainstorm chat
  to think through finishing *that* project — same read-only, permission-scoped,
  Claude-powered design as 💬 Assistant, but its conversation is **saved per
  project** so you can pick it back up later, and it's grounded in that
  project's Category/Subcategory, open tasks, and recent field notes. It's
  **propose, then confirm**: the AI never saves anything itself — a suggested
  next step needs an explicit **➕ Add to project** click (which tags the new
  task to the project's current stage, so it counts toward advancing it), and
  any reply can be kept with **💾 Save as project note**. Turned off for
  Done/Abandoned projects.
- **🗒 Drafts** (Piece 52): the Assistant role is meant for an AI agent's own
  household-member account — it reads everything a Parent can, but every
  write it attempts (a new project, a rule, an inventory item, a household
  member, a budget/project transaction — even a receipt/document upload —
  or an approve/reject decision on a Wishlist item or Work Bag submission)
  is captured as a **draft** instead of applying directly. A Parent/Admin
  reviews each one on the 🗒 Drafts page (under 🏠 Household) and either
  **Approves** it — applying the exact same change a live user's action
  would have made, attributed to whoever proposed it (an approve/reject
  recommendation is attributed to the approving Parent instead, since
  that's who actually exercised the judgment) — or **Discards** it, which
  deletes any attached file and leaves the real data untouched. A Parent or
  Admin's own actions are completely unaffected — everything above only
  intercepts a signed-in **Assistant**.
- Setup is below under **[Setting up the AI Assistant](#setting-up-the-ai-assistant)**.

### Help & records
- **In-app Help** (❓ Help in the top bar): tutorials & FAQ for every feature,
  grouped by area with a contents list and expandable questions. **Sections
  about a tool you don't have access to show a locked placeholder instead**
  (Piece 53) — Requirements Editor, Billing, Household Budget, People/roles,
  and the Admin section. The **See full FAQ** permission
  (`help.full_access`) bypasses this and always shows everything; Parent
  and Assistant get it by default, Child doesn't.
- **Audit log** of all changes (create/update/delete), with password fields
  redacted and never logged in plaintext.

---

## Setting up the AI Assistant

The 💬 Assistant is **off until an admin adds an API key** — Compendium doesn't ship
with one. It uses your own account with Anthropic (Claude), so **you pay Anthropic
per use** (inexpensive for this kind of Q&A).

**1. Get a Claude API key:** sign in at **console.anthropic.com**, add billing, and
create an API key under **API Keys** (it looks like `sk-ant-…`).

**2. Enter it in Compendium.** As an admin, open **💬 Assistant → ⚙️ AI settings** and:

- Paste the key.
- Choose the **model** (Sonnet is the balanced default; Opus is the most
  capable and priciest; Haiku is the cheapest).
- Save. The key is stored **on this machine** (in your Compendium data folder), never
  in the program itself, and is only ever sent to Anthropic.

**3. Ask a question.** Open **💬 Assistant** and type a question (e.g. *"Which projects
are in Prep?"*, *"What are my open tasks?"*, *"How many overdue tasks are there?"*).

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

- **v0.54** — **Fixed duplicate reminder notifications.** A daily chore
  ("Cook Dinner") rang twice for the same missed day instead of once —
  root cause: the reminder check ("has this already been sent?") and the
  write marking it sent weren't atomic, so two nearly-simultaneous callers
  (the app runs 2 worker processes, plus a periodic background check)
  could both see "not sent yet" before either recorded it, both firing a
  notification. Fixed for chores and, since Appointments, standalone
  Requirements, and the household idea Backlog reminder share the exact
  same pattern, all four now claim the "sent" flag atomically *before*
  notifying — only whichever caller actually wins that flag ever sends.
- **v0.53** — **Parent UI review pass.** A screenshot-driven, mobile-focused
  button/layout review across the whole app: Dashboard sections now
  collapse by default and Backlog/My requirements were dropped from the
  summary (still live on their own pages); Procurement is now "Orders and
  Deliveries"; the Planning stage's card shows the next to-do instead of
  Requirements; every Productivity Overview item (Appointments/Chores/
  Boards/Tasks) now has a one-tap ✓, and marking one done correctly stays
  on the dashboard instead of jumping away. The Projects list, Tasks
  board, and Chores page were redesigned around real card headers,
  collapsed-by-default groups, and (for Chores) a Daily/Weekly/Monthly/
  Quarterly/Yearly grouping with its own dedicated New/Edit form page.
  Boards, Appointments, and Household Files gained color-coded, two-tone
  filters; Contacts split into Individuals/Organizations tabs; a
  persistent notification bell now sits in the mobile header; Money's
  Budget/Loans/Savings buttons fit on one row; Inventory gained a
  previously-missing "＋ New item" button (there was no way to add the
  very first item before this) plus an optional subcategory level that
  nests into its own collapsible groups. The AI Assistant page dropped
  Gemini support entirely (Claude only, never used otherwise), gained a
  5-conversation rolling history per person, and can now propose a new
  project as a Pending draft mid-conversation for a parent to approve.
- **v0.52** — **Mobile-responsive audit.** Checked the app on real phone-
  width viewports (375px/330px/320px) across every page, project-detail
  tab, and form. Found the responsive foundation from Piece 31.6/31.7
  (hamburger nav, auto-wrapped/restacking tables, ≥16px inputs, wrapping
  flex/grid layouts) already covers nearly everything correctly — one
  genuine bug found and fixed: the dashboard's month-calendar grid was
  getting caught by the same generic table-restacking script built for
  dense data tables, which on phones collapsed the 7-column Sun–Sat grid
  into a broken vertical list of labelled day rows instead of keeping it
  a compact calendar. The calendar now opts out (`no-rstack`) while every
  other table keeps restacking as before.
- **v0.51** — **Full legacy-artifact sweep.** A 3-way parallel audit (dead
  code, orphaned schema, stale UI text) found and closed out everything
  left over from this app's original solar-installation-business origins
  beyond the Contract concept (v0.50). A genuine bug fixed along the way:
  `household_members.access_level` was being silently re-added on every
  single app restart by a migration ordering issue dating back to the
  Piece 35 household reorg — it's been resurrecting itself forever,
  confirmed and fixed against the real database, not just a fresh
  install. Also dropped several other write-only orphan columns (Piece
  27.3's invoice-generation fields, Piece 27.9's payroll time-segments)
  and the BPMN-era task auto-tagger. The Billing tab's income category
  field is now free text with suggestions (matching Household Budget's
  own pattern) instead of a locked dropdown of solar payment milestones
  ("50% Deposit," "Final 10% Invoice") that had never actually been used;
  the party field relabeled "Customer" → "Payer." Three solar-specific
  document-upload slots ("Signed Contract," "Design / One-Line," "Site
  Plan (KMZ/KML)") were removed, leaving just "Site Photos." Swept ~20
  instances of stale business vocabulary ("the office," "supervisor,"
  "crew," "on staff," un-renamed "install date" labels) across 10
  templates — wording only, no behavior change.
- **v0.50** — **Removed the legacy "Contract" concept.** Flagged back in
  v0.30 (Piece 54) as a leftover from this app's original solar-
  installation-business origins — a project's Contract total (the
  customer's agreed price) has no household DIY equivalent. Confirmed
  with real data before removing anything: every one of the household's
  real projects had it blank, and zero income transactions had ever been
  logged against it. Removed outright, not renamed: the Contract input/
  tile on a project's Billing tab, the "Money in projects" dashboard/
  Money-page tile, the Contract column on the Money page's Payments
  table and the Closed Projects review page, the Wrap-up worklist's
  always-$0 "balance due" figure, and the AI assistant's contract-total
  filter/answers. **Collected/Outstanding/Expenses/Net are untouched** —
  they were already computed entirely from the real income/expense
  ledger, independent of Contract the whole time.
- **v0.49** — **CSRF protection, via Flask-WTF.** This app's biggest
  remaining security gap, flagged but deliberately deferred in v0.45
  (Piece 69): none of its ~119 POST forms carried any CSRF defense
  beyond the partial mitigation of `SESSION_COOKIE_SAMESITE=Lax`. Every
  form across all 40 templates now carries a hidden token
  (`{{ csrf_token() }}`), and every JavaScript `fetch()`-based POST (the
  Plan tab's actions, the Work Bag's offline-submission flush) sends the
  same token via an `X-CSRFToken` header instead. One deliberate
  configuration choice: Flask-WTF's default token expiry (1 hour) is
  disabled in favor of tying it to the session's own 12-hour lifetime —
  the Work Bag's offline queue can genuinely sit unflushed for hours
  with no signal, and a shorter token expiry would have silently broken
  that exact feature. New dependency: `Flask-WTF` (pulls in `WTForms` as
  its own dependency, though this app still hand-writes every form in
  Jinja rather than adopting WTForms itself) — the one dependency this
  app has added specifically because CSRF correctness matters in a way
  its usual "no ORM, no JS framework" minimalism doesn't extend to.
- **v0.48** — **Merged in: projects get a real Owner** (originally built
  as v0.46 on the now-merged `feature/plan-tab-and-task-sections`
  branch). Previously the only way a person was connected to a project
  was through individual task assignment — there was no way to say "this
  whole project is mine" without also having a task on it (and no way at
  all if the project was created with zero tasks). A project now has an
  **Owner**, defaulting to whoever creates it, reassignable anytime from
  its General tab. The dashboard's "Projects by family member" card
  (Piece 64) now counts both signals — a project shows under its owner
  (marked 👑) and under anyone with a task on it, so a parent can tell at
  a glance who's overseeing something bigger vs. who's just got a small
  piece of it. **Caught and fixed on review before this merge**: the
  owner-reassignment route shipped without the Assistant-role
  draft-interception every other `projects.manage` action gets (Piece
  52's "every Assistant write becomes a draft for a Parent to approve"
  promise) — closed before this ever went live, not a live incident.
- **v0.47** — **Merged in: 🔁 Repeat last prompt, AI task-flagging, and a
  Section→Subtask task hierarchy** (originally built as v0.45 on
  `feature/plan-tab-and-task-sections`). Three related additions to
  project planning:
  - **🔁 Repeat last** — a persistent button (Assistant page and the Plan
    tab) that re-asks your last question anytime, not just after a
    failure — always a fresh turn, never a resend of a failed one.
  - **AI task-flagging** — the Plan tab's AI can call out an *existing*
    task it's discussing with a one-click "🚩 Flag" suggestion; confirming
    it sets a real, persisted indicator on that task, visible on the
    Tasks tab even after navigating away.
  - **Sections** — a new one-level grouping for a project's tasks (a
    major phase like "Tow old tractor" containing smaller subtasks),
    independent of each task's own pipeline stage. The Plan tab's AI can
    suggest a whole section with its subtasks in one visually distinct,
    bordered block, or a plain ungrouped task as before.
- **v0.46** — **One-time LAN→VPS data migration, plus an automatic
  one-way VPS→LAN backup pull.** With the VPS now running (v0.45), the
  household's real projects/tasks lived only on the LAN machine; they're
  now the VPS's live data too (migrated once, verified by checksum and
  row counts, with the VPS's prior seed data backed up first). Going
  forward the VPS is the single source of truth for daily use — the LAN
  and VPS databases are **independent and do not sync** — but a new
  scheduled task (`CompendiumVPSBackupPull`, Windows Task Scheduler,
  daily) now automatically pulls the VPS's latest nightly snapshot down
  to the LAN machine's `lan_backups/` folder via a new
  `deploy/pull_vps_backup.py`, so the LAN copy stays a current backup
  with no manual effort — solving the "off-box backup" gap `DEPLOY.md`
  had flagged as still-manual. See [OPERATIONS.md](OPERATIONS.md) for
  the full architecture writeup and troubleshooting playbook (including
  a real OneDrive/Task-Scheduler interaction that took some real
  debugging to work around).
- **v0.45** — **production hosting scaffolding + security hardening**, on
  branch `deploy/production-hosting-security`. The app's security posture
  assumed a trusted home LAN; this piece makes it safe to run reachable
  from the open internet, plus the scaffolding a `python app.py` dev
  server doesn't have. Fixes: the Flask session-signing key was a
  **hardcoded literal committed to the repo** — anyone who could read the
  source could forge a valid login session for any account, including an
  admin; it's now a real random key, generated once and persisted
  alongside the database (or set explicitly via `COMPENDIUM_SECRET_KEY`
  on a server). `init_db()` used to only run inside `python app.py`'s own
  startup block — under a real WSGI server (gunicorn) that path is never
  executed, so the database would never get created; it now runs at
  import time instead, the same fix already used for the background
  scheduler. **Login rate-limiting** (8 failed attempts per IP per 15
  minutes, then a 429) reuses the audit log's existing per-login records
  — no new table. A new `COMPENDIUM_BEHIND_PROXY` setting (VPS-only,
  never for the LAN setup) tells Flask to trust a real reverse proxy in
  front of it, correctly mark the session cookie `Secure`, and see the
  real client IP instead of the proxy's. New `deploy/` folder (systemd
  service, Caddy reverse-proxy config, a SQLite-safe backup script) and
  [DEPLOY.md](DEPLOY.md) walk through the rest, starting from an
  already-provisioned VPS (provisioning the box itself, paying for it,
  and DNS are the household's own steps). **Known gap, flagged rather
  than fixed**: no CSRF token protection exists anywhere in this app's
  many POST forms — a real retrofit is a separate, larger piece; partially
  mitigated for now by `SESSION_COOKIE_SAMESITE=Lax`. **Closed in v0.49
  (Piece 72), below.**
- **v0.44** — **🧠 Plan tab gets the 🔁 Retry button too.** Piece 57 added
  a retry button to the global 💬 Assistant chat but deliberately skipped
  the per-project Plan tab, since that chat saves your message to the
  database *before* calling the AI — a naive retry would have created a
  duplicate entry. Fixed properly: a failed reply now shows the same
  Retry button, and retrying reuses the already-saved message instead of
  inserting a second copy.
- **v0.43** — **"Estimated cost" relabeled "Money invested / budget."** The
  project field (originally named for its Piece 54 install-business
  origins) now reads more naturally for a household project — the label
  changed everywhere it appears (the Create/Edit Project form, a
  project's General details tab, the Requirements Editor's field picker,
  and version-history diffs), with no change to the underlying data or
  behavior.
- **v0.42** — **Household overview's Pipeline tiles replaced with a
  per-family-member project breakdown.** Instead of 6 tiles showing a
  whole-household count per pipeline stage, the card now shows one row
  per family member with their active projects as small chips — icon-
  and color-coded by pipeline stage (reusing the same icons/colors
  already used elsewhere on the dashboard), plus a consistent color per
  person via a circular initial avatar. A project counts for someone if
  they have any task assigned on it; a project with no one assigned gets
  its own "Unassigned" row so nothing silently disappears. Members with
  zero active projects don't get an empty row.
- **v0.41** — **Dashboard's Payments table replaced with "Upcoming
  payments."** The full per-project Payments table on the Household
  overview card is gone (it now lives on the 💰 Money page, Piece 62) —
  in its place, a short, actionable list of Outstanding project expenses
  due (or overdue) within the next month, so the dashboard stays focused
  on what needs paying soon rather than a full billing table.
- **v0.40** — **"💰 Money" — a financial overview page.** The 🏠 Household
  dropdown's three separate Budget/Loans/Savings links are now one "💰
  Money" link, opening a new `/money` page styled like the dashboard's
  other overview cards: the same "Money in flight" tiles Household
  overview shows, a combined savings-goal progress bar across every
  account with a goal set, a needs-attention row (over-budget categories,
  unpaid bills), this month's expense-by-category pie chart, a 3-month
  cash-flow projection, and the Payments table — all in one place, with
  quick links out to the full Budget/Loans/Savings pages for actual
  editing (none of those three pages changed or moved). The money-tile and
  Payments-table calculations were extracted into shared functions
  (`_household_money_snapshot()`/`_payments_summary()`) so the dashboard
  and the new page are guaranteed to always agree.
- **v0.39** — **Moved the Productivity Overview card** directly beneath
  Household overview (was further down, after Backlog) per follow-up
  feedback right after v0.38 shipped — pure layout reorder, no behavior
  change.
- **v0.38** — **Dashboard "Productivity Overview" card + a real Month
  Calendar.** Appointments, Chores, Boards (new — no dashboard summary
  existed before), and Tasks are now consolidated into one card instead
  of four separate ones, alongside a functional month-grid calendar with
  markers for every due date, prev/next month navigation, and a "This
  month" jump-back link. Appointments split into **Today / Tomorrow /
  Next 2 weeks** tiers (an overdue appointment folds into "Today" with
  its overdue badge, rather than disappearing) — everything beyond that
  2-week glance window still shows up on the calendar once you navigate
  to its month. Boards counts as "mine" the same way Boards' own "Mine"
  filter does: assignee **or** collaborator. Non-Child dashboards only —
  the Child dashboard's own "🗓 My schedule" widget is untouched.
- **v0.37** — **Loans/Savings/Budget UI polish.** Loan and Savings account
  detail pages now show a **balance-history chart** (a hand-rolled SVG line
  chart of the running balance over every entry, matching Piece 55's
  chart style) — the same pattern serves both, since a loan's Payment/
  Charge ledger and a savings account's Deposit/Withdrawal ledger only
  differ in which direction each entry moves the balance. Savings accounts
  with a **goal amount** now show a **progress bar** toward it (was
  captured on the form since Piece 54 but never compared against the
  balance anywhere). The Loans and Savings **list pages** each gained a
  small summary strip (account count + total balance; Savings also totals
  every account's goal) — Budget already had an equivalent Income/
  Expenses/Net summary.
- **v0.36** — **"Load Bag" — pull a project into your Work Bag without
  waiting for a task assignment.** Each active project's dashboard card now
  has a 🎒 toggle (add/remove yourself from the project's Work Bag
  directly — a new `work_bag_members` table, independent of task
  assignment) and a "⬇ Load tasks" button (claims every currently
  *unassigned* task on that project for you; tasks already assigned to
  someone else are left untouched). A bagged project's other-people's
  tasks now show up in your Work Bag too, but as **view-only reference**
  cards (no Submit/Mark-done controls) — the field-sync endpoint only ever
  accepted changes to your own tasks, so this avoids a silent-failure trap
  rather than relaxing that check.
- **v0.35** — **Boards get collaborators and a due time.** Beyond the
  single "sent to" assignee, any number of household members can now be
  added as **collaborators** on a board — notified when added, counted
  under their own "Mine" filter, and free to see/check off the same card
  together (new `board_collaborators` join table; no new permission —
  Boards routes were already open to any signed-in member). Due dates can
  now carry an optional **time** ("Tuesday, 4pm"), mirroring Appointments'
  existing date+time pattern exactly — the overdue badge deliberately
  stays date-only, matching every other due-date calculation in this app.
- **v0.34** — **the 💬 Assistant chat gets a Retry button.** Jacob's first
  beta-test feedback: if a question fails (dropped connection, provider
  error), a Retry button now appears next to the error message and resends
  the exact same question — previously you'd have had to retype it or
  copy it back out of the chat bubble. The 🧠 Plan tab's chat has the same
  gap but a different fix (it saves the user's message to the database
  before calling the AI, so a naive resend would duplicate that row) — not
  addressed this piece, tracked in `HANDOFF.md`.
- **v0.33** — **the app can now be reached from a phone on the same WiFi**,
  for beta-testing. `python app.py` behaves exactly as before by default
  (localhost-only, debug mode on); set `COMPENDIUM_HOST=0.0.0.0` (and
  optionally `COMPENDIUM_PORT`) to bind to the machine's LAN address
  instead — debug mode (the interactive Werkzeug debugger) automatically
  turns itself off whenever the app isn't localhost-only, since leaving it
  on while reachable from other devices is a real code-execution risk.
- **v0.32** — **bug fix: assigning a project task to a household member
  never actually saved.** The "Assigned to" dropdown (both on an existing
  task's row and the "add a task" form) posted a form field named
  `employee_id` — a leftover from before the Piece 35 employees→household-
  members rename — while the backend's `_task_assignee()` helper (and the
  dropdown's own "who's currently selected" check) read/compared against
  `household_member_id`, the actual column name. The mismatch meant an
  assignment silently never saved (always landed as unassigned) and the
  dropdown could never show the correct person as selected even if it had.
  Due date and status, on separate small per-field forms with correctly-
  named fields, were never affected — which is exactly why only assignment
  looked broken. Fixed by renaming both `<select>`'s form field to
  `household_member_id` and the display-comparison to match.
- **v0.31** — **the Household Budget page gets at-a-glance reporting**: a
  donut chart of expenses by category, a forward-looking anticipated
  cash-flow projection (Outstanding transactions from both ledgers +
  Budget's recurring monthly targets, netted per month — not a running
  bank balance, since this app has no starting-balance concept anywhere),
  and two historical trend bar charts (income vs. expense, spending by
  category), both adjustable in window length. All four combine the
  household and project ledgers, matching v0.30's dashboard rollup. No
  charting library exists anywhere in this app (confirmed — nothing but
  inline JS, no CDN scripts), so every chart is hand-rolled inline SVG
  computed server-side in Python (`_pie_geometry`/`_bar_series_geometry`)
  — works offline like the rest of this app, no new dependency. New
  month-range helpers (`_recent_months`/`_forward_months`) since no
  multi-month query existed anywhere before this piece. Pure reporting —
  no schema changes.
- **v0.30** — **the dashboard money widget rolls up the whole household**,
  and two new money features. The old 4-tile "Money in flight" (Contract/
  Collected/Outstanding/Expenses) is now 6 tiles — **unpaid expenses,
  loans, income, savings, money in projects, and anticipated spending
  (est. vs. actual)** — combining the per-project ledger and the household
  Budget ledger for the first time (they'd never been rolled up together
  before). **Loans and Savings** are new: named accounts, each with a
  running balance computed live from its own entry ledger (mirrors the
  project Billing ledger's own design, not a single stored number) —
  `finances.manage`-gated and draft-intercepted for an Assistant, same as
  every other money feature. `household_transactions` gained a real
  Outstanding/Paid **status** (it had none before — every logged expense
  was implicitly already-settled), so the new "unpaid expenses" tile can
  mean something on the household side too. Projects gained an
  **estimated cost** field, set during Planning, compared against actual
  expenses logged so far (not against the Contract total — see below) on
  the new "Anticipated spending" tile. Household Budget's category field
  gained suggestions, including a new **Discretionary Spending** category.
  **Flagged, not fixed, this piece**: the project "Contract" concept
  (`contract_amount`, the Billing tab's Contract tile, `set_contract`) is a
  leftover from this app's original solar-installation-business origins —
  the new estimate feature was deliberately built to compare against actual
  expenses instead, specifically so it wouldn't deepen reliance on Contract
  while it's still around; see `HANDOFF.md` for the full inventory of where
  it lives, queued for a future piece to reconsider.
- **v0.29** — **a Child's account gets an individually-focused experience**,
  building on v0.27's permission system. Dashboard: Parent/Assistant keep
  the household-wide overview; a Child gets a personal **🗓 My schedule**
  widget instead (Today/Tomorrow/Next 2 weeks, merging their own tasks,
  chores, and appointments), no Procurement or Backlog cards, and the
  stage-listing cards scoped to only projects they have a task on. Nav:
  **Work Bag** is a standalone top-level button again (was folded into the
  Household dropdown in v0.24); **Family**, **Household Files**, and the
  **Requirements Editor** are now genuinely gated — not just hidden links —
  reusing `household.manage`/`rules.manage` (a real, if minor, pre-existing
  gap: those routes carried no server-side check at all before this).
  **Project documents follow task assignment** for a Child specifically — a
  project's Documents tab and Requirements-tab file links only show if they
  have a task on that project; everything else about the project (info,
  task list) stays visible regardless. A Child's own already-filed field
  photos/receipts are exempt, so a later reassignment can't orphan their own
  uploads. **Help/FAQ** sections about a tool someone doesn't have access to
  now show a locked placeholder instead of the tutorial; a new
  `help.full_access` permission (Parent/Assistant by default) bypasses it.
  Verified the AI Assistant/Plan chat's tools already scope to whoever's
  actually signed in and don't expose any file listings, so no change was
  needed there. Fixed a real pre-existing gap surfaced along the way: the
  Requirements Editor's own page had no permission check at all (only its
  write routes did).
- **v0.28** — **the Assistant role becomes an AI agent's own account**,
  closing the loop v0.27 (below) deliberately left open. Assistant's
  permission bundle now matches Parent (everything but Delete), but every
  one of its writes — across all 7 permission areas: projects, requirement
  rules, inventory, household members, household/project finances
  (including receipt and document uploads), and Wishlist/Work-Bag approve-
  or-reject decisions — is captured as a **draft** (new `drafts` table)
  instead of applying directly. A new **🗒 Drafts** page (under 🏠 Household)
  lets a Parent/Admin Approve (apply the change for real, moving any
  attached file from a separate draft-only upload folder into live storage)
  or Discard (deletes any attached file, changes nothing) each one. A Parent
  or Admin's own actions are completely unaffected. Also closed a real gap
  the same audit surfaced: the 💬 Assistant/🧠 Plan AI chat included contract
  totals unconditionally, a text-based way around the finances.manage gate
  — now respects it like everything else. Fixed a genuinely pre-existing
  bug found along the way: `update_rule` (editing a requirement rule) was
  never registered against the `rules.manage` permission, so it silently
  fell back to admin-only access the whole time since Piece 17/35 — a
  non-admin granted `rules.manage` could add a rule but never edit one.
- **v0.27** — **roles actually grant access.** Parent/Child/Assistant were
  pure display labels since Piece 35 — confirmed by a full-codebase audit
  that `role` had zero effect on any access decision anywhere. Each role now
  comes with a default permission bundle, materialized as real grants when a
  person is added or their role changes (additive only — a role change never
  removes a grant someone already has; per-person overrides still work
  exactly as before on the Access console). Two new permissions:
  **`finances.manage`** and **`projects.manage`**, closing real gaps —
  creating/editing/cancelling projects and adding/editing household Budget
  entries or a project's own billing ledger were wide open to any signed-in
  user before this. For a Child specifically, finances are **hidden
  entirely** (not just edit-locked, unlike every other `.manage`
  permission) — the Budget page, a project's Billing tab, the dashboard's
  money tiles, and even the 💬 Assistant/🧠 Plan chat's contract-total
  answers are all gated the same way, so there's no back door. Also fixed a
  pre-existing bug found along the way: a project transaction's delete route
  had no permission gate of any kind (now gated, though its hard-delete
  behavior — no soft-delete/trash routing like every other delete route —
  is left as a separate, known issue).
- **v0.26** — the "📊 My Dashboard" nav link's icon changed from 🏠 to 📊 —
  since Piece 49 gave the new "🏠 Household" dropdown the same house icon,
  sitting right next to "My Dashboard" in the nav bar, the two looked like
  duplicates. Cosmetic only, no functional change.
- **v0.25** — nav-bar correction: v0.24 (below) put the renamed **👨‍👩‍👧
  Family** link *next to* the new 🏠 Household dropdown instead of *inside*
  it, splitting one intended group into two nav elements. Merged them —
  **🏠 Household** is now a single dropdown containing Budget, Work Bag,
  Approvals, **and** Family together, with no separate standalone Family
  link. Caught from user feedback ("Family... does not open as a drop-down
  at all") right after v0.24 shipped.
- **v0.24** — nav-bar UI cleanup: the top bar had grown a link per feature
  (10+ items) — regrouped into two new dropdowns, **✅ To-do** (Tasks, Boards,
  Chores, 🔔 Notifications, Appointments — the standalone notification bell
  moved in here, with its unread count now shown on the dropdown itself) and
  **🏠 Household** (Budget, Work Bag, Approvals, and the renamed household-
  member roster page — see v0.25 above for the correction to how Family was
  actually wired in). Also removed the "Vixinman Designs internal tool"
  subtitle from the header and swapped the ☀️ logo for 🦊 throughout the
  live UI (header, login page) and the README masthead — docs-only
  branding, no functional change. No schema/route changes.
- **v0.23** — new feature: **AI-assisted project planning** — a "🧠 Plan" tab
  on each project's own page, a brainstorming chat scoped to that one
  project rather than the whole household. Reuses the existing AI provider
  config, `run_agent()` tool loop, and read-only tool registry unchanged
  (Piece 32) — no new AI write-tools, preserving the assistant's read-only
  design promise. New `project_plan_messages` table persists the
  conversation per project so it can be reopened later; a new project-scoped
  context builder feeds the model the project's Category/Subcategory, open
  tasks, and recent field notes for tailored suggestions. Suggested next
  steps use a simple `TASK: ` line convention the tab's JS turns into an
  **➕ Add to project** button — a real, human-clicked POST to the existing
  `add_task` route (which gained one optional `pipeline_status` field so a
  Plan-tab-added task counts toward that stage's ready-count, closing a
  latent gap where manually-added tasks never did); replies can also be kept
  with **💾 Save as project note** via the existing Work Bag note route. No
  new permission — matches the existing "any signed-in household member"
  policy on project tasks/notes.

- **v0.22** — UI cleanup + docs sweep: Wishlist moved off the top-level nav
  bar (which had grown a link per new feature) and now lives primarily
  under **Inventory** — a "🎁 Wishlist" button in the Inventory toolbar,
  a per-row "🎁" quick-add that pre-fills "more of this item" (new
  `?prefill_item=` param on `/wishlist`, mirroring Appointments'
  `?prefill_contact=`), and a plain entry in the 🗄 Databases dropdown.
  Also swept `templates/help.html`, which hadn't been touched since the
  Piece 41 reorg cleanup: added Chores, Appointments, Household Budget,
  and Contacts sections, a Wishlist tutorial under Inventory, and a
  Category/Subcategory FAQ under Projects — closing a five-feature
  documentation gap.

- **v0.21** — new feature: **household expense/budget/receipt tracking**,
  second of two features requested together (Wishlist, v0.20, was the
  first). A new "💵 Budget" page: a household-wide income/expense ledger
  (separate from each project's own Billing tab/`project_transactions`,
  which is completely untouched), with an optional receipt photo/PDF per
  transaction and an optional Contact link, plus per-category monthly
  budget targets compared against actual spend for the selected month.
  New `household_transactions`/`household_budgets` tables (purely
  additive, no migration). Extended `_contact_uses()` (the FK-safety
  helper from Piece 45) to also count household transactions referencing
  a Contact, so deleting one still in use is correctly blocked.

- **v0.20** — new feature: **Wishlist**. Anyone can add something they
  want, optionally linked to an existing Inventory item ("more of this"),
  a Project, and/or a Contact — all independent and optional. Each
  submission sits as Pending until a Parent/Admin approves or rejects it,
  reusing the existing "approvals" permission (relabeled "Approve field
  work & wishlist requests") rather than adding a new one — the same
  parental-oversight concept the Work Bag's field-work approvals already
  use. Approving does nothing automatic; it just marks it OK to buy.
  New `wishlist_items` table (no migration needed, purely additive).
  Fixed a latent FK-safety gap along the way: `TRASH_REGISTRY`
  `["inventory_item"]`'s in-use check was hardcoded empty (harmless until
  now) — refactored the Contacts in-use check from Piece 43 into a
  reusable `_contact_uses()` helper and added a matching one for Inventory
  items, both now correctly block deletion of anything still referenced
  by a wishlist item instead of raising a raw database error.

- **v0.19** — replaced the Project form's free-text "Project type" field
  with a fixed **Subcategory** dropdown that cascades from the chosen
  Project category: Home Improvement → Building, Landscaping, Gardening,
  Maintenance & Repair; Personal Improvement → Education, Health, Habit,
  Relationship, Misc. No schema change (still the same `project_type`
  column); a controlled vocabulary is what makes it useful for the
  Requirements Engine to match rules against, unlike arbitrary typed text.
  The Requirements Editor's "suggest a value" list and the Requirements
  Library's type filter both switched from "whatever's been typed in real
  projects so far" to the full fixed list.

- **v0.18** — reworked **External Helpers into Contacts**: broadened to
  cover organizations (subscription services, co-ops, utilities), not just
  people. A Type toggle (Person/Organization) shows/hides six new
  organization-only fields (website, account/member number, a main contact
  person, renewal date) — existing entries default to Person, unaffected.
  Renamed to "Contacts" everywhere visible; internal table/route/endpoint
  names are unchanged. Appointments can now link to a contact — a "＋ Add
  appointment" quick-link on a contact's row pre-fills a new, linked
  appointment, and the row shows its upcoming-appointment count. Caught and
  fixed a real bug along the way: the new `external_helper_id` foreign key
  (this app runs with `PRAGMA foreign_keys=ON`) made deleting a still-
  referenced contact raise a raw database error instead of the app's usual
  friendly "still in use" message — added the missing in-use check, same
  pattern already used for rules/employees/etc.

- **v0.17** — new feature: **Appointments**, making scheduling/tracking
  dates a core function rather than something only Chores or a project's
  target date could half-cover. Modeled directly on Chores (same table
  shape, same completion-driven recurrence, same reminder mechanics) with
  two real additions: an optional time-of-day field, and a one-time-vs-
  recurring toggle (Chores are always recurring; most appointments aren't).
  A new `/appointments` page, a dashboard card, a nav entry, and folded into
  the `.ics` calendar export (which now emits real timed events, not just
  all-day placeholders, when a time is set). Also fixed two stale README
  claims left over from Piece 41 Part A — the pipeline description still
  said Prep gated on "all permits filed + an install date set" and that
  stage turnovers included "the install-date auto-advance"; both were
  removed when Part A de-gated the pipeline, just never caught since that
  piece's Help sweep only covered `templates/help.html`, not this file.

- **v0.16** — last of the Piece 41 cleanup: a Help/FAQ sweep against
  everything Parts A-D changed. Fixed: the pipeline tutorial's claim that
  "Prep auto-advances to In Progress once permits are filed and you set an
  install date" (that auto-advance was removed in Part A — a stage now
  advances once its own tasks are done, full stop); the Inventory
  section's entire "mark an item stale" tutorial (the feature is gone —
  replaced with a plain "add an item" tutorial covering free-text
  categories and the quantity field); and the admin section's mention of
  "this week's installs" on the dashboard (that tile was removed in Part
  A). This closes out Piece 41 — the only items left on `HANDOFF.md`'s
  open list are the deferred visual theme pass and a manual browser
  click-through.

- **v0.15** — fourth of the Piece 41 cleanup: Inventory. It was still a
  solar-parts catalog — a hardcoded 15-category taxonomy (PV Module/
  Inverter/Battery/Charge Controller/...) with per-category electrical spec
  fields (Voc/Vmp/FCC ID#), a needed/available/on-PO stock model plus a full
  stock ledger and a 6-month stale-stock review queue, and a managed vendor
  entity with no add-vendor UI at all. Purged the legacy catalog (confirmed
  every row in the real database was solar-business reference data — 439
  items/49 tools/11 vehicles/52 vendors, all at 0 available/0 needed, none
  of it real household stock). Categories are now free text with a
  datalist. Collapsed needed/available/on-PO to a single `quantity` column;
  dropped the stock ledger, the stale-stock workflow, and the managed
  vendor entity (replaced with a plain "purchased from" text field).
  Deleted `inventory_seed.py`/`inventory_research.py` outright. Verified
  via a migration test and the actual purge run against the real household
  database (439/49/11/52 → 0).

- **v0.14** — third of the Piece 41 cleanup: the Requirements Editor. Purged
  all 145 `resource_rules` in the live database — every one matched a field
  Part B just dropped (county/utility_provider/products/property_type/PV-
  Generator-Battery variants), leftover NM-permit data from the original
  solar business. The "…matches this value" field was blind free text (an
  admin had to already know the exact stored string); it's now a datalist
  that suggests real values — project_category's two fixed choices, or
  whatever's already in use for project_type/site_location. Rebuilt the
  Requirements Library's (`/directory`) filter bar around the new minimal
  field set (category + type) in place of the old product/utility-
  connection/mounting-type/manufactured-house/service-type/property-type
  filters, and dropped the "Verification flags come from the NM reference
  set" copy. Verified via a migration test and the actual purge run against
  the real household database (145 → 0).

- **v0.13** — second of the Piece 41 cleanup: the Project form itself. It was
  still a solar-sale intake form — Property type, County (with an NM county
  datalist), Utility provider, Warranty type, a required Payment dropdown,
  Tax credit, Expand option, and a required Products/services checklist (PV
  Systems/Battery Banks/Generators/Well Pumps/Mini Split Air Conditioners/
  Technician Service) with its own PV-mounting/manufactured-house/
  service-type sub-options and a whole "pre-fill a service ticket" flow built
  around picking Technician Service. None of it had anything left to serve
  once Part A dropped the pipeline gating that read some of these fields and
  Part C is slated to purge every one of the 145 resource_rules that match
  on the rest. `PROJECT_FIELDS` shrinks from 18 columns to 4: project name,
  category, type, and site location (now optional — not every project has
  one). Dropped via a meta-guarded migration; verified as a pure schema
  cleanup on the real household database, which had zero live projects.
  Also fixed the AI assistant's project-lookup tools and global search,
  which queried the now-gone `county`/`cost_method` columns directly.

- **v0.12** — first of a new five-part cleanup (Piece 41): after logging into
  the live app for the first time since the structural reorg, the household
  found the surviving subsystems still shaped for a solar-installation
  business rather than a household — the dashboard centered on "this week's
  installs," the Project form was a solar-sale intake form, the Requirements
  Editor still filtered on solar product categories, and Inventory was a
  parts catalog. This part covers the dashboard + pipeline: removed the
  duplicated "This week's installs" tile and "🔨 Installs" bucket table
  (both keyed off `install_date`); every pipeline stage now advances on
  "this stage's own tasks are done" only — dropped the Planning
  electric-loads gate and the Prep permits-filed/install-date gate (and the
  auto-advance from Prep to In Progress that used to trigger when both were
  satisfied). Requirements-filed coverage and the materials/procurement
  rollup are still shown (genuinely useful, not solar-specific), just no
  longer restricted to a particular stage. Added "＋ New project"/"📁 View
  projects" buttons to the dashboard (there was previously no way to start
  or browse projects from it) and renamed "⭐ Company overview" to "🏠
  Household overview." `install_date` itself stays as a plain optional field
  (still used by calendar export and the Work Bag), relabeled "Target/
  completion date." Parts B-E (Project form, Requirements Editor, Inventory,
  a Help/FAQ sweep) are next.

- **v0.11** — bugfix/cleanup, not a removal: the same audit that drove v0.9/v0.10
  found `templates/work_bag_photos.html` referenced an undefined template
  variable, hard-crashing (500) the Photos step of every Work Bag task. The
  leftover "pay type" time-segment widget it was part of also fed a `segments`
  field the backend never read — the route only ever consumed a plain `hours`
  number — so it was both broken and, even patched, silently discarded. Replaced
  it with the single plain-number hours field the route already expects.
  `templates/submissions.html` had the matching dead "Time (by pay type)" column
  (always rendered "—") and stale copy about "pending payroll... for Finance to
  approve" — neither payroll nor a Finance role exist here; dropped the column,
  reworded the copy. **The approval gate itself is unchanged and intentional**:
  Work Bag submissions from Assistants/Children still land as a Pending
  `field_submissions` row and nothing is written permanently until a Parent/Admin
  approves it. Also fixed a stale AI Assistant doc claim left over from v0.10
  about pricing being gated by permission — contract figures are visible to
  everyone now that the Cost Model's margin breakdown is gone. Third and last of
  the three-part audit cleanup; only the deferred visual theme pass remains.

- **v0.10** — cut two more solar-only subsystems found by the same audit: the
  **Loads & Sizing** electrical calculator (PV/battery/inverter sizing, a
  per-project load survey, a bill of materials, its own appliance/component
  catalog) and the **Cost Model / GRT tax pricing** system (an Equipment/
  Labor/Travel/Adders/Overhead estimator, a 33-county NM tax table, a
  cost-vs-margin breakdown). Both priced or sized a job for the original
  solar business with no household equivalent — `HANDOFF.md`'s own plan
  already said to cut the pricing machinery down to plain budget-vs-actual,
  just never finished it. ~2,300 lines gone across `app.py`, `schema.sql`,
  and three deleted templates (`project_loads.html`, `catalog.html`,
  `finance_settings.html`); 10 tables dropped. `electric_loads` stays as a
  plain text field (still gates the Planning stage); the Billing tab's
  contract-total field and the income/expense ledger — the actual
  budget-vs-actual tracking — are untouched. Second of three audit parts;
  a Work Bag bugfix is next.

- **v0.9** — cut the BPMN task-generation engine (`bpmn_export.py`), found by a
  full-repo staleness audit: it was the only way any project got tasks, hardcoding
  the entire solar sales→install→closeout pipeline (10 lanes; steps like "50%
  Deposit Received," "Meter set by {utility}") regardless of a project's category.
  Tasks are added manually now — the **+ Add task** form already existed and worked
  alongside auto-generation. Also removed: the per-project BPMN chart viewer/export,
  and the auto-trigger that regenerated tasks on every pipeline stage advance. First
  of three parts closing out a full solar-business-code audit; Loads & Sizing / Cost
  Model / GRT tax are next.

- **v0.8** — retired `nm_directory.py`. `HANDOFF.md`'s plan was to repurpose
  it as a vendor/contractor directory, but that need turned out to already
  be covered: the **External Helpers** roster (v0.4) is the same shape
  (name, specialty, phone, email, notes). Its remaining live content — the
  county→utility auto-match on the project form (pick a county, it
  suggests which of ~30 statewide NM utilities serve it) — was solar-business
  logic for matching a job site to its utility; cut, since the household has
  one property and one utility. **Utility provider** is now a plain text
  field. The county field keeps its NM-county datalist for convenience (now
  inlined in `app.py`); the file's dead NM AHJ/utility rule-batch data (unused
  since v0.7) went with it.

- **v0.7** — redesigned the Rules Editor into a household **Requirements
  Engine**. `RULE_CATEGORIES` renamed for household use (License →
  Certification, Compliance → Prerequisite; a migration remaps existing
  rows). Projects gain **project_category** (Home Improvement / Personal
  Improvement) and free-text **project_type**, giving rules something
  household-relevant to match against — the solar-specific project fields
  stay in place but are no longer the only option. Each rule can carry
  optional, purely informational **est_cost / est_time / maintenance_note**
  fields. A rule can also skip the project condition entirely and become a
  **standalone recurring requirement** — for internal household obligations
  not tied to any project (taxes, homeschool registration) — reminded on its
  own interval with the same assign/mark-done mechanics as Chores, plus a
  "My requirements" dashboard card. The solar-specific seed content
  (`SEED_RULES`, the NM AHJ/utility rule batches) is gone; a fresh install
  now starts with an empty Requirements Engine. `/rules` and `/directory`
  keep their URLs, relabeled **Requirements Editor** / **Requirements
  Library** throughout the nav and UI.

- **v0.6** — added **Chores** (`/chores`): a new `routine_tasks` table for
  recurring household tasks that aren't tied to any project (trash day,
  watering, a weekly clean) — the split between project-driven steps and
  standalone recurring tasks that the household reorg called for. Recurrence
  is a plain day-interval (`recurrence_days`, with Daily/Weekly/Biweekly/
  Monthly presets plus a custom option); no status workflow — "Mark done"
  logs it and advances the next-due date by the interval. Reminders reuse
  the household-idea backlog's exact idempotent notification pattern. A "My
  chores" card on the dashboard sits alongside "My tasks."

- **v0.5** — cut the barcode/asset-tag registry entirely: register/print tags,
  scan-in/out, checkout/checkin/retire, the truck-loading scan flow, and stock
  audits are gone — built for a multi-person crew truck-loading parts, doesn't
  fit household scale. Drops `inventory_assets`/`stock_audits`/
  `stock_audit_scans` and the `barcodes.py` Code128-SVG module; a
  meta-guarded migration drops the tables from an existing database. Also
  ships the inventory catalog **empty** on a fresh install instead of
  pre-seeding Vixinman's 439-item solar catalog, vendor list, tool kit, and
  vehicle fleet — none of it is household-relevant. Kept the
  category→spec-field definitions the item form still needs; cut the actual
  seed data rows.

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
