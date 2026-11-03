# Verse on Unreal Engine

The whole Verse moves from three.js to Unreal Engine 5.7. Deck 4 (the hangar)
becomes a destructible 1v1 battlefield against a single, much stronger bot.
The three.js Verse keeps running until the Unreal Verse reaches parity
(`parity.md`); one pull request then deletes it.

This folder is the source of truth for that work. Every agent working on the
Unreal Verse reads this file first, then its work package in
`work-packages.md`, then the contracts it touches in `contracts/`.

| File | What it holds |
|---|---|
| `README.md` | Decisions (this file) |
| `architecture.md` | Modules, process model, networking, bridge |
| `contracts/` | Frozen interfaces every package codes against |
| `work-packages.md` | The 22 fan-out packages: scope, owned paths, acceptance |
| `orchestration.md` | Phases, gates, rules for parallel agents |
| `parity.md` | Checklist the Unreal Verse must pass before three.js is deleted |

## Decisions

| Area | Decision |
|---|---|
| Scope | The whole Verse (bridge, ops, engineering, hangar). three.js stays until parity, then is deleted in one PR |
| Platforms | Windows and Linux built together (Linux cross-compiled from Windows); macOS later. No GPU means no Verse; the app itself keeps working |
| Hosting | `Verse.exe` runs as its own borderless window, launched and supervised by the Dodaios backend, linked by a local token-guarded WebSocket bridge. Never a child window (`SetParent`) |
| IDE side panel | Pixel Streaming of an Unreal view into the panel, running only while the panel is visible |
| Live terminals | Desk screens in Unreal show the pane's terminal cells, served by the backend. Taking over a desk brings the app to the front on that terminal |
| Repo | Public main repo, open source, under `unreal/`. Art as code plus Git LFS for unavoidable binaries. One File Per Actor. Never engine source, never Fab or Megascans content |
| Assets | Own work or CC0 only (`art/verse/LICENSES.md` stays the ledger) |
| Look | Photoreal (Lumen, Nanite), new style "Military-Industrial Noir": black steel, concrete, oil, wear, hard work lights, dust and haze. Accents sparse in amber, red, gold. Never cyan or violet |
| Camera | Duel: first person only; third person only for kill cam and finisher. Elsewhere overview, third and first person as today |
| Projectiles | Visible laser bolts at about 300 m/s, no drop. Own bolts amber, the opponent's red |
| Ammo | Magazines; tactical reload (round chambered) faster than empty reload |
| Recoil | Learnable pattern per weapon plus about 15 % random, camera kick, first-shot accuracy, recovery slower than the kick so sustained fire really climbs |
| Arsenal | Start: assault rifle, pistol, knife, Bulwark (deployable energy barricade), breach charge. Then SMG and DMR, later a large arsenal. All weapons fully black, fictional names, modelled on no real firearm |
| Movement | Walk, sprint, crouch, prone, lean left/right, slide, jump, mantle. Per-bone hit zones |
| Melee | Frontal: fast knife strike, high damage, not a one-shot. From behind or the flank within 1.5 m: a finisher, a guaranteed kill (about 2.5 s: throw to the ground, struggle as animation only, knife to the throat), paired animation with motion warping |
| Gore | Heavy blood, spatter on walls and floor, wounds at the hit location, pools, bloody finishers. No dismemberment. A setting switches to reduced (no blood, finishers cut away); the default is full |
| Destruction | Full physics: walls, cover, containers, glass, catwalks and ceiling panels break; the hall floor does not. The server decides every break; clients simulate debris. Repair drones rebuild broken parts after about 60 s |
| Arena | A dense zone of about 50 x 40 m inside the 100 x 62 m hall, three height levels. The hangar is a normal deck day to day and turns into the arena on demand |
| Mode | Endless 1v1 deathmatch. Respawn after 3 s at the spawn farthest from and out of sight of the opponent, short spawn protection that ends on the first own shot. Game mode logic is swappable for future modes |
| Networking | Server-authoritative from day one, also against the local bot (the bot is a player with its own controller). Online PvP later without a rewrite |
| Bot | Full movement including finishers, shoots through walls only at heard or believed positions, breaches, uses Bulwark and gadgets, learns the player within a match. Fair perception, no wallhack. Tiers normal, hard, elite plus an adaptive mode. Higher skill wins more often, never always |
| Duel entry | Armoury station in the hangar plus a quick-start button in the Verse bar |
| Progression | Duel wins award commander XP; duel statistics (wins, K/D, headshots, finishers) in the service record |
| Delivery | Optional download. The installer, a plain `git clone` and app updates never carry the Verse. Opening the Verse the first time shows a card with the download size and a "Download the Verse" button; the package (its own release asset per platform) downloads resumably, is signature- and hash-checked and installs into the user data folder. Settings can remove it again. Only an installed Verse receives delta updates. The source stays in this repo under `unreal/`; `.lfsconfig` keeps its binaries out of every default clone |
| Testing | Fully autonomous: builds, tests, headless bot-vs-bot runs, screenshots, performance. The user plays at the end of integration |
| Legal | No names of other games, studios or real firearm makes or models anywhere: code, assets, commits, PRs, docs |

## What carries over from the three.js duel

Only rules and concepts carry over, never numbers. The numbers were tuned
for the reactor-shaft arena on deck 3 and for a heat-only blaster.

- The bot's fair-perception contract (`combat/observe.ts`, test `bot.test.ts:32-46`).
- The Ornstein-Uhlenbeck aim wander (`combat/bot/aim.ts`).
- Utility selection with hysteresis (`combat/bot/brain.ts`).
- Tiers as data (`combat/bot/tiers.ts`).
- The balance harness gates (`combat/harness/*`): no single trick beats hard,
  a skilled player model wins about 40 % against elite.
