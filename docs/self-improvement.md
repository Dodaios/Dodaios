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
| `brief` | the brief names what the merged change needed | a replay (two calls or more) |
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

The seed suite also holds 226 requests to the lead with the first move each
needs (`seed/first_move.json`): the routing eval's golden set
(`docs/lead-routing-evals.md`). The YAML files in `tests/fixtures/lead_routing/`
stay the one place a case is written; the packaged file is generated from them
(`python scripts/lead_routing_eval.py --write-seed`) and a test fails when the
two differ, because an installed app has no `tests/`. A request and its
translation share a group: 226 tasks in 168 groups, 106 practice, 53 select, 22
guard and 45 sealed.

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
quiet. A night makes at most eight such calls, however much there is to do; while
there are fewer than 30 of the person's own tasks in the select split (too few for
the gate to decide), at most 24, so the first decision comes in one or two nights.

Forgetting reaches the tasks: when a memory is forgotten or replaced, every
task that names it is retired and its text erased.

On the maintainer's installation one run of three calls gave 24 question
tasks from 12 memories and 6 message tasks from 8 messages, 5 of which need no
memory; the two askings disagreed on the other 2, which were left out.

Five whole nights on a copy of the maintainer's memory and messages
(2026-11-24, 27 model calls, eight per night before the ramp-up above existed):
the nights built 197 tasks, 107 of them real messages that need no memory.
Nothing could be decided in the first two nights (15 and 28 select tasks). In
night 3 the tuner proposed `recall.min_score` 0 -> 4 and the gate let it in
(as good on 44 tasks and 33 % cheaper); night 4 checked it again on 26 new
guard tasks, kept it, and let in 4 -> 8 the same way. Night 5 turned down
`recall.entity_boost` 1.5 -> 1.9 (no gain, 14 % dearer). The learned advantage
on 36 sealed tasks went from 0 to +11.1 points (0.583 as shipped, 0.694 now),
and the memories a message brings into the prompt from 112 to 43 tokens on
average: the shipped settings bring up a weak match for many messages that need
none.

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

Every night does this intake first (`night._past_work`), before its records
are gone. The repositories are the ones the recorded sessions ran in, one per
repository however many worktrees it has (`intake.session_folders`). It calls
no model; a record or clone that cannot be read is logged and costs nothing
else of the night. The night's report says how many tasks it stored. Measured
on 2026-11-23 on the maintainer's machine: 154 sessions in 2 repositories, 261
tasks stored in 48 seconds the first night, 31 seconds on later nights with
nothing new. The `brief` tasks are measured by the brief replay (see "Replaying
a lead turn up to its brief"); no runner is registered for `coding` yet, so those
tasks are kept, not measured.

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
files apart, or, for Python, by its dotted module, also with the clone's own
folder in front. The check's own cost is the brief's length in tokens; a
replayed task costs the lead's message and the brief (see below).

Not scored yet: whether the brief already said what the person had to add
afterwards; that needs a judge. Applied to the opening words of the mined
sessions as they stand (2026-11-23): a typed request scores 0, as it should,
and the eight openings that were briefs themselves average 0.08. That is where
the briefs of the past stood on this measure. The brief the lead writes today
comes from a replay (next section).

### Replaying a lead turn up to its brief

A brief task gives the lead a request the person once typed into a coding
agent, and asks what brief the lead writes for it today
(`dodaios/rsi/bench/brief_replay.py`, `brief_world.py`).

**What the lead does first.** Before this runner was built, eleven real
replays on the lead's plan answered that (2026-11-24, the lead on Claude Code,
its recorded system prompt and the routing eval's tool list). With the app's
tools in reach the lead never wrote the brief at once: its first move was
`delegate` with `options.prepare` (the brief kit) in all three such replays,
as in the two recorded live turns that handed coding work over. In five more
replays the replay's tool server had failed to start (a setup fault of the
trial, since fixed: see below); without its tools the lead said the connection
to the app was gone and searched the repository with the CLI's own `Grep` and
`Read`. The last three replays ran the runner as it is now: each asked for the
kit, got it, and handed the work over (two model calls, 17 to 20 seconds; one
read three files first, five calls). Their briefs scored 0, 0 and 0.18.

**The task's form.** So a replay answers the calls by which the lead reads
the repository, and nothing else:

- the brief kit, once: built by the app's own code for the lead's own wording,
  from the repository as it was when the work started (`base`), and rendered
  as the app's tool server renders it. It writes nothing: the glossary's use
  counters stay as they are;
- the app's read-only folder tools (`Read`, `Grep`, `Glob`, `Ls`), run by the
  app's own code in that repository: a path in the person's clone is read at
  the same place there, a path outside the repository is not answered;
- at most four answered calls in all.

The first call that is not answered is the move. A hand-off (`delegate`) is
the brief; its task, context and done-when are scored. A text answer or a
question on the card is no brief: score 0, and it costs as much as a long
brief (2,000 tokens besides the message), so not handing over never looks
cheaper than handing over. Anything else (the shell, the person's memory, a
look outside the repository, the kit asked for again, a fifth look) is void
with what it was.

**The repository as it was.** For each repository a night makes one scratch
clone under `rsi/brief` in the data folder (`git clone --shared --no-checkout`
from the person's clone: it borrows the objects and never touches that clone,
its index, its branches or its worktrees) and moves it to each task's commit,
hooks and large-file downloads off. It is removed at the end of the night. A
task whose repository is not on this machine, whose commit is not in the
clone, or whose request showed a picture is void with the reason, before
anything is spent.

**What the lead is given.** The input of one recorded lead turn, pinned in
`bench.db` while that row exists and the lead stays on the same CLI and model:
its system prompt, and its message with the person's words replaced by the
request and one fixed line, *"(Have a coding agent do this, in the repository
<id>, local folder <folder>.)"*. The standing lines are applied as the run's
overlay says. Both arms of every comparison get the same template and the same
line. The pin keeps a result reusable and a comparison the budget cut short
comparable on the next night; the newest turn changes with every message.

What the fixed line costs in fidelity: the person typed the request into a
coding agent, so it never reached the lead. The line says what that choice
said, that a coding agent is to do it and where. Without it the lead read
"fix this" as addressed to itself and went through the code the way an agent
would (a real replay read six files and was still reading). With it the lead
may look into the code a little less than it would for a request typed to it
openly; both arms lose the same.

**The replay's safety.** A replay starts the CLI in its default permission
mode whatever the person set for their own sessions (on the maintainer's
machine that is "bypass", which would let the CLI run its own tools without
asking), and without the CLI's own writing tools (`Edit`, `Write`,
`MultiEdit`, `NotebookEdit`) or shell. A brief replay also goes without the
CLI's own reading tools: they would read the person's clone as it is today,
merged change included. Only a call of the app's own server is ever answered;
everything else stays refused and unrun. The replay's tool server runs the
replay's own code (`PYTHONPATH`), not an installed copy of the app.

**Cost and budget.** A task's cost is the lead's message and the brief, in
tokens: the line under test rides in every message, the brief is what the
agent then reads. A brief replay counts one call against the night's replay
limit, and one more for each call it answers (each makes the CLI ask the model
again). The limit is the one first_move uses: one `Budget` object serves both
worlds of a night (see "What a night's replays may spend"). A run the limit
cuts in the middle is void as cut by the budget, and the comparison carries on
the next night.

**What it cannot see.** Whether the brief said what the person had to add
afterwards; whether the brief check that may send a brief back once would
have done so (the first brief is scored); a look-up that is not a folder tool
(the shell, the person's memory, the web); the conversation before the turn;
and everything after the hand-off: what the agent then did with the brief.

### How the first_move domain scores

The lead's first move decides the rest of its turn: answer in text, ask on the
question card, hand work to an agent, look something up. A first_move task is
one request and what that first move should be (`dodaios/rsi/bench/first_move.py`):

- the first tool call that is right, with the arguments it must carry, or no
  tool when the right move is to answer in text. The rules that match a move
  against this are the routing eval's; the eval reads them from the kernel, so
  the two cannot disagree;
- a short line of text before the first tool call, where a tool is right. The
  reply style asks for it, and `FIRST_LINE` asks for it beside every message.

A right move scores 1, a right move without the line before the tool 0.5, a
wrong one 0. The cost of a task is the message the lead got, in tokens: the
lines beside every message are part of it and stay in the conversation, while
the system prompt is the same on both sides of a comparison.

What it cannot see: anything after the first move (what the tool did, the
reply's shape and length, a brief's wording), and what the line before the
tool says (only that it came).

### Tasks from your own lead turns

A recorded lead turn (see "Lead turns on record") says what the lead was given
and what it did first. Whether that was right, only what the person did next
can say (`follow_up_kind` in `dodaios/evals/agent_score/signals.py`):

- **Corrected, then accepted.** The person's next message corrected the turn or
  asked again (within 30 minutes), the turn after that went through (it ended
  done and nothing corrected, repeated or undid it), and its first move differs.
  That later move is the truth for the earlier turn's input. Only these tasks
  can show a gain.
- **Accepted.** A turn that went through and was not corrected, repeated or
  undone. Its first move is what the person let stand: such a task can show that
  a change breaks something that worked, never that a change is better.

A corrected turn and the turn that got it right share a group, so they land in
the same split. Left out: a turn that carried a running task on, one still
too new to know, and one whose record does not say which tool it called (an
older row that kept the schema load `ToolSearch` instead of the call after it).
A task holds no words of the person's, only the row it replays and the tool of
the right move; when the row is gone (the chat was deleted, the row aged out),
the task is retired. Every night takes these in first (`bench/own/lead.py`). No
model is called for it.

### Replaying a lead turn

The runner (`dodaios/rsi/bench/lead_replay.py`, `lead_cli.py`) gives the lead's
CLI what a turn gave it, with the change under test applied:

- a task from the person's turns: the recorded system prompt and message, with
  the standing lines switched as the run's overlay says (`dodaios/rsi/lines.py`);
- a seed task: its request as the lead's message (`lead_message`, built under
  the run's overlay) on top of the lead's current system prompt.

The CLI starts with the lead's own flags (only the app's tool server; the
vendor's web, sub-agent and shell tools removed), the lead's model and effort,
one empty working folder for every replay and no session kept on disk. The app's tool server is
replaced by `replay_tools.py`, which lists exactly the tools the lead's chat is
offered and answers every call with "not run". Every permission prompt is
denied. The stream is read with the live chat's own parser; at the first tool
call (a schema load is not one) or the end of a text answer, the CLI and what
it started are stopped.

What answers is fixed for a night: CLI and its version, model, effort and tool
list. It is part of the result's fingerprint, with the switches the domain
reads and nothing else that is learned, so an unchanged arm is never paid for
twice: a counted result of the same task content under the same arm, from the
last 14 days, is reused. The model the CLI says it ran is checked on every
call; a run on another model does not count, and two results that name
different models are no pair.

What a replay cannot see: the CLI's own conversation on a resumed turn (the
record names it, it is not part of the input), so a replay starts a fresh
conversation with the recorded system prompt and message. Only Claude Code has a
replay today; the domain's tasks wait on another lead CLI.

### What a night's replays may spend

Fixed in `dodaios/rsi/budget.py` and asked before every call:

- only on the lead's plan: Claude Code signed in, no API key in its
  environment (it would bill that key per token), not cooling down after a
  limit. Without that, no replay is built and the tasks wait;
- only while the person is away; a call is not started once they are back;
- at most **40 replay calls a night**, for first_move and brief together (one
  `Budget` object serves both; a brief replay takes one call and one more for
  each call it answers). A lead call carries the lead's system prompt,
  about 50 000 characters (some 12 500 tokens), plus the CLI's own prompt and
  the tool list; 40 calls are roughly half a million input tokens, most of them
  read from the provider's cache because the system prompt repeats. That is
  about one long working session of the person's, and it finishes one
  comparison of a candidate on 30 tasks (60 calls) in two nights;
- the plan's usage windows (`agent_usage`, read at most once a minute): no
  call while any window is 80 % full, and no more than 20 % of a window spent
  in one night (`night.BUDGET_SHARE`). When they cannot be read, the cap
  alone applies.

A comparison the budget cuts short is not decided "no clear difference": its
results are kept, the next night measures the rest, and the error budget is
spent only when it is decided. A verdict that is already clear on the tasks
measured so far stands, because the interval holds at every look. The learned
advantage is measured only when something learned changes what a replay
gets; while nothing does, both sides are the same assistant and nothing is
spent.

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

## Lead turns on record

To measure a change to the lead (the assistant's own chat), a benchmark
replays a past turn: it gives the model exactly what it was given then, with
one thing changed, and compares the model's first move. A replay needs a
record of the original turn, and such records take months to collect. So the
app records the lead's turns from now on. The replay is the first_move domain's
runner (see "Replaying a lead turn").

**What the lead is given** comes from one function,
`runner_cli.lead_model_input`. It returns what the coding CLI gets for a lead
turn: the system prompt text as passed, the message text, the model, the
effort and the CLI. The message is the person's text with the lines that go
beside it (`dodaios_harness.lead_message`), the effort note in front, and, on a
resumed conversation, the catch-up block. Claude Code gets the identity as a
system-prompt file; the other CLIs get it inside the message, and every planner
takes that step from the same helper. A test pins the bytes of the message for
a set of inputs, so a change to what the lead is given is always a visible
change. The CLI's own system prompt and, on a resumed turn, the CLI's own
conversation are not part of it: a row names the conversation it continued.

**What is kept**, one row per lead turn, in `lead_turns.db` in the data
directory (`dodaios/rsi/lead_turns.py`, a kernel file with a schema version):

- the time, the chat session and turn ids, the CLI, the model and the effort;
- a hash of the tool list the chat was offered (names, descriptions, schemas);
- the system prompt text and the message text, exactly as passed, compressed;
- the conversation a resumed turn continued, whether the turn carried a running
  task on, and how many pictures went with the message (not the pictures);
- the first move: the first tool call's name and arguments, and whether a line
  of text came before it; or that the model answered in text only. A schema
  load (`ToolSearch`, which Claude Code needs before a deferred tool) is not the
  move; the call after it is.

Only lead turns are kept: the `jarvis` surface, not a slash command, not a
coding thread and not an agent's own chat. A turn that ended before the model
did anything is not kept. A row is never changed after it is written.

**For how long.** A row is kept for at most 90 days, and the file keeps at most
200 MB of stored text; when it is full, the oldest rows go first. A lead turn
takes about 25 KB, so this holds about 8,000 turns. Both limits are checked
each time a row is written and when the app first opens the file. Deleted text
is overwritten on disk, not left in free space.

**Deleting.** When the person deletes a chat session, its rows are deleted too
(`AgentChatStore.delete_session` calls `lead_turns.forget_session`). Forgetting
a memory does not delete rows: a row holds the whole system prompt the lead
was given, not a list of the memories in it, and the memory's text can appear
there shortened or reworded. A row that holds a forgotten memory therefore
stays until its 90 days are over.

**Nothing leaves the machine.** The file is read only by the benchmark on this
computer. Nothing sends it, uploads it or adds it to a report.

**It never slows or breaks a turn.** The turn only notes what it saw. The row
is written by a background task, off the event loop, as soon as the first move
is known (the first tool call, or the end of a turn that answered in text).
Any failure is logged once and the row is skipped.

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

## How coding agents are steered

How Dodaios steers the coding runs it hands out is a coding policy per cell
(the area of the work, the model, the coding CLI and its version line). The
trainer changes it one measured step at a time, on the person's real requests
rather than on benchmark tasks (`docs/rsi-policy-selector.md`). A candidate
runs on half of the requests in its cell, the other half stays as it is, and
the selector's gate decides on the judged runs.

- **Holding.** A cell starts without holding: the lead's job ends with the
  agent's turn and nothing is sent back to the agent. Waiting for the checks
  and ordering fixes is the first thing tried there. It has to make clearly
  more runs pass (at least 10 points, within 125 % of the cost), or the cell
  stays as it was.
- **Steering.** In a cell that holds, fewer fix orders or a shorter wait for
  checks are tried, and kept only when they cost less and nothing else gets
  worse.
- **A line for the first brief.** When the same fix order keeps coming, one
  fixed sentence from the code goes into the first brief on trial.

Nothing waits for the person. Every policy the trainer put in place is in the
list of what the assistant changed in itself, with one plain sentence ("Waits
for the checks and asks for fixes, for <model> in <harness>"), the measurement
that let it in (pass rate of each half and the lower bound of the difference)
and Take back, which restores the exact policy from before. A candidate on
trial is listed among the candidates. The first run under a new policy that
weakened a check rolls the policy back by itself.

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

Where a domain has tasks whose truth the person only accepted (first_move's
accepted turns), rule 3 rests on the other tasks alone, the ones whose right
answer is known: a candidate is "better" only there. Rules 1, 2 and 4 rest on
all tasks of the split, and the accepted ones alone must not get clearly worse.
"As good" needs many tasks: on 53 tasks a difference of exactly zero is bounded
only to about 10 points either way, and rule 4 needs 5, which takes about 120.

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
4. It measures the learned advantage on the sealed tasks, also split into the
   parts of the area (`run.parts`; for recall: tasks where a memory is needed
   and tasks where none is), so the page can show where a difference lies. The
   parts are plain means; every decision rests on the whole.
5. It writes down what it did (`nights` and `series` in `bench.db`; schema step
   3 added the `parts` column, older points read as having none).

Before all of this a night copies the memory and builds new tasks from the
person's own memory and messages (see above), and erases tasks about memories
that are gone.

Nothing is announced: no notice, no sound, no voice. The app looks every ten
minutes whether a night is due: the person must have been away for 15 minutes,
and there is at most one night in 20 hours. Measuring the recall asks no
model; building tasks does, at most eight small calls a night (24 while too few
tasks exist to decide on). Measuring the first move and the briefs replays lead
turns, at most 40 calls a night for both together (see "What a night's replays
may spend"). The limits are fixed in the code, not in a setting: only while the person is away, on the
assistant's subscription or a local model, never a key that bills per token,
and no more than 20 % of a plan's usage window in one night. The person's stop
(`Night.pause`) is kept in `bench.db` and
survives a restart; while it is set nothing is proposed, measured or changed.

### The tuner

The first learner (`dodaios/learners/tuner.py`) needs no model. For every
parameter a domain measures it tries values 1, 2, 4 and 8 steps below and above
the value in effect, each alone, on the practice tasks, and proposes at most
one move per night: the one with the largest gain, or else the cheapest one
that scores no worse. It may be as greedy as it likes; the gate decides on
other tasks. It does not ask again for a value the gate turned down in the
last 30 days.

### The line learner

Every lead message carries standing lines (`dodaios_harness.message_lines`):
how much to think, the line before the first tool, the reply's shape, how to
brief an agent, where a question goes. Each costs tokens on every message and
stays in the conversation. The line learner (`dodaios/learners/lines.py`) tries
the message without one of them on at most 12 practice tasks and proposes the
drop that loses nothing there and is at least 5 % cheaper. The gate lets it in
only by its rules: as good and at least 5 % cheaper, or better.

It only ever offers a line the kernel lists as learnable (`dodaios/rsi/lines.py`):
one whose effect a benchmark sees, and only in the domain that sees it. Today
that is `FIRST_LINE`, switched by `lead.first_line` and measured by first_move,
and `BRIEF_LINE`, whose wording `lead.brief_line` picks and the brief domain
measures. `BRIEF_LINE` has three fixed wordings written in the code, never by a
model: as shipped (look the files up with the brief kit, then brief), the same
look-up asked for in fewer words, and no look-up asked for. They differ only in
the look-up, whose effect is the files a brief names and its length; the rest
of the line (the outcome first, a done the agent can check, the git default,
the real limits) is the same in all three, because no domain measures it. For
the same reason the line is never dropped whole. The learner tries each other
wording on the practice tasks and proposes the one that is clearly better, or
as good and at least 5 % cheaper. The reply's shape, how long the model works
and a question later in the turn are not seen by any domain, so a drop of
`REPLY_SHAPE_LINE`, `EFFORT_LINE` or `QUESTION_CARD_LINE` would pass a gate that
cannot see its harm; they have no switch. A dropped line is a self-change like every other: it shows in the list
of what the assistant changed in itself as one sentence, and one click puts it
back. While a first_move candidate waits for its measurement, nothing new is
proposed in that domain: every look costs calls.

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

The Self-improvement page (Workspace, after "Built for you";
`dodaios/ui/web/frontend/src/views/SelfImprovementView.tsx`) reads
`GET /api/self-improvement` (`dodaios/rsi/overview.py`; the shape is pinned in
`tests/unit/ui/web/test_self_improvement_routes.py`). Top to bottom:

- the state in words (running or stopped, the last night, when the next one
  may come) and one button: Stop, or Resume while stopped;
- per measured area the learned advantage in points, with the two scores and
  the prompt cost behind it. A difference whose range includes zero is called
  "not certain yet", whatever its sign;
- the advantage night by night with its range, a mark where the app version
  changed, and a table of the same numbers;
- what is in effect, each change with the measurement that let it in and the
  one that checked it again, and a one-click "Take back"; a change opens into a
  sheet with the stored reasons as they are;
- the last nights (three shown, the rest folded), then what waits to be
  measured and what rests after an update, when there is any.

Until the person's own tasks exist it measures nothing, and the page says so
in two sentences instead of drawing anything. The page words everything from
its own strings (`locales/self_improvement/`); the only backend text it shows
as it is are the stored reasons, in the sheet. It repaints on
`SelfChangeChanged` and polls every five minutes for a night's new point.
There is no other control on purpose: the person only stops or undoes
(`POST /api/self-improvement/pause`, `POST /api/self-improvement/changes/{id}/undo`).

## What exists today

| Part | State |
| --- | --- |
| Shared shapes: overlay, fingerprint, task, split, result, evidence | built |
| Kernel storage with a schema version | built |
| Kernel and evidence paths refused by the registry | built |
| Parameters with limits, read by the memory recall; learned values survive updates | built |
| A recall that can be replayed without leaving a trace (no use count, no cache) | built |
| Tasks from past coding work (`brief`, `coding`), read from CLI records and merged pull requests | stored every night; `brief` measured by its replay, `coding` not yet |
| The brief domain's check: does a brief point at where the work turned out to be | built; the brief comes from the replay below |
| The paired test whose bounds stay valid at every look (`dodaios/rsi/sequential.py`) | built |
| `bench.db`, the seed suite, the recall domain, runs under overlays | built |
| The measured gate: rules, error budget, decisions on candidates and on changes in effect | built |
| The tuner, the night cycle, automatic rollback, the sandbox | built |
| Recall tasks from the person's own memory and messages, made at night | built |
| The lead's model input as one function (`lead_model_input`), its message bytes pinned by a test | built |
| Lead turns on record (`lead_turns.db`): what the lead was given and its first move | built; replayed by the first_move domain |
| The page that shows it | built |
| Holding learned per cell of coding work: put on trial where a cell does not hold, kept only if more runs pass | built |
| A mined line for the first brief goes on trial by itself; nothing waits for the owner | built |
| Coding policy changes in `GET /api/self-improvement`, with the measurement that let them in | built |
| The first_move domain's check, shared with the routing eval; its 226 seed tasks packaged and pinned to the YAML | built |
| first_move tasks from the person's lead turns: corrected-then-accepted (can show a gain), accepted (guards) | built; taken in every night |
| The replay of a lead turn on Claude Code: tools offered, none run, stopped at the first move; results reused per arm | built; other lead CLIs wait |
| The budget of a night's replays: 40 calls, 20 % of a usage window, never above 80 %, only on the plan, only while away | built |
| The line learner, and `FIRST_LINE` as the one learnable standing line | built |
| The brief replay: a mined request in the pinned lead input, the kit and the folder look-ups answered from the repository at the task's commit, the hand-off scored | built |
| One night's 40 replay calls shared by first_move and brief | built |
| `BRIEF_LINE` learnable as one of three fixed wordings, measured by the brief domain | built |
| A replay asks in the default permission mode and has none of the CLI's own writing or shell tools | built |
| Whether a brief said what the person had to add afterwards (a judge) | later |
| Always-on recording of work, the other domains, lessons, the jury | later |
