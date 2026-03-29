# System Map

> Purpose: give future AI chats and new contributors a fast, practical map of the whole program:
> what it is, where things live, how data flows, and how to find the right files without pretending to
> understand the entire app from memory.

This file is not a replacement for code inspection.
It is the bridge between startup instructions and targeted file reading.

---

## 1) What This App Is

- Flask + SQLite dental clinic app
- real clinic data, so stability matters more than speed
- Windows-first workflow
- main entry: `wsgi.py` -> `clinic_app/__init__.py:create_app()`
- main runtime data root: `data/`

Core product areas:
- dashboard / home
- patients and patient file
- payments and treatments
- appointments
- expenses
- reports
- admin / RBAC / theme
- diagnosis / images
- receptionist draft-review-approve workflow

---

## 2) How To Understand The App Safely

No AI should assume it knows the whole app after reading one startup file.

Use this order when whole-app context matters:

1. Read `AGENTS.md`
2. Read `MEMORY.md`
3. Read `KNOWN_ISSUES.md`
4. Read `LAST_PLAN.md`
5. Read `docs/AGENT_HANDOFF.md`
6. Read this file: `docs/SYSTEM_MAP.md`
7. Read `docs/INDEX.md`
8. Only then open the exact blueprint/template/service files for the feature you are touching

If the task is about UI:
- also read `DESIGN_BRIEF.md`

If the task is about Reception:
- also read:
  - `docs/RECEPTION_DESK_SPEC.md`
  - `docs/RECEPTION_DESK_IMPLEMENTATION_CONTRACT.md`
  - `docs/RECEPTION_DESK_PHASES.md`

If behavior is unclear after reading docs:
- inspect the actual route, template, service, and tests
- use Playwright if needed to confirm live UI behavior

---

## 3) Core Mental Model

Think of the app in layers:

### Layer A: Request / route layer

Where the browser goes first:
- blueprint routes under `clinic_app/blueprints/`

This tells you:
- URL
- permission guard
- what template is rendered
- what service/helper is called

### Layer B: Template / UI layer

Where most visible behavior lives:
- `templates/`
- `static/css/`
- `static/js/`

This tells you:
- page structure
- visible controls
- client-side assumptions
- dark mode / RTL / layout dependencies

### Layer C: Service / logic layer

Where shared behavior should usually live:
- `clinic_app/services/`

This tells you:
- money math
- patient normalization
- appointment logic
- RBAC/security helpers
- Reception draft storage / posting helpers

### Layer D: Data / model layer

Where persistence rules live:
- `clinic_app/models.py`
- `clinic_app/models_rbac.py`
- raw sqlite helpers in `clinic_app/services/database.py`
- runtime DB in `data/app.db`

This tells you:
- what is actually stored
- what is a real table vs an app convention
- what can break data integrity

---

## 4) The Most Important Structural Truths

These are the high-value facts future chats must know early.

### Payments and treatments are coupled

There is no separate treatments table.

- a treatment is a parent row in `payments`
- child payment rows attach by `parent_payment_id`
- many screens depend on correct `remaining_cents` on the parent row

Files to know:
- `clinic_app/blueprints/payments/routes.py`
- `clinic_app/services/payments.py`
- `templates/payments/_list.html`

### Reception is a staging workflow, not live editing

Reception does not edit live patient/payment/treatment rows directly.

- drafts are stored separately
- manager/admin reviews
- live posting happens only on approval

Files to know:
- `clinic_app/blueprints/reception/routes.py`
- `clinic_app/services/reception_entries.py`
- `clinic_app/services/reception_bootstrap.py`
- `docs/RECEPTION_DESK_*`

### UI is mixed across templates and JS

Some pages are cleanly server-rendered.
Some have important embedded JS and page-specific behavior.

Highest-risk examples:
- `templates/appointments/vanilla.html`
- `templates/admin/settings/index.html`
- `templates/payments/_list.html`
- `templates/diag_plus/*`

### RBAC and security are real risk areas

Do not casually change:
- `clinic_app/auth.py`
- `clinic_app/services/security.py`
- `clinic_app/models_rbac.py`
- `clinic_app/blueprints/admin_settings.py`

### Diagnosis / images is semi-separate

`diag_plus` uses its own styling and interaction patterns.
It is not yet as aligned with the main shell as the rest of the app.

---

## 5) Fast File-Finding Guide

When a task is about...

### Dashboard / patient list

Start with:
- `clinic_app/blueprints/core/core.py`
- `templates/core/index.html`
- `templates/core/patients_list.html`

### Patient file / patient profile

Start with:
- `clinic_app/blueprints/patients/routes.py`
- `templates/patients/detail.html`
- `templates/patients/edit.html`
- `clinic_app/services/patients.py`

### Payments / treatments / receipts

Start with:
- `clinic_app/blueprints/payments/routes.py`
- `templates/payments/_list.html`
- `clinic_app/services/payments.py`

### Appointments

Start with:
- `clinic_app/blueprints/appointments/routes.py`
- `clinic_app/services/appointments.py`
- `templates/appointments/vanilla.html`

### Reception workflow

Start with:
- `clinic_app/blueprints/reception/routes.py`
- `clinic_app/services/reception_entries.py`
- `templates/reception/`
- `docs/RECEPTION_DESK_*`

### Admin / theme / users / roles

Start with:
- `clinic_app/blueprints/admin_settings.py`
- `templates/admin/settings/index.html`
- `clinic_app/services/theme_settings.py`
- `clinic_app/models_rbac.py`

### Expenses

Start with:
- legacy:
  - `clinic_app/blueprints/expenses/routes.py`
  - `templates/expenses/`
  - `static/css/expenses.css`
  - `static/js/expenses.js`
- simple:
  - `clinic_app/blueprints/simple_expenses.py`
  - `templates/simple_expenses/`

### Diagnosis / images

Start with:
- `clinic_app/blueprints/images/images.py`
- `templates/diag_plus/`
- `static/diag_plus/style.css`

---

## 6) How To Read A Feature Correctly

For any non-trivial feature, do not read just one file.

Use this chain:

1. route
2. template
3. service/helper
4. related tests
5. CSS/JS if UI behavior matters

Example:

If the task is “change the patient payment flow,” do not stop at:
- `templates/payments/_list.html`

Also inspect:
- `clinic_app/blueprints/payments/routes.py`
- `clinic_app/services/payments.py`
- related payment tests under `tests/`

---

## 7) What Future Chats Must Not Assume

Do not assume:
- a page’s template is the whole feature
- a route name tells the whole story
- a clean UI change is safe without checking services or JS
- a model “already knows” the app after reading startup docs
- payments/treatments behave like a normal separate-table design
- Reception is allowed to touch live records directly

---

## 8) When To Use Playwright Or Figma

Use Playwright when:
- you need to see what the current UI actually does
- you need to verify a form flow, modal, or dynamic page behavior
- the code is too mixed to trust template reading alone

Use Figma MCP when:
- you need a serious UI direction
- you want design capture, reference, or design-to-code help
- you want to compare the current app against a proposed better surface

Do not use either as a substitute for reading the route/service files when logic is involved.

---

## 9) What This File Solves

This file does not make future AIs “fully know” the app.

It does make them much better at:
- getting oriented quickly
- knowing where to look first
- not confusing UI files with business logic
- not missing the big structural traps
- giving more grounded answers with less fake confidence

That is the realistic goal.
