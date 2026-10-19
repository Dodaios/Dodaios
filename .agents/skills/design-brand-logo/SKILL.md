---
name: design-brand-logo
description: Get the real square brand mark for a Plugins-store card, or as a last resort draw an honest placeholder. Use when a card shows a colour tile or letter monogram, or a logo looks wrong or unofficial.
---

- `PluginsView.tsx` uses `jarvis/ui/web/frontend/src/assets/brands/<plugin-id>.svg` first; the Simple Icons glyph on `logo_color` and the monogram are only fallbacks.
- Look in this order: `https://cdn.jsdelivr.net/gh/gilbarbara/logos@main/logos/<name>-icon.svg` (then `<name>.svg`), `https://cdn.jsdelivr.net/gh/pheralb/svgl@main/static/library/<name>.svg`, then the vendor's own `/icon.svg`, `/logo.svg`, `/api/logo?type=icon`, favicon or press page. Take the square icon (viewBox no wider than ~1.45:1), never the wordmark.
- If the real app icon is a white glyph on a brand colour, the fallback is already right: set `logo_color` and add the plugin to "Deliberately not bundled" in `brands/LOGOS.md`.
- Placeholder only when nothing exists: one geometric glyph for what the service does, white on its brand colour, square, no text, readable at 20 px, ledger basis `own work`. Never imitate a mark. Do not bundle when the vendor's brand rules forbid third-party use.
- Strip `<script>`, `<foreignObject>`, `on*` handlers, external `href`s and `<image>`; add a `LOGOS.md` row (id, source, legal basis, date); run `python scripts/ci/check_brand_logos.py`; `npm run build` and stage the whole rebuilt `dist/`.
