---
name: web-interface-guidelines
description: Vercel's Web Interface Guidelines as a project skill. Use when reviewing, building, or fixing web UI for accessibility, interaction, animation, layout, typography, forms, and performance compliance. Contains the full guidelines plus a copy-paste review checklist.
---

# Vercel Web Interface Guidelines (project skill)

Source: https://github.com/vercel-labs/web-interface-guidelines (vendored copy; see LICENSE).
Installed project-locally for the MedCheck dashboard.

## How to use

1. **Building UI:** read `references/guidelines.md` sections relevant to the work
   (Interactions, Animations, Layout, Typography, Forms, Images, Performance, Dark mode,
   i18n) and follow them.
2. **Reviewing UI:** read `references/command.md` and run that checklist against the
   changed files; report concise findings with file:line and the rule violated.
3. Prefer semantic HTML + framework primitives over ARIA patches; keep keyboard paths and
   visible focus; honor `prefers-reduced-motion`.

## Non-negotiables extracted for MedCheck

- Icon-only buttons need `aria-label`; every control has a visible label.
- All flows keyboard-operable; visible `:focus-visible` rings; focus never obscured.
- Hit targets ≥ 24px (≥ 44px on mobile); `<input>` font-size ≥ 16px on mobile.
- Distinguish action elements (`<button>`) from navigation (`<a>`/`<Link>`).
- Async updates announced (`aria-live="polite"`), loading buttons keep their label.
- Images have `alt` (or `alt=""` when decorative); decorative icons `aria-hidden`.
- No horizontal scroll; respect zoom; no layout shift on load (reserve space).
- Honor `prefers-reduced-motion`; animations convey meaning, not decoration.
- Confirm destructive actions or provide undo; never disable paste.
