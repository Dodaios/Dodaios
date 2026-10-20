# Dodaios Verse level system: ranks, rewards and duty status

Status: **rebuilt for the capital ship (2026-10-19).** Backend
`dodaios/progression/`, REST `/api/progression`, data layer
`components/society/progression/`, rank surfaces and duty status
`components/society/verse/ranks/`. The rulebook in
`dodaios/progression/rules.py` is the source of truth; this page is its
readable version. The XP curve and the XP rules of earlier builds are kept, so
earned XP keeps its meaning; ranks, rewards and world actions are new.

## 1. Who levels up

| Subject | Id | Earns from |
|---|---|---|
| The commanding officer (the person) | `person` | Talking to the assistant, giving the crew work, growing the crew, small actions aboard |
| Every agent, an officer of the crew | `agent:<agent_id>` | Finished work: results, quests, answers to teammates |
| The companion drone (the pet from My Pets) | `pet:<pet_id>` | The lead's own work (the lead is drawn as the companion) and walks with the commander |

The lead (`jarvis`) never has an agent subject: its work pays the companion.
Each pet keeps its own level; the active one earns. Coding panes are not
subjects.

## 2. XP rules

Every award comes from one rule: a fixed amount, optionally a cooldown, a
daily cap (local calendar day) or "once per reference". The server applies
every limit against its own ledger, so a replayed event or a client that
reports twice never pays twice. Nothing calls a model.

**Server rules** (read off bus events): `chat_turn` 5 and `voice_turn` 5
(100/day each), `quest_posted` 15 (75/day), `quest_completed` 20,
`agent_hired` 50 (once per agent), `mission_completed` 30 (150/day); officers
`task_done` 40, `task_blocked` 8 (40/day), `quest_done` 60,
`answered_teammate` 5 (50/day); the companion `jarvis_answered` 4 (120/day)
and `delegated` 10 (100/day).

**World rules** (reported by the Verse through `POST /api/progression/actions`):

| Source | Pays | XP | Limit | Reported when |
|---|---|---|---|---|
| `daily_visit` | commander | 25 | once per day (the server's day) | the Verse opens |
| `deck_discovered` | commander | 20 | once per deck | the first visit of `bridge`, `ops`, `engineering` or `hangar` |
| `simulator_round` | commander | 8 | every 45 s, 80/day | a scored round of a game in the simulator room |
| `simulator_record` | commander | 15 | every 45 s, 60/day | a new best in the simulator room |
| `team_briefing` | commander | 10 | every 10 min, 40/day | a team gathers in the briefing room (`ref` = team id, kept in the log) |
| `inspection` | commander | 15 | once per deck and day, 30/day | the commander has walked every room of a deck (`ref` = deck id) |
| `walk_together` | companion | 3 | every 20 s, 60/day | about 50 m walked with the drone at the commander's heel |

A whole day of everything aboard pays about one ordinary day of work: the
world is a garnish, the work is the meal.

The retro games still report `arcade_round` / `arcade_record`; the client
sends them as `simulator_round` / `simulator_record` (and the previous ship's
`holodeck_*` names too). Retired sources (`holodeck_round`,
`holodeck_record`, `warp_jump`, the office tower's `floor_discovered`,
`dog_*`, `arcade_*`, `team_meeting`) are listed in `RETIRED_SOURCES`: never
paid again, but ledger rows that carry them still read and still count, and
the service record shows them as "earlier service".

The decks a report may name are `VERSE_DECKS` in the rulebook; the client's
copy is `DECK_IDS` in `components/society/verse/decks.ts`, and parity tests
on both sides hold them together.

## 3. Level curve

Unchanged: level *L* → *L + 1* costs `40 + 25·(L−1)^1.1` XP, rounded to 5;
the cap is level 50 (43 230 XP in all). The server sends the whole curve
(`level_xp`); the client keeps its own copy (`LEVEL_XP` in `levelCatalog.ts`,
pinned to the rulebook's numbers by a test) for the moments it has no answer
yet.

## 4. Ranks

Everyone aboard climbs one ladder in four tiers. The commander, every officer
and the companion share it, so a rank means the same on every name plate.

| Tier | Ranks (first level) | Pip colour | Uniform |
|---|---|---|---|
| `deck` (enlisted ratings) | Recruit 1, Deckhand 3, Technician 5, Senior Technician 8 | steel | charcoal work uniform |
| `line` (officers) | Ensign 11, Lieutenant 14, Senior Lieutenant 17, Commander 21, Captain 25 | blue | olive-grey tunic with cap |
| `command` | Line Captain 29, Commodore 33 | red | black tunic with cap |
| `flag` | Rear Admiral 37, Vice Admiral 41, Admiral 45, Fleet Admiral 50 | gold | off-white tunic with cap |

Ids are snake_case (`senior_lieutenant`, `fleet_admiral`, …). The first
promotion comes on day one; each one after takes a little longer than the one
before; none is further than about six weeks of ordinary use.

**The rank plate** (drawn to `art/verse/style-bible.md` §7.2). A brushed-steel
plate, 54 × 22 mm with 45° chamfered ends, worn on the left chest and held by
a pin head at each end, with six elongated-hexagon sockets (12 × 7 mm) in two
rows of three. Slot index, seen facing the wearer: top row 0 1 2, bottom row
3 4 5 (the character's material slots `M_RankTile_1..6`). A lit slot holds a
satin enamel pip in the tier colour (steel #A9ADB2, blue #4D86D9, red
#E3242B, gold #C8A24A), one colour per plate and never emissive; an empty
socket is dark (#2A2D31). Each rank lights its own left-right-symmetric
pattern, so no two ranks share a plate even without the colour: deck ratings
build from the bottom row, line officers from the top, the command ranks and
the flag officers take the remaining shapes, and the fleet admiral wears all
six.

| Rank | Top · bottom | Rank | Top · bottom |
|---|---|---|---|
| Recruit | `000 · 010` | Captain | `111 · 101` |
| Deckhand | `000 · 101` | Line Captain | `010 · 010` |
| Technician | `000 · 111` | Commodore | `101 · 010` |
| Senior Technician | `010 · 111` | Rear Admiral | `010 · 101` |
| Ensign | `010 · 000` | Vice Admiral | `101 · 101` |
| Lieutenant | `101 · 000` | Admiral | `101 · 111` |
| Senior Lieutenant | `111 · 000` | Fleet Admiral | `111 · 111` |
| Commander | `111 · 010` | | |

`plateTiles(rankId)` (or `rankBadge(level)`) in `verse/ranks/ranks.ts` gives
the six slots and the colour; the SVG (`RankPlate.tsx`) and the character's
chest plate both read it.

**Ranks are derived from levels on the client.** The Verse never shows the
server's `title`: it computes the rank from the level with its own ladder
(`rankForLevel`). A backend older than the frontend (the desktop app keeps its
Python until it restarts) names other ranks, but its levels mean the same.

## 5. Rewards

| Slot | For | Pieces (level) |
|---|---|---|
| `uniform` | commander | `uniform_deck` 1 (issued on day one), `uniform_line` 11, `uniform_command` 29, `uniform_flag` 37: each tier's uniform the day its first rank is reached |
| `ribbon` | commander · officers | `ribbon_good_conduct` 6 · 4, `ribbon_meritorious` 19 · 16, `ribbon_distinguished` 31 · 27, `ribbon_fleet_cross` 47 · 43 |

The commander wears the uniform of the highest tier issued unless another
issued one is chosen at the quartermaster (kept per browser profile).
Officers wear their own tier's uniform automatically and earn ribbons; the
companion drone wears its rank only. A ribbon bar is 30 × 8 mm, a flat
two-tone stripe from the ship's palette (never gold), worn in one row above
the plate. Agent looks for the agent card
(`LOOK_UNLOCKS`) stay open from level 1.

## 6. Duty status

What a crew member is doing, read from its real run state
(`verse/ranks/dutyStatus.ts`):

| Status | Where the figure is | Beacon |
|---|---|---|
| `working` | seated at its console, typing, screen live | steady green |
| `waiting` | stands, turns to the commander | amber, slow pulse |
| `idle` | off duty: mess hall, corridor, viewports | none |
| `paused` | in its bunk | none |
| `error` | at its console, not typing | red, slow pulse |

Inputs: the roster's run state (`working`, `idle`, `paused`; sample rows may
say `waiting`), the live bus (`SocietyResultPosted` with `blocked` marks an
error until a `done` result or a new run; a `SocietyMessageSent` QUERY from an
agent to the person marks it waiting until the person writes back), and for a
coding pane the IDE's own dot (`working` / `waiting` / `idle` / `error`,
`stopped` = paused). Precedence: paused > waiting > working > error > idle.
`useDutyBoard(members)` returns every member's status live.

## 7. Surfaces

- **Rank card** (`RankCard`, in the HUD): the plate, the rank, the level and
  tier, the bar to the next level and the XP still missing for the next rank;
  a click opens the service record.
- **Service record** (`ServiceRecord`, an accessible dialog): Record (plate,
  rank, level, total XP, this level, next rank, ribbons, the log of recent
  awards, the bell switch), Ladder (every rank by tier, held, current, ahead
  with the XP missing), Quartermaster (uniform choice, ribbons with their
  levels), How to earn (the rules the running server pays, with limits),
  Crew (every officer's rank, highest first, and the companion drone). The
  stage opens it from the records hall, the rank board and the quartermaster
  (`openRecord("rewards")`).
- **Promotion notice** (`PromotionNotice`): a new rank for the commander or
  the companion gets a notice under the top edge: the new plate with its tiles
  laid on one by one, the rank, the level, one line of salute and what the
  quartermaster issued; it goes on Acknowledge, Escape or after seven seconds
  and never takes the focus. Any other level-up, and every officer's, is a
  quiet line in the corner. Reduced motion keeps every word and drops the
  movement. Promotions while the Verse was closed are told once. The ship's
  bell strikes two pairs for a new rank of the commander or the drone and one
  quiet pair for any other level-up; the service record switches it off.
- `RanksOverlay` mounts the record and the notice together.

## 8. Contracts

- `GET /api/progression` returns the subjects, the pet, recent awards, the
  curve, the rules, the rewards (`reward_id`, `slot`, `levels`), the looks,
  the ranks (`id`, `level`, `tier`) and the decks.
- `POST /api/progression/actions` takes `{action, ref}`; `deck_discovered`
  and `inspection` refs must be a deck; `daily_visit` uses the server's day.
  An unknown action or ref answers 422.
- `ProgressionAwarded` (bus → WebSocket) carries `subject_id`,
  `subject_kind`, `xp_source`, `xp`, `total_xp`, `level`, `previous_level`,
  `title`, `unlocked`, `unlocked_looks`.
- The ledger is `<data_dir>/progression.db`, opened on the first award; its
  schema is unchanged, so earlier rows read as they are.
- Tests: `tests/unit/progression/` (rulebook, service, routes, parity with
  the frontend) and the vitest suites under `components/society/progression/`
  and `components/society/verse/ranks/`.
