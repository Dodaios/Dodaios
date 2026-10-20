"""Ollama — keyless local brain via Ollama's OpenAI-compatible endpoint.

Runs whatever models the user has pulled into a local (or LAN) Ollama server —
no API key, no cloud account, nothing leaves the machine. The server's ``/v1``
endpoint speaks the OpenAI Chat-Completions format, so this brain is a thin
binding of the shared ``_openai_base`` streamer to the server root resolved
from ``[brain.providers.ollama].base_url`` / ``OLLAMA_HOST`` / the localhost
default — the same shape as the NVIDIA brain.

Keyless by design (§3 / AP-22): ``ollama`` is deliberately ABSENT from
``PROVIDER_SECRET_CANDIDATES`` — that absence is what makes the key-aware
resolver treat it as always reachable. A dead server fast-fails on the 2 s
connect timeout so the fallback chain crosses to the next family instead of
stalling. Tool calling rides the OpenAI-compat layer (``tool_choice`` is not
used on the pipeline path); reliability is model-dependent — the qwen line is
the recommended pull.

Model discovery is NATIVE (``/api/tags`` + ``/api/show``): with no configured
model the brain runs the smallest DOWNLOADED model whose declared capabilities
match the turn (``completion``, plus ``tools`` for tool turns, plus ``vision``
for a turn carrying images); ``:cloud`` references never count as local, and a
model-less server produces an honest "pull one first" error instead of a
hardcoded default that would 404.

**Vision is a MODEL property, never a server property.** A blanket
``supports_vision = True`` on the class made every Ollama install advertise
sight: ``resolve_vision_brain`` picked it for Screen Context and the CU planner
let it plan from screenshots, so a host whose only pull is a text-only model
answered *about* the picture it had never seen. The flag is therefore resolved
per SELECTED model from the cached catalog (the same route OpenRouter takes),
the image path negotiates a ``vision``-capable download, and a server without
one raises an honest error instead of describing a screenshot blind.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, fields, replace
from typing import Any
from urllib.parse import urlsplit

import httpx

from jarvis.brain import local_context
from jarvis.core import config as cfg
from jarvis.core.config import OllamaModelOptions
from jarvis.core.protocols import BrainDelta, BrainRequest

from ._openai_base import stream_complete

log = logging.getLogger(__name__)

DEFAULT_SERVER_ROOT = "http://localhost:11434"

# A tools-capable local model line that streams tool calls reliably through
# the OpenAI-compat layer (Gemma-family models have known streaming-tool-call
# defects there). Used in error/help text only — never silently pulled.
RECOMMENDED_PULL = "qwen3.5"

# The multimodal counterpart, named only in help text for a turn that carries
# images and finds no ``vision``-capable download. Never silently pulled.
RECOMMENDED_VISION_PULL = "qwen3-vl"

# Local server: an unreachable endpoint must fail fast (2 s) so the fallback
# chain moves on, while a slow CPU-bound generation may legitimately stream
# for minutes — hence the wide read timeout.
CLIENT_TIMEOUT = httpx.Timeout(connect=2.0, read=120.0, write=30.0, pool=30.0)

# The automatic window per (server root, model): sized once per process, since
# a changed ``num_ctx`` makes Ollama reload the weights.
_AUTOMATIC_CONTEXT: dict[tuple[str, str], int] = {}
# What ``/api/ps`` last reported per (server root, running model): the context
# (``None`` when the server does not report one) and when it was read.
_RUNNING_CONTEXT: dict[tuple[str, str], tuple[int | None, float]] = {}
_RUNNING_TTL_S = 300.0
# (server root, profile alias) the server refused to create, and when.
_PROFILE_REFUSED: dict[tuple[str, str], float] = {}
_PROFILE_REFUSED_TTL_S = 300.0

_NUM_CTX_PARAMETER_RE = re.compile(r"^\s*num_ctx\s+(\d+)\s*$", re.MULTILINE)
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})


@dataclass(frozen=True, slots=True)
class _PreparedCall:
    """What one ``complete()`` streams with. Per call, never per instance."""

    run_model: str
    req: BrainRequest
    #: The context this call should run with, or ``None`` when nothing set one.
    planned: int | None
    #: Whether the server is known to run ``planned`` (a created profile, or
    #: the model's own declaration).
    confirmed: bool


def reset_context_memo() -> None:
    """Forget sized and verified windows (tests, or a changed endpoint)."""
    _AUTOMATIC_CONTEXT.clear()
    _RUNNING_CONTEXT.clear()
    _PROFILE_REFUSED.clear()


def _running_memo(root: str, run_model: str) -> int | None:
    """The context ``/api/ps`` last reported for ``run_model``, if still fresh."""
    memo = _RUNNING_CONTEXT.get((root, run_model.removesuffix(":latest")))
    if memo is None or time.monotonic() - memo[1] > _RUNNING_TTL_S:
        return None
    return memo[0]


def _is_this_machine(root: str) -> bool:
    """Whether the server root points at the machine this app runs on."""
    return (urlsplit(root).hostname or "").lower() in _LOOPBACK_HOSTS


def _declared_num_ctx(parameters: Any) -> int | None:
    """The ``num_ctx`` a model's own Modelfile sets, from ``/api/show``."""
    if not isinstance(parameters, str):
        return None
    match = _NUM_CTX_PARAMETER_RE.search(parameters)
    return int(match.group(1)) if match else None


def normalize_server_root(url: str) -> str:
    """Normalize a user/env-supplied Ollama address to a bare server root.

    Accepts ``host:port``, a full URL, a trailing slash, or a pasted ``…/v1``
    / ``…/api`` suffix and always returns ``scheme://host[:port]`` so callers
    append ``/v1`` (chat) or ``/api/...`` (native) themselves. ``0.0.0.0`` is
    a server BIND address, not a client target (connecting to it fails on
    Windows), so it maps to localhost.
    """
    root = (url or "").strip().rstrip("/")
    if not root:
        return DEFAULT_SERVER_ROOT
    if "://" not in root:
        root = f"http://{root}"
    for suffix in ("/v1", "/api"):
        if root.endswith(suffix):
            root = root[: -len(suffix)]
    root = root.replace("://0.0.0.0", "://localhost")
    return root.rstrip("/")


def _request_has_images(req: BrainRequest) -> bool:
    """True when any user message of ``req`` carries an image block.

    ``getattr`` for the same backwards-compatibility reason the shared streamer
    uses it: a Protocol predating multimodal messages has no ``images`` field.
    """
    for message in getattr(req, "messages", ()) or ():
        if getattr(message, "images", ()):
            return True
    return False


def _declared_vision_support(model: str) -> bool:
    """Whether this install can be handed an image, read SYNCHRONOUSLY.

    ``resolve_vision_brain`` and the CU planner ask for ``supports_vision``
    before any call has been made, so the answer may not hit the network here
    (that would block the caller's event loop). It comes from the cached model
    catalog instead, which stores each download's declared ``/api/show``
    capabilities under the generic modality fields.

    Fail-OPEN on unknown: with a configured model whose capabilities are not
    cached, or a catalog that has never been fetched on this host, the answer
    stays ``True`` — the image path then negotiates a real vision model and
    raises an honest error if there is none, which is strictly better than
    declaring an install blind and silently routing every screenshot to the
    cloud. Fail-CLOSED once the catalog actually says no: a server whose
    downloads are all text-only answers ``False`` and drops out of the vision
    chain, so the resolver crosses to a provider that can see (AP-21/AP-22).
    """
    try:
        from jarvis.brain.model_catalog import (  # noqa: PLC0415 — lazy (AP-26)
            model_capabilities,
            pick_vision_model,
            provider_has_modality_data,
        )

        if model:
            vision = model_capabilities("ollama", model)["vision"]
            return True if vision is None else bool(vision)
        if not provider_has_modality_data("ollama"):
            return True
        return pick_vision_model("ollama") is not None
    except Exception:  # noqa: BLE001 — a probe must never break construction
        log.debug("ollama: vision capability probe failed — assuming capable")
        return True


def default_server_root() -> str:
    """Vendor-default server root: ``OLLAMA_HOST`` if set, else localhost.

    Ollama's own CLI honors ``OLLAMA_HOST`` for both serving and connecting,
    so a user who moved their server declares it exactly once.
    """
    return normalize_server_root(os.environ.get("OLLAMA_HOST") or DEFAULT_SERVER_ROOT)


class OllamaBrain:
    name: str = "ollama"
    # Conservative floor — the real window is model-dependent (the qwen line
    # reaches 128k); the manager treats this as a budget hint, not a hard cap.
    context_window: int = 32_768
    # Class-attr DEFAULTS (capable). The INSTANCE narrows them per selected
    # model in ``__init__`` and again once the server has answered — an Ollama
    # server serves whatever the user pulled, and a text-only pull must not be
    # sent screenshots (the vision resolver and the CU planner both gate on
    # ``supports_vision``).
    supports_tools: bool = True
    supports_vision: bool = True

    def __init__(self, model: str | None = None) -> None:
        self._model = (model or "").strip()
        self._client: Any = None
        self._server_root: str | None = None
        self._credential: str | None = None
        self._requested_context_window: int | None = None
        # Discovery cache per requirement profile (tools, vision) — a plain
        # chat turn may run a smaller model than a tool turn or an image turn
        # without re-asking the server every time.
        self._discovered: dict[tuple[bool, bool], str] = {}
        # Per-model ``/api/show`` capability cache, shared by discovery and the
        # image path so one turn never probes the same download twice.
        self._caps_cache: dict[str, set[str] | None] = {}
        # The same answer's native context window, for the automatic sizing,
        # and the ``num_ctx`` the model's own Modelfile declares, if any.
        self._native_context: dict[str, int | None] = {}
        self._declared_context: dict[str, int | None] = {}
        self.supports_vision = _declared_vision_support(self._model)
        if self._model:
            from jarvis.brain.model_catalog import model_capabilities

            self.supports_tools = model_capabilities("ollama", self._model)["tools"] is not False
        # Tool fitting and history compaction happen before complete().
        # Publish an explicit local context limit before either budgets: the
        # person's own, else the window this model was last given, else the
        # floor every automatic window starts from (never the class figure,
        # which the server does not run unless it is asked to).
        options = self._model_options(self._model) if self._model else None
        if options is not None and options.num_ctx:
            self.context_window = options.num_ctx
        else:
            seen = local_context.known_window_for_model(self.name, self._model)
            self.context_window = seen or self._unconfirmed_budget(self._model)

    def can_call_tools(self) -> bool:
        return self.supports_tools

    def set_context_window(self, tokens: int) -> None:
        """Allocate the gateway's resolved context on this instance only."""
        if isinstance(tokens, bool) or not isinstance(tokens, int) or tokens < 1:
            raise ValueError("Context window must be a positive integer")
        self._requested_context_window = tokens

    def _resolve_root(self) -> str:
        if self._server_root is None:
            ep = cfg.resolve_provider_endpoint(
                "ollama", vendor_default_base_url=default_server_root()
            )
            # Root convention: the stored/resolved value is the SERVER root;
            # ``/v1`` (chat) and ``/api/*`` (discovery) are appended here. A
            # team-proxy target (``…/p/ollama``) follows the same convention.
            self._server_root = normalize_server_root(ep.base_url or default_server_root())
            self._credential = ep.credential
        return self._server_root

    def _ensure_client(self) -> Any:
        if self._client is None:
            root = self._resolve_root()
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(
                # A local Ollama ignores the key entirely, but the SDK insists
                # on a non-empty one; a team proxy swaps in its real token.
                api_key=self._credential or "ollama",
                base_url=f"{root}/v1",
                timeout=CLIENT_TIMEOUT,
                max_retries=0,
            )
        return self._client

    def _native_headers(self) -> dict[str, str]:
        """Native discovery/profile calls use the same endpoint credential as chat."""
        self._resolve_root()
        return {"Authorization": f"Bearer {self._credential}"} if self._credential else {}

    async def _resolve_model(self, *, need_tools: bool = False, need_vision: bool = False) -> str:
        """The configured model, else the smallest CAPABLE download.

        Hard rules for the silent default (three live incidents 2026-07-25):
        ``:cloud`` entries are ollama.com-proxied references, not local
        weights — a "local" brain must never route through them. Among the
        real downloads the SMALLEST wins (the former first-installed pick
        landed on a 30B model whose 256k default context needed 45 GB on a
        32 GB box and froze the whole desktop) — but only one whose DECLARED
        ``/api/show`` capabilities match the turn: ``completion`` always
        (bge-m3 would 400 on chat), plus ``tools`` when the request carries
        tools (deepseek-llm 400s on a tool turn), plus ``vision`` when it
        carries images (a text-only model does not refuse a screenshot — it
        answers about the words around it). The user's explicit model pick
        always overrides this.
        """
        if self._model:
            if need_tools:
                caps = await self._capabilities(self._model, self._resolve_root())
                if caps is not None:
                    self.supports_tools = "tools" in caps
                    if not self.supports_tools:
                        raise RuntimeError(
                            f"The selected Ollama model '{self._model}' does not support tools. "
                            "Choose a tool-capable model for this agent. "
                            "No other provider was called."
                        )
            return self._model
        profile = (need_tools, need_vision)
        if profile in self._discovered:
            return self._discovered[profile]
        root = self._resolve_root()
        try:
            async with httpx.AsyncClient(
                timeout=CLIENT_TIMEOUT, headers=self._native_headers(),
            ) as client:
                resp = await client.get(f"{root}/api/tags")
                resp.raise_for_status()
                models = resp.json().get("models") or []
        except Exception as exc:
            raise RuntimeError(
                f"Ollama not reachable at {root} — is it running? Start it "
                "(or install from https://ollama.com/download), then retry."
            ) from exc
        from jarvis.brain.ollama_inventory import is_hidden_alias

        local = [
            m
            for m in models
            if (name := str(m.get("name") or "").strip())
            and not name.endswith(":cloud")
            and not m.get("remote")
            and not is_hidden_alias(name)
        ]
        if not local:
            raise RuntimeError(
                f"Ollama at {root} has no downloaded models (cloud references "
                f"do not count) — run: ollama pull {RECOMMENDED_PULL}, then retry."
            )
        local.sort(key=lambda m: int(m.get("size") or 0))
        for m in local:
            name = str(m.get("name")).strip()
            caps = await self._capabilities(name, root)
            if caps is not None:
                if "completion" not in caps:
                    continue
                if need_tools and "tools" not in caps:
                    continue
                # Vision is the one requirement that must NOT fail open: an
                # unprobeable model is skipped rather than handed a screenshot
                # it cannot see, because a blind answer looks exactly like a
                # sighted one.
                if need_vision and "vision" not in caps:
                    continue
            elif need_vision:
                continue
            self._discovered[(need_tools, need_vision)] = name
            log.info(
                "ollama: no model configured — using smallest capable download "
                "(tools=%s, vision=%s): %s",
                need_tools,
                need_vision,
                name,
            )
            return name
        if need_vision:
            if any(str(row.get("name")).strip() not in self._caps_cache for row in local):
                raise RuntimeError(
                    "Ollama could not report image capabilities for the downloaded models. "
                    "Check the server connection and retry; no image was sent to a model."
                )
            raise RuntimeError(
                f"None of the models downloaded at {root} can see images — run: "
                f"ollama pull {RECOMMENDED_VISION_PULL} (a multimodal model), "
                "then retry."
            )
        wanted = "chat + tool calling" if need_tools else "chat"
        raise RuntimeError(
            f"None of the models downloaded at {root} supports {wanted} — run: "
            f"ollama pull {RECOMMENDED_PULL}, then retry."
        )

    async def _capabilities(self, name: str, root: str) -> set[str] | None:
        """DECLARED capabilities of one download via native ``/api/show``.

        Gate on capability, never the model name (AP-21). ``None`` = the probe
        could not answer — the caller FAILS OPEN for chat/tools (a probe glitch
        must never brick the pick; the real call then errors honestly) and
        fails CLOSED for vision, where a wrong yes is invisible.

        Cached per model for the lifetime of the brain instance: discovery and
        the image path both ask, and the answer only changes when the user
        re-pulls a model — at which point the catalog TTL and a new instance
        pick it up.
        """
        if name in self._caps_cache:
            return self._caps_cache[name]
        caps_set: set[str] | None = None
        try:
            async with httpx.AsyncClient(
                timeout=CLIENT_TIMEOUT, headers=self._native_headers(),
            ) as client:
                resp = await client.post(f"{root}/api/show", json={"model": name})
                resp.raise_for_status()
                shown = resp.json()
                caps = shown.get("capabilities")
            if isinstance(caps, list):
                caps_set = {str(c) for c in caps}
            from jarvis.brain.ollama_inventory import (  # noqa: PLC0415 — lazy (AP-26)
                native_context_length,
            )

            self._native_context[name] = native_context_length(shown.get("model_info"))
            self._declared_context[name] = _declared_num_ctx(shown.get("parameters"))
        except Exception:  # noqa: BLE001 — retry unavailable metadata on the next turn
            log.debug("ollama: capability lookup failed for %s", name, exc_info=True)
            caps_set = None
        if caps_set is not None:
            self._caps_cache[name] = caps_set
        return caps_set

    async def _pinned_model_can_see(self, model: str) -> bool:
        """Whether the user's PINNED model declares ``vision`` (``/api/show``).

        Fails CLOSED on an unanswerable probe: an image turn must not run on a
        model we cannot confirm as multimodal.
        """
        caps = await self._capabilities(model, self._resolve_root())
        return caps is not None and "vision" in caps

    async def complete(self, req: BrainRequest) -> AsyncIterator[BrainDelta]:
        client = self._client
        if client is None:
            # First use imports the SDK — seconds on a cold disk, and never on
            # the event loop (BUG-189; see claude_api.py for the measurement).
            client = await asyncio.to_thread(self._ensure_client)
        need_vision = _request_has_images(req)
        model = await self._resolve_model(need_tools=bool(req.tools), need_vision=need_vision)
        if need_vision and self._model and not await self._pinned_model_can_see(model):
            # A pinned text-only model is the user's own choice, so we do not
            # silently swap it — but we also refuse to answer about a picture
            # it never saw. The caller degrades honestly (Screen Context says
            # it cannot look; the CU planner skips this brain).
            # An unavailable probe says nothing about model capabilities.
            # Keep the provider eligible for a later retry after recovery.
            caps = self._caps_cache.get(model)
            if caps is None:
                raise RuntimeError(
                    "Ollama could not verify this model's image capability. "
                    "Check the server connection and retry; no image was sent to the model."
                )
            if caps is not None:
                self.supports_vision = "vision" in caps
            raise RuntimeError(
                f"The configured Ollama model '{model}' cannot see images. Pick a "
                f"multimodal model on the Ollama card (ollama pull "
                f"{RECOMMENDED_VISION_PULL}), or leave the model empty so Dodaios "
                "picks a vision-capable download for image turns."
            )
        if need_vision:
            # The negotiated model DOES see — keep the instance flag honest for
            # the next synchronous resolver question.
            self.supports_vision = True
        call = await self._prepare_call(model, req)
        req = call.req
        root = self._resolve_root()
        native = self._native_context.get(model)
        # Refuse before sending what the window certainly cannot hold. Until
        # the server confirmed a window (a created profile, or an earlier
        # look at the loaded model) there is nothing to hold the request to.
        window = self._effective_window(call, root)
        if window:
            self.context_window = window
            local_context.ensure_fits(
                req, window, provider=self.name, model=model, kind="ollama", ceiling=native
            )
        # A temperature the person set on the model card is sent even to an
        # agent that chose none; otherwise the agent request profile decides.
        options = self._model_options(model)
        send_temperature = True if options is not None and options.temperature is not None else None
        # Invariant at this point: either the request carries no images, or the
        # model just negotiated declares ``vision`` — so the streamer may encode
        # them.
        stream = stream_complete(
            client, call.run_model, req, supports_vision=True, send_temperature=send_temperature
        )
        reported: int | None = None
        try:
            first = True
            async for delta in stream:
                if first:
                    # The first token proves the model is loaded, so the server
                    # can now say which window it really runs. Checked before
                    # anything is handed on: a prompt that was cut short must
                    # never reach the caller as an answer.
                    window = await self._verify_running_context(call, root, model) or window
                    if window:
                        self.context_window = window
                        local_context.ensure_fits(
                            req,
                            window,
                            provider=self.name,
                            model=model,
                            kind="ollama",
                            ceiling=native,
                            truncated=True,
                        )
                first = False
                if delta.usage:
                    reported = local_context.reported_prompt_tokens(delta.usage)
                yield delta
        except local_context.LocalContextError:
            raise
        except Exception as exc:
            if not local_context.is_overflow_refusal(str(exc)):
                raise
            # The server refused the size itself. Say how large the window has
            # to be and where to set it instead of passing a bare HTTP 400 on.
            raise local_context.refusal_error(
                req, provider=self.name, model=model, kind="ollama", window_tokens=window or 0
            ) from exc
        finally:
            await stream.aclose()
        if not window:
            # No profile and a server that does not report its window: judge
            # it by what it says it read.
            self._judge_reported_prompt(req, root, model, reported)

    def _judge_reported_prompt(
        self, req: BrainRequest, root: str, model: str, reported: int | None
    ) -> None:
        verdict, tokens = local_context.judge_reported_prompt(
            self.name, root, model, req, reported
        )
        if verdict == "tighten":
            self.context_window = tokens
            log.warning(
                "ollama: %s twice read about %d prompt tokens of requests at least "
                "twice that size, so the prompt is most likely being cut short. "
                "Planning the next turn for %d tokens. %s",
                model,
                tokens,
                tokens,
                local_context.fix_hint("ollama", local_context.certain_tokens(req)),
            )
        elif verdict == "restore":
            self.context_window = self._unconfirmed_budget(model)

    def _unconfirmed_budget(self, model: str) -> int:
        """What to budget for before any window is confirmed for ``model``.

        The floor every automatic window starts from, held to the model's own
        window where the cached catalog knows it — never the class figure,
        which the server does not run unless it is asked to.
        """
        from jarvis.brain.ollama_profiles import (  # noqa: PLC0415 — lazy (AP-26)
            AUTOMATIC_CONTEXT_FLOOR,
        )

        native = self._native_context.get(model)
        if native is None and model:
            try:
                from jarvis.brain.model_catalog import (  # noqa: PLC0415 — lazy (AP-26)
                    model_context_length,
                )

                native = model_context_length("ollama", model)
            except Exception:  # noqa: BLE001 — an unreadable catalog means "unknown"
                log.debug("ollama: cached context length unavailable for %s", model)
        return min(AUTOMATIC_CONTEXT_FLOOR, native) if native else AUTOMATIC_CONTEXT_FLOOR

    async def prepare_context_window(self) -> None:
        """Settle ``context_window`` before the caller budgets a turn.

        Tools are fitted before ``complete()`` runs, so a brain that only
        learned its window there would have its first turn planned for the
        wrong size. With a pinned model this sizes the window once (two local
        round-trips, then cached); a discovering brain keeps the floor until
        its first call picked a model. Never raises.
        """
        if not self._model or self._requested_context_window is not None:
            return
        try:
            root = self._resolve_root()
            options = self._model_options(self._model)
            planned = (
                options.num_ctx
                if options is not None and options.num_ctx
                else await self._planned_window(self._model)
            )
            # What the server was last seen running for this model wins over
            # the plan: a refused profile or a capped window is already known.
            seen = local_context.known_window(self.name, root, self._model)
            reported = seen[0] if seen is not None and seen[1] == "server" else None
            self.context_window = min(planned, reported) if reported else planned
        except Exception as exc:  # noqa: BLE001 — sizing must never cost the turn
            log.debug("ollama: could not settle the context window early: %s", exc)

    async def _planned_window(self, model: str) -> int:
        """The window ``model`` should run with when the person set none.

        The larger of what the model declares for itself (a Modelfile
        ``num_ctx``) and the automatic size: a model that already asks for
        more than the automatic window must not be shrunk by it.
        """
        automatic = await self._automatic_context(model)
        return max(automatic, self._declared_context.get(model) or 0)

    async def _automatic_context(self, model: str) -> int:
        """The window sized for this machine, once per server and model.

        Remembered for the life of the process, because a changed ``num_ctx``
        makes Ollama reload the weights. Only a complete answer is remembered:
        when the size or the model facts could not be read (a server still
        starting), the conservative result stands for this call and the next
        one asks again. Never raises.
        """
        root = self._resolve_root()
        key = (root, model.removesuffix(":latest"))
        cached = _AUTOMATIC_CONTEXT.get(key)
        if cached is not None:
            return cached
        from jarvis.brain import ollama_pull  # noqa: PLC0415 — lazy (AP-26)
        from jarvis.brain.ollama_inventory import same_model  # noqa: PLC0415
        from jarvis.brain.ollama_profiles import automatic_context  # noqa: PLC0415

        size_gb: float | None = None
        try:
            async with httpx.AsyncClient(
                timeout=CLIENT_TIMEOUT, headers=self._native_headers(),
            ) as client:
                resp = await client.get(f"{root}/api/tags")
                resp.raise_for_status()
                rows = resp.json().get("models") or []
            for row in rows:
                if same_model(str(row.get("name") or ""), model):
                    size = int(row.get("size") or 0)
                    size_gb = size / (1024**3) if size > 0 else None
                    break
        except Exception as exc:  # noqa: BLE001 — an unreadable size means the floor
            log.debug("ollama: size lookup for %s failed: %s", model, exc)
        if model not in self._native_context:
            await self._capabilities(model, root)
        if _is_this_machine(root):
            accelerator_gb, _source = await asyncio.to_thread(ollama_pull.accelerator_gb)
            ram_gb = await asyncio.to_thread(ollama_pull.total_memory_gb)
        else:
            # The server is another machine; this one's memory says nothing
            # about what fits there.
            accelerator_gb, ram_gb = 0.0, None
        tokens, reason = automatic_context(
            size_gb=size_gb,
            native_context=self._native_context.get(model),
            accelerator_gb=accelerator_gb,
            ram_gb=ram_gb,
        )
        if size_gb is not None and model in self._native_context:
            _AUTOMATIC_CONTEXT[key] = tokens
            # A brain built for the next turn budgets for this from the start.
            local_context.remember_window(
                self.name, root, model, tokens, source="plan", kind="ollama"
            )
        log.info("ollama: %s has no context set, using %s", model, reason)
        return tokens

    def _effective_window(self, call: _PreparedCall, root: str) -> int | None:
        """The window this call is known to run with, or ``None``.

        What the server last reported for the model about to stream wins,
        held to the plan; otherwise the plan counts only when the server
        accepted it.
        """
        running = _running_memo(root, call.run_model)
        if running:
            return min(running, call.planned) if call.planned else running
        return call.planned if call.confirmed else None

    async def _verify_running_context(
        self, call: _PreparedCall, root: str, model: str
    ) -> int | None:
        """Read the window the server RUNS and return the one this call has.

        ``/api/ps`` reports the context a loaded model was given. A smaller
        one than planned means the profile was not applied or the server
        capped it; the caller then refuses a request that already exceeds it
        instead of answering from a shortened prompt. The answer is kept for
        a few minutes per server and running model, and it is applied on
        every call, not only the one that fetched it. A server that does not
        report the figure leaves the plan standing.
        """
        key = (root, call.run_model.removesuffix(":latest"))
        memo = _RUNNING_CONTEXT.get(key)
        if memo is None or time.monotonic() - memo[1] > _RUNNING_TTL_S:
            from jarvis.brain.ollama_inventory import same_model  # noqa: PLC0415 — lazy (AP-26)

            running: int | None = None
            try:
                async with httpx.AsyncClient(
                    timeout=CLIENT_TIMEOUT, headers=self._native_headers(),
                ) as client:
                    resp = await client.get(f"{root}/api/ps")
                    resp.raise_for_status()
                    rows = resp.json().get("models") or []
                for row in rows:
                    if same_model(str(row.get("name") or row.get("model") or ""), call.run_model):
                        value = row.get("context_length")
                        if isinstance(value, (int, float)) and value > 0:
                            running = int(value)
                        break
            except Exception as exc:  # noqa: BLE001 — verification is best-effort
                log.debug("ollama: running-context check for %s failed: %s", call.run_model, exc)
                return self._effective_window(call, root)
            _RUNNING_CONTEXT[key] = (running, time.monotonic())
            if running is not None:
                effective = min(running, call.planned) if call.planned else running
                local_context.remember_window(
                    self.name, root, model, effective, source="server", kind="ollama"
                )
                if call.planned and running < call.planned:
                    log.warning(
                        "ollama: %s runs with %d tokens of context, not the %d that "
                        "were prepared. %s",
                        call.run_model,
                        running,
                        call.planned,
                        local_context.fix_hint(
                            "ollama", call.planned, ceiling=self._native_context.get(model)
                        ),
                    )
        return self._effective_window(call, root)

    def _model_options(self, model: str) -> OllamaModelOptions | None:
        """The user's per-model knobs for ``model`` from
        ``[brain.providers.ollama.models."<tag>"]``, or ``None``.

        Keyed by the RESOLVED tag, so a discovered model is tuned exactly like
        a pinned one. A config that cannot be read is logged and treated as
        "no options" — the turn must not die on a settings glitch (AP-30).
        """
        try:
            provider = cfg.load_config().brain.providers.get("ollama")
        except Exception as exc:  # noqa: BLE001 — a config glitch must not kill the turn
            log.warning("ollama: could not read per-model options: %s", exc)
            return None
        if provider is None:
            return None
        return (provider.models.get(model)
                or provider.models.get(model.removesuffix(":latest"))
                or provider.models.get(f"{model}:latest"))

    async def _apply_model_options(self, model: str, req: BrainRequest) -> tuple[str, BrainRequest]:
        """``(model to stream, request)`` for ``model`` — see ``_prepare_call``."""
        call = await self._prepare_call(model, req)
        return call.run_model, call.req

    async def _prepare_call(self, model: str, req: BrainRequest) -> _PreparedCall:
        """Turn the per-model options into what one call streams with.

        Bakeable knobs go through a derived profile alias (``/api/create``);
        ``keep_alive`` through the warm ping; ``temperature`` / ``num_predict``
        / ``think`` override the request — but only where the caller left the
        field at its default, so a deterministic tool step that asked for
        ``temperature=0`` or ``reasoning_effort="none"`` keeps its own choice.

        The context window is never left to the server's default, which is
        small and shortens a longer prompt without an error: the runtime's
        allocation wins, then the person's own ``num_ctx``, then the larger of
        the model's own declaration and the automatic size. Everything this
        call needs afterwards is returned, not kept on the instance: one
        brain serves concurrent calls.
        """
        opts = self._model_options(model)
        # ``confirmed``: the server is known to run ``planned`` without a
        # profile, because the model itself declares it.
        confirmed = False
        if self._requested_context_window is not None:
            if opts is not None and opts.num_ctx and opts.num_ctx < self._requested_context_window:
                raise RuntimeError("The local model context changed. Start the turn again.")
            opts = (opts or OllamaModelOptions()).model_copy(
                update={"num_ctx": self._requested_context_window}
            )
            planned: int | None = self._requested_context_window
        elif opts is not None and opts.num_ctx:
            planned = opts.num_ctx
        else:
            planned = await self._planned_window(model)
            declared = self._declared_context.get(model)
            if declared and declared >= planned:
                confirmed = True
            else:
                opts = (opts or OllamaModelOptions()).model_copy(update={"num_ctx": planned})
        from jarvis.brain.ollama_profiles import (  # noqa: PLC0415 — lazy (AP-26)
            ensure_profile,
            has_bakeable,
            profile_name,
            to_v1_kwargs,
            warm,
        )

        root = self._resolve_root()
        run_model = model
        if opts is not None and has_bakeable(opts):
            refused_key = (root, profile_name(model, opts))
            refused_at = _PROFILE_REFUSED.get(refused_key)
            if refused_at is not None and time.monotonic() - refused_at < _PROFILE_REFUSED_TTL_S:
                # This server said no a moment ago; asking again on every turn
                # costs two round-trips and a warning each time.
                created = False
            else:
                try:
                    run_model = await ensure_profile(
                        root, model, opts, headers=self._native_headers()
                    )
                    created = True
                    _PROFILE_REFUSED.pop(refused_key, None)
                except Exception as exc:  # noqa: BLE001 — degrade to the base model, say so
                    if self._requested_context_window is not None:
                        # The runtime already budgets against this window.
                        # Sending to the base model would silently serve a
                        # smaller context.
                        raise RuntimeError(
                            "Could not prepare the selected local model context."
                        ) from exc
                    _PROFILE_REFUSED[refused_key] = time.monotonic()
                    log.warning(
                        "ollama: profile for %s unavailable, running the base model with "
                        "the server's own context instead of %s tokens (%s)",
                        model,
                        opts.num_ctx,
                        exc,
                    )
                    created = False
            if opts.num_ctx:
                confirmed = created
        if opts is not None and opts.keep_alive is not None:
            await warm(root, run_model, opts.keep_alive, headers=self._native_headers())
        overrides: dict[str, Any] = {}
        defaults = {f.name: f.default for f in fields(BrainRequest)}
        for key, value in to_v1_kwargs(opts).items():
            if getattr(req, key, None) == defaults.get(key):
                overrides[key] = value
        if planned and confirmed:
            # Only a window the server accepted is published for the next
            # turn's budget. After a refused profile the running window is
            # whatever the server defaults to; ``_verify_running_context``
            # reads it once the model has loaded.
            self.context_window = planned
        return _PreparedCall(
            run_model=run_model,
            req=replace(req, **overrides) if overrides else req,
            planned=planned,
            confirmed=bool(planned and confirmed),
        )

    def estimate_cost(self, req: BrainRequest) -> float:
        # Local inference has no per-token bill.
        return 0.0
