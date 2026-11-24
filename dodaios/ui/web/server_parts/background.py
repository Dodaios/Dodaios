"""Background services the boot starts and the shutdown stops, plus health watchdogs."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from dodaios.core.events import (
    VoiceBootStatus,
)


if TYPE_CHECKING:
    pass

from ._srv import server_module


def _follow_main_saved() -> bool:
    """``[agentic_ide] follow_main`` as saved now (the in-memory config is read at boot)."""
    try:
        from dodaios.core.config import load_config

        return bool(getattr(load_config().agentic_ide, "follow_main", False))
    except Exception as exc:  # noqa: BLE001 -- an unreadable file means "not opted in"
        logger.debug("Follow main: the configuration could not be read: {}", exc)
        return False


class BackgroundServicesMixin:
    """Background services the boot starts and the shutdown stops, plus health watchdogs."""


    #: Breathing room between "voice is ready" and bringing anyio's workers
    #: up. Ready is the end of the heavy boot work, not of the box's — the
    #: wake models have just loaded and the frontend is still mounting.
    _ANYIO_WARM_DELAY_S = 5.0

    def _schedule_anyio_pool_warm(self) -> None:
        """Bring a few anyio workers up, once, at the first calm moment.

        Every start happens on the loop (anyio leaves no other way), so the
        one place to pay for it is right after boot, before the first click —
        never on the boot path itself (AP-26). Idempotent: the ready event
        can arrive more than once (warm-up, then the watchdog).
        """
        if self._anyio_pool_warmed:
            return
        self._anyio_pool_warmed = True

        async def _warm() -> None:
            from dodaios.core.loop_executor import warm_anyio_worker_pool

            try:
                await asyncio.sleep(self._ANYIO_WARM_DELAY_S)
                resident = await warm_anyio_worker_pool()
            except Exception as exc:  # noqa: BLE001 — a pool that grows lazily is
                # yesterday's behaviour, not a boot failure
                logger.opt(exception=exc).debug("anyio pool warm-up did not complete")
                return
            logger.info("anyio worker pool warmed: {} thread(s) resident", resident)

        self._anyio_pool_warm_task = asyncio.create_task(
            _warm(), name="anyio-pool-warm"
        )

    async def _voice_ready_watchdog(self, deadline_s: float = 45.0) -> None:
        """Release boot waiters after a failed warm-up without promising speech.

        The startup banner + "STARTING…" status flip to listening ONLY when a
        ``VoiceBootStatus(ready=True)`` arrives (mirrored by /api/voice/status).
        The pipeline emits it at the end of warm-up — but if construction crashes
        or an un-timed model download/load wedges warm-up, that event is never
        published and the banner sticks forever even though the user can already
        type (permanent "Getting ready to listen"). This backstop fires once,
        well past a healthy cold boot (voice-usable budget ≤ 20 s, AP-26), and
        releases boot waiters. A genuine ready flips ``_voice_ready`` first, in
        which case this is a silent no-op. ``detail="watchdog_timeout"`` marks the
        signal as a degraded release (voice may be offline until restart), not a
        real "you can speak now".
        """
        try:
            await asyncio.sleep(deadline_s)
        except asyncio.CancelledError:
            return
        if self._voice_ready:
            return
        logger.warning(
            "Voice-ready watchdog fired after {:.0f}s — the speech pipeline never "
            "signalled ready (a construction crash or a wedged warm-up load). "
            "Releasing boot waiters; voice remains unavailable until the pipeline "
            "confirms listening.",
            deadline_s,
        )
        # Set the endpoint mirror first so /api/voice/status is correct even if
        # the bus publish below fails; the WS event then updates live tabs.
        self._voice_ready = False
        try:
            await self.bus.publish(VoiceBootStatus(ready=True, detail="watchdog_timeout"))
        except Exception as exc:  # noqa: BLE001 — mirror already set; never crash
            logger.debug("watchdog VoiceBootStatus publish failed: %s", exc)

    def _schedule_marketplace_refresh_scheduler(self) -> None:
        """Start marketplace token refresh after the current boot turn.

        Both desktop and headless launch through :meth:`start`. Deferring the
        small amount of catalog/keyring setup until the loop gets control back
        keeps it off the readiness-critical path, while the stored handle makes
        the operation exactly-once even if start is invoked again before the
        callback runs.
        """
        if self._refresh_scheduler is not None or self._refresh_scheduler_start_handle is not None:
            return
        self._refresh_scheduler_stopping = False
        loop = asyncio.get_running_loop()
        self._refresh_scheduler_start_handle = loop.call_soon(
            self._start_marketplace_refresh_scheduler
        )

    def _start_main_follower(self) -> None:
        """Keep a git checkout's app on the newest main, when the person opted in.

        The follower is a daemon thread whose first look waits well past boot;
        here it is only created. ``[agentic_ide] follow_main`` is re-read every
        round, so the toggle takes effect without a restart.
        """

        def enabled() -> bool:
            return bool(getattr(self.cfg.agentic_ide, "follow_main", False)) or _follow_main_saved()

        try:
            from dodaios.core.main_follow import start_follower

            start_follower(
                enabled=enabled, idle=self._nothing_a_restart_would_end, restart=self._restart_app
            )
        except Exception as exc:  # noqa: BLE001 -- following main is a convenience, never a boot blocker
            logger.opt(exception=exc).warning("Follow main did not start.")

    def _nothing_a_restart_would_end(self) -> bool:
        """Whether the app may restart by itself right now without costing anybody work."""
        app = self.app
        kontrollierer = getattr(app.state, "kontrollierer", None)
        running = getattr(kontrollierer, "running_mission_ids", None)
        if callable(running) and running():
            return False
        # A chat that answers in this process (the front page's, a created
        # agent's) loses its running turn to a restart; a thread's CLI
        # lives in the turn host and is carried on. A chat service that
        # was never built runs nothing.
        chat = getattr(app.state, "agent_chat", None)
        interrupted = getattr(chat, "turns_a_restart_would_end", None)
        if callable(interrupted) and interrupted():
            return False
        from dodaios.live.runtime import active

        if any(getattr(session, "is_active", False) for session in active()):
            return False
        from dodaios.core.runtime_refs import get_speech_pipeline

        pipeline = get_speech_pipeline()
        in_session = getattr(pipeline, "is_session_active", None)
        return not (callable(in_session) and in_session())

    def _restart_app(self) -> bool:
        """Ask the desktop shell to restart the app. ``False``: there is none to ask."""
        desktop = getattr(self.app.state, "desktop_app", None)
        request = getattr(desktop, "request_restart", None)
        return bool(request()) if callable(request) else False

    def _start_microphone_rescue(self) -> None:
        """Restart by itself when the audio system stops answering for the microphone.

        Best-effort, exactly once, off the boot path: the task only looks at a
        flag every few seconds (see ``dodaios.audio.stuck_rescue``).
        """
        # ``getattr``: tests build a server without its constructor.
        if getattr(self, "_microphone_rescue_task", None) is not None:
            return
        try:
            from dodaios.audio.capture import stuck_microphone
            from dodaios.audio.stuck_rescue import MicrophoneRescue

            rescue = MicrophoneRescue(
                stuck=stuck_microphone,
                idle=self._nothing_a_restart_would_end,
                restart=self._restart_app,
                data_dir=Path(self.cfg.memory.data_dir),
            )
            self._microphone_rescue_task = asyncio.get_running_loop().create_task(
                rescue.run(), name="microphone-rescue"
            )
        except Exception as exc:  # noqa: BLE001 -- a safety net must never block boot
            logger.opt(exception=exc).warning("Microphone rescue did not start.")

    async def _stop_microphone_rescue(self) -> None:
        task = getattr(self, "_microphone_rescue_task", None)
        self._microphone_rescue_task = None
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:  # Cancellation is the successful teardown.
            pass

    def _start_local_models_health_monitor(self) -> None:
        """The Local models self-check task (best-effort, exactly once, off the boot path)."""
        if self._local_models_health_monitor is not None:
            return
        try:
            from dodaios.local_models.health_monitor import HealthMonitor

            monitor = HealthMonitor(lambda: self.cfg)
            monitor.start()
        except Exception as exc:  # noqa: BLE001 -- a badge must never block boot
            logger.opt(exception=exc).warning("Local models health monitor did not start.")
            return
        self._local_models_health_monitor = monitor

    async def _stop_local_models_health_monitor(self) -> None:
        monitor = self._local_models_health_monitor
        self._local_models_health_monitor = None
        if monitor is not None:
            try:
                await monitor.stop()
            except Exception as exc:  # noqa: BLE001 -- shutdown stays best-effort
                logger.opt(exception=exc).debug("Local models health monitor stop failed.")

    def _schedule_local_models_autostart(self) -> None:
        """Start the local model server with Jarvis when it is wanted and in use.

        Best-effort, exactly once, off the boot path: the task sleeps a few
        seconds first, then decides from the config (autostart on AND a role
        or the active brain uses the server) and starts/warms accordingly.
        """
        if self._local_models_autostart_task is not None:
            return
        try:
            from dodaios.local_models.autostart import schedule

            self._local_models_autostart_task = schedule(lambda: self.cfg)
        except Exception as exc:  # noqa: BLE001 -- a convenience must never block boot
            logger.opt(exception=exc).warning("Local models autostart did not schedule.")

    async def _stop_local_models_autostart(self) -> None:
        task = self._local_models_autostart_task
        self._local_models_autostart_task = None
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # noqa: BLE001 -- shutdown stays best-effort
            logger.opt(exception=exc).debug("Local models autostart stop failed.")

    def _start_marketplace_refresh_scheduler(self) -> None:
        """Create the periodic OAuth refresh task (best-effort, exactly once)."""
        self._refresh_scheduler_start_handle = None
        if self._refresh_scheduler is not None:
            return
        try:
            from dodaios.marketplace.connect_helpers import (
                build_handler_from_catalog,
                connected_plugin_ids,
            )
            from dodaios.marketplace.refresh_scheduler import RefreshScheduler
            from dodaios.marketplace.token_store import TokenStore

            token_store = TokenStore()

            def _refresh_live_session(plugin_id: str) -> None:
                registry = self._plugin_registry
                if registry is None or self._refresh_scheduler_stopping:
                    return
                task = asyncio.create_task(
                    registry.refresh_credentials(plugin_id),
                    name=f"plugin-refresh:{plugin_id}",
                )
                self._refresh_registry_tasks.add(task)

                def _consume_refresh_result(done: asyncio.Task[Any]) -> None:
                    self._refresh_registry_tasks.discard(done)
                    if done.cancelled():
                        return
                    try:
                        done.result()
                    except Exception as exc:  # noqa: BLE001 -- background isolation
                        logger.opt(exception=exc).warning(
                            "Marketplace live-session refresh failed for {}.",
                            plugin_id,
                        )

                task.add_done_callback(_consume_refresh_result)

            scheduler = RefreshScheduler(
                plugin_ids_fn=lambda: connected_plugin_ids(token_store),
                store=token_store,
                build_handler=build_handler_from_catalog,
                on_refreshed=_refresh_live_session,
            )
            scheduler.start()
        except Exception as exc:  # noqa: BLE001 -- refresh must never block boot
            logger.opt(exception=exc).warning(
                "Marketplace refresh scheduler did not start; connected OAuth plugins may expire."
            )
            return

        self._refresh_scheduler = scheduler
        self.app.state.refresh_scheduler = scheduler
        logger.info(
            "Marketplace refresh scheduler started; connected OAuth tokens "
            "will be renewed in the background."
        )

    def _schedule_credential_migration(self) -> None:
        """Copy keys from the renamed credential service once, off the boot path (AP-26).

        A daemon thread in the main instance only, started with a delay; reads
        never depend on it (``get_secret`` falls back to the legacy service),
        so a process that skips it loses nothing.
        """
        try:
            from dodaios.core.identity_credentials import schedule_credential_migration

            schedule_credential_migration()
        except Exception as exc:  # noqa: BLE001 -- a background copy must never block boot
            logger.opt(exception=exc).warning("Credential copy did not schedule.")

    def _schedule_distribution_check(self) -> None:
        """Warn once, off the boot path (AP-26), when both package names are installed."""
        try:
            from dodaios.core.distribution import schedule_duplicate_distribution_check

            schedule_duplicate_distribution_check()
        except Exception as exc:  # noqa: BLE001 -- a diagnostic must never block boot
            logger.opt(exception=exc).debug("Duplicate distribution check did not schedule.")

    def _schedule_appshot_shortcut(self) -> None:
        """Arm the global appshot shortcut once the wake model has loaded.

        Off the boot path (AP-26): the key reader and the hotkey backend load
        native libraries. Headless hosts arm nothing and say so in the log.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.debug("Appshot shortcut not scheduled — no running event loop.")
            return

        async def _arm() -> None:
            from dodaios.appshot.hotkey import start_appshot_shortcut
            from dodaios.core import runtime_refs as _rr

            await _rr.await_wake_model_ready(timeout=12.0)
            try:
                await start_appshot_shortcut(self.bus)
            except Exception as exc:  # noqa: BLE001 - voice/chat work without it
                logger.opt(exception=exc).warning("Appshot shortcut could not start")

        self._appshot_shortcut_task = loop.create_task(_arm(), name="appshot-shortcut")

    def _schedule_realtime_transport_warm(self) -> None:
        """Pre-open the selected realtime transports off the boot path.

        ``run.bat --headless`` and every browser-only install boot through this
        server and never through the desktop shell, so without this hook they
        paid the realtime provider's whole cold start inside the user's first
        call — for a subscription transport a spawned app-server plus a live
        account check. Every OS reaches it the same way; nothing here is
        desktop- or Windows-specific.

        Exactly-once by construction: the desktop shell starts its own warm
        worker under :data:`REALTIME_WARM_TASK_NAME` before it awaits
        :meth:`start`, and both run on the same loop, so an already-live task
        of that name means this boot is already covered. Whether warming is
        appropriate at all stays the factory's decision — it skips itself when
        realtime is not the configured voice mode and warms only explicitly
        selected providers.
        """
        existing = self._realtime_warm_task
        if existing is not None and not existing.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No loop (a synchronous start in a test harness): nothing to warm
            # onto, and boot must not care.
            logger.debug("Realtime transport warm not scheduled — no running event loop.")
            return
        for task in asyncio.all_tasks(loop):
            if task.get_name() == server_module().REALTIME_WARM_TASK_NAME and not task.done():
                logger.debug(
                    "Realtime transport warm already running on this loop — "
                    "not scheduling a second one."
                )
                return
        self._realtime_warm_task = loop.create_task(
            self._warm_realtime_transports(), name=server_module().REALTIME_WARM_TASK_NAME
        )

    async def _warm_realtime_transports(self) -> None:
        """Warm the explicitly selected realtime transports once, after boot.

        Advisory by contract and never silent (AP-30): a failure here changes
        nothing except that the first call pays the cold start it pays today,
        and it says so at warning level.
        """
        try:
            # Spawn-only prestart BEFORE the boot delay: the managed local
            # server loads its models for 45-90 s in a SEPARATE process, so
            # firing its spawn first costs the boot nothing and moves local
            # voice readiness forward by the whole delay. The full warm below
            # keeps its delay — it is what spawns app-servers and verifies
            # accounts inside THIS process.
            from dodaios.realtime.factory import realtime_prespawn_transports

            await realtime_prespawn_transports(self.cfg)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 -- prespawn is advisory, never fatal
            logger.opt(exception=exc).debug(
                "Realtime transport prespawn failed — the regular warm below "
                "still covers the start."
            )
        try:
            await asyncio.sleep(server_module().REALTIME_WARM_BOOT_DELAY_S)
            from dodaios.realtime.factory import realtime_warm_selected_transports

            await realtime_warm_selected_transports(self.cfg)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 -- warming is advisory, never fatal
            logger.opt(exception=exc).warning(
                "Realtime transport warm failed — the first realtime call will "
                "pay the provider's cold start."
            )

    async def _stop_marketplace_refresh_scheduler(self) -> None:
        """Cancel a pending start and stop the live refresh task, if any."""
        self._refresh_scheduler_stopping = True
        handle = self._refresh_scheduler_start_handle
        self._refresh_scheduler_start_handle = None
        if handle is not None:
            handle.cancel()

        scheduler = self._refresh_scheduler
        self._refresh_scheduler = None
        self.app.state.refresh_scheduler = None
        if scheduler is not None:
            try:
                await scheduler.stop()
            except Exception as exc:  # noqa: BLE001 -- shutdown stays best-effort
                logger.opt(exception=exc).warning("Marketplace refresh scheduler stop failed.")

        # A successful token refresh may already have queued a live MCP-session
        # rebuild. Drain those tasks before PluginToolRegistry.stop(); otherwise
        # a late task can reconnect a client after registry shutdown and leak it.
        pending = list(self._refresh_registry_tasks)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        self._refresh_registry_tasks.clear()
