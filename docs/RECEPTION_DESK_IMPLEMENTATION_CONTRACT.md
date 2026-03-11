# Reception Desk Implementation Contract

> Phase 0 freeze for the Reception Desk + Manager Review system.
> This file does not replace [docs/RECEPTION_DESK_SPEC.md](/c:/Users/ivxti/OneDrive/Desktop/GitHub/Clinic-App-Local/docs/RECEPTION_DESK_SPEC.md) or [docs/RECEPTION_DESK_PHASES.md](/c:/Users/ivxti/OneDrive/Desktop/GitHub/Clinic-App-Local/docs/RECEPTION_DESK_PHASES.md).
> It converts them into a build contract for the first implementation cycle.

## Purpose

Lock the minimum implementation rules before coding so the feature is built safely and does not drift away from the approved workflow.

This contract is the bridge between:

- workflow truth in `docs/RECEPTION_DESK_SPEC.md`
- implementation order in `docs/RECEPTION_DESK_PHASES.md`
- the current live codebase and permission system

## Current Codebase Anchors

These are the real integration points confirmed in the current app:

- Patient detail route: `clinic_app/blueprints/patients/routes.py` -> `patients.patient_detail`
- Patient detail template: `templates/patients/detail.html`
- Live treatment and payment controls live in `templates/payments/_list.html`
- Live treatment creation route: `payments.create_treatment`
- Live payment creation route: `POST /patients/<pid>/treatments/<treatment_id>/payment`
- Patient search endpoints already exist:
  - `clinic_app/blueprints/patients/routes.py` -> `/patients/search`
  - `clinic_app/blueprints/core/core.py` -> `/api/patients/live-search`
- Permissions are currently enforced through `require_permission(...)`
- Role and permission definitions currently live in `clinic_app/models_rbac.py`

## First Release Goal

The first release must allow:

- receptionist draft entry
- manager queue review
- manager draft editing
- hold / reject handling
- existing patient correction drafts
- existing payment correction drafts
- existing treatment correction drafts

The first release must not allow:

- silent live posting
- auto-routing into a patient or treatment without manager confirmation
- merge workflow
- duplicate cleanup workflow
- receptionist use of live `Add Treatment` / `Add Payment` actions
- reception delete drafts
- split delete/add correction chains

## Frozen Entry Points

The first implementation cycle will support these entry points only:

### 1. Main Reception Desk page

- purpose: receptionist starts an entry without locked patient context
- source code value: `reception_desk`
- patient locked: no
- treatment locked: no

### 2. Patient File draft entry

- launched from patient detail page
- source code value: `patient_file`
- patient locked: yes
- treatment locked: no

### 3. Treatment Card draft entry

- launched from a treatment card inside the patient file
- source code value: `treatment_card`
- patient locked: yes
- treatment locked: yes

## Frozen Status Model

Pending entries will use this status set:

- `new`
- `edited`
- `held`
- `approved`
- `rejected`

Rules:

- receptionist save creates `new`
- manager edit changes status to `edited`
- hold changes status to `held`
- reject changes status to `rejected`
- only approval flow may set `approved`

Optional queue labels like `Needs patient review` stay derived UI labels for later, not core stored statuses in the first slice.

### Returned / Needs changes (UI label, not a stored status)

“Returned” is a receptionist-facing concept, but it must not expand the stored status set.

When a manager returns an item to reception:
- store `last_action = returned`
- store `return_reason` (optional)
- keep `status` as `edited` (recommended) or `new` (allowed), but do not add a new status.

The receptionist UI should show a clear **Needs changes** chip when `last_action = returned` (and optionally display the `return_reason` if present).

## Frozen Permission Plan

The workflow must be permission-based, not role-name-based.

The first implementation cycle should introduce these permissions:

- `reception_entries:create`
- `reception_entries:review`
- `reception_entries:approve`

Deferred permissions:

- `reception_entries:restore`
- `reception_entries:delete`

Permission intent:

- receptionist draft entry buttons depend on `reception_entries:create`
- queue visibility depends on `reception_entries:review`
- final live approval depends on `reception_entries:approve`
- existing live treatment and payment buttons remain under current `payments:edit`

## Frozen Draft Data Shape

The pending entry backbone must store at least:

- `draft_type`
- `source`
- `status`
- `visit_date`
- `submitted_at`
- `submitted_by_user_id`
- `locked_patient_id` nullable
- `locked_treatment_id` nullable
- `locked_payment_id` nullable
- `target_patient_id` nullable
- `page_number` nullable
- `patient_name`
- `phone` nullable
- `visit_type` nullable
- `treatment_text` nullable
- `doctor` or `doctor_id`
- `money_received_today`
- `paid_today` nullable
- `total_amount` nullable
- `discount_amount`
- `remaining_amount` nullable derived snapshot for review display only
- `note` nullable
- `warning_flags`
- `match_summary`
- `last_action`
- `return_reason` nullable (optional)
- `hold_reason` nullable (optional)
- `patient_intent` (e.g., `new_patient` vs `unknown/existing`)
- `reviewed_by_user_id` nullable
- `reviewed_at` nullable
- `rejection_reason` nullable
- `target_payment_id` nullable
- `target_treatment_id` nullable

Important rules:

- `discount_amount` defaults to zero when blank
- `remaining_amount` is not receptionist input
- if `total_amount` is blank, `remaining_amount` stays unknown
- `patient_name` is required only when patient is not locked by source context
- `locked_*` fields describe context the draft started from
- `target_*` fields describe the live record the manager approves against

## Frozen Validation Rules

Hard blocks:

- missing patient name when patient is not locked
- missing doctor
- `money_received_today = yes` and `paid_today` missing
- `paid_today > total_amount - discount_amount` when total exists

Soft warnings:

- phone missing
- page number missing
- possible patient match found
- multiple patient matches
- total missing
- remaining unknown

## Frozen Correction Boundaries

V1 supports same-record corrections.

Same-record means the correction stays on the same live patient, payment, or treatment.

- `edit_patient` updates only the same live patient
- `edit_payment` updates only the same live payment
- `edit_treatment` updates only the same live treatment
- no reassignment between patient/treatment chains in V1
- before-vs-after comparison is mandatory for correction review

Allowed `edit_patient` fields:

- full name
- primary phone
- additional phones
- primary page number
- additional page numbers
- notes

Allowed `edit_payment` fields:

- amount
- date
- method
- doctor
- note

Allowed `edit_treatment` fields:

- treatment text
- doctor
- note
- total
- discount
- visit type
- treatment date

Not allowed through correction drafts:

- duplicate merge behavior
- changing generated file number identity in V1
- delete/add replacement chains
- moving a payment to another treatment
- moving a payment to another patient
- moving a treatment to another patient

## Frozen Review Rules

Manager review must show:

- receptionist entry summary
- entry source
- top patient suggestion if available
- match reason labels
- compact patient summary
- warning chips

If multiple patient candidates exist:

- show them inline in the review screen
- do not require a new tab for normal review
- if source is `patient_file` or `treatment_card`, show the locked source patient first unless conflict is detected

Manager action rules:

- `Edit` updates pending draft only
- `Hold` keeps item outside live data
- `Return` sends back to reception for changes (return reason optional)
- `Reject` requires a reason
- `Approve` remains separate from edit

## Frozen Review-Open Behavior

- Opening a draft does not lock it.
- No auto-lock timeout is needed in V1.
- Pending state remains unchanged until hold/return/reject/approve/edit happens.

## Frozen First-Release UI Boundaries

Receptionist sees:

- Reception Desk area (single location at `/reception`)
- draft entry actions from patient file and treatment card later in the cycle
- helper text that the draft was sent for manager review
- History grouped by date (their own by default)
- A “New submission” slide-over/modal (no draft-save feature)

Receptionist does not see:

- live treatment creation actions as their primary workflow
- live payment posting actions as their primary workflow
- merge choices
- routing choices between existing and new treatment

Manager sees:

- review queue (accessible inside the same `/reception` area)
- review detail screen
- inline candidate patient comparisons
- approval decision path
- History grouped by date (defaults to All)

## Frozen First-Release Exclusions

Out of the first implementation cycle:

- Merge Center
- duplicate cleanup workflow
- admin redesign for role UX
- full appointments redesign
- treatment label standardization
- automatic approval
- background posting without final manager confirmation
- reception delete drafts
- split delete/add correction chains

## Frozen Deletion Policy

- Reception delete drafts are out of V1.
- True deletions remain manager-only outside the workflow in V1.
- treatment deletion with attached child payments is out of scope

Safety rule (when approval posting is enabled later):
- Approval must show an explicit final confirmation before writing live data.
- When attaching a payment to a treatment, recompute and persist the parent treatment `remaining_cents` correctly (do not leave stale remaining values).
- Approval must be blocked if a treatment correction would create invalid money state.
- The system must not silently force `remaining_cents` to zero to hide the issue.

## Safe Build Sequence

The implementation must proceed in this order:

1. Pending entry backbone
2. Permission wiring
3. Reception Desk draft UI
4. Manager review queue
5. Live approval posting
6. Matching and warning polish
7. Context-entry enhancements
8. Validation and rollout hardening

## Specific Safety Notes For This Repo

- `clinic_app/models_rbac.py` is a protected area and should be treated as high attention work.
- `templates/payments/_list.html` currently exposes live `Add Treatment` and `Add Payment` controls under `payments:edit`; receptionist draft controls must not be mixed into those without clear separation.
- Approval posting must not reuse the existing live payment/treatment routes directly from receptionist screens.
- Pending-entry storage must stay separate from current live payment rows because live treatments are represented as parent payment rows.

## Definition Of Ready For Phase 1

Phase 1 can begin only if all of these remain accepted:

- the 3 entry sources are locked
- the status model is locked
- the first-release permission set is locked
- the first-release exclusions are locked
- live posting remains deferred until after queue review is working
