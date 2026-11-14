# Pets

A pet is an animated pixel-art companion. Pets live in the app: the active pet
is how the app draws the assistant, an agent can wear any pet, and the user
can draw their own. Users pick and create pets under **Settings → My Pets**.

Pets are not shown on the desktop any more. The desktop overlay styles `pet`
and `mascot` were removed (2026-11-14); an install that still has
`[ui] orb_style = "pet"` or `"mascot"` loads the Dodaios Bar instead
(`dodaios.ui.overlay_styles.LEGACY_STYLE_ALIASES`). The desktop overlay is the
bar, the voice orb or nothing (`docs/dodaios-bar.md`).

## Where pets appear

- **The assistant's mark.** The active pet (`[ui] pet_id`) is the figure the
  app draws for the assistant (`PetMark`, the onboarding guide, the
  assistant's swatch). An id that no longer exists on disk, and the old
  `"none"` an earlier install may have saved, are drawn as the default pet,
  Gigi.
- **In the Dodaios Verse.** Aboard the capital ship the chosen pet is the
  commander's companion drone: it hovers at the commander's heel
  (`docs/verse/README.md`).
- **Worn by an agent.** In an agent's look dialog (*Companion → Look →
  Pet*) any pet from My Pets can replace the agent's shape. It is stored as
  `companion.pet` in the agent's avatar JSON (`dodaios/society/companion.py`,
  mirrored by `components/society/companion/appearance.ts`) and drawn by
  `CompanionMark` wherever the agent appears: roster, chats, mentions, the
  level hall, the bot stage (each scene plays a pet row, `PET_STATE` in
  `botStage/scenes.ts`), the live line of its routine traces, and as its 3D
  companion in the Verse with the pet's own model and gait. The agent's
  colour stays for its chat bubbles. A pet that does not exist on this
  machine (deleted, or drawn on another one) shows the shape again; a shared
  agent template keeps a built-in pet and drops a drawn one.

## States

The vocabulary lives in `dodaios/ui/pets/states.py` (a module with no imports)
and is mirrored in `frontend/src/lib/petStates.ts`; a parity test keeps them
equal. A state is one animation row of a pet:

| State | Meaning |
|---|---|
| `idle` | nothing is happening |
| `listening` | the assistant hears the user |
| `thinking` | the assistant works out an answer |
| `talking` | the assistant speaks |
| `success` (one-shot, 1.5 s) | something the user asked for worked |
| `error` (one-shot, 2 s) | something failed |
| `sleeping` | a long quiet stretch |
| `working` | a step that changes, sends or runs something |
| `searching` | a step that looks something up |
| `held` | the pet is picked up |

Where the app draws a pet, it picks the state from what it shows (an agent's
routine trace, a bot-stage scene, the assistant's turn). A pet whose sheet has
no row for a state borrows one: `working` -> `thinking`, `searching` ->
`working`, `held` -> `listening`, and every chain ends at `idle`
(`STATE_FALLBACKS`).

## Sprite format `jarvis-pet/1`

A pet is a folder with two files:

```text
<pet-id>/
  pet.json    manifest
  sheet.png   sprite sheet (RGBA, real transparency)
```

The sheet is a grid of square cells. `frame_size` is 32, 48 or 64 source
pixels. Each state is one row with up to eight frames. By convention the rows
follow the order of `PET_STATES`: `idle`, `listening`, `thinking`, `talking`,
`success`, `error`, `sleeping`, `working`, `searching`, `held`. The last three
rows are optional for user-made pets (a 64 px sheet has room for only eight
rows); the missing ones fall back as described under *States*.

```json
{
  "format": "jarvis-pet/1",
  "id": "gigi",
  "name": "Gigi",
  "description": "The Dodaios ghost, eight bits tall.",
  "frame_size": 48,
  "sheet": "sheet.png",
  "animations": {
    "idle":      {"row": 0, "frames": 8, "fps": 6, "loop": true,
                  "accent_frames": 1, "accent_every": 3},
    "listening": {"row": 1, "frames": 6, "fps": 8, "loop": true},
    "thinking":  {"row": 2, "frames": 8, "fps": 8, "loop": true},
    "talking":   {"row": 3, "frames": 4, "fps": 10, "loop": true},
    "success":   {"row": 4, "frames": 8, "fps": 10, "loop": false},
    "error":     {"row": 5, "frames": 6, "fps": 9, "loop": false},
    "sleeping":  {"row": 6, "frames": 6, "fps": 3, "loop": true}
  }
}
```

Row conventions:

- **Accent frames.** `accent_frames` (optional) marks the last cells of a
  looping row as an accent, such as a blink, that plays only on every
  `accent_every`-th pass. The built-in idle rows breathe on seven cells and
  blink on the eighth every third breath.
- **Talking by voice.** The `talking` row is ordered by mouth openness, from
  closed to widest, so a renderer with a live output level can pick the frame
  from that level.
- **Idle acts.** A built-in pet may ship little one-shot scenes on a second
  sheet, declared next to the animations: `"acts_sheet": "acts.png"` and
  `"acts": {"fire": {"row": 0, "frames": 8, "fps": 9}, ...}` (1-24 character
  slugs, at most 12 acts, one row each, always one-shot). A user upload is a
  single sheet, so the store drops `acts` from an uploaded `pet.json`.

Rules the loader enforces (`dodaios/ui/pets/manifest.py`):

- `format` must be `jarvis-pet/1`; `id` matches `^[a-z0-9][a-z0-9-]{0,31}$`
  (built-in) or `^u[0-9a-f]{16}$` (user-created).
- `name` is 1–40 characters, `description` at most 140.
- `idle` is required. A missing state borrows another row through
  `STATE_FALLBACKS` (for example `sleeping` → `idle`).
- `frames` is 1–8, `fps` is 1–12, and every referenced cell lies inside the
  sheet. The sheet is at most 512 × 512 pixels and 2 MB.
- Transparency is binary: a pixel is either opaque or gone (alpha ≥ 128
  counts as opaque). The loader nudges any exact-magenta (`#FF00FF`) sprite
  pixel to `#FE00FE`, so a colour-keyed renderer never punches a hole in it.

Built-in pets live in `dodaios/ui/pets/builtin/<id>/` and are generated from
pixel data by `scripts/pets/build_pets.py` (deterministic; a test checks the
committed PNGs match the script). User-created pets live in
`<data dir>/pets/<u…id>/`.

### Built-in pets

| Id | Name | Idea |
|---|---|---|
| `gigi` | Gigi | The Dodaios ghost in brand black and white: it floats, cups its hands to listen, scans while it thinks, its bands light up as it talks, its bits burst on success, it glitches on errors and its tail fades out asleep (default) |
| `miso` | Miso | A cat: ears up while listening, curls up to sleep |
| `brew` | Brew | A teapot: steams while thinking, whistles while talking |
| `bolt` | Bolt | A battery: charges while thinking, sparks on success, runs flat asleep |
| `mochi` | Mochi | A jelly blob that wobbles while listening |
| `shelly` | Shelly | A snail: the shell spins while thinking, it withdraws to sleep |
| `ember` | Ember | A baby dragon: smoke rings while thinking, a fire breath on success, a sooty cough on errors, naps in its eggshell |
| `cocoa` | Cocoa | A chocolate Labrador puppy: tilts its head to listen, digs while it works, sniffs along a scent trail while searching, does zoomies on success, droops its ears on errors and naps in its dog bed |
| `dodaios` | Dodaios | The hooded figure of the logo in black and white: the hood's tip perks up to listen and droops asleep, three dots hop beside it while it thinks, the cape trails a hop on success, it types on a laptop at its feet, and hangs by the hood with dangling feet when it is carried |
| `pip` | Pip | A penguin chick in grey fluff: taps its beak to think, shivers on errors, belly-slides and tucks its beak in to sleep |
| `hazel` | Hazel | A red squirrel: tufted ears perk to listen, holds an acorn while thinking, flicks one up on success, naps inside her tail |
| `otto` | Otto | A sea otter: cracks a clam on its belly while thinking, does a backflip on success, sleeps floating on its back |
| `nox` | Nox | A little owl: turns its head to listen, wears reading glasses to work, spreads its wings on success, ruffles on errors |
| `kiko` | Kiko | An axolotl: gill fronds fan out to listen and glow while it thinks, droop on errors, floats asleep among bubbles |
| `inky` | Inky | An inkwell with a quill for a tuft: the quill taps while thinking and scribbles while working, ink blots on errors |
| `toasty` | Toasty | A retro toaster: the slots glow while thinking, the toast pops on success, burns and smokes on errors |
| `cassie` | Cassie | An 80s cassette: the reels are its eyes and spin while thinking, music notes while talking, tape spaghetti on errors |
| `sprout` | Sprout | A plant spirit: a leaf unfurls while thinking, a flower blooms on success, the leaves wilt on errors and fold to sleep |
| `flick` | Flick | An original house elf: huge ears shoot up to listen and droop on errors, scrubs while working, sleeps under its ears |
| `aurelia` | Aurelia | An original princess in an emerald gown: tilts her head to listen, writes letters with a quill, twirls on success |

## Adding a pet

- **As a user:** Settings → My Pets → Create pet. Upload a sheet in the
  layout above (a template PNG is offered for download), add a name and a
  one-sentence description, optionally a `pet.json`. Without a manifest the
  rows are read in `PET_STATES` order and the frame count per row is the
  number of non-empty cells.
- **As a developer:** add a builder to `scripts/pets/build_pets.py`, run it,
  and commit the generated folder. The parity and completeness tests require
  every built-in pet to provide all ten states.

## Interfaces

### Events (`dodaios/core/events.py`)

- `PetChanged(pet_id, source)`: published by the pets routes after a new
  active pet is on disk; `useWebSocket` turns it into a refetch of the pets
  query, so every open window redraws its pets.

### Configuration

| Key | Default | Meaning |
|---|---|---|
| `[ui] pet_id` | `gigi` | The active pet (built-in id or `u…` id) |

The removed desktop pet's keys (`[ui] pet_scale`, `pet_bubble`,
`pet_strip_always`, `orb_mascot_path`, `[trigger] hotkey_pet_toggle`) still
load from an old `jarvis.toml` and are ignored.

### REST (`dodaios/ui/web/pets_routes.py`)

| Method and path | Body / result |
|---|---|
| `GET /api/pets` | `{active, pets: [{id, name, description, builtin, frame_size, animations, sheet_url}]}` |
| `GET /api/pets/{id}/sheet.png` | The sprite sheet |
| `GET /api/pets/template.png` | The empty sprite-sheet template (48 px cells, rows in state order) |
| `PUT /api/pets/active` | `{pet_id}` → saves `[ui] pet_id`, publishes `PetChanged`; `"none"` is refused; 409 on a dev instance (both instances share one `jarvis.toml`) |
| `POST /api/pets` | multipart: `sheet` (PNG), `name`, `description`, optional `manifest` (JSON), optional `frame_size` → the new pet |
| `DELETE /api/pets/{id}` | user-created pets only; deleting the active pet makes the default pet active |

Every route is also a `jarvis api pets <op>` command (CLI-first contract).
