"""``society_ask_user``: an agent asks the person up to four short questions.

Each question offers two to four prepared answers with the recommended one
first; the person taps an answer (or types their own) and the card walks
through the series as "question 1 of 3" (dodaios/agent_chat/questions.py).
A question may also let the person pick several answers (``kind: multi``) or
ask for their own words only (``kind: text``).
Three guarantees keep work moving and asking rare:

* When nobody answers for five minutes, the open questions take their
  recommendations, and the agent is told so. Closing the card does the same.
* At most four questions per call and two calls per turn; beyond that the
  agent gets its own recommendations back instead of another card.
* A routine never asks. Its chat is unattended by design, so the tool is not
  offered there (``society_tools``) and refuses to wait if called anyway.
"""

from __future__ import annotations

import logging
from typing import Any, Final

from dodaios.agent_chat import ask_gate
from dodaios.agent_chat.questions import (
    CANCELLED,
    DECLINED,
    KINDS,
    MAX_ASKS_PER_TURN,
    MAX_OPTIONS,
    MAX_QUESTIONS,
    MESSAGE,
    MIN_OPTIONS,
    MOVED_ON,
    QUESTION_TIMEOUT_S,
    RECALLED,
    SKIPPED,
    TIMEOUT,
    UNATTENDED,
    QuestionAnswer,
    QuestionSpec,
    TooManyQuestions,
    for_agent,
    parse_questions,
    recommended_answer,
)
from dodaios.agent_chat.secret_requests import asks_for_secret
from dodaios.core.protocols import ToolResult

from .routine_runner import is_routine_session

log = logging.getLogger(__name__)

__all__ = ["ASK_USER_TOOL_NAME", "AskUserTool"]

ASK_USER_TOOL_NAME: Final[str] = "society_ask_user"
_MINUTES: Final[int] = int(QUESTION_TIMEOUT_S // 60)

#: How long one call waits for the card. CLI seats drop an MCP call after
#: about a minute (Claude Code: 60 s), so the tool hands back a "still
#: waiting" result in time and the agent polls with ``wait_for``.
WAIT_SLICE_S: Final[float] = 45.0

_QUESTION_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "question": {
            "type": "string",
            "description": "The question, clear and specific, ending with a question mark.",
        },
        "kind": {
            "type": "string",
            "enum": list(KINDS),
            "description": (
                "single (default): one answer. multi: the user may pick several. "
                "text: the user writes the answer; options are optional suggestions."
            ),
        },
        "options": {
            "type": "array",
            "maxItems": MAX_OPTIONS,
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string", "description": "1-5 word answer."},
                    "description": {
                        "type": "string",
                        "description": "One short line: what choosing this means.",
                    },
                },
                "required": ["label"],
            },
            "description": (
                f"{MIN_OPTIONS}-{MAX_OPTIONS} answers, your recommendation FIRST "
                "(optional for kind text)."
            ),
        },
        "recommendation_reason": {
            "type": "string",
            "description": "One sentence: why the first option beats the runner-up.",
        },
    },
    "required": ["question", "recommendation_reason"],
}


class AskUserTool:
    """Ask the person a short series of questions with prepared answers."""

    name: str = ASK_USER_TOOL_NAME
    risk_tier: str = "safe"
    is_action_tool: bool = False
    description: str = (
        "Ask the user when a decision genuinely belongs to them: their taste, priorities, "
        "money, accounts, or an irreversible trade-off you cannot infer from the request, "
        "your instructions, memory or sensible defaults. Ask ONLY questions whose answer "
        "changes what you do; decide everything else yourself and say what you assumed. "
        f"Put all related questions into ONE call (at most {MAX_QUESTIONS}, fewer is "
        "better); the user answers them one after another. Each question offers "
        f"{MIN_OPTIONS}-{MAX_OPTIONS} concrete, mutually exclusive answers with your "
        "recommendation FIRST and recommendation_reason saying why it beats the "
        "runner-up; set kind 'multi' only when several answers can be combined. "
        "The user may also type their own answer. If nobody answers within "
        f"{_MINUTES} minutes, your recommendations are applied, so recommend the safest "
        "sensible choice. Never ask for permission to do what you were asked, never ask "
        "what you could look up, and never ask again what was already answered. "
        "Never ask for a token, key or password here: use society_request_credential. "
        f"A turn can show at most {MAX_ASKS_PER_TURN} question cards. While the user has "
        "not answered yet, the call returns status 'waiting' with a question_id: then call "
        "this tool again with only wait_for set to that id, and do nothing else meanwhile. "
        "A gate runs before any card: it answers from memory when memory already holds the "
        "answer, applies your recommendation when the pending action is reversible and you "
        "are confident, and asks ONE question at a time otherwise. Say what you are doing "
        "with pending_action (tool, action), confidence (0-1, your confidence in your "
        "recommendation) and missing_required (true when the action cannot run without the "
        "answer). A result with status not_asked means no card was shown: act on it, state "
        "the assumption in your reply and verify cheaply."
    )
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "questions": {
                "type": "array",
                "minItems": 1,
                "maxItems": MAX_QUESTIONS,
                "items": _QUESTION_SCHEMA,
                "description": "The questions, most important first. Usually just one.",
            },
            "pending_action": {
                "type": "object",
                "description": "The action this answer unblocks: tool and action name.",
                "properties": {
                    "tool": {"type": "string"},
                    "action": {"type": "string"},
                    "reversibility": {
                        "type": "string",
                        "enum": ["reversible", "recoverable", "irreversible"],
                    },
                },
            },
            "confidence": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
                "description": "Your confidence (0-1) that your recommended answer is right.",
            },
            "missing_required": {
                "type": "boolean",
                "description": "True when a required parameter of the action is missing.",
            },
            "wait_for": {
                "type": "string",
                "description": (
                    "Only to keep waiting on a card you already opened: the question_id from "
                    "a 'waiting' result. Send it alone, without questions."
                ),
            },
        },
    }

    def __init__(self, runtime: Any, agent_id: str, *, session_id: str) -> None:
        self._runtime = runtime
        self._agent_id = agent_id
        self._session_id = session_id
        #: Per open card: the specs of the call, the gate's decisions and the log rows.
        self._gated: dict[str, _Gated] = {}

    async def execute(self, args: dict[str, Any], ctx: Any) -> ToolResult:
        wait_for = str(args.get("wait_for") or "").strip()
        if wait_for:
            return await self._keep_waiting(wait_for)
        try:
            specs = parse_questions(args)
        except ValueError as exc:
            # Bad questions go back to the agent as the tool error to fix.
            return ToolResult(success=False, output=None, error=f"invalid questions: {exc}")
        if any(asks_for_secret(spec.question, value_only=True) for spec in specs):
            # A typed answer would carry the secret into the chat and the model.
            return ToolResult(
                success=False,
                output=None,
                error=(
                    "A question card never asks for a token, key or password: its answer is "
                    "plain chat text. Call society_request_credential instead; it opens a "
                    "secure field and its description can say where the user creates the "
                    "credential."
                ),
            )
        if is_routine_session(self._session_id):
            return _unattended(
                specs,
                "Routines run unattended and cannot ask the user. Your recommendations were "
                "applied; continue with them and mention the assumptions in your result.",
            )
        gate = self._gate(args, specs)
        if not gate.result.needs_card:
            return gate.finish(None)
        service = self._runtime.chat_service()
        if service is None or not callable(getattr(service, "open_questions", None)):
            return _unattended(specs, _NOBODY)
        asked = tuple(specs[i] for i in gate.result.ask_indices)
        try:
            question_id = await service.open_questions(self._session_id, asked, asker=self._asker())
        except TooManyQuestions:
            # The turn limit is reported to the agent in the returned result.
            return _unattended(
                specs,
                f"This turn already asked the user {MAX_ASKS_PER_TURN} times, so no card was "
                "shown. Your recommendations were applied: continue with them, decide any "
                "further questions yourself and list your assumptions in the reply.",
            )
        except RuntimeError as exc:
            # No running chat turn to show a card in (a background run): nobody
            # can answer, so the recommendations stand rather than a stall.
            log.info("society ask: %s cannot ask here (%s)", self._agent_id, exc)
            return _unattended(specs, _NOBODY)
        self._gated[question_id] = gate
        return await self._wait(service, question_id, asked)

    def _gate(self, args: dict[str, Any], specs: tuple[QuestionSpec, ...]) -> _Gated:
        """Run the ask-gate and log what it decided (never raises)."""
        pending = args.get("pending_action")
        pending = pending if isinstance(pending, dict) else {}
        confidence = args.get("confidence")
        confidence = (
            min(1.0, max(0.0, float(confidence)))
            if isinstance(confidence, (int, float)) and not isinstance(confidence, bool)
            else None
        )
        ctx = ask_gate.AskContext(
            confidence=confidence,
            reversibility=ask_gate.pending_reversibility(
                str(pending.get("tool") or "").strip(),
                str(pending.get("action") or "").strip(),
                str(pending.get("reversibility") or "").strip(),
            ),
            missing_required=args.get("missing_required") is True,
            clarify_enabled=self._clarify_enabled(),
        )
        result = ask_gate.decide(specs, ctx, _safe_search())
        row_ids: list[str] = []
        try:
            from dodaios.trust.ask_log import ask_log

            for spec, decision in zip(specs, result.decisions, strict=True):
                row_ids.append(
                    ask_log().record(
                        question=spec.question,
                        decision=decision.decision,
                        reason=decision.reason,
                        session_id=self._session_id,
                        agent_id=self._agent_id,
                        reversibility=ctx.reversibility,
                        confidence=ctx.confidence,
                        clarify_on=ctx.clarify_enabled,
                        answer=decision.answer.answer if decision.answer else "",
                        answer_source=decision.answer.source if decision.answer else "",
                    )
                )
        except Exception:  # noqa: BLE001 - measuring never blocks a question
            log.warning("ask gate: could not log the decisions", exc_info=True)
            row_ids = [""] * len(specs)
        return _Gated(specs, result, row_ids)

    def _clarify_enabled(self) -> bool:
        """The owner's ``voice.clarify_incomplete_enabled`` (default OFF)."""
        voice = getattr(getattr(self._runtime, "config", None), "voice", None)
        return getattr(voice, "clarify_incomplete_enabled", False) is True

    async def _keep_waiting(self, question_id: str) -> ToolResult:
        service = self._runtime.chat_service()
        try:
            specs = service.question_specs(self._session_id, question_id)
        except (AttributeError, KeyError):
            # Unknown question id is reported to the agent in the result.
            self._gated.pop(question_id, None)
            return ToolResult(
                success=False,
                output=None,
                error=(
                    "No open question card with that id in this chat (it closed with the "
                    "turn). Continue with your recommendations; do not ask again."
                ),
            )
        return await self._wait(service, question_id, specs)

    async def _wait(
        self, service: Any, question_id: str, specs: tuple[QuestionSpec, ...]
    ) -> ToolResult:
        answers = await service.wait_questions(self._session_id, question_id, WAIT_SLICE_S)
        if answers is None:
            return ToolResult(
                success=True,
                output={
                    "status": "waiting",
                    "question_id": question_id,
                    "note": (
                        "The user has not finished answering yet; the card stays open and "
                        f"applies your recommendations on its own after {_MINUTES} quiet "
                        "minutes. Call society_ask_user again now with only "
                        f'{{"wait_for": "{question_id}"}} to keep waiting. Do nothing else '
                        "meanwhile and do not ask anything new."
                    ),
                },
            )
        gate = self._gated.pop(question_id, None)
        return gate.finish(answers) if gate else _result(specs, answers)

    def _asker(self) -> str:
        cached = getattr(self._runtime, "cached_agent", None)
        agent = cached(self._agent_id) if callable(cached) else None
        return str(getattr(agent, "name", "") or "")


class _Gated:
    """One call after the gate: the specs, the decisions and the log rows."""

    def __init__(
        self, specs: tuple[QuestionSpec, ...], result: ask_gate.GateResult, row_ids: list[str]
    ) -> None:
        self.specs = specs
        self.result = result
        self.row_ids = row_ids

    def finish(self, asked: list[QuestionAnswer] | None) -> ToolResult:
        """Merge the owner's answer to the asked question into the gate's own answers."""
        answers: list[QuestionAnswer] = []
        pick = iter(asked or [])
        for i, decision in enumerate(self.result.decisions):
            if i in self.result.ask_indices:
                answer = next(pick, None) or recommended_answer(self.specs[i], UNATTENDED)
                self._learn(i, answer)
                answers.append(answer)
            elif decision.answer is not None:
                answers.append(decision.answer)
        out = _result(self.specs, answers)
        if not isinstance(out.output, dict):
            return out
        if not self.result.needs_card:
            out.output["status"] = "not_asked"
        notes = [
            f"{d.decision}: {d.reason}"
            + (f" (memory: {d.evidence})" if d.decision == ask_gate.FROM_MEMORY else "")
            for d in self.result.decisions
            if d.decision != ask_gate.ASK
        ]
        if notes:
            out.output["gate"] = notes
            out.output["note"] = f"{out.output.get('note') or ''} {_GATE_NOTE}".strip()
        return out

    def _learn(self, index: int, answer: QuestionAnswer) -> None:
        """Label a card as needless when memory held the answer or the owner says so."""
        from dodaios.trust.ask_log import ask_log, is_needless_signal

        if not (0 <= index < len(self.row_ids)) or not self.row_ids[index]:
            return
        needless = ""
        if answer.by_person and is_needless_signal(answer.answer):
            needless = "owner_said_so"
        elif answer.by_person:
            memory = ask_gate.recall_answer(self.specs[index], _safe_search())
            if memory and memory.answer and memory.answer.answer == answer.answer:
                needless = "in_memory"
        ask_log().mark_answer(
            self.row_ids[index], source=answer.source, answer=answer.answer, needless=needless
        )


def _safe_search() -> ask_gate.MemorySearch | None:
    try:
        return ask_gate.vault_search()
    except Exception:  # noqa: BLE001 - no vault means no memory answer, never a failed ask
        log.debug("ask gate: no memory search", exc_info=True)
        return None


_GATE_NOTE: Final[str] = (
    "Not asked (answered from memory, or your recommendation applied): state each assumption "
    "in your reply and verify it cheaply. One question at a time."
)

_NOBODY: Final[str] = (
    "Nobody can answer in this run. Your recommendations were applied; continue with "
    "them and mention the assumptions in your result."
)


def _unattended(specs: tuple[QuestionSpec, ...], note: str) -> ToolResult:
    answers = [recommended_answer(spec, UNATTENDED) for spec in specs]
    result = _result(specs, answers)
    result.output["note"] = note
    return result


def _result(specs: tuple[QuestionSpec, ...], answers: list[QuestionAnswer]) -> ToolResult:
    if any(a.source == CANCELLED for a in answers):
        return ToolResult(
            success=False,
            output={"answers": None, "source": CANCELLED},
            error="The user stopped this turn before answering. Do not continue the task.",
        )
    rows: list[dict[str, Any]] = []
    for spec, answer in zip(specs, answers, strict=True):
        row: dict[str, Any] = {
            "question": spec.question,
            "answer": answer.answer,
            "source": answer.source,
        }
        if answer.option_indices:
            row["picked"] = [spec.options[i].label for i in answer.option_indices]
        if answer.option_index is not None:
            row["recommended"] = answer.option_index == 0
            description = spec.options[answer.option_index].description
            if description:
                row["option_description"] = description
        elif answer.by_person and not answer.option_indices:
            row["typed"] = True
        row.update(for_agent(answer))
        rows.append(row)
    output: dict[str, Any] = {"answers": rows}
    sources = {a.source for a in answers}
    if TIMEOUT in sources:
        output["note"] = (
            f"The user did not answer for {_MINUTES} minutes, so your recommendations were "
            "applied to the open questions. The user did not choose them: continue with "
            "them and say you went with your default."
        )
    elif SKIPPED in sources:
        output["note"] = (
            "The user closed the card and left the open questions to you: your "
            "recommendations were applied. Continue without asking again."
        )
    elif MESSAGE in sources or MOVED_ON in sources:
        output["note"] = (
            "The user replied in the chat instead of on the card: read that message as "
            "their answer. Questions they did not address took your recommendations."
        )
    if sources == {RECALLED}:
        output["note"] = (
            "The user already answered these questions, so no new card was shown. "
            "Continue with their answers and do not ask again."
        )
    if DECLINED in sources:
        skipped = "The user skipped a question (empty answer): decide it yourself."
        output["note"] = f"{output['note']} {skipped}" if "note" in output else skipped
    return ToolResult(success=True, output=output)
