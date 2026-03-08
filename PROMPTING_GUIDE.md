# PROMPTING_GUIDE.md - Safe AI Prompting For This Project

This file is for the clinic owner. Use it when asking AI to change the app.

The goal is simple:
- smaller tasks
- fewer errors
- less chance of AI breaking unrelated parts of the clinic app

---

## 1) Golden Rule

Ask for **one small thing at a time**.

Good:
- "Make the appointments page use the sidebar layout only."
- "Fix the dark mode on the images page drop zone."
- "Split one section of admin settings into a cleaner layout."

Bad:
- "Redesign the whole app."
- "Improve everything in admin, reports, and appointments."
- "Make it modern and fix bugs."

---

## 2) Best Prompt Formula

Copy this structure:

```text
Goal: [what you want]
Area: [which page or feature]
Type: [UI-only / bug fix / UI + backend]
Allowed files: [if known, list them; if not, say "find them first"]
Do not touch: [anything risky or unrelated]
Reason: [why this matters]
Success means: [what should be true when done]
Show me: a short plan, risk level, and wait for OK before editing
```

---

## 3) Copy-Paste Templates

### Template A - Safe UI change

```text
Goal: Update the layout/style of one page
Area: [page name]
Type: UI-only
Allowed files: find them first, then tell me the allowed files
Do not touch: routes, database, services, API response formats
Reason: I want visual improvement without breaking working logic
Success means: the page looks better, still works in Arabic/RTL and dark mode, and no unrelated behavior changes
Show me: a short plan, risk level, and wait for OK before editing
```

### Template B - Safe bug fix

```text
Goal: Fix one bug
Area: [page or feature]
Type: bug fix
Allowed files: find them first, then tell me the allowed files
Do not touch: unrelated features or protected files unless the bug requires it
Reason: this bug affects daily clinic use
Success means: the bug is reproduced, fixed at the root cause, and the relevant tests/checks are run
Show me: the root cause, short plan, risk level, and wait for OK before editing
```

### Template C - Explore first, no code yet

```text
I do not want code changes yet.
First explore this feature and explain:
1. which files control it
2. what is risky
3. the safest small next step
Area: [feature or page]
```

### Template D - Sidebar rollout task

```text
Goal: Opt one page into the sidebar layout
Area: [page name]
Type: UI-only
Allowed files: the page template and any directly related CSS only
Do not touch: routes, APIs, business logic, database, tests outside this page's behavior
Reason: continue the page-by-page UI rollout safely
Success means: the page uses the sidebar shell and existing functions still work
Show me: a short plan, risk level, allowed files, and wait for OK before editing
```

---

## 4) Project-Specific Safety Words

When you want the AI to be careful, include these exact phrases:

- `UI-only task`
- `one focused goal only`
- `find allowed files first`
- `do not touch protected areas`
- `wait for OK before editing`
- `run relevant tests only if backend changes`
- `update MEMORY.md and docs if needed`

These phrases help force the AI into a safer workflow.

---

## 5) If You Do Not Know File Names

That is fine. Say this:

```text
I do not know the file names.
First inspect the code and tell me which files control this feature.
Then propose the smallest safe change.
Do not edit anything yet.
```

---

## 6) What To Avoid Asking In One Prompt

Avoid combining these in one request:
- UI redesign + bug fixing + refactor
- admin + appointments + payments together
- layout changes + database/schema changes
- translation work + route changes + CSS cleanup together

If you want all of those, break them into separate chats or separate tasks.

---

## 7) My Recommended Default Prompt

If you are unsure, start with this:

```text
You are working on a real clinic app for a non-coder.
I want one small safe change only.
First inspect the feature and tell me:
1. what files control it
2. what the risk is
3. the smallest safe next step

Then give me a short plan with allowed files and wait for OK before editing.
```

---

## 8) Best Workflow For You

Use this order for future AI work:
1. Explore first if the task is unclear.
2. Approve one small plan.
3. Let the AI edit only the allowed files.
4. Ask what was changed in simple language.
5. Make sure `MEMORY.md` is updated if the task was important.

---

## 9) Good Real Examples For This Repo

```text
Goal: Make the appointments page use the sidebar shell
Area: appointments page
Type: UI-only
Allowed files: templates/appointments/vanilla.html and static/css/app.css only
Do not touch: appointment routes, APIs, services, JSON formats, tests outside the page
Reason: continue the current UI rollout safely
Success means: the appointments page uses the sidebar layout and all current appointment actions still work
Show me: a short plan, risk level, and wait for OK before editing
```

```text
Goal: Fix dark mode on the images page drop zone
Area: patient images page
Type: UI-only
Allowed files: find them first, then tell me the allowed files
Do not touch: diagnosis logic, upload backend, database, patient routes
Reason: dark mode looks broken and unprofessional
Success means: the drop zone matches dark mode without changing image upload behavior
Show me: a short plan, risk level, and wait for OK before editing
```

```text
I want to improve admin settings, but do not edit yet.
First inspect the admin area and tell me the safest way to split it into smaller steps.
I want a recommendation, not code yet.
```