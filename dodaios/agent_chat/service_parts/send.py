"""Receiving a message and dispatching it as a turn."""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from typing import Any

from dodaios.agent_chat import service as _s
from dodaios.agent_chat.runner_api import TurnHandle
from dodaios.agent_chat.store import (
    AgentChatSession,
)
from dodaios.society.delivery import IncomingMessage


class SendMixin:
    """Receiving a message and dispatching it as a turn."""

    # ---------------------------------------------------------------- turns

    async def receive_message(self, session_id: str, incoming: IncomingMessage) -> dict[str, Any]:
        """Persist a trusted internal message even while its receiving chat is busy."""
        if self.store.get_session(session_id) is None:
            raise _s.NoSuchSession(session_id)
        existing = self.store.incoming_message(session_id, incoming.message_id)
        if existing is not None:
            return existing
        await self._emit(session_id, _s.make_event("agent_message", incoming.model_dump()))
        return incoming.model_dump()

    async def message_status(
        self, session_id: str, message_id: str, status: str, *, turn_id: str = "", error: str = ""
    ) -> None:
        await self._emit(
            session_id,
            _s.make_event(
                "agent_message_status",
                {
                    "message_id": message_id,
                    "status": status,
                    "turn_id": turn_id,
                    "error": error,
                },
            ),
        )

    async def bind_society_session(
        self, session_id: str, *, routine_run: bool = False
    ) -> AgentChatSession:
        """Recheck the roster before a Society command or turn uses a session."""
        from dodaios.society.chat_binding import bind_society_session

        return await bind_society_session(self, session_id, routine_run=routine_run)

    async def clear_conversation(self, session_id: str, *, name: str = "") -> dict[str, Any]:
        """Start a coding thread's conversation over (``/clear``); the session afterwards.

        The thread shows empty and its agent's next turn opens a new
        conversation; what was said before stays stored (``thread_clear``).
        Raises :class:`SessionBusy` while a turn runs or is being prepared: the
        command then waits behind it like any message typed meanwhile.
        """
        session = self.store.get_session(session_id)
        if session is None:
            raise _s.NoSuchSession(session_id)
        if session.surface != "agent":
            raise ValueError("Only a coding thread is cleared this way")
        if session_id in self._preparing:
            raise _s.SessionBusy(session_id)
        # The UI calls a turn idle from its turn_finished on (reports_running).
        await self._await_finishing(session_id)
        async with self._publish_lock(session_id):
            # No await between this check and the write: the event itself
            # drops the CLI conversation, and a turn admitted in between would
            # resume the old one and bring it back. One small write, so it
            # runs on the loop like a turn's end does.
            if session_id in self._preparing or self.is_running(session_id):
                raise _s.SessionBusy(session_id)
            # Cards of the old conversation that still waited for an answer
            # (a question, a secure field) are closed with it.
            self._cancel_questions(session_id)
            stored = self.store.append_event(session_id, _s.make_event(_s.CLEARED_KIND, {}))
            if name:
                self.store.update_session(session_id, title=name)
            self._deliver_event(session_id, stored)
        _s.log.info("agent chat %s: conversation cleared by the person", session_id)
        cleared = self.store.get_session(session_id)
        if cleared is None:  # deleted while it was cleared
            return {}
        # The open windows hold the session row: its title and its
        # conversation changed with the clear.
        await self._emit(
            session_id,
            _s.make_event(
                "session_updated",
                {
                    "title": cleared.title,
                    "vendor_session": cleared.vendor_session or "",
                    "cleared_seq": cleared.cleared_seq,
                },
            ),
        )
        return cleared.to_dict()

    async def send(
        self,
        session_id: str,
        text: str,
        attachments: list[dict[str, Any]] | None = None,
        *,
        tool_choices: list[str] | None = None,
        incoming: IncomingMessage | None = None,
        direct_user: bool = True,
        read_only: bool = False,
        control_owned: bool = False,
        control_runner: Any = None,
        output_language: str = "",
        native_goal: bool = False,
        display_text: str | None = None,
        routine_run: bool = False,
        author: dict[str, str] | None = None,
        background_result: bool = False,
    ) -> str:
        """Persist the person's message and start the turn. Returns turn_id.

        ``background_result`` continues an earlier request of the person whose
        delegates finished after its turn had closed (``parked_work``). It is
        their own task, so the turn runs with their standing, but nothing was
        typed: no command parsing, no goal steering, and the timeline draws
        no bubble or line for the message, only the answer.

        ``author`` marks a message another agent wrote on the person's behalf
        (``{"agent_id", "name"}``, a Jarvis agent steering a coding thread):
        it rides on the ``user_message`` so the thread shows who wrote it.

        ``attachments`` are what the composer already had read for this message
        (``dodaios.agent_chat.attachments``): a described screenshot, an
        extracted document. Their contents go INTO the message the turn
        receives, because a chat may be answered by a coding CLI or a
        text-only model that cannot open the file itself.

        A message with attachments may carry no sentence at all — dropping a
        picture and pressing Enter is a complete gesture — but an empty message
        with nothing attached is still refused.
        """
        session = self.store.get_session(session_id)
        if session is None:
            raise _s.NoSuchSession(session_id)
        # Nothing was typed for a background result: it passes the gates a
        # control-owned message passes, and keeps the person's standing.
        control_owned = control_owned or background_result
        if (
            direct_user
            and incoming is None
            and not control_owned
            and author is None
            and _s.thread_clear.wants_clear(session, text, attachments)
        ):
            # "/clear" the person typed in a coding thread: the thread starts
            # over, and no turn runs for it (``thread_clear``). It needs no
            # folder, so a worktree put away stays away.
            await self.clear_conversation(session_id, name=_s.thread_clear.clear_name(text) or "")
            return ""
        if session.surface == "agent":
            # A worktree the app made for this thread and put away while the
            # thread rested is back before the turn needs its folder.
            from dodaios.orchestrator.verification import workdir

            if workdir.away(session.cwd):
                await asyncio.to_thread(workdir.restore, session.cwd)
        if session.surface == "society":
            session = await self.bind_society_session(session_id, routine_run=routine_run)
        selected_runner = None
        if session.surface == "jarvis":
            from dodaios.core.task_agent import subscription_seat_off_loop

            # The saved chat pick is authoritative. Global worker preferences
            # supply defaults when creating chats, never replace a user's
            # provider/model on send (#223). Resolve only that pick's seat.
            seat = await subscription_seat_off_loop(session.provider)
            if seat is not None:
                provider, selected_runner = seat
                if session.provider != provider:
                    session = _s.replace(
                        session,
                        provider=provider,
                        vendor_session=None,
                    )
                    self.store.reseat_session(session_id, provider=provider, model=session.model)
        if (
            session.surface in ("jarvis", "society")
            and direct_user
            and incoming is None
            and not control_owned
        ):
            from dodaios.agent_chat.control_types import COMMANDS

            command = re.match(r"^/([a-z]+)(?:\s|$)", text.strip())
            if command and command[1] in {row["name"] for row in COMMANDS}:
                raise ValueError("Use the chat command endpoint for slash commands")
        if session_id in self._preparing:
            raise _s.SessionBusy(session_id)
        # The UI calls a turn idle from its turn_finished on (reports_running).
        await self._await_finishing(session_id)
        if session_id in self._preparing:
            raise _s.SessionBusy(session_id)
        if self.is_running(session_id):
            # A person may steer an active Jarvis goal: user_message pauses
            # its old turn before this preparation can become a new runner.
            goal = (
                self._controls.state(session_id).goal
                if session.surface == "jarvis"
                and direct_user
                and incoming is None
                and not control_owned
                and hasattr(self, "_controls")
                else None
            )
            if goal is None or goal.status != "active":
                raise _s.SessionBusy(session_id)
        if session.surface == "society":
            from dodaios.society.chat_binding import direct_chat_owner

            owner = direct_chat_owner(session_id)
            if owner is not None and any(
                direct_chat_owner(sid) == owner for sid in self.running_session_ids()
            ):
                raise _s.SessionBusy(session_id)
        turn_id = uuid.uuid4().hex
        cancel = asyncio.Event()
        run = _s._Running(turn_id, cancel)
        self._preparing[session_id] = run
        control_revision: int | None = None
        control_text = text
        if (
            session.surface in ("jarvis", "society")
            and direct_user
            and incoming is None
            and not control_owned
        ):
            if hasattr(self, "_controls"):
                try:
                    control_revision = await self._controls.user_message(session_id, text)
                except (asyncio.CancelledError, Exception):
                    if self._preparing.get(session_id) is run:
                        self._preparing.pop(session_id, None)
                    run.ready.set()
                    raise
        try:
            if read_only:
                session = _s.replace(session, permission_mode="plan")
            if session.permission_mode in ("plan", "read-only") and session.surface in (
                "jarvis",
                "society",
            ):
                from dodaios.agent_chat.control import supports_restricted_turn

                if not supports_restricted_turn(session):
                    raise ValueError(
                        "This runner cannot enforce read-only mode; choose an API model"
                    )
            if incoming is not None:
                receipt = await self.receive_message(session_id, incoming)
                if receipt["status"] == "delivered":
                    if self._preparing.get(session_id) is run:
                        self._preparing.pop(session_id, None)
                    run.ready.set()
                    return str(receipt.get("turn_id") or "")
                if receipt["status"] == "failed":
                    raise ValueError("This internal message already failed")
            if self.is_running(session_id):
                raise _s.SessionBusy(session_id)
            kit = _s.kit_for(session.surface)
            text = text.strip()
            attached = _s.chat_attachments.to_analysis(attachments)
            if not text and not attached:
                raise ValueError("empty message")
            # What the turn receives; ``text`` stays what the person typed so the
            # timeline shows their sentence rather than a page of extracted PDF.
            prompt = _s.chat_attachments.compose(text, attached)
            if session.surface == "jarvis" and direct_user and not control_owned:
                # "New" in the Nodes library: the type chip rides in front of the
                # description. The bubble keeps the chip; the turn gets the request.
                from dodaios.agent_chat.node_request import expand_node_request

                node_request = expand_node_request(text)
                if node_request is not None:
                    prompt = _s.chat_attachments.compose(node_request, attached)
                    if display_text is None:
                        display_text = text
            if session.surface == "agent" and direct_user and not control_owned:
                # Other threads dragged in from the sidebar arrive as thread
                # links; the turn gets a card for each, the bubble the words.
                from dodaios.agent_chat.thread_mentions import expand_thread_mentions

                mentioned = await asyncio.to_thread(
                    expand_thread_mentions,
                    self.store,
                    text,
                    own_session_id=session_id,
                    is_running=self.is_running,
                )
                if mentioned is not None:
                    prompt = _s.chat_attachments.compose(mentioned, attached)
                    if display_text is None:
                        display_text = text
            if session.surface == "society" and not text.startswith("/"):
                # Decisions on the agent's proposals reach it here, once, as a
                # system note in front of its next message: never as a message
                # from the person, and never as a turn of their own. A slash
                # command stays the first thing a CLI seat reads.
                from dodaios.society.proposals import decision_context

                decided = decision_context(self.store.list_events(session_id, tail=200))
                if decided:
                    prompt = decided + "\n\n" + prompt
                    if display_text is None:
                        display_text = text
            # A plain chat shows its pictures to the model itself.
            images: tuple[str, ...] = ()
            native_pictures = False
            if attached and not kit.plain and session.surface != "jarvis":
                from dodaios.agent_chat import plain_chat

                # A coding thread's CLI sees the pictures itself (Claude Code and
                # GLM as image blocks, Codex through ``--image``), so no vision
                # description is needed and the 4-picture cap does not apply. The
                # file path stays in the text for the CLI's tools.
                if (
                    selected_runner or _s.session_runner(session)
                ) in plain_chat.NATIVE_IMAGE_RUNNERS:
                    found = await asyncio.to_thread(
                        plain_chat.image_paths, session.cwd, attached, limit=None
                    )
                    images = tuple(str(path) for path in found)
                    native_pictures = bool(images)
            if native_pictures:
                attached = _s._seen_directly(session.cwd, attached, images)
                prompt = _s.chat_attachments.compose(text, attached)
            if attached and kit.plain:
                from dodaios.agent_chat import plain_chat

                found = await asyncio.to_thread(plain_chat.image_paths, session.cwd, attached)
                images = tuple(str(path) for path in found)
                if images:
                    prompt += "\n\n" + plain_chat.IMAGES_NOTE
            if session.surface == "jarvis":
                # Pictures of earlier messages keep their IDs, so the task the
                # person confirms a message after the screenshot still carries it.
                await asyncio.to_thread(self._refresh_picture_handoffs, session)
            visual_references: list[str] = []
            if attached and session.surface == "jarvis":
                visual_references = _s.chat_attachments.handoff_references(attached)
                image_context = await asyncio.to_thread(
                    _s.chat_attachments.handoff_context,
                    session.cwd,
                    attached,
                    session_id=session_id,
                )
                if image_context:
                    prompt += "\n\n" + image_context
            if (
                session.surface == "jarvis"
                and direct_user
                and incoming is None
                and not control_owned
                and text
            ):
                # "What's this?" / "turn this mail into an event": with Screen
                # Context on, "this" is what is on screen (screen_reference).
                from dodaios.agent_chat.screen_reference import screen_context_block

                screen_block = await screen_context_block(
                    text,
                    session_id=session_id,
                    cwd=session.cwd,
                    locale=output_language,
                    bus=self._bus(),
                )
                if screen_block:
                    prompt += "\n\n" + screen_block
                    if display_text is None:
                        display_text = text
            if session.surface == "jarvis" and direct_user and incoming is None and text:
                # A message from the owner's phone chat: the reply is read on a
                # small screen (channels.output_contract).
                from dodaios.agent_chat.screen_reference import is_away
                from dodaios.channels.output_contract import STYLE_BLOCK

                if is_away():
                    prompt = f"{prompt}{chr(10)}{chr(10)}{STYLE_BLOCK}"
                    if display_text is None:
                        display_text = text
            # Agent cards serialize Add selections as capability pins. Translate the
            # browser pin to the same validated receipt used by the root composer.
            if session.surface == "jarvis" and any(
                "core:browser" in {item.strip() for item in match.split(",")}
                for match in _s._TOOL_PIN_LINE.findall(text)
            ):
                tool_choices = list(dict.fromkeys([*(tool_choices or []), "tool:society_browser"]))
            selected = []
            if tool_choices:
                if session.surface != "jarvis":
                    raise ValueError("Tool selections are supported by the Dodaios chat")
                from dodaios.agent_chat.runner_brain import brain_manager
                from dodaios.agent_chat.tool_catalog import live_catalog, resolve_choices

                inventory = await asyncio.to_thread(
                    live_catalog, brain_manager(), cwd=session.cwd, stance=session.permission_mode
                )
                selected = resolve_choices(tool_choices, inventory)
                # Discovery yields; another send may have acquired this session.
                if self.is_running(session_id):
                    raise _s.SessionBusy(session_id)

            # Roster state can change while a control message or an internal
            # delivery is being recorded. Rebind after those awaits, then reserve
            # the seat without yielding again. Keep the caller's read-only choice.
            if session.surface == "society":
                session = await self.bind_society_session(session_id, routine_run=routine_run)
                if read_only:
                    session = _s.replace(session, permission_mode="plan")
                if session.permission_mode in ("plan", "read-only"):
                    from dodaios.agent_chat.control import supports_restricted_turn

                    if not supports_restricted_turn(session):
                        raise ValueError(
                            "This runner cannot enforce read-only mode; choose an API model"
                        )

            # Revalidate after the last await, then transfer the reservation
            # to the runner without yielding. Scheduled runs stay independent.
            if cancel.is_set():
                raise asyncio.CancelledError
            if self._preparing.get(session_id) is not run or self.is_running(session_id):
                raise _s.SessionBusy(session_id)
            if session.surface == "society":
                from dodaios.society.chat_binding import direct_chat_owner

                owner = direct_chat_owner(session_id)
                if owner is not None and any(
                    direct_chat_owner(sid) == owner and self.is_running(sid)
                    for sid in self._running
                    if sid != session_id
                ):
                    raise _s.SessionBusy(session_id)

            self._preparing.pop(session_id, None)
            self._running[session_id] = run
        except (asyncio.CancelledError, Exception):
            if self._preparing.get(session_id) is run:
                self._preparing.pop(session_id, None)
            try:
                if control_revision is not None:
                    await self._controls.message_rejected(
                        session_id, control_text, control_revision
                    )
            except Exception:
                _s.log.exception(
                    "chat control status could not close rejected message in %s", session_id
                )
            finally:
                run.ready.set()
            raise
        turn_started_emitted = False
        try:
            if (
                session.surface == "jarvis"
                and direct_user
                and incoming is None
                and not control_owned
            ):
                from dodaios.agent_chat.store import ChatSelection

                self.store.save_chat_selection(
                    ChatSelection(
                        session.provider, session.model, session.effort, session.account_id
                    )
                )
            from dodaios.core.tool_read_only import set_chat_read_only

            set_chat_read_only(session_id, session.permission_mode in ("plan", "read-only"))

            history_start = kit.history_start(session) if kit.history_start is not None else 0
            history = await asyncio.to_thread(
                self.store.list_events, session_id, after_seq=history_start
            )
            await asyncio.to_thread(
                _s.token_efficiency.note_turn_start,
                turn_id,
                history,
                start_seq=history_start,
                spill=session.surface == "jarvis",
            )
            if incoming is not None:
                await self.message_status(
                    session_id, incoming.message_id, "delivered", turn_id=turn_id
                )
            else:
                await self._emit(
                    session_id,
                    _s.make_event(
                        "user_message",
                        {
                            # The full prompt: this is what was actually sent, and the
                            # API runner rebuilds the conversation from these events —
                            # storing only the sentence would lose the picture on the
                            # NEXT turn (runner_api.messages_from_events).
                            "text": prompt,
                            **({"origin": "control"} if control_owned and not direct_user else {}),
                            **({"origin": _s.BACKGROUND_ORIGIN} if background_result else {}),
                            **({"author": dict(author)} if author else {}),
                            **(
                                {"tool_choices": [row.model_dump(mode="json") for row in selected]}
                                if selected
                                else {}
                            ),
                            # What the person typed, when it differs from the prompt.
                            # Absent on an ordinary message, so nothing changes there.
                            **(
                                {"typed": display_text if display_text is not None else text}
                                if attached or display_text is not None
                                else {}
                            ),
                            **(
                                {"attachments": _s._attachment_receipts(attached)}
                                if attached
                                else {}
                            ),
                            # The pictures a later message may still forward
                            # (attachments.refresh_handoffs); the receipts above
                            # lose their file references when they are shown.
                            **(
                                {"visual_references": visual_references}
                                if visual_references
                                else {}
                            ),
                        },
                    ),
                )
            runner = selected_runner or _s.session_runner(session)
            turn_started_emitted = True
            await self._emit(
                session_id,
                _s.make_event(
                    "turn_started",
                    {
                        "turn_id": turn_id,
                        "provider": session.provider,
                        "model": session.model,
                        # The effort the turn RUNS with. It is the session's own
                        # pick: no surface overrides it any more (the kit's
                        # `effort` went with the setup helper), so reading one off
                        # the kit would only be a way to raise an AttributeError
                        # on every turn.
                        "effort": _s.normalize_effort(session.provider, session.effort),
                        "runner": runner,
                        "surface": session.surface,
                    },
                ),
            )

            bus = self._bus()
            # The lead's one turn contract, whatever seat runs it
            # (lead_turn_contract): the reply language comes from the one
            # resolver, a CLI seat also gets the skill and recall blocks, and
            # the answer is checked after the turn (TurnCompletion, lead mode).
            from dodaios.agent_chat.side_threads import parent_of, speaks_as_lead

            lead_contract = (
                session.surface == "jarvis"
                and direct_user
                and incoming is None
                and control_runner is None
                and not native_goal
                and not kit.plain
                and bool(text)
                # A side thread of the conversation is the lead answering too.
                and speaks_as_lead(self, session_id)
            )
            lead_pre = None
            if lead_contract:
                from dodaios.agent_chat import lead_turn_contract
                from dodaios.agent_chat.runner_brain import brain_manager
                from dodaios.agent_chat.runner_cli import _CLAUDE_CODE_RUNNERS

                if not output_language:
                    manager = brain_manager()
                    spoken = history
                    parent = parent_of(self, session_id)
                    if parent:
                        # A side thread is the same conversation to the person:
                        # a short question beside it keeps its language.
                        spoken = await asyncio.to_thread(self.store.list_events, parent) + history
                    output_language = lead_turn_contract.resolve_language(
                        # A background result's prompt is composed here, in
                        # English: the answer stays in the conversation's
                        # language, which the person's own messages set.
                        "" if background_result else text,
                        spoken,
                        getattr(manager, "reply_language", "auto"),
                    )
                if runner != "brain" and _s.supports_cli_runner(runner) and not background_result:
                    lead_pre = await lead_turn_contract.prepare(
                        text,
                        carries_recall=runner in _CLAUDE_CODE_RUNNERS or not session.vendor_session,
                    )
            if author and not output_language and session.surface == "agent":
                # An agent briefs a coding thread for the person, usually in
                # English. The person reads the thread: it answers in theirs.
                output_language = await self._language_of_the_person(session_id, author)
            # A plain chat's system prompt is the surface's own. Written per
            # turn, so its workspace notes follow the session's folder.
            plain_system = (
                await kit.plain_chat(session, text, self._assistant_name())
                if kit.plain_chat is not None
                else ""
            )
            handle = _s.TurnHandle(
                session=session,
                turn_id=turn_id,
                emit=lambda ev: self._emit(session_id, ev),
                request_approval=lambda call_id, name, args, summary: self._ask(
                    session_id, turn_id, call_id, name, args, summary
                ),
                cancel=cancel,
                history=history,
                tools_disabled=kit.plain,
                plain_system=plain_system,
                images=images,
                assistant_name=self._assistant_name(),
                bus=bus,
                surface=session.surface,
                stance=session.permission_mode if kit.uses_stance else "",
                output_language=output_language,
                goal_turn=native_goal,
                opened_by=_s._opened_by(session, author, history),
                control_service=self,
                on_steer=lambda writer, _sid=session_id, _tid=turn_id: self._set_steerer(
                    _sid, _tid, writer
                ),
                on_conversation=lambda vendor, _sid=session_id: self._keep_conversation(
                    _sid, vendor
                ),
            )
        except BaseException as exc:
            try:
                if turn_started_emitted:
                    await self._emit(
                        session_id,
                        _s.make_event(
                            "turn_finished",
                            {
                                "turn_id": turn_id,
                                "status": (
                                    "cancelled"
                                    if isinstance(exc, asyncio.CancelledError)
                                    else "error"
                                ),
                                "duration_ms": 0,
                                "usage": {},
                                "error": (
                                    None if isinstance(exc, asyncio.CancelledError) else str(exc)
                                ),
                            },
                        ),
                    )
            except asyncio.CancelledError:
                pass  # A second stop still releases the pending reservation.
            except Exception:
                _s.log.exception("agent chat could not close the failed start for %s", turn_id)
            finally:
                if self._running.get(session_id) is run:
                    self._running.pop(session_id, None)
                run.ready.set()
                from dodaios.core.tool_read_only import set_chat_read_only

                stored_session = self.store.get_session(session_id)
                set_chat_read_only(
                    session_id,
                    bool(
                        stored_session and stored_session.permission_mode in ("plan", "read-only")
                    ),
                )
            if hasattr(self, "_controls"):
                try:
                    await self._controls.turn_completed(
                        session_id,
                        turn_id,
                        display_text if display_text is not None else text,
                        direct_user and incoming is None,
                        read_only,
                    )
                except Exception:
                    _s.log.exception("chat completion hook failed for aborted start %s", turn_id)
            raise

        async def _body() -> None:
            started = time.monotonic()
            from dodaios.society.delivery import incoming_context

            # What caused this turn: an assignment (the delivery names its event
            # id) or nothing above it. The person's own message is a root.
            cause = incoming if incoming is not None else incoming_context.get()
            if cause is not None and cause.sender_kind == "user":
                cause = None
            if routine_run:
                turn_origin = "routine"
            elif cause is not None:
                turn_origin = "agent"
            elif background_result:
                turn_origin = "chat"
            else:
                turn_origin = "chat" if direct_user else "system"
            origin = _s.ChatTurn(
                session_id,
                turn_id,
                display_text if display_text is not None else text,
                direct_user and incoming is None,
                str(handle.trace_id),
                span_id=turn_id,
                parent_span_id=cause.message_id if cause is not None else "",
                origin=turn_origin,
            )
            origin_token = _s.current_chat_turn.set(origin)
            from dodaios.orchestrator import traces

            traces.open_turn(
                origin, provider=session.provider, model=session.model, runner=selected_runner or ""
            )
            from dodaios.agent_chat.turn_completion import TurnCompletion

            completion = (
                TurnCompletion(
                    self,
                    handle,
                    origin.user_text,
                    allow_correction=origin.direct_user and not read_only,
                    context=prompt,
                    lead=session.surface != "society",
                )
                if (session.surface == "society" and control_runner is None and not native_goal)
                or lead_contract
                else None
            )
            run_handle = (
                _s.replace(handle, emit=completion.emit, request_approval=completion.ask)
                if completion is not None
                else handle
            )

            async def run_attempt(active_handle: TurnHandle, run_prompt: str) -> None:
                if session.surface == "society":
                    environment = await _s.society_execution_environment(session_id)
                    if environment is None and runner != "brain":
                        raise ValueError(
                            "Agent execution environment is unavailable; native execution refused."
                        )
                    if environment == "sandbox" and (
                        runner != "brain" or control_runner is not None or native_goal
                    ):
                        raise ValueError(
                            "The sandbox requires a Dodaios API or local model; "
                            "a native agent cannot run on the host in sandbox mode."
                        )
                if control_runner is not None:
                    vendor = await control_runner(active_handle, text)
                    if vendor:
                        self.store.update_session(session_id, vendor_session=vendor)
                elif runner == "brain":
                    async with self._brain_locks.setdefault(session_id, asyncio.Lock()):
                        await _s.run_brain_turn(
                            active_handle,
                            run_prompt,
                            bridge=self._bridge_for(bus),
                            always_allowed=self.always_allowed(session_id),
                            **({"tool_choices": selected} if selected else {}),
                        )
                elif _s.supports_cli_runner(runner):
                    from dodaios.agent_chat.tool_catalog import selection_briefing

                    # A CLI runs AS Jarvis — its own tools over MCP, its calls
                    # answered by the chat's approval card — only where the
                    # surface both is Jarvis and seats a CLI at all. The front
                    # page is the first and the second is now false there, so
                    # today this is every CLI turn running as a plain coding
                    # agent. Asked of the kit rather than the surface name, so
                    # a surface that combines the two keeps working.
                    as_jarvis = kit.brain_runner and kit.cli_seats
                    # Requests still running behind this turn; the brain
                    # runner carries the same note in its briefing.
                    background = self.parked_work.context_note(session_id)
                    if session.surface == "jarvis":
                        from dodaios.agent_chat import side_threads

                        # A side thread's brief, or the side threads running
                        # beside this main-thread turn.
                        # The repositories in play, for the lead's own
                        # conversation and only when it differs from what that
                        # conversation was last handed ([rsi] repo_index).
                        repo_note = ""
                        if not side_threads.is_side_thread(self, session_id):
                            from dodaios.rsi.repo_cards import cli_note

                            repo_note = cli_note(session_id, text)
                        background = "\n\n".join(
                            note
                            for note in (
                                background,
                                side_threads.context_note(self, session_id),
                                side_threads.running_note(self, session_id),
                                repo_note,
                            )
                            if note
                        )
                    if lead_pre is not None and not active_handle.continuation:
                        run_prompt = lead_pre.apply(run_prompt)
                    vendor = await _s.run_cli_turn(
                        active_handle,
                        run_prompt
                        + selection_briefing(selected)
                        + (f"\n\n{background}" if background else ""),
                        runner,
                        identity=as_jarvis,
                        bridge=self._bridge_for(bus) if as_jarvis else None,
                        always_allowed=self.always_allowed(session_id),
                    )
                    if vendor and vendor != session.vendor_session:
                        self.store.update_session(session_id, vendor_session=vendor)
                elif runner == "api" and _s.supports_api_runner(session.provider):
                    await _s.run_api_turn(active_handle, run_prompt)
                else:
                    await self._emit(
                        session_id,
                        _s.make_event(
                            "turn_finished",
                            {
                                "turn_id": turn_id,
                                "status": "error",
                                "duration_ms": 0,
                                "usage": {},
                                "error": (
                                    f"No runner for provider {session.provider!r} on this "
                                    "machine. Connect it under API Keys → Agents."
                                ),
                            },
                        ),
                    )

            try:
                run_prompt = prompt
                for _ in range(_s.MAX_ASKS_PER_TURN + 2):
                    if (
                        origin.direct_user
                        and session.surface in ("jarvis", "society")
                        and control_runner is None
                        and not native_goal
                    ):
                        from dodaios.agent_chat.delegation_wait import run_with_delegates

                        await run_with_delegates(self, run_handle, run_prompt, run_attempt)
                    else:
                        await run_attempt(run_handle, run_prompt)
                    if completion is None:
                        break
                    continuation = await completion.next_prompt()
                    if continuation is None:
                        break
                    stored = self.store.get_session(session_id)
                    run_handle = _s.replace(
                        run_handle,
                        session=_s.replace(
                            run_handle.session,
                            vendor_session=stored.vendor_session if stored else None,
                        ),
                        history=await asyncio.to_thread(
                            self.store.list_events, session_id, after_seq=history_start
                        ),
                        continuation=True,
                        # The pictures went with the message they came with.
                        images=(),
                    )
                    run_prompt = continuation
                if completion is not None:
                    await completion.publish()
            except asyncio.CancelledError:
                if run.detached:
                    # The CLI keeps working in the turn host; the next app
                    # start carries this turn on, so it stays open.
                    raise
                _s.log.info(
                    "agent chat %s: turn %s task was cancelled (stop flag %s)",
                    session_id,
                    turn_id,
                    "set" if run.cancel.is_set() else "NOT set",
                )
                await self._emit(
                    session_id,
                    _s.make_event(
                        "turn_finished",
                        {
                            "turn_id": turn_id,
                            "status": "cancelled",
                            "duration_ms": int((time.monotonic() - started) * 1000),
                            "usage": completion.usage if completion is not None else {},
                            **(
                                {"cost_usd": completion.cost}
                                if completion and completion.cost is not None
                                else {}
                            ),
                            "error": None,
                        },
                    ),
                )
                raise
            except _s.TurnHandedOver:
                # Another app process attached to the turn host and carries
                # this turn on; it stays open for that process to finish.
                run.detached = True
                _s.log.info("agent chat turn %s handed over to another app process", turn_id)
            except Exception as exc:  # noqa: BLE001 — a runner bug must not leave the UI spinning
                _s.log.exception("agent chat turn %s crashed", turn_id)
                await self._emit(
                    session_id,
                    _s.make_event(
                        "turn_finished",
                        {
                            "turn_id": turn_id,
                            "status": "error",
                            "duration_ms": 0,
                            "usage": completion.usage if completion is not None else {},
                            **(
                                {"cost_usd": completion.cost}
                                if completion and completion.cost is not None
                                else {}
                            ),
                            "error": f"{type(exc).__name__}: {exc}",
                        },
                    ),
                )
            finally:
                if session.surface in ("jarvis", "society"):
                    from dodaios.society.browser.tool import stop_chat_browser

                    await stop_chat_browser(session_id)
                if self._running.get(session_id) is run:
                    self._running.pop(session_id, None)
                stored_session = self.store.get_session(session_id)
                set_chat_read_only(
                    session_id,
                    bool(
                        stored_session and stored_session.permission_mode in ("plan", "read-only")
                    ),
                )
                _s.current_chat_turn.reset(origin_token)
                if kit.turn_completed is not None and not run.detached:
                    try:
                        first_seq = max(
                            (int(e.get("seq") or 0) for e in history), default=history_start
                        )
                        events = await asyncio.to_thread(
                            self.store.list_events, session_id, after_seq=first_seq
                        )
                        await kit.turn_completed(
                            session, _s.ChatCompletion(origin, json.dumps(events))
                        )
                    except Exception:
                        _s.log.exception("chat completion hook failed for %s", turn_id)
                if session.surface == "jarvis" and not run.detached:
                    # The summary of a long conversation is written now, in the
                    # background, so the next turn does not wait for it.
                    _s.lead_compaction.schedule_after_turn(self, session)
                for aid in self.pending_approvals(session_id):
                    fut = self._approvals.pop(aid, None)
                    self._approval_session.pop(aid, None)
                    if fut is not None and not fut.done():
                        fut.set_result("cancel")
                self._cancel_questions(session_id)
                if (
                    kit.turn_prompts
                    and origin.direct_user
                    and control_runner is None
                    and not native_goal
                    and not run.detached
                ):
                    try:
                        await self._open_turn_prompts(session_id, turn_id, runner)
                    except Exception:  # noqa: BLE001 — a missing card leaves the reply readable
                        _s.log.exception("agent chat: end-of-turn card failed for %s", turn_id)
                if hasattr(self, "_controls"):
                    await self._controls.turn_completed(
                        session_id, turn_id, origin.user_text, origin.direct_user, read_only
                    )

        try:
            run.task = asyncio.create_task(_body(), name=f"agent-chat-{turn_id[:8]}")
        except BaseException:
            if self._running.get(session_id) is run:
                self._running.pop(session_id, None)
            run.ready.set()
            raise
        run.ready.set()
        return turn_id
