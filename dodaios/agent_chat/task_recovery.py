"""Notice an agent giving up after a recoverable tool failure.

This reads execution receipts, not the language of the assistant's answer.
It does not decide whether an arbitrary goal is complete, authorize an action,
or run a second model as a judge. The CLI runner may use its hint for ONE
continuation of the same request, on the same seat and with the same grants.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

_TERMINAL = (
    "blocked_by_policy",
    "approval_required",
    "permission_rejected",
    "approval_denied",
    "blacklist match",
    "actionblocked",
    "the person declined",
    "user denied",
    "user declined",
    "permission denied",
    "access denied",
    "access is denied",
    "unauthorized",
    "forbidden",
    "auth_failed",
    "authentication failed",
    "invalid api key",
    "invalid token",
    "not logged in",
    "not authenticated",
    "quota",
    "credit balance",
    "http 429",
    "usage limit",
    "rate limit",
    "rate-limited",
)
_DISCOVERY = frozenset({"toolsearch", "list_tools", "tools-list", "search_tools"})
# A call refused before it ran (its arguments did not parse or validate) had
# no effect and no target of its own: the next successful call of the same
# tool is its corrected retry.
_NOT_RUN = (
    "not valid json",
    "invalid json",
    "jsondecodeerror",
    "argument validation",
    "inputvalidationerror",
    "input validation error",
    "was not invoked",
    "invalid arguments",
    "invalid params",
    "invalid questions",
    "is a required property",
    "unexpected keyword argument",
)
# Meta tools that call another tool by name; a refused call names it only in
# its (unparsed) arguments, while the retry reports the inner tool itself.
_WRAPPERS = frozenset({"tool_call", "call_tool", "use_tool", "invoke_tool"})
_INNER_NAME = re.compile(r"""['"](?:name|tool|tool_name)['"]\s*:\s*['"]([\w.:/-]{1,160})['"]""")


def _bare(name: str) -> str:
    return name.rsplit("__", 1)[-1].lower()


def _names(name: str, arguments: Any) -> frozenset[str]:
    """The tool a call is about: itself, or for a meta tool the tools it names.

    A meta call that names its inner tools is only about them, so a later
    meta call of another tool does not settle it.
    """
    if _bare(name) not in _WRAPPERS:
        return frozenset({_bare(name)})
    inner: set[str] = set()
    values = arguments.values() if isinstance(arguments, dict) else [arguments]
    for value in values:
        raw = value if isinstance(value, str) else json.dumps(value, default=str)
        inner.update(_bare(found) for found in _INNER_NAME.findall(raw[:8000]))
    return frozenset(inner or {_bare(name)})


def blocks_automatic_recovery(text: str | None) -> bool:
    return any(marker in (text or "").lower() for marker in _TERMINAL)


@dataclass
class ToolRecovery:
    """A successful unrelated action cannot erase an unfinished part of a task.

    A success of the same action settles its failure, and a success of the
    same tool settles a call of that tool that was refused before it ran.
    """

    calls: dict[str, tuple[str, str]] = field(default_factory=dict)
    unresolved: dict[tuple[str, str], str] = field(default_factory=dict)
    #: Failed calls that never ran (malformed arguments), with the tools they named.
    not_run: dict[tuple[str, str], frozenset[str]] = field(default_factory=dict)
    names: dict[str, frozenset[str]] = field(default_factory=dict)
    declined: bool = False
    blocked: bool = False
    had_tool_calls: bool = False

    def observe(self, event: dict[str, Any]) -> None:
        payload = event.get("payload") or {}
        call_id = str(payload.get("call_id") or "")
        if event.get("kind") == "tool_call":
            self.had_tool_calls = True
            arguments = json.dumps(payload.get("input") or {}, sort_keys=True, default=str)
            self.calls[call_id] = (
                str(payload.get("name") or "tool"),
                hashlib.sha256(arguments.encode("utf-8")).hexdigest(),
            )
            self.names[call_id] = _names(self.calls[call_id][0], payload.get("input"))
            return
        if event.get("kind") != "tool_result":
            return
        key = self.calls.pop(call_id, (str(payload.get("name") or "tool"), call_id))
        name = key[0]
        names = self.names.pop(call_id, frozenset({_bare(name)}))
        # Descriptions, provider bodies and retrieved instructions are never
        # copied into a recovery prompt. Only a registered tool name and a
        # fixed diagnostic code can cross that boundary.
        raw = payload.get("output")
        text = raw if isinstance(raw, str) else json.dumps(raw, default=str)
        text = text[:8000]
        discovery = _bare(name) in _DISCOVERY
        missing = discovery and text.lstrip().startswith("No matching deferred tools found")
        if payload.get("is_error") or missing:
            if blocks_automatic_recovery(text):
                self.blocked = True
                self.unresolved.pop(key, None)
            else:
                self.unresolved[key] = "discovery_empty" if missing else "tool_failed"
                low = text.lower()
                if any(marker in low for marker in _NOT_RUN):
                    self.not_run[key] = names
                else:
                    self.not_run.pop(key, None)
        else:
            self.unresolved.pop(key, None)
            # The corrected retry settles every refused call of the same tool.
            for stale in [k for k, named in self.not_run.items() if named & names]:
                self.not_run.pop(stale, None)
                self.unresolved.pop(stale, None)

    def hint(self) -> str | None:
        if self.declined or self.blocked or not self.unresolved:
            return None
        failures = ", ".join(
            f"{reason} for {re.sub(r'[^a-zA-Z0-9_.:/-]', '_', key[0])[:160]}"
            for key, reason in list(self.unresolved.items())[:3]
        )
        return (
            f"The execution receipts contain unresolved failures: {failures}. "
            "A successful unrelated action does not prove every requested outcome. "
            "Check ALL parts of the original request before ending. An alternative may "
            "already have completed the task: verify that evidence without repeating "
            "completed actions, and finish if all outcomes are satisfied. "
            "Inspect the actual available tools and the current state, then use a supported "
            "path if one exists. Do not repeat an identical failed lookup. A failed write "
            "may already have taken effect: read back before repeating it. A user denial, "
            "policy block, missing login or exhausted subscription is not permission to "
            "bypass the restriction, change credentials, or switch to a paid API. "
            "If a real blocker remains, explain the unfinished part and the specific "
            "prerequisite. This is the only automatic continuation of this turn."
        )
