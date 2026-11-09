"""memory-search and memory-forget: the assistant's hands on the memory vault.

``memory-search`` finds what the vault knows beyond the always-on profile
block (episodes, older versions, sensitive memories). ``memory-forget``
erases a memory and all its versions when the user asks for it.

Risk tier: safe; both only touch the local vault file.
"""

from __future__ import annotations

import asyncio
from typing import Any

from dodaios.core.protocols import ExecutionContext, ToolResult


def _vault() -> Any:
    from dodaios.memory.vault.runtime import active

    return active()


def _conversation(query: str, limit: int) -> list[dict[str, Any]]:
    try:
        from dodaios.agent_chat.lead import search_conversation

        return search_conversation(query, limit=min(limit, 6))
    except Exception:  # noqa: BLE001 — the conversation is extra; memory still answers
        return []


def _describe(memory: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": memory.id,
        "kind": memory.kind,
        "text": memory.text,
        "since": (memory.valid_from or "")[:10],
    }
    if memory.valid_to:
        row["until"] = memory.valid_to[:10]
    if memory.expired_at:
        row["replaced"] = True
    return row


class MemorySearchTool:
    name: str = "memory-search"
    risk_tier: str = "safe"
    description: str = (
        "Search the user's long-term memory (facts, preferences, people, projects, "
        "past events) and what was said earlier in your conversation with the user, "
        "beyond what your instructions already list. Use it before saying you do not "
        "know something personal or do not remember an earlier talk. Set history=true "
        "for how something changed over time (e.g. where the user lived before)."
    )
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Keywords or a short question."},
            "history": {
                "type": "boolean",
                "description": "Include replaced and ended memories.",
                "default": False,
            },
            "limit": {"type": "integer", "default": 8, "minimum": 1, "maximum": 20},
        },
        "required": ["query"],
    }

    async def execute(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        vault = _vault()
        query = str(args.get("query") or "").strip()
        if not query:
            return ToolResult(success=False, output=None, error="query is missing")
        limit = max(1, min(20, int(args.get("limit") or 8)))
        history = bool(args.get("history"))

        def _run() -> list[dict[str, Any]]:
            if vault is None:
                return []
            hits = vault.search(query, limit=limit, include_closed=history)
            vault.mark_used(h.memory.id for h in hits if not h.memory.expired_at)
            return [_describe(h.memory) for h in hits]

        rows = await asyncio.to_thread(_run)
        said = await asyncio.to_thread(_conversation, query, limit)
        if vault is None and not said:
            return ToolResult(success=False, output=None, error="memory is not running")
        if not rows and not said:
            return ToolResult(success=True, output=f"Nothing in memory matches {query!r}.")
        output: dict[str, Any] = {"memories": rows}
        if said:
            # Earlier in the one endless conversation (agent_chat/lead.py).
            output["conversation"] = said
        return ToolResult(success=True, output=output)


class MemoryForgetTool:
    name: str = "memory-forget"
    risk_tier: str = "safe"
    description: str = (
        "Erase something from the user's long-term memory when they ask you to "
        "forget it. Pass the id from memory-search, or a description; with a "
        "description only a clear single match is erased, otherwise the candidates "
        "are returned so you can ask which one."
    )
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "Memory id from memory-search."},
            "about": {"type": "string", "description": "What to forget, in words."},
        },
    }

    async def execute(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        from dodaios.memory.vault.runtime import changed

        vault = _vault()
        if vault is None:
            return ToolResult(success=False, output=None, error="memory is not running")
        memory_id = str(args.get("id") or "").strip()
        about = str(args.get("about") or "").strip()
        if not memory_id and not about:
            return ToolResult(success=False, output=None, error="pass id or about")

        def _run() -> ToolResult:
            target = vault.get(memory_id) if memory_id else None
            if target is None and about:
                hits = vault.search(about, limit=5)
                clear = len(hits) == 1 or (len(hits) > 1 and hits[0].score >= 2 * hits[1].score)
                if not hits:
                    return ToolResult(success=True, output=f"Nothing in memory about {about!r}.")
                if not clear:
                    return ToolResult(
                        success=True,
                        output={
                            "ambiguous": True,
                            "candidates": [_describe(h.memory) for h in hits],
                        },
                    )
                target = hits[0].memory
            if target is None:
                return ToolResult(success=False, output=None, error=f"no memory {memory_id!r}")
            count = vault.forget(target.id, reason="user asked to forget")
            changed()
            return ToolResult(success=True, output=f"Forgot: {target.text} ({count} version(s)).")

        return await asyncio.to_thread(_run)
