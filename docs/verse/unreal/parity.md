# Verse on Unreal: parity checklist

The three.js Verse is deleted in one pull request, and only once every row
below passes on the Unreal Verse (README, "Scope"). The rows come from
today's code. Paths in the "Today" column are relative to
`dodaios/ui/web/frontend/src/components/society/verse/` unless they start
with `src/`, `dodaios/`, `art/`, `scripts/` or `tests/`.

## 1. How a row passes

Every row has an automated check. A row passes when its check is green on
`main` in the lane named below (architecture §8.3). Nobody ticks a row by hand.

| Kind | What it is | Lane |
|---|---|---|
| `AT` | Unreal automation test `Verse.Parity.<Section>.<Id>`, `-nullrhi` unless marked GPU | `unreal-build` |
| `GT` | Gauntlet run of the real `Verse.exe` (`-nullrhi`) against a real backend with a fake bus and seeded roster/panes (`tests/unit/verse_host/fixtures/`, G0.11) | `unreal-build` (smoke), `unreal-gauntlet` |
| `BT` | Backend pytest with a scripted fake Verse peer on `WS /api/verse/bridge` (`tests/unit/verse_host/`) | Python CI |
| `VT` | Vitest of the web pieces that stay (launcher card, panel stream, bus handlers) | Frontend CI |
| `SS` | Harness screenshot of a fixed camera on the GPU build, compared with a stored reference (SSIM ≥ 0.9) plus the palette-share check of `contracts/art-pipeline.md` | `unreal-perf` |
| `ST` | Static check over files (schema, key coverage, forbidden names) | `unreal-static` |

`scripts/unreal/parity_report.py` (new) reads the row ids in this file,
matches them to test results by id (`Verse.Parity.D.07` ↔ row `D-07`) and
prints `n/N green`. The deletion PR (section 21) is allowed only when it
prints `N/N`, and it links the report.

A check cell that names only a kind (for example just `AT`) asserts the
row's Feature column exactly, with every number that column states (times,
counts, ranges, defaults), against the Today reference; the test name ends in
the row id. A row whose Feature column states no number asserts the
behaviour on at least one scripted case per state it names.

A row marked **[gap]** needed a bridge message or a config key that the
first draft of `contracts/bridge-protocol.md` lacked. Section 20 lists them;
all of them are now defined in `contracts/bridge-protocol.md` §14, frozen with
`verse.bridge/1`, so no package waits on them.

A row marked **[changed]** keeps the behaviour under a different form,
because a README decision changed it (an own window instead of a canvas in
the page, the hangar duel instead of the reactor duel). The acceptance
column states the new form.

## 2. Mounts, hosting and lifecycle

| Id | Feature | Today | Unreal acceptance check |
|---|---|---|---|
| A-01 | Full Verse under Agents > Verse tab | `src/views/DodaiosAgentsView.tsx:24`, `src/views/society/SocietyView.tsx:33` | `VT`: selecting the Verse tab sends `POST /api/verse/show {reason:"verse_view"}`; `GT`: Verse reaches `Visible` and sends `lifecycle.ready` |
| A-02 | Compact Verse in the IDE side panel, opens on engineering | `src/components/agentic/sidePanel/OfficeTab.tsx:57` | `GT`: `panel.visibility {visible:true}` puts Verse in `Panel` state with deck `engineering`; `VT`: the panel component starts the stream |
| A-03 | IDE layout switch "Verse" maximizes the side panel and gives it back on leave | `src/components/agentic/threads/IdeLayoutSwitch.tsx:44-68` | `VT`: choosing "Verse" sends `show`; leaving restores the panel layout exactly as `IdeLayoutSwitch.test.tsx:26` asserts today |
| A-04 | Both mounts awake at once, each its own runtime | `VerseStage.tsx:156-159` | **[changed]** `GT`: panel visible + full view shown at once → one `Verse.exe`, the panel shows the last frame and "Verse is open", stream stopped (architecture §6) |
| A-05 | A visited stage keeps its renderer while hidden (`active=false`) | `VerseStage.tsx:98-99`, `src/hooks/useCanvasAwake.ts` | **[changed]** `GT`: hide → `Dormant` within 1 s, zero GPU frames; show again → `Visible` within 300 ms with the same deck and commander pose |
| A-06 | Hidden stage renders nothing (`frameloop: never`) | `VerseStage.tsx:930` | `GT`: in `Dormant` the harness counts 0 rendered frames over 10 s and CPU under 1 % of one core |
| A-07 | Loading screen: key art, tip, progress bar, fades out once the first deck is on screen | `VerseLoadingScreen.tsx`, `verseLoading.css` | `AT`: boot shows the loading widget until the deck's first frame, then fades in under 600 ms; `GT`: cold start to first frame ≤ 8 s |
| A-08 | No WebGL: "Verse unavailable" text, the app keeps working | `VerseStage.tsx:912,920` (`useWebglSupported`) | `BT`: probe reports `unsupported` (no D3D12 SM6 / Vulkan 1.3 / under 6 GB VRAM); `VT`: the launcher card shows the localized unsupported text; no `Verse.exe` spawned |
| A-09 | Renderer crash stays inside the Verse (error boundary, tab retry) | `VerseStage.tsx:105-110`, `OfficeTab.tsx:11-38` | `BT`: kill `Verse.exe` → supervisor restarts with backoff 1/4/15 s; 3 crashes in 5 min → status `crashed`, card offers the crash report; app process unaffected |
| A-10 | Deck missing or failed: status line "deck missing" | `VerseStage.tsx:964-968` | `AT`: a deck whose data layer fails to load shows the localized `verse.stage.deck_missing` text and the lift still works |
| A-11 | Eye-level scene fails: the deck falls back to the plate | `VerseStage.tsx:903-908` | **[changed]** no plate exists; `AT`: a failed World Partition cell load logs to the bridge (`log`), retries once, then shows A-10 |
| A-12 | WebGL context loss rebuilds the canvas (`generation`) | `src/hooks/useWebglSurface.ts`, `VerseStage.tsx:162` | `AT`: simulated device-removed (RHI lost) → Verse exits cleanly with a crash report; `BT`: supervisor relaunch restores deck and pose from saved state |
| A-13 | App quit or crash ends the Verse | n/a today (same process) | `BT`: closing the job object kills `Verse.exe`; app quit sends `lifecycle.quit` and Verse exits within 3 s with state saved |

## 3. Decks and content

| Id | Feature | Today | Unreal acceptance check |
|---|---|---|---|
| B-01 | Four decks in order bridge, ops, engineering, hangar | `decks.ts:7` | `ST`: the deck DataAsset list equals `VERSE_DECKS` (`dodaios/progression/rules.py:51`) in order; `AT`: each loads and shows its first frame |
| B-02 | Deck number shown one-based on the lift and the title | `decks.ts:16-18`, `hud/DeckBar.tsx` | `AT`: title widget for hangar reads "04" and the localized `verse.deck.label` with n=4 |
| B-03 | `testbed` deck exists for pipeline smoke but never ships | `.gitignore:532-533`, `content/useDeck.ts` | `ST`: Shipping pak contains no `testbed` map; `AT`: Development build loads it with `-VerseDeck=testbed` |
| B-04 | Rooms, stations, sockets, routes from the cooked manifest (`verse.deck/1`) | `content/manifest.ts`, `art/verse/schema/deck.schema.json` | `ST`: every room, station, socket and route id of today's four manifests has a placed actor or volume with the same id (`contracts/art-pipeline.md` placement import); `AT` loads and counts them |
| B-05 | Deck cache: riding back to a deck is instant | `content/useDeck.ts` | `AT`: ride bridge→ops→bridge; the second arrival shows its first frame under 500 ms |
| B-06 | Commander spawn: first visit at the deck spawn, after a ride out of the lift | `life/commander.ts`, `life/cast.ts:91-95` | `AT`: first load places the commander at the `spawn` socket; after a lift ride at the lift socket |
| B-07 | A walk order belongs to the deck it was given on | `life/commander.ts`, `VerseStage.tsx:339-344` | `AT`: order a walk, ride the lift, come back: the commander stands at the lift, not walking to the old target |
| B-08 | Hangar is a normal deck day to day; the duel zone hides the crew | `VerseStage.tsx:785`, `actors/ActorsLayer.tsx:254-256` | **[changed]** `AT`: arena mode on → no crew pawn inside the arena bounds, the deck's stations outside it still work; arena off → crew back |

## 4. Turbolift

| Id | Feature | Today | Unreal acceptance check |
|---|---|---|---|
| L-01 | Lift panel lists the decks top to bottom, current one marked and focused | `hud/LiftPanel.tsx` | `AT`: open lift UI → 4 rows in `DECK_IDS` order, current row has keyboard focus and the "current" state |
| L-02 | Choosing a deck shuts the doors, rides, opens them on the new deck | `VerseStage.tsx:346-357`, `verse-doors` | `AT`: ride → door widget closed for ≥ 400 ms, deck changes, doors open within 150 ms of the first frame of the new deck |
| L-03 | Doors give up and open after 5 s | `VerseStage.tsx:301-306` (`DOORS_GIVE_UP_MS`) | `AT`: block the deck load → doors open at 5 s ± 0.2 s with A-10 shown |
| L-04 | Reduced motion skips the door animation | `VerseStage.tsx:354` | `AT`: `reduced_motion=true` (from `settings.changed`) → ride switches decks with no door phase |
| L-05 | Same deck chosen: panel closes, nothing rides | `VerseStage.tsx:349` | `AT` |
| L-06 | Lift opens from the lift station, the deck title switch and the tool rail | `VerseStage.tsx:396,976,981` | `AT`: each of the three opens the lift UI |
| L-07 | Lift ride sound (doors, ride) | `audio/useStageAudio.ts` | `AT`: a ride emits the door-close, ride and door-open cues (audio event log) |

## 5. Feeds the Verse consumes

| Id | Feature | Today | Unreal acceptance check |
|---|---|---|---|
| F-01 | Roster of society agents (name, tier, created, run state) | `life/useCrewLife.ts` → `../data` `useSocietyRoster` (`GET /api/society/agents`) | `BT`: `roster.snapshot` on subscribe matches `GET /api/society/agents`; `GT`: a seeded agent appears as an officer pawn |
| F-02 | Roster freshness: refresh every 5-6.5 s while awake, 30 s base | `life/useCrewLife.ts:52-60` | `BT`: `SocietyRoomChanged`/`SocietyMessageSent`/`SocietyResultPosted`/`SocietyTeamChanged` trigger `roster.delta` within 1 s; a 30 s safety re-read happens; nothing is read while Verse is `Dormant` |
| F-03 | Coding panes as technicians (workspace, call sign, dot, state) | `../crewFeeds/codingFloor.ts`, `src/store/workspacePanes` | `BT`: `roster.snapshot.panes[]` matches `GET /api/agentic-ide/panes`; `AgenticIdeTerminalsAdded/Closed` → `roster.delta` within 1 s |
| F-04 | Pane look stable per pane lifetime (`history_id` hash) | `../crewFeeds/codingFloor.ts` | `AT`: the same `history_id` dresses the same body and accent across relaunches |
| F-05 | Pane screens, about 450 ms, at most 6 seated | `../crewFeeds/usePaneScreens.ts` | `BT`: `screens.watch` for ≤ 8 panes pushes dirty rows at ≤ 10 Hz; latency PTY→frame ≤ 200 ms p95 |
| F-06 | In-page xterm buffers with colours and attributes | `src/lib/liveTerminals.ts`, `effects/terminalCanvas.ts` | `BT`: the styled mirror yields fg/bg/bold/dim/inverse/underline per cell for a scripted ANSI stream, equal to xterm's reading (golden file) |
| F-07 | Plain replay for a pane the IDE has not mounted | `effects/terminalCanvas.ts` `snapshotText` | `BT`: a pane with no web client still streams cells (styled mirror seeded from replay bytes) |
| F-08 | Desk chat tails, every 2.5 s, at most 6 agents | `../crewFeeds/useDeskChats.ts` | `BT`: `chat_tails.watch` → `chat_tails.update` on `SocietyMessageSent` within 1 s; at most 6 agents watched |
| F-09 | Chat groups (teams) | `src/lib/societyChatGroups.ts`, `life/useCrewLife.ts` | `BT`: `groups.snapshot` matches the group read; a new group → `groups.delta` |
| F-10 | Team meetings and rounds (who speaks, transcript), leased poller plus socket | `../crewFeeds/useTeamRounds.ts`, `../crewFeeds/teamwork.ts` | `BT`: a round opened/settled and each line said → `meetings.update` with speaker and transcript tail; a round running before connect is in the snapshot |
| F-11 | `/ws` bus events Society* and ProgressionAwarded | `life/useCrewLife.ts`, `../progression/useProgressionSync.ts` | `BT`: each of the four event types reaches the right topic (roster, meetings, progression) once, in order, with `seq` |
| F-12 | Progression read plus slow re-read | `../progression/useProgressionSync.ts` | `BT`: `progression.snapshot` on subscribe equals `GET /api/progression`; `ProgressionAwarded` → `progression.awarded` |
| F-13 | Level-ups that happened while the Verse was closed are told once | `../progression/progressionStore.ts:158-190` (`jarvis.verse.levels.seen.v1`) | **[gap]** `BT`: the backend keeps the last seen award seq per person; `GT`: one missed promotion is shown once on the next show, not again on the one after |
| F-14 | Companion pet (chosen pet, mascot style pet) | `../companion/companionPetStore.ts:59-75` (`useSyncCompanionPet`) | **[gap]** `BT`: a `companion` topic carries the active pet id and look; `AT`: the pet pawn uses that look; a change applies within 2 s |
| F-15 | IDE state and IDE agent list for the launcher | `hud/LauncherPanel.tsx` (`fetchIdeState`, `fetchIdeAgents`) | `BT`: `launcher.options` reply lists workspaces (active first) and agents from the same endpoints |
| F-16 | Static content from `public/verse` | `content/loadDeck.ts`, `actors/characters.ts`, `audio/verseAudio.ts` | `ST`: every asset the Unreal build needs is cooked into its paks; `GT`: Verse runs with `public/verse` absent |
| F-17 | i18n chunk `ship` for the person's language | `src/i18n/index.ts:215`, `src/i18n/locales/ship/*.json` | `BT`: `welcome.locale.strings` carries `ship/verse.<lang>.json` + `ship/ranks.<lang>.json` for the app language; see section 18 |
| F-18 | Commander rank and uniform | `ranks/useRanks.ts` (`useCommanderRank`, `useCommanderUniform`), `../progression/cosmetics.ts:84` | `AT`: the commander's plate tiles and uniform tier follow `progression.snapshot`; **[gap]** the uniform choice (today `localStorage dodaios.verse.uniform.v1`) moves to app config and arrives in `welcome` |
| F-19 | No feed is read while the Verse is hidden | `useCanvasAwake` gating in every feed hook | `BT`: in `Dormant` the bridge carries only heartbeats and events, no screen frames; screens unsubscribed |

## 6. Crew life

| Id | Feature | Today | Unreal acceptance check |
|---|---|---|---|
| C-01 | Duty status from run state, pane dot and live signals | `ranks/dutyStatus.ts` | `AT`: table test over every `(run_state, asking, last result, pane dot)` row of `ranks/ranks.test.ts` gives the same status |
| C-02 | Precedence paused > waiting > working > error > idle; working never shown in error | `ranks/dutyStatus.ts:21-24` | `AT`: same table test |
| C-03 | Officer working: bridge console, seated typing | `life/planner.ts` `intentOf` | `GT`: a seeded working agent sits at a bridge console playing the typing loop |
| C-04 | Officer waiting: stands at console, turns to the commander | `life/planner.ts` | `GT`: waiting agent stands at its console and its yaw tracks the commander within 15° |
| C-05 | Officer error: at console, alert, not typing | `life/planner.ts` | `GT` |
| C-06 | Officer paused: in a bunk on ops, asleep | `life/planner.ts` | `GT` |
| C-07 | Officer idle: seeded off-duty routine, 6 min slots (mess 5, corridor 2, viewport 3) | `life/planner.ts:40-63` | `AT`: `idleVenueOf(id, t)` port gives today's venue for 1,000 seeded `(id, t)` pairs (golden table exported from the TS function) |
| C-08 | Technician working/waiting/error at an engineering terminal; idle in the workshop | `life/planner.ts:68-75` | `GT`: one pane per state lands at the right venue and activity |
| C-09 | Home consoles handed out in service order (lead first, then arrival, then id), stable when others leave | `life/planner.ts:11-14`, `life/crew.ts` `byServiceOrder` | `AT`: golden placement for a 12-member roster; removing one idle member changes no other console |
| C-10 | Nobody shares a seat; previous socket kept across refreshes | `life/planner.ts` `placeOnDeck` | `AT`: 100 random roster refreshes → no socket twice, ≥ 95 % of members keep their socket |
| C-11 | Team round: speaker at the briefing table talks, free members listen | `life/planner.ts:77-82`, `../crewFeeds/teamwork.ts` | `GT`: a scripted round with 3 members → 1 talking at briefing, 2 listening; speaker change moves the talk clip |
| C-12 | Agent-to-agent message: the sender walks to the receiver once free | `../crewFeeds/teamwork.ts:13-17` | `GT`: a `SocietyMessageSent` ASSIGN between two idle agents → the sender's pawn reaches within 1.5 m of the receiver |
| C-13 | New agent arrives at the hangar shuttle and walks to the lift for 40 s | `life/cast.ts:81-89`, `life/useCrewLife.ts:28` | `GT`: create an agent while on hangar → a pawn spawns at the shuttle and reaches the lift socket |
| C-14 | Members on the deck when it opens stand in place; others come by lift | `life/cast.ts:77` (`entry`) | `AT` |
| C-15 | Leavers walk to the lift and vanish | `actors/ActorsLayer.tsx` | `GT`: a member whose venue moves off deck walks to the lift and despawns |
| C-16 | Re-plan every 20 s for off-duty moves | `life/useCrewLife.ts:26` | `AT`: idle slot boundary crossed → the member moves within 21 s |
| C-17 | Own walk pace per member 1.2-1.45 m/s; commander 1.45 | `life/cast.ts:58-61` | `AT`: pace from the same hash as `walkPace` |
| C-18 | Paths: A* with string pulling, local avoidance, no corner cutting | `nav/pathfind.ts`, `actors/locomotion.ts` | `AT`: Recast path on each deck between all station pairs exists; 20 pawns crossing a corridor → no overlap of capsules over 1 s |
| C-19 | Commander salute: the crew salutes on a promotion | `VerseStage.tsx:200` (`cheerUntil`), `actors/ActorsLayer.tsx` | `GT`: `progression.awarded` with a commander promotion → every visible crew pawn plays the salute within 1 s |
| C-20 | Ship's company: up to 3 troopers on patrol routes, sentry posts, up to 2 utility drones | `life/cast.ts:20-21,104-124` | `AT`: on each deck the counts match today's manifest routes and posts, capped 3/2 |
| C-21 | Companion drone follows the commander at heel | `life/cast.ts:96-100` | `AT`: walk 30 m → companion stays within 2.5 m after 2 s |
| C-22 | Rank looks: uniform by tier, accent colour, lit plate tiles, cap for capped tiers | `actors/look.ts`, `ranks/ranks.ts` | `AT`: for each of the 15 ranks the plate's lit tiles equal `plateTiles(id)`; uniform material equals the tier's |
| C-23 | Room light: people lit by the room they stand in, eased over 0.5 s | `actors/roomLight.ts` | `SS` GPU: an officer walking from bridge to mess shows the mess's colour on the reference shot; Lumen covers it |
| C-24 | Dev override of a member's duty | `life/devOverrides.ts` | `AT`: `Verse.QA.SetDuty <id> working` forces the status; `none` releases it (section 19) |

## 7. Stations and the use key

| Id | Feature | Today | Unreal acceptance check |
|---|---|---|---|
| S-01 | Station kinds: agents_list, team, service_record, mess_call, games, quartermaster, coding_launcher, create_agent, lift | `content/deck.ts:38-40` | `ST`: the station enum has exactly these nine plus `armoury`; every manifest station is placed |
| S-02 | `agents_list` opens the agent ledger in the app | `VerseStage.tsx:368-370` | **[gap]** `BT`: `agents.open_list` → web UI opens the Agents ledger (side panel: Agents tab, `OfficeTab.tsx:57`); Verse hides |
| S-03 | `team` opens the group of the running team, else the first team; none → notice | `VerseStage.tsx:359-375` | **[gap]** `BT`: `group.open {group_id}` → web UI opens that group; `AT`: no team → localized `verse.notice.no_team` |
| S-04 | `service_record` in the records hall opens the ladder, elsewhere the record | `VerseStage.tsx:377` | `AT`: records hall station opens the service record on "Ladder", ready room desk on "Record" |
| S-05 | `quartermaster` opens the record on "Rewards" | `VerseStage.tsx:378` | `AT` |
| S-06 | `mess_call` calls idle officers to the mess for 90 s; again ends it; nobody → notice | `VerseStage.tsx:379-387` | `GT`: 3 idle officers → all head to the mess, notice `verse.notice.mess_called` count 3; second use ends it; 0 idle → `mess_nobody` |
| S-07 | `games` opens the simulator: list of programmes, retro arcade, asteroid run | `hud/SimulatorPanel.tsx` | **[gap]** `BT`: `simulator.open {programme}` → the web arcade opens (`src/components/society/arcade/*` stays web); a new best reports `simulator_record "asteroid-run"` |
| S-08 | `coding_launcher` opens the launcher | `VerseStage.tsx:390`, `hud/LauncherPanel.tsx` | `AT` + section 8 |
| S-09 | `create_agent` creates an agent (or the host's own create flow); one at a time | `VerseStage.tsx:322-329` | `BT`: `agent.create` runs the same code as `POST /api/society/agents`; a second call within 5 s → `rate_limited`; cancel is no error |
| S-10 | `lift` walks there and opens the lift | `VerseStage.tsx:392` | `AT` |
| S-11 | Using a station walks the commander to its spot first | `VerseStage.tsx:367` | `AT`: activate from 10 m away → commander path ends at the station spot |
| S-12 | E works what the crosshair is on, else the station within reach, the one in front preferred | `VerseStage.tsx:639-643,445-455`, `life/control.ts` `stationWithin` | `AT`: port of `eyeLevelGame.test.tsx:182-192` cases (nearest without facing, front with facing, behind when alone) |
| S-13 | Station within reach checked 5 times a second, offered as a prompt with its key below the view centre | `VerseStage.tsx:466-479`, `hud/FloatingLabels.tsx` | `AT`: walk into reach → prompt with localized name, action and "E" within 250 ms; never drawn on the commander's back |
| S-14 | Station labels on hover (name + action, no key) | `VerseStage.tsx:862-876` | `AT`: hovering a station in overview shows name and action without the key glyph |
| S-15 | Desk takeover stations: each desk monitor showing exactly one pane | `VerseStage.tsx:423-437` | `AT`: desks with 0 or 2+ panes, and the master station, offer no takeover |
| S-16 | Takeover label is the pane's title, action "take over" | `VerseStage.tsx:868-870` | `AT` |
| S-17 | Armoury station starts the duel (successor of the 4 reactor ring consoles) | `VerseStage.tsx:412-416` (ring consoles) | **[changed]** `AT`: E at the armoury opens the duel panel; the ring consoles are gone |
| S-18 | Clicking a station in overview activates it | `VerseStage.tsx:550-554` | `AT` |

## 8. Actions into the app

| Id | Feature | Today | Unreal acceptance check |
|---|---|---|---|
| X-01 | Open a pane from a technician's card | `VerseStage.tsx:331-334`, `../crewFeeds/codingNavigate.ts` | `BT`: `pane.open {pane_id}` → `VerseOpenRequested` → web opens the IDE on that pane, side panel un-maximized; Verse hides |
| X-02 | Open an agent from an officer's card | `VerseStage.tsx:335-336` | `BT`: `agent.open` → web opens the agent (host `onSelectAgent`, else Agents section) |
| X-03 | Launcher: pick workspace, CLI agent, count 1-4, brief; opens panes and briefs them | `hud/LauncherPanel.tsx:14-17,79-94` | `BT`: `launcher.start` with count 3 → 3 panes opened, started, briefed; reply per pane `submitted` |
| X-04 | Launcher: one batch at a time, closing stops the batch | `hud/LauncherPanel.tsx:9-10`, `hud/hudDialogs.test.tsx:79` | **[gap]** `BT`: second `launcher.start` while one runs → `busy`; `launcher.cancel` stops further panes |
| X-05 | Launcher: start timeout 30 s, poll 0.6 s, failure line with reason | `hud/LauncherPanel.tsx:16-17,71` | `BT`: a pane that never goes live → reply `submitted:false` after 30 s; `AT`: the localized failure line shows the reason |
| X-06 | Launcher "Open IDE" button | `VerseStage.tsx:993` | `BT`: maps to `pane.open` without a pane (IDE section) **[gap]** `ide.open` |
| X-07 | Desk takeover: the real terminal at 1:1, keys land on the pane | `hud/TakeoverPanel.tsx` | **[changed]** `BT`: `ide.focus_terminal {pane_id}` → web opens the IDE on that pane with keyboard focus in its xterm; desktop raises the app; Verse hides |
| X-08 | Takeover "Changes" opens the pane's changes | `hud/TakeoverPanel.tsx:85-92` | **[gap]** `BT`: `pane.open {pane_id, open:"changes"}` → `requestPane(..., {open:"changes"})` |
| X-09 | Takeover of a pane the IDE grid has not mounted opens it; never a second copy | `hud/TakeoverPanel.tsx:15-20`, `takeover.test.tsx:142-165` | `BT`: focus on an unmounted pane mounts it once; on a mounted pane no new terminal |
| X-10 | Takeover leaves on Ctrl+Q; Escape belongs to the agent | `hud/TakeoverPanel.tsx:74-84` | **[changed]** n/a in Verse (no terminal inside it); `VT`: after `ide.focus_terminal`, Escape reaches the xterm |
| X-11 | All app actions are idempotent and rate-limited | n/a | `BT`: open commands 4/s, `agent.create` 1 per 5 s, `launcher.start` 1 per 10 s (`contracts/bridge-protocol.md` §11) |

## 9. World actions (progression)

| Id | Feature | Today | Unreal acceptance check |
|---|---|---|---|
| W-01 | `daily_visit` on the first awake moment | `../progression/useProgressionSync.ts:90` | `GT`: first `Visible` of a launch sends one `progression.action daily_visit`; later shows do not |
| W-02 | `deck_discovered` per deck on arrival | `../progression/useProgressionSync.ts:91` | `GT`: arriving on each deck sends one action with the deck id |
| W-03 | `inspection`: every room of the deck visited, once per deck per day | `life/useWorldActions.ts:31-48` | `GT`: harness walks the commander through every room volume → one action with the deck id; a second tour that day sends none |
| W-04 | `walk_together`: every 50 m with the companion within 2.5 m, 0.5 s tick | `life/useWorldActions.ts:20-23,49-58` | `AT`: 120 m at heel → exactly 2 actions; 120 m with the drone held back → 0 |
| W-05 | `team_briefing`: a round running while on the bridge, once per round | `life/useWorldActions.ts:62-71` | `GT`: a round runs, commander on bridge → 1 action with the team id; the round ends and runs again → 1 more |
| W-06 | `simulator_record` when the asteroid best rises | `hud/SimulatorPanel.tsx:39` | `BT` with S-07 |
| W-07 | Reporting twice is harmless (server meters) | `life/useWorldActions.ts:2-3` | `BT`: duplicate actions pay once (existing `progression/service.py` rules) |
| W-08 | `duel_won` / `duel_lost` and duel stats in the service record | none today (`rules.py:134`) | `BT`: one `duel.result` per set (`won`, `lost`, `unfinished`), idempotent per `match_id`; `won` and `lost` sets of 60 s or more pay commander XP, every result updates `duel_stats` (wins, K/D, headshots, finishers); `AT`: service record shows them |

## 10. Screens and in-world effects

| Id | Feature | Today | Unreal acceptance check |
|---|---|---|---|
| E-01 | Bridge console shows its officer's chat tail | `effects/useScreenFaces.ts` | `GT`: a `SocietyMessageSent` for an officer appears on its console render target within 2 s |
| E-02 | Console belongs to its officer whether or not they sit there; an empty console says so | `effects/useScreenFaces.ts:8-9` | `AT`: officer at the mess → console still shows their tail; no owner → localized empty text |
| E-03 | Engineering terminal shows its pane cell for cell, colours and box drawing | `effects/terminalCanvas.ts` | `SS` GPU: golden pane (ANSI colours, box-drawing frame, wide glyph) on a monitor matches the reference; `AT`: cell-to-glyph mapping on the render target equals the bridge cells |
| E-04 | Bottom block of rows that fits is shown; width fills the tile | `effects/terminalCanvas.ts:8-10` | `AT`: 60-row pane on a 24-row monitor shows rows 37-60 |
| E-05 | Engineering master station: every coding pane in a grid | `effects/useScreenFaces.ts:6-7` | `GT`: 5 panes → master screen shows 5 tiles |
| E-06 | Briefing wall screen: the running round's transcript | `effects/useScreenFaces.ts:7-8` | `GT`: lines of a scripted round appear in order |
| E-07 | Any other screen: standby page | `effects/useScreenFaces.ts:8` | `AT` |
| E-08 | Screen colours: green live work, amber needs the commander, red fault, dim blue standby; header strip with station and status; faint scanlines | `effects/screenPainter.ts:2-7` | `SS` GPU per state; `AT`: header text equals the localized status |
| E-09 | Cursor blink; redraw only on change, a few screens per frame | `effects/ScreensLayer.tsx:5-6` | `AT`: game-thread cost of monitors ≤ 0.3 ms/frame with 8 busy panes; far monitors update at 2 Hz (architecture §5.3) |
| E-10 | Status beacon over each crew head: steady (working), slow pulse amber (waiting), slow pulse red (error), none (idle, paused) | `effects/BeaconsLayer.tsx`, `ranks/dutyStatus.ts:5-11` | `AT`: beacon component state per status; `SS` GPU for colour |
| E-11 | Floor ring at each crew member's feet in the status colour, grey off duty; constant few pixels, drawn over everything | `effects/BeaconsLayer.tsx:6-12` | `AT`: ring screen size within ±1 px at 5 m and 40 m in overview; visible through a console (custom depth) |
| E-12 | Holo tables: projection lit during a team round (briefing table) or always (strategy table) | `effects/HoloLayer.tsx`, `VerseStage.tsx:845-855` | `AT`: briefing holo off without a round, on with one; strategy holo always on |
| E-13 | Lamps blink at their cooked rate; alarm lamps blink only while someone on the deck has a fault; reactor core breathes; occasional fixture dip | `effects/LightsLayer.tsx` | `AT`: an `error` member on the deck turns alarm lamps on, clearing it turns them off; blink rates equal the manifest's `blink_hz` ± 5 % |
| E-14 | Reduced motion keeps every state but drops pulses and movement | `effects/*` `reduced` props | `AT`: `reduced_motion` → beacons steady, holo rings still, no fixture dips |
| E-15 | Labels hidden behind walls and behind the camera at eye level | `hud/FloatingLabels.tsx:7-10`, `eyeLevelGame.test.tsx:349-376` | `AT`: port of the three cases |

## 11. HUD, cards and notices

| Id | Feature | Today | Unreal acceptance check |
|---|---|---|---|
| H-01 | Deck title top left: number, name, aboard / working / waiting counts | `hud/DeckBar.tsx` `DeckTitle` | `GT`: seeded 4 aboard, 2 working, 1 waiting (+ error counts as waiting) → widget shows 4/2/1 |
| H-02 | Rank card beside the title (compact variant in the panel) opens the service record | `ranks/RankCard.tsx` | `AT`: click opens the record on "Record" |
| H-03 | Tool rail: view switch, lift, hoverboard, commander, duel, settings, help | `hud/DeckBar.tsx:67-120` | `AT`: Verse bar has each control with its key hint; duel hidden in the panel, settings only where eye level is possible |
| H-04 | Name plate on hover/selection: name, rank (or "terminal" for technicians), status, accent | `VerseStage.tsx:861-873` | `AT` |
| H-05 | Crew card: name, plate, rank, status, post; open chat/terminal, show, walk over; close | `hud/CrewCard.tsx` | `AT`: open → X-01/X-02; show turns the camera to them; walk sends the commander to a walkable spot 0.9 m in front; show/walk hidden when not on this deck |
| H-06 | First click selects a crew member, a second click on the same one opens them | `VerseStage.tsx:514-518,537-541` | `AT` |
| H-07 | Notices: one line, 4.2 s; help text 15 s | `VerseStage.tsx:117-120,311-314` | `AT`: notice lifetime 4.2 s ± 0.1; help 15 s |
| H-08 | Help text differs at eye level and in overview, plus the duel line | `VerseStage.tsx:988` | `AT`: `verse.stage.help_eye` vs `verse.stage.help` + `verse.stage.help_duel` |
| H-09 | Reticle at eye level, marked when something usable is under it | `VerseStage.tsx:990` | `AT` |
| H-10 | Hint "click to look" while the mouse is free at eye level | `VerseStage.tsx:991-993` | **[changed]** `AT`: shown when the Verse window has focus but no mouse capture |
| H-11 | Hint "click for keys" while the keys go elsewhere | `VerseStage.tsx:995-997` | **[changed]** `AT` (panel stream): shown in the panel until a click on it routes input to the stream |
| H-12 | Dialogs: modal, focus trapped, Escape or scrim closes, focus returns to the opener | `hud/VerseDialog.tsx`, `hud/hudDialogs.test.tsx:53` | `AT`: every Verse menu traps keyboard/gamepad navigation, Esc closes, focus returns to the previous widget |
| H-13 | Opening a dialog releases mouse look | `VerseStage.tsx:672-674` | `AT`: opening any menu shows the cursor and stops look input |
| H-14 | A HUD panel open/close click sound | `audio/useStageAudio.ts:4` | `AT`: audio event log has the click |

## 12. Ranks and the service record

| Id | Feature | Today | Unreal acceptance check |
|---|---|---|---|
| R-01 | 15 ranks in 4 tiers, mirrored from `rules.py RANKS` | `ranks/ranks.ts:21-60` | `ST`: the rank DataAsset equals `rules.py` `RANKS` (ids, levels, tiers, plate patterns); replaces `tests/unit/progression/test_frontend_parity.py:74` |
| R-02 | Rank derived from level, never the server's rank id | `ranks/ranks.ts:6-8` | `AT`: a snapshot with a stale rank id and level 23 shows the level-23 rank |
| R-03 | Rank plate: six hexagon tiles, unique pattern per rank | `ranks/ranks.ts:10-18`, `ranks/RankPlate.tsx` | `AT`: all 15 patterns distinct and symmetric |
| R-04 | Service record dialog with five pages: Record, Ladder, Quartermaster, How to earn, Crew | `ranks/ServiceRecord.tsx:1-14,56-67` | `AT`: five tabs in that order, each opens by `openRecord(tab)` equivalent |
| R-05 | Record page: plate, rank, level, XP, next rank and what is missing, ribbons, recent log, bell | `ranks/ServiceRecord.tsx` `RecordPage` | `GT`: seeded progression → every field matches the snapshot |
| R-06 | Ladder: held ranks plain, current marked red, ahead dimmed with XP missing | `ranks/ServiceRecord.tsx` `LadderPage` | `AT` |
| R-07 | Quartermaster: uniforms by tier, pick one or the highest issued; ribbons with levels | `ranks/ServiceRecord.tsx` `QuartermasterPage`, `../progression/cosmetics.ts` | `AT`: picking a uniform changes the commander's material at once and persists (F-18) |
| R-08 | How to earn: every rule the running server pays, with limits | `ranks/ServiceRecord.tsx` `EarnPage`, `ranks/rankModel.ts` | `GT`: rules list equals the snapshot's `rewards` with cooldowns and caps |
| R-09 | Crew page: every officer's rank, highest first, and the companion | `ranks/ServiceRecord.tsx` `CrewPage` | `AT` |
| R-10 | Promotion notice for commander/companion: plate tiles laid one by one, rank, level, salute line, issued items; closes on acknowledge, Escape or 7 s; never takes focus | `ranks/PromotionNotice.tsx:2-8` | `AT`: notice lasts 7 s, does not take input focus from gameplay |
| R-11 | Other level-ups: a quiet corner line, 5 s or a click | `ranks/PromotionNotice.tsx:9-10` | `AT` |
| R-12 | Level bell sound on award, switchable | `../progression/levelSounds.ts:11` (`jarvis.verse.level.sound.v1`) | **[gap]** setting moves to app config; `AT`: off → no bell |
| R-13 | Overlay drawn only while the Verse is visible; the queue is kept | `ranks/RanksOverlay.tsx:13-14` | `GT`: award while `Dormant` → shown on the next show |
| R-14 | Rank words localized (`verse.ranks.rank.<id>`) in 5 locales | `ranks/ranksLocales.test.ts` | `ST` with N-02 |

## 13. Views, camera and input

| Id | Feature | Today | Unreal acceptance check |
|---|---|---|---|
| V-01 | Three views: overview (bird's-eye), third person, first person | `engine/realtime/viewMode.ts` | `AT`: `Verse.QA.View.Set` to each; state reports it |
| V-02 | V cycles overview → third → first, skipping what cannot show | `viewMode.ts` `cycleView`, `views.test.tsx:31` | `AT`: port of the test |
| V-03 | 1/2/3 (top row and keypad) pick a view | `viewMode.ts:28-32` | `AT` |
| V-04 | Wheel moves third person 1.2-5 m eased; pushing past the closest hands over to first; scrolling out of first returns to third | `engine/realtime/shoulderRig.ts:6-10,50-51`, `views.test.tsx:67-108` | `AT`: ports of the five wheel cases |
| V-05 | Third person: commander lower right third, camera a little above the head, looking down slightly; never through walls (pulled in at once, eased out) | `shoulderRig.ts:4-6,20-21` | `AT`: framing ratio test; camera spring arm probe never inside geometry over a scripted wall-hug walk |
| V-06 | First person: eyes at 1.65 m just in front of the face, no sideways lag, segment test keeps it out of walls | `shoulderRig.ts:12-15,59` | `AT`: eye height 165 cm ± 2; facing a wall at 0.1 m the camera stays outside it |
| V-07 | Shoulder↔eyes blend over about 0.2 s, FOV included | `shoulderRig.ts:15-16`, `views.test.tsx:141` | `AT` |
| V-08 | First person pitch range wider than third, clamped back on return | `views.test.tsx:161` | `AT` |
| V-09 | FOV defaults 70° third, 85° first, settable in range | `shoulderRig.ts:40-42`, `engine/realtime/viewSettings.ts` | `AT` |
| V-10 | Sensitivity and inverted Y applied the same way in every view and in the duel | `engine/realtime/mouseLook.ts`, `views.test.tsx:183-190` | `AT`: same mouse delta turns the deck view and the duel camera by the same angle |
| V-11 | Raw mouse input where available | `mouseLook.ts`, `views.test.tsx:206` | `AT`: Enhanced Input uses raw mouse deltas (no OS acceleration) |
| V-12 | Commander walks relative to the view, faces it walking, leans ≤ 45° into a strafe, walks backwards facing the view | `views.test.tsx:222-237` | `AT`: ports of the three cases |
| V-13 | Shift hurries | `VerseStage.tsx:684` | `AT` |
| V-14 | Overview: WASD/arrows pan, +/- zoom about the centre, wheel zooms, drag looks | `VerseStage.tsx:700-707`, `engine/pointerInput.ts` | `AT` |
| V-15 | Click on the floor walks the commander there (overview and eye level, nearest walkable within 1.2 m) | `VerseStage.tsx:545-565`, `nav/floorPick.ts` | `AT`: click on floor → path to the projected point; on a wall → nothing (`eyeLevelGame.test.tsx:141`) |
| V-16 | Clicks pick a crew member in plain view, never one behind a wall | `engine/realtime/eyePick.ts`, `eyeLevelGame.test.tsx:133` | `AT` |
| V-17 | Commander button: third person reframes, overview focuses the commander | `VerseStage.tsx:984` | `AT` |
| V-18 | Show a crew member: turn toward them at eye level, else centre the map | `VerseStage.tsx:842-853` | `AT` |
| V-19 | L toggles mouse look | `VerseStage.tsx:631-637,712` | `AT`: L toggles mouse capture at eye level |
| V-20 | Choosing third/first takes the mouse at once, overview gives it back | `VerseStage.tsx:399-411` | `AT` |
| V-21 | The view last chosen is kept (default third) | `viewSettings.ts` (`dodaios.verse.view.v1`) | `AT`: relaunch restores the view; **[gap]** one-time import of today's localStorage values (section 20) |
| V-22 | A new deck frames the commander where they come aboard | `VerseStage.tsx:226-236` | `AT` |
| V-23 | Compact panel: overview and walking only; small panel stays overview | `engine/stageView.ts`, `VerseStage.tsx:246-262` | **[changed]** `GT`: in `Panel` state the stream offers overview and third person, never first person or the duel (architecture §6) |
| V-24 | Panel quality "auto" renders at the low tier | `VerseStage.tsx:291-292` | `GT`: panel stream renders with Low scalability; GPU ≤ 1.5 ms per frame at 960x600 |
| V-25 | Quality auto/high/low; auto drops to low under ~45 fps | `engine/realtime/RealtimeBackdrop.tsx:14-17`, `viewSettings.ts` | `AT`: forced slow frames on auto → Low scalability after the window; pinned High stays |
| V-26 | Frame stats readable by QA in every build | `VerseStage.tsx:210` (`__verseStats`), `runtime.ts` | `AT`: `Verse.QA.Stats` returns fps, tier and frame ms (section 19) |

## 14. Focus, keys and Escape

| Id | Feature | Today | Unreal acceptance check |
|---|---|---|---|
| K-01 | The Verse reads its keys only while it has focus; never from a text field | `engine/stageFocus.ts:1-6`, `stageFocus.test.tsx:29-50` | **[changed]** `AT`: keys act only while the Verse window has OS focus; `VT`: the panel stream forwards keys only after a click on it, never while an input or xterm in the page has focus |
| K-02 | The stage never pulls focus on its own | `stageFocus.ts:24-31`, `stageFocus.test.tsx:62` | `BT`: Verse takes foreground only after `lifecycle.show` (with `AllowSetForegroundWindow` from the app); never on boot, never on an event |
| K-03 | The full stage takes the keyboard when opened, unless someone is typing; the panel never takes it | `VerseStage.tsx:622-628` | `BT`: `show` while a text field in the app has focus and `reason:"verse_view"` still shows (explicit user act); the panel never sends a focus request |
| K-04 | Ctrl/Meta/Alt chords are never the Verse's | `VerseStage.tsx:672-675` | `AT`: Alt+Tab, Ctrl+anything pass to the OS and bind nothing |
| K-05 | Escape order: end mouse look, else close the card or panel, else let it through (leaves the Verse) | `VerseStage.tsx:677-688` | `AT`: with capture → Esc releases it; with a menu → closes it; with nothing open → opens the in-game menu that offers "Back to the app" |
| K-06 | One key back to the app | none today (Escape leaves the Agents view) | `AT`+`BT`: F10 (rebindable) sends `focus.return_to_app`, Verse hides, app raised within 300 ms |
| K-07 | Losing focus clears held keys and stops Arc Storm | `VerseStage.tsx:725` (`blur`) | `AT`: focus loss while W and F held → commander stops, storm ends |
| K-08 | Focus loss pauses a running duel | `VerseStage.tsx:657-668,795` | `AT`: focus loss mid-match → match paused, resumes only on explicit resume |
| K-09 | Key map: WASD/arrows, Shift, V, 1/2/3, E, L, F (hold), B, +/-, F9 (dev) | `VerseStage.tsx:690-718` | `ST`: Enhanced Input mapping context contains each binding; `AT`: each fires its action |
| K-10 | Pointer lock released by the OS pauses the duel | `VerseStage.tsx:657-668` | `AT`: mouse capture loss mid-match → pause |
| K-11 | Workspace first, leaving is one key away; hidden pauses | product rule (README Hosting, `architecture.md` 1.2) | `GT`: from any state (menu, duel, takeover prompt) F10 returns to the app in ≤ 300 ms |

## 15. Extras

| Id | Feature | Today | Unreal acceptance check |
|---|---|---|---|
| Z-01 | Sovereign skin: the commander's body in every view (deck, duel, first-person arms) | `actors/characters.ts:15-21`, `life/cast.ts:93` | `AT`: commander pawn mesh is the Sovereign skeletal mesh in deck, duel and first person; an install without it falls back to the officer body |
| Z-02 | Sovereign cloak: three spring columns, two segments, pitch lifts walking, roll swings on strafe/turn, hem lags on stop, flutter while moving | `actors/cloak.ts`, `abilities/sovereign.test.ts:36-90` | `AT`: port of the cloak tests (still at rest, lift on walk, sideways on strafe, lower lags upper) on the cloak bones `Cloak_{R,C,L}{1,2}` |
| Z-03 | First-person arms cut from the commander's own body; Sovereign sleeves black velvet with a gold cuff | `viewmodel/viewmodel.ts:11-17`, `viewmodel/ViewmodelLayer.tsx:39-43` | `AT`: first-person arms use the commander mesh's arm section; `SS` GPU arms on the reference shot; gold only on the cuff |
| Z-04 | Arms hang loose and swing with the walk on the deck; never sink into walls; do not stretch with FOV | `viewmodel/viewmodel.ts:7-10,22-24` | `AT`: arms drawn with own FOV; facing a wall at 0.1 m no arm pixel is hidden by it |
| Z-05 | Arc Storm: hold F, lightning from both hands toward the aim; arms rise; bolts re-strike many times a second; light flickers; sparks where they land | `abilities/arcStorm.ts`, `actors/ActorsLayer.tsx:240-251` | `AT`: hold F → storm level rises, both hand sockets emit, aim follows the view at eye level and the body's facing in overview; release → fades |
| Z-06 | Arc Storm bolt geometry: from hand to target, fixed segment count, near the line, same seed same bolt | `abilities/sovereign.test.ts:5-33` | `AT`: port of the three bolt tests on the Niagara beam's control points |
| Z-07 | Arc Storm sound: low hum plus crackle that jumps with each strike; silent without audio | `abilities/arcSound.ts` | `AT`: audio log has hum on press, crackle level tied to strikes, stop on release |
| Z-08 | Arc Storm colour follows the palette | `abilities/arcStorm.ts:2-8` (violet-white today) | **[changed]** `SS`: palette check finds no violet or cyan; core cool white, glow from the allowed accents (README "Look") |
| Z-09 | Hoverboard on B: folds out, glide 5.5 m/s, speeds up toward the held direction, coasts to a stop, loses speed on a wall, hover bob, lean into speed and turns; notice on/off | `actors/hoverboard.ts:18-19`, `actors/hoverboard.test.ts`, `VerseStage.tsx:414-422` | `AT`: port of `hoverboard.test.ts`; top speed 550 cm/s ± 5 %; localized `verse.board.on/off` |
| Z-10 | Arc Storm and hoverboard never in the duel | `VerseStage.tsx:415`, `ActorsLayer.tsx:241` | `AT`: in arena mode F and B do nothing and the board folds away |
| Z-11 | Earth view outside the hull: Earth in low orbit below and ahead of the viewports, sun, stars; turns at about orbital speed; no parallax walking past a window | `engine/realtime/spaceView.ts:1-13,64,345` | `AT`: Earth actor rotation rate equals today's `ORBIT_RAD_PER_S × orbitSpeed` ± 5 %; space rendered at infinity (sky sphere / separate scene capture); `SS` from each deck's viewport |
| Z-12 | Space only through glass; gaps the deck left open are painted hull dark | `engine/realtime/hullMask.ts` | `SS`: per deck, no star or Earth pixel outside glass masks on 6 reference shots |
| Z-13 | Earth textures from NASA public-domain imagery (day, night lights, clouds, relief) | `scripts/verse/earth.py` | `ST`: Unreal Earth textures cite `art/verse/LICENSES.md` rows; the GEBCO elevation terms are checked and recorded in the ledger (`contracts/art-pipeline.md` 11) |
| Z-14 | Deck ambience loops, quiet; stop while hidden; volume setting; app-wide UI sound off silences the Verse | `audio/useStageAudio.ts`, `audio/verseAudio.ts:12-14` | `AT`: each deck plays its loop; `Dormant` mutes; volume 0 silences; **[gap]** `settings.changed {ui_sound:false}` mutes |
| Z-15 | Sound variants and random pitch/level, never the same take twice in a row; placed sounds panned and attenuated | `audio/verseAudio.ts:7-12`, `audio/verseAudio.test.ts` | `AT`: 20 plays of a cue never repeat a variant consecutively |
| Z-16 | Recorded CC0 sounds credited | `public/verse/audio/CREDITS.md`, `public/THIRD_PARTY_NOTICES.txt:571-576` | `ST`: every Unreal sound wave cites a ledger row; notices updated |

## 16. The duel (app-level parity)

The reactor duel's mechanics are replaced, not ported (README). Its rules
live on in `contracts/combat-state.md` and `contracts/bot.md`; these rows only
hold what the app and the person rely on.

| Id | Feature | Today | Unreal acceptance check |
|---|---|---|---|
| D-01 | Duel start panel: what it is, three opponents, controls; choosing starts at once | `hud/DuelPanel.tsx` | `AT`: panel lists normal, hard, elite and adaptive with the controls table; choosing starts the match |
| D-02 | Last difficulty remembered and focused (default hard) | `VerseStage.tsx:748`, `duel/duelController.ts:51` | `AT`: relaunch → last tier focused |
| D-03 | Entry from the tool rail (Duel button) | `VerseStage.tsx:986` | **[changed]** `AT`: the Verse bar's quick start (the in-Verse tool rail, WP18.7) starts the duel; `BT`+`GT`: the web launcher card's quick start → `POST /api/verse/show {reason:"quick_start_duel"}` → `lifecycle.show {reason:"quick_start_duel"}` → commander in the hangar, arena mode on, match running |
| D-04 | Entry from the world (arena marker, ring consoles) | `VerseStage.tsx:412-421`, `hud/duelDiscovery.test.tsx` | **[changed]** `AT`: armoury station has a marker visible from overview and near it; E opens D-01 |
| D-05 | Started elsewhere, the lift rides to the arena deck first, then the match starts once the scene is there | `VerseStage.tsx:767-783` | `AT`: start from bridge → ride to hangar, match starts after the arena is loaded |
| D-06 | No duel in the compact panel | `VerseStage.tsx:418,986` | `GT`: no duel entry in `Panel` state |
| D-07 | Overview switches to a person view on start | `VerseStage.tsx:756` | **[changed]** `AT`: first person forced in the duel (README "Camera"); third person only in kill cam and finisher |
| D-08 | Hidden stage pauses the match | `VerseStage.tsx:795` | `GT`: `lifecycle.hide` mid-match → paused; `show` → pause menu, not running |
| D-09 | Escape mid-match pauses; pause menu resume / leave | `VerseStage.tsx:575-578`, `hud/DuelHud.tsx` | `AT` |
| D-10 | Result screen with rematch; leave mid-match says so | `hud/DuelHud.tsx`, `VerseStage.tsx:796-800` | **[changed]** endless mode in sets of first to 10: `AT`: each set end shows the end-of-set screen (kills, deaths, headshots, finishers, adaptive `s`); leave shows the session summary and "again"; mid-set leave shows `verse.duel.notice.left` and sends the `unfinished` result (W-08) |
| D-11 | Leaving puts the commander back on the deck where the duel ended, keys cleared, camera reframed | `VerseStage.tsx:784-793`, `ActorsLayer.tsx:231-238` | `AT`: leave → arena mode off, commander on walkable floor near the armoury |
| D-12 | HUD: score, clock, own health, crosshair with spread, hit markers (headshot distinct, kill), damage direction arcs, call-outs, countdown and banners | `hud/DuelHud.tsx:2-12`, `hud/duelHud.test.tsx` | `AT` against `contracts/combat-state.md` HUD fields; ammo replaces heat |
| D-13 | Crew hidden inside the arena; the rest of the deck unchanged | `ActorsLayer.tsx:254-256` | Same as B-08 |
| D-14 | Mouse look shared with the deck views (sensitivity, invert, FOV) | `VerseStage.tsx:285-298` | V-10 |
| D-15 | Fair perception: no bot shot without a sighting or a heard/believed position | `combat/observe.ts`, `combat/bot/bot.test.ts:32-46` | `GT`: `contracts/bot.md` F4 fire audit, 0 unclassified shots |
| D-16 | Balance gates: no single trick beats hard; skilled model about 40 % vs elite; higher tier wins more, never always | `combat/harness/balance.ts`, `combat/harness/exploits.test.ts` | `GT` (`unreal-gauntlet`): gates of `contracts/bot.md` §10-11 green |
| D-17 | Duel sound set preloaded on entry | `audio/verseAudio.ts` `preload` | `AT`: no cue missing on the first shot (audio log) |
| D-18 | Duel result reaches progression | none today | W-08 |

## 17. Settings

| Id | Feature | Today | Unreal acceptance check |
|---|---|---|---|
| T-01 | Settings panel: sensitivity, invert Y, FOV third, FOV first, volume, quality, reset; apply at once | `hud/ViewSettingsPanel.tsx`, `viewSettings.ts:38-41` | `AT`: each control changes the live value; reset restores sensitivity 1, invert off, quality auto, FOV 70/85, volume 0.7, view third |
| T-02 | Current render tier shown in the panel | `VerseStage.tsx:1001` | `AT` |
| T-03 | Stored settings survive restarts; bad stored values read as valid | `viewSettings.ts`, `eyeLevelGame.test.tsx:251-261` | `AT`: corrupt the settings file → defaults, no crash |
| T-04 | New settings: gore full/reduced, return key | README "Gore", architecture §1.2 | `BT`: `settings.gore`, `settings.return_key` in `welcome`; `settings.changed` applies live |

## 18. i18n

| Id | Feature | Today | Unreal acceptance check |
|---|---|---|---|
| N-01 | Five locales: en, de, es, pt, zh | `src/i18n/locales/ship/verse.{en,de,es,pt,zh}.json` | `ST`: every string id the Unreal UI uses exists in all five files |
| N-02 | Keys: 206 under `verse.*` (stage, deck, state, crew, station, card, post, tools, settings, lift, notice, screen, launcher, games, duel, board, takeover) and 142 under `verse.ranks.*` | `src/i18n/locales/ship/verse.en.json`, `ranks.en.json` | `ST`: Unreal string table ids ⊆ these files; no hard-coded user-facing English in `unreal/**` (scan of `FText::FromString`/`NSLOCTEXT` literals) |
| N-03 | Strings come from the app, a string change needs no Verse rebuild | `useLocaleChunk("ship")` | `BT`: edit a value in `verse.de.json` → `welcome.locale.strings` carries it; `AT`: UI shows it |
| N-04 | Live language change | `src/i18n` `useT` re-render | `BT`+`AT`: `settings.changed {lang, strings}` re-texts every open widget without a restart |
| N-05 | German umlauts and deck names render | `hud/duelDiscovery.test.tsx:109` | `SS`: a German-locale shot with the umlaut and sharp-s glyphs (U+00E4, U+00F6, U+00FC, U+00DF) renders with no tofu; zh shot renders CJK (font fallback in the UI font asset) |
| N-06 | Placeholders `{n}`, `{count}`, `{reason}` filled | `src/i18n` `fill` | `AT`: every key with a placeholder renders with sample values and no braces left |
| N-07 | App-level Verse strings stay in the app | `src/i18n/locales/*.json` (`society.shell.mode_verse`, `society.world.mode_map`, `ide_side_panel.office.*`, `ide_threads.layout_verse`) | `VT`: launcher card and panel use these keys plus new `verse_host.*` keys in all five locales |

## 19. QA hooks

Today's hooks live on `window`; three of them (`__verseStats`, `__verseDuel`,
`__verseView`) ship in built bundles. Their successors are console commands
in Development and Test builds and, in Shipping, the same commands reached
through a bridge `qa.exec` frame that the backend only accepts when it runs
with `DODAIOS_VERSE_QA=1` **[gap]**.

| Id | Feature | Today | Unreal acceptance check |
|---|---|---|---|
| Q-01 | Frame numbers | `__verseStats` (`VerseStage.tsx:210`) | `AT`: `Verse.QA.Stats` → JSON `{fps, frame_ms, tier, state}`; `BT`: reachable in Shipping via `qa.exec` with the flag, refused without |
| Q-02 | Stage handle: runtime, camera, actor poses, live crew, set duty (dev) | `__verse` (`VerseStage.tsx:211-219`), `life/devOverrides.ts` | `AT`: `Verse.QA.Dump` (camera, every pawn pose, crew statuses) and `Verse.QA.SetDuty` |
| Q-03 | Duel driver: start(tier), leave, place, look, hold, press, state | `__verseDuel` (`VerseStage.tsx:804-819`) | `AT`: `Verse.QA.Duel.{Start,Leave,Place,Look,Hold,Press,State}`; a harness test drives a full session with them, no mouse |
| Q-04 | Duellist bodies' animation state | `__verseDuelBodies` (`duel/figure.ts:125-128`) | `AT`: `Verse.QA.Duel.Bodies` |
| Q-05 | View driver: set, look, zoom, state (person, distance, hfov, yaw, pitch, commander hidden, locked) | `__verseView` (`VerseStage.tsx:822-837`) | `AT`: `Verse.QA.View.{Set,Look,Zoom,State}` with the same state fields |
| Q-06 | Post and material tuning, loaded material names | `__verseTune`, `__verseMaterials` (`engine/realtime/RealtimeBackdrop.tsx:73-99`) | `AT`: `Verse.QA.Tune` (exposure, bloom) and `Verse.QA.Materials` |
| Q-07 | Space look override and state | `__verseSpace`, `__verseSpaceState` (`spaceView.ts:91`, `RealtimeBackdrop.tsx:169`) | `AT`: `Verse.QA.Space.{Set,State}` |
| Q-08 | Viewmodel layout retune (dev) | `__verseViewmodel` (`viewmodel/ViewmodelLayer.tsx:58`) | `AT`: `Verse.QA.Viewmodel` (non-shipping) |
| Q-09 | Content override for every deck (dev) | `?verseContent=` / `localStorage verse.content` (`content/useDeck.ts`) | `AT`: `-VerseDeck=<id>` command line (non-shipping) |
| Q-10 | Duel on any deck (testing) | `localStorage verse.duel.anyDeck` (`VerseStage.tsx:131-138`) | Retired: the arena is part of the hangar. `ST`: no such switch exists |
| Q-11 | Alignment overlay on F9 (dev) and frame readout | `engine/DebugOverlay.tsx`, `hud/DeckBar.tsx` `StatsReadout` | `AT`: `Verse.Debug.Overlay` toggles nav, sockets and station markers (non-shipping); `stat unit` readout |
| Q-12 | Headless check without pointer lock | `__verseView` docstring (`VerseStage.tsx:821`) | `GT`: the whole of sections 13-16 runs under `-nullrhi` with QA commands only |

## 20. Contract gaps to close first

These rows depended on messages or config the first contract draft lacked.
All are now in `contracts/bridge-protocol.md` §14 (and the `busy` error code
in §2); the "Proposed addition" column is what §14 defines.

| Gap | Rows | Proposed addition |
|---|---|---|
| Open the agent ledger | S-02 | Command `agents.open_list {}` → `VerseOpenRequested {target:"agents"}` |
| Open a group | S-03 | Command `group.open {group_id}` |
| Simulator programmes | S-07, W-06 | Command `simulator.open {programme}`; the arcade stays web code and reports its own rounds |
| Launcher batch control | X-04, X-06 | Reply `busy` for a second `launcher.start`; command `launcher.cancel {}`; command `ide.open {}` |
| Pane changes view | X-08 | `pane.open` gains optional `open: "changes"` |
| Seen-award marker | F-13 | Backend keeps the last told award seq per person; `progression.snapshot` carries `told_seq` |
| Companion pet | F-14 | Topic `companion` with `{pet_id, look}` from the pets endpoint and the overlay style |
| Settings moved out of browser storage | F-18, R-12, V-21, T-01, Z-14 | Config keys `verse.view.*`, `verse.uniform`, `verse.level_sound`, plus `ui_sound` in `welcome` and `settings.changed`. One-time import: on first `show`, the web app posts `dodaios.verse.view.v1`, `dodaios.verse.uniform.v1`, `jarvis.verse.level.sound.v1`, `jarvis.verse.levels.seen.v1` and `jarvis.office.arcade.asteroids.best` from its localStorage to `POST /api/verse/settings/import` |
| QA in Shipping | Q-01..Q-12 | Frame `qa.exec {command}` accepted only with `DODAIOS_VERSE_QA=1` |

## 21. The deletion pull request

Opened only after `parity_report.py` prints `N/N`. One PR, title
"Remove the three.js Verse". It must leave `npm run build`, the frontend
tests, the Python tests and `scripts/agent_done_gate.py` green, and it must
be visible in the running app: the Verse tab and the IDE panel open the
Unreal Verse.

### 21.1 Removed

| Path | What it is |
|---|---|
| `dodaios/ui/web/frontend/src/components/society/verse/` (whole folder, 27.6k lines, 53 test files) | The three.js Verse: stage, engine, actors, life, nav, effects, hud, ranks, duel, combat, viewmodel, abilities, audio, content, testing |
| `dodaios/ui/web/frontend/src/components/society/crewFeeds/` | Verse-only feed hooks (desk chats, pane screens, team rounds, coding floor, navigate); no importer outside the Verse. `openPaneSession` moves first (21.2) |
| `dodaios/ui/web/frontend/public/verse/decks/`, `characters/`, `space/`, `loading.webp` | Cooked plates, AVIF tiles, `scene.glb`, lightmaps, nav PNGs, glTF characters, Earth WebP, loading art |
| `dodaios/ui/web/frontend/public/verse/audio/` | Removed once the same CC0 files are imported into `unreal/Verse/Content` with ledger rows (Z-16); `CREDITS.md` moves with them |
| `scripts/verse/cook.py`, `_cook_entry.py`, `package.py`, `package_realtime.py`, `_realtime_entry.py`, `eyeview.py`, `_eyeview_entry.py`, `closeup.py`, `_closeup_entry.py`, `avif_test.py`, `meshopt_pack.mjs`, `textures.py`, `validate.py` | Plate and realtime glTF cook for three.js. `blender.py`, `_bootstrap.py`, `mcp_bridge.py` and `earth.py` stay if `export_unreal.py` uses them (`contracts/art-pipeline.md` §2) |
| `art/verse/lib/cook.py`, `plate_post.py`, `realtime.py`, `navgrid.py`, `lightmap.py` | three.js-only cook stages (plate, glTF export, nav PNG, lightmap bake). Builders, kit, characters, schema, `LICENSES.md`, style bible stay |
| `art/verse/decks/*/` plate and nav outputs | Only generated plate/nav files; deck builders stay |
| `docs/verse/realtime.md`, `docs/verse/pipeline.md`, `docs/verse/combat.md`, `docs/verse/sovereign.md` | Docs of the removed runtime. Their doctrines already live in `contracts/` (combat, bot); `docs/verse/README.md` is rewritten to point at `docs/verse/unreal/` |

Kept on purpose: `src/i18n/locales/ship/*.json` (the backend serves them to Unreal, N-03), `art/verse/` builders, kit, characters, schema, `LICENSES.md` and style bible, `src/components/society/progression/` and `arcade/`.

### 21.2 Frontend references to rewire

| File | Today | After |
|---|---|---|
| `src/views/DodaiosAgentsView.tsx:8-9` | Renders `VerseStage`, `VerseLoadingScreen` | Renders the Verse launcher card (status from `GET /api/verse/status`, show/stop, unsupported, crashed) and calls `POST /api/verse/show` while the tab is active |
| `src/views/DodaiosAgentsView.test.tsx:8` | Mocks `VerseStage` | Mocks the launcher card |
| `src/views/society/SocietyView.tsx:36-37` | `VerseLoadingScreen`, `preloadLoadingArt` as lazy fallback | Plain fallback; no Verse art preload |
| `src/views/society/SocietyView*.test.tsx` | Tab `society.shell.mode_verse` | Unchanged label; assert the card instead of the stage |
| `src/components/agentic/sidePanel/OfficeTab.tsx:5,9,57` | Lazy `VerseStage compact initialDeck="engineering"` | Pixel Streaming view component (`panel.visibility`, `panel.resize`, signalling on `WS /api/verse/signal`) with the no-GPU card fallback |
| `src/components/agentic/sidePanel/IdeSidePanel.test.tsx:19,275` | Mocks `VerseStage` | Mocks the stream view; keeps "Dodaios Verse tab shows engineering" |
| `src/components/agentic/threads/IdeLayoutSwitch.tsx:12-68` | "verse" maximizes the side panel | Same switch; maximized panel hosts the stream, or (decision of the bridge package) sends `show` for the full window |
| `src/components/society/progression/cosmetics.ts:13`, `progressionApi.ts:12`, `progressionStore.ts:16`, `useProgressionSync.ts:16-17`, `verseDecks.test.ts:11` | Import `../verse/ranks/ranks` (`RANK_TIERS`, `isPromotion`) and `../verse/decks` (`DECK_IDS`) | Move `ranks/ranks.ts` (pure, no three.js) to `src/components/society/progression/ranks.ts` and `decks.ts` to `progression/decks.ts` before the deletion; re-point the imports. `useProgressionSync` (world actions, bell) loses its Verse-only half: `daily_visit` and `deck_discovered` are reported by Unreal (W-01, W-02) |
| `src/components/society/progression/useProgressionSync.ts:90-91` | Reports `daily_visit`, `deck_discovered` | Removed (Unreal reports them); the award listener stays for the app's own level UI |
| `src/components/society/progression/levelSounds.ts`, `progressionStore.ts:158` | localStorage settings | Read once for the import (section 20), then from config |
| `src/components/society/crewFeeds/codingNavigate.ts` `openPaneSession` | Used by the Verse's crew card | Moves to `src/components/agentic/openPaneSession.ts`; the `VerseOpenRequested` bus handler calls it |
| `src/components/society/arcade/*` | Opened only by `hud/SimulatorPanel.tsx` | Opened by the `simulator.open` handler (section 20); keeps its own round reports |
| `src/lib/liveTerminals.ts` presenter API (`presentTerminal`, `registerTerminalPresenter`) and `src/components/agentic/presentedRenderer.ts` | Let the Verse takeover borrow an xterm | Removed with their tests if no other presenter registers (grep `registerTerminalPresenter`); `registerLiveTerminal` stays if the IDE uses it |
| `src/components/agentic/AgenticTerminal.tsx:1211,1398,1584,1827,2019,2127,2512` and `AgenticTerminal.offscreen.test.tsx:204` | "Verse window" reader paths (borrowed xterm, parked bytes, fit observer) | Removed with the presenter; tests for these paths removed |
| `src/components/agentic/ideHotkeys.ts:448` | "type without focusing the pane (the Verse types into a hidden pane)" | Option removed if the takeover was its only caller |
| `src/views/AgenticIdeView.tsx:96` | Comment on the maximized Verse panel | Comment updated |
| `src/i18n/index.ts:215` | Registers chunk `ship` for the stage | Chunk no longer loaded by the web app; the files stay for the backend (N-03); keys used by nothing on the web are exempt from the web key-usage check |
| `src/hooks/useCanvasAwake.ts`, `useWebglSurface.ts`, `src/lib/graphDimension.ts` | Shared with other 3D views | Stay (other importers: mars, world, wiki graph) |
| `package.json` | `three`, `@react-three/fiber`, `@react-three/drei` | Stay (used elsewhere); `three-mesh-bvh` is reached through drei and needs no change |

### 21.3 Backend, tests, CI and packaging to rewire

| File | Today | After |
|---|---|---|
| `dodaios/progression/rules.py:49-51,183-184` | Comments point at `verse/decks.ts` and `verse/ranks/ranks.ts` | Point at the Unreal DataAssets' text sources (`unreal/Verse/Config/` or the exported JSON the `ST` checks read) |
| `tests/unit/progression/test_frontend_parity.py:4,74-96` | Reads `verse/ranks/ranks.ts`, `verse/decks.ts` and the `ship` chunk | Reads the moved `progression/ranks.ts` / `decks.ts` and the Unreal rank and deck data (R-01, B-01) |
| `dodaios/ui/web/frontend/src/components/society/progression/verseDecks.test.ts` | `DECK_IDS` vs `VERSE_DECKS` | Re-pointed to `progression/decks.ts` |
| `dodaios/ui/web/server.py:73-80` | MIME types `.avif`, `.glb`, `.hdr` for Verse plates and models | Removed if no other static file needs them (grep the dist for each suffix) |
| `dodaios/ui/web/frontend/public/THIRD_PARTY_NOTICES.txt:571-576` | Verse sound credits under `public/verse/audio` | Re-pointed to the Unreal content path, shipped with the Verse payload |
| `scripts/ci/repo-junk-allowlist.txt:11-12` | Allows `public/verse/decks/*/realtime/scene.glb` | Lines removed |
| `.gitignore:528-533` | Verse cook outputs and `public/verse/decks/testbed/` | Replaced by the `unreal/` ignores (architecture §8.1); `art/verse/.cache/` stays |
| `dodaios/core/events.py:2578-2596`, `dodaios/memory/write_feedback.py:12`, `dodaios/progression/__init__.py:1` | Docstrings mention the Verse animating awards | Text only; updated to "the Unreal Verse via the bridge" |
| `dodaios/ui/web/progression_routes.py:4,64,100` | Actions reported "from the Verse" | Unchanged code; the bridge relay calls the same service in-process |
| New: `dodaios/verse_host/`, `dodaios/ui/web/verse_routes.py`, `tests/unit/verse_host/` | n/a | Land before parity (architecture §1.1); listed here because the deletion PR must not touch them |
| Installer and updater (`dodaios/core/installer_update.py:106`) | 1.5 GB cap; no Verse payload | Cap raised and Verse delta packages wired (README "Delivery") before the deletion PR |

## 22. Row count

245 rows in sections 2-19 (A 13, B 8, L 7, F 19, C 24, S 18, X 11, W 8, E 15, H 14, R 14, V 26, K 11, Z 16, D 18, T 4, N 7, Q 12).
