# Game settings

Settings → **Game settings** keeps a player's own settings for each game in
one place: mouse sensitivity, keybinds, audio, video and gameplay. A converter
carries a hip-fire sensitivity from one game to every other game at the same
cm/360.

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
| PUT | `/api/games/{id}/profile` | merge `values`, `keybinds`, `dpi` (`reset_dpi`), `notes`; `null` resets a field |
| DELETE | `/api/games/{id}/profile` | forget the profile |
| PUT | `/api/games/dpi` | default mouse DPI |
| POST | `/api/games/convert` | `{game_id, sens, dpi?, to_dpi?}` → the same cm/360 in every linear game |

The app does not write into the games' own config files; the page shows
where each game keeps them.
