"""Typing-only view of the host class for the mixins in this package.

The mixins read attributes the host `__init__` sets and call methods their
sibling mixins define. This class declares them so the type checker sees them.
It is imported under `TYPE_CHECKING` only; at run time the mixins derive from
`object` and nothing here exists.
"""
from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Iterable
from typing import Any
from uuid import UUID

from dodaios.brain.dispatcher import BrainDispatcher
from dodaios.brain.evidence_gate import EvidenceVerdict
from dodaios.brain.intent_router import RoutingDecision
from dodaios.brain.local_action_gate import LocalToolCall
from dodaios.brain.manager import _PendingVoiceConfirm
from dodaios.brain.rate_limit_tracker import RateLimitTracker
from dodaios.brain.turn_override import TurnOverride
from dodaios.control.cost import CostMeter
from dodaios.core.bus import EventBus
from dodaios.core.config import JarvisConfig
from dodaios.core.protocols import Brain, BrainMessage, ImageBlock, ReasoningEffort, Tool
from dodaios.memory.core_memory import CoreMemory
from dodaios.memory.curator.curator import Curator
from dodaios.memory.people import PersonStore
from dodaios.memory.user_profile import UserProfile
from dodaios.safety.tool_executor import ToolExecutor


class BrainHostState:
    """Attributes and cross-mixin methods of the host, typed for checking only."""

    _HISTORY_MAX: int
    _active_name: str
    _bus: EventBus
    _config: JarvisConfig
    _conversation_language: str
    _core_memory: CoreMemory | None
    _cost_meter: CostMeter | None
    _curator: Curator | None
    _dead_provider_models: set[tuple[str, str | None]]
    _dead_providers: set[str]
    _evidence_required_tool: Any
    _history: list[BrainMessage]
    _jarvis_agent_cancel_fn: Callable[[str | None], Awaitable[str]] | None
    _jarvis_agent_status_fn: Callable[[str | None], Awaitable[str]] | None
    _local_action_tools: dict[str, Tool]
    _pending_voice_confirm: _PendingVoiceConfirm | None
    _people: PersonStore | None
    _provider_down_idx: int
    _rate_tracker: RateLimitTracker
    _reply_language: str
    _skill_meta_turn: str
    _system_prompt_extra: str
    _tool_executor: ToolExecutor | None
    _tools: dict[str, Tool]
    _user_profile: UserProfile | None
    _voice_confirm_enabled: bool
    _pending_drop_images: tuple[ImageBlock, ...]
    _force_level: str | None
    _router_lead_key: tuple[str, str | None] | None

    def _active_turn_history(self) -> list[BrainMessage]:
        raise NotImplementedError

    def _agentic_ide_owns_turn(self, user_text: str) -> bool:
        raise NotImplementedError

    async def _apply_main_provider_switch(self, word: str) -> str:
        raise NotImplementedError

    def _apply_plugin_relevance(self, user_text: str, tools: dict[str, Tool]) -> dict[str, Tool]:
        raise NotImplementedError

    def _apply_reply_language_switch(self, code: str) -> str:
        raise NotImplementedError

    async def _apply_subagent_provider_switch(self, word: str) -> str:
        raise NotImplementedError

    def _apply_turn_override_tools(self, tools: dict[str, Tool] | None, override: TurnOverride) -> dict[str, Tool]:
        raise NotImplementedError

    def _arm_voice_confirm(self, descriptor: dict[str, Any], user_text: str) -> None:
        raise NotImplementedError

    def _brain_can_call_tools(self, provider: str, model: str | None) -> bool:
        raise NotImplementedError

    def _build_dispatcher(self, brain: Brain, *, tools_override: dict[str, Tool] | None=..., max_turns: int | None=..., deadline_s: float | None=..., reasoning_effort: ReasoningEffort | None=..., delegated_voice: bool=..., tool_context: dict[str, Any] | None=..., loop_control: Any=..., own_tools: Iterable[str]=..., direct_tools: frozenset[str] | None=...) -> BrainDispatcher:
        raise NotImplementedError

    def _build_fallback_chain(self, level: str) -> list[tuple[str, str | None]]:
        raise NotImplementedError

    def _build_tool_ack_emitter(self, user_text: str) -> Callable[[str, dict[str, Any]], Awaitable[None]] | None:
        raise NotImplementedError

    def _build_turn_context(self) -> str:
        raise NotImplementedError

    def _cancel_all_background_tasks(self) -> int:
        raise NotImplementedError

    def _cancel_readback(self, count: int) -> str:
        raise NotImplementedError

    def _check_unsupported_intent(self, user_text: str) -> str | None:
        raise NotImplementedError

    async def _collect_vision_images(self, *, trace_id: UUID, user_text: str=..., is_smalltalk: bool=...) -> tuple[ImageBlock, ...]:
        raise NotImplementedError

    def _consume_pending_skill_trigger(self, user_text: str) -> None:
        raise NotImplementedError

    def _contextual_routing_state(self, user_text: str, *, use_history: bool) -> tuple[str, tuple[str, ...]]:
        raise NotImplementedError

    def _cu_goal_with_context(self, goal: str) -> str:
        raise NotImplementedError

    def _depth_readback(self, level: str) -> str:
        raise NotImplementedError

    def _detect_cancel_intent(self, text: str) -> bool:
        raise NotImplementedError

    def _detect_depth_override(self, text: str) -> str | None:
        raise NotImplementedError

    def _detect_language_switch_intent(self, text: str) -> str | None:
        raise NotImplementedError

    def _detect_subagent_switch_intent(self, text: str) -> str | None:
        raise NotImplementedError

    def _detect_switch_intent(self, text: str) -> str | None:
        raise NotImplementedError

    def _direct_ack_language(self, user_text: str) -> str:
        raise NotImplementedError

    def _drop_run_skill_when_inline_injected(self, tools: Any) -> Any:
        raise NotImplementedError

    _evidence_directive: str

    def _fast_model(self, name: str) -> str | None:
        raise NotImplementedError

    async def _force_spawn_worker(self, user_text: str, *, trace_id: UUID | None=..., source_layer: str | None=...) -> str | None:
        raise NotImplementedError

    def _gate_screen_tool(self, tools: dict[str, Tool], *, user_text: str, has_image: bool, pointing_turn: bool=...) -> dict[str, Tool]:
        raise NotImplementedError

    def _get_brain(self, name: str, model: str | None=..., *, scope: str | None=...) -> Brain:
        raise NotImplementedError

    def _get_force_spawn_pattern(self) -> re.Pattern[str]:
        raise NotImplementedError

    def _get_routing_patterns(self) -> tuple[re.Pattern[str], re.Pattern[str], re.Pattern[str]]:
        raise NotImplementedError

    def _has_pending_screen_confirm(self, *, source_layer: str | None, conversation_id: str | None, allow_voice_confirm: bool) -> bool:
        raise NotImplementedError

    def _hide_action_tools_on_signalless_turn(self, tools: dict[str, Tool], user_text: str) -> dict[str, Tool]:
        raise NotImplementedError

    def _hide_agentic_ide_tools_without_workspace(self, tools: dict[str, Tool]) -> dict[str, Tool]:
        raise NotImplementedError

    def _hide_artifact_tool_without_request(self, tools: dict[str, Tool], user_text: str) -> dict[str, Tool]:
        raise NotImplementedError

    def _hide_run_skill_on_pc_control_turn(self, tools: dict[str, Tool], user_text: str) -> dict[str, Tool]:
        raise NotImplementedError

    @staticmethod
    def _hide_screenshot_for_blind_brain(tools: dict[str, Tool], brain: Any, *, prov_name: str=..., model: str | None=...) -> dict[str, Tool]:
        raise NotImplementedError

    def _hide_spawn_on_knowledge_question(self, tools: dict[str, Tool], user_text: str) -> dict[str, Tool]:
        raise NotImplementedError

    def _hide_spawn_when_plugin_tool_handles_turn(self, tools: dict[str, Tool], user_text: str) -> dict[str, Tool]:
        raise NotImplementedError

    def _hoist_tool_model(self, chain: list[tuple[str, str | None]]) -> list[tuple[str, str | None]]:
        raise NotImplementedError

    async def _honest_failure_readback(self, result: Any, *, user_text: str, situation: str, generic_key: str, reason_key: str, lang: str | None=...) -> str:
        raise NotImplementedError

    def _image_turn_tool_override(self) -> dict[str, Tool]:
        raise NotImplementedError

    def _is_explicit_heavy_request(self, user_text: str) -> bool:
        raise NotImplementedError

    @staticmethod
    def _is_lead_turn() -> bool:
        raise NotImplementedError

    def _is_pointer_intent(self, user_text: str) -> bool:
        raise NotImplementedError

    def _is_smalltalk(self, user_text: str) -> bool:
        raise NotImplementedError

    def _lead_vision_chain(self, chain: list[tuple[str, str | None]]) -> list[tuple[str, str | None]]:
        raise NotImplementedError

    def _live_tool_names(self) -> tuple[str, ...]:
        raise NotImplementedError

    def _localize_direct_ack(self, call: LocalToolCall, raw_output: str, lang: str) -> str:
        raise NotImplementedError

    def _match_skill_for_turn(self, user_text: str, lang: str=...) -> Any | None:
        raise NotImplementedError

    async def _maybe_dispatch_skill_mission(self, user_text: str, *, trace_id: UUID | None=...) -> str | None:
        raise NotImplementedError

    _memory_context_suffix: str

    @staticmethod
    def _override_dispatch_kwargs(override: TurnOverride | None) -> dict[str, Any]:
        raise NotImplementedError

    def _picked_level(self, user_text: str) -> RoutingDecision:
        raise NotImplementedError

    def _previous_user_turn_text(self, *, use_history: bool) -> str:
        raise NotImplementedError

    async def _provider_down_reply(self, trace_uuid: UUID, cause: str | None=...) -> str:
        raise NotImplementedError

    async def _publish_response_generated(self, *, trace_id: UUID, text: str) -> None:
        raise NotImplementedError

    def _recent_user_turn_texts(self, count: int, *, use_history: bool) -> tuple[str, ...]:
        raise NotImplementedError

    async def _record_response_side_effects(self, *, user_text: str, response_text: str, use_history: bool, trace_id: UUID | None=...) -> None:
        raise NotImplementedError

    def _render_skill_candidate_hint(self, user_text: str=...) -> str | None:
        raise NotImplementedError

    def _render_skill_turn_injection(self, user_text: str) -> str | None:
        raise NotImplementedError

    def _research_wants_artifact(self, t: str) -> bool:
        raise NotImplementedError

    async def _resolve_screen_context_turn(self, user_text: str, *, source_layer: str | None, conversation_id: str | None, allow_voice_confirm: bool, trace_id: UUID) -> Any:
        raise NotImplementedError

    def _resolve_turn_lang(self) -> str:
        raise NotImplementedError

    async def _resume_voice_confirm(self, user_text: str) -> str | None:
        raise NotImplementedError

    async def _run_agentic_ide_close_fast_path(self, user_text: str, *, trace_id: UUID | None=...) -> str | None:
        raise NotImplementedError

    async def _run_agentic_ide_fast_path(self, user_text: str, *, trace_id: UUID | None=..., consume_pending_voice_attachments: bool=...) -> str | None:
        raise NotImplementedError

    async def _run_agentic_ide_spawn_fast_path(self, user_text: str, *, trace_id: UUID | None=...) -> str | None:
        raise NotImplementedError

    def _run_evidence_gate(self, user_text: str) -> EvidenceVerdict:
        raise NotImplementedError

    async def _run_local_action_fast_path(self, user_text: str, *, trace_id: UUID | None=...) -> str | None:
        raise NotImplementedError

    async def _run_navigation_fast_path(self, user_text: str, *, trace_id: UUID | None=...) -> str | None:
        raise NotImplementedError

    async def _run_society_inventory_fast_path(self, user_text: str, *, trace_id: UUID | None=...) -> str | None:
        raise NotImplementedError

    def _skill_stand_downs_allowed(self) -> bool:
        raise NotImplementedError

    _skill_turn_match: Any | None

    def _smalltalk_tool_override(self) -> dict[str, Tool]:
        raise NotImplementedError

    def _spoken_reply_language(self, user_text: str) -> str:
        raise NotImplementedError

    def _start_pointer_task(self, user_text: str, is_smalltalk_turn: bool):
        raise NotImplementedError

    def _suppress_plugins_covered_by_cli(self, tools: dict[str, Tool], user_text: str=...) -> dict[str, Tool]:
        raise NotImplementedError

    def _turn_has_action_intent(self, user_text: str) -> bool:
        raise NotImplementedError

    def _update_turn_language(self, user_text: str) -> None:
        raise NotImplementedError

    @staticmethod
    async def _vault_recall(user_text: str) -> str:
        raise NotImplementedError

    @property
    def force_spawn_mode(self) -> str:
        raise NotImplementedError
