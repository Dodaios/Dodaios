"""Typing-only view of the host class for the mixins in this package.

The mixins read attributes the host `__init__` sets and call methods their
sibling mixins define. This class declares them so the type checker sees them.
It is imported under `TYPE_CHECKING` only; at run time the mixins derive from
`object` and nothing here exists.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from dodaios.agent_chat import turn_prompts
from dodaios.agent_chat.approval_bridge import ChatApprovalBridge
from dodaios.agent_chat.approval_defer import DeferredApprovals
from dodaios.agent_chat.control import ChatControls
from dodaios.agent_chat.credential_requests import CredentialRequests, CredentialSpec
from dodaios.agent_chat.parked_work import ParkedWorkBoard
from dodaios.agent_chat.questions import QuestionAnswer
from dodaios.agent_chat.service import _OpenQuestion, _Running
from dodaios.agent_chat.store import AgentChatStore
from dodaios.society.delivery import IncomingMessage


class AgentChatHostState:
    """Attributes and cross-mixin methods of the host, typed for checking only."""

    @property
    def _TURN_PROMPT_TAIL(self) -> int:
        raise NotImplementedError
    _always_allowed: dict[str, set[str]]
    _approval_call: dict[str, tuple[str, dict[str, Any]]]
    _approval_choice: dict[str, tuple[str, str, str]]
    _approval_edits: dict[str, dict[str, Any]]
    _approval_feedback: dict[str, str]
    _approval_session: dict[str, str]
    _approvals: dict[str, asyncio.Future[str]]
    _assistant_name: Callable[[], str]
    _brain_locks: dict[str, asyncio.Lock]
    _bridge: ChatApprovalBridge | None
    _bus: Callable[[], Any | None]
    _cli_rules: dict[str, list[dict[str, Any]]]
    _controls: ChatControls
    _credentials: CredentialRequests
    _default_cwd: Callable[[], str]
    _deny_feedback: dict[tuple[str, str], str]
    _held_for_reattach: set[str]
    _mirrored_voice_turns: set[str]
    _narrow_rules: dict[str, list[dict[str, str]]]
    _preparing: dict[str, _Running]
    _question_tasks: set[asyncio.Task[None]]
    _questions: dict[str, _OpenQuestion]
    _reattach_task: Any
    _ruled_on_agent: dict[str, set[str]]
    _running: dict[str, _Running]
    _steerers: dict[str, tuple[str, Callable[..., Awaitable[bool]]]]
    _subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]]
    _tool_always: dict[str, set[str]]
    _unanswered: dict[tuple[str, str, str], str]
    _voice_call_chats: dict[str, str]
    store: AgentChatStore

    async def _ask(self, session_id: str, turn_id: str, call_id: str, name: str, args: dict[str, Any], summary: str) -> str:
        raise NotImplementedError

    async def _await_finishing(self, session_id: str) -> None:
        raise NotImplementedError

    def _bridge_for(self, bus: Any | None) -> ChatApprovalBridge | None:
        raise NotImplementedError

    def _cancel_questions(self, session_id: str) -> None:
        raise NotImplementedError

    def _deliver_event(self, session_id: str, stored: dict[str, Any]) -> None:
        raise NotImplementedError

    async def _emit(self, session_id: str, event: dict[str, Any]) -> None:
        raise NotImplementedError

    def _keep_conversation(self, session_id: str, vendor: str) -> None:
        raise NotImplementedError

    async def _language_of_the_person(self, session_id: str, author: dict[str, str]) -> str:
        raise NotImplementedError

    def _may_be_hosted(self, session_id: str) -> bool:
        raise NotImplementedError

    async def _open_turn_prompts(self, session_id: str, turn_id: str, runner: str) -> None:
        raise NotImplementedError

    def _publish_event(self, session_id: str, event: dict[str, Any]) -> None:
        raise NotImplementedError

    def _publish_lock(self, session_id: str) -> asyncio.Lock:
        raise NotImplementedError

    def _refresh_picture_handoffs(self, session: Any) -> None:
        raise NotImplementedError

    async def _resolve_turn_question(self, session_id: str, card: turn_prompts.OpenAsk, answers: list[QuestionAnswer]) -> None:
        raise NotImplementedError

    @staticmethod
    def _restore_credential_save(session_id: str, spec: CredentialSpec, owner: str | None=...) -> Callable | None:
        raise NotImplementedError

    def _running_turn_id(self, session_id: str) -> str | None:
        raise NotImplementedError

    def _set_steerer(self, session_id: str, turn_id: str, writer: Callable[..., Awaitable[bool]] | None) -> None:
        raise NotImplementedError

    def _turn_prompt_lock(self) -> asyncio.Lock:
        raise NotImplementedError

    def always_allowed(self, session_id: str) -> set[str]:
        raise NotImplementedError

    def defer_open_approvals(self, session_id: str) -> int:
        raise NotImplementedError

    @property
    def deferred_approvals(self) -> DeferredApprovals:
        raise NotImplementedError

    def is_running(self, session_id: str) -> bool:
        raise NotImplementedError

    @property
    def parked_work(self) -> ParkedWorkBoard:
        raise NotImplementedError

    def pending_approvals(self, session_id: str) -> list[str]:
        raise NotImplementedError

    def running_session_ids(self) -> list[str]:
        raise NotImplementedError

    async def send(self, session_id: str, text: str, attachments: list[dict[str, Any]] | None=..., *, tool_choices: list[str] | None=..., incoming: IncomingMessage | None=..., direct_user: bool=..., read_only: bool=..., control_owned: bool=..., control_runner: Any=..., output_language: str=..., native_goal: bool=..., display_text: str | None=..., routine_run: bool=..., author: dict[str, str] | None=..., background_result: bool=...) -> str:
        raise NotImplementedError

    def take_deny_feedback(self, session_id: str, call_id: str) -> str:
        raise NotImplementedError
