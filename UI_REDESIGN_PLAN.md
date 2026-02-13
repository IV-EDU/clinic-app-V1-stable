# UI Redesign Plan – Clinic-App-Local

> Comprehensive plan for remaking the UI to be clinical, modern, dark-mode-ready, and user-friendly.
> Agreed upon after full codebase review. All phases are independent and shippable.
>
> **Last Updated:** 2025-02-13

---

## Design Principles

- **Clinical/medical aesthetic** — clean, professional, dark blue-grey dark mode (not pure black)
- **Arabic-first** — RTL is first-class, Arabic search normalization
- **Minimal clicks** — modals over page navigation, batch entry, smart defaults
- **One source of truth** — consolidate duplicate systems (expenses), split monoliths (admin)
- **Don't break what works** — import, backup, merge Python logic stays untouched

---

## Phase Overview

| Phase | What | Priority | Risk |
|-------|------|----------|------|
| 1 | CSS design system + dark mode foundation | Highest | Low (CSS-only) |
| 2 | Modal system + toast notifications + loading states | Highest | Low (JS/CSS) |
| 3 | Arabic search normalization + global search bar | Highest | Low-Med |
| 4 | Split admin settings into 5 pages + fix bugs + add audit events | Highest | Medium |
| 5 | Dashboard homepage + nav restructure + backup automation | Highest | Medium |
| E | Expense consolidation (kill full, evolve simple) | High | Medium |
| 6 | Reception tab (active workflow) | High | Low-Med |
| 7 | Data Entry tab (staging/review workflow) | High | Medium |
| 8 | Patient files list redesign | Medium | Low |
| 9 | Patient detail tabs + add patient modal + merge modal fix | Medium | Medium |
| 10 | Reports simplification | Medium | Low |
| 11 | Duplicate/merge UX polish | Medium | Low-Med |
| 12 | Keyboard shortcuts | Low | Low |
| 13 | Audit trail enhancements (before/after, tombstones, undo) | Low | Medium |
| 14 | Receipt/print polish | Low | Low |
| 15 | Backup status indicator + quick backup | Low | Low |

---

## Phase 1: CSS Design System + Dark Mode Foundation
**Priority:** Highest | **Risk:** Low (CSS-only, no backend) | **Est:** 1 session

### What
- Create `static/css/design-system.css` with:
  - CSS custom properties for the complete color palette (light + dark)
  - Semantic tokens: `--color-surface`, `--color-surface-raised`, `--color-text-primary`, `--color-text-secondary`, `--color-border`, `--color-accent`, `--color-success`, `--color-warning`, `--color-danger`
  - Typography scale (4–5 sizes)
  - Spacing scale (4px base)
  - Border radius tokens
  - Shadow tokens (subtle, medium, strong)
  - Transition tokens
- Dark mode via `[data-theme="dark"]` on `<html>`, toggled by user preference
- Dark mode uses dark blue-grey (`#1a1d23` base), not pure black
- Per-user toggle stored in `localStorage` (no DB change needed for Phase 1)
- Update `_base.html` to load design system CSS and add theme toggle

### Files to Touch
- Create: `static/css/design-system.css`
- Edit: `templates/_base.html` (add CSS link, add theme toggle script)
- Edit: `static/css/app.css` (migrate hard-coded colors to variables)

### Safety
- Pure CSS + JS. No backend changes. Cannot break data.
- Existing theme variables from `theme-system.css` are preserved and bridged.

---

## Phase 2: Modal System + Toast Notifications + Loading States
**Priority:** Highest | **Risk:** Low (JS/CSS) | **Est:** 1 session

### What
- Create a reusable modal component (JS class + CSS):
  - `openModal(id)`, `closeModal(id)`, auto-focus, escape to close, backdrop click to close
  - Sizes: small, medium, large, full
  - Replaces current inline modal implementations one-by-one
- Toast notifications replace flash messages:
  - Success (green), error (red), warning (amber), info (blue)
  - Auto-dismiss after 5s, manual dismiss
  - Stacking from top-right
- Loading states:
  - Skeleton loaders for cards/lists
  - Button spinner on form submit
  - Prevent double-submit

### Files to Touch
- Create: `static/js/modal-system.js`
- Create: `static/js/toast.js`
- Create: `static/css/components.css` (modal, toast, loading styles)
- Edit: `templates/_base.html` (load new JS/CSS, toast container)

### Safety
- Does not remove old modals immediately. New system is opt-in, then migrate page by page.

---

## Phase 3: Arabic Search Normalization + Global Search Bar
**Priority:** Highest | **Risk:** Low-Medium | **Est:** 1 session

### What
- Arabic character normalization: collapse ا/أ/إ/آ, ه/ة, ي/ى variants in search
- Apply to: patient search (home, appointments autocomplete, admin data tab)
- Global search bar in nav: always visible, searches patients by name/phone/file#
- Search results in dropdown, Enter to go to patient detail

### Files to Touch
- Create: `clinic_app/services/arabic_search.py` (normalize function)
- Edit: `clinic_app/blueprints/core/core.py` (use normalized search)
- Edit: `clinic_app/blueprints/appointments/routes.py` (patient search API)
- Edit: `clinic_app/blueprints/patients/routes.py` (search)
- Edit: `templates/_nav.html` (add search bar)
- Add Arabic translations to `services/i18n.py`

### Safety
- Normalization is additive — plain-text search still works, Arabic search becomes better.
- Test with Run-Tests.bat after backend changes.

---

## Phase 4: Split Admin Settings + Bug Fix + Audit Events
**Priority:** Highest | **Risk:** Medium | **Est:** 2 sessions

### What
- Split the 4,959-line `admin_settings.py` into 5 focused blueprints:
  1. `admin/users.py` — User & role management
  2. `admin/doctors.py` — Doctor management
  3. `admin/appearance.py` — Theme, colors, logos, branding
  4. `admin/data.py` — Import, export, backups, duplicates (keeps all import logic untouched)
  5. `admin/audit.py` — Audit viewer, export, privacy
- Split the 6,220-line template into 5 separate pages
- Each page gets its own nav link under an "Admin" dropdown
- **Fix:** Remove the 4x duplicated `merge_mode` line (~3071-3078)
- **Add:** Audit events for patient merge, import commit, backup/restore

### Files to Touch
- Create: `clinic_app/blueprints/admin/users.py`, `doctors.py`, `appearance.py`, `data.py`, `audit.py`, `__init__.py`
- Create: `templates/admin/users.html`, `doctors.html`, `appearance.html`, `data.html`, `audit.html`
- Edit: `clinic_app/blueprints/__init__.py` (register new blueprints)
- Edit: `templates/_nav.html` (admin dropdown)
- Deprecate (keep but redirect): `admin_settings.py` main index route

### Safety
- Import logic: COPY as-is into `admin/data.py`, do not restructure the internal logic.
- Keep all route URLs working (add redirects from old URLs).
- Run full test suite after.

---

## Phase 5: Dashboard Homepage + Nav Restructure + Backup Automation
**Priority:** Highest | **Risk:** Medium | **Est:** 2 sessions

### What
- Replace current home page (patient list) with a dashboard:
  - Today's stats cards: patients seen, appointments, payments collected, pending
  - Quick actions: new patient, new appointment, new expense
  - Recent activity feed (last 10 events)
  - Move patient list to a "Patients" tab/page (accessible from nav)
- Nav restructure: Dashboard | Patients | Reception | Appointments | Reports | Admin dropdown
- Rename "Today's Visits" to "Reception" (active workflow, not passive list)
- Backup automation:
  - Auto-backup on startup if last backup >24 hours old
  - Rotation: keep max 30 backups or 90 days
  - Integrity check: verify backup file after creation (open + `PRAGMA integrity_check`)

### Files to Touch
- Create: `templates/core/dashboard.html`
- Edit: `clinic_app/blueprints/core/core.py` (dashboard route, backup-on-startup)
- Edit: `templates/_nav.html` (restructure)
- Create or edit: `clinic_app/services/backup.py` (backup automation)
- Add translations to `services/i18n.py`

---

## Phase E: Expense Consolidation
**Priority:** High | **Risk:** Medium | **Est:** 1–2 sessions

### What
- Evolve simple expenses into a medium-weight "Clinic Expenses" system:
  - Add optional category field (dental-specific: Lab Work, Materials, Equipment, Rent, Utilities, Salaries, Other)
  - Add optional receipt photo upload (reuse existing image upload pattern)
  - Add monthly summary view
  - Keep the simple entry form as default (date + amount + description + optional category)
- Keep legacy expenses code but hide from nav (soft-deprecate)
- Single "Expenses" nav item pointing to evolved simple system

### Files to Touch
- Edit: `clinic_app/blueprints/simple_expenses.py` (add category, photo)
- Edit: `clinic_app/services/simple_expenses.py` (add category support)
- Edit: `templates/simple_expenses/` (category dropdown, photo upload, monthly view)
- Edit: `templates/_nav.html` (single Expenses link)
- Migration: add `category` column to `simple_expenses` table

### Safety
- Legacy expenses: hide from nav but DO NOT delete code or routes.
- Migration is additive only (new nullable column).

---

## Phase 6: Reception Tab (Active Workflow)
**Priority:** High | **Risk:** Low-Medium | **Est:** 1 session

### What
- New "Reception" page showing today's active workflow:
  - Expected patients (today's appointments, sorted by time)
  - Current status for each (waiting, in-progress, done, no-show)
  - Quick actions: check-in, mark complete, view patient file
  - Live-updating (poll every 30s or manual refresh)
- Links from here to patient detail, appointment detail

### Files to Touch
- Create: `templates/core/reception.html`
- Edit: `clinic_app/blueprints/core/core.py` (reception route)
- Uses existing appointment data + status API

---

## Phase 7: Data Entry Tab (Staging/Review)
**Priority:** High | **Risk:** Medium | **Est:** 1–2 sessions

### What
- Batch data entry page for reception staff:
  - Quick-add multiple payments in a spreadsheet-like grid
  - Paste from Excel support
  - Staging area: entries are "pending" until reviewed and committed
  - Review mode: doctor/admin reviews pending entries, approves or rejects
- This reduces errors from manual entry under time pressure

### Files to Touch
- Create: `templates/core/data_entry.html`
- Create: `clinic_app/blueprints/core/data_entry.py` or add routes to `core.py`
- Create: `clinic_app/services/data_entry.py` (staging logic)
- May need new table: `staged_payments`

---

## Phase 8: Patient Files List Redesign
**Priority:** Medium | **Risk:** Low | **Est:** 1 session

### What
- Card-based patient list with avatar placeholder, file#, name, phone, last visit, balance
- Filters: search, date range, balance status (paid/owing/overpaid)
- Sort by name, file#, last visit, balance
- Responsive grid layout

### Files to Touch
- Edit: `templates/core/index.html` or create `templates/patients/list.html`
- Edit: `static/css/` (patient card styles)

---

## Phase 9: Patient Detail Tabs + Add Patient Modal + Merge Modal Fix
**Priority:** Medium | **Risk:** Medium | **Est:** 2 sessions

### What
- Tabbed patient detail page: Overview | Payments | Diagnosis | Medical | Images
  - Currently these are separate pages; combine into tabs with lazy loading
- Convert "Add Patient" from full page to modal:
  - Same backend validation and duplicate detection logic
  - `fetch()` POST instead of form submission
  - Duplicate check happens live as user types (debounced)
- Fix merge/duplicate modals:
  - Current merge UI is "really bad" (user's words)
  - Clearer side-by-side comparison
  - Clear "keep source / keep target / merge" choices per field
  - Preview before commit

### Files to Touch
- Edit: `templates/patients/detail.html` (tabbed layout)
- Create: `templates/patients/add_modal.html` (fragment)
- Edit: `templates/patients/duplicate_confirm.html` (improve UI)
- Edit: `clinic_app/blueprints/patients/routes.py` (modal-compatible endpoints)
- Backend duplicate detection logic: DO NOT CHANGE, only change how it's called (fetch vs form)

---

## Phase 10: Reports Simplification
**Priority:** Medium | **Risk:** Low | **Est:** 1 session

### What
- Dashboard-style report landing page with summary cards:
  - Today's collections, this week, this month
  - Outstanding receivables total
  - Top 5 doctors by collections
- Drill-down to existing detailed reports
- Covers 80% of reporting questions without navigating to detailed views

---

## Phase 11: Duplicate/Merge UX Polish
**Priority:** Medium | **Risk:** Low-Medium | **Est:** 1 session

### What
- Improve admin duplicate detection UI
- Side-by-side patient comparison cards
- One-click merge with preview
- Batch duplicate review mode

---

## Phase 12: Keyboard Shortcuts
**Priority:** Low | **Risk:** Low | **Est:** 0.5 sessions

### What
- Global shortcuts: `Ctrl+K` → search, `Ctrl+N` → new patient, `Escape` → close modal
- Discoverable via `?` key showing shortcut overlay

---

## Phase 13: Audit Trail Enhancements
**Priority:** Low | **Risk:** Medium | **Est:** 1–2 sessions

### What
- Before/after diffs for payment edits
- Audit events for: patient merge, import, backup/restore, user login
- Payment tombstone table for 30-day soft-delete/undo
- Timeline view in admin audit page

### Files to Touch
- Edit: `clinic_app/services/audit.py` (expand event types, add diff logic)
- Create: migration for `payment_tombstones` table
- Edit: `templates/admin/audit.html` (timeline view)

---

## Phase 14: Receipt/Print Polish
**Priority:** Low | **Risk:** Low | **Est:** 0.5 sessions

### What
- Consistent print styling across all receipt types
- Preview before print
- Batch print support

---

## Phase 15: Backup Status Indicator + Quick Backup
**Priority:** Low | **Risk:** Low | **Est:** 0.5 sessions

### What
- Status badge in nav showing last backup time
- Color-coded: green (<24h), yellow (1-7 days), red (>7 days)
- One-click backup button in admin area
- Backup progress indicator

---

## Implementation Rules

1. **One phase at a time.** Complete and test before moving to next.
2. **UI-only changes first** within each phase, then backend if needed.
3. **Run tests** after any backend change.
4. **Update docs** after every phase (AGENTS.md §13 auto-update rule).
5. **Import/backup/merge Python logic: DO NOT MODIFY** except the 3 small fixes noted.
6. **Arabic translations** must be added for every new display string.
7. **Dark mode** must work for every new component from Phase 1 onward.

---

## Progress Tracker

| Phase | Status | Date Started | Date Done | Notes |
|-------|--------|-------------|-----------|-------|
| 1 | Not started | | | |
| 2 | Not started | | | |
| 3 | Not started | | | |
| 4 | Not started | | | |
| 5 | Not started | | | |
| E | Not started | | | |
| 6 | Not started | | | |
| 7 | Not started | | | |
| 8 | Not started | | | |
| 9 | Not started | | | |
| 10 | Not started | | | |
| 11 | Not started | | | |
| 12 | Not started | | | |
| 13 | Not started | | | |
| 14 | Not started | | | |
| 15 | Not started | | | |
