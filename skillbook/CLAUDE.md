# Skillbook

Standalone side project (ACE learning loop, guardrails, CRDT peer sync); decisions live in `docs/adr/`.

- Write only under `skillbook/`. `wiki/obsidian-vault/` is off-limits.
- All storage goes through `memory_layer.store.MemoryStore`: tables prefixed `skb_`, database files under `skillbook/data/`.
- Dependency direction: `memory_layer` (stdlib + numpy) <- `guardrails` <- `ace_core`; `p2p_sync` -> `memory_layer`; `symcon_bridge` stdlib (+ optional `aiomqtt`). No cycles, no imports from `tests/`.
- Public interfaces are `Protocol`s, wire data is pydantic v2, internals are `@dataclass(slots=True, frozen=True)`; no ABCs.
- The LLM is a deterministic mock unless `ANTHROPIC_API_KEY` is set.
- No TODO, FIXME or NotImplementedError under `src/`.
- Done means `pytest skillbook/ -x -q --seeds=5` passes from the repo root.
