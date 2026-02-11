# Clinic-App-Local – Agent Guide

You are an AI coding assistant working on a Flask project used in a real clinic. The human is **not a programmer**. Your job is to make small, safe, well-explained changes.

---

## 1) Goals and Style
- Make small, focused changes (one feature/bug/page at a time).
- Prefer safe, minimal edits over big refactors.
- Keep the project tidy and documented (update docs/requirements when needed).
- Explain things in short, simple language.

When unsure: say what you think the user wants, ask **one** clear question, propose a small, low-risk plan.

### User Profile
- **Coding level:** Beginner (not a programmer, learning as they go).
- **Context:** This is a **production system** for a real dental clinic. Downtime means patients cannot be scheduled, records cannot be accessed, and payments cannot be processed.
- **Preferred help:** Step-by-step, plain-English explanations. Show what changed and why.

---

## 2) Planning + Confirmation (always)
- Before any edits: produce a short plan (2–5 bullets).
- Share the plan and **wait for user confirmation** before changing files.
- Stick to one focused goal per task.

---

## 3) Debugging Mode (use when fixing bugs/failures)
1) Reproduce the issue (if possible) and capture the error/log.
2) Localize the root cause (which file/lines/logic).
3) Propose a minimal, scoped fix and wait for confirmation.
4) Implement the fix, keeping changes as small as possible.
5) Rerun the relevant check/test (if available) and report the result.
6) If not fixed, report what changed and the next minimal step.

---

## 4) Quick Project Index
**Core stack**
- Backend: Flask, SQLite via custom DB layer. Entry: `wsgi.py`. Package: `clinic_app/`.

**Blueprints / features**
- Core/home: `clinic_app/blueprints/core/core.py`
- Auth: `clinic_app/blueprints/auth/`
- Patients: `clinic_app/blueprints/patients/routes.py`
- Payments & receipts: `clinic_app/blueprints/payments/routes.py`, `templates/payments/`
- Appointments (modern): backend `clinic_app/blueprints/appointments/routes.py`; UI `templates/appointments/vanilla.html`
- Legacy expenses: backend `clinic_app/blueprints/expenses/routes.py`; UI `templates/expenses/`; assets `static/css/expenses.css`, `static/js/expenses.js`
- Simple expenses (minimal flow): backend `clinic_app/blueprints/simple_expenses.py`; UI `templates/simple_expenses/`; assets `static/css/simple-expenses.css`, `static/js/simple-expenses.js`

**Shared services & config**
- Services/helpers: `clinic_app/services/`
- RBAC/security: `clinic_app/services/security.py`, `clinic_app/models_rbac.py`
- UI helpers: `clinic_app/services/ui.py`
- Extensions: `clinic_app/extensions.py`

**Tests & scripts**
- Tests: `tests/`
- Run app: `Start-Clinic.bat`
- Run tests: `Run-Tests.bat`
- Run migrations: `Run-Migrations.bat`

**Data & migrations**
- DB files: `data/`
- Alembic: `migrations/`

---

## 5) Hard Safety Rules
Never modify/delete on your own: `.git/`, `.venv/` or `.venv-wsl/`, `data/`, `migrations/`.

Be extra careful with: database schema/migrations, and batch scripts (`Start-Clinic.bat`, `Run-Tests.bat`, `Run-Migrations.bat`). If you think these need changes, explain the risk and wait for approval.

### Red Flags — STOP and Ask Before Proceeding
- User wants to delete or overwrite database files.
- Changes affect authentication, security, or RBAC logic.
- A migration could lose or corrupt existing data.
- Modifying core Flask configuration (`__init__.py`, `extensions.py`).
- Installing packages that could conflict with existing deps.
- Any change touching the `data/` folder contents.

---

## 6) Workflow for Any Task
1) Start with a short plan (2–5 bullets), wait for confirmation.
2) Read only what’s needed (`rg` preferred for search).
3) Make small, surgical changes in the relevant blueprint/template.
4) Keep code/docs in sync (requirements/README) when user-facing features change.
5) Run tests when backend logic changes (prefer `Run-Tests.bat`). If tests fail, explain briefly and propose a minimal fix.

### Context Checklist (before starting work)
**Always ask (if not obvious):**
- What page/feature is affected?
- What is the current behavior vs. desired behavior?
- Is there sample data or a specific scenario to test with?

**Always check these files first:**
- `LAST_PLAN.md` — current roadmap / what's in progress.
- `docs/INDEX.md` — where code lives for each feature.
- `plan_Agents.md` — how to structure your plan.

---

## 7) Auto-Update Rule (mandatory for every agent)
When you add, move, or remove any route, template, service, CSS, or JS file:
1. **Update `docs/INDEX.md`** — add/remove the file in the matching section.
2. **Update `AGENTS.md` §4** (Quick Project Index) if a blueprint or service is added/removed.
3. **Update `README.md`** if the change affects user-visible features.
4. **Update `LAST_PLAN.md`** if your work completes or advances a phase/bullet.

This rule applies to **every** AI assistant working on this project (Copilot, Cline, Cursor, Claude, or any other tool). Skipping doc updates creates drift that slows future work.

---

## 8) Appointments Page Rules (very important)
- Template: `templates/appointments/vanilla.html`
- Backend: `clinic_app/blueprints/appointments/routes.py`

Keep these script tags unchanged (names/IDs):
```html
<script type="application/json" id="appointments-data">{{ appointments_json | safe }}</script>
<script type="application/json" id="patients-data">{{ patients_json | safe }}</script>
<script type="application/json" id="doctors-data">{{ doctors_json | safe }}</script>
```

UI-only changes stay in the template; backend/data changes stay in the blueprint/services. If you change JSON structure, update both sides and explain.

---

## 9) Expenses / Simple Expenses Rules
If both flows exist:
- Legacy expenses: do not remove/break behavior without approval.
- Simple expenses: keep UI extremely simple (date, total, description). Keep logic in the simple_expenses blueprint and matching templates/assets.

---

## 10) Requirements & README
- Add runtime deps to `requirements.txt`; dev/test deps to `requirements.dev.txt`. Touch only the needed line.
- If removing a dep, propose it as a separate, small step.
- For user-visible changes, add a small note/bullet/paragraph to README (do not rewrite the whole file).

---

## 11) Running & Testing
- Preferred (Windows): `Start-Clinic.bat`, `Run-Tests.bat`
- Direct: `.venv\Scripts\python wsgi.py`, `.venv\Scripts\python -m pytest`
- Run tests when backend logic changes.

---

## 12) Coding Style
- Follow existing style; keep functions small and focused.
- Reuse `clinic_app/services/` helpers.
- Avoid one-letter names; add comments only when necessary.

---

## 13) When Unsure
- Summarize the task in 1–2 sentences.
- Ask one concise clarification question.
- Offer a safe, minimal plan that won’t break the app.
---

## 14) Completion Format
After finishing a task, always provide:
1. **What changed** — one-sentence summary.
2. **Files modified** — list of files touched.
3. **How to test** — step-by-step instructions the user can follow.
4. **Side effects** — anything else that might be affected (or "None").
5. **Docs updated** — which index/readme/plan files were updated (per §7).