# Clinic-App-Local - Agent Guide

> **Last Updated:** 2025-02-13
>
> This file is the single source of truth for any AI agent working on this codebase.
> Reading this file should give you enough context to work without reading all source files.

---

## WARNING: Auto-Update Rule (READ FIRST)

**Every AI agent MUST update documentation after making changes. No exceptions.**

When you add, move, or remove any route, template, service, CSS, or JS file:

1. **Update `docs/INDEX.md`** -- add/remove the file in the matching section.
2. **Update this file (`AGENTS.md`)** -- update section 4 (Blueprints) or section 5 (Services) if a blueprint or service is added/removed/changed.
3. **Update `README.md`** if the change affects user-visible features.
4. **Update `LAST_PLAN.md`** if your work completes or advances a phase/bullet.
5. **Update `UI_REDESIGN_PLAN.md`** progress tracker if your work completes or advances a redesign phase.
6. **Append to `docs/CHANGELOG.md`** -- one line: date, what changed, files touched.

This rule applies to **every** AI assistant (Copilot, Cline, Cursor, Claude, or any other tool).
Skipping doc updates creates drift that makes future work harder and wastes user tokens.

**After every task, your completion message MUST include: "Docs updated: [list which files]" or explain why none needed updating.**

---

## 1) User Profile and Context

- **Coding level:** Beginner (not a programmer, learning as they go).
- **Context:** This is a **production system** for a real dental clinic. Downtime means patients cannot be scheduled, records cannot be accessed, and payments cannot be processed.
- **Language:** The clinic operates in Arabic. The app is bilingual (English + Arabic UI). Arabic/RTL is first-class.
- **Platform:** Windows only. The app runs locally via `Start-Clinic.bat` on port 8080. No cloud, no Docker.
- **Preferred help:** Step-by-step, plain-English explanations. Show what changed and why.

When unsure: say what you think the user wants, ask **one** clear question, propose a small, low-risk plan.

---

## 2) Architecture Overview

### Tech Stack
| Layer | Technology | Notes |
|-------|-----------|-------|
| Backend | Flask 3.0.0 | App factory in `clinic_app/__init__.py` |
| Database | SQLite (WAL mode) | Single file `data/app.db`, `busy_timeout=5000`, `foreign_keys=ON` |
| ORM | Custom `SQLAlchemyEngine` | **NOT** Flask-SQLAlchemy. See `clinic_app/extensions.py` |
| Auth | Flask-Login + custom RBAC | `models_rbac.py`: User/Role/Permission with many-to-many |
| Forms | Flask-WTF / WTForms | CSRF protection globally enabled |
| Rate limiting | Flask-Limiter | 60/min POST, in-memory storage |
| i18n | Custom bilingual system | `clinic_app/services/i18n.py` (~2021 lines), `T()` globally in Jinja |
| PDF | fpdf2 + arabic_reshaper + python-bidi | Bilingual receipts with logos |
| Migrations | Alembic | Auto-runs on startup via `services/auto_migrate.py` |
| Packaging | PyInstaller | Windows .exe builds, spec file: `clinic_app.spec` |
| Frontend | Jinja2 templates + vanilla JS | CSS via `app.css` + `theme-system.css`, no frontend framework |
| Theming | CSS variables from DB | `theme_settings` table, auto-contrast, clinic logo/branding |

### Entry Points
- `wsgi.py` -> calls `create_app()` from `clinic_app/__init__.py`
- `Start-Clinic.bat` -> creates `.venv`, installs deps, runs `wsgi.py` on port 8080
- `Run-Tests.bat` -> runs `pytest`
- `Run-Migrations.bat` -> runs Alembic

### App Factory Flow (`create_app()`)
1. Determine data root (`data/` folder)
2. Check for pending DB restore (`restore_pending.json` marker)
3. Configure Flask (secret key, DB URI, locale, doctors, PDF fonts)
4. Register Jinja helpers (`T()` for i18n, `render_page()` for templates)
5. Register UI helpers (theme variable injection per request)
6. Init extensions (SQLAlchemy, CSRF, Limiter)
7. Init Flask-Login
8. Register all blueprints
9. Auto-upgrade DB via Alembic
10. Bootstrap base tables (appointments, receipts, doctor_colors)
11. Backfill missing payment doctors
12. Ensure admin user exists
13. Init security (headers, rate limits)
14. Register CLI commands

---

## 3) Database Schema

All tables live in a single SQLite file: `data/app.db`.

### Core Domain Tables
| Table | Primary Key | Purpose |
|-------|-------------|---------|
| `patients` | `id` (UUID text) | Patient records. Has `short_id` (format: `P######`) used as file number |
| `doctors` | `id` (UUID text) | Doctor list with `doctor_label` and `color` |
| `appointments` | `id` (UUID text) | Scheduled visits. FK to `patients.id` (SET NULL) and `doctors.id` |
| `payments` | `id` (text) | Payment/treatment records. Linked to patient via raw SQL (no FK in ORM) |
| `simple_expenses` | `id` (integer) | Simple expense entries (date, amount, description) |

### Clinical Tables (raw SQL, not ORM)
| Table | Purpose |
|-------|---------|
| `diagnosis` | Tooth-level diagnosis (Palmer notation), per patient |
| `diagnosis_event` | History log of diagnosis changes |
| `medical` | Patient medical notes (problems, allergies, medications) |
| `medical_event` | History log of medical note changes |

### Auth/RBAC Tables (SQLAlchemy ORM in `models_rbac.py`)
| Table | Purpose |
|-------|---------|
| `users` | App users with hashed passwords. FK to `roles` |
| `roles` | Named roles (admin, doctor, reception, etc.) |
| `permissions` | Individual permission codes (30+ codes like `patients:view`, `payments:edit`) |
| `role_permissions` | Join table: role to permission (many-to-many) |

### Support Tables
| Table | Purpose |
|-------|---------|
| `theme_settings` | Key-value store for UI theme (colors, fonts, logos) |
| `doctor_colors` | Per-doctor UI colors for calendar/appointment cards |
| `receipt_sequences` | Auto-incrementing receipt serial numbers |
| `receipts` | Issued receipt metadata (serial, patient, payment, timestamp) |
| `receipt_reprints` | Reprint tracking history |
| `audit_log` | Append-only audit trail (currently payment events only) |
| `audit_snapshots` | Patient state snapshots linked to audit events |
| `import_row_fingerprints` | SHA-256 hashes to prevent duplicate imports |

### Key Data Conventions
- **Money is stored in cents** (integer). Display divides by 100. See `services/payments.py`.
- **IDs are UUIDs** (text) for patients, doctors, appointments, payments.
- **Patient `short_id`** format: `P######` (e.g., `P000001`). Used as file number displayed to users.
- **Patient pages** are managed via `services/patient_pages.py` (page numbers from legacy Excel import).
- **Timestamps**: ISO 8601 for domain data, epoch seconds for audit.

---

## 4) Blueprints and Routes

### Core / Home Dashboard
- **Blueprint:** `clinic_app/blueprints/core/core.py` (489 lines)
- **Template:** `templates/core/index.html`
- **Purpose:** Paginated patient list with search, stats sidebar
- **Key routes:** `/` redirect to `/home`

### Authentication
- **Blueprint:** `clinic_app/blueprints/auth/routes.py`
- **Template:** `templates/auth/login.html`
- **Purpose:** Login/logout, session management

### Patients
- **Blueprint:** `clinic_app/blueprints/patients/routes.py` (1,422 lines)
- **Templates:** `templates/patients/` (new, edit, detail, delete_confirm, duplicate_confirm, quickview, edit_modal, _edit_form_fields)
- **Purpose:** CRUD, merge, CSV export, search API, duplicate detection on add
- **Key routes:** `/patients/new`, `/patients/<pid>`, `/patients/<pid>/edit`, `/patients/<pid>/delete`, `/export/patients.csv`
- **Important:** Duplicate detection runs on add (checks name+phone similarity). The `detail.html` shows payments, treatments, and links to diagnosis/medical/images.

### Payments and Receipts
- **Blueprint:** `clinic_app/blueprints/payments/routes.py` (1,558 lines)
- **Templates:** `templates/payments/` (form, receipt, view/edit/treatment modals, print, _list, _form_fields)
- **Purpose:** Add/edit/delete payments per patient, PDF receipts, treatment plans, child payments
- **Key routes:** `/patients/<pid>/excel-entry` (add), `/patients/<pid>/payments/<pay_id>/edit`, `.../receipt/view`, `.../print`
- **Important:** Doctor must be selected. Money in cents. Child payments linked to parent treatments.

### Appointments
- **Blueprint:** `clinic_app/blueprints/appointments/routes.py` (839 lines)
- **Template:** `templates/appointments/vanilla.html` (the main UI)
- **Purpose:** Scheduling, overlap detection, JSON APIs, server-rendered cards + JS enhancement
- **Key routes:** `/appointments/vanilla` (main), `/api/appointments/save`, `/api/appointments/delete`, `/api/appointments/status`, `/api/patients/search`
- **CRITICAL -- keep these script tag IDs unchanged in vanilla.html:**
  - `<script type="application/json" id="appointments-data">`
  - `<script type="application/json" id="patients-data">`
  - `<script type="application/json" id="doctors-data">`

### Reports
- **Blueprint:** `clinic_app/blueprints/reports/routes.py` (1,296 lines)
- **Templates:** `templates/reports/` (collections, collections_doctors, details, receivables)
- **Purpose:** Daily/monthly/range collection reports, doctor analytics, receivables, CSV export
- **Key routes:** `/collections`, `/collections/doctors`, `/collections/day/<d>`, `/receivables`

### Admin Settings (MONOLITHIC -- planned for split in UI Redesign Phase 4)
- **Blueprint:** `clinic_app/blueprints/admin_settings.py` (4,959 lines)
- **Template:** `templates/admin/settings/index.html` (6,220 lines -- single mega-page, 7 tabs)
- **Purpose:** Users, roles, doctors, theme, logos, data import/export, backup/restore, audit
- **Contains critical logic:**
  - **Import system** (lines ~1880-3500): Excel fingerprinting, 3-tier patient resolution (file number then page+name+phone then create new), SHA-256 dedup, preflight dry-run, auto-backup before import, commit. **Rated 8/10 -- DO NOT REFACTOR.**
  - **Backup** (lines ~3860-3970): SQLite backup API, `restore_pending.json` marker, safety backup before restore.
  - **Audit viewer** (lines ~4400-4959): JSON/CSV export, privacy controls, snapshot viewer.
- **Known bug:** Lines ~3071-3078 have 4x duplicated `merge_mode` fallback check (copy-paste error -- harmless, should be cleaned up).

### Legacy Expenses (over-engineered -- planned for soft-deprecation)
- **Blueprint:** `clinic_app/blueprints/expenses/routes.py` (950 lines)
- **Service:** `clinic_app/services/expense_receipts.py` (1,220 lines)
- **Templates:** `templates/expenses/` (index, new, edit, detail, categories, materials, suppliers, status, receipts)
- **Status:** Has stub functions (edit_supplier, edit_material "not yet implemented"). Default categories are corporate (Travel, Meals) not dental. Do NOT add features to this system.

### Simple Expenses (minimal -- will evolve per UI Redesign Phase E)
- **Blueprint:** `clinic_app/blueprints/simple_expenses.py` (~200 lines)
- **Service:** `clinic_app/services/simple_expenses.py`
- **Templates:** `templates/simple_expenses/` (index, new)
- **Key routes:** `/simple-expenses/`, `/simple-expenses/new`

### Diagnosis / Medical / Images (Palmer / Diag+)
- **Blueprint:** `clinic_app/blueprints/images/images.py` (588 lines, blueprint name: `palmer_plus`)
- **Templates:** `templates/diag_plus/` (diagnosis, medical, images)
- **Purpose:** Tooth-level Palmer chart, medical notes, patient photo management
- **Key routes:** `/patients/<pid>/diagnosis/`, `/patients/<pid>/medical/`, `/patients/<pid>/images/`
- **Storage:** Images in `data/patient_images/`

---

## 5) Services Reference

| File | Purpose | Key Details |
|------|---------|-------------|
| `services/payments.py` | Money formatting, balance calc | `format_money()`, `calculate_remaining()` -- **money in cents** |
| `services/patients.py` | Patient helpers, merge | `merge_patient_records()` -- moves payments, appointments, diagnosis, medical, images. **DO NOT modify merge logic without review.** |
| `services/appointments.py` | Scheduling logic | Overlap detection, grouping, formatting |
| `services/appointments_enhanced.py` | Enhanced appointment helpers | Additional formatting, stats |
| `services/doctor_colors.py` | Doctor lifecycle and colors | CRUD, color management (541 lines) |
| `services/patient_pages.py` | Page number management | Legacy Excel page mapping, admin settings (535 lines) |
| `services/i18n.py` | Bilingual EN/AR translations | `T()` function, 2000+ pairs, `SUPPORTED_LOCALES`. All new strings MUST have entries here. |
| `services/ui.py` | Template rendering | `render_page()` -- **all blueprints use this**, injects theme/locale/user |
| `services/theme_settings.py` | Theme persistence | `get_setting()`, `set_setting()`, CSS variable injection |
| `services/audit.py` | Audit logging | `write_event()`, patient snapshots, sensitive data redaction. Currently covers payment events only. |
| `services/security.py` | Security headers, rate limits | Applied post-request |
| `services/admin_guard.py` | Admin user check | `ensure_admin_exists()` on startup |
| `services/bootstrap.py` | Table creation | Ensures critical tables exist on first run |
| `services/database.py` | DB helpers | Low-level query utilities |
| `services/auto_migrate.py` | Alembic integration | Runs migrations on startup |
| `services/migrations.py` | Migration helpers | Supporting functions |
| `services/data_fixes.py` | One-time fixes | `backfill_missing_payment_doctors()` |
| `services/csrf.py` | CSRF for JSON APIs | Token injection for `fetch()` calls |
| `services/errors.py` | Error handling | Logging, error pages |
| `services/pdf_enhanced.py` | PDF receipts | Bilingual with logos, arabic reshaping |
| `services/import_first_stable.py` | Import preview | Excel preview for data import |
| `services/expense_receipts.py` | Full expense logic | Over-engineered (1,220 lines). Planned for deprecation. |
| `services/expense_receipt_files.py` | Expense file attachments | File upload/download |
| `services/simple_expenses.py` | Simple expense logic | CRUD for date+amount+desc expenses |

---

## 6) Key Patterns and Conventions

### Template Rendering
All blueprints use **`render_page()`** from `services/ui.py` (never raw `render_template()`). This injects theme variables, locale, user context, and shared data into every template.

### i18n / Translations
- Use `T('key')` in Jinja templates and `t('key')` in Python code.
- All display strings MUST have EN/AR entries in `services/i18n.py`.
- **New features MUST add translations** -- the clinic operates in Arabic.
- RTL/LTR is toggled via `dir` attribute on `<html>`, driven by locale cookie.

### Money
- Stored as **integers (cents)**. Display: `format_money(amount_in_cents)` gives `"123.45"`.
- **Never store money as float.** Always divide by 100 for display, multiply by 100 for storage.

### IDs
- Patients, doctors, appointments, payments: **UUID text strings**.
- Patient `short_id`: `P######` format (e.g., `P000001`). This is the "file number".

### CSRF
- All POST requests require CSRF token. Flask-WTF handles form submissions.
- For `fetch()` / JSON APIs: include `X-CSRFToken` header. See `services/csrf.py`.

### Audit Trail
- Append-only `audit_log` table. Currently covers payment events only.
- Sensitive keys in payment metadata are auto-redacted.
- Patient snapshots captured for payment create/update/delete events.

### Theming
- CSS variables stored in `theme_settings` DB table.
- Injected into every page via `services/ui.py` then `services/theme_settings.py`.
- Clinic logo stored in `data/theme/`.

---

## 7) Static Assets

### CSS Files
| File | Purpose |
|------|---------|
| `static/css/app.css` | Main global styles (buttons, cards, grids, forms, tables) |
| `static/css/theme-system.css` | CSS variable foundation, theme overrides |
| `static/css/print-receipts.css` | Print-specific styles for receipts |
| `static/css/expenses.css` | Legacy expense styles |
| `static/css/simple-expenses.css` | Simple expense styles |
| `static/css/expense-file-upload.css` | Expense file upload component |

### JS Files
| File | Purpose |
|------|---------|
| `static/js/patient-form-repeaters.js` | Dynamic form field repeaters |
| `static/js/patient-receipts.js` | Receipt interaction helpers |
| `static/js/status-chip.js` | Status badge/chip component |
| `static/js/expenses.js` | Legacy expense interactions |
| `static/js/expense-file-upload.js` | File upload handling |
| `static/js/simple-expenses.js` | Simple expense interactions |

### Fonts
- `static/fonts/Cairo-Regular.ttf` -- Arabic font
- `static/fonts/DejaVuSans.ttf` -- Unicode fallback (used in PDFs)

---

## 8) Data Directory Structure

All runtime data lives under `data/` -- **NEVER modify directly:**

```
data/
  app.db              <- Main SQLite database
  app.db.bak          <- Backup copy
  patient_images/     <- Patient photos organized by patient ID
  backups/            <- DB backups (SQLite backup API)
  exports/            <- CSV/data exports
  import_reports/     <- Import analysis results
  receipts/           <- Generated receipt files
  audit/              <- Audit log exports
    archive/          <- Archived audit data
  logs/               <- Application logs
  theme/              <- Clinic branding
    logo-current.*    <- Current header logo
    pdf-logo-current.* <- Current PDF logo
    logos/            <- Logo history
    pdf_logos/        <- PDF logo history
```

---

## 9) Planning + Confirmation (always)

- Before any edits: produce a short plan (2-5 bullets).
- Share the plan and **wait for user confirmation** before changing files.
- Stick to one focused goal per task.
- Read `plan_Agents.md` for detailed planning rules.

---

## 10) Debugging Mode

1. Reproduce the issue (if possible) and capture the error/log.
2. Localize the root cause (which file/lines/logic).
3. Propose a minimal, scoped fix and wait for confirmation.
4. Implement the fix, keeping changes as small as possible.
5. Rerun the relevant check/test and report the result.
6. If not fixed, report what changed and the next minimal step.

---

## 11) Hard Safety Rules

### NEVER modify or delete on your own:
- `.git/` -- version control
- `.venv/` or `.venv-wsl/` -- Python environments
- `data/` -- real patient data
- `migrations/` -- DB version history

### Be extra careful with (explain risk + wait for approval):
- Database schema/migrations
- Batch scripts (`Start-Clinic.bat`, `Run-Tests.bat`, `Run-Migrations.bat`)
- Import logic in `admin_settings.py` (lines ~1880-3500) -- rated 8/10, DO NOT refactor
- Backup/restore logic -- uses SQLite backup API + marker-based restore
- Patient merge logic in `services/patients.py`
- Money storage format (cents)

### Red Flags -- STOP and Ask Before Proceeding
- User wants to delete or overwrite database files
- Changes affect authentication, security, or RBAC logic
- A migration could lose or corrupt existing data
- Modifying core Flask configuration (`__init__.py`, `extensions.py`)
- Installing packages that could conflict with existing deps
- Any change touching the `data/` folder contents
- Modifying the import system fingerprinting or patient resolution logic

---

## 12) Workflow for Any Task

1. Start with a short plan (2-5 bullets), wait for confirmation.
2. Read only what is needed.
3. Make small, surgical changes in the relevant blueprint/template.
4. Keep code/docs in sync when user-facing features change.
5. Run tests when backend logic changes (prefer `Run-Tests.bat`).
6. **Update docs** per the Auto-Update Rule (top of this file).

### Context Checklist (before starting work)
**Always check these files first:**
- `UI_REDESIGN_PLAN.md` -- active UI redesign phases and progress
- `LAST_PLAN.md` -- V1 roadmap (phases 0-6 done, 7 ~70%)
- `docs/INDEX.md` -- file-to-feature mapping
- `plan_Agents.md` -- how to structure plans

**Always ask (if not obvious):**
- What page/feature is affected?
- What is the current behavior vs. desired behavior?

---

## 13) Known Issues and Decisions

### Known Bugs
1. `admin_settings.py` lines ~3071-3078: 4x duplicated `merge_mode` fallback check (copy-paste). Harmless but should be cleaned up.
2. Legacy expense system has stub functions for edit_supplier/edit_material ("not yet implemented").

### Architectural Decisions (agreed with user)
- **Import system:** DO NOT refactor. It works (8/10). Only fix the 4x duplicate line.
- **Backup system:** Needs auto-backup rotation + integrity check (planned in UI Redesign Phase 5).
- **Audit system:** Extend to cover merge events, patient/appointment changes (planned in Phase 13).
- **Admin settings:** Will be split into 5 pages (Phase 4).
- **Add Patient:** Will become modal instead of separate page (Phase 9).
- **Theme:** Will simplify from 7 color pickers to 1 primary + auto-derived (Phase 1).
- **Expenses:** Kill full system, evolve simple (Phase E).

### Active Redesign
A comprehensive 15-phase UI redesign is planned. See **`UI_REDESIGN_PLAN.md`** for full details and progress.

---

## 14) Appointments Page Rules (very important)

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

## 15) Expenses Rules

Two expense systems currently exist:
- **Legacy expenses** (`blueprints/expenses/`): Over-engineered, corporate-style. Planned for soft-deprecation.
- **Simple expenses** (`blueprints/simple_expenses.py`): Minimal flow. Will evolve per UI Redesign Phase E.

Rules:
- Do NOT add features to legacy expenses.
- Do NOT remove legacy expenses without user approval.
- Simple expenses is the future.

---

## 16) Requirements and README

- Runtime deps in `requirements.txt`. Dev/test deps in `requirements.dev.txt`.
- Touch only the needed line when adding/removing deps.
- For user-visible changes, add a small note to README.

---

## 17) Running and Testing

- **Preferred (Windows):** `Start-Clinic.bat` (app), `Run-Tests.bat` (tests)
- **Direct:** `.venv\Scripts\python wsgi.py`, `.venv\Scripts\python -m pytest`
- Run tests when backend logic changes.

---

## 18) Coding Style

- Follow existing style; keep functions small and focused.
- Reuse `clinic_app/services/` helpers.
- Use `render_page()` for all template rendering.
- Use `T()` / `t()` for all display strings.
- Store money in cents. Use UUID text for entity IDs.
- Avoid one-letter names; add comments only when necessary.

---

## 19) When Unsure

- Summarize the task in 1-2 sentences.
- Ask one concise clarification question.
- Offer a safe, minimal plan that will not break the app.

---

## 20) Completion Format

After finishing a task, always provide:
1. **What changed** -- one-sentence summary.
2. **Files modified** -- list of files touched.
3. **How to test** -- step-by-step instructions the user can follow.
4. **Side effects** -- anything else that might be affected (or "None").
5. **Docs updated** -- which docs were updated per the Auto-Update Rule, or why none needed updating.

---

## 21) Tests and Dev Tools

### Test Suite (`tests/`)
- **Config:** `tests/conftest.py`
- **~32 test files** covering: core smoke, auth/security, patients, payments, appointments, reports, i18n, database
- Run via `Run-Tests.bat` or `pytest`

### Dev Tools (`devtools/`)
- `test_simple_expenses.py`, `test_expense_system.py` -- expense dev scripts
- `test_duplicates.py` -- duplicate detection testing
- `check_template.py` -- appointment template checker

---

## 22) Reference Files

| File | Purpose |
|------|---------|
| `AGENTS.md` (this file) | Complete architecture + agent behavior rules |
| `UI_REDESIGN_PLAN.md` | Active 15-phase UI redesign plan with progress tracker |
| `LAST_PLAN.md` | V1 product roadmap (phases 0-6 done, 7 ~70%) |
| `plan_Agents.md` | How to structure plans for this project |
| `docs/INDEX.md` | Complete code-to-feature file mapping |
| `docs/CHANGELOG.md` | Running log of all changes made by AI agents |
| `.github/copilot-instructions.md` | Auto-loaded by GitHub Copilot |
| `README.md` | User-facing project overview |
