"""Phases of the desktop backend boot (``DesktopApp._run_backend``).

``_run_backend`` used to be one 1,370-line function. Each phase is now one method
of :class:`BackendBoot`, called by ``_run_backend`` in the original order. Nothing
here changes what runs or when: heavy imports stay inside the phase that did them,
every thread and task starts at the same point, and the exception handling is the
same. State that later phases read lives on the ``BackendBoot`` instance.

Everything that used to be a local of ``_run_backend`` and is needed by a later
phase is an attribute: ``loop``, ``bootstrap``, ``server``, ``supervisor``,
``chat_store``, ``turn_traces``, ``brain_holder`` and the brain/MCP/service
coroutines the heavy backend task schedules.

The module imports ``desktop_app`` at its top and ``desktop_app`` imports this
module only inside ``_run_backend``, so there is no import cycle and nothing here
loads before the backend thread starts.
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from dodaios.ui import desktop_app as _da


class BackendBoot:
    """One backend boot: build it with the app, call the phases in order."""

    def __init__(self, app: Any) -> None:
        self.app = app
        self.loop: asyncio.AbstractEventLoop
        self.bootstrap: Any
        self.server: Any
        self.heavy: SimpleNamespace
        self.supervisor: Any
        self.chat_store: Any
        self.turn_traces: Any
        self.brain_holder: dict[str, Any]
        self.brain_ready: asyncio.Event
        self.bp = False
        self.bp_t0 = 0.0
        self.bp_last = 0.0

    # ---- Boot profiling (JARVIS_BOOT_PROFILE=1) ---------------------------

    def db_mark(self, _name: str) -> None:
        _now = time.perf_counter()
        if self.bp:
            print(
                f"[BOOT_PROFILE] db_{_name}={(_now - self.bp_last) * 1000.0:.1f}",
                flush=True,
            )
        self.bp_last = _now

    def db_boot_ready(self) -> None:
        if self.bp:
            print(
                f"BOOT_READY_MS={(time.perf_counter() - self.bp_t0) * 1000.0:.1f}",
                flush=True,
            )

    # ---- Phases, in boot order ---------------------------------------------

    def install_loop(self, prebound: tuple[Any, Any] | None) -> None:
        """Create or adopt the backend loop, prewarm its executor, set up boot profiling."""
        app = self.app
        if prebound is not None:
            # Fast-boot launcher path: the loop already exists and the bootstrap
            # is already bound + serving (the launcher did that BEFORE importing
            # this heavy module, so the bind beat the import floor). Reuse them.
            loop, _prebound_bootstrap = prebound
            app._backend_thread = threading.current_thread()
        else:
            loop = asyncio.new_event_loop()
            _prebound_bootstrap = None
        asyncio.set_event_loop(loop)
        app._backend_loop = loop

        # Before anything can await: hand the loop a default executor that is
        # already at full size, so ``asyncio.to_thread`` never has to grow one
        # under it. Growing costs a synchronous ``Thread.start()`` ON the loop,
        # and three of the worst stalls measured 2026-07-29 (75.7 s, 16.6 s,
        # 15.3 s) were exactly that. Filling it happens on a background thread,
        # so this call itself is a pool allocation (AP-26).
        try:
            from dodaios.core.loop_executor import install_prewarmed_default_executor

            app._io_executor = install_prewarmed_default_executor(loop)
        except Exception:  # noqa: BLE001 — a loop that can still stall is the
            # behaviour we shipped yesterday; a boot that fails is not.
            from loguru import logger as _ex_log

            _ex_log.opt(exception=True).warning(
                "Could not install the prewarmed default executor — "
                "asyncio.to_thread may stall the loop while the pool grows."
            )
            app._io_executor = None

        # Cold-boot profiling (gated behind JARVIS_BOOT_PROFILE=1; production
        # stdout unchanged). The desktop window only appears once
        # ``_wait_for_backend`` sees ``/api/health`` 200, which the backend can
        # answer the moment it is serving. BOOT_READY_MS below is therefore the
        # honest "the window can be created now" anchor — the same anchor the
        # headless harness uses (``scripts/measure_desktop_boot.py``).
        _bp = os.environ.get("JARVIS_BOOT_PROFILE") == "1"
        _bp_t0 = time.perf_counter()
        _bp_last = _bp_t0
        # Expose the boot t0 so ``_start_speech_and_orb`` can emit an honest
        # ``VOICE_READY_MS`` anchor (wake loop armed) on the SAME clock as
        # ``BOOT_READY_MS`` (window appears). The gap between the two is the
        # wake-boot cost the user actually feels ("the window is fast but
        # talking to it takes forever"). Gated identically; production stdout
        # unchanged.
        app._bp_t0 = _bp_t0
        app._bp = _bp
        self.loop = loop
        self._prebound_bootstrap = _prebound_bootstrap
        self.bp = _bp
        self.bp_t0 = _bp_t0
        self.bp_last = _bp_last

    def bind_bootstrap(self) -> None:
        """Bind the tiny serve-first bootstrap on the admin port (or adopt the prebound one)."""
        app = self.app
        loop = self.loop
        _prebound_bootstrap = self._prebound_bootstrap
        _db_boot_ready = self.db_boot_ready
        if _prebound_bootstrap is not None:
            # Already bound + BOOT_READY emitted by the launcher — just adopt it.
            bootstrap = _prebound_bootstrap
            app._bootstrap = bootstrap
        else:
            from dodaios.ui.web.fast_bootstrap import FastBootstrap

            bootstrap = FastBootstrap(
                session_token=app.session_token,
                vite_dev_url=(app.cfg.ui.vite_dev_url if app.cfg.ui.dev_mode else None),
            )
            try:
                loop.run_until_complete(bootstrap.serve("127.0.0.1", app.cfg.ui.admin_api_port))
            except Exception as exc:
                app._backend_boot_error = exc
                raise
            app._bootstrap = bootstrap
            _db_boot_ready()  # /api/health is servable now → window can appear

        def _log_unhandled_async(loop_: asyncio.AbstractEventLoop, context: dict) -> None:
            exc = context.get("exception")
            msg = context.get("message", "<no message>")
            from loguru import logger as _logger

            if exc is not None:
                _logger.opt(exception=exc).error("Unhandled asyncio exception: {}", msg)
            else:
                # The task names the leak; the message alone never does.
                _logger.error("Asyncio event context: {} ({!r})", msg, context.get("task"))

        loop.set_exception_handler(_log_unhandled_async)
        self.bootstrap = bootstrap

    def wait_for_shell_paint(self) -> None:
        """Hold the heavy imports until the window has painted (12 s backstop)."""
        app = self.app
        loop = self.loop
        if app._bootstrap is not None:
            shell_painted = loop.run_until_complete(app._bootstrap.wait_shell_painted(timeout=12.0))
            from loguru import logger as _boot_logger

            if shell_painted:
                _boot_logger.info("Desktop boot shell painted; heavy initialization released.")
            else:
                _boot_logger.warning(
                    "Desktop boot shell paint was not acknowledged within 12s; "
                    "releasing heavy initialization through the bounded fallback."
                )

    def start_prefetch(self) -> None:
        """Start the wake/TTS import prefetch, audio device settle and wake-model prefetch."""
        app = self.app
        from dodaios.speech.warmup_prefetch import (
            start_tts_import_prefetch,
            start_wake_import_prefetch,
        )

        start_wake_import_prefetch()
        # Same idea for the default TTS SDK (google-genai). This is disjoint
        # from the wake import and remains a logged no-op for another provider
        # or a headless host without the optional dependency.
        start_tts_import_prefetch()
        # Background providers import their SDK when their actual consumer
        # needs it. Warming every installed SDK here competes with voice and
        # the route graph even when the selected providers never use it.

        # Start the audio-device settle after the shell paint too. Phase A then
        # reuses the result instead of re-paying the blocking stability poll.
        from dodaios.audio.device_init import start_audio_device_prefetch

        start_audio_device_prefetch()

        # Wake-model prefetch overlaps the heavy backend build and is adopted by
        # the later provider warm-up. It is a no-op when voice is disabled and
        # must never make the visible desktop startup load-bearing.
        # ``app_cfg`` lets it skip itself on a host whose wake engine never
        # builds a Whisper to adopt the weights (vosk_kws, custom_onnx, OWW):
        # there the load was ~50 s of cold disk for nothing, in front of the
        # models the user is actually waiting for (BUG-214).
        try:
            from dodaios.plugins.stt import start_wake_model_prefetch

            start_wake_model_prefetch(app.cfg.stt, app_cfg=app.cfg)
        except Exception:  # noqa: BLE001, S110 — prefetch never blocks boot
            pass

    def build_server(self) -> None:
        """Import the heavy modules and build the WebServer in a worker thread."""
        app = self.app
        loop = self.loop
        _db_mark = self.db_mark
        from dodaios.brain.factory import build_default_brain
        from dodaios.core.events import (
            ComposeRequested,
            ErrorOccurred,
            MessageSent,
            ResponseGenerated,
            ShowWindowRequested,
        )
        from dodaios.mcp import state as mcp_state
        from dodaios.mcp.registry import MCPRegistry
        from dodaios.state.chat_store import ChatStore, default_chats_db_path
        from dodaios.state.supervisor import Supervisor
        from dodaios.ui.web.server import WebServer  # lazy to avoid a circular import

        _db_mark("pre_webserver")
        # Build the FastAPI app + all routes (~1 s, CPU-bound) in a worker thread
        # via the running loop, so the loop stays free to answer the bootstrap's
        # /api/health while it builds — that is what lets the window appear at
        # bind time rather than after the ~1 s ctor. WebServer.__init__ is
        # loop-agnostic (pure construction + route mounting), so off-loop is safe.
        server = loop.run_until_complete(
            asyncio.to_thread(WebServer, app.cfg, defer_feature_routes=True)
        )
        app._server = server
        _db_mark("webserver_ctor")

        # Just-in-time permissions: hand the service the bus and this loop BEFORE
        # the speech task below can ask for the microphone. WebServer.start() does
        # the same on its first line, but it runs behind the wake-model gate, i.e.
        # AFTER _start_speech_and_orb. Two references are stored, nothing is probed
        # and no OS dialog can follow from here (AP-26; design 3.6).
        from dodaios.platform.permission_service import attach_bus as _attach_permission_bus

        _attach_permission_bus(server.bus, loop)
        self.server = server
        self.heavy = SimpleNamespace(
            build_default_brain=build_default_brain,
            ComposeRequested=ComposeRequested,
            ErrorOccurred=ErrorOccurred,
            MessageSent=MessageSent,
            ResponseGenerated=ResponseGenerated,
            ShowWindowRequested=ShowWindowRequested,
            mcp_state=mcp_state,
            MCPRegistry=MCPRegistry,
            ChatStore=ChatStore,
            default_chats_db_path=default_chats_db_path,
            Supervisor=Supervisor,
        )

    def init_stores(self) -> None:
        """Supervisor, chat store, turn traces, chat pruning and the optional latency log."""
        app = self.app
        server = self.server
        Supervisor = self.heavy.Supervisor
        ChatStore = self.heavy.ChatStore
        default_chats_db_path = self.heavy.default_chats_db_path
        supervisor = Supervisor(bus=server.bus)
        # Persist text chats to data/chats.db (next to sessions.db) so the Chats
        # conversation manager has durable, segmented history across restarts.
        chat_store = ChatStore(
            bus=server.bus, db_path=default_chats_db_path(app.cfg.memory.data_dir)
        )
        chat_store.open()
        # The reasoning trace of a chat turn (tool calls, worker dispatch, the
        # brain's rationale) is recorded off the bus and stored next to the
        # reply, so a reopened chat shows "Thought for 4s" + steps again.
        from dodaios.state.turn_trace import TurnTraceCollector

        turn_traces = TurnTraceCollector(server.bus)
        # Cap unbounded growth at startup (mirrors the session-store prune in
        # sessions/init.py). 365d is deliberately generous — the user wants "all
        # my chats"; voice sessions already prune at 30d and text is tiny — so
        # this only ever clears year-plus-old threads.
        chat_store.prune_older_than(365)

        # LATENCY_REPORT_001: per-turn JSONL writer. Opt-in via
        # ``[latency].log_jsonl = true``. Daemon thread writes one row per
        # ``LatencyTurnComplete`` event so the aggregation CLI has data to
        # crunch. No-op when disabled (zero allocation, zero subscriber).
        try:
            lat_cfg = getattr(app.cfg, "latency", None)
            if lat_cfg is not None and getattr(lat_cfg, "log_jsonl", False):
                from dodaios.telemetry.latency_log import LatencyLogWriter

                log_path = Path(getattr(lat_cfg, "log_path", "state/latency_log.jsonl"))
                if not log_path.is_absolute():
                    log_path = Path.cwd() / log_path
                app._latency_log_writer = LatencyLogWriter(log_path)
                app._latency_log_writer.attach(server.bus)
                from loguru import logger as _llog

                _llog.info("Latency log JSONL writer attached: {}", log_path)
        except Exception as exc:  # noqa: BLE001 — telemetry never breaks boot
            from loguru import logger as _llog

            _llog.opt(exception=exc).warning(
                "Latency log writer init failed — continuing without JSONL log.",
            )
        self.supervisor = supervisor
        self.chat_store = chat_store
        self.turn_traces = turn_traces

    def apply_frontier(self) -> None:
        """Frontier auto-switch; runs before the brain build so the build sees the new TOML."""
        app = self.app
        loop = self.loop
        server = self.server
        try:
            from dodaios.brain.frontier_autoswitch import apply_frontier_resolution
            from dodaios.brain.frontier_resolver import FrontierResolver

            data_dir = Path(app.cfg.memory.data_dir)
            data_dir.mkdir(parents=True, exist_ok=True)
            resolver = FrontierResolver(
                cache_path=data_dir / "frontier_cache.json",
            )
            switches = loop.run_until_complete(
                apply_frontier_resolution(app.cfg, resolver, server.bus),
            )
            from loguru import logger as _flog

            if switches:
                _flog.info(
                    "Frontier autoswitch: {} model(s) raised to frontier.",
                    len(switches),
                )
            else:
                _flog.info("Frontier autoswitch: TOML already frontier-compliant.")
        except Exception as exc:  # noqa: BLE001 — a resolver failure must not stop boot.
            from loguru import logger as _flog

            _flog.opt(exception=exc).warning(
                "Frontier autoswitch failed — keeping TOML defaults.",
            )

    def publish_app_state(self) -> None:
        """Hang the core objects off ``server.app.state``."""
        app = self.app
        server = self.server
        supervisor = self.supervisor
        chat_store = self.chat_store
        server.app.state.supervisor = supervisor
        server.app.state.chat_store = chat_store
        server.app.state.brain = None
        # shell only gets set in run() (after webview.create_window);
        # _focus_handler fetches the value dynamically.
        server.app.state.shell = None
        server.app.state.desktop_app = app
        server.app.state.realtime_transport_broker_token = getattr(
            app, "realtime_transport_broker_token", ""
        )
        # Local desktop run: the user IS at this machine, so reveal/open-with-
        # default-app target their own desktop. Enable the native file actions.
        server.app.state.native_file_actions = True

    def setup_brain(self) -> None:
        """Deferred brain build: holder, ready event and the background builder."""
        server = self.server
        build_default_brain = self.heavy.build_default_brain
        brain_holder: dict[str, Any] = {"brain": None, "error": None}
        brain_ready = asyncio.Event()

        def _wire_ready_brain(brain: Any) -> None:
            try:
                mission_manager = getattr(server.app.state, "mission_manager", None)
                if mission_manager is not None:
                    brain.set_mission_command_handlers(
                        status_fn=mission_manager.jarvis_agent_status,
                        cancel_fn=mission_manager.jarvis_agent_cancel,
                    )
                    from loguru import logger as _bootlog

                    _bootlog.info(
                        "Wave-4 Y bootstrap: Brain.set_mission_command_handlers "
                        "wired up (status/cancel via MissionManager)."
                    )
            except AttributeError:
                from loguru import logger as _bootlog

                _bootlog.warning(
                    "MissionManager is missing jarvis_agent_status/-_cancel — status/"
                    "cancel voice patterns fall back to the normal spawn path."
                )
            except Exception as exc:  # noqa: BLE001
                from loguru import logger as _bootlog

                _bootlog.opt(exception=exc).warning(
                    "Wave-4 Y bootstrap failed — status/cancel handlers stay unwired."
                )

            try:
                workflow_runner = getattr(server.app.state, "workflow_runner", None)
                attach_brain = getattr(workflow_runner, "attach_brain", None)
                if callable(attach_brain) and callable(brain):
                    attach_brain(brain)
            except Exception as exc:  # noqa: BLE001
                from loguru import logger as _bootlog

                _bootlog.opt(exception=exc).warning(
                    "WorkflowRunner.attach_brain failed after the deferred build."
                )

            try:
                task_runner = getattr(server.app.state, "task_runner", None)
                if (
                    task_runner is not None
                    and getattr(task_runner, "_brain", None) is None
                    and hasattr(brain, "run_task")
                ):
                    task_runner._brain = brain
            except Exception as exc:  # noqa: BLE001
                from loguru import logger as _bootlog

                _bootlog.opt(exception=exc).warning(
                    "TaskRunner brain wiring failed after the deferred build."
                )

        async def _build_brain_bg() -> None:
            try:
                built = await asyncio.to_thread(build_default_brain, bus=server.bus, tier="router")
                brain_holder["brain"] = built
                server.app.state.brain = built
                from loguru import logger

                logger.info(
                    "Text-chat brain: {} active (shared with the voice pipeline).",
                    getattr(built, "active_provider", "unknown"),
                )
                _wire_ready_brain(built)
            except Exception as exc:  # noqa: BLE001
                from loguru import logger

                brain_holder["error"] = f"{type(exc).__name__}: {exc}"
                logger.opt(exception=exc).error(
                    "BrainManager build failed — chat replies with a setup hint."
                )
            finally:
                brain_ready.set()

        async def _await_brain_ready(timeout_s: float = 30.0) -> Any | None:
            if not brain_ready.is_set():
                try:
                    await asyncio.wait_for(brain_ready.wait(), timeout=timeout_s)
                except TimeoutError:
                    # Expected while the brain is still warming; the caller
                    # handles a None brain and the timeout is the signal.
                    pass
            return brain_holder["brain"]

        self.brain_holder = brain_holder
        self.brain_ready = brain_ready
        self.build_brain_bg = _build_brain_bg
        self.await_brain_ready = _await_brain_ready

    def make_deferred_voice_brain(self) -> Any:
        """Return a callable brain facade that lets the wake listener boot first."""
        app = self.app
        brain_holder = self.brain_holder
        _await_brain_ready = self.await_brain_ready
        _supported_call_kwargs = _da._supported_call_kwargs
        desktop_cfg = app.cfg

        class _DeferredVoiceBrain:
            """Callable brain facade that lets the wake listener boot first.

            The voice pipeline only needs a callable brain once a user utterance
            has been captured. Wake detection itself must not wait for the
            BrainManager build. This proxy waits at turn dispatch time and
            delegates to the real shared brain as soon as it is ready.
            """

            def __init__(self) -> None:
                self._pending_skill_notes: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

            @property
            def active_provider(self) -> str:
                brain = brain_holder["brain"]
                return str(getattr(brain, "active_provider", "starting"))

            @property
            def reply_language(self) -> str:
                brain = brain_holder["brain"]
                if brain is not None:
                    return str(getattr(brain, "reply_language", "auto"))
                return str(getattr(getattr(desktop_cfg, "brain", None), "reply_language", "auto"))

            @property
            def conversation_language(self) -> str:
                brain = brain_holder["brain"]
                return str(getattr(brain, "conversation_language", "")) if brain else ""

            def seed_history(self, turns: Any) -> None:
                brain = brain_holder["brain"]
                if brain is None:
                    raise RuntimeError("Brain is still starting; cannot resume conversation")
                brain.seed_history(turns)

            def take_voice_history_seed(self) -> Any:
                brain = brain_holder["brain"]
                take = getattr(brain, "take_voice_history_seed", None)
                return take() if callable(take) else ()

            # Realtime direct mode builds its tool bridge from these two
            # attributes at session construction; delegate through to the
            # real brain so a session opened after boot sees the full tool
            # set (None during early boot → bridge cleanly degrades).
            @property
            def _tools(self) -> Any:
                return getattr(brain_holder["brain"], "_tools", None)

            @property
            def _tool_executor_ref(self) -> Any:
                return getattr(brain_holder["brain"], "_tool_executor_ref", None)

            def _brain_unavailable_message(self) -> str:
                detail = brain_holder["error"] or "BrainManager not initialized"
                return f"Brain unavailable: {detail}"

            def _drain_skill_notes(self, brain: Any) -> None:
                note = getattr(brain, "note_skill_trigger", None)
                if not callable(note) or not self._pending_skill_notes:
                    return
                pending = list(self._pending_skill_notes)
                self._pending_skill_notes.clear()
                for args, kwargs in pending:
                    note(*args, **kwargs)

            async def _resolve(self) -> Any | None:
                brain = await _await_brain_ready()
                if brain is not None:
                    self._drain_skill_notes(brain)
                return brain

            def note_skill_trigger(self, *args: Any, **kwargs: Any) -> None:
                brain = brain_holder["brain"]
                note = getattr(brain, "note_skill_trigger", None)
                if callable(note):
                    note(*args, **kwargs)
                    return
                if len(self._pending_skill_notes) < 16:
                    self._pending_skill_notes.append((args, dict(kwargs)))

            async def __call__(self, text: str) -> str:
                brain = await self._resolve()
                if brain is None:
                    return self._brain_unavailable_message()
                return await brain(text)

            async def generate(self, text: str, *args: Any, **kwargs: Any) -> str:
                brain = await self._resolve()
                if brain is None:
                    return self._brain_unavailable_message()
                generate = getattr(brain, "generate", None)
                if callable(generate):
                    return await generate(
                        text,
                        *args,
                        **_supported_call_kwargs(generate, kwargs),
                    )
                return await brain(text)

            async def generate_stream(self, text: str, **kwargs: Any):
                brain = await self._resolve()
                if brain is None:
                    yield self._brain_unavailable_message()
                    return
                stream = getattr(brain, "generate_stream", None)
                if not callable(stream):
                    yield await self.generate(text)
                    return
                call_kwargs = dict(kwargs)
                try:
                    iterator = stream(text, **call_kwargs)
                except TypeError:
                    # Capability probe, not an error: older brain plugins do not
                    # accept these kwargs, so drop them one at a time and retry.
                    call_kwargs.pop("allow_voice_confirm", None)
                    try:
                        iterator = stream(text, **call_kwargs)
                    except TypeError:
                        # Second and last kwarg to drop; a TypeError after this
                        # is a real signature mismatch and propagates.
                        call_kwargs.pop("on_progress", None)
                        iterator = stream(text, **call_kwargs)
                async for chunk in iterator:
                    yield chunk

        return _DeferredVoiceBrain()

    def subscribe_chat_dispatch(self) -> None:
        """Subscribe the brain dispatcher to user ``MessageSent`` events."""
        app = self.app
        server = self.server
        chat_store = self.chat_store
        supervisor = self.supervisor
        turn_traces = self.turn_traces
        brain_holder = self.brain_holder
        _await_brain_ready = self.await_brain_ready
        MessageSent = self.heavy.MessageSent
        ErrorOccurred = self.heavy.ErrorOccurred
        ResponseGenerated = self.heavy.ResponseGenerated
        _supported_call_kwargs = _da._supported_call_kwargs
        _await_cancellable_chat_turn = _da._await_cancellable_chat_turn
        _CHAT_TURN_ABORTED = _da._CHAT_TURN_ABORTED
        _is_brain_diagnostic = _da._is_brain_diagnostic

        async def _on_user_message(evt: MessageSent) -> None:
            """Brain dispatcher: every user-authored MessageSent triggers generate.

            **Important**: we filter out source_layer="chat", because
            ChatStore publishes a MessageSent when it persists a message.
            Without that filter this would be an infinite loop.

            Brain API: an ``async (text) -> str`` callable. We do the
            state transitions + store write explicitly here. When ``brain``
            is None (build failure), we return an honest setup message
            — NOT a scripted mock reply.
            """
            if evt.role != "user":
                return
            if evt.source_layer == "chat":
                return

            thread_id = evt.thread_id or "default"
            # The turn's trace window opens with the user's words; everything
            # the bus sees from here until the reply lands is this turn's.
            turn_started_ms = time.time_ns() // 1_000_000
            # Persist the initiating turn before the reply. Older builds stored
            # only the assistant half, producing anonymous "New Thread" rows
            # that looked like text messages the user never sent.
            await chat_store.add_message(
                thread_id=thread_id,
                role="user",
                text=evt.text,
                publish_event=False,
            )
            from loguru import logger

            brain = await _await_brain_ready()

            # ------------------------------------------------------------------
            # Pre-brain hook (instruction-skill model, 2026-06-09 rebuild,
            # AD-S4): a TriggerMatcher hit no longer macro-runs the skill —
            # it is noted on the BrainManager, which injects the rendered
            # skill instructions into the upcoming brain turn. Uniform chat
            # output path, guaranteed invocation, no raw-Markdown replies.
            # ------------------------------------------------------------------
            try:
                from dodaios.skills.skill_context import try_get_skill_context
                from dodaios.skills.trigger_matcher import TriggerMatcher

                skill_ctx = try_get_skill_context()
                if skill_ctx is not None and brain is not None:
                    matcher = TriggerMatcher(skill_ctx.registry)
                    match_result = matcher.match_voice_with_match(evt.text, lang="auto")
                    if match_result is not None:
                        matched, regex_match = match_result
                        groups = regex_match.groups()
                        content = ""
                        for grp in reversed(groups):
                            if grp and grp.strip():
                                content = grp.strip()
                                break

                        note = getattr(brain, "note_skill_trigger", None)
                        if callable(note):
                            note(matched.name, content=content, source="chat")
                            logger.info(
                                "Skill trigger matched (chat): '{}' — handed to the brain turn",
                                matched.name,
                            )
            except Exception as exc:  # noqa: BLE001
                # The pre-brain hook is defensive — a crash here must never
                # block the chat path. Fall through to the brain.
                logger.opt(exception=exc).debug("Skill pre-hook (chat) skipped")

            if brain is None:
                # Build-failure path: a system error instead of a Jarvis reply.
                detail = brain_holder["error"] or "BrainManager not initialized"
                message = f"Brain unavailable: {detail}"
                await server.bus.publish(
                    ErrorOccurred(
                        layer="brain",
                        error_type="BrainUnavailable",
                        message=detail,
                        recoverable=True,
                        source_layer="brain",
                    )
                )
                await server.bus.publish(
                    ResponseGenerated(
                        trace_id=evt.trace_id,
                        text=message,
                        language="de",
                        source_layer="brain",
                    )
                )
                await chat_store.add_message(
                    thread_id=thread_id,
                    role="system",
                    text=message,
                )
                return

            loop = asyncio.get_running_loop()
            # Instant acknowledgment (2026-08-17): the chat path has no
            # streaming, so a heavy turn shows only "thinking…" until the whole
            # reply returns. Show the same first-sign-of-life line the voice
            # engines speak as a muted pre-ack bubble; cancelled the moment the
            # reply is in (a fast turn shows nothing).
            ack_task = None
            try:
                from dodaios.brain.assistant_name import agent_brand
                from dodaios.voice.instant_ack import start_chat_instant_ack

                ack_task = start_chat_instant_ack(
                    server.bus,
                    text=evt.text,
                    thread_id=thread_id,
                    trace_id=evt.trace_id,
                    brain=brain,
                    agent_brand=agent_brand(app.cfg),
                )
            except Exception:  # noqa: BLE001 — a missing ack must never block chat
                logger.opt(exception=True).debug("chat instant ack not armed")
            # Word-by-word preview of the reply for the chat column: the
            # brain's text_consumer feeds a coalescing publisher, the UI
            # shows the growing text and swaps in the final message.
            from dodaios.core.text_stream import TextDeltaPublisher

            delta_publisher = TextDeltaPublisher(
                server.bus,
                channel="chat",
                thread_id=thread_id,
                trace_id=evt.trace_id,
                source_layer="ui.desktop.chat",
            )
            try:
                await supervisor.set_state("THINKING")
                generate = getattr(brain, "generate", None)
                # Both brain shapes run as an X-abortable task so the bar's X
                # (request_hangup → cancel_active_chat_turn) stops a chat turn
                # too, not just a voice turn (bug 2026-06-19: the X was ignored
                # on the chat path).
                if callable(generate):
                    # source_layer lets the router exempt a drag-dropped mission
                    # recap (ui.web.ws.mission_inject) from force-spawn — a recap
                    # is discussed inline, never re-dispatched (doom-loop fix
                    # 2026-06-16). Other callers default to None (normal routing).
                    # allow_voice_confirm=True is load-bearing here (audit
                    # GT-12): a chat user IS present, but there is no approval
                    # modal anywhere outside the mission deck, so without this
                    # an ask-tier tool (send this mail, run this command) went
                    # to the executor with no channel at all and came back
                    # refused. With it, chat gets the same two-turn flow voice
                    # has — the turn ENDS with the confirmation question as its
                    # reply, and the user's next message ("ja"/"nein") resolves
                    # it. The phrasing layer is channel-agnostic by design
                    # (dodaios/voice/tool_confirmation.py); nothing here speaks.
                    chat_kwargs: dict[str, Any] = {
                        "trace_id": evt.trace_id,
                        "source_layer": evt.source_layer,
                        "conversation_id": thread_id,
                        "allow_voice_confirm": True,
                        "text_consumer": delta_publisher.feed,
                    }
                    reply = await _await_cancellable_chat_turn(
                        generate(
                            evt.text,
                            **_supported_call_kwargs(generate, chat_kwargs),
                        ),
                        loop,
                    )
                else:
                    reply = await _await_cancellable_chat_turn(brain(evt.text), loop)
            except Exception as exc:  # noqa: BLE001
                detail = f"{type(exc).__name__}: {exc}"
                message = f"Brain error: {detail}"
                logger.opt(exception=exc).warning("BrainManager call failed")
                delta_publisher.cancel()
                if ack_task is not None and not ack_task.done():
                    ack_task.cancel()
                await server.bus.publish(
                    ErrorOccurred(
                        layer="brain",
                        error_type=type(exc).__name__,
                        message=str(exc),
                        recoverable=True,
                        source_layer="brain",
                    )
                )
                await server.bus.publish(
                    ResponseGenerated(
                        trace_id=evt.trace_id,
                        text=message,
                        language="de",
                        source_layer="brain",
                    )
                )
                await chat_store.add_message(
                    thread_id=thread_id,
                    role="system",
                    text=message,
                )
                await supervisor.set_state("IDLE")
                return

            if ack_task is not None and not ack_task.done():
                ack_task.cancel()
            if reply is _CHAT_TURN_ABORTED:
                # The user pressed the bar's X mid-think — honour it and drop
                # back to IDLE instead of speaking a half-finished turn.
                logger.info("Chat turn aborted by the bar's X — back to IDLE.")
                delta_publisher.cancel()
                await supervisor.set_state("IDLE")
                return
            await delta_publisher.flush(done=True)

            try:
                await supervisor.set_state("SPEAKING")
                if reply:
                    role = "system" if _is_brain_diagnostic(reply) else "assistant"
                    trace = turn_traces.snapshot(turn_started_ms) if role == "assistant" else None
                    await chat_store.add_message(
                        thread_id=thread_id, role=role, text=reply, trace=trace
                    )
            finally:
                await supervisor.set_state("IDLE")

        server.bus.subscribe(MessageSent, _on_user_message)

    def wire_overlay_and_window(self) -> None:
        """Overlay drop, show-window/compose subscriptions, appshot opener, focus route."""
        app = self.app
        loop = self.loop
        server = self.server
        _await_brain_ready = self.await_brain_ready
        ShowWindowRequested = self.heavy.ShowWindowRequested
        ComposeRequested = self.heavy.ComposeRequested
        try:
            from dodaios.brain.drop_context import items_from_paths
            from dodaios.overlay.drop_bridge import (
                report_drop_result,
                set_drop_handler,
            )
            from dodaios.ui.drop_intake import capture_presence_drop

            def _on_overlay_drop(paths: list[str], text: str) -> None:
                items = items_from_paths(paths) if paths else []
                dragged = (text or "").strip() or None
                if not items and dragged is None:
                    # A drop the user definitely made, carrying nothing we can
                    # use (an empty folder, an unreadable path). Say so — this
                    # is precisely the case where silence leaves them guessing
                    # whether the bar even noticed.
                    report_drop_result(False)
                    return

                async def _handle_drop() -> None:
                    accepted = False
                    try:
                        current_brain = await _await_brain_ready()
                        result = await capture_presence_drop(
                            brain=current_brain,
                            thread_id="default",
                            items=items,
                            dragged_text=dragged,
                        )
                        accepted = result.captured
                    finally:
                        # The overlay gets an honest answer either way: a
                        # confirmation tick that appears when the content never
                        # reached the context would be worse than none at all.
                        report_drop_result(accepted)

                asyncio.run_coroutine_threadsafe(_handle_drop(), loop)

            set_drop_handler(_on_overlay_drop)
        except ModuleNotFoundError as exc:
            from loguru import logger as _dlog

            if exc.name == "overlay":
                _dlog.debug(
                    "overlay drop handler wiring skipped: optional overlay package not installed"
                )
            else:
                _dlog.opt(exception=exc).debug("overlay drop handler wiring skipped")
        except Exception as exc:  # noqa: BLE001 — drop wiring must never block boot.
            from loguru import logger as _dlog

            _dlog.opt(exception=exc).debug("overlay drop handler wiring skipped")

        # Overlay right-click (bar OR orb) → raise the main desktop window.
        # OrbBusBridge publishes ShowWindowRequested from the Tk thread; the
        # handler runs on the asyncio loop and immediately thread-hops, because
        # pywebview calls block their calling thread (see _on_show_window_requested).
        server.bus.subscribe(ShowWindowRequested, app._on_show_window_requested)
        # The appshot card and the Appshots page open the editor in a window
        # of its own (dodaios.appshot.editor_window holds the opener; it is
        # always called from a worker thread, as open_detached_window needs).
        try:
            from dodaios.appshot.editor_window import EDITOR_VIEW, register_window_opener

            register_window_opener(
                lambda query: app.open_detached_window(EDITOR_VIEW, query=query),
                prewarm=app.prewarm_appshot_editor,
            )
        except Exception as exc:  # noqa: BLE001 - the page editor stays the fallback
            from loguru import logger as _alog

            _alog.opt(exception=exc).debug("appshot editor window wiring skipped")
        # The bar's pen asks for a fresh chat: the window comes up through the
        # very same off-loop path; the frontend opens the new chat itself.
        server.bus.subscribe(ComposeRequested, app._on_show_window_requested)
        app._install_focus_route(server)

    def setup_workflows(self) -> None:
        """Workflow store, runner and scheduler (not fatal on failure)."""
        app = self.app
        server = self.server
        DATA_DIR = _da.DATA_DIR
        try:
            from dodaios.workflows import (
                WorkflowRunner,
                WorkflowScheduler,
                WorkflowStore,
            )

            workflow_store = WorkflowStore(DATA_DIR / "workflows.sqlite")
            workflow_runner = WorkflowRunner(
                store=workflow_store,
                bus=server.bus,
                brain=None,  # set later via attach_brain
                tool_registry=None,  # set later via attach_tools
                tool_executor=None,
            )
            # Harness + tools (audit 2026-08-17, AU-03): the runner shipped
            # with attach_harness_manager/attach_tools defined and NEVER
            # called, so every harness_dispatch step died on "No
            # HarnessManager available" and every tool_call on "Tool
            # registry/executor not available" — a scheduled workflow could
            # not touch the desktop or call a single tool. Same defect the
            # TaskRunner had (deep-dive H-02, server.py:3224), fixed the same
            # way. Both attachments are references, not work: the
            # HarnessManager ctor only zeroes four fields (entry-point scan
            # is lazy, on first dispatch), and BrainToolSurface resolves the
            # brain per lookup — so the boot critical path stays untouched.
            # A live surface rather than brain._tools, because
            # BrainManager.refresh_tools() swaps that dict out on every
            # CLI/MCP connect.
            try:
                from dodaios.harness.manager import HarnessManager
                from dodaios.workflows.runner import BrainToolSurface

                workflow_runner.attach_harness_manager(HarnessManager(bus=server.bus))
                tool_surface = BrainToolSurface(lambda: getattr(server.app.state, "brain", None))
                workflow_runner.attach_tools(tool_surface, tool_surface)
            except Exception as exc:  # noqa: BLE001 — degrade, don't kill workflows.
                from loguru import logger as _wf_logger

                _wf_logger.opt(exception=exc).warning(
                    "Workflow runner has no harness/tools — harness_dispatch "
                    "and tool_call steps will fail; the rest still runs."
                )
            workflow_scheduler = WorkflowScheduler(
                store=workflow_store,
                runner=workflow_runner,
                bus=server.bus,
            )
            server.app.state.workflow_store = workflow_store
            server.app.state.workflow_runner = workflow_runner
            server.app.state.workflow_scheduler = workflow_scheduler
            app._workflow_store = workflow_store
            app._workflow_scheduler = workflow_scheduler
        except Exception as exc:  # noqa: BLE001
            from loguru import logger

            logger.opt(exception=exc).warning(
                "Workflow system could not start — the workflows view stays empty."
            )
            server.app.state.workflow_store = None
            server.app.state.workflow_runner = None
            server.app.state.workflow_scheduler = None
            app._workflow_store = None
            app._workflow_scheduler = None

    def setup_mcp(self) -> None:
        """MCP registry, tool registry and the background MCP autostart coroutine."""
        app = self.app
        server = self.server
        mcp_state = self.heavy.mcp_state
        MCPRegistry = self.heavy.MCPRegistry
        mcp_registry = MCPRegistry()
        mcp_registry.load_from_mcp_json()
        server.app.state.mcp_registry = mcp_registry
        # App-Control: expose the live registry so the ``manage-mcp-server`` tool
        # can reload/start servers after editing mcp.json (no restart).
        from dodaios.core import runtime_refs

        runtime_refs.set_mcp_registry(mcp_registry)

        # tool_registry is a plain dict — MCPToolAdapters and native tools are
        # merged here. BrainManager refreshes its tool set on BrainToolsChanged.
        tool_registry: dict[str, Any] = {}
        server.app.state.tool_registry = tool_registry

        async def _start_enabled_mcps() -> None:
            enabled = mcp_state.get_enabled_names()
            if not enabled:
                return
            from loguru import logger as _logger

            try:
                await mcp_registry.start_enabled(enabled)
            except Exception as exc:  # noqa: BLE001
                _logger.opt(exception=exc).warning("MCP autostart failed")
                return

            # Register MCP tools as adapters in the tool registry.
            # The adapter wraps each MCP tool to the Tool protocol so the
            # BrainManager / ToolUseLoop can consume them uniformly.
            try:
                from dodaios.mcp.adapter import register_mcp_tools_in_registry

                adapters = await register_mcp_tools_in_registry(
                    mcp_registry,
                    tool_registry,
                    default_risk_tier=app.cfg.harness.default_risk_tier,
                )
                _logger.info(
                    "{} MCP tools registered as adapters",
                    len(adapters),
                )
            except Exception as exc:  # noqa: BLE001
                _logger.opt(exception=exc).warning(
                    "MCP tool registration failed",
                )
                return

            # Notify the live brain so it picks up the new tools without restart.
            if adapters:
                try:
                    from dodaios.core.events import BrainToolsChanged

                    bus = getattr(server.app.state, "bus", None)
                    if bus is not None:
                        import asyncio as _asyncio

                        event = BrainToolsChanged(
                            source_layer="desktop_app._start_enabled_mcps",
                            reason="mcp_autostart",
                        )
                        if _asyncio.iscoroutinefunction(bus.publish):
                            await bus.publish(event)
                        else:
                            bus.publish(event)
                except Exception as exc:  # noqa: BLE001
                    _logger.opt(exception=exc).warning(
                        "BrainToolsChanged publish failed after MCP autostart",
                    )

        self.start_enabled_mcps = _start_enabled_mcps

    def setup_conductor(self) -> None:
        """Conductor store, runner and scheduler (not fatal on failure)."""
        app = self.app
        server = self.server
        _make_conductor_announcer = _da._make_conductor_announcer
        try:
            from conductor import ConductorStore as _CStore
            from conductor import Runner as _CRunner
            from conductor import Scheduler as _CSched

            conductor_store = _CStore()  # ~/.conductor/conductor.sqlite
            # The bus reaches Conductor through its ``on_event`` seam, not the
            # other way round (Conductor never imports ``jarvis``). Without
            # this, every scheduled job ran into its own SQLite and the user
            # never learned that anything had happened at all (audit AU-01).
            conductor_runner = _CRunner(
                conductor_store,
                on_event=_make_conductor_announcer(
                    server.bus,
                    lambda: getattr(server.app.state, "brain", None),
                    lambda: getattr(app.cfg.brain, "reply_language", ""),
                ),
            )
            conductor_scheduler = _CSched(conductor_store, conductor_runner)
            server.app.state.conductor_store = conductor_store
            server.app.state.conductor_runner = conductor_runner
            server.app.state.conductor_scheduler = conductor_scheduler
            app._conductor_store = conductor_store
            app._conductor_scheduler = conductor_scheduler
        except Exception as exc:  # noqa: BLE001
            from loguru import logger

            logger.opt(exception=exc).warning(
                "Conductor setup failed — the Conductor view stays empty."
            )
            server.app.state.conductor_store = None
            server.app.state.conductor_runner = None
            server.app.state.conductor_scheduler = None
            app._conductor_store = None
            app._conductor_scheduler = None

    def define_service_bootstraps(self) -> None:
        """The conductor and workflow bootstrap coroutines the heavy backend task schedules."""
        server = self.server

        async def _bootstrap_conductor() -> None:
            """Conductor store init + seed jobs + scheduler start."""
            from loguru import logger as _logger

            store = server.app.state.conductor_store
            scheduler = server.app.state.conductor_scheduler
            if store is None:
                return
            try:
                await store.init()
                await store.cleanup_interrupted_runs()
                from conductor import ensure_seed_jobs

                added = await ensure_seed_jobs(store)
                _logger.info("Conductor store ready ({} new seed job(s)).", added)
                if scheduler is not None:
                    scheduler.start()
                    _logger.info("Conductor scheduler started.")
            except Exception as exc:  # noqa: BLE001
                _logger.opt(exception=exc).warning("Conductor bootstrap failed")

        async def _bootstrap_workflows() -> None:
            """Store init + seed workflows + scheduler start.

            Fire-and-forget from the backend loop — errors are logged but
            not propagated, so the rest of the app still boots. Without a
            brain callable, the scheduler still runs (only brain_prompt
            steps would fail during a run).
            """
            from loguru import logger as _logger

            store = server.app.state.workflow_store
            scheduler = server.app.state.workflow_scheduler
            if store is None:
                return
            try:
                await store.init()
                await store.cleanup_interrupted_runs()
                from dodaios.workflows import ensure_seed_workflows

                added = await ensure_seed_workflows(store)
                _logger.info("Workflow store ready ({} new seed workflow(s)).", added)
                # Harness manager + tool surface are attached above, at runner
                # construction — ``tool_call`` and ``harness_dispatch`` steps
                # run through the brain's own risk-tier-aware ToolExecutor.
                if scheduler is not None:
                    scheduler.start()
                    _logger.info("Workflow scheduler started.")
            except Exception as exc:  # noqa: BLE001
                _logger.opt(exception=exc).warning(
                    "Workflow bootstrap failed",
                )

        self.bootstrap_conductor = _bootstrap_conductor
        self.bootstrap_workflows = _bootstrap_workflows

    async def heavy_backend(self) -> None:
        """Everything behind the live wake listener: routes, server.start, brain, MCP, workflows."""
        app = self.app
        loop = self.loop
        server = self.server
        bootstrap = self.bootstrap
        _bp = self.bp
        _bp_t0 = self.bp_t0
        _db_mark = self.db_mark
        _write_meta = _da._write_meta
        _log_input_isolation = _da._log_input_isolation
        _build_brain_bg = self.build_brain_bg
        _start_enabled_mcps = self.start_enabled_mcps
        _bootstrap_workflows = self.bootstrap_workflows
        _bootstrap_conductor = self.bootstrap_conductor
        # Wake-model CPU/disk priority: hold the ENTIRE heavy backend
        # (server.start's mission/wiki/session/channel init + git-prune,
        # then the brain + MCP build) until the wake model has loaded.
        # Measured: the light base/cpu wake model loads ~4 s isolated but
        # ~8 s when it races this boot storm for CPU/disk — gating the
        # whole storm behind wake roughly halves the custom-wake hear-
        # ready time. This matches the user's explicit "window ->
        # Jarvis-Bar -> rest" order: the bootstrap already serves the
        # static UI shell, so only the API DATA (chat history, missions,
        # wiki) and background services land a few seconds later. Bounded
        # so a stuck/absent wake load never blocks the backend forever.
        try:
            await asyncio.wait_for(app._wake_model_loaded.wait(), timeout=12.0)
        except TimeoutError:
            from loguru import logger as _slog

            _slog.info(
                "Heavy backend: wake-model gate timed out (12 s) — starting the backend anyway."
            )
        if app._shutdown_done:
            return
        # Route imports/mounting and the board used to run before the
        # speech task even existed. Complete them off-loop only after
        # wake warmup, and never expose a partially installed API.
        await server.prepare_app()
        if app._shutdown_done:
            return
        _db_mark("feature_routes")
        # Hand the REAL app to the bootstrap BEFORE the heavy _init_*
        # chain runs. Every route whose subsystem is still warming
        # answers its documented 503/None placeholder (the WebServer
        # ctor sets those up for exactly this contract), so the UI
        # becomes INTERACTIVE — chat history (app.state.chat_store is
        # set before this task), settings, WS — within seconds instead
        # of every data request being HELD behind ~8-15 s of
        # mission/wiki/session/channel init. TTI forensic 2026-07-02:
        # the window served at 1.2 s but set_app happened at +16 s,
        # which is the "Getting ready" wall the user actually sees.
        # BEFORE the UI can reach the API: the grid restores and
        # attaches panes the moment it can, and each of them must
        # re-join the agent the PTY host kept running instead of
        # starting it again in this process (RUB-102). A bare flag —
        # the registry and the reattach pass come after server.start.
        from dodaios.agentic_ide import host_mode

        host_mode.enable()
        bootstrap.set_app(server.app)
        _db_mark("app_interactive")
        if _bp:
            # Honest end-to-end anchor: the UI's data requests are now
            # answered — spawn -> app usable, same clock as BOOT_READY.
            print(
                f"APP_INTERACTIVE_MS={(time.perf_counter() - _bp_t0) * 1000.0:.1f}",
                flush=True,
            )
        # The bootstrap owns the bound port for the process lifetime;
        # the meta file only needs the API to answer, which set_app
        # just made true.
        _write_meta(app.cfg.ui.admin_api_port, os.getpid())
        _log_input_isolation()
        try:
            await server.start(start_serving=False)
            _db_mark("server_start")
            # Reattach to coding agents that kept running while the app
            # was closed, and reopen the workspaces in their layout.
            from dodaios.agentic_ide.session import schedule_boot_restore

            schedule_boot_restore()
            # Carry on the IDE thread turns the turn host kept running.
            from dodaios.ui.web.agent_chat_routes import schedule_turn_reattach

            schedule_turn_reattach(server.app.state)
        except Exception as exc:  # noqa: BLE001 — never kill the backend loop
            from loguru import logger as _slog

            _slog.opt(exception=exc).error("Heavy backend init (server.start) failed.")
        loop.create_task(_build_brain_bg(), name="brain-build")
        # MCP autostart as a fire-and-forget task — doesn't block backend-ready.
        loop.create_task(_start_enabled_mcps())
        loop.create_task(_bootstrap_workflows(), name="workflow-bootstrap")
        loop.create_task(_bootstrap_conductor(), name="conductor-bootstrap")

        # One-shot: provision the Vosk wake model if missing, off the boot
        # path (AP-26). Runs behind the live wake listener (this whole
        # function already waited on ``app._wake_model_loaded`` above), so
        # a fresh install that skipped/failed the installer prefetch still
        # app-heals without editing jarvis.toml. Never fatal — the wake
        # word degrades honestly until the model lands.
        async def _provision_wake_model() -> None:
            try:
                from dodaios.core.config import load_config
                from dodaios.speech import wake_model_fetch as _wmf

                cfg = load_config()
                lang = _wmf.resolve_wake_language(cfg)
                if _wmf.vosk_model_present(lang):
                    return
                landed = await asyncio.to_thread(_wmf.ensure_vosk_model, lang)
                if landed is None:
                    return
                # The matching-language model just landed. Re-resolve the
                # wake plan and live-switch the running detector to
                # vosk_kws so the user's word works immediately — no
                # restart (mirrors the settings PUT live-apply). A
                # headless/absent pipeline just means it applies on the
                # next voice start.
                import importlib.util as _ilu

                from dodaios.core.runtime_refs import get_speech_pipeline
                from dodaios.speech.wake_phrase import resolve_wake_plan

                pipeline = get_speech_pipeline()
                if pipeline is not None and hasattr(pipeline, "set_wake_plan"):
                    plan = resolve_wake_plan(
                        cfg.trigger.wake_word,
                        local_whisper_available=(_ilu.find_spec("faster_whisper") is not None),
                        language=lang,
                    )
                    if plan.engine == "vosk_kws":
                        pipeline.set_wake_plan(plan)
                        from loguru import logger as _wmf_ok

                        _wmf_ok.info(
                            "Wake model for '{}' provisioned off-boot; "
                            "live-switched detector to vosk_kws.",
                            lang,
                        )
            except Exception:  # noqa: BLE001 — a background probe never crashes boot
                from loguru import logger as _wmf_log

                _wmf_log.opt(exception=True).debug("Off-boot wake-model provision skipped.")

        loop.create_task(_provision_wake_model(), name="wake-model-provision")

    def start_voice_and_backend_tasks(self) -> None:
        """Arm the wake listener first, then the realtime warm and the heavy backend task."""
        app = self.app
        loop = self.loop
        server = self.server
        supervisor = self.supervisor
        _DeferredVoiceBrain = self.make_deferred_voice_brain

        def _log_speech_and_orb_done(task: asyncio.Task) -> None:
            if task.cancelled():
                return
            exc = task.exception()
            if exc is not None:
                from loguru import logger as _slog

                _slog.opt(exception=exc).error("Startup task {} crashed.", task.get_name())

        # Wake-model GIL-priority gate: set by ``_start_speech_and_orb`` once
        # the (light base/cpu) wake model has finished loading. The heavy
        # backend (the GIL-heavy brain + MCP build) waits on this so the wake
        # model load is NOT starved by the import storm — it loads in ~3 s
        # isolated instead of ~8.8 s racing brain/mcp. Matches the user's
        # "window -> Jarvis-Bar -> rest" order.
        app._wake_model_loaded = asyncio.Event()

        # === 1) Jarvis-Bar / wake listener FIRST ========================
        # The user's "Jarvis is ready to talk to" gate. Scheduled before the
        # heavy backend so the wake word arms within ~1 s of the window
        # appearing, not after the whole _init_* chain. Wake detection only
        # needs a callable for later turn dispatch, so the deferred proxy
        # waits for the real shared brain at answer time instead of keeping
        # the wake word deaf while the app is visibly open.
        speech_task = loop.create_task(
            app._start_speech_and_orb(loop, server.bus, supervisor, _DeferredVoiceBrain(), server),
            name="speech-and-orb",
        )
        speech_task.add_done_callback(_log_speech_and_orb_done)

        # === 1b) Realtime transport pre-warm, beside the wake listener ===
        # Deliberately NOT inside ``_heavy_backend_bg``: that task waits on
        # the wake-model gate AND the whole ``server.start()`` chain before
        # it schedules anything, so the warm could not begin until roughly
        # 30-40 s after launch — while the wake word is armed within ~1 s.
        # A user who spoke in that window paid the provider's full cold
        # start (documented 15-25 s for the ChatGPT-subscription transport)
        # inside their own call, with the bar already claiming to listen.
        #
        # AP-26 is preserved by construction: the worker below does nothing
        # until VoiceBootStatus reports ``voice_usable``, i.e. AFTER the
        # mark ``check_boot_budget.py`` measures, and nothing on the boot
        # path ever awaits it — so neither VOICE_USABLE nor APP_INTERACTIVE
        # can move because of it.
        loop.create_task(
            app._run_realtime_transport_warm(server.bus),
            name="realtime-transport-warm",
        )
        app._heavy_backend_task = loop.create_task(self.heavy_backend(), name="heavy-backend")
        app._heavy_backend_task.add_done_callback(_log_speech_and_orb_done)
        loop.call_soon(app._start_virtual_cursor)

    def run_loop(self) -> None:
        """Start the watchdogs and run the loop until ``shutdown`` stops it."""
        app = self.app
        loop = self.loop
        # Watch this loop from OFF it, for the rest of the process's life.
        # Everything the user touches — every WebSocket frame, every route,
        # every brain turn — is serialized through the loop below, so one
        # synchronous call on it stops all of them at once. That failure
        # reaches the user as "Not responding" in the title bar and as
        # keystrokes arriving seconds late in an Agentic-IDE pane, and it
        # cannot be diagnosed from the inside: the diagnostics route that
        # measures loop lag runs ON the loop and answers nothing while it
        # is wedged (2026-07-28 — ten minutes of silence, health included,
        # and a sampling profiler attached to the live process was the only
        # way to learn it was a TOML parse). Costs one sleeping thread.
        app._start_loop_watchdog(loop)
        # And watch the OTHER shared resource a stall can be blamed on.
        # A loop can be perfectly healthy while the machine has run out of
        # ephemeral ports, at which point nothing anywhere can connect and
        # the user reports the whole computer freezing for a few minutes
        # and then healing itself. Off-loop, one census every 30 s, and it
        # names the destination the ports went to (BUG-215).
        app._start_socket_budget_watchdog()
        app._backend_serving_since = time.monotonic()
        # run_forever() has exactly one legitimate way out: shutdown()
        # calling loop.stop(). Every OTHER way out — a BaseException from
        # a callback, a stop nobody asked for — takes the whole backend
        # with it and leaves the window standing in front of a dead
        # process. Naming which of the two happened is the difference
        # between a diagnosable incident and a grey OFFLINE dot.
        try:
            loop.run_forever()
        except BaseException as exc:  # noqa: BLE001 — re-raising here
            # would only reach the excepthook; we want it in the log WITH
            # the recovery decision that follows, then a clean unwind.
            from loguru import logger as _crash_log

            _crash_log.opt(exception=exc).critical(
                "Backend event loop crashed out of run_forever()."
            )
            app._note_backend_stopped(f"{type(exc).__name__}: {exc}")
        else:
            app._note_backend_stopped("the loop was stopped")

    def teardown(self) -> None:
        """Stop the watchdogs, close the loop and release the executor."""
        app = self.app
        loop = self.loop
        app._stop_loop_watchdog()
        app._stop_socket_budget_watchdog()
        try:
            loop.close()
        except Exception:  # noqa: BLE001, S110
            # Closing an already-closed or still-busy loop on the way out;
            # the process exits either way.
            pass
        # Never waited on: a worker still inside a blocking native call
        # would hold the quit open, and this process is on its way out
        # anyway (the restart path depends on the port and the
        # single-instance mutex being released promptly).
        executor = getattr(app, "_io_executor", None)
        if executor is not None:
            try:
                executor.shutdown(wait=False, cancel_futures=True)
            except Exception:  # noqa: BLE001,S110 - last statement of a
                # process that is exiting; the OS reclaims the threads.
                pass
