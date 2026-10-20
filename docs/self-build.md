# Self-building loop

Dodaios notices what the person keeps doing and builds what would take that
work off them: a memory, a skill, a routine, a specialised agent or a code
change in one of their projects. It does this without being asked, keeps
only what proves useful, and lets the person see and undo everything.

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
- **Build** goes through the existing creation paths (proposals, the skill
  creator, routines, the roster, coding threads), never a new back door. No
  agent gets a tool that creates agents.
- **Prove**: a judge the builder cannot edit checks the build before it counts
  (replay of the turns that triggered it, shadow runs, tests and CI).
- **Trial**: the build is live, labelled "built by Dodaios" and undoable with
  one click.
- **Keep or archive** is decided from use, corrections and cost. Archived
  builds are restorable, never deleted.

## The ledger: `dodaios/self_build/`

Every build has one row in `self_build.db` (in the data directory). Each stage
writes there and nowhere else.

| Module | Holds |
|---|---|
| `records.py` | `Kind`, `State`, `Outcome`, `BuildRecord`, the allowed state moves |
| `ledger.py` | `BuildLedger`: `open_case`, `set_state`, `attach_proof`, `attach_artefact`, `record_use`, reads, rejections, meta |
| `policy.py` | `admit` (may a build open, and how far may it go), `trial_over`, `settle`, the kill switch, the silent first days |
| `undo.py` | `UndoRegistry`: one undoer per kind |
| `cost.py` | `attributed(build_id)` tags model calls; `spent(record)` sums them from the cost ledger |
| `service.py` | `SelfBuild`, started at boot; `current()` returns it; `register_builder(kind, fn)` |

States:

```
proposed → building → proving → trial → kept | archived | undone
    │          └──────────┴─────────┴──> failed
    └─> rejected
```

`kept` and `archived` can still be undone; `archived` can be kept again.

### How a builder plugs in

1. Register an undoer for the kind: `service.undo.register(Kind.SKILL, fn)`. A
   kind without an undoer is never built, only proposed.
2. Register a builder: `service.register_builder(Kind.SKILL, fn)`. It is
   called with the record when a proposal is accepted.
3. To open a build, call `service.admit(kind, signature)`. `start` is `None`
   (do not open), `PROPOSED` (open as a card) or `BUILDING` (build now).
4. Open it with `ledger.open_case(kind, signature, title, case=..., evidence=...,
   state=admission.start)`. `title` is one sentence the person reads.
5. Run every model call inside `cost.attributed(record.id)`.
6. Record what you created with `attach_artefact(id, artefact, undo)`, the
   judge's verdict with `attach_proof`, then move the record to `trial` or
   `failed`.
7. Report each use with `record_use(id, Outcome.ACCEPTED | CORRECTED | USED |
   IGNORED)`.

A `signature` is a stable key for the need (for example
`routine:weekly-sales-report`). Only one build per signature can be open at a
time, and a signature the person rejected or undid `max_rejections` times is
not offered again.

## The loop for memories, skills, routines and agents

`dodaios/self_build/app.py` installs it at boot (`install_in_app`): one builder
and one undoer for each of the four kinds, and the event subscriptions below.

| Module | Holds |
|---|---|
| `miner.py` | counts the person's requests into needs; the thresholds |
| `signals.py` | `self_build_signals.db`: turns, clusters, verdicts, lessons, specs, artefact index |
| `decide.py` | the one decide call: prompt, parse, the no-model fallback |
| `brain.py` | model access: signed-in subscriptions and local models only |
| `judge.py` | the proofs, pure Python |
| `sandbox.py` | runs a drafted skill's steps read-only on a past request (subscription or local seat, side-effect tools held back) |
| `builders.py` | build, undo, archive (dormant) and restore per kind |
| `loop.py` | event intake, the gate, the decide queue, use counting, maintenance |

**Observe.** Inputs are finished voice turns (`VoiceTurnCompleted`), the
person's own typed turns in the Jarvis chat and agent chats (the chat
surfaces' completion hook; turns an agent or routine started are dropped), and
the prompts the person types to coding agents in the IDE (channel `pane`).
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
prompt is filed once; the maintenance pass catches a missed notice. While the
loop is paused or off the read position still moves, so nothing typed then is
filed later. Prompts typed straight into a terminal (not through the app) are
not in the history and are not counted.

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
archived, the person rejected or undid one in the last 30 days, a decide
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
stretch, and it is decided at the latest 20 minutes after it was queued. Without a signed-in subscription or a local
model the loop writes a plain card from the counts and builds nothing until a
model can write the spec. Calls are tagged `self_build:decide` in the cost
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

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | master switch |
| `silent_days` | `7` | the first days after the loop first ran only record cases |
| `memory`, `skill`, `routine`, `agent`, `code` | `trial`, `suggest`, `suggest`, `suggest`, `suggest` | autonomy per kind: `off`, `suggest`, `trial`, `full` |
| `trial_days`, `trial_uses` | `14`, `10` | a trial ends at whichever comes first |
| `max_builds_per_day` | `3` | builds past the proposal stage per day |
| `max_agents_per_week` | `1` | |
| `max_open_trials` | `5` | |
| `max_code_runs_per_day` | `1` | |
| `max_rejections` | `2` | |
| `code_land_repos` | `[]` | repositories (`owner/name`) whose loop pull requests are merged after green CI ([code builds](self-build-code.md)) |

At `suggest` a card asks first. At `trial` the build goes live on trial; an
unused trial is archived on its own, a used one waits for the person's keep.
At `full` a used trial is kept on its own too.

## REST: `/api/self-build`

`GET ""` (builds and status), `GET /digest?hours=24`, `POST /pause`
(`{"paused": true}` is the kill switch), `GET /{id}` (record, history, cost),
`POST /{id}/accept`, `POST /{id}/keep`, `POST /{id}/undo`. Every change
publishes `SelfBuildChanged` on the app bus, and the WebSocket forwards it.

`GET /settings` and `PUT /settings` read and change `[self_build]`. The PUT is
validated against `SelfBuildConfig`, written to `jarvis.toml` through
`config_writer.set_self_build_settings` and applied at once: the loop reads
the config through a getter. `GET /provenance?type=skill` lists the artefacts
builds created, keyed `"<type>:<id>"`, for the "built by Dodaios" badge.

The settings, the pause and accepting or keeping a build are excluded from the
brain's app actions, and `self_build.*` is on the self-mod deny list: only the
person decides how far the loop goes (rule 3). Reading the ledger and undoing
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

- **Built for you** (sidebar, under Agents; section id `self-build`) lists
  every build on the shelf of what it asks of the person: waiting for a yes,
  on trial, being built, kept, archived and undone. A row shows the build's
  one sentence, its kind, how often the need was seen and a small lifecycle
  rail; proposals and trials carry their actions inline. A build opens into
  its case file: why, what it noticed, how it was checked, what it made, use,
  cost and every state change. Undo is one click with no confirmation.
- The **digest** is one line at the top: what was built, proposed, kept,
  archived or undone in the last 24 hours, and how much is live. The nav row
  shows how many proposals wait. Nothing is announced: no toast, no sound, no
  voice.
- **Pause building** is the loop's kill switch. **Stop all agents** engages
  the society kill switch after a confirmation (which pauses building too);
  while it is engaged the page says so and offers Release.
- **Settings → General → Self-building** edits `[self_build]`, including the
  repositories whose loop pull requests merge on green CI (`code_land_repos`),
  shown with a warning that a listed repository changes without a review.
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
