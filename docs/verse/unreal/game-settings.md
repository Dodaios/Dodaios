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

## In Unreal

VerseUI reads its copy of the catalogue, `unreal/Verse/Data/ui/game_settings.json`
(`python -m dodaios.verse_host.game_settings` writes it; a unit test keeps it
equal to the Python catalogue). `FVerseAppSettings::Game` holds the values:
an unknown id or a value the catalogue refuses is ignored, a missing id reads
as its default. `welcome` and `settings.changed` apply them; the in-game menu
(Esc → Settings, the same seven tabs and the `verse_settings` strings, which
`welcome.locale.strings` carries too) writes each change as one `settings.set`
with only the changed ids. A preset sets every quality group, one group turns
the preset to Custom, and a key rebind that swaps two keys sends both in one
patch. `GameUserSettings.ini` keeps a copy (`UVerseUiUserSettings::GameSettings`
and the mirrored duel FOV, keys, quality, text size and tier), so the Verse
starts with the last values before `welcome` arrives; `welcome` wins.

| Applies live | How |
|---|---|
| Window mode, resolution (`native` = desktop), frame limit (`unlimited` = 0), V-Sync | `UGameUserSettings`, applied and saved; not in the editor |
| HDR | `UGameUserSettings::EnableHDRDisplayOutput` at start only (restart flag) |
| Brightness | `GEngine->DisplayGamma`, 1.6 .. 2.8 around 2.2 |
| Anti-aliasing, 3D resolution, sharpening | `r.AntiAliasingMethod`, `r.ScreenPercentage`, `r.Tonemapper.Sharpen` (set by code) |
| Quality preset and groups | `auto` runs the engine's hardware benchmark once per start; otherwise each scalability group |
| Camera effects | An unbound post-process volume: a switch that is off overrides motion blur, depth of field, film grain, chromatic aberration, lens flares or bloom to zero; on keeps the level's own look |
| Volumes, mix, mute in the background | `UVerseAudioSubsystem`: master = `view.volume`, effects on the weapon, impact, foley, destruction and gadget buses, ambience on its bus, menu sounds on the UI bus, night mode 6 dB off weapons and destruction |
| Keybinds | `FVerseKeyMap` and the Enhanced Input remap; the return key stays `return_key` |
| Duel FOV, opponent tier | `Verse.Settings.DuelFov`, the armoury's preselected tier and quick start |
| Kill cam, duel stats | The kill cam starts only when on; the end-of-set and session screens hide the stats table when off |
| HUD and crosshair | `FVerseHudOptions` in the HUD painter: size, opacity, hit markers, damage numbers, damage direction, performance stats, crosshair style, colour, size, thickness, gap, outline, spread |
| Colour-blind mode, text size | The Slate renderer's colour vision correction (not in the editor); the layout's text scale |

Systems VerseUI cannot reach read the values through one API,
`UVerseUiSubsystem::GetGameSetting(id)` (legacy ids read their old place), or
without a VerseUI dependency from the console variables
`Verse.Settings.Game.<id>`. `OnSettingsApplied` fires after each apply. These
consumers do not exist yet and read the value there once they land: mouse
sensitivity, aim multiplier, hoverboard sensitivity, raw input, smoothing and
the hold or toggle modes (input owner), shoulder and head bob (camera owner),
auto reload (weapon owner), music and voice volumes and the hit sound (no
music or voice bus and no hit-confirm cue yet), high contrast, camera shake,
flash reduction, subtitles and the sound visualiser.
