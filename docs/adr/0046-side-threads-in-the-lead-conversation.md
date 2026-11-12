# ADR-0046 — Side threads: the lead answers a new message while it still works

**Status:** Accepted · **Date:** 2026-11-12 · **Extends:**
[ADR-0041](0041-several-orders-at-once.md) §4 and
[ADR-0045](0045-lead-keeps-one-endless-conversation.md)

## Context

ADR-0041 freed the lead's chat while a turn only *waits* for delegated work.
A turn that is still answering or running a tool kept its seat, and a message
sent meanwhile waited in the queue ("Waits until the current task is done").
With long research or build turns that wait is minutes: the person writes a
second thing and nothing happens. They expect a conversation partner that
keeps answering while the work goes on.

ADR-0041 rejected concurrent turns in one session: the service, the approval
cards, the stop button and the timeline all assume one running turn.

## Decision

A message sent to the lead's conversation while its turn is working is
answered at once in a **side thread**: a chat session of its own that runs
beside the main thread (`dodaios/agent_chat/side_threads.py`). The one-turn
assumption holds in both sessions.

1. **When.** Only the lead's conversation, only from the composer route
   (`POST /sessions/{id}/messages`), only while a turn runs. A turn that
   merely waits still hands its seat over first (ADR-0041 §4), so that message
   is answered in the main thread. `delivery: "after"` keeps the queue. At
   most four side threads run at once (`MAX_RUNNING`); a further message
   queues as before. A message during an active goal still steers the goal.
   Phone and channel messages keep the queue: their replies are routed from
   the conversation's own turns.
2. **What it is.** An ordinary `jarvis` session on the conversation's seat,
   folder and stance. A row in `agent_chat_side_threads` names its
   conversation; `list_sessions` and the thread search leave such sessions
   out, so a side thread is never a chat of its own. It shares the
   conversation's "always allow" memory and speaks as the lead (lead doctrine,
   turn contract).
3. **Context.** It does not share the main thread's context window. Its turn
   is briefed (`context_note`): why it exists, the conversation's summary and
   its recent messages, and the instruction to answer only this message. The
   brief travels as briefing, never inside the person's words (ADR-0041:
   deterministic routes read the turn's text).
4. **In the timeline.** Two notices in the conversation: `side_thread_started`
   (the person's message) and `side_thread_finished` (status `done`, `stopped`,
   `failed`, `interrupted` or `moved`, with the answer). The reducer keeps one
   line per side thread and patches it in place, so the exchange stands where
   it was asked. While it runs, the front page reads the side session itself
   for the work trace, the cards and the streaming answer; afterwards the
   answer is on the notice, so a reopened chat opens no second connection.
   The notice also lists every message the side thread wrote (`messages`),
   each on its own: a confirmation and, minutes later, the result stay two
   bubbles after it ended, as they were while it ran. `answer` (what was said
   after the last tool call) is what the lead's later turns read.
   The activity panel lists a running side thread under "Running".
5. **What the lead knows afterwards.** `side_thread_finished` is replayed into
   the lead's history as one labelled record (`replay`), on the brain seat
   through `messages_from_events` and on a CLI seat through the catch-up block,
   which also covers a side thread that ended inside the CLI's own turn. A
   main-thread turn that starts while side threads run is told so
   (`running_note`).
6. **A message that belongs to the running request.** Its line has "Belongs to
   the running task": the side thread stops without an answer and the message
   starts as the next turn of the main thread, right after the running request
   and with its whole context (`move_to_main`). Each side thread has its own
   stop; the composer's stop still stops the main turn only, and the moved
   message then starts at once.
7. **Restart.** A `jarvis` turn is the app's child, so a side thread dies with
   the process. Boot closes every one left `running` as `interrupted`
   (`recover`), written in the chat, never silently.

## Consequences

- The chat never makes the person wait for a working turn; several requests
  run side by side and each answer stands under its own message.
- No additional model call: the side thread's turn is the turn the queued
  message would have run later. Parallel turns do spend a subscription's rate
  budget faster; the cap of four bounds that.
- A side thread sees the conversation as of its start. It does not see what
  the main turn finds out while both run, and the main turn learns of the side
  thread's answer on its next turn.
- Side-thread sessions stay in the chat database (their full trace is the
  detail behind the answer) and are removed with their rows when deleted.

## Not covered

- A moved message is not written into the running turn. Tried on the Claude
  Code seat (2026-11-12): a message written into a turn that is in the middle
  of an answer, with no tool call left, is queued by the CLI, answered after
  that answer as a turn of its own, and the chat never shows that second
  answer, because the turn closes at the first result line. The same holds
  for a message steered into a coding thread at that moment
  (`runner_cli._steer`); that is open.

## Alternatives considered

- **Always steer the message into the running turn.** Wrong for an unrelated
  request: it derails the running work and is answered only when the model
  gets to it. For a correction it is also not dependable (see "Not covered").
- **A model call that classifies each message (correction or new task).**
  An extra paid call on every message and a wrong guess either way; the
  person's own button is cheaper and predictable.
- **A second concurrent turn in the same session.** Rejected in ADR-0041 for
  the same reasons as before.
- **Forking the seat's own conversation (`--fork-session`).** Only one CLI
  has it, and a fork of an endless conversation carries its whole window; the
  brief is seat-independent and bounded.

## References

- `dodaios/agent_chat/side_threads.py`, `dodaios/agent_chat/store.py`,
  `dodaios/ui/web/agent_chat_routes.py`, `dodaios/agent_chat/runner_api.py`,
  `dodaios/agent_chat/dodaios_harness.py`
- `components/agentchat/SideThread.tsx`, `components/agentchat/reduce.ts`,
  `components/home/LeadActivityPanel.tsx`
- `tests/unit/agent_chat/test_side_threads.py`,
  `components/agentchat/SideThread.test.tsx`
