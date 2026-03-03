# LAST_PLAN.md – V1 Roadmap & UI Redesign Plan

> **Single roadmap** for the clinic app. Combines the original V1 plan with the 15-phase UI redesign.
> Read `AGENTS.md` for behavior rules. Read `KNOWN_ISSUES.md` for what's broken.
> Read `MEMORY.md` for what was done recently.
>
> **Last Updated:** 2025-07-14

---

## Guiding Principles

- One data root: `data/` only. No Docker, Redis, S3, or complex infra.
- Small, safe, shippable steps — each phase works on its own.
- Arabic/RTL is first-class everywhere.
- Build on what exists: current CSS variables, admin, PDF services, batch scripts.
- One phase at a time. Complete and test before moving to next.

---

## Completed Phases

### Phase 0 – Data Root & Housekeeping ✅
All runtime storage under `data/`. `_data_root()` in `__init__.py` confirmed.

### Phase 1 – Theme & UI Foundation ✅
`static/css/theme-system.css` created and loaded in `_base.html`. CSS variables for full color palette.

### Phase 2 – Persistent Theme Settings ✅
`theme_settings` table added. `clinic_app/services/theme_settings.py` with get/set. Alembic migration done.

### Phase 3 – Admin Theme & Arabic Settings Tab ✅
Theme tab in admin settings (color, font-size, Arabic toggles). Backend POST route to store settings.

### Phase 4 – Clinic Branding Assets ✅
Local upload for clinic logos. Logo used in `_nav.html` and PDF headers. Files in `data/theme/`.

### Phase 5 – Arabic/RTL Polish ~90% ✅
`i18n.py` has 2000+ lines, full `en`/`ar` dictionary. `T()` globally registered. Cairo font bundled.
**Remaining:** New features need Arabic entries added to `i18n.py` (ongoing).

### Phase 6 – PDF Styling Integration ✅
Theme colors and uploaded logo in PDF services. Arabic reshaping for PDF output.

### UI Phase 1 – CSS Design System + Dark Mode ✅
`design-system.css` (1500+ lines). FOUC prevention, FAB toggle, dark mode via `[data-theme="dark"]`.
Dark blue-grey base (`#1a1d23`), not pure black. Per-user toggle in localStorage.

### UI Phase 2 – Modal System + Toast Notifications ✅
`components.css`, `modal-system.js`, `toast.js`. Verified in light, dark, and RTL modes.

### UI Phase 3 – Arabic Search + Global Search Bar ✅
`arabic_search.py` with `normalize_arabic`. Global search bar in `_nav.html` with keyboard nav.

---

## Current / Next Phases

### Phase 7 – Final Polish & Packaging ~70%
- ~~PyInstaller spec, build scripts, frozen-mode detection.~~
- **TODO:** Create `PACKAGING.md`, update `README.md` with theme/logo/language docs.
- **TODO:** Final UI consistency pass across all major screens.

### UI Phase 4 – Split Admin Settings (NEXT — Highest Priority)
**Risk:** Medium | **Est:** 2 sessions

Split the 5,700-line admin settings monolith into 5 focused pages:
1. `admin/users.py` — User & role management
2. `admin/doctors.py` — Doctor management
3. `admin/appearance.py` — Theme, colors, logos, branding
4. `admin/data.py` — Import, export, backups, duplicates (keep import logic AS-IS)
5. `admin/audit.py` — Audit viewer, export, privacy

Also:
- Split the 5,700-line template into 5 separate pages
- Each page gets its own nav link under "Admin" dropdown
- Fix: remove duplicated `merge_mode` line
- Add: audit events for patient merge, import commit, backup/restore

**Files:** Create `clinic_app/blueprints/admin/{users,doctors,appearance,data,audit}.py`, create `templates/admin/{users,doctors,appearance,data,audit}.html`, edit `_nav.html`.
**Safety:** Import logic COPY as-is. Keep all route URLs working (add redirects). Run full test suite.

### UI Phase 5 – Dashboard Homepage + Nav Restructure
**Risk:** Medium | **Est:** 2 sessions

Replace home page (patient list) with a dashboard:
- Today's stats cards: patients seen, appointments, payments collected
- Quick actions: new patient, new appointment, new expense
- Recent activity feed (last 10 events)
- Move patient list to a "Patients" page

Nav restructure: Dashboard | Patients | Reception | Appointments | Reports | Admin dropdown.
Backup automation: auto-backup on startup if >24h old, rotation (max 30 / 90 days).

### Phase E – Expense Consolidation
**Risk:** Medium | **Est:** 1–2 sessions

Evolve simple expenses into a medium-weight "Clinic Expenses" system:
- Add optional category (Lab Work, Materials, Equipment, Rent, Utilities, Salaries, Other)
- Add optional receipt photo upload
- Add monthly summary view
- Keep simple entry form as default
- Keep legacy expenses code but hide from nav (soft-deprecate)
- Migration: add `category` column to `simple_expenses` table

---

## Future Phases (Not Started)

| Phase | What | Priority | Risk |
|-------|------|----------|------|
| UI 6 | Reception tab (active workflow — check-in, status, quick actions) | High | Low-Med |
| UI 7 | Data entry tab (batch payments, paste from Excel, staging/review) | High | Medium |
| UI 8 | Patient files list redesign (cards, filters, sort) | Medium | Low |
| UI 9 | Patient detail tabs + add patient modal + merge modal fix | Medium | Medium |
| UI 10 | Reports simplification (dashboard-style landing) | Medium | Low |
| UI 11 | Duplicate/merge UX polish (side-by-side, one-click merge) | Medium | Low-Med |
| UI 12 | Keyboard shortcuts (Ctrl+K search, Ctrl+N new patient, ? help) | Low | Low |
| UI 13 | Audit trail enhancements (before/after diffs, tombstones, undo) | Low | Medium |
| UI 14 | Receipt/print polish (consistent styling, preview, batch print) | Low | Low |
| UI 15 | Backup status indicator + quick backup button | Low | Low |

---

## Implementation Rules

1. **One phase at a time.** Complete and test before moving to next.
2. **UI-only changes first** within each phase, then backend if needed.
3. **Run tests** after any backend change (`scripts/Run-Tests.bat` or `scripts/Run-Validation.bat`).
4. **Update docs** after every phase (`docs/INDEX.md`, `MEMORY.md`, `docs/CHANGELOG.md`).
5. **Import/backup/merge Python logic: DO NOT MODIFY** unless specifically fixing a bug.
6. **Arabic translations** must be added for every new display string.
7. **Dark mode** must work for every new component.
8. **Read `DESIGN_BRIEF.md`** before any UI work.

---

## Progress Tracker

| Phase | Status | Notes |
|-------|--------|-------|
| 0–6 (V1 foundation) | ✅ Done | Theme, branding, Arabic, PDFs |
| 7 (Packaging) | ~70% | Missing PACKAGING.md, README update, final polish |
| UI 1 (Design system) | ✅ Done | design-system.css, dark mode, FOUC prevention |
| UI 2 (Modals/toasts) | ✅ Done | components.css, modal-system.js, toast.js |
| UI 3 (Arabic search) | ✅ Done | normalize_arabic, global search bar |
| UI 4 (Admin split) | Not started | NEXT — highest priority |
| UI 5 (Dashboard) | Not started | After UI 4 |
| E (Expenses) | Not started | After UI 5 |
| UI 6–15 | Not started | Future |

---

## V2 Ideas (Do Not Start Until V1 Is Done)

*Add ideas here as they come up.*

- AI/metrics dashboards
- Playwright visual regression tests
- Multi-clinic support
- Cloud backup option
