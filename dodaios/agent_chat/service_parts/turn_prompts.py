"""End-of-turn question and plan cards."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Final

from dodaios.agent_chat import service as _s
from dodaios.agent_chat import (
    turn_prompts,
)
from dodaios.agent_chat.plan_review import PlanReview
from dodaios.agent_chat.questions import (
    QuestionAnswer,
)


class TurnPromptsMixin:
    """End-of-turn question and plan cards."""

    # ------------------------------------------------------------ end-of-turn cards

    #: How far back a finished turn's reply is looked for. The question block
    #: ends the reply, so the newest events always hold it.
    _TURN_PROMPT_TAIL: Final[int] = 2000

    def _turn_prompt_lock(self) -> asyncio.Lock:
        # Lazily: a service built without __init__ (test doubles) still works.
        lock: asyncio.Lock | None = getattr(self, "_prompt_lock", None)
        if lock is None:
            lock = asyncio.Lock()
            self._prompt_lock = lock
        return lock

    async def _open_turn_prompts(self, session_id: str, turn_id: str, runner: str) -> None:
        """After a coding agent's turn: its question card, else its plan card.

        A reply ending in a ``jarvis-ask`` block opens a deferred question
        card; a finished turn while the session is still in plan mode opens a
        plan card. Nothing waits on either — the answer is the next message.
        """
        events = self.store.list_events(session_id, tail=self._TURN_PROMPT_TAIL)
        status, text = _s.turn_prompts.turn_reply(events, turn_id)
        if status != "done":
            return
        specs = _s.turn_prompts.parse_ask_block(text)
        if specs:
            await self._emit(
                session_id,
                _s.make_event(
                    "question_required",
                    {
                        "turn_id": turn_id,
                        "question_id": uuid.uuid4().hex,
                        "asker": "",
                        "questions": [spec.to_payload() for spec in specs],
                        "deferred": True,
                    },
                ),
            )
            return
        session = self.store.get_session(session_id)
        if session is None or session.permission_mode != "plan" or not text.strip():
            return
        build = _s.mode_after_plan(
            _s.ladder_key(session.surface, runner), session.permission_mode, session.build_mode
        )
        if build in _s.PLAN_MODES:
            return
        await self._emit(
            session_id,
            _s.make_event("plan_ready", {"turn_id": turn_id, "build_mode": build}),
        )

    async def answer_turn_question(
        self,
        session_id: str,
        question_id: str,
        *,
        index: int = 0,
        option_index: int | None = None,
        text: str | None = None,
        author: dict[str, str] | None = None,
        option_indices: list[int] | None = None,
        source: str = "person",
    ) -> bool:
        """The person's answer to one question of an end-of-turn card.

        ``source`` as for :meth:`resolve_question`. False for an unknown,
        closed or already answered question; raises ``ValueError`` for an
        answer that does not fit. The last answer closes the card and sends the
        answers to the agent as the next message.
        """
        async with self._turn_prompt_lock():
            card = _s.turn_prompts.open_ask(self.store.list_events(session_id), question_id)
            if card is None:
                return False
            try:
                answers = _s.turn_prompts.answer(
                    card,
                    index,
                    option_index=option_index,
                    text=text,
                    option_indices=option_indices,
                    source=source,
                )
            except IndexError:  # a stale option index is a no-op click; the caller reports False
                return False
            if any(a is None for a in answers):
                await self._turn_question_progress(session_id, card, answers)
                return True
            final = [a for a in answers if a is not None]
            await self._resolve_turn_question(session_id, card, final)
        await self._send_turn_answer(session_id, card, final, author=author)
        return True

    async def skip_turn_question(
        self,
        session_id: str,
        question_id: str,
        *,
        index: int | None = None,
        author: dict[str, str] | None = None,
    ) -> bool:
        """The person closed an end-of-turn card: the agent's recommendations stand.

        With ``index``, only that question is skipped (an empty answer the
        agent decides on); the card sends once its last question is settled.
        """
        async with self._turn_prompt_lock():
            card = _s.turn_prompts.open_ask(self.store.list_events(session_id), question_id)
            if card is None:
                return False
            if index is None:
                final = _s.turn_prompts.skipped(card)
            else:
                if not 0 <= index < len(card.specs) or card.answers[index] is not None:
                    return False
                answers = list(card.answers)
                answers[index] = _s.declined_answer()
                if any(a is None for a in answers):
                    await self._turn_question_progress(session_id, card, answers)
                    return True
                final = [a for a in answers if a is not None]
            await self._resolve_turn_question(session_id, card, final)
        await self._send_turn_answer(session_id, card, final, author=author)
        return True

    async def submit_turn_question(
        self,
        session_id: str,
        question_id: str,
        answers: list[dict[str, Any]],
        *,
        author: dict[str, str] | None = None,
    ) -> bool:
        """The person's reviewed answers to a whole end-of-turn card, sent as
        the next message. Same contract as :meth:`submit_questions`."""
        async with self._turn_prompt_lock():
            card = _s.turn_prompts.open_ask(self.store.list_events(session_id), question_id)
            if card is None:
                return False
            if len(answers) != len(card.specs):
                raise ValueError(f"send one answer per question ({len(card.specs)})")
            final = [
                current if current is not None else _s.answer_json(spec, raw)
                for spec, current, raw in zip(card.specs, card.answers, answers, strict=True)
            ]
            await self._resolve_turn_question(session_id, card, final)
        await self._send_turn_answer(session_id, card, final, author=author)
        return True

    async def _turn_question_progress(
        self,
        session_id: str,
        card: turn_prompts.OpenAsk,
        answers: list[QuestionAnswer | None],
    ) -> None:
        await self._emit(
            session_id,
            _s.make_event(
                "question_progress",
                {
                    "turn_id": card.turn_id,
                    "question_id": card.question_id,
                    "answers": [a.to_payload() if a else None for a in answers],
                },
            ),
        )

    async def _resolve_turn_question(
        self, session_id: str, card: turn_prompts.OpenAsk, answers: list[QuestionAnswer]
    ) -> None:
        await self._emit(
            session_id,
            _s.make_event(
                "question_resolved",
                {
                    "turn_id": card.turn_id,
                    "question_id": card.question_id,
                    "answers": [a.to_payload() for a in answers],
                },
            ),
        )

    async def _language_of_the_person(self, session_id: str, author: dict[str, str]) -> str:
        """The language of the person ``author`` writes for; ``""`` when unknown.

        Read from the person's own sentences in the conversation they have
        with that agent (the one that owns the thread), else in the lead's.
        """
        try:
            from dodaios.agent_chat import lead_turn_contract
            from dodaios.agent_chat.runner_brain import brain_manager
            from dodaios.society.roster import LEAD_AGENT_ID

            row = await asyncio.to_thread(self.store.thread_owner, session_id)
            asked_in = [str(row["owner_session"]) if row else ""]
            if not asked_in[0] or str(author.get("agent_id") or "") != LEAD_AGENT_ID:
                # An agent the person never wrote to works for the lead's person.
                asked_in.append(await asyncio.to_thread(self.store.lead_session_id) or "")
            pin = getattr(brain_manager(), "reply_language", "auto")
            for conversation in dict.fromkeys(asked_in):
                if not conversation or conversation == session_id:
                    continue
                events = await asyncio.to_thread(self.store.list_events, conversation)
                language = lead_turn_contract.resolve_language("", events, pin)
                if language:
                    return language
            return ""
        except Exception:  # noqa: BLE001 - a language hint is never worth a turn
            _s.log.debug("agent chat %s: the person's language not read", session_id, exc_info=True)
            return ""

    async def _send_turn_answer(
        self,
        session_id: str,
        card: turn_prompts.OpenAsk,
        answers: list[QuestionAnswer],
        *,
        author: dict[str, str] | None = None,
    ) -> None:
        await self.send(
            session_id,
            _s.turn_prompts.answers_prompt(card.specs, answers),
            display_text=_s.turn_prompts.answers_display(card.specs, answers),
            author=author,
        )

    async def resolve_turn_plan(
        self,
        session_id: str,
        turn_id: str,
        decision: str,
        *,
        build_mode: str = "",
        author: dict[str, str] | None = None,
        review: PlanReview | None = None,
    ) -> bool:
        """The person's answer to a plan card: ``build`` or ``keep``.

        ``build`` moves a session that is still in Plan to the mode its
        permission pill names and sends the go-ahead as the next message;
        ``keep`` only closes the card, so the person can tell the agent what
        to change. ``build_mode`` is the mode the pill showed when the person
        clicked Build: the one the thread goes on in, so what the button said
        is what runs. Without it the session's recorded mode, then the card's,
        decide. False when the card is not open (any more).

        ``review`` is what the person did in the plan's review window
        (``plan_review``): their edits and comments go to the agent with the
        go-ahead, or, with ``keep``, as the next message, so the agent revises
        the plan instead of waiting for the person to type the same again.
        """
        if decision not in _s.turn_prompts.PLAN_DECISIONS:
            raise ValueError(f"decision must be one of {_s.turn_prompts.PLAN_DECISIONS}")
        async with self._turn_prompt_lock():
            events = self.store.list_events(session_id)
            card = _s.turn_prompts.open_plan(events, turn_id)
            if card is None:
                return False
            original = _s.turn_prompts.turn_reply(events, turn_id)[1]
            await self._emit(
                session_id,
                _s.make_event("plan_resolved", {"turn_id": turn_id, "decision": decision}),
            )
            wanted = (
                _s.plan_review.changes_wanted(original, review)
                if decision == _s.turn_prompts.PLAN_KEEP
                else ""
            )
            if decision == _s.turn_prompts.PLAN_KEEP and not wanted:
                return True
            session = None if wanted else self.store.get_session(session_id)
            # The pill may have moved since the card opened, and a session
            # the person already took out of Plan keeps the mode they picked.
            build = ""
            if session is not None and session.permission_mode in _s.PLAN_MODES:
                ladder = _s.ladder_key(session.surface, _s.session_runner(session))
                shown = build_mode.strip()
                if shown and shown in _s.permission_ids(ladder) and shown not in _s.PLAN_MODES:
                    build = shown
                else:
                    # The card's mode came from ``mode_after_plan`` when the
                    # plan was finished: never the ladder's top rung by default.
                    build = session.build_mode or card.build_mode
            if session is not None and build and build not in _s.PLAN_MODES:
                self.store.update_session(session_id, permission_mode=build)
                await self._emit(
                    session_id,
                    _s.make_event("session_updated", {"permission_mode": build}),
                )
        if wanted:
            # Still planning: the session keeps its mode and the agent revises.
            shown_text = _s.plan_review.shown(original, review, _s.turn_prompts.PLAN_KEEP_SHOWN)
            await self.send(session_id, wanted, display_text=shown_text, author=author)
            return True
        go_ahead = _s.plan_review.go_ahead(original, review, _s.turn_prompts.PLAN_GO_AHEAD)
        await self.send(
            session_id,
            go_ahead,
            display_text=(
                None
                if go_ahead == _s.turn_prompts.PLAN_GO_AHEAD
                else _s.plan_review.shown(original, review, _s.turn_prompts.PLAN_GO_AHEAD)
            ),
            author=author,
        )
        return True
