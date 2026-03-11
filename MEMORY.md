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
  - new visit-only entries
  - new treatments
  - new payments
  - corrections to an existing payment
  - corrections to an existing treatment
- Same-record means the correction stays on the same live payment or treatment.
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
| V1 excludes reception delete drafts | Prevent high-risk delete approvals in the first rollout | 2026-03-11 |
| No split delete/add correction chains in V1 | One mistake must be reviewed as one correction request | 2026-03-11 |

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

### Session: [Brief Title]
**Date:** YYYY-MM-DD
**What was done:**
- [bullet points of changes]

**Key decisions:**
- [any new decisions and their reasoning]
