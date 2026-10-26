"""The unattended ask-queue (MASTERPLAN §2.9, agent-definition §3.4).

An action an agent may not run on its own — above its permission ceiling,
or matched by one of its ``require_approval`` rules — lands here as data.
The chat card, the world's gate, the Jarvis bar badge and voice are
projections of this table. Expiry NEVER drops work: an expired item flips
to ``blocked`` and re-surfaces on the next app focus or voice turn until a
person decides.

Rule evaluation (``decide``), in order: global blacklist (not here — the
ToolExecutor raises before anything), the agent's ``require_approval``
patterns (queue), its explicit approval mode, then the legacy
``always_allow`` patterns and risk ceiling. Bypass still blocks actions above
an inherited ceiling; Always ask queues even safe reads.
Patterns are capability ids (``plugin:gmail``), ``capability:verb``
(``plugin:gmail:send``) or ``capability:*``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

from dodaios.missions.ids import uuid7_str

from .events import ApprovalState, MsgType, PermissionCeiling, SocietyEnvelope, now_ms
from .roster import AgentRecord
from .store import SocietyStore

log = logging.getLogger(__name__)

__all__ = [
    "RULE_BREADTHS",
    "RULE_KINDS",
    "Approval",
    "Approvals",
    "Verdict",
    "apply_rule",
    "card_rule",
    "decide",
    "matches",
    "rule_text",
    "save_card_rule",
]

DEFAULT_TTL_MS: Final[int] = 24 * 60 * 60 * 1000
_TIER_RANK: Final[dict[str, int]] = {"safe": 0, "monitor": 1, "ask": 2, "block": 3}


class Verdict(StrEnum):
    RUN = "run"
    QUEUE = "queue"
    BLOCK = "block"


def matches(pattern: str, capability_id: str, verb: str = "") -> bool:
    """``plugin:gmail`` matches the capability; ``plugin:gmail:send`` one verb;
    ``plugin:gmail:*`` every verb; ``plugin:*`` every plugin."""
    pattern = pattern.strip()
    if not pattern:
        return False
    if pattern == capability_id:
        return True
    if pattern.endswith(":*"):
        prefix = pattern[:-2]
        return capability_id == prefix or capability_id.startswith(prefix + ":")
    if verb and pattern == f"{capability_id}:{verb}":
        return True
    return False


def decide(
    agent: AgentRecord,
    capability_id: str,
    tool_tier: str,
    *,
    verb: str = "",
    approval_mode: str | None = None,
) -> Verdict:
    """What happens to one intended action under the bound chat's mode."""
    if tool_tier == "block":
        return Verdict.BLOCK
    rules = agent.approval_rules
    if any(matches(p, capability_id, verb) for p in rules.get("require_approval", [])):
        return Verdict.QUEUE
    mode = (
        approval_mode
        if approval_mode is not None
        else str(agent.approval_mode) if agent.approval_mode is not None else ""
    )
    if mode == "always_ask":
        return Verdict.QUEUE
    if any(matches(p, capability_id, verb) for p in rules.get("always_allow", [])):
        # The person's explicit standing yes can authorize this action up to
        # the ask tier. Always ask above intentionally ignores standing yes.
        return Verdict.RUN if _TIER_RANK.get(tool_tier, 1) <= 2 else Verdict.QUEUE
    if mode == "bypass":
        # Bypass removes prompts, not an inherited risk ceiling. An action
        # above that ceiling is denied instead of being silently escalated.
        if _TIER_RANK.get(tool_tier, 1) > _TIER_RANK[str(agent.permission_ceiling)]:
            return Verdict.BLOCK
        return Verdict.RUN
    if mode == "ask":
        return Verdict.RUN if tool_tier == "safe" else Verdict.QUEUE
    ceiling = _TIER_RANK[str(agent.permission_ceiling)]
    tier = _TIER_RANK.get(tool_tier, 1)
    if tier <= ceiling and tool_tier != str(PermissionCeiling.ASK):
        return Verdict.RUN
    return Verdict.QUEUE


@dataclass(slots=True)
class Approval:
    id: str
    agent_id: str
    trace_id: str
    capability: str
    action: dict[str, Any]
    summary: str
    state: ApprovalState
    created_ms: int
    expires_ms: int
    resolved_ms: int | None
    note: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "trace_id": self.trace_id,
            "capability": self.capability,
            "action": self.action,
            "summary": self.summary,
            "state": str(self.state),
            "created_ms": self.created_ms,
            "expires_ms": self.expires_ms,
            "resolved_ms": self.resolved_ms,
            "note": self.note,
        }

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Approval:
        try:
            action = json.loads(row.get("action_json") or "{}")
        except ValueError:
            action = {}
        return cls(
            id=str(row["id"]),
            agent_id=str(row["agent_id"]),
            trace_id=str(row.get("trace_id") or ""),
            capability=str(row.get("capability") or ""),
            action=action if isinstance(action, dict) else {},
            summary=str(row.get("summary") or ""),
            state=ApprovalState(str(row.get("state") or "pending")),
            created_ms=int(row.get("created_ms") or 0),
            expires_ms=int(row.get("expires_ms") or 0),
            resolved_ms=row.get("resolved_ms"),
            note=str(row.get("note") or ""),
        )


class Approvals:
    def __init__(self, store: SocietyStore, *, ttl_ms: int = DEFAULT_TTL_MS) -> None:
        self._store = store
        self._ttl = ttl_ms

    async def enqueue(
        self,
        *,
        agent_id: str,
        trace_id: str,
        capability: str,
        action: dict[str, Any],
        summary: str,
    ) -> Approval:
        now = now_ms()
        approval_id = uuid7_str()
        await self._store.insert_approval(
            {
                "id": approval_id,
                "agent_id": agent_id,
                "trace_id": trace_id,
                "capability": capability,
                "action_json": json.dumps(action, ensure_ascii=False),
                "summary": summary[:500],
                "state": str(ApprovalState.PENDING),
                "created_ms": now,
                "expires_ms": now + self._ttl,
                "resolved_ms": None,
                "note": "",
            }
        )
        await self._store.append_and_publish(
            SocietyEnvelope(
                msg_type=MsgType.HOLD,
                from_agent=agent_id,
                to_agent="user",
                trace_id=trace_id,
                payload={
                    "approval_id": approval_id,
                    "capability": capability,
                    "text": summary[:500],
                },
            )
        )
        got = await self.get(approval_id)
        assert got is not None
        return got

    async def get(self, approval_id: str) -> Approval | None:
        row = await self._store.get_approval_row(approval_id)
        return Approval.from_row(row) if row else None

    async def items(
        self, *, state: ApprovalState | None = None, agent_id: str | None = None
    ) -> list[Approval]:
        rows = await self._store.list_approval_rows(
            state=str(state) if state else None, agent_id=agent_id
        )
        return [Approval.from_row(r) for r in rows]

    async def pending(self) -> list[Approval]:
        """Everything a person still has to decide — pending AND blocked."""
        pending = await self.items(state=ApprovalState.PENDING)
        blocked = await self.items(state=ApprovalState.BLOCKED)
        return sorted(pending + blocked, key=lambda a: a.created_ms)

    async def resolve(self, approval_id: str, *, approve: bool, note: str = "") -> Approval:
        current = await self.get(approval_id)
        if current is None:
            raise KeyError(approval_id)
        if current.state in (ApprovalState.APPROVED, ApprovalState.DENIED):
            return current
        state = ApprovalState.APPROVED if approve else ApprovalState.DENIED
        await self._store.update_approval(
            approval_id,
            {"state": str(state), "resolved_ms": now_ms(), "note": note[:500]},
        )
        await self._store.append_and_publish(
            SocietyEnvelope(
                msg_type=MsgType.RELEASE if approve else MsgType.VETO,
                from_agent="user",
                # Inline workers already await this row. A RELEASE addressed to
                # the agent would enqueue an extra chat turn and repeat the task.
                to_agent="user" if current.action.get("resume_in_place") else current.agent_id,
                trace_id=current.trace_id,
                payload={
                    "approval_id": approval_id,
                    "capability": current.capability,
                    "agent_id": current.agent_id,
                    "approved": approve,
                    "text": note or ("approved" if approve else "denied"),
                    **({"reason": "blocked_by_policy"} if not approve else {}),
                },
            )
        )
        got = await self.get(approval_id)
        assert got is not None
        return got

    async def expire_due(self, *, now: int | None = None) -> int:
        """Pending items past their expiry become ``blocked`` — parked, never
        dropped. Returns how many flipped."""
        now = now if now is not None else now_ms()
        flipped = 0
        for item in await self.items(state=ApprovalState.PENDING):
            if item.expires_ms <= now:
                await self._store.update_approval(item.id, {"state": str(ApprovalState.BLOCKED)})
                flipped += 1
        return flipped

    async def resurface(self) -> list[Approval]:
        """On app focus / a voice turn: blocked items become pending again with
        a fresh expiry, so the person is asked once more."""
        revived: list[Approval] = []
        for item in await self.items(state=ApprovalState.BLOCKED):
            await self._store.update_approval(
                item.id, {"state": str(ApprovalState.PENDING), "expires_ms": now_ms() + self._ttl}
            )
            got = await self.get(item.id)
            if got is not None:
                revived.append(got)
        return revived


# ------------------------------------------------------------ rules from the card
#
# The chat's approval card can turn one answer into a standing rule on the
# agent's own ``approval_rules`` (``always_allow`` / ``require_approval``). The
# patterns stay the source of truth: a rule's readable text is derived from its
# pattern for display, never stored. Nothing below changes ``decide()``.

#: The two lists a card may write to.
RULE_KINDS: Final[tuple[str, ...]] = ("always_allow", "require_approval")
#: ``action``: only this verb of the app (``plugin:gmail:send``); ``app``: every
#: action of the app (``plugin:gmail``).
RULE_BREADTHS: Final[tuple[str, ...]] = ("action", "app")


def card_rule(tool_name: str, args: dict[str, Any]) -> dict[str, str] | None:
    """The rule an approval card for this call can save on the agent, if any.

    Only a tool the agent's own rules govern qualifies: one of the capability
    catalog's rows, reached bare or through this app's MCP server. A runtime's
    or another server's own tool (Claude's ``Bash``, an ACP terminal) answers
    ``None``; its "always" stays the runtime's business.
    """
    from dodaios.agent_chat.approval_card import action_verb, app_label
    from dodaios.core.mcp_names import own_cli_tool

    from .capabilities import capability_id_for_tool
    from .runtime import current_runtime

    if tool_name.startswith("mcp__") and own_cli_tool(tool_name) is None:
        return None
    bare = own_cli_tool(tool_name) or tool_name
    capability = capability_id_for_tool(bare)
    rt = current_runtime()
    if capability is None or rt is None:
        return None
    try:
        rows = rt.catalog()
    except Exception:  # noqa: BLE001 — no catalog, no rule offer; the card still asks
        log.warning("approval card: capability catalog unavailable", exc_info=True)
        return None
    row = next((r for r in rows if r.id == capability), None)
    if row is None:
        return None
    verb = action_verb(args)
    return {
        "capability": capability,
        "app": app_label(row.label or bare),
        "verb": verb,
        "pattern": f"{capability}:{verb}" if verb else capability,
        "broad": capability,
    }


def rule_text(kind: str, app: str, verb: str = "") -> str:
    """A rule as a sentence, for logs and notices (the card localizes its own)."""
    what = f"{verb} with {app}" if verb else app
    if kind == "require_approval":
        return f"Ask first before {what}"
    return f"Always allow {what}"


def apply_rule(rules: dict[str, list[str]], kind: str, pattern: str) -> dict[str, list[str]]:
    """``rules`` with ``pattern`` added to ``kind`` and taken out of the other list.

    A person who says "always allow" for exactly this pattern withdraws the
    same "ask first", and the other way round. A broader opposite pattern is
    left alone: :func:`decide` still reads ``require_approval`` first.
    """
    if kind not in RULE_KINDS:
        raise ValueError(f"kind must be one of {RULE_KINDS}")
    other = "require_approval" if kind == "always_allow" else "always_allow"
    out = {
        "require_approval": list(rules.get("require_approval", [])),
        "always_allow": list(rules.get("always_allow", [])),
    }
    if pattern not in out[kind]:
        out[kind] = sorted([*out[kind], pattern])
    out[other] = [p for p in out[other] if p != pattern]
    return out


async def save_card_rule(
    session_id: str, tool_name: str, args: dict[str, Any], *, kind: str, breadth: str = "action"
) -> dict[str, Any] | None:
    """Write a rule from the approval card onto the society agent of ``session_id``.

    Returns ``{kind, pattern, app, verb, text, still_asks}`` or ``None`` when no
    rule fits (not a society chat, not an agent's own tool). ``still_asks`` is
    true when a broader ``require_approval`` keeps asking anyway.
    """
    from .runtime import current_runtime
    from .surface import agent_id_of

    if kind not in RULE_KINDS or breadth not in RULE_BREADTHS:
        raise ValueError("unknown rule kind or breadth")
    rt = current_runtime()
    agent_id = agent_id_of(session_id)
    offer = card_rule(tool_name, args)
    if rt is None or agent_id is None or offer is None:
        return None
    agent = await rt.roster.get(agent_id)
    if agent is None:
        return None
    pattern = offer["broad"] if breadth == "app" else offer["pattern"]
    verb = "" if breadth == "app" else offer["verb"]
    rules = apply_rule(agent.approval_rules, kind, pattern)
    if rules != agent.approval_rules:
        updated = await rt.roster.update(agent.agent_id, {"approval_rules": rules})
        rt.cache_agent(updated)
    still_asks = kind == "always_allow" and any(
        matches(p, offer["capability"], offer["verb"]) for p in rules["require_approval"]
    )
    return {
        "kind": kind,
        "pattern": pattern,
        "app": offer["app"],
        "verb": verb,
        "text": rule_text(kind, offer["app"], verb),
        "still_asks": still_asks,
    }
