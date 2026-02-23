# Advisor Memory
Last updated: 2026-02-23

## Current Priorities
1. **Agent ecosystem overhaul** — Advisor and Coder both rewritten. ✅
2. UI Redesign — Phase 4 next (Splitting the Admin Settings monolith).
3. Handle the architectural risks of Phase 4 carefully (Excel import logic preservation).

## Recent Decisions
- **2026-02-23:** Rewrote `advisor.md` — project-adaptive, deep analysis rule, proactive nudging, merged Architecture into Ideation mode, moved handoff format to knowledge base.
- **2026-02-23:** Killed 11 irrelevant skills, kept 5 (xlsx, pdf, webapp-testing, frontend-design, skill-creator), created agent-creator skill.
- **2026-02-23:** Locked in "Handoff Workflow." Advisor plans → handoff brief → User pastes to Coder.
- **2026-02-23:** Completed Phase 2 (Modals) and Phase 3 (Arabic Search).

## Open Questions
- How to safely split the 6000-line `admin_settings.py` monolith in Phase 4.

## Permanent Context
- This is a PRODUCTION dental clinic app — real patients, real data, no cloud
- User is NOT a programmer — plain language always
- Arabic/RTL is first-class, never an afterthought
- Money stored in cents (integer), IDs are UUIDs, never touch import system
- Admin credentials: admin/admin — NEVER change them

## Agent Roster
- `agents/advisor.md` — Strategic Advisor: mastermind brain, deep analysis, prioritization, planning
- `agents/coder.md` — Lead Coder: executes handoff briefs, writes code
