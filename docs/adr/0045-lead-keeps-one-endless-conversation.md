# ADR-0045 — The lead keeps one endless conversation

**Status:** Accepted · **Date:** 2026-11-09

## Context

The lead assistant opened a new chat for every conversation. Typed chats,
voice calls (`sessions.db`) and channel messages (`chats.db`) lived in three
histories, results of delegated work landed in "the newest chat", a report
failed when no chat was open, and every new chat started with no context.
The model saw at most the last 40 messages.

Created agents already had one endless chat each (MASTERPLAN §10); the lead
was excluded on purpose.

## Decision

1. **One conversation.** The lead has exactly one `jarvis`-surface session,
   remembered in `agent_chat.db` (`jarvis_lead_session`). An upgrade adopts the
   newest existing chat; older chats stay readable as history. It cannot be
   deleted. `dodaios/agent_chat/lead.py` is the one place that resolves it.
2. **Everything lands there.** Typed turns, voice calls without another chat
   on screen, agent reports, society notices, lead routine results (including
   the morning brief) and the owner's private Telegram chat. A "new chat"
   request returns the conversation with the picked model on its seat.
   Friends' and group messages never enter it.
3. **Long history is compacted, not cut.** The lead reuses the society
   checkpoint compaction (`society/conversation.py`): the provider's context
   window sets the budget, older events become a rolling summary, the recent
   tail stays verbatim. Voice calls start on the same summary plus a tail.
4. **Fresh start, not new chat.** `/clear` moves the checkpoint to the newest
   message with a short note; the thread, its archive and memory stay.
5. **Recall.** `memory-search` also returns matching lines from the
   conversation (`conversation` key), so earlier talks are found in text and
   voice.
6. **Visible learning.** Background memory writes post a written
   `memory_learned` notice ("Remembered: …") with an undo for new memories.
7. **Proactive, quietly.** The morning brief is one tagged lead routine,
   off by default, never billed to a provider key, written only.
8. **Front page.** No chat list in the sidebar ("Earlier chats" opens the
   archive); an activity panel on the right shows what waits, runs and
   finished.

## Consequences

- The model starts every turn with relevant context instead of nothing, at
  the cost of a summary call when the window fills.
- Memory work (episodes from checkpoints, corrections, nightly consolidation)
  builds on the checkpoints; that is owned by the memory vault (ADR-0044).
- Coding chats (`agent`), side chats and created agents are unchanged.
- Discord still uses the classic chat path until it can tell a direct
  message from a server channel.
