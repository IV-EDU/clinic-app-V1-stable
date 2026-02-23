# Advisor Memory
Last updated: 2026-02-23

## Current Priorities
1. UI Redesign — Phase 2 next (modal system + toast notifications)
2. Fix remaining Phase 1 dark mode polish issues as they come up
3. Decide on agent ecosystem — what other agents to build (use advisor for this)

## Recent Decisions
- 2026-02-23: Updated `advisor.md` to include LLM tool class recommendations (heavyweight vs nimble coder) and updated the Handoff Brief format.
- 2026-02-23: Created Strategic Advisor as first agent (`agents/advisor.md`)
- 2026-02-23: Memory system uses rolling snapshot pattern (this file), max 40 lines
- 2026-02-23: Fixed dark mode issues — modal backdrop, button lighting, patient card gradient
- 2026-02-22: Completed Phase 1 of UI Redesign (design-system.css, dark toggle, FOUC prevention)

## Open Questions
- What should the second agent be? (use Meta Mode to figure this out)
- Should we do Phase 2 (modals) or Phase 3 (Arabic search) next? -> Decided Phase 2 Modals first.

## Permanent Context
- This is a PRODUCTION dental clinic app — real patients, real data, no cloud
- User is NOT a programmer — plain language always
- Arabic/RTL is first-class, never an afterthought
- Money stored in cents (integer), IDs are UUIDs, never touch import system
- Admin credentials: admin/admin — NEVER change them

## Agent Roster
- `agents/advisor.md` — Strategic Advisor: blunt thinking partner, prioritization, critique, mentoring
