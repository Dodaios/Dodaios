# ADR-0042 — Team threads: peers coordinated by trusted code

**Status:** Accepted · **Date:** 2026-10-13

## Context

Several coding agents on different models run side by side in the Agentic IDE,
but each works alone. A person who wants one model's plan checked by another
carries plans, diffs and reviews between panes by hand. Missions automate plan,
work and review with one worker and one reviewer on the same provider chain
([ADR-0009](0009-self-healing-worker-critic.md)), so different models never
check each other, and a mission cannot be paused or redirected.

The goal: one prompt, a team of different models that plans, builds and reviews
together in one visible thread, bounded and interruptible.

## Decision

1. **A coordinator in trusted Python owns the order of work**
   (`jarvis/agent_chat/team/engine.py`). The steps are fixed: blind plans,
   challenge, master plan with votes, build, review rounds. The coordinator
   decides whose turn runs and what that member reads; models only write
   contributions. No member gets a tool that starts or messages another
   member, so the rule that no spawn tool enters a worker set (AP-5, AP-14)
   holds unchanged and a team thread can never become an open model loop.
2. **A member is an ordinary thread session** (agent-chat surface `agent`,
   `jarvis/agent_chat/runner_cli.py`). Access modes, approval cards, the risk
   check and subscription logins are exactly those of a thread; the coordinator
   adds no second permission path. The engine reaches sessions through a narrow
   port (`team/port.py`), so tests script the peers without a model.
3. **Agreement is typed and conservative.** Voters and reviewers end their
   reply with a `team-verdict` block. A missing or unreadable verdict counts as
   an objection, an approval with a blocking finding is no approval.
4. **Every step is derived from the entries already filed**
   (`team_threads.db`). Pause, a restart and a failed member all continue from
   the same data. A thread that was running when the process ended comes back
   paused; nothing a person did not start resumes by itself.
5. **Bounds end in a question, never in a loop.** Rounds, turns, working time
   and (where reported) cost are limited. Reaching a limit or failing to agree
   stops the thread with a typed reason and the open points, and waits for the
   person, who answers, accepts or stops.
6. **The folder is observed, not locked.** Reviewers get the diff between two
   git tree snapshots taken through a throwaway index. Steps that must only
   read are instructed so and checked with the same snapshots; a change is
   reported in the thread.

## Consequences

- Different model families check each other's plan and work, and the thread
  keeps a record of what each caught. A one-family team still runs and says
  what it cannot give (AP-22).
- A member whose seat fails leaves and the team degrades instead of failing,
  down to two members.
- Reading steps are not sandboxed per runner. A vendor CLI's plan mode would
  enforce it for some runners but ends in an approval card that an unattended
  turn cannot answer; detection is uniform across every runner instead.
- Members share one working tree, so they build one after another. Splitting
  the build across parallel builders needs a worktree per builder and a merge
  step, and is left for a later change.
- The engine is built on first use; nothing is added to the boot path (AP-26).
