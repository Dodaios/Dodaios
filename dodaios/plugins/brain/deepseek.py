"""DeepSeek's native OpenAI-compatible text and tool API."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import replace
from typing import TYPE_CHECKING

from dodaios.core import config as cfg
from dodaios.core.protocols import BrainDelta, BrainRequest

from ._openai_base import CLIENT_TIMEOUT, stream_complete

if TYPE_CHECKING:
    from openai import AsyncOpenAI

BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-flash"
_KEYRING_SLOT = "deepseek_api_key"


class DeepSeekBrain:
    """Stream text and tool calls using the user's DeepSeek API key."""

    name: str = "deepseek"
    context_window: int = 1_000_000
    supports_tools: bool = True
    supports_vision: bool = False

    def __init__(self, model: str | None = None) -> None:
        self._model = model or DEFAULT_MODEL
        self._cached_client: tuple[int, AsyncOpenAI] | None = None

    def can_call_tools(self) -> bool:
        return self.supports_tools

    def _create_client(self) -> AsyncOpenAI:
        revision = cfg.secret_revision(_KEYRING_SLOT)
        endpoint = cfg.resolve_provider_endpoint(self.name, vendor_default_base_url=BASE_URL)
        if not endpoint.credential:
            raise RuntimeError("No DeepSeek API key found (deepseek_api_key / DEEPSEEK_API_KEY).")
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            api_key=endpoint.credential,
            base_url=endpoint.base_url,
            timeout=CLIENT_TIMEOUT,
            max_retries=0,
        )
        self._cached_client = revision, client
        return client

    async def complete(self, req: BrainRequest) -> AsyncIterator[BrainDelta]:
        cached = self._cached_client
        if cached is None or cached[0] != cfg.secret_revision(_KEYRING_SLOT):
            client = await asyncio.to_thread(self._create_client)
        else:
            _, client = cached
        # Thinking tool turns require replaying reasoning_content, which the
        # shared chat history does not preserve.
        async for delta in stream_complete(
            client,
            self._model,
            replace(req, reasoning_effort=None),
            extra_body={"thinking": {"type": "disabled"}},
            supports_vision=self.supports_vision,
        ):
            yield delta

    def estimate_cost(self, req: BrainRequest) -> float:
        from dodaios.brain.cost import calculate_cost_usd

        input_tokens = sum(len(str(message.content)) for message in req.messages) // 4
        return calculate_cost_usd(self._model, input_tokens, req.max_tokens)
