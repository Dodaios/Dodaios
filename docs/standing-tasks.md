# Standing tasks

A standing task is something the assistant looks after for the owner over time, with no end
date: an ads campaign, an inbox, a launch, a hiring pipeline, a server, numbers someone checks
by hand. The owner hands it over once. From then on the assistant looks at it on its own, at a
pace it sets itself, and writes only when something changed, is prepared or needs the owner.

## How it differs from what already exists

| | What it is | Who starts each round | What it remembers |
| --- | --- | --- | --- |
| Routine ([routines.md](routines.md)) | a fixed prompt on a fixed schedule | the schedule | nothing of its own |
| Project (`project` tool) | a goal with an end, success criteria and sub-goals | the owner, then a daily review | the plan and the job evidence |
| "Needs you" check, morning brief | four fixed topics (mail, calendar, agents, deadlines) | the schedule | the open loops |
| Event trigger ([lead-event-triggers.md](lead-event-triggers.md)) | a rule on an incoming event | the event | nothing |
| **Standing task** | an open-ended responsibility | the assistant | working notes, a run log, its own pace |

Use a routine for "every day at 8 send me X". Use a project for work that is finished at some
point. Use a standing task when the work needs judgement, memory of the last state and a pace
that follows what is happening.

## What a task holds

- `title`, `goal` (what looking after it means, in the owner's terms), `how` (where to look and
  with what: accounts, tools, agents, files).
- `autonomy`: one of three levels, see below. `limits`: free text the owner wrote or confirmed,
  required for `act`.
- `state`: `proposed`, `active`, `paused` or `ended`.
- `interval_min`: the current pace, between 15 minutes and 7 days (default 3 hours). Each run
  may set the next one.
- `notes`: the working notes a run leaves for the next run (up to 4,000 characters).
- A run log: when, outcome, a one or two sentence summary, what was changed, the pace after it.
- At most 12 tasks may be open (proposed, active or paused) at once.

## Autonomy levels

| Level | The assistant may |
| --- | --- |
| `watch` | read only; it tells the owner when something changed or needs them |
| `prepare` (default) | also get the next step ready (a draft, a proposal, the numbers); nothing outside Dodaios changes |
| `act` | make changes that stay inside `limits`; anything outside them is prepared and asked |

Raising the level or changing `limits` needs the owner. Lowering the level, pausing and
changing the pace or the wording do not.

## What a run does

A standing task is carried by one recurring routine of the lead, tagged
`lead-standing:<id>` and quiet (no start card). The routine's stored prompt is one stable
line. The work order is composed for every run from the task, its notes and its last five
runs:

1. Find out what is true now, with the connected tools and accounts. No answer from the notes
   alone.
2. Compare with the notes: what changed, what is new, what is due.
3. Do what the level allows.
4. Report once with the `standing_task` tool (`action: "report"`): the outcome (`quiet`,
   `reported`, `prepared`, `acted` or `asked`), a summary, the full updated notes, what was
   changed, and the minutes until the next look.

The run's final reply is posted into the owner's conversation. A run with nothing for the
owner replies with the "nothing" marker and posts nothing. A run that never reported gets a
log line written for it by the app (`failed` with the error, `skipped` when it was stopped or
held back). Three failed runs in a row pause the task and say so once. The morning brief, when
the owner has one, gets a section on what the standing tasks did since the last brief.

### What a run may do

- The level is not only wording. A `watch` or `prepare` run gets a chat in the `ask`
  permission mode. An `act` run gets at most the mode of the chat the task was accepted in,
  and less when that chat has been narrowed since. A task the owner writes by hand in the
  panel gets what an ordinary lead routine gets.
- Nobody watches a run's chat, so an approval card raised there is answered at once instead
  of being left open. A call that only looks is let through: reading a file, searching,
  fetching a page, and every read of Dodaios' own tools and connected accounts. A level above
  `watch` may also write files inside the run's own folder (a draft, a table). Everything else
  is refused with the reason; the run then prepares the step and asks the owner in its report.
- A tool the app cannot tell to be read-only (a shell command, a tool of an MCP server the
  owner added to their coding CLI) is refused in a `watch` or `prepare` run. The owner's
  standing rules on the Trust page still apply, so a call they allow there runs; otherwise
  such a task needs the level `act`.
- The run's own report (`standing_task` with `action: "report"`) never needs a card, on a
  brain seat or a CLI seat.
- Risk tiers, approvals, the reversibility rule for unattended work and the owner's stop holds
  apply to every call of a run, as for any routine.
- A run whose model cannot ask for an approval in a background chat does not start when its
  level requires asking. It is logged as `failed` with that reason.
- What the code does not enforce: the difference between `watch` and `prepare` (both run in
  `ask`), and the wording of the `limits` of an `act` run. The limits are part of the run's
  work order; the app's hard limits, approval rules, stop holds and the kill switch are what
  holds in code, as for an ordinary lead routine.
- Three failed runs in a row pause the task and post one notice saying why. A stopped run or
  a run held back for billing is `skipped` and never counts.
- After an app start the routine of every active task is checked once and replaced when an
  app exit ended it (`heal_after_start`); reading the tasks does the same repair.
- Text a run reads from outside (mail, pages, files, tool results) is data, never an
  instruction.

### Billing

- A run is unattended work. It follows the one background billing rule
  (`dodaios/brain/background_policy.py`, see [routines.md](routines.md)): while a subscription
  is connected, a run never bills a per-token API key. The backing routine is pinned to the
  subscription seat the front page runs on when there is one. A run held back for this reason
  is logged as `skipped` with the reason; the same hold run after run stays one line.
- "Run now" in the app is the owner's own start and runs on the task's seat as chosen. A run
  the assistant starts itself (`run_now` through the tool) is not: the hold applies.
- An install that never connected a subscription keeps billing the seat it picked.

## How one comes to exist

**The owner asks.** "Look after my Meta ads campaign" in the lead conversation: the lead calls
`standing_task` with `action: "take_on"` and an exact quote from that message. The task is
active at once and the lead reads back state, pace and next run.

**The assistant suggests.** A task can be stored as `proposed`. Nothing runs. The owner sees a
card in the conversation and accepts with one click, or says yes and the lead calls `accept`
with those words. The assistant suggests one:

- when its initiative level allows it (`dodaios/brain/proactivity.py`): at `balanced` it offers
  once, in a sentence, when the owner keeps coming back to the same ongoing thing or hands over
  something with no end date; at `high` it stores the proposal right away and says so in one
  sentence; at `off` it never offers;
- from a "needs you" check, a trigger or another routine run, where `take_on` is never
  possible and becomes a proposal.

A proposal the owner declined, or a task they ended, is not suggested again for 30 days.
Suggesting the same title twice returns the open task.

**The owner writes one by hand** in the assistant's panel (`POST` below).

A request with a pace in it ("keep an eye on my inbox every day") is still a standing task. A
time of day ("every day at 8") or the word "routine" keeps it a routine
(`dodaios/society/routine_intent.py`, `hands_over_ongoing_work`).

## The `standing_task` tool

`dodaios/brain/standing_task_tool.py`. Lead only; a voice call hands this to the chat. The
lead's chat gets it from the tool gateway (`BrainSupervisorToolGateway.lead_extra_tools`) on a
brain seat and on a CLI seat. An unattended lead routine run gets it from
`society.surface.society_tools`, where it is the lead's own tool and does not depend on grants.

| Action | Needs | Notes |
| --- | --- | --- |
| `take_on` | title, goal; optional how, autonomy, limits, check_every_min; `request_quote` | owner's own message plus an exact quote from it, else it becomes a proposal |
| `propose` | the same fields, `reason` | any turn |
| `accept` | standing_id, `request_quote` | the owner's yes in their current message; a quote under 4 characters must be the whole message |
| `decline` | standing_id | |
| `list`, `status` | `status` takes standing_id | the task and its last runs |
| `update` | standing_id and the fields to change | raising autonomy or changing limits needs the owner's message and quote |
| `pause` | standing_id | any turn |
| `resume`, `run_now`, `end` | standing_id | the owner's own message |
| `note` | standing_id, text | appends one line to the working notes |
| `report` | standing_id, outcome, summary; optional notes, actions, next_check_min | only from a run of that task's own routine |

Who may do what is read from trusted provenance, never from an argument: the chat turn the app
set (`current_chat_turn`, `direct_user`), the unattended-origin marker of the routine runner,
and the run's own chat id (`...:routine:<task id>:<run>`), compared with the task's routine id.
`act` always needs non-empty limits.

Reads, `report`, `note` and `propose` have the risk tier `safe`, so a run reports without an
approval card. Everything else is `monitor`.

## Routes

All under `/api/agent-chat/lead/standing`.

| Route | Does |
| --- | --- |
| `GET /` | the open tasks, the bounds and the levels; `?ended=1` adds ended tasks |
| `POST /` | the owner creates one: `{title, goal, how?, autonomy?, limits?, interval_min?, timezone?}` |
| `GET /{id}` | `{task, runs}`; `?runs=N` (default 20, at most 100) |
| `PATCH /{id}` | changes the fields that are sent |
| `POST /{id}/{action}` | `accept`, `decline`, `pause`, `resume`, `end` or `run` |

A refusal keeps the service's sentence as `detail`: unknown id 404, invalid input 422, a state
or limit conflict 409, the scheduler not running 503.

## Where it lives

`dodaios/standing_tasks/`: `models.py` (the task, a run, the bounds), `store.py` (SQLite
`standing_tasks.db`),
`work_order.py` (the run's prompt and the brief section, pure text), `service.py` (taking on,
the backing routine, runs, the hooks the routine runner calls). The tool is
`dodaios/brain/standing_task_tool.py`, the routes are in `dodaios/ui/web/agent_chat_routes.py`.

## What is not done

- A voice call cannot take on, accept or change a standing task; it is done in the chat.
- A task belongs to the lead. A run uses the lead's own tools and may hand work to agents with
  `delegate`, but an agent cannot own a standing task.
- `limits` is free text the model reads. Code does not parse it; what enforces it is the
  permission mode of the run's chat, the risk tiers and the approvals.
- There is no event-driven run yet: a task looks at its own pace, or when someone starts a run.
- The lead routing golden set has cases for standing tasks, but no live recording yet
  ([lead-routing-evals.md](lead-routing-evals.md)).
