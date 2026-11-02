# Hangar arena (WP11)

Deck 4 is a normal deck day to day and turns into a dense, three-level,
destructible 1v1 arena on demand (README, Arena and Mode). This file is the
layout spec of WP11.1 and the reference for the other WP11 sub-tasks. The
layout itself is code: `art/verse/decks/hangar/unreal_arena/layout.py` holds
every box, stair, spawn, light and station once; the numbers below come from
it and from the flow report its tool writes.

```text
python art/verse/decks/hangar/unreal_arena_build.py      # placements, flow report, plans
python -m pytest tests/verse/test_verse_hangar_arena.py  # A11.1, A11.2, A11.5, A11.7 (static)
```

## 1. Frame

Plan metres in the frame of `hangar_layout.py` and `coordinates.md` 3.1:
`x` east (0 = west hull wall, 100 = east), `z` toward the near wall (0 = the
hero wall, 62 = the near wall), `h` height above the hall floor. Unreal space
is `(100 x, 100 z, 100 h)` cm. The three.js numbers do not carry over (README,
"What carries over").

| Item | Value |
|---|---|
| Hall | 100 x 62 m, ceiling underside at 21 m, hull walls and hero wall solid concrete |
| Hall floor | concrete, `Verse_Architecture`, no `destructible` block: never breaks (A11.7) |
| Launch well | opening x 27..37, z 9..19, 26 m deep, railed; the pit is outside the nav. This supersedes the well of `hangar_layout.py` (x 8..38, z 8..20) and the worked example of coordinates 3.1 for the Unreal hangar: WP12 day zones and WP15 crew sockets must keep clear of x 27..37, z 9..19 and may use the old well area as floor |
| Arena | x 25..75, z 4..44: 50 x 40 m, walkable extent 49 x 39.5 m |
| Levels | L0 floor 0 m, L1 3.0 m, L2 6.0 to 6.3 m |
| Perimeter | blast barriers 4.5 m plus a see-through fence to 10 m on all four edges, arena layer only; the north run (z 3.4..4) stops at the hero pier (x 49..51), which closes the gap. Checked by `test_arena_is_sealed_from_the_hall`: nav built over the whole hall in arena mode, no node outside the arena reaches one inside |

## 2. Zones

| Zone | Owner | Data layer | Holds |
|---|---|---|---|
| `shell` | WP11 | `DL_Hangar_Base` (perimeter: `DL_Hangar_Arena`) | Floor slabs, hull and hero walls, ceiling, launch well, hero pier, truss columns, perimeter, work lights |
| `arena_canyon` | WP11 | `DL_Hangar_Arena` | Three container rows (x 60.6, 66.6, 72.6; 2.4 m wide, 3.0 m tall), 3.6 m aisles, staggered cross alleys, shut doors on every second container, bridge to the shuttle roof, south stair to the R2 roofs |
| `arena_shuttle` | WP11 | `DL_Hangar_Arena` | The walkable gunship (x 46..54, z 15..33): armoured hull, side hatches, open tail, inner bulkhead with a breakable service panel, roof deck at L1 with a turret; ground cover around the pad |
| `arena_booth` | WP11 | `DL_Hangar_Arena` | The glazed lookout (x 25..38, z 32..44): lower room at L1 with breakable glass to the east, upper room at L2, inner stair, floor stair, bridge to the shuttle |
| `arena_catwalks` | WP11 | `DL_Hangar_Arena` | North runs at L2 split by the hero pier, west leg, launch-well crossing and landing, enclosed south gallery on a solid deck, ceiling panels, hanging screens, the hung container, the stairs between levels |
| `armoury` | WP11 | `DL_Hangar_Base` | Loadout room x 77..97.5, z 47.2..61.6; the `armoury` station (WP16 class, WP18 panel) and the loadout board |
| `lift_lobby`, `day_stations` | WP12 | `DL_Hangar_Base`, `DL_Hangar_Day` | Not in this package |

Every placement carries `owner: "WP11"` and the tag
`Verse.Material.<penetration material>`. Pieces that never break use
`Verse_Architecture` (or `Verse_Prop` for pawn-only railings and fences);
breakable ones use `Verse_Destructible` with the class of
`/Script/VerseDestruction.VerseDestructible` (WP06).

## 3. Levels, lanes and cover rhythm

Nav shares (A11.1, at least 15 % each): L0 65.0 %, L1 18.4 %, L2 16.5 % of
1,949 m², one connected island.

| Link | From | To |
|---|---|---|
| Booth floor stair | L0 south corridor (z 42) | L1 booth door, bridge to the shuttle |
| Booth inner stair | L1 booth | L2 booth upper room |
| R2 stair | L0 south end of aisle 2 | L1 roofs of R2 containers 4-5 |
| Catwalk to canyon | L2 north run (east) | L1 roofs of R1 containers 1-2, bridge to the shuttle roof |
| Well crossing stair | L2 well landing | L1 shuttle roof |
| Gallery stair | L0 corridor x 58..60 | L2 south gallery, which leads into the booth upper room |
| West leg | L2 north run (west) | L2 booth upper room |

Lanes:

- **Canyon** (east): three 3.6 m aisles along z, cross alleys offset per row
  so no alley runs the whole width. Container walls are `container_wall`
  (300 HP, bullets hole, charges breach), so the canyon opens over a match;
  drones close it again after about 60 s (destruction 7).
- **Shuttle** (middle): the hull is armour and never breaks; the interior is
  a short close-range lane with two side hatches and an open tail. The
  bulkhead's service panel is the only breakable part, a choice to open a
  through-lane.
- **West floor**: the well with its railing (see-through, not walkable), the
  well crossing above it, crates and cover walls on the floor.
- **Upper ring**: north runs, west leg, booth upper room and the enclosed
  south gallery form an L2 loop. The north run is split by the hero pier, the
  gallery has sheet-metal walls (bolts hole them, charges breach them), so
  every long upper sightline has to be opened first.

Cover rhythm: the flow tool placed 40 blockers (`COVER` in `layout.py`):
18 hanging blast screens (bottom 3.6 m or 5.0 m, top 9 m) cut the upper
diagonals, 9 cover walls (3.4 m) and a crate the floor lanes, 12 truss
columns both.
After them no unbroken sightline in the arena exceeds 40 m (section 6).

## 4. Spawns

`AVerseSpawnPoint` actors from the `spawn` sockets (`team: any`,
`duel: true`, probe heights 0.3, 1.0, 1.65 m). Nine spawns, every pair at
least 22.6 m apart by path (A11.2 asks 20 m).

| Id | Plan (x, z, h) m | Heading |
|---|---|---|
| `sp_nw_floor` | 26.0, 5.0, 0 | 45 |
| `sp_north_mid` | 48.0, 8.0, 0 | 90 |
| `sp_ne_canyon` | 70.8, 6.0, 0 | 90 |
| `sp_e_canyon` | 71.0, 40.0, 0 | 270 |
| `sp_south_mid` | 48.5, 43.0, 0 | 270 |
| `sp_booth` | 31.5, 40.5, 3.0 | 0 |
| `sp_cat_west` | 26.2, 18.0, 6.0 | 90 |
| `sp_shuttle_roof` | 50.0, 30.5, 3.0 | 270 |
| `sp_cat_gantry` | 57.5, 37.2, 6.0 | 180 |

Selection and protection are `UVerseRuleset_Deathmatch` (combat-state 9.2,
9.3): out of the opponent's sight if any spawn is, then the farthest by path,
ties within 1 m by `VerseRng(match seed, death count)`; a spawn with a pawn,
Bulwark or armed breach charge within 3 m is skipped. Path length is the
navmesh path from the opponent's floor point (`APawn::GetNavAgentLocation`)
to the spawn floor, queried through reflection on
`UNavigationSystemV1::FindPathToLocationSynchronously` (VerseCombat has no
NavigationSystem module edge); no path falls back to the Euclidean distance.
The spawn list is sorted by `SpawnId`, then actor name, before the tie break,
so a seeded match picks the same spawns however World Partition loads them.

## 5. Destructibles

Every breakable piece is solid at its material's reference thickness
(destruction 9), checked by `test_destructibles_are_solid_at_their_reference_thickness`.

| Class | Material | Pieces | Where |
|---|---|---|---|
| Container wall | `container_wall`, 4 mm | 34 | Canyon long walls and shut doors |
| Ceiling panel | `ceiling_panel`, 25 mm | 26 | Over the north runs, at 9 m |
| Catwalk segment | `catwalk_grating`, 30 mm | 23 | North runs, west leg, well crossing, bridges (charges only) |
| Wall panel | `sheet_metal`, 3 mm | 15 | South gallery walls, shuttle service panel |
| Cladding wall | `cladding_panel`, 40 mm | 8 | Booth lower room north and south faces |
| Glass pane | `glass`, 24 mm | 8 | Booth lower room east face, upper room south face |

Arena on and arena off both run the full destruction reset (destruction 11);
the switch raises the event, VerseDestruction does the reset.

## 6. Flow (WP11.11)

`unreal_arena/flow.py` measures the layout on a 0.5 m 2.5D nav grid (body
radius 0.3 m, height 1.8 m, step 0.5 m). Sight runs eye to eye at 1.65 m;
glass, grating, railings and the fence let sight through, as in the game.

| Measure | Value | Gate |
|---|---|---|
| Longest unbroken sightline (2 m lattice, 262,450 pairs) | 38.8 m | A11.5: at most 40 m |
| Sightline histogram, 5 m bins from 0 | 4625, 9284, 9367, 5939, 3656, 1524, 780, 176, 0 | |
| Time to contact, walker model, 120 runs | median 6.25 s (p10 1.0 s, p90 14.8 s) | A11.5: 6-15 s for normal vs normal |
| Hider (explorer seeker vs camper on the 8 least-seen spots), 60 runs | median 17.25 s | BG12 with `hider`: at most 25 s |

The walker and explorer are design-time stand-ins: seeded, deterministic,
4.8 m/s, no hearing. A11.5 is final only with normal-tier bots from the
harness: `unreal_arena_build.py --bot-log <runs.jsonl>` adds the bot runs
(`{"run", "t_contact_s"}` per line) to the report.

## 7. Day and arena switch (WP11.8)

`UVerseHangarSwitchSubsystem` (VerseDecks, server): unloads one of
`DL_Hangar_Day` / `DL_Hangar_Arena`, activates the other, waits for
streaming, then raises `FVerseArenaSwitchEvent {bArenaOn, Deck: "hangar"}` on
the hub. The listeners do the rest: `AVerseGameMode` starts the match (arena
on) and the ruleset ends it with an `Unfinished` summary (arena off),
VerseDestruction resets, VerseCrew walks the crew out of the arena bounds
(`ArenaBoundsCm`). Entries: the armoury station and the Verse bar quick start
call `RequestArena`; the bridge's `lifecycle.show {reason: "quick_start_duel"}`
goes through `HandleLifecycleShow`. A switch over 2.0 s is logged (A11.4);
stuck layers finish after 10 s.

## 8. Rules (WP11.9, WP11.10)

`AVerseGameMode` is the forwarder of combat-state 10; deathmatch start values
are text in `unreal/Verse/Data/rules/deathmatch.json` (`verse.rules/1`:
respawn 3.0 s, protection 2.0 s, first to 10, no regeneration, armour 0).
The ruleset keeps per-set lines from the hub (fire, hit, gadget, fracture,
death) and raises one `FVerseSetSummary` per finished set and one
`Unfinished` summary when the arena closes or the Verse quits mid-set.

## 9. Lighting (WP11.12)

Hard work lights from the roof truss (20 spots at 18.5 m, 4300 K, 55°),
low aisle spots in the canyon (4300 K), rect lights in the booth, the
gunship cabin, the catwalk ceiling and the armoury (4500 K): all inside the
4300-6500 K of art-pipeline 8.2. All movable with shadows (art-pipeline 6.3:
Lumen only).

Haze and post are data in `layout.py` (`HAZE`, `POST`), written to
`look.json` by the build tool: exponential height fog (density 0.035,
falloff 0.12, start 4 m) plus volumetric fog with neutral grey scattering
(albedo saturation 0, art-pipeline 8.3), Lumen GI and reflections, manual
exposure. The placement schema has no volume kind, so the level owner puts
the fog actor and the post volume into `LV_Hangar` from these values (open,
below). Palette shares of art-pipeline 8.1 are measured on the rendered build.

## 10. Open items

| Item | Needs |
|---|---|
| Placement files into `unreal/Verse/Art/Placements/hangar/` and `sync_placements` into `LV_Hangar` | Graybox meshes `SM_<Family>` / `GC_<Family>` and their import records: the static gate refuses placements without records. The `deck` mode of `scripts/verse/export_unreal.py` is reserved and owned by the integration owner |
| Fog actor and post volume in `LV_Hangar` | The level owner, from `look.json` (no volume kind in `verse.placement/1`) |
| Screenshots, palette shares, perf JSON, 600 MB deck budget (A11.6), switch timing in the real level (A11.4) | The imported level and the visual lane (WP10.8) |
| A11.4 "0 pieces not Intact, 0 crew in the arena" | WP06 reset and WP15 crew listeners on `OnArenaSwitch` |
| A11.5 with bots, BG12 | WP08 decisions and WP10 Gauntlet runs |
| A11.7 1,000 breach charges on the floor | WP06 pieces and WP02 gadgets; the floor has no destructible block today |
| `lifecycle.show` wiring | WP17 calls `HandleLifecycleShow` from the bridge client |
