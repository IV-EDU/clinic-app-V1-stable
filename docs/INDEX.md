# Clinic-App-Local – Code & Feature Index

High-level map of the main features and where their code lives.

Whenever you add, move, or remove routes, templates, services, or CSS/JS, update this index in the same task.

---

## 1) Core Application

- **Entry points**
  - App factory: `clinic_app/__init__.py`
  - WSGI entry: `wsgi.py`
  - Alternate app entry (for WSGI servers): `clinic_app/app.py`
  - CLI commands: `clinic_app/cli.py`

- **Configuration / extensions**
  - Flask extensions (DB, CSRF, etc.): `clinic_app/extensions.py`
  - Authentication helpers / login manager: `clinic_app/auth.py`
  - UI helpers (render_page, theme overrides): `clinic_app/services/ui.py`
  - i18n / Arabic support: `clinic_app/services/i18n.py`
  - Theme settings storage: `clinic_app/services/theme_settings.py`
  - Security / RBAC: `clinic_app/services/security.py`, `clinic_app/models_rbac.py`
  - Main database models: `clinic_app/models.py`
  - Blueprint registration orchestrator: `clinic_app/blueprints/__init__.py`

---

## 2) Core Home / Dashboard

- **Blueprint**
  - `clinic_app/blueprints/core/core.py` (endpoint `core.index`)

- **Templates**
  - Dashboard: `templates/core/index.html`
  - Base layout: `templates/_base.html`
  - Navigation bar: `templates/_nav.html`
  - Flash messages: `templates/_flash.html`
  - Shared macros: `templates/_macros.html`

- **Styling**
  - Global styles and components: `static/css/app.css`
  - Theme tokens and utilities: `static/css/theme-system.css`

- **Key routes**
  - `/` → `core.index` (main dashboard, uses patients list and today’s stats)

---

## 3) Authentication

- **Blueprint**
  - `clinic_app/blueprints/auth/routes.py`

- **Templates**
  - Login page: `templates/auth/login.html`

- **Forms**
  - `clinic_app/forms/auth.py`

---

## 4) Patients

- **Blueprint**
  - `clinic_app/blueprints/patients/routes.py`

- **Templates**
  - New patient: `templates/patients/new.html`
  - Edit patient: `templates/patients/edit.html`
  - Patient detail (file + payments): `templates/patients/detail.html`
  - Delete confirm: `templates/patients/delete_confirm.html`
  - Duplicate confirm: `templates/patients/duplicate_confirm.html`
  - Print receipt modal: `templates/patients/print_receipt_modal.html`
  - Quick-view modal fragment: `templates/patients/quickview_fragment.html`
  - Edit modal fragment: `templates/patients/edit_modal_fragment.html`
  - Shared form fields partial: `templates/patients/_edit_form_fields.html`

- **Services**
  - Patient helpers / IDs: `clinic_app/services/patients.py`
  - Payments helpers (balances, money formatting): `clinic_app/services/payments.py`

- **Related styling**
  - Global card/grid/button styles: `static/css/app.css`

- **Related tests**
  - Core dashboard and index tests: `tests/`

- **Key routes**
  - `/patients/new` → `patients.new_patient`
  - `/patients/<pid>` → `patients.patient_detail`
  - `/patients/<pid>/quickview` → `patients.patient_quickview` (HTML fragment for admin quick-view modals)
  - `/patients/<pid>/edit` → `patients.edit_patient`
  - `/patients/<pid>/delete` (GET/POST) → delete confirm + delete
  - `/export/patients.csv` → `patients.export_patients_csv`

---

## 5) Payments & Receipts (Per-Patient)

- **Blueprint**
  - `clinic_app/blueprints/payments/routes.py`

- **Templates**
  - Payment form: `templates/payments/form.html`
  - Payment delete confirm: `templates/payments/delete_confirm.html`
  - Per-payment receipt view: `templates/payments/receipt.html`
  - Payment view modal fragment: `templates/payments/view_receipt_modal_fragment.html`
  - Payment list (embedded in patient detail): `templates/payments/_list.html`
  - Payment form modal fragment: `templates/payments/form_modal_fragment.html`
  - Edit payment modal fragment: `templates/payments/edit_payment_modal_fragment.html`
  - Treatment form modal fragment: `templates/payments/treatment_form_modal_fragment.html`
  - View treatment modal fragment: `templates/payments/view_treatment_modal_fragment.html`
  - Print treatment modal fragment: `templates/payments/print_treatment_modal_fragment.html`
  - Treatment summary print: `templates/payments/treatment_summary_print.html`
  - Shared form fields partial: `templates/payments/_form_fields.html`

- **Services**
  - Payment calculations & validation: `clinic_app/services/payments.py`
  - PDF generation for payments: `clinic_app/services/pdf_enhanced.py`

- **Styling**
  - Global styles + print styles: `static/css/app.css`, `static/css/print-receipts.css`
  - Shared JS helpers: `static/js/patient-receipts.js`, `static/js/status-chip.js`

- **Key routes (per patient)**
  - `/patients/<pid>/excel-entry` (GET/POST) → add payment for a patient
  - `/patients/<pid>/payments/<pay_id>/edit` (GET/POST) → edit payment
  - `/patients/<pid>/payments/<pay_id>/delete` (GET/POST) → delete payment
  - `/patients/<pid>/payments/<pay_id>/receipt/view` → HTML receipt view
  - `/patients/<pid>/payments/<pay_id>/view-modal` → modal fragment used by the patient detail “View receipt” modal
  - `/patients/<pid>/payments/<pay_id>/print` → PDF receipt download/print

---

## 6) Appointments (Modern UI)

- **Blueprint**
  - `clinic_app/blueprints/appointments/routes.py`

- **Templates**
  - Main appointments UI: `templates/appointments/vanilla.html`
  - New appointment: `templates/appointments/new.html`

- **Services**
  - Appointment logic: `clinic_app/services/appointments.py`
  - Enhanced helpers: `clinic_app/services/appointments_enhanced.py`

- **Important notes**
  - `appointments_vanilla` renders grouped appointment cards server-side via `render_page()`, and `templates/appointments/vanilla.html` contains the layout and JS enhancements (filters, search, modals).
  - UI-only changes stay in the template; data and API changes go in the blueprint/services and must be kept in sync with the JS used on this page.

- **Key routes**
  - `/appointments` → `appointments.index` (redirects to vanilla view)
  - `/appointments/vanilla` → `appointments.vanilla` (main modern appointments UI)
  - `/appointments/table` → `appointments.table` (legacy redirect to vanilla)
  - `/api/appointments/save` → `appointments.api_save_appointment` (create/update)
  - `/api/appointments/delete` → `appointments.api_delete_appointment`
  - `/api/appointments/status` → `appointments.api_update_status`
  - `/api/patients/search` → `appointments.api_patients_search` (patient autocomplete)

---

## 7) Legacy Expenses

- **Blueprint**
  - `clinic_app/blueprints/expenses/routes.py`
  - File upload helper: `clinic_app/blueprints/expenses/file_upload.py`

- **Templates**
  - Base: `templates/expenses/base.html`
  - Main index/list: `templates/expenses/index.html`
  - New/edit/detail: `templates/expenses/new.html`, `templates/expenses/edit.html`, `templates/expenses/detail.html`, `templates/expenses/detail_enhanced.html`
  - Receipt file management: `templates/expenses/receipt_files.html`
  - Categories, materials, suppliers, status, receipts: `templates/expenses/*.html`
    - Categories: `templates/expenses/categories.html`
    - Materials: `templates/expenses/materials.html`, `templates/expenses/material_form.html`
    - Suppliers: `templates/expenses/suppliers.html`, `templates/expenses/supplier_form.html`
    - Status: `templates/expenses/status.html`

- **Forms**
  - Expense WTForms: `clinic_app/forms/expenses.py`

- **Services**
  - Expense receipts & files: `clinic_app/services/expense_receipts.py`, `clinic_app/services/expense_receipt_files.py`

- **Styling & scripts**
  - Styles: `static/css/expenses.css`, `static/css/expense-file-upload.css`
  - JS: `static/js/expenses.js`, `static/js/expense-file-upload.js`

- **Key routes**
  - `/expenses` (index) + related detail/edit/new routes in `expenses/routes.py`

---

## 8) Simple Expenses (Minimal Flow)

- **Blueprint**
  - `clinic_app/blueprints/simple_expenses.py`

- **Templates**
  - Base: `templates/simple_expenses/base.html`
  - Dashboard/index: `templates/simple_expenses/index.html`
  - New expense: `templates/simple_expenses/new.html`

- **Services**
  - Simple expenses logic: `clinic_app/services/simple_expenses.py`
  - WTForms: `clinic_app/forms/simple_expenses.py`

- **Styling & scripts**
  - Styles: `static/css/simple-expenses.css`
  - JS: `static/js/simple-expenses.js`

- **Tests**
  - `devtools/test_simple_expenses.py` (dev script)
  - Related tests under `tests/`

- **Key routes**
  - `/simple-expenses/` → `simple_expenses.index`
  - `/simple-expenses/new` → `simple_expenses.new_expense`

---

## 9) Diagnosis / Medical / Images (Palmer / Diag+)

- **Blueprint**
  - `clinic_app/blueprints/images/images.py` (Blueprint name: `palmer_plus`)

- **Templates**
  - Tooth diagnosis: `templates/diag_plus/diagnosis.html`
  - Medical notes: `templates/diag_plus/medical.html`
  - Patient images: `templates/diag_plus/images.html`

- **Styling**
  - Shared styles: `static/diag_plus/style.css`

- **Storage**
  - Uses the same SQLite DB as the rest of the app (`PALMER_PLUS_DB` config).
  - Patient images stored under `data/patient_images/`.

- **Key routes (under `/patients/<pid>` prefix)**
  - `/patients/<pid>/` → `palmer_plus.index` (redirect to diagnosis)
  - `/patients/<pid>/diagnosis/` → `palmer_plus.diag_page`
  - `/patients/<pid>/medical/` → `palmer_plus.med_page`
  - `/patients/<pid>/images/` → `palmer_plus.images_page`

---

## 10) Reports

- **Blueprint**
  - `clinic_app/blueprints/reports/routes.py`

- **Templates**
  - Collections overview: `templates/reports/collections.html`
  - Collections by doctor: `templates/reports/collections_doctors.html`
  - Collections details: `templates/reports/details.html`
  - Receivables (patients who still owe): `templates/reports/receivables.html`

- **Key routes**
  - `/collections` → `reports.collections`
  - `/collections/doctors` → `reports.collections_doctors`
  - `/collections/day/<d>` → `reports.collections_day`
  - `/collections/month/<m>` → `reports.collections_month`
  - `/collections/range` → `reports.collections_range`
  - `/receivables` → `reports.receivables`

---

## 11) Admin / Settings / Doctor Colors / Theme

- **Blueprint**
  - `clinic_app/blueprints/admin_settings.py`

- **Templates**
- Admin settings UI (users, roles, doctor colors, theme, data import/export): `templates/admin/settings/index.html`
  - Role create/edit form: `templates/admin/role_form.html`
  - User create/edit form: `templates/admin/user_form.html`

- **Services**
  - Doctor colors: `clinic_app/services/doctor_colors.py`
  - Theme settings: `clinic_app/services/theme_settings.py`
  - Admin guard: `clinic_app/services/admin_guard.py`
  - Data import preview helpers: `clinic_app/services/import_first_stable.py`

- **Key routes**
  - `/admin/settings` → `admin_settings.index`
  - `/admin/settings/data-import/first-stable/preview` → `admin_settings.preview_first_stable_import` (upload preview only)
  - `/admin/settings/data-export/payments.csv` → `admin_settings.export_payments_csv`

---

## 12) Shared Services (Misc)

- **Database & migrations**
  - DB helper: `clinic_app/services/database.py`
  - Auto-migrate: `clinic_app/services/auto_migrate.py`
  - Migrations helpers: `clinic_app/services/migrations.py`

- **Security & auth**
  - Security helpers: `clinic_app/services/security.py`
  - Admin guard: `clinic_app/services/admin_guard.py`

- **Audit & errors**
  - Audit logging: `clinic_app/services/audit.py`
  - Error logging: `clinic_app/services/errors.py`

- **Startup & data integrity**
  - Bootstrap (creates critical tables on first run): `clinic_app/services/bootstrap.py`
  - CSRF for JSON APIs: `clinic_app/services/csrf.py`
  - Startup data fixes (backfills missing doctor_id): `clinic_app/services/data_fixes.py`

- **Patient helpers**
  - Patient page-number mapping: `clinic_app/services/patient_pages.py`

---

## 13) Tests & Dev Tools

- **Test suite** (`tests/`)
  - Config: `tests/conftest.py`
  - Core / smoke: `test_core_smoke.py`, `test_wiring_smoke.py`, `test_modular_layout.py`, `test_core_backup_and_back.py`, `test_core_helper_migration.py`, `test_core_payments_list.py`, `test_home_sorting.py`
  - Auth / security: `test_auth_bootstrap.py`, `test_bypass_csrf.py`, `test_security_features.py`, `test_admin_csrf_diagnostic.py`, `test_admin_roles.py`, `test_admin_users.py`
  - Patients: `test_medical_save.py`, `test_import_dates.py`, `test_diag_set.py`
  - Payments: `test_add_payment_route.py`, `test_payments_delete_treatment_cascade.py`, `test_payments_modal_validation_doctor_required.py`, `test_payments_overall_remaining_grouped.py`, `test_payments_remove_initial_keeps_children.py`, `test_admin_audit_payments.py`
  - Appointments: `test_vanilla.py`, `test_vanilla_route.py`, `test_appointments_receipts.py`
  - Reports: `test_reports_pagination.py`
  - i18n: `test_i18n_toggle.py`
  - Database: `test_database_service.py`
  - Print / receipts: `test_print_receipts.py`

- **Dev tools** (`devtools/`)
  - Simple expenses dev script: `devtools/test_simple_expenses.py`
  - Expense system dev script: `devtools/test_expense_system.py`
  - Duplicate detection dev script: `devtools/test_duplicates.py`
  - Appointment template checker: `devtools/check_template.py`
  - Historical docs: `docs/appointments template.html`, `docs/appointments_template_source.html`, `docs/old/`

---

## 14) Data & Storage

- **Active data root**
  - All runtime data (DB, backups, exports, images, receipts) lives under: `data/`
  - Main DB: `data/app.db`
  - Patient images: `data/patient_images/`
  - Receipts: `data/receipts/`
  - Backups/exports/logs: under `data/` subfolders.

- **Legacy data**
  - Archived previous app DB and images: `docs/legacy-data/clinic_app_data/`
  - These are kept only for reference; the app should not write to `clinic_app/data/` anymore.

---

## 15) Static Assets Detail

- **JavaScript**
  - Patient form repeaters: `static/js/patient-form-repeaters.js`
  - Patient receipts: `static/js/patient-receipts.js`
  - Status chip: `static/js/status-chip.js`
  - Expenses: `static/js/expenses.js`, `static/js/expense-file-upload.js`
  - Simple expenses: `static/js/simple-expenses.js`

- **Fonts** (used by PDF generation)
  - Arabic font: `static/fonts/Cairo-Regular.ttf`
  - Unicode font: `static/fonts/DejaVuSans.ttf`

- **Diag+**
  - Palmer/Diag+ styles: `static/diag_plus/style.css`

---

## 16) Root-Level Files & Scripts

- **Entry / config**
  - App entry: `wsgi.py`
  - Alembic config: `alembic.ini`
  - PyInstaller spec: `clinic_app.spec`
  - Dependencies: `requirements.txt` (runtime), `requirements.dev.txt` (dev/test)
  - Git ignore: `.gitignore`
  - Cline ignore: `.clineignore`
  - Project restore helper: `restore_project.py`

- **Batch scripts (Windows)**
  - Start app: `Start-Clinic.bat` (port 8080)
  - Start preview: `Start-Clinic-Preview.bat`
  - Run tests: `Run-Tests.bat`
  - Run migrations: `Run-Migrations.bat`
  - Build exe: `Build-Clinic.bat`
  - Release packaging: `Make-Clinic-Release.bat`, `Make-Clinic-Release-Zip.bat`, `Make-Clinic-Zip.bat`

- **Documentation**
  - Agent rules: `AGENTS.md`
  - Planning guide: `plan_Agents.md`
  - V1 roadmap: `LAST_PLAN.md`
  - Project overview: `README.md`
  - Code index (this file): `docs/INDEX.md`
  - Copilot auto-instructions: `.github/copilot-instructions.md`

---

## 17) When Updating This Index

- If you:
  - Add a new feature/page, or
  - Add/move/remove a blueprint, template, service, or CSS/JS file,
  - Change where data is stored,
- Then:
  - Update the relevant section above to keep this index accurate.
  - Keep descriptions short and focused (1–2 lines per bullet).

Use this file as a quick map so future work stays organized and easy to navigate.
