"""The boot-time service stacks (missions, tasks, sessions, channels, society, chat)."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from dodaios.core.config import resolve_config_path

if TYPE_CHECKING:
    pass

from ._srv import server_module

if TYPE_CHECKING:
    from dodaios.ui.web.server_parts._host_state import WebServerHostState as _HostBase
else:
    _HostBase = object


class BootStacksMixin(_HostBase):
    """The boot-time service stacks (missions, tasks, sessions, channels, society, chat)."""

    async def _init_screenshot_retention(self) -> None:
        """Auto-delete captured screenshot blobs older than the configured
        window (default 10 days).

        Jarvis captures screenshots into ``data/flight_recorder/blobs/`` for
        in-session context (Vision system + Flight-Recorder event blobs); they
        are throwaway afterwards and otherwise grow without bound (observed:
        ~91k files / ~38 GB). Runs a one-shot sweep at boot plus a periodic
        background task. ``flight_recorder_retention_days = 0`` disables it.
        """
        from dodaios.telemetry.retention import (
            DEFAULT_RETENTION_INTERVAL_SECONDS,
            retention_task,
            sweep_old_blobs,
        )

        retention_days = self.cfg.telemetry.flight_recorder_retention_days
        if retention_days <= 0:
            logger.info(
                "Screenshot retention disabled (flight_recorder_retention_days={})",
                retention_days,
            )
            return

        # The same directory the writers use, NOT cfg.memory.data_dir. The
        # production writer is the Vision ScreenshotSource
        # (dodaios/vision/engine.py constructs it with no blob_dir → falls back
        # to _DEFAULT_BLOB_DIR in dodaios/vision/screenshot.py =
        # flight_recorder_dir()/blobs). It ignores cfg.memory.data_dir, so
        # deriving from that key would make the sweep a silent no-op whenever
        # data_dir is overridden.
        from dodaios.core.paths import flight_recorder_dir as _flight_recorder_dir

        flight_recorder_dir = _flight_recorder_dir()

        # The one-shot boot sweep is pure cleanup of old blobs — nothing
        # downstream consumes its stats (they are only logged). Awaiting it sat
        # on the boot path before the voice pipeline could start. Fold it into
        # the front of the (already background) retention task so _init returns
        # immediately; the same task reference is still cancelled on shutdown.
        async def _boot_sweep_then_retain() -> None:
            try:
                stats = await sweep_old_blobs(
                    flight_recorder_dir=flight_recorder_dir,
                    retention_days=retention_days,
                )
                if stats["removed"] > 0:
                    logger.info(
                        "Screenshot retention boot sweep: removed={} freed={:.1f} MB (cutoff={}d)",
                        stats["removed"],
                        stats["bytes_freed"] / (1024 * 1024),
                        retention_days,
                    )
                else:
                    logger.debug(
                        "Screenshot retention boot sweep: nothing older than {}d",
                        retention_days,
                    )
            except Exception:  # noqa: BLE001 — cleanup never blocks/breaks boot
                logger.warning("Screenshot retention boot sweep failed", exc_info=True)
            await retention_task(
                flight_recorder_dir=flight_recorder_dir,
                retention_days=retention_days,
                interval_seconds=DEFAULT_RETENTION_INTERVAL_SECONDS,
            )

        self._screenshot_retention_task = asyncio.create_task(_boot_sweep_then_retain())

    async def _init_flight_recorder(self) -> None:
        """Attach the flight-recorder audit log to the EventBus (ADR-0007).

        Writes every event as a JSONL line under ``data/flight_recorder/`` — a
        replayable audit trail of what Jarvis did, including every Computer-Use
        action. Gated on ``telemetry.flight_recorder`` (default on); the recorder
        is held on ``app.state`` for later flush/close on shutdown. The recorder
        auto-flushes every second, and oversized event blobs land under
        ``blobs/`` which the screenshot-retention task already prunes.
        """
        from dodaios.core.paths import flight_recorder_dir
        from dodaios.telemetry.recorder import attach_flight_recorder

        rec = attach_flight_recorder(
            self.bus,
            enabled=self.cfg.telemetry.flight_recorder,
            data_dir=flight_recorder_dir(),
        )
        if rec is None:
            logger.info("Flight recorder disabled (telemetry.flight_recorder=false)")
            return
        self._flight_recorder = rec
        self.app.state.flight_recorder = rec
        logger.info("Flight recorder attached — events -> data/flight_recorder/*.jsonl")

    async def _init_mission_stack(self) -> None:
        """Phase-6 production wiring: bootstrap_missions() returns the
        complete stack (manager, Kontrollierer, budget, voice listener,
        cleanup task), including safety hooks and the WS-manager bus bridge.
        """
        from dodaios.missions.init import bootstrap_missions

        data_dir = Path(self.cfg.memory.data_dir)
        # Startup wiring runs before this stack accepts work.
        data_dir.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240
        db_path = data_dir / "missions.db"

        # Isolation root: <repo_parent>/jarvis-agent-outputs/ (preferred; falls back
        # to <repo_parent>/sub-agents-outputs/ if only the old dir exists — see
        # resolve_outputs_root). The repo root is 4 levels above dodaios/ui/web/server.py:
        # server.py -> web -> ui -> jarvis -> repo.
        repo_root = server_module().WEB_DIR.parent.parent.parent
        # Test/benchmark isolation seam: an explicit JARVIS_ISOLATION_ROOT
        # redirects the mission worktree container (and, with it, the startup
        # cleanup sweep) away from the SHARED production outputs dir.
        # Unset in production → unchanged behavior. Critical because
        # ``startup_sweep`` is filesystem-driven (removes any entry older than
        # cleanup_days by mtime, not DB-gated): without this seam an isolated
        # headless boot (e.g. scripts/measure_boot.py) would sweep real mission
        # outputs older than 14 days.
        from dodaios.missions.isolation.worktree import (
            resolve_outputs_root,
            resolve_readable_outputs_roots,
        )

        _iso_override = os.environ.get("JARVIS_ISOLATION_ROOT")
        if _iso_override:
            isolation_root = Path(_iso_override)
        else:
            isolation_root = resolve_outputs_root(repo_root)

        # Fail-closed primary-instance gate: POSITIVE proof is required.
        # Only the launcher process, after confirming it holds the
        # single-instance lock, sets JARVIS_PRIMARY_INSTANCE="1".
        # Any other caller — smoke scripts, eval harnesses, --no-lock parallel
        # sessions, or anything that simply does not set the variable — gets
        # _is_primary=False and will NOT run the crash_recovery sweep.
        # This prevents side-processes from sweeping the desktop app's live
        # missions to FAILED('crash_recovery') (the 98-of-286 false-failure
        # bucket, forensic 2026-05-31, missions 019e7095 / 019e6fea).
        _is_primary = os.environ.get("JARVIS_PRIMARY_INSTANCE") == "1"
        result = await bootstrap_missions(
            db_path=db_path,
            isolation_root=isolation_root,
            repo_root=repo_root,
            recover_missions=_is_primary,
            tts_speak_fn=None,  # TTS wiring comes from DesktopApp once voice is live
            brain_caller=None,  # The decomposer runs in heuristic-only mode
            # Welle-4 Y: pass the speech bus through for MissionAnnouncer, so
            # mission-completion events land as AnnouncementRequested on the
            # global bus — pipeline._on_announcement subscribes there.
            speech_bus=self.bus,
            # Defaults from jarvis.toml [phase6.*] (all overridable via cfg later)
            safety_enabled=True,
            # User mandate 2026-05-31 ("no budget at all", frontier-quality-
            # over-cost): the per-mission/daily cost cap is DISABLED so a long,
            # high-quality Opus mission is never aborted mid-work for cost. The
            # per_mission_usd/daily_usd values below are inert while disabled.
            budget_enabled=False,
            per_mission_usd=5.0,
            daily_usd=50.0,
            cleanup_days=14,
            cleanup_startup_sweep=True,
            cleanup_daily=False,
            max_workers=5,
        )

        self.app.state.mission_manager = result["manager"]
        self.app.state.kontrollierer = result["kontrollierer"]
        # Voice "cancel the mission" must also stop the in-flight run, not just
        # flip the state: hand the manager the orchestrator's cancel hook.
        _cancel_hook = getattr(result["kontrollierer"], "cancel_running_mission", None)
        if callable(_cancel_hook):
            result["manager"].bind_run_canceller(_cancel_hook)
        self.app.state.missions_budget = result["budget"]
        self.app.state.mission_announcer = result["mission_announcer"]
        # Mission-Bus -> global-bus bridge that re-publishes terminal missions
        # as MissionCompleted so the Tasks scheduler can drive When-Then rules.
        self.app.state.mission_event_bridge = result["mission_event_bridge"]
        # outputs_routes.py uses this to render the Outputs view; it would
        # otherwise have to re-derive the same WEB_DIR.parent.parent.parent
        # walk and would silently drift if the launcher layout changes.
        self.app.state.outputs_root = isolation_root
        self.app.state.outputs_roots = resolve_readable_outputs_roots(repo_root)
        self._missions_voice_listener = result["voice_listener"]
        self._missions_cleanup_task = result["cleanup_task"]

        # Welle-4 wiring: the spawn_worker tool in the brain needs both the
        # MissionManager AND the Kontrollierer. The brain is built in
        # DesktopApp._start_speech_and_orb via build_default_brain() — the
        # singleton setters make both available there (lazy resolve via
        # _resolve_mission_manager / _resolve_kontrollierer).
        # Without the Kontrollierer setter, the voice path would dispatch a
        # mission but nothing would trigger run_mission — the mission would
        # stay PENDING and the user would hear no answer (BUG-016).
        try:
            from dodaios.brain.factory import (
                set_kontrollierer,
                set_mission_manager,
                set_worker_bootstrap_failed,
            )

            set_mission_manager(result["manager"])
            set_kontrollierer(result["kontrollierer"])
            set_worker_bootstrap_failed(False)
            self.app.state.worker_available = True
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "set_mission_manager/kontrollierer wiring failed — "
                "spawn_worker is disabled for this run: %s",
                exc,
            )
            # Surface the failure for both downstream readers:
            #  - `self.app.state.worker_available` lets REST routes and
            #    UI components show an explicit "worker unavailable" hint
            #    instead of permanently rendering "loading" / "pending".
            #  - the factory-level singleton lets the Brain's spawn_worker
            #    tool short-circuit at execute()-time with an honest
            #    "could not be initialized" message instead of the
            #    transient "not ready yet" the in-progress path returns.
            self.app.state.worker_available = False
            try:
                from dodaios.brain.factory import set_worker_bootstrap_failed

                set_worker_bootstrap_failed(True)
            except Exception as inner_exc:  # noqa: BLE001
                logger.warning(
                    "set_worker_bootstrap_failed wiring failed: %s",
                    inner_exc,
                )

        # WS bridge: the Phase-4 ConnectionManager is subscribed to the bus.
        ws_mgr = getattr(self.app.state, "missions_ws_manager", None)
        if ws_mgr is not None:
            result["manager"].bus.subscribe_all(ws_mgr.fanout)

        # Welle-4 follow-up: bridge MissionBus -> SubAgentRegistry so the
        # Sub-Agents board lights up. The legacy publishers for
        # JarvisAgentTaskStarted/Completed were removed in the migration; without
        # this hook the dashboard stays empty even while missions are flowing.
        registry = getattr(self.app.state, "sub_agent_registry", None)
        if registry is not None:
            registry.attach_mission_bus(result["manager"].bus)

        recovered = result["recovered_mission_ids"]
        sweep = result["sweep_stats"]
        logger.info(
            "Phase-6 stack online (db={}, recovered={}, sweep={}/{}/{} scanned/removed/errors)",
            db_path,
            len(recovered),
            sweep["scanned"],
            sweep["removed"],
            sweep["errors"],
        )

        # Periodic recovery re-sweep (2026-06-10, mission 019eb25c): boot
        # recovery runs ONCE and — correctly — skips a mission whose owner still
        # looks live (active-guard). But that guard is boot-only: when the owning
        # instance dies AFTER boot, the orphan stays non-terminal (e.g.
        # CRITIQUING) in the DB and UI forever ("missions never find an end").
        # This timer re-runs the SAME conservative, active-guarded sweep so an
        # orphan is finalized on the next tick once it crosses the unchanged
        # staleness threshold. Gated on the same primary-instance flag as boot
        # recovery — a secondary/--no-lock instance must never sweep a primary's
        # live missions. Cancelled on shutdown (see start()'s cleanup path).
        if _is_primary:
            from dodaios.missions.recovery import periodic_recovery_sweep

            self._missions_resweep_task = asyncio.create_task(
                periodic_recovery_sweep(result["manager"].store),
                name="mission-recovery-resweep",
            )

            # Missions parked in WAITING_CAPACITY resume from their checkpoint
            # once their own subscription has capacity again — never on another
            # provider or a paid key (dodaios/missions/capacity.py). Primary
            # instance only, like the sweep: two instances must not both
            # resume one mission.
            from dodaios.missions.capacity import capacity_resume_loop

            self._missions_resume_task = asyncio.create_task(
                capacity_resume_loop(result["kontrollierer"].resume_waiting_missions),
                name="mission-capacity-resume",
            )

    async def _init_task_stack(self) -> None:
        """Phase-5 task-queue wiring (BUG-007).

        Builds the TaskStore + TaskRunner + TaskScheduler, runs the
        startup cleanup for ``running`` tasks (app exit), and starts
        the scheduler loop as a background task.

        The runner is wired with the brain so agentic (``agent``) tasks run a
        tool-restricted turn unattended (read-only/monitor-tier plugins pass;
        ask-tier still gates). ``speak``/``harness_dispatch`` actions still
        have no TTS/harness here — those remain follow-up wiring. The UI is
        live regardless (list + cancel + detail timeline) since the routes
        only touch store + scheduler.
        """
        from dodaios.control.cancel import CancelToken
        from dodaios.tasks.approval_bridge import TaskAutoApprover
        from dodaios.tasks.runner import TaskRunner
        from dodaios.tasks.scheduler import TaskScheduler
        from dodaios.tasks.store import TaskStore

        data_dir = Path(self.cfg.memory.data_dir)
        # Startup wiring runs before this stack accepts work.
        data_dir.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240
        # Tasks share the DB with memory (ADR-0003) — an additive schema.
        db_path = data_dir / "jarvis.db"

        store = TaskStore(db_path)
        await store.init()

        # Crash recovery: all running -> interrupted, plus an error log entry.
        recovered = await store.cleanup_interrupted()
        if recovered:
            logger.info(
                "TaskStack: cleaned up {} interrupted tasks from the previous run",
                recovered,
            )
        retired = await store.retire_catalogue_tasks()
        if retired:
            logger.info(
                "TaskStack: cancelled {} schedules from the retired automations catalogue",
                retired,
            )

        # Wire the brain so agentic (`agent`) tasks can run a tool-restricted
        # turn unattended. app.state.brain is set before server.start() (see
        # launcher.py); a headless Mock-Brain without run_task falls back to
        # None → agent tasks fail cleanly instead of crashing.
        brain = getattr(self.app.state, "brain", None)
        agent_brain = brain if (brain is not None and hasattr(brain, "run_task")) else None
        # Unattended pre-authorization: agent tasks whose plugins were toggled
        # write/full auto-approve those ask-tier calls for their own turn.
        auto_approver = TaskAutoApprover(self.bus)

        # Harness dispatch (deep-dive 2026-07-15, H-02): the UI offers
        # scheduled Computer-Use actions (taskSpec.ts thenKind "computer_use"
        # -> harness_dispatch), but this runner shipped without a
        # HarnessManager, so every such task failed at runtime with
        # "HarnessManager not configured". The manager is cheap to construct
        # (entry-point class scan; instances build lazily on first dispatch).
        from dodaios.harness.manager import HarnessManager

        def workflow_services():
            return (
                getattr(self.app.state, "workflow_store", None),
                getattr(self.app.state, "workflow_runner", None),
            )

        runner = TaskRunner(
            store=store,
            bus=self.bus,
            harness_manager=HarnessManager(bus=self.bus),
            agent_brain=agent_brain,
            auto_approver=auto_approver,
            result_sink=self._society_routine_result,
            owned_agent_runner=self._run_society_routine,
            owned_action_guard=self._guard_society_routine_action,
            workflow_services=workflow_services,
        )
        scheduler = TaskScheduler(
            store=store, bus=self.bus, runner=runner, workflow_services=workflow_services,
        )
        scheduler.attach_owner_gate(self._society_owner_retired)
        scheduler.bind_bus()
        await scheduler.hydrate()

        cancel_token = CancelToken()
        scheduler_task = asyncio.create_task(
            scheduler.run(cancel_token), name="task-scheduler-loop"
        )

        self._task_store = store
        self._task_runner = runner
        self._task_scheduler = scheduler
        self._task_cancel_token = cancel_token
        self._task_scheduler_task = scheduler_task

        # Routes read from app.state — see tasks_routes.py:28
        self.app.state.task_store = store
        self.app.state.task_scheduler = scheduler
        self.app.state.task_runner = runner

        logger.info(
            "TaskStack live (db={}, recovered={}, hydrated={} scheduled)",
            db_path,
            recovered,
            len(scheduler._heap),
        )

    def _read_sessions_toml_section(self) -> dict:
        """The raw ``[sessions]`` section from the config file (may be empty).

        That section is NOT in the Pydantic tree (see assumption A-2 in the
        Phase-7 bootstrap), hence tomllib directly.
        """
        toml_path = resolve_config_path()
        if not toml_path.exists():
            return {}
        try:
            import tomllib

            with toml_path.open("rb") as fh:
                raw = tomllib.load(fh)
            return raw.get("sessions", {}) or {}
        except Exception as exc:  # noqa: BLE001
            logger.opt(exception=exc).warning(
                "Could not read the [sessions] section from jarvis.toml — using defaults"
            )
            return {}

    def _resolve_sessions_db_path(self) -> Path:
        """Absolute path to sessions.db, shared by recorder and board.

        The default lives in ``cfg.memory.data_dir`` itself — the directory
        every other SQLite store of this app uses (chats, missions, friends) —
        so a second instance of the app (``dodaios.core.instance``, which points
        ``memory.data_dir`` at ``data-dev/``) keeps its sessions apart from the
        default app's. An explicit relative ``[sessions].db_path`` is anchored
        at the data-dir parent (the repo root, as before), an absolute one is
        taken as is; neither depends on the process CWD. The shipped default
        string ``"data/sessions.db"`` (present in every jarvis.toml) IS the
        default and follows the data dir like an absent key.
        """
        section = self._read_sessions_toml_section()
        raw = section.get("db_path")
        if not raw or Path(str(raw)) == Path("data/sessions.db"):
            return Path(self.cfg.memory.data_dir) / "sessions.db"
        db_path = Path(str(raw))
        if not db_path.is_absolute():
            db_path = Path(self.cfg.memory.data_dir).parent / db_path
        return db_path

    def _init_session_stack(self) -> None:
        """Voice-session recorder + store for the transcription view.

        Bootstrap analogous to ``_init_mission_stack``, but sync — the store
        uses sqlite3 + threading.Lock (see ``dodaios/sessions/store.py``).
        """
        from dodaios.sessions.init import bootstrap_sessions

        # Defaults match jarvis.toml [sessions] (enabled=true,
        # data/sessions.db, retention 30d). User can override via TOML.
        section = self._read_sessions_toml_section()
        enabled = bool(section.get("enabled", True))
        try:
            retention_days = int(section.get("retention_days", 30))
        except (TypeError, ValueError):
            retention_days = 30

        if not enabled:
            logger.info("Voice-session recorder disabled via [sessions].enabled=false")
            return

        db_path = self._resolve_sessions_db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)

        result = bootstrap_sessions(
            bus=self.bus,
            db_path=db_path,
            enabled=True,
            retention_days=retention_days,
        )
        self.app.state.session_store = result["store"]
        self._session_recorder = result["recorder"]
        logger.info("Session recorder online (db={}, retention={}d)", db_path, retention_days)
        # Spoken turns also appear in the Jarvis agent chat (Voice | Chat):
        # the mirror files each completed voice turn into the newest
        # jarvis-surface session without answering it. Best-effort — the
        # voice path stays untouched when the chat is unavailable.
        try:
            from dodaios.agent_chat.voice_mirror import VoiceChatMirror

            from ..agent_chat_routes import _service_from_state

            state = self.app.state

            def _mirror_service() -> Any:
                try:
                    return _service_from_state(state)
                except Exception:  # noqa: BLE001 — mirroring stays best-effort
                    return None

            self._voice_chat_mirror = VoiceChatMirror(_mirror_service)
            self._voice_chat_mirror.attach(self.bus)
        except Exception as exc:  # noqa: BLE001 — never break boot for the mirror
            logger.debug("Voice chat mirror init failed: {}", exc)

    async def _init_channel_stack(self) -> None:
        """Bootstraps FriendRegistry + ChannelManager + starts all channels.

        The Friends UI works even without Telegram (FriendRegistry is always
        there). TelegramChannel lands in ``start_errors`` when the token is
        missing, without blocking the other channels.
        """
        from dodaios.channels.bootstrap import bootstrap_channels
        from dodaios.channels.chat_bridge import ChannelChatBridge

        # data_dir might not exist on every branch under cfg.memory;
        # fall back to ./data so the code stays branch-portable.
        data_dir = Path("data")
        try:
            mem_dir = getattr(self.cfg, "memory", None)
            if mem_dir is not None and getattr(mem_dir, "data_dir", None):
                data_dir = Path(mem_dir.data_dir)
        except Exception:  # noqa: BLE001, S110 — portable data-dir fallback
            pass
        data_dir.mkdir(parents=True, exist_ok=True)
        friends_db = data_dir / "friends.db"

        # Telegram/Discord configs from integrations.* (branch-portable via getattr)
        tg_cfg = None
        dc_cfg = None
        sl_cfg = None
        integrations = getattr(self.cfg, "integrations", None)
        from dodaios.core.instance import current_instance

        if not current_instance().owns_ambient_duties:
            # A second (dev) instance of the app must not poll the same bot
            # tokens as the live one — Telegram answers a second getUpdates
            # poller with 409 and both would answer the user's friends. The
            # Friends registry still comes up; only the channels stay off.
            logger.info(
                "Friends-Stack: chat channels stay off in instance '{}' "
                "(they belong to the default app)",
                current_instance().name,
            )
        elif integrations is not None:
            tg_cfg = getattr(integrations, "telegram", None)
            dc_cfg = getattr(integrations, "discord", None)
            sl_cfg = getattr(integrations, "slack", None)

        manager, registry = await bootstrap_channels(
            bus=self.bus,
            telegram_config=tg_cfg,
            discord_config=dc_cfg,
            slack_config=sl_cfg,
            friends_db_path=friends_db,
            auto_start=True,
        )
        self.app.state.friend_registry = registry
        self.app.state.channel_manager = manager
        from ..agent_chat_routes import _service_from_state

        app_state = self.app.state

        def _lead_chat_service() -> Any:
            try:
                return _service_from_state(app_state)
            except Exception:  # noqa: BLE001 — the classic chat path stays
                return None

        bridge = ChannelChatBridge(
            bus=self.bus,
            manager=manager,
            get_chat_service=_lead_chat_service,
            get_scheduler=lambda: getattr(app_state, "task_scheduler", None),
        )
        bridge.start()
        self._channel_chat_bridge = bridge
        try:
            # Push to the paired phone: needs-you cards and lead notices.
            from dodaios.mobile.notify import install as install_mobile_push

            install_mobile_push(self.bus, config=self.cfg)
        except Exception as exc:  # noqa: BLE001 — a phone push problem never breaks boot
            logger.debug("Mobile push notifier init failed: {}", exc)
        self.app.state.channel_chat_bridge = bridge

        # A channel that a background retry starts later (no network yet at
        # login) gets its chat-bridge consumer through the manager's late-start
        # listener the bridge registered; the panel and the approval buttons
        # read the manager live.
        if "telegram" in manager.started():
            logger.info("Friends-Stack live: Telegram channel active")
        else:
            errs = manager.start_errors().get("telegram")
            if errs and "telegram" in manager.retrying():
                logger.info(
                    "Friends-Stack live: Telegram channel not started yet ({}); "
                    "trying again in the background",
                    errs,
                )
            elif errs:
                logger.info("Friends-Stack live: Telegram-Channel disabled ({})", errs)
            else:
                logger.info("Friends-Stack live: Telegram-Channel disabled (config off)")
        if "slack" in manager.started() and getattr(manager.get("slack"), "active", False):
            logger.info("Friends-Stack live: Slack channel active")
        elif manager.start_errors().get("slack"):
            logger.info(
                "Friends-Stack live: Slack channel not running ({}){}",
                manager.start_errors()["slack"],
                "; trying again in the background" if "slack" in manager.retrying() else "",
            )

    async def _society_routine_result(
        self,
        tags: tuple[str, ...],
        text: str,
        status: str,
        *,
        details: dict[str, str] | None = None,
    ) -> None:
        """A routine tagged ``agent:<id>`` reports its result into that agent's
        own chat (the ecosystem card promises it). Tasks never import the
        society; this is the one seam. Every failure is logged, never raised
        into the task. ``details`` (a skipped run's ``reason_code``,
        ``provider`` and ``routine``) ride along on the notice so the chat
        words the reason in the reader's language."""
        from dodaios.society.routines import agent_id_from_tags
        from dodaios.society.runtime import current_runtime

        agent_id = agent_id_from_tags(tags)
        if agent_id is None:
            return
        try:
            runtime = current_runtime()
            if runtime is None:
                factory = getattr(self.app.state, "society_factory", None)
                if factory is None:
                    return
                runtime = self.app.state.society or factory()
                self.app.state.society = runtime
                await runtime.ensure_started()
            agent = await runtime.roster.get(agent_id)
            if agent is None:
                logger.info("routine result for unknown society agent {}", agent_id)
                return
            await runtime.post_chat_notice(
                agent,
                {
                    "kind": "society_result",
                    "status": status,
                    "text": text[:4000],
                    "agent_id": agent.agent_id,
                    "agent_name": agent.name,
                    "source": "routine",
                    **{key: str(value)[:200] for key, value in (details or {}).items()},
                },
            )
        except Exception:  # noqa: BLE001 — the task already recorded its result; delivery is best effort
            logger.warning("society: routine result not delivered to {}", agent_id, exc_info=True)

    async def _society_owner_retired(self, tags: tuple[str, ...]) -> bool:
        """Whether a task belongs to a retired (archived) society agent."""
        from dodaios.society.routines import agent_id_from_tags
        from dodaios.society.runtime import current_runtime

        agent_id = agent_id_from_tags(tags)
        if agent_id is None:
            return False
        runtime = current_runtime()
        if runtime is None:
            runtime = self._build_society_runtime()
            self.app.state.society = runtime
            await runtime.ensure_started()
        agent = await runtime.roster.get(agent_id)
        return agent is not None and str(agent.state) == "archived"

    async def _guard_society_routine_action(self, tags: tuple[str, ...]) -> None:
        from dodaios.society.routine_runner import guard_owned_routine
        from dodaios.society.runtime import current_runtime

        runtime = current_runtime()
        if runtime is None:
            runtime = self._build_society_runtime()
            self.app.state.society = runtime
            await runtime.ensure_started()
        await guard_owned_routine(runtime, tags)

    async def _run_society_routine(
        self, task_id: str, tags: tuple[str, ...], prompt: str, cancel: Any
    ) -> str | None:
        from dodaios.society.routine_runner import run_owned_routine
        from dodaios.society.routines import agent_id_from_tags
        from dodaios.society.runtime import current_runtime

        if agent_id_from_tags(tags) is None:
            return None
        runtime = current_runtime()
        if runtime is None:
            runtime = self._build_society_runtime()
            self.app.state.society = runtime
            await runtime.ensure_started()
        return await run_owned_routine(runtime, task_id, tags, prompt, cancel)

    def _build_society_runtime(self) -> Any:
        """Build the agent-society runtime on first use (see society_routes).

        Every collaborator is a getter over ``app.state`` so the runtime
        follows the live mission manager, budget tracker, brain tool surface
        and skill registry — whichever of them exists at call time.
        """
        from dodaios.society.runtime import SocietyRuntime, SocietyRuntimeClosed

        state = self.app.state
        if getattr(state, "society_stopping", False):
            raise SocietyRuntimeClosed("society runtime stopped")
        data_dir = Path(getattr(getattr(self.cfg, "memory", None), "data_dir", None) or "data")

        if getattr(state, "society", None) is not None:
            return state.society

        def _manager() -> Any | None:
            return getattr(state, "mission_manager", None)

        def _mission_bus() -> Any | None:
            manager = getattr(state, "mission_manager", None)
            return getattr(manager, "bus", None) if manager is not None else None

        def _budget() -> Any | None:
            return getattr(state, "missions_budget", None)

        def _tools() -> Any | None:
            brain = getattr(state, "brain", None)
            if brain is not None:
                from dodaios.brain.tool_surface import maybe_reconcile_tool_surface

                maybe_reconcile_tool_surface(brain)
            tools = getattr(brain, "_tools", None)
            if tools is None:
                tools = getattr(state, "tool_registry", None)
            return tools if tools is not None and hasattr(tools, "items") else None

        def _skills() -> Any | None:
            registry = getattr(state, "skill_registry", None)
            if registry is None:
                return None
            lister = getattr(registry, "all", None) or getattr(registry, "list", None)
            try:
                return list(lister()) if callable(lister) else None
            except Exception:  # noqa: BLE001 — the catalog then shows no skills
                return None

        from dodaios.society.chat_binding import make_deliver_hook

        from ..agent_chat_routes import _service_from_state

        # Board messages addressed to an agent wake its canonical chat on the
        # agent-chat service (built lazily by its own factory).
        deliver = make_deliver_hook(
            lambda: _service_from_state(state),
            lambda: self.cfg,
        )
        def _society_plugin_state() -> tuple[list[str], set[str]]:
            from dodaios.marketplace.catalog_data import load_catalog
            from dodaios.marketplace.connect_helpers import usable_plugin_ids

            return [spec.id for spec in load_catalog().plugins], usable_plugin_ids()

        state.society = SocietyRuntime(
            data_dir,
            mission_manager=_manager,
            mission_bus=_mission_bus,
            budget_tracker=_budget,
            brain_tools=_tools,
            skills=_skills,
            deliver=deliver,
            chat_service=lambda: _service_from_state(state),
            cfg=lambda: self.cfg,
            # The island learns of a figure's new place through the app bus the
            # WebSocket forwards (SocietyCheckpointChanged).
            plugin_state=_society_plugin_state,
            event_publish=self.bus.publish,
            app_bus=self.bus,
            task_services=lambda: (
                getattr(state, "task_store", None), getattr(state, "task_scheduler", None)
            ),
        )
        def browser_brain(agent: Any) -> Any:
            from dodaios.agent_chat.browser_model import browser_model_for_agent

            return browser_model_for_agent(self.cfg, agent)

        state.society.browser.live.model_resolver = browser_brain
        state.society.browser.live.executor = lambda: getattr(
            getattr(state, "brain", None), "_tool_executor", None
        )
        return state.society

    def _build_agent_chat_service(self) -> Any:
        """Build the agent-chat service on first use (see agent_chat_routes)."""
        from dodaios.agent_chat.service import AgentChatService, remember_app_loop
        from dodaios.agent_chat.store import AgentChatStore
        from dodaios.brain.assistant_name import DEFAULT_ASSISTANT_NAME, resolve_assistant_name

        # Every builder comes through here (routes, the voice mirror, the
        # channel bridge, the agents' MCP tools), from any kind of thread.
        # Handing the loop over asks nothing, so it is safe under their lock.
        app_loop = getattr(self.app.state, "app_loop", None)
        if app_loop is not None:
            remember_app_loop(app_loop)
        data_dir = Path(getattr(getattr(self.cfg, "memory", None), "data_dir", None) or "data")
        store = AgentChatStore(data_dir / "agent_chat.db")

        def _name() -> str:
            try:
                return resolve_assistant_name(self.cfg)
            except Exception:  # noqa: BLE001 — the name is cosmetic
                return DEFAULT_ASSISTANT_NAME

        from dodaios.core.events import DelegationResultReady

        # Install on first chat use, keeping result tracking off the boot path.
        self.bus.unsubscribe(DelegationResultReady, self._forward_delegation_to_chat)
        self.bus.subscribe(DelegationResultReady, self._forward_delegation_to_chat)
        service = AgentChatService(store, assistant_name=_name, bus=lambda: self.bus)
        # Messages and delegation waits a restart interrupted go on from here.
        service.start_restart_recovery()
        # The record and verdicts of delegated coding runs: one event listener,
        # always on; it holds nothing unless a run's coding policy says so.
        from dodaios.orchestrator.verification.recorder import install as install_run_recorder

        install_run_recorder(
            service, data_dir, self.cfg,
            self_change=lambda: getattr(self.app.state, "self_change", None),
        )
        # The lead's repository index, only while ``[rsi] repo_index`` is set.
        from dodaios.rsi.repo_cards import install as install_repo_board

        install_repo_board(service, self.cfg)
        # How briefs for coding agents are checked and followed: the ``[briefs]`` switches.
        from dodaios.briefs import settings as brief_settings

        brief_settings.configure(self.cfg)
        # "Needs you" list and notifier: one event listener, nothing on boot.
        from dodaios.agent_chat.attention import install as install_attention

        install_attention(
            service,
            publish=self.bus.publish,
            society=lambda: getattr(self.app.state, "society", None),
        )
        # Waiting approvals also reach the owner's Telegram (dodaios/notify).
        try:
            from dodaios.notify import wiring as notify_wiring

            notify_wiring.attach_chat_service(service, app_state=self.app.state, cfg=self.cfg)
        except Exception as exc:  # noqa: BLE001 — the chat works without Telegram buttons
            logger.opt(exception=exc).warning("notify: Telegram approvals not attached")
        return service
