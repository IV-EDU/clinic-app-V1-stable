# Agent Handoff (Clinic-App-Local)

This file is a fast ramp for the next agent so they don’t have to re-discover the repo.

## Read order (fast)

1. `AGENTS.md` (safety + protected areas)
2. `MEMORY.md` (current state + latest decisions)
3. `KNOWN_ISSUES.md` + `LAST_PLAN.md` (priorities)
4. Reception workflow docs (if working on Reception):
   - `docs/RECEPTION_DESK_SPEC.md`
   - `docs/RECEPTION_DESK_IMPLEMENTATION_CONTRACT.md`
   - `docs/RECEPTION_DESK_PHASES.md`

## App overview

- **Stack:** Flask + SQLite, Windows, port `8080`.
- **Entry:** `wsgi.py` → `clinic_app/__init__.py:create_app()`.
- **Data root:** `data/` (main DB at `data/app.db`). See `_data_root()` in `clinic_app/__init__.py`.
- **DB access:** mixed style
  - raw sqlite3 connections via `clinic_app/services/database.py:db()`
  - SQLAlchemy engine/session via `clinic_app/extensions.py` and `clinic_app/models.py` / `clinic_app/models_rbac.py`

## Blueprints (main user surfaces)

Registered in `clinic_app/blueprints/__init__.py`:

- **Core/Dashboard:** `clinic_app/blueprints/core/core.py`
  - `/` dashboard (requires `patients:view`)
  - `/patients/list` list UI
  - `/api/patients/live-search` JSON (patients view)
- **Patients:** `clinic_app/blueprints/patients/routes.py`
  - `/patients/new`, `/patients/<pid>`, edit/delete, quickview fragments
  - Patient file template: `templates/patients/detail.html`
- **Payments:** `clinic_app/blueprints/payments/routes.py`
  - Payments are accessed via patient file; standalone payments index redirects home.
  - Embedded payments/treatments UI: `templates/payments/_list.html`
- **Appointments:** `clinic_app/blueprints/appointments/routes.py` + `clinic_app/services/appointments.py`
  - `/appointments` redirects to the vanilla UI; has JSON APIs for status + patient search
- **Reports:** `clinic_app/blueprints/reports/routes.py`
- **Admin settings (RBAC, theme, audits):** `clinic_app/blueprints/admin_settings.py` (`/admin/...`)
- **Simple expenses:** `clinic_app/blueprints/simple_expenses.py` (`/simple-expenses/...`)
- **Diagnosis/Images (Palmer+):** `clinic_app/blueprints/images/images.py` (separate styling)

## Permissions / RBAC

- Decorator: `clinic_app/auth.py:requires()` wrapped by `clinic_app/services/security.py:require_permission()`.
- RBAC models and legacy role fallback: `clinic_app/models_rbac.py`.
- Admin roles/users UI: `clinic_app/blueprints/admin_settings.py`.

## Payments/Treatments model (critical)

There is no separate “treatments” table.

- A **treatment** is a **parent row** in `payments` where `parent_payment_id` is NULL/empty.
- A **payment for that treatment** is a **child row** in `payments` where `parent_payment_id = <treatment_id>`.
- Many screens rely on `remaining_cents` on the parent being correct; routes often recompute it after edits.
  - Shared helpers: `clinic_app/services/payments.py`
  - Live routes: `clinic_app/blueprints/payments/routes.py`

---

## Reception Desk workflow (planning is locked)

### Goal

Reception does daily entry work as drafts; manager/admin reviews; the system posts into live patient file only on approval.

### Locked decisions

- **Reception cannot change live data directly.**
  - Live `payments:edit` / `patients:edit` must not be granted to Reception roles.
  - Server-side permissions enforce this (not just hiding buttons).
- **Reception area URL:** `/reception`
  - Internal views inside the same area (permission-gated): Desk / Manager Queue / History
  - New submission opens as a slide-over/modal (avoid “tons of pages” feel)
  - No “Save draft” feature
- **Stored statuses (frozen):** `new`, `edited`, `held`, `approved`, `rejected`
  - “Returned / Needs changes” is a UI label (derived from `last_action='returned'` + optional `return_reason`)
- **Option B editing model (recall-to-edit):**
  - Managers may lock an item while reviewing.
  - Reception may Recall any time before approval; recall clears the lock and returns the item to reception editing.
  - If held and recalled → becomes `edited` (held cleared).
- **New patient flow:**
  - Reception can mark “New patient” as intent.
  - Manager can override and attach to an existing patient if strong duplicate matches exist.
  - Otherwise manager approval can create the new patient, then post the treatment/payment.
- **V1 scope:** payments/treatments inserts first (new treatment + attach payment). Corrections (editing existing live rows) deferred.
- **Posting safety:** approval always requires an explicit final confirmation; when attaching payment, recompute and persist parent `remaining_cents`.

### Real integration anchors

- Patient file: `templates/patients/detail.html`
- Live treatments/payments UI: `templates/payments/_list.html`

### Planning docs

- `docs/RECEPTION_DESK_SPEC.md`
- `docs/RECEPTION_DESK_IMPLEMENTATION_CONTRACT.md`
- `docs/RECEPTION_DESK_PHASES.md`

