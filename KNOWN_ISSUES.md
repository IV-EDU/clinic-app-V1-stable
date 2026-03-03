# Known Issues, UX Problems & Strategic Context

> **For AI agents:** Read this file before starting any work. It contains the honest assessment
> of what's wrong with the app and what the user's goals are. Updated March 3, 2026.
> See also: `docs/FULL_AUDIT_REPORT.md` for the detailed per-page audit.

---

## User Context (Important)

- The user is **not a programmer**. They are a dentist running a real clinic.
- They want the app to look and feel like a **modern, professional product** — not a developer prototype.
- They are considering a **React rewrite** because the current UI feels unpolished and inconsistent.
- They want a **receptionist workflow** where front-desk staff enters data and the doctor reviews before committing.
- They want a **dashboard homepage** instead of a plain patient list.
- They are frustrated that the app **looks like it was built by different people at different times** (because it was).

---

## Critical UX Problems

### 1. Admin Settings Is Overwhelming and Ugly
**Location:** `/admin/settings` — `templates/admin/settings/index.html` (5,700 lines)

Problems:
- **7 tabs crammed into a horizontal bar** — on smaller screens they wrap awkwardly
- **Data tab has 6 sub-tabs inside it** — tabs-within-tabs is confusing navigation
- **Theme tab is a wall of color pickers** with no visual grouping or sections — user has to scroll through 8+ color swatches stacked vertically, plus branding fields, plus logo upload, plus PDF logo upload. It's intimidating.
- **Roles table shows raw permission strings** like `patients:view`, `payments:edit` — meaningless to a non-technical user. Should show human-readable labels.
- **Audit tab mixing two unrelated things** — payment audit log and patient snapshots in the same tab with no clear separation
- **Data tab Advanced/Simple toggle** is a checkbox that barely looks clickable — easy to miss
- **Overall**: The admin settings feel like a developer control panel, not a clinic management tool. Too much information, too little visual hierarchy.

**What good admin panels look like:**
- Separate pages for each section (not tabs) with a sidebar navigation
- Clear visual sections with headers, descriptions, and icons
- Settings grouped by purpose: "My Clinic" (name, logo, branding), "People" (users, roles, doctors), "Data" (import, export, backups), "Advanced" (audit, permissions)
- Progressive disclosure — show simple options first, hide advanced options behind clear "Show advanced" sections

### 2. Diagnosis / Medical / Images Are Disconnected
**Location:** `templates/diag_plus/` — blueprint `palmer_plus`

Problems:
- These pages have **their own mini-navigation** (← Back, Adult/Child/Medical/Images) instead of the main app nav bar
- **No hamburger menu**, no quick access to other sections
- **Images page shows NO patient information** — just a toolbar and a drop zone. You don't even know which patient you're looking at unless you read the URL.
- **Different visual style** from the rest of the app — feels like a separate product bolted on
- The patient info mini-card (on Diagnosis/Medical) is inconsistent with the patient detail page header

### 3. Two Expense Systems
- **Simple Expenses** (`/simple-expenses/`): In the nav menu. Minimal: date, amount, description.
- **Legacy Expenses** (`/expenses/`): NOT in the nav menu. Full-featured: categories, statuses, file uploads, CSV/PDF export. But the user can't find it without knowing the URL.
- This is confusing and wasteful. Choose one or merge them.

### 4. The Patient List Is Not a Dashboard
- Home page (`/`) is just a patient list with a search bar
- No overview of: today's appointments, recent payments, outstanding balances, clinic stats
- A dashboard should give the doctor a "morning briefing" — what's happening today, what needs attention

---

## Bugs (Functional)

| # | Severity | Location | Description | Status |
|---|----------|----------|-------------|--------|
| 1 | Medium | Audit tab → View detail modal | Changes table had two columns both labeled "CURRENT" — should be "Before" / "After" | **Fixed** (Mar 3 2026) |
| 2 | Low | All diagnosis/images pages | SVG `<path>` attribute error in console (cosmetic) | Open |
| 3 | Low | Outstanding balances | Two patients share file number P000002 — data quality issue | Open |
| 4 | Low | Audit tab → Technical details (dark mode) | `<pre>` block had hardcoded white background in dark mode | **Fixed** (Mar 3 2026) |
| 5 | Low | Data → Analyze preview | FILE NUMBER column showed "—" for all rows because legacy Excel has page numbers, not file numbers. Now falls back to page number. | **Fixed** (Mar 3 2026) |

---

## Dark Mode Gaps

| Location | Issue |
|----------|-------|
| Images page drop zone | Stays white — doesn't respect dark mode |
| Simple Expenses month picker | White background in dark mode |
| Native date/month `<input>` elements | Some render light in dark mode depending on browser |

---

## Arabic Translation Gaps

| Location | What's missing |
|----------|---------------|
| Appointments page | "Doctor" label, "All doctors" option |
| Legacy Expenses | Category names (12), Status names (3), Amount labels |
| Admin settings | Role names (Admin, Receptionist, etc.) |
| Patient treatments | "Any Doctor" in treatment cards |

---

## Code Quality Concerns

| Area | Issue |
|------|-------|
| `templates/admin/settings/index.html` | **5,700 lines** — all 7 admin tabs in one file. Very hard to maintain. |
| `templates/appointments/vanilla.html` | **~2,800 lines** — page + embedded JS. Should be split. |
| Two expense systems | Duplicate code paths: `blueprints/expenses/` + `blueprints/simple_expenses.py` with separate services, templates, CSS, JS each |
| Diagnosis/Medical/Images | Separate template system (`diag_plus/`) with its own styles (`static/diag_plus/style.css`) — not integrated with main design system |

---

## Strategic Decision Pending: React vs. Flask

The user is considering a full React rewrite. Key considerations:

**React won't automatically make the app look better.** What makes apps look professional is:
1. A design system / UI component library (Material UI, Shadcn, Ant Design)
2. Consistent spacing, typography, and color usage
3. Good information architecture (where things are, how you navigate)

**The same design system approach works with Flask + CSS.** The current app already has `design-system.css` and `theme-system.css`. The problem isn't the technology — it's that:
- The design system isn't applied consistently across all pages
- Some pages (diag_plus) don't use it at all
- Admin settings has too much crammed into one screen
- There's no clear information hierarchy

**React would help with:**
- Complex interactive UIs (drag-and-drop appointment scheduling, live search, real-time updates)
- Component reusability across pages
- Easier state management for complex forms (like the admin settings)
- Better developer tooling and ecosystem

**React would cost:**
- 3-6 months to rebuild what already works
- Need to build a REST API layer (currently all server-rendered)
- Arabic/RTL, dark mode, all UI polish starts from zero
- The user can't code — they need AI agents for ALL work

**Recommended path:** Polish Flask for V1 release, then gradually add React for new complex pages while keeping existing Flask pages working. This is called the "strangler fig" pattern.

---

## Priority Fix Order

1. ~~Fix the 3 bugs (1-2 hours)~~ — Bug #1, #4, #5 fixed (Mar 3 2026). Bugs #2, #3 still open.
2. Fix dark mode gaps (1-2 hours)
3. Complete Arabic translations (2-3 hours)
4. Redesign admin settings into proper sections with sidebar nav (8-16 hours)
5. Integrate Diagnosis/Medical/Images into main layout (4-8 hours)
6. Merge or remove duplicate expenses system (2-4 hours)
7. Add dashboard cards to home page (4-8 hours)
8. Add receptionist workflow (8-16 hours)

---

*This file is for AI agents working on this project. Keep it updated as issues are resolved.*
