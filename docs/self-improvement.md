# Self-improvement

Dodaios changes its own behaviour while it is used: the values it retrieves
memories with, the lessons it keeps, its skills, how it briefs coding agents.
No model is trained. What improves is everything around the model.

This page describes the part that decides whether a change made the assistant
better. It is being built in steps (issue #1921); the last section says what
exists today.

## What "better" means

Version B of the assistant is better than version A when, on the same tasks
with the same model, B solves more and loses nothing noticeable in any domain.
Quality comes first. Between two versions that are equally good, the cheaper
one is better.

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

### The seed suite

A new installation has no past work, CI needs a benchmark that depends on
nobody's data, and a published number must be one everybody can reproduce. The
seed suite is that: the memories of one invented person (150 of them) and 330
messages she might send (`dodaios/rsi/bench/seed/recall.json`). 60 messages
need no memory; 40 ask for the newer of an old and a new fact about the same
thing; 62 share more words with a sibling memory than with the right one.

```
python -m dodaios.rsi.bench
python -m dodaios.rsi.bench --set recall.turn_limit=3 --set recall.relative_floor=0.5
```

The command reads nothing from an installation and writes nothing; it builds
the invented person's memory in RAM, with its own clock, so the numbers are
the same on every machine and on every day. With `--set` it prints the paired
comparison against the shipped defaults per split.

The seed suite never decides anything about a real installation. A value
tuned on an invented person's memories says nothing about a real person's, so
a change to the live assistant needs evidence from that person's own tasks.

### How the recall domain scores

For each message the run asks the code a live turn uses which memories the
message brings up (`recall_for` in `dodaios/memory/vault/runtime.py`).

- A message with gold memories scores the share of them the model has in
  front of it. A gold memory shown behind an outdated one counts half.
- A message that needs no memory scores 1 when nothing is looked up for it,
  else 0. Without this, a recall that shows something to every message would
  score best.
- The cost of a task is the prompt it adds, in tokens (characters / 4).

### Tasks from your own memory and messages

What the assistant should be good at is this person, not an invented one. So
an installation builds its own recall tasks, at night
(`dodaios/rsi/bench/own/`), on a copy of the memory taken that night:

- **Questions.** For a memory, a model writes two messages the person might
  send that need exactly that memory, in the person's own language and tone
  (a few real messages serve as examples of the style). Python then decides
  what is kept: the message must share a topic word with its memory, must not
  be the memory said again, must be short, and must not fit a sibling memory
  better.
- **Messages.** Real messages the person sent, each with the stored memories a
  generous search finds for it. A model says which of them the message needs,
  or none. It is asked twice, with the candidates in the opposite order, and a
  message becomes a task only when both answers agree. This is where the true
  mix comes from: most messages need no memory at all.

What is offered to the labeller is searched with the shipped values, never
with learned ones, so the tasks are not shaped by what they are meant to judge.

The memories and messages go to the provider the person's assistant already
answers on, on its subscription or a local model, and to no one else. Memories
marked sensitive are never sent. A key that bills per token is never used:
without a subscription or a local model no tasks are made and the nights stay
quiet. A night makes at most eight such calls, however much there is to do.

Forgetting reaches the tasks: when a memory is forgotten or replaced, every
task that names it is retired and its text erased.

On the maintainer's installation one run of three calls gave 24 question
tasks from 12 memories and 6 message tasks from 8 messages, 5 of which need no
memory; the two askings disagreed on the other 2, which were left out.

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
reason, as is one that was not merged, was reverted, changed no file, or whose
request holds credential-shaped text. A session that opens with a brief the app itself sent
gives only the coding task. No model is called and nothing leaves the machine.

```
python -m dodaios.rsi.bench.past_work --repo .
```

prints how many tasks each split gets and what was left out, without any
request text. With `--store` it puts the tasks into `bench.db` instead
(`past_work/intake.py`). A CLI deletes a session record after some weeks, so
the tasks are stored when they are found, and a stored task stays when its
record is gone. It is retired only for a reason the repository gives: its pull
request was reverted, or its commit left the default branch.

The repository is read in two steps: one walk over the subjects of the default
branch, then the paths and line counts of only the pull requests that are
asked about.

Measured on 2026-11-23 on the maintainer's machine: 151 sessions had opened
235 pull requests; 133 pieces of work became 133 brief and 117 coding tasks,
in 20 seconds. In a hand check of 22 of them, every request asked for the
change that was merged.

Readers exist for two CLIs (`claude`, `codex`); another one is a function that
gives the same shape. A sub-agent's own record is not read, and a brief from
before the app logged its briefs cannot be told from the person's words.

### How the brief domain scores

A brief is scored on the files it names against the change that was merged
for the request (`dodaios/rsi/bench/brief.py`):

- **found**: the share of the change, in lines, that lies in files the brief
  names;
- **astray**: of the paths the brief names, the share the change did not touch.

The score is the balance of the two (the harmonic mean of found and
1 - astray). A brief that names the one file most of the work was in scores
well, one that lists every file in sight does not, and one that names no file
scores 0. A file is named by its path, by its file name where that name tells
files apart, or, for Python, by its dotted module. The cost is the brief's
length in tokens.

Not scored yet: whether the brief already said what the person had to add
afterwards; that needs a judge. And nothing writes the brief for a task yet:
the check takes a text. Applied to the opening words of the mined sessions as
they stand (2026-11-23): a typed request scores 0, as it should, and the eight
openings that were briefs themselves average 0.08. That is where the briefs
of the past stood on this measure.

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

Today the memory recall reads thirteen parameters (how strongly a pinned or a
fresh memory is preferred, how many memories and lessons a message may bring
up, how many characters they may take, and how well a memory must match to be
shown at all). Their defaults are the constants the code had; the last one is
new and ships switched off (0), so nothing changes until a night proves a
value for it.

## Notes the assistant wrote for itself

The memory learner keeps two kinds of rule for the assistant. A lesson is the
person's correction in the person's words: an instruction. It applies at once,
nothing measures whether to obey it, and it is the same on both sides of every
comparison. A how-to is different: the assistant watched a tool fail and a
later call work, and wrote itself a note that rides in later prompts. That is
the assistant changing its own behaviour.

Each night every current how-to note gets an entry of the surface `lesson` in
the registry (`dodaios/rsi/adopt.py`). So it shows in the list of what the
assistant changed in itself, the person can take it back with one click (the
note is ended in the memory), and a run of the assistant as it ships does not
see it. The entry holds the memory's id and none of its words: a note the
person forgot leaves nothing behind. A how-to is not measured yet; the list
says so.

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

### The rules

They are fixed in `dodaios/rsi/gate/rules.py`. No learner and no setting
changes them.

**Letting a candidate in** is decided on the select tasks, comparing the
assistant as it is with the assistant plus the candidate:

1. Fewer than 30 tasks: nothing is decided, the candidate waits.
2. The whole interval is below zero: rejected, it is worse.
3. The whole interval is above zero: accepted. Quality comes first, so a clear
   gain may cost more, up to a cap per domain. The recall has no cap: each
   parameter's own limits already bound how long the prompt can get.
4. No clear gain, but at least 5 % cheaper and the lower bound above -0.05:
   accepted, it is as good and costs less.
5. No clear gain and more than 10 % more expensive: rejected.
6. Otherwise rejected as "no clear difference": every task of the split was
   used, and asking again without new tasks would only spend the error budget.

**Keeping a change** is decided on the guard tasks, comparing the assistant as
it is with the assistant without that change. It stays (a change on trial
becomes live) when it shows no harm. It is taken back when the whole interval
is below zero, or when it is negative on the guard tasks and no longer
positive on the select tasks measured again. Each night checks what is on
trial and the newest live changes, newest first.

### The error budget

Every decision on a split can be wrong by chance: at 5 %, one decision in
twenty lets in a change that is not better. A learner that keeps proposing
would in the end fit those very tasks. So the select tasks of a domain are a
budget of twelve decisions, each made at 5 % (`dodaios/rsi/gate/alpha.py`).
When it is used up, nothing more is decided there and no learner is asked to
propose, until new tasks arrive: when the split grew by a quarter, a new
budget opens, on tasks the earlier candidates never met.

This bounds each single decision, and it means at most 0.6 wrongly admitted
changes per budget on average. It does not promise that none slips in. That is
what the second measurement is for: every admitted change has to hold again on
the guard tasks, which no candidate was ever decided on, and it is checked
there again in later nights.

The order in which a comparison walks its tasks follows the question alone
(the target and the version of the change), never the results. So the same
comparison can be repeated and gives the same answer.

### Whose tasks decide

An installation decides on tasks built from the person's own work. The seed
suite decides only in a sandbox. Without tasks of its own, an installation
measures nothing and applies nothing: candidates wait.

## The night

While the person is away the kernel runs one round (`dodaios/rsi/night.py`):

1. It checks what is in effect: every change on trial and the newest live
   ones, each against the assistant without it. What no longer pays is taken
   back. After an app update everything learned is checked again.
2. The learners propose. Each gets practice tasks and nothing else.
3. The gate measures every candidate on tasks no learner saw.
4. It measures the learned advantage on the sealed tasks.
5. It writes down what it did (`nights` and `series` in `bench.db`).

Before all of this a night copies the memory and builds new tasks from the
person's own memory and messages (see above), and erases tasks about memories
that are gone.

Nothing is announced: no notice, no sound, no voice. The app looks every ten
minutes whether a night is due: the person must have been away for 15 minutes,
and there is at most one night in 20 hours. Measuring the recall asks no
model; building tasks does, at most eight small calls a night. The limits are
fixed in the code, not in a setting: only while the person is away, on the
assistant's subscription or a local model, never a key that bills per token.
(The share of a plan's usage window a night may use, 20 %, is fixed for the
domains that will run whole turns; eight small calls stay far below it.) The person's stop (`Night.pause`) is kept in `bench.db` and
survives a restart; while it is set nothing is proposed, measured or changed.

### The tuner

The first learner (`dodaios/learners/tuner.py`) needs no model. For every
parameter a domain measures it tries values 1, 2, 4 and 8 steps below and above
the value in effect, each alone, on the practice tasks, and proposes at most
one move per night: the one with the largest gain, or else the cheapest one
that scores no worse. It may be as greedy as it likes; the gate decides on
other tasks. It does not ask again for a value the gate turned down in the
last 30 days.

### Try it

```
python -m dodaios.rsi.night --sandbox --nights 3
python -m dodaios.rsi.night --sandbox --plant recall.relative_floor=0.9 --nights 3
```

`--sandbox` builds a throwaway installation that decides on the seed suite and
prints what each night did. `--plant` puts a value in effect first, as if an
earlier night had learned it. With the shipped values the tuner's proposals
are turned down ("no clear difference on 84 tasks"): the seed suite is too
small to prove an effect of one or two points. With `--plant
recall.min_score=12`, a value that looks up almost nothing, the first night
lets in `recall.min_score = 8.0` as "better on 84 tasks" (+0.12, between +0.02
and +0.21), and the second night confirms it on the guard tasks. The step
after that (4.0, +0.11) is not proven on 84 tasks and stays out: a small suite
proves large effects only.

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
  ships is measured again, and the curve marks the update. The first night
  after an update checks everything that was learned, not only the newest.

This is tested against frozen states. `tests/fixtures/rsi/upgrade/v1/` is what
an installation had learned under the version that introduced the kernel: its
three files as SQL text and a manifest. `tests/unit/rsi/test_upgrade.py` opens
every such folder with today's code and requires that what was learned still
applies, that every change and its evidence are readable, that no task moved
to another split, and that a night carries on from there and can still take a
change back to the exact earlier value. A release that changes a kernel schema
adds a new folder (`python -m tests.unit.rsi.upgrade_fixture v2`); an old one
is never regenerated.

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
| Tasks from past coding work (`brief`, `coding`), read from CLI records and merged pull requests | built; stored with `--store`, not yet run |
| The brief domain's check: does a brief point at where the work turned out to be | built; nothing writes the brief for a task yet |
| The paired test whose bounds stay valid at every look (`dodaios/rsi/sequential.py`) | built |
| `bench.db`, the seed suite, the recall domain, runs under overlays | built |
| The measured gate: rules, error budget, decisions on candidates and on changes in effect | built |
| The tuner, the night cycle, automatic rollback, the sandbox | built |
| Recall tasks from the person's own memory and messages, made at night | built |
| The page that shows it | next |
| Always-on recording of work, the other domains, lessons, the jury | later |
