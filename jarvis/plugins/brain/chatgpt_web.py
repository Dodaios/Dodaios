"""ChatGPT web brain: the normal chat on the user's ChatGPT subscription.

Talks to the local ChatGPT web bridge (see ``chatgpt_web_bridge``) over its
loopback Responses API. It needs no API key and spends no Codex quota: each
turn is one message in the user's own ChatGPT web session.

Contract per turn:

* conversation id ``dodaios:<chat session id>``: a continued chat reuses its
  ChatGPT conversation, a new chat gets a new one;
* an idempotency key per turn, so the bridge itself drops a duplicate send;
* streamed text over SSE; closing the stream aborts the turn;
* typed failures (``ChatGPTWebError.code``): ``login_required``, ``offline``,
  ``session_invalid``, ``bridge_unavailable``, ``submission_ambiguous``.
  Nothing is ever re-sent automatically: once the request left, an unclear
  outcome is ``submission_ambiguous`` and the user decides.

The bridge accepts no tool schemas, so this brain is text-only.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from jarvis.core.protocols import BrainDelta, BrainMessage, BrainRequest

from .chatgpt_web_bridge import (
    ChatGPTWebError,
    bridge_token,
    is_loopback,
    settings,
    supervisor,
)

log = logging.getLogger(__name__)

DEFAULT_MODEL = "chatgpt-web/instant"
CLIENT_TIMEOUT = httpx.Timeout(connect=3.0, read=300.0, write=30.0, pool=10.0)
_UNSAFE_ID_CHARS = re.compile(r"[^A-Za-z0-9_.:-]")
# Every turn is typed into the ChatGPT web composer, so prompt size is answer
# latency. The full Jarvis prompt (~59k characters) is mostly tool guidance
# this text-only brain cannot use: keep the persona head and recent turns.
MAX_SYSTEM_CHARS = 8_000
MAX_HISTORY_MESSAGES = 12
MAX_MESSAGE_CHARS = 4_000


def conversation_id(session_id: str | None) -> str:
    """``dodaios:<session>``, clipped to the bridge's 128-character id limit."""
    raw = _UNSAFE_ID_CHARS.sub("-", (session_id or "").strip()) or uuid.uuid4().hex
    return f"dodaios:{raw}"[:128]


def idempotency_key(turn_id: str | None, body: dict[str, Any]) -> str:
    digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return f"dodaios-{turn_id or uuid.uuid4().hex}-{digest}"[:200]


# ---- self / clarify / delegate -------------------------------------------

RouteKind = Literal["self", "clarify", "delegate"]
_DELEGATE_TARGETS = frozenset({"codex", "claude"})


@dataclass(frozen=True)
class RouteDecision:
    kind: RouteKind
    text: str
    target: str | None = None


def parse_route_decision(reply: str) -> RouteDecision:
    """Read an optional JSON routing envelope from a chat reply, defensively.

    Only a complete, well-formed object with ``"route"`` in
    {self, clarify, delegate} counts, and ``delegate`` additionally needs a
    known ``target`` and a non-empty ``task``. Anything else (prose, broken
    JSON, unknown route or target) is the reply itself, answered by ``self``.
    A badly parsed reply therefore never delegates.
    """
    text = (reply or "").strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else text
    if not (candidate.startswith("{") and candidate.endswith("}")):
        return RouteDecision("self", reply)
    try:
        data = json.loads(candidate)
    except ValueError:  # not JSON: the reply is prose, answered by self
        return RouteDecision("self", reply)
    if not isinstance(data, dict):
        return RouteDecision("self", reply)
    route = data.get("route")
    body = data.get("task") if route == "delegate" else data.get("text")
    if not isinstance(body, str) or not body.strip():
        return RouteDecision("self", reply)
    if route == "delegate":
        target = data.get("target")
        if target not in _DELEGATE_TARGETS:
            return RouteDecision("self", reply)
        return RouteDecision("delegate", body.strip(), target)
    if route in ("self", "clarify"):
        return RouteDecision(route, body.strip())
    return RouteDecision("self", reply)


# ---- request shaping -----------------------------------------------------


def _text_of(msg: BrainMessage) -> str:
    if isinstance(msg.content, str):
        return msg.content
    parts = []
    for block in msg.content:
        if isinstance(block, dict) and isinstance(block.get("text"), str):
            parts.append(block["text"])
    return "\n".join(parts)


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit].rstrip() + "\n[…]"


def _input_items(req: BrainRequest) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if req.system:
        items.append(
            {"type": "message", "role": "system", "content": _clip(req.system, MAX_SYSTEM_CHARS)}
        )
    for msg in req.messages[-MAX_HISTORY_MESSAGES:]:
        if msg.role == "tool":
            # No tools on this bridge; a stale tool result is context text.
            note = f"[tool result]\n{_clip(_text_of(msg), MAX_MESSAGE_CHARS)}"
            items.append({"type": "message", "role": "user", "content": note})
            continue
        text = _clip(_text_of(msg), MAX_MESSAGE_CHARS)
        if text:
            items.append({"type": "message", "role": msg.role, "content": text})
    return items


def _error_from_body(status: int, payload: Any) -> ChatGPTWebError:
    err = payload.get("error") if isinstance(payload, dict) else None
    code = str((err or {}).get("code") or "") if isinstance(err, dict) else ""
    message = str((err or {}).get("message") or "") if isinstance(err, dict) else ""
    if code == "chatgpt_session_expired":
        supervisor.mark_session_invalid()
        return ChatGPTWebError("session_invalid", "The ChatGPT session expired; sign in again.")
    if status == 401 or code == "invalid_api_key":
        return ChatGPTWebError(
            "bridge_unavailable", "The bridge rejected the Dodaios access token."
        )
    if status == 503:
        return ChatGPTWebError("login_required", "Sign in to ChatGPT in the bridge browser.")
    return ChatGPTWebError("failed", f"ChatGPT bridge error {status} {code}: {message}".strip())


class ChatGPTWebBrain:
    name: str = "chatgpt-web"
    context_window: int = 128_000
    supports_tools: bool = False
    supports_vision: bool = False

    def __init__(self, model: str | None = None) -> None:
        self._model = (model or "").strip() or DEFAULT_MODEL
        if not self._model.startswith("chatgpt-web/"):
            self._model = DEFAULT_MODEL

    @staticmethod
    def subscription_connected() -> bool:
        """Never a background seat: each turn is a message in the user's own
        ChatGPT web conversation, so only a turn the user sends may use it.
        A provider the user selects explicitly does not ask this probe."""
        return False

    def can_call_tools(self) -> bool:
        return False

    def estimate_cost(self, req: BrainRequest) -> float:
        return 0.0

    def _prepare(self) -> tuple[str, str]:
        s = settings()
        if not is_loopback(s.base_url):
            raise ChatGPTWebError("failed", "The ChatGPT bridge URL must be a loopback address.")
        state = supervisor.ensure_running()
        if state.status == "login_required":
            raise ChatGPTWebError("login_required", state.detail)
        if state.status == "session_invalid":
            raise ChatGPTWebError("session_invalid", state.detail)
        if state.status in ("offline", "starting"):
            raise ChatGPTWebError("offline", state.detail)
        if state.status != "ready":
            raise ChatGPTWebError("bridge_unavailable", state.detail)
        token = bridge_token(s)
        if not token:
            raise ChatGPTWebError("bridge_unavailable", "The ChatGPT bridge has no access token.")
        return s.base_url, token

    async def complete(self, req: BrainRequest) -> AsyncIterator[BrainDelta]:
        import asyncio  # noqa: PLC0415 — only for the blocking supervisor probe

        from jarvis.core.chat_turn import current_chat_turn  # noqa: PLC0415

        root, token = await asyncio.to_thread(self._prepare)
        turn = current_chat_turn.get()
        body = {"model": self._model, "input": _input_items(req), "stream": True}
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "text/event-stream",
            "x-chatgpt-web-conversation-id": conversation_id(turn.session_id if turn else None),
            "x-idempotency-key": idempotency_key(turn.turn_id if turn else None, body),
        }
        sent = False
        finished = False
        try:
            async with httpx.AsyncClient(timeout=CLIENT_TIMEOUT) as client:
                async with client.stream(
                    "POST", f"{root}/v1/responses", json=body, headers=headers
                ) as resp:
                    sent = True
                    if resp.status_code != 200:
                        raw = await resp.aread()
                        try:
                            payload = json.loads(raw)
                        except ValueError:  # a non-JSON error body still maps by status code
                            payload = None
                        raise _error_from_body(resp.status_code, payload)
                    async for delta in self._events(resp):
                        if delta.finish_reason:
                            finished = True
                        yield delta
        except ChatGPTWebError:
            raise
        except httpx.ConnectError as exc:
            raise ChatGPTWebError("offline", "The ChatGPT bridge is not reachable.") from exc
        except httpx.HTTPError as exc:
            if sent and not finished:
                raise ChatGPTWebError(
                    "submission_ambiguous",
                    "The connection to ChatGPT broke mid-answer; the message may have "
                    "been sent. It was not re-sent.",
                ) from exc
            raise ChatGPTWebError(
                "bridge_unavailable", f"ChatGPT bridge request failed: {exc}"
            ) from exc
        if sent and not finished:
            raise ChatGPTWebError(
                "submission_ambiguous",
                "ChatGPT ended the answer without completing it; it was not re-sent.",
            )

    async def _events(self, resp: httpx.Response) -> AsyncIterator[BrainDelta]:
        event = ""
        # The bridge's own status notes arrive as "commentary" messages; only
        # the model's answer is shown to the user.
        commentary: set[str] = set()
        async for line in resp.aiter_lines():
            if line.startswith("event:"):
                event = line[6:].strip()
                continue
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data or data == "[DONE]":
                continue
            try:
                payload = json.loads(data)
            except ValueError:
                log.debug("chatgpt-web: skipped an unparsable SSE line")
                continue
            kind = str(payload.get("type") or event)
            if kind == "response.output_item.added":
                item = payload.get("item")
                if isinstance(item, dict) and item.get("phase") == "commentary":
                    commentary.add(str(item.get("id")))
            elif kind == "response.output_text.delta":
                if str(payload.get("item_id")) in commentary:
                    continue
                text = payload.get("delta")
                if isinstance(text, str) and text:
                    yield BrainDelta(content=text)
            elif kind == "response.completed":
                yield BrainDelta(finish_reason="stop")
                return
            elif kind == "response.incomplete":
                yield BrainDelta(finish_reason="length")
                return
            elif kind in ("response.failed", "error"):
                if kind == "response.failed":
                    inner = (payload.get("response") or {}).get("error")
                else:
                    inner = payload.get("error", payload)
                raise _error_from_body(200, {"error": inner if isinstance(inner, dict) else {}})
