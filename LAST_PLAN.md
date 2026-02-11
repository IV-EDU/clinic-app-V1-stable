# LAST PLAN – Simplified, Shippable UI & Branding Plan

> This replaces the older enterprise-heavy plan. It is tailored for a single clinic on Windows, keeps one data folder, preserves Arabic/RTL, and focuses on changes we can actually finish.

## Guiding Principles
- One data root: use the top-level `data/` only. Do not write to `clinic_app/data/` (use only as read-only fixtures if present).
- Keep it simple: no Docker, no Redis, no S3/CDN, no Prometheus/Grafana/Jaeger for this scope.
- Small, safe steps; each phase must be shippable on its own.
- Arabic/RTL must remain first-class everywhere.
- Build on what exists: current CSS variables, admin, PDF services, and batch scripts.

## Phase 0 – Data Root & Housekeeping
- Confirm all runtime storage (DB, backups, exports, uploads) lives under `data/`.
- Audit code for writes to `clinic_app/data/`; treat that path as legacy/fixtures only and avoid new writes there.
- Ensure any new helpers read/write via `app.config["DATA_ROOT"]` and `static/uploads/` only.

## Phase 1 – Theme & UI Foundation (no DB change)
- Add `static/css/theme-system.css` that extends existing variables (`--ink`, `--muted`, `--border`, `--bg`, `--card`) with a minimal set: `--primary-color`, `--accent-color`, `--bg-primary`, `--text-primary`, etc.
- Include `theme-system.css` in `_base.html` after `app.css`.
- Define a small unified component set (buttons/cards/form controls/chips) using these variables.
- Convert a few key screens first: navigation, login, appointments, simple expenses. Keep RTL/Arabic intact.

## Phase 2 – Persistent Theme Settings (small DB addition)
- Add a single `theme_settings` table (under the main SQLite DB in `data/`), storing `id`, `key`, `value`, `category`, `updated_at`.
- Implement `clinic_app/services/theme_settings.py` using the existing DB helper style (no new ORM). Functions: `get_setting`, `set_setting`, `get_theme_variables`.
- Load theme variables per request and inject as a small `<style>` or `data-theme="custom"` override.
- Alembic migration: one migration for this table, with a clear rollback (drop only this table).

## Phase 3 – Admin Theme & Arabic Settings Tab
- Add a Theme tab in admin settings with:
  - Primary color, accent/secondary color.
  - Base font-size slider (for readability).
  - Arabic defaults: default language toggle; optional “larger Arabic text” toggle that bumps Arabic font-size/line-height via variables.
- Backend POST route to validate and store via `theme_settings` service.

## Phase 4 – Clinic Branding Assets (logos/backgrounds)
- Simple local uploads to `static/uploads/…` (e.g., `uploads/logos/clinic.png`, `uploads/backgrounds/login.jpg`).
- Minimal `asset_manager.py`:
  - `save_logo(file_storage) -> relative_path`
  - `get_logo_url(kind)`
  - Basic type/size validation (Pillow optional if comfortable).
- Use logo in `_nav.html` and PDF headers; keep backgrounds optional.

## Phase 5 – Arabic/RTL Polish Across the App
- Review core templates (auth, home, patients, appointments, payments, receipts, expenses/simple expenses) for:
  - All user-facing strings wrapped with `t(...)` and translated.
  - Proper `dir`/`lang` handling and RTL alignment in nav, forms, tables/lists.
  - Arabic font sizing/weights for readability (Tajawal/Noto already in `app.css`).
- Tests: extend existing i18n tests; manual checks in Arabic and English for main flows.

## Phase 6 – PDF Styling Integration
- Apply theme colors and uploaded logo in existing PDF services (receipts/payments).
- Keep it minimal: no separate `pdf_templates` table yet; just color + logo + optional watermark toggle.
- Add/extend smoke tests for PDFs where feasible.

## Phase 7 – Final Polish & Packaging to .exe
- UI polish: ensure unified styles across major screens; consistent flash messages, buttons, headings.
- Documentation: update `README.md` with how to change theme colors, upload logos, switch default language.
- Packaging (Windows):
  - Plan a small PyInstaller wrapper that starts the Flask app (uses existing venv) and optionally opens the browser.
  - Add a simple `PACKAGING.md` with the command to build/run the `.exe` wrapper.

## Out of Scope / Future Ideas
- CDN/S3, Redis, Prometheus/Grafana/Jaeger, AI/metrics dashboards, Playwright visual regression: keep as future/optional after core delivery.

## Safety & Testing Checklist (per phase)
- Use existing scripts: `Run-Tests.bat` after backend changes; `Start-Clinic.bat` for manual checks.
- No new paths outside `data/` and `static/uploads/`.
- Arabic and English manual verification on key pages each phase.
- Migrations are small and reversible; avoid touching existing tables beyond the new `theme_settings`.
