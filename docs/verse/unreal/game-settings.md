# Verse game settings

Settings → Game settings is the Dodaios Verse's own options menu, inside the
app. It holds what a player expects from a big PC shooter, in seven tabs:
graphics, audio, mouse and camera, keybinds, gameplay, interface (HUD and
crosshair) and accessibility. The in-game menu (Esc → Settings) edits the same
values.

## One catalogue, one store

- `dodaios/verse_host/game_settings.py` lists every setting once: id, tab,
  section, kind (`choice`, `toggle`, `range`, `key`), options or range,
  default, performance cost, and whether it needs a Verse restart.
- Values live in the Verse settings store (`<data dir>/verse/settings.json`,
  `dodaios/verse_host/settings_store.py`), flat under `settings.game` by id
  (`"graphics.shadows": "high"`).
- Settings that existed before the catalogue keep their old place and the
  catalogue entry names it with `path`: `gore`, `reduced_motion`,
  `return_key`, `ui_sound`, `level_sound`, `view.volume`, `view.sensitivity`,
  `view.invert_y`, `view.fov_first`, `view.fov_third`, `view.mode`.
- No key can drive two actions; the store refuses a patch that would bind one
  key twice. The page swaps the two keys in one patch instead.
- Only options Unreal can apply without extra plugins are listed (engine
  anti-aliasing and Temporal Super Resolution, scalability groups, the user
  settings for window, resolution, frame limit and V-Sync).

## Routes

| Method | Path | Does |
|---|---|---|
| GET | `/api/verse/settings/catalogue` | the catalogue (`verse.settings.catalogue/1`) |
| GET | `/api/verse/settings` | every value, defaults filled in |
| PATCH | `/api/verse/settings` | a `settings.set`-shaped subset; 422 on an unknown key or value; a running Verse gets `settings.changed` with exactly the changed keys |

## Bridge

`welcome.settings.game` carries every catalogue value, `settings.changed` and
`settings.set` carry subsets of it, and `welcome.features` announces
`game_settings` (additive in `verse.bridge/1`, `contracts/bridge-protocol.md`
3.2). Verse applies the values it gets and writes changes from its own menu
with `settings.set`.

## The page

`frontend/src/views/VerseSettingsView.tsx` draws the menu like a game's:
tabs across the top (Q / E switch them), rows with a "‹ value ›" stepper or a
filled bar, keycaps you click and then press, and a detail column with the
description, default, performance cost and a live crosshair preview. Picking
a quality preset sets every quality group; changing one group turns the
preset to Custom. Strings are the `verse_settings` locale chunk.
