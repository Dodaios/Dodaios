"""ChatGPT plan brain: turns on the user's ChatGPT plan via Sign in with ChatGPT.

Inference goes to the public Responses API (``api.openai.com/v1/responses``)
with the plan's access token from ``chatgpt_plan_auth``. Contract per turn:

* ``store: false`` and ``stream: true``; ``input`` carries the full history
  (no ``previous_response_id``); the system prompt goes in ``instructions``,
  never a ``role: "system"`` item;
* no sampling, metadata or hosted-tool fields: the plan route rejects them;
* only ``response.completed`` is success; a stream that ends without it fails;
* nothing is ever re-sent: once the request may have left, an unclear outcome
  is ``submission_ambiguous`` and the user decides;
* there is no API-key fallback. ``OPENAI_API_KEY`` is never read here.

Failures are ``ChatGPTPlanError`` with the server's code, HTTP status and
request id, so the UI can explain them (usage limit, ineligible account, ...).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

from jarvis.core.protocols import BrainDelta, BrainMessage, BrainRequest

from .chatgpt_plan_auth import RESOURCE, USAGE_URL, ChatGPTPlanError, auth

log = logging.getLogger(__name__)

RESPONSES_URL = f"{RESOURCE}/responses"
CLIENT_TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0)
_RETRY_DELAYS = (1.0, 3.0)

# User-facing explanations of the documented plan error codes.
_EXPLAIN = {
    "subscription_sharing_user_not_eligible": (
        "This ChatGPT account cannot share its plan with Dodaios."
    ),
    "subscription_sharing_usage_limit_exceeded": (
        f"Your ChatGPT plan's usage limit is reached; see {USAGE_URL}."
    ),
    "subscription_sharing_usage_unavailable": (
        "ChatGPT plan usage is temporarily unavailable; try again later."
    ),
    "subscription_sharing_unsupported_capability": (
        "The ChatGPT plan does not support part of this request."
    ),
    "subscription_sharing_route_not_supported": (
        "The ChatGPT plan does not support this request route."
    ),
    "subscription_sharing_invalid_user": "The ChatGPT sign-in is no longer valid; reauthorize.",
    "chatpass_v2_scope_not_authorized": "The sign-in lacks plan access; reauthorize and allow it.",
    "chatpass_v2_invalid_authorization_context": (
        "The sign-in is not valid for plan use; reauthorize."
    ),
    "subscription_sharing_user_unavailable": (
        "ChatGPT plan access is temporarily unavailable; try again later."
    ),
}
_RETRYABLE = frozenset(
    {"subscription_sharing_usage_unavailable", "subscription_sharing_user_unavailable"}
)


def _text_of(msg: BrainMessage) -> str:
    if isinstance(msg.content, str):
        return msg.content
    return "\n".join(
        block["text"]
        for block in msg.content
        if isinstance(block, dict) and isinstance(block.get("text"), str)
    )


def build_body(req: BrainRequest, model: str) -> dict[str, Any]:
    """The Responses request: full history, instructions, nothing optional."""
    items: list[dict[str, Any]] = []
    extra_system: list[str] = []
    for msg in req.messages:
        text = _text_of(msg)
        if not text:
            continue
        if msg.role == "system":
            extra_system.append(text)
        elif msg.role == "tool":
            # Text-only route: a stale tool result is context for the model.
            items.append({"role": "user", "content": f"[tool result]\n{text}"})
        else:
            items.append(
                {"role": "assistant" if msg.role == "assistant" else "user", "content": text}
            )
    body: dict[str, Any] = {"model": model, "input": items, "store": False, "stream": True}
    instructions = "\n\n".join(p for p in (req.system or "", *extra_system) if p)
    if instructions:
        body["instructions"] = instructions
    return body


def error_from(status: int, payload: Any, request_id: str | None) -> ChatGPTPlanError:
    """Map an admission or stream error, keeping status, code and request id."""
    err: Any = payload.get("error") if isinstance(payload, dict) else None
    code = message = param = ""
    if isinstance(err, dict):
        code, message, param = (
            str(err.get("code") or ""),
            str(err.get("message") or ""),
            str(err.get("param") or ""),
        )
    elif isinstance(payload, dict) and payload.get("detail"):
        message = str(payload["detail"])
    if code in _EXPLAIN:
        text = _EXPLAIN[code]
        if param:
            text = f"{text} ({param})"
    elif status == 401:
        code, text = (
            code or "unauthorized",
            "ChatGPT rejected the sign-in; check the account and reauthorize.",
        )
    elif status == 403:
        code, text = (
            code or "forbidden",
            f"ChatGPT refused the request: {message or 'permission denied'}.",
        )
    elif status == 429:
        code, text = (
            code or "rate_limited",
            f"ChatGPT is rate limiting this account; see {USAGE_URL}.",
        )
    elif status == 503:
        code, text = code or "unavailable", "ChatGPT is temporarily unavailable."
    else:
        code = code or "failed"
        text = f"ChatGPT plan error {status} {code}: {message}".strip()
    return ChatGPTPlanError(code, text, status=status, request_id=request_id)


class ChatGPTPlanBrain:
    name: str = "chatgpt-plan"
    context_window: int = 128_000
    supports_tools: bool = False
    supports_vision: bool = False

    def __init__(self, model: str | None = None) -> None:
        model = (model or "").strip()
        self._model = model.removeprefix("chatgpt-plan/")

    @staticmethod
    def subscription_connected() -> bool:
        """Signed in with plan scope: background work may run on this seat."""
        try:
            return auth().connected()
        except ChatGPTPlanError:
            return False

    def can_call_tools(self) -> bool:
        return False

    def estimate_cost(self, req: BrainRequest) -> float:
        return 0.0

    def _prepare(self) -> tuple[str, str]:
        a = auth()
        status = a.status()
        if not status["signed_in"]:
            raise ChatGPTPlanError("not_signed_in", "Sign in with ChatGPT on the Agents tab first.")
        if not status["plan_enabled"]:
            raise ChatGPTPlanError(
                "plan_scope_missing",
                "The ChatGPT sign-in did not grant plan access; reauthorize and allow it.",
            )
        token = a.access_token()
        model = self._model or status["model"]
        if not model:
            models = a.models()
            if not models:
                raise ChatGPTPlanError(
                    "no_models", "Your ChatGPT plan lists no models for Dodaios."
                )
            model = models[0]["slug"]
        return token, model

    async def complete(self, req: BrainRequest) -> AsyncIterator[BrainDelta]:
        token, model = await asyncio.to_thread(self._prepare)
        body = build_body(req, model)
        headers = {"Authorization": f"Bearer {token}", "Accept": "text/event-stream"}
        for attempt, delay in enumerate((0.0, *_RETRY_DELAYS)):
            if delay:
                await asyncio.sleep(delay)
            admitted = False
            finished = False
            try:
                async with httpx.AsyncClient(timeout=CLIENT_TIMEOUT) as client:
                    async with client.stream(
                        "POST", RESPONSES_URL, json=body, headers=headers
                    ) as resp:
                        if resp.status_code != 200:
                            raw = await resp.aread()
                            try:
                                payload = json.loads(raw)
                            except ValueError:  # a non-JSON error body still maps by status
                                payload = None
                            exc = error_from(
                                resp.status_code, payload, resp.headers.get("x-request-id")
                            )
                            # A 503 admission refusal was not processed: retrying is no resubmit.
                            if (
                                resp.status_code == 503 or exc.code in _RETRYABLE
                            ) and attempt < len(_RETRY_DELAYS):
                                log.info(
                                    "chatgpt-plan: %s, retrying (request %s)",
                                    exc.code,
                                    exc.request_id,
                                )
                                continue
                            raise exc
                        admitted = True
                        async for delta in _events(resp):
                            if delta.finish_reason:
                                finished = True
                            yield delta
            except ChatGPTPlanError:
                raise
            except httpx.ConnectError as exc:
                raise ChatGPTPlanError(
                    "network", "api.openai.com is not reachable; nothing was sent."
                ) from exc
            except httpx.HTTPError as exc:
                if admitted and not finished:
                    raise ChatGPTPlanError(
                        "submission_ambiguous",
                        "The connection to ChatGPT broke mid-answer; the message may have been "
                        "processed. It was not re-sent.",
                    ) from exc
                raise ChatGPTPlanError(
                    "submission_ambiguous",
                    "The request to ChatGPT failed after it may have been sent "
                    f"({type(exc).__name__}); it was not re-sent.",
                ) from exc
            if not finished:
                raise ChatGPTPlanError(
                    "incomplete_stream",
                    "ChatGPT ended the answer without completing it; it was not re-sent.",
                )
            return


async def _events(resp: httpx.Response) -> AsyncIterator[BrainDelta]:
    event = ""
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
            log.debug("chatgpt-plan: skipped an unparsable SSE line")
            continue
        kind = str(payload.get("type") or event)
        if kind == "response.output_text.delta":
            text = payload.get("delta")
            if isinstance(text, str) and text:
                yield BrainDelta(content=text)
        elif kind == "response.completed":
            yield BrainDelta(finish_reason="stop")
            return
        elif kind == "response.incomplete":
            reason = ((payload.get("response") or {}).get("incomplete_details") or {}).get("reason")
            if reason == "max_output_tokens":
                yield BrainDelta(finish_reason="length")
                return
            raise ChatGPTPlanError(
                "incomplete", f"ChatGPT stopped the answer early ({reason or 'unknown'})."
            )
        elif kind in ("response.failed", "error"):
            inner = (
                (payload.get("response") or {}).get("error")
                if kind == "response.failed"
                else payload.get("error", payload)
            )
            raise error_from(200, {"error": inner if isinstance(inner, dict) else {}}, None)
