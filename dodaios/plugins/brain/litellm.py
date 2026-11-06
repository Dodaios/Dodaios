"""LiteLLM proxy — an OpenAI-compatible gateway you host.

One proxy key and a base URL reach every model that proxy is configured to
serve (the same shape as OpenRouter, except the host is yours). Model names
are the proxy's own aliases, so a model-less brain asks the proxy which
chat models it has and uses the first one the picker would show.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Any

from dodaios.core import config as cfg
from dodaios.core.protocols import BrainDelta, BrainRequest

from ._openai_base import CLIENT_TIMEOUT, stream_complete

log = logging.getLogger(__name__)

# LiteLLM's default listen address, in the OpenAI-client form (the SDK appends
# ``/chat/completions``). A pasted root without ``/v1`` also works: the proxy
# serves both. An explicit ``[brain.providers.litellm].base_url`` replaces this.
BASE_URL = "http://localhost:4000/v1"

# Until the proxy says how big the loaded model is. A 128k guess sends the
# full tool list and a small local model refuses the turn.
_UNPUBLISHED_WINDOW = 32_768


def openai_client_base(url: str) -> str:
    """The OpenAI client base: ``…/v1``, added when a pasted host omitted it.

    A proxy people paste as ``https://llm.example`` serves chat at
    ``/v1/chat/completions``. Leaving the ``/v1`` off makes ``/models`` 404,
    which the card reports as "Model unavailable".
    """
    base = (url or "").strip().rstrip("/")
    if base and not base.endswith("/v1"):
        base += "/v1"
    return base


def openai_server_root(base_url: str) -> str:
    """The server root a window probe can append ``/v1/...`` to.

    The stored LiteLLM URL is the OpenAI client base and may already end in
    ``/v1``. The probe expects the root.
    """
    root = (base_url or "").strip().rstrip("/")
    if root.endswith("/v1"):
        root = root[: -len("/v1")]
    return root.rstrip("/")


def first_chat_model(ids: list[str]) -> str:
    """The first id the model picker would offer, or ``""`` when none qualify."""
    from dodaios.brain.model_catalog import ModelInfo, filter_brain_models, sort_models

    infos = [ModelInfo(id=name, label=name) for name in ids if name]
    usable = sort_models("litellm", filter_brain_models(infos))
    return usable[0].id if usable else ""


def context_tokens_from_model_info(payload: Any, model: str) -> int | None:
    """``max_input_tokens`` for ``model`` in a LiteLLM ``/model/info`` body."""
    rows = payload.get("data") if isinstance(payload, dict) else None
    for row in rows or ():
        if not isinstance(row, dict):
            continue
        name = str(row.get("model_name") or row.get("id") or "").strip()
        if name != model:
            continue
        info = row.get("model_info") if isinstance(row.get("model_info"), dict) else {}
        tokens = info.get("max_input_tokens")
        if isinstance(tokens, int) and not isinstance(tokens, bool) and tokens > 0:
            return tokens
    return None


async def _model_info_window(root: str, model: str, headers: dict[str, str]) -> int | None:
    """LiteLLM's own ``/model/info`` when ``/v1/models`` states no window."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(2.0)) as client:
            response = await client.get(f"{root}/model/info", headers=headers)
    except Exception as exc:  # noqa: BLE001 — a probe must never fail the turn
        log.debug("litellm: /model/info failed at %s: %s", root, exc)
        return None
    if response.status_code != 200:
        return None
    try:
        payload = response.json()
    except ValueError:
        return None
    tokens = context_tokens_from_model_info(payload, model)
    if tokens:
        from dodaios.brain import local_context

        local_context.remember_window(
            "litellm", root, model, tokens, source="server", kind="litellm",
        )
    return tokens


def discover_chat_model(base_url: str, api_key: str) -> str:
    """The chat model a proxy lists at ``{base}/models``. Empty when none qualify."""
    import httpx

    url = (base_url or "").rstrip("/") + "/models"
    response = httpx.get(
        url,
        headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
        timeout=5.0,
    )
    response.raise_for_status()
    rows = response.json().get("data") or []
    ids = [
        str(row.get("id") or "").strip()
        for row in rows
        if isinstance(row, dict)
    ]
    return first_chat_model(ids)


def fit_reply_cap(req: BrainRequest, window: int) -> BrainRequest:
    """Shrink ``max_tokens`` so the prompt plus the reply fits ``window``.

    The config ceiling is 32,768. A smaller model rejects a request that asks
    for more new tokens than it can hold.
    """
    if window <= 0 or req.max_tokens <= 1:
        return req
    from dodaios.brain.local_context import _budget_tokens

    room = max(1, window - _budget_tokens(req))
    if req.max_tokens <= room:
        return req
    return replace(req, max_tokens=room)


class LiteLLMBrain:
    name: str = "litellm"
    context_window: int = _UNPUBLISHED_WINDOW
    supports_tools: bool = True
    # Unknown stays blind. A catalog entry that declares image input turns it on.
    supports_vision: bool = False

    def __init__(self, model: str | None = None) -> None:
        self._model = (model or "").strip()
        self._client: Any = None
        self._api_key: str | None = None
        try:
            from dodaios.brain.model_catalog import model_capabilities, model_context_length

            caps = model_capabilities("litellm", self._model) if self._model else {}
            if caps:
                if caps.get("vision") is not None:
                    self.supports_vision = bool(caps["vision"])
                if caps.get("tools") is not None:
                    self.supports_tools = bool(caps["tools"])
            cached = model_context_length("litellm", self._model) if self._model else None
            if cached:
                self.context_window = cached
        except Exception:  # noqa: BLE001 — a capability probe must never break construction
            pass
        if self._model:
            from dodaios.brain import local_context

            seen = local_context.known_window_for_model(self.name, self._model)
            if seen:
                self.context_window = seen

    def can_call_tools(self) -> bool:
        return self.supports_tools

    def _ensure_client(self) -> Any:
        if self._client is None:
            ep = cfg.resolve_provider_endpoint("litellm", vendor_default_base_url=BASE_URL)
            if not ep.credential:
                raise RuntimeError(
                    "No LiteLLM API key found (litellm_api_key / LITELLM_API_KEY). "
                    "Use the proxy master key or a virtual key."
                )
            if not ep.base_url:
                raise RuntimeError(
                    "LiteLLM needs a server URL — set it on the provider card "
                    "(usually http://localhost:4000/v1)."
                )
            from openai import AsyncOpenAI

            self._api_key = ep.credential
            base_url = ep.base_url if ep.via_proxy else openai_client_base(ep.base_url or "")
            self._client = AsyncOpenAI(
                api_key=ep.credential,
                base_url=base_url,
                timeout=CLIENT_TIMEOUT,
            )
        return self._client

    async def _resolve_model(self, client: Any) -> str:
        """The configured model, else the first chat model the proxy lists."""
        if self._model:
            return self._model
        try:
            listed = await client.models.list()
        except Exception as exc:
            raise RuntimeError(
                "LiteLLM has no model selected and the proxy did not answer "
                "/models. Check the server URL and key, or set a model on the card."
            ) from exc
        names = [
            str(getattr(item, "id", "") or "").strip()
            for item in (getattr(listed, "data", None) or [])
        ]
        chosen = first_chat_model(names)
        if not chosen:
            raise RuntimeError(
                "The LiteLLM proxy lists no chat models. Add one in the proxy "
                "config, or set a model on the LiteLLM card."
            )
        self._model = chosen
        return self._model

    async def prepare_context_window(self) -> None:
        """Size the tool list from the proxy's window before the turn is sent.

        A brain still discovering its model keeps the unpublished floor. Never
        raises: a silent proxy is budgeted small instead of refusing the turn.
        """
        if not self._model:
            return
        try:
            client = await asyncio.to_thread(self._ensure_client)
            root = openai_server_root(str(getattr(client, "base_url", "") or ""))
            headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
            from dodaios.brain import local_context

            window = await local_context.probe_server_window(
                root, self._model, headers=headers, provider=self.name,
            )
            tokens = window.tokens if window is not None else await _model_info_window(
                root, self._model, headers,
            )
        except Exception as exc:  # noqa: BLE001 — sizing must never cost the turn
            log.debug("litellm: could not settle the context window early: %s", exc)
            return
        if tokens:
            self.context_window = tokens

    async def complete(self, req: BrainRequest) -> AsyncIterator[BrainDelta]:
        client = self._client
        if client is None:
            client = await asyncio.to_thread(self._ensure_client)
        model = await self._resolve_model(client)
        req = fit_reply_cap(req, self.context_window)
        async for delta in stream_complete(
            client, model, req, supports_vision=self.supports_vision,
        ):
            yield delta

    def estimate_cost(self, req: BrainRequest) -> float:
        # The proxy's prices depend on the upstream model. A conservative
        # stand-in, the same shape as the OpenRouter brain.
        in_tokens = sum(len(str(m.content)) for m in req.messages) // 4
        return (in_tokens * 10 + req.max_tokens * 30) / 1_000_000
