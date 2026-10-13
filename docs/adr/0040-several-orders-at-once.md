# ADR-0040 — Several orders at once: background tasks in a live call, parked requests in chat

**Status:** Accepted · **Date:** 2026-10-13 · **Extends:**
[ADR-0034](0034-non-blocking-heavy-turns.md) for the continuous voice sessions of
[ADR-0036](0036-continuous-voice-and-agent-selection.md) and for the typed chat

## Context

The user gives one order, and while it is still being carried out gives the
next: "brief the agent in terminal two", then "create an agent for the docs",
then "and look up X". ADR-0034 made a heavy turn stop blocking the legacy
realtime session. The sessions every realtime provider uses today
(`jarvis/live`) and the typed chat still handled one order at a time:

- `LiveTools.execute` held one lock for the whole execution, so every tool of
  a call ran strictly after the previous one, across turns.
- In the subscription session a follow-up was accepted but reasoning took it
  only "after the current tool returns its receipt". A tool that ran for
  twenty seconds held the second order for twenty seconds.
- A tool released at the voice budget reported back only if the user had said
  nothing since. Any new sentence dropped the report, so the model never
  learned that the first order had finished.
- A released tool counted as pending work, so one long action kept every
  other report (an agent's result, another tool's receipt) waiting.
- In the typed chat a turn that had handed work to a coding pane or an agent
  stayed open until that work reported back, for up to thirty minutes. The
  next message waited in the queue behind it.
- `spawn_worker` answered every spawn inside thirty seconds of a running one
  with "already running", including a different order from a later turn.

## Decision

One vocabulary for both surfaces: an order that outlives the attention of the
conversation continues **in the background**, the conversation takes the next
order at once, and the result comes back later **naming the request it
answers**. No new model, no sub-agent type and no background model call is
introduced; the work that continues is the action that was already started.

### 1. Live voice: independent actions run side by side

`LiveTools` serializes only what shares a resource: the screen tools
(`computer`, `take_appshot`, `computer_use`) and the session controls
(`confirm_action`, `end_call`). Every other call runs concurrently. One call
ID delivered on two transports still executes once: the second waits for the
first one's receipt.

### 2. Live voice: an action the user moved on from becomes a background task

`LiveTools.execute_releasable` waits for a call until it should no longer
hold the conversation:

- an **action** still running when the user gives the next request
  (`revision` changes) is released after a short grace (`MOVE_ON_GRACE_S`),
  so an action about to finish still answers its own call;
- **any** call still running after the caller's deadline is released (the
  native wire, where the model is blocked on the result, passes the existing
  voice budget). A lookup is never released by new speech: its answer belongs
  to the question that asked for it.

The call is answered with a pending receipt that carries a `task_id`. The
action is not cancelled and not repeated; it finishes on the call's
`TaskBoard` (`jarvis/live/tasks.py`) and keeps its durable receipt in the
ledger. All three session classes use the same path: the native session with
the voice budget as deadline, the continuous and the subscription session
without one.

### 3. Live voice: the receipt is told at a pause, and it may finish what waited

When a background task ends, the session queues its receipt and offers it at
the next pause (nobody speaks, no answer is being generated, no tool the
model waits for is running). A running background task does not hold a pause
back. The report:

- is delivered whatever the user said in between when the task was an
  **action**; a late screen or lookup result is still dropped once the request
  changed, as before;
- carries the request the action was started for, and asks the model to open
  with it (`task_report_prompt`);
- is the deferred function result, so the model keeps its tools for what the
  user had already asked for and was waiting on it ("start an agent" … "tell
  it to run the tests"). It is told not to repeat the finished action and to
  start nothing new;
- stays owed when the call does not voice it, for a bounded number of pauses.

A stop word cancels every running background task. `task_status` lists the
tasks of the call with their request, state and result, and stops one by id.

### 4. Chat: a turn that only waits hands its seat to the next message

On Dodaios' own chat (surface `jarvis`), a turn whose model work is done and
which only waits for delegates gives up its seat when the person sends another
message (`jarvis/agent_chat/parked_work.py`):

- the turn closes with what it has said, and its `turn_finished` names who is
  still working (`background`);
- the same `DelegationWait` continues outside the turn, reading the same local
  evidence and calling no model;
- when the delegates have reported, the earlier request continues in a turn of
  its own, opened by a `user_message` with `origin: "background"` that the
  timeline draws as "result for your earlier request";
- every turn started meanwhile is told which requests still run behind it.

A turn that is still answering or running a tool keeps its seat, and the new
message queues behind it as before; when that turn then starts waiting, the
queued message starts. A wait nobody interrupts keeps its turn, exactly as
before. An agent's own chat (`society`) keeps holding its turn.

### 5. A second order is not a duplicate spawn

The spawn window exists for fragments of one utterance. A typed message and a
live call's request are whole turns the user finished, so a spawn from a
different such turn that asks for something else dispatches while the first
still runs. The same order repeated, and every spawn without an identifiable
turn (the classic pipeline), stay under the window.

## Consequences

- Orders given in quick succession in a live call or in the chat start right
  away and report back one by one, each tied to its request.
- No additional chargeable call: the report of a background task is the model
  round the tool result would have caused anyway, and the chat continuation
  is the round the held turn would have run.
- History order changes in the chat: a parked request's answer is appended
  when its delegates report, possibly after later exchanges. The timeline
  marks it, and the continuation prompt tells the model to name the request.
- Parked chat work and background tasks live in memory. A restart forgets the
  wait, never the delegated work, whose own report still reaches the chat or
  the next call.

## Not covered

- The classic voice pipeline still runs one turn at a time (ADR-0034 §3 is not
  built).
- Background missions still run one after another
  (`max_concurrent_missions = 1`, a capacity decision for subscription
  workers); a second mission is accepted and queued.
- A mission's result is read back in voice and shown in its own views; it is
  not posted into the typed chat that started it.

## Alternatives considered

- **Concurrent turns in one chat session.** The service, the approval cards,
  the stop button and the timeline all assume one running turn; the long part
  of an order is the delegated work, not the model's answer, so freeing the
  seat during that wait gives the behaviour without rewriting the session.
- **Release every live tool call after a fixed time.** Changes the common
  case of an action that finishes within a few seconds into a later report for
  no gain; outside the blocking native wire only the user moving on is a
  reason to stop waiting.
- **Report a background task without tool authority.** Loses the order that
  depended on it; the receipt is the function result the model was promised.
- **Text similarity alone for the spawn window.** Fragments of one utterance
  have different words; the turn identity is what tells a second order apart.

## References

- `jarvis/live/tasks.py`, `jarvis/live/tools.py`, `jarvis/live/session.py`,
  `jarvis/live/native.py`, `jarvis/live/subscription.py`,
  `jarvis/realtime/report_prompt.py`
- `jarvis/agent_chat/parked_work.py`, `jarvis/agent_chat/delegation_wait.py`,
  `jarvis/agent_chat/send_queue.py`, `jarvis/agent_chat/service.py`
- `jarvis/plugins/tool/spawn_worker.py`
- `tests/unit/live/test_background_tasks.py`,
  `tests/unit/agent_chat/test_parked_work.py`,
  `tests/unit/plugins/tool/test_spawn_worker_cooldown.py`
