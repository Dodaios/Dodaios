"""Open questions the agent asked the person."""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import TYPE_CHECKING, Any

from dodaios.agent_chat import service as _s
from dodaios.agent_chat.credential_requests import (
    CredentialRequests,
)
from dodaios.agent_chat.questions import (
    QUESTION_TIMEOUT_S,
    QuestionAnswer,
    QuestionSpec,
)

if TYPE_CHECKING:
    from dodaios.agent_chat.service import _OpenQuestion


if TYPE_CHECKING:
    from dodaios.agent_chat.service_parts._host_state import AgentChatHostState as _HostBase
else:
    _HostBase = object


class QuestionsMixin(_HostBase):
    """Open questions the agent asked the person."""

    # ------------------------------------------------------------ questions

    async def open_questions(
        self,
        session_id: str,
        specs: tuple[QuestionSpec, ...],
        *,
        asker: str = "",
        timeout_s: float | None = QUESTION_TIMEOUT_S,
        rationed: bool = True,
    ) -> str:
        """Show ``specs`` as one card in the running turn; returns its question id.

        The card watches itself: whenever ``timeout_s`` passes without a new
        answer, every open question takes its recommendation (index 0). Each
        answer restarts that window, so a workflow behind this turn keeps
        moving but a person mid-series is never cut off. Closing the card
        applies the recommendations at once; a finished turn cancels it. Wait
        for the outcome with :meth:`wait_questions`.

        ``timeout_s=None`` waits for the person as long as it takes, and
        ``rationed=False`` lifts the cards-per-turn cap (a coding agent's own
        ``AskUserQuestion``, which asks as often in a terminal).

        Raises ``RuntimeError`` when the session has no running turn, and
        ``TooManyQuestions`` once the turn has used its cards.
        """
        run = self._running.get(session_id)
        if run is None or run.task is None or run.task.done():
            raise RuntimeError("this chat has no running turn to ask in")
        question_id = uuid.uuid4().hex
        loop = asyncio.get_running_loop()
        open_q = _s._OpenQuestion(session_id, run.turn_id, specs, loop.create_future())
        # A question the person already answered is never put to them again:
        # its answer comes back, and the card shows only what is still open.
        open_q.answers[:] = _s.recall(specs, self._answered(session_id, run.turn_id))
        if open_q.done:
            open_q.delivered = True
            open_q.result.set_result(list(open_q.answers))
            self._questions[question_id] = open_q
            return question_id
        if rationed and run.asks >= _s.MAX_ASKS_PER_TURN:
            raise _s.TooManyQuestions(f"this turn already asked {run.asks} times")
        run.asks += 1
        self._questions[question_id] = open_q
        await self._emit(
            session_id,
            _s.make_event(
                "question_required",
                {
                    "turn_id": run.turn_id,
                    "question_id": question_id,
                    "asker": asker,
                    "questions": [spec.to_payload() for spec in specs],
                    "timeout_s": timeout_s or 0,
                    "expires_ms": _s._expires_ms(timeout_s),
                },
            ),
        )
        task = asyncio.create_task(
            self._watch_question(open_q, question_id, timeout_s),
            name=f"agent-chat-question-{question_id[:8]}",
        )
        self._question_tasks.add(task)
        task.add_done_callback(self._question_tasks.discard)
        return question_id

    async def wait_questions(
        self, session_id: str, question_id: str, timeout_s: float | None = None
    ) -> list[QuestionAnswer] | None:
        """The card's answers once it closed; ``None`` while it is still open after ``timeout_s``.

        Raises ``KeyError`` for an unknown or foreign question id.
        """
        open_q = self._questions.get(question_id)
        if open_q is None or open_q.session_id != session_id:
            raise KeyError(question_id)
        try:
            answers = await asyncio.wait_for(asyncio.shield(open_q.result), timeout_s)
            open_q.delivered = True
            return answers
        except TimeoutError:  # still open: the caller polls again
            return None

    def question_specs(self, session_id: str, question_id: str) -> tuple[QuestionSpec, ...]:
        """The questions on card ``question_id``; raises ``KeyError`` when unknown."""
        open_q = self._questions.get(question_id)
        if open_q is None or open_q.session_id != session_id:
            raise KeyError(question_id)
        return open_q.specs

    def undelivered_questions(self, session_id: str, turn_id: str) -> list[str]:
        """Cards whose answers have not reached the runner, including just-answered ones."""
        return [
            qid
            for qid, q in self._questions.items()
            if q.session_id == session_id and q.turn_id == turn_id and not q.delivered
        ]

    async def ask_questions(
        self,
        session_id: str,
        specs: tuple[QuestionSpec, ...],
        *,
        asker: str = "",
        timeout_s: float | None = QUESTION_TIMEOUT_S,
        rationed: bool = True,
    ) -> list[QuestionAnswer]:
        """Open a card and wait until it closes (a caller with no call timeout)."""
        question_id = await self.open_questions(
            session_id, specs, asker=asker, timeout_s=timeout_s, rationed=rationed
        )
        answers = await self.wait_questions(session_id, question_id)
        assert answers is not None
        return answers

    async def _watch_question(
        self, open_q: _OpenQuestion, question_id: str, timeout_s: float | None
    ) -> None:
        loop = asyncio.get_running_loop()
        reported = 0
        forever = timeout_s is None
        window = timeout_s or 0.0
        deadline = loop.time() + window
        try:
            while not open_q.done:
                # Inspect stored answers before waiting. A click can arrive
                # before this watcher starts or while a progress event emits.
                open_q.wake.clear()
                answered = sum(a is not None for a in open_q.answers)
                touched, open_q.touched = open_q.touched, False
                if (answered > reported or touched) and not open_q.done:
                    reported = answered
                    deadline = loop.time() + window
                    await self._emit(
                        open_q.session_id,
                        _s.make_event(
                            "question_progress",
                            {
                                "turn_id": open_q.turn_id,
                                "question_id": question_id,
                                "answers": [a.to_payload() if a else None for a in open_q.answers],
                                "expires_ms": _s._expires_ms(timeout_s),
                            },
                        ),
                    )
                    continue
                remaining = None if forever else deadline - loop.time()
                if remaining is not None and remaining <= 0:
                    _s.log.info(
                        "agent chat: question %s in %s timed out; recommendations applied",
                        question_id,
                        open_q.session_id,
                    )
                    open_q.closing = _s.TIMEOUT
                    break
                try:
                    await asyncio.wait_for(open_q.wake.wait(), remaining)
                except TimeoutError:  # the loop re-reads the deadline and closes
                    continue
        except asyncio.CancelledError:
            # App shutdown: the card closes with the process.
            open_q.closing = _s.CANCELLED
            raise
        finally:
            answers = self._final_answers(open_q)
            if not open_q.result.done():
                open_q.result.set_result(answers)
            try:
                await self._emit(
                    open_q.session_id,
                    _s.make_event(
                        "question_resolved",
                        {
                            "turn_id": open_q.turn_id,
                            "question_id": question_id,
                            "answers": [a.to_payload() for a in answers],
                        },
                    ),
                )
            except Exception:  # noqa: BLE001 — the outcome is already delivered to the waiter
                _s.log.warning(
                    "agent chat: could not record question %s", question_id, exc_info=True
                )

    def _answered(self, session_id: str, turn_id: str) -> dict[Any, Any]:
        """The person's answers in this turn and within ``RECALL_WINDOW_S``."""
        found = _s.person_answers(
            self.store.list_events(session_id, tail=self._TURN_PROMPT_TAIL),
            turn_id=turn_id,
            since_ms=int((time.time() - _s.RECALL_WINDOW_S) * 1000),
        )
        for open_q in getattr(self, "_questions", {}).values():
            if open_q.session_id == session_id:
                _s.note_answers(found, open_q.specs, open_q.answers)
        return found

    def _final_answers(self, open_q: _OpenQuestion) -> list[QuestionAnswer]:
        source = open_q.closing or _s.TIMEOUT
        # A fallback never overrides what the person already answered elsewhere.
        earlier: list[QuestionAnswer | None] = [None] * len(open_q.specs)
        if source != _s.CANCELLED and any(a is None for a in open_q.answers):
            try:
                earlier = _s.recall(open_q.specs, self._answered(open_q.session_id, open_q.turn_id))
            except Exception:  # noqa: BLE001 — an unreadable log leaves the defaults
                _s.log.warning("agent chat: earlier answers unavailable", exc_info=True)
        answers: list[QuestionAnswer] = []
        for spec, answer, before in zip(open_q.specs, open_q.answers, earlier, strict=True):
            if answer is None:
                answer = (
                    _s.QuestionAnswer("", None, _s.CANCELLED)
                    if source == _s.CANCELLED
                    else before or _s.recommended_answer(spec, source)
                )
            answers.append(answer)
        return answers

    def _open_card(self, session_id: str, question_id: str) -> _OpenQuestion | None:
        open_q = getattr(self, "_questions", {}).get(question_id)
        if open_q is None or open_q.session_id != session_id or open_q.done:
            return None
        return open_q

    def resolve_question(
        self,
        session_id: str,
        question_id: str,
        *,
        index: int = 0,
        option_index: int | None = None,
        option_indices: list[int] | None = None,
        text: str | None = None,
        source: str = "person",
    ) -> bool:
        """The person's answer to question ``index`` of the card.

        ``source`` says who gave it when that is not the person (the assistant
        that handed the agent its work, ``questions.DELEGATOR``). False for an
        unknown, foreign, closed or already answered question. Raises
        ``ValueError`` for an answer that does not fit the question.
        """
        open_q = self._open_card(session_id, question_id)
        if open_q is None:
            return False
        if not 0 <= index < len(open_q.specs) or open_q.answers[index] is not None:
            return False
        open_q.answers[index] = _s.answer_from(
            open_q.specs[index],
            option_index=option_index,
            option_indices=option_indices,
            text=text,
            source=source,
        )
        open_q.wake.set()
        return True

    def submit_questions(
        self, session_id: str, question_id: str, answers: list[dict[str, Any]]
    ) -> bool:
        """The person's reviewed answers to the whole card, sent at once.

        One entry per question (``{option_index | option_indices | text | skip}``);
        a question already answered keeps its answer. All entries are checked
        before any is stored, so a bad one changes nothing. False for an
        unknown, foreign or closed card; ``ValueError`` for an answer that does
        not fit or a list of the wrong length.
        """
        open_q = self._open_card(session_id, question_id)
        if open_q is None:
            return False
        if len(answers) != len(open_q.specs):
            raise ValueError(f"send one answer per question ({len(open_q.specs)})")
        parsed = [
            current if current is not None else _s.answer_json(spec, raw)
            for spec, current, raw in zip(open_q.specs, open_q.answers, answers, strict=True)
        ]
        open_q.answers[:] = parsed
        open_q.wake.set()
        return True

    def skip_question(self, session_id: str, question_id: str, index: int | None = None) -> bool:
        """The person closed the card: every open question takes its recommendation.

        With ``index``, only that question is skipped: it resolves to an empty
        answer the agent decides on its own, and the rest of the card stays open.
        """
        open_q = self._open_card(session_id, question_id)
        if open_q is None:
            return False
        if index is not None:
            if not 0 <= index < len(open_q.specs) or open_q.answers[index] is not None:
                return False
            open_q.answers[index] = _s.declined_answer()
        else:
            open_q.closing = _s.SKIPPED
        open_q.wake.set()
        return True

    def touch_question(self, session_id: str, question_id: str) -> bool:
        """The person is answering on the card but has not sent it yet: the
        quiet window starts again, so a careful reader is never cut off."""
        open_q = self._open_card(session_id, question_id)
        if open_q is None:
            return False
        open_q.touched = True
        open_q.wake.set()
        return True

    async def answer_by_message(self, session_id: str, text: str) -> dict[str, Any]:
        """A chat message sent while a question card is open answers it.

        The newest open card takes the message as the answer to its current
        question (source ``message``); its other open questions, and every
        older open card, settle with their recommendations (``moved_on``)
        unless a question asked to stay open. Returns ``{"consumed": True}``
        when a running turn took the message as its answer, so the caller
        sends nothing else. An end-of-turn card is settled the same way, but
        ``consumed`` stays False: the message itself is what the agent reads
        next, so the caller sends it as usual.
        """
        typed = (text or "").strip()
        if not typed:
            return {"consumed": False, "question_id": None}
        live = [
            (qid, q)
            for qid, q in getattr(self, "_questions", {}).items()
            if q.session_id == session_id and not q.done
        ]
        if live:
            newest_id, newest = live[-1]
            for qid, open_q in live:
                current = _s._first_open(open_q.answers) if qid == newest_id else -1
                for index, spec in enumerate(open_q.specs):
                    if open_q.answers[index] is not None:
                        continue
                    if index == current:
                        open_q.answers[index] = _s._message_answer(spec, typed)
                    elif spec.dismiss_on_move_on:
                        open_q.answers[index] = _s.recommended_answer(spec, _s.MOVED_ON)
                open_q.wake.set()
            return {"consumed": True, "question_id": newest_id}
        async with self._turn_prompt_lock():
            card = _s.turn_prompts.newest_open_ask(
                self.store.list_events(session_id, tail=self._TURN_PROMPT_TAIL)
            )
            if card is None:
                return {"consumed": False, "question_id": None}
            current = _s._first_open(card.answers)
            final = [
                a
                if a is not None
                else _s._message_answer(spec, typed)
                if index == current
                else _s.recommended_answer(spec, _s.MOVED_ON)
                for index, (spec, a) in enumerate(zip(card.specs, card.answers, strict=True))
            ]
            await self._resolve_turn_question(session_id, card, final)
        return {"consumed": False, "question_id": card.question_id}

    def pending_questions(self, session_id: str) -> list[str]:
        return [
            qid for qid, q in self._questions.items() if q.session_id == session_id and not q.done
        ]

    def _cancel_questions(self, session_id: str) -> None:
        # Tolerates a service built without __init__ (test doubles), like _controls.
        credentials: CredentialRequests | None = getattr(self, "_credentials", None)
        if credentials is not None:
            credentials.finish_turn(session_id)
        questions: dict[str, _OpenQuestion] = getattr(self, "_questions", {})
        for qid, open_q in list(questions.items()):
            if open_q.session_id != session_id:
                continue
            if not open_q.done:
                open_q.closing = _s.CANCELLED
                open_q.wake.set()
            questions.pop(qid, None)
