"""Recognise a model server that refuses a request because it carries tools.

Local OpenAI-compatible servers only accept tool definitions when they were
started for it, and each says so in its own words:

* llama.cpp ``llama-server`` without ``--jinja``:
  "tools param requires --jinja flag" (older builds: "Unsupported param: tools").
* vLLM without ``--enable-auto-tool-choice``: '"auto" tool choice requires
  --enable-auto-tool-choice and --tool-call-parser to be set'.
* Ollama, for a model whose template has no tool support:
  "registry.ollama.ai/library/<model> does not support tools".

The phrases live here once so the voice/chat brains (which retry the turn
without tools) and the agent gateway (which explains the refusal to an agent
runtime) can never disagree about what counts as a tools refusal. Matching is
loose on purpose: every phrase is specific to tool support, so a false match
costs one tool-less answer, never a wrong action.
"""

from __future__ import annotations

from typing import Final

#: Lower-case fragments that only appear when a server refuses tools.
TOOLS_UNSUPPORTED_PHRASES: Final[tuple[str, ...]] = (
    # Ollama, and several gateways
    "does not support tools",
    "tools are not supported",
    "tool use is not supported",
    "does not support function calling",
    "function calling is not enabled",
    "tool calling is not supported",
    # llama.cpp llama-server
    "tools param requires --jinja",
    "tool_choice param requires --jinja",
    "unsupported param: tools",
    # vLLM
    "--enable-auto-tool-choice",
    "enable-auto-tool-choice",
    "--tool-call-parser",
)

_LLAMA_CPP_HINT: Final = (
    "llama.cpp: start llama-server with --jinja so it accepts tool definitions."
)
_VLLM_HINT: Final = (
    "vLLM: start the server with --enable-auto-tool-choice --tool-call-parser <parser> "
    "(hermes for Qwen models)."
)
_TEMPLATE_HINT: Final = (
    "The model's chat template declares no tool support; pick a model with tool "
    "calling to let it act."
)
_GENERIC_HINT: Final = (
    "The model server refused tool definitions; enable tool calling on the server "
    "or pick a model with tool support."
)


def is_tools_rejection(message: str) -> bool:
    """Whether an error text says the server cannot take tools."""
    text = (message or "").lower()
    return any(phrase in text for phrase in TOOLS_UNSUPPORTED_PHRASES)


def tools_rejection_hint(message: str) -> str | None:
    """The fix for a tools refusal (naming the missing server flag), else ``None``."""
    text = (message or "").lower()
    if not is_tools_rejection(text):
        return None
    if "jinja" in text or "unsupported param: tools" in text:
        return _LLAMA_CPP_HINT
    if "tool-choice" in text or "tool-call-parser" in text:
        return _VLLM_HINT
    if "does not support tools" in text:
        return _TEMPLATE_HINT
    return _GENERIC_HINT


__all__ = ["TOOLS_UNSUPPORTED_PHRASES", "is_tools_rejection", "tools_rejection_hint"]
