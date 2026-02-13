# LAST PLAN – Simplified, Shippable UI & Branding Plan

> This replaces the older enterprise-heavy plan. It is tailored for a single clinic on Windows, keeps one data folder, preserves Arabic/RTL, and focuses on changes we can actually finish.

## Guiding Principles
- One data root: use the top-level `data/` only. Do not write to `clinic_app/data/` (use only as read-only fixtures if present).
- Keep it simple: no Docker, no Redis, no S3/CDN, no Prometheus/Grafana/Jaeger for this scope.
- Small, safe steps; each phase must be shippable on its own.
- Arabic/RTL must remain first-class everywhere.
- Build on what exists: current CSS variables, admin, PDF services, and batch scripts.

## Phase 0 – Data Root & Housekeeping ✅ DONE
- ~~Confirm all runtime storage (DB, backups, exports, uploads) lives under `data/`.~~
- ~~Audit code for writes to `clinic_app/data/`; treat that path as legacy/fixtures only and avoid new writes there.~~
- ~~Ensure any new helpers read/write via `app.config["DATA_ROOT"]` and `static/uploads/` only.~~
- *Evidence: `_data_root()` in `__init__.py` uses `data/` exclusively; all runtime paths created under `data/`.*

## Phase 1 – Theme & UI Foundation (no DB change) ✅ DONE
- ~~Add `static/css/theme-system.css` that extends existing variables.~~
- ~~Include `theme-system.css` in `_base.html` after `app.css`.~~
- ~~Define a small unified component set using these variables.~~
- ~~Convert key screens: navigation, login, appointments, simple expenses. Keep RTL/Arabic intact.~~
- *Evidence: `static/css/theme-system.css` exists and is loaded in `_base.html`.*

## Phase 2 – Persistent Theme Settings (small DB addition) ✅ DONE
- ~~Add a single `theme_settings` table.~~
- ~~Implement `clinic_app/services/theme_settings.py`.~~
- ~~Load theme variables per request and inject as override.~~
- ~~Alembic migration for this table.~~
- *Evidence: `theme_settings.py` exists with `get_setting`, `set_setting`, and SQL table.*

## Phase 3 – Admin Theme & Arabic Settings Tab ✅ DONE
- ~~Add a Theme tab in admin settings (color, font-size, Arabic toggles).~~
- ~~Backend POST route to validate and store via `theme_settings` service.~~
- *Evidence: Admin settings blueprint + template exist at `admin_settings.py` and `templates/admin/settings/index.html`.*

## Phase 4 – Clinic Branding Assets (logos/backgrounds) ✅ DONE
- ~~Simple local uploads for clinic logos.~~
- ~~Use logo in `_nav.html` and PDF headers.~~
- *Evidence: `data/theme/` has `logo-current.jpeg`, `logo-current.png`, `pdf-logo-current.png`, plus `logos/` and `pdf_logos/` subdirectories.*

## Phase 5 – Arabic/RTL Polish Across the App ~90% DONE
- ~~All core templates have `t(...)` wrapping and Arabic translations.~~
- ~~`dir`/`lang` handling and RTL alignment in nav, forms, tables/lists.~~
- ~~Arabic fonts (Cairo) bundled in `static/fonts/`.~~
- *Evidence: `i18n.py` has 2000+ lines with full `en`/`ar` dictionary; `T()` is globally registered in Jinja; RTL toggling in `_base.html`.*
- **Remaining:** Ongoing string completeness — new features/labels need Arabic entries added to `i18n.py`.

## Phase 6 – PDF Styling Integration ✅ DONE
- ~~Apply theme colors and uploaded logo in existing PDF services.~~
- ~~Arabic reshaping for PDF output.~~
- *Evidence: `pdf_enhanced.py` references `data/theme/` for logos; `fpdf2`, `arabic-reshaper`, `python-bidi` in requirements.txt.*

## Phase 7 – Final Polish & Packaging to .exe ~70% DONE
- ~~PyInstaller spec file exists (`clinic_app.spec`).~~
- ~~Build scripts exist: `Build-Clinic.bat`, `Make-Clinic-Release.bat`, `Make-Clinic-Release-Zip.bat`, `Make-Clinic-Zip.bat`.~~
- ~~Frozen-mode detection in `__init__.py`.~~
- **Remaining:**
  - Create `PACKAGING.md` documenting the build/run process.
  - Update `README.md` with theme/logo/language change instructions.
  - Final UI consistency pass across all major screens.

## Out of Scope / Future Ideas
- CDN/S3, Redis, Prometheus/Grafana/Jaeger, AI/metrics dashboards, Playwright visual regression: keep as future/optional after core delivery.

## Safety & Testing Checklist (per phase)
- Use existing scripts: `Run-Tests.bat` after backend changes; `Start-Clinic.bat` for manual checks.
- No new paths outside `data/` and `static/uploads/`.
- Arabic and English manual verification on key pages each phase.
- Migrations are small and reversible; avoid touching existing tables beyond the new `theme_settings`.

---

## Remaining V1 Items
- **Phase 5:** Add Arabic translations for any new strings introduced after initial i18n pass.
- **Phase 7:** Create `PACKAGING.md`, update `README.md` with theme/logo/language docs, final UI consistency pass.

---

## V2 Ideas (future, not started)
*Placeholder — add ideas here as they come up. Do not start V2 work until V1 remaining items are closed.*

---

## Active UI Redesign (NEW)
A comprehensive 15-phase UI redesign plan has been created. See **`UI_REDESIGN_PLAN.md`** for:
- CSS design system + dark mode
- Modal system + toast notifications
- Arabic search normalization
- Admin settings split (5 pages)
- Dashboard homepage + nav restructure
- Expense consolidation
- Reception tab, data entry tab
- Patient detail redesign
- And more (15 phases total)

This plan supersedes V2 Ideas above — the redesign IS the next major work.
