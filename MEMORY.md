# MEMORY.md - Session Handoff Log

> **For AI agents:** Read this at the START of every session. Update it at the END.
> This file ensures continuity across different chats, tools, and models.
> See `AGENTS.md` for the full protocol.

---

## Current State (updated March 11, 2026)

**App status:** Running, stable. Flask + SQLite dental clinic on Windows.
**Branch:** `main`
**Data:** Production use (do not break).
**Login:** `admin` / `admin` (NEVER change this)
**Tests:** Last known: 107 passing, 2 skipped (verified March 8, 2026).

### Fast ramp (don’t re-discover the repo)

- Read `docs/AGENT_HANDOFF.md` for the app map + the locked Reception Desk decisions.
- Older historical session notes were archived into `MEMORY_ARCHIVE.md`.

---

## App Map (short)

- **Entry:** `wsgi.py` → `clinic_app/__init__.py:create_app()` (port `8080`).
- **Data root:** `data/` (DB at `data/app.db`).
- **Blueprint registration:** `clinic_app/blueprints/__init__.py`.
- **Patient file:** `templates/patients/detail.html` embeds the live treatments/payments UI.
- **Payments/treatments model:** “treatment” = parent row in `payments` (no separate table). Child payments link via `parent_payment_id`.
- **Permissions/RBAC:** `require_permission(...)` (`clinic_app/auth.py` + `clinic_app/services/security.py`); RBAC models in `clinic_app/models_rbac.py`.
- **UI shell:** sidebar opt-in via `{% set use_sidebar = true %}`; common renderer is `clinic_app/services/ui.py:render_page()`.

---

## Reception Desk (decision complete, Mar 11 2026)

### Goal

Reception does daily entry work as drafts; **Manager/Admin** reviews; system posts into the live patient file **only on approval**.

### Locked decisions

- Reception staff must **not** change live data directly (server-side permission enforcement; not just hiding buttons).
- **Single Reception area:** `/reception` with internal permission-gated views:
  - Desk
  - Manager Queue
  - History (grouped by date; simple workflow history for both)
- New submission opens as **slide-over/modal** (avoid “tons of pages” feel). No “save draft” feature.
- History is simple workflow history, not full audit.
- History should show action notes such as Returned, Held, Approved, Rejected.
- Stored statuses are frozen: `new`, `edited`, `held`, `approved`, `rejected`.
  - “Returned / Needs changes” is a **UI label** derived from `last_action='returned'` + optional `return_reason` (typically with `status='edited'`).
- Opening a draft does not lock it.
- V1 supports same-record corrections:
  - corrections to an existing patient
  - new visit-only entries
  - new treatments
  - new payments
  - corrections to an existing payment
  - corrections to an existing treatment
- Existing patient corrections must stay on the same live patient.
- Same-record means the correction stays on the same live patient, payment, or treatment.
- Manager review for corrections must show current live values beside proposed values.
- Invalid money math blocks approval.
- **New patient intent:**
  - Reception may mark “New patient”.
  - Manager may override to an existing patient if strong duplicates exist; otherwise approval can create the patient then post treatment/payment.
  - New patient file is created only on manager approval.
- Posting safety: approval requires explicit final confirmation; when attaching payment to a treatment, recompute and persist parent `remaining_cents`.
- Reception delete drafts are out of V1.
- True deletions remain manager-only outside the workflow in V1.
- No split delete/add correction chains in V1.

### Planning docs (source of truth)

- `docs/RECEPTION_DESK_SPEC.md`
- `docs/RECEPTION_DESK_IMPLEMENTATION_CONTRACT.md`
- `docs/RECEPTION_DESK_PHASES.md`

---

## What's Next (roadmap context)

Sidebar rollout is complete (Mar 8, 2026). Next priority phase is:

1. **Reception Workflow** (High)
2. **Expense Consolidation** (Medium)
3. **Patient Detail Redesign** (Medium)

---

## Active Decisions Log

| Decision | Reason | Date |
|----------|--------|------|
| Flask for V1 (not React rewrite) | Polish existing app vs rewrite cost | 2025-07-14 |
| Collapsible sidebar layout | Consistent modern shell | 2026-03-03 |
| Page-by-page rollout | Avoid breaking whole app | 2026-03-03 |
| Sidebar hidden by default | Opt-in per page | 2026-03-03 |
| Keep existing theme system | Admin-controlled colors, no hard-coded scheme | 2026-03-03 |
| Prompt-template workflow for AI tasks | Reduce vague prompts/regressions | 2026-03-08 |
| Reception Desk review workflow | Reception drafts; manager/admin approves; post on approval only | 2026-03-11 |
| Reception area UX | Single `/reception` area; modal-first; simple workflow history | 2026-03-11 |
| Reception history is workflow-focused, not full audit | Keep V1 history simple and practical | 2026-03-11 |
| No auto-lock on draft open | Opening a draft should not change its state | 2026-03-11 |
| V1 supports same-record corrections for payments/treatments | Allow corrections without moving records across chains | 2026-03-11 |
| V1 supports same-record patient corrections | Let reception draft patient-file fixes without live editing | 2026-03-11 |
| V1 excludes reception delete drafts | Prevent high-risk delete approvals in the first rollout | 2026-03-11 |
| No split delete/add correction chains in V1 | One mistake must be reviewed as one correction request | 2026-03-11 |
| Reception V1 matching and approval rules are frozen | Make Phase 1 implementation safe and stop workflow drift during build | 2026-03-17 |

---

## Template for New Entries

### Session: Reception doc sync
**Date:** 2026-03-11
**What was done:**
- Updated Reception Desk handoff/planning docs so new agent chats inherit the same locked V1 workflow rules.
- Locked simple workflow History, no auto-lock on open, same-record correction boundaries, manager-only true deletions, and no split delete/add correction chains.
- Synced the spec, implementation contract, phases doc, and agent handoff around the same draft types, statuses, and V1 exclusions.

**Key decisions:**
- History is simple workflow history, not full audit.
- V1 supports create + same-record correction drafts only.
- Reception delete drafts are out of V1; true deletions stay manager-only outside the workflow.

### Session: Reception Figma English LTR
**Date:** 2026-03-11
**What was done:**
- Created a local high-fidelity HTML mockup for the Reception workflow core screens at `.tmp/reception_figma.html`.
- Captured the mockup into a new Figma file with four desktop screens: Desk / Default, Desk / New Submission Open, Manager Queue / Default, and History / Grouped by Date.
- Kept this first pass fully English and fully LTR to match the approved design direction before a separate Arabic/RTL pass.

**Key decisions:**
- English/LTR is the first design deliverable; Arabic/RTL will be a separate follow-up file.
- The Figma file keeps the existing calm clinic shell, card-based layout, and draft-only messaging.
- Generated Figma file: `https://www.figma.com/design/SxsRTBtfCB05BbZQX0gcWe`

### Session: Receptionist home redesign
**Date:** 2026-03-11
**What was done:**
- Reworked the design direction after feedback that the first Figma file felt too heavy and too different from the real app UI.
- Created a second local mockup focused only on the receptionist home screen at `.tmp/receptionist_home_figma.html`.
- Captured a simpler English/LTR receptionist-first screen with the current shell style, `All` filter, today’s drafts, and older unsubmitted drafts.

**Key decisions:**
- Receptionist screen should be designed separately from manager review screens.
- The receptionist home should stay close to the current program shell and avoid a dense queue/dashboard feel.
- Corrected Figma file: `https://www.figma.com/design/lGe0GWOsqQKMuJTvllK5tg`

### Session: Receptionist home redesign v2
**Date:** 2026-03-11
**What was done:**
- Opened the real app locally, logged in, and inspected the actual dashboard and patient list shell before redesigning again.
- Rebuilt the receptionist mockup to follow the real app structure more closely: same header rhythm, simpler sidebar feel, flatter cards, and a quieter filter bar.
- Removed the fake unsubmitted/save mode from the receptionist flow and changed the working list to drafts that are still not approved.

**Key decisions:**
- Default receptionist filter should be `Today`.
- `All` should mean every draft that is still not approved.
- Preferred updated Figma file: `https://www.figma.com/design/MZfXnFtVsSp3J0kxRHPkG5`

### Session: Receptionist home polish v3
**Date:** 2026-03-11
**What was done:**
- Refined the receptionist screen again to remove the unnecessary sort button and make the working list feel more obvious and calmer.
- Clarified in the design that reception reopens drafts and edits/resubmits from inside the same modal, with no separate save mode.
- Added a lighter polish pass focused on usability rather than more UI complexity, then captured a new Figma file.

**Key decisions:**
- No `Newest First` control is needed because the list should already show most recent drafts first by default.
- The receptionist lands on open drafts first, then edits/resubmits from the modal.
- Latest refined Figma file: `https://www.figma.com/design/6MebqaJoT66CCJHuwqwtRc`

### Session: Receptionist home refinement v4
**Date:** 2026-03-11
**What was done:**
- Refined the receptionist mockup again to remove duplicated counts in the top summary cards and normalize every row into one fixed three-column layout.
- Removed technical source chips from beside patient names and replaced them with plain human subtext only when useful.
- Removed the `Resubmitted` state from the receptionist view so edited-and-submitted drafts return to `Waiting Review`, then captured a fresh Figma file.

**Key decisions:**
- Receptionist-visible row states stay limited to `Waiting Review` and `Returned`.
- `All` still means all drafts that are not yet approved, while `Today` remains the default filter.
- Preferred V4 Figma file: `https://www.figma.com/design/AsYYLlSENheSVGuRwsHWBX`

### Session: Receptionist home refinement v5
**Date:** 2026-03-11
**What was done:**
- Applied the final receptionist list cleanup by moving the status chip into its own slot between the explanation text and the action button.
- Removed the helper text under `Open Draft` / `Edit Draft` so the action area stays cleaner.
- Captured the final adjusted receptionist mockup into a new Figma file.

**Key decisions:**
- Status chip should sit between the middle explanation block and the action button.
- No helper copy is needed under the action button in the real UI.
- Preferred V5 Figma file: `https://www.figma.com/design/4Wup0Kc55zj6eSAGFx3XWh`

### Session: Figma references cleanup
**Date:** 2026-03-11
**What was done:**
- Added `docs/FIGMA_REFERENCES.md` as the single repo doc for approved Figma links.
- Linked that file from `docs/INDEX.md`.
- Removed obsolete local exploration mockup `.tmp/reception_figma.html` and trimmed the reference doc so only the current receptionist design remains documented.

**Key decisions:**
- `docs/FIGMA_REFERENCES.md` should list current approved design references only, not every discarded iteration.
- Current approved receptionist design remains V5: `https://www.figma.com/design/4Wup0Kc55zj6eSAGFx3XWh`

### Session: Receptionist modal design
**Date:** 2026-03-11
**What was done:**
- Built the receptionist modal mockup at `.tmp/receptionist_modal_figma.html` using the approved receptionist home shell and current program field coverage.
- Captured the modal mockup into a new Figma file with treatment new, payment new, payment waiting, treatment returned, and locked-context reference states.
- Updated `docs/FIGMA_REFERENCES.md` and `docs/CHANGELOG.md` so future chats can find the approved modal design immediately.

**Key decisions:**
- The receptionist modal uses one shared shell with two modes: Treatment and Payment.
- Treatment mode keeps treatment text, consultation checkbox, visit type, doctor, total, discount, paid today, remaining, date, method, and note.
- Payment mode keeps amount, date, method, doctor, and note.
- Waiting drafts reopen in the same modal; returned drafts show the manager reason near the top.
- Current approved receptionist modal Figma file: `https://www.figma.com/design/27o4Oit52wnAcxIx9ZQtRs`

### Session: Patient-file draft correction scope
**Date:** 2026-03-11
**What was done:**
- Updated the Reception Desk handoff/spec/contract/phases docs so reception can also draft patient-file corrections, not only treatment/payment corrections.
- Locked `edit_patient` as a same-record correction type and limited it to practical patient profile fields already used at the front desk.

**Key decisions:**
- Reception may draft patient-profile changes from the patient file.
- `edit_patient` stays on the same live patient and does not become merge/identity-reassignment workflow.
- V1 patient correction fields are: full name, primary phone, additional phones, primary page number, additional page numbers, and notes.
- Generated file number identity changes stay out of V1 for safety.

### Session: Receptionist modal polish v2
**Date:** 2026-03-11
**What was done:**
- Refined the receptionist modal mockup so it feels calmer and closer to an implementation-ready clinic UI.
- Tightened the modal depth, section hierarchy, background treatment, and copy while preserving the same workflow and field coverage.
- Captured the refined version to a new preferred Figma file and updated the design reference doc.

**Key decisions:**
- Current preferred receptionist modal file is now V2: `https://www.figma.com/design/9Dh1wj2NQ2mXMgi9DPqpBo`
- The polished V2 modal keeps the same treatment/payment coverage, waiting/returned behavior, and locked-context references as V1.
- The local source of truth remains `.tmp/receptionist_modal_figma.html`.

### Session: Reception decision freeze
**Date:** 2026-03-17
**What was done:**
- Closed the last open Reception V1 planning gaps in the spec/contract instead of starting code with fuzzy rules.
- Locked passive-warning-only receptionist save behavior, explicit match-strength rules, deterministic approval routing, and a confirmation-only final approval screen.
- Updated the fast handoff doc so future agents treat Reception as Phase 1 backend-ready rather than re-planning it again.

**Key decisions:**
- Reception does not choose live patient matches before save in V1; managers resolve live candidates during review.
- Weak matches require explicit manager choice; conflicting identity signals block approval.
- `new_payment` stays payment-only and must not silently become `new_treatment` at approval time.
- Final approval is a confirmation step, not a second edit form.

### Session: Reception Phase 1A backend foundation
**Date:** 2026-03-17
**What was done:**
- Added runtime bootstrap for `reception_entries` and `reception_entry_events` so Reception drafts/history are stored separately from live patient and payment data.
- Added runtime Reception permission seeding for `reception_entries:create`, `reception_entries:review`, and `reception_entries:approve`, with default-role assignment for Admin, Manager, and Reception only.
- Added `clinic_app/services/reception_entries.py` with payload validation, draft creation, draft fetch/list helpers, and submitted-event creation.
- Added targeted tests covering bootstrap idempotence, role permission assignment, draft validation, draft storage, event creation, and JSON decoding.

**Current state:**
- Reception backend foundation exists, but there is still no `/reception` route or user-facing screen yet.
- Current live patient/payment entry permissions were intentionally not changed in this slice.
- Next implementation step should be the first minimal Reception Desk surface that calls the new draft service.

**Key decisions:**
- Reception draft storage uses new staging tables in the same SQLite DB, not live payment rows.
- Reception permissions are seeded at startup without touching custom roles or removing any existing permissions.
- Matching logic is still deferred; current draft records store warnings/placeholders only.

### Session: Reception Desk first surface
**Date:** 2026-03-17
**What was done:**
- Added the first real Reception blueprint and `/reception` page using the sidebar shell and server-rendered form flow.
- Added one working Desk submission path for `new_treatment` drafts from Reception Desk into `reception_entries`.
- Added a personal recent-drafts list, receptionist summary counts, and a manager placeholder block for users with review/approve permissions.
- Added route tests for access control, successful submit, invalid submit, and current-user draft visibility.

**Current state:**
- Receptionists can now create draft treatment entries from `/reception`.
- There is still no manager queue, no patient-file launcher, and no live approval/posting.
- Existing live patient/payment entry permissions remain unchanged on purpose.

**Key decisions:**
- The first user-facing slice supports Desk-origin `new_treatment` drafts only.
- Draft notes are stored inside `payload_json` for now instead of a dedicated column.
- Review-only users can access the page shell and see a placeholder, but not the create form.

### Session: [Brief Title]
**Date:** YYYY-MM-DD
**What was done:**
- [bullet points of changes]

**Key decisions:**
- [any new decisions and their reasoning]
