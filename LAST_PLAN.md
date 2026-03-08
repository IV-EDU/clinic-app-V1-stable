# LAST_PLAN.md - V1 Roadmap & UI Redesign Plan

> **Single roadmap** for the clinic app.
> Read `AGENTS.md` for behavior rules. Read `KNOWN_ISSUES.md` for what's broken.
> Read `MEMORY.md` for what was done recently.
>
> **Last Updated:** 2026-03-08

---

## Guiding Principles

- One data root: `data/` only. No Docker, Redis, S3, or complex infra.
- Small, safe, shippable steps - each phase works on its own.
- Arabic/RTL is first-class everywhere.
- Build on what exists: current CSS variables, admin, PDF services.
- One phase at a time. Complete and test before moving to next.
- Page-by-page UI rollout - never break the whole app at once.
- The **sidebar shell is the default direction** for the main app from now on.
- "Uses the sidebar" and "fully matches the new UI language" are related, but not identical. Both must be tracked.

---

## UI End State Target

The goal is **not** only to make a few pages look modern.
The goal is for the clinic app to end V1 with a **consistent main application shell** and a **coherent visual language** across the main working surfaces.

### By the end of the UI rollout, the main app should share:

- the sidebar + slim topbar shell for normal in-app pages
- consistent card spacing, headers, buttons, and table treatment
- consistent dark mode behavior
- consistent Arabic/RTL behavior
- one calm, medical visual direction based on the existing design system

### Coverage rule

We are tracking 2 levels of completion:

- **Shell adoption**: page uses the sidebar shell
- **UI alignment**: page visually matches the new dashboard/patient-list direction closely enough to feel like the same app

### Main surfaces that should be aligned by the end of this phase:

- Dashboard / home
- Patient list
- Patient file flow (detail, edit, new, delete/confirm surfaces where appropriate)
- Appointments
- Main payments flow tied to patients
- Expenses (simple and legacy entry surfaces as needed)
- Reports
- Admin main surfaces

### Special surfaces that may remain intentionally separate or partially aligned:

- Login/auth screens
- Print/PDF/receipt print surfaces
- Diagnosis / tooth-chart / image-heavy specialty pages
- Tiny confirm dialogs or utility forms that do not justify full reskin work yet

These special surfaces should still look clean and consistent, but they do **not** all need the full sidebar-shell treatment immediately.

---

## Completed Phases

### Phase 0 - Data Root & Housekeeping DONE
All runtime storage under `data/`. `_data_root()` in `__init__.py` confirmed.

### Phase 1 - Theme & UI Foundation DONE
`static/css/theme-system.css` created and loaded in `_base.html`. CSS variables for full color palette.

### Phase 2 - Persistent Theme Settings DONE
`theme_settings` table added. `clinic_app/services/theme_settings.py` with get/set. Alembic migration done.

### Phase 3 - Admin Theme & Arabic Settings Tab DONE
Theme tab in admin settings (color, font-size, Arabic toggles). Backend POST route to store settings.

### Phase 4 - Clinic Branding Assets DONE
Local upload for clinic logos. Logo used in `_nav.html` and PDF headers. Files in `data/theme/`.

### Phase 5 - Arabic/RTL Polish ~90% DONE
`i18n.py` has 2000+ lines, full `en`/`ar` dictionary. `T()` globally registered. Cairo font bundled.
**Remaining:** New features need Arabic entries added to `i18n.py` (ongoing).

### Phase 6 - PDF Styling Integration DONE
Theme colors and uploaded logo in PDF services. Arabic reshaping for PDF output.

### UI Phase 1 - CSS Design System + Dark Mode DONE
`design-system.css` (1500+ lines). FOUC prevention, FAB toggle, dark mode via `[data-theme="dark"]`.

### UI Phase 2 - Modal System + Toast Notifications DONE
`components.css`, `modal-system.js`, `toast.js`. Verified in light, dark, and RTL modes.

### UI Phase 3 - Arabic Search + Global Search Bar DONE
`arabic_search.py` with `normalize_arabic`. Global search bar in `_nav.html` with keyboard nav.

### Bugfix: Admin Data & Audit Tab DONE (Mar 3 2026)
- Audit modal: proper Before/After columns for updates, single column for create/delete
- Dark mode: audit technical details pre block styled correctly
- Analyze preview: backend generates sequential P000XXX file numbers
- Data tab layout: responsive overflow fix for windowed browsers
- i18n: added audit_deleted_value and audit_created_value keys (EN+AR)

---

## Current Phase: UI Reskin - Collapsible Sidebar + Page-by-Page Rollout

> **Strategy:** Add a sidebar to `_base.html` that is hidden by default. Pages opt in with
> `{% set use_sidebar = true %}`. Old pages look identical. New pages get the modern layout.
> This means zero breakage and we can roll out one page at a time.

### Current Reality Check (Mar 8 2026)

The live code confirms:

- Sidebar shell is implemented in the base layout
- Dashboard is opted in
- Patient list is opted in
- Appointments is **not yet** opted in
- Patient detail/file pages are **not yet** opted in
- Most other major surfaces still extend `_base.html` without sidebar activation

This means the rollout direction is correct, but the roadmap must treat sidebar adoption across the rest of the app as still unfinished.

### Step 0 - Safe sidebar wrapper in _base.html DONE
**Risk:** Low (hidden by default) | **Est:** 1 session

Add to `_base.html`:
- Flex shell: `<div class="app-shell"><aside class="sidebar">...</aside><main>...existing...</main></div>`
- Sidebar contents: iSmile logo/branding, nav links (Home, Patients, Appointments, Expenses, Admin Settings), collapse toggle
- **Collapsible:** expanded (~240px icons+labels) / collapsed (~60px icons only), state saved in `localStorage`
- **Hidden by default** - only pages with `{% set use_sidebar = true %}` activate it
- RTL: sidebar flips to right side
- Dark mode: sidebar respects theme variables
- Print: sidebar hidden via `@media print`
- Mobile (<768px): sidebar becomes off-canvas drawer with hamburger button
- Search bar, language toggle, user/logout move to a slim top bar in the main content area

**Files:** `templates/_base.html`, `templates/_nav.html`, `static/css/app.css`

### Step 1 - Dashboard homepage DONE
**Risk:** Low | **Est:** 1 session

First page to opt into sidebar. Replace the plain patient list at `/` with:
- 4 stat cards: Total Patients, Today's Collections, Today's Appointments, Total Outstanding
- Recent Patients mini-table (last 10 patients)
- Quick Actions: Add Patient, New Payment, View Appointments, Admin Settings
- Collection Trends mini-chart (optional - Chart.js)

Move the full patient list to `/patients` (already exists as a route).

**Files:** `templates/core/index.html` or new `templates/core/dashboard.html`, `clinic_app/blueprints/core/core.py`, `clinic_app/services/i18n.py`

### Step 2 - Patient list page DONE
**Risk:** Low | **Est:** 1 session

Opt `/patients` into sidebar. Apply mockup card layout:
- Stat cards strip at top
- Search + filter dropdowns (doctor, date range, balance status)
- Patient table with all existing columns
- Styled pagination

**Files:** `templates/core/patients_list.html`, `clinic_app/blueprints/core/core.py`, `clinic_app/services/i18n.py`

### Step 3 - Appointments page <-- NEXT
**Risk:** Low-Medium | **Est:** 1 session

Opt `/appointments` into sidebar. Keep all existing features, just wrap in new layout.

- Add `{% set use_sidebar = true %}` to `templates/appointments/vanilla.html`
- Fix any sidebar-specific spacing or overflow conflicts in `static/css/app.css`
- Do **not** change route paths, embedded JS behavior, API contracts, or appointment business logic in this step

**Files:** `templates/appointments/vanilla.html`, `static/css/app.css`

### Step 4 - Patient file flow
**Risk:** Medium | **Est:** 1-2 sessions

Bring the patient file surfaces into the new shell one focused surface at a time.

Priority order:
- `templates/patients/detail.html`
- `templates/patients/edit.html`
- `templates/patients/new.html`
- patient confirm/delete surfaces only if needed for consistency

Rules:
- Keep patient actions, modal flows, payment fragments, and permissions working exactly as they do now
- Do not mix this step with payment logic or diagnosis changes
- Treat the patient detail page as a major surface, not a minor follow-up

### Step 5 - Payments, Expenses, Reports
**Risk:** Medium | **Est:** multiple small sessions

Continue sidebar adoption and UI alignment across the remaining everyday work surfaces.

Sub-order:
- per-patient payment entry/edit surfaces where they are part of daily workflow
- simple expenses
- legacy expenses main surfaces
- reports landing and major report pages

Do this one area at a time, not as one large batch.

### Step 6 - Admin Settings
**Risk:** Medium-High | **Est:** multiple sessions

Admin stays last because it is broad, dense, and easier to destabilize.

- Sidebar should become the outer shell for the admin area
- Internal admin navigation may later be simplified or partially replaced
- Do not attempt a full admin redesign in one step

### Step 7 - Coverage review and polish
**Risk:** Low-Medium | **Est:** 1-2 sessions

Before declaring the rollout complete, perform a final coverage check.

Confirm:
- all main surfaces use the intended shell
- dark mode is consistent
- RTL is consistent
- spacing/cards/buttons/tables feel like one app
- any intentionally excluded specialty pages are documented as exceptions

---

## Future Phases (After Sidebar Rollout)

| Phase | What | Priority | Risk |
|-------|------|----------|------|
| Admin Split | Split 6,000-line admin settings into focused pages | Medium | Medium |
| Expense Consolidation | Evolve simple expenses, soft-deprecate legacy | Medium | Medium |
| Reception Workflow | Check-in, status tracking, quick actions | High | Low-Med |
| Patient Detail Redesign | Tabs, better layout, add patient modal | Medium | Medium |
| Reports Simplification | Dashboard-style landing for reports | Medium | Low |
| Duplicate/Merge Polish | Side-by-side comparison, one-click merge | Medium | Low-Med |
| Keyboard Shortcuts | Ctrl+K search, Ctrl+N new patient | Low | Low |
| Audit Enhancements | Before/after diffs, undo capability | Low | Medium |
| Receipt/Print Polish | Consistent styling, preview, batch print | Low | Low |

---

## Implementation Rules

1. **One step at a time.** Complete and test before moving to next.
2. **UI-only changes first** within each step, then backend if needed.
3. **Run tests** after any backend change (`Run-Tests.bat`).
4. **Update docs** after every step (`docs/INDEX.md`, `MEMORY.md`).
5. **Import/backup/merge Python logic: DO NOT MODIFY** unless specifically fixing a bug.
6. **Arabic translations** must be added for every new display string.
7. **Dark mode** must work for every new component.
8. **Page-by-page rollout** - never break the whole app. Use `{% set use_sidebar = true %}` to opt in.
9. **Do not assume shell adoption equals full redesign.** Check visual consistency separately.
10. **Treat patient detail and patient-facing payment flow as core surfaces.** They are not optional leftovers.

---

## Progress Tracker

| Phase | Status | Notes |
|-------|--------|-------|
| 0-6 (V1 foundation) | DONE | Theme, branding, Arabic, PDFs |
| UI 1-3 (Design system, modals, search) | DONE | |
| Bugfix: Admin data/audit | DONE | Mar 3 2026 |
| Sidebar Step 0 (base wrapper) | DONE | Sidebar shell, topbar, collapse, mobile drawer |
| Sidebar Step 1 (Dashboard) | DONE | `/` redesigned as dashboard |
| Sidebar Step 2 (Patient list) | DONE | `/patients/list` moved to sidebar layout |
| Sidebar Step 3 (Appointments) | DONE | Mar 8 2026 - Opted into sidebar |
| Sidebar Step 4 (Patient file flow) | DONE | Mar 8 2026 - detail/edit/new wrapped in shell |
| Sidebar Step 5 (Payments, Expenses, Reports) | DONE | Mar 8 2026 - Wrapped in shell
| Sidebar Step 6 (Admin Settings) | DONE | Mar 8 2026 - Last major rollout area |
| Sidebar Step 7 (Coverage review) | DONE | Mar 8 2026 - Visual audit verified app-wide alignment |

---

## V2 Ideas (Do Not Start Until V1 Is Done)

- AI/metrics dashboards
- Multi-clinic support
- Cloud backup option
