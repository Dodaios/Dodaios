# Game settings

Settings → **Game settings** keeps a player's own settings for each game in
one place: graphics and performance, mouse sensitivity, keybinds, audio and
gameplay. A converter carries a hip-fire sensitivity from one game to every
other game at the same cm/360.

## Graphics & performance

Every game gets the same block (`dodaios/games/performance.py`, keys
`perf_*`): resolution from 1280×720 to 5120×2880 including ultrawides,
display mode, refresh rate up to 540 Hz, FPS limit up to **Unlimited**,
V-Sync, G-Sync/FreeSync, HDR, quality preset, render scale (50–200 %),
upscaler (DLSS, FSR, XeSS, TSR) and its mode, sharpening, frame generation,
low latency (Reflex / Anti-Lag), every detail level, anti-aliasing,
anisotropic filtering, ambient occlusion, ray tracing (up to path tracing)
and the post effects. The game's own video options follow under the names
the game uses; the ones the block already covers (display mode, resolution
typed as text) are dropped.

Four presets fill the block in one click: **Competitive** (unlimited FPS,
lowest latency, low detail), **Balanced**, **Quality** and **Epic** (path
tracing, frame generation, HDR). A preset that says `"monitor"` for the FPS
limit takes the detected monitor's refresh rate; resolution and refresh rate
follow the monitor.

`GET /api/games/system` (`dodaios/games/system.py`) reads the GPU (NVIDIA
via NVML / nvidia-smi, any vendor on Windows by name), CPU, RAM and every
monitor's current mode plus the highest refresh rate at that resolution.
From the GPU it picks a class (entry, mid, high, enthusiast) and the
recommended preset. When Windows runs the monitor below what it can do, the
page says so.

## Keybinds

Each action has a primary and a secondary bind. A bind is a key, a mouse
button, the wheel, or a combination joined with ` + ` (`Ctrl + Shift + F`,
`Shift + Mouse 4`); a modifier pressed and released alone binds itself
(`Left Shift`). Actions like sprint, crouch, aim, walk and lean can be set to
hold or toggle. Players add their own actions (emotes, macros, comms). A
keyboard and a mouse panel light up every bound input and mark collisions.

## Games

Fortnite, Call of Duty (Black Ops 6 / Warzone), Rainbow Six Siege X, Valorant,
Counter-Strike 2, Apex Legends, Overwatch 2, Battlefield 6, PUBG, Marvel
Rivals, The Finals, Escape from Tarkov, Destiny 2, ARC Raiders and Rocket
League.

The settings of each game live in `dodaios/games/catalog.json`: setting names
as the game prints them, ranges, defaults where they could be verified (`null`
otherwise), the default PC keybinds, where the game keeps its own config file,
and the mouse **yaw** used for conversion. Adding a game is one entry there;
the page needs no change.

Each setting has a `type`: `slider` (min/max), `number`, `select` (options),
`toggle` or `text`.

## Sensitivity

`yaw` is the number of degrees the camera turns per mouse count at
sensitivity 1, in the game's own units:

```
cm/360 = 360 * 2.54 / (dpi * sens * yaw)
sens_b = sens_a * yaw_a * dpi_a / (yaw_b * dpi_b)
```

Games whose sensitivity is not linear (Battlefield 6, PUBG, ARC Raiders,
Rocket League) have `yaw: null` and are left out of the converter. Only
hip-fire converts; scoped and ADS multipliers depend on each game's field of
view.

## Storage and API

Profiles are saved in `<data dir>/games/profiles.json` (`dodaios/games/store.py`),
checked against the catalog before they are written.

| Method | Path | Does |
|--------|------|------|
| GET | `/api/games` | games, which have a profile, default DPI |
| GET | `/api/games/{id}` | one game's definition and profile |
| PUT | `/api/games/{id}/profile` | merge `values`, `keybinds`, `alt_keybinds`, `bind_modes`, `dpi` (`reset_dpi`), `notes`; replace `custom_binds`; `null` resets a field |
| DELETE | `/api/games/{id}/profile` | forget the profile |
| PUT | `/api/games/dpi` | default mouse DPI |
| GET | `/api/games/system` | GPU, CPU, RAM, monitors, recommended preset |
| POST | `/api/games/convert` | `{game_id, sens, dpi?, to_dpi?}` → the same cm/360 in every linear game |

The app does not write into the games' own config files; the page shows
where each game keeps them.
