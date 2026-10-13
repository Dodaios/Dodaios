"""Generic local OpenAI-compatible brain (HuggingFace transformers serve & co).

One card for every self-hosted server that speaks the OpenAI Chat-Completions
format: HuggingFace ``transformers serve`` (port 8000), llama.cpp
``llama-server`` (port 8080), vLLM, LM Studio (port 1234) — and TGI installs
keep working, though TGI itself is in maintenance mode and never the
recommendation. Ollama has its own dedicated provider; this is the
bring-your-own-server slot.

Unlike the cloud brains there is NO vendor default endpoint — a base URL is
REQUIRED and its absence raises an honest, example-bearing error instead of
guessing a port. The credential is OPTIONAL (``local_openai_api_key`` /
``LOCAL_OPENAI_API_KEY``): most local servers ignore it, some (LM Studio
behind a reverse proxy, vLLM with ``--api-key``) check it. Keyless by design
(§3 / AP-22): ``local-openai`` stays ABSENT from
``PROVIDER_SECRET_CANDIDATES`` so the key-aware resolver treats it as always
reachable and a dead server just fast-fails across families.

Vision defaults to UNSUPPORTED and is only ever raised by evidence: whether a
given local server accepts image content is unknowable in general, so the
shared streamer DROPS images with a warning rather than letting a text-only
server reject the whole turn. When the server's own ``/v1/models`` DOES declare
image input for the selected model (some OpenAI-compatible servers publish the
modality fields), the cached catalog carries that declaration and this brain
believes it. Unknown stays blind — a confident description of a picture nobody
looked at is the failure mode worth being conservative about.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

from jarvis.brain import local_context
from jarvis.core import config as cfg
from jarvis.core.protocols import BrainDelta, BrainRequest

from ._openai_base import stream_complete
from .ollama import normalize_server_root

log = logging.getLogger(__name__)

# Same shape as the Ollama timeout: a dead local server must fail fast so the
# fallback chain crosses families; a slow CPU-bound generation may stream long.
CLIENT_TIMEOUT = httpx.Timeout(connect=2.0, read=120.0, write=30.0, pool=30.0)

_NO_BASE_URL_HELP = (
    "The local OpenAI-compatible provider needs a server URL — set it on the "
    'provider card (or [brain.providers."local-openai"].base_url). Examples: '
    "HuggingFace transformers serve: http://localhost:8000 - "
    "llama.cpp llama-server: http://localhost:8080 - "
    "LM Studio: http://localhost:1234 - vLLM: http://localhost:8000."
)


def _declared_vision_support(model: str) -> bool:
    """Whether the SELECTED model declares image input, from the cached catalog.

    Mirrors the Ollama card's probe but with the opposite default: Ollama can
    ask its server what each download can do, a generic OpenAI-compatible
    server usually cannot be asked at all — so silence means blind here.
    Synchronous by necessity (``resolve_vision_brain`` asks before any call) and
    therefore cache-only; it never touches the network.
    """
    if not model:
        return False
    try:
        from jarvis.brain.model_catalog import model_capabilities  # noqa: PLC0415 — lazy (AP-26)

        return model_capabilities("local-openai", model)["vision"] is True
    except Exception:  # noqa: BLE001 — a probe must never break construction
        log.debug("local-openai: vision capability probe failed — staying blind")
        return False


class LocalOpenAIBrain:
    name: str = "local-openai"
    # Conservative floor — the real window depends on the served model; the
    # manager treats this as a budget hint, not a hard cap.
    context_window: int = 32_768
    supports_tools: bool = True
    supports_vision: bool = False

    def __init__(self, model: str | None = None) -> None:
        self._model = (model or "").strip()
        self._client: Any = None
        self._server_root: str | None = None
        self._credential: str | None = None
        self.supports_vision = _declared_vision_support(self._model)
        # Tool fitting happens before complete(): publish the window this
        # model was last seen running with, so the budget is the real one.
        seen = local_context.known_window_for_model(self.name, self._model) if self._model else None
        if seen:
            self.context_window = seen

    def can_call_tools(self) -> bool:
        return self.supports_tools

    def _resolve_root(self) -> str:
        if self._server_root is None:
            ep = cfg.resolve_provider_endpoint("local-openai", vendor_default_base_url=None)
            if not ep.base_url:
                raise RuntimeError(_NO_BASE_URL_HELP)
            # Root convention (same as the Ollama card): the stored value is
            # the SERVER root; ``/v1`` is appended here, and a pasted ``…/v1``
            # is normalized away instead of doubling up.
            self._server_root = normalize_server_root(ep.base_url)
            # Optional key: a team-proxy token wins, else the user's optional
            # local key, else a placeholder the server ignores.
            self._credential = ep.credential or cfg.get_secret(
                "local_openai_api_key", "LOCAL_OPENAI_API_KEY"
            )
        return self._server_root

    def _ensure_client(self) -> Any:
        if self._client is None:
            root = self._resolve_root()
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(
                api_key=self._credential or "local",
                base_url=f"{root}/v1",
                timeout=CLIENT_TIMEOUT,
            )
        return self._client

    async def _resolve_model(self) -> str:
        """The configured model, else the first one the server lists (``/v1/models``)."""
        if self._model:
            return self._model
        root = self._resolve_root()
        headers = {}
        if self._credential:
            headers["Authorization"] = f"Bearer {self._credential}"
        try:
            async with httpx.AsyncClient(timeout=CLIENT_TIMEOUT) as client:
                resp = await client.get(f"{root}/v1/models", headers=headers)
                resp.raise_for_status()
                data = resp.json().get("data") or []
        except Exception as exc:
            raise RuntimeError(
                f"Local OpenAI-compatible server not reachable at {root} — is it "
                "running? (transformers serve / llama-server / LM Studio / vLLM)"
            ) from exc
        names = [str(m.get("id") or "").strip() for m in data]
        names = [n for n in names if n]
        if not names:
            raise RuntimeError(
                f"The server at {root} lists no models (/v1/models is empty) — "
                "load a model in the server, or set one explicitly on the card."
            )
        self._model = names[0]
        log.info("local-openai: no model configured — using first served: %s", self._model)
        return self._model

    def _probe_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._credential}"} if self._credential else {}

    async def _guard_window(
        self, req: BrainRequest, root: str, model: str, *, fresh: bool = False
    ) -> bool:
        """Refuse ``req`` when the server's own window cannot hold it.

        Returns whether the server stated its window. A stated window also
        becomes this brain's ``context_window``, so the next turn's tool
        surface is budgeted against what really runs.
        """
        window = await local_context.probe_server_window(
            root, model, headers=self._probe_headers(), fresh=fresh
        )
        if window is None:
            return False
        self.context_window = window.tokens
        local_context.ensure_fits(
            req, window.tokens, provider=self.name, model=model, kind=window.kind
        )
        return True

    async def prepare_context_window(self) -> None:
        """Settle ``context_window`` before the caller budgets a turn.

        Tools are fitted before ``complete()`` runs, so the first turn after a
        model was chosen would otherwise be planned for the class figure and
        refused whole instead of having its tools trimmed. One cached question
        to the server; a brain still discovering its model skips it. Never
        raises.
        """
        if not self._model:
            return
        try:
            root = self._resolve_root()
            window = await local_context.probe_server_window(
                root, self._model, headers=self._probe_headers()
            )
        except Exception as exc:  # noqa: BLE001 — sizing must never cost the turn
            log.debug("local-openai: could not settle the context window early: %s", exc)
            return
        if window is not None:
            self.context_window = window.tokens

    def _judge_reported_prompt(
        self, req: BrainRequest, root: str, model: str, reported: int | None
    ) -> None:
        """Compare what a server that states no window says it read.

        Two responses in a row that read far less than was sent tighten the
        budget of the next turn; one that read more than a recorded suspicion
        clears it. Never fails the turn: the signal is a suspicion.
        """
        verdict, tokens = local_context.judge_reported_prompt(
            self.name, root, model, req, reported
        )
        if verdict == "tighten":
            self.context_window = tokens
            log.warning(
                "local-openai: %s at %s twice read about %d prompt tokens of requests "
                "at least twice that size, so the server is most likely cutting the "
                "prompt short. Planning the next turn for %d tokens. %s",
                model,
                root,
                tokens,
                tokens,
                local_context.fix_hint("unknown", local_context.certain_tokens(req)),
            )
        elif verdict == "restore":
            self.context_window = type(self).context_window

    async def complete(self, req: BrainRequest) -> AsyncIterator[BrainDelta]:
        client = self._client
        if client is None:
            # First use imports the SDK — seconds on a cold disk, and never on
            # the event loop (BUG-189; see claude_api.py for the measurement).
            client = await asyncio.to_thread(self._ensure_client)
        model = await self._resolve_model()
        root = self._resolve_root()
        stated = await self._guard_window(req, root, model)
        reported: int | None = None
        stream = stream_complete(client, model, req, supports_vision=self.supports_vision)
        try:
            first = True
            async for delta in stream:
                if first and not stated:
                    # A server that loads on demand only knows its window once
                    # the model is in memory, which the first token proves.
                    # Ask again before anything is handed on, so a prompt that
                    # was cut short never reaches the caller as an answer.
                    stated = await self._guard_window(req, root, model, fresh=True)
                first = False
                if delta.usage:
                    reported = local_context.reported_prompt_tokens(delta.usage)
                yield delta
        except local_context.LocalContextError:
            raise
        except Exception as exc:
            if not local_context.is_overflow_refusal(str(exc)):
                raise
            # The server refused the size itself. Say how large it has to be
            # and where to change it instead of passing a bare HTTP 400 on.
            known = local_context.known_window(self.name, root, model)
            stated_window = known is not None and known[1] == "server"
            raise local_context.refusal_error(
                req,
                provider=self.name,
                model=model,
                kind=known[2] if known is not None and stated_window else "unknown",
                window_tokens=known[0] if known is not None and stated_window else 0,
            ) from exc
        finally:
            await stream.aclose()
        if not stated:
            self._judge_reported_prompt(req, root, model, reported)

    def estimate_cost(self, req: BrainRequest) -> float:
        # Local inference has no per-token bill.
        return 0.0
