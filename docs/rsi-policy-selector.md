# The policy selector's gate

When is a new way of briefing or steering coding agents better than the one in
use? This is the rule, fixed in code (`dodaios/rsi/selector.py`, the bounds in
`dodaios/rsi/stats.py`). It reads the run record (every coding run is
recorded and judged, see `docs/coding-run-verification.md`) and only reports.
The trainer below is what changes a policy, through the self-change registry.

```
python -m dodaios.rsi.selector --cells
python -m dodaios.rsi.selector --cell "backend|claude-opus-5-5|claude-cli 2.1" \
    --candidate <policy id> --reference <policy id> --branch B --target cost
```

## Where runs are compared

Only inside a *cell*: the domain a run was bound to, the requested model, and
the runner with its CLI version line (`claude-cli 2.1`). A run whose answering
model or CLI line changed on the way is left out. The unit is the person's
request: the runs of one request are averaged.

## What a run counts for

| | |
| --- | --- |
| pass | 1 when the run ended `verified` and nothing the person or the repository did next took it back, else 0 (`self_checked` is 0). Taken back: merged work turned red (`leaked`), the person took the result over (`taken_over`) or asked again (`asked_again`), the pull request was closed without merging (`pr_closed`), the commit was reverted (`reverted`). A run the person took over counts, as not passed; a run a new order superseded is left out |
| one-shot | passed with no follow-up order and without the person stepping in |
| P | follow-up orders; a run that hit the limit counts the limit |
| cost | USD plus 0.001 USD per second of turn time |
| churn | lines added plus deleted |
| hard | a violation of the output scan in the final output (a weakened check, a changed gate or hook, a secret or deployment file), or merged work that turned red later (a leak); an edit to a core path of the app or to an instruction file for agents is not one |

## The rule

1. **Hard exclusions.** One hard event of the candidate rejects it.
2. **Enough data.** At least 60 requests per arm, and both arms lost about the
   same share of runs to model or CLI changes; otherwise `inconclusive`.
3. **The PassRate never drops.** A drop rejects. A lower bound below −0.10
   without a drop asks for more runs.
4. **Branch A:** the PassRate rises by at least 0.10, its lower bound is above
   zero, and the cost stays within 125 % of the reference.
5. **Branch B:** the lower bound of the target metric chosen before the data
   exist is above zero, and the other metrics stay above their floors
   (one-shot −0.05, P +0.15, cost +10 %, churn +15 %).

Lower bounds are one-sided at 95 %, from randomisation tests: labels permuted
within blocks (CLI line and repository) for a canary, signs flipped for paired
tasks. A percentile bootstrap is not used for decisions; on binary metrics with
few wins it claims too much.

## Policies and the loop that changes them

A *coding policy* says how the app steers one cell's runs: whether a run is
held until its verdict (`hold`), how many follow-up orders a run may get and
how long checks are waited for (never above the code's own limits), and
optionally a domain block of at most 600 characters for the first brief
(`dodaios/rsi/policy.py`). The factory policy does not hold. Its runs are
judged, but the lead is not held back and no order goes to the agent. A policy
stored before `hold` existed reads as one that does not hold, and keeps its id. Policies are self-changes of
the surface `coding_policy` (Trust → Self-changes): one target per cell for
the active policy, one for a candidate on trial, each with versions, a diff and
a byte-exact rollback. A policy with text for the agents waits for the owner;
one beyond the limits is blocked.

Every run is bound before its order goes out (or, failing that, at its first
turn): the active policy, or, while a candidate is on trial, the candidate for
half of the person's requests (a fixed draw per request, `dodaios/rsi/bind.py`).
The policy is frozen into the run's record.

After each verdict the trainer (`dodaios/rsi/trainer.py`) looks at that cell:

1. Without a candidate, with an active policy that holds, and with 60 runs
   under it, each candidate of a small fixed grid (fewer follow-up orders, a
   shorter wait; it keeps the active policy's `hold`) is replayed on the record (`dodaios/rsi/replay.py`): up to where it would have stopped,
   a run is exactly what was recorded. The first candidate the replay does not
   reject goes on trial, and its claim (branch B, cost) is fixed before its
   own data exist. A replay that covers less than 90 % of the runs says nothing.
2. With a candidate on trial, the gate above decides on the runs since the
   claim. Accepted: the candidate becomes the active policy, on probation.
   Rejected, or without an answer after 28 days: the trial ends.
3. The first run under a new active policy whose final output weakened a
   check, or whose merged work turned red later, rolls it back to the exact
   previous policy.

In a cell whose active policy does not hold (the factory policy), the trainer
proposes nothing and says why. A run that is not held gets no follow-up order,
and nobody waits for its checks, so a candidate that only changes those would
measure nothing.

## Text for agents (Phase 5)

When no steering candidate survives the replay, the miner
(`dodaios/rsi/mining.py`) reads the follow-up orders recorded under the cell's
active policy. When one of a few fixed patterns cost a follow-up order in at
least five runs (a check or test configuration was changed, tests were
deleted, skipped or loosened, linters failed, tests failed), it suggests
exactly one fixed sentence to add to the domain block, citing those runs. The
sentences are written in the code, not by a model, and none asks an agent to
check less.

Such a proposal waits for the owner in Trust → Self-changes, with the cited
runs in its reason. Only after approval does it go on trial: its claim
(branch B, fewer follow-up orders) is fixed then, half of the person's
requests in that cell carry the block in their first brief, and the gate
decides as for any candidate. The thread shows the lead's words in its bubble;
the block is only in what the agent reads.

## New models and CLI versions

A new answering model or CLI version line opens a new cell, compared only with
itself (`dodaios/rsi/drift.py`). Until it has a policy of its own it runs
under the active policy of its nearest predecessor (same domain, model and
runner, the closest earlier line). Once it has 40 judged runs,
`python -m dodaios.rsi.drift` compares them with the last 40 of the
predecessor and gives one recommendation per new cell. A drop is named only
when it is shown; nothing switches a model or a CLI by itself.

## What it takes, honestly

At 80 requests per arm and equal pass rates the PassRate's bound sits near
−0.10, so a cheaper policy needs well over 100 requests per arm before branch B
can accept it. Most decisions will take weeks in a quiet cell.

## Tests

`tests/unit/rsi/test_selector.py`: the exact sign-flip case (3 wins, 0 losses
in 30 tasks is p = 1/8), calibration under equal arms, blocking, and each part
of the rule. `tests/unit/rsi/test_policy.py`: limits, storage, the canary
split, the registry (trial, owner approval for text, blocking, rollback) and
binding in a recorded run. `tests/unit/rsi/test_replay_and_trainer.py`: replay
cuts and coverage, and the whole loop with a real registry, including a mined
line that waits for the owner. `tests/unit/rsi/test_mining.py`: the patterns.
`tests/contract/test_workspace_chat_threads.py`: an approved block in a real
first brief. `tests/unit/rsi/test_drift.py`: which cell follows which,
inheritance and the notes.
