# Coding-agent marks

The marks of the terminal coding agents a workspace pane can run (Claude Code,
Codex, Cursor, Grok Build, Kimi, OpenCode, Z.ai), bundled so a pane header, an
agent picker, the thread list and the tool chips render offline. A coding agent
with a product mark of its own (the Claude Code mascot, the Codex tile) shows that
mark, not its vendor's company logo. Agents without one (Antigravity, DeepSeek)
reuse the files in `../providers/`.

Every mark belongs to its owner and is used **solely to identify the agent a
pane runs** (nominative use). It does not imply that the owner endorses,
sponsors or is affiliated with this project. If you own a mark listed here and
want it removed, open an issue and it will be taken out.

> A CC0 or MIT licence on an SVG settles the **copyright in the drawing**. It
> does not grant **trademark** rights, and no entry below claims otherwise.

## Rules

* Files are taken unmodified from the recorded source. The only edit allowed is
  dropping root-level `width`/`height`/`style`, because the tile sizes the mark.
* A single-colour glyph (`mono`) is drawn as a CSS mask over the current text
  ink (neutral monochrome), never in a palette colour of ours. A full-colour
  mark (`colour`) is drawn as the vendor coloured it.
* `scripts/ci/check_brand_logos.py` fails on a file without a row, and on a row
  that describes a redrawn or recoloured mark.

| agent | Source | Legal basis | Render | Added |
| --- | --- | --- | --- | --- |
| claude-code | lobehub/lobe-icons, `@lobehub/icons-static-svg` 1.102.0 `icons/claudecode-color.svg` (root width/height/style dropped) | MIT | colour | 2026-11-14 |
| codex | lobehub/lobe-icons, `@lobehub/icons-static-svg` 1.102.0 `icons/codex-color.svg` (root width/height/style dropped) | MIT | colour | 2026-11-14 |
| cursor | lobehub/lobe-icons, `@lobehub/icons-static-svg` 1.102.0 `icons/cursor.svg` (root width/height/style dropped) | MIT | mono | 2026-11-14 |
| grok-build | lobehub/lobe-icons, `@lobehub/icons-static-svg` 1.102.0 `icons/grok.svg` (root width/height/style dropped) | MIT | mono | 2026-11-14 |
| kimi | simple-icons 16.30.0 `icons/kimi.svg` (byte-for-byte) | CC0-1.0 | mono | 2026-10-27 |
| opencode | lobehub/lobe-icons, `@lobehub/icons-static-svg` 1.102.0 `icons/opencode.svg` (root width/height/style dropped) | MIT | mono | 2026-11-14 |
| zai | lobehub/lobe-icons, `@lobehub/icons-static-svg` 1.101.0 `icons/zai.svg` (root width/height/style dropped) | MIT | mono | 2026-10-27 |
