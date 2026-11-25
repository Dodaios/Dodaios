"""App assembly: the route graph hand-off and the registries mounted on the app."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI
from loguru import logger

if TYPE_CHECKING:
    pass

from ._srv import server_module

if TYPE_CHECKING:
    from dodaios.ui.web.server_parts._host_state import WebServerHostState as _HostBase
else:
    _HostBase = object


class AppSetupMixin(_HostBase):
    """App assembly: the route graph hand-off and the registries mounted on the app."""

    def _finish_app_setup(self, app: FastAPI) -> None:
        """Install optional surfaces before any consumer receives this app.

        Desktop defers this work behind local voice warmup. Headless and other
        callers retain eager construction. The shared bus, skill registry and
        voice-status subscriber already exist before this method runs.
        """
        # Sub-agent registry (dashboard feature) — subscribes to the bus immediately.
        try:
            from dodaios.agents import JarvisAgentRegistry

            sub_agent_registry = JarvisAgentRegistry(bus=self.bus)
            sub_agent_registry.attach()
            app.state.sub_agent_registry = sub_agent_registry
        except Exception as exc:  # noqa: BLE001
            logger.opt(exception=exc).warning("JarvisAgentRegistry setup failed")
            app.state.sub_agent_registry = None

        # Wire in the MCP, tool, provider, profile, task, skills, CLI, and
        # sub-agents routes — lazy import avoids cycles.
        from dodaios.runs.routes import router as runs_router
        from dodaios.runs.runs_ws import router as runs_ws_router

        from ..agent_accounts_routes import router as agent_accounts_router
        from ..agent_chat_routes import router as agent_chat_router
        from ..agent_mcp_routes import router as agent_mcp_router
        from ..agent_runtime_routes import router as agent_runtime_router
        from ..agentic_ide_git_routes import router as agentic_ide_git_router
        from ..agentic_ide_resources_routes import router as agentic_ide_resources_router
        from ..agentic_ide_routes import router as agentic_ide_router
        from ..agentic_ide_scm_routes import router as agentic_ide_scm_router
        from ..antigravity_routes import router as antigravity_router
        from ..app_actions_routes import router as app_actions_router
        from ..appshot_routes import router as appshot_router
        from ..attention_routes import router as attention_router
        from ..board_routes import (
            board_router as board_meta_router,
        )
        from ..board_routes import (
            router as board_router,
        )
        from ..browser_profile_routes import router as browser_profile_router
        from ..chat_library_routes import router as chat_library_router
        from ..chats_routes import router as chats_router
        from ..claude_routes import router as claude_router
        from ..cli_routes import router as cli_router
        from ..clip_routes import router as clip_router
        from ..clipboard_routes import router as clipboard_router
        from ..commands_routes import router as commands_router
        from ..computer_use_routes import router as computer_use_router
        from ..computers_routes import router as computers_router
        from ..contacts_routes import router as contacts_router
        from ..control_routes import router as control_router
        from ..costs_routes import router as costs_router
        from ..custom_api_routes import router as custom_api_router
        from ..deck_routes import router as deck_router
        from ..designs_routes import router as designs_router
        from ..desktop_routes import router as desktop_router
        from ..diagnostics_routes import router as diagnostics_router
        from ..dictation_routes import router as dictation_router
        from ..dictionary_routes import router as dictionary_router
        from ..docs_routes import router as docs_router
        from ..dodaiosx_routes import router as jarvisx_router
        from ..downloads_routes import router as downloads_router
        from ..drop_routes import router as drop_router
        from ..federation_proxy_routes import router as federation_proxy_router
        from ..feedback_routes import router as feedback_router
        from ..friends_routes import router as friends_router
        from ..frontier_routes import router as frontier_router
        from ..grok_build_routes import router as grok_build_router
        from ..ide_browser_routes import router as ide_browser_router
        from ..ide_skills_routes import router as ide_skills_router
        from ..link_icon_routes import router as link_icon_router
        from ..live_routes import router as live_router
        from ..living_pages_routes import router as living_pages_router
        from ..local_models_assistant_routes import (
            router as local_models_assistant_router,
        )
        from ..local_models_routes import router as local_models_router
        from ..local_voice_routes import router as local_voice_router
        from ..looks_routes import frame_router as looks_frame_router
        from ..looks_routes import router as looks_router
        from ..marketplace_publish_routes import router as marketplace_publish_router
        from ..marketplace_routes import router as marketplace_router
        from ..mcp_routes import router as mcp_router
        from ..mission_billing_routes import router as mission_billing_router
        from ..missions_auth import router as missions_auth_router
        from ..missions_pty_routes import router as missions_pty_router
        from ..missions_routes import router as missions_router
        from ..missions_ws_routes import (
            ConnectionManager as _MissionsConnMgr,
        )
        from ..missions_ws_routes import (
            router as missions_ws_router,
        )
        from ..mobile_routes import router as mobile_router
        from ..nodes_routes import router as nodes_router
        from ..notify_routes import router as notify_router
        from ..onboarding_routes import router as onboarding_router
        from ..outputs_routes import router as outputs_router
        from ..permissions_routes import router as permissions_router
        from ..personal_memory_routes import router as personal_memory_router
        from ..pets_routes import router as pets_router
        from ..preview_routes import router as preview_router
        from ..profile_routes import router as profile_router
        from ..project_routes import router as project_router
        from ..provider_routes import router as provider_router
        from ..review_routes import router as review_router
        from ..ritual_routes import router as ritual_router
        from ..routine_hooks_routes import router as routine_hooks_router
        from ..runtime_gateway_routes import router as runtime_gateway_router
        from ..screen_context_routes import router as screen_context_router
        from ..self_build_routes import router as self_build_router
        from ..self_change_routes import router as self_change_router
        from ..self_improvement_routes import router as self_improvement_router
        from ..self_mod_routes import router as self_mod_router
        from ..server_pairing_routes import router as server_pairing_router
        from ..sessions_routes import router as sessions_router
        from ..settings_routes import router as settings_router
        from ..setup_report_routes import router as setup_report_router
        from ..skills_routes import router as skills_router
        from ..slack_channel_routes import router as slack_channel_router
        from ..socials_routes import router as socials_router
        from ..society_browser_routes import router as society_browser_router
        from ..society_figure_routes import router as society_figure_router
        from ..society_routes import router as society_router
        from ..soul_routes import router as soul_router
        from ..starter_plan_routes import router as starter_plan_router
        from ..status_light_routes import router as status_light_router
        from ..sub_agents_routes import router as sub_agents_router
        from ..tasks_routes import router as tasks_router
        from ..team_thread_routes import router as team_thread_router
        from ..telephony_routes import router as telephony_router
        from ..tool_model_routes import router as tool_model_router
        from ..tools_routes import router as tools_router
        from ..traces_routes import router as traces_router
        from ..trust_routes import router as trust_router
        from ..update_routes import router as update_router
        from ..voice_call_routes import router as voice_call_router
        from ..wallpaper_routes import router as wallpaper_router
        from ..workflows_routes import router as workflows_router
        from ..workspace_clis_routes import router as workspace_clis_router
        from ..workspace_routes import router as workspace_router

        # Conductor is an external package in the same monorepo. Import
        # defensively — anyone who checks out the repo without conductor would
        # otherwise get an ImportError here at server boot.
        try:
            from conductor.api import router as conductor_router
        except ImportError as exc:
            logger.warning("Conductor module not available: {} — Conductor view stays empty", exc)
            conductor_router = None
        app.include_router(mcp_router)
        # Connect-flow for the Agent MCP surface: what it offers, which
        # clients this box has, and writing the entry into their config.
        app.include_router(agent_mcp_router)
        app.include_router(tools_router)
        app.include_router(tool_model_router)
        # Jarvis' OWN tools, offered outwards over MCP so an agent-chat session
        # drives Jarvis instead of a bare workspace. Key-gated like the rest of
        # the Control API; mounted raw because the transport streams.
        from dodaios.ui.web.mcp_server_routes import build_mcp_asgi_app

        # ONE mount, two surfaces, dispatched inside on the rest of the path:
        # "" is Jarvis' own tools, "/agents" is the agent ecosystem. A second
        # Starlette mount on the longer path would never match a request
        # without a trailing slash — see mcp_server_routes._surface_for.
        app.mount("/api/control/mcp", build_mcp_asgi_app())
        # Event-loop diagnostics (read-only) — names the owner of an AP-20
        # cancellation busy-loop from inside the loop; see diagnostics_routes.
        app.include_router(diagnostics_router)
        app.include_router(provider_router)
        # Local voice card (setup, status, self-test) — ADR-0037.
        app.include_router(local_voice_router)
        app.include_router(live_router)
        from dodaios.agent_chat.tasks import run_subscription_task
        from dodaios.core.task_agent import register_runner

        register_runner(run_subscription_task)
        # Local models section: inventory / unload / delete behind the
        # pull-capable card (same capability gate as the pull routes).
        app.include_router(local_models_router)
        # The section's setup assistant — same capability gate, its own chat
        # surface on the Agents tier.
        app.include_router(local_models_assistant_router)
        app.include_router(antigravity_router)
        app.include_router(claude_router)
        app.include_router(grok_build_router)
        # Several subscriptions per coding CLI, switchable without a logout.
        app.include_router(agent_accounts_router)
        app.include_router(control_router)
        # Native window chrome and the editor tool windows; headless hosts
        # answer honestly with a fallback URL.
        app.include_router(desktop_router)
        # The picture behind the tiled section layout.
        app.include_router(wallpaper_router)
        app.include_router(ide_browser_router)
        app.include_router(profile_router)
        app.include_router(settings_router)
        app.include_router(soul_router)
        app.include_router(permissions_router)
        # In-app updater (GET status / POST apply). Managed-install only — see
        # dodaios/ui/web/update_routes.py; refuses to self-reset a dev checkout.
        app.include_router(update_router)
        # Share-safe cross-device setup report (read-only) — names why THIS
        # install behaves differently from another device (triage).
        app.include_router(setup_report_router)
        # Starter plans + the one-time "all set" readiness note.
        app.include_router(starter_plan_router)
        # Frontier auto-switch modal API (GET pending / POST ack) + Self-Mod
        # read/restore API. Both were the last route modules left unmounted; the
        # 404 on /api/frontier/pending silently broke the desktop auto-switch
        # modal too, not just the `jarvis frontier` CLI command.
        app.include_router(frontier_router)
        app.include_router(self_mod_router)
        app.include_router(routine_hooks_router)
        app.include_router(tasks_router)
        app.include_router(skills_router)
        app.include_router(docs_router)
        app.include_router(cli_router)
        # Spend & Tokens — a read model over sessions/missions/agent-chat.
        app.include_router(costs_router)
        # Causal trace tree: lead turn -> assignment -> agent turn -> job.
        app.include_router(traces_router)
        # Command Registry — the one machine-readable catalog of app commands
        # (consumed by the app-command brain tool, the UI, CLI, and docs gen).
        app.include_router(commands_router)
        app.include_router(friends_router)
        app.include_router(marketplace_router)
        app.include_router(custom_api_router)
        app.include_router(marketplace_publish_router)
        app.state.friend_registry = None
        app.state.channel_manager = None
        app.state.channel_chat_bridge = None
        # Twilio telephony voice agent (webhook + media WS + REST status/config).
        # Degrades gracefully when the `twilio` extra is not installed (AD-T8).
        app.include_router(telephony_router)
        from dodaios.telephony.status import TelephonyManager

        app.state.telephony_manager = TelephonyManager()
        # Browser-microphone voice bridge (B2): /ws/audio — the headless/VPS
        # voice path via the browser's own mic/speaker, no sounddevice. Always
        # mounted; every call on it runs on a realtime voice session.
        from dodaios.browser_voice.route import router as browser_voice_router

        app.include_router(browser_voice_router)
        app.include_router(sub_agents_router)
        app.include_router(outputs_router)
        app.include_router(downloads_router)
        app.include_router(clipboard_router)
        # The logo in front of a web link in a chat answer.
        app.include_router(link_icon_router)
        # Socials section — project social-media links (pure file store, no Brain dep).
        app.include_router(socials_router)
        # In-app feedback / bug-report form → Discord webhook.
        app.include_router(feedback_router)
        # "Make It Yours" multi-agent workspace (/api/workspace/*).
        # Provides agent detection, workspace launch planning, and PTY WebSocket
        # for in-app Claude Code / Codex terminals (xterm panes, not OS windows).
        app.include_router(workspace_router)
        app.include_router(workspace_clis_router)
        # Agentic IDE (/api/agentic-ide/*) — a chosen folder plus named terminals
        # running Claude Code / Codex, addressable by voice ("what is Mika
        # doing?") and promptable from Jarvis. Reuses the same PTY stack as the
        # workspace above; adds the folder picker, call-signs, transcripts, and
        # the focused coding mode.
        # Before the IDE router, so its /{…} paths never shadow /git/….
        app.include_router(agentic_ide_scm_router)
        app.include_router(agentic_ide_git_router)
        app.include_router(agentic_ide_resources_router)
        app.state.team_threads = None
        app.include_router(team_thread_router)
        app.include_router(project_router)
        # "Built for you": the self-building ledger (/api/self-build/*).
        app.state.self_build = None
        app.include_router(self_build_router)
        # The self-change registry (/api/self-change/*): gated, versioned, reversible.
        app.state.self_change = None
        app.include_router(self_change_router)
        # The Self-improvement page (/api/self-improvement/*): measured, read-only, stop and undo.
        app.state.self_improvement = None
        app.include_router(self_improvement_router)
        # The Skills tab's library of saved Markdown prompts (/api/agentic-ide/skills/*).
        app.include_router(ide_skills_router)
        app.include_router(agentic_ide_router)
        # The pane-activity sweep has no bus of its own (the registry is a plain
        # holder by design); this is the one place that holds one, so the sweep
        # is told where a changed reading goes. A reference, not work — nothing
        # runs until a workspace is opened (AP-26).
        from dodaios.agentic_ide import notifications as ide_notifications

        ide_notifications.set_publisher(self.bus.publish)
        # The project/chat library behind the chat surface's sidebar. Pure file
        # store, no Brain and no session dependency — it lists on a fresh
        # install with no keys and answers headless.
        app.include_router(chat_library_router)
        # Contacts section — user-curated address book (pure file store, no Brain dep).
        app.include_router(contacts_router)
        # Settings -> Computers: the user's own servers and local VMs over SSH.
        app.include_router(server_pairing_router)
        app.include_router(computers_router)
        # Settings -> Phone: the paired phone's companion app and its pushes.
        app.include_router(mobile_router)
        # Desktop pets — the `pet` overlay style's pets, look and visibility.
        app.include_router(pets_router)
        # Looks — in-app visuals in the orb's place, and their sandboxed frame files.
        app.include_router(looks_router)
        app.include_router(designs_router)
        app.include_router(looks_frame_router)
        app.include_router(dictionary_router)
        # Dictation mode — hold to speak, text lands in the focused field.
        # Mounted so every action is also `jarvis api dictation <op>`, which is
        # the documented Wayland path (no app-owned global shortcuts there).
        app.include_router(dictation_router)
        # The voice orb's click — call / hangup without speaking the wake word.
        app.include_router(voice_call_router)
        app.include_router(workflows_router)
        if conductor_router is not None:
            app.include_router(conductor_router)
        app.include_router(preview_router)
        app.include_router(board_router)
        app.include_router(board_meta_router)
        app.include_router(federation_proxy_router)
        # Phase 8.5 — review-pipeline read-only UI (Plan §6.5).
        app.include_router(review_router)
        # One-shot, intent-driven screen look. Answers honestly (not 503) on a
        # machine with no display, so `jarvis api screen-context status` is a
        # valid capability probe everywhere.
        app.include_router(screen_context_router)
        # Appshots: the front window as conversation context, on a shortcut,
        # a button or a spoken request. Captures through Screen Context.
        app.include_router(app_actions_router)
        app.include_router(appshot_router)
        app.include_router(jarvisx_router)
        # The mission deck's pictures: the last Screen-Context capture (one
        # frame, in memory, TTL) and Computer-Use frames by content hash.
        app.include_router(deck_router)
        # Voice-session transcription view (sidebar -> "Transcription").
        # Returns 503 as long as app.state.session_store isn't set.
        app.include_router(sessions_router)
        # Run Inspector — forensic lens over the same voice sessions. Read-only;
        # 503 until app.state.session_store is set, like sessions_router.
        app.include_router(runs_router)
        app.include_router(runs_ws_router)
        # Chats conversation manager — unified text+voice history, resume +
        # "Speak in this conversation". Reuses chat_store + session_store +
        # brain + speech_pipeline from app.state (graceful 503s when absent).
        app.include_router(chats_router)
        # Agent chat — the typed front-page chat as an agent session on the
        # agent-tier providers (dodaios/agent_chat). The service is built on
        # first use by the routes (store = data/agent_chat.db) so nothing
        # opens on the boot path (AP-26); stop() cancels running turns.
        app.state.agent_chat = None
        app.state.agent_chat_factory = self._build_agent_chat_service
        app.include_router(attention_router)
        app.include_router(status_light_router)
        app.include_router(agent_chat_router)
        # What a short phrase starts ("good morning"): the lead's rituals.
        app.include_router(ritual_router)
        from ..agent_server_routes import router as agent_server_router

        app.include_router(agent_server_router)
        # Agent society (dodaios/society) — the roster, the typed board, the
        # scheduler and the mission bridge. Built on the first /api/society
        # call from the factory (store = data/society.db); nothing opens on
        # the boot path (AP-26).
        app.state.society = None
        app.state.society_factory = self._build_society_runtime
        # The router-tier voice tools reach the same runtime through the
        # brain factory's lazy resolver (AD-OC1).
        from dodaios.brain.factory import set_society_factory

        set_society_factory(self._build_society_runtime)
        app.include_router(society_router)
        app.include_router(agent_runtime_router)
        app.include_router(runtime_gateway_router)
        app.include_router(society_browser_router)
        app.include_router(browser_profile_router)
        app.include_router(society_figure_router)
        app.include_router(drop_router)
        # Default: no recorder wired up — _init_session_stack() in start()
        # sets this once it succeeds.
        app.state.session_store = None
        # Phase-6 mission stack — token issuance is behind SurfaceSecurity;
        # mission WS and PTY then perform their narrower hello-frame auth too.
        app.include_router(missions_auth_router)
        app.include_router(missions_router)
        # Paid-API fallback switch for missions (Settings; never voice/agents).
        app.include_router(mission_billing_router)
        app.include_router(missions_ws_router)
        app.include_router(missions_pty_router)
        # Computer-Use run control (deep-dive 2026-07-15, H-09): start/list/
        # inspect/cancel desktop goals — auto-exposed as `jarvis api
        # computer-use <op>` by the dynamic CLI layer.
        app.include_router(computer_use_router)
        # First-time onboarding guide (/api/onboarding/*).
        app.include_router(onboarding_router)
        # Personal memory vault API (ADR-0044): items, history, export, import.
        app.include_router(personal_memory_router)
        # Living pages: pages the assistant keeps current (stop/resume refresh).
        app.include_router(living_pages_router)
        # Nodes: the library of typed nodes and everything older runs left behind.
        app.include_router(nodes_router)
        app.include_router(clip_router)
        # Reminders and desktop notifications (dodaios/notify).
        app.include_router(notify_router)
        # The owner's own Slack app as a conversation channel (dodaios/channels/slack.py).
        app.include_router(slack_channel_router)
        # Trust & privacy: standing rules, undo, the "what it knows" overview.
        app.include_router(trust_router)
        # ConnectionManager singleton for the global event stream. Attached
        # to MissionBus.subscribe_all() in start().
        app.state.missions_ws_manager = _MissionsConnMgr()
        # MissionManager + Kontrollierer are wired lazily in start()
        # (they need a running event loop for aiosqlite). Default is None,
        # so the REST routes return 503 instead of crashing.
        app.state.mission_manager = None
        app.state.kontrollierer = None
        app.state.mission_tool_approvals = self._mission_tool_approvals

        # Board aggregator (personal-mastery dashboard) — the aggregator is
        # run as a background task in start(); the store is read-only and
        # available immediately.
        self._setup_board(app)

        # Preview registry — subscribed to PreviewServerStarted/Closed events.
        try:
            from dodaios.preview.registry import PreviewRegistry

            preview_registry = PreviewRegistry(bus=self.bus)
            preview_registry.attach()
            app.state.preview_registry = preview_registry
        except Exception as exc:  # noqa: BLE001
            logger.opt(exception=exc).warning("PreviewRegistry setup failed")
            app.state.preview_registry = None

        # The SPA catch-all must remain after every API router.
        self._register_static_or_spa(app)

    def _setup_board(self, app: FastAPI) -> None:
        """Initialize the board store + aggregator + evaluator + BioGenerator.

        The store is read-only and ready immediately (creates an empty DB
        on the first query, so the UI mount doesn't hit a 500). The
        aggregator runs in ``start()`` as a background task; the evaluator
        and the BioScheduler subscribe to the bus there.
        """
        try:
            from dodaios.board.aggregator import BoardAggregator
            from dodaios.board.bio_brain import BIO_TIMEOUT_S, resolve_bio_brain
            from dodaios.board.evaluator import AchievementEvaluator
            from dodaios.board.insights import BoardInsights
            from dodaios.board.insights import default_sources as insight_sources
            from dodaios.board.profile import BioGenerator, BioStore
            from dodaios.board.scheduler import BioScheduler
            from dodaios.board.store import BoardStore
            from dodaios.core.paths import board_db_path, user_data_dir, user_logs_dir

            db_path = board_db_path()
            jsonl_dir = user_logs_dir()
            jsonl_dir.mkdir(parents=True, exist_ok=True)

            # The board's rich source is the durable voice-session store
            # (sessions.db), not the flight-recorder JSONL (which is empty on
            # most installs). Resolved exactly like bootstrap_sessions does —
            # a bare CWD-relative path would silently starve the board of its
            # source whenever the app starts from a different directory.
            sessions_db_path = self._resolve_sessions_db_path()

            aggregator = BoardAggregator(
                jsonl_dir=jsonl_dir,
                db_path=db_path,
                sessions_db_path=sessions_db_path,
            )
            store = BoardStore(db_path=db_path)
            insights = BoardInsights(
                insight_sources(
                    data_dir=Path(self.cfg.memory.data_dir),
                    sessions_db=sessions_db_path,
                    board_db=db_path,
                )
            )
            evaluator = AchievementEvaluator(db_path=db_path, bus=self.bus)
            bio_store = BioStore(db_path=db_path)

            # Optional data-source paths (missions, self-mod).
            # If the file/DB doesn't exist, the block just silently drops out
            # of the prompt — no error. Paths come from ``user_data_dir()``,
            # not relative strings, so an app restart in a different CWD
            # doesn't starve the generator of its data.
            data_root = user_data_dir() / "data"
            recall_db = data_root / "memory.db"
            missions_db = data_root / "missions.db"
            self_mod_log = data_root / "self_mod.log"

            bio_cfg = self.cfg.board.bio
            cfg = self.cfg

            def _bio_brain_resolver() -> Any:
                # Lazy: capture cfg + bus from the closure, so a later
                # provider switch via the UI takes effect immediately
                # (the resolver invalidates its cache via ConfigReloaded).
                # Background billing rule: subscription or local model once a
                # subscription is connected, never a per-token key.
                return resolve_bio_brain(cfg, bus=self.bus)

            bio_generator = BioGenerator(
                brain_resolver=_bio_brain_resolver,
                store=store,
                bio_store=bio_store,
                jsonl_dir=jsonl_dir,
                recall_db_path=recall_db,
                missions_db_path=missions_db,
                self_mod_log_path=self_mod_log,
                temperature=bio_cfg.temperature,
                max_tokens=bio_cfg.max_tokens,
                timeout_s=BIO_TIMEOUT_S,
                reply_language=lambda: self.cfg.brain.reply_language,
            )
            # Hook-driven: rewrites the bio on unlocked achievements, never on
            # a timer or at boot.
            scheduler = BioScheduler(
                generator=bio_generator,
                bio_store=bio_store,
                bus=self.bus,
            )

            self._board_aggregator = aggregator
            self._board_aggregator_task: asyncio.Task[None] | None = None
            self._board_evaluator = evaluator
            self._bio_scheduler = scheduler
            self._bio_generator = bio_generator
            app.state.board_aggregator = aggregator
            app.state.board_store = store
            app.state.board_insights = insights
            app.state.achievement_evaluator = evaluator
            app.state.bio_generator = bio_generator
            app.state.bio_store = bio_store
            logger.info(
                "Board ready (jsonl={}, db={}, achievements={})",
                jsonl_dir,
                db_path,
                len(evaluator.list_all()),
            )
        except Exception as exc:  # noqa: BLE001
            logger.opt(exception=exc).warning("Board setup failed — /board returns empty")
            self._board_aggregator = None
            self._board_aggregator_task = None
            self._board_evaluator = None
            self._bio_scheduler = None
            self._bio_generator = None
            app.state.board_aggregator = None
            app.state.board_store = None
            app.state.board_insights = None
            app.state.achievement_evaluator = None
            app.state.bio_generator = None
            app.state.bio_store = None

    def _setup_skill_registry(self, app: FastAPI) -> None:
        """First-run bootstrap + attach the SkillRegistry to ``app.state``.

        Failure cases (e.g. a read-only filesystem in the test runner) are
        not fatal — the UI then shows "No skills" instead of crashing.
        """
        try:
            from dodaios.skills.bootstrap import ensure_user_skills_dir
            from dodaios.skills.prefs import load_state_overrides
            from dodaios.skills.registry import SkillRegistry

            skills_root = ensure_user_skills_dir()
            registry = SkillRegistry(
                root=skills_root,
                bus=self.bus,
                state_prefs_loader=load_state_overrides,
            )
            self._skill_registry = registry
            app.state.skill_registry = registry
            # reload_sync() (disk glob + parse) is deferred off the boot critical
            # path — run after uvicorn is listening (start()).
            self._pending_reloads.append(("SkillRegistry", registry))
            logger.info("SkillRegistry created (scan deferred) from {}", skills_root)
        except Exception as exc:  # noqa: BLE001
            logger.opt(exception=exc).warning(
                "SkillRegistry setup failed — Skills view stays empty"
            )
            app.state.skill_registry = None

    def _setup_doc_registry(self, app: FastAPI) -> None:
        """Bring up the doc registry + populate the FTS5 index initially.

        Roots = ``default_doc_roots()`` (see ``dodaios/core/paths.py``).
        The derived FTS index is process-local and rebuilt on every start. A
        shared on-disk WAL made unrelated dev worktrees and overlapping restart
        processes block the Docs view indefinitely on Windows.

        Failure cases (unreadable roots, unavailable FTS5 support) are not
        fatal — the UI surfaces a retryable load error instead of crashing.
        """
        try:
            from dodaios.core.paths import default_doc_roots
            from dodaios.docs.registry import DocRegistry

            roots = default_doc_roots()
            registry = DocRegistry(
                roots=roots,
                index_db=None,
                bus=self.bus,
            )
            self._doc_registry = registry
            app.state.doc_registry = registry
            # The initial Markdown scan + FTS index build is deferred off the
            # boot critical path and runs after uvicorn is listening (start()).
            self._pending_reloads.append(("DocRegistry", registry))
            logger.info("DocRegistry created (scan deferred) for {} roots", len(roots))
        except Exception as exc:  # noqa: BLE001
            logger.opt(exception=exc).warning("DocRegistry setup failed — Docs view stays empty")
            app.state.doc_registry = None

    def _setup_cli_registry(self, app: FastAPI) -> None:
        """Set up the ``CliToolRegistry`` and run the catalog probe asynchronously.

        The constructor creates the registry without probing (non-blocking).
        An asyncio task is scheduled in ``start()`` that runs ``bootstrap()`` —
        until then the endpoints return ``status=checking`` for all entries.

        Failure cases: read-only FS or DB lock → no crash, just an empty registry.
        """
        try:
            from dodaios.clis.registry import CliToolRegistry
            from dodaios.clis.shared import set_active_registry

            registry = CliToolRegistry(bus=self.bus)
            self._cli_registry = registry
            app.state.cli_registry = registry
            # Shared state: from here on, CliToolLoader and make_cli_patterns_fn
            # see the same instance — the LLM gets the real connected CLIs as
            # tools, not an empty catalog copy.
            set_active_registry(registry)
            logger.info(
                "CliToolRegistry created ({} catalog entries, bootstrap pending)",
                len(registry.catalog().all()),
            )
        except Exception as exc:  # noqa: BLE001
            logger.opt(exception=exc).warning(
                "CliToolRegistry setup failed — CLIs view stays empty"
            )
            app.state.cli_registry = None

    def _setup_plugin_registry(self, app: FastAPI) -> None:
        """Construct the PluginToolRegistry (non-blocking) and publish it.

        Mirror of _setup_cli_registry: the bootstrap (which opens an MCPClient
        per connected plugin) is scheduled as a background task in start(). The
        shared handle lets the plugin-tools loader + the marketplace routes see
        the SAME instance on the SAME bus.
        """
        try:
            from dodaios.marketplace.plugin_registry import PluginToolRegistry
            from dodaios.marketplace.plugin_shared import set_active_plugin_registry

            registry = PluginToolRegistry(bus=self.bus)
            self._plugin_registry = registry
            app.state.plugin_registry = registry
            set_active_plugin_registry(registry)
            logger.info("PluginToolRegistry created (bootstrap pending)")
        except Exception as exc:  # noqa: BLE001
            logger.opt(exception=exc).warning(
                "PluginToolRegistry setup failed — plugins stay worker-only"
            )
            app.state.plugin_registry = None
            self._plugin_registry = None

    def _schedule_registry_bootstraps(self) -> None:
        """Start registry discovery after composition without delaying readiness."""
        async def bootstrap(registry: Any, label: str) -> None:
            try:
                await registry.bootstrap()
            except Exception as exc:  # noqa: BLE001 -- other registries remain usable
                logger.opt(exception=exc).warning("{} registry bootstrap failed", label)

        for registry, attribute, label in (
            (self._cli_registry, "_cli_bootstrap_task", "cli"),
            (self._plugin_registry, "_plugin_bootstrap_task", "plugin"),
        ):
            existing = getattr(self, attribute, None)
            if registry is not None and (existing is None or existing.done()):
                setattr(self, attribute, asyncio.create_task(
                    bootstrap(registry, label), name=f"{label}-registry-bootstrap",
                ))

    async def _stop_registry_bootstraps(self) -> bool:
        """Cancel both owners before awaiting either one's resource cleanup."""
        owners = {
            attribute: task
            for attribute in ("_cli_bootstrap_task", "_plugin_bootstrap_task")
            if (task := getattr(self, attribute, None)) is not None
        }
        for task in owners.values():
            if not task.done() and not task.cancelling():
                task.cancel()
        if not owners:
            return True
        done, pending = await asyncio.wait(
            set(owners.values()), timeout=server_module()._REGISTRY_BOOTSTRAP_STOP_TIMEOUT_S,
        )
        for attribute, task in owners.items():
            if task in done:
                if not task.cancelled() and (error := task.exception()) is not None:
                    logger.warning("Registry bootstrap stopped with {}", type(error).__name__)
                setattr(self, attribute, None)
        if pending:
            logger.warning("{} registry bootstrap owner(s) still stopping", len(pending))
        return not pending
