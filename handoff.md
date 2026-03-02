## Task: Fix Admin Analyze Tab CSS and Nav Search Bar Layout Bugs

### Recommended Agent:
**Nimble Coder / UI:** This task is purely CSS/HTML plumbing to fix layout regressions caused by recent UI Redesign phases. No complex backend logic or database migrations are required.

### Goal
We recently completed Phase 1-3 of the UI Redesign. In the process, two critical UI bugs were introduced that need immediate fixing before we add new features:
1. The `.btn-sm` class was lost, breaking the pagination and mode buttons in the Admin -> Data -> Analyze tab.
2. The global search bar added to `_nav.html` is visually broken/glitchy. The manager wants this fixed *perfectly*.

### Plan (Execute Exactly This)

#### 1. Fix Admin Button CSS
Open `static/css/app.css` and add the missing `.btn-sm` class definition exactly as follows:
```css
.btn.btn-sm, button.btn-sm {
  padding: 4px 8px;
  font-size: 0.85rem;
  border-radius: var(--radius-sm, 6px);
  gap: 4px;
}
```

#### 2. Fix Nav Search Bar CSS (`templates/_nav.html`)
The search bar needs to look embedded, subtle, and premium. In `templates/_nav.html`, find the `<style>` block and update the search bar CSS exactly like this:

Replace the `.nav-search-form` block with:
```css
  .nav-search-form {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: 8px; /* Use a slight rounded corner, not a pill */
    padding: 0px 8px;
    box-shadow: inset 0 1px 3px rgba(0,0,0,0.02); /* Very subtle inner shadow */
    transition: all var(--transition-normal);
  }
  .nav-search-form:focus-within {
    border-color: var(--color-primary, #3b82f6);
    box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.2);
    background: #ffffff;
  }
```

Replace the `.nav-search-input` block with:
```css
  .nav-search-input {
    border: none;
    background: transparent;
    padding: 0.4rem 0.5rem 0.4rem 0px;
    width: 100%;
    outline: none;
    color: var(--color-text);
    font-size: 0.9rem; /* Slightly smaller typography */
  }
  html[dir="rtl"] .nav-search-input {
    padding: 0.4rem 0px 0.4rem 0.5rem; /* Flip padding for Arabic */
  }
```

#### 3. Visual QA (CRITICAL)
Start the server (`python wsgi.py`). Use your browser to take screenshots of BOTH fixes:
1. Navigate to `/auth/login`, login with `admin`/`admin`.
2. Navigate to Admin -> Data -> Analyze. Take a screenshot showing the fixed `.btn-sm` buttons.
3. Take a screenshot of the fixed Nav Search Bar.
4. Save these to `data/agent-screenshots/` and explicitly tell the user to open them.

### Constraints
- **NEVER touch the import logic.**
- Do not introduce new CSS frameworks (no Tailwind/Bootstrap).
- Do NOT mark this task as complete until you have taken screenshots.

### Manager Review Step (Mandatory)
Before executing, state:
1. "I will be modifying `static/css/app.css` and `templates/_nav.html`."
2. "I will NOT be touching backend routing or import/merge logic."
3. "I will provide screenshots of both fixes before declaring done."
