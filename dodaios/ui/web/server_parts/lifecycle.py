"""``start()`` and ``stop()``: the boot order and the shutdown order."""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from dodaios.core import module_health

if TYPE_CHECKING:
    pass

from ._srv import server_module

if TYPE_CHECKING:
    from dodaios.ui.web.server_parts._host_state import WebServerHostState as _HostBase
else:
    _HostBase = object


class LifecycleMixin(_HostBase):
    """``start()`` and ``stop()``: the boot order and the shutdown order."""

    async def start(
        self,
        host: str = "127.0.0.1",
        port: int | None = None,
        *,
        start_serving: bool = True,
    ) -> None:
        """Run the boot init chain. When ``start_serving`` is False the uvicorn
        server is NOT started — the caller already serves this app's ASGI
        callable (the fast-boot bootstrap in launcher.py serves a holding app on
        the port and delegates to ``self.app`` once this init chain completes).
        """
        # Just-in-time permissions: the service publishes PermissionNeeded /
        # PermissionResolved through this bus, from any thread, onto this loop.
        # FIRST, so a consumer that asks while the rest of start() runs is heard.
        # It stores two references and probes nothing (AP-26); the desktop app
        # already did the same right after the ctor, before the speech task.
        from dodaios.platform.permission_service import attach_bus as _attach_permission_bus

        _attach_permission_bus(self.bus, asyncio.get_running_loop())
        # The chat service is built on first use, by whichever thread asks
        # first; ``_build_agent_chat_service`` hands it this loop. Recorded
        # before the init chain below, during which requests are already
        # answered: a builder that found no loop closed every thread turn the
        # turn host still ran as "The app restarted" (2026-11-12).
        self.app.state.app_loop = asyncio.get_running_loop()

        # Which data directory holds the agents, chats and settings this run
        # shows: a switched JARVIS_DATA_DIR otherwise looks like lost data.
        from dodaios.core.config import log_data_dir_once

        log_data_dir_once()

        await self.prepare_app()
        import uvicorn

        # Boot profiling (opt-in via JARVIS_BOOT_PROFILE=1; zero behavior change
        # otherwise). Emits one machine-readable ``[BOOT_PROFILE] <phase>=<ms>``
        # line per phase to stdout so the boot-timing harness
        # (scripts/measure_boot.py) can attribute cold-start cost without an LLM
        # or a log-level change. NEVER on the voice critical path.
        _boot_profile = os.environ.get("JARVIS_BOOT_PROFILE") == "1"
        _boot_last = time.perf_counter()

        def _boot_mark(_name: str) -> None:
            nonlocal _boot_last
            _now = time.perf_counter()
            if _boot_profile:
                print(
                    f"[BOOT_PROFILE] {_name}={(_now - _boot_last) * 1000.0:.1f}",
                    flush=True,
                )
            _boot_last = _now

        # Cloud-first fail-closed: never expose a non-loopback bind without a
        # Control API key — the key, not the bind address, is the boundary.
        from dodaios.core import control_key as _control_key
        from dodaios.ui.web.control_auth import assert_bind_safe

        resolved_port = port if port is not None else self.cfg.ui.admin_api_port
        # Desktop bootstrap already owns the listener. CLI agents still need
        # its address to mount Jarvis' scoped tools, including Browser-Use.
        from dodaios.core import runtime_refs as _runtime_refs

        _runtime_refs.set_api_base_url(f"http://127.0.0.1:{resolved_port}")
        # Announce each change of the passive provider-health record on the bus;
        # the existing /ws fan-out carries it to every open window, whose status
        # dots then re-read (no poll, no extra socket — AP-33). Registering is
        # cheap: nothing is read or started until the first outcome arrives.
        from dodaios.brain.provider_health_ledger import publish_changes_to

        publish_changes_to(self.bus, asyncio.get_running_loop())
        if start_serving:
            assert_bind_safe(host, _control_key.get_control_key())
            # Requests from here arrive on a real socket: local open access is
            # for this user's own processes, not for every account on loopback.
            from .. import peer_owner

            config = uvicorn.Config(
                app=peer_owner.from_socket(self.app),
                host=host,
                port=resolved_port,
                log_level=self.cfg.telemetry.log_level.lower(),
                lifespan="on",
                loop="asyncio",
            )
            server = uvicorn.Server(config)
            self._server = server
            self._serve_task = asyncio.create_task(server.serve())

            deadline = asyncio.get_running_loop().time() + 5.0
            while not server.started:
                if asyncio.get_running_loop().time() > deadline:
                    raise TimeoutError(
                        f"uvicorn server on {host}:{resolved_port} not ready within 5s"
                    )
                if self._serve_task.done():
                    exc = self._serve_task.exception()
                    if exc is not None:
                        raise exc
                    raise RuntimeError("uvicorn.Server.serve() exited before 'started'")
                await asyncio.sleep(0.05)
        else:
            # Bootstrap fast-boot path: a separate server already serves on the
            # port and delegates to self.app once this init chain finishes.
            self._server = None
            self._serve_task = None

        _boot_mark("uvicorn_serve")

        # Voice-ready UI backstop (permanent "starting up" bug): the frontend's
        # startup banner + top-left "STARTING…" status clear ONLY on a
        # VoiceBootStatus(ready=True). If the speech pipeline crashes during
        # construction or an un-timed model load wedges warm-up, that event never
        # fires and the UI hangs forever. Arm a watchdog that force-releases the UI
        # after a generous deadline — but only when voice is meant to warm up
        # (else _voice_ready is already seeded True and there is nothing to wait
        # for, e.g. JARVIS_VOICE=0 / headless).
        if not self._voice_ready:
            self._voice_ready_watchdog_task = asyncio.create_task(
                self._voice_ready_watchdog(), name="voice-ready-watchdog"
            )
        else:
            # Voice is off, so no ready event will ever arrive to trigger
            # this; the end of the deferred phase is the calm moment instead.
            self._schedule_anyio_pool_warm()

        # Phase-6 mission stack — MissionManager with a DB path derived from
        # the config's memory data_dir (same folder as data/jarvis.db, its
        # own file data/missions.db). Recovery runs in start().
        try:
            await self._init_mission_stack()
        except Exception as exc:  # noqa: BLE001  # broad-except: module boundary — missions
            module_health.report_failure("missions", exc)
            logger.opt(exception=exc).warning(
                "MissionManager init failed — /api/missions returns 503"
            )
        _boot_mark("mission_stack")

        # Screenshot retention: auto-delete old Vision / Flight-Recorder blobs
        # (data/flight_recorder/blobs/) after the configured window. Runs a
        # one-shot boot sweep plus a periodic background task.
        try:
            await self._init_screenshot_retention()
        except Exception as exc:  # noqa: BLE001  # broad-except: module boundary — screenshot-retention
            module_health.report_failure("screenshot-retention", exc)
            logger.opt(exception=exc).warning(
                "Screenshot retention init failed — blobs will not be auto-pruned"
            )
        _boot_mark("screenshot_retention")

        # Flight-recorder audit log: attach the wildcard JSONL event recorder so
        # there is a replayable audit trail of what Jarvis did (every event,
        # incl. every Computer-Use action). It was defined but never wired at
        # boot, so telemetry.flight_recorder=true logged nothing (audit #14).
        try:
            await self._init_flight_recorder()
        except Exception as exc:  # noqa: BLE001  # broad-except: module boundary — flight-recorder
            module_health.report_failure("flight-recorder", exc)
            logger.opt(exception=exc).warning(
                "Flight recorder init failed — the audit log will be inactive"
            )
        _boot_mark("flight_recorder")

        # The self-change registry (versioned, gated, reversible self-changes).
        _self_change = None
        try:
            import asyncio as _asyncio

            from dodaios.self_change import wiring as _sc_wiring

            _boot_loop = _asyncio.get_running_loop()
            _self_change = _sc_wiring.install(
                Path(self.cfg.memory.data_dir),
                self.cfg,
                lambda: _boot_loop,
                publish=self.bus.publish,
            )
            self.app.state.self_change = _self_change
        except Exception as exc:  # noqa: BLE001  # broad-except: module boundary — self-change
            module_health.report_failure("self-change", exc)
            logger.opt(exception=exc).warning(
                "self-change registry init failed — self-changes are not gated this run"
            )

        # The night cycle of the self-improvement kernel (docs/self-improvement.md):
        # looks every ten minutes whether a night is due and the person is away.
        if _self_change is not None:
            try:
                from dodaios.rsi import night as _night

                _nights = _night.install(
                    Path(self.cfg.memory.data_dir),
                    _self_change,
                    config=self.cfg,
                    loop=_boot_loop,
                )
                _nights.start()
                self.app.state.self_improvement = _nights
            except Exception as exc:  # noqa: BLE001  # broad-except: module boundary — self-improvement
                module_health.report_failure("self-improvement", exc)
                logger.opt(exception=exc).warning(
                    "self-improvement nights not started — nothing is measured this run"
                )

        # The self-building loop's ledger: opens self_build.db, nothing else at
        # boot. Observers and builders register themselves later.
        try:
            from dodaios.self_build.service import start as start_self_build

            _self_build = start_self_build(
                Path(self.cfg.memory.data_dir), lambda: self.cfg, publish=self.bus.publish
            )
            self.app.state.self_build = _self_build
            _self_build.start_sweeper()
            from dodaios.self_build.app import install_in_app

            install_in_app(_self_build, self.app.state, self.bus)
            from dodaios.self_build.code import install as install_code_builder

            install_code_builder(_self_build, self.app.state)
            if _self_change is not None:
                _sc_registry, _prev_hook = _self_change, _self_build._changed

                def _mirror_hook(record: Any) -> None:
                    _prev_hook(record)
                    try:
                        _sc_wiring.mirror_build(_sc_registry, record)
                    except Exception:  # noqa: BLE001 - a mirror never costs the build
                        logger.debug("self-change mirror failed", exc_info=True)

                _self_build.ledger.set_change_hook(_mirror_hook)
                _self_change.register_external_reverter(
                    lambda change: _sc_wiring.revert_build(_self_build, change)
                )
        except Exception as exc:  # noqa: BLE001  # broad-except: module boundary — self-build
            module_health.report_failure("self-build", exc)
            logger.opt(exception=exc).warning(
                "self-build ledger init failed — nothing will be self-built this run"
            )

        # Jarvis' own self-learning loop: two bus subscriptions, nothing else
        # at boot. Reviews run later in the background (dodaios/memory/learning).
        try:
            from dodaios.memory.learning.loop import start_learning

            start_learning(self.cfg, self.bus)
        except Exception as exc:  # noqa: BLE001  # broad-except: module boundary — learning-loop
            module_health.report_failure("learning-loop", exc)
            logger.opt(exception=exc).warning(
                "Learning loop init failed — the assistant will not learn this run"
            )

        # Voice-session recorder + store for the transcription view.
        # Sub-setup: runs sync (SQLite-WAL, no async loop needed), but is
        # run in start() so the EventBus is guaranteed to be alive.
        try:
            self._init_session_stack()
        except Exception as exc:  # noqa: BLE001  # broad-except: module boundary — sessions
            module_health.report_failure("sessions", exc)
            logger.opt(exception=exc).warning(
                "SessionRecorder init failed — /api/sessions returns 503"
            )
        _boot_mark("session_stack")

        # Phase-5 task stack (tasks view). TaskStore lives additively in
        # data/jarvis.db (ADR-0003); the scheduler runs as an asyncio loop
        # terminated by the CancelToken in stop().
        try:
            await self._init_task_stack()
        except Exception as exc:  # noqa: BLE001  # broad-except: module boundary — tasks
            module_health.report_failure("tasks", exc)
            logger.opt(exception=exc).warning("TaskStack init failed — /api/tasks returns 503")
        _boot_mark("task_stack")

        # Start the skill hot-reload watcher once the loop is stable.
        if self._skill_registry is not None:
            try:
                self._skill_registry.start_watcher(asyncio.get_running_loop())
            except Exception as exc:  # noqa: BLE001  # broad-except: module boundary — skill-watcher
                module_health.report_failure("skill-watcher", exc)
                logger.opt(exception=exc).warning(
                    "SkillRegistry watcher start failed — no hot-reload"
                )

        # Doc hot-reload watcher, likewise. watchdog observes its own
        # observer thread per root.
        if self._doc_registry is not None:
            try:
                self._doc_registry.start_watcher(asyncio.get_running_loop())
            except Exception as exc:  # noqa: BLE001  # broad-except: module boundary — doc-watcher
                module_health.report_failure("doc-watcher", exc)
                logger.opt(exception=exc).warning(
                    "DocRegistry watcher start failed — no hot-reload"
                )

        # These owners must settle before shutdown closes their registries.
        self._schedule_registry_bootstraps()

        # Board aggregator as a never-ending task. run_forever() does an
        # on-startup run first and then sleeps 6h (Plan §5-A Decision #2).
        if self._board_aggregator is not None:
            self._board_aggregator_task = asyncio.create_task(
                self._board_aggregator.run_forever(interval_s=6 * 3600),
                name="board-aggregator",
            )

        # Achievement evaluator on the bus. Phase B.
        if self._board_evaluator is not None:
            try:
                self._board_evaluator.attach()
            except Exception as exc:  # noqa: BLE001  # broad-except: module boundary — achievements
                module_health.report_failure("achievements", exc)
                logger.opt(exception=exc).warning("AchievementEvaluator.attach() failed")

        # Bio scheduler — subscribes to achievement unlocks only. It starts no
        # task and generates nothing here; the brain is resolved per
        # generation, when a board event actually asks for one.
        if self._bio_scheduler is not None:
            try:
                self._bio_scheduler.start()
            except Exception as exc:  # noqa: BLE001  # broad-except: module boundary — bio-scheduler
                module_health.report_failure("bio-scheduler", exc)
                logger.opt(exception=exc).warning("BioScheduler.start() failed")

        # Friends-Stack: FriendRegistry + ChannelManager. Started as a BACKGROUND
        # task so a slow Telegram/Discord network connect (bot login / getUpdates
        # handshake — observed ~4 s, and a 409 retry storm on a restart overlap)
        # does not delay backend-ready and, with it, the speech warm-up. Channels
        # are background transports — nothing user-visible needs them live before
        # voice; /api/friends + /api/socials 503 until the stack is up (the route
        # guards already handle the brief app.state.channel_manager=None window).
        async def _init_channel_stack_guarded() -> None:
            try:
                await self._init_channel_stack()
            except Exception as exc:  # noqa: BLE001  # broad-except: module boundary — channels
                module_health.report_failure("channels", exc)
                logger.opt(exception=exc).warning(
                    "ChannelStack init failed — /api/friends returns 503"
                )

        self._channel_stack_task = asyncio.create_task(
            _init_channel_stack_guarded(), name="channel-bootstrap"
        )

        # Desktop notifications and the reminder scheduler (dodaios/notify).
        # Only the default app delivers: a second (dev) instance would tell
        # every reminder twice. JARVIS_DEV_REMINDERS=1 lets the dev app tell
        # its own data dir's reminders in its chat, without desktop
        # notifications, to try how they read (docs/dev-instance.md).
        try:
            from dodaios.core.instance import current_instance
            from dodaios.notify import wiring as notify_wiring

            owns = current_instance().owns_ambient_duties
            dev_reminders = not owns and os.environ.get("JARVIS_DEV_REMINDERS") == "1"
            notify_wiring.install(
                app_state=self.app.state,
                bus=self.bus,
                cfg=self.cfg,
                get_service=lambda: getattr(self.app.state, "agent_chat", None),
                start_scheduler=owns or dev_reminders,
                desktop_reminders=owns,
            )
        except Exception as exc:  # noqa: BLE001 — the app runs without notifications  # broad-except: module boundary — notify
            module_health.report_failure("notify", exc)
            logger.opt(exception=exc).warning("notify: not started")

        try:
            from dodaios.lead_triggers import wiring as trigger_wiring

            trigger_wiring.install(self.bus)
        except Exception as exc:  # noqa: BLE001 — the app runs without event triggers  # broad-except: module boundary — lead-triggers
            module_health.report_failure("lead-triggers", exc)
            logger.opt(exception=exc).warning("lead triggers: not started")

        try:
            from dodaios.rituals import said as ritual_said

            # What a ritual gathered after it was started by voice is said in the open call.
            ritual_said.install(self.bus)
        except Exception as exc:  # noqa: BLE001 — rituals still start; a late result is only written  # broad-except: module boundary — rituals
            module_health.report_failure("rituals", exc)
            logger.opt(exception=exc).warning("rituals: voice not wired")

        # Run the deferred registry disk scans (skill + doc reload_sync) off the
        # boot critical path. Each is a blocking glob + FTS index build (~hundreds
        # of ms) that nothing at BOOT_READY needs — the views tolerate an empty
        # registry until the scan lands. Run in a worker thread so the scan never
        # stalls the event loop; sequential so two SQLite writers don't contend.
        if self._pending_reloads:
            pending = list(self._pending_reloads)
            self._pending_reloads.clear()
            # Docs are user-facing and can be opened immediately after the
            # shell appears. Keep the scans sequential, but put Docs ahead of
            # the authoring-only skill catalog once the wake gate releases.
            pending.sort(key=lambda item: item[0] != "DocRegistry")

            async def _run_deferred_reloads() -> None:
                # Yield until the wake model is loaded before these blocking disk
                # scans start their worker thread —
                # otherwise they steal CPU/disk from the custom-wake base/cpu
                # model load and can extend its time. NO-OP on headless / voice-off
                # (returns immediately); bounded so a stuck wake load never blocks
                # the scans. The Docs view can request the same load immediately.
                from dodaios.core import runtime_refs as _rr

                await _rr.await_wake_model_ready(timeout=12.0)
                for label, registry in pending:
                    try:
                        if label == "DocRegistry":
                            # Shares the on-demand route lock: if the user
                            # already opened Docs this becomes an instant no-op.
                            await registry.ensure_loaded()
                        else:
                            await asyncio.to_thread(registry.reload_sync)
                        logger.info(
                            "{} deferred scan complete ({} entries)",
                            label,
                            len(registry.list()),
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.opt(exception=exc).warning(
                            "{} deferred reload failed — view stays empty", label
                        )

            self._deferred_reload_task = asyncio.create_task(
                _run_deferred_reloads(), name="deferred-registry-reload"
            )

        _boot_mark("watchers_and_background")
        # Schedule last: callers regain control and publish the ready app before
        # catalog/keyring reads or refresh network calls can begin. This shared
        # hook covers normal desktop, headless, and direct WebServer starts.
        self._schedule_marketplace_refresh_scheduler()
        self._start_local_models_health_monitor()
        self._start_main_follower()
        self._start_microphone_rescue()
        self._schedule_local_models_autostart()
        # Same reasoning, and the same three boot paths: a headless or
        # browser-only install has no desktop shell to warm the realtime
        # transport for it.
        self._schedule_realtime_transport_warm()
        self._schedule_appshot_shortcut()
        self._schedule_credential_migration()
        self._schedule_distribution_check()

    async def stop(self) -> None:
        from dodaios.core import runtime_refs

        appshot_task = getattr(self, "_appshot_shortcut_task", None)
        if appshot_task is not None:
            appshot_task.cancel()
            await asyncio.gather(appshot_task, return_exceptions=True)
            self._appshot_shortcut_task = None
        try:
            from dodaios.appshot.hotkey import stop_appshot_shortcut

            await stop_appshot_shortcut()
        except Exception:
            logger.opt(exception=True).warning("Appshot helpers failed to stop")

        if runtime_refs.get_web_app() is self.app:
            runtime_refs.set_web_app(None)
        # A cancelled setup waiter cannot stop its worker thread. Join it
        # before closing board/stores/subscriptions that it may still create.
        try:
            await self._feature_setup.stop()
        except Exception as exc:  # noqa: BLE001 -- close partial setup too
            logger.opt(exception=exc).warning("Application feature setup failed during shutdown")
        # Fence lazy creation even when no Society owner exists yet. The shared
        # brain factory and HTTP surface can still be called while shutdown awaits.
        self.app.state.society_stopping = True
        registry_bootstraps_stopped = await self._stop_registry_bootstraps()
        # A short-lived server can stop before these delayed boot helpers run.
        # Own and drain them here instead of leaving asyncio.run()/pytest to
        # discover them during loop teardown. Stop the deferred registry reload
        # before its registries are closed below so shutdown cannot race a scan.
        for attr in ("_anyio_pool_warm_task", "_deferred_reload_task"):
            task = getattr(self, attr, None)
            setattr(self, attr, None)
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        society = getattr(self.app.state, "society", None)
        society_shutdown_failure: str | None = None
        if society is not None:
            try:
                # The runtime owns delivery tasks, subscriptions and SQLite as
                # well as the browser. Leaving its store open prevents exit.
                await asyncio.wait_for(society.close(), timeout=server_module()._SOCIETY_SHUTDOWN_TIMEOUT_S)
            except Exception as exc:  # noqa: BLE001 -- finish independent cleanup below
                society_shutdown_failure = type(exc).__name__
                logger.warning("Society runtime cleanup incomplete ({})", society_shutdown_failure)
        self._mic_level_sessions.clear()
        self._stop_mic_level_bridge()

        try:
            from dodaios.memory.learning.loop import stop_learning

            await stop_learning()
        except Exception as exc:  # noqa: BLE001 -- finish independent cleanup below
            logger.opt(exception=exc).debug("Learning loop stop failed")

        team_threads = getattr(self.app.state, "team_threads", None)
        if team_threads is not None:
            # Before the chat turns end: a coordinator that sees its members'
            # turns cancelled under it would read that as members failing.
            try:
                await team_threads.close()
            except Exception as exc:  # noqa: BLE001 -- finish independent cleanup below
                logger.opt(exception=exc).debug("team threads close failed")

        agent_chat = getattr(self.app.state, "agent_chat", None)
        if agent_chat is not None:
            try:
                await agent_chat.cancel_all()
            except Exception as exc:  # noqa: BLE001
                logger.opt(exception=exc).debug("agent chat cancel_all failed")

        # Stop token refresh before the plugin registry so an in-flight refresh
        # cannot enqueue a live-session rebuild while that registry is closing.
        await self._stop_marketplace_refresh_scheduler()
        await self._stop_local_models_health_monitor()
        await self._stop_microphone_rescue()
        await self._stop_local_models_autostart()

        # Stop the skill watcher, otherwise the watchdog thread stays behind
        # as a zombie and prevents the process from exiting.
        if self._skill_registry is not None:
            try:
                self._skill_registry.stop_watcher()
            except Exception as exc:  # noqa: BLE001
                logger.opt(exception=exc).warning("SkillRegistry watcher stop failed")

        # Close the doc watcher + FTS5 connection.
        if self._doc_registry is not None:
            try:
                self._doc_registry.close()
            except Exception as exc:  # noqa: BLE001
                logger.opt(exception=exc).warning("DocRegistry close failed")

        # Unset the shared CLI registry — otherwise the module singleton keeps
        # a reference to a "dead" registry when the server restarts.
        try:
            from dodaios.clis.shared import set_active_registry

            set_active_registry(None)
        except Exception as exc:  # noqa: BLE001
            logger.opt(exception=exc).debug("CLI shared-registry cleanup failed: {}", exc)

        # Symmetric teardown for the plugin registry: unset the module singleton
        # AND stop the registry so each connected plugin's MCPClient (with its
        # AsyncExitStack / subprocess) is closed cleanly. Without this, an
        # in-process restart (--no-lock parallel dev, test teardown) would leave
        # a stale shared handle and leaked MCP sessions.
        # A timed-out bootstrap may still hold the registry lock while cleaning
        # up. Keep both references for a later stop attempt; closing it now can
        # block indefinitely on that same lock.
        if (
            self._plugin_registry is not None
            and getattr(self, "_plugin_bootstrap_task", None) is None
        ):
            try:
                from dodaios.marketplace.plugin_shared import set_active_plugin_registry

                set_active_plugin_registry(None)
                await self._plugin_registry.stop()
            except Exception as exc:  # noqa: BLE001
                logger.opt(exception=exc).debug("PluginToolRegistry cleanup failed: {}", exc)
            self._plugin_registry = None
            self.app.state.plugin_registry = None

        # Cleanly stop the board-aggregator task before uvicorn goes down. The
        # run_forever() loop catches CancelledError itself and re-raises it.
        if self._board_aggregator_task is not None:
            self._board_aggregator_task.cancel()
            try:
                await asyncio.wait_for(self._board_aggregator_task, timeout=2.0)
            except (TimeoutError, asyncio.CancelledError):
                pass
            except Exception as exc:  # noqa: BLE001
                logger.opt(exception=exc).warning("Board-aggregator shutdown error")
            self._board_aggregator_task = None
        # Voice-ready backstop watchdog: usually already finished (it fires once
        # and returns), but cancel it if a shutdown lands inside its deadline so
        # it is never orphaned as a pending task at loop close.
        _watchdog_task = getattr(self, "_voice_ready_watchdog_task", None)
        if _watchdog_task is not None:
            _watchdog_task.cancel()
            try:
                await asyncio.wait_for(_watchdog_task, timeout=2.0)
            except (TimeoutError, asyncio.CancelledError):
                pass
            except Exception as exc:  # noqa: BLE001
                logger.opt(exception=exc).debug("voice-ready watchdog shutdown: {}", exc)
            self._voice_ready_watchdog_task = None
        # Realtime transport warm: usually finished long before a shutdown, but
        # a stop inside its boot delay must not orphan it at loop close.
        _warm_task = self._realtime_warm_task
        self._realtime_warm_task = None
        if _warm_task is not None and not _warm_task.done():
            _warm_task.cancel()
            try:
                await asyncio.wait_for(_warm_task, timeout=2.0)
            except (TimeoutError, asyncio.CancelledError):
                pass
            except Exception as exc:  # noqa: BLE001 -- shutdown stays best-effort
                logger.opt(exception=exc).debug("Realtime transport warm shutdown: {}", exc)
        if self._bio_scheduler is not None:
            try:
                await self._bio_scheduler.stop()
            except Exception as exc:  # noqa: BLE001
                logger.opt(exception=exc).debug("BioScheduler.stop(): {}", exc)
        if self._board_evaluator is not None:
            try:
                self._board_evaluator.close()
            except Exception as exc:  # noqa: BLE001
                logger.opt(exception=exc).debug("AchievementEvaluator.close(): {}", exc)
        if self._board_aggregator is not None:
            try:
                self._board_aggregator.close()
            except Exception as exc:  # noqa: BLE001
                logger.opt(exception=exc).debug("Board-Aggregator close(): {}", exc)

        # Terminate PTY sessions before uvicorn goes down — prevents reader
        # threads from trying to write into a closed loop.
        try:
            self._pty.close_all()
        except Exception as exc:  # noqa: BLE001
            logger.opt(exception=exc).warning("PTY cleanup failed")

        # Cleanly shut down the Phase-6 mission stack — closing the
        # connection closes the SQLite DB. Cancel the periodic recovery
        # re-sweep + cleanup task BEFORE the store closes (otherwise the
        # re-sweep ticks against a closed connection).
        resweep_task = getattr(self, "_missions_resweep_task", None)
        if resweep_task is not None:
            resweep_task.cancel()
            try:
                await asyncio.wait_for(resweep_task, timeout=2.0)
            except (TimeoutError, asyncio.CancelledError):
                pass
            self._missions_resweep_task = None

        # The resume timer stops here; a mission it already resumed runs in its
        # own task and is finalized by cancel_all_running below.
        resume_task = getattr(self, "_missions_resume_task", None)
        if resume_task is not None:
            resume_task.cancel()
            try:
                await asyncio.wait_for(resume_task, timeout=2.0)
            except (TimeoutError, asyncio.CancelledError):  # expected while stopping the timer
                pass
            self._missions_resume_task = None

        cleanup_task = getattr(self, "_missions_cleanup_task", None)
        if cleanup_task is not None:
            cleanup_task.cancel()
            try:
                await asyncio.wait_for(cleanup_task, timeout=2.0)
            except (TimeoutError, asyncio.CancelledError):
                pass
            self._missions_cleanup_task = None

        # Screenshot-retention background task (opt-in via retention_days > 0).
        screenshot_task = getattr(self, "_screenshot_retention_task", None)
        if screenshot_task is not None:
            screenshot_task.cancel()
            try:
                await asyncio.wait_for(screenshot_task, timeout=2.0)
            except asyncio.CancelledError:
                pass
            except TimeoutError:
                logger.warning("retention_task: did not stop within 2s — may be blocking on I/O")
            self._screenshot_retention_task = None

        # Flush + close the flight-recorder audit log so the last buffered events
        # reach disk before shutdown (it otherwise auto-flushes every ~1s).
        recorder = getattr(self, "_flight_recorder", None)
        if recorder is not None:
            try:
                await recorder.flush()
                await recorder.close()
            except Exception as exc:  # noqa: BLE001 — shutdown best-effort
                logger.opt(exception=exc).debug("Flight recorder close: {}", exc)
            self._flight_recorder = None

        # Finalize in-flight missions BEFORE the store closes: a restart used
        # to kill the process with missions still running, leaving them
        # non-terminal until the recovery re-sweep buried them 30 min later as
        # opaque crash_recovery/ERROR cards (live missions 019eb27f/019eb288,
        # 2026-06-10 19:24). cancel_all_running flips each to an honest
        # CANCELLED('app_shutdown') and awaits the dying run tasks briefly.
        kontrollierer = getattr(self.app.state, "kontrollierer", None)
        cancel_all = getattr(kontrollierer, "cancel_all_running", None)
        if cancel_all is not None:
            try:
                await cancel_all(reason="app_shutdown")
            except Exception as exc:  # noqa: BLE001
                logger.opt(exception=exc).warning("In-flight mission finalize on shutdown failed")

        try:
            await self._mission_tool_approvals.deny_all(reason="app_shutdown")
        except Exception as exc:  # noqa: BLE001 - shutdown remains best-effort
            logger.opt(exception=exc).warning("Pending mission tool approval cleanup failed")

        mission_manager = getattr(self.app.state, "mission_manager", None)
        if mission_manager is not None:
            try:
                await mission_manager.stop()
            except Exception as exc:  # noqa: BLE001
                logger.opt(exception=exc).warning("MissionManager.stop() failed")
            self.app.state.mission_manager = None
            self.app.state.kontrollierer = None

        # Shut down the Phase-5 task stack: cancel the scheduler loop, wait
        # for running runner tasks (max 2s), close the store.
        if self._task_scheduler is not None and self._task_cancel_token is not None:
            try:
                self._task_cancel_token.cancel("server_shutdown")
            except Exception as exc:  # noqa: BLE001
                logger.opt(exception=exc).debug("Task-CancelToken.cancel(): {}", exc)
        if self._task_scheduler_task is not None:
            self._task_scheduler_task.cancel()
            try:
                await asyncio.wait_for(self._task_scheduler_task, timeout=2.0)
            except (TimeoutError, asyncio.CancelledError):
                pass
            except Exception as exc:  # noqa: BLE001
                logger.opt(exception=exc).warning("TaskScheduler loop shutdown error: {}", exc)
            self._task_scheduler_task = None
        if self._task_scheduler is not None:
            try:
                await self._task_scheduler.shutdown()
            except Exception as exc:  # noqa: BLE001
                logger.opt(exception=exc).debug("TaskScheduler.shutdown(): {}", exc)
        if self._task_store is not None:
            try:
                await self._task_store.close()
            except Exception as exc:  # noqa: BLE001
                logger.opt(exception=exc).warning("TaskStore.close() failed")
        self._task_scheduler = None
        self._task_store = None
        self._task_runner = None
        self._task_cancel_token = None
        self.app.state.task_store = None
        self.app.state.task_scheduler = None
        self.app.state.task_runner = None

        # Detach the voice-session recorder from the bus + close the DB connection.
        recorder = getattr(self, "_session_recorder", None)
        store = getattr(self.app.state, "session_store", None)
        if recorder is not None or store is not None:
            try:
                from dodaios.sessions.init import shutdown_sessions

                shutdown_sessions({"store": store, "recorder": recorder})
            except Exception as exc:  # noqa: BLE001
                logger.opt(exception=exc).warning("SessionRecorder shutdown failed")
            self._session_recorder = None
            self.app.state.session_store = None

        try:
            from dodaios.notify import wiring as notify_wiring

            await notify_wiring.shutdown()
        except Exception as exc:  # noqa: BLE001
            logger.opt(exception=exc).warning("notify shutdown failed")

        # A shutdown inside the channel bootstrap (the first seconds after
        # login) cancels it; bootstrap_channels then stops what it started
        # and cancels its start retries itself, so none outlives the app.
        _channel_stack_task = getattr(self, "_channel_stack_task", None)
        self._channel_stack_task = None
        if _channel_stack_task is not None and not _channel_stack_task.done():
            _channel_stack_task.cancel()
            try:
                await asyncio.wait_for(_channel_stack_task, timeout=5.0)
            except (TimeoutError, asyncio.CancelledError):  # cancelled on purpose: nothing to tell
                pass
            except Exception as exc:  # noqa: BLE001 -- shutdown stays best-effort
                logger.opt(exception=exc).debug("Channel bootstrap shutdown: {}", exc)
        channel_manager = getattr(self.app.state, "channel_manager", None)
        friend_registry = getattr(self.app.state, "friend_registry", None)
        channel_bridge = getattr(self, "_channel_chat_bridge", None)
        if channel_bridge is not None:
            try:
                await channel_bridge.stop()
            except Exception as exc:  # noqa: BLE001
                logger.opt(exception=exc).warning("ChannelChatBridge shutdown failed")
            self._channel_chat_bridge = None
            self.app.state.channel_chat_bridge = None
        if channel_manager is not None or friend_registry is not None:
            try:
                from dodaios.channels.bootstrap import shutdown_channels

                if channel_manager is not None and friend_registry is not None:
                    await shutdown_channels(channel_manager, friend_registry)
                elif channel_manager is not None:
                    await channel_manager.stop_all()
                elif friend_registry is not None:
                    await friend_registry.close()
            except Exception as exc:  # noqa: BLE001
                logger.opt(exception=exc).warning("ChannelStack shutdown failed")
            self.app.state.channel_manager = None
            self.app.state.friend_registry = None

        if self._server is not None:
            self._server.should_exit = True
            if self._serve_task is not None:
                try:
                    await asyncio.wait_for(self._serve_task, timeout=5.0)
                except TimeoutError:
                    logger.warning("uvicorn shutdown timeout — force-cancel")
                    self._serve_task.cancel()
        self._server = None
        self._serve_task = None

        # A recall store nobody closed keeps a non-daemon aiosqlite thread, and
        # the process could not exit until systemd killed it (BC-250 2026-10-29).
        try:
            from dodaios.memory.recall import close_open_recall_stores

            closed = await close_open_recall_stores()
            if closed:
                logger.info("Closed {} recall store(s) left open", closed)
        except Exception as exc:  # noqa: BLE001 - shutdown continues best-effort
            logger.opt(exception=exc).warning("Recall store cleanup failed")

        # Browser/desktop realtime owners must release their ephemeral threads
        # before their shared process is reaped. Keep this unconditional: a
        # failed startup can complete the Codex handshake before uvicorn marks
        # itself running, and that process still needs bounded teardown.
        try:
            from dodaios.codex_app_server import close_shared_codex_app_servers

            await close_shared_codex_app_servers()
        except Exception as exc:  # noqa: BLE001 - shutdown continues best-effort
            logger.opt(exception=exc).warning("Codex subscription app-server cleanup failed")

        if society_shutdown_failure is not None:
            raise RuntimeError(f"society_runtime_shutdown_incomplete ({society_shutdown_failure})")
        if not registry_bootstraps_stopped:
            raise RuntimeError("registry_bootstrap_shutdown_incomplete")
