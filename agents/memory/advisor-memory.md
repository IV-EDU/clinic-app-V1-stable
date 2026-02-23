# Advisor Memory
Last updated: 2026-02-23

## Current Priorities
1. UI Redesign — **Phase 4 next** (Splitting the Admin Settings monolith)
2. Handle the architectural risks of Phase 4 carefully (Excel import logic preservation).
3. Continue enforcing the "Manager Authorization" rule for all coding agents.

## Recent Decisions
- **2026-02-23:** Locked in the "Handoff Workflow." Advisor plans -> writes Handoff Brief -> User pastes to Coder (ChatGPT Pro). No fully autonomous loops to save Antigravity credits.
- **2026-02-23:** Added "Manager Authorization" rule to `AGENTS.md` to stop agents from writing code before being explicitly told "Proceed."
- **2026-02-23:** Completed Phase 2 (Modals) and Phase 3 (Arabic Search).

## Open Questions
- How to safely split the 6000-line `admin_settings.py` monolith in Phase 4 without breaking the 8/10 fragility data import logic.

## Permanent Context
- This is a PRODUCTION dental clinic app — real patients, real data, no cloud
- User is NOT a programmer — plain language always
- Arabic/RTL is first-class, never an afterthought
- Money stored in cents (integer), IDs are UUIDs, never touch import system
- Admin credentials: admin/admin — NEVER change them

## Agent Roster
- `agents/advisor.md` — Strategic Advisor: blunt thinking partner, prioritization, critique, mentoring
