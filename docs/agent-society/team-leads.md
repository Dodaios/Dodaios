# Team leads

A team (a group of agents in the Agents section) can have a **lead**: one of
its members that manages the team for the person. The person talks to the lead
in an ordinary chat and says what the team should achieve. The lead breaks it
into tasks, hands each task to the member whose role fits, checks what comes
back, sends rework or re-assigns, and reports when the goal is done. The
person steps in only for what is theirs: answering a question the lead cannot
decide, continuing a paused goal, or stopping one.

Code: `jarvis/society/team_lead.py` (the engine), `jarvis/society/team_tools.py`
(the lead's tools), `/api/society/chat-groups/{id}/…` in
`jarvis/ui/web/society_routes.py`, and the lead's view in
`src/components/society/chat/TeamLeadView.tsx` (the chat) with
`TeamLeadPanel.tsx` (the team beside it).

## Naming a lead

Open a team and choose **Lead**. Either create a lead (a new agent whose
standing instructions are to manage this team) or make an existing member the
lead. A lead is an `orchestrator` on the roster, the tier the scheduler allows
to assign work; a promoted member returns to its previous tier when it stops
leading. An agent leads at most one team, and the assistant itself is never a
team lead because it already leads every agent.

The team's **mission** is a short standing purpose. The lead reads it on every
managing turn.

## Talking to the lead

The **Lead** tab of a team is the lead's own chat, the same conversation and
composer every agent has. There is no separate form for goals:

- **Asking for work** is a message. When the lead hands out the first task
  from it, a goal opens in the person's own words (source `chat`).
- **Answering** a question the lead asked, or telling it to go on with a
  paused goal, is a message too. The lead's tools work on that goal again
  inside the person's turn; a turn nobody typed (a check-in, another agent's
  message) can never answer for the person.
- **Reports** appear in the conversation as cards: the result of a goal, an
  interim update, a failure, or the lead's question.
- Above the composer sit the actions only a lead is asked: a status, a
  suggestion for the next goals, a look at the team, and taking the
  initiative. Each sends its sentence as the person's message.

Beside the chat, the team panel follows the work live: the goal in progress
with every task, what waits behind it, the members and what each is on, and
the finished goals. It holds the controls that are not a sentence (stop,
continue, try again) and the setup: mission, initiative, who leads.

After the person's turn the engine follows up exactly as after a managing
turn: results that landed meanwhile are reviewed, and a goal left with
nothing running and no report is asked once for a typed one.

## How a goal runs

1. **Plan.** The lead gets a managing turn in its own chat with the goal, the
   mission and the members. It hands out tasks with `society_team_assign`.
2. **Work.** Every task is one `ASSIGN` on the society board, on its own
   trace. The scheduler decides whether the member starts, exactly as for any
   other assignment. A busy member is not a failure: the task waits and knocks
   again by itself.
3. **Review.** When a result lands, the engine wakes the lead with it. Results
   that arrive while the lead is mid-turn are batched into its next turn.
4. **Report.** The lead closes the goal with `society_team_report`. A lead
   that ends a turn with nothing running and no report is asked once to say
   which it is, the result or a question for the person. If it still reports
   nothing, its answer is the report.

A team works on one goal at a time; further goals queue and start in order.

Work handed to a lead from elsewhere becomes a team goal as well: when the
assistant delegates to a lead by voice or chat, or a quest is routed to one,
the goal's report answers that assignment. A goal may queue or wait for the
person for a long time, so it never holds one of the lead's run slots; the
team's own queue is what bounds it.

Every state change of a goal is a compare-and-swap on its current state, so a
stop always wins over a pause, a resume or a report that was decided on an
older read.

## The lead's tools

Offered only in the chats of an agent that currently leads a team.

| Tool | What it does |
|---|---|
| `society_team_assign` | Hand one task to one member. Returns at once with the task's state. With no goal in progress it opens one; `goal` names it. |
| `society_team_board` | Read the mission, the members, every open goal with its tasks, and the goals finished most recently. |
| `society_team_report` | `progress`, `needs_input` (one question for the person), `done`, `failed`. |

None of them starts work by itself. Assigning appends an envelope; the
scheduler (trusted Python) applies the tier wall, the delegation depth, the
budgets and the concurrency cap.

## Goal and task states

| Goal | Meaning |
|---|---|
| `queued` | Waits behind the team's current goal. |
| `running` | The lead or a member is working on it. |
| `needs_input` | The lead asked the person a question. |
| `paused` | Stopped until the person continues it. |
| `done`, `failed`, `cancelled` | Finished. |

| Task | Meaning |
|---|---|
| `waiting` | The member was busy; the assignment knocks again. |
| `assigned` | The assignment is on the board. |
| `running` | The member took it. |
| `done`, `blocked` | The member's result, or a final refusal. |
| `cancelled` | The goal was stopped first. |

Both vocabularies are pinned across Python, SQL and TypeScript by
`tests/unit/society/test_society_enum_parity.py`.

## Bounds

- The engine never calls a model. A lead's turns run on the lead's seat and a
  member's on the member's seat.
- Every turn belongs to a goal the person started, or to a check-in they
  switched on.
- A goal has a budget of managing turns. When it is spent the goal pauses and
  the person decides whether to continue.
- A goal has a task limit, and a team a limit of open goals.
- The society kill switch pauses every running goal.
- Goals that were running when the app closed come back `paused`, with their
  open tasks marked as interrupted. Opening the app never resumes one.
- A task with no sign of life is checked against the scheduler and then
  against the member's own chat. A member that is still working is left
  alone, a turn that finished without its result reaching the board becomes
  the task's result, and only work the chat never saw reaches the lead as
  `blocked`. The lead is never left waiting forever, and never hands the same
  work out twice because a start was slow.

## Initiative

How much a lead does without being asked is the person's choice, made in the
team panel's setup:

| Way | What the lead does |
|---|---|
| Only when asked | Works when the person writes and whenever a result comes in. The default. |
| Keeps watch | Also looks at its team unprompted (every hour, every four hours, or once a day): it follows up on stuck work and starts standing duties the mission names. |
| Takes the initiative | As above, and when no goal is open it sets the team's next goal from the mission and hands out the first tasks (source `lead`). |

A look is an ordinary agent routine tagged `team-checkin:<team id>` (and
`team-initiative:<team id>` when it may set goals), so it appears with the
lead's other routines and follows the same rules for which seat may run
background work. A lead that takes the initiative stays inside every bound
below: one goal at a time, the turn budget, the task limit. With a mission
that gives it nothing to derive a goal from, it starts nothing and says what
it needs.

## Drills

One failure cannot be produced on demand through the app: a start that takes
longer than the board waits for it. A drill file makes it reproducible in a
running app, with a real model and without changing any code.

Create `society_drill.json` in the app's data directory:

```json
{"slow_start_s": 8}
```

While the file exists, every start of a member's turn is held for that many
seconds (at most 30) after the turn has begun. The board gives up on the start
after five seconds, so the task stays `assigned` although the member is
working. A few minutes later the sweep reads the member's finished turn from
its chat, the task becomes `done`, and the lead is woken with the result. The
file is read on every start: delete it and the next start is normal again, no
restart needed. Each held start is logged as `society drill: holding the start`.
