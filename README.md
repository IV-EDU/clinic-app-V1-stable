==================================================
Clinic App (Local) – README
==================================================

This is a Flask-based clinic management app designed to run locally on Windows.

It includes:
- Appointments
- Patients
- Receipts and payments
- Expenses
- Reports
- Admin / roles / users (includes data import/export)

This folder "Clinic-App-Local" is the main project folder.

--------------------------------------------------
1. How to run the app on Windows
--------------------------------------------------

First time:

1. Install Python 3.12 (or a compatible 3.x) on Windows.
2. Put this project folder somewhere, for example:
   C:\Clinic-App-Local
3. In that folder, double-click:
   Start-Clinic.bat

The script will:
- Create a virtual environment (.venv) the first time
- Install dependencies from requirements.txt
- Run the app via wsgi.py on port 8080

Next times:

1. Open the Clinic-App-Local folder.
2. Double-click Start-Clinic.bat again.
3. When the console says the server is running, open your browser and go to:

   http://127.0.0.1:8080/

Then log in with your clinic user.

Safe Excel/CSV preview and export:
- Admin → Settings → Data import can analyze an uploaded file and show a preview (no database changes).
- Preview mode is a developer tool and is not intended for clinic builds.
- Admin → Settings → Data import includes an “Export all payments (CSV)” button for clinic-wide export.

--------------------------------------------------
2. Project structure (short version)
--------------------------------------------------

You are in the folder: Clinic-App-Local.

Important locations:

- clinic_app/      → main Python backend code
  - clinic_app/blueprints/  → routes / views / APIs, grouped by feature
    - appointments/         → appointments-related routes and APIs
    - patients/, payments/, receipts/, reports/, expenses/, admin_*, etc.
  - clinic_app/services/    → shared logic (database, appointments, security, helpers)
  - clinic_app/extensions.py → Flask extensions (DB, login, limiter, etc.)

- templates/      → Jinja2 HTML templates
  - _base.html            → main layout
  - _nav.html             → top navigation bar
  - appointments/vanilla.html → modern appointments UI (Tailwind + JavaScript)

- static/         → CSS, JS, images
- tests/          → pytest tests for the project
- data/           → local database files and data (real clinic data – important)

Root-level important files:

- wsgi.py              → entry point for the app
- Start-Clinic.bat     → run the app on Windows
- Run-Tests.bat        → run tests on Windows
- Run-Migrations.bat   → run database migrations
- requirements.txt     → runtime Python dependencies
- requirements.dev.txt → dev/test dependencies
- README.md            → this file

--------------------------------------------------
3. Appointments page (the "fancy" UI)
--------------------------------------------------

The main appointments UI lives here:

Frontend:
- Template file:
  templates/appointments/vanilla.html

Backend:
- Route module:
  clinic_app/blueprints/appointments/routes.py
- Function (usually):
  appointments_vanilla()

How it works (current design):

1. The backend route `appointments_vanilla()` loads appointments, doctors, and patients from the database using the SQLAlchemy models and helpers in `clinic_app/services/appointments.py`.
2. It groups and formats those appointments on the server and renders `templates/appointments/vanilla.html` via the shared `render_page()` helper, so most of the cards and layout are already in the HTML when the browser receives the page.
3. The JavaScript inside `templates/appointments/vanilla.html` then:
   - Enhances the filters (date range, doctor, search term)
   - Wires up the “new / edit appointment” modal
   - Calls backend JSON APIs to save, update status, or delete appointments
   - Provides live patient search for the appointment form

If the appointments page is broken, it usually means:
- The HTML structure or IDs that the JavaScript expects have been changed in the template, or
- One of the JSON APIs under `/api/appointments/...` or `/api/patients/search` is returning an unexpected format or error.

--------------------------------------------------
4. Running tests
--------------------------------------------------

To run tests on Windows:

Option 1: Double-click
- Run-Tests.bat

Option 2: From a terminal in the project folder, with the virtual environment active:

- .venv\Scripts\python -m pytest

All tests live under:
- tests/

--------------------------------------------------
5. Requirements
--------------------------------------------------

Dependencies are listed in:

- requirements.txt          → main runtime dependencies
- requirements.dev.txt      → dev/test tools (like pytest, etc.)

Inside the virtual environment you can install them manually with:

- pip install -r requirements.txt
- pip install -r requirements.dev.txt

--------------------------------------------------
6. Payments & doctor selection
--------------------------------------------------

- When adding or editing a payment you must choose a doctor from the dropdown (the form will not submit until one is selected).
- Clinics that rely on the generic “Any Doctor” entry can still pick it explicitly from the same list.
- Payment cards and PDF receipts now display the selected doctor for clearer accounting.

--------------------------------------------------
7. Clinic logo (header branding)
--------------------------------------------------

- You can upload a clinic logo from **Admin → Settings → Theme**.
- Supported files: PNG or JPG, max ~2 MB. The file is stored under your `data/theme/` folder.
- If a logo is configured, it appears in the top header; otherwise the app title text is shown.

--------------------------------------------------
8. Reports pagination
--------------------------------------------------

- Collections, Collections by doctor, and Receivables now use page-based tables (same idea as Home).
- Use the page controls under each table to move between pages while keeping active filters.
- Default size is 50 rows per page.

--------------------------------------------------
9. Notes for AI assistants (Cline, ChatGPT, etc.)
--------------------------------------------------

- The user is NOT a coder. Use simple language and small, safe changes.
- Always start by reading `AGENTS.md` in the project root. It describes:
  - How to behave and reply.
  - Safety rules (what not to touch).
  - When to consult `LAST_PLAN.md`, `plan_Agents.md`, `docs/INDEX.md`, and this README.
- Do NOT modify or delete (without explicit user approval):
  - `.git/`
  - `.venv/` or `.venv-wsl/`
  - `data/`
  - `migrations/`
- For appointments UI:
  - Frontend: `templates/appointments/vanilla.html`
  - Backend: `clinic_app/blueprints/appointments/routes.py`
  - The main layout is server-rendered; JavaScript enhances filters, search, and modals and talks to `/api/appointments/...` and `/api/patients/search`.
- For simple expenses (minimal flow):
  - Backend: `clinic_app/blueprints/simple_expenses.py`
  - Frontend: `templates/simple_expenses/`
  - Assets: `static/css/simple-expenses.css`, `static/js/simple-expenses.js`
- For indexing and navigation:
  - See `docs/INDEX.md` for a feature → files map (blueprints, templates, services, CSS/JS, tests).
- For roadmap/planning:
  - See `LAST_PLAN.md` for the current V1 UI/branding/Arabic roadmap.
- Always start by showing a short plan before making changes.
- Prefer small, local edits over big refactors, and keep docs updated when features change.

==================================================
END OF README CONTENT
==================================================
