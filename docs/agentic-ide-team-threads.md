# Agentic IDE: team threads

A team thread gives one task to several coding agents on different models and
lets them carry it together, as peers: they plan, agree, build and review, and
the person reads one thread. Nobody copies a plan, a diff or a review from one
agent to another. In the second mode, planner and builder, one member owns a
living plan, one builds it step by step and the others review every step.

It lives in the thread layout of the Agentic IDE
([`agentic-ide-threads.md`](agentic-ide-threads.md)). Design decisions:
[ADR-0042](adr/0042-team-threads-trusted-coordinator.md).

## Starting one

The people icon on a project row opens the start form. It offers two ways of
working: **Peers** (the default, described first below) and **Planner and
builder** (see [its own section](#planner-and-builder)). The team is suggested
from what is connected on this machine: one seat per model family, a coding CLI
before a provider API (by default Claude, GPT and Gemini when all three are
there). The person can swap, add and remove members, two to four in total, then
writes the task and sends it. That one prompt is all the team needs.

A member starts on its coding agent's own default model. When that default is
refused on the member's first turn (a CLI configured for a model the signed-in
account may not use), the member is asked once more on the first model the CLI
lists for the account, and the thread says so.

With one model family connected the team still works (two rows of that family,
or the same seat twice) and the thread says what such a team cannot give:
members of one family share their blind spots.

## The order of work

A coordinator in the app, not a model, decides whose turn runs and what that
member reads.

| Step | What happens |
|---|---|
| Own plans | Every member writes its plan without seeing the others'. |
| Challenge | Every member reads the other plans, names their flaws and says what the common plan must contain. |
| Master plan | One member writes the master plan; the others agree or object. An objection starts a new round with another author. |
| Build | The author of the agreed plan implements it in the project folder. |
| Review | The others review the change against the plan. Findings go back to the builder, who fixes or rebuts them; then they review again. |

The thread is done when every reviewer approves. A reply without a readable
verdict never counts as agreement. A vote belongs to one plan: when a plan is
rewritten, it is voted on again.

Reviewers read the change as a diff between two snapshots of the folder (the
working tree with untracked files, taken with git through a throwaway index, so
the person's index, branches and files are not touched; the only trace is
unreferenced objects that git's own housekeeping removes). Outside a git
repository they read the files directly and the thread says so. The steps
before the build must not change files; the coordinator compares snapshots
around them and reports a change in the thread with the files' names, so a
cache that a check left behind can be told from an edit.

## The team room

A team thread opens as a room: the team on a canvas, their chats beside it,
the task, state, steps and bounds above. Below about 980 pixels of width the
canvas sits above the chats.

- **Canvas.** Each member is a node with its model's mark, its name, its role
  (planner and builder) and its state in one line: what it is doing right now
  (the file it reads, the command it runs, with the time), waiting for the
  person, waiting for its turn, finished, or gone with the reason. The person
  is a node too. The layout is fixed per team size and fitted to the frame,
  so nothing moves while the team works; it can be zoomed and moved.
- **Lines.** Every line is a real handoff the coordinator made, never
  decoration: the task and the person's messages to every member, a plan to
  the members who read it, a vote or a plan review back to its author, a build
  to its reviewers, findings back to the builder, a blocked step to the
  planner. A line's label says what went across last ("Master plan, round 2",
  "3 findings, 1 blocking", "Change, 4 files", "Agrees"), with a count when
  more went that way. A line a member is working on right now flows; the lines
  of the current step and the step before it are drawn with their labels;
  older lines stay as faint traces whose label shows on hover.
- **Chats.** The side column has a tab per member with that member's own
  conversation as it streams in: its turns, tool calls, diffs and words. What
  the coordinator handed the member is folded to its first line. **Follow**
  (on by default) shows whoever is working; picking a tab or a node turns it
  off. A member's thread is read from its own socket, one per member however
  many places show it, opened through the app's connect budget.
- **Exchanges.** A click on a line shows everything the two members exchanged,
  both ways, in order, the newest unfolded. Escape or the close button returns
  to the chat.
- **Story.** The shared story is a tab: every contribution as one line (who,
  what, the verdict, to whom, a two-line gist) under a heading per step, the
  person's messages, notices and the outcome where they happened, and at the
  end what the team caught in each other's work, with who raised it, where,
  and whether it is resolved. A click unfolds a contribution in place.
- **Header.** The steps as one line, time and turns against their limits, the
  cost where a seat reports one (the list price the coding agents report; a
  subscription seat is not billed per turn), and for planner and builder the
  plan's progress, which opens the plan.
- **Ways back.** Nothing in the room navigates away except **Full thread** on
  a member's chat (or **Answer in its thread** when the member waits for an
  approval there). That thread shows **Back to the team** at its top, the team
  stays marked in the thread list meanwhile, and the room comes back on the
  same chat. The start form has **Back** to what was open before it.

## Stepping in

- **Message:** whatever the person writes reaches every member with its next
  turn and outranks plans and peers.
- **Pause** stops the running turns and returns once every one of them has
  really stopped; **Continue** goes on from the same step without asking again
  for what is already in the thread.
- **Stop** ends the thread.
- Each member runs with the access mode a new thread of its coding agent gets,
  and its approval cards and safety rules are the same as in any thread. A
  member whose turn waits for the person is marked in the header.

## Bounds

| Bound | Default |
|---|---|
| Working time (paused time does not count) | 90 minutes |
| Model turns | 40 |
| Master plans before the thread asks | 3 rounds |
| Review rounds before the thread asks | 3 rounds |
| One turn | 30 minutes |
| Cost | no cap; counted where the seat reports a price |

When a bound is reached, or the members cannot agree, the thread stops and
waits with a short account of the open points:

- **Plan not agreed:** answer the open points (one more round with the answer),
  or take the latest plan as it is.
- **Review not approved:** answer, ask for another round, or accept the work
  with the findings left open. The record keeps them as unresolved.
- **Time, turns or cost:** Continue raises the bound by half.
- **A turn did not finish:** Continue asks that member again.

A turn that fails is tried once more. A member whose seat keeps failing (not
signed in, quota, crash) leaves the team and the others go on; when the
builder leaves, another member takes over. When that would leave fewer than
two members, nobody is dropped: the thread waits and Continue asks again.

A turn counts against the bounds when it starts, so one that Pause cut short
is not free. An answer that has arrived is filed before a pause takes effect,
so Continue never asks for the same work twice.

Nothing continues by itself. A thread that was working when the app closed
comes back paused.

## Planner and builder

The second mode gives each member a role instead of making everyone plan:

| Role | What it does |
|---|---|
| Planner | Owns the plan: an ordered list of small steps, each with a title, a goal and `done_when`, the check that proves the step. |
| Builder | Builds the plan one step at a time and reports each step as done or blocked. |
| Reviewer | Reviews the plan and every step. |

The start form shows a role per member: by default member 1 plans, member 2
builds and every further member reviews. A team needs exactly one planner and
one builder. Nobody checks only their own work: with two members the builder
reviews the plan and the planner reviews each step.

| Step | What happens |
|---|---|
| Plan | The planner writes the plan and ends with a typed `team-plan` block. The plan reviewers agree or object (`team-verdict`); an objection goes back to the planner with the reasons, until the plan is agreed. |
| Steps | The builder gets the current step with the whole plan around it and ends with a typed `team-step` block. A reviewer checks the step against its `done_when` and the diff since the step started. Changes requested go back to the builder on the same step. |
| Final review | When every step is accepted, every member but the builder reviews the whole change; the planner signs off on it against its plan. Findings go back to the builder. |

The plan lives in the thread and is versioned. A builder that reports a step
as blocked, or asks for a change to the rest of the plan, sends the planner a
revision request: the planner writes the next version, the reviewers check it,
and building goes on from the first step that is not accepted. An accepted
step keeps its status in the new version while its title stays the same;
the planner reopens one by listing its number. A change asked for together
with a finished step waits until that step is reviewed.

A plan the coordinator cannot read (no block, broken JSON, a step without
`done_when`) is never taken for a plan: the planner is asked once more with
the reason, then the thread waits for the person.

The room's **Plan** tab shows the current version (marked while it is still
proposed), each step with its state (open, building, in review, changes
requested, accepted) and who holds it, and an open revision request. In the
story, a plan round, each step of the plan and the final review have a
heading of their own; the canvas shows each member's role, the plan going to
its readers, each step going to its reviewer and a blocked step going back to
the planner.

Bounds are those of the table above, with two differences: plan rounds count
per version (a revision starts again at one), and review rounds count per
step. When a step is still not approved after its rounds, the person answers
(one more round), accepts the step as it is (the record keeps its findings
open and the plan marks it), or stops. Messages, Pause, Continue and Stop
work as in the peers mode, and a member that leaves hands its role to a
reviewer.

## API and CLI

`/api/team-threads` (see `jarvis/ui/web/team_thread_routes.py`): list, `seats`,
start, read, `message`, `pause`, `resume`, `accept`, `stop`, delete. Start takes
`mode` (`peers` or `planner_builder`) and a `role` per seat; a thread's read
carries `mode`, each member's `role` and, for planner and builder, `plan`. The routes
are reachable through the CLI's `api` group like every other route.

## Not included yet

- Members build one after another, never at the same time: the work is not
  split across parallel builders.
- A team thread is started from the IDE, not by voice or from the Dodaios chat.
- A finished thread takes no follow-up task; start a new one.
- A member runs on its provider's active account; a second subscription account
  of one provider cannot be picked per member.

## Platforms

Nothing is OS-specific: the coordinator, the store (`team_threads.db` in the
data folder) and the git calls are the same everywhere, and a machine without
git degrades as described above.
