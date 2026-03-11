# Reception Desk Phases

> Temporary implementation roadmap for the Reception Desk + Manager Review system.
> Keep this separate from `docs/RECEPTION_DESK_SPEC.md`, which defines the workflow itself.
> Use `docs/RECEPTION_DESK_IMPLEMENTATION_CONTRACT.md` as the Phase 0 freeze before starting code.
> Delete or fold this into permanent docs after the feature is fully implemented.

## Purpose

This file explains how to build the Reception Desk system safely, in phases, without mixing:

- workflow design
- backend logic
- UI implementation
- duplicate cleanup / merge work

## Core Build Rules

- Build in thin slices.
- Do not mix backend and UI rules together.
- Do not post anything live until the approval flow is working.
- Keep daily review separate from duplicate cleanup and merge work.
- Use permissions, not role names.
- Keep receptionist draft actions separate from manager live actions.
- History is simple workflow history, not full audit.
- V1 supports same-record corrections.
- Reception delete drafts are out of V1.
- No split delete/add correction chains in V1.

## Phase 0: Discovery and Freeze

### Goal

Freeze the design and confirm integration points before coding.

### Deliverables

- `docs/RECEPTION_DESK_SPEC.md`
- this phases file
- `docs/RECEPTION_DESK_IMPLEMENTATION_CONTRACT.md`
- exact UI insertion points confirmed
- exact permission plan confirmed

### Scope

- Reception Desk workflow planning
- patient file entry path planning
- treatment card entry path planning
- manager review planning

### Do Not Do Yet

- database/storage work
- routes
- templates
- live posting

### Status

- Frozen for implementation handoff

## Phase 1: Pending Entry Backbone

### Goal

Create the safe staging layer for pending receptionist entries.

### Build

- pending entry storage
- status storage
- entry source storage
- review metadata storage
- draft type storage
- existing payment correction context
- existing treatment correction context
- workflow event history for the History tab
- permission definitions for the new workflow

### Pending Entry Data

At minimum, store:

- draft type: `new_visit_only`, `new_treatment`, `new_payment`, `edit_payment`, `edit_treatment`
- source: `reception_desk`, `patient_file`, `treatment_card`
- locked patient id optional
- locked treatment id optional
- locked payment id optional
- visit date
- submitted timestamp
- page number
- name
- phone
- visit type
- treatment text
- doctor
- money received yes/no
- paid today
- total optional
- discount optional
- note
- status
- reviewer info
- review timestamps
- history/event trail

### Likely Files

- [clinic_app/models_rbac.py](c:\Users\ivxti\OneDrive\Desktop\GitHub\Clinic-App-Local\clinic_app\models_rbac.py)
- new service module under `clinic_app/services/`
- new workflow routes or blueprint shell under `clinic_app/blueprints/`
- [clinic_app/blueprints/__init__.py](c:\Users\ivxti\OneDrive\Desktop\GitHub\Clinic-App-Local\clinic_app\blueprints\__init__.py)

### Risk

- Medium

### Why First

Everything depends on this. No UI or live posting should come first.

## Phase 2: Permission Wiring

### Goal

Separate receptionist entry controls from manager live controls.

### Build

Add new permissions such as:

- `reception_entries:create`
- `reception_entries:review`
- `reception_entries:approve`

Optional later:

- `reception_entries:restore`
- `reception_entries:delete`

### Rules

- receptionist draft actions depend on reception-entry permissions
- live patient/payment actions stay under existing permissions
- do not tie workflow visibility to role names

### Likely Files

- [clinic_app/models_rbac.py](c:\Users\ivxti\OneDrive\Desktop\GitHub\Clinic-App-Local\clinic_app\models_rbac.py)
- admin user/role management wiring later if needed

### Risk

- Medium

## Phase 3: Reception Desk UI

### Goal

Allow receptionists to create pending entries only.

### Build

- main Reception Desk area at `/reception` (single place)
- internal views inside the same area (permission-gated):
  - Desk (reception entry + “my history” by default)
  - Manager Queue (for managers/admins)
  - History (shared safety/audit view, grouped by date)
- “New submission” opens as a slide-over/modal (avoid a large multi-page feel)
- form sections:
  - Patient
  - Visit
  - Payment
  - Notes
- soft warnings
- same-record correction submissions
- no delete submissions
- no live posting

### Entry Modes

#### A. Reception Desk

- unlocked patient context
- matching required

#### B. Patient File Entry

- patient locked
- patient identity shown read-only
- no retyping name or phone

#### C. Treatment Card Entry

- patient locked
- treatment locked
- both shown read-only

### UI Goals

- simple
- Arabic-friendly
- one-column
- minimal choices
- clear helper text

### Likely Files

- new templates for Reception Desk
- [templates/patients/detail.html](c:\Users\ivxti\OneDrive\Desktop\GitHub\Clinic-App-Local\templates\patients\detail.html)
- [templates/payments/_list.html](c:\Users\ivxti\OneDrive\Desktop\GitHub\Clinic-App-Local\templates\payments\_list.html)
- [templates/core/patients_list.html](c:\Users\ivxti\OneDrive\Desktop\GitHub\Clinic-App-Local\templates\core\patients_list.html)
- [templates/appointments/vanilla.html](c:\Users\ivxti\OneDrive\Desktop\GitHub\Clinic-App-Local\templates\appointments\vanilla.html)
- `i18n.py`

### Risk

- Low to Medium

## Phase 4: Manager Review Queue

### Goal

Allow managers to review pending entries without touching live data yet.

### Build

- queue page
- statuses
- single-item review screen
- inline candidate patient cards
- inline patient details
- actions:
  - Approve
  - Edit
  - Choose different patient
  - Hold
  - Return (reason optional)
  - Reject

### Rules

- `Edit` updates only pending draft
- no live posting yet in this phase
- stored statuses remain frozen (do not add `returned` as a stored status)
  - “Returned / Needs changes” is a derived UI label (e.g., `last_action=returned` + optional `return_reason`)
- before-vs-after comparison cards are required for corrections
- opening a draft does not lock it
- no delete approval path in V1
- Same-record means the correction stays on the same live payment or treatment.
- alternate patient suggestions should be inline, not new-tab first
- source context matters:
  - treatment card strongest
  - patient file strong
  - reception desk weaker

### Likely Files

- new review templates
- new workflow routes
- matching helpers in services

### Risk

- Medium

## Phase 5: Approval Posting Logic

### Goal

Allow manager approval to create/update live records safely.

### Approval Outcomes

- Record visit only
- Create new treatment
- Add new payment to existing treatment
- Edit existing payment
- Edit existing treatment

### Safety Rules

- no auto-posting from system suggestion
- manager final confirmation required before live posting
- hold/reject/edit must not affect live data
- on posting (especially attaching payment), recompute and persist parent treatment `remaining_cents` correctly
- Invalid money math blocks approval.

### Explicit V1 Exclusions

- delete payment
- delete treatment
- delete/add replacement chain
- move payment across treatment chains
- move treatment across patients

### Likely Files

- new approval service
- integration with patients/payments services
- possibly new tests around posting behavior

### Risk

- High

### Why Late

This is the most dangerous part of the project.

## Phase 6: Matching and Warning Polish

### Goal

Reduce manager review time without reducing safety.

### Build

- confidence labels
- reason labels:
  - matched by phone
  - matched by page
  - matched by Arabic name
  - matched by combined clues
- queue grouping:
  - Ready
  - Check
  - Hold
- more polished warning chips

### Risk

- Low to Medium

## Phase 7: Context Entry Enhancements

### Goal

Make the workflow faster from places staff already use.

### Build

- `+ Treatment Entry` for receptionist in patient file
- `+ Payment Entry` for receptionist on treatment cards
- helper text under entry buttons:
  - `Sent for manager review`
- keep manager live actions separate

### Rules

- receptionist should not see the live manager add-payment/add-treatment controls
- manager should not see receptionist draft controls in a confusing way
- control visibility should be permission-based

### Risk

- Medium

## Phase 8: Validation and Hardening

### Goal

Reduce data damage and confirm safe behavior before rollout.

### Build

- test edge cases
- refine warnings
- verify light/dark + Arabic/RTL
- verify permissions
- verify manager review never posts wrong data by default

### Must-Test Cases

- pending entry from Reception Desk
- pending entry from patient file
- pending entry from treatment card
- manager edit does not change live data
- hold/reject do not change live data
- approve to existing treatment
- approve to new treatment
- existing payment correction approval
- existing treatment correction approval
- invalid money math blocks approval
- delete draft path is unavailable to reception
- split delete/add correction chains cannot be created
- ambiguous patient does not auto-route
- permission separation of receptionist vs manager controls
- new patient file is created only on manager approval

### Risk

- Medium

## Phase 9: Rollout and Follow-up

### Goal

Release the feature carefully and observe real use.

### Rollout Idea

- enable for a limited user group first
- observe receptionist behavior
- observe manager review pain points
- adjust copy, warnings, and layout before broader use

### Not Included

- Merge Center
- duplicate cleanup overhaul
- admin integration of Merge Center
- full appointments redesign

## Recommended Implementation Order

1. Phase 1: Pending Entry Backbone
2. Phase 2: Permission Wiring
3. Phase 3: Reception Desk UI
4. Phase 4: Manager Review Queue
5. Phase 5: Approval Posting Logic
6. Phase 6: Matching and Warning Polish
7. Phase 7: Context Entry Enhancements
8. Phase 8: Validation and Hardening
9. Phase 9: Rollout and Follow-up

## Important Deferred Work

These should stay out of the first implementation cycle:

- Merge Center
- duplicate cleanup workflow
- admin placement of Merge Center
- full role/permission UX redesign in admin
- treatment label standardization
