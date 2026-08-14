# Handoff: Vixinman Household Compendium

Context for whoever (whichever Claude) picks this up next. This repo started life as
**Solbiz** — an internal ops tool for **ECC Solar** (NM solar installer): clients, jobs,
licenses/permits/compliance, inventory, payroll, the works. It's being converted into a
**household** version: routine tasks + ongoing projects (repairs, builds, certifications)
for one household, not a multi-client business.

---

## Status: what's already done

The **text/branding rebrand pass is complete and verified.** Confirmed via repo-wide
search (zero remaining matches for `ECC` / `Solbiz`, case-insensitive, across
`.py`/`.html`/`.sql`/`.md`/`.js`/`.txt`, excluding `dist`/`build`/`.git`/screenshots):

- **Product name:** "Solbiz" → **"Compendium"** (short form used in nav/titles/cache
  keys) / **"Vixinman's Home Compendium"** (full display name)
- **Company name:** "ECC Solar" / "ECC" → **"Vixinman Designs"** — copyright notice,
  `LICENSE`, code comments, invoice remit-to block, `schema.sql` comments, all templates
- **Desktop packaging paths:**
  - `~/Solbiz` → `~/Compendium` (data dir)
  - `Solbiz.exe` → `Compendium.exe`
  - `Solbiz-Import` → `Compendium-Import`
  - `solbiz-error.log` / `solbiz-startup-error.log` → `compendium-error.log` /
    `compendium-startup-error.log`
  - `desktop/run_solbiz.py` → `desktop/run_compendium.py`
  - Env var `SOLBIZ_DATA_DIR` → `COMPENDIUM_DATA_DIR` (verified consistent between
    `desktop/run_compendium.py` and `app.py`'s `DATA_DIR = Path(os.environ.get(...))`)

**NOT done yet:**
- **Visual theme.** `templates/base.html` still uses the original green
  (`--brand: #1a6e3c`, `--brand-dark: #12522c`). The target aesthetic is
  **parchment / illuminated-manuscript**: natural paper-fiber background, ornate
  borders, accent colors in blue, green, red, gold/brass, and black ("burnt wood"). This
  is real visual design work (textures, border art, probably a different typeface), not
  a CSS-variable swap — treat as its own phase, explicitly deferred by the user until
  after the schema/feature reorg below is done.
- **The structural/domain reorg** — this is the actual task for this session. See below.

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
| `jobs` table + pipeline | **`projects`** | Keep the shape (versioning, per-job BPMN chart, standardized pipeline with gated stages). Drop `client_id` FK. Rename pipeline stages: `Proposal → Job Prep → Installation → Inspections → Closing → Complete` (+ `Lost`) becomes something like `Planning → Prep → In Progress → Verify → Wrap-up → Done` (+ `Abandoned`). Verify covers permit sign-off / inspections / certification exams — open question whether it stays its own stage or folds into another; see Open Questions. |
| `employees` table + org chart | **`household_members`** | Same table shape (name/nickname dup-guard, licenses & certs per person, per-person dashboard) survives. The 28-role org-chart (`reports_to` hierarchy, Sales/Design/Warehouse/Install departments) shrinks to a small role set — see below. |
| Task generation (single stream, job-driven) | **split into `routine_tasks` vs `project_tasks`** | User explicitly wants routine (recurring chores) separate from tasks that are steps within a specific project. Project tasks keep today's job-generated/auto-assigned-by-role behavior, just renamed. Routine tasks are a new, lighter table — recurrence rule, assigned household member, no pipeline stage. |

### Roles — from 28 solar org-chart roles down to something like:
- Adult / Parent
- Kid / Dependent
- (optional) External helper — a contractor, tutor, or coach who touches a project but
  isn't a household member (may or may not warrant a real table vs. just a free-text
  field on the project)

**Cut as a consequence of the smaller role set** (flag for confirmation, don't just
silently drop): emergency access lockout, the new-member onboarding checklist workflow,
payroll pay-type multipliers/overtime rules, and most of the GM/Admin permission-grant
system with expiration dates. None of these have an obvious household analog unless the
user wants household-level access control (e.g., "lock a kid's account," "who can edit
the budget") — worth a direct question rather than an assumption.

### Requirements Engine (was Rules Editor / L/P/C Directory)
**Keeps its shape almost exactly** — this is one of the strongest carryovers. The
"pick a type → the app surfaces what's required" pattern generalizes cleanly from
*permits/licenses/compliance* to *permits/certifications/prerequisites* (e.g., pick
"add a deck" → surfaces building-permit requirement; pick "get EMT certified" →
surfaces prerequisite coursework). Verbatim source-text field, verify/unverified
callouts, and the consolidation-of-shared-requirements behavior all still make sense.

### Inventory / BOM / barcode asset registry
**Keeps its shape** — on-hand/needed/ordered status, stock ledger, barcode
scan-in/scan-out, stale-stock notice. Swap the 439-item solar catalog
(`inventory_seed.py`) for either an empty household catalog or a small starter set
(tools, hardware, common supplies). Whether barcode scanning survives at all for a
household inventory is an open question — flagged below.

### Cut entirely — no household equivalent
- Payroll, pay types, overtime, pay periods, payroll reminder
- NM statewide reference data — 33 counties' AHJ contacts, utility interconnection
  contacts (`nm_directory.py`). Either drop, or repurpose as a generic
  **contractor/vendor directory** (plumber, electrician, warranty phone numbers) —
  open question.
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

## Open questions to resolve with the user before/while implementing

1. **Verify stage:** own pipeline stage, or folded into Prep/Wrap-up?
2. **External helpers** (contractor, tutor, coach touching a project): real table, or
   just a free-text field on the project?
3. **Household-level access control:** worth keeping any permission tiers (e.g.
   kid-account restrictions, budget-edit access), or drop all of it?
4. **Vendor/contractor directory:** repurpose `nm_directory.py`'s shape for this, or cut
   outright?
5. **Barcode/asset scanning:** worth keeping for household inventory, or overkill?
6. **Inventory starter catalog:** ship empty, or seed with a small household starter set?

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