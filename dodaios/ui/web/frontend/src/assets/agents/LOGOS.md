# Coding-agent marks

The marks of the terminal coding agents a workspace pane can run (Cursor,
DeepSeek, Kimi, OpenCode, Z.ai), bundled so a pane header, an agent picker and
the tool chips render offline. Agents whose vendor is also a provider family
(Claude, Codex, Antigravity, Grok) reuse the files in `../providers/` instead
of keeping a copy here.

Every mark belongs to its owner and is used **solely to identify the agent a
pane runs** (nominative use). It does not imply that the owner endorses,
sponsors or is affiliated with this project. If you own a mark listed here and
want it removed, open an issue and it will be taken out.

> A CC0 or MIT licence on an SVG settles the **copyright in the drawing**. It
> does not grant **trademark** rights, and no entry below claims otherwise.

## Rules

* Files are taken unmodified from the recorded source. The only edit allowed is
  dropping root-level `width`/`height`/`style`, because the tile sizes the mark.
* Every file here is a single-colour glyph. It is drawn as a CSS mask over the
  current text ink (neutral monochrome), never in a palette colour of ours.
* `scripts/ci/check_brand_logos.py` fails on a file without a row, and on a row
  that describes a redrawn or recoloured mark.

| agent | Source | Legal basis | Render | Added |
| --- | --- | --- | --- | --- |
| cursor | simple-icons 16.30.0 `icons/cursor.svg` (byte-for-byte) | CC0-1.0 | mono | 2026-10-27 |
| deepseek | simple-icons 16.30.0 `icons/deepseek.svg` (byte-for-byte) | CC0-1.0 | mono | 2026-10-27 |
| kimi | simple-icons 16.30.0 `icons/kimi.svg` (byte-for-byte) | CC0-1.0 | mono | 2026-10-27 |
| opencode | simple-icons 16.30.0 `icons/opencode.svg` (byte-for-byte) | CC0-1.0 | mono | 2026-10-27 |
| zai | lobehub/lobe-icons, `@lobehub/icons-static-svg` 1.101.0 `icons/zai.svg` (root width/height/style dropped) | MIT | mono | 2026-10-27 |
