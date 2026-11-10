# Verse harness (WP10)

Autonomous proof for the Unreal Verse: CI lanes, the netcode test, headless
bot-vs-bot balance runs with their gates, perf capture, screenshots and the
evidence folder. Plan: `docs/verse/unreal/work-packages.md` WP10. Contracts:
`contracts/bot.md` 10 and 11, `contracts/combat-state.md` 12,
`contracts/destruction.md` 10, `architecture.md` 7 and 8,
`contracts/art-pipeline.md` 8.1 and 14.

## Layout

| Path | What |
|---|---|
| `schema/scenario.schema.json` | `verse.scenario/1`: the units one headless process plays (`-VerseHarness=<file>`) |
| `schema/bout.schema.json` | `verse.bout/1`: one line per bout in `bouts.jsonl` |
| `schema/balance.schema.json` | `verse.balance/1`: the report `balance.py` writes |
| `balance/sets.json` | Set definitions, bout cut (15 kills or 600 s), learning, reset and adaptive pairings, the merge-queue subset |
| `balance/scenarios/*.json` | Scripted scenarios `wall_opened_unseen` (F7) and `destruction_storm` (destruction.md 10) |
| `balance/bout_table.json` | Bouts per pairing for 95 % intervals of at most +-0.06, from the measured speed (risk RK1) |
| `netcode/netcode.json` | Dedicated server plus 2 lagged clients: lag, loss, duration, gates |
| `perf/budgets.json`, `perf/replay.json` | Budgets of architecture.md 7; the fixed perf replay path |
| `capture/cameras.json` | Reference views per deck for screenshots and palette shares |
| `fairness/match_memory_fields.json` | Field names the L1 no-persistence scan looks for |
| `clang-format.yml` | Style the static lane applies to changed C++ lines |
| `../Data/bot/person_models.json` | Person models `skilled`, `average` and the 17 tricks (propose-only) |

## Commands

```text
python scripts/unreal/balance.py --set ladder --bouts 200 --seed 7 --jobs 4
python scripts/unreal/balance.py --set ladder --set tricks --tricks spray,camper,rusher,wallspam --gates BG1,BG2,BG4,BG11 --bouts 40
python scripts/unreal/balance.py --set all --nightly
python scripts/unreal/balance.py --from-bouts <run folder>      # gates from recorded bouts
python scripts/unreal/balance.py --speed                        # x real time and the bout table
python scripts/unreal/netcode.py [--iris both]
python scripts/unreal/perf.py run --runs 2 | compare A B | parse <csv>
python scripts/unreal/capture.py shots --wp WP12 --subtask 12.3 | palette <png> | proof-dir --wp WP10 --subtask 10.8
python scripts/unreal/check_bot_isolation.py                    # F1, F6
python scripts/unreal/check_lfs.py --diff origin/main
python scripts/unreal/done_check.py
```

Every run that starts Unreal takes the machine lock (`scripts/unreal/with_lock.py`).

## Lanes

| Workflow | Runner | Trigger | Runs |
|---|---|---|---|
| `unreal-static.yml` | GitHub-hosted, LFS off, 5 min | PR, merge queue, main | DAG, folder names and tracked External files (`check_art_text.py`), F1 and F6, LFS pointers and remote objects and sizes, clang-format, art text and ledger, workflow policy, the script tests (including fork safety, A10.2) |
| `unreal-build.yml` | self-hosted | same-repo PR, merge queue, main | Win64 Editor and Game, automation under `-nullrhi`, netcode smoke; Linux Game cross build |
| `unreal-gauntlet.yml` | self-hosted | merge queue (short), nightly (long) | `balance.py` and gates; nightly netcode with Iris on and off |
| `unreal-perf.yml` | self-hosted | nightly, quiet hours | perf replay twice (budgets, 3 % stability), reference views with palette shares |

The `ci.yml` jobs that make these lanes required (`gate.needs`) belong to the
integration owner (architecture.md 8.2).

## Inside the game process

`UVerseHarnessSubsystem` (a game instance subsystem, created only when the
command line asks for a harness run) starts one driver:

- `UVerseBalanceGauntletController` for `-VerseHarness=`: spawns both slots,
  records bouts from the `UVerseEventHub` events into `FVerseBoutRecorder`, writes
  `bouts.jsonl` and `speed.json`, then exits.
- `UVerseCaptureDirector` for `-VerseCapture=`: reference views or the perf
  flythrough; waits for shader compiles, loading and streaming before each shot.
- The netcode autopilot for `-VerseNetDuration=` and `-VerseNetAutopilot=`.

`AVerseModelController` is a person model: the brain (null until WP08), then
reaction time and turn rate of the person model, then the trick overrides of
`FVerseTrickOverrides`. It reads only `FVersePerceptFrame` (F6).

## Fire audit log format (F4)

VerseBot writes one line per bot shot to the process log, which `balance.py`
merges into the bouts:

```text
[VerseFireAudit] pairing=<id> match=<m> bout=<n> side=<A|B> mode=<Visible|Suppression|Prefire|WallShot> t=<server ms> ids=<percept ids> mass=<belief> age=<s>
```

A bot shot without such a line counts as unclassified and fails F4.

## Waiting on other packages

| Item | Needs | Until then |
|---|---|---|
| Kill-based gates BG1-BG10, BG12 | WP08 brain, WP02 weapons, WP11 ruleset | Report `not_run` with "null brain" when no shot was fired |
| F2, F3, BR1 verdicts | Their automation tests (WP07, WP08) | Fed through `balance.py --checks <json>`, else `not_run` |
| F5 bearing windows | `UVersePerceptionService` (WP07) feeding no-percept windows into the bout | `not_run` below 2,000 windows |
| F7 plan watch, `destruction_storm` budgets | WP06 pieces and WP08 plans | `not_run` |
| `botMsP99`, `navFailures`, adaptive `s` | VerseBot timing, nav and `BotEffectiveSkill` on `AVersePlayerState` | `null`; `s` is read by reflection once the field exists |
| Destruction reset between bouts | WP06 and WP11 reset | Bouts run without it |
| Reconcile counters | WP02 prediction writing `[VerseCounter] reconcile...=<n>` | Netcode gates on corrections and joins only |
