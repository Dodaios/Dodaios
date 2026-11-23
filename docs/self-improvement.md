# Self-improvement

Dodaios changes its own behaviour while it is used: the values it retrieves
memories with, the lessons it keeps, its skills, how it briefs coding agents.
No model is trained. What improves is everything around the model.

This page describes the part that decides whether a change made the assistant
better. It is being built in steps (issue #1921); the last section says what
exists today.

## What "better" means

Version B of the assistant is better than version A when, on the same tasks
with the same model, B solves more, loses nothing noticeable in any domain,
and costs no more.

The number a person sees is the **learned advantage**: the assistant as it is
now against the assistant as it ships, in the same night, on the same tasks,
with the same model. A change of the model or of a coding CLI moves both sides
alike, so it cannot pass as learning.

- **Learned** is every change in the self-change registry that the person did
  not make: parameters, lessons, skills, policies.
- **As it ships** is the assistant with all of those counted as rolled back.
- **The same on both sides** is what the person said or wrote themselves:
  facts about them, their instructions, the persona, their contacts.

## Kernel and learners

```
 kernel (the assistant cannot change it)      learners (improvable)
 ───────────────────────────────────────      ───────────────────────────
 benchmark     tasks, splits, results          tuner      parameters
 gate          paired test, evidence           reflector  lessons
 registry      candidate, trial, live, undo    skill reviser, brief shadow
 night cycle   idle time, budget               coding policy, meta level
```

The kernel is `dodaios/rsi/` and `dodaios/self_change/`. Both are core paths:
the registry refuses any self-change that touches them, and also one that
touches what the kernel reads its evidence through (`EVIDENCE_PATHS` in
`dodaios/self_change/surfaces.py`: the chat event store, the judge from
another model family, the skill replay, the seat that may be asked, the CI
workflows). A learner proposes; only the kernel decides.

No person approves anything. A change that the gate cannot measure stays a
candidate and is never applied. The person keeps two controls: stop, and undo.

## The benchmark

A task is one thing to do together with the check that says whether it was
done (`dodaios/rsi/bench/model.py`). Tasks come from a seed suite that ships
with the app and from the person's own past work.

| Domain | The check | Needs a model |
| --- | --- | --- |
| `recall` | the right memory is among the first hits | no |
| `skill` | the right skill is picked, or none | no |
| `first_move` | the lead's first tool call for a request | one call |
| `action` | a whole turn reaches the same committing call | one turn |
| `answer` | a jury of other model families prefers it, blind | turn and jury |
| `brief` | the brief names what the merged change needed | one call |
| `coding` | the tests that were merged pass | a coding run |

### Splits

Tasks that came from the same piece of work share a *group*, and a group falls
into exactly one of four splits by a hash of its key. The domain is not part of
the draw: the brief task and the coding task of one pull request are in the same
split, so nothing practised on one can be graded on the other.

| Split | Share | Used for | Read by |
| --- | --- | --- | --- |
| practice | 40 % | learners try candidates here | learners |
| select | 25 % | decides whether a candidate goes in | the gate |
| guard | 15 % | decides whether a live change stays | the gate |
| sealed | 20 % | only reported: the number the person sees | the report |

The draw is fixed in code and pinned by a test. Nothing re-draws it, so a task
a learner has seen can never become a task the assistant is graded on.

### Tasks from past coding work

The app does not have to wait for its own records to have tasks with a known
answer. The coding CLIs keep a record of every session on the person's
machine, and the repository keeps every merged pull request
(`dodaios/rsi/bench/past_work/`). Joined, they say what was asked and what the
right result was, for work that already happened:

- a `brief` task: given the person's request and the repository as it was, does
  a brief name the files the merged change touched, its tests, and what the
  person had to say afterwards?
- a `coding` task: given the same request and state, do the tests that were
  merged with the work pass? Only for a change that brought tests and code.

Both tasks of one pull request share a group. What a task is given never holds
the merged commit or its paths.

Which words asked for which pull request is decided by a strict rule, because
a guess would grade the assistant against the wrong answer. The first pull
request of a session takes the first thing the person said that is long enough
to be a request; what they said after it is what they had to add. A later pull
request counts only when the person said exactly one thing since the previous
one. A pull request the rule cannot place is left out and counted with its
reason, as is one that was not merged, was reverted, or whose request holds
credential-shaped text. A session that opens with a brief the app itself sent
gives only the coding task. No model is called and nothing leaves the machine.

```
python -m dodaios.rsi.bench.past_work --repo .
```

prints how many tasks each split gets and what was left out, without any
request text. Measured on 2026-11-23 on the maintainer's machine: 146 sessions
had opened 226 pull requests; 129 pieces of work became 129 brief and 114
coding tasks, in 16 seconds. In a hand check of 22 of them, every request asked
for the change that was merged.

Readers exist for two CLIs (`claude`, `codex`); another one is a function that
gives the same shape. A sub-agent's own record is not read, and a brief from
before the app logged its briefs cannot be told from the person's words.

### A run changes nothing

A benchmark run computes under an **overlay** (`dodaios/rsi/overlay.py`)
instead of the live state: other parameter values, all learned changes rolled
back (`FACTORY`), single changes rolled back, a fixed clock. While an overlay
is active the run is a replay and writes nothing into live stores. Code in the
run's own task finds the overlay by itself; a tool call that arrives through
the gateway in another task finds it by the run's session id.

### Which assistant did this

Every result names the state that produced it, as a **fingerprint**
(`dodaios/rsi/fingerprint.py`): app version, learned changes in effect, a hash
of the parameter values, model, seat and CLI version. Two runs are a pair only
when model, seat, CLI and app version agree.

## Parameters

Behaviour that used to be a constant in the code is a **parameter**
(`dodaios/rsi/params/`): a name, the value the app ships with, and limits.
`params.get("recall.turn_limit")` stands where the constant was. The catalog
(`catalog.py`) is part of the kernel: a learner can move a value between its
limits and can never widen them. Each parameter names the benchmark domain
that can measure it; without one it stays at its default.

A learned value is a self-change of the surface `parameter`, written by the
registry into `params.db`, with a version, a diff and a byte-exact rollback.
`get` answers the overlay of a benchmark run first, then the learned value,
then the shipped default.

Today the memory recall reads twelve parameters (how strongly a pinned or a
fresh memory is preferred, how many memories and lessons a message may bring
up, and how many characters they may take). Their defaults are the constants
the code had.

## The gate's answer

The gate compares two states on the same tasks and answers with **evidence**
(`dodaios/rsi/gate/evidence.py`): per domain the mean difference per task,
bounds that stay valid however often the gate looked, and the number of pairs.

| Verdict | Meaning | What the registry does |
| --- | --- | --- |
| `accept` | better where it claimed, nowhere clearly worse | applies it on trial |
| `reject` | worse, or a hard rule broken | never applies it |
| `undecided` | not enough tasks yet | keeps it a candidate |
| `unmeasured` | no check can tell | keeps it a candidate |

A change is applied only while the live state still has the fingerprint it was
measured against.

## Updates

The app is updated often, and nothing learned may be lost by an update.

- Everything learned is in the data directory, never in the program folder.
- Every kernel file carries a schema version that only moves forward
  (`dodaios/rsi/storage.py`). A newer app migrates an older file step by step,
  each step in one transaction, after putting a copy of the file aside. An
  older app that meets a newer file opens it read-only and pauses its writing.
- A learned parameter value remembers the shipped default it was learned
  against. When an update changes that default, the value stays in effect and
  is measured again first. When a parameter is renamed, the value moves along
  (`aliases`). When a parameter is gone, or the value lies outside new limits,
  the entry rests without effect and without an error, and applies again as
  soon as a version knows it.
- A task keeps its id when its content is corrected; results belong to the
  content hash they were measured on, so only those go stale.
- The fingerprint holds the app version. After an update the assistant as it
  ships is measured again, and the curve marks the update.

## What the app shows

`GET /api/self-improvement` (planned shape):

```json
{
  "status": {"state": "idle", "paused": false, "last_night_ms": 0,
             "budget": {"used": 0.0, "cap": 0.2}},
  "advantage": {"domains": [
    {"domain": "recall", "measured": true, "why_not": "",
     "now": 0.81, "factory": 0.74, "diff": 0.07, "low": 0.02, "high": 0.12, "n": 140,
     "cost_now": 0.0, "cost_factory": 0.0}]},
  "series": [{"ts_ms": 0, "domain": "recall", "diff": 0.07, "low": 0.02, "high": 0.12,
              "n": 140, "app": "5.7.0"}],
  "stack": [{"id": "", "surface": "parameter", "target": "", "title": "", "state": "live",
             "since_ms": 0,
             "effect": {"domain": "recall", "diff": 0.03, "low": 0.01, "high": 0.05, "n": 90}}],
  "night": {"ts_ms": 0, "practised": [{"domain": "recall", "tasks": 60}],
            "tried": 4, "kept": 1, "rejected": [{"title": "", "reason": ""}]}
}
```

## What exists today

| Part | State |
| --- | --- |
| Shared shapes: overlay, fingerprint, task, split, result, evidence | built |
| Kernel storage with a schema version | built |
| Kernel and evidence paths refused by the registry | built |
| Parameters with limits, read by the memory recall; learned values survive updates | built |
| A recall that can be replayed without leaving a trace (no use count, no cache) | built |
| Tasks from past coding work (`brief`, `coding`), read from CLI records and merged pull requests | built, not yet stored or run |
| The recall benchmark, the paired test, the measured gate | next |
| Tuner, night cycle, automatic rollback, the page | next |
| Always-on recording of work, the other domains, lessons, the jury | later |
