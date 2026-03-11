# MEMORY_ARCHIVE.md

This file archives older `MEMORY.md` content to keep `MEMORY.md` short and usable.

Archived on: 2026-03-11
Source: snapshot of `MEMORY.md` before trimming.

---

# MEMORY.md - Session Handoff Log

> **For AI agents:** Read this at the START of every session. Update it at the END.
> This file ensures continuity across different chats, tools, and models.
> See `AGENTS.md` for the full protocol.

---

## Current State (updated March 11, 2026)

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

### Session: Reception Desk Plan Finalized (Mar 11 2026)
**What was done:**
- Finalized the Reception Desk + Manager Review plan and updated the planning docs:
  - `docs/RECEPTION_DESK_SPEC.md`
  - `docs/RECEPTION_DESK_IMPLEMENTATION_CONTRACT.md`
  - `docs/RECEPTION_DESK_PHASES.md`
- Confirmed implementation anchors in the live app:
  - Patient file: `templates/patients/detail.html`
  - Live treatments/payments UI: `templates/payments/_list.html`
  - Treatments are parent rows in `payments`; child payments link via `parent_payment_id`.

**Key decisions (locked):**
- Reception staff must not change live data directly; they submit pending entries for manager/admin review.
- Stored statuses remain frozen: `new`, `edited`, `held`, `approved`, `rejected`.
  - “Returned / Needs changes” is a UI label derived from `last_action='returned'` + optional `return_reason` (usually with `status='edited'`).
- Option B editing model: receptionist can **Recall** any time before approval; recall clears manager lock. Held items become `edited` after recall.
- UI direction: one Reception area at `/reception` with internal views (Desk / Manager Queue / History) gated by new permissions; new entry opens as slide-over/modal; no draft-save feature.
- New patient flow: receptionist may mark “New patient”; manager can override to an existing patient when strong duplicate matches exist; otherwise approval can create a new patient then post the treatment/payment.
- Approval auto-posts to live records only after explicit manager/admin confirmation (no silent posting). On posting (especially attaching payment), recompute and persist parent `remaining_cents` correctly.

**What's next:**
- Implement Phase 1–4 (pending backbone + permissions + receptionist UI + manager queue) before enabling approval posting.

### Session: Reception Desk Phase 0 Freeze (Mar 8 2026)
**What was done:**
- Re-read the Reception Desk planning docs and checked them against the live code integration points before starting implementation.
- Confirmed the current live anchors: patient detail lives in `templates/patients/detail.html`, live treatment/payment controls live in `templates/payments/_list.html`, and permissions are enforced through `require_permission(...)` with definitions in `clinic_app/models_rbac.py`.
- Added a new planning handoff file: [docs/RECEPTION_DESK_IMPLEMENTATION_CONTRACT.md](/c:/Users/ivxti/OneDrive/Desktop/GitHub/Clinic-App-Local/docs/RECEPTION_DESK_IMPLEMENTATION_CONTRACT.md).
- Froze the first implementation cycle around: 3 entry sources, 5 core statuses, 3 new workflow permissions, minimum pending-entry field set, validation rules, review rules, and explicit first-release exclusions.
- Updated [docs/RECEPTION_DESK_PHASES.md](/c:/Users/ivxti/OneDrive/Desktop/GitHub/Clinic-App-Local/docs/RECEPTION_DESK_PHASES.md) so Phase 0 is marked frozen for implementation handoff, and linked the spec to the new contract.

**Key decisions:**
- The contract now locks `reception_desk`, `patient_file`, and `treatment_card` as the only initial source codes.
- The first workflow permission set is locked as `reception_entries:create`, `reception_entries:review`, and `reception_entries:approve`.
- Optional queue helper labels stay derived UI labels for later; they are not part of the stored status model in the first slice.
- Receptionist draft controls must remain clearly separate from the existing live `payments:edit` treatment/payment controls.
- Approval posting remains deferred until after pending-entry storage and manager review are working.

**What's next:**
- Start Phase 1 only: design and implement the pending-entry backbone as a separate staging layer.
- Treat `clinic_app/models_rbac.py` as high-attention work when Phase 2 starts.
- Do not start UI or live posting before the staging layer is in place.

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
- (Older session details preserved in this archive.)

### Session: Sidebar Step 3 (Appointments) + Server Fixes (Mar 8 2026)
**What was done:**
- Opted the Appointments page (`/appointments`) into the sidebar shell via `{% set use_sidebar = true %}` in `templates/appointments/vanilla.html`.
- (Older session details preserved in this archive.)

### Session: Patient List Step 2 + RTL CSS Fixes (Mar 3 2026)
**What was done:**
- (Older session details preserved in this archive.)

### Session: Sidebar + Topbar Polish (Mar 3 2026)
**What was done:**
- (Older session details preserved in this archive.)

### Session: Dashboard Homepage (Mar 3 2026)
**What was done:**
- (Older session details preserved in this archive.)

### Session: Sidebar Shell Implementation (Mar 3 2026)
**What was done:**
- (Older session details preserved in this archive.)

### Session: Admin Bugfixes + UI Reskin Planning (Mar 3 2026)
**What was done:**
- (Older session details preserved in this archive.)

### Session: Project Organization & Workflow Redesign (Jul 14 2025)
**What was done:**
- (Older session details preserved in this archive.)

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
| Reception Desk review workflow | Reception drafts; manager/admin approves; system posts on approval only | 2026-03-11 |
| Reception area UX | Single `/reception` area with Desk/Queue/History; modal-first; recall-to-edit | 2026-03-11 |

---

## Template for New Entries

When updating this file, add a new entry under "Recent Sessions":

### Session: [Brief Title]
**Date:** YYYY-MM-DD
**What was done:**
- [bullet points of changes]

**Key decisions:**
- [any new decisions and their reasoning]

