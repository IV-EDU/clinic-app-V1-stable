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
- **History is simple workflow history, not full audit.**
  - History tab is a simple daily workflow list with action notes, not a full audit timeline.
- **Opening a draft does not lock it.**
- **Stored statuses (frozen):** `new`, `edited`, `held`, `approved`, `rejected`
  - “Returned / Needs changes” is a UI label (derived from `last_action='returned'` + optional `return_reason`)
- **V1 supports same-record corrections:**
  - existing patient correction
  - existing payment correction
  - existing treatment correction
  - Same-record means the correction stays on the same live patient, payment, or treatment.
  - no moving payments to other treatments
  - no moving treatments to other patients
  - no turning a patient correction into a merge or identity reassignment
  - manager review must show before-vs-after comparison for corrections
  - Invalid money math blocks approval.
- **New patient flow:**
  - Reception can mark “New patient” as intent.
  - Manager can override and attach to an existing patient if strong duplicate matches exist.
  - Otherwise manager approval can create the new patient, then post the treatment/payment.
  - New patient file is created only on manager approval.
- **Reception delete drafts are out of V1.**
  - True deletions stay manager-only outside the reception workflow for now.
  - No split delete/add correction chains in V1.
- **Posting safety:** approval always requires an explicit final confirmation; when attaching payment, recompute and persist parent `remaining_cents`.
- **Reception pre-save matching:** reception sees passive warnings only; live candidate choice stays manager-side.
- **Match thresholds are now frozen:** strong matches may be preselected, weak matches require explicit manager choice, and conflicting identity signals block approval.
- **Approval routing is now frozen:** `new_payment` attaches to an existing treatment only and must not silently become `new_treatment`.

### Real integration anchors

- Patient file: `templates/patients/detail.html`
- Live treatments/payments UI: `templates/payments/_list.html`

### Planning docs

- `docs/RECEPTION_DESK_SPEC.md`
- `docs/RECEPTION_DESK_IMPLEMENTATION_CONTRACT.md`
- `docs/RECEPTION_DESK_PHASES.md`

### Current implementation note

- Reception Phase 1 is partially live now:
  - Desk page exists
  - Manager queue exists
  - Hold / Return / Reject review actions exist
  - Narrow approval exists for Desk-origin `new_treatment` drafts only
- Approval currently creates a new live patient + treatment row only.
- Do not casually widen approval to corrections, payment-only drafts, or duplicate-resolution flows without updating the Reception planning docs first.
