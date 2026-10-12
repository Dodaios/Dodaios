# Team leads

A team (a group of agents in the Agents section) can have a **lead**: one of
its members that manages the team for the person. The person gives the team a
goal. The lead breaks it into tasks, hands each task to the member whose role
fits, checks what comes back, sends rework or re-assigns, and reports when the
goal is done. The person steps in only for what is theirs: answering a
question the lead cannot decide, continuing a paused goal, or stopping one.

Code: `jarvis/society/team_lead.py` (the engine), `jarvis/society/team_tools.py`
(the lead's tools), `/api/society/chat-groups/{id}/…` in
`jarvis/ui/web/society_routes.py`, and the board in
`src/components/society/chat/TeamLeadBoard.tsx`.

## Naming a lead

Open a team and choose **Lead**. Either create a lead (a new agent whose
standing instructions are to manage this team) or make an existing member the
lead. A lead is an `orchestrator` on the roster, the tier the scheduler allows
to assign work; a promoted member returns to its previous tier when it stops
leading. An agent leads at most one team, and the assistant itself is never a
team lead because it already leads every agent.

The team's **mission** is a short standing purpose. The lead reads it on every
managing turn.

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
| `society_team_assign` | Hand one task to one member. Returns at once with the task's state. |
| `society_team_board` | Read the mission, the members and every open goal with its tasks. |
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

## Check-ins

Off by default. When the person switches them on (every hour, every four
hours, or once a day), the lead looks at its team unprompted: it follows up on
stuck work and starts standing duties the mission names. A check-in is an
ordinary agent routine tagged `team-checkin:<team id>`, so it appears with the
lead's other routines and follows the same rules for which seat may run
background work.
