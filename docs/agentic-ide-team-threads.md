# Agentic IDE: team threads

A team thread gives one task to several coding agents on different models and
lets them carry it together, as peers: they plan, agree, build and review, and
the person reads one thread. Nobody copies a plan, a diff or a review from one
agent to another.

It lives in the thread layout of the Agentic IDE
([`agentic-ide-threads.md`](agentic-ide-threads.md)). Design decisions:
[ADR-0042](adr/0042-team-threads-trusted-coordinator.md).

## Starting one

The people icon on a project row opens the start form. The team is suggested
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

## The shared thread

- Every contribution appears under its author's name with what it is: own plan,
  challenge, master plan, vote, build report, review, answer to the review.
  First plans and challenges open folded; the current master plan, the reports
  and the reviews are open.
- **Caught by the team** lists every objection and finding with who raised it,
  where, and whether it is resolved.
- Each member is an ordinary thread underneath. A click on its chip opens it
  with every tool call and diff; the thread list shows the team once and keeps
  the members out of it.
- The header shows the step, the time and turns used against their limits, and
  the cost where a seat reports one. That amount is the list price the coding
  agents report; a subscription seat is not billed per turn.

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

## API and CLI

`/api/team-threads` (see `jarvis/ui/web/team_thread_routes.py`): list, `seats`,
start, read, `message`, `pause`, `resume`, `accept`, `stop`, delete. The routes
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
