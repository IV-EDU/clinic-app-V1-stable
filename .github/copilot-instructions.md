# Copilot Instructions – Clinic-App-Local

> Auto-read by GitHub Copilot. For full rules see `AGENTS.md`.

## About
Dental clinic management system (Flask + SQLite, Windows).
The user is **not a programmer** — use simple language, small safe changes.

## Safety — NEVER modify or delete
- `data/` — real patient data
- `migrations/` — DB version history
- `.venv/`, `.venv-wsl/` — Python environments
- `.git/` — version control

## Project Layout
```
clinic_app/             ← Main Python package
  blueprints/           ← Feature modules (appointments, patients, payments, expenses, reports, admin, auth, images)
  services/             ← Shared business logic (24 files)
  forms/                ← WTForms
  models.py, models_rbac.py
templates/              ← Jinja2 HTML pages
static/css/ static/js/  ← Frontend assets (Tailwind-based CSS, vanilla JS)
tests/                  ← pytest suite (~32 files)
e2e/tests/              ← Playwright browser smoke suite
data/                   ← Runtime data (DB, backups, images) — DO NOT TOUCH
```

## Key Conventions
- Plan first (2–5 bullets), then implement. **One feature per session — never combine multiple phases.**
- Reuse helpers in `clinic_app/services/`. Follow existing code style.
- Use `render_page()` for template rendering, `T()` for i18n strings.
- Money stored in cents (integer). IDs are UUID text strings.
- Runtime deps → `requirements.txt`. Dev deps → `requirements.dev.txt`.
- Run `Run-Validation.bat` after code changes (full `pytest` + Playwright smoke).
- Use `Run-Tests.bat` for logic-only runs and `Run-E2E-Tests.bat` for browser-only runs.
- **Tests MUST pass before declaring done.** No exceptions.
- **No whitespace-only changes** in files you're not functionally modifying.
- **No new files** (markdown, configs, etc.) unless the user explicitly asks.
- Start app via `Start-Clinic.bat` (port 8080).
- Login: `admin` / `admin`. **NEVER change the admin password.** A previous agent did this and locked the user out.

## Active Work
- **UI Redesign:** See `UI_REDESIGN_PLAN.md` for the 15-phase plan.
- **V1 Roadmap:** See `LAST_PLAN.md` (phases 0–6 done, 7 ~70%).

## Appointments Page — Important
Template: `templates/appointments/vanilla.html`. Keep these script tag IDs unchanged:
- `#appointments-data`, `#patients-data`, `#doctors-data`

## Auto-Update Rule (MANDATORY)
When you add, move, or remove any route, template, service, CSS, or JS file:
1. Update the matching section in `docs/INDEX.md`
2. If it changes user-visible features, add a note to `README.md`
3. Keep `AGENTS.md` §4 (Blueprints & Routes) accurate
4. Update `UI_REDESIGN_PLAN.md` progress tracker if applicable
5. Append to `docs/CHANGELOG.md` — one line: date, what changed, files touched

## Reference Docs
- `AGENTS.md` — full agent behavior rules + complete architecture reference
- `plan_Agents.md` — how to design plans
- `UI_REDESIGN_PLAN.md` — active UI redesign phases and progress
- `LAST_PLAN.md` — V1 product roadmap (phases 0-6 done, 7 in progress)
- `docs/INDEX.md` — complete code-to-feature map
- `docs/CHANGELOG.md` — running log of all AI agent changes
