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
- Admin Data tab: analyze preview with P000XXX file numbers, responsive layout
- Admin Audit tab: proper Before/After modal, dark mode technical details
- **Collapsible sidebar** in all opted-in pages (`use_sidebar = true`)
- **Dashboard** (`/`) with stat cards + today's appointments + quick actions
- **Patient list** (`/patients/list`) with stat strip, balance filter pills, sort, paginate
- Full test suite passes

### Known Problems
- See `KNOWN_ISSUES.md` for detailed list
- Admin settings is a 6,000-line monolith (index.html)
- Dark mode has gaps on some pages
- Two expense systems exist (legacy + simple)
- Diagnosis pages are disconnected from main app flow

---

## What's Next - IMPORTANT

### Immediate: Sidebar Step 3 — Appointments page (see LAST_PLAN.md)

**Steps 0, 1, and 2 are DONE.** Steps 0 (sidebar shell), 1 (dashboard), and 2 (patient list) are complete.

**Step 3:** Opt the Appointments page (`/appointments`) into the sidebar.
- Template: `templates/appointments/vanilla.html` — add `{% set use_sidebar = true %}` at the top
- The page already has its own JS-heavy layout; just wrapping it in the sidebar context is enough for Step 3
- Add any needed CSS scoping to `static/css/app.css` if the sidebar layout conflicts with existing appointments CSS
- **Do NOT change route paths, JS logic, appointment data, or the `/api/appointments/...` endpoints**

**After Step 3:** Step 4 = Patient file flow (detail/edit/new), Step 5 = Payments/Expenses/Reports, Step 6 = Admin Settings

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
- `<div class="wrap">` - main content wrapper (max-width: 1100px, overflow-x: hidden)
- `{% block content %}` - child templates inject here
- Theme toggle FAB at bottom-right
- Blocks: `extra_css`, `content`, `extra_js`

**_nav.html structure (448 lines):**
- Horizontal top bar with 3 sections: `.start` (kebab menu + back + home + search), `.center` (logo/brand), `.end` (lang toggle + user/logout)
- Kebab menu has: Appointments, Collections, Expenses, Admin Settings (permission-gated)
- Patient live search with dropdown
- Responsive breakpoints at 1200px, 900px, 768px

**.wrap in app.css:**
- `max-width:1100px; margin:20px auto; padding:0 12px; overflow-x:hidden`
- Admin settings already overrides this with `.wrap:has(.admin-settings-container) { max-width: none; overflow-x: visible; }`

**Theme CSS variables available:** `--primary-color`, `--accent-color`, `--page-bg`, `--bg-surface`, `--text-primary`, `--text-secondary`, `--border`, `--card-shadow`, `--radius-md`, `--radius-lg`, `--spacing-sm/md/lg`, etc. Full list in `static/css/design-system.css` and `static/css/theme-system.css`.

**render_page() injects:** `lang`, `dir`, `t` (translation), `theme_css`, `theme_logo_url`, `clinic_name`, `clinic_tagline`, `user_has_permission`, `show_file_numbers`

**35 templates** extend `_base.html` (21 direct, 14 via sub-bases). All get the sidebar wrapper, but only opted-in pages show it.

---

## Recent Sessions

### Session: Documentation Sync + Prompting System (Mar 8 2026)
**What was done:**
- Performed a deep architecture scan of the repo to identify the true high-value files, risky areas, and doc mismatches
- Confirmed the live code already contains the sidebar shell, dashboard, and patient list rollout
- Synced the roadmap/design guidance to the real code state so future agents stop starting from stale assumptions
- Added a project-local prompting guide for the user with copy-paste templates and safety guardrails
- Clarified that the next UI task is still Appointments sidebar opt-in, UI-only unless a separate bug demands backend work

**Key decisions:**
- The best way to reduce AI mistakes is to fix project instructions first, not to attempt bigger autonomous edits
- Flask remains the correct V1 path; the immediate problem is workflow discipline and documentation consistency, not framework choice
- The agent spec in `agents/clinic-lead-developer.md` is well-designed and should be used for new sessions
- Sidebar adoption and visual polish are two separate concerns — Step 3 should only add the shell, not redesign the page
- The reference screenshot (orange/white dental dashboard) is only inspiration — the app should use its own blue/teal palette defined in DESIGN_BRIEF.md

**What's next:**
- Execute Sidebar Step 3 on `templates/appointments/vanilla.html` as a scoped UI-only task
- Use the `agents/clinic-lead-developer.md` agent spec in the new chat
- Use `PROMPTING_GUIDE.md` for structuring the request

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
