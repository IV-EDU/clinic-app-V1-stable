# MEMORY.md - Session Handoff Log

> **For AI agents:** Read this at the START of every session. Update it at the END.
> This file ensures continuity across different chats, tools, and models.
> See `AGENTS.md` for the full protocol.

---

## Current State (updated March 3, 2026)

**App status:** Running, stable. Flask + SQLite dental clinic on Windows.
**Branch:** `feature/phase4-admin-split`
**Repo:** `IV-EDU/clinic-app-V1-stable` (default branch: `main`)
**Data:** 1,021 patients, 912 payments. Production use.
**Login:** `admin` / `admin` (NEVER change this)
**Tests:** 107 passing, 2 skipped.

### What Works
- Core patient CRUD, payments, receipts (PDF with Arabic reshaping)
- Appointments page (vanilla.html) - clean card-based UI
- Simple expenses - minimal working flow
- Arabic/RTL with Cairo font, `T()` i18n system (2000+ translations)
- Dark mode toggle (design-system.css + data-theme attribute)
- Theme settings (admin), clinic logo/branding
- Admin Data tab: analyze preview with P000XXX file numbers, responsive layout
- Admin Audit tab: proper Before/After modal, dark mode technical details
- Full test suite passes

### Known Problems
- See `KNOWN_ISSUES.md` for detailed list
- Admin settings is a 6,000-line monolith (index.html)
- Dark mode has gaps on some pages
- No dashboard - home page is just a patient list
- Two expense systems exist (legacy + simple)
- Diagnosis pages are disconnected from main app flow

---

## What's Next - IMPORTANT

### Immediate: Sidebar Step 0 (see LAST_PLAN.md)

The user wants a **full UI reskin** inspired by a mockup with a left sidebar + card-based design.

**Strategy:** Page-by-page rollout. Add sidebar to `_base.html` hidden by default. Pages opt in with `{% set use_sidebar = true %}`.

**Step 0 requirements:**
1. Add flex shell to `_base.html`: `<div class="app-shell"><aside class="sidebar">...</aside><main>...existing...</main></div>`
2. Sidebar has: iSmile logo, nav links (Home, Patients, Appointments, Expenses, Admin Settings), **collapse toggle** at bottom
3. **Collapsible:** expanded (~240px icons+labels) / collapsed (~60px icons only), saved in `localStorage`
4. Hidden by default - only `{% set use_sidebar = true %}` activates it
5. RTL: sidebar flips to right side
6. Dark mode: sidebar uses theme CSS variables
7. Print: sidebar hidden
8. Mobile (<768px): off-canvas drawer with hamburger
9. Search bar, language toggle, user/logout -> slim top bar in main content area
10. DO NOT break any existing pages - old pages without the flag look identical

**Files to touch:** `templates/_base.html`, `templates/_nav.html`, `static/css/app.css`

**After Step 0:** Step 1 = Dashboard homepage (first page to opt into sidebar)

### Key architecture context for the next agent:

**_base.html structure:**
- `<html lang="{{ lang }}" dir="{{ dir }}">`
- `<head>` loads: app.css -> theme-system.css -> design-system.css -> components.css + JS files
- `{{ theme_css|safe }}` injects admin theme overrides as inline `:root` CSS
- `{% include '_nav.html' %}` - top horizontal nav bar (~450 lines)
- `<div class="wrap">` - main content wrapper (max-width: 1100px, overflow-x: hidden)
- `{% block content %}` - child templates inject here
- Theme toggle FAB at bottom-right
- Blocks: `extra_css`, `content`, `extra_js`

**_nav.html structure (448 lines):**
- Horizontal top bar with 3 sections: `.start` (kebab menu + back + home + search), `.center` (logo/brand), `.end` (lang toggle + user/logout)
- Kebab menu has: Appointments, Collections, Expenses, Admin Settings (permission-gated)
- Patient live search with dropdown
- Responsive breakpoints at 1200px, 900px, 768px

**.wrap in app.css:**
- `max-width:1100px; margin:20px auto; padding:0 12px; overflow-x:hidden`
- Admin settings already overrides this with `.wrap:has(.admin-settings-container) { max-width: none; overflow-x: visible; }`

**Theme CSS variables available:** `--primary-color`, `--accent-color`, `--page-bg`, `--bg-surface`, `--text-primary`, `--text-secondary`, `--border`, `--card-shadow`, `--radius-md`, `--radius-lg`, `--spacing-sm/md/lg`, etc. Full list in `static/css/design-system.css` and `static/css/theme-system.css`.

**render_page() injects:** `lang`, `dir`, `t` (translation), `theme_css`, `theme_logo_url`, `clinic_name`, `clinic_tagline`, `user_has_permission`, `show_file_numbers`

**35 templates** extend `_base.html` (21 direct, 14 via sub-bases). All get the sidebar wrapper, but only opted-in pages show it.

---

## Recent Sessions

### Session: Admin Bugfixes + UI Reskin Planning (Mar 3 2026)
**What was done:**
- Fixed audit modal Before/After columns (was showing "CURRENT"/"CURRENT")
- Fixed dark mode technical details pre block
- Fixed FILE NUMBER in analyze preview (backend generates P000XXX)
- Fixed data tab responsive layout (overflow clipping on windowed browsers)
- Added i18n keys: audit_deleted_value, audit_created_value (EN+AR)
- Committed bugfixes as d401ce5
- Committed cleanup of 117 pre-existing uncommitted changes
- Updated LAST_PLAN.md: removed packaging/exe plans, added sidebar rollout plan
- Updated MEMORY.md with full context for next agent

**Key decisions:**
- User wants full UI reskin with collapsible left sidebar (inspired by mockup screenshots)
- Page-by-page rollout (not all-at-once) to avoid breaking the app
- Sidebar hidden by default, pages opt in with `{% set use_sidebar = true %}`
- Keep all existing features/data/buttons, just reorganize into new layout
- Keep existing theme system and colors

### Session: Project Organization & Workflow Redesign (Jul 14 2025)
**What was done:**
- Full project organization audit
- Rewrote AGENTS.md, created MEMORY.md, DESIGN_BRIEF.md
- Merged plans into LAST_PLAN.md
- Moved skills, deleted stale files
- Updated .gitignore

---

## Active Decisions Log

| Decision | Reason | Date |
|----------|--------|------|
| Flask for V1 (not React rewrite) | Polish existing app (~4-6 weeks) vs rewrite (~3-5 months) | 2025-07-14 |
| Collapsible sidebar layout | User's mockup preference, modern medical app feel | 2026-03-03 |
| Page-by-page rollout | Avoid breaking the whole app, can revert individual pages | 2026-03-03 |
| Sidebar hidden by default | Zero breakage on day one, opt-in per page | 2026-03-03 |
| Keep existing theme system | Colors configurable via Admin > Theme, no hard-coded scheme change | 2026-03-03 |

---

## Template for New Entries

When updating this file, add a new entry under "Recent Sessions":

### Session: [Brief Title]
**Date:** YYYY-MM-DD
**What was done:**
- [bullet points of changes]

**Key decisions:**
- [any new decisions and their reasoning]
