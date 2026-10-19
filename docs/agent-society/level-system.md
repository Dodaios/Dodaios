# Dodaios Verse level system: the service record

Status: **rebuilt for the starship (2026-10-19).** Backend `dodaios/progression/`,
REST `/api/progression`, data layer `components/society/progression/`, ship UI
`components/society/starship/levels/`. The rulebook in
`dodaios/progression/rules.py` is the source of truth; this page is its
readable version.

## 1. Who levels up

| Subject | Id | Earns from |
|---|---|---|
| The captain (the person) | `person` | Talking to Jarvis, giving the crew work, growing the crew, small actions aboard |
| Every Jarvis agent | `agent:<agent_id>` | Finished work: results, quests, answers to teammates |
| The companion (the pet) | `pet:<pet_id>` | Jarvis's own work (the pet IS Jarvis aboard) and walks with the captain |

The lead (`jarvis`) never has an agent subject: it is drawn as the pet, so
its work pays the pet. Coding panes are not subjects.

## 2. XP rules

Every award comes from one rule: a fixed amount, optionally a cooldown, a
daily cap (local calendar day) or "once per reference". The server applies
every limit against its own ledger, so a replayed event or a client that
reports twice never pays twice. Nothing calls a model.

**Server rules** (read off bus events) are unchanged: `chat_turn` 5 and
`voice_turn` 5 (100/day each), `quest_posted` 15 (75/day), `quest_completed`
20, `agent_hired` 50 (once per agent), `mission_completed` 30 (150/day);
agents `task_done` 40, `task_blocked` 8 (40/day), `quest_done` 60,
`answered_teammate` 5 (50/day); the pet `jarvis_answered` 4 (120/day) and
`delegated` 10 (100/day).

**World rules** (reported by the ship through `POST /api/progression/actions`):

| Source | Pays | XP | Limit | Reported when |
|---|---|---|---|---|
| `daily_visit` | captain | 25 | once per day | the Verse opens |
| `deck_discovered` | captain | 20 | once per deck (`bridge`, `ops`, `engineering`, `holodeck`, `honors`) | the first visit of a deck |
| `holodeck_round` | captain | 8 | every 45 s, 80/day | a scored round on the holodeck |
| `holodeck_record` | captain | 15 | every 45 s, 60/day | a new best |
| `team_briefing` | captain | 10 | every 10 min, 40/day | a team gathered at its table |
| `warp_jump` | captain | 5 | every 10 min, 30/day | a jump to a known destination |
| `walk_together` | pet | 3 | every 20 s, 60/day | every 50 m walked with the companion |

The office's sources (`floor_discovered`, `dog_*`, `arcade_*`,
`team_meeting`) are retired; ledger rows that carry them still read.

## 3. Level curve

Unchanged, so earned XP keeps its meaning: level *L* → *L + 1* costs
`40 + 25·(L−1)^1.1` XP, rounded to 5; the cap is level 50. The server sends
the whole curve (`level_xp`).

## 4. Ranks and rewards

Everyone aboard climbs one naval ladder (`RANKS`; the frontend's copy with
the collar pips is `starship/levels/ranks.ts`, and a parity test pins them):

| Tier | Ranks (first level) | Insignia (original SVG, `Insignia.tsx`) |
|---|---|---|
| Enlisted | Cadet 1, Crewman 3, Specialist 5, Petty Officer 7, Chief Petty Officer 10 | silver chevrons (the chief over a rocker); the cadet an empty bar |
| Warrant | Warrant Officer 13 | one gold pip on a bar |
| Officers | Ensign 16, Lieutenant Junior Grade 19, Lieutenant 22, Lieutenant Commander 26, Commander 30, Captain 34 | gold pips, a hollow pip for the half grades |
| Flag | Commodore 38, Rear Admiral 42, Vice Admiral 46, Admiral 50 | a gold bar with one to four stars |

On a figure the rank is the collar: silver pips for enlisted ranks, gold for
officers, four gold for flag officers.

Rewards (`REWARDS`), each opening on a level:

| Slot | For | Pieces (level) |
|---|---|---|
| `suit` | captain | field armour 6, command coat 16, dress whites 26, admiral's coat 42 |
| `destination` | captain | gas giant 5, crimson nebula 10, ice moon 15, twin suns 20, event horizon 25, aurora world 30, galactic core 40 (equal to `space/destinations.ts`) |
| `decoration` | captain · agents | service ribbon 8 · 3, commendation 18 · 16, star medal 36 · 32, legion of merit 47 · 44 |

The suit the captain wears is the finest open one unless chosen at the
quartermaster or in the service record ("finest open", the duty suit, or an
open suit; kept per browser profile). The helm sets the destination. Agent
looks (`LOOK_UNLOCKS`) stay open from level 1.

## 5. Surfaces

- **Rank card** under the deck card: insignia, rank, level and the XP bar; a
  click opens the service record.
- **Name plates**: the rank after every android's name.
- **Service record** (`ServiceRecord.tsx`): Record (rank, level, XP still
  missing, next promotion, what opens next, the ship's log of recent awards),
  Ranks (the whole ladder by tier, held bright, the current framed, the ones
  ahead dim with the XP still missing), Rewards (suits and destinations with
  their levels), How to earn (every rule in plain words), Crew (every agent's
  rank, best first). The rank wall and the display cases in the Hall of
  Honour open it too.
- **Promotion ceremony** (`PromotionCeremony.tsx`): for the captain and the
  companion a centred card — the old insignia steps aside, the new one is laid
  on, the rank, the level and what it opened; a quiet toast for an android.
  Reduced motion keeps the information and drops the motion. Promotions while
  the Verse was closed are told once.

## 6. Contracts

- `GET /api/progression` returns the subjects, the pet, recent awards, the
  curve, the rules, the rewards, the looks and the ranks (`id`, `level`,
  `tier`).
- `POST /api/progression/actions` takes `{action, ref}`; `deck_discovered`
  and `warp_jump` refs are checked against the decks and the destinations.
- `ProgressionAwarded` (bus → WebSocket) carries `subject_id`, `subject_kind`,
  `xp_source`, `xp`, `total_xp`, `level`, `previous_level`, `title`,
  `unlocked`.
- The ledger is `<data_dir>/progression.db`, opened on the first award.
