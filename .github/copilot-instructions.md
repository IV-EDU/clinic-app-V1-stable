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
data/                   ← Runtime data (DB, backups, images) — DO NOT TOUCH
```

## Key Conventions
- Plan first (2–5 bullets), then implement. One feature at a time.
- Reuse helpers in `clinic_app/services/`. Follow existing code style.
- Runtime deps → `requirements.txt`. Dev deps → `requirements.dev.txt`.
- Run tests via `Run-Tests.bat` after backend changes.
- Start app via `Start-Clinic.bat` (port 8080).

## Appointments Page — Important
Template: `templates/appointments/vanilla.html`. Keep these script tag IDs unchanged:
- `#appointments-data`, `#patients-data`, `#doctors-data`

## Auto-Update Rule
When you add, move, or remove any route, template, service, CSS, or JS file:
1. Update the matching section in `docs/INDEX.md`
2. If it changes user-visible features, add a note to `README.md`
3. Keep `AGENTS.md` §4 (Quick Project Index) accurate

## Reference Docs
- `AGENTS.md` — full agent behavior rules
- `plan_Agents.md` — how to design plans
- `LAST_PLAN.md` — V1 product roadmap (phases 0-6 done, 7 in progress)
- `docs/INDEX.md` — complete code-to-feature map
