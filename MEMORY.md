# MEMORY.md - Session Handoff Log

> **For AI agents:** Read this at the START of every session. Update it at the END.
> This file ensures continuity across different chats, tools, and models.
> See `AGENTS.md` for the full protocol.

---

## Current State (updated March 17, 2026)

**App status:** Running, stable. Flask + SQLite dental clinic on Windows.
**Branch:** `main`
**Data:** Production use (do not break).
**Login:** `admin` / `admin` (NEVER change this)
**Tests:** Last known focused Reception subset for patient-file `new_treatment` + review/service regressions: 83 passing (verified March 30, 2026). Last broader suite before Reception work: 107 passing, 2 skipped (verified March 8, 2026).

### Fast ramp (don’t re-discover the repo)

- Read `docs/AGENT_HANDOFF.md` for the app map + the locked Reception Desk decisions.
- Reception now has a live Desk page, manager queue, draft detail page, hold/return/reject actions, returned-draft edit/resubmit, approval for Desk-origin and patient-file locked `new_treatment`, a locked treatment-card `new_payment` draft/approval path, and same-record `edit_patient`, `edit_payment`, and `edit_treatment` correction paths.
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

### Session: Reception patient-file new treatment drafts
**Date:** 2026-03-30
**What was done:**
- Added a locked patient-file `new_treatment` draft route pair at `/reception/entries/new-treatment` so reception can launch a treatment draft directly from the patient file without retyping patient identity.
- Reused the shared Reception treatment form with a locked-patient summary state, plus a new patient-detail launcher button for `reception_entries:create` users.
- Extended Reception manager edit, returned-draft resubmit, and approval handling so patient-file `new_treatment` drafts stay locked to the same live patient and never show the desk-origin patient chooser.
- Added focused route/review coverage for launcher visibility, create validation, manager detail/edit, same-patient approval, stale locked-patient blocking, and returned-draft resubmission.

**Current state:**
- Reception now supports `new_treatment` from both `reception_desk` and `patient_file`.
- Patient-file `new_treatment` approval always posts onto the same locked patient; it does not create a new patient or attach to a searched patient.
- Focused Reception subset passes: 83 tests across `test_reception_patient_treatment_routes`, `test_reception_review_routes`, and `test_reception_entries_service`.

**Key decisions:**
- Reused the existing shared treatment-draft form instead of creating a second patient-file-only form; the patient context is now rendered as read-only/locked.
- Kept desk-origin `new_treatment` routing unchanged; only patient-file drafts bypass the existing-patient chooser and use the locked live patient.

### Session: Reception shared history view
**Date:** 2026-03-30
**What was done:**
- Added the missing `History` tab inside `/reception` using the existing index page instead of adding a new route or page.
- Added a joined Reception history query so the page can show workflow events with draft metadata plus actor usernames when available.
- Implemented a grouped-by-date workflow feed where receptionists see only their own draft activity while managers/reviewers can see all Reception activity.
- Added focused route coverage for history visibility, date grouping/order, reason notes, and closed-draft events.

**Current state:**
- `/reception` now supports `view=desk`, `view=queue`, and `view=history`.
- Shared History is a simple workflow event feed, not a full audit view.
- Focused Reception review route suite passes: 42 tests in `tests/test_reception_review_routes.py`.

**Key decisions:**
- Keep receptionist history ownership-scoped to match existing draft-detail access instead of exposing other users’ workflow items.
- Keep the History surface event-based rather than one-row-per-draft so Returned/Held/Approved steps stay visible without expanding into full audit tooling.

### Session: Reception manager draft editing
**Date:** 2026-03-30
**What was done:**
- Added the missing manager-side Reception `Edit` action for pending drafts by reusing the existing dedicated edit pages instead of adding modal editing.
- Expanded `/reception/entries/<entry_id>/edit` so manager/reviewer users can edit pending `new_treatment`, `new_payment`, `edit_patient`, `edit_payment`, and `edit_treatment` drafts without posting live data.
- Added a shared Reception draft-update helper so receptionist resubmits and manager edits now use the same validated draft-update path while keeping their review metadata behavior separate.
- Added manager-edit UI copy, a detail-page `Edit draft` action, and focused route coverage for access rules, closed-draft blocking, held-draft editing, and no-live-write payment draft edits.

**Current state:**
- Managers can now correct pending Reception drafts before approving, holding, returning, or rejecting them.
- Manager edits stay draft-only: they update `reception_entries` + workflow events, clear hold/return/reject reasons, and return to the draft detail page.
- Focused Reception regression subset passes: 102 tests across `test_reception_review_routes`, `test_reception_entries_service`, `test_reception_payment_routes`, `test_reception_patient_correction_routes`, and `test_reception_treatment_correction_routes`.

**Key decisions:**
- Manager edit uses dedicated pages now; modal editing is still deferred.
- Locked `new_payment` drafts are included in manager edit, but manager edits still never create or update live rows until approval.

### Session: Reception existing-patient routing for desk-origin treatment drafts
**Date:** 2026-03-29
**What was done:**
- Extended manager approval for desk-origin `new_treatment` drafts so approvers can either create a new patient or attach the new treatment to one chosen existing patient.
- Added inline existing-patient candidate cards plus a Reception-scoped patient search endpoint on the draft detail page for manager review.
- Kept the routing choice read-only until final approval; no manager patient choice is persisted onto the draft before posting.
- Added focused Reception review tests for candidate rendering, patient search, existing-patient approval, missing target validation, and stale selected-patient failure.

**Current state:**
- Desk-origin `new_treatment` approval now supports both new-patient creation and manager-chosen existing-patient attachment.
- Focused Reception review/service suite passes: 65 tests (`python -m pytest tests/test_reception_review_routes.py tests/test_reception_entries_service.py -q`).

**Key decisions:**
- Existing-patient routing updates only the live treatment posting target; it does not edit the chosen patient profile in this slice.
- Matching polish is still intentionally limited to inline candidates plus manual search; no auto-selection or broader override logic was added.

### Session: Reception same-record treatment correction
**Date:** 2026-03-29
**What was done:**
- Added the first same-record Reception treatment-correction flow for `edit_treatment`.
- Treatment cards now expose a separate Reception draft action that launches a locked treatment-correction form instead of the live edit modal.
- Managers can review current-vs-proposed treatment values, approve the correction onto the same live treatment, and returned treatment corrections can be edited/resubmitted by the original receptionist.
- Added focused service/route coverage for the new `edit_treatment` path and reran the Reception regression subset successfully.

**Current state:**
- Supported live approval paths are now:
  - Desk-origin `new_treatment`
  - Treatment-card locked `new_payment`
  - Patient-file locked `edit_patient`
  - Treatment-card locked `edit_treatment`
- Focused Reception regression subset now passes with 75 tests.

**Key decisions:**
- `edit_treatment` stays locked to the same live treatment and same live patient only.
- Approval updates the existing treatment row directly and blocks corrections where `total - discount` would fall below the amount already paid.

### Session: Reception same-record payment correction
**Date:** 2026-03-29
**What was done:**
- Added the missing same-record Reception `edit_payment` flow for treatment-card payment rows.
- Treatment cards now expose a separate Reception draft action for both the parent row’s initial payment and later child-payment rows.
- Managers can review current-vs-proposed payment values, approve the correction onto the same live payment, and returned payment corrections can be edited/resubmitted by the original receptionist.
- Added focused route/service coverage for both parent-row and child-row payment corrections and reran the Reception regression subset successfully.

**Current state:**
- Supported live approval paths are now:
  - Desk-origin `new_treatment`
  - Treatment-card locked `new_payment`
  - Patient-file locked `edit_patient`
  - Treatment-card locked `edit_treatment`
  - Treatment-card locked `edit_payment`
- Focused Reception regression subset now passes with 91 tests.

**Key decisions:**
- `edit_payment` stays locked to the same live payment, same live treatment, and same live patient only.
- Parent-row initial-payment corrections update only payment-editable fields and recompute the parent treatment remaining balance without touching treatment-only fields.
- Payment-correction approval blocks if the live payment changed after draft creation and uses stable SQL tie-breakers for Reception entry/event ordering.

### Session: Startup diagnostics hardening
**Date:** 2026-03-29
**What was done:**
- Hardened Windows launch scripts so startup failures are always captured in persistent logs under `data/logs/` instead of only transient console output.
- Updated `Start-Clinic.bat` to write `startup_stdout.log`, `startup_stderr.log`, and preserve migration failures to `migrate_last.log`.
- Updated `Start-Clinic-Preview.bat` to write `preview_startup_stdout.log`, `preview_startup_stderr.log`, and preserve migration failures to `preview_migrate_last.log`.
- Patched bootstrap compatibility in `clinic_app/services/bootstrap.py` to auto-add missing `reception_entries` columns for older databases before creating Reception indexes.

**Key decisions:**
- Keep app/runtime logic unchanged; only improve operator diagnostics and recovery clarity.
- Keep startup resilient across mixed schema states so migration commands can run instead of failing early with `sqlite3.OperationalError`.

### Session: Reception and AI workflow guardrails
**Date:** 2026-03-29
**What was done:**
- Reviewed the frozen Reception Desk plan against the current app architecture and confirmed the draft-review-approve model is still the right direction for this repo.
- Added two missing approval hardening rules to the Reception spec/implementation contract: stale-data re-review before posting and idempotent final approval to prevent duplicate writes.
- Updated the portable AI workflow files so agents should not invent extra suggestions when the current plan is already sound.

**Key decisions:**
- Keep the Reception workflow direction as-is; do not widen it into receptionist-side live routing or duplicate-cleanup logic.
- AI agents should add suggestions only when they materially improve safety, fit, or decision quality.

### Session: UI quality and tooling guidance hardening
**Date:** 2026-03-29
**What was done:**
- Updated the main AI instruction files so future chats inherit a stronger UI quality bar: simple, polished, clinic-appropriate, and not generic AI-looking output.
- Added explicit guidance that repo code quality is mixed and agents should prefer small cleanup over adding more debt when touching weak areas.
- Added a rule that agents should surface useful skills/plugins/MCPs/tools only when there is a concrete benefit, not as filler.

**Key decisions:**
- Future UI work should aim for high taste and restraint, not flashy redesigns or generic templates.
- Tooling suggestions are encouraged only when they materially improve quality, safety, or speed.

### Session: Workflow hardening for fewer errors and less back-and-forth
**Date:** 2026-03-29
**What was done:**
- Tightened the AI workflow files so new chats explicitly optimize for lower hallucination risk by verifying repo facts instead of guessing.
- Added a standing rule that the AI should actively evaluate whether the user's request is vague, risky, contradictory, or based on a weak assumption, and say so clearly.
- Added a standing rule that after one scoped approval, the AI should complete the full approved safe chunk without repeated permission prompts unless the risk boundary changes.

**Key decisions:**
- “Perfect” and “zero hallucinations” is not a realistic standard; the operational goal is very low error risk through verification, clear uncertainty, and controlled execution.
- The workflow should favor larger cohesive approved chunks, but not cross real risk boundaries silently.

### Session: Workflow cleanup and verification rules
**Date:** 2026-03-29
**What was done:**
- Added an explicit verification ladder to the main AI instruction files: docs first, code second, tests/checks third, then conclude.
- Added an explicit debt-control rule so touched weak areas should either get a small cleanup or a stated reason for deferring cleanup.
- Added an explicit UI rebuild rule that redesign work should preserve routes, permissions, data contracts, and business logic unless the task says otherwise.
- Added a short default tool map so future chats use docs/code search, Playwright, Figma MCP, and tests more consistently.

**Key decisions:**
- The workflow should favor verifiable claims over confident guesses.
- Safe future UI rebuilds must preserve core behavior by default.

### Session: Whole-app system map
**Date:** 2026-03-29
**What was done:**
- Added `docs/SYSTEM_MAP.md` as a practical whole-program orientation doc for future AI chats and contributors.
- Linked the new system map from `docs/AGENT_HANDOFF.md`, `START_HERE_AI.md`, and `docs/INDEX.md` so it becomes part of the normal startup/ramp path.
- Documented the main architectural layers, structural traps, fast file-finding paths, and when to use Playwright/Figma for safer understanding.

**Key decisions:**
- No AI should be expected to “fully know” the whole program from memory alone.
- Future chats should use layered orientation: startup docs first, system map second, then targeted code inspection for the active feature.

### Session: AI system blueprint and instruction hardening
**Date:** 2026-03-29
**What was done:**
- Added `AI_SYSTEM_BLUEPRINT.md` to define the recommended AI operating model for this repo before building plugins or Obsidian automation.
- Strengthened `agents/clinic-lead-developer.md` so the main agent behaves more like a critical mentor and lead developer, not an agreeable assistant.
- Lightly updated `AGENTS.md` to require better consequence analysis, stronger option comparison, and clearer pushback on weak ideas.

**Key decisions:**
- Keep `clinic-lead-developer.md` as the main AI brain for this project.
- Delay plugin creation until the strengthened behavior is tested in real work.
- Treat Obsidian integration as a later phase after behavior and note structure are stable.

### Session: Portable AI startup file
**Date:** 2026-03-29
**What was done:**
- Added `START_HERE_AI.md` as a compact startup guide for new chats and different models.
- Documented the required file read order, expected mentor-style behavior, plan-before-edit standard, and what must be updated after meaningful work.

**Key decisions:**
- Cross-chat consistency should come from repo files, not chat memory.
- `START_HERE_AI.md` should stay short and portable, while deeper rules remain in `AGENTS.md`, `agents/clinic-lead-developer.md`, and `AI_SYSTEM_BLUEPRINT.md`.

### Session: Skill search for agent creation
**Date:** 2026-03-29
**What was done:**
- Read the repo handoff files and the `skill-installer` instructions before checking installable skills.
- Queried the curated OpenAI skills catalog and confirmed there is no direct installable skill specifically for creating agents.
- Checked the experimental catalog path as well; the helper reported that `skills/.experimental` was not found upstream.

**Key decisions:**
- For agent work in this environment, prefer the already available `microsoft-foundry` skill for Foundry agents rather than trying to install a missing generic agent-builder skill.

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

### Session: Reception manager queue and review actions
**Date:** 2026-03-17
**What was done:**
- Replaced the old manager placeholder with a real manager queue inside `/reception`, keeping the same sidebar-based shell.
- Added per-draft detail pages and draft-only manager actions for hold, return, and reject.
- Extended the Reception draft service so those actions update only `reception_entries` and `reception_entry_events`, never live patient or payment rows.
- Added route coverage for queue access, detail access rules, hold/return/reject behavior, and receptionist visibility of returned drafts.

**Key decisions:**
- Manager review in this slice remains fully draft-only; approval posting is still deferred.
- Review-only users now land on the manager queue by default instead of a placeholder page.
- Returned drafts come back to the receptionist desk as `status='edited'` with `last_action='returned'` and visible manager reason.

### Session: Reception first approval posting slice
**Date:** 2026-03-17
**What was done:**
- Added the first live posting path for Reception approvals: Desk-origin `new_treatment` drafts can now create a new patient file and one live treatment row from the manager detail page.
- Added final-confirmation approval UI, stored created live target IDs back onto the draft, and recorded an `approved` workflow event.
- Added tests covering approve permission, confirmation requirement, successful patient+treatment posting, and blocked approval when total amount is missing.

**Key decisions:**
- Approval is still intentionally narrow: only Desk-origin `new_treatment` drafts are supported.
- This slice creates a new patient and treatment only; it does not resolve duplicates or attach to existing live patients yet.
- Payment-only drafts, correction drafts, and manager-side duplicate resolution remain deferred.

### Session: Reception returned draft edit/resubmit loop
**Date:** 2026-03-17
**What was done:**
- Added receptionist-side edit/resubmit routes for returned Desk-origin `new_treatment` drafts only.
- Extracted the shared Reception draft form into a partial and added a dedicated returned-draft edit page.
- Added `resubmit_returned_entry(...)`, cleared active return state on successful resubmit, and changed desk/queue ordering to `updated_at DESC` so resubmitted drafts float to the top.
- Added route/service coverage for returned-draft ownership, invalid resubmit attempts, sticky form re-rendering, and desk/queue ordering after resubmit.

**Current state:**
- Reception can now complete the daily loop: submit draft, manager returns, receptionist fixes it, and resubmits it to the manager queue.
- Only returned Desk-origin `new_treatment` drafts are editable in this slice; held drafts remain manager-side and approval scope is unchanged.
- Reception/RBAC regression subset now passes with 49 tests.

**Key decisions:**
- Only returned drafts are editable by reception; held drafts are not.
- Returned reasons are cleared from active draft state after successful resubmit but remain in workflow history.
- Queue and desk lists must prioritize `updated_at`, not original `submitted_at`.

### Session: Reception locked new_payment draft/approval
**Date:** 2026-03-17
**What was done:**
- Added locked-context `new_payment` drafts launched from treatment cards into a dedicated `/reception/entries/new-payment` page.
- Added manager approval for those drafts through the existing Reception detail flow, posting one child payment onto the locked live treatment.
- Hardened the shared `add_payment_to_treatment(...)` helper so both the live payment route and the Reception approval path now recompute and persist parent `remaining_cents`.
- Added route/service/payment regression coverage for payment draft creation, approval, stale-balance failure, and shared helper balance updates.

**Current state:**
- Reception can now create `new_payment` drafts only from a specific treatment card, not from the Desk page.
- Managers can approve those locked payment drafts; approval re-checks the current live remaining amount and blocks overpayment if the balance changed.
- Reception/payment/RBAC regression subset now passes with 66 tests.

**Key decisions:**
- `new_payment` drafts stay locked to `treatment_card` source only in this slice.
- Reception approval must reuse the shared live add-payment helper; no separate Reception-only SQL path for child payments.
- Parent `remaining_cents` recomputation is now part of the shared helper contract, not optional route cleanup.

### Session: Reception same-record edit_patient correction
**Date:** 2026-03-17
**What was done:**
- Added patient-file launcher support for locked `edit_patient` drafts and a dedicated Reception patient-correction page.
- Extended Reception detail/review/approval so managers can compare current vs proposed patient values and approve those drafts onto the same live patient only.
- Added returned-draft edit/resubmit support for `edit_patient` drafts owned by the original receptionist.
- Refactored live `/patients/<pid>/edit` to use the same shared patient-profile normalization/update helper as Reception approval, then added regression coverage for phone/page sync.

**Current state:**
- Reception now supports one same-record correction type end-to-end: `edit_patient` from the patient file.
- Supported live approval paths are now:
  - Desk-origin `new_treatment`
  - Treatment-card locked `new_payment`
  - Patient-file locked `edit_patient`
- Reception/patient-profile/RBAC regression subset now passes with 80 tests.

**Key decisions:**
- `edit_patient` stays locked to the same live patient; no merge, reassignment, or short-id rewrite logic was added.
- Returned `edit_patient` drafts are editable by the original receptionist; held drafts are not.
- Live patient edit and Reception patient-correction approval must keep sharing the same patient-profile persistence helper.
