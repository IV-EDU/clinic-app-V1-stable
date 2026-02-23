## Task: Navbar Responsiveness & Live Patient Search

### Recommended Agent:
[Nimble Coder / UI] - Use a fast, UI-focused model that writes minimal code and won't over-engineer UI tasks.

### Goal
Polish the `_nav.html` bar. Fix overflow issues caused by long clinic names and too many buttons. Upgrade the generic search input into a "Live Search" dropdown that fetches top patient results dynamically (vanilla JS), while preserving the ability to do a full-page search.

### Edge Cases & UX (Mandatory Fixes)
- **Empty Results:** If the query returns 0 patients, show a simple "No patients found" row in the dropdown.
- **Click-away:** Clicking anywhere outside the search input or dropdown must instantly close the dropdown.
- **Fallback Search:** The last row of the dropdown must always be a link saying "View all results for '[query]'" which submits the full search form normally.
- **Keyboard Navigation:** Users should be able to use the Up/Down arrow keys to navigate the dropdown results and hit Enter to select a patient.
- **RTL Alignment:** Ensure the dropdown text aligns properly for Arabic (right).

### Plan
1. **Fix Overflow & Responsiveness:**
   - Open `templates/_nav.html`.
   - Move the "Appointments" button inside the `<div class="kebab-menu">`, placing it at the very top.
   - Update the search `<form>` input to be responsive: `width: 100%; max-width: 250px; min-width: 120px;`.
   - Add inline CSS truncation to `<div class="brand-name">`: `white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 300px;`.

2. **Backend API for Live Search:**
   - Create a lightweight JSON endpoint in `clinic_app/blueprints/core.py` (or `.patients.py`) accepting `?q=`.
   - Query the `Patient` model using the *exact same Arabic normalization logic* used by the main search route.
   - Return a maximum of 5 recent results as JSON (`[{"id": "...", "name": "...", "short_id": "P001", "phone": "..."}]`).

3. **Frontend Live Search (Vanilla JS):**
   - Modify the search `<form>` in `_nav.html` to include `autocomplete="off"`. Ensure the container wrapper has `position: relative`.
   - Create a hidden, `position: absolute` `<div>` directly under the input for the dropdown results.
   - Add Vanilla JS to listen for `input` events with a ~300ms debounce.
   - Fetch the API results and render them as clickable rows linking directly to their profile (`/patients/<id>`). Implement the Edge Cases listed above.

### Constraints
- **NO React/Vue/jQuery.** Pure Vanilla JS only.
- Do NOT modify `admin_settings.py` or the `/data/` folder.
