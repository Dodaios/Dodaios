# Verse combat: the reactor duel

Status: **combat core built, tested and through an adversarial pass,
2026-10-20; playable in the 3D view since 2026-10-26** (see "In the 3D view"). The Verse stays a workspace first. Combat is optional: the person
starts a 1v1 blaster duel at any time from the control ring in the middle of
the **Reactor Shaft** hall on the engineering deck, against a bot today and
against another person later. Leaving is always one key away.

Code: `dodaios/ui/web/frontend/src/components/society/verse/combat/`
(TypeScript, no React, no three.js). This document covers the architecture,
the arena, the rules and their tuned numbers, the bot, the balance results
and what the integrator has to do.

| File | What it is |
|---|---|
| `sim.ts` | The deterministic fixed-tick simulation: `createMatch`, `step(state, inputs, ctx)`. |
| `types.ts`, `input.ts`, `tuning.ts` | InputCommand, MatchState, CombatEvent; control state to input; every balance number. |
| `arena.ts`, `arenaReactor.ts` | Arena description and runtime (movement grid, raycasts, cover); the Reactor Shaft arena. |
| `raycast.ts`, `rng.ts`, `math.ts` | Segment sweeps; seeded randomness; small math. |
| `observe.ts` | What a player can know (line of sight, view cone, sounds). The bot reads only this. |
| `protocol.ts`, `transport.ts` | Versioned wire messages; Channel, in-process LocalNetwork, WebSocket adapter. |
| `server.ts`, `client.ts` | Authoritative MatchServer; MatchClient with prediction, reconciliation, interpolation. |
| `view.ts`, `camera.ts` | Per-frame ViewState and HUD; shoulder-camera rigs and crosshair convergence. |
| `session.ts`, `index.ts` | `createLocalDuel()`: the one object the 3D view needs; the public surface. |
| `bot/` | `BotBrain` (tactics and reflexes), `AimController`, route finding, difficulty tiers. |
| `harness/` | Headless duels, person models and scripted exploit strategies, balance runs (`cli.ts` for big runs, in parallel). |
| `*.test.ts` | Unit, netcode and adversarial tests (`exploits.test.ts`, `netcodeAdversarial.test.ts`, `harness/exploits.test.ts`). |

## Architecture

Multiplayer from day one: even the duel against the bot runs as a server
with two clients. The bot is just another client.

```
                 +-------------------------------------------+
                 |  MatchServer (authoritative)              |
                 |  MatchState --step(state, inputs)--> ...  |
                 |  60 Hz fixed tick, input queue per player |
                 +-----------+-------------------+-----------+
          snapshots, events  |                   |  snapshots, events
          (full state, ack)  |                   |
                 +-----------v-----+       +-----v-----------+
   Transport --> | Channel         |       | Channel         | <-- Transport
  (LocalNetwork  +-----------+-----+       +-----+-----------+   (LocalNetwork
   now, WebSocket            |  InputCommands    |                today)
   for PvP)      +-----------v-----+       +-----v-----------+
                 | MatchClient     |       | MatchClient     |
                 |  prediction     |       |  prediction     |
                 |  reconciliation |       |  reconciliation |
                 |  interpolation  |       |  interpolation  |
                 +-----------+-----+       +-----+-----------+
                             |                   |
                    keys + mouse            observe(view) -> BotBrain
                    ViewState, events       (same information a person has)
```

### The simulation

`step(state, inputs, ctx) -> { state, events }` is pure and deterministic:

- **Fixed tick**, 60 Hz. Every duration is in ticks.
- **No clock, no `Math.random`.** Random draws are *counter-based*: the spread
  of shot N of player P is `hash(matchSeed, P, N, salt)`, a deflection angle
  is `hash(matchSeed, boltId, tick, salt)`. A client predicting its own shot
  gets exactly the server's spread without sharing an RNG stream. Bots and the
  harness use their own seeded generators (`Rng`).
- **Plain JSON state** (`MatchState`): players, bolts, scores, phase, a short
  pose history for lag compensation. No classes, no maps.
- **Quantised every step**: positions to 1 mm, aim to 1e-4 rad, health/heat/
  energy to 1e-3. The wire format uses the same grid, so a snapshot carries
  the server's state *exactly* and a client's replay matches it bit for bit.
- **Inputs, not actions**: `inputs[slot]` is an InputCommand or `null` (the
  player's last input repeats: held buttons stay held, presses do not repeat).
- **Nothing from a client is trusted**: every command goes through
  `sanitizeInput` inside the step. A legal command (anything `makeInput`
  builds) passes unchanged, so prediction still matches; anything else is made
  legal: the move stick is clamped to length 1 (a diagonal is never faster),
  non-numbers become 0 or the previous aim, pitch is clamped, unknown button
  bits are dropped.
- Order inside a tick: aim and presses, then dodge/shield/vent/sights/sprint,
  movement, every player's trigger, then the lag-compensation rewind of the
  new bolts (so a rewound bolt can never stop the other player's shot of the
  same tick), bolts, regeneration and timers, round rules.

An `InputCommand` is everything a player ever sends:

| Field | Meaning |
|---|---|
| `seq` | Per-player sequence number, +1 per tick (acknowledged back for reconciliation). |
| `mx`, `my` | Strafe right / forward, -1..1, in the aim frame (WASD). Sent as 1/127. |
| `yaw`, `pitch` | Absolute aim, radians (yaw 0 faces +Z like the deck sockets). Sent as 1e-4. |
| `buttons` | FIRE, ADS, SHIELD, SPRINT (held), DODGE, VENT, FORFEIT (pressed). |
| `viewTick` | The server tick the client was displaying (its interpolation time), for lag compensation; -1 = none. |

### Server, clients, transport

- **MatchServer** accepts Channels; a duel starts when two players said hello
  with the same protocol version and the same **rules hash** (`rulesHash`:
  the tuning and the arena, so a client built for a re-laid-out room is
  rejected instead of mispredicting every wall). It runs the fixed step on its
  own clock (`update(nowMs)`), applies one queued input per player per tick
  (a late player's last input repeats; a queue longer than 6 is trimmed so a
  player who fell behind catches up, and the presses of the dropped inputs
  carry over into the next one, so a roll or vent is never lost), and every
  `snapshotEvery` ticks sends each player the full state, the last input it
  applied for them (`ackSeq`) and every event since the snapshot that client
  last confirmed (each input message names it; at least two snapshot periods,
  at most 1.5 s), so lost snapshots lose no effect. Malformed messages are
  ignored. A leave or a closed channel ends the match for the other player;
  the end message is reliable and carries the final snapshot, so the last
  kill, round end and match end always arrive.
- **MatchClient** turns the control state into one InputCommand per tick,
  sends it together with the previous two (loss), and steps its own copy of
  the match with it at once (**prediction**). On a snapshot it takes the
  server's state, drops the acknowledged inputs and replays the rest
  (**reconciliation**). The opponent is drawn from the snapshots, a little in
  the past (**snapshot interpolation**), never from guesses. Own actions
  (shots, rolls, shield, vents) play from the prediction at once; everything
  else from the server; each event plays once (`eventKey`). It also counts how
  often its prediction was wrong (`prediction`), for a debug overlay.
- **Lag compensation hook**: the server keeps 32 ticks of poses. A shot's
  `viewTick` says what the shooter saw; the server flies the new bolt through
  the ticks between that and now against the poses of those ticks (projectile
  fast-forward, at most 15 ticks = 250 ms), then on as usual. On in the local
  duel (it makes the person's shots land on the opponent they see), and the
  switch for PvP.
- **Transport**: server and clients only see a `Channel`. `LocalNetwork` links
  them in-process on a virtual clock and, for tests or practice, adds seeded
  latency, jitter and loss (reliable messages are never dropped and stay in
  order among themselves). Messages pass through JSON like on a real wire.
  `socketChannel(ws)` adapts a browser or Node WebSocket for the PvP server.

### Wire protocol, version 2

JSON arrays with a one-letter tag; numbers in states and inputs are integers
on the quantisation grid. Version 2 (the adversarial pass): the hello carries
the rules hash, snapshots carry the events since the client's last confirmed
snapshot, and the end message carries the final snapshot.

| Direction | Message | Reliable |
|---|---|---|
| C to S | `["h", version, playerId, name, rulesHash]` hello | yes |
| C to S | `["i", lastSnapshotTick, [[seq, mx*127, my*127, yaw*1e4, pitch*1e4, buttons, viewTick], ...]]` newest inputs, repeated; `lastSnapshotTick` confirms what the client has | no |
| C to S | `["l"]` leave (forfeit) | yes |
| C to S | `["p", clientMs]` ping | no |
| S to C | `["w", version, slot, matchId, seed, rulesHash, arenaId, snapshotEvery, config, playerIds]` welcome | yes |
| S to C | `["s", tick, ackSeq, state, events]` snapshot (full state, about 0.5 kB) and the events since the client's confirmed snapshot | no |
| S to C | `["e", winner, reason, scores, tick, ackSeq, state, events]` match over, with the final snapshot | yes |
| S to C | `["o", clientMs, serverTick]` pong | no |
| S to C | `["r", reason]` rejected (version, tuning or arena, bad id, full, duplicate) | yes |

Measured at 30 Hz snapshots over a 50 ms link: about 18 kB/s down (snapshots
of about 0.5 kB) and 6 kB/s up (inputs of about 95 B, sent 60 times a second
with the two before) per player, uncompressed. A binary encoding of the same
arrays is a drop-in later.

### Why this is ready for PvP

To play another person: run `MatchServer` in Node behind a WebSocket server,
give each person a `MatchClient` over `socketChannel`, set `snapshotEvery: 2`
and `lagCompensation: true`. Nothing in the simulation, the client, the view
or the protocol changes. Open items for real PvP are listed at the end.

## The arena: Reactor Shaft

The duel happens in the reactor hall of the engineering deck (manifest room
`reactor`), in the deck's own frame: x to the right, z toward the camera, y
up, metres. The arena overlays the deck one to one.

```
            far wall (z 2): heat stacks O, machinery bays [##]
   x 33 +--------------------------------------------------+ x 82
        |  O     O    [##][###][##]     O     O     O       |
        |                 .  N  .                           |
        |             .     |     .                [=]  ||  |  [=] coolant run (1 m high)
        |          .        |        .                      |  ||  power conduit (to ceiling)
   W  0 >- - - - - -( ( core ) )- - - - - - < 1    [=]  ||  |  E
        |          .        |        .                      |
        |             .     |     .                [=]  ||  |
        |                 .  S  .                           |
        +-------- door ---------- door ---------- door -----+ z 38.1
   0, 1: spawns (sides swap every round). The circle is the drop (r 13);
   the core stands on a control ring (r 5..6.5) reached by four catwalks.
```

| Element | Where (deck metres) | Movement | Bolts |
|---|---|---|---|
| Hall | x 33..82, z 2..38.1, ceiling 12 | inside | walls stop them; doorways let them out |
| Shaft (drop) | centre (54, 22), r 13 | blocked (no falling) | fly over it, fall in |
| Control ring | r 5..6.5 around the axis | walkable | floor |
| Catwalks N, E, S, W | 1.2 m wide, ring to rim | walkable | floor |
| Core containment | r 3.75, up to 1.9 m | blocked | stops them (cover); shots over 1.9 m pass |
| Heat stacks | x 35.4, 41.4, 66.6, 72.6, 78.6; z 3.35; r 1.35 | blocked | stop them |
| Machinery bays | x 45.6..50.8, 52.6..55.6, 57.2..62.4 on the far wall | blocked | stop them |
| Power conduits | x 78.0..79.4, z 12/22/32 +-1.15, to the ceiling | blocked | stop them (hard cover) |
| Coolant runs | x 70.8..75.6, z 12/22/32 +-0.7, 1.0 m high | blocked | stop low bolts only |
| Spawns | side 0 (38.8, 22) facing +X; side 1 (69.2, 22) facing -X | | out of each other's sight (the core) |
| Duel terminals | ring consoles `reactor_ring__ring_1..4` (58.24, 17.76), (49.76, 17.76), (49.76, 26.24), (58.24, 26.24) | | |

Derived from the deck sources (`art/verse/decks/engineering/eng_common.py`,
`eng_reactor.py`, `eng_dressing.py`, `art/verse/kit/props/industrial/reactor.py`).
`arena.test.ts` checks it against the cooked deck: the room outline and the
ring consoles match the manifest, and away from the rim band the walkable
area agrees with `nav.png` to more than 95% both ways. One deliberate
difference: the cooked nav grid marks most of the 2.4 m rim band around the
drop as blocked (plate seams and bolt strips); the arena treats it as floor up
to the kerb, as it reads on screen, so the narrow south passage between the
drop and the gallery wall stays open. The arena's movement grid is 0.1 m,
eroded by the body radius (0.3 m).

Spawns are mirrored about the shaft axis and the players swap sides every
round (the first round's sides come from the seed), so the room's east/west
differences even out: over 20,051 balance rounds side 0 won 50.6% (see below).

## Rules and tuned numbers

A match is best of three rounds (first to 2, at most 5 rounds with draws).
Each round: a 3 s countdown (aim only), then live play until a player dies or
90 s pass (then the higher health wins the round), then a 2.5 s pause. Forfeit
works at any moment. 40 s into a round the **reactor surges**: health stops
regenerating and both players' positions are pinged on the HUD every 1.5 s,
so no round can stall in a hide-and-seek between people.

### Blaster

| | Value |
|---|---|
| Rate of fire | 5 bolts/s (12 ticks), full-auto while held |
| Bolt | travels at 60 m/s (visible, dodgeable at range), 6 cm radius, 90 m range |
| Damage | 15 up to 12 m, falling to 9 at 32 m; headshots (>= 1.5 m high) x1.5 |
| Time to kill, all hits | 7 bolts = 1.2 s close, about 2.2 s at 30 m; 0.8 s with headshots |
| Heat | +9 per shot; cools 35/s after 0.3 s without firing |
| Overheat | at 100 (the 12th bolt in a row): locked 2.5 s; a vent press 0.9..1.25 s into the lock ends it at once |
| Manual vent | press when heat >= 5: 0.5 s + 0.01 s per heat point; a second press in the window (30..52% of the vent) finishes it at once; one try per vent |
| Spread (cone half-angle) | hip 1.6 deg, sights 0.3 deg; +1.0 / +0.3 deg at full run speed |
| Bloom | +0.45 deg per shot hip (max 3.5), +0.2 in sights (max 1.5); recovers 5 deg/s after 0.1 s |
| Recoil | kicks the aim up 0.55 deg (hip) / 0.35 deg (sights) and +-0.2 deg sideways per shot; settles 9 deg/s by itself |
| Sights | 0.18 s in, 0.12 s out; 60% move speed |
| Not while | shield up, rolling (and 0.2 s after), venting, sprinting (and 0.15 s after) |

### Energy shield

| | Value |
|---|---|
| Energy | 100; raising needs 20 and costs 6; drains 8/s while up |
| Coverage | a front arc of +-60 deg around the aim, 0.8 m out, 2 m high |
| Normal block | absorbs the bolt for 0.9 energy per point of its damage; 40% of blocked bolts glance off at a seeded angle (+-40 deg about the mirror direction) with half damage, as the blocker's bolt |
| Perfect parry | a bolt meeting the shield within 0.15 s (9 ticks) of raising it goes straight back at whoever sent it (+-1.2 deg), 1.2x faster, full damage, no energy cost; up to 3 reflections per bolt (rallies) |
| Whiff penalty | a raise whose parry window met no bolt turns the parry window off for raises in the next 1.0 s; timed parries stay strong, flicking earns nothing |
| Re-raise lockout | 0.4 s after lowering |
| Break | at 0 energy: down for 3 s, then regenerates from 0; the key must be pressed again |
| Regeneration | 20/s after 0.9 s lowered |
| While up | 50% move speed, no firing, no sights, no sprint |

### Movement and health

| | Value |
|---|---|
| Run | 4.8 m/s (78% straight back), acceleration 34 m/s2, braking 42 m/s2 |
| Sprint | 7.0 m/s, input within 50 deg of forward, ends on fire/sights/shield |
| Dodge roll | 4 m in 0.4 s in the move direction (back if none), 2.0 s cooldown, **no invulnerability frames**, blaster back 0.2 s after |
| Health | 100; regenerates 10/s after 5 s without damage (not during the surge) |
| Bodies | 0.3 m radius on the grid; bolt hit capsule 0.34 m (+0.06 bolt) from 0.34 to 1.46 m; heads from 1.5 m |

## The bot

`BotBrain` is a client like any other: each tick it gets an `Observation`
and returns a `ControlState`, which becomes an InputCommand through the same
`makeInput` as a person's keys.

**Fair perception (`observe.ts`).** It sees what the person's screen would
show: the opponent inside the hip camera's view (+-44 deg from the camera
behind the right shoulder: 50 deg vertical at 16:9 shows +-40 deg, so close
by it sees far to the sides, as the screen does) or within 3 m, with a clear
line to the opponent's head, chest or hips from its eyes or from the camera
(the shoulder view looks round a right-hand corner before the body leaves
cover, for people and bots alike; the camera is pulled in at walls). It sees
bolts the same way, hears shots (where from), running footsteps within 9 m
(16 m sprinting) and the surge pings, and knows which way a hit came from.
Health bars are on both HUDs, so it knows health. A test runs whole duels and
checks that every shot it fires follows a real sighting.

**Human-like timing.** A new sighting is acted on after a sampled reaction
time; while tracking, it acts on what it saw 95..150 ms ago (extrapolated);
incoming bolts are answered after their own reaction delay. It decides a few
times a second, not every frame.

**Aim (`bot/aim.ts`).** It leads with its read of the target's motion: the
velocity it sees, or, once the target has turned its running round twice
within 0.7 s (A-D strafing), the average over the last 200..300 ms, so a
wobbling target is aimed at the middle of its wobble instead of chased, as a
practised player does. A speed-limited, stiffness-settled mouse with a
wandering error (Ornstein-Uhlenbeck) and a larger error right after acquiring
a target that fades; partial lead on a moving target with noise in its speed
read; partial recoil compensation; it aims where a roll will end and holds
fire into rolls; fires only when the aim is within a tier-set multiple of the
target's width.

**Tactics (utility, with hysteresis).** Fight in the open (strafe with
changing rhythm, hold a range, close in without a line of sight; a far
opponent is approached only with a reason, when it vents or its shield is
broken, when the bot leads by 25 health or beyond 34 m, otherwise the bot
trades from where it is and drifts in slowly, because walking straight at a
shooter makes the easiest target there is), take cover
and peek (cover spots are precomputed next to every tall solid: core, stacks,
machinery, conduits; it picks one hidden from the opponent with a peek point
that has a line), retreat to regenerate when losing, push an overheated,
venting, shield-broken or weak opponent, flank (to the opponent's side or
back), hunt (last sighting, sounds, then an approach lane chosen per round
through the middle or round either side, then search on).

**Reflexes.** Per seen incoming bolt: a timed parry (raise half a window
before impact, with a timing error), a dodge roll sideways toward open floor,
or a block. A steady stream is read by its rhythm and the next bolt parried.
Under pressure and losing the trade it blocks for a moment, then answers.
Vents are timed with an error (larger under fire). A freshly raised shield is
baited (it holds fire to not feed a parry) and its drop punished during the
0.4 s re-raise lockout.

**Tiers.** All parameters live in `bot/tiers.ts`; `createLocalDuel({ difficulty, bot })` takes a tier and optional overrides.

| | normal | hard | elite |
|---|---|---|---|
| Reaction (mean, sd) | 305 +- 60 ms | 255 +- 50 ms | 215 +- 40 ms |
| Tracking latency | 150 ms | 120 ms | 95 ms |
| Aim error (wandering) | 1.6 deg | 1.15 deg | 0.92 deg |
| Mouse speed | 380 deg/s | 520 deg/s | 720 deg/s |
| Lead / recoil control | 60% / 35% | 80% / 70% | 90% / 85% |
| Reads A-D strafing (motion window) | never | 200 ms | 300 ms |
| Heat cap | never stops (overheats) | 86 | 80 |
| Vent timing error | 160 ms | 85 ms | 50 ms |
| Parry tries / timing error | 25% / 110 ms | 45% / 65 ms | 65% / 42 ms |
| Block / dodge use | 42% / 12% | 60% / 25% | 75% / 35% |
| Cover / flank / aggression | 0.4 / 0.2 / 0.5 | 0.65 / 0.45 / 0.6 | 0.85 / 0.7 / 0.7 |
| Bait and punish | never | 55% | 90% |
| Head aim | never | 15% | 25% |
| Decides every | 320 ms | 220 ms | 160 ms |

## Balance

The harness (`harness/`) runs headless duels: two controllers observe the
authoritative state through `observe` and step the simulation directly (the
same duels over the full client/server stack play out the same; see
"Netcode under attack" below). It has three kinds of players:

- **The bot tiers.**
- **Two person models** (`harness/strategies.ts`), to estimate how people
  fare. *Skilled*: reactions 225 +- 18 ms (nearly all within 200..250 ms), a
  110 ms tracking delay, aim error 1.0 deg (elite 0.92), fast flicks
  (900 deg/s), heads 30% of the time, vents and parries timed by eye
  (sd 60 / 55 ms), reads A-D strafing. *Average*: 270 +- 40 ms, looser aim
  (1.45 deg), overheats now and then, parries rarely. They play by the same
  rules and perception as the bots. They are estimates, not measurements;
  a playtest calibrates them.
- **One-trick strategies**: a base player (the hard bot unless named,
  `skilled+trick` for a skilled person) with one behaviour forced, so a
  result shows what the trick itself is worth.

| Strategy | Behaviour |
|---|---|
| spam | holds the trigger whenever it sees the opponent, never vents, never shields |
| turtle | shield up all the time, never fires |
| blocker | raises the shield at every bolt it sees (no planned parries), fires otherwise |
| camper | sits in cover near its spawn and waits |
| dodger | rolls whenever the roll is ready |
| flicker | flicks the shield for parries as fast as the lockout allows |
| rusher | runs straight at the opponent |
| circle | closes in and orbits the opponent at about 2 m, firing (point-blank circle strafing) |
| jiggle | reverses its strafe every 140..300 ms (A-D spam) |
| hider | once ahead on health, breaks off and hides (plays for the clock and the health tiebreak) |
| edge | fires 11 bolts (heat 99, one short of an overheat), then vents at once with a timed press |
| parrier | tries to parry every bolt it sees; never holds a block, never rolls |
| watcher | holds the cover spot nearest its spawn that sees the other spawn, pre-aimed in sights |
| kiter | keeps 28 m away (across the shaft) and fights in sights |
| brawler | fights at 6 m |

### Results (300 duels per pairing, best of 3, seed 2026)

56 pairings: 16,800 duels, 40,623 rounds, 9 of them timed out. "A won" is the
first-named side; slots alternate every duel. TTK is from the first hit on a
full-health player to the kill (misses, blocks and regeneration included).
Accuracy, parry rate (share of the bolts reaching a player that it parried)
and perfect vents are A / B. With 300 duels a win rate is good to about
+-3 points (one standard error); repeat runs with other seeds moved single
pairings by up to 7 points.

**Skill ladder**

| Pairing | A won duels | A won rounds | Round | TTK | Accuracy | Parry rate | Perfect vents |
|---|---|---|---|---|---|---|---|
| hard vs normal | 80% | 73% | 11.3 s | 5.8 s | 33 / 26% | 18 / 14% | 80 / 51% |
| elite vs hard | 86% | 76% | 10.4 s | 5.0 s | 39 / 30% | 26 / 18% | 92 / 76% |
| elite vs normal | 98% | 89% | 10.1 s | 4.7 s | 42 / 26% | 26 / 13% | 93 / 50% |
| normal vs normal | 50% | 50% | 13.0 s | 6.8 s | 26 / 26% | 11 / 11% | 50 / 55% |
| hard vs hard | 46% | 48% | 11.3 s | 5.5 s | 31 / 32% | 18 / 19% | 78 / 77% |
| elite vs elite | 48% | 49% | 10.8 s | 5.2 s | 34 / 35% | 25 / 26% | 93 / 93% |

(Over four seed sets the mirrors average 46..50% of duels and 48..50% of rounds.)

**People against the bots** (the person models; duels / rounds won by the person)

| | vs normal | vs hard | vs elite |
|---|---|---|---|
| skilled | 91 / 82% | 72 / 65% | 40 / 43% |
| average | 66 / 61% | 31 / 36% | 7 / 16% |

Skilled against elite on the final code: 40% (above) and 37..38% in two more
runs of 400 duels; about 42% of rounds. How it moves with the person
(400 duels each):

| Skilled person | vs elite (duels / rounds) | vs hard |
|---|---|---|
| reactions 200 ms | 44 / 46% | |
| reactions 225 ms | 37 / 40% | |
| reactions 250 ms | 31 / 37% | |
| aim error 0.85 deg / 1.2 deg | 42 / 45%, 34 / 38% | |
| 200 ms and 0.85 deg (a very good player) | 47 / 47% | 80 / 70% |
| 250 ms and 1.2 deg (a good player) | 24 / 33% | 62 / 59% |

So: **normal** is for learning (an average player wins two duels in three),
**hard** is a fair fight for a good player and a real challenge for an
average one, **elite** is hard for a skilled player but beatable: it wins
about 6 duels in 10.

**One-trick strategies against the hard bot** (the trick on the hard bot's aim
and movement; a trick that ties means it is worth as much as the bot's mixed
play, a trick that wins would be an exploit)

| Trick | Hard won duels | Hard won rounds | Round | TTK | Notes |
|---|---|---|---|---|---|
| spam | 92% | 84% | 8.8 s | 4.0 s | overheats 0.8 times a round |
| turtle | 100% | 100% | 8.0 s | 3.1 s | the shield breaks, then nothing is left |
| blocker | 41% | 45% | 10.1 s | 4.7 s | parries 29% by reacting in time (45..48% over three more seeds) |
| camper | 94% | 87% | 9.8 s | 5.7 s | |
| dodger | 55% | 55% | 12.5 s | 6.3 s | 4.4 rolls a round |
| flicker | 59% | 56% | 11.3 s | 5.7 s | the whiff lock holds its parries to 19% |
| rusher | 80% | 70% | 8.0 s | 3.1 s | |
| circle | 82% | 73% | 7.8 s | 3.0 s | point blank the hard bot hits 53% |
| jiggle | 65% | 60% | 9.9 s | 4.6 s | wobbling barely moves you; see below |
| hider | 61% | 58% | 13.8 s | 6.4 s | 6 rounds went to the clock |
| edge | 50% | 50% | 10.5 s | 5.1 s | 99% perfect vents; heat mastery is worth exactly the bot's own heat play |
| parrier | 57% | 55% | 10.0 s | 4.7 s | |
| watcher | 57% | 54% | 13.4 s | 7.5 s | side 0 won only 39% of these rounds: the east side's hold is behind a conduit |
| kiter | 59% | 54% | 13.6 s | 7.6 s | was 38% before the bots stopped walking at far shooters |
| brawler | 58% | 56% | 10.3 s | 4.6 s | |

**A skilled person playing one trick against the elite bot** (elite's win
rate; against plain skilled play the elite bot wins 60%. A trick that pushes
this below 60% would be a cheap way to beat the bot.)

| Trick | Elite won duels | Elite won rounds |
|---|---|---|
| spam | 98% | 91% |
| blocker | 62% | 59% |
| camper | 99% | 94% |
| dodger | 65% | 60% |
| flicker | 70% | 63% |
| rusher | 89% | 81% |
| circle | 92% | 81% |
| jiggle | 56% | 54% |
| hider | 74% | 66% |
| edge | 59% | 56% |
| parrier | 63% | 59% |
| watcher | 66% | 61% |
| kiter | 63% | 58% |
| brawler | 72% | 66% |

No trick helps a skilled player much: jiggle (A-D spam) is the best at
+4 points, edge +1, everything else costs. (The turtle is left out; it
cannot win a round.)

**Tricks against each other** (A won duels): spam vs blocker 10%, spam vs
flicker 25%, dodger vs spam 89%, rusher vs camper 67%, flicker vs rusher 83%,
dodger vs blocker 36%, dodger vs flicker 63%, blocker vs flicker 65%,
blocker vs rusher 73%, kiter vs brawler 48%, kiter vs dodger 57%, edge vs
blocker 56%, jiggle vs kiter 32%, normal vs spam 63%, normal vs turtle 100%.
They beat each other in circles (blocker beats dodger, flicker and rusher;
edge beats blocker; dodger beats spam and flicker; kiter beats jiggle), and
none beats the bots.

### The adversarial pass (2026-10-20)

A second agent tried to break the core and to beat the bots cheaply. What it
found and what changed:

**Bugs, all fixed and covered by tests**

| # | Found | Fix |
|---|---|---|
| 1 | Lag compensation favoured slot 0: a rewound bolt of slot 0 could kill slot 1 before slot 1's own shot of the same tick was fired. | Every trigger first, then the rewinds (`exploits.test.ts`). |
| 2 | A modified client could run at 12 m/s (a 10x move stick), send strings or NaN as aim, set unknown button bits; a malformed message could throw inside the server. | `sanitizeInput` inside the step (legal commands unchanged), shape checks in the server; `makeInput` never sends a diagonal longer than 1 (`netcodeAdversarial.test.ts`). |
| 3 | When the server trimmed a backed-up input queue, a roll, vent or forfeit in a dropped input was lost (the client had already played it). | Presses of dropped inputs carry over into the next one. |
| 4 | The end message (reliable) could overtake the final snapshot (unreliable) under jitter: the last kill, round end and match end were never shown, and the client's last state was stale. | The end message carries the final snapshot (protocol v2). |
| 5 | Events rode along for only two snapshot periods: at 10% loss about 1% of all events (hits, deaths, round ends) never reached a client. | Each snapshot carries the events since the client's last confirmed snapshot; 0 of 1,748 lost at 10% loss, 0 in a whole duel at 15% loss and 40 ms jitter. |
| 6 | The handshake compared only the tuning: a client built for a re-laid-out arena would mispredict every wall. | `rulesHash` covers tuning and arena. |
| 7 | The bot saw +-75 deg round its body; the hip camera shows +-51 deg at 16:9, but more to the sides up close and round a right-hand corner. | Bot perception from the camera point (see The bot). |
| 8 | A non-array frame crashed the in-process transport and the client. | Guards. |

**Exploits**

- **Keeping your distance won.** Holding 28 m beat the hard bot 62%, the
  elite bot's own clone at 28 m beat it 70%, and kiting lifted the skilled
  person from 35% to 48% against elite; any preferred range from 16 m up
  beat the default bot. The cause was the bots: they walked straight in on a
  far opponent (a body walking along the line of fire is the easiest target
  there is, and here the way in goes round the open shaft). Now they close in
  only with a reason (the opponent vents or its shield is broken, they lead
  by 25 health, or it is beyond 34 m) and otherwise trade from where they are
  and drift in. The new bot beats the old one 61%; kiting now loses
  (above). Fights moved a little longer: rounds about 11 s instead of 10,
  TTK about 5 s instead of 4.
- **A-D strafing beat a good leader.** The bots led with the velocity of
  the moment, which a wobbling target turns into a guess: skilled+jiggle won
  48% against elite (plain skilled 38%), elite+jiggle beat elite 56%. Against
  a poor leader it is the opposite (normal+jiggle beat normal 5%: a wobbling
  target barely moves). Hard and elite now read it (above); the edge fell to
  about 4 points, which is about what the technique should be worth.
- **Tried and harmless:** turtling, shield flicking and parry spam (the
  whiff lock and the re-raise lockout), roll chaining (no invulnerability),
  firing to the overheat edge with timed vents (ties the bot; skill, not an
  exploit), point-blank circle strafing (at 2 m bots hit 53..60%; the shield
  arc does not save the orbiter either), camping, spawn watching, playing for
  the clock (the surge pings both).
- **Spawns:** never in sight of each other, mirrored, swapped every round:
  side 0 won 49.4% of 40,623 rounds. A pre-aimed hold behind the east
  conduits is stronger than any hold on the west floor (side 0 won 34..39%
  of the watcher's rounds), but holding is not a winning plan, and sides swap
  each round.

### Netcode under attack

Whole bot duels through MatchServer, LocalNetwork and two MatchClients:

- With no loss, a client predicts its own movement exactly; the only
  corrections come from what it cannot know (the opponent's newest hits and
  deaths): about 6..7% of snapshots at 60 ms with 30 ms jitter. At 70 ms,
  40 ms jitter and 15% loss it stays under 30%, worst about 1 m (a death
  learnt a round trip late).
- Every event reaches both clients exactly once, and the final state is the
  server's, at 15% loss and 40 ms jitter (`netcodeAdversarial.test.ts`).
- The same seeds replay the same networked duel, event for event.
- 17.7 kB/s down and 5.9 kB/s up per player at 30 Hz snapshots over 50 ms.

### Findings and decisions

- **Higher skill wins more, and never always.** The ladder is ordered
  (hard over normal 80%, elite over hard 86%, elite over normal 98%), mirrors
  are even, and the skill shows where it should: accuracy 26, 31..33,
  34..42%; parry rate 11, 18, 25%; perfect vents 50, 78, 93%.
- **No strategy dominates.** Every one-trick strategy loses to or ties the
  hard bot, and none lets a skilled person beat elite cheaply.
- **Heat is a real resource.** Holding the trigger overheats 0.8 times a
  round and loses to every tier, even normal (63% for normal). Firing to the
  edge with timed vents is exactly as good as the bots' own heat play.
- **Parries are skill, not spam.** Without the whiff lock, flicking the
  shield parried 42% of bolts and beat the hard bot 64% (measured before the
  adversarial pass); with it a whiffed raise costs the next second of
  parries. The window is 0.15 s: a reacted raise at mid range (15..25 m,
  where a bolt flies 0.25..0.4 s) lands in it; up close only anticipation
  (the stream's rhythm) parries.
- **The roll has no invulnerability.** Bolts travel, so stepping out of their
  path is the evasion and it reads on screen. With the first 1.6 s cooldown,
  0.15 s of invulnerability turned roll spam into the best trick (61% against
  hard); at 2.0 s cooldown and 0.2 s recovery the roll is a deliberate tool.
- **Range is a choice, not a win.** Long range is slow (TTK 7..8 s at 28 m)
  and dodge-heavy, close range fast; neither wins by itself once the bots
  stopped walking into fire.
- **Pace.** Real time to kill is about 5 s (1.2 s if every bolt hits up
  close), a round 10..13 s, a match about 25..30 s of play plus countdowns.
  The reactor surge trims rare stalemates (9 timeouts in 40,623 rounds).

### Running it

```
# the suite, with the balance and exploit smoke tests (about 5 s)
npx vitest run src/components/society/verse/combat
# full matrix inside vitest (single process, slow)
COMBAT_BALANCE=full npx vitest run src/components/society/verse/combat/harness
# fast, from a shell: bundle once, then every pairing in its own process
npx esbuild src/components/society/verse/combat/harness/cli.ts --bundle --platform=node --format=esm --outfile=$TMP/balance.mjs
node $TMP/balance.mjs 300 all 2026 - 15        # 56 pairings x 300 duels, 15 processes: about 1.5 min
node $TMP/balance.mjs 300 elite:skilled+kiter  # one pairing
# try a change against the defaults
node $TMP/balance.mjs 300 hard:dodger,hard:hard 1 '{"dodge":{"iframeTicks":9}}' 2
```

Sets: `ladder`, `humans`, `exploits`, `elite` (skilled+trick vs elite),
`cross`, `all`. Strategy ids: `normal`, `hard`, `elite`, `skilled`, `average`,
a trick (on the hard bot) or `base+trick`; for experiments also
`base+rangeN` (fight at N m), `base+approachN` (walk in at N/10 without a
reason), `base+mwN` (motion read window N ms).

## For the integrator

### Start, play, leave

```ts
import { createLocalDuel, idleControl, resolveAim, cameraRigFor, cameraPose } from "./combat";

const duel = createLocalDuel({ difficulty: "hard", seed: Date.now() >>> 0 });
// every animation frame:
const { view, events } = duel.frame(dtMs, control);   // control: ControlState
// view.players / view.bolts / view.hud / view.match -> draw; events -> effects and sounds
// keep calling until duel.finished, then read duel.result and duel.dispose()
duel.forfeit();                                        // the leave key, any time
```

1. **Entry.** Offer "Start duel" (with a normal / hard / elite choice) at the
   four control-ring consoles (`REACTOR_ARENA.terminals`, the manifest's
   `reactor_ring__ring_N` stand sockets, E to use) and from a menu anywhere on
   the engineering deck. Build the arena early (`buildArena(REACTOR_ARENA, 0.3)`,
   about 20 ms) when the deck loads.
2. **On start.** Fade, place the commander and a bot figure at the positions
   in the first `view.players` (spawns swap each round: follow `view.players`
   every frame, they are authoritative), switch the stage into combat mode
   (combat camera, HUD, crosshair), keep crew in the hall as non-colliding
   bystanders or send them out, disable station interactions in the hall.
3. **On end.** Show `duel.result` (won/lost, rounds, stats), return control
   to the deck's walking (snap the commander onto the deck nav grid with its
   `nearestWalkable`: the arena's rim band is wider than the cooked grid's).

### Input mapping (suggested)

| Key | ControlState |
|---|---|
| W A S D | `moveY` / `moveX` (-1..1, camera frame) |
| Mouse | `yaw`, `pitch` (pass through `resolveAim`, below) |
| Left button (hold) | `fire` |
| Right button (hold) | `ads` |
| Q (hold) | `shield` |
| Space (press) | `dodge` (direction from WASD, backward if none) |
| R (press) | `vent`; press again inside the window for a perfect vent |
| Shift (hold) | `sprint` |
| Esc then confirm | `duel.forfeit()` |

Presses are latched by the client until the next tick, so a quick tap on a
144 Hz frame is never lost.

### Camera and aim

- `cameraRigFor(player)` gives the over-the-shoulder rig for the player's
  state: hip (0.55 m right, 1.68 m up, 2.5 m back, 50 deg), sights (0.42,
  1.62, 1.3, 34 deg; blended by `player.ads`), sprint (2.9 m back, 55 deg),
  shield (2.75 m back, 48 deg).  The angles are vertical, for the default
  third-person field of view. Ease between rigs over about 0.15 s; keep the
  existing camera collision.
- `cameraPose(player, rig)` places the camera behind the right shoulder and
  orbits the pivot with the pitch.
- `resolveAim(ctx, view, cameraPosition, cameraDirection)` converges the
  blaster on whatever is under the crosshair (the muzzle sits right of and
  below the camera); feed its `yaw` and `pitch` into the ControlState. Bolts
  then land on the crosshair.
- Crosshair: `crosshairRadiusPx(view.hud.spreadDeg, fovDeg, viewportHeight)`.
  Recoil: `hud.recoilPitchDeg` / `recoilYawDeg` (the crosshair kicks and
  settles; add a small camera shake on `shot` for the local player).

### Drawing

- `view.players[i]`: position, `yaw` (body), `aimYaw`/`aimPitch` (blaster,
  with recoil), `speed`, `sprinting`, `ads`, `shieldUp`, `shieldEnergy`,
  `parrying` (window open: flash the shield), `shieldBroken`, `dodging` and
  `dodgeProgress` (roll animation), `venting`/`overheated`/`heat` (vents glow,
  steam), `alive`. The local player is already smoothed between ticks; the
  opponent is interpolated.
- `view.bolts[i]`: position, unit direction, speed, `kind` (`shot`,
  `deflect`, `parry`), `owner`. Draw a stretched emissive capsule about 1.2 m
  long and 5 cm thick along the direction with a short trail; colour by owner
  (the person's and the opponent's), brighter for a parried bolt.
- The shield: a curved energy panel 0.8 m in front, +-60 deg, 2 m high,
  facing the aim yaw; opacity from `shieldEnergy`.

### Effects and sounds (events)

| Event | Play |
|---|---|
| `shot` | muzzle flash and blaster sound at `x,y,z`; local camera kick |
| `hit` | sparks at the hit point; hit marker for `owner` (headshot variant); damage indicator from `fromX,fromZ` and a hurt sound for `target` |
| `impact` | scorch and sparks on the `surface` along the normal |
| `block` / `deflect` | shield ripple at the point; glance sound and sparks for a deflection |
| `parry` | bright flash, a sharp parry sound, a short hit-pause if wanted |
| `bolt_expire` | end the bolt's trail (left the room or fell into the shaft) |
| `shield_up` / `shield_down` / `shield_break` / `shield_ready` | shield hum on/off, break shatter, ready ping |
| `overheat`, `vent_start`, `vent_perfect`, `vent_miss`, `vent_end` | overheat alarm and steam; vent hiss; perfect-vent chime; miss buzz |
| `dodge` | roll animation and whoosh |
| `death` | collapse; kill banner |
| `countdown`, `round_start`, `round_end`, `match_end` | announcer and banners (`round_end.reason`: kill, time, trade) |
| `surge` | reactor alarm, a red pulse in the hall's lights |
| `ping` | a HUD marker on the opponent for about a second |

### HUD

`view.hud` (the local player): `health`/`healthMax`, `heat` (0..1),
`overheated`, `venting` with `ventProgress` and `ventWindow` (draw the vent bar
with its sweet spot), `ventAttempted`, `shieldEnergy`, `shieldUp`,
`shieldBroken` with `shieldBrokenLeft`, `shieldCanRaise`, `parryReady`
(whiff lock), `dodgeReady` and `dodgeCooldown`, `spreadDeg`, `ads`,
`sprinting`, `canFire`, `enemyHealth`. `view.match`: `phase`, `round`,
`scores` (by slot; `view.slot` is the person's), `roundsToWin`, `countdown`,
`roundTimeLeft`, `surge`, `winner`, `endReason`.

## In the 3D view

Code: `src/components/society/verse/duel/` (controller, input, camera, HUD
model, sound, figures, blaster, effects, shield, `DuelLayer.tsx`) and
`hud/DuelHud.tsx`, `hud/DuelPanel.tsx`, `hud/duel.css`. Strings:
`verse.duel.*` in `src/i18n/locales/ship/verse.<lang>.json`.

### Start and leave

- **Ring consoles.** In third person on Reactor Engineering, standing within
  2.2 m of a control-ring console (`REACTOR_ARENA.terminals`) shows *Duel
  terminal: Start a duel [E]*; E opens the start panel.
- **Tool rail.** The **Duel** button opens the same panel on any deck. Off
  engineering, choosing an opponent rides the turbolift down first and starts
  the match once the deck's eye-level scene is on screen.
- **Start panel** (`DuelPanel`): what the duel is, normal / hard / elite as
  three rows (no native select), the controls. A choice starts the match at
  once and asks for the pointer lock (the click is the user gesture).
- **Leaving.** Esc releases the pointer and pauses the match (the duel's clock
  stands still while paused); Esc again, or *Leave the duel*, forfeits and
  returns to the deck. After the match the result screen offers *Rematch* and
  *Back to the ship*. On leaving, the commander stands where they finished
  (snapped onto the deck's nav grid) and the shoulder camera snaps behind them.
- A stage that goes out of sight pauses a running match.

`DuelController` (React-free) owns the phases `off -> running <-> paused ->
result -> running | off`, the `LocalDuel`, the input, the camera, the HUD feed
and the sound; `VerseStage` holds one per stage and renders `DuelLayer` (in
the Canvas, eye-level view only) and `DuelHud` while a duel is on. During a
duel the stage's own keys, pointer picking, labels, crew card and tool rail
are off, the commander's deck body is hidden (`runtime.duelActive`), and crew
standing in the reactor hall are not drawn (`runtime.duelArea`), so nobody
stands in the line of fire.

### Controls

| Key | Control |
|---|---|
| W A S D (or arrows) | move (strafe / forward in the aim frame) |
| Shift | sprint (forward only) |
| Mouse (pointer lock) | aim; unlocked, movement over the stage aims too |
| Left button | fire (hold) |
| Right button | aim down the sights (hold): the camera closes in over the shoulder and narrows its field of view |
| Q | energy shield (hold) |
| Space | dodge roll in the move direction |
| R | vent; again inside the gold window: perfect vent |
| Esc | pause; again: leave |

Presses are latched until the next frame reads them. Keys the duel uses never
reach the stage's handlers. A click while the pointer is not locked locks it
again (*Click to aim* shows under the crosshair).

### Camera

`DuelCamera` turns with the eye-level views' mouse look (`mouseLook.ts`:
the same rate per pixel, sensitivity and inverted axis; the pointer lock asks
for raw movement), so aiming feels the same in and out of a match. The duel
is always fought over the shoulder: first person on the deck switches to the
duel's camera for the match and back afterwards. It eases the core's rigs
(`cameraRigFor`: hip, sights, sprint, shield; about 0.15 s) and adds 0.2 m to the side (less in the sights) so the
body clears the crosshair. The camera's vertical field of view is the rig's
(50 deg hip, about 80 deg across a 16:9 frame, the angle the bot's perception
assumes; 34 deg in the sights), widened or narrowed by the same ratio as the
person's third-person field of view in the view settings (`duelFov`). It is pulled in front of
the deck's geometry with the eye view's BVH (`runtime.eye.test`) and eases
back out. The view follows the blaster's recoil (the screen kicks with every
shot and settles with it) while the aim sent to the simulation is the mouse's;
`resolveAim` converges the muzzle on whatever the crosshair covers. Shots, hits
taken and parries add a short shake. Each round starts facing the spawn's
direction. `RealtimeBackdrop` renders from `runtime.cameraOverride` while it
is set.

### Bodies, blaster, effects

- **Figures** (`figure.ts`): the commander's own officer body and look for the
  person, the trooper body in gunmetal armour with red accents and a red visor
  for the bot. The legs walk the way the body moves (the walk plays backwards
  when it backs off, the hips turn at most 80 deg off the aim), spine and chest
  twist and bend toward the aim, the head follows it, and both arms reach the
  blaster by two-bone IK (`solveElbow`): right hand on the grip, left on the
  shroud, or palm forward behind a raised shield. Sprinting carries the
  blaster low, venting tips it up. A dodge is a tucked roll along the move
  direction; a knocked-out body falls backwards.
- **Blaster** (`blaster.ts`): procedural, graphite and brushed gold, energy
  cells along the receiver (amber for the person, red for the bot), heat vents
  on the shroud glowing blue to amber to red with the heat and pulsing while
  venting, an emitter ring at the muzzle.
- **Bolts** (`effects.ts`): a white-hot core in a coloured glow with a tapering
  trail, HDR so the eye view's bloom catches them and additive so they read on
  the low tier too; amber (person), red (bot), near white and thicker when
  parried. Pooled.
- **Impacts**: sparks with gravity, a flash, a scorch mark that glows hot for
  1.6 s and fades after 24 s. **Hits**: sparks and a flash on the body.
  **Muzzle**: a star flash. **Overheat / vent**: steam from the muzzle.
- **Shield** (`shield.ts`): a translucent curved panel, +-60 deg, 0.8 m out,
  2 m high, with a hex lattice, bright edges and a scan line; strength follows
  energy, the parry window shows as a hot rim, a block ripples blue-white from
  the strike point, a parry flashes the panel gold-white, a break flickers red.

Shader note: the trail's alpha clamps its varying before `pow`; MSAA samples
varyings just outside a triangle, and one NaN in the HDR target is spread over
the whole frame by the bloom (a black screen).

### HUD

`buildHudModel(view, feed, now, camYaw)` (pure, tested) turns the view and the
frame's events into what `DuelHud` draws: score and round clock top centre
with round pips and the opponent's health; a spread-aware crosshair
(`crosshairRadiusPx`), red over the opponent, dimmed while the blaster cannot
fire, with hit markers (white, gold headshot, red knockout); damage arcs
around it pointing where hits came from (relative to the camera); a red edge
flash on hits taken and a pulse at low health; call-outs (parry, parried,
deflected, perfect vent, vent missed, overheated, shield broken); health,
shield (parry ready / cooling / down with its countdown) and roll cooldown
bottom left; heat with the vent's gold window and a sweeping marker bottom
right; the countdown, *Fight* and round banners; the surge warning and the
opponent's pinged position; the pause and result screens (accuracy, damage,
headshots, parries, blocks, perfect vents). Key hints show for the first
seconds of a match.

### Sound

`DuelSound` synthesises everything with WebAudio (no recorded assets): the
blaster's zap, impacts, body hits and the shooter's marker tick, block,
deflection whine, parry bell, shield hum up and down, shield break, overheat
alarm, vent hiss, perfect / missed vent chimes, roll whoosh, death, countdown
ticks, round start and end chords, surge alarm. The opponent's sounds are
panned and attenuated by where they happen relative to the camera; a
compressor keeps bursts from clipping. The AudioContext starts on the start
click.

### QA hooks

`window.__verseDuel` (built bundles too, like `__verseStats`): `start(tier)`
on the deck on screen, `leave()`, `look(dx, dy)`, `hold({fire, ads, shield,
moveX, moveY, sprint})`, `press("dodge" | "vent")`, `place(x, z, yaw)` (put the
commander somewhere, e.g. at a ring console), `state()` (phase, HUD model,
view, result, crosshair target, camera pose). `localStorage["verse.duel.anyDeck"]
= "1"` lets the duel start on any deck without the lift ride (the arena's
coordinates stay engineering's), for testing a deck whose eye-level export is
missing.

Measured (headless Chrome, RTX 5070 Ti, 2560 x 1392, tier high, engineering
preview export): 60 fps (vsync) through a whole match, 160..250 draw calls,
CPU 1.5..3.8 ms per frame.

### Open

- The bodies have no aiming, firing, hit-reaction or roll clips; the upper
  body and the roll are procedural. Proper clips would look better.
- Pointer lock in the desktop app's WebView is untested here (headless runs
  aim through the QA hook).
- No settings for the duel's volume or a separate mouse sensitivity (it uses
  the eye view's).

## Testing

```
cd dodaios/ui/web/frontend
npx tsc -p tsconfig.json --noEmit
npx vitest run src/components/society/verse/combat
```

Duel integration: `duel/duel.test.ts` (input mapping, camera, HUD model, the
start / pause / Escape / leave / result / rematch flow against the real local
duel) and `hud/duelHud.test.tsx` (start panel, HUD, pause and result screens).

87 tests in 10 files, about 5 s (the files declare the node environment; the
frontend's default jsdom made the same suite take 10..20 s). The full balance
matrix is one more test, opt-in with `COMBAT_BALANCE=full`.

| File | Covers |
|---|---|
| `sim.test.ts` | match flow, rate of fire and bolt speed, falloff and headshots, overheat, timed vents, sights and spread, shield block/back/parry/break/lockout, run/sprint/sights/shield speeds, drop and catwalks, dodge, rounds and side swap, forfeit, regeneration, determinism, JSON round trip, purity |
| `exploits.test.ts` | no tunnelling at 5 m per tick (bodies, wall pipes, coolant runs), no hits through the core, low bolts stopped by waist-high cover, the shield at point blank (front holds, flank does not), parry rallies stop after three reflections, a bolt never hits its owner, deflections never hit the deflector; same-tick lag-compensated one-shots trade, mirrored duels are mirrored; double knock-outs, five trades make a draw, a drawn time-out, the dead cannot act, shields and presses across a round change, forfeit in the countdown and the pause; eleven bolts and a timed vent never overheat, holding or spamming the vent key |
| `arena.test.ts` | spawns out of sight, walkways and drop, solids, bolts over the drop and through doorways, cover spots; against the cooked deck: room outline, ring consoles, nav grid agreement over 95% |
| `raycast.test.ts` | box, cylinder, capsule and sphere sweeps; seeded randomness |
| `netcode.test.ts` | exact state and input round trip, snapshot size; latency, jitter, loss and reliable order; WebSocket adapter; handshake; exact self-prediction (0 corrections); prediction under 70 ms, jitter and 8% loss; smooth opponent; leave and disconnect; rejected tuning or third player; lag-compensated shot |
| `netcodeAdversarial.test.ts` | a modified client (10x move stick, strings and huge numbers as aim, unknown buttons, malformed messages); legal inputs pass the sanitising unchanged; a press inside a trimmed burst survives; another arena is rejected; whole bot duels at 70 ms, 40 ms jitter and 15% loss: every event exactly once on both clients, the final state arrives, corrections stay small, the same seeds replay the same duel |
| `bot/bot.test.ts` | never fires without a recent real sighting (whole duels); reaction time per tier; leads a running target; parries and blocks a marksman's bolts; routes round and over the shaft |
| `session.test.ts` | a whole match against the bot through the full stack; forfeit at any time; over a laggy link; crosshair convergence hits; crosshair size |
| `harness/balance.test.ts` | elite beats normal, tricks lose to hard, duels reproduce from their seed |
| `harness/exploits.test.ts` | kiting, point-blank orbiting and rushing lose; playing for the clock and spawn watching are no walkover; a skilled person beats normal and finds elite hard but beatable |

## Later, for PvP

- A Node host: `MatchServer` per duel behind a WebSocket server, matchmaking
  and accounts outside this module. Inputs are already sanitised and messages
  shape-checked; add rate limits per connection there.
- Clock drift and jitter: the server's input queue absorbs them (late inputs
  repeat the last one, a backed-up queue is trimmed without losing presses),
  at the cost of a rare one-tick correction; for real networks add client
  time dilation (run a little faster or slower to keep the queue at 2).
- Lag-compensation trust: a client says which tick it saw (`viewTick`), so a
  cheater can claim the full 250 ms rewind for every shot. The cap bounds it;
  the server could also bound the rewind by its own round-trip measurement.
  For the victim, a rewound bolt appears partway along its flight.
- Interest management: today every client gets the full state, including a
  hidden opponent; for competitive play send the opponent only when visible.
- Parry fairness under latency: judge the parry window on the defender's
  input tick (favour the defender) as the shot side already is. Over a
  network everyone sees incoming bolts a round trip into their flight, which
  makes reacted parries and rolls harder than in the local duel.
- Prediction shows the opponent's held trigger: when the opponent let go
  within the last round trip, a bolt can show for a few ticks and vanish
  (1 in 80 opponent bolts at 70 ms).
- Different browsers may round `Math.sin` and friends differently in the
  last bit. The server is authoritative and the state is quantised, so that
  only causes a rare correction, never a lasting desync.
- A binary encoding of the same arrays; delta snapshots if bandwidth matters.
