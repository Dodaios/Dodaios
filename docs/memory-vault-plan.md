# Personal memory vault — build plan

Decision: ADR-0044. Each chunk ships as its own pull request and leaves the
app working. Status 2026-11-09: chunks 1-6 done (#1093, #1098, #1126, #1160, #1168, #1198,
and the wiki removal).

| # | Chunk | Done when |
|---|-------|-----------|
| 1 | **Core store** — `dodaios/memory/vault/`: schema, add/supersede/forget/pin, search (FTS5 BM25 + entity + recency), history, profile block, audit, tombstones, `.mem` bundle + Markdown export, idempotent import | unit tests cover every write path and an export → import round trip |
| 2 | **Writes** — explicit remember/forget tools on the new store; one background extractor (candidate facts → nearest memories → ADD / UPDATE / INVALIDATE / NOOP) on the existing background provider chain and call cap; sensitivity rules; off switch per chat | a conversation that states, changes and revokes a fact leaves exactly the right current and closed rows |
| 3 | **Reads** — profile block in the cached system prompt, per-turn relevant memories in the turn context, `memory-search` / `memory-history` tools, the same block for the realtime and GPT-Live engines; replaces the wiki injector, identity card and core-memory block | the main bot answers "what do you know about me?" and "where did I live before?" from the store, in text and voice |
| 4 | **Import of today's memory** — one-time importer for the wiki vault pages, the learned notebooks, `core_memory.json` and `USER.md`; keeps a tar.gz of the old vault | a copy of the real vault imports with no secrets and no duplicates |
| 5 | **Memory section** — new UI: profile, all memories by kind, timeline of changes, edit / pin / forget, export and import buttons | visible in the running desktop app |
| 6 | **Removal** — delete the wiki subsystem, its routes, tools, Obsidian setup, Command Deck wiki graph, config sections and tests; move agent notebooks to `data/agents/` | suite green, no import of `dodaios.memory.wiki` left |

## Store layout (chunk 1)

- `data/memory/vault.db` — SQLite, WAL.
- `memory` rows are never updated in place except for `pinned`, use
  counters and closing (`valid_to`, `expired_at`). An edit is a new row that
  supersedes the old one.
- `current` = `expired_at IS NULL AND (valid_to IS NULL OR valid_to > now)`.
- `tombstone(id, content_hash, forgotten_at, reason)`: a forgotten memory's
  text is purged from `memory`, the FTS index and the audit log.

## Bundle format (`.mem`-compatible)

```
manifest.json            format, version, created_at, counts, app
items/<kind>.jsonl       one memory per line, all fields
entities.jsonl
audit/log.jsonl
audit/tombstones.jsonl   applied first on import
CHECKSUMS                sha256 per file
```

Import matches on `id`, then on `content_hash`, so the same bundle imported
twice changes nothing.

## The one endless conversation (2026-11-09)

Memory work for the lead's single endless conversation (the conversation
itself is `docs/plans/one-endless-lead-chat.md`, local only):

| Item | Where |
|---|---|
| Due dates on memories, `GET /upcoming`, coming-up grounding | `store.upcoming`, `runtime.dated_notes` |
| Pause learning (no temporary chats any more) | `PUT /pause`, Memory sidebar |
| Corrections and standing rules pin themselves | `reconcile` (`pin`, procedural only) |
| Per-message recall in realtime calls | `realtime/session.py::_voice_memory_recall` |
| Agents read preferences and standing instructions only | `runtime.agent_block`, `SocietyMemory.head` |
| One-time learning from the old chats | `vault/backfill.py` (30 calls max, resumable) |
| Daily merge of near-duplicates | `vault/consolidate.py` |
| Calendar appointments as short-lived memories | `vault/calendar_sync.py` (no model call, mail not read) |
| Compacted conversation parts become episodes | `vault/episodes.py`, hooked in `society.conversation.prepare_history` for the lead |

Learning keeps its triggers (5 minutes of quiet or 30 turns), which already
suit one conversation that never ends.
