## Task: UI Redesign Phase 2 – Modal System & Toasts

### Recommended Agent:
**[Nimble Coder / UI]** — Use Claude Sonnet (or equivalent strict coding model).
*Why: This is frontend plumbing (Vanilla JS & CSS). You need a model that writes minimal, tight code and perfectly respects the existing `design-system.css` variables without hallucinating complex frameworks.*

### Goal
Replace the scattered, inconsistent inline modals and flash messages across the app with a unified, reusable JavaScript/CSS system. We need a standard Modal class and a Toast notification system that handles success/error states natively, fully supporting the existing dark mode.

### Plan
1. **Create CSS:** Build `static/css/components.css` with classes for `.modal-container`, `.modal-dialog` (various sizes), and `.toast-container` / `.toast`. Ensure perfect dark mode support using `design-system.css` variables.
2. **Create JS:** Build `static/js/modal-system.js` and `static/js/toast.js` with simple, globally accessible functions like `openModal(id)` and `showToast(message, type)`.
3. **Integrate:** Add the new CSS/JS to `templates/_base.html` along with the base structural HTML for the toast container.
4. **Implement Loading States:** Add a simple CSS spinner class and skeleton loader class to `components.css`.

### Constraints
- **NO FRAMEWORKS:** Use only Vanilla JS and pure CSS.
- **DO NOT MIGRATE YET:** Do NOT rewrite the existing modals (like the diagnosis page or patient detail page) in this task. Just build the foundation in `_base.html` and verify it works. We will migrate pages one-by-one in future tasks.
- **RTL FIRST:** Ensure the toast container stacks correctly in Arabic (RTL) mode.
- **COLORS:** Strictly use the `--color-*` variables defined in `design-system.css`. Do not hardcode any hex codes or `rgba` values.

### Definition of Done
- Server runs cleanly (`python wsgi.py`).
- DevTools shows `components.css`, `modal-system.js`, and `toast.js` loading correctly via `_base.html`.
- **CRITICAL - VISUAL QA:** The agent MUST use the `browser_subagent` to trigger `openModal('id')` and `showToast('msg')` in the browser console. The agent MUST take screenshots of both components in BOTH Light Mode and Dark Mode, save them to `data/agent-screenshots/`, and present them to the user for final approval. The task is not done until the user verifies the screenshots.
