# ADR-0044 — A personal memory vault replaces the wiki vault

**Status:** Accepted · **Date:** 2026-11-02

## Context

The main assistant's long-term memory is an Obsidian-style Markdown vault
(`wiki/obsidian-vault`, ADR-0013) written by a two-stage LLM curator that
rewrites whole pages, plus five side stores that grew next to it: the
learned notebooks (`society/jarvis/MEMORY.md`, `USER.md`), `core_memory.json`,
`data/workspace/USER.md`, the identity card and the contacts mirror. Six
stores, ~30k lines, and still no answer to "what do you know about me?", no
history of how a fact changed, and no export.

The patterns that make long-term memory in a personal assistant work, as
established in current memory research and practice:

1. **Atomic memories, not pages.** One sentence per memory, typed, with its
   source. A page is a view, never the unit of storage.
2. **A small profile always in the prompt, the rest searched per turn.**
3. **Supersede, never overwrite.** A changed fact closes the old one with a
   date (bi-temporal validity) instead of deleting it, so the assistant knows
   both "now" and "before".
4. **Write in the background, reconcile against what exists.** A candidate
   fact is compared with its nearest memories and becomes ADD, UPDATE,
   INVALIDATE or NOOP.
5. **The user sees and controls everything:** view, edit, pin, forget, a
   per-chat off switch.
6. **Portable.** No shared format has won; an open, portable layout works:
   a folder of JSONL per kind, a manifest, an audit log, tombstones applied
   first, checksums, content-derived ids so a re-import merges.

## Decision

1. **One store.** `dodaios/memory/vault/` owns the main assistant's
   long-term memory in one SQLite file, `data/memory/vault.db`, that belongs
   to the user. Tables: `memory`, `entity`, `memory_entity`, `audit`,
   `tombstone`, and an FTS5 index. Embeddings, when present, are an optional
   extra table; search works without them.
2. **The memory row.** `id`, `content_hash`, `kind`, `text` (one sentence),
   `entities`, `scope`, `valid_from`/`valid_to`, `recorded_at`/`expired_at`,
   `supersedes_id`, `origin` (user / inferred / imported), `source`,
   `confidence`, `sensitivity`, `pinned`, `use_count`, `last_used_at`.
   Kinds: `profile`, `preference`, `relationship`, `project`, `procedural`,
   `episode`, `reference`, `ephemeral`.
3. **Writes.** An explicit "remember / forget" is applied at once without a
   model call. Everything else goes through one background extractor that
   reconciles each candidate against the nearest current memories. Nothing
   is deleted unless the user asks; a forget leaves a tombstone and purges
   every derived copy.
4. **Reads.** A budgeted profile block (pinned, profile, preference,
   procedural, active projects) sits in the cached system prompt; a hybrid
   search adds the few memories relevant to the turn. Voice engines get the
   same profile block and the same search tool.
5. **Export and import.** A portable bundle (lossless) and a
   Markdown rendering (readable) from the Memory section; import is
   idempotent. The old vault, notebooks, core memory and USER.md are imported
   once, then the wiki subsystem is removed.
6. **Scope.** This ADR covers the main assistant. Agent notebooks keep their
   format and move out of the vault folder when the vault is removed.

Supersedes ADR-0013 (knowledge wiki) and ADR-0015 (Obsidian setup wizard)
once the removal chunk lands. The plan lives in
`docs/memory-vault-plan.md`.

## Consequences

- One place to look, one file to back up, one button to export.
- The Obsidian integration goes away. A Markdown export still opens in
  Obsidian, but it is a copy, not the store.
- Removing ~30k lines of wiki code and ~21k lines of its tests is done in a
  separate, last chunk, after the import has run on real data.
