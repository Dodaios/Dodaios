"""The untagged generate loop: one full brain turn with tool rounds."""
from __future__ import annotations

import asyncio
import base64
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from dodaios.brain import manager as _m
from dodaios.brain import provider_health_ledger as _health_ledger
from dodaios.brain import seat_health as _seat_health
from dodaios.brain.action_honesty import (
    has_unbacked_action_claim,
    replace_unbacked_action_claim,
)
from dodaios.brain.local_action_gate import LocalActionMode
from dodaios.brain.manager import (
    _DELEGATE_DEADLINE_S,
    _DELEGATE_MAX_TURNS,
    _DELEGATE_REASONING_EFFORT,
    _DESKTOP_ACTION_TOOL_NAMES,
    _MID_ANSWER_ERROR_PHRASES,
    _REPLY_LANG_NAMES,
    _SPAWN_TOOL_NAMES,
    _TURN_HISTORY_OVERRIDE,
    _TURN_OVERRIDE,
    _conversational_turn_suppresses_read_mandate,
    _estimate_usd_from_usage,
    _primary_provider_down_cause,
    _turn_cost_usd,
    _turn_phrase_language,
    _unfulfilled_replacement,
    log,
)
from dodaios.brain.mission_command_gate import match_mission_command
from dodaios.core.events import BrainProviderSwitched, BrainTurnCompleted, BrainTurnStarted
from dodaios.core.protocols import BrainMessage, CostRecord, ImageBlock
from dodaios.core.turn_language import TURN_LANGUAGE
from dodaios.i18n import catalog as i18n_catalog
from dodaios.i18n.locales import is_known_language

if TYPE_CHECKING:
    from dodaios.brain.manager_parts._host_state import BrainHostState as _HostBase
else:
    _HostBase = object


class _TurnLoopMixin(_HostBase):
    """The untagged generate loop: one full brain turn with tool rounds."""

    async def _generate_untagged(
        self,
        user_text: str,
        *,
        use_history: bool = True,
        trace_id: UUID | None = None,
        text_consumer: Callable[[str], None] | None = None,
        on_progress: Callable[[], None] | None = None,
        source_layer: str | None = None,
        conversation_id: str | None = None,
        allow_voice_confirm: bool = False,
        prefer_tool_model: bool = False,
        emit_tool_ack: bool = True,
        force_output_language: str | None = None,
        consume_pending_voice_attachments: bool = False,
        language_text: str | None = None,
    ) -> str:
        # 1. Intercept meta-commands (cancel, switch, depth override).
        # User request 2026-04-25: no standardised confirmation phrases
        # ("OK, ich wechsle auf X", "Abgebrochen ..."). State changes remain
        # functional; feedback runs visually via bus events
        # (BrainProviderSwitched) or UI indicators. The pipeline stays silent
        # on empty responses (see pipeline.py:937).
        # AD-OE6 zero-silent-drop signal: reset per turn. Only the
        # failure-diagnostic returns below flip it True; the meta-command
        # early-returns ("") that follow correctly leave it False.
        self._last_turn_all_failed = False
        self._last_turn_suppressed = False
        self._last_turn_executed_action_tool = False
        # Clear last turn's provider identity so a helper prompt build before the
        # fallback loop (wiki-delta base) does not carry a stale provider name.
        self._active_turn_identity = None
        turn_trace_id = trace_id or uuid4()

        # Tool-surface self-heal (live 2026-07-13): a source that connects
        # AFTER the boot's last BrainToolsChanged — or whose event is lost to a
        # wedged plugin bootstrap — otherwise stays invisible for the WHOLE
        # session and the model refuses with "tool not available". Cheap
        # names-only drift check against the live CLI/plugin/MCP caches; one
        # refresh_tools() when they diverge. Never raises.
        from dodaios.brain.tool_surface import reconcile_tool_surface_async

        await reconcile_tool_surface_async(self)

        # Conversation use, never app boot: load the persistent team before
        # planning or building the first prompt, even if Agents was never opened.
        from dodaios.brain.factory import prepare_society_context

        await prepare_society_context()

        # auto mode: resolve this turn's language so _reply_language_directive()
        # hard-pins it (a soft "mirror" drifts to German on tool-synthesis
        # turns — live bug 2026-06-14: an English weather turn answered in
        # German). Conversation stickiness: a thin interjection ("Now") inherits
        # the running conversation language instead of flipping it (forensic
        # 2026-06-18); ambiguous text stays "unknown" -> soft mirror; an explicit
        # reply_language pin leaves it empty -> the directive uses the pin.
        self._update_turn_language(user_text if language_text is None else language_text)

        # Realtime-delegate language override (live 2026-07-23): the realtime
        # session is the ONE authoritative resolver for a voice turn — its own
        # model reply and the recorded jarvis_lang already consume that decision.
        # A delegated jarvis_action turn must speak the SAME language instead of
        # re-deriving it here from a possibly code-switched transcript, which let
        # an English realtime conversation answer a memory-save turn in German
        # ("Notiert ..."). Pin the caller-forced language so
        # _reply_language_directive() hard-locks it; an explicit
        # brain.reply_language pin still wins (checked first in that directive).
        if (
            is_known_language(force_output_language)
            and self._reply_language not in _REPLY_LANG_NAMES
        ):
            self._turn_detected_lang = force_output_language
            if TURN_LANGUAGE.get() is not None:
                TURN_LANGUAGE.set(force_output_language)

        # Two-turn voice/chat confirmation resume (turn N+1). MUST run before the
        # cancel-intent intercept: a "nein"/"stop" answer to a pending
        # confirmation is a VETO of that one action, not a global cancel-all.
        # Returns the spoken outcome (turn consumed) or None (user moved on →
        # the pending action is dropped and this utterance runs as a normal turn).
        screen_context = None
        if self._pending_voice_confirm is not None:
            resumed = await self._resume_voice_confirm(user_text)
            if resumed is not None:
                await self._record_response_side_effects(
                    user_text=user_text, response_text=resumed,
                    use_history=use_history, trace_id=turn_trace_id,
                )
                return resumed

        # A veto such as "stop" belongs to the pending one-shot look, not to
        # the global cancel-all gate below. Resolve only an already-armed,
        # conversation-scoped proposal here; ordinary turns still take the
        # cheap classifier at the normal Screen Context integration point.
        if self._has_pending_screen_confirm(
            source_layer=source_layer,
            conversation_id=conversation_id,
            allow_voice_confirm=allow_voice_confirm,
        ):
            screen_context = await self._resolve_screen_context_turn(
                user_text,
                source_layer=source_layer,
                conversation_id=conversation_id,
                allow_voice_confirm=allow_voice_confirm,
                trace_id=turn_trace_id,
            )
            if screen_context.ends_the_turn:
                screen_reply = screen_context.question or screen_context.message or ""
                await self._record_response_side_effects(
                    user_text=user_text,
                    response_text=screen_reply,
                    use_history=use_history,
                    trace_id=turn_trace_id,
                )
                return screen_reply

        if self._detect_cancel_intent(user_text):
            confirmation = self._cancel_readback(self._cancel_all_background_tasks())
            await self._record_response_side_effects(
                user_text=user_text,
                response_text=confirmation,
                use_history=use_history,
                trace_id=turn_trace_id,
            )
            return confirmation

        society_reply = await self._run_society_inventory_fast_path(
            user_text, trace_id=turn_trace_id,
        )
        if society_reply is not None:
            await self._record_response_side_effects(
                user_text=user_text, response_text=society_reply,
                use_history=use_history, trace_id=turn_trace_id,
            )
            return society_reply

        # An addressed Agentic-IDE pane outranks every self-configuration gate
        # below — the same precedence the desktop gate already honours further
        # down (``_agentic_ide_owns_turn`` there), applied here because the
        # config gates run FIRST and therefore get the only chance to be wrong.
        #
        # Live 2026-07-28 20:34, coding mode on, six panes open: a spoken
        # order to brief two of them was claimed by the reply-language gate on
        # three unrelated words scattered across the utterance. It applied the
        # setting and returned, so ``_run_agentic_ide_fast_path`` below never
        # ran and no agent was briefed — while the live model, which is told
        # none of this, reported both as working. The gate's own proximity
        # bound (``voice_command_gate._match_language_switch``) is the first
        # fix; this is the second, because a config gate winning a turn that
        # NAMES A RUNNING AGENT is wrong however plausible its match looked —
        # briefing an agent and changing a setting are not things a user can
        # mean at the same time.
        #
        # Deliberately NOT applied to the cancel intercept above: stopping work
        # is a safety control and must keep working under every phrasing.
        # Cheap enough for the hot path — an in-memory regex sweep, no IO and
        # no model call (AP-9/AP-11) — and it answers "no" on any fault.
        ide_owns_turn = self._agentic_ide_owns_turn(user_text)

        switch_target = (
            None if ide_owns_turn else self._detect_switch_intent(user_text)
        )
        if switch_target:
            confirmation = await self._apply_main_provider_switch(switch_target)
            if confirmation:
                await self._record_response_side_effects(
                    user_text=user_text,
                    response_text=confirmation,
                    use_history=use_history,
                    trace_id=turn_trace_id,
                )
                return confirmation

        # Deterministic reply-language switch — runs BEFORE the force-spawn
        # heuristic so "stell auf Englisch um" sets brain.reply_language
        # directly (live + persisted) instead of being dispatched as a worker
        # mission (2026-06-22 forensic). Provider-independent: no LLM tool-call.
        lang_switch = (
            None if ide_owns_turn else self._detect_language_switch_intent(user_text)
        )
        if lang_switch:
            confirmation = self._apply_reply_language_switch(lang_switch)
            if confirmation:
                await self._record_response_side_effects(
                    user_text=user_text,
                    response_text=confirmation,
                    use_history=use_history,
                    trace_id=turn_trace_id,
                )
                return confirmation

        # Deterministic sub-agent (Heavy-Task worker) provider switch — same
        # reasoning as the language switch: runs BEFORE the force-spawn/LLM path
        # so "switch the sub-agent provider to X" sets brain.sub_jarvis.provider
        # directly instead of escalating to a worker mission (2026-06-22 forensic).
        subagent_switch = (
            None if ide_owns_turn else self._detect_subagent_switch_intent(user_text)
        )
        if subagent_switch:
            confirmation = await self._apply_subagent_provider_switch(subagent_switch)
            if confirmation:
                await self._record_response_side_effects(
                    user_text=user_text,
                    response_text=confirmation,
                    use_history=use_history,
                    trace_id=turn_trace_id,
                )
                return confirmation

        depth_override = (
            None if ide_owns_turn else self._detect_depth_override(user_text)
        )
        if depth_override in ("deep", "fast"):
            self._force_level = depth_override
            confirmation = self._depth_readback(depth_override)
            await self._record_response_side_effects(
                user_text=user_text,
                response_text=confirmation,
                use_history=use_history,
                trace_id=turn_trace_id,
            )
            return confirmation

        # AD-12 + AP-OC5 (Jarvis-Agent bridge wave-4 router): intercept status/cancel
        # phrases via pattern match BEFORE the force-spawn heuristic
        # misinterprets them as action verbs ("brich ab" contains the verb 'ab'
        # and would otherwise trigger a new spawn). Pattern-match-first is
        # mandatory — no LLM hallucination risk on "laeuft das noch?".
        oc_match = match_mission_command(user_text)
        if oc_match is not None:
            log.info(
                "Mission command recognized: intent=%s id=%s lang=%s text=%r",
                oc_match.intent,
                oc_match.mission_id,
                oc_match.language,
                user_text[:120],
            )
            if (
                oc_match.intent == "status"
                and self._jarvis_agent_status_fn is not None
            ):
                response = await self._jarvis_agent_status_fn(oc_match.mission_id)
                await self._record_response_side_effects(
                    user_text=user_text,
                    response_text=response,
                    use_history=use_history,
                    trace_id=turn_trace_id,
                )
                return response
            if (
                oc_match.intent == "cancel"
                and self._jarvis_agent_cancel_fn is not None
            ):
                response = await self._jarvis_agent_cancel_fn(oc_match.mission_id)
                await self._record_response_side_effects(
                    user_text=user_text,
                    response_text=response,
                    use_history=use_history,
                    trace_id=turn_trace_id,
                )
                return response
            # Pattern matched, but no handler registered — fall through to
            # the normal path. Logging aids debugging ("why does the status
            # read still spawn?": handlers not wired).
            log.warning(
                "Mission command match without a handler — fallback to "
                "the normal generate path. Bootstrap must call "
                "set_mission_command_handlers()."
            )

        routing_text, contextual_tool_names = self._contextual_routing_state(
            user_text, use_history=use_history,
        )

        # Skill-aware routing guard (AD-S3): probe ONCE per turn, before any
        # fast path can grab the utterance. "starte die Morgenroutine" is an
        # is_open_app_intent hit AND a spawn-verb hit — without this early
        # probe the skill never gets a chance (the root cause of "Jarvis
        # never calls a skill"). Overwritten on every turn.
        self._skill_turn_match = self._match_skill_for_turn(user_text)
        # Evidence-gate state is strictly per-turn — a stale directive must
        # never leak into a later prompt build (e.g. a skill turn that
        # early-returns before the gate runs).
        self._evidence_directive = ""
        self._evidence_required_tool = ""
        self._evidence_required_is_write = False
        self._evidence_required_domain = ""
        self._public_fact_prefetched = False
        # AD-S4: a trigger noted by the speech pipeline / chat hook takes
        # precedence — it carries the captured content and the source label.
        self._consume_pending_skill_trigger(user_text)
        if self._skill_turn_match is None and routing_text != user_text:
            # Match the prior utterance independently before trying the
            # composite routing context. Whole-utterance (``^...$``) plugin
            # skill triggers cannot match the wrapper by design, yet they
            # still own an explicitly referential follow-up.
            previous_text = self._previous_user_turn_text(use_history=use_history)
            if previous_text:
                self._skill_turn_match = self._match_skill_for_turn(previous_text)
            if self._skill_turn_match is None:
                self._skill_turn_match = self._match_skill_for_turn(routing_text)
            if self._skill_turn_match is not None:
                self._skill_turn_source = "continuation"
        # AD-S9: an explicit heavy-work trigger ("Sub-Agent", "Jarvis-Agent",
        # "spawne", "deep dive", …) names the execution vehicle — the mission
        # path owns such a turn, not the inline skill prompt. Live bug
        # 2026-06-10 14:34: "spawne einen Sub-Agent … Gmail …" became a mute
        # inline gmail-skill turn instead of a mission.
        if (
            self._skill_turn_match is not None
            and self._is_explicit_heavy_request(user_text)
        ):
            log.info(
                "Skill match %s stands down — explicit heavy-work trigger in "
                "the utterance wins (AD-S9: mission, not inline skill).",
                getattr(self._skill_turn_match, "name", "?"),
            )
            self._skill_turn_match = None

        # Sibling of AD-S9: a plugin/marketplace skill that merely keyword-
        # matched an APP NAME ("Discord", "Spotify", "Slack") must NOT capture a
        # turn the deterministic desktop-control gate owns. Computer-Use is the
        # universal GUI integration — "open Discord and find the post on screen"
        # must reach it even when the plugin's API/MCP integration is absent,
        # instead of suppressing the local-action fast path and falling through
        # to a tool-less CLI talker that hallucinates a permissions refusal.
        # Live bug 2026-06-21 (sessions.db turn 67276501-…): plugin-discord
        # matched the bare word "Discord", the antigravity deep brain (a CLI
        # talker that drops all tools) then said "ich habe keinen Zugriff auf
        # Discord". The gate decision is authoritative and precise: only a
        # DIRECT open or a COMPUTER_USE plan stands the skill down — a pure
        # dispatch ("schick eine Discord-Nachricht", gate → None/UNSUPPORTED)
        # keeps its skill, and a non-app skill turn ("starte die Morgenroutine",
        # gate → None) is untouched.
        if self._skill_turn_match is not None:
            _gate_plan = _m.match_local_action(
                user_text,
                lang=self._spoken_reply_language(user_text),
                live_tool_names=self._live_tool_names(),
            )
            _claiming = _gate_plan is not None and _gate_plan.mode in (
                LocalActionMode.DIRECT,
                LocalActionMode.COMPUTER_USE,
            )
            # A relevance-channel match that is not instruction-only yields to
            # the desktop gate on ANY plan, not just a claiming one. The author
            # of a trigger asked for their phrase to win, so trigger matches keep
            # the narrower historical rule verbatim — this widening is additive
            # and applies only to the new, inferred channel, where nobody stated
            # an intent for the skill to beat local control.
            if not _claiming and _gate_plan is not None and not self._skill_stand_downs_allowed():
                _claiming = True
            if _claiming and _gate_plan is not None:
                log.info(
                    "Skill match %s stands down — the deterministic local-action "
                    "gate claims this turn as %s; Computer-Use owns it "
                    "(universal GUI integration, not a keyword-matched plugin).",
                    getattr(self._skill_turn_match, "name", "?"),
                    _gate_plan.mode.value,
                )
                self._skill_turn_match = None
        if self._skill_turn_match is not None:
            log.info(
                "Skill-matched turn: %r → skill %s (fast paths stand down)",
                user_text[:80],
                getattr(self._skill_turn_match, "name", "?"),
            )
            # AD-S5: mission skills never run inline — dispatch the worker
            # with the rendered instructions as the brief and return the
            # optimistic ACK. Falls through to the inline path when the
            # dispatch is not possible (AD-OE6: no silent drop).
            mission_reply = await self._maybe_dispatch_skill_mission(
                user_text, trace_id=turn_trace_id,
            )
            if mission_reply is not None:
                await self._record_response_side_effects(
                    user_text=user_text,
                    response_text=mission_reply,
                    use_history=use_history,
                    trace_id=turn_trace_id,
                )
                return mission_reply

        # Screen Context is a one-shot, explicit look request. It must run on
        # the production BrainManager path before desktop-action routing: an
        # ambiguous request asks first, a privacy refusal shuts every alternate
        # screen path, and a successful capture owns the visual part of the turn.
        if screen_context is None:
            screen_context = await self._resolve_screen_context_turn(
                user_text,
                source_layer=source_layer,
                conversation_id=conversation_id,
                allow_voice_confirm=allow_voice_confirm,
                trace_id=turn_trace_id,
            )
        if screen_context.ends_the_turn:
            screen_reply = screen_context.question or screen_context.message or ""
            await self._record_response_side_effects(
                user_text=user_text,
                response_text=screen_reply,
                use_history=use_history,
                trace_id=turn_trace_id,
            )
            return screen_reply

        # An addressed Agentic-IDE terminal outranks the desktop gate — the
        # mirror image of the skill stand-down just above, and for the same
        # reason: whichever gate holds the MORE SPECIFIC evidence wins.
        #
        # Live bug 2026-07-26 09:44 (coding mode on, twelve panes open): "let
        # Bruno do a deep dive and look into why you cannot paste text in the
        # Agentic IDE" reached Computer-Use, which clicked into the workspace's
        # own chat box and typed a prompt there — Jarvis operating its own UI by
        # hand while the agent named in the sentence sat idle. The gate had
        # matched the GUI verb "kopieren", a word that appears in that sentence
        # as the DESCRIPTION of a bug, never as an order to copy anything. A
        # single-verb matcher cannot tell "copy this" from "copying is broken",
        # whereas naming a running pane is unambiguous.
        #
        # ``owns_turn`` is the shared precedence the force-spawn guard and the
        # spawn gate already consult (it stands down by itself when the user
        # names the background-worker vehicle), so this third consumer cannot
        # drift away from them. The turn is not answered here — it simply stays
        # available for the Agentic-IDE fast path a few lines below.
        if (
            not screen_context.has_image
            and self._skill_turn_match is None
            and not self._agentic_ide_owns_turn(user_text)
        ):
            local_action = await self._run_local_action_fast_path(
                user_text, trace_id=turn_trace_id,
            )
            if local_action is not None:
                await self._record_response_side_effects(
                    user_text=user_text,
                    response_text=local_action,
                    use_history=use_history,
                    trace_id=turn_trace_id,
                )
                return local_action

        # Navigation fast-path: a clear "go to section X" command moves the UI
        # deterministically (a dumb action, AD-OE3). Placed BEFORE the capability
        # gate — which would refuse "zeig die Socials" because 'social' is an
        # external-integration marker — and before force-spawn. Pure regex, no
        # LLM (AP-11). See ADR-0011 amendment "Navigate tool".
        nav_reply = await self._run_navigation_fast_path(
            user_text, trace_id=turn_trace_id,
        )
        if nav_reply is not None:
            await self._record_response_side_effects(
                user_text=user_text,
                response_text=nav_reply,
                use_history=use_history,
                trace_id=turn_trace_id,
            )
            return nav_reply

        # Agentic-IDE fleet close: "close all Codex terminals" is a concrete
        # workspace action, not a question for the router to interpret. It runs
        # before addressed delivery so the word "all" cannot become a prompt
        # sent into the very panes the user asked to stop.
        ide_close_reply = await self._run_agentic_ide_close_fast_path(
            user_text, trace_id=turn_trace_id,
        )
        if ide_close_reply is not None:
            await self._record_response_side_effects(
                user_text=user_text,
                response_text=ide_close_reply,
                use_history=use_history,
                trace_id=turn_trace_id,
            )
            return ide_close_reply

        # Agentic-IDE fast-path: an instruction aimed at a named terminal of the
        # open coding workspace is DELIVERED to that terminal, deterministically.
        # Placed before force-spawn — whose depth-marker hoist used to swallow
        # exactly these turns (live bug 2026-07-25: "let Kai do a deep dive"
        # dispatched a background mission while Kai sat idle) — and before the
        # capability gate. Placed AFTER navigation so a section command still
        # moves the UI even when a pane happens to share that word. Returns None
        # on every turn that does not address a terminal.
        # Image-based assignments must reach workspace-orchestrate's scoped
        # selection and materialization boundary, not the text-only fast paths.
        from dodaios.core.image_references import get_store as image_reference_store
        from dodaios.core.image_references import scope_for

        visual_assignment = (
            screen_context.has_image
            or bool(getattr(self, "_pending_turn_images", {}).get(turn_trace_id))
            or bool(getattr(self, "_pending_drop_images", ()))
            or "Visual reference IDs" in user_text
            or bool(image_reference_store().available(
                scope_for(trace_id=turn_trace_id), fresh_only=True
            ))
        )
        ide_reply = None if visual_assignment else await self._run_agentic_ide_fast_path(
            user_text,
            trace_id=turn_trace_id,
            consume_pending_voice_attachments=consume_pending_voice_attachments,
        )
        if ide_reply is not None:
            await self._record_response_side_effects(
                user_text=user_text,
                response_text=ide_reply,
                use_history=use_history,
                trace_id=turn_trace_id,
            )
            return ide_reply

        # Agentic-IDE pane spawn: "spawn five more Claude Code terminals" opens
        # five panes instead of dispatching a background mission. Same reason to
        # be deterministic and to sit ahead of force-spawn as the path above —
        # the utterance NAMES the spawn vehicle, so nothing but a narrower
        # deterministic rule can keep it in the workspace. Runs after the
        # addressed-terminal path because ``detect_spawn`` stands down for an
        # addressed pane ("sag Mika, sie soll ein Terminal öffnen" is Mika's
        # work), which makes the two mutually exclusive by construction.
        ide_spawn_reply = (
            None if visual_assignment else await self._run_agentic_ide_spawn_fast_path(
                user_text, trace_id=turn_trace_id,
            )
        )
        if ide_spawn_reply is not None:
            await self._record_response_side_effects(
                user_text=user_text,
                response_text=ide_spawn_reply,
                use_history=use_history,
                trace_id=turn_trace_id,
            )
            return ide_spawn_reply

        # Agent-C (capability-coupling): pre-generation capability gate.
        # If the utterance looks like an action request but no registered
        # capability covers it, return a deterministic "not supported" reply
        # and skip both brain and the Jarvis-Agent worker.  No LLM call, no latency cost
        # (AP-11 compliant — pure regex + registry lookup).
        # AD-S3: a matched skill IS the capability — the unsupported-intent
        # refusal must not fire on a skill turn.
        unsupported = (
            None
            if self._skill_turn_match is not None or screen_context.has_image
            else self._check_unsupported_intent(user_text)
        )
        if unsupported is not None:
            await self._record_response_side_effects(
                user_text=user_text,
                response_text=unsupported,
                use_history=use_history,
                trace_id=turn_trace_id,
            )
            return unsupported

        # Persona mandate phase 3: deterministic force-spawn heuristic before
        # the LLM tool-use loop. Prevents spawn reflex on ambiguous smalltalk
        # inputs (see docs/persona-research.md section 2 — 60% empty smalltalk
        # outputs from the reflexive LLM spawn path).
        if screen_context.has_image:
            forced_spawn = None
        elif (
            contextual_tool_names
            and not self._is_explicit_heavy_request(user_text)
            and not self._research_wants_artifact(user_text)
        ):
            log.info(
                "Force-spawn stood down for contextual live tool(s): %s",
                ", ".join(contextual_tool_names),
            )
            forced_spawn = None
        elif (
            _TURN_OVERRIDE.get() is not None
            and not _TURN_OVERRIDE.get().allow_force_spawn  # type: ignore[union-attr]
            and not self._is_explicit_heavy_request(user_text)
        ):
            # A caller-picked turn (the typed chat) IS the worker in its folder:
            # the heuristic must not hand its work to a background mission. An
            # explicit "spawn an agent for this" still spawns.
            forced_spawn = None
        else:
            forced_spawn = await self._force_spawn_worker(
                user_text, trace_id=turn_trace_id, source_layer=source_layer,
            )
        if forced_spawn is not None:
            # Bug fix 2026-04-30: history update also in the force-spawn path.
            # Previously returned directly → main Jarvis had no memory on the
            # NEXT turn that this question was ever asked.
            await self._record_response_side_effects(
                user_text=user_text,
                response_text=forced_spawn,
                use_history=use_history,
                trace_id=turn_trace_id,
            )
            return forced_spawn

        # Evidence gate (AD-CLI4..AD-CLI8): questions about external-data
        # domains (calendar/email/tasks/repos/deployments) are never answered
        # from the model's head. Either a connected CLI covers the domain
        # (mandatory-tool directive for this turn) or the answer is a
        # deterministic honest refusal. Pure regex + registry lookup, no LLM
        # (AP-11). Only MISSION skill turns returned above — an inline
        # plugin-skill turn reaches this point, so _run_evidence_gate itself
        # stands down on a matched skill (AD-S3); non-CLI capabilities
        # (paired skills, router tools, MCP) make the gate stand down (PASS).
        verdict = self._run_evidence_gate(user_text)
        if verdict.kind == "honest_refusal":
            await self._record_response_side_effects(
                user_text=user_text,
                response_text=verdict.refusal_text,
                use_history=use_history,
                trace_id=turn_trace_id,
            )
            return verdict.refusal_text
        if verdict.kind == "require_tool" and (
            _conversational_turn_suppresses_read_mandate(user_text)
        ):
            # Opinion/advice/conversational turn: never FORCE a read tool — and so
            # never void the answer — just because a domain keyword appeared. Live
            # 2026-06-30 (Bora-Bora): "...bei meinem Budget bei 25.000 Euro ...
            # passt es?" matched the cloud domain, the gate forced cli_gcloud, and
            # the backstop then deleted the model's good travel answer. The tool
            # stays in the surface, so the model keeps discretion to call it; it is
            # just never forced. A bare data lookup ("Was sind meine Abrechnungen?")
            # carries no opinion opener and stays gated (no confab regression).
            log.info(
                "Evidence gate stood down (conversational): domain=%s tool=%s "
                "— answering inline, not forcing the tool.",
                verdict.domain, verdict.tool_name,
            )
        elif verdict.kind == "require_tool":
            log.info(
                "Evidence gate: domain=%s requires tool %s this turn",
                verdict.domain, verdict.tool_name,
            )
            self._evidence_directive = verdict.directive
            self._evidence_required_tool = verdict.tool_name
            # Persist the domain so the honest "couldn't reach X" fallback can
            # NAME the capability (B3) instead of the generic "the tool".
            self._evidence_required_domain = verdict.domain

        # Say-do honesty guard for WRITES. The read evidence gate above never
        # fires on a "save this" turn (it is not a lookup), so a confirmed offer
        # ("ja, leg die an … die Mail ist …") or an explicit "merk dir, dass …"
        # used to be answered with a chatty "Okay, sehr gut" and NO write call —
        # nothing persisted (live session 2026-06-30). Mandate the right write
        # tool this turn, reusing the evidence machinery: the prompt directive,
        # the smalltalk tool-widening (_evidence_required_tool stays visible),
        # and the unverified-answer backstop that catches a fake confirmation.
        # resolve_save_mandate routes contact data → contact-upsert and a
        # general fact → wiki-ingest. Only when the read gate did not already
        # mandate a tool, and only if the target tool is actually registered (a
        # deployment without contacts/wiki degrades to no mandate — never a
        # mandate for a missing tool, §3 open-source).
        if not self._evidence_required_tool:
            from dodaios.brain.contact_intent import resolve_save_mandate

            _save_mandate = resolve_save_mandate(user_text)
            if _save_mandate is not None and _save_mandate[0] in (
                getattr(self, "_tools", None) or {}
            ):
                self._evidence_directive = _save_mandate[1]
                self._evidence_required_tool = _save_mandate[0]
                self._evidence_required_is_write = True
                log.info(
                    "Say-do guard: save intent — mandating %s this turn",
                    _save_mandate[0],
                )

        # Say-do guard for LOCAL OUTCOMES (shell-consistency rework 2026-08-08).
        # A natural file/folder/system request ("erstell einen Ordner auf dem
        # Desktop") used to reach the LLM with run_shell merely OPTIONAL:
        # whether the model mapped the outcome onto a shell command was model
        # whim, and the capability block's "never invent tools" rule biased it
        # towards the dictated refusal ("mir fehlt das passende Werkzeug")
        # although the tool was registered and visible (maintainer report
        # 2026-08-08 — a timer request worked, a folder request refused).
        # Mirror the save mandate above: deterministically mandate run_shell so
        # the directive + honest write backstop turn "sometimes works" into
        # "always works or fails honestly". Never overrides an earlier mandate
        # (read evidence / save — those are more specific), stands down on a
        # skill-matched turn (AD-S3/AD-S9: a matched skill IS the capability
        # and must not be steamrolled by a generic shell mandate), and
        # degrades to no mandate when run_shell is not registered (§3
        # open-source).
        if not self._evidence_required_tool and self._skill_turn_match is None:
            from dodaios.brain.local_outcome_gate import resolve_local_outcome_mandate

            _local_mandate = resolve_local_outcome_mandate(user_text)
            if _local_mandate is not None and _local_mandate[0] in (
                getattr(self, "_tools", None) or {}
            ):
                self._evidence_directive = _local_mandate[1]
                self._evidence_required_tool = _local_mandate[0]
                self._evidence_required_is_write = True
                log.info(
                    "Local-outcome guard: file/system intent — mandating %s this turn",
                    _local_mandate[0],
                )

        # A society model can describe a routine without ever calling its
        # configuration tool. Make the write mandatory on explicit creation
        # turns, including a short confirmation after the details were agreed.
        # The live surface check keeps this guard out of other chat surfaces.
        if not self._evidence_required_tool and "society_propose_change" in self._live_tool_names():
            from dodaios.society.routine_intent import requests_routine_creation

            if requests_routine_creation(user_text):
                self._evidence_directive = (
                    "MANDATORY THIS TURN: read society_routines, then save the routine with "
                    "society_propose_change (kind=routine, mode=apply) from the agreed details, "
                    "and verify it."
                )
                self._evidence_required_tool = "society_propose_change"
                self._evidence_required_is_write = True
                self._evidence_required_domain = "routine"
                log.info("Society routine creation intent — mandating society_propose_change")

        # Jarvis itself (voice and the lead chat) schedules an agent's
        # recurring work through the society-create-routine app command. A
        # request like "a briefing every day at 8" never says "routine" and
        # used to end as an inactive draft skill (live 2026-09-29), so the
        # recurrence alone makes the save mandatory.
        if (
            not self._evidence_required_tool
            and "society-create-routine" in self._live_tool_names()
        ):
            from dodaios.society.routine_intent import wants_agent_routine

            if wants_agent_routine(user_text):
                self._evidence_directive = (
                    "MANDATORY THIS TURN: scheduled work. Call society-create-routine for "
                    "yourself (agent_id jarvis), never for another agent and never create an "
                    "agent for it, with a self-contained prompt and the schedule; never "
                    "create-skill. Report the returned next_run."
                )
                self._evidence_required_tool = "society-create-routine"
                self._evidence_required_is_write = True
                self._evidence_required_domain = "routine"
                log.info("Recurring-work intent — mandating society-create-routine")

        # A small on-device model answers public-fact questions from an
        # unreliable memory and often skips search_web (live 2026-10-28: an
        # invented train story with "[used tool search_web]" typed as text).
        # Mandate the search for those turns; the backstop below keeps a short
        # clarifying question and replaces any unsearched claim.
        if not self._evidence_required_tool and self._skill_turn_match is None:
            from dodaios.brain.app_control import LOCAL_PROVIDERS
            from dodaios.brain.public_fact_gate import (
                PUBLIC_FACT_DOMAIN,
                SEARCH_TOOL,
                public_fact_search_directive,
            )

            _pf_override = _TURN_OVERRIDE.get()
            _pf_provider = (
                str(getattr(_pf_override, "provider", "") or "")
                if _pf_override is not None
                else ""
            ) or str(getattr(self._config.brain, "primary", "") or "")
            _pf_directive = public_fact_search_directive(
                user_text,
                provider=_pf_provider,
                tool_names=self._live_tool_names(),
                previous_user_text=self._previous_user_turn_text(use_history=use_history),
                local_providers=LOCAL_PROVIDERS,
            )
            if _pf_directive is not None:
                self._evidence_directive = _pf_directive
                self._evidence_required_tool = SEARCH_TOOL
                self._evidence_required_domain = PUBLIC_FACT_DOMAIN
                log.info(
                    "Public-fact guard: on-device provider %s — mandating %s this turn",
                    _pf_provider,
                    SEARCH_TOOL,
                )
                # The small model calls the tool only now and then; run the one
                # search here and hand it the results (the realtime grounding).
                # A question naming no event ("an accident?") borrows its
                # subject from the last turns, or is answered with a question.
                from dodaios.brain.public_fact_gate import (
                    PUBLIC_FACT_CLARIFY_DIRECTIVE,
                    PUBLIC_FACT_CLARIFY_DOMAIN,
                    prefetch_public_fact_evidence,
                    public_fact_evidence_directive,
                    public_fact_search_query,
                )

                _pf_query = public_fact_search_query(
                    user_text, self._recent_user_turn_texts(2, use_history=use_history)
                )
                if _pf_query is None:
                    self._evidence_directive = PUBLIC_FACT_CLARIFY_DIRECTIVE
                    self._evidence_required_domain = PUBLIC_FACT_CLARIFY_DOMAIN
                else:
                    _pf_evidence = await prefetch_public_fact_evidence(
                        _pf_query, trace_id=turn_trace_id
                    )
                    if _pf_evidence is not None:
                        self._evidence_directive = public_fact_evidence_directive(_pf_evidence)
                        self._public_fact_prefetched = True
            elif not self._evidence_directive:
                # A hosted model without tools (the print-mode Claude CLI) cannot
                # search either (BC-250 2026-10-29: "je ne peux pas faire de
                # recherche en direct ici" about the latest Artemis II news). Run
                # the search for an explicitly fresh public fact and hand it the
                # results; its own answer is never replaced afterwards. The cheap
                # text check runs first: the capability probe builds the primary
                # brain, which only a turn that needs a search may do.
                from dodaios.brain.public_fact_gate import (
                    hosted_fresh_fact_query,
                    prefetch_public_fact_evidence,
                    public_fact_evidence_directive,
                )

                _pf_query = hosted_fresh_fact_query(
                    user_text,
                    provider=_pf_provider,
                    local_providers=LOCAL_PROVIDERS,
                    previous_user_text=self._previous_user_turn_text(use_history=use_history),
                    recent_user_texts=self._recent_user_turn_texts(2, use_history=use_history),
                )
                if _pf_query is not None and not self._brain_can_call_tools(
                    _pf_provider, self._fast_model(_pf_provider)
                ):
                    _pf_evidence = await prefetch_public_fact_evidence(
                        _pf_query, trace_id=turn_trace_id
                    )
                    if _pf_evidence is not None:
                        self._evidence_directive = public_fact_evidence_directive(_pf_evidence)
                        log.info(
                            "Public-fact search: tool-less provider %s answers from a "
                            "system-run %s",
                            _pf_provider,
                            SEARCH_TOOL,
                        )

        # Phase 5 / ADR-0006: pre-call budget gate. Block rather than request
        # when cooldown is active or the task/daily budget is exhausted.
        trace_uuid = turn_trace_id
        if self._cost_meter is not None:
            if self._cost_meter.is_in_cooldown():
                return ("Cost-Cooldown aktiv — Tagesbudget erschoepft. "
                        "Neue Anfragen werden erst nach dem Cooldown-Ende bearbeitet.")
            if self._cost_meter.over_task_budget(trace_uuid):
                return "Task-Budget fuer diese Konversation ueberschritten."
            if self._cost_meter.over_daily_budget():
                return "Tagesbudget ueberschritten."

        # Smalltalk spawn-hide (bug fix 2026-05-01): on clearly identified
        # smalltalk the spawn vehicles are hidden so the LLM cannot be tempted to
        # hallucinate "spawn_worker" (see voice session 2026-04-30 22:38, "es
        # geht ab" → fake spawn). Only those — the rest of the surface stays, so
        # a request the substring allowlist merely READS as chit-chat still has
        # something to act with (see _smalltalk_tool_override). Force-spawn
        # already ran (smalltalk wins there against verb match); now we also
        # constrain the LLM tool-choice path.
        is_smalltalk_turn = self._is_smalltalk(user_text)
        if is_smalltalk_turn:
            log.info(
                "Smalltalk-Turn → nur read-only Tools fuer LLM sichtbar: %r",
                user_text[:80],
            )

        # 2. Router: which level applies?
        decision = self._picked_level(user_text)
        log.debug("Router-Decision: level=%s reason=%s", decision.level, decision.reason)

        # 3. Build fallback chain and try each entry.
        # Provider-agnostic tool routing flags (consumed by _build_fallback_chain):
        #  - _turn_substantive: a non-smalltalk turn. With the intelligent router
        #    on, a tool-capable provider LEADS such a turn for a tool-incapable
        #    talker and the LLM picks the tool (or falls through to the talker).
        #  - _turn_needs_tools: the narrower action-intent signal used as the
        #    flag-OFF (kill-switch) delegation. Reuses the deterministic detectors.
        # Reset _router_lead_key here too so a monkeypatched _build_fallback_chain
        # (tests / callers that replace it) never leaves a stale fall-through marker.
        self._router_lead_key = None
        self._turn_substantive = not is_smalltalk_turn
        self._turn_needs_tools = (not is_smalltalk_turn) and self._turn_has_action_intent(
            user_text
        )
        chain = self._build_fallback_chain(decision.level)
        if prefer_tool_model:
            # Realtime delegation runs on the Tool Model pick; hoisted BEFORE
            # the empty-chain check so an all-dead chain keeps the honest
            # provider-down diagnostic below.
            chain = self._hoist_tool_model(chain)
        if not chain:
            # Empty chain means either (a) no providers registered or
            # (b) all filtered out by _dead_providers (no key set).
            # In production (b) is the common case — provide an actionable message.
            self._last_turn_all_failed = True
            # Keep the actionable provider/key diagnostic in the LOG (UI/console
            # surface it), but SPEAK only a localized, provider-agnostic apology
            # — never read setup hints or provider names aloud (AP-11/ADR-0010).
            if self._dead_providers:
                log.warning(
                    "Provider chain empty (all dead/keyless) — spoken fallback. "
                    "Diagnostic: providers without a credential this session: %s",
                    ", ".join(str(p) for p in self._dead_providers),
                )
            else:
                log.warning("No brain providers available — spoken fallback used.")
            # An all-keyless chain has exactly one honest spoken cause.
            return await self._provider_down_reply(trace_uuid, cause="missing_key")

        history_override = _TURN_HISTORY_OVERRIDE.get()
        # The typed chat's pick, if any: its own credential scope and no
        # dead-listing — a chat key that fails must not silence the voice brain.
        turn_override = _TURN_OVERRIDE.get()
        history = (
            list(history_override)
            if history_override is not None
            else (self._history if use_history else [])
        )
        _drop_in_hist = sum(
            1 for m in history
            if isinstance(getattr(m, "content", None), str)
            and "\U0001F4CE" in m.content
        )
        if _drop_in_hist:
            log.info(
                "📎 DROP CONTEXT present in this turn's history: %d note(s), "
                "use_history=%s, total history=%d",
                _drop_in_hist, use_history, len(history),
            )
        last_exc: Exception | None = None
        response_text = ""
        used_provider: str | None = None
        used_model: str | None = None
        _turn_executed: set[str] = set()  # tools that REALLY ran this turn
        # AI Pointer (deictic push): launch the cursor-element resolution BEFORE
        # the vision-image await so it overlaps with it instead of running serially
        # after (AP-9: keep the deictic turn off the serial hot path). The task does
        # the regex gate itself, so non-deictic turns complete instantly with
        # ("", None) and fast-skip on a headless host. Awaited just below.
        pointer_task = (
            None
            if screen_context.has_image
            else self._start_pointer_task(user_text, is_smalltalk_turn)
        )
        if screen_context.has_image:
            pending_images = getattr(self, "_pending_turn_images", None)
            injected = pending_images.pop(trace_uuid, ()) if pending_images else ()
            images = tuple(injected) + (
                ImageBlock(
                    mime=screen_context.mime,
                    data_b64=base64.b64encode(screen_context.image).decode("ascii"),
                    source_hash=screen_context.source_hash,
                ),
            )
        else:
            images = await self._collect_vision_images(
                trace_id=trace_uuid,
                user_text=user_text,
                is_smalltalk=is_smalltalk_turn,
            )
        # Per-provider error aggregation for a meaningful user message when
        # the whole chain fails. Pattern: (provider, model, kind, detail).
        # kind ∈ {"rate_limit", "missing_key", "skipped_cooldown", "init_fail",
        #         "call_fail"}
        provider_errors: list[tuple[str, str, str, str]] = []

        # Personal memory vault (ADR-0044): memories that match this message and
        # are not in the always-on block ride along in the same per-turn slot.
        if not (
            turn_override is not None
            and turn_override.tool_context.get("tool_origin") == "society"
        ):
            recalled = await self._vault_recall(user_text)
            if recalled:
                self._memory_context_suffix = "\n\n".join(
                    p for p in (self._memory_context_suffix.strip(), recalled) if p
                )

        # Wave 2 (omni-latency): assemble the per-turn dynamic context (date +
        # wiki) once. In cache-optimized mode it rides on the user
        # message (keeping the cached system prompt stable); empty in legacy
        # mode. Reused for every provider in the fallback chain below.
        turn_context = self._build_turn_context()
        if screen_context.note:
            turn_context = (
                f"{turn_context}\n\n{screen_context.note}"
                if turn_context
                else screen_context.note
            )

        # AD-S3/S4: on a skill-matched turn the rendered instructions ride on
        # the per-turn context (guaranteed invocation, no run-skill round
        # trip needed) — deterministic code, not a prompt-only hope. The
        # cached system prefix stays byte-stable.
        _skill_block = self._render_skill_turn_injection(user_text)
        if _skill_block:
            turn_context = (
                f"{turn_context}\n\n{_skill_block}" if turn_context else _skill_block
            )
        else:
            # No capture, but the deterministic scorer may still have found
            # plausible candidates. Narrowing 20 undifferentiated bullets down
            # to the 1-3 that actually score is the cheapest part of this whole
            # change and the part with no blast radius: the model still decides.
            _narrow_block = self._render_skill_candidate_hint(user_text)
            if _narrow_block:
                turn_context = (
                    f"{turn_context}\n\n{_narrow_block}"
                    if turn_context
                    else _narrow_block
                )
        # AI Pointer (deictic push): collect the result of the resolution started
        # above. When the utterance points at the mouse cursor ("was ist das da?")  # i18n-allow
        # the resolved element rides on this turn's context + a tight crop is
        # attached only when the element is unlabeled. Unrelated turns ("how's the
        # weather?") yield ("", None). See docs/plans/ai-pointer/DESIGN.md.
        pointer_block = ""
        pointer_image: ImageBlock | None = None
        if pointer_task is not None:
            try:
                pointer_block, pointer_image = await pointer_task
            except Exception:  # noqa: BLE001 — never crash a turn on pointer context
                log.debug("AI Pointer per-turn injection skipped", exc_info=True)
                pointer_block, pointer_image = "", None

        # AI Pointer grounding (2026-06-02): a deictic pointer turn ("worauf zeige
        # ich?") must be scoped to the CURSOR region so the brain answers from the
        # cursor element/crop — it must NOT guess the pointing target from the
        # full-screen permanent-vision image (the live "described something
        # completely elsewhere" bug). On such a turn we (1) replace the full-screen
        # image with the tight cursor crop (or none, for a labelled element),
        # (2) drop the full-screen screenshot + inspect-pointer tools (below), and
        # (3) inject a "do not guess" instruction when resolution failed.
        pointing_turn = (not is_smalltalk_turn) and self._is_pointer_intent(user_text)
        if pointing_turn and not screen_context.has_image:
            images = (pointer_image,) if pointer_image is not None else ()
            if not pointer_block:
                pointer_block = (
                    "[AI Pointer] The user asked what they are pointing at, but the "
                    "element under the cursor could not be read right now. Tell them "
                    "you cannot tell what is under the cursor at the moment — do NOT "
                    "guess from the rest of the screen."
                )
            turn_context = (
                f"{turn_context}\n\n{pointer_block}" if turn_context else pointer_block
            )

        # Drag-drop SILENT context: pictures parked by ``add_dropped_context``
        # (a drop never triggers its own turn) are pulled into THIS real turn,
        # once — added AFTER vision + AI-Pointer image logic so neither clobbers
        # them. Cleared on consume; never re-sent on later turns.
        _dropped_imgs = getattr(self, "_pending_drop_images", ()) or ()
        if _dropped_imgs:
            self._pending_drop_images = ()
            images = tuple(_dropped_imgs) + tuple(images)

        # Grounded per-tool ack (perceived-latency): built ONCE per turn so a
        # provider-chain retry cannot double-announce. The loop fires it the
        # moment a tool is actually selected; None when the feature is off or
        # this is a Voice-Control utterance.
        _tool_ack_emitter = (
            self._build_tool_ack_emitter(user_text) if emit_tool_ack else None
        )

        vision_capable_seen = False
        if images:
            chain = self._lead_vision_chain(chain)
        screen_turn_t0 = time.perf_counter() if images else None

        for idx, (prov_name, model) in enumerate(chain):
            # Skip providers already marked dead in THIS turn.
            # Example: gemini-fast fails with missing_key → gemini-deep would
            # still be in the chain but would fail for the same reason. Skip
            # saves an avoidable subprocess/network call. An overridden turn
            # runs on its own credential scope, so the voice brain's dead-list
            # is not its truth.
            if turn_override is None and prov_name in self._dead_providers:
                continue
            # A FALLBACK whose key or login real calls found dead (a persisted
            # verdict with a TTL) is not re-walked. The first entry is the
            # owner's own choice: it always runs, and its failure is reported.
            if (
                turn_override is None
                and idx > 0
                and _seat_health.fallback_is_known_dead(prov_name, model)
            ):
                continue
            # Model-scoped dead-list: this exact (provider, model) took a
            # billing rejection earlier THIS turn but the provider itself
            # was kept alive because another model was still untried — see
            # `_dead_provider_models`.
            if turn_override is None and (prov_name, model) in self._dead_provider_models:
                continue
            # Circuit breaker: skip rate-limited providers during cooldown
            if not self._rate_tracker.is_available(prov_name, model):
                log.debug("Skip rate-limited: %s(%s)", prov_name, model)
                provider_errors.append(
                    (prov_name, model, "skipped_cooldown",
                     "still in 30s rate-limit cooldown"))
                continue

            try:
                # The classic call keeps its two-argument shape (tests and
                # callers replace ``_get_brain`` with that signature); only an
                # overridden turn asks for its own credential scope.
                brain = (
                    self._get_brain(prov_name, model, scope=turn_override.credential_scope)
                    if turn_override is not None
                    else self._get_brain(prov_name, model)
                )
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                msg = str(exc)
                kind = _m._classify_provider_error(msg, default="init_fail")
                # The status dots read what real turns did; the record keeps
                # only the classification, never this message (AP-34). An
                # overridden turn (an agent chat) runs on its own credential
                # scope and model, so it is not the Brain tab's evidence.
                if turn_override is None:
                    _health_ledger.record_failure(
                        prov_name, _health_ledger.MODALITY_BRAIN, exc, model=model
                    )
                # On missing_key: remove provider from the chain for the rest
                # of the session. Prevents each voice turn from running 8x
                # sequentially against the same missing keys. Never for an
                # overridden turn: its key is the chat's, not the voice's.
                if (
                    turn_override is None
                    and kind in _m._DEAD_LIST_KINDS
                    and prov_name not in self._dead_providers
                ):
                    self._dead_providers.add(prov_name)
                    if kind == "missing_key":
                        log.warning(
                            "Provider %s ohne API-Key — fuer diese Session deaktiviert. "
                            "Setup: Sidebar -> API-Keys.", prov_name)
                    else:
                        log.warning(
                            "Provider %s account-blocked (Credit/Quota/Tier) — "
                            "fuer diese Session deaktiviert. Detail: %s",
                            prov_name, msg[:160])
                else:
                    log.debug(
                        "Brain %s(%s) konnte nicht instantiiert werden: %s",
                        prov_name, model, exc)
                provider_errors.append((prov_name, model, kind, msg[:200]))
                continue

            # Attached pixels are evidence, not decoration. A provider that
            # cannot inspect them must never answer as though it had; skip it
            # by runtime capability and preserve the normal cross-family retry
            # order for the remaining vision-capable providers.
            if images and getattr(brain, "supports_vision", False) is not True:
                provider_errors.append(
                    (prov_name, model, "vision_unsupported", "vision unsupported")
                )
                log.info(
                    "Skipping %s(%s): this turn carries an image but the "
                    "provider does not advertise vision support",
                    prov_name,
                    model,
                )
                continue
            if images:
                vision_capable_seen = True

            _turn_tools = (
                # Captured-screen turn: the pixels answer it, but the surface is
                # NARROWED, not emptied — a look glued to an action still needs
                # its vehicle, and cu_gate enforces the look/operate boundary per
                # call (see _image_turn_tool_override).
                self._image_turn_tool_override()
                if screen_context.has_image
                else self._smalltalk_tool_override() if is_smalltalk_turn
                # Non-smalltalk turn: drop plugin tools irrelevant to this
                # utterance (progressive disclosure), then hide any plugin whose
                # CLI counterpart is connected (req 4: CLI > plugin fallback).
                else self._suppress_plugins_covered_by_cli(
                    self._apply_plugin_relevance(routing_text, self._tools), routing_text
                )
            )
            # Skill inline-injected (AD-S4): drop run-skill so a weak model
            # cannot make a redundant, garbled run-skill tool call — the
            # gemini-fast ``<call:tool.run-skill ...>`` text leak. The
            # instructions already ride on the turn context, so execution is
            # provider-/model-agnostic (no tool call needed).
            _turn_tools = self._drop_run_skill_when_inline_injected(_turn_tools)
            # Knowledge-question spawn-hide (forensic 2026-06-27): a plain
            # factual question ("Welche Unternehmen haben so viel Speicherplatz?")
            # must not be able to reach spawn_worker — the router-LLM reflexively
            # delegated it ("ich ziehe einen Experten hinzu") instead of answering
            # inline. The deterministic force-spawn gate already stood down; this
            # removes the spawn tools from the LLM surface so the reflex has no
            # tool to grab. search_web / reads / computer_use stay visible.
            if isinstance(_turn_tools, dict):
                _turn_tools = self._hide_spawn_on_knowledge_question(
                    _turn_tools, user_text
                )
            # Signalless-turn action-hide (forensic 2026-06-27): inside a live
            # desktop episode a turn with NO actionable signal of its own ("Was
            # geht ab?" mis-heard as "Lask it up!" conf 0.509) must not reach
            # computer_use/spawn — the router-LLM would otherwise INHERIT the
            # previous turn's CU action from the conversation context. Outside an
            # episode there is nothing to inherit and the vehicle stays.
            if isinstance(_turn_tools, dict):
                _turn_tools = self._hide_action_tools_on_signalless_turn(
                    _turn_tools, user_text
                )
            # Plugin-tool spawn-hide (forensic 2026-06-27, voice 17:44): "Schau
            # mal nach was in meinem Google Calendar am 29. ist" spawned a worker
            # ("umfangreicheres Stueck Arbeit") that has no google_calendar tool
            # (plugin tools are router-tier only, AP-5/AP-14) -> "kann ich nicht".
            # When a connected plugin's usage-card keywords match the turn, drop
            # the spawn vehicles so the router uses the plugin tool DIRECTLY.
            if isinstance(_turn_tools, dict):
                _turn_tools = self._hide_spawn_when_plugin_tool_handles_turn(
                    _turn_tools, routing_text
                )
            # Agentic-IDE pane tools exist only relative to an OPEN workspace
            # (2026-07-28 cost audit): with none open they can only fail,
            # while their schemas ride every loop iteration. Status/resume
            # always stay visible.
            if isinstance(_turn_tools, dict):
                _turn_tools = self._hide_agentic_ide_tools_without_workspace(
                    _turn_tools
                )
            # An artifact is built when the user asks to SEE something, never
            # because an answer might look nicer as a page (maintainer mandate
            # 2026-08-11). Structural, not prompt-level: on a turn that did not
            # ask, the model never sees the tool — and never pays for its schema
            # or starts a background mission.
            if isinstance(_turn_tools, dict):
                _turn_tools = self._hide_artifact_tool_without_request(
                    _turn_tools, user_text
                )
            # A referential follow-up that inherited a currently registered
            # plugin/MCP tool remains inline even when that tool has no usage
            # card. The explicit heavy-work and artifact requests above retain
            # their normal mission path.
            if (
                isinstance(_turn_tools, dict)
                and contextual_tool_names
                and not self._is_explicit_heavy_request(user_text)
                and not self._research_wants_artifact(user_text)
            ):
                _turn_tools = {
                    name: tool
                    for name, tool in _turn_tools.items()
                    if name not in _SPAWN_TOOL_NAMES
                }
            # PC-control run-skill hide (forensic 2026-07-02, voice 20:28): "ein
            # Terminal öffnen, Cloud-Code öffnen, … ein Prompt geben" — an
            # explicit desktop request — was hijacked by the semantically-similar
            # cloud-debug skill via the SKILLS-FIRST rule and dead-ended in the
            # capability refusal. When the user names the desktop vehicle,
            # computer_use is authoritative — drop run-skill from the surface.
            if isinstance(_turn_tools, dict):
                _turn_tools = self._hide_run_skill_on_pc_control_turn(
                    _turn_tools, user_text
                )
            # Scheduled work for an agent is a routine, never a draft skill
            # with a cron line (live 2026-09-29: "every day at 8" became an
            # inactive skill while the routine was reported as set up).
            if (
                isinstance(_turn_tools, dict)
                and self._evidence_required_tool == "society-create-routine"
            ):
                _turn_tools = {n: t for n, t in _turn_tools.items() if n != "create-skill"}
            # AI Pointer: on a deictic pointer turn the cursor crop is already the
            # only attached image, so drop the redundant ``inspect-pointer`` PULL
            # tool (calling it produced an empty spoken answer — observed live).
            # The full-screen ``screenshot`` tool is deliberately KEPT: removing it
            # made the router refuse "Was siehst du hier?" with "I lack a tool"
            # (the capability gate maps "see" to a vision tool). With the tool
            # present there is no refusal, and the injected crop + prompt steer the
            # brain to answer from the crop, not the whole screen. See
            # docs/plans/ai-pointer/DESIGN.md.
            if pointing_turn and isinstance(_turn_tools, dict):
                _turn_tools = {
                    k: v for k, v in _turn_tools.items() if k != "inspect-pointer"
                }
            # Screen-relevance gate (2026-06-14): the on-demand ``screenshot``
            # tool is only in scope when the utterance refers to the screen (or
            # an image is attached / it is a pointer turn). On a plain
            # conversation or cut-off small-talk fragment the brain must not be
            # able to reach for — and then narrate — the screen.
            if isinstance(_turn_tools, dict):
                _turn_tools = self._gate_screen_tool(
                    _turn_tools,
                    user_text=user_text,
                    has_image=bool(images),
                    pointing_turn=pointing_turn,
                )
            # A brain that cannot inspect pixels must never be OFFERED the
            # screenshot tool — see _hide_screenshot_for_blind_brain.
            if isinstance(_turn_tools, dict):
                _turn_tools = self._hide_screenshot_for_blind_brain(
                    _turn_tools, brain, prov_name=prov_name, model=model
                )
            if turn_override is not None:
                # The caller's extra hands (a chat's folder tools) join the
                # surface AFTER every gate above, and a plan-mode filter runs
                # last — the gates decide what Jarvis may reach for, the
                # override only adds a folder and, in plan mode, takes the
                # writing hands away.
                _turn_tools = self._apply_turn_override_tools(_turn_tools, turn_override)
            # Active-model self-awareness: stamp the provider/model that is about
            # to answer so _build_system_prompt injects the correct, specific
            # self-identity (anti-"I'm Gemini" hallucination, forensic 2026-06-20).
            # Set here — after dead/cooldown skips — so it always names the
            # provider that genuinely runs this attempt, including a fallback win.
            self._active_turn_identity = (prov_name, model)
            # Delegated realtime voice turns get hard loop bounds so an
            # unbounded delegate can never run away (live 2026-07-14: 14
            # rounds / 66 s on "what is in my wiki"). They are ceilings, not
            # targets — see _DELEGATE_MAX_TURNS for why the round budget and
            # the wall clock carry different numbers. On either bound the loop
            # forces ONE final tool-less round over the evidence already
            # gathered, so the user still hears a grounded answer. Classic
            # turns call with the unchanged signature (kwargs only on
            # delegation).
            _disp_kwargs: dict[str, Any] = (
                {
                    "max_turns": _DELEGATE_MAX_TURNS,
                    "deadline_s": _DELEGATE_DEADLINE_S,
                    "reasoning_effort": _DELEGATE_REASONING_EFFORT,
                    "delegated_voice": True,
                }
                if prefer_tool_model
                else self._override_dispatch_kwargs(turn_override)
            )
            await _m._settle_context_window(brain)
            disp = self._build_dispatcher(
                brain, tools_override=_turn_tools, **_disp_kwargs
            )
            # Intelligent router: the router LEAD must NOT stream its conversational
            # text to TTS. On the streaming path (generate_stream) text_consumer
            # speaks each chunk live DURING dispatch — so a no-tool router answer
            # would be spoken and THEN the fall-through talker would speak again
            # (double answer). Suppress the consumer for the lead: if it picks a
            # tool, the result is surfaced by generate_stream's final reconciliation
            # (nothing was yielded → it yields holder["final"]); if it picks none,
            # the chosen talker streams the answer normally after the fall-through.
            _is_router_lead = self._router_lead_key == (prov_name, model)
            _attempt_consumer = None if _is_router_lead else text_consumer
            try:
                # CostMeter: start per-trace tracking (idempotent if already started).
                if self._cost_meter is not None:
                    self._cost_meter.start(trace_uuid, prov_name, model)
                agg = await disp.dispatch(
                    user_text,
                    images=images,
                    history=history,
                    trace_id=trace_id,
                    intent_level=decision.level,
                    evidence_required_tool=self._evidence_required_tool,
                    text_consumer=_attempt_consumer,
                    ack_emitter=_tool_ack_emitter,
                    on_progress=on_progress,
                    turn_context=turn_context,
                    reply_language=self._reply_language,
                    conversation_language=self._conversation_language,
                    voice_confirm=(allow_voice_confirm and self._voice_confirm_enabled),
                )
                # Post-call cost hook: aggregated usage → meter.
                # The meter cancels on overrun via CancelToken (see ADR-0006);
                # the pre-call gate above catches that on the next turn.
                if self._cost_meter is not None and agg.usage:
                    usd = _estimate_usd_from_usage(self._cost_meter, model, agg.usage)
                    self._cost_meter.add(CostRecord(
                        trace_id=trace_uuid, provider=prov_name, model=model,
                        tokens_in=int(agg.usage.get("input_tokens", 0)),
                        tokens_out=int(agg.usage.get("output_tokens", 0)),
                        tokens_cache_hit=int(agg.usage.get("cache_hit_tokens", 0)),
                        usd=usd, timestamp_ns=time.time_ns(),
                    ))
                # Empty-Response-Guard: wenn der Provider zwar erfolgreich
                # antwortet aber **leeren** Content liefert (Safety-Block,
                # truncated-Response, Schema-Mismatch), behandeln wir das wie
                # einen Soft-Fail und gehen zum naechsten Provider in der
                # Chain. Frueher: response_text = "" + break → die globale
                # `if not response_text`-Logik unten verschickte dann irrefuehrend
                # "Provider X, Y unerreichbar" statt einen anderen Provider zu
                # probieren. Empty != fail-permanently, aber empty != success.
                #
                # 2026-04-29 Fix: Tool-Calls + suppress_response sind LEGITIME
                # leere Texte. Beispiel: spawn_worker ist fire-and-forget
                # mit suppress_response=True; der Tool-Use-Loop setzt dann
                # final_agg.text="" und finish_reason="suppress_response". Vorher
                # hat das den Empty-Response-Guard getriggert, der dann zum
                # naechsten Provider gefallen ist — der hat denselben Spawn
                # nochmal probiert. Die Folge: 3 Provider gecallt, 2 Spawns
                # abgelehnt, drittes fiel auf multi_spawn zurueck und
                # scheiterte ebenfalls.
                response_empty = not (agg.text or "").strip()
                # A REQUESTED tool call only excuses empty text when a tool
                # could actually have run. On a turn that offered NO tools at
                # all — a Screen Context turn strips every one of them — a
                # model-emitted call executed nothing by construction, so
                # treating it as a legitimate silence is always wrong.
                #
                # Live 2026-08-02 09:58: "kannst du bitte schnell einen
                # Screenshot machen?" captured the screen correctly, the one
                # vision-capable provider in the chain answered with 1170
                # tokens of reasoning, zero text and finish_reason=tool_calls,
                # this guard read it as legitimate, no other provider was
                # tried, and the user heard "that didn't work just now" while a
                # fresh screenshot sat unused. Gating on ``_turn_tools`` keeps
                # the tools-present behaviour byte-identical, so no executed
                # side effect can ever be re-run by a fallback.
                tool_calls_executed = bool(agg.tool_calls) and bool(_turn_tools)
                suppressed = (agg.finish_reason == "suppress_response")
                if response_empty and not tool_calls_executed and not suppressed:
                    log.warning(
                        "Brain %s(%s) lieferte leeren Content — "
                        "vermutlich Safety-Block oder Empty-Response. "
                        "Versuche naechsten Provider in der Chain.",
                        prov_name, model,
                    )
                    provider_errors.append((
                        prov_name, model, "empty_response",
                        "Provider gab leere Antwort zurueck (Safety/Schema?)",
                    ))
                    continue

                # INTELLIGENT ROUTER fall-through: this attempt is the tool-capable
                # router LEAD that was prepended for a tool-incapable talker. It got
                # first crack at tool selection; if it picked NO tool (pure
                # conversation) and a chosen talker follows in the chain, discard
                # its answer and fall through so the user keeps their selected
                # brain's voice. A tool it DID select (tool_calls non-empty) breaks
                # normally below and IS the turn's result. Placed BEFORE the events
                # publish below, so the discarded router turn is not recorded as the
                # turn; its cost was metered above (it genuinely ran). Reversible
                # via [brain.routing].intelligent_router (then _router_lead_key is
                # never set, so this never fires).
                if (
                    self._router_lead_key == (prov_name, model)
                    and not tool_calls_executed
                    and idx < len(chain) - 1
                ):
                    log.info(
                        "Intelligent router: %s picked no tool — falling through to "
                        "%s for the conversational answer.",
                        prov_name, chain[idx + 1][0],
                    )
                    continue

                response_text = agg.text
                # Honest mid-answer error notice (AD-OE6): the model round
                # AFTER tool execution died mid-stream (the provider sent
                # finish_reason="error") and produced no text. The empty-
                # response guard above is correctly skipped when tool calls
                # exist, so without this branch the turn counts as a success
                # with empty text and the user hears NOTHING (forensic
                # 2026-07-05, session 3e27dd8e, 223k-token round). Do NOT
                # fall through to the next provider — the executed tools
                # would re-run their side effects; speak honestly instead.
                if (
                    response_empty
                    and tool_calls_executed
                    and str(agg.finish_reason or "") == "error"
                ):
                    response_text = i18n_catalog.pick(
                        _MID_ANSWER_ERROR_PHRASES, self._resolve_turn_lang()
                    )
                    log.warning(
                        "Brain %s(%s): stream ended finish_reason=error AFTER "
                        "%d tool call(s) — speaking the honest mid-answer "
                        "error notice instead of an empty (silent) turn.",
                        prov_name, model, len(agg.tool_calls),
                    )
                # Record whether THIS (winning) turn was a fire-and-forget
                # ``suppress_response`` spawn, so the voice pipeline can stay
                # silent for it but speak a clarifying question for a different
                # empty turn (function_call/CU without speech). See
                # ``SpeechPipeline._handle_silent_brain_turn``.
                self._last_turn_suppressed = suppressed
                # AD-OE6 companion signal #2: did THIS winning turn SUCCESSFULLY
                # execute a desktop-action tool (computer_use / open_app / …)?
                # If so and it produced no narration, the voice pipeline speaks
                # a success confirmation instead of a clarifying question
                # (live bug 2026-06-09). Read ``executed_tool_names`` — the tools
                # that REALLY ran — not ``tool_calls`` (which also holds calls a
                # guard blocked, e.g. computer_use refused on a how-to question);
                # speaking "Erledigt." for a blocked action would be a lie.
                executed = getattr(agg, "executed_tool_names", None) or set()
                self._last_turn_executed_action_tool = bool(
                    set(executed) & _DESKTOP_ACTION_TOOL_NAMES
                )
                # Remember the tools that REALLY ran so the post-recovery
                # evidence-gate enforcement (below) can tell whether a mandated
                # tool was actually called this turn.
                _turn_executed = set(executed)
                used_provider, used_model = prov_name, model
                if turn_override is None:
                    _health_ledger.record_success(
                        prov_name, _health_ledger.MODALITY_BRAIN, model=model
                    )

                # Bug C Fix (2026-04-29) — BrainTurnStarted/Completed publishen
                # NUR wenn der Brain-Call erfolgreich war (Stream lieferte
                # Tokens oder Tool-Calls). Vorher: Event wurde publisht bevor
                # _ensure_client crashte → Halluzinations-Tag in voice_turns
                # ("openai/gpt-4o" ohne Key). Jetzt: wir wissen dass dieser
                # Call wirklich Daten lieferte (`continue`-Pfade kommen hier
                # nicht an), also schreiben wir nur den ECHTEN Provider in
                # die Voice-Session-DB.
                tokens_in_total = int(agg.usage.get("input_tokens", 0)) if agg.usage else 0
                tokens_out_total = int(agg.usage.get("output_tokens", 0)) if agg.usage else 0
                # Every plugin reports cache hits under the protocol key and
                # keeps ``input_tokens`` to the uncached share.
                tokens_cached_total = int(agg.usage.get("cache_hit_tokens", 0)) if agg.usage else 0
                cost_usd_total = await _turn_cost_usd(
                    prov_name, model, tokens_in_total, tokens_out_total, tokens_cached_total
                )
                await self._bus.publish(BrainTurnStarted(
                    provider=prov_name,
                    model=model,
                    intent_level=decision.level,
                ))
                await self._bus.publish(BrainTurnCompleted(
                    provider=prov_name,
                    model=model,
                    tokens_in=tokens_in_total,
                    tokens_out=tokens_out_total,
                    tokens_cached=tokens_cached_total,
                    cost_usd=cost_usd_total,
                    text_len=len(response_text or ""),
                    finish_reason=str(getattr(agg, "finish_reason", "ok") or "ok"),
                ))
                if turn_override is not None:
                    turn_override.receipt.record(
                        provider=prov_name,
                        model=model,
                        tokens_in=tokens_in_total,
                        tokens_out=tokens_out_total,
                        cost_usd=cost_usd_total,
                        finish_reason=str(getattr(agg, "finish_reason", "ok") or "ok"),
                    )

                if idx > 0:
                    log.info(
                        "Fallback-Hit: %s(%s) — %d provider übersprungen",
                        prov_name, model, idx,
                    )
                if screen_turn_t0 is not None:
                    log.info(
                        "screen-turn answered by %s(%s) in %d ms (skipped=%d)",
                        prov_name,
                        model,
                        int((time.perf_counter() - screen_turn_t0) * 1000),
                        idx,
                    )
                    # Under an override the pick answering after its router
                    # lead is the plan, not a fallback: the sidebar and its
                    # "Brain -> X" toast follow this event, and the live brain
                    # did not move (review 2026-08-25).
                    if turn_override is None:
                        await self._bus.publish(BrainProviderSwitched(
                            from_provider=self._active_name,
                            to_provider=prov_name,
                        ))
                break
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                msg = str(exc)
                # Classify FIRST so a terminal-billing 429 ("credits depleted",
                # "insufficient_quota") is treated as a DEAD provider, not a
                # transient rate-limit that keeps the empty provider leading the
                # chain every turn (live forensic 2026-06-28: a depleted Gemini
                # router bricked the whole turn even though OpenRouter was funded
                # — AP-22). Only a genuinely transient 429 takes the cooldown path.
                kind = _m._classify_provider_error(msg, default="call_fail")
                # A window too small for one request says nothing about whether
                # the provider works; recording it would turn its status dot
                # red for a setting, not a fault.
                if turn_override is None and kind != "local_context":
                    _health_ledger.record_failure(
                        prov_name, _health_ledger.MODALITY_BRAIN, exc, model=model
                    )
                if kind == "rate_limit":
                    self._rate_tracker.mark_rate_limited(prov_name, model)
                    log.warning("Rate-Limited %s(%s) — 30s Cooldown aktiviert", prov_name, model)
                    provider_errors.append(
                        (prov_name, model, "rate_limit", "HTTP 429"))
                else:
                    log.warning("Brain %s(%s) fehlgeschlagen: %s", prov_name, model, exc)
                    if (
                        turn_override is None
                        and kind in _m._DEAD_LIST_KINDS
                        and prov_name not in self._dead_providers
                    ):
                        # account_blocked (e.g. a bare 402) is model-scoped when
                        # the SAME provider still has an untried model later in
                        # this turn's chain (a capped paid model with a funded
                        # free model behind it, tests/unit/brain/
                        # test_depleted_credits_classification.py covers only the
                        # classifier, not this chain policy). missing_key/bad_key
                        # are credential problems and stay provider-wide — a dead
                        # key blocks every model, not just this one.
                        remaining_model = any(
                            other_name == prov_name
                            and other_model != model
                            and (other_name, other_model) not in self._dead_provider_models
                            for other_name, other_model in chain[idx + 1:]
                        )
                        if kind == "account_blocked" and remaining_model:
                            self._dead_provider_models.add((prov_name, model))
                            log.warning(
                                "Model %s(%s) billing-blocked — anderes Modell "
                                "desselben Anbieters bleibt in dieser Kette aktiv.",
                                prov_name, model)
                        else:
                            self._dead_providers.add(prov_name)
                            log.warning(
                                "Provider %s fuer diese Session deaktiviert (%s) — die Kette "
                                "weicht auf einen anderen verfuegbaren Anbieter aus. "
                                "Setup: Sidebar -> API-Keys.", prov_name, kind)
                    # The local-context sentence ends with the setting to
                    # change; cutting it at 200 chars would drop exactly that.
                    detail = msg if kind == "local_context" else msg[:200]
                    provider_errors.append((prov_name, model, kind, detail))
                # NOTE BUG-019 (2026-05-11): this generic ``continue`` does
                # not touch the failing provider's *internal* state. For
                # most providers that's correct (an HTTP error is purely
                # transient). For Gemini specifically, however, a 403
                # "CachedContent not found" means the locally-cached
                # ``self._cached_content_name`` is stale — and because we
                # don't clear it here, every subsequent voice turn re-uses
                # the same dead cache id and re-fails, sending the whole
                # fallback chain into the 40-second pipeline timeout and
                # leaving the user with silent THINKING → LISTENING. The
                # root-cause annotation lives at the actual failure site
                # in ``dodaios/plugins/brain/gemini.py`` (search for
                # "BUG-019 ROOT CAUSE"). The right place to fix this is
                # *inside* the provider (catch the cache-not-found error,
                # call its own ``invalidate_cache()``, retry without the
                # cached_content field) — not by leaking Gemini-specific
                # error matching into this cross-provider chain.
                continue

        # When `used_provider` is set, AT LEAST ONE provider completed the turn
        # successfully — even if `response_text` is empty (e.g. suppress_response
        # for fire-and-forget tools like spawn_worker). In that case do NOT
        # return the "all failed" message — the UI receives feedback via bus events
        # (JarvisAgentAnnouncement, etc.).
        # B5 Agent C: reset per-turn wiki suffix regardless of outcome so
        # stale context cannot leak into the next voice turn.
        self._memory_context_suffix = ""

        if screen_context.has_image and not vision_capable_seen:
            from dodaios.screen_context.intent import (  # noqa: PLC0415
                no_vision_provider_reply,
            )

            language = _turn_phrase_language(self, user_text)
            response_text = no_vision_provider_reply(language)
            await self._record_response_side_effects(
                user_text=user_text,
                response_text=response_text,
                use_history=use_history,
                trace_id=trace_uuid,
            )
            return response_text

        if used_provider is None:
            self._last_turn_all_failed = True
            log.error("Alle %d Provider-Versuche fehlgeschlagen. Letzter Fehler: %s",
                     len(chain), last_exc)
            # Developer diagnostic → LOG only. The voice path gets a localized,
            # provider-agnostic apology (live complaint 2026-06-01: the grok/
            # Anthropic billing diagnostic was spoken while Gemini was active).
            log.warning(
                "Spoken fallback used instead of chain diagnostic: %s",
                _m._format_provider_chain_error(provider_errors),
            )
            down_cause = _primary_provider_down_cause(provider_errors)
            if turn_override is not None:
                turn_override.receipt.mark_provider_down(down_cause)
            return await self._provider_down_reply(trace_uuid, cause=down_cause)

        # Text-serialized calls are recovered inside BrainDispatcher's shared
        # ToolUseLoop, where the exact turn-scoped tool surface, deadline,
        # safety guards, and exactly-once tracking remain authoritative. Never
        # re-parse and execute here against the manager-global tool registry:
        # that old fallback bypassed per-turn plugin/screen/deadline gates.
        # Two-turn voice/chat confirmation (turn N): the tool-use loop deferred a
        # consequential tool and produced a confirmation QUESTION as its text.
        # Arm the pending state and return the question directly — the leaked-tool
        # recovery + evidence gate below do not apply to a deferral (no tool ran,
        # nothing to recover; the answer is a question, not an unverified claim).
        if (
            getattr(agg, "finish_reason", "") == "voice_confirm_pending"
            and getattr(agg, "voice_confirm", None)
        ):
            self._arm_voice_confirm(agg.voice_confirm, user_text)
            await self._record_response_side_effects(
                user_text=user_text, response_text=agg.text,
                use_history=use_history, trace_id=trace_uuid,
            )
            return agg.text

        # ONE output-language resolution for every honesty phrase this turn
        # (one resolver decides the turn for ALL layers). The two
        # guards below used to resolve separately with DIFFERENT defaults
        # ("de" here, DEFAULT_LOCALE there), so an undetectable turn could speak
        # a German evidence fallback followed by an English honesty phrase in the
        # same breath. All locales are equal — the shared DEFAULT_LOCALE decides.
        honesty_lang = _turn_phrase_language(self, user_text)

        # Evidence-gate enforcement (live repro 2026-06-17, session 296abc82):
        # the gate MANDATED a tool this turn, but neither the normal tool loop
        # nor the leaked-tool recovery above actually ran it — so the model's
        # answer is unverified, at worst a confabulation ("the gcloud tool
        # blocked execution because it classified the request as an explanatory
        # question"). Replace it with an honest non-data fallback; never speak an
        # answer a mandated read tool was supposed to ground. Shared-loop leak
        # recovery has already populated ``_turn_executed`` when it succeeded.
        if self._evidence_required_tool:
            from dodaios.brain.public_fact_gate import (
                PUBLIC_FACT_CLARIFY_DOMAIN,
                PUBLIC_FACT_DOMAIN,
                public_fact_answer_unverified,
                public_fact_clarifying_question,
                public_fact_unfulfilled_answer,
            )

            if self._evidence_required_domain == PUBLIC_FACT_CLARIFY_DOMAIN:
                # Too vague to search: ask, in the conversation's language (the
                # small model asked its own question in English on 2026-10-28).
                _replacement = (
                    None
                    if self._last_turn_suppressed
                    else public_fact_clarifying_question(honesty_lang)
                )
            elif self._evidence_required_domain == PUBLIC_FACT_DOMAIN:
                # The system search grounds the fact check only. It is not a
                # tool the model ran, so it must not silence the action-honesty
                # gate later in this turn.
                _fact_executed = _turn_executed
                if getattr(self, "_public_fact_prefetched", False):
                    _fact_executed = {*_turn_executed, self._evidence_required_tool}
                _replacement = (
                    public_fact_unfulfilled_answer(honesty_lang)
                    if public_fact_answer_unverified(
                        response_text,
                        executed=_fact_executed,
                        suppressed=self._last_turn_suppressed,
                    )
                    else None
                )
            else:
                _replacement = _unfulfilled_replacement(
                    required_tool=self._evidence_required_tool,
                    executed=_turn_executed,
                    response_text=response_text,
                    suppressed=self._last_turn_suppressed,
                    is_write=self._evidence_required_is_write,
                    lang=honesty_lang,
                    domain=self._evidence_required_domain,
                )
            if _replacement is not None:
                log.warning(
                    "Mandated tool %s never ran (executed=%s, write=%s) — "
                    "replacing the unverified answer with an honest fallback.",
                    self._evidence_required_tool,
                    sorted(_turn_executed),
                    self._evidence_required_is_write,
                )
                response_text = _replacement
                if turn_override is not None:
                    turn_override.receipt.mark_guard_failure("mandated_tool_unfulfilled")

        # A "[used tool …]" line in the model's text is an imitation of the
        # chat history marker, never a call (live 2026-10-28: an invented train
        # story behind "[used tool search_web]"). A claimed search that never
        # ran makes the whole answer a guess; any other marker is dropped.
        from dodaios.brain.tool_marker import strip_tool_markers

        _marker_free, _claimed_tools = strip_tool_markers(response_text)
        if _claimed_tools:
            _marker_executed = _turn_executed
            if getattr(self, "_public_fact_prefetched", False):
                _marker_executed = {*_turn_executed, "search_web"}
            _phantom = sorted(set(_claimed_tools) - set(_marker_executed))
            if "search_web" in _phantom:
                from dodaios.brain.public_fact_gate import public_fact_unfulfilled_answer

                log.warning(
                    "Model typed a search_web marker but no search ran — "
                    "replacing the unverified answer."
                )
                response_text = public_fact_unfulfilled_answer(honesty_lang)
                if turn_override is not None:
                    turn_override.receipt.mark_guard_failure("unbacked_action_claim")
            else:
                if _phantom:
                    log.warning("Model typed markers for tools that never ran: %s", _phantom)
                response_text = _marker_free

        execution_evidence = set(_turn_executed)
        full_action_fallback = not execution_evidence and has_unbacked_action_claim(response_text)
        honest_response = replace_unbacked_action_claim(
            response_text,
            executed_tools=execution_evidence,
            language=honesty_lang,
        )
        if honest_response != response_text:
            log.warning(
                "Blocked a model action promise with no execution evidence."
            )
            response_text = honest_response
            if full_action_fallback and turn_override is not None:
                turn_override.receipt.mark_guard_failure("unbacked_action_claim")

        # 4. History + Events
        if use_history:
            self._history.append(BrainMessage(role="user", content=user_text))
            self._history.append(BrainMessage(role="assistant", content=response_text))
            if len(self._history) > 40:
                self._history = self._history[-40:]

        await self._publish_response_generated(
            trace_id=trace_uuid,
            text=response_text,
        )

        # Fire-and-forget: the curator extracts personal facts from the turn
        # and merges them into USER.md / people/*.md in a controlled manner.
        # Runs async, does not block the response.
        if self._curator is not None and not (
            (profile_override := _TURN_OVERRIDE.get()) is not None
            and profile_override.tool_context.get("tool_origin") == "society"
        ):
            try:
                asyncio.create_task(
                    self._curator.process_turn(user_text, response_text),
                    name="curator-process-turn",
                )
            except RuntimeError:
                # No running event loop (sync context) — skip.
                log.debug("Curator-Task nicht scheduled (kein Event-Loop)")

        return response_text
