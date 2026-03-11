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
  - History (grouped by date; safety/audit surface for both)
- New submission opens as **slide-over/modal** (avoid “tons of pages” feel). No “save draft” feature.
- Stored statuses are frozen: `new`, `edited`, `held`, `approved`, `rejected`.
  - “Returned / Needs changes” is a **UI label** derived from `last_action='returned'` + optional `return_reason` (typically with `status='edited'`).
- **Option B editing model (Recall-to-edit):**
  - Managers can lock an item while reviewing.
  - Reception can **Recall** any time before approval; recall clears the lock.
  - If an item is held and reception recalls/edits it, it becomes `edited` (held cleared).
- **New patient intent:**
  - Reception may mark “New patient”.
  - Manager may override to an existing patient if strong duplicates exist; otherwise approval can create the patient then post treatment/payment.
- Posting safety: approval requires explicit final confirmation; when attaching payment to a treatment, recompute and persist parent `remaining_cents`.
- V1 scope direction: inserts first (new treatment + attach payment). Editing existing live rows (corrections) later after stability.

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
| Reception area UX | Single `/reception` area; modal-first; recall-to-edit | 2026-03-11 |

---

## Template for New Entries

### Session: [Brief Title]
**Date:** YYYY-MM-DD
**What was done:**
- [bullet points of changes]

**Key decisions:**
- [any new decisions and their reasoning]

