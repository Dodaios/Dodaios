"""The REST routes registered inline on the app."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI
from fastapi.responses import Response
from loguru import logger
from pydantic import BaseModel

from dodaios import __version__
from dodaios.core import module_health
from dodaios.core.events import (
    SystemStarted,
)
from dodaios.core.registry import list_all_plugins
from dodaios.terminal import discover_shells


if TYPE_CHECKING:
    pass



class MemoryFactBody(BaseModel):
    """Body of ``POST``/``DELETE /api/memory/facts``.

    Typed so a non-string ``fact`` is a 422 at the boundary instead of an
    ``AttributeError`` (500) inside the handler.
    """

    fact: str
    category: str = "general"


class RestRoutesMixin:
    """The REST routes registered inline on the app."""

    def _register_rest_routes(self, app: FastAPI) -> None:
        from dodaios.core.instance import current_instance as _ci

        def _instance_name() -> str:
            return _ci().name

        cfg = self.cfg
        bus = self.bus

        @app.get("/api/health")
        async def health() -> dict[str, Any]:
            # ``instance`` lets the frontend badge a dev window as such
            # (``dodaios.core.instance``): "default" or "dev".
            # ``degraded`` names the optional modules that failed to start or
            # load; the app answers without them (reasons: /api/diagnostics/modules).

            return {
                "ok": True,
                "version": __version__,
                "instance": _instance_name(),
                "degraded": module_health.degraded_names(),
            }

        @app.post("/api/ui/shell-painted", status_code=204, response_model=None)
        async def shell_painted() -> Response:
            # FastBootstrap consumes this acknowledgement during warm-up. A
            # browser can paint after the full FastAPI app has already taken
            # over, so the live app must accept the same POST as an idempotent
            # no-op instead of returning FastAPI's 405 Method Not Allowed.
            return Response(status_code=204)

        @app.get("/api/config")
        async def get_config() -> dict[str, Any]:
            # Read-only snapshot — secrets are, by design, never in the config.
            return cfg.model_dump()

        @app.get("/api/plugins")
        async def get_plugins() -> dict[str, list[str]]:
            try:
                return list_all_plugins()
            except Exception as exc:  # noqa: BLE001
                logger.opt(exception=exc).warning("Plugin discovery failed")
                return {}

        @app.post("/api/debug/emit-test-event")
        async def emit_test_event() -> dict[str, Any]:
            evt = SystemStarted(version=__version__, source_layer="ui.web.debug")
            await bus.publish(evt)
            return {
                "ok": True,
                "event": "SystemStarted",
                "trace_id": str(evt.trace_id),
            }

        @app.post("/api/window/focus")
        async def window_focus() -> dict[str, Any]:
            # Placeholder until the desktop shell replaces this with a real
            # raise. Headless / VPS has no window: ok=False so a later
            # desktop launch does not treat this ACK as "I brought a window
            # forward" and silently exit (BUG-182).
            return {"ok": False, "focused": False, "reason": "no_window"}

        @app.get("/api/brain/status")
        async def brain_status() -> dict[str, Any]:
            """Returns the currently active brain provider + model.

            The frontend uses this on mount to initialize the sidebar footer
            correctly (instead of assuming the hardcoded "claude-api"
            default). Live switches still arrive via the WS event
            ``BrainProviderChanged``.
            """
            brain = getattr(app.state, "brain", None)
            # BrainManager exposes `active_provider`. MockBrain only has `name`.
            # Fast-boot deferral: the heavy BrainManager build runs in a
            # background thread, so `app.state.brain` is None for the first
            # ~850 ms while uvicorn already serves. In that window fall back to
            # the configured primary provider — it already names the brain that
            # WILL become active — instead of "unknown", which would freeze the
            # sidebar footer on a bare "—" until a manual provider switch (the
            # mount-fetch is one-shot and nothing re-fetches once the build
            # finishes).
            provider = (
                getattr(brain, "active_provider", None)
                or getattr(brain, "name", None)
                or cfg.brain.primary
                or "unknown"
            )
            prov_cfg = cfg.brain.providers.get(provider)
            model = getattr(prov_cfg, "model", None) if prov_cfg else None
            return {"provider": provider, "model": model or "unknown"}

        @app.get("/api/voice/status")
        async def voice_status() -> dict[str, Any]:
            """Return the current voice boot-readiness flag.

            The frontend reads this on mount to initialize the "voice starting"
            badge correctly — the ``VoiceBootStatus`` WS event is one-shot, so a
            late-connecting UI would miss it. The value is maintained by the bus
            subscriber in ``_build_app`` on the server instance.
            """
            return {"ready": bool(getattr(self, "_voice_ready", False))}

        async def _jarvis_agent_status_snapshot() -> dict[str, Any]:
            """Jarvis-Agent bridge status for the settings view (Wave 3).

            Read-only snapshot:

            * ``configured``       — is the ``[harness.jarvis_agent]`` block
              (legacy alias: ``[harness.openclaw]``) present in jarvis.toml?
            * ``enabled``          — bridge toggle from the block
            * ``binary_path``      — configured path
            * ``binary_detected``  — resolver result (PATH + .cmd/.ps1/.exe)
            * ``version_pin``      — AD-21 pin (None when the block is missing)
            * ``brain_primary``    — active SUBAGENT provider
              (``[brain.sub_jarvis].provider``); falls back to ``brain.primary``
              only when no subagent provider is set. NOT the router
              brain — the subagent runs the heavy tasks.
            * ``provider_slug``    — worker slug of the active subagent
              provider per AD-6 (claude-api->claude-cli)
            * ``model_resolved``   — override from config OR the frontier-deep
              model of the active subagent provider
            * ``mapping``          — the full slug-mapping table

            Contract: docs/jarvis-agents-bridge.md §4.3 wizard/setup extension.
            The endpoint returns NO secrets — only a boolean for whether a key is set.
            """
            import shutil

            from ..agent_status import subscription_statuses

            codex_bin = getattr(getattr(cfg, "codex", None), "binary_path", "") or None
            auth_statuses = await subscription_statuses(codex_bin)

            oc_cfg = cfg.harness.jarvis_agent
            router_primary = (cfg.brain.primary or "").lower()

            try:
                from dodaios.missions.worker_runtime.provider_map import (
                    MAPPINGS,
                    canonical_worker_provider,
                    to_worker_slug,
                )
            except Exception:  # noqa: BLE001
                MAPPINGS = ()  # type: ignore[assignment]
                to_worker_slug = None  # type: ignore[assignment]
                canonical_worker_provider = None  # type: ignore[assignment]

            # The HEAVY-TASK subagent runs on ``[brain.worker].provider`` —
            # NOT on ``brain.primary`` (that is only the lightweight router
            # brain). Mark the brain that ACTUALLY executes heavy tasks as
            # active; fall back to the router brain only when no subagent
            # provider is configured (worker then uses its default chain).
            # Mirrors dodaios/missions/init.py::_worker_factory so the displayed
            # brain never drifts from the worker that runs. (Bug 2026-05-28:
            # the UI showed Gemini active while heavy work ran on Claude.)
            sub_cfg = getattr(cfg.brain, "worker", None)
            sub_raw = getattr(sub_cfg, "provider", None) if sub_cfg is not None else None
            sub_provider = (
                canonical_worker_provider(sub_raw)
                if canonical_worker_provider is not None
                else None
            )
            primary = sub_provider or router_primary

            # Model: an explicit ``[brain.sub_jarvis].model`` wins; else the
            # active provider's deep_model (frontier) from
            # ``[brain.providers.<provider>]``.
            sub_model_override = getattr(sub_cfg, "model", None) if sub_cfg is not None else None
            prov_cfg = cfg.brain.providers.get(primary)
            primary_deep_model = (sub_model_override or "").strip() or (
                getattr(prov_cfg, "deep_model", None) or getattr(prov_cfg, "model", None)
                if prov_cfg
                else None
            )

            provider_slug: str | None = None
            if to_worker_slug is not None:
                try:
                    provider_slug = to_worker_slug(primary)
                except Exception:  # noqa: BLE001
                    provider_slug = None

            model_resolved: str | None = None
            if oc_cfg is not None and oc_cfg.model:
                model_resolved = oc_cfg.model
            elif provider_slug and primary_deep_model:
                model_resolved = f"{provider_slug}/{primary_deep_model}"

            binary_path = oc_cfg.binary_path if oc_cfg is not None else "openclaw"

            def _detect_binary() -> str | None:
                """Resolve the bridge binary — up to four full PATH scans."""
                found = shutil.which(binary_path)
                if found:
                    return found
                for ext in (".cmd", ".ps1", ".exe"):
                    cand = shutil.which(binary_path + ext)
                    if cand:
                        return cand
                return None

            # Off the loop: a PATH scan walks every directory on PATH, and on a
            # long Windows PATH that is the slowest thing this route does. Left
            # inline it froze every other section for as long as it took.
            binary_detected: str | None = await asyncio.to_thread(_detect_binary)

            from dodaios.brain.assistant_name import agent_brand
            from dodaios.core.config import (
                get_jarvis_agent_secret,
                get_provider_secret,
                get_secret,
                jarvis_agent_secret_slot,
            )
            from dodaios.ui.web.provider_spec import get_spec

            # Display brand follows the wake-word-derived assistant name.
            brand = agent_brand(cfg)

            def _key_flags(
                slot: tuple[str, str] | None, provider: str
            ) -> tuple[bool, bool]:
                """Whether a dedicated and/or a shared credential exists."""
                try:
                    dedicated = bool(slot and get_secret(slot[0], env_fallback=slot[1]))
                    shared = bool(get_provider_secret(provider))
                except Exception:  # noqa: BLE001 — one unreadable store hides no other row
                    return False, False
                return dedicated, shared

            mapping_rows = []
            for mapping in MAPPINGS:
                slot = jarvis_agent_secret_slot(mapping.jarvis)
                secret_key = slot[0] if slot else None
                # Off the loop: each of these reads the OS credential store,
                # which blocks for as long as that store feels like taking.
                dedicated_key_set, shared_key_set = await asyncio.to_thread(
                    _key_flags, slot, mapping.jarvis
                )
                api_key_set = dedicated_key_set or shared_key_set
                oauth_connected = False
                oauth_stale = False
                # Claude subscription auth is owned by the CLI. Its status
                # command covers platform-native stores such as macOS Keychain;
                # the legacy bearer-file check only preserves the recoverable
                # expired state for older Linux/Windows installs.
                if mapping.jarvis == "claude-api":
                    try:
                        from dodaios.claude_credentials import (
                            freshest_claude_oauth,
                        )

                        auth_status = auth_statuses["claude"]
                        oauth_connected = bool(
                            auth_status.connected and auth_status.mode == "subscription"
                        )
                        snapshot_status = freshest_claude_oauth().status
                        oauth_stale = not oauth_connected and snapshot_status == "expired"
                    except Exception:  # noqa: BLE001
                        oauth_connected = False
                        oauth_stale = False
                spec = get_spec(mapping.jarvis)
                # A keyless local provider has nothing to save, so every
                # credential question below has to answer differently for it.
                # Without this the card demanded "save a dedicated ollama key
                # on this card", offered a field for a key that does not exist,
                # and refused activation — a local-only install could pick no
                # worker at all. Read off the card's own auth mode, never a
                # provider name (AP-21).
                keyless = bool(spec and spec.auth_mode == "none")
                # claude-api is dual-billed like Codex/Antigravity: the Claude Max
                # subscription (claude CLI OAuth login) OR an Anthropic API key.
                # Every other MAPPINGS provider bills per token on an API account.
                row_billing = (
                    "local"
                    if keyless
                    else "subscription_or_api"
                    if mapping.jarvis == "claude-api"
                    else "api"
                )
                credential_source = (
                    "dedicated"
                    if dedicated_key_set
                    else "legacy_shared"
                    if shared_key_set
                    else "oauth"
                    if oauth_connected or oauth_stale
                    else "none"
                )
                mapping_rows.append(
                    {
                        "jarvis": mapping.jarvis,
                        "worker_slug": mapping.worker_slug,
                        "env_var": mapping.env_var,
                        "env_fallback": mapping.env_fallback,
                        # Readiness, not credential presence: a keyless card is
                        # ready the moment it exists, and gating it on a key it
                        # never has locked it out of the picker entirely.
                        "key_set": (
                            True if keyless else api_key_set or oauth_connected or oauth_stale
                        ),
                        "api_key_set": api_key_set,
                        "dedicated_key_set": dedicated_key_set,
                        "shared_key_set": shared_key_set,
                        "oauth_connected": oauth_connected,
                        "oauth_stale": oauth_stale,
                        "credential_source": "none" if keyless else credential_source,
                        # No key field on a card with no key slot.
                        "secret_key": None if keyless else secret_key,
                        "keyless": keyless,
                        # The card's own name, so the picker stops showing raw
                        # ids like "local-openai" next to "xAI Grok".
                        "label": spec.label if spec else mapping.jarvis,
                        "dashboard_url": spec.dashboard_url if spec else None,
                        "credential_help": (
                            f"Runs on your own hardware — no key, nothing leaves "
                            f"this machine. Configure its server on the "
                            f"{spec.label} card under Brain."
                            if keyless and spec
                            else f"Dedicated {brand} key for {spec.label}. "
                            "It is not used by Brain or Realtime."
                            if spec
                            else f"Dedicated {brand} API key."
                        ),
                        "is_active_brain": mapping.jarvis == primary,
                        "billing": row_billing,
                    }
                )

            # Codex is a DIRECT worker (CodexDirectWorker) with no worker slug,
            # so it is not in MAPPINGS. Surface it as an explicit selectable
            # subagent row. Backed by the ChatGPT subscription (OAuth) OR an
            # OpenAI API key — "key_set" is true when either is present.
            try:
                codex_status = auth_statuses["codex"]
                codex_connected = codex_status.connected
                codex_installed = codex_status.installed
            except Exception:  # noqa: BLE001
                codex_connected = False
                codex_installed = False
            try:
                codex_key = bool(
                    get_secret(
                        "codex_openai_api_key",
                        env_fallback="CODEX_OPENAI_API_KEY",
                    )
                )
            except Exception:  # noqa: BLE001
                codex_key = False
            mapping_rows.append(
                {
                    "jarvis": "openai-codex",
                    "openclaw": "codex-cli (direct)",
                    "env_var": "ChatGPT-OAuth",
                    "env_fallback": "OPENAI_API_KEY",
                    "key_set": codex_connected or (codex_installed and codex_key),
                    "api_key_set": codex_key,
                    "dedicated_key_set": codex_key,
                    "shared_key_set": False,
                    "oauth_connected": codex_connected,
                    "credential_source": (
                        "oauth" if codex_connected else "dedicated" if codex_key else "none"
                    ),
                    "secret_key": "codex_openai_api_key",
                    "dashboard_url": "https://platform.openai.com/api-keys",
                    # Framed as the ALTERNATIVE to the ChatGPT login — the old
                    # wording made the subscription card look like it required
                    # an OpenAI API key (user report 2026-07-17).
                    "credential_help": (
                        "No ChatGPT login? Paste an OpenAI API key instead — "
                        "Codex then bills per token. Not used by Brain or "
                        "Realtime."
                    ),
                    "is_active_brain": primary == "openai-codex",
                    # ChatGPT subscription OAuth OR an OpenAI API key.
                    "billing": "subscription_or_api",
                }
            )

            # Antigravity is a DIRECT worker (GoogleCliWorker over the official
            # agy/Gemini CLI) with no worker slug, so it is not in MAPPINGS —
            # the Google sibling of Codex. Dual billing, mirror of Codex: the
            # installed Google CLI plus either its subscription OAuth login or
            # a Gemini API key (per token). A key cannot replace the executable.
            antigravity_status = None
            try:
                from dodaios.google_cli.auth_service import (
                    antigravity_provider_ready,
                )

                antigravity_status = auth_statuses["google"]
                antigravity_connected = (
                    antigravity_status.connected and antigravity_status.mode == "oauth-personal"
                )
            except Exception:  # noqa: BLE001
                antigravity_connected = False
            try:
                antigravity_key = bool(get_jarvis_agent_secret("gemini"))
            except Exception:  # noqa: BLE001
                antigravity_key = False
            antigravity_ready = (
                antigravity_provider_ready(
                    antigravity_status,
                    api_key_present=antigravity_key,
                )
                if antigravity_status is not None
                else False
            )
            mapping_rows.append(
                {
                    "jarvis": "antigravity",
                    "openclaw": "agy-cli (direct)",
                    "env_var": "Google-OAuth",
                    "env_fallback": "GEMINI_API_KEY",
                    # The worker DRIVES the agy/Gemini CLI — a Gemini API key
                    # alone, with no CLI on the machine, must never render the
                    # card "Ready" (Windows test-machine report 2026-07-18:
                    # Antigravity showed Ready although never installed, then
                    # every run died at spawn). Mirrors the Codex row's
                    # installed-gate below.
                    "key_set": antigravity_ready,
                    "api_key_set": antigravity_key,
                    "dedicated_key_set": False,
                    "shared_key_set": False,
                    "oauth_connected": antigravity_connected,
                    "credential_source": (
                        "oauth"
                        if antigravity_connected
                        else "gemini_agent_key"
                        if antigravity_key
                        else "none"
                    ),
                    "secret_key": None,
                    "dashboard_url": None,
                    "credential_help": None,
                    "is_active_brain": primary == "antigravity",
                    # Google subscription OAuth OR a Gemini API key.
                    "billing": "subscription_or_api",
                }
            )

            # Grok Build is a DIRECT worker (GrokBuildDirectWorker over the
            # official grok CLI) with no worker slug, so it is not in MAPPINGS.
            # SuperGrok / X Premium+ subscription only — the xAI API-key path
            # stays on the separate ``grok`` card.
            grok_build_status = None
            try:
                from dodaios.grok_build_auth import (
                    grok_build_provider_ready,
                )

                grok_build_status = auth_statuses["grok"]
                grok_build_connected = (
                    grok_build_status.connected and grok_build_status.mode == "subscription"
                )
            except Exception:  # noqa: BLE001
                # A probe that cannot answer means "not connected" on this
                # overview row, which is the safe reading and one the user can
                # see. The Agents tab runs the same check and reports the real
                # cause there; this row must never take the whole page down.
                grok_build_connected = False
            grok_build_ready = (
                grok_build_provider_ready(grok_build_status)
                if grok_build_status is not None
                else False
            )
            mapping_rows.append(
                {
                    "jarvis": "grok-build",
                    "openclaw": "grok-cli (direct)",
                    "env_var": "SuperGrok-OAuth",
                    "env_fallback": None,
                    "key_set": grok_build_ready,
                    "api_key_set": False,
                    "dedicated_key_set": False,
                    "shared_key_set": False,
                    "oauth_connected": grok_build_connected,
                    "credential_source": "oauth" if grok_build_connected else "none",
                    "secret_key": None,
                    "dashboard_url": None,
                    "credential_help": None,
                    "is_active_brain": primary == "grok-build",
                    "billing": "subscription",
                    "label": "Grok Build",
                }
            )

            return {
                "configured": oc_cfg is not None,
                "enabled": bool(oc_cfg.enabled) if oc_cfg else False,
                "binary_path": binary_path,
                "binary_detected": binary_detected,
                "version_pin": oc_cfg.version if oc_cfg else None,
                "time_cap_min": oc_cfg.time_cap_min if oc_cfg else None,
                "concurrency": oc_cfg.concurrency if oc_cfg else None,
                "state_dir_root": oc_cfg.state_dir_root if oc_cfg else None,
                "brain_primary": primary,
                "provider_slug": provider_slug,
                "model_override": oc_cfg.model if oc_cfg else None,
                # The dedicated subagent LLM pin ([brain.sub_jarvis].model);
                # empty/None means "provider's deep model" (model_resolved).
                "sub_model_override": sub_model_override,
                "model_resolved": model_resolved,
                "mapping": mapping_rows,
            }

        pending_agent_status: asyncio.Task[dict[str, Any]] | None = None

        @app.get("/api/jarvis-agent/status")
        async def jarvis_agent_status() -> dict[str, Any]:
            """Read bridge configuration and provider credential readiness without secrets."""
            nonlocal pending_agent_status
            from ..agent_status import observe_status_result

            # Several windows ask together. Share only unfinished work so a new
            # read after a login or config change still gets a fresh snapshot.
            if pending_agent_status is None or pending_agent_status.done():
                pending_agent_status = asyncio.create_task(_jarvis_agent_status_snapshot())
                pending_agent_status.add_done_callback(observe_status_result)
            return await asyncio.shield(pending_agent_status)

        @app.get("/api/memory/facts")
        async def get_memory_facts() -> dict[str, Any]:
            """Returns the core memory (persona, user facts, preferences).

            The frontend shows this in the notes view, so the user can see
            what Jarvis has remembered. core_memory.json is automatically
            injected into the system prompt on the next brain call — so this
            view is a read-only mirror of the persistent memory state.
            """
            from dodaios.core.config import DATA_DIR
            from dodaios.memory import CORE_MEMORY_FILENAME, CoreMemory

            from ..error_text import LOG_HINT

            try:
                mem = CoreMemory.load(DATA_DIR / CORE_MEMORY_FILENAME)
                return {"ok": True, "data": mem.all()}
            except Exception as exc:  # noqa: BLE001
                logger.opt(exception=exc).warning("Memory read error")
                return {"ok": False, "error": "memory read failed. " + LOG_HINT, "data": {}}

        @app.post("/api/memory/facts")
        async def add_memory_fact(payload: MemoryFactBody) -> dict[str, Any]:
            """User-driven add from the UI."""
            from dodaios.core.config import DATA_DIR
            from dodaios.memory import CORE_MEMORY_FILENAME, CoreMemory

            from ..error_text import LOG_HINT

            fact = payload.fact.strip()
            category = payload.category.strip() or "general"
            if not fact:
                return {"ok": False, "error": "fact is missing"}
            try:
                mem = CoreMemory.load(DATA_DIR / CORE_MEMORY_FILENAME)
                mem.add_fact(fact, category=category)
                return {"ok": True, "data": mem.all()}
            except Exception as exc:  # noqa: BLE001
                logger.opt(exception=exc).warning("Memory write error")
                return {"ok": False, "error": "memory write failed. " + LOG_HINT}

        @app.delete("/api/memory/facts")
        async def delete_memory_fact(payload: MemoryFactBody) -> dict[str, Any]:
            """User-driven remove from the UI."""
            from dodaios.core.config import DATA_DIR
            from dodaios.memory import CORE_MEMORY_FILENAME, CoreMemory

            from ..error_text import LOG_HINT

            fact = payload.fact.strip()
            category = payload.category.strip() or "general"
            if not fact:
                return {"ok": False, "error": "fact is missing"}
            try:
                mem = CoreMemory.load(DATA_DIR / CORE_MEMORY_FILENAME)
                ok = mem.remove_fact(fact, category=category)
                return {"ok": ok, "data": mem.all()}
            except Exception as exc:  # noqa: BLE001
                logger.opt(exception=exc).warning("Memory delete error")
                return {"ok": False, "error": "memory delete failed. " + LOG_HINT}

        @app.get("/api/terminal/shells")
        async def terminal_shells() -> dict[str, Any]:
            """Returns all shells installed on this system.

            The frontend uses this to populate the shell dropdown with only
            available options — no "command not found" on spawn.
            """
            return {"shells": [{"id": s.id, "label": s.label} for s in discover_shells()]}
