# DESIGN_BRIEF.md – Clinic App Design Rules for AI Agents

> **Read this before any UI/design work.** This replaces generic "make it modern" instincts
> with specific guidance for a real dental clinic application.

---

## Identity

- **App type:** Dental clinic management (patients, payments, appointments, expenses)
- **Users:** Dentist (owner), receptionist (data entry), both Arabic-speaking
- **Mood:** Calm, clean, professional, trustworthy — like a modern medical office
- **NOT:** Bold, playful, techy, startup-y, dark/moody, or experimental
- **Quality bar:** Simple does not mean bland. The UI should feel intentional, well-composed, and human-designed, not like generic AI output or a rushed template.

---

## Color Palette

Use the CSS variables defined in `static/css/design-system.css` and `static/css/theme-system.css`.

| Role | Light Mode | Dark Mode | Variable |
|------|-----------|-----------|----------|
| Background | `#f8f9fa` (warm grey) | `#1a1d23` (blue-grey, NOT pure black) | `--color-bg` |
| Surface (cards) | `#ffffff` | `#22262e` | `--color-surface` |
| Surface raised | `#ffffff` | `#2a2e36` | `--color-surface-raised` |
| Primary | `#2563eb` (calm blue) | `#3b82f6` | `--color-primary` |
| Accent | `#0891b2` (teal) | `#06b6d4` | `--color-accent` |
| Success | `#16a34a` | `#22c55e` | `--color-success` |
| Warning | `#d97706` | `#f59e0b` | `--color-warning` |
| Danger | `#dc2626` | `#ef4444` | `--color-danger` |
| Text primary | `#1e293b` | `#e2e8f0` | `--color-text` |
| Text secondary | `#64748b` | `#94a3b8` | `--color-text-secondary` |
| Border | `#e2e8f0` | `#334155` | `--color-border` |

**Rules:**
- Never hard-code hex colors — always use CSS variables.
- Never use pure black (`#000`) for backgrounds or text.
- Never use neon, saturated, or "fun" accent colors.
- Accent colors should feel medical/clinical, not techy.

---

## Typography

- **Primary font:** Cairo (Arabic-optimized, bundled in `static/fonts/`)
- **Fallback:** system-ui, -apple-system, sans-serif
- **Scale:** Use the design system tokens:
  - `--font-size-xs`: 0.75rem (labels, captions)
  - `--font-size-sm`: 0.875rem (secondary text, table cells)
  - `--font-size-base`: 1rem (body text)
  - `--font-size-lg`: 1.125rem (card titles)
  - `--font-size-xl`: 1.25rem (section headings)
  - `--font-size-2xl`: 1.5rem (page titles)

**Rules:**
- Never use more than 3 font sizes on one page.
- Keep body text at `--font-size-base`. Don't make everything large.
- Arabic text needs slightly more line-height (~1.6 vs 1.5 for English).

---

## Layout & Spacing

- **Structure:** Use `_base.html` layout. On legacy pages this means top nav + main content. On opted-in reskin pages this means sidebar + slim topbar + main content.
- **Cards** for all main content sections. Avoid content directly on the page background.
- **Spacing scale** (4px base): 4, 8, 12, 16, 20, 24, 32, 48, 64px.
- **Max content width:** ~1200px centered on large screens.
- **RTL:** Use flex/grid, not fixed left/right positioning. All layouts must work with `dir="rtl"`.

**Rules:**
- Fewer, clearer sections > many nested boxes.
- Consistent padding inside cards. Consistent gaps between cards.
- On mobile widths, cards stack vertically — no horizontal scroll.

---

## Components

### Buttons
- Use shared `.btn` classes: `.btn-primary` (main action), `.btn-secondary`, `.btn-danger`, `.btn-success`.
- **One primary button per section** — make the main action obvious.
- Use `.btn-sm` for inline/table actions.
- Destructive actions (delete, remove) always use `.btn-danger`.

### Cards
- `.card` or `.u-card` — white surface, subtle border, small shadow, rounded corners.
- Card header (optional): title + actions row. Card body: content. Card footer (optional): secondary actions.

### Tables
- Right-align numeric/money columns. Left-align text.
- Keep action buttons in a dedicated "Actions" column.
- Use zebra striping or hover highlight, not both.
- Tables must scroll horizontally on mobile, not break layout.

### Forms
- Labels above inputs (not beside — breaks on narrow screens and in Arabic).
- Required fields marked with subtle asterisk, not red text.
- Error messages below the field, in `--color-danger`.
- Group related fields with subtle section dividers.

### Modals
- Use one consistent modal style: header/body/footer.
- Maximum width 600px for forms, 800px for data views.
- Always closeable via X button, Escape key, and backdrop click.

### Alerts / Messages
- Use shared alert pattern: success (green), warning (amber), error (red), info (blue).
- Toast notifications for transient messages (auto-dismiss). Inline alerts for persistent messages.

---

## What NOT to Do

- **No gradients** on backgrounds or cards (flat surfaces only).
- **No decorative illustrations or icons** that don't serve a function.
- **No animations** except subtle transitions (opacity, transform) on hover/focus.
- **No custom scrollbars** — use browser defaults.
- **No second competing navigation system on the same page.** On sidebar pages, the sidebar + slim topbar is the official shell. On legacy pages, the top nav remains the shell.
- **No sticky headers inside scrollable content** (only the main nav is sticky).
- **No inline `<style>` blocks** — use shared CSS files. If you must add inline styles temporarily, plan a follow-up to move them.
- **No generic “AI-made” page patterns** — avoid random hero sections, decorative gradients, oversized empty cards, fake dashboard filler, or trendy layouts that do not improve real clinic workflows.

---

## Reference Pages

When making design decisions, compare your work to these existing pages:

**Good examples** (follow their patterns):
- Dashboard home (`templates/core/index.html`) — current sidebar-shell reference
- Patient list (`templates/core/patients_list.html`) — current sidebar-shell table/page reference
- Appointments page (`vanilla.html`) — clean card layout, good dark mode
- Simple expenses — minimal, clear, functional
- Login page — centered card, clean form

**Needs improvement** (see `KNOWN_ISSUES.md`):
- Admin settings — overwhelming, needs splitting
- Sidebar rollout is incomplete — appointments, expenses/reports, and admin still need reskin alignment
- Dark mode has gaps on some pages

---

## Quick Checklist Before Committing UI Changes

- [ ] Works in both light mode and dark mode?
- [ ] Works in both LTR (English) and RTL (Arabic)?
- [ ] Uses CSS variables, not hard-coded colors?
- [ ] Uses shared `.btn`, `.card`, alert components?
- [ ] No more than one primary button per section?
- [ ] Tables right-align numbers, left-align text?
- [ ] New user-facing strings wrapped in `T()` with Arabic translations in `i18n.py`?
- [ ] No inline `<style>` blocks (or plan to move them)?
- [ ] Responsive on narrow screens (no horizontal overflow)?
