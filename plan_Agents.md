# plan_Agents.md – Planning Guide for Agents

This file explains **how** you should design plans for new tasks in Clinic-App-Local.  
It works together with:
- `AGENTS.md` – behavior and safety rules.
- `LAST_PLAN.md` – the product roadmap for V1.

Whenever the user asks you to:
- “plan this”
- “design a roadmap”
- “think about next steps”
you **must** follow this guide.

---

## 1) Overall Planning Flow

For any non-trivial task (more than a one-line change):

1. **Understand the request**
   - Rephrase the user’s request in 1–2 sentences.
   - Mention which part of the app it touches (e.g. “patient file UI”, “payments receipts”).
   - Quickly consider: is the requested approach safe and sensible? If not, say so and propose a better alternative.

2. **Look at the roadmap**
   - Skim `LAST_PLAN.md`.
   - Decide:
     - Which phase/section your work belongs to, **or**
     - That you want to propose a new phase/bullet.

3. **Identify affected areas**
   - List the main places you expect to touch (a few bullets is enough), for example:
     - Blueprints / routes / endpoints.
     - Templates.
     - CSS files.
     - Services/helpers.
     - Tests.

4. **Draft a small, shippable plan**
   - Break the work into 3–6 short bullets.
   - Each bullet should be:
     - Focused on one page/feature.
     - Either “UI-only”, “UI + backend (no routing change)”, or “UI + backend (routing change)” (say which).
     - Small enough to keep the app stable if you stop after that bullet.
   - If any bullet feels risky (especially DB/schema/security), clearly mark it and flag this to the user.

5. **Ask for confirmation**
   - Show the plan to the user.
   - Clearly ask for approval before editing files.
   - If you also propose changes to `LAST_PLAN.md`, call them out separately and ask if they agree.

6. **Execute in small slices**
   - Implement one slice at a time.
   - After each slice:
     - Summarize what changed.
     - Mention any tests you ran or would run.
     - Stop and offer the user a chance to review before moving on.
   - Clean up after each slice:
     - Remove temporary debug prints or experimental code you added.
     - Update `docs/INDEX.md` and `README.md` if your slice changed the structure or user-visible behavior.

---

## 2) Linking Plans to `LAST_PLAN.md`

When you create a plan, always add a short “roadmap link” line, for example:

- “Roadmap link: `LAST_PLAN.md`, Phase 2 – Core Screens.”
- “Roadmap link: New proposed bullet under Phase 5 – Diag_Plus Integration.”

If your planned work does not clearly fit into an existing phase:

1. Propose a **new bullet or phase** in `LAST_PLAN.md` in your message.
2. Explain briefly why it belongs there and what benefit it brings.
3. Wait for the user to approve before editing `LAST_PLAN.md`.

Do **not** silently drift away from the roadmap. If the roadmap feels wrong or outdated, say so and propose an update.

---

## 3) Designing Good Plans (UI / Theme / Arabic)

For UI-heavy tasks (most tasks in this app), your plan should consider:

1. **Scope**
   - Limit each plan to one or two screens, or a clearly defined feature area:
     - e.g., “patient detail + payments list”, or
     - “appointments filters + cards”, or
     - “payments UI + doctor chips (templates + CSS + small helpers)”.

2. **Shared systems**
   - Plan to use:
     - `_base.html` and `render_page()` for layouts.
     - Shared CSS from `static/css/app.css` and `static/css/theme-system.css`.
     - Shared components (buttons, cards, alerts, modals).

3. **Theme**
   - Use CSS variables (`--primary-color`, `--accent-color`, etc.).
   - Avoid introducing new hard-coded brand colors.

4. **Arabic & RTL**
   - Ensure your plan includes checking:
     - Text wrapping and overflow for Arabic labels.
     - Correct `dir="rtl"` behavior on inputs, tables, cards.
     - That all new labels have entries in `i18n.py` for both English and Arabic.

5. **Safety**
   - Prefer “UI-only” slices first.
   - If you need backend changes, mark that bullet as “UI + backend” and keep it small and focused.
   - Include a bullet to run at least the most relevant tests (or `Run-Tests.bat`) when backend or template wiring changes.

Example skeleton for a UI plan:
- Summarize: “Improve patient detail header and payments cards to match main theme and fix overflow.”
- Roadmap link: `LAST_PLAN.md`, Phase A – Design System & Core Shell (for header) and Phase C – Payments (for cards).
- Plan:
  - Update shared CSS for button/card variants (UI-only).
  - Apply shared components to `templates/patients/detail.html` (UI-only).
  - Refactor `templates/payments/_list.html` layout to be responsive and RTL-safe (UI + backend if needed).
  - Run tests covering core layout and payments pages and report results.

---

## 4) Designing Good Plans (Backend / Bug Fixes)

For tasks that touch Python logic:

1. **State the reason explicitly**
   - Example: “This change is needed because a test is failing / there is a reported bug.”

2. **Narrow the scope**
   - Limit to:
     - One route/endpoint.
     - One helper function.
     - One DB query or validation.

3. **Testing**
   - Say which tests you plan to run (e.g. “Run-Tests.bat”, or a specific test file).
   - Include a bullet “Run tests for this area and report results.” and actually run them when possible.

4. **Risk level**
   - Add a short risk note:
     - “Risk: Low (UI-only).”
     - “Risk: Medium (small change to payments validation).”
     - “Risk: High (DB schema).”
   - For High risk, always ask the user if they are comfortable before proceeding.

Example skeleton for a backend plan:
- Summarize: “Fix overpayment validation bug on payments form.”
- Roadmap link: `LAST_PLAN.md`, Phase 2 – Core Screens (payments validation).
- Plan:
  - Reproduce the bug and capture the exact error / wrong behavior.
  - Localize the issue in `clinic_app/services/payments.py` and confirm with a quick read.
  - Propose a minimal fix to the validation logic and update any related UI messages.
  - Run tests related to payments and report results.

---

## 5) Updating `LAST_PLAN.md`

When you are asked to “update the plan” or it is obvious that the roadmap is out of date:

1. **Read the current `LAST_PLAN.md`.**
2. **Identify:**
   - Parts that are already implemented (and can move to “Completed”).
   - Parts that are no longer relevant.
   - New work the user is asking for that is not represented yet.
3. **Propose changes in your message**:
   - Be explicit: “I propose to:
     - Mark Phase X, bullet Y as completed.
     - Add a new Phase Z bullet for [new feature].”
4. **Wait for approval**:
   - Only after the user agrees should you actually edit `LAST_PLAN.md`.

Keep changes small and clear so the roadmap stays easy to read.

---

## 6) What Not to Do in Plans

- Do **not**:
  - Plan to touch many unrelated areas in one go (e.g. “fix patients, payments, appointments, and expenses all at once”).
  - Promise new infrastructure (Docker, Redis, cloud services) unless the user asks.
  - Hide risky work inside a small-sounding bullet.
  - Skip the planning/confirmation step, even for a small change.

If the user asks for something very large, break your response into:
- A high-level multi-phase roadmap.
- A **first small slice** (one screen/feature) with a concrete plan.
Then ask which slice they want you to start with.

---

## 7) Example: Large UI Refresh Request

User request (simplified):
> “Unify UI across patients, payments, appointments, expenses; add per-clinic theme; ensure Arabic everywhere.”

Good planning response:
- Summarize:
  - “You want the whole app to feel like one program, with clinic branding and complete Arabic support, without breaking existing logic.”
- Roadmap link:
  - “This spans multiple phases in `LAST_PLAN.md` (Phases 1–6). For this task I suggest we focus only on Phase 2: Core Screens.”
- Plan (for this first slice):
  - “Update shared button/card styles to use theme variables (UI-only).”
  - “Apply new header + actions layout to patient detail (`templates/patients/detail.html`) (UI-only).”
  - “Refactor payment cards in `templates/payments/_list.html` so they align and do not overflow, including Arabic text (UI-only).”
  - “Quick visual check in English + Arabic on patient detail and payments pages.”

This keeps the first step small, shippable, and clearly connected to the roadmap.

---

Use this guide to keep your plans:
- Small.
- Clear.
- Roadmap-aligned.
- Safe for a real clinic’s production use.
