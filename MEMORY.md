# MEMORY.md - Session Handoff Log

> **For AI agents:** Read this at the START of every session. Update it at the END.
> This file ensures continuity across different chats, tools, and models.
> See `AGENTS.md` for the full protocol.

---

## Current State (updated March 8, 2026)

**App status:** Running, stable. Flask + SQLite dental clinic on Windows.
**Branch:** `main`
**Repo:** `IV-EDU/clinic-app-V1-stable` (default branch: `main`)
**Data:** 1,021 patients, 912 payments. Production use.
**Login:** `admin` / `admin` (NEVER change this)
**Tests:** 107 passing, 2 skipped (verified March 8, 2026).

### What Works
- Core patient CRUD, payments, receipts (PDF with Arabic reshaping)
- Appointments page (vanilla.html) - clean card-based UI
- Simple expenses - minimal working flow
- Arabic/RTL with Cairo font, `T()` i18n system (2000+ translations)
- Dark mode toggle (design-system.css + data-theme attribute)
- Theme settings (admin), clinic logo/branding
- Admin Data tab: analyze preview with horizontal scrolling table, proper wrapping
- Admin Audit tab: proper Before/After modal, dark mode technical details
- **Collapsible sidebar** on ALL major pages — Dashboard, Patients, Appointments, Payments, Expenses, Reports, Admin Settings
- **Dashboard** (`/`) with stat cards + today's appointments + quick actions
- **Patient list** (`/patients/list`) with stat strip, balance filter pills, sort, paginate
- Full test suite passes

### Known Problems
- See `KNOWN_ISSUES.md` for detailed list
- Admin settings is a 6,000-line monolith (templates/admin/settings/index.html) — now in sidebar but not split
- Dark mode has occasional minor gaps on specialty pages (diagnosis, print views)
- Two expense systems exist but legacy is removed from nav and UI; only simple expenses shown
- Diagnosis pages are disconnected from main app flow

---

## What's Next - IMPORTANT

### THE V1 SIDEBAR ROLLOUT IS COMPLETE

All 7 steps of the Sidebar Phase (see `LAST_PLAN.md`) are **DONE** as of March 8, 2026.

The next phase of work is documented in `LAST_PLAN.md` under "Future Phases (After Sidebar Rollout)". The top priorities are:

1.  **Reception Workflow** (High priority) — Check-in, status tracking, quick appointment actions
2.  **Expense Consolidation** (Medium) — Evolve simple expenses, soft-deprecate legacy
3.  **Patient Detail Redesign** (Medium) — Tabs, better layout, add patient modal

The user will specify which of these to start next.

### Agent startup order (important)

Every new chat agent should read files in this order before proposing work:
1. `AGENTS.md`
2. `MEMORY.md`
3. `KNOWN_ISSUES.md`
4. `LAST_PLAN.md`
5. `DESIGN_BRIEF.md` for UI work
6. `PROMPTING_GUIDE.md` if the user request is broad or non-technical

### Key architecture context for the next agent:

**_base.html structure:**
- `<html lang="{{ lang }}" dir="{{ dir }}">`
- `<head>` loads: app.css -> theme-system.css -> design-system.css -> components.css + JS files
- `{{ theme_css|safe }}` injects admin theme overrides as inline `:root` CSS
- `{% include '_nav.html' %}` - top horizontal nav bar (~450 lines)
- `<aside class="sidebar" id="app-sidebar">` — Collapsed sidebar (240px wide, 64px when collapsed). An INLINE `<script>` immediately follows the `<aside>` tag to read `localStorage('sidebar_collapsed')` and apply `.collapsed` before the browser paints, preventing flash.
- `<div class="sidebar-main">` - main content wrapper pushed to the right of the sidebar
- `{% block content %}` - child templates inject here
- Theme toggle FAB at bottom-right (hidden on sidebar pages)
- Blocks: `extra_css`, `content`, `extra_js`

**Sidebar key facts:**
- Opt-in per-template: `{% set use_sidebar = true %}` at top of template
- Sidebar collapse state stored in `localStorage` key `sidebar_collapsed`
- Collapse state read INLINE (directly after `<aside>` tag) to avoid FOUC on heavy pages
- Toggle button is at `left: 240px` (flush with outer edge, NOT overlapping menu items)
- RTL: sidebar flips to right, toggle button uses `right: 240px`
- Branding: logo (`theme_logo_url`), clinic name (`clinic_name`) in primary color, tagline (`clinic_tagline`) below name
- Active nav item: gold active background (`.sidebar-item.active`)
- CSS: `static/css/app.css` (sections 5-7, ~300 lines, starting at `.sidebar-collapse-btn`)

**render_page() injects:** `lang`, `dir`, `t` (translation), `theme_css`, `theme_logo_url`, `clinic_name`, `clinic_tagline`, `user_has_permission`, `show_file_numbers`


---

## Recent Sessions

### Session: Reception Desk Workflow Planning (Mar 8 2026)
**What was done:**
- Deeply reviewed the live patient/treatment/payment structure before planning the receptionist workflow.
- Confirmed that treatments are parent payment rows and later payments are child rows linked by `parent_payment_id`, so receptionist intake must not post directly to live payment data.
- Agreed on a new temporary planning doc: [docs/RECEPTION_DESK_SPEC.md] to preserve the design across future chats.
- Wrote the first working spec for the planned `Reception Desk + Manager Review` system.
- Extended the spec with 3 entry modes: `Reception Desk`, `Patient File`, and `Treatment Card`.
- Added a separate implementation roadmap doc: [docs/RECEPTION_DESK_PHASES.md].

**Key decisions:**
- Receptionist remains responsible for main entry work, but all entries go to pending review first.
- Receptionist form should use: page number, name, phone, visit type, treatment, doctor, note, and optional payment fields.
- `Remaining` must always be system-calculated and read-only; receptionist never types it.
- `Total` and `Discount` stay optional; `Paid today` can be submitted by itself when money was received.
- Manager actions are `Approve`, `Edit`, `Choose different patient`, `Hold`, and `Reject`.
- `Edit` updates only the pending draft and returns to review; approval stays separate.
- Multiple patient suggestions must be handled inline in the review screen, not by sending the manager to new tabs.
- Daily review and duplicate cleanup / merge workflow must remain separate systems.
- If entry starts from `Patient File`, patient identity is locked and receptionist should not retype name/phone.
- If entry starts from `Treatment Card`, both patient and treatment are locked.
- Manager review should treat `Treatment Card` as strongest context, `Patient File` as strong context, and `Reception Desk` as weaker/manual context.
- New workflow must be permission-based, not role-name-based.
- Receptionist draft controls should later use `+ Treatment Entry` / `+ Payment Entry` with helper text like `Sent for manager review`.

**What's next:**
- Continue refining the Reception Desk spec before any implementation.
- Later create a separate Merge Center plan after the reception workflow is clearer.

### Session: Analyze Tab Horizontal Scroll Fix (Mar 8 2026)
**What was done:**
- Fixed Admin > Data > Analyze tab — tables were not wrapping/scrollable correctly with the sidebar active (narrower viewport).
- **Root causes found (3):** (1) Global `table { width: 100% }` forced the 9-column table to compress into the container rather than overflow. (2) `th` cells were wrapping multi-line (e.g. "FILE\nNUMBER"), shrinking columns enough that overflow never triggered. (3) `.data-subpane` (direct grid child of `.admin-form`) lacked `min-width: 0`.
- **Fix applied:** Inline styles `overflow-x:auto; width:100%` on `.data-scroll-area` divs, `width:auto; min-width:100%` on the two `admin-table` elements; plus page-scoped CSS `white-space: nowrap` on `th` and `min-width: 0` on `.data-subpane` in the admin settings `<style>` block.
- Added base `.data-scroll-area` rule to `app.css` (cache bumped to v=13).

**Key decisions:**
- Inline styles used on specific HTML elements for maximum reliability (class-based CSS was being overridden by load-order/cascade issues).
- `white-space: nowrap` on `th` is the critical trigger — without it, column headers wrap and the table fits in the container, so the scroll never fires.

**What's next:**
- V1 Sidebar Rollout is COMPLETE. Next task is from `LAST_PLAN.md` Future Phases: Reception Workflow (High), Expense Consolidation (Medium), or Patient Detail Redesign (Medium).

### Session: Sidebar Steps 5, 6, 7 + Bug Fixes (Mar 8 2026)
**What was done:**
- **Sidebar Steps 5, 6, 7** fully completed — all major pages now use the sidebar shell.
  - Step 5 (Payments, Expenses, Reports): Opted in `templates/payments/form.html`, `templates/simple_expenses/base.html`, `templates/reports/collections.html` and related report templates. Fixed `.simple-expenses-container` to use `flex: 1` instead of `min-height: 100vh` to prevent over-stretching.
  - Step 6 (Admin Settings): Opted in `templates/admin/settings/index.html`. Re-targeted the wide-container override from `.wrap:has(...)` to `.wrapper:has(...)`.
  - Step 7 (Coverage Review): Visually audited the Dashboard, Patient List, Patient File, and Admin Settings in all 4 combinations (LTR/RTL + Light/Dark). Zero regressions found.
- **Legacy Expenses cleanup**: Deleted `clinic_app/blueprints/expenses/` and `templates/expenses/` directories. Unregistered from `__init__.py`. User confirmed no old data to preserve.
- **Sidebar FOUC bug fixed**: The toggle button's `localStorage` state check was moved **inline** immediately after the `<aside>` tag in `_base.html`. This ensures the browser applies the `.collapsed` class *before* painting on heavy pages like Admin Settings, eliminating the visual flash.
- **Sidebar toggle button overlap fixed**: Shifted the toggle button from `left: 228px` to `left: 240px` (and corresponding RTL `right:` values), so it sits flush with the outer sidebar edge without imposing on the menu items.
- **Sidebar branding**: Logo enlarged, clinic name styled in primary brand color, clinic tagline from Admin Theme settings injected below the name.
- **107 tests passing** throughout.

**Key decisions:**
- FOUC fix must be inline (not DOMContentLoaded) because heavy pages delay script execution.
- Toggle button must sit at exactly `left: 240px` (the sidebar width boundary), not inside it.
- Legacy expenses removed only after confirming user had no previous expense data.

**What's next:**
- V1 Sidebar Rollout is COMPLETE. The next task is one of the Future Phases in `LAST_PLAN.md` (Reception Workflow, Expense Consolidation, Patient Detail Redesign, etc.)


**What was done:**
- Integrated the core Patient File flow (`templates/patients/detail.html`, `edit.html`, `new.html`) into the sidebar shell using the `{% set use_sidebar = true %}` switch.
- Verified visual stability: The embedded `payments/_list.html` component scales down gracefully inside the `.sidebar-main` container.
- Confirmed modals (Edit Patient, merge previews, print receipts) are unaffected by the sidebar presence.
- Evaluated RTL support: Navigation and layout successfully mirror when Arabic is selected.
- 110 tests passed without issue.

**Key decisions:**
- Patient actions (Merge, Delete) and their respective confirmation pages were deliberately omitted from this scope as per `LAST_PLAN.md` instructions restricting scope to primary flow files to minimize regression risks on unmapped edges.

**What's next:**
- Execute **Sidebar Step 5**: Payments, Expenses, and Reports. This will cover the standalone payments flow, simple expenses, legacy expenses root, and the reports main hub.

### Session: Sidebar Step 3 (Appointments) + Server Fixes (Mar 8 2026)
**What was done:**
- Opted the Appointments page (`/appointments`) into the sidebar shell via `{% set use_sidebar = true %}` in `templates/appointments/vanilla.html`.
- Implemented a server-startup safeguard: Created `.agents/workflows/start-server.md` and updated `AGENTS.md` specifying `python wsgi.py` as the preferred server start method to bypass Powershell script strictness, and explicitly instructing agents to cleanly terminate the port (`send_command_input` with `Terminate: true`).
- Verified the Sidebar layout via browser agent; Arabic/RTL mirrors correctly and components fit alongside the sidebar.
- 107 tests run, all passing (no regressions in data or API structure).
- Documented progress in `LAST_PLAN.md`, `CHANGELOG.md`, and `MEMORY.md`.

**Key decisions:**
- UI changes for appointments remain purely layout-wrapper opt-ins. All dense internal CSS and JS was preserved intact, keeping risk near zero.
- The workflow documentation approach (`.agents/workflows/`) is now the established way to prevent AI execution loops on system-specific tooling.

**What's next:**
- Execute **Sidebar Step 4**: Patient file flow (starting with `templates/patients/detail.html`).
- Ensure the detail page (which includes embedded payments and receipts) is cleanly enveloped by the sidebar and its internal navigation components don't clash.

### Session: Documentation Sync + Prompting System (Mar 8 2026)

### Session: Patient List Step 2 + RTL CSS Fixes (Mar 3 2026)
**What was done:**
- Fixed all Arabic/RTL sidebar bugs: compound CSS selector `html[dir="rtl"].has-sidebar` → `html[dir="rtl"] .has-sidebar` (4 rules in `app.css`, 3 in `_nav.html` inline style)
- Fixed collapse-button hover jump: added `transform .22s ease` to transition, removed redundant `translateY(-50%)` from both hover rules
- Bumped CSS cache to `?v=5` then `?v=6`
- **Step 2 complete:** Patient list (`/patients/list`) now has:
  - Stat strip: "Total Patients" (all-time) + "With Balance" (outstanding count)
  - Balance filter pill-row: All | With Balance | Paid Up (SQL correlated subquery reusing payments ledger formula)
  - `balance` param preserved in search form hidden input, sort link, and all pagination links
  - `overall_total` + `with_balance_count` computed in backend and passed to template
- Added i18n keys: `outstanding_balances`, `balance_filter_label`, `balance_filter_all`, `balance_filter_owed`, `balance_filter_paid` (EN + AR)
- 107 tests pass, 2 skipped — no regressions

**What's next (Step 3):** Opt Appointments page into sidebar (`{% set use_sidebar = true %}` in `templates/appointments/vanilla.html`). Keep all existing JS/data behaviour, just wrap in new layout. Files: `templates/appointments/vanilla.html`, `static/css/app.css`.

### Session: Sidebar + Topbar Polish (Mar 3 2026)
**What was done:**
- Fixed the core visual problem: sidebar pages now have a proper product app layout
- Slim fixed topbar (56px): white bg, no gradient, search fills width, dark mode toggle, user/logout only
- Topbar floats to the RIGHT of the sidebar (via `position: fixed; left: 240px`), collapses with sidebar
- Sidebar now `top: 0; height: 100vh` — full height from very top of screen
- Page background set to `var(--color-bg, #f4f5f7)` — light gray so white cards float off it
- Sidebar-main gets `padding-top: 56px` to clear the fixed topbar
- Hardcoded `--nav-h: 56px` in JS instead of measuring from DOM (fixes timing issue with fixed nav)
- Added dark mode toggle button in topbar (class `topbar-theme-btn`); hidden on non-sidebar pages; FAB hidden on sidebar pages
- Sidebar active item: stronger color + icon opacity polish + subtle divider at top of nav
- Hidden on sidebar: kebab, home-btn, center brand, lang-toggle, back-btn
- RTL: topbar `left: 0; right: 240px`; dark mode: all scoped with `html[data-theme="dark"].has-sidebar`
- All 107 tests pass

**What's next:**
- Roll out sidebar to other pages one at a time (Patients detail, Appointments, Expenses, Admin)
- Each just needs `{% set use_sidebar = true %}` at top of template

### Session: Dashboard Homepage (Mar 3 2026)
**What was done:**
- Phase 1 Step 1 complete: home page (`templates/core/index.html`) rewritten as a dashboard
- Opted in to sidebar with `{% set use_sidebar = true %}`
- Dashboard layout: page header with scheduled/done badges, 3 stat cards (Total Patients, Today's Collections, Appointments Today), search bar with sort + Add Patient, patient table with avatar initials, updated pagination counter
- Backend unchanged — all data was already available (`total_patients`, `today_total`, `appointments_count`, `upcoming_count`, `completed_count`, `patients`, etc.)
- Added dashboard CSS section to `static/css/app.css` (scoped to `.dashboard-page`, ~180 lines)
- Added i18n keys: `dashboard_overview`, `dashboard_subtitle`, `todays_collections`, `recent_patients`, `manage_patient_records`, `this_week`, `showing`, `of` (EN + AR)
- 107 tests pass, 2 skipped — no regressions

**What's next:**
- Roll out sidebar to other pages (Patients list, Appointments, Payments, Expenses, Admin Settings) — one page at a time, just add `{% set use_sidebar = true %}` to each template

### Session: Sidebar Shell Implementation (Mar 3 2026)
**What was done:**
- Phase 1 Step 0 complete: collapsible left sidebar added to `_base.html`
- Sidebar HTML: logo/brand, nav links (Home, Appointments, Collections, Expenses, Admin), collapse toggle
- Sidebar is **hidden by default** — pages opt in with `{% set use_sidebar = true %}`
- CSS appended to `static/css/app.css` (scoped to `.has-sidebar`/`.sidebar`, ~230 lines)
- Collapse state saved in `localStorage` key `sidebar_collapsed`
- RTL: sidebar flips to right side; Dark mode: uses theme CSS vars; Print: hidden; Mobile: off-canvas drawer + hamburger (injected via JS)
- Fixed Jinja2 `block 'content' defined twice` bug (used single block with conditional wrapper)
- All 107 tests pass, 2 skipped — no regressions

**Key decisions:**
- Block-twice Jinja2 error fixed by using one `{% block content %}` with conditional `class`/`id` on wrapper div
- `.has-sidebar` on body + `.sidebar-main` on content wrapper → CSS handles margin push
- `--nav-h` CSS var set dynamically from `.header.offsetHeight` in JS

**What's next:**
- Step 1: Dashboard homepage (first page to opt into sidebar with `{% set use_sidebar = true %}`)
  - Stats cards: Total Patients, Today's Collections, Appointments today
  - Recent patients table (restyled)
  - Files: `templates/core/index.html` (or new dashboard template), `clinic_app/blueprints/core/core.py`

### Session: Admin Bugfixes + UI Reskin Planning (Mar 3 2026)
**What was done:**
- Fixed audit modal Before/After columns (was showing "CURRENT"/"CURRENT")
- Fixed dark mode technical details pre block
- Fixed FILE NUMBER in analyze preview (backend generates P000XXX)
- Fixed data tab responsive layout (overflow clipping on windowed browsers)
- Added i18n keys: audit_deleted_value, audit_created_value (EN+AR)
- Committed bugfixes as d401ce5
- Committed cleanup of 117 pre-existing uncommitted changes
- Updated LAST_PLAN.md: removed packaging/exe plans, added sidebar rollout plan
- Updated MEMORY.md with full context for next agent

**Key decisions:**
- User wants full UI reskin with collapsible left sidebar (inspired by mockup screenshots)
- Page-by-page rollout (not all-at-once) to avoid breaking the app
- Sidebar hidden by default, pages opt in with `{% set use_sidebar = true %}`
- Keep all existing features/data/buttons, just reorganize into new layout
- Keep existing theme system and colors

### Session: Project Organization & Workflow Redesign (Jul 14 2025)
**What was done:**
- Full project organization audit
- Rewrote AGENTS.md, created MEMORY.md, DESIGN_BRIEF.md
- Merged plans into LAST_PLAN.md
- Moved skills, deleted stale files
- Updated .gitignore

---

## Active Decisions Log

| Decision | Reason | Date |
|----------|--------|------|
| Flask for V1 (not React rewrite) | Polish existing app (~4-6 weeks) vs rewrite (~3-5 months) | 2025-07-14 |
| Collapsible sidebar layout | User's mockup preference, modern medical app feel | 2026-03-03 |
| Page-by-page rollout | Avoid breaking the whole app, can revert individual pages | 2026-03-03 |
| Sidebar hidden by default | Zero breakage on day one, opt-in per page | 2026-03-03 |
| Keep existing theme system | Colors configurable via Admin > Theme, no hard-coded scheme change | 2026-03-03 |
| Prompt-template workflow for AI tasks | Reduce vague prompts, narrow scope, and prevent cross-feature regressions | 2026-03-08 |

---

## Template for New Entries

When updating this file, add a new entry under "Recent Sessions":

### Session: [Brief Title]
**Date:** YYYY-MM-DD
**What was done:**
- [bullet points of changes]

**Key decisions:**
- [any new decisions and their reasoning]
