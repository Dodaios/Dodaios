"""Groq — OpenAI-compatible gateway to Groq's LPU-hosted open models.

One Groq API key (``gsk_…`` from console.groq.com) reaches the open models Groq
serves on its own inference hardware: Llama, GPT-OSS, Qwen, Kimi and more. Its
time-to-first-token is among the lowest of any hosted API, which makes it a good
voice brain. The endpoint speaks the OpenAI Chat-Completions format, so this
brain is a thin binding of the shared ``_openai_base`` streamer to Groq's fixed
base URL — the same shape as the OpenRouter/NVIDIA brains.

The same key already powers Groq speech-to-text; both surfaces read the one
``groq_api_key`` family slot.

Bring-your-own-key, capability-gated (never provider-name-gated, AP-21): a
missing key raises a clean error so the fallback chain crosses to whatever the
user actually has, and the model id comes from the user's pick (the live
``/openai/v1/models`` catalog).
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from jarvis.core import config as cfg
from jarvis.core.protocols import BrainDelta, BrainRequest

from ._openai_base import CLIENT_TIMEOUT, stream_complete

# Groq's OpenAI-compatible endpoint. Passed as the vendor default so an explicit
# ``[brain.providers.groq].base_url`` override or the team proxy can still
# redirect it (resolve_provider_endpoint).
BASE_URL = "https://api.groq.com/openai/v1"

# Last-resort default when the brain is built with NO model: fast, tool-capable,
# on Groq's free tier. The manager passes the user's pick in almost every path.
DEFAULT_MODEL = "openai/gpt-oss-120b"


class GroqBrain:
    name: str = "groq"
    context_window: int = 128_000
    supports_tools: bool = True
    supports_vision: bool = False

    def __init__(self, model: str | None = None) -> None:
        self._model = model or DEFAULT_MODEL
        self._client: Any = None

    def can_call_tools(self) -> bool:
        return self.supports_tools

    def _ensure_client(self) -> Any:
        if self._client is None:
            ep = cfg.resolve_provider_endpoint("groq", vendor_default_base_url=BASE_URL)
            if not ep.credential:
                raise RuntimeError(
                    "No Groq API key found (groq_api_key / GROQ_API_KEY). "
                    "Get a console.groq.com key (starts with gsk_)."
                )
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(
                api_key=ep.credential,
                base_url=ep.base_url,
                timeout=CLIENT_TIMEOUT,
            )
        return self._client

    async def complete(self, req: BrainRequest) -> AsyncIterator[BrainDelta]:
        client = self._client
        if client is None:
            # First use imports the SDK — never on the event loop (BUG-189).
            client = await asyncio.to_thread(self._ensure_client)
        async for delta in stream_complete(client, self._model, req):
            yield delta

    def estimate_cost(self, req: BrainRequest) -> float:
        # Groq prices are model-dependent and low; conservative estimate,
        # mirroring the OpenRouter brain.
        in_tokens = sum(len(str(m.content)) for m in req.messages) // 4
        return (in_tokens * 1 + req.max_tokens * 1) / 1_000_000
