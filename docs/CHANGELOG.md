# Changelog – Clinic-App-Local

> Running log of all changes made by AI agents. Append one line per task.
> Format: `YYYY-MM-DD | What changed | Files touched`
>
> **Every AI agent MUST append to this file after completing a task.**

---

2025-02-13 | Created comprehensive AGENTS.md (full architecture reference), UI_REDESIGN_PLAN.md (15-phase plan), docs/CHANGELOG.md, updated copilot-instructions.md and LAST_PLAN.md | AGENTS.md, UI_REDESIGN_PLAN.md, docs/CHANGELOG.md, .github/copilot-instructions.md, LAST_PLAN.md
2025-02-13 | Cleaned up ~246 MB of unnecessary files: build/, dist/, .venv-wsl/, .venv3/, __pycache__/, .pytest_cache/, clinic.sqlite, ClinicApp-Source.zip, restore_project.py, docs/old/, docs/legacy-data/, old doc HTML files. Updated .cursorrules and docs/INDEX.md to match. | .cursorrules, docs/INDEX.md, docs/CHANGELOG.md
2026-02-19 | Reverted Phase 4 admin blueprint split (commit 01a4fd8) — restored original monolithic admin_settings.py and settings/index.html template. Reset admin password to admin/admin. Added "NEVER change admin password" safeguards. | AGENTS.md, .github/copilot-instructions.md, docs/CHANGELOG.md
2026-02-19 | Added hybrid validation workflow: Node Playwright smoke tests (isolated temp DB), Run-E2E-Tests.bat, Run-Validation.bat, and documentation updates for post-change verification defaults. | package.json, playwright.config.ts, e2e/tests/helpers.ts, e2e/tests/auth_home_smoke.spec.ts, e2e/tests/appointments_json_smoke.spec.ts, e2e/tests/patient_form_smoke.spec.ts, devtools/playwright_server.py, devtools/run_playwright_smoke.py, Run-E2E-Tests.bat, Run-Validation.bat, .gitignore, README.md, docs/INDEX.md, AGENTS.md, LAST_PLAN.md, .github/copilot-instructions.md, docs/CHANGELOG.md
2026-02-19 | Fixed merge_mode 4x duplicate bug in admin_settings.py (lines ~3055-3062). Added protective agent rules to AGENTS.md and copilot-instructions.md. Added .playwright-mcp/ to .gitignore. | clinic_app/blueprints/admin_settings.py, AGENTS.md, .github/copilot-instructions.md, .gitignore, docs/CHANGELOG.md
