# Self-building loop

Dodaios notices what the person keeps doing and builds what would take that
work off them: a memory, a skill, a routine, a specialised agent or a code
change in one of their projects. It does this without being asked, keeps
only what proves useful, and lets the person see and undo everything.

It never asks for approval either. There is no switch for it and no "waiting
for your OK" card: a build goes live on trial when it can be undone, and a
finished trial is kept or archived from the person's own use, never from a
click. What the person has is the pause (the loop's kill switch) and undo.

```
 observe ──> decide ──> build ──> prove ──> trial ──> keep / archive
 (free)     (1 call)  (sandbox) (judge)   (live,     (measured)
                                           undoable)
```

- **Observe** counts repetition in the person's own actions. No model is asked
  and untrusted content (web pages, tool results, other agents) is never
  evidence.
- **Decide** picks the smallest artefact that meets the need, in this order:
  memory, skill, routine, agent, code. "Build nothing" is a valid answer.
- **Build** goes through the existing creation paths (the learning notebook,
  the skill creator, routines, the roster, coding threads), never a new back
  door. No agent gets a tool that creates agents.
- **Prove**: a judge the builder cannot edit checks the build before it counts
  (replay of the turns that triggered it, shadow runs, tests and CI).
- **Trial**: the build is live, labelled "built by Dodaios" and undoable with
  one click.
- **Keep or archive** is decided from use and corrections, never by a click.
  Archived builds are never deleted.

## The ledger: `dodaios/self_build/`

Every build has one row in `self_build.db` (in the data directory). Each stage
writes there and nowhere else.

| Module | Holds |
|---|---|
| `records.py` | `Kind`, `State`, `Outcome`, `BuildRecord`, the allowed state moves |
| `ledger.py` | `BuildLedger`: `open_case`, `set_state`, `attach_proof`, `attach_artefact`, `record_use`, reads, rejections, meta |
| `policy.py` | the fixed `autonomy` per kind, `admit` (may a build open now), `trial_over`, `settle`, the kill switch, the silent first days |
| `undo.py` | `UndoRegistry`: one undoer per kind |
| `cost.py` | `attributed(build_id)` tags model calls; `spent(record)` sums them from the cost ledger |
| `service.py` | `SelfBuild`, started at boot; `current()` returns it; `register_builder(kind, fn)`; the trial sweep |

States:

```
building → proving → trial → kept | archived | undone
    └──────────┴─────────┴──> failed
```

`kept` builds and `archived` builds that made something can still be undone.
`proposed` and `rejected` exist only in ledgers an older version wrote, when a
card asked the person first. When the service starts, every record still in
`proposed` moves to `archived` with the note "archived: no longer asked"; the
record stays. Such an archived proposal never went on trial, so it neither
blocks its need nor counts against a cap: the loop may build that need on its
own later.

### How a builder plugs in

1. Register an undoer for the kind: `service.undo.register(Kind.SKILL, fn)`. A
   kind without an undoer is never built.
2. Register a builder: `service.register_builder(Kind.SKILL, fn)`. The status
   lists the kind; the loop that admits a build hands it to its builder.
3. To open a build, call `service.admit(kind, signature)`. `start` is
   `BUILDING` (build now) or `None` (not now: `reason` says why, and the need
   comes back on a later pass). It is never a card that waits for the person.
4. Open it with `ledger.open_case(kind, signature, title, case=...,
   evidence=...)`; it starts in `building`. `title` is one sentence the person
   reads.
5. Run every model call inside `cost.attributed(record.id)`.
6. Record what you created with `attach_artefact(id, artefact, undo)`, the
   judge's verdict with `attach_proof`, then move the record to `trial` or
   `failed`.
7. Report each use with `record_use(id, Outcome.ACCEPTED | CORRECTED | USED |
   IGNORED)`.

A `signature` is a stable key for the need (for example
`routine:weekly-sales-report`). Only one build per signature can be open at a
time, and a signature whose builds the person undid `max_rejections` times is
not built again.

## The loop for memories, skills, routines and agents

`dodaios/self_build/app.py` installs it at boot (`install_in_app`): one builder
and one undoer for each of the four kinds, and the event subscriptions below.

| Module | Holds |
|---|---|
| `miner.py` | counts the person's requests into needs; the thresholds |
| `signals.py` | `self_build_signals.db`: turns, clusters, verdicts, lessons, specs, artefact index |
| `decide.py` | the one decide call: prompt, parse |
| `brain.py` | model access: signed-in subscriptions and local models only |
| `judge.py` | the proofs, pure Python |
| `sandbox.py` | runs a drafted skill's steps read-only on a past request (subscription or local seat, side-effect tools held back) |
| `builders.py` | build, undo, archive (dormant) and restore per kind |
| `loop.py` | event intake, the gate, the decide queue, use counting, maintenance |

**Observe.** Inputs are finished voice turns (`VoiceTurnCompleted`), the
person's own typed turns in the Dodaios chat, agent chats, the IDE's side chat
(channel `side`) and the IDE's agent chat (channel `pane`) (the chat surfaces'
completion hook; turns an agent or routine started are dropped), and the
prompts the person gives coding agents in the IDE (channel `pane`).
Only the person's words are stored; tool names are kept as context, and the
assistant's answer is read once for memory use (below), never stored.
Requests are grouped by six-letter stems of their content words (the skill
matcher's multilingual tokenizer). A need crosses its threshold when, within
28 days:

| Need | Threshold | Rungs |
|---|---|---|
| repeated request | 3 times on 3 days, a tool used in half of them | skill |
| weekly habit | same weekday in 3 weeks, within 3 hours | skill, routine |
| daily habit | 4 days within 14, within 2 hours | skill, routine |
| repeated correction | 2 corrections on 2 days within 14 | memory |
| recurring failure | 3 failed answers on 2 days | memory, skill |
| sequence | B follows A within 15 minutes, on 3 days | skill |
| domain | 3 needs (each twice) on one tool family, 10 requests over 14 days | agent |

A prompt typed to a coding agent counts as work done with a tool (the coding
agent is one), so a pane prompt repeated on three days is a repeated request.
A pane prompt is never a correction of the assistant.

**Pane prompts.** The IDE writes every prompt a pane receives to its prompt
history (`agentic_ide/prompt_history.py`, one append-only JSONL file per
pane). A row carries `origin: "person"` only when the person sent it from the
app's window: the prompt bar, a pane's chat or the launcher, recognised by the
desktop session cookie or the browser's `Sec-Fetch-Site: same-origin` without
a control key (`control_auth.person_at_window`). Briefs the brain or an agent
sent to a pane carry no origin and are never evidence; the person's spoken
request behind a brief is already counted as a voice turn. From a row the loop
files `typed` (the person's sentence) when the prompt was a brief written
around it, else the prompt itself; a row whose text is only dropped files'
contents is skipped. The route tells the loop when such a prompt was stored,
and each pass reads a history file from where the last one stopped, so a
prompt is filed once. Only rows the running app announced this way count: the
maintenance pass and the start only move the read position past the others,
because a row no notice announced was written by another process (a test run,
another instance) and is not the person's. While the
loop is paused or off the read position still moves, so nothing typed then is
filed later.

**Prompts typed into a pane.** Most work in the IDE is typed or dictated
straight into a pane's terminal, which the prompt history does not see. A
Claude pane reports each prompt its CLI accepts through a `UserPromptSubmit`
hook (`agentic_ide/claude_session_hook.py`, next to the session hook; it
prints nothing, because that hook's output would join the prompt) into
`<pane>.prompts.jsonl` in the panes' state folder. Such a prompt is the
person's only when they pressed Enter in that pane's own window before it
(within 30 minutes: a prompt typed while the agent works is reported when its
turn starts); each Enter confirms one prompt. A prompt that matches one the
IDE itself sent to the pane (its prompt history) is skipped, as are slash
commands, shell lines, machine-made messages and steering with fewer than
three content words ("continue"). Other coding CLIs have no such hook; their
directly typed prompts are not counted.

Read offsets are kept per file; offsets of files that are gone or untouched
for longer than the 28-day window are pruned in the maintenance pass, and
files that old get none. The prompt history and the panes' state folder are
per instance, so a dev instance never feeds the main app's loop, and the test
suite redirects both.

**Agent chats.** A request typed to a society agent is filed like any other
turn and also counts as a use of a self-built agent. Whose need it is follows
one rule: a need whose turns all come from one agent's chat belongs to that
agent's own learning (`society/learning.py`, which writes the agent a skill
after a turn with a real procedure) and the loop leaves it alone; a need that
spans several agents, or an agent and the assistant, is the loop's, unless
one of those agents already has a skill, active or draft, that serves it (its
requests replayed through the router as if the skill were active, or its name,
description and "when to use" covering the need's core words). Then neither a
global skill nor another agent is built, and the verdict is recorded as
"served". Turns in agent chats do not count towards a domain: that work
already has an agent.

Habits are counted on the person's wall clock: the time zone their UI
reported, or, until it has reported one, this computer's own zone (read as an
IANA name and checked against the offsets the operating system reports; the
log says once that the fallback is in use). A self-built routine is scheduled
in the same zone.

**Gate, no model.** A need is dropped when a build for it is open, kept or
archived after its trial, the person undid one in the last 30 days, a decide
verdict said "nothing" in the last 30 days (unless the need has doubled since),
earlier builds failed their proof twice, an installed skill already catches
its requests, or `admit` refuses every candidate kind.

**Decide.** After 90 seconds of quiet (or when a call ends), at most one model
call per need and four per day. Quiet means the person is not in the middle
of talking to Dodaios: no turn of theirs (voice, chat, agent chat, a prompt
typed to a pane through the app), no typing into a pane's terminal in the app
and no open call for those 90 seconds (`core/presence.py`). The operating
system's input idle time is not asked: a person working in other programs
moves the mouse every second, and the decide call is light. While the person
talks to Dodaios the need waits and is looked at again after the next quiet
stretch, and it is decided at the latest 20 minutes after it was queued. Without a
signed-in subscription or a local model nothing is decided and nothing is put
to the person; the need comes back once a model can write the spec. Calls are
tagged `self_build:decide` in the cost
ledger; build calls `self_build:<id>`.

**Build and prove.**

| Kind | Built through | Proof | Archived means |
|---|---|---|---|
| memory | the learning notebook (`MEMORY.md`/`USER.md`) | the learning review's evidence check | entry removed, text kept |
| skill | the skill creator's writer, then the registry's `promote` ([ADR-0043](adr/0043-self-built-skills-go-live-on-trial.md)) | replay through the skill router, lint, duplicates, tools; then its steps run read-only on one or two accepted requests (`sandbox.py`) | switched off |
| routine | a lead-owned Automations task on a subscription or local seat, no plugin grants, no announcement | schedule before 2/3 of the requests, grounded prompt, nothing outbound, a shadow run | paused |
| agent | `Roster.create` on a subscription or local seat | free name, clean instructions, focus from used tools, shadow answers | paused |

Every artefact carries the shared join key `id` next to its own fields: the skill name, the routine's task id, the agent id, or the memory notebook's path in the vault (with `entry_id`).

**Measure.** A skill run counts as a use, a correction within two minutes as
corrected. A routine run counts, a manual request within a day after a run as
corrected, a failed run as ignored. A turn in a self-built agent's chat
counts. A memory counts when it was in the prompt and the turn relied on it,
at most once per conversation: its entry text is in the notebook snapshot the
assistant's prompts carry (an archived or edited entry is not), and the
person's words name the entry's subject (two of its words), or the request
is about it (its need, or one of its words) and the answer carries a word only
the entry could have given (`judge.memory_relied`, no model). A correction in
a turn about the entry, or the next turn after one that relied on it, counts
as corrected. Pane and agent-chat turns never count: those agents do not read
the assistant's notebook. Kept builds unused for 30 days are archived.

**Idle cost.** One SQLite insert and a scan of four weeks of clusters per
turn; no model call and no timer unless a need is waiting to be decided.

## Settings: `[self_build]`

The section holds the loop's limits, nothing that decides whether it asks:

| Key | Default | Meaning |
|---|---|---|
| `silent_days` | `7` | the first days after the loop first ran: needs are counted, nothing is built |
| `trial_days`, `trial_uses` | `14`, `10` | a trial ends at whichever comes first |
| `max_builds_per_day` | `3` | builds opened per day |
| `max_agents_per_week` | `1` | |
| `max_open_trials` | `5` | |
| `max_code_runs_per_day` | `1` | |
| `max_rejections` | `2` | a need whose builds the person undid this often is not built again |
| `code_land_repos` | `[]` | repositories (`owner/name`) whose loop pull requests are merged after green CI ([code builds](self-build-code.md)) |

`enabled` and the per-kind stages (`memory`, `skill`, `routine`, `agent`,
`code`) are no longer read. A config file that still sets them loads; their
values are ignored. How far each kind goes is fixed in `policy.autonomy`:

| Kind | Autonomy | Means |
|---|---|---|
| memory, skill, routine, agent | `full` | built, proven and live on trial with one-click undo; the trial ends by measure |
| code | `watch` | nothing new: no issue is taken in and nothing is built until code changes have a measured path of their own; the pull requests the loop already opened are still watched until they settle ([code builds](self-build-code.md)) |

Any "not now" (paused, the silent first days, a cap, no undo for the kind)
opens nothing; the need comes back on a later pass. A build goes live on trial
as soon as it is proven. When the trial ends, the hourly sweep keeps it if it
was used at least twice and accepted more often than corrected, and archives
it otherwise, for every kind. No click keeps it; the person can undo it at
any time.

## REST: `/api/self-build`

`GET ""` (builds and status), `GET /digest?hours=24`, `POST /pause`
(`{"paused": true}` is the kill switch), `GET /{id}` (record, history, cost),
`POST /{id}/undo`. There is no route that accepts or keeps a build. Every
change publishes `SelfBuildChanged` on the app bus, and the WebSocket forwards
it. The status carries `paused`, `silent`, `autonomy` (the fixed level per
kind: `full` or `watch`), `builders` and `code` (the code pass's last run).

`GET /settings` and `PUT /settings` read and change the limits in
`[self_build]` (the keys in the table above, no `levels`). The PUT is
validated against `SelfBuildConfig`, written to `jarvis.toml` through
`config_writer.set_self_build_settings` and applied at once: the loop reads
the config through a getter. A body that names `enabled` or a stage is
refused (422), and the writer refuses those keys too. `GET /provenance?type=skill` lists the artefacts
builds created, keyed `"<type>:<id>"`, for the "built by Dodaios" badge.

The settings and the pause are excluded from the brain's app actions, and
`self_build.*` is on the self-mod deny list: only the person sets the loop's
limits and pauses it (rule 3). Reading the ledger and undoing
a build stay reachable, so "what did you build?" works when asked.

The society kill switch (`POST /api/society/kill-switch`) also pauses the
loop. Releasing it does not resume the loop; the person resumes it in "Built
for you".

### Artefact ids

The badge joins on the artefact a builder records with `attach_artefact`. Use
these ids so the badge finds its build:

| `type` | `id` |
|---|---|
| `skill` | the skill's `name` as `/api/skills` lists it |
| `routine` | the routine's task id (`/api/society/agents/{id}/routines`) |
| `agent` | the society `agent_id` |
| `memory` | the wiki or memory path |
| `code` | the pull request URL |

Extra keys (`label`, `url`, `repo`) are allowed and shown in the build's
detail.

## In the app

- **Built for you** (sidebar, under Agents; section id `self-build`) is one
  reading column. At the top, one sentence says what the page is. A slim line
  shows its state when there is something to say: the quiet first days with
  their progress (and the date helpers may start), paused or stopped, each with
  the one button that undoes that state. There is no "off".
- Then, in the order a person asks about it: **Active** (trials with day and
  use progress, builds in progress, kept helpers), **Noticed**, and
  **Archived** (folded; undone and failed builds and archived old proposals sit
  there too). Nothing on the page asks for an OK: there is no "Waiting for your
  OK" list and no Build it, Keep or Restore button. "How does this work?"
  explains the three steps behind one toggle. A build opens as a sheet on the
  right with its case file: why, what it noticed, how it was checked, what it
  made, use, cost and every state change. Undo is one click with no
  confirmation, offered while there is something to take back.
- **Noticed so far** comes from `GET /api/self-build/noticed` (read-only): each
  request the person made more than once in the miner's window, labelled with
  their own latest wording (cut to 90 characters), how often and on how many
  days, pips toward the repeat threshold, and where it stands (counting, ready,
  answered directly, undone by the person, already served, nothing to build).
  Requests made once are only counted. Needs that became a build (in progress,
  on trial or kept) are left out.
  The response also carries when the quiet start ends.
- `GET /digest` counts what was built, kept, archived or undone in the last
  24 hours. Nothing is announced: no toast, no sound, no voice, no count on the
  nav row.
- **Pause building** is the loop's kill switch. **Stop all agents** sits in
  the page footer and engages the society kill switch after a confirmation
  (which pauses building too); while it is engaged the top says so and offers
  Release.
- **Settings → General → Self-building** edits the limits in `[self_build]`,
  including the repositories whose loop pull requests merge on green CI
  (`code_land_repos`), shown with a warning that a listed repository changes
  without a review. It has no master switch and no stage per kind.
- A **"Built by {assistant}"** badge marks skills (Skills list and detail),
  routines (an agent's routines) and agents (the agent card) that a build
  created, and opens that build.
- Live: the WebSocket forwards `SelfBuildChanged` and the page re-reads the
  ledger.

## Rules enforced in code

1. Background work for the loop never bills a per-token key. It runs on
   subscriptions or local models, or it waits.
2. Only the person's own actions are evidence.
3. The builder cannot edit the judge, the budgets, `[self_build]`, the kill
   switch, `security.*`, secrets or the self-mod allowlist.
4. No agent tool creates agents; only the trusted builder service does.
5. A build without an undo path is not created.
6. Hard caps per day and week (above).
7. Nothing leaves the machine on the loop's initiative: no messages, emails or
   posts, and no comments in other people's repos.
8. Dodaios never speaks about its builds unprompted.
9. Nothing asks the person to approve or keep a build: `admit` opens a build
   or nothing, and the sweep settles trials by measure. The person's controls
   are the pause and undo.
