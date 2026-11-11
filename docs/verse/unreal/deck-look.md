# Deck look (WP12)

How the Unreal decks (bridge, ops, engineering, hangar) get their look at runtime. Two
transient actors do it when `UVerseDeckSubsystem` arrives on a deck. Both are purely visual:
they add no collision and no nav, and they leave the sockets and the coordinates contract
untouched.

## Lighting: `AVerseDeckLighting` (`VerseDeckLook.cpp`)

- **Camera look.** An unbound post-process volume per deck sets these values from `FVerseDeckLook`:
  - manual exposure (EV100);
  - Lumen GI and reflections;
  - light bloom, vignette and grain;
  - a near-neutral grade (highlights 1.03 / 1.0 / 0.97).

  The decks' colour comes from the read-outs and the gold accents, not from a sepia wash.
- **Fixture grids.** A light socket with `count` > 1 spreads rect lights over its room. A room
  whose light sockets give less than 5 lm/m² counts as unlit and gets the default ceiling grid.
  Halls over 800 m² get 20 fixtures.
- **Screen glow.** Every screen socket throws an amber point glow (900 lm) onto its console.
- **Arrival.** `ArrivalLocationCm`, `ArrivalYawDeg` and `ArrivalPitchDeg` reframe a deck whose
  spawn socket puts the third-person camera behind a wall. This applies to the hangar and to ops.

## Life: `AVerseDeckLife` (`VerseDeckLife.cpp`)

| What | How |
|---|---|
| Read-outs | Every `M_Screen` slot of the deck gets one `MI_Readout_<Layout>` (`M_Verse_Screen`), chosen by deck and position. The layouts are drawn by `art/verse/decks/life/screens.py` in amber, ivory and red on charcoal; no cyan, blue or violet (art-pipeline 8.3). WP16's live monitors replace a read-out when they bind their render target. |
| Wall displays | `SM_Clutter_WallDisplay` every ~5 m of wall where a horizontal trace finds a flat wall with nothing standing in front, 1.65 m up, with an amber glow. |
| Holo globes | `SM_Clutter_HoloGlobe` (amber light lines) turns over each `holo` socket, with an amber point light. |
| Gold guides | `SM_Clutter_GuideStrip` dashes along each room edge, 30 cm in, only where a trace lands on the room's own floor and the space above is open. |
| Desk props | Tablets, mugs, data pads, headsets and tool cases (`kit/props/command/clutter.py`) in front of console screens and on any flat table, desk or counter top 65–115 cm up (corner traces check that the top is flat). |
| Floor props | Cable coils and, on engineering, tool cases beside equipment, never in the middle of a walkway. |

## Materials

`kit/mi_recipes.py` gives these deck families a scanned or drawn texture set. The sets are
built by `art/verse/decks/life/textures.py` under `/Game/Verse/Textures/DeckLife/`:

| Family | Set |
|---|---|
| `Seat_` | Leather (Poly Haven `brown_leather`, CC0), dark oxblood tint |
| `Fabric_` | Fabric (Poly Haven `denim_fabric_04`, CC0) |
| `Rubber_` | Rubber (own, procedural) |
| `Trim_BrushedSteel`, `Console_Deck` | Brushed (own, procedural) |
| `Console_Body` | Paint (arena set) |

The console-top trim `MI_Paint_TrimRed` is brand gold. The walkway inlays
(`MI_Light_FloorInlay`) and the guides glow gold at 45 nits, so they keep their colour at the
decks' exposure.
