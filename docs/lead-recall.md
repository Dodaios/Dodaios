# Recall: ids, cards and the chain of recall

The lead's context window works like a cache: what it probably needs next is
inlined, everything else stays reachable behind an id.

## Stable ids

| Id | Object |
| --- | --- |
| `ev:<seq>` (`ev:<session>:<seq>` across threads) | one event of a conversation |
| `turn:<turn id>` | the events of one turn |
| `thread:<session id>` | a chat thread, the lead's own included |
| `job_<hex>` / `job:<id>` | a row of the jobs ledger |
| `trg:<event id>` | a trigger event and what was decided about it |
| `artifact:<id>` | a page or deliverable a job produced |
| `agent:<id>` | a named agent |

## Inline and spill

In the lead's history (`agent_chat/recall.py`, used by the brain seat, the CLI
seat's catch-up block and fresh-start transcript):

- Every agent report and trigger notice carries its `ev:<seq>` id.
- A report nobody has answered yet is inlined whole, as before.
- Once an answer follows it, a report longer than 2,000 characters shrinks to a
  card: the first 700 characters plus `recall("ev:<seq>")` for the rest.
- Short reports, messages and the person's own words are never shortened.
- Conversation search hits carry the `ev:` id of the message.

Nothing is dropped: a spilled body stays in the event log and `recall` reads it
in 4,000-character pages (`more` is the next offset). The sizes decide only what
is pasted up front, not what the model may read.

## Chain of recall

`recall(id)` returns a summary, the key fields, the ids of the closest related
objects under `related`, and a `more` cursor for long content. Following those
ids hops from a message to the work it started and on to its result:

- a notice or report links to its trigger event, its job, its agent and thread;
- a trigger event links to its notice, the result of the routine it started and
  the other events of the same thread;
- a job links to its thread, its agent and its result (an artifact, or the
  report event);
- a thread links to its jobs, the thread that started it and the threads it
  started.

The re-read measure (`agent_chat/token_efficiency.py`) counts the notice cards,
so the saving shows in `reread` on the costs panel.
