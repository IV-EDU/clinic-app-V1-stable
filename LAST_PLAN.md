# LAST_PLAN.md - V1 Roadmap & UI Redesign Plan

> **Single roadmap** for the clinic app.
> Read `AGENTS.md` for behavior rules. Read `KNOWN_ISSUES.md` for what's broken.
> Read `MEMORY.md` for what was done recently.
>
> **Last Updated:** 2026-03-03

---

## Guiding Principles

- One data root: `data/` only. No Docker, Redis, S3, or complex infra.
- Small, safe, shippable steps - each phase works on its own.
- Arabic/RTL is first-class everywhere.
- Build on what exists: current CSS variables, admin, PDF services.
- One phase at a time. Complete and test before moving to next.
- Page-by-page UI rollout - never break the whole app at once.

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

### Step 0 - Safe sidebar wrapper in _base.html <-- NEXT
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

### Step 1 - Dashboard homepage
**Risk:** Low | **Est:** 1 session

First page to opt into sidebar. Replace the plain patient list at `/` with:
- 4 stat cards: Total Patients, Today's Collections, Today's Appointments, Total Outstanding
- Recent Patients mini-table (last 10 patients)
- Quick Actions: Add Patient, New Payment, View Appointments, Admin Settings
- Collection Trends mini-chart (optional - Chart.js)

Move the full patient list to `/patients` (already exists as a route).

**Files:** `templates/core/index.html` or new `templates/core/dashboard.html`, `clinic_app/blueprints/core/core.py`, `clinic_app/services/i18n.py`

### Step 2 - Patient list page
**Risk:** Low | **Est:** 1 session

Opt `/patients` into sidebar. Apply mockup card layout:
- Stat cards strip at top
- Search + filter dropdowns (doctor, date range, balance status)
- Patient table with all existing columns
- Styled pagination

**Files:** `templates/patients/list.html`, `templates/core/index.html`, `clinic_app/services/i18n.py`

### Step 3 - Appointments page
Opt into sidebar. Keep all existing features, just wrap in new layout.

### Step 4 - Expenses, Reports
Opt into sidebar one at a time.

### Step 5 - Admin Settings
Last to convert. Sidebar may eventually replace some internal tab navigation.

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

---

## Progress Tracker

| Phase | Status | Notes |
|-------|--------|-------|
| 0-6 (V1 foundation) | DONE | Theme, branding, Arabic, PDFs |
| UI 1-3 (Design system, modals, search) | DONE | |
| Bugfix: Admin data/audit | DONE | Mar 3 2026 |
| Sidebar Step 0 (base wrapper) | Not started | NEXT |
| Sidebar Step 1 (Dashboard) | Not started | After Step 0 |
| Sidebar Step 2 (Patient list) | Not started | After Step 1 |
| Sidebar Steps 3-5 | Not started | Future |

---

## V2 Ideas (Do Not Start Until V1 Is Done)

- AI/metrics dashboards
- Multi-clinic support
- Cloud backup option
