# Verse on Unreal: work packages

The 22 fan-out packages that build the Unreal Verse. Read `README.md`
(decisions) first, then your package below, then every contract it lists.
Facts about today's code carry a file reference; everything else here is a
plan decision.

## 0. Rules for every package

### 0.1 Ids, branches, pull requests

| Item | Rule |
|---|---|
| Package id | `WP01` to `WP22`. Placement JSON `owner` fields, import records and PR bodies use this id |
| Sub-task id | `WP<nn>.<k>`. One sub-task is one agent and one PR, sized to land in about a day of agent work |
| Branch | `claude/verse-wp<nn>-<k>-<slug>` (matches the `claude/verse-wp<nn>-*` rule `validate_ownership` reads, art-pipeline 9) |
| PR title | Conventional Commits, `type(verse): subject`, lower case, imperative (`feat(verse): add the slide move`); after landing a branch with several commits, `gh pr edit <n> --title` (architecture 8.4) |
| PR body | First line `Work-Package: WP<nn>`; second line `Sub-task: WP<nn>.<k>`; then the evidence block of `orchestration.md` 5.5 |
| Commits | English, no names of other games, studios, franchises or real firearm makes or models anywhere (README Legal; `unreal-static` scans) |

### 0.2 Ownership

| Rule | Detail |
|---|---|
| Exclusive paths | Each package writes only the paths listed under "Owned". Two packages never own the same file. A path not listed anywhere belongs to the integration owner; that includes `scripts/unreal/**` except the scripts a package lists |
| QA commands | The `Verse.QA.*` console commands of `parity.md` section 19 are registered in the Core `UVerseQaRegistry` (G0.3). Each package implements the commands of its own area in its own `Private/QA/` folder (Crew `SetDuty`, Combat `Duel.*`, Decks `View.*`, `Space.*`, UI `Stats`); WP17 owns the `qa.exec` bridge path |
| Art records | An import record (`unreal/Verse/Art/Import/**`) or MI recipe (`unreal/Verse/Art/Materials/**`) belongs to the package that owns the content folder of its asset (`contracts/art-pipeline.md` 9); placement JSON belongs to the zone owner (section 3) |
| Module split | Several packages share a C++ module; they own disjoint subfolders `Public/<Area>/` and `Private/<Area>/` of it. `<Module>.Build.cs` and the module startup file (`<Module>Module.cpp/.h`) belong to the integration owner |
| Tests | Each package owns `Private/Tests/<Area>/` inside its subfolders and `unreal/Verse/Content/Verse/Test/WP<nn>/` for fixture maps and test assets |
| Zones | Deck zones and their owners are in section 3; a zone owner writes only actors tagged `verse.zone:<zone>` (art-pipeline 9) |
| Data | Tuning JSON under `unreal/Verse/Data/<area>/` belongs to the listed package. Files marked "propose-only" are frozen by a contract change rule: the package edits them in its PR, the integration owner merges with the gate run the contract asks for |
| Contracts | Nobody but the integration owner edits `docs/verse/unreal/contracts/**`, `unreal/Verse/Source/VerseCore/**`, `unreal/Verse/Source/Verse/**`, `*.Build.cs`, `*.Target.cs`, `Verse.uproject`, `Config/Default*.ini`, `LV_<Deck>.umap`, data layers, every `.gitattributes`, `.gitignore` and `.lfsconfig`, `.githooks/**`, `scripts/unreal/fake_bridge.py` and the golden fixtures. A package that needs a change opens a request naming the item, the reason and the consumers (`orchestration.md` 3.4) |

### 0.3 Parallel work against stubs

Every package can start the day G0 lands (section 1). Where a package needs
another package's runtime behaviour, it codes against the frozen contract
and a fake it writes itself:

| Rule | Detail |
|---|---|
| Stubs and fakes | G0 ships a null stub of every contract interface in `VerseCore` (`orchestration.md` 0.3), so everything builds from day one. A package that needs richer behaviour writes its own fake in `Private/Tests/<Area>/Fakes/`, named `FFake<Interface>` or `AFake<Class>`, compiled only `WITH_DEV_AUTOMATION_TESTS`. Fakes implement the contract interface exactly; no extra methods |
| Conformance | The producing package ships `Verse.Contract.<Interface>.*` tests. When the real producer lands, the consumer re-runs its acceptance tests against it; that run is the package's final acceptance |
| Synthetic events | `UVerseEventHub` is in Core from G0, so any package can drive itself by publishing contract event structs from a test (Gore, UI, Audio, Bot do this) |
| Bridge | G0.11 ships `scripts/unreal/fake_bridge.py` with the golden fixtures of every `verse.bridge/1` message and scripted scenarios; Unreal packages that read feeds test against it, never against a live app |
| Placeholder art | Box and capsule meshes from `Content/Verse/Test/WP<nn>/`, the G0 test skeleton `SK_Test_Human` (frozen bone names, crude mesh). Never engine sample content (art-pipeline 12.3) |
| Builds | Only through `scripts/unreal/build.py`, which takes the machine-wide GPU-heavy lock (architecture 8.2). Never UBT, UAT, Blender or UnrealEditor directly |

### 0.4 Evidence

Every PR attaches what its package lists under "Evidence". Files go to
`unreal/Verse/Saved/Harness/proof/WP<nn>/<sub-task>/` (ignored; never a
folder named `evidence` or `screenshots`, architecture 8.4) and are uploaded
as CI artifacts: screenshots as PNG from `scripts/unreal/screenshot.py`
(G0.6; WP10.8's `capture.py` adds scripted cameras and the palette
measurement on top), metrics as JSON, test results as the automation report
JSON. A visible change without a screenshot of the running build is not done
(architecture 8.3). An acceptance row that names only a test asserts exactly
what the row's sub-task output says, with the numbers this file states.

### 0.5 Repo gates

Every package follows the repo gate rules of architecture 8.4: no `.fbx`,
`.wav`, `.exr`, `.gif` or video committed; no folder named `Build` (outside
`unreal/Verse/Build/`), `Models`, `Env`, `Logs`, `Dist`, `Secrets`,
`Video`, `Renders`, `Evidence`, `Recordings` or `Screenshots`; English only in
every text file including `Config/*.ini`; no user-profile paths or email
addresses in docs; no `CLAUDE.md` under `unreal/`, `art/` or `docs/`; LFS
objects pushed with the branch.

## 1. G0: foundation before fan-out (integration owner, not a package)

| # | Item | Why everyone needs it |
|---|---|---|
| G0.1 | VS 2022 Build Tools with the MSVC and Windows SDK versions 5.7 needs (not installed on the dev box on 2026-11-02), the Linux cross toolchain, git-lfs, `unreal/Toolchain/toolchains.json`, `scripts/unreal/doctor.py` | Nothing compiles without it |
| G0.2 | Contracts frozen; the conflicts of section 4 are decided in the contracts | Packages code against them |
| G0.3 | `VerseCore`: coordinate module and golden file, gameplay tags (including every `Noise.*` tag of bot 3.2), log categories, `VerseRng`, all contract structs and enums (including `FVerseInputFrame`, `FVerseGadgetEvent`, `FVerseArenaSwitchEvent`, `FVerseStationUsedEvent`, `FVerseSetSummary`), DataAsset schemas (weapon, gadget, melee, tier, adaptive, penetration, audibility, destruction tuning), `UVerseEventHub` with every delegate of combat-state 11.1, `UVerseQaRegistry`, a null stub per contract interface | Shared types |
| G0.4 | Primary module `Source/Verse/` (game instance, default pawn with `UVerseCombatStateComponent`, default classes, `UVerseSettings`); `VerseHarness` only in `VerseEditor.Target.cs`; `VerseServer.Target.cs` deleted (decision C7) | Today's targets list Harness in the Game and Server targets and no primary module exists (`unreal/Verse/Source/*.Target.cs`) |
| G0.5 | Every `*.Build.cs` with exactly the DAG edges of architecture 2; `scripts/unreal/check_build_dag.py` | Rule 1 of the DAG |
| G0.6 | `scripts/unreal/build.py`, `with_lock.py`, `test.py`, `screenshot.py`, `smoke.py`, `worktree.py` (`orchestration.md` 0.5) | Only build, test and capture entry |
| G0.7 | Art pipeline entry points (art-pipeline 2): `export_unreal.py`, `import_art.py`, `check_art_text.py`, `verse_pipeline/*`, `fbx-ue/1` calibration green, `unreal/Verse/.gitattributes` (art-pipeline 10.2) | Every art package |
| G0.8 | Empty World Partition levels `LV_Bridge`, `LV_Ops`, `LV_Engineering`, `LV_Hangar` with data layers `DL_<Deck>_Base`, `DL_Hangar_Day`, `DL_Hangar_Arena`; project collision profiles and trace channels | Zone owners place into them |
| G0.9 | `SK_Test_Human` placeholder skeleton with the frozen bone names of art-pipeline 12.1 | Movement, combat, gore tests before WP13 |
| G0.10 | First `unreal-static` and `unreal-build` lane runs, wired into `CI gate` (architecture 8.2, handed to WP10 afterwards) | A green lane is the done signal |
| G0.11 | Golden JSON fixtures for every `verse.bridge/1` message (including section 14), binary `cells.bin/1` codec vectors, `scripts/unreal/fake_bridge.py` with scripted scenarios (roster churn, busy panes, meetings, awards, lifecycle, panel), in `tests/unit/verse_host/fixtures/` and `unreal/Verse/Tests/Data/bridge/` | WP15, WP16, WP18, WP20, WP21 start on day one instead of waiting for WP17 |
| G0.12 | Repo hygiene of architecture 8.4: `unreal/Verse/.gitignore` (with `!Build/`), `.lfsconfig`, `unreal/** export-ignore`, the guarded `git lfs pre-push` line in `.githooks/pre-push`, `git lfs push` in `scripts/agent_land.py`, `scripts/unreal/forbidden_names.sha256`, today's `unreal/Verse/.gitattributes` reduced to art-pipeline 10.2 (no `.fbx`, `.wav`, `.exr`, `.glb` lines) | Without it the first Unreal PR fails the junk gate or pushes pointers without objects |
| G0.13 | Baselines and pilot (`orchestration.md` 0.8, 0.9) | Proves the pipeline before 22 packages use it |

## 2. Packages

### WP01 Movement

**Goal.** A networked, predicted first-person character with walk, sprint,
crouch, prone, lean left/right, slide, jump and mantle, whose hit bodies move
with every stance.

**Owned.** `unreal/Verse/Source/VerseMovement/**` except `Public/Anim/`,
`Private/Anim/` (WP13); `unreal/Verse/Data/movement/*.json`;
`unreal/Verse/Content/Verse/Movement/**`; `unreal/Verse/Content/Verse/Test/WP01/**`.

**Contracts consumed.** `coordinates.md` (all); `combat-state.md` 2.1 (stance,
lean `int8`, sprint/airborne/mantling flags, `IVerseMovementQuery`), 11.1
(`FVerseInputFrame`, `FVerseNoiseEvent`);
`bot.md` 3.1 (eye moves with stance and lean), 3.2 (footstep, slide, land,
mantle noise ranges), 8.3 (bot drives movement through the same input);
`destruction.md` 6.1 (low breach mantle links); architecture 3.3.

**Depends on.** G0 only. Hit bodies use `SK_Test_Human` until WP13 lands.

**Start values** (tuning in `DA_MovementTuning`, not frozen): walk 4.5 m/s,
sprint 6.5 m/s, crouch 2.2 m/s, prone 0.9 m/s; slide entry from sprint at
5.5 m/s or more, boost to 7.5 m/s, decays to crouch in at most 1.1 s,
cooldown 1.0 s; jump apex 0.55 m; mantle low ledges 0.5-1.2 m in 0.45 s, high
1.2-2.0 m in 0.85 s; lean camera offset 35 cm with 12 deg roll, enter 0.15 s;
prone enter 0.7 s, exit 0.6 s, turn cap 90 deg/s.

| # | Sub-task (one agent) | Output |
|---|---|---|
| 1.1 | `AVerseCharacter` and `UVerseCharacterMovement` scaffold; `IVerseMovementQuery`; `DA_MovementTuning` loaded from JSON | Class, interface, importer, unit tests |
| 1.2 | Input path: Enhanced Input mapping for the person, plus a server-side consumer of `FVerseInputFrame` so bot and model controllers use the identical path (`bot.md` B1) | Input component, test that both paths produce identical moves |
| 1.3 | Walk, sprint, crouch, jump with sprint as a compressed saved-move flag; sprint and mantle raise the "blocks firing" flag | Moves and flags |
| 1.4 | Prone: second half-height, horizontal prone body box, floor clearance checks, turn cap, transitions | Prone mode with tests |
| 1.5 | Slide: `MOVE_Custom` / `CMOVE_Slide`, entry rule, friction curve, decay to crouch | Slide mode |
| 1.6 | Mantle: shared ledge trace at move time on client and server, predicted `FRootMotionSource_MoveToForce`, low and high variants, mantle through a low breach link | Mantle with tests |
| 1.7 | Lean: quantised value in custom move data, camera offset and roll, spine drive value for WP13, wall check that stops leaning into geometry | Lean with tests |
| 1.8 | Noise: `Noise.Footstep.Walk/Run/Sprint`, `Noise.Move.Slide/Land/Mantle` as `FVerseNoiseEvent` on the hub (surface material for audio); crouch walk and prone crawl raise none | Noise events matching `bot.md` 3.2 |
| 1.9 | Fixture map `LV_Test_Movement`: ledges 0.5/1.0/1.5/2.0/2.1 m, 0.75 m crawl tunnel, 1.2 m crouch tunnel, slopes 30 and 46 deg, stairs, a 4 m drop, lean corners | Map under `Test/WP01/` |
| 1.10 | Netcode: correction counters per move kind; run in the netcode test (dedicated + 2 lagged clients) | Counters, test, report JSON |
| 1.11 | Hit-zone table: bone to `EVerseHitZone` map read from the physics asset; tests that lean and prone move the bodies | Table and tests |

| Id | Acceptance test | Pass |
|---|---|---|
| A1.1 | `Verse.Movement.Speeds` | Each stance's steady speed within 2 % of the DataAsset value on flat floor |
| A1.2 | `Verse.Movement.Mantle` | 1,000 seeded approaches on the fixture ledges: 0.5-2.0 m succeed at least 99.5 %; 2.1 m never mantles; time within 1 tick of the DataAsset |
| A1.3 | `Verse.Movement.Prone.Clearance` | Prone passes the 0.75 m tunnel; standing and crouch are blocked; prone never starts with less than 0.4 m clearance |
| A1.4 | `Verse.Movement.Slide` | Slide starts only from sprint at 5.5 m/s or more; ends in crouch within 1.1 s; second slide blocked for 1.0 s |
| A1.5 | `Verse.Movement.Lean.Wall` | Lean against a wall never puts the camera inside geometry (0 of 500 seeded corner poses) |
| A1.6 | Netcode smoke, 2 min, `PktLag=60 PktLagVariance=10 PktLoss=1` | At most 2 corrections per minute per client in total, at most 0.5 per minute from mantle and prone combined; lean value on the server equals the client's for every move |
| A1.7 | `Verse.Movement.InputParity` | Same `FVerseInputFrame` stream from a person and a bot controller gives the same capsule path within 0.1 cm over 60 s |
| A1.8 | `Verse.Movement.Noise` | Footstep audible ranges per stance match `DA_Audibility`; crouch walk and prone emit 0 events over 60 s |
| A1.9 | Cost | Movement for 2 pawns at most 0.3 ms server game thread per tick |

**Evidence.** Netcode report JSON with correction counts; screenshots of a
mantle, a slide and a lean in the fixture map; automation report.

### WP02 Weapons, recoil, projectiles, magazines

**Goal.** Server-authoritative, client-predicted firearms with magazines,
tactical and empty reloads, a learnable recoil pattern that really climbs,
visible 300 m/s bolts, lag-compensated per-bone hits, damage, and the two
start gadgets.

**Owned.** `Source/VerseCombat/{Public,Private}/{Weapons,Inventory,Projectiles,Damage,LagComp,Gadgets}/**`;
`unreal/Verse/Data/weapons/*.json` (including `gadgets.json`);
`unreal/Verse/Content/Verse/Combat/Abilities/**`;
`unreal/Verse/Content/Verse/Test/WP02/**`. `UVerseCombatStateComponent`
lives in `Damage/`.

**Contracts consumed.** `combat-state.md` 1-6, 11, 12, and 2.3 (gadgets);
`destruction.md` 2 (`IVersePenetrationQuery`, `IVersePieceDamage`); `bot.md`
3.2 (shot, reload and gadget noise tags); `coordinates.md`.

**Depends on.** G0 only. Fakes: WP01 (`IVerseMovementQuery`), WP03
(`TraceBolt` that returns no piece), WP13 (hit bodies: `SK_Test_Human`), WP14
(meshes: boxes), WP11 (ruleset `CanDamage` that allows all).

| # | Sub-task | Output |
|---|---|---|
| 2.1 | Weapon definition importer JSON to `DA_Weapon_*`, Graveline and Tallow start values, name check | Importer, two assets, diff test |
| 2.2 | `UVerseInventoryComponent`: slot fast array, equip and holster, owner-only replication | Component and tests |
| 2.3 | Magazine and reload state machine: tactical vs empty, commit fraction, cancel, chambered round, `FVerseReloadEvent` and reload noise | State machine and tests |
| 2.4 | Recoil: `FVerseRecoilState`, kick, accumulator, pull-down compensation, recovery; tests R1-R6 | Recoil code and tests |
| 2.5 | Spread, bloom, first-shot accuracy, seed derivation, server validation (30 cm origin, `sigma + 1.5 deg`) | Spread code and tests |
| 2.6 | Fire path: `ServerFire`, shot counter, `ClientConfirmShot`, predicted bolt reconcile and removal on `Rejected` | Prediction and netcode test |
| 2.7 | `UVerseProjectileManager`: 5 m per tick steps, latency advance capped at 250 ms, `MaxRange`, trace order pieces then bodies, penetration loop via `IVersePenetrationQuery` | Manager and tests |
| 2.8 | Lag compensation: 1 s per-bone ring buffer, 250 ms cap, query API reused by WP04 | Ring buffer and tests |
| 2.9 | Damage: `UVerseHealthSet`, GAS damage effect, zone multipliers, falloff, armor first, ruleset hooks, `FVerseDeathEvent` | Damage code and tests |
| 2.10 | Hub events Fire, Hit, Penetration, Death, Reload with the transports of combat-state 5.1 | Events and transport tests |
| 2.11 | Bolt presentation: own predicted bolt amber, opponent bolt red from `FVerseFireEvent`, impact VFX only from the cosmetic hit event; placeholder VFX until WP14.9 | Presentation component |
| 2.12 | Bulwark ability and actor (GAS, prediction key) per `combat-state.md` 2.3 | Ability, actor and tests |
| 2.13 | Breach charge ability and actor: plant, fuse, detonation through `IVersePieceDamage` with breach radius, pawn damage with self-damage per `combat-state.md` 2.3 | Ability, actor and tests |
| 2.14 | Skitter (SMG) and Longsight (DMR) data on the same schema, invariants green | Two assets |

| Id | Acceptance test | Pass |
|---|---|---|
| A2.1 | `Verse.Combat.Recoil.*` R1-R6 for every weapon asset | All green; full-magazine Graveline spray with no look input: `A_p` rises after every shot and ends at 50 % or more of the summed kick |
| A2.2 | `Verse.Combat.Damage.ZonesAndFalloff` | Table-driven, every weapon and zone at 0 m, start, mid, end and beyond, exact to 1e-4 hp. Graveline: 4 upper-torso hits kill at 25 m or less, 2 head hits kill |
| A2.3 | `Verse.Combat.FireRate` | Measured over a full magazine: Graveline 690 RPM within 1 %; Tallow never above 380 |
| A2.4 | `Verse.Combat.Reload.Times` | Tactical and empty reload times within 1 tick of the asset; tactical leaves magazine + 1; cancel before commit keeps the old magazine |
| A2.5 | `Verse.Combat.Projectile.Flight` | Speed 300 m/s within 0.5 %, zero drop over `MaxRange`, despawn at `MaxRange` plus at most 5 m |
| A2.6 | `Verse.Combat.Prediction.FireReconcile` (netcode test) | At 60 ms lag, predicted bolt origin within 1 cm of the server's; a rejected shot's bolt disappears within one round trip plus 1 tick; ammo count never diverges after reconcile |
| A2.7 | `Verse.Combat.LagComp.Rewind` | A target strafing at 6.5 m/s is hit at 60, 120 and 250 ms lag when the client aim was on it; at 300 ms the rewind clamps to 250 ms |
| A2.8 | Cost | 64 bolts in flight: projectile manager at most 0.2 ms server game thread per tick |
| A2.9 | Forbidden-name scan over `Data/weapons/*.json` and `DA_Weapon_*` | 0 hits |
| A2.10 | `Verse.Combat.Gadget.Bulwark` (GD1) | 1,000 seeded bolts at an intact Bulwark: 0 pass; 1,000 sight traces: all pass; it disappears on the tick its health reaches 0 or 25 s after deploy |
| A2.11 | `Verse.Combat.Gadget.Breach` (GD2 to GD4) | Detonation 2.5 s after the plant within 1 tick; pawn damage at 0, 1.5, 3.0 m equals 120, 60, 0 to 1e-4 hp, owner included; the target piece reaches its breach result in 100 of 100 plants |

**Evidence.** Recoil spray plot (pitch and yaw per shot, 10 seeds) as PNG
and JSON; netcode report; first-person screenshot of amber and red bolts in
flight; automation report.

### WP03 Penetration and material table

**Goal.** Bolts that pass, lose damage on, and leave glowing holes in
materials according to one table, with sightlines through holes that the
person and the bot share exactly.

**Owned.** `Source/VerseDestruction/{Public,Private}/{Penetration,Holes}/**`;
`unreal/Verse/Data/destruction/penetration.json` (propose-only);
`unreal/Verse/Content/Verse/Destruction/_Holes/**`;
`unreal/Verse/Content/Verse/Test/WP03/**`.

**Contracts consumed.** `destruction.md` 2, 5, 6.2, 10; `combat-state.md` 6;
`bot.md` 3.1 (`TestSight`); `art-pipeline.md` 5 (channels), 8.3 (colour bans).

**Depends on.** G0 only. Fakes: WP06 pieces and proxies (`AFakePiece` solid
boxes tagged with a material id); WP02 as caller (WP03 tests call `TraceBolt`
directly).

| # | Sub-task | Output |
|---|---|---|
| 3.1 | Golden fixture of `destruction.md` 2: every material at 0.5x, 1x and 3x reference thickness and powers 50, 100, 150, hand-computed cost, pass and remaining damage | Fixture JSON in `Test/WP03/` |
| 3.2 | Table importer JSON to `DA_PenetrationTable`; frozen wire order check | Importer and test |
| 3.3 | `TraceBolt`: entry and exit on current proxies, traced thickness, cost, damage multiplier, 3-piece limit, impassable materials | Query implementation |
| 3.4 | `TestSight`: `VerseSight` channel, intact glass and grating see-through, damaged glass blocks, two-point hole test | Query implementation |
| 3.5 | Bolt hole records: fast array, caps 24 per piece and 512 per arena, hole 25 turns a wall `Holed`, eviction, epoch | Records and tests |
| 3.6 | Hole rendering: 256 x 256 mask per piece on first hole, rim decal, glow (tau 1.2 s, dull red at 2.5 s, off at 4 s), 128 glowing cap | Materials and component |
| 3.7 | Physical materials on non-destructible world geometry (concrete, armor steel, hall floor) mapped to table rows | Mapping and test |
| 3.8 | Fixture map: every material at 0.5x, 1x and 3x reference thickness, hole angle rig | Map |

| Id | Acceptance test | Pass |
|---|---|---|
| A3.1 | `Verse.Destruction.Penetration.Table` | 8 materials x 3 thicknesses x 3 power levels match the hand-computed table to 1e-4; rifle through two container walls keeps 0.5625 of damage (destruction 2) |
| A3.2 | `Verse.Combat.Penetration.Budget` | Concrete, armor steel and hall floor never pass; the 4th piece always stops a bolt |
| A3.3 | `Verse.Destruction.Sight.Holes` | A ray through a 15 mm hole in 0.3 cm sheet at 30 deg off the axis passes; the same ray through a 4 cm panel fails; 10,000 seeded rays agree with the analytic test |
| A3.4 | `Verse.Destruction.Holes.Caps` | Hole 25 on a wall makes it `Holed` and clears holes; arena cap drops the oldest hole of the fullest piece |
| A3.5 | Cost | 64 `TraceBolt` calls per tick at most 0.3 ms server game thread |
| A3.6 | Palette | Glow frames at 0, 1, 2.5 and 4 s: 0 banned pixels by the rendered-pixel rule of `art-pipeline.md` 8.3 |

**Evidence.** Screenshot sequence of a hole cooling (0, 1, 2.5, 4 s);
screenshot through a hole from both sides; table test report JSON.

### WP04 Melee and finisher

**Goal.** A fast frontal knife strike (two hits kill) and a 2.5 s paired
finisher from the back or flank within 1.5 m that always kills once locked.

**Owned.** `Source/VerseCombat/{Public,Private}/{Melee,Finisher}/**`;
`unreal/Verse/Data/melee/*.json`; `unreal/Verse/Content/Verse/Combat/Finisher/**`;
`unreal/Verse/Content/Verse/Test/WP04/**`.

**Contracts consumed.** `combat-state.md` 1 (rewind), 7, 8 (finisher event
fields), 9.3, D5; `bot.md` 3.2 (knife and finisher noise); `art-pipeline.md` 12
(`Warp_Finisher`, `Weapon_L`).

**Depends on.** WP02.8 rewind (fake: current transforms), WP01 stance and
grounded flags (fake), WP13.7 paired clips (placeholder montages with root
motion only, notifies at 0.25/0.9/1.8/2.1/2.5 s), WP05 and WP18 only as event
listeners.

| # | Sub-task | Output |
|---|---|---|
| 4.1 | `UVerseMeleeDefinition` importer; classification (7.1, 7.2) as a pure function | Function and grid test |
| 4.2 | Front strike: hit delay, cone, cooldown, damage through WP02's path with `Source = Melee`, noise | Strike and tests |
| 4.3 | Finisher GAS ability: validate, lock both, server phase timeline, abort on attacker death, `FVerseFinisherEvent` reliable multicast | Ability and tests |
| 4.4 | Motion warping to `Warp_Finisher` on server and clients | Warp setup and netcode test |
| 4.5 | Finisher cameras: both third person from Locked, back to first person at 2.5 s with the weapon re-equipped; cut-to-black hook for Reduced gore | Camera handling |
| 4.6 | Victim snap to the paired pose on Locked with smoothing | Correction code |
| 4.7 | Knife presentation: predicted swing, whiff, equip | Presentation |

| Id | Acceptance test | Pass |
|---|---|---|
| A4.1 | `Verse.Combat.Melee.Classify` | Grid 0-180 deg in 5 deg steps x 0-2.5 m in 0.1 m x dz -1..1 m in 0.2 m: 100 % match with 7.2 |
| A4.2 | `Verse.Combat.Melee.Strike` | 55 damage, 2 strikes kill from 100, cooldown 0.7 s within 1 tick |
| A4.3 | `Verse.Combat.Finisher.Timeline` (netcode test) | Phase times 0.25/0.9/1.8/2.1/2.5 s within 1 tick on server and both clients |
| A4.4 | D5 | 500 seeded finishers: 100 % kill unless the attacker dies before 2.1 s; aborts leave victim health unchanged |
| A4.5 | Warp accuracy | Attacker position error at Takedown at most 5 cm, on server and on both lagged clients |
| A4.6 | Invulnerability rules | The victim takes 0 other damage during the finisher; the attacker takes damage normally |

**Evidence.** A screenshot sequence (one per phase) of a finisher from both
clients side by side; netcode timeline JSON; automation report.

### WP05 Gore and setting

**Goal.** Heavy, location-true blood (bursts, spatter on walls and floor,
wounds, pools, bloody finisher), no dismemberment, with a Reduced setting,
and provably no effect on gameplay.

**Owned.** `Source/VerseGore/**` except `VerseGore.Build.cs`;
`unreal/Verse/Content/Verse/Gore/**`; `art/verse/gore/**` (procedural texture
builders); `unreal/Verse/Content/Verse/Test/WP05/**`.

**Contracts consumed.** `combat-state.md` 8, D6; `bot.md` 3.1 (gore never
seen by the bot); architecture 2 (Core-only includes).

**Depends on.** G0 only; drives itself with synthetic hub events. WP13
character material slots for wound masks (fake: test mesh with a wound mask
parameter). D6 final run uses WP10's harness.

| # | Sub-task | Output |
|---|---|---|
| 5.1 | Hub listener; synthetic event player (hit, death, finisher streams); skip on dedicated server and `-nullrhi` | Subsystem and tool |
| 5.2 | Blood bursts per zone and bolt direction (Niagara) | VFX assets |
| 5.3 | Wall and floor spatter: own visibility traces along the bolt, decal pool, oldest-first recycling | Spatter system |
| 5.4 | Wound masks: impact in bone space to a mask on the character material, up to 16 per character | Mask system |
| 5.5 | Pools under bodies: growth over 4 s, recycled | Pool system |
| 5.6 | Finisher gore driven by `FVerseFinisherEvent` phases | Finisher effects |
| 5.7 | Reduced level: neutral impact flash, no decals, cut to black Takedown to Recover; live switch purges existing gore | Setting handling |
| 5.8 | Budget counters reported to the harness; D6 hash test | Counters and test |

| Id | Acceptance test | Pass |
|---|---|---|
| A5.1 | `Verse.Gore.NoGameplayEffect` (D6) | Same seeded 10-minute bot-vs-bot match with Full and Reduced: replicated state hash equal on every tick |
| A5.2 | Include scan | `Source/VerseGore/**` includes no header from `VerseCombat`, `VerseBot` or `VerseDestruction` |
| A5.3 | No collision | 1,000 traces on every channel through decals, pools and blood particles hit nothing |
| A5.4 | Budget | At most 256 spatter decals, 16 pools, 16 wounds per character alive; `gore_storm` (30 hits/s for 60 s) at most 0.3 ms GPU at 1440p and 0.05 ms game thread per hit |
| A5.5 | Reduced | 1,000 hits leave 0 blood decals, particles or wounds; cut to black starts and ends within 1 frame of Takedown and Recover |

**Evidence.** Screenshot pairs Full vs Reduced for a body hit, a wall
spatter, a pool and a finisher; D6 hash log; budget JSON.

### WP06 Destruction and repair drones

**Goal.** Walls, cover, containers, glass, catwalks and ceiling panels break
under server authority with client-side debris, nav updates, and drones that
rebuild them after about 60 s; the hall floor never breaks.

**Owned.** `Source/VerseDestruction/**` except `Penetration/`, `Holes/` (WP03)
and `VerseDestruction.Build.cs`; `unreal/Verse/Content/Verse/Destruction/**`
except `_Holes/`; `art/verse/kit/destructible/**`;
`unreal/Verse/Data/destruction/tuning.json` (propose-only);
`unreal/Verse/Content/Verse/Test/WP06/**`.

**Contracts consumed.** `destruction.md` (all); `art-pipeline.md` 4.2
(`destructible` block), 5, 13; architecture 4, 7.

**Depends on.** G0.7 art pipeline (hard for Geometry Collections), WP03 holes
(fake: no-op), damage sources (tests call `ApplyPieceDamage` directly).

| # | Sub-task | Output |
|---|---|---|
| 6.1 | Spike: Blender Voronoi fracture as code to `SM_<Piece>_Frac` to `GC_<Piece>`; fallback editor fracture with the same seed; written verdict | Spike report and one working piece |
| 6.2 | Builders for six classes (wall panel 1.2/2.4/4.8 m, cladding wall, container wall, glass pane, catwalk segment, ceiling panel), solid with the material's reference thickness (`destruction.md` 9, decision C4) | Builders, exports |
| 6.3 | Per-state proxy meshes and up to 4 Holed and Breached variants per piece | Proxies |
| 6.4 | `AVerseDestructible`, state machine, `DA_PieceManifest` (GUID order, hash), manager fast array, `IVersePieceDamage`, `IVersePieceQuery` | Core runtime |
| 6.5 | Fracture events and client debris: strain field from seed, `VerseDebris` channel, caps and lifetimes | Debris system |
| 6.6 | Breach radius (150 cm) effects, forward-only transitions | Breach handling |
| 6.7 | Nav: dirty bounds +50 cm, at most 4 tiles in flight, mantle links for low breaches, drop links for destroyed catwalks | Nav updates |
| 6.8 | Repair drones: dock, queue order, flight, durations, encroachment wait, interruption, 30 HP target | Drone actor and tests |
| 6.9 | Full reset: epoch, burst under 16 KB, drones recalled, nav rebuilt | Reset |
| 6.10 | `UVerseDestructibleValidator`: watertight, thickness by ray sampling, proxies, GC, manifest | Validator in both lanes |
| 6.11 | `destruction_storm` scenario and budget counters | Scenario and JSON |

| Id | Acceptance test | Pass |
|---|---|---|
| A6.1 | `Verse.Destruction.States` | Every class follows table 3.2 transitions; bullets never take a wall past Holed; floor, concrete and armor steel never change |
| A6.2 | `Verse.Destruction.LateJoin` | A client joining after 200 changes builds the same proxy set as the server (0 mismatches) without spawning debris |
| A6.3 | `destruction_storm` | 400 debris bodies max (150 Low), 40 per fracture, 32 GC actors, physics at most 2 ms, at most 64 fracture events/s, state items about 20 bytes |
| A6.4 | `Verse.Destruction.Nav` | A breach is navigable within 100 ms in 100 of 100 trials |
| A6.5 | `Verse.Destruction.Repair` | Repair starts 60 s after the last damage within 1 tick; damage during repair returns the piece to `RepairFrom`; downed drone cancels; at most 3 drones active; completion waits while a pawn overlaps |
| A6.6 | Validator | Fails a double-plane wall and a missing proxy; passes all shipped pieces |
| A6.7 | Determinism of gameplay | Server and 2 clients agree on every proxy state and hole set after a 10-minute storm (hash per second) |

**Evidence.** Screenshots of each class in every state; a 10-frame breach
sequence; drone repair before, during, after; storm budget JSON; spike
report.

### WP07 Bot perception and belief map

**Goal.** The fairness boundary: a perception service that turns world truth
into percept frames with honest error, and a belief grid that tracks where
the opponent probably is from those percepts only.

**Owned.** `Source/VerseCombat/{Public,Private}/Perception/**`
(`UVersePerceptionService`); `Source/VerseBot/{Public,Private}/Belief/**`
(grid, opponent estimates, `FVersePieceBelief`);
`unreal/Verse/Content/Verse/Test/WP07/**`.

**Contracts consumed.** `bot.md` 1 (B2), 2, 3, 4, 10 (F2, F3, F7);
`destruction.md` 6.2; `combat-state.md` 5.1 (noise events).

**Depends on.** G0 only. Fakes: WP01 eye and stance (fake pawn with the
`Camera` bone of `SK_Test_Human`, decision C3), WP03 `TestSight` (plain trace
on `VerseSight`), WP06 piece query; Recast nav on its fixture maps.

| # | Sub-task | Output |
|---|---|---|
| 7.1 | Service skeleton: register observers, one frame per tick, per-observer RNG stream, profile from tier | Service |
| 7.2 | Sight: 55 deg cone, 55-80 deg peripheral band, 2 m awareness, 8 sample points, `VisibleMask`, dark-zone factor, ADS cone | Sight percepts |
| 7.3 | Hearing from `DA_Audibility`: error model, line-of-sight factor 1.5, level guess 0.9 / 0.7 | Heard percepts |
| 7.4 | Bolt, hurt, HUD and kill-feed percepts | Percepts |
| 7.5 | Belief grid from nav: 1 m columns x levels, 8-neighbour plus links, rebuild on believed nav change | Grid |
| 7.6 | Update rules: predict, clear, sighting, heard, hurt wedge, kill feed spawn prior, normalise with 1 % prior | Update step |
| 7.7 | Derived values `TopCluster`, `Confidence`, `SupportAge`, `Spread`, belief states; opponent health and ammo estimates | Read API |
| 7.8 | Piece belief and cover dependency sets | Piece belief |
| 7.9 | Fairness tests F2, F3 and scenario `wall_opened_unseen` | Tests |
| 7.10 | Dev-only belief heatmap overlay for screenshots | Debug draw |

| Id | Acceptance test | Pass |
|---|---|---|
| A7.1 | F2 percept boundary | Opponent behind opaque piece and silent: 0 sightings and 0 heard over 60 s; behind a hole: seen only when `TestSight` passes; crouch walk at 3 m: never heard |
| A7.2 | Heard error | Over 10,000 samples error sd within 10 % of the model sd; 0 percepts equal to the true location |
| A7.3 | F3 counterfactual | 20 seeds: input frames bit-identical up to the first differing percept tick |
| A7.4 | Belief tracking | Sighting, then 3 s hidden movement at 4.5 m/s on the fixture: `TopCluster` contains the true position in at least 70 % of 200 trials |
| A7.5 | Mass | Sum 1 within 1e-6 after every step; no cell at exactly 0 |
| A7.6 | Cost | Belief step at most 0.05 ms with 6,000 cells; perception at most 0.15 ms per observer per tick |
| A7.7 | `wall_opened_unseen` | No bot plan uses a breach before the bot perceives it |

**Evidence.** Heatmap overlay screenshots at sighting, +1 s, +3 s; F2/F3
report JSON; cost JSON.

### WP08 Bot decisions, EQS, learning

**Goal.** A bot brain that picks tactics by utility with hysteresis, finds
cover, peeks, flanks, breaches, wall-shoots only with authority, stalks for
finishers, and learns the person within one match.

**Owned.** `Source/VerseBot/{Public,Private}/{Controller,Brain,Tactics,Eqs,Learning,Audit}/**`;
`unreal/Verse/Content/Verse/Bot/**` except `Tiers/` (WP09);
`unreal/Verse/Content/Verse/Test/WP08/**`.

**Contracts consumed.** `bot.md` 1, 2, 4.5, 5, 6, 7, 10 (F1, F4, BR1, L1);
`destruction.md` 6.1; `combat-state.md` 2.1 (`BotTier`, `BotEffectiveSkill`),
2.3 (gadgets), 9.3 (spawn protection).

**Depends on.** G0 only. Fakes: WP07 (scripted `FVersePerceptFrame` streams
and a fake belief), WP09 aim and reflexes (fixed reaction, perfect follow),
WP01 and WP02 input (fake pawn that records the input frame), WP02.12/2.13
gadgets for the Bulwark and Breach states (fake abilities).

| # | Sub-task | Output |
|---|---|---|
| 8.1 | `AVerseBotController`, virtual input device, `FVerseBotBrainCore::Think`, record and replay harness (BR1); writes `BotTier` and `BotEffectiveSkill` into its player state | Controller and replay |
| 8.2 | StateTree schema, utility selection, +0.18 hysteresis, noise, 0.4 s dwell, forced re-decide triggers | Tree core |
| 8.3 | States Attack, Hold (Go, Hide, Peek), Retreat, Reload, Search | States |
| 8.4 | States Flank and StalkForFinisher | States |
| 8.5 | States DeployBulwark, Breach, Wallbang with authority 4.5 | States |
| 8.6 | Belief EQS contexts; `EQS_Cover`, `EQS_PeekCorner` | Queries |
| 8.7 | `EQS_WallbangSpot`, `EQS_BreachSpot`, `EQS_FinisherApproach` | Queries |
| 8.8 | `UVerseBeliefNavFilter` | Filter |
| 8.9 | `UVerseBotMatchMemory`: heatmaps, peek habits, ranges, route counts, habits; biases; weight bounds; reset | Learning |
| 8.10 | `FVerseBotFireAudit` log and classifier | Audit |
| 8.11 | Make `check_bot_isolation.py` (WP10) pass over `Source/VerseBot/**` | Clean scan |

| Id | Acceptance test | Pass |
|---|---|---|
| A8.1 | BR1 replay | 10 recorded 5-minute streams replay bit-identical |
| A8.2 | F1 isolation | 0 violations |
| A8.3 | F4 fire audit | 0 unclassified shots over 1,000 bouts |
| A8.4 | BG12 health | `timeToContactS` median at most 25 s against `hider`; at most 1 stuck event per 10 min; bot total at most 0.5 ms p99 per tick (decision 0.1 ms, EQS 0.2 ms amortised) |
| A8.5 | BG8 learning | Hard vs `repeek`, `watcher`, `camper`: `learningDelta` at least +0.05 and at least 0.03 better than learning off |
| A8.6 | BG9 reset and L1 | Nothing carried into match 2; no learned data on disk or on the bridge (file and frame scan) |
| A8.7 | BG4 tricks | Every trick vs hard: bout win rate at most 0.50 and kill share upper bound at most 0.55 |

**Evidence.** Balance report `verse.balance/1` for BG4, BG8, BG9, BG12; one
annotated screenshot per state (presentation overlay); fire audit sample.

### WP09 Bot aim, tiers, adaptive

**Goal.** Human-limited aim (reaction, OU wander, turn rate, lead, recoil
control), reflexes and fire discipline, the three tiers as data, and the
adaptive mode.

**Owned.** `Source/VerseBot/{Public,Private}/{Aim,Reflexes,Tiers,Adaptive}/**`
(including the `VerseImportBotTiers` commandlet);
`unreal/Verse/Data/bot/tiers.json`, `adaptive.json` (propose-only, merged with
a green nightly gauntlet per `bot.md` change rule);
`unreal/Verse/Content/Verse/Bot/Tiers/**` (generated assets);
`unreal/Verse/Content/Verse/Test/WP09/**`.

**Contracts consumed.** `bot.md` 2, 8, 9 (schema, floors, caps), B4;
`combat-state.md` 4 (recoil pattern the bot compensates).

**Depends on.** G0 only. Fakes: WP02.1/2.4 weapon assets and recoil (G0 test
weapon asset with the start curves), WP07 sight percepts (scripted), WP01
stance input (fake pawn). Gate runs need WP08 and WP10.

| # | Sub-task | Output |
|---|---|---|
| 9.1 | Tier import commandlet JSON to assets, CI diff check, floor and cap validation | Commandlet and test |
| 9.2 | Aim controller: reaction sampling, track latency and extrapolation, acquire error, OU wander, turn cap, stiffness, lead | Aim model |
| 9.3 | Recoil control: predictive pattern pull-down, residual correction after track latency | Recoil control |
| 9.4 | Fire discipline: tolerance, bursts, ADS range, elite taps beyond 30 m, no fire on a protected target | Fire gate |
| 9.5 | Reflexes: stance, lean, slide, prone, sound discipline, knife, finisher, pistol switch | Reflex layer |
| 9.6 | No-sight fire: suppression 0.35 s, prefire rule | Fire modes |
| 9.7 | Adaptive controller: window, deadband, gain, step cap, warmup, apply at respawn, interpolation | Adaptive |
| 9.8 | Tuning loop with the harness: tier patch proposals until BG1-BG3, BG6, BG7, BG10 pass | Patches and reports |

| Id | Acceptance test | Pass |
|---|---|---|
| A9.1 | `Verse.Bot.Aim.OU` | Stationary sd within 5 % of `AimNoiseDeg` over 100,000 ticks (pitch x 0.6) |
| A9.2 | `Verse.Bot.Aim.Reaction` | Mean within 3 % of `ReactionMs`, 0 samples under the 0.6 x mean floor over 10,000 draws |
| A9.3 | `Verse.Bot.Aim.TurnCap` | 0 ticks above `TurnRateDegS` |
| A9.4 | `Verse.Bot.Aim.Recoil` | Remaining pattern climb over a 30-round spray equals (1 - `RecoilPatternComp`) within 0.05 for every tier |
| A9.5 | `Verse.Bot.Adaptive` | Steps never above 0.05, `s` in [0, 1], no change inside the deadband or before 4 kills, applied only at respawn |
| A9.6 | Gates | BG1, BG2: bout win rate at least 0.75 and kill share lower bound at least 0.56; BG3: elite vs normal at least 0.90 and kill share at most 0.85; BG6: skilled vs elite 0.40 within 0.06; BG7: average vs normal 0.45-0.65; BG10: person share 0.40-0.60 over kills 30-60 |

**Evidence.** Nightly gauntlet report with BG1-BG12; aim trace plots per tier
(error vs time for 5 engagements); adaptive `s` trace.

### WP10 Harness

**Goal.** Autonomous proof: CI lanes, netcode test, headless bot-vs-bot
balance runs with gates, perf capture, screenshots and evidence tooling.

**Owned.** `Source/VerseHarness/**` except `VerseHarness.Build.cs`;
`unreal/Verse/Harness/**`; `unreal/Verse/Data/bot/person_models.json`
(propose-only); `scripts/unreal/{balance,capture,perf,netcode,check_bot_isolation,check_forbidden_names,check_lfs,done_check}.py`
(the hash list `forbidden_names.sha256` stays with the integration owner);
`.github/workflows/unreal-static.yml`, `unreal-build.yml`,
`unreal-gauntlet.yml`, `unreal-perf.yml` (handed over after G0.10; the `ci.yml`
jobs and `gate.needs` entries that make them required stay with the
integration owner, architecture 8.2);
`tests/unit/unreal_scripts/**`.

**Contracts consumed.** `bot.md` 10, 11; `combat-state.md` 12;
`destruction.md` 10 (`destruction_storm`); architecture 7, 8;
`art-pipeline.md` 14 (static gates).

**Depends on.** G0.6 and G0.10. Runs with a null brain until WP08 lands; every
other package plugs scenarios in.

| # | Sub-task | Output |
|---|---|---|
| 10.1 | `unreal-static`: DAG check, forbidden-name scan (hashed list, architecture 8.4), forbidden folder names, LFS pointers and remote objects, size gate, clang-format, licence ledger, art text checks; workflow policy (`permissions:`, SHA-pinned actions, `gate.needs`) | Lane |
| 10.2 | `unreal-build`: self-hosted, fork guard, concurrency plus lock, Win64 Editor and Game, Linux Game cross build, automation under `-nullrhi` | Lane |
| 10.3 | Netcode runner: dedicated plus 2 lagged clients, 2-minute smoke, correction and reconcile counters, Iris on and off nightly | Runner and lane step |
| 10.4 | Gauntlet controller, `AVerseModelController`, scenario schema, report `verse.balance/1` | Controller and schema |
| 10.5 | `balance.py`: sets, `--jobs`, seeds, patches, Wilson intervals, gates BG1-BG12, F1-F7, L1, BR1 | Driver |
| 10.6 | Speed measurement and bout-count calibration (architecture risk RK1) | Speed report, bout table |
| 10.7 | `unreal-perf`: fixed replay, Insights and `stat` parsing, NVML VRAM, budgets of architecture 7, quiet hours | Lane |
| 10.8 | `capture.py`: scripted camera, screenshots, palette share measurement (art-pipeline 8.1), evidence folder layout | Tool |
| 10.9 | Person models and the 17 tricks as model controller overrides | Models |
| 10.10 | F5 hidden-bearing statistic (nightly), F6 symmetry check | Checks |
| 10.11 | `done_check.py`: the Unreal lane status the repo done gate can call (hook line added by the integration owner) | Script |

| Id | Acceptance test | Pass |
|---|---|---|
| A10.1 | Static lane | Runs on GitHub-hosted in at most 5 minutes, with LFS off; fails each of: a planted forbidden name (from a test-only hash), a non-pointer `.uasset`, a pointer whose object is missing on the remote, a 51 MB LFS object, a new Build.cs edge, a folder named `Renders` under `unreal/` |
| A10.2 | Fork safety | Static check of the workflows: no self-hosted job can run on `pull_request` from a fork |
| A10.3 | Harness speed | At least 20x real time per process at `-nullrhi`, or a measured figure with bout counts recomputed so gate intervals are at most 0.06 wide |
| A10.4 | Gate math | Gates computed on a fixture report equal a hand calculation |
| A10.5 | Perf stability | Two runs of the same replay differ by at most 3 % in average fps and p99 frame time |
| A10.6 | Lock | Two concurrent `build.py` calls serialise; neither fails |

**Evidence.** Links to green runs of each lane; speed report; sample
`report.json`; perf JSON with a screenshot from the replay.

### WP11 Hangar arena and combat mode switch

**Goal.** Deck 4 turns from a normal deck into a dense 50 x 40 m, three-level
destructible arena on demand and back, running the endless 1v1 deathmatch.

**Owned.** Hangar zones `shell`, `arena_canyon`, `arena_shuttle`,
`arena_booth`, `arena_catwalks`, `armoury` (placement JSON,
`Content/Verse/Decks/Hangar/<Zone>/`, their external actors);
`art/verse/decks/hangar/**` except `zones/lift_lobby.py` and
`zones/day_stations.py` (WP12);
`Source/VerseDecks/{Public,Private}/HangarSwitch/**`;
`Source/VerseCombat/{Public,Private}/Rules/**` (`AVerseGameMode`,
`UVerseRuleset_Deathmatch`, `AVerseSpawnPoint`, spawn selection and
protection); `unreal/Verse/Data/rules/*.json`;
`unreal/Verse/Content/Verse/Test/WP11/**`.

**Contracts consumed.** `combat-state.md` 9, 10; `destruction.md` 11;
`art-pipeline.md` 4, 9, 13; `coordinates.md` 3.1, 3.2; `bridge-protocol.md` 12
(`quick_start_duel`).

**Depends on.** G0.7 and G0.8; WP06 destructible classes (fake: static pieces
with a valid `destructible` block), WP12 deck loading (fake: load
`LV_Hangar` directly), WP02 loadout, WP15 only as an event listener.

| # | Sub-task | Output |
|---|---|---|
| 11.1 | Arena layout spec and graybox: zone inside the 100 x 62 m hall, 3 levels, lanes, cover rhythm, at least 8 spawns | Spec in `docs/verse/unreal/arena.md`, graybox placements |
| 11.2 | Hangar shell for Unreal: solid walls, floor never breaks, ceiling 21 m | Shell builder and export |
| 11.3 | `arena_canyon`: container rows with destructible walls, 3.6 m aisles | Zone |
| 11.4 | `arena_shuttle`: walkable gunship as a mid building | Zone |
| 11.5 | `arena_booth`: glazed lookout with breakable glass | Zone |
| 11.6 | `arena_catwalks`: upper level, catwalk segments, ceiling panels, launch well crossing | Zone |
| 11.7 | `armoury`: loadout room geometry, station placements for WP16 and WP18 | Zone |
| 11.8 | Day/arena switch: data layers, `FVerseArenaSwitchEvent` on the hub (crew out of the hall, full destruction reset and nav rebuild happen in the listeners; VerseDecks never includes Crew or Destruction) | Switch subsystem |
| 11.9 | Game mode forwarder, deathmatch ruleset, `AVersePlayerState`, set logic (first to 10) and `FVerseSetSummary` per set and for the unfinished set on leave, D1-D4 | Rules |
| 11.10 | Spawn points, selection 9.2, protection 9.3 | Spawns |
| 11.11 | Flow analysis tool: sightline length histogram, time-to-contact from bot runs | Tool and report |
| 11.12 | Lighting pass: Lumen, hard work lights, haze, palette shares | Lighting |

| Id | Acceptance test | Pass |
|---|---|---|
| A11.1 | Arena geometry | Walkable arena bounds at most 50 x 40 m; 3 levels each at least 15 % of nav area; nav is one connected island per agent type |
| A11.2 | Spawns | At least 8; every spawn pair at least 20 m path apart |
| A11.3 | `Verse.Combat.Deathmatch.*` D1-D4 | 200 seeded deaths: respawn at 3.0 s within 1 tick; chosen spawn out of sight whenever a candidate is and farthest by path; 0 damage taken while protected; protection ends on the tick of the first own shot |
| A11.8 | Set summary | 50 scripted sets: one `FVerseSetSummary` each with kills matching the server log; leaving mid-set raises one `Unfinished` summary |
| A11.4 | Switch | Day to arena and back each at most 2.0 s; after either, 0 pieces not Intact, 0 crew pawns inside arena bounds |
| A11.5 | Flow | Normal vs normal median time to contact 6-15 s; longest unbroken sightline at most 40 m; BG12 with `hider` at most 25 s |
| A11.6 | Budgets | Hangar deck content at most 600 MB; nightly perf 120 fps average and p99 at most 11 ms at 1440p High in the duel replay |
| A11.7 | Floor | 1,000 breach charges on the floor change nothing |

**Evidence.** Top-down and four eye-level screenshots per zone; day and
arena screenshots of the same camera; flow report; perf JSON.

### WP12 Bridge, ops and engineering decks

**Goal.** The three agent decks and the hangar's day zones in Unreal, at
parity with today's rooms, sockets and stations, with deck loading, lift
travel, cameras and the deck world actions.

**Owned.** All zones of `bridge`, `ops`, `engineering` (placements, content
folders, external actors) and hangar zones `lift_lobby`, `day_stations`;
`art/verse/decks/{bridge,ops,engineering}/**`,
`art/verse/decks/hangar/zones/{lift_lobby,day_stations}.py`;
`art/verse/kit/**` except `kit/destructible/**` (WP06);
`unreal/Verse/Content/Verse/Kit/**`; the kit and prop material instances
and their recipes (`contracts/art-pipeline.md` 9); `Source/VerseDecks/**` except
`HangarSwitch/` (WP11), `Stations/` (WP16) and `VerseDecks.Build.cs`;
`unreal/Verse/Content/Verse/Test/WP12/**`.

**Contracts consumed.** `art-pipeline.md` (all); `coordinates.md`;
`bridge-protocol.md` 9 (`daily_visit`, `deck_discovered`, `inspection`).

**Depends on.** G0.7 and G0.8 (hard for import; builders and JSON proceed in
parallel), WP14.1 masters (fake: G0 default master), WP17 (fake bridge).

| # | Sub-task | Output |
|---|---|---|
| 12.1 | Deck loading, World Partition streaming, lift travel, deck manifest import (rooms, sockets, stations) | Deck subsystem |
| 12.2 | Architecture kit: 42 pieces exported with collision and MI recipes | Kit assets |
| 12.3 | Props kit by category | Prop assets |
| 12.4 | Bridge deck zones | Zones |
| 12.5 | Ops deck zones | Zones |
| 12.6 | Engineering deck zones (the reactor shaft stays as a deck feature, no duel) | Zones |
| 12.7 | Hangar `lift_lobby` and `day_stations` (arrivals, `create_agent` counter, shuttle-to-lift path sockets) | Zones |
| 12.8 | Lighting and look per deck in Military-Industrial Noir | Lighting |
| 12.9 | Space view outside the windows from the CC0 ledger textures | Space view |
| 12.10 | Deck cameras: overview, third and first person, mouse look, focus with the return key | Camera rig |
| 12.11 | World action reporters: `daily_visit`, `deck_discovered`, `inspection` | Reporters |

| Id | Acceptance test | Pass |
|---|---|---|
| A12.1 | Parity of content | Rooms, sockets and stations per deck equal today's manifests (`public/verse/decks/<id>/manifest.json`) 100 % by id |
| A12.2 | Loading | Cold deck load at most 4 s, lift travel at most 3 s on the reference box |
| A12.3 | Palette | Four reference views per deck within the caps of art-pipeline 8.1; 0 banned pixels by the rendered-pixel rule of art-pipeline 8.3 |
| A12.4 | Perf | 120 fps average at 1440p High per deck walk replay; VRAM at most 6 GB; deck content at most 600 MB |
| A12.5 | World actions | Golden bridge messages for each action; `inspection` sent once all rooms of a deck were visited |
| A12.6 | Art validation | `validate_assets` and `validate_ownership` green for every zone |

**Evidence.** Side-by-side sheet: today's eye-level view and the Unreal view
of the same spot for each room; palette report; load-time JSON.

### WP13 Characters, FPS skeleton, animations

**Goal.** One original FPS-grade human rig for player, bot and crew, body
variants and uniforms, all locomotion, weapon, finisher, death and crew
clips, and the animation runtime.

**Owned.** `art/verse/characters/**` (including `rig_fps.py`);
`unreal/Verse/Content/Verse/Characters/**` (`Rig/` under `git lfs lock`);
`unreal/Verse/Content/Verse/Animations/**`;
`Source/VerseMovement/{Public,Private}/Anim/**`; the import records and MI
recipes of those folders (art-pipeline 9; weapon skeletal meshes are WP14's);
`unreal/Verse/Content/Verse/Test/WP13/**`.

**Contracts consumed.** `art-pipeline.md` 3, 10, 11, 12; `combat-state.md` 7.4
(phase times), 2.1; `bot.md` 3.1 (the eye is the `Camera` bone, decision C3);
WP01 move set.

**Depends on.** G0.7 skeletal import; WP01 movement query (fake anim pawn).

| # | Sub-task | Output |
|---|---|---|
| 13.1 | `rig_fps.py`: `SKEL_Verse_Human` bones of 12.1, IK and weapon bones, `Camera`, A-pose; `SK_Calib_Rig` check | Rig |
| 13.2 | Skinning of the two CC0 body variants, at most 8 influences; garments: commander, crew, black tactical opponent | Meshes |
| 13.3 | `PHYS_Verse_Human` hit-zone bodies; `IKRig_Verse_Human` chains | Physics asset, IK rig |
| 13.4 | Locomotion: stand, crouch, prone idles and 8-way moves, sprint, jump, fall, land, slide, mantle low and high with root motion, lean poses | Clip set |
| 13.5 | First-person body: head hidden for the owner, first-person rendering without wall clipping, aim offsets | FP setup |
| 13.6 | Weapon clips per class at 60 fps: idle, ADS, fire, tactical and empty reload, equip, holster, knife strike | Clip set |
| 13.7 | Paired finisher clips with `Warp_Finisher` and root motion, markers at 0.25/0.9/1.8/2.1/2.5 s | Clip pair |
| 13.8 | Deaths, hit reacts, third-person clips for kill cam | Clip set |
| 13.9 | Crew clips: sit, type, stand, walk, talk, bunk | Clip set |
| 13.10 | `UVerseAnimInstance`: state machine from `IVerseMovementQuery`, foot IK, off-hand IK to `SOCKET_Support`, lean over three spine bones | Anim runtime |

| Id | Acceptance test | Pass |
|---|---|---|
| A13.1 | Bone names | 100 % match with art-pipeline 12.1; at most 200 bones; at most 8 influences per vertex |
| A13.2 | Finisher markers | Within 1 frame (30 fps) of the phase times |
| A13.3 | Off-hand IK | Hand to `SOCKET_Support` error at most 0.5 cm in every idle and ADS pose of every weapon |
| A13.4 | Foot IK | On 30 deg slopes and stairs no foot penetration above 1 cm |
| A13.5 | First-person clipping | Weapon 20 cm from a wall: 0 weapon pixels hidden by the wall in the owner's view |
| A13.6 | Cost | Animation at most 0.4 ms game thread for 2 FPS characters plus 12 crew |
| A13.7 | Licence | Every imported mesh cites a ledger row or `own` |

**Evidence.** Turnaround screenshots of each body and uniform; first-person
screenshots per weapon idle, ADS, reload; finisher contact sheet;
anim cost JSON.

### WP14 Weapon models, materials, style

**Goal.** The look: master materials, post-process and LUT for
Military-Industrial Noir, original fully black weapons on their own
skeletons, and weapon VFX.

**Owned.** `art/verse/weapons/**`; `unreal/Verse/Content/Verse/Weapons/**`;
`unreal/Verse/Content/Verse/Materials/Master/**` (under the integration
owner's `git lfs lock`, merged by the integration owner);
`unreal/Verse/Content/Verse/Materials/Instances/Weapons/**`;
`unreal/Verse/Content/Verse/VFX/Weapons/**`;
`unreal/Verse/Content/Verse/PostProcess/**`; the import records and MI
recipes of these folders (art-pipeline 9); `art/verse/style-unreal.md`.

**Contracts consumed.** `art-pipeline.md` 6, 7, 8, 11, 12.2; README Look and
Arsenal; `combat-state.md` 3 (`BoltColorOwn`, `BoltColorFoe`).

**Depends on.** G0.7; weapon ids from WP02.1 (fake: G0 test ids).

| # | Sub-task | Output |
|---|---|---|
| 14.1 | Master materials (opaque triplanar, UV PBR, decal, emissive, glass, hole-mask aware) with documented parameters; palette ban check in `validate_assets` | Masters |
| 14.2 | Post-process: AgX-matching LUT, exposure, fog and haze, work-light profiles; reference views | Look profile |
| 14.3 | Weapon design sheet: original silhouettes, fictional names, fully black, a checklist that no part copies a real firearm | Sheet in `style-unreal.md` |
| 14.4 | Graveline rifle: model, skeleton (`Magazine`, `Bolt`, `Trigger`, sockets) | Assets |
| 14.5 | Tallow pistol | Assets |
| 14.6 | Hookbill knife (`Root`, `SOCKET_Tip`) | Assets |
| 14.7 | Bulwark and breach charge models | Assets |
| 14.8 | Skitter SMG and Longsight DMR | Assets |
| 14.9 | Bolt VFX (amber own, red foe), muzzle, impact sparks and scorch | VFX |
| 14.10 | First-person shading pass: black steel, wear, oil, viewmodel lighting | Material instances |

| Id | Acceptance test | Pass |
|---|---|---|
| A14.1 | Weapon budgets | At most 24 bones and 60 k triangles first person; all sockets of 12.2 present |
| A14.2 | Fully black | Base colour luminance at most 0.06 (linear) on every weapon material; no gold or coloured trim |
| A14.3 | Banned colours | 0 banned pixels by the rendered-pixel rule of art-pipeline 8.3 in every reference view and VFX frame |
| A14.4 | LUT | Mean CIEDE2000 at most 3 against AgX reference renders of a 24-patch chart |
| A14.5 | VFX cost | 64 bolts in flight at most 0.1 ms GPU at 1440p |
| A14.6 | Names | Forbidden-name scan over assets, records and the design sheet: 0 hits |

**Evidence.** Weapon turnarounds and first-person shots under work light;
chart comparison image and numbers; reference view set.

### WP15 Crew and daily life

**Goal.** Officers (society agents) and technicians (coding panes) live on the
decks from real app data: duty status, ranks, routines, arrivals, meetings,
the pet drone.

**Owned.** `Source/VerseCrew/**` except `VerseCrew.Build.cs`;
`unreal/Verse/Content/Verse/Crew/**`; `unreal/Verse/Data/crew/*.json`;
`unreal/Verse/Content/Verse/Test/WP15/**`.

**Contracts consumed.** `bridge-protocol.md` 4 (roster, duty values), 7
(meetings, groups), 9 (`walk_together`, `team_briefing`), 11 (`agent.open`),
14 (`companion` topic); `combat-state.md` 11.1 (`FVerseArenaSwitchEvent`);
`coordinates.md`.

**Depends on.** G0 only (fake bridge from G0.11). Fakes: WP17 bridge client
feeds, WP13 crew rig and clips (`SK_Test_Human`), WP12 sockets (fixture deck).

| # | Sub-task | Output |
|---|---|---|
| 15.1 | Crew manager: pawns from `roster.snapshot` and `roster.delta`, ranks and uniforms | Manager |
| 15.2 | Duty status presentation for `working`, `waiting`, `idle`, `paused`, `error` with fallback | Presentation |
| 15.3 | Routines: seats, desks, bunks, walks over Recast with crowd avoidance | Routines |
| 15.4 | New agent arrival: spawn at the shuttle, walk to the lift (as `life/cast.ts:81-89`) | Arrival |
| 15.5 | Meetings and groups: gather on `meetings.update`, `team_briefing` action | Meetings |
| 15.6 | Pet drone from the `companion` topic, follow and `walk_together` | Pet |
| 15.7 | Hide crew from the hall on `FVerseArenaSwitchEvent` | Listener |
| 15.8 | Interaction: select crew, nameplate, `agent.open` | Interaction |
| 15.9 | Perf pass for 40 crew | Profile |

| Id | Acceptance test | Pass |
|---|---|---|
| A15.1 | Spawn | 40 agents plus 8 panes spawn within 1 s of the snapshot; a delta applies within 200 ms |
| A15.2 | Duty mapping | Each of `working`, `waiting`, `idle`, `paused`, `error` maps to its presentation; an unknown value maps to `idle` (bridge 4.2 fallback) |
| A15.3 | `walk_together` | Simulated walk sends one action per 50 m with the drone within 2.5 m, none during the 20 s cooldown |
| A15.4 | Arena | 0 crew pawns inside arena bounds 2 s after the switch |
| A15.5 | Soak | 30 minutes with 40 crew: 0 stuck pawns, game thread at most 1 ms |

**Evidence.** Screenshot of each deck with crew at work; duty status sheet;
soak JSON.

### WP16 Terminals and stations

**Goal.** Desk monitors that show the panes' live terminal cells and chat
tails, desk takeover that brings the app to the front on that pane, and all
stations.

**Owned.** `Source/VerseScreens/**` except `VerseScreens.Build.cs`;
`Source/VerseDecks/{Public,Private}/Stations/**`;
`Source/VerseUI/{Public,Private}/Stations/**`;
`unreal/Verse/Content/Verse/Screens/**`, `unreal/Verse/Content/Verse/UI/Stations/**`;
`unreal/Verse/Content/Verse/Test/WP16/**`.

**Contracts consumed.** `bridge-protocol.md` 5, 6, 11, 12, 14 (open commands,
`launcher.cancel`, `busy`); architecture 5.3.

**Depends on.** G0 only (fake bridge and cells fixtures from G0.11). Fakes:
WP17 bridge client, WP12 screen sockets (fixture map), WP18 UI framework
(plain UMG root).

| # | Sub-task | Output |
|---|---|---|
| 16.1 | `cells.bin/1` and `cells.json/1` decoder and grid model | Decoder |
| 16.2 | Glyph atlas from the IDE font (licence checked, 13 px reference), one render target per monitor, dirty-row drawing | Renderer |
| 16.3 | Watch set: desks within view distance, at most 8, far monitors at 2 Hz | Watch manager |
| 16.4 | Chat tail screens | Screens |
| 16.5 | Takeover: interact sends `ide.focus_terminal`, Verse hides | Takeover |
| 16.6 | Station framework: `AVerseStation`, prompt, kinds | Framework |
| 16.7 | Station UIs and commands: ledger (`agents.open_list`), group (`group.open`), record (opens WP21's view), simulator (`simulator.open`), launcher (`launcher.options`, `launcher.start`, `launcher.cancel`, `ide.open`), `create_agent` | UIs |
| 16.8 | Armoury station actor: raises `FVerseStationUsedEvent` on the hub (combat-state 11.1) that WP18's armoury UI listens to (VerseDecks never includes VerseUI); the UI's "start" asks WP11's switch | Station |

| Id | Acceptance test | Pass |
|---|---|---|
| A16.1 | Decoder | Every golden fixture decodes byte-exact |
| A16.2 | Load | 8 panes at 60 x 240 at 10 Hz: at most 0.3 ms game thread per frame, at most 200 KB/s |
| A16.3 | Colour | 256-colour and RGB test screens vs reference image: mean CIEDE2000 at most 2 |
| A16.4 | Takeover | Key press to app window in the foreground on that pane at most 500 ms (with WP17 host) |
| A16.5 | Commands | Golden messages for every station command; `rate_limited` reply shown, not retried in a loop |

**Evidence.** Screenshot of a monitor next to the same pane in the IDE;
load JSON; takeover timing JSON.

### WP17 Backend verse host and bridge

**Goal.** The backend side (supervisor, probe, bridge server, relays,
commands) and the Unreal side (bridge client, typed feeds, lifecycle, window
and focus) of `verse.bridge/1`.

**Owned.** `dodaios/verse_host/**` except `signal.py` (WP20);
`dodaios/ui/web/verse_routes.py`; the `Verse*` event block in
`dodaios/core/events.py` (all Verse events, including `VerseDuelRecorded`);
the `VerseOpenRequested` handler block in
`dodaios/ui/web/frontend/src/hooks/useWebSocket.ts`; the shared launch
sequence `dodaios/agentic_ide/launch_sequence.py` (new);
`dodaios/ui/web/frontend/src/components/verseHost/**` and its mount in
`dodaios/ui/web/frontend/src/views/DodaiosAgentsView.tsx` behind the config
flag `verse.unreal_preview` until the deletion PR;
`tests/unit/verse_host/**` except `fixtures/` (G0.11) and `test_signal*.py`
(WP20); `Source/VerseBridge/**` except `Private/Duel/` (WP21) and
`VerseBridge.Build.cs`.

**Contracts consumed.** `bridge-protocol.md` (all); architecture 1, 5.

**Depends on.** G0 only. Fakes: WP21 `record_duel` service; WP20 signal
handler (the route answers close 1013 until it lands).

| # | Sub-task | Output |
|---|---|---|
| 17.1 | Conformance: the backend codec and the `VerseBridge` codec pass every G0.11 golden fixture and `fake_bridge.py` scenario (BW11) | Conformance tests in both languages |
| 17.2 | Route, loopback check, `hello` and token, one-client rule, heartbeat, close codes (BW1) | Route |
| 17.3 | Supervisor: lazy launch, job object and `PR_SET_PDEATHSIG`, env token, backoff, crash folder, status `crashed` after 3 crashes (BW2), `GET /api/verse/status` values of architecture 1.1 | Supervisor |
| 17.4 | Probe: D3D12 SM6 with 6 GB or Vulkan 1.3, install check, `unsupported` | Probe |
| 17.5 | Roster relay, duty port, rank join, parity tests against the TS code (BW3) | Relay |
| 17.6 | Styled screen mirror, screens relay, cells codec (BW4) | Relay |
| 17.7 | Chat tails relay (BW5), groups and meetings relay (BW6) | Relays |
| 17.8 | Progression relay: snapshot, awarded forward, actions, `told_seq` and `progression.told` (BW7) | Relay |
| 17.9 | `VerseOpenRequested` and web handler for every open command of bridge 11 and 14; launcher sequence moved into the backend with single flight and `launcher.cancel`; rate limits (BW9, BW12) | Commands |
| 17.10 | Locale and settings in `welcome` and `settings.changed`; `settings.set`; `POST /api/verse/settings/import`; `companion` topic; `qa.exec` gate (BW10, BW12) | Relays and route |
| 17.11 | Unreal `VerseBridge`: WS client, JSON and binary codec, reconnect with `last_seq`, typed feed subsystems, command sender with replies | Client |
| 17.12 | Unreal lifecycle: Booting, Visible, Panel, Dormant, Exiting; return key; foreground hand-off both ways; single-instance mutex; `gpu.yield`; X11 and Wayland activation | Lifecycle |
| 17.13 | Web launcher card (status, launch, quick-start duel) and desktop foreground hand-off; for `not_installed` the card shows size and a "Download the Verse" button with progress and cancel (routes `POST/DELETE /api/verse/install`, `GET /api/verse/install/progress` calling WP22's `verse_host/install`); remove in Settings; `npm run build` check | Frontend |

| Id | Acceptance test | Pass |
|---|---|---|
| A17.1 | Golden round trip | 100 % of fixtures encode and decode identically in Python and C++ |
| A17.2 | Auth | Wrong token closes 4401 within 100 ms; no `hello` in 5 s closes 4400; non-loopback peer 4403; second client replaces the first |
| A17.3 | Liveness | Dead link declared at 5 s within 0.5 s; restarts after 1, 4, 15 s; 3 crashes in 5 minutes leave status `crashed` |
| A17.4 | Containment | Killing the app process ends a dummy `Verse.exe` within 2 s on Windows and Linux |
| A17.5 | Token | Token absent from every process command line and from logs (scan) |
| A17.6 | Lifecycle | Dormant to Visible at most 300 ms; cold start to first frame at most 8 s; Dormant CPU under 1 % of one core and 0 GPU frames |
| A17.7 | Screens relay | 8 busy panes: at most 200 KB/s; event loop latency added p99 at most 5 ms |
| A17.8 | No secrets | Frame scan over a 30-minute session finds no key or credential pattern |
| A17.9 | Parity additions | Golden round trip for every section 14 message; a second `launcher.start` during a batch replies `busy`; `qa.exec` replies `unavailable` without `DODAIOS_VERSE_QA=1`; the settings import writes each key once and a second call imports nothing |

**Evidence.** pytest and automation reports; lifecycle timing JSON; screenshot
of the launcher card in the running app (from the rebuilt `dist`).

### WP18 HUD, armoury, menus, kill cam

**Goal.** Everything the person reads and clicks in Unreal outside stations:
HUD, kill feed, kill cam, armoury loadout and tier choice, Verse bar, menus
and settings, end-of-set screen.

**Owned.** `Source/VerseUI/**` except `Stations/` (WP16), `ServiceRecord/`
(WP21), `Audio/` (WP19) and `VerseUI.Build.cs`;
`unreal/Verse/Content/Verse/UI/**` except `Stations/`, `ServiceRecord/`;
`unreal/Verse/Data/ui/*.json`; `unreal/Verse/Content/Verse/Test/WP18/**`.

**Contracts consumed.** `combat-state.md` 2.1 (including `BotTier` and
`BotEffectiveSkill` on `AVersePlayerState`), 5.1, 9, 11.1 (`FVerseSetSummary`);
`bot.md` 3.3 (what the HUD shows is what the bot knows), 9.2 (`s` on the end
screen); `destruction.md` 4 (kill cam replay of breaks); `bridge-protocol.md`
3.2 (locale, settings), 12 (`settings.changed`), 14 (`settings.set`).

**Depends on.** G0 only (fake bridge from G0.11). Fakes: WP02 events
(synthetic hub events), WP11 player state.

| # | Sub-task | Output |
|---|---|---|
| 18.1 | HUD framework, safe areas, 1080p to 4K scaling, strings from `welcome` | Framework |
| 18.2 | Crosshair on the true bolt direction with spread display; hit markers (hit, headshot, kill, blocked); damage direction | Widgets |
| 18.3 | Magazine and reserve, reload state, gadget charges, health, stance, spawn protection | Widgets |
| 18.4 | Kill feed, set score, respawn countdown | Widgets |
| 18.5 | Kill cam: client ring buffer of the last 4 s (transforms, fire and fracture events), third-person replay of the killer during the 3 s respawn, skip | Kill cam |
| 18.6 | Armoury UI: loadout view, tier normal, hard, elite or adaptive, start duel | Armoury UI |
| 18.7 | Verse bar: quick-start duel, deck navigation, return to app | Bar |
| 18.8 | Menus and settings: Esc menu, gore Full or Reduced, key rebinding including the return key, sensitivity, deck view FOVs (parity V-09: 70 third, 85 first), duel FOV 80-110 (default 100, the value `bot.md` 3.1 sizes the bot's view cone from), reduced motion, volumes, scalability. App-backed settings go through `settings.set`; duel FOV, keys and scalability are stored in Unreal's user settings | Menus |
| 18.9 | End-of-set screen with set summary and adaptive `s` | Screen |
| 18.10 | Accessibility: marker shapes that work without colour, text size | Pass |

| Id | Acceptance test | Pass |
|---|---|---|
| A18.1 | Crosshair | Centre of the crosshair and the predicted bolt direction differ by 0 px at 1440p over 1,000 shots |
| A18.2 | Kill cam | Starts within 150 ms of `FVerseDeathEvent`, ends at least 200 ms before respawn; replayed killer path within 10 cm of the server log |
| A18.3 | Cost | HUD at most 0.3 ms game thread plus GPU |
| A18.4 | Strings | 0 hard-coded user strings (scan); 5 locales render without clipping at 1080p |
| A18.5 | Settings | Every setting keeps its value across a Verse restart; after rebinding the return key to F8, F8 sends `focus.return_to_app` and F10 does nothing; a gore change sends one `settings.set` and the next `welcome` carries it |

**Evidence.** HUD screenshots in a fight at 1080p, 1440p, 4K; kill cam
contact sheet; one screenshot per locale of the armoury.

### WP19 Audio

**Goal.** Heavy, located sound: layered weapons, bolts, impacts per material,
footsteps, reloads, melee, destruction, drones, deck ambience; one audibility
table shared with the bot.

**Owned.** `unreal/Verse/Content/Verse/Audio/**`;
`Source/VerseUI/{Public,Private}/Audio/**`; `art/verse/audio/**` (synthesis
builders and fetch scripts only: recordings in `.wav` or `.flac` are never
committed, they are fetched from ledger URLs into `art/verse/.cache/` and only
the imported `.uasset` is committed, architecture 8.4);
`unreal/Verse/Data/audio/*.json` (`DA_Audibility` values are propose-only, Core);
`unreal/Verse/Content/Verse/Test/WP19/**`.

**Contracts consumed.** `bot.md` 3.2 and F6; `combat-state.md` 5.1;
`destruction.md` 6.2 (loudness by cause), 7 (drone noise); README Assets
(own or CC0 only).

**Depends on.** WP02 events (synthetic), material ids from WP03 and WP06
(fixture), WP12 ambience zones (fixture).

| # | Sub-task | Output |
|---|---|---|
| 19.1 | Framework: MetaSound sources, submixes, concurrency, attenuation from `DA_Audibility` | Framework |
| 19.2 | Weapons: layered mechanical thump, body, tail, room reflection; first and third person; distance layers | Weapon sounds |
| 19.3 | Bolt flyby, impacts for the 8 materials, penetration exit | Sounds |
| 19.4 | Footsteps per surface and stance, slide, land, mantle, lean and prone foley | Sounds |
| 19.5 | Reloads (tactical and empty distinct), equip, knife, finisher | Sounds |
| 19.6 | Destruction by class, debris settle, drone flight and weld | Sounds |
| 19.7 | Occlusion through pieces (holes and breaches open it), spatialisation | System |
| 19.8 | Deck ambience, crew beds, UI sounds | Sounds |
| 19.9 | Licence ledger rows and audit | Ledger |

| Id | Acceptance test | Pass |
|---|---|---|
| A19.1 | F6 symmetry | Attenuation maximum distance equals the `DA_Audibility` range for every `Noise.*` tag (0 mismatches) |
| A19.2 | Latency | Shot to sound start at most 1 frame |
| A19.3 | Load | `destruction_storm`: at most 64 voices, audio thread at most 1.5 ms |
| A19.4 | Loudness | Duel reference capture integrated -16 LUFS within 1, true peak at most -1 dBTP |
| A19.5 | Dormant | Muted within 100 ms of hide |
| A19.6 | Licence | Every sound asset cites a ledger row or `own` |

**Evidence.** Loudness report; capture WAV of the reference duel replay (CI
artifact, not committed); occlusion test JSON.

### WP20 Pixel Streaming side panel

**Goal.** The IDE side panel shows a Pixel Streaming 2 view of the running
`Verse.exe` while visible, stopping within 1 s when hidden, with a fallback
card.

**Owned.** `Source/VerseStream/**` except `VerseStream.Build.cs`;
`dodaios/verse_host/signal.py`;
`dodaios/ui/web/frontend/src/components/agentic/sidePanel/verseStream/**`;
`dodaios/ui/web/frontend/src/components/agentic/sidePanel/OfficeTab.tsx`;
`tests/unit/verse_host/test_signal*.py`;
`unreal/Verse/Content/Verse/Test/WP20/**`.

**Contracts consumed.** `bridge-protocol.md` 12 (`panel.*`); architecture 1.3, 6.

**Depends on.** G0 only. Fakes: WP17 route and lifecycle (`fake_bridge.py`
from G0.11 sends `panel.visibility`); any deck map. The frontend library pin
in `package.json` is a request to the integration owner. `OfficeTab.tsx`
shows the stream only behind the config flag `verse.unreal_preview` until the
deletion PR.

| # | Sub-task | Output |
|---|---|---|
| 20.1 | Signalling in the backend: loopback ICE only, token rules, protocol test against the plugin | `signal.py` |
| 20.2 | `VerseStream`: session start and stop, offscreen render at panel size, panel camera, 30 fps, hardware H.264 (AV1 if offered), 8 Mbit/s cap | Module |
| 20.3 | Frontend component with the pinned MIT library; visibility via `IntersectionObserver` and page visibility; fallback card | Component |
| 20.4 | Input over the data channel: overview and walking only; no duel in the panel | Input map |
| 20.5 | Arbitration: full window wins; last frame with "Verse is open" | Arbitration |
| 20.6 | Perf and lifecycle tests | Tests |

| Id | Acceptance test | Pass |
|---|---|---|
| A20.1 | Start and stop | Stream visible within 1.5 s of the panel showing; stopped within 1 s of hiding |
| A20.2 | Cost | At most 1.5 ms GPU per frame at 960 x 600; VRAM in Panel at most 3 GB |
| A20.3 | Latency | Glass-to-glass under 80 ms (timestamp overlay test) |
| A20.4 | Arbitration | Full view open: 0 streamed frames rendered |
| A20.5 | Bundle | `npm run build` output contains the component; screenshot from the running app |

**Evidence.** Screenshot of the side panel streaming in the running app;
latency JSON; GPU cost JSON.

### WP21 Progression and duel stats

**Goal.** Duel wins award commander XP; duel statistics (wins, K/D,
headshots, finishers) land in the service record, both in the web app and in
Unreal.

**Owned.** `dodaios/progression/duel_stats.py`; the duel rule block in
`dodaios/progression/rules.py`; `ProgressionService.record_duel` and helpers
in `dodaios/progression/service.py`; the duels read in
`dodaios/ui/web/progression_routes.py`; `tests/unit/progression/test_duel_*.py`
and the duel rows of `tests/unit/progression/test_frontend_parity.py`;
the duel section of `dodaios/ui/web/frontend/src/components/society/verse/ranks/ServiceRecord.tsx`;
`Source/VerseBridge/Private/Duel/**`; `Source/VerseUI/{Public,Private}/ServiceRecord/**`;
`unreal/Verse/Content/Verse/UI/ServiceRecord/**`.

**Contracts consumed.** `bridge-protocol.md` 9, 10; `combat-state.md` 9.1, 10
(`BuildSetSummary`), 11.1 (`FVerseSetSummary`, `UVerseEventHub::OnSetEnded`);
`bot.md` 9.2.

**Depends on.** G0 only. Fakes: WP17 relay (tests call `record_duel`
directly; the Unreal side uses the G0.11 fake bridge), WP11 set summary
(synthetic `OnSetEnded` events).

| # | Sub-task | Output |
|---|---|---|
| 21.1 | Duel stats store: table, migration, totals, per tier and per weapon | Store |
| 21.2 | XP rules `duel_won`, `duel_lost`, `duel_finisher`, tier multipliers, server trigger, caps; refusal through `POST /actions`; frontend parity test | Rules |
| 21.3 | `record_duel`: idempotent on `match_id`, clamping, awards, `VerseDuelRecorded` publish | Service |
| 21.4 | `GET /api/progression` with `duel_stats`; `GET /api/progression/duels?limit=20` | Routes |
| 21.5 | Web service record duel section; `npm run build` check | Frontend |
| 21.6 | Unreal reporter (in VerseBridge, reads `OnSetEnded`, never includes VerseCombat): one `duel.result` per finished set and one `unfinished` result on leave; the pending result is saved and sent as `crash_recovered` on the next launch | Reporter |
| 21.7 | Unreal service record view, commander XP and rank, promotion notice; sends `progression.told` once a promotion was shown (bridge 14) | UI |

| Id | Acceptance test | Pass |
|---|---|---|
| A21.1 | Idempotency | 100 sends of one `match_id` give 1 row and 1 award |
| A21.2 | XP | A won set vs hard pays 60; daily caps 200 / 50 / 25 hold; a set with `match_time_s` 59 pays 0; an `unfinished` result pays 0 and still updates `duel_stats` |
| A21.3 | Clamp | More than 1 kill per 2 s of match time is clamped and logged |
| A21.4 | Crash recovery | Verse killed after a set: next launch sends `crash_recovered` within 10 s of `welcome` |
| A21.5 | Refusal | `POST /api/progression/actions` with `duel_won` returns 422 or `bad_request` |
| A21.6 | Bundle | Web service record shows the duel section in the running app |

**Evidence.** pytest report; screenshots of both service records with the
same numbers.

### WP22 Packaging, installer, updater, Linux

**Goal.** Windows and Linux builds packaged, chunked per deck, published as an
optional per-platform release asset that the app downloads only when the user
asks for it (README Delivery), updated by delta packages once installed, with
machines without a GPU unaffected. The normal installer and app updates never
carry the Verse.

**Owned.** `scripts/unreal/package.py`; `.github/workflows/unreal-package.yml`
(workflow policy of architecture 8.2); `unreal/Toolchain/**` (`toolchains.json`,
`ddc.json`); `unreal/Verse/Build/**` (engine-required platform resources);
`packaging/windows/verse/**`, `packaging/linux/verse/**`; the Verse download
and delta logic in `dodaios/core/installer_update.py`; the on-demand
installer `dodaios/verse_host/install/**` (download, resume, signature and
hash check, unpack, uninstall, delta apply; called by WP17's routes); the
`GIT_LFS_SKIP_SMUDGE=1` lines in `install/**`, `dodaios/core/main_follow.py`
and `dodaios/ui/web/update_routes.py`; `tests/unit/installer/test_verse_*.py`.

**Contracts consumed.** architecture 7 (size, cold start), 8.1, 8.3;
`art-pipeline.md` 10.2 (installer clone without LFS); README Platforms and
Delivery.

**Depends on.** G0.1 and G0.6; any content for size runs (an empty map is
enough to start). `Verse.Target.cs` changes are requests to the integration
owner.

| # | Sub-task | Output |
|---|---|---|
| 22.1 | Toolchain setup and pins: MSVC, SDK, Linux clang cross toolchain, `toolchains.json`, verify command | Scripts |
| 22.2 | BuildCookRun Win64 and Linux Shipping; Harness absent from Shipping | `package.py` |
| 22.3 | IoStore chunk per deck; shipped PSO cache | Chunk rules |
| 22.4 | Delta packages: chunk diff, apply, hash verify, rollback | Delta tool |
| 22.5 | On-demand install: Verse release asset per platform with manifest (version, size, hashes, signature), resumable download with progress, verify, unpack into the user data folder, uninstall; `MAX_INSTALLER_BYTES` stays unchanged | `verse_host/install` |
| 22.6 | Installers and app updates on Windows and Linux carry no Verse payload; `GIT_LFS_SKIP_SMUDGE=1` in clone paths; installed Verses get a separate Verse update channel | Installers |
| 22.7 | Linux smoke: container or VM, `-nullrhi` server run, Vulkan first frame where a device exists, X11 and Wayland activation check | Nightly job |
| 22.8 | Signing hand-off to the existing signing workflow; no keys on the runner | Workflow step |
| 22.9 | Disk hygiene: DDC cap 40 GB, `Intermediate` pruning, alert below 40 GB free | Script |

| Id | Acceptance test | Pass |
|---|---|---|
| A22.1 | Size | Payload at most 2 GB compressed at parity; typical delta at most 300 MB |
| A22.2 | Cold start | At most 8 s to first frame on the reference box with the shipped PSO cache |
| A22.3 | No GPU | Install on a GPU-less VM: app runs, Verse status `unsupported`, 0 errors in the app log |
| A22.7 | On demand | Fresh install: Verse status `not_installed`, installer size unchanged against the previous release; download from the card installs and launches; an interrupted download resumes; a tampered package is rejected; uninstall frees the folder and returns to `not_installed` |
| A22.4 | LFS | A fresh installer clone and an in-app update each download 0 bytes of `unreal/**` LFS objects; the release source archive contains no `unreal/` path |
| A22.5 | Update | Delta applies with 100 % hash match; a corrupted chunk rolls back to the previous version |
| A22.6 | Linux | Linux Game target builds in `unreal-build`; 60 s server smoke passes nightly |

**Evidence.** Package size report per chunk; cold-start JSON; GPU-less VM
screenshot of the launcher card; delta apply log.

## 3. Deck zones and owners

| Deck | Zone | Owner |
|---|---|---|
| hangar | `shell`, `arena_canyon`, `arena_shuttle`, `arena_booth`, `arena_catwalks`, `armoury` | WP11 |
| hangar | `lift_lobby`, `day_stations` | WP12 |
| bridge, ops, engineering | every zone (list fixed in WP12.4-12.6 placement files) | WP12 |
| any | Station actors are placed by the zone owner; their classes come from WP16 | - |
| any | Destructible pieces are placed by the zone owner; their classes and assets come from WP06 | - |

## 4. Contract conflicts, decided (G0.2)

Each conflict found in review is decided in the contracts themselves, so no
package waits on it. G0.2 is done when the code in `VerseCore` matches.

| # | Conflict | Decision (now in the contract) |
|---|---|---|
| C1 | Penetration: rifle `PenetrationPower` 40 with 2 passes and a per-cm formula vs "100 = assault rifle", 3 pieces and a reference-thickness formula; `IVersePieceDamageSink` vs `IVersePieceDamage` | `destruction.md` 2 wins: 100 = rifle, reference-thickness cost formula, at most 3 pieces, `IVersePieceDamage`. `combat-state.md` 3, 3.1 (rifle 100 / 3, pistol 50 / 2, `HoleRadiusMm`) and 6 now follow it |
| C2 | Trace channel `VerseHitBody` missing from the frozen channel list | Added to `destruction.md` frozen interface (per-bone hit bodies only) |
| C3 | Eye socket `head_cam` vs rig bone `Camera` | The `Camera` bone of `SKEL_Verse_Human` (`art-pipeline.md` 12.1); `bot.md` 3.1 updated |
| C4 | Breakable minimum thickness "at least 10 cm" vs "material reference thickness within 10 %" | `destruction.md` 9 governs destructibles; the 10 cm and 20 cm minimums of `art-pipeline.md` 5, 6.3 apply to non-destructible architecture only; `art-pipeline.md` 13 updated |
| C5 | `duel.result` per finished set vs per session | One result per set: `won` / `lost` per finished set, `unfinished` for the set left mid-way (stats only, no XP); payload `FVerseSetSummary` (`combat-state.md` 9.1, 11.1; `bridge-protocol.md` 10) |
| C6 | Gadget contract referenced but missing | `combat-state.md` 2.3 (`UVerseGadgetDefinition`, Bulwark and breach charge rules, `FVerseGadgetEvent`, tests GD1 to GD4) |
| C7 | `VerseServer.Target.cs` exists although binary installs cannot build Server targets; Harness is in the Game target | G0.4 deletes `VerseServer.Target.cs` and lists `VerseHarness` only in `VerseEditor.Target.cs` (architecture 8.1) |
| C8 | `AVerseCharacter` (VerseMovement) was also given combat fields | Combat phase and spawn protection live in `UVerseCombatStateComponent` (`combat-state.md` 2.1, 11.2) |
| C9 | `VerseBridge` (duel reporter), `VerseUI` (adaptive `s`) and `VerseDecks` (arena switch) needed types from modules they may not include | `FVerseSetSummary`, `FVerseArenaSwitchEvent` and hub delegates in Core; `BotTier` / `BotEffectiveSkill` on `AVersePlayerState` (`combat-state.md` 2.1, 11.1) |
| C10 | Gate ids collided: phase gates G0-G3 vs bot gates G1-G12, combat D1-D6 vs destruction D1-D6, recoil R1-R6 vs bot R1 and architecture risks R1-R16, bot B1-B8 vs bridge work items B1-B11 | Bot gates `BG1-BG12`, bot replay `BR1`, learning test `L1`, piece-truth test `F7`; destruction rules `DR1-DR6`; architecture risks `RK1-RK16`; bridge work items `BW1-BW12` |
| C11 | Parity gaps needed bridge messages that did not exist | Added to `bridge-protocol.md` §14 before the freeze |

## 5. Dependency table

"Starts on" is what must exist before the first sub-task. "Stubs" are faked
by the package itself. "Final acceptance needs" is what must be real for the
package's last acceptance run.

| WP | Starts on | Stubs (own fakes) | Final acceptance needs |
|---|---|---|---|
| WP01 Movement | G0 | WP13 rig (`SK_Test_Human`) | WP10 netcode runner |
| WP02 Weapons | G0 | WP01, WP03, WP11 ruleset, WP13, WP14 | WP01, WP03, WP10 |
| WP03 Penetration | G0 | WP06 pieces | WP06 |
| WP04 Melee | G0 | WP02.8 rewind, WP01 flags, WP13.7 clips | WP02, WP13, WP10 |
| WP05 Gore | G0 | Hub events, WP13 material slots | WP10 (D6) |
| WP06 Destruction | G0 (G0.7 hard) | WP03 holes | WP03, WP10 |
| WP07 Perception, belief | G0 | WP01 eye, WP03 sight, WP06 pieces | WP01, WP03, WP06 |
| WP08 Decisions | G0 | WP07, WP09, WP01, WP02 | WP07, WP09, WP02, WP06, WP10 |
| WP09 Aim, tiers | G0 | WP02 weapons, WP07 percepts | WP08, WP10 |
| WP10 Harness | G0 | Null brain | WP08 for gates |
| WP11 Hangar arena | G0 | WP06 classes, WP12 loading, WP02 loadout | WP06, WP12, WP02, WP08, WP10 |
| WP12 Decks | G0 | WP14 masters, WP17 bridge | WP14, WP17 |
| WP13 Characters | G0 (G0.7 hard) | WP01 query | WP01 |
| WP14 Style, weapons | G0 (G0.7 hard) | WP02 ids | - |
| WP15 Crew | G0 (G0.11 fake bridge) | WP17 client, WP13 rig, WP12 sockets | WP17, WP13, WP12 |
| WP16 Terminals, stations | G0 (G0.11 fake bridge) | WP17 client, WP12 sockets, WP18 UI root | WP17, WP12 |
| WP17 Verse host, bridge | G0 | WP21 service, WP20 signal | WP21 |
| WP18 HUD, menus, kill cam | G0 (G0.11 fake bridge) | WP02 events, WP11 state, WP17 locale | WP02, WP11, WP17 |
| WP19 Audio | G0 | WP02 events, WP03/WP06 materials, WP12 zones | WP02, WP06 |
| WP20 Pixel Streaming | G0 (G0.11 fake bridge) | WP17 lifecycle | WP17 |
| WP21 Progression | G0 (G0.11 fake bridge) | WP17 relay, WP11 summary | WP17, WP11 |
| WP22 Packaging | G0.1, G0.6 | Empty map | All content packages for the size gate |

Early unblockers, scheduled first inside their packages: WP10.1-10.4
(lanes and harness), WP13.1 (rig), WP06.1 (fracture spike), WP14.1
(masters), WP11.1 (graybox), WP02.8 (rewind for WP04). The fake bridge is
G0.11, so no package waits on WP17.

## 6. Sub-task counts

| WP | Package | Sub-tasks |
|---|---|---|
| WP01 | Movement | 11 |
| WP02 | Weapons, recoil, projectiles, magazines | 14 |
| WP03 | Penetration and material table | 8 |
| WP04 | Melee and finisher | 7 |
| WP05 | Gore and setting | 8 |
| WP06 | Destruction and repair drones | 11 |
| WP07 | Bot perception and belief map | 10 |
| WP08 | Bot decisions, EQS, learning | 11 |
| WP09 | Bot aim, tiers, adaptive | 8 |
| WP10 | Harness | 11 |
| WP11 | Hangar arena and combat mode switch | 12 |
| WP12 | Bridge, ops and engineering decks | 11 |
| WP13 | Characters, FPS skeleton, animations | 10 |
| WP14 | Weapon models, materials, style | 10 |
| WP15 | Crew and daily life | 9 |
| WP16 | Terminals and stations | 8 |
| WP17 | Backend verse host and bridge | 13 |
| WP18 | HUD, armoury, menus, kill cam | 10 |
| WP19 | Audio | 9 |
| WP20 | Pixel Streaming side panel | 6 |
| WP21 | Progression and duel stats | 7 |
| WP22 | Packaging, installer, updater, Linux | 9 |
| | Total | 213 |
