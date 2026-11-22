# The policy selector's gate

When is a new way of briefing or steering coding agents better than the one in
use? This is the rule, fixed in code (`dodaios/rsi/selector.py`, the bounds in
`dodaios/rsi/stats.py`). It reads the run record of enforced checks
(`[rsi] verify = "enforce"`, see `docs/coding-run-verification.md`) and only
reports: nothing here switches a policy yet.

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
| pass | 1 when the run ended `verified`, else 0; a run the person took over is left out |
| one-shot | passed with no follow-up order and without the person stepping in |
| P | follow-up orders; a run that hit the limit counts the limit |
| cost | USD plus 0.001 USD per second of turn time |
| churn | lines added plus deleted |
| hard | a weakened check or an off-limits change in the final output |

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

## What it takes, honestly

At 80 requests per arm and equal pass rates the PassRate's bound sits near
−0.10, so a cheaper policy needs well over 100 requests per arm before branch B
can accept it. Most decisions will take weeks in a quiet cell.

## Tests

`tests/unit/rsi/test_selector.py`: the exact sign-flip case (3 wins, 0 losses
in 30 tasks is p = 1/8), calibration under equal arms, blocking, and each part
of the rule.
