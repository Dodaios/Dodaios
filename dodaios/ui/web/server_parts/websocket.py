"""The ``/ws`` hub: client bookkeeping, level frames, and inbound frame routing."""

from __future__ import annotations

import asyncio
import math
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from loguru import logger
from pydantic import ValidationError

from dodaios import __version__
from dodaios.core.events import (
    ErrorOccurred,
    Event,
    MessageSent,
    SystemStarted,
    TerminalClosed,
    TerminalCommandExecuted,
    TerminalOutput,
    TerminalSpawned,
)
from dodaios.terminal import get_shell

from ..schema import (
    WSAudioLevel,
    WSCommand,
    WSMessageIn,
    WSWelcome,
    event_to_ws_envelope,
)

if TYPE_CHECKING:
    pass

from ._srv import server_module


class WebSocketMixin:
    """The ``/ws`` hub: client bookkeeping, level frames, and inbound frame routing."""

    def _register_ws_route(self, app: FastAPI) -> None:
        @app.websocket("/ws")
        async def ws_endpoint(ws: WebSocket) -> None:
            await self._handle_ws(ws)

    async def _handle_ws(self, ws: WebSocket) -> None:
        await ws.accept()
        session_id = str(uuid4())
        send_lock = asyncio.Lock()
        self._clients[session_id] = ws
        self._client_send_locks[session_id] = send_lock

        welcome = WSWelcome(session_id=session_id, version=__version__)

        def _drop_stalled_client() -> None:
            """Detach this WS client so a wedged socket cannot keep blocking
            the event bus (AP-18). The receive loop's ``finally`` does the
            same cleanup; doing it here too is idempotent and stops the bleed
            immediately instead of waiting for the OS TCP timeout."""
            self._remove_ws_client(session_id)
            try:
                self.bus._wildcard_subscribers.remove(_forward)  # type: ignore[attr-defined]
            except ValueError:
                pass

        async def _forward(event: Event) -> None:
            if session_id not in self._clients:
                return
            try:
                envelope = event_to_ws_envelope(event)
                async with send_lock:
                    # Bounded send: a stalled/half-open client must NEVER block
                    # the bus (BUG-CU-STALL). On timeout we drop the client.
                    await asyncio.wait_for(ws.send_json(envelope), timeout=server_module()._WS_SEND_TIMEOUT_S)
            except WebSocketDisconnect:
                _drop_stalled_client()
            except TimeoutError:
                logger.warning(
                    "WS client dropped — send stalled >{}s (a wedged tab must "
                    "never freeze the event bus) session_id={} event={}",
                    server_module()._WS_SEND_TIMEOUT_S,
                    session_id,
                    type(event).__name__,
                )
                _drop_stalled_client()
            except Exception as exc:  # noqa: BLE001
                logger.opt(exception=exc).warning(
                    "WS forward failed",
                    session_id=session_id,
                    event=type(event).__name__,
                )

        self.bus.subscribe_all(_forward)

        try:
            async with send_lock:
                await ws.send_json(welcome.model_dump())
            # Welcome must remain the first frame. Register this session only
            # after it has arrived, then lazily tap the already-open native mic.
            self._mic_level_sessions.add(session_id)
            self._ensure_mic_level_bridge()

            while True:
                try:
                    raw = await ws.receive_json()
                except WebSocketDisconnect:
                    break
                except RuntimeError as exc:
                    # The socket is gone — e.g. starlette raises
                    # RuntimeError('WebSocket is not connected ...') after an
                    # unclean client disconnect instead of WebSocketDisconnect.
                    # `continue` here re-calls receive_json on the dead socket
                    # forever: a ~9 MB/s traceback log-storm that wedges the
                    # event loop and triggers a self-restart cancelling every
                    # in-flight mission (live incident 2026-06-14). Treat it as
                    # a disconnect and leave the loop.
                    logger.opt(exception=exc).warning(
                        "WS receive aborted; closing connection",
                        session_id=session_id,
                    )
                    break
                except Exception as exc:  # noqa: BLE001
                    # A failed receive leaves the socket state uncertain. Treat
                    # every read error as terminal so a dead socket can never
                    # spin in this loop (AP-20).
                    logger.opt(exception=exc).warning(
                        "WS receive failed; closing connection",
                        session_id=session_id,
                    )
                    try:
                        await self.bus.publish(
                            ErrorOccurred(
                                layer="ui.web.ws",
                                error_type=type(exc).__name__,
                                message=str(exc),
                                recoverable=False,
                                source_layer="ui.web.ws",
                            )
                        )
                    except Exception as publish_exc:  # noqa: BLE001
                        logger.opt(exception=publish_exc).warning(
                            "WS receive failure could not be published",
                            session_id=session_id,
                        )
                    break

                await self._route_incoming(session_id, raw, send_lock)

        except WebSocketDisconnect:
            pass
        except Exception as exc:  # noqa: BLE001
            logger.opt(exception=exc).error(
                "WS handler aborted",
                session_id=session_id,
            )
            await self.bus.publish(
                ErrorOccurred(
                    layer="ui.web.ws",
                    error_type=type(exc).__name__,
                    message=str(exc),
                    recoverable=False,
                    source_layer="ui.web.ws",
                )
            )
        finally:
            # Unsubscribe to avoid a memory leak.
            try:
                self.bus._wildcard_subscribers.remove(_forward)  # type: ignore[attr-defined]
            except ValueError:
                pass
            self._remove_ws_client(session_id)
            try:
                await ws.close()
            except Exception as exc:  # noqa: BLE001
                logger.opt(exception=exc).debug(
                    "WebSocket was already closed", session_id=session_id
                )

    def _ensure_mic_level_bridge(self) -> None:
        """Tap both voice levels while a web UI is connected.

        The microphone and the assistant's own output. ``level_tap`` only
        computes its RMS while something is subscribed, so a web client
        connecting is what turns that measurement on — and disconnecting turns
        it back off.
        """
        if self._mic_level_unsub is not None or not self._mic_level_sessions:
            return

        # Lazy import keeps audio modules off the web server's startup path.
        from dodaios.audio import level_tap, mic_level

        loop = asyncio.get_running_loop()

        def _receive(level: float) -> None:
            try:
                loop.call_soon_threadsafe(self._queue_mic_level, float(level))
            except RuntimeError as exc:
                # Shutdown can close the event loop between the audio callback
                # and this handoff. The subscriber is removed during teardown.
                logger.opt(exception=exc).debug("Microphone level loop is closed")

        def _receive_tts(level: float) -> None:
            try:
                loop.call_soon_threadsafe(self._queue_tts_level, float(level))
            except RuntimeError as exc:
                logger.opt(exception=exc).debug("Output level loop is closed")

        self._mic_level_unsub = mic_level.subscribe(_receive)
        self._tts_level_unsub = level_tap.subscribe(_receive_tts)

    def _stop_mic_level_bridge(self) -> None:
        unsubscribe = self._mic_level_unsub
        self._mic_level_unsub = None
        unsubscribe_tts = self._tts_level_unsub
        self._tts_level_unsub = None
        self._mic_level_latest = 0.0
        self._tts_level_latest = 0.0
        self._mic_level_revision += 1
        if unsubscribe is not None:
            unsubscribe()
        if unsubscribe_tts is not None:
            unsubscribe_tts()

        task = self._mic_level_task
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()
        self._mic_level_task = None

    def _remove_ws_client(self, session_id: str) -> WebSocket | None:
        ws = self._clients.pop(session_id, None)
        self._client_send_locks.pop(session_id, None)
        self._mic_level_sessions.discard(session_id)
        if not self._mic_level_sessions:
            self._stop_mic_level_bridge()
        return ws

    def _queue_mic_level(self, level: float) -> None:
        """Coalesce audio-thread samples into at most one pending send task."""
        if not self._mic_level_sessions:
            return
        self._mic_level_latest = min(1.0, max(0.0, level)) if math.isfinite(level) else 0.0
        self._mic_level_revision += 1
        if self._mic_level_task is None or self._mic_level_task.done():
            self._mic_level_task = asyncio.create_task(self._drain_mic_levels())

    def _queue_tts_level(self, level: float) -> None:
        """Same coalescing as the microphone, for the assistant's own voice."""
        if not self._mic_level_sessions:
            return
        self._tts_level_latest = min(1.0, max(0.0, level)) if math.isfinite(level) else 0.0
        self._mic_level_revision += 1
        if self._mic_level_task is None or self._mic_level_task.done():
            self._mic_level_task = asyncio.create_task(self._drain_mic_levels())

    async def _drain_mic_levels(self) -> None:
        """Send only the freshest level; functional WS traffic has priority."""
        sent_revision = -1
        try:
            while self._mic_level_sessions and sent_revision != self._mic_level_revision:
                sent_revision = self._mic_level_revision
                frame = WSAudioLevel(
                    input=self._mic_level_latest,
                    output=self._tts_level_latest,
                ).model_dump()
                await asyncio.gather(
                    *(
                        self._send_mic_level(session_id, frame)
                        for session_id in tuple(self._mic_level_sessions)
                    )
                )
        finally:
            if self._mic_level_task is asyncio.current_task():
                self._mic_level_task = None

    async def _send_mic_level(self, session_id: str, frame: dict[str, Any]) -> None:
        ws = self._clients.get(session_id)
        send_lock = self._client_send_locks.get(session_id)
        if ws is None or send_lock is None:
            return

        async def _send() -> None:
            async with send_lock:
                if self._clients.get(session_id) is ws:
                    await ws.send_json(frame)

        try:
            await asyncio.wait_for(_send(), timeout=server_module()._WS_LEVEL_SEND_TIMEOUT_S)
        except TimeoutError:
            # This sample is already stale; the next one will replace it.
            return
        except WebSocketDisconnect:
            self._remove_ws_client(session_id)
        except Exception as exc:  # noqa: BLE001
            logger.opt(exception=exc).debug("Microphone level send failed", session_id=session_id)
            stale_ws = self._remove_ws_client(session_id)
            if stale_ws is not None:
                try:
                    await stale_ws.close()
                except Exception as close_exc:  # noqa: BLE001
                    logger.opt(exception=close_exc).debug(
                        "Microphone level socket close failed",
                        session_id=session_id,
                    )

    async def _route_incoming(
        self,
        session_id: str,
        raw: Any,
        send_lock: asyncio.Lock,
    ) -> None:
        """Validates and dispatches an incoming WS frame."""
        if not isinstance(raw, dict):
            await self.bus.publish(
                ErrorOccurred(
                    layer="ui.web.ws",
                    error_type="InvalidFrame",
                    message=f"Expected dict, got {type(raw).__name__}",
                    recoverable=True,
                    source_layer="ui.web.ws",
                )
            )
            return

        frame_type = raw.get("type")
        try:
            if frame_type == "message":
                msg = WSMessageIn.model_validate(raw)
                thread_id = (msg.metadata or {}).get("thread_id", session_id)
                await self.bus.publish(
                    MessageSent(
                        thread_id=thread_id,
                        role="user",
                        text=msg.content,
                        source_layer="ui.web.ws",
                    )
                )
            elif frame_type == "command":
                cmd = WSCommand.model_validate(raw)
                await self._handle_command(session_id, cmd, send_lock)
            else:
                await self.bus.publish(
                    ErrorOccurred(
                        layer="ui.web.ws",
                        error_type="UnknownFrameType",
                        message=f"type={frame_type!r}",
                        recoverable=True,
                        source_layer="ui.web.ws",
                    )
                )
        except ValidationError as exc:
            logger.warning("WS frame validation error", errors=exc.errors())
            await self.bus.publish(
                ErrorOccurred(
                    layer="ui.web.ws",
                    error_type="ValidationError",
                    message=str(exc),
                    recoverable=True,
                    source_layer="ui.web.ws",
                )
            )
        except WebSocketDisconnect:
            # A reply frame (pong, terminal.spawned) hit a closed socket — that
            # is the receive loop's business, not a failed command.
            raise
        except Exception as exc:  # noqa: BLE001 — one bad frame must not end the session
            # A handler failing on one frame (a malformed terminal.resize, a
            # PTY write error) used to escape into _handle_ws, which closed the
            # whole UI event socket. Report it and keep the connection.
            action = raw.get("action") if frame_type == "command" else None
            logger.opt(exception=exc).warning(
                "WS frame handler failed", frame_type=frame_type, action=action
            )
            await self.bus.publish(
                ErrorOccurred(
                    layer="ui.web.ws",
                    error_type="CommandFailed" if frame_type == "command" else "FrameFailed",
                    message=f"{action or frame_type} failed: {type(exc).__name__}",
                    recoverable=True,
                    source_layer="ui.web.ws",
                )
            )

    async def _handle_command(
        self,
        session_id: str,
        cmd: WSCommand,
        send_lock: asyncio.Lock,
    ) -> None:
        if cmd.action == "ping":
            ws = self._clients.get(session_id)
            if ws is not None:
                async with send_lock:
                    await ws.send_json({"type": "pong", "payload": cmd.payload})
        elif cmd.action == "test_event":
            await self.bus.publish(SystemStarted(version=__version__, source_layer="ui.web.ws.cmd"))
        elif cmd.action == "terminal.spawn":
            await self._handle_terminal_spawn(session_id, cmd.payload, send_lock)
        elif cmd.action == "terminal.input":
            await self._handle_terminal_input(cmd.payload)
        elif cmd.action == "terminal.resize":
            self._handle_terminal_resize(cmd.payload)
        elif cmd.action == "terminal.close":
            self._handle_terminal_close(cmd.payload)
        elif cmd.action == "stt_dictate":
            await self._handle_dictation(cmd.payload)
        elif cmd.action == "mission.inject":
            await self._handle_mission_inject(session_id, cmd.payload)

    async def _handle_mission_inject(self, session_id: str, payload: dict[str, Any]) -> None:
        """Drag-drop a mission card → inject it into the live conversation.

        Composes a bounded, human-readable user turn from the card's own data
        and publishes it as a normal ``MessageSent``. The existing brain
        dispatcher then answers it (spoken on voice, shown in chat) and the
        text lands in ``BrainManager._history`` so follow-ups stay in context.
        A distinct ``source_layer`` marks the turn for traceability AND is the
        signal the router uses to exempt a recap from force-spawn — a dropped
        card is DISCUSSED inline, never re-dispatched as a new mission. The
        brain dispatcher still runs the turn (only ``"chat"``/``"brain:mock"``
        are skipped), so it answers exactly like a typed message.
        """
        from dodaios.ui.web.mission_inject import (
            MISSION_INJECT_SOURCE_LAYER,
            compose_mission_inject_text,
        )

        text = compose_mission_inject_text(payload)
        if not text:
            logger.debug("mission.inject: empty/unparseable payload — ignored")
            return
        thread_id = str(payload.get("thread_id") or session_id)
        await self.bus.publish(
            MessageSent(
                thread_id=thread_id,
                role="user",
                text=text,
                source_layer=MISSION_INJECT_SOURCE_LAYER,
            )
        )

    async def _handle_dictation(self, payload: dict[str, Any]) -> None:
        """Start/stop chat mic-dictation on the live SpeechPipeline.

        Transcribe-only: the pipeline streams ``DictationTranscript`` events
        (forwarded to the browser by the wildcard subscriber) straight into the
        chat input — it never reaches the brain. Resolves the pipeline via
        ``runtime_refs``; if there is none (headless / voice disabled) it emits a
        recoverable error + a toast instead of crashing (cloud-first no-op).
        """
        from dodaios.core.runtime_refs import get_speech_pipeline

        mode = str(payload.get("mode", "start"))
        # "chat" (default) fills the composer; "insert" is dictation mode —
        # the transcript is pasted into the focused field of whatever app is in
        # front. The chat mic button never sends "insert".
        target = "insert" if str(payload.get("target", "chat")) == "insert" else "chat"
        pipeline = get_speech_pipeline()
        if pipeline is None:
            # Headless / voice disabled — no server mic. Recoverable, not fatal:
            # surface it as an ErrorOccurred (the frontend already handles that
            # event) and return. Cloud-first no-op.
            await self.bus.publish(
                ErrorOccurred(
                    layer="ui.web.dictation",
                    error_type="DictationUnavailable",
                    message="Dictation needs a server microphone (not available in this mode).",
                    recoverable=True,
                    source_layer="ui.web.ws",
                )
            )
            return
        try:
            if mode == "stop":
                pipeline.stop_dictation()
            else:
                started = pipeline.start_dictation(target=target, source="ws")
                if not started:
                    await self.bus.publish(
                        ErrorOccurred(
                            layer="ui.web.dictation",
                            error_type="DictationBusy",
                            message="Mic is busy — can't start dictation right now.",
                            recoverable=True,
                            source_layer="ui.web.ws",
                        )
                    )
        except Exception as exc:  # noqa: BLE001 — never crash the WS loop
            logger.warning("dictation command failed", error=str(exc))

    async def _handle_terminal_spawn(
        self,
        session_id: str,
        payload: dict[str, Any],
        send_lock: asyncio.Lock,
    ) -> None:
        shell_id = str(payload.get("shell", "pwsh"))
        cols = int(payload.get("cols", 120) or 120)
        rows = int(payload.get("rows", 30) or 30)
        cwd = payload.get("cwd")
        cwd_str = str(cwd) if cwd else None

        shell = get_shell(shell_id)
        if shell is None:
            await self.bus.publish(
                ErrorOccurred(
                    layer="ui.web.terminal",
                    error_type="ShellNotFound",
                    message=f"Shell {shell_id!r} not installed",
                    recoverable=True,
                    source_layer="ui.web.terminal",
                )
            )
            return

        bus = self.bus

        async def _on_output(terminal_id: str, data: str) -> None:
            await bus.publish(
                TerminalOutput(
                    terminal_id=terminal_id,
                    data=data,
                    source_layer="ui.web.terminal",
                )
            )

        async def _on_closed(terminal_id: str, exit_code: int) -> None:
            self._pty_input_buffers.pop(terminal_id, None)
            self._pty_shell_ids.pop(terminal_id, None)
            await bus.publish(
                TerminalClosed(
                    terminal_id=terminal_id,
                    exit_code=exit_code,
                    source_layer="ui.web.terminal",
                )
            )

        try:
            session = await self._pty.spawn(
                shell_argv=shell.argv,
                shell_id=shell.id,
                cwd=cwd_str,
                cols=cols,
                rows=rows,
                on_output=_on_output,
                on_closed=_on_closed,
            )
        except RuntimeError as exc:
            await self.bus.publish(
                ErrorOccurred(
                    layer="ui.web.terminal",
                    error_type="PtySpawnFailed",
                    message=str(exc),
                    recoverable=True,
                    source_layer="ui.web.terminal",
                )
            )
            return

        self._pty_input_buffers[session.terminal_id] = ""
        self._pty_shell_ids[session.terminal_id] = shell.id

        await self.bus.publish(
            TerminalSpawned(
                terminal_id=session.terminal_id,
                shell_id=shell.id,
                pid=session.pid,
                source_layer="ui.web.terminal",
            )
        )
        # Direct response frame with terminal_id, so the frontend can
        # unambiguously match up multiple parallel spawn requests.
        ws = self._clients.get(session_id)
        if ws is not None:
            async with send_lock:
                await ws.send_json(
                    {
                        "type": "terminal.spawned",
                        "payload": {
                            "terminal_id": session.terminal_id,
                            "shell_id": shell.id,
                            "pid": session.pid,
                        },
                    }
                )

    async def _handle_terminal_input(self, payload: dict[str, Any]) -> None:
        terminal_id = str(payload.get("terminal_id", ""))
        data = str(payload.get("data", ""))
        if not terminal_id or not data:
            return
        if not self._pty.write(terminal_id, data):
            return
        # Audit log: maintain the line buffer, emit a command on \r/\n.
        buf = self._pty_input_buffers.get(terminal_id, "")
        for ch in data:
            if ch in ("\r", "\n"):
                line = buf.strip()
                if line:
                    await self.bus.publish(
                        TerminalCommandExecuted(
                            terminal_id=terminal_id,
                            shell_id=self._pty_shell_ids.get(terminal_id, ""),
                            command=line,
                            source_layer="ui.web.terminal.audit",
                        )
                    )
                buf = ""
            elif ch in ("\x7f", "\b"):
                # Backspace — remove the last character from the buffer
                buf = buf[:-1]
            elif ch >= " ":
                buf += ch
            # We ignore other control chars (Ctrl-C etc.) in the buffer.
        # Memory cap for extremely long pasted lines.
        if len(buf) > 4096:
            buf = buf[-4096:]
        self._pty_input_buffers[terminal_id] = buf

    def _handle_terminal_resize(self, payload: dict[str, Any]) -> None:
        terminal_id = str(payload.get("terminal_id", ""))
        cols = int(payload.get("cols", 0) or 0)
        rows = int(payload.get("rows", 0) or 0)
        if terminal_id and cols > 0 and rows > 0:
            self._pty.resize(terminal_id, cols, rows)

    def _handle_terminal_close(self, payload: dict[str, Any]) -> None:
        terminal_id = str(payload.get("terminal_id", ""))
        if terminal_id:
            self._pty.close(terminal_id)
