"""The verse host: one object per app that ties supervisor, probe, bridge and relays.

``dodaios/ui/web/verse_routes.py`` creates it lazily on ``app.state`` and
calls into it; nothing runs until the first ``show`` (architecture 1.1:
never at app start). Lifecycle (contract 12): the host sends ``lifecycle.*``,
``panel.*``, ``gpu.*`` and ``settings.changed``, and tracks what Verse
reports (``lifecycle.state``, ``lifecycle.ready``, ``window.state``,
``panel.stream_state``, ``focus.return_to_app``, ``lifecycle.bye``).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

from . import probe as probe_mod
from . import protocol as P
from .bridge import BridgeHub, BridgeSession, TokenBox, mint_token
from .install_port import InstallJob, VerseInstaller, load_installer
from .ports import AppBackend, BackendPort
from .relays.chat_tails import ChatTailsRelay
from .relays.commands import CommandsRelay
from .relays.meetings import MeetingsRelay
from .relays.progression import ProgressionRelay
from .relays.roster import RosterRelay
from .relays.screens import ScreensRelay
from .relays.settings import CompanionRelay, SettingsRelay, locale_block
from .settings_store import SettingsStore
from .supervisor import Supervisor

log = logging.getLogger(__name__)

IDLE_QUIT_S = 600.0
GPU_YIELD_QUIT_S = 10.0
DECKS = ("bridge", "ops", "engineering", "hangar")


def allow_foreground(pid: int | None) -> None:
    """Let ``pid`` take the foreground (Windows foreground lock); a no-op elsewhere."""
    if not pid or sys.platform != "win32":
        return
    try:  # pragma: no cover - Windows only
        import ctypes

        ctypes.windll.user32.AllowSetForegroundWindow(int(pid))
    except Exception:  # noqa: BLE001
        log.debug("verse host: AllowSetForegroundWindow failed", exc_info=True)


def panel_available() -> bool:
    import importlib.util

    try:
        return importlib.util.find_spec("dodaios.verse_host.signal") is not None
    except (ImportError, ValueError):  # WP20 signalling not installed yet
        return False


def restrict_to_user(path: Path) -> None:
    """User-only access to ``path`` (the dev discovery file holds a token)."""
    if sys.platform == "win32":  # pragma: no cover - Windows only
        import subprocess

        user = os.environ.get("USERNAME", "")
        if user:
            subprocess.run(
                ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:F"],  # noqa: S607
                capture_output=True,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
    else:
        os.chmod(path, 0o600)


class VerseHost:
    def __init__(
        self,
        app: Any,
        *,
        backend: BackendPort | None = None,
        store: SettingsStore | None = None,
        data_dir: Path | None = None,
        supervisor: Supervisor | None = None,
        app_version: str | None = None,
        installer: VerseInstaller | None = None,
    ) -> None:
        if data_dir is None:
            from dodaios.core.config import DATA_DIR

            data_dir = Path(DATA_DIR)
        self.app = app
        self.data_dir = Path(data_dir) / "verse"
        self.backend: BackendPort = backend or AppBackend(app)
        self.store = store or SettingsStore(self.data_dir / "settings.json")
        self.tokens = TokenBox()
        self.port = 8765
        if app_version is None:
            try:
                from dodaios import __version__ as app_version
            except Exception:  # source checkout without a version; the welcome says 0.0.0
                app_version = "0.0.0"
        self.app_version = str(app_version)
        from dodaios.agentic_ide.launch_sequence import LaunchSequence

        self.launcher = LaunchSequence(_LaunchSteps(self.backend))
        self.hub = BridgeHub(check_token=self.tokens.check, welcome=self._welcome)
        from .signal import SignalHub

        self.signal = SignalHub(lambda: self.tokens.get("launch"), on_panel=self._on_signal_panel)
        self.hub.on_hung = self._on_hung
        self.hub.on_session = self._on_session
        self.supervisor = supervisor or Supervisor(
            exe=probe_mod.find_executable,
            bridge_url=self.bridge_url,
            set_token=lambda t: self.tokens.set("launch", t),
            mint=mint_token,
            crash_dir=self.data_dir / "crashes",
            on_change=self._status_changed,
            request_quit=self._request_quit,
        )
        self.capability: probe_mod.Capability | None = None
        self.visibility = "hidden"
        self.panel = "hidden"
        self.gpu = "free"
        self.state: str | None = None
        self.vram_mb: int | None = None
        self.fps: float | None = None
        self.dormant_since: float | None = None
        self.pending_show: dict[str, Any] | None = None
        self.timings: dict[str, Any] = {}
        self._show_sent_at: float | None = None
        self._launch_at: float | None = None
        self._idle_task: asyncio.Task[None] | None = None
        self.dev_file: Path | None = None
        self.qa: dict[str, Any] = {}
        self._roster: RosterRelay | None = None
        self.install = InstallJob(
            installer or load_installer(Path(data_dir)),
            on_change=self._install_changed,
            before_remove=self._before_remove,
        )
        self._wire()

    # ------------------------------------------------------------------ wiring
    def _wire(self) -> None:
        hub = self.hub
        hub.relay(self._make_roster)
        hub.relay(lambda s: ScreensRelay(s, self.backend))
        hub.relay(lambda s: ChatTailsRelay(s, self.backend))
        hub.relay(lambda s: MeetingsRelay(s, self.backend))
        hub.relay(lambda s: ProgressionRelay(s, self.backend, self.store))
        hub.relay(lambda s: SettingsRelay(s, self.backend, self.store, self._publish_settings))
        hub.relay(lambda s: CompanionRelay(s, self.backend))
        hub.relay(
            lambda s: CommandsRelay(
                s, self.backend, launcher=self.launcher, qa=self.qa, on_open=self._after_open
            )
        )
        for name, handler in (
            ("lifecycle.state", self._n_state),
            ("lifecycle.ready", self._n_ready),
            ("lifecycle.bye", self._n_bye),
            ("window.state", self._n_window),
            ("panel.stream_state", self._n_panel_stream),
            ("focus.return_to_app", self._n_return),
        ):
            hub.notice(name, handler)
        self.qa["Verse.QA.SetDuty"] = self._qa_set_duty

    def _make_roster(self, session: BridgeSession) -> RosterRelay:
        relay = RosterRelay(session, self.backend)
        relay.uniform = str(self.store.settings().get("uniform", "standard"))
        self._roster = relay
        return relay

    async def _qa_set_duty(self, args: list[str]) -> Any:
        if len(args) != 2:
            raise P.BridgeError("bad_request", "Verse.QA.SetDuty <agent_id> <duty>")
        if self._roster is None:
            raise P.BridgeError("unavailable", "The roster relay is not running.")
        return await self._roster.qa_set_duty(args[0], args[1])

    # ------------------------------------------------------------------ urls, tokens
    def bridge_url(self) -> str:
        return f"ws://127.0.0.1:{self.port}{P.PATH}"

    def set_port(self, port: int | None) -> None:
        if port:
            self.port = int(port)

    def features(self) -> list[str]:
        feats = list(P.BASE_FEATURES)
        if not panel_available():
            # The panel is Pixel Streaming (WP20); announced once its signalling lands.
            feats.remove("panel")
        if self.backend.duel_service() is not None:
            feats.insert(feats.index("companion"), "duel_stats")
        # welcome.settings.game and its settings.changed / settings.set subsets.
        feats.append("game_settings")
        return feats

    def _welcome(self, session: BridgeSession) -> dict[str, Any]:
        self.hub.features = self.features()
        config = getattr(getattr(self.app, "state", None), "config", None)
        return {
            "protocol": P.PROTOCOL,
            "app_version": self.app_version,
            "app_pid": os.getpid(),
            "session": session.id,
            "features": self.hub.features,
            "encoding": {"screens": session.screens_encoding},
            "limits": dict(P.LIMITS),
            "locale": locale_block(config),
            "settings": self.store.settings(),
            "decks": list(DECKS),
            "state": {"visibility": self.visibility, "panel": self.panel, "gpu": self.gpu},
        }

    def write_dev_discovery(self) -> Path | None:
        """``<DATA_DIR>/verse/bridge.json`` for editor runs (contract 1, Dev discovery)."""
        if not self.store.flag("dev_bridge", "DODAIOS_VERSE_DEV_BRIDGE"):
            return None
        token = mint_token()
        self.tokens.set("dev", token)
        path = self.data_dir / "bridge.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        body = {"url": self.bridge_url(), "token": token, "pid": os.getpid()}
        path.write_text(json.dumps(body), encoding="utf-8")
        restrict_to_user(path)
        self.dev_file = path
        return path

    def remove_dev_discovery(self) -> None:
        if self.dev_file is not None:
            with contextlib.suppress(OSError):
                self.dev_file.unlink()
            self.dev_file = None
            self.tokens.set("dev", None)

    # ------------------------------------------------------------------ status
    def _stale(self) -> bool:
        cap = self.capability
        return cap is None or (
            cap.gpu.failed and time.time() - cap.checked_at >= probe_mod.RETRY_FAILED_S
        )

    def check(self, *, refresh: bool = False) -> probe_mod.Capability:
        """The cached capability; blocking when it has to probe (sync callers only)."""
        if refresh or self._stale():
            self.capability = probe_mod.check(refresh=refresh)
        assert self.capability is not None
        return self.capability

    async def acheck(self, *, refresh: bool = False) -> probe_mod.Capability:
        """:meth:`check` for async paths: the GPU probe runs off the event loop."""
        if refresh or self._stale():
            self.capability = await asyncio.to_thread(probe_mod.check, refresh=refresh)
        assert self.capability is not None
        return self.capability

    def status(self) -> dict[str, Any]:
        sup = self.supervisor.state
        if sup.status in ("running", "crashed"):
            status = sup.status
        else:
            cap = self.check()
            status = {"unsupported": "unsupported", "not_installed": "not_installed"}.get(
                cap.status, "stopped"
            )
        running = status == "running"
        return {
            "status": status,
            "state": (self.state or "booting") if running else None,
            "pid": sup.pid if running else None,
            "vram_mb": self.vram_mb if running else None,
            "fps": self.fps if running else None,
            "crash_report": sup.crash_report,
        }

    async def astatus(self) -> dict[str, Any]:
        """:meth:`status` for async paths (any probe runs off the event loop)."""
        await self.acheck()
        return self.status()

    async def _install_changed(self) -> None:
        """A download finished or the Verse was removed: find the executable again."""
        self.capability = None
        await self.acheck()
        await self._status_changed()

    async def _before_remove(self) -> None:
        if self.supervisor.running:
            await self.supervisor.stop("update")

    async def _status_changed(self) -> None:
        if not self.supervisor.running:
            self.state = None
            self.vram_mb = self.fps = None
        bus = self.backend.bus
        if bus is None:
            return
        from dodaios.core.events import VerseStatusChanged

        await self.acheck()  # status() then reads the cache, never probes on the loop
        st = self.status()
        with contextlib.suppress(Exception):
            await bus.publish(
                VerseStatusChanged(
                    source_layer="verse_host",
                    status=st["status"],
                    state=st["state"] or "",
                    pid=st["pid"] or 0,
                )
            )

    # ------------------------------------------------------------------ commands from the app
    async def show(self, reason: str = "verse_view", monitor: dict[str, Any] | None = None) -> dict:
        """Open the Verse view: launch lazily, then ``lifecycle.show`` once linked."""
        if reason not in ("verse_view", "quick_start_duel", "station"):
            raise ValueError(f"bad show reason {reason!r}")
        cap = await self.acheck()
        if cap.status != "ok" and self.supervisor.state.status != "running":
            return self.status()
        self.pending_show = {
            "monitor": monitor or {"x": 0, "y": 0, "w": 1920, "h": 1080, "dpi": 96},
            "reason": reason,
        }
        self._show_sent_at = time.monotonic()
        if not self.supervisor.running:
            self._launch_at = time.monotonic()
            await self.supervisor.ensure_running(manual=True)
        else:
            await self._flush_show()
        return self.status()

    async def _flush_show(self) -> None:
        session = self.hub.current
        if session is None or self.pending_show is None:
            return
        allow_foreground(session.pid or self.supervisor.state.pid)
        session.send("lifecycle.show", self.pending_show)
        self.visibility = "visible"
        self.pending_show = None

    async def hide(self, reason: str = "user") -> bool:
        if reason not in ("app_focus", "user", "minimised"):
            raise ValueError(f"bad hide reason {reason!r}")
        self.visibility = "hidden"
        return await self.hub.push_all("lifecycle.hide", {"reason": reason})

    async def app_took_focus(self) -> bool:
        self.visibility = "hidden"
        return await self.hub.push_all("focus.app_took", {})

    async def pause(self, reason: str, *, resume: bool = False) -> bool:
        return await self.hub.push_all(
            "lifecycle.resume" if resume else "lifecycle.pause", {"reason": reason}
        )

    async def stop(self, reason: str = "app_quit") -> dict[str, Any]:
        await self.supervisor.stop(reason)
        return await self.astatus()

    async def _request_quit(self, reason: str, deadline_ms: int) -> bool:
        return await self.hub.push_all(
            "lifecycle.quit", {"reason": reason, "deadline_ms": deadline_ms}
        )

    async def panel_visibility(self, visible: bool, w: int, h: int, dpr: float) -> bool:
        self.panel = "visible" if visible else "hidden"
        if visible and not self.supervisor.running and (await self.acheck()).status == "ok":
            await self.supervisor.ensure_running(manual=True)
        return await self.hub.push_all(
            "panel.visibility", {"visible": visible, "w": w, "h": h, "dpr": dpr}
        )

    async def panel_resize(self, w: int, h: int, dpr: float) -> bool:
        return await self.hub.push_all("panel.resize", {"w": w, "h": h, "dpr": dpr})

    async def gpu_pressure(self, busy: bool, by: str = "other") -> bool:
        """``gpu.yield`` / ``gpu.free``; a Dormant Verse quits itself on ``gpu.yield``."""
        self.gpu = "yield" if busy else "free"
        if by not in ("blender_cook", "local_stt", "local_model", "other"):
            by = "other"
        sent = await self.hub.push_all("gpu.yield" if busy else "gpu.free", {"by": by})
        if sent and busy and self.state == "dormant":
            # Contract 12: a Dormant Verse quits at once on gpu.yield. That exit
            # gives the GPU back; it is not a crash and must not relaunch.
            self.supervisor.expect_exit(GPU_YIELD_QUIT_S)
        return sent

    async def settings_changed(self, changed: dict[str, Any]) -> bool:
        if not changed:
            return False
        return await self.hub.push_all("settings.changed", changed)

    async def qa_exec(self, command: str, args: list[str]) -> dict[str, Any]:
        """Run a ``Verse.QA.*`` command inside Verse (Shipping too); needs DODAIOS_VERSE_QA=1."""
        from .relays.commands import qa_enabled

        if not qa_enabled():
            raise P.BridgeError("unavailable", "QA commands need DODAIOS_VERSE_QA=1.")
        if not command.startswith("Verse.QA."):
            raise P.BridgeError("bad_request", "command must be a Verse.QA.* command.")
        session = self.hub.current
        if session is None:
            raise P.BridgeError("unavailable", "Verse is not connected.")
        return await session.request("qa.exec", {"command": command, "args": list(args)})

    async def _publish_settings(self, changed: dict[str, Any]) -> None:
        bus = self.backend.bus
        if bus is None:
            return
        from dodaios.core.events import VerseSettingsChanged

        await bus.publish(VerseSettingsChanged(source_layer="verse_host", settings=changed))

    async def _after_open(self) -> None:
        self.visibility = "hidden"

    # ------------------------------------------------------------------ bridge callbacks
    async def _on_hung(self, session: BridgeSession) -> None:
        await self.supervisor.on_hung()

    async def _on_session(self, session: BridgeSession | None) -> None:
        if session is None:
            return
        await self._flush_show()
        if self._idle_task is None or self._idle_task.done():
            self._idle_task = asyncio.ensure_future(self._idle_loop())

    async def _n_state(self, session: BridgeSession, msg: P.Inbound) -> None:
        state = msg.data.get("state")
        if state not in P.LIFECYCLE_STATES:
            return
        previous, self.state = self.state, state
        vram = msg.data.get("vram_mb")
        fps = msg.data.get("fps")
        self.vram_mb = vram if isinstance(vram, int) else self.vram_mb
        self.fps = float(fps) if isinstance(fps, int | float) else self.fps
        now = time.monotonic()
        if state == "dormant":
            self.dormant_since = now
            self.visibility = "hidden"
        else:
            self.dormant_since = None
        if state == "visible":
            self.visibility = "visible"
            if previous == "dormant" and self._show_sent_at is not None:
                self.timings["dormant_to_visible_ms"] = round((now - self._show_sent_at) * 1000)
        if previous != state:
            await self._status_changed()

    async def _n_ready(self, session: BridgeSession, msg: P.Inbound) -> None:
        self.supervisor.mark_healthy()
        first = msg.data.get("first_frame_ms")
        if isinstance(first, int | float):
            self.timings["first_frame_ms"] = first
        if self._launch_at is not None:
            self.timings["cold_start_ms"] = round((time.monotonic() - self._launch_at) * 1000)
            self._launch_at = None

    async def _n_bye(self, session: BridgeSession, msg: P.Inbound) -> None:
        log.info("verse host: Verse said bye (saved=%s)", msg.data.get("saved"))
        # Verse quits after a bye (an answer to lifecycle.quit, or its own exit,
        # e.g. after a launch): the exit that follows is a stop.
        self.supervisor.expect_exit()

    async def _n_window(self, session: BridgeSession, msg: P.Inbound) -> None:
        visible = msg.data.get("visible")
        if isinstance(visible, bool):
            self.visibility = "visible" if visible else "hidden"

    async def _n_panel_stream(self, session: BridgeSession, msg: P.Inbound) -> None:
        state = msg.data.get("state")
        if state in ("starting", "streaming", "stopped", "failed"):
            session.panel_stream = dict(msg.data)
            await self.signal.publish_stream_state(dict(msg.data))

    async def _on_signal_panel(self, kind: str, data: dict[str, Any]) -> None:
        """The panel's player socket opened, resized or closed: tell Verse (bridge 12)."""
        try:
            w, h, dpr = int(data.get("w", 0)), int(data.get("h", 0)), float(data.get("dpr", 1.0))
        except (TypeError, ValueError):
            log.debug("verse host: ignored a malformed %s from the signalling", kind)
            return
        if kind == "panel.visibility":
            await self.panel_visibility(bool(data.get("visible")), w, h, dpr)
        elif kind == "panel.resize":
            await self.panel_resize(w, h, dpr)

    async def _n_return(self, session: BridgeSession, msg: P.Inbound) -> None:
        """Verse hid itself and allowed our foreground: raise the app window."""
        self.visibility = "hidden"
        bus = self.backend.bus
        if bus is None:
            return
        from dodaios.core.events import ShowWindowRequested

        await bus.publish(ShowWindowRequested(source_layer="verse_host", source="verse_return"))

    async def _idle_loop(self) -> None:
        """Dormant for 10 minutes: ask Verse to quit (``idle_10min``)."""
        while self.hub.current is not None:
            await asyncio.sleep(5.0)
            since = self.dormant_since
            if since is not None and time.monotonic() - since >= IDLE_QUIT_S:
                self.dormant_since = None
                await self.supervisor.stop("idle_10min")
                return

    # ------------------------------------------------------------------ import
    def import_browser_settings(self, values: dict[str, Any]) -> list[str]:
        """``POST /api/verse/settings/import``: write each key only where it is still unset."""
        if self.store.get("imported"):
            return []
        patch: dict[str, Any] = {}
        imported: list[str] = []
        view = values.get("dodaios.verse.view.v1")
        if isinstance(view, str):
            with contextlib.suppress(ValueError):
                view = json.loads(view)
        if isinstance(view, dict):
            clean: dict[str, Any] = {}
            for key, value in view.items():
                if self.store.is_set(f"view.{key}"):
                    continue
                try:
                    from .settings_store import validate

                    clean.update(validate({"view": {key: value}})["view"])
                except ValueError:  # invalid browser value is skipped on import
                    continue
            if clean:
                patch["view"] = clean
                imported.append("dodaios.verse.view.v1")
        uniform = values.get("dodaios.verse.uniform.v1")
        if isinstance(uniform, str) and uniform and not self.store.is_set("uniform"):
            patch["uniform"] = uniform.strip('"')[:40]
            imported.append("dodaios.verse.uniform.v1")
        sound = values.get("jarvis.verse.level.sound.v1")
        if sound is not None and not self.store.is_set("level_sound"):
            patch["level_sound"] = str(sound).strip('"').lower() not in ("0", "false", "off")
            imported.append("jarvis.verse.level.sound.v1")
        if patch:
            self.store.update(patch)
        seen = values.get("jarvis.verse.levels.seen.v1")
        if seen is not None and self.store.get("told_seq") is None:
            with contextlib.suppress(TypeError, ValueError):
                self.store.raise_told_seq(int(str(seen).strip('"')))
                imported.append("jarvis.verse.levels.seen.v1")
        best = values.get("jarvis.office.arcade.asteroids.best")
        if best is not None and self.store.get("arcade_best") is None:
            with contextlib.suppress(TypeError, ValueError):
                self.store.put("arcade_best", int(str(best).strip('"')))
                imported.append("jarvis.office.arcade.asteroids.best")
        self.store.put("imported", True)
        return imported


class _LaunchSteps:
    """The backend port as the launch sequence's steps."""

    def __init__(self, backend: BackendPort) -> None:
        self.backend = backend

    async def open_terminal(self, workspace_id: str | None, agent: str) -> tuple[str, str]:
        return await self.backend.open_terminal(workspace_id, agent)

    async def start_terminal(self, name: str, workspace_id: str) -> None:
        await self.backend.start_terminal(name, workspace_id)

    async def list_panes(self) -> list[dict[str, Any]]:
        return await self.backend.list_panes()

    async def prompt_terminal(self, name: str, text: str, workspace_id: str) -> bool | None:
        return await self.backend.prompt_terminal(name, text, workspace_id)


def get_host(app: Any) -> VerseHost:
    host = getattr(app.state, "verse_host", None)
    if host is None:
        host = VerseHost(app)
        app.state.verse_host = host
    return host
