# MEMORY.md – Session Handoff Log

> **For AI agents:** Read this at the START of every session. Update it at the END.
> This file ensures continuity across different chats, tools, and models.
> See `AGENTS.md` §0 and §14 for the full protocol.

---

## Current State (updated after each session)

**App status:** Running, stable. Flask + SQLite dental clinic on Windows.
**Branch:** `feature/phase4-admin-split`
**Repo:** `IV-EDU/clinic-app-V1-stable`
**Data:** 1,021 patients, 912 payments. Production use.
**Login:** `admin` / `admin` (NEVER change this)

### What Works
- Core patient CRUD, payments, receipts (PDF with Arabic reshaping)
- Appointments page (vanilla.html) — clean card-based UI
- Simple expenses — minimal working flow
- Arabic/RTL with Cairo font, `T()` i18n system (2000+ translations)
- Dark mode toggle (design-system.css + data-theme attribute)
- Theme settings (admin), clinic logo/branding
- Full test suite passes (`scripts/Run-Tests.bat`)

### Known Problems
- See `KNOWN_ISSUES.md` for detailed list
- Admin settings is a 5,700-line monolith — needs splitting (Phase 4 in LAST_PLAN.md)
- Dark mode has gaps on some pages
- No dashboard — home page is just a patient list
- Two expense systems exist (legacy + simple)
- Diagnosis pages are disconnected from main app flow

---

## Recent Sessions

### Session: Project Organization & Workflow Redesign
**Date:** 2025-07-14
**What was done:**
- Full project organization audit completed
- Rewrote `AGENTS.md` (653 → ~210 lines) with guardian/Jarvis behavior, memory protocol
- Created `DESIGN_BRIEF.md` (clinic-specific design system for AI agents)
- Created `MEMORY.md` (this file — session handoff system)
- Merged `UI_REDESIGN_PLAN.md` + `plan_Agents.md` content into `LAST_PLAN.md`
- Moved skills from `agents/skills/` to `skills/` (xlsx, pdf, webapp-testing, agent-creator, skill-creator)
- Rewrote `.cursorrules` and `.github/copilot-instructions.md` as 3-line redirects to AGENTS.md
- Deleted stale files: `agents/` dir, `handoff.md`, `HANDOFF-PHASE2.md`, `UI_REDESIGN_PLAN.md`, `plan_Agents.md`
- Updated `.gitignore`

**Key decisions made:**
- Single source of truth: `AGENTS.md` (all IDE configs redirect to it)
- 4 key files: `AGENTS.md` + `KNOWN_ISSUES.md` + `LAST_PLAN.md` + `MEMORY.md`
- `DESIGN_BRIEF.md` replaces generic frontend-design skill (clinic-specific calm/professional aesthetic)
- Memory/handoff via file (not API) — works across all AI tools
- 5 skills retained in `skills/` directory

---

## Active Decisions Log

| Decision | Reason | Date |
|----------|--------|------|
| Flask for V1 (not React rewrite) | Polish existing app (~4-6 weeks) vs rewrite (~3-5 months) | 2025-07-14 |
| AGENTS.md as single source of truth | Prevents rule drift across 7+ config files | 2025-07-14 |
| File-based memory (MEMORY.md) | Works across all AI tools, no API needed | 2025-07-14 |
| Calm/clinical design (not bold/techy) | Medical app for a dentist, not a startup | 2025-07-14 |
| Keep both expense systems for now | Legacy has users; consolidate in Phase E | 2025-07-14 |

---

## What's Next

**Immediate (next session):**
- Start Phase 4 from `LAST_PLAN.md` — Split admin settings into 5 focused pages
- Or: pick any item from `KNOWN_ISSUES.md` and fix it

**Upcoming:**
- Phase 5: Dashboard homepage + nav restructure
- Phase E: Expense consolidation
- Phase 7 remaining: PACKAGING.md, README update, final UI consistency pass

---

## Template for New Entries

When updating this file, add a new entry under "Recent Sessions":

```
### Session: [Brief Title]
**Date:** YYYY-MM-DD
**What was done:**
- [bullet points of changes]

**Key decisions:**
- [any new decisions and their reasoning]
```

Move old entries to an `## Archived Sessions` section at the bottom when the file exceeds ~150 lines.
