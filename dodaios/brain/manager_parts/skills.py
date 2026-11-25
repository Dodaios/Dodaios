"""Skill matching, injection and mission dispatch for a turn."""
from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from dodaios.brain import manager as _m
from dodaios.brain.manager import (
    _PAIRED_CONNECTION_TTL_S,
    _TURN_HISTORY_OVERRIDE,
    _is_definitional_question_about,
    log,
)
from dodaios.brain.turn_planner import is_contextual_follow_up, plan_turn

if TYPE_CHECKING:
    from dodaios.brain.manager_parts._host_state import BrainHostState as _HostBase
else:
    _HostBase = object


class _SkillsMixin(_HostBase):
    """Skill matching, injection and mission dispatch for a turn."""

    def note_skill_trigger(
        self, skill_name: str, *, content: str = "", source: str = "trigger"
    ) -> None:
        """Record a direct trigger match for the next generate() turn (AD-S4).

        Called by the speech pipeline / desktop chat hook when the
        TriggerMatcher fires. The skill is NOT executed here — generate()
        resolves it, injects its instructions into the turn context (or
        dispatches a mission for ``execution: mission`` skills), and the
        normal brain turn produces the spoken answer.
        """
        self._pending_forced_skill = (skill_name, content, source)

    def _consume_pending_skill_trigger(self, user_text: str) -> None:
        """Fold a noted trigger into this turn's skill match (AD-S4)."""
        pending = self._pending_forced_skill
        self._pending_forced_skill = None
        self._skill_turn_content = ""
        self._skill_turn_source = "match"
        if pending is None:
            return
        skill_name, content, source = pending
        try:
            from dodaios.skills.skill_context import try_get_skill_context

            ctx = try_get_skill_context()
            if ctx is None:
                return
            skill = ctx.registry.get(skill_name)
        except Exception:  # noqa: BLE001
            log.warning("noted skill trigger %r could not be resolved", skill_name)
            return
        if self._skill_is_blocked(skill):
            log.info("noted skill %r is block-tier — ignored", skill_name)
            return
        self._skill_turn_match = skill
        self._skill_turn_content = content
        self._skill_turn_source = source

    def _skills_config(self) -> Any:
        """The ``[skills]`` config section.

        Reads ``self._config`` directly rather than through a defensive
        ``getattr`` chain: an earlier draft looked up a mistyped attribute name
        and silently fell back to defaults, which left shadow mode permanently
        on and made every capture test fail for a reason nothing reported. A
        wrong config read must be a crash, not a quiet behaviour change.

        The section fallback stays, because an older ``jarvis.toml`` parsed by a
        newer binary genuinely can lack it.
        """
        from dodaios.core.config import SkillsConfig

        section = getattr(self._config, "skills", None)
        return section if section is not None else SkillsConfig()

    def _match_skill_for_turn(self, user_text: str, lang: str = "auto") -> Any | None:
        """Deterministic skill-match probe (AD-S3). Returns the matched Skill or None.

        Two channels, in strict order, through the ONE shared entry point
        (``dodaios.skills.match_eval.evaluate_match``):

        1. The author's voice-trigger regex — absolute precedence, unchanged.
           Every utterance that worked before this method grew a second channel
           still takes exactly the same path.
        2. The deterministic relevance scorer — the paraphrase channel. Only
           reached on a trigger MISS, so it is purely additive.

        The relevance fallback is nested HERE rather than added as another gate
        in ``generate()`` for one reason: every guard below (definitional
        question, block tier, and — via the caller — AD-S9 and the local-action
        stand-down) is then inherited structurally instead of re-implemented,
        and the call site does not move.

        Never raises — routing must not break when the skill subsystem is
        absent (headless/mock boots).
        """
        self._skill_relevance = None
        self._skill_match_band = "none"
        self._skill_match_class = ""
        self._skill_meta_turn = ""
        try:
            from dodaios.skills import guards, match_eval
            from dodaios.skills.autofire_policy import classify, may_capture
            from dodaios.skills.skill_context import try_get_skill_context

            ctx = try_get_skill_context()
            if ctx is None:
                # No registry to look anything up in — but a request ABOUT
                # skills is still recognisable from the words alone, and the
                # flag is what keeps the skill tools in charge of the turn.
                from dodaios.skills.authoring_request import skill_meta_kind

                self._skill_meta_turn = skill_meta_kind(user_text) or ""
                return None

            # Channel 0 (2026-08-12): the user NAMED a skill ("nutz den Skill
            # X"). autofire_policy sanctions exactly this as the human path to
            # any skill class, so it resolves deterministically and inherits
            # trigger-grade rights — the prompt-only version of this promise
            # converted to zero invocations in 14 live days. Still subject to
            # the block-tier guard below via the shared decision flow.
            from dodaios.skills.explicit_request import (
                resolve_explicit_skill_request,
            )

            explicit = resolve_explicit_skill_request(user_text, ctx.registry)
            if explicit is not None:
                explicit_skill, explicit_decision = explicit
                if self._skill_is_blocked(explicit_skill):
                    log.info(
                        "explicitly named skill %s is block-tier — not captured",
                        getattr(explicit_skill, "name", "?"),
                    )
                    self._record_skill_decision(
                        user_text, explicit_decision, lang=lang,
                        vetoed_by=guards.VETO_BLOCK_TIER, skill=explicit_skill,
                    )
                    return None
                self._skill_match_band = explicit_decision.band
                self._skill_match_class = classify(explicit_skill)
                self._record_skill_decision(
                    user_text, explicit_decision, lang=lang,
                    skill=explicit_skill, fired=True,
                )
                return explicit_skill

            # Channel 0.4 (2026-09-29): scheduled work for an agent ("a briefing
            # every day at 8", "create a routine that …") is an agent routine.
            # No skill captures it — neither the skill-creator (it wrote an
            # inactive draft skill live) nor a briefing skill that would run
            # once now instead of scheduling.
            if "society-create-routine" in self._live_tool_names():
                from dodaios.society.routine_intent import wants_agent_routine

                if wants_agent_routine(user_text):
                    log.info("scheduled agent work — society-create-routine owns this turn")
                    return None

            # Channel 0.5 (2026-08-18): the user asked to CREATE a skill
            # ("erstell mir einen neuen Skill, der … mit YouTube Music …").
            # Every service named inside that sentence is the CONTENT of the
            # skill to be built, never a command to that service — yet the
            # trigger channel below would hand the turn to whichever brand
            # regex matches first (live 2026-08-18 17:51: plugin-youtube_music
            # captured the authoring turn, the model burned the tool budget on
            # `jarvisctl --help`, the user heard "Das hat gerade nicht
            # geklappt"). Resolved BEFORE the trigger channel, deterministically:
            # the skill-creator builtin captures with trigger-grade rights when
            # it is active; when it is not, NO skill captures and the
            # create-skill router tool owns the turn on its own.
            from dodaios.skills.authoring_request import (
                resolve_skill_authoring_request,
            )

            authoring = resolve_skill_authoring_request(user_text, ctx.registry)
            if authoring is not None:
                self._skill_meta_turn = authoring.kind
                authoring_skill = authoring.skill
                if authoring.kind == "lifecycle":
                    # "deaktiviere / lösch / zeig … den Skill X": the brand
                    # skill named inside must not run; the skill app-commands
                    # (skill-enable / skill-disable / skill-delete /
                    # skills-list) own the turn.
                    log.info(
                        "skill lifecycle request — no domain skill may capture "
                        "this turn; the skill app-commands own it"
                    )
                    self._record_skill_decision(
                        user_text, authoring.decision, lang=lang,
                        vetoed_by=guards.VETO_LIFECYCLE_REQUEST,
                    )
                    return None
                if authoring_skill is None:
                    log.info(
                        "skill authoring request — no domain skill may capture "
                        "this turn; the create-skill tool owns it"
                    )
                    self._record_skill_decision(
                        user_text, authoring.decision, lang=lang,
                        vetoed_by=guards.VETO_AUTHORING_REQUEST,
                    )
                    return None
                if self._skill_is_blocked(authoring_skill):
                    self._record_skill_decision(
                        user_text, authoring.decision, lang=lang,
                        vetoed_by=guards.VETO_BLOCK_TIER, skill=authoring_skill,
                    )
                    return None
                log.info(
                    "skill authoring request → %s captures the turn "
                    "(services named inside the request are content, not commands)",
                    getattr(authoring_skill, "name", "?"),
                )
                self._skill_match_band = authoring.decision.band
                self._skill_match_class = classify(authoring_skill)
                self._record_skill_decision(
                    user_text, authoring.decision, lang=lang,
                    skill=authoring_skill, fired=True,
                )
                return authoring_skill

            cfg = self._skills_config()
            decision = match_eval.evaluate_match(
                ctx.registry,
                user_text,
                lang=lang,
                limit=max(3, int(getattr(cfg, "narrow_candidates", 3)) + 2),
                use_relevance=bool(getattr(cfg, "relevance_enabled", True)),
                fire_threshold=getattr(cfg, "fire_threshold", None),
                hint_threshold=getattr(cfg, "hint_threshold", None),
            )
            if decision.top is None:
                self._record_skill_decision(user_text, decision, lang=lang)
                return None

            try:
                skill = ctx.registry.get(decision.top.skill_name)
            except Exception:  # noqa: BLE001
                self._record_skill_decision(user_text, decision, lang=lang)
                return None

            # Unchanged guards, now shared by both channels. `evidence` is the
            # RAW matched span, never a normalized token — the definitional
            # guard re-escapes it against the original text, so a
            # transliterated token would blind it on every umlaut word.
            evidence = decision.top.evidence
            if _is_definitional_question_about(user_text, evidence):
                log.info(
                    "skill %s matched token %r but the turn is a definitional "
                    "question about it — not captured (answer it instead)",
                    getattr(skill, "name", "?"),
                    evidence,
                )
                self._record_skill_decision(
                    user_text, decision, lang=lang,
                    vetoed_by=guards.VETO_DEFINITIONAL, skill=skill,
                )
                return None
            if self._skill_is_blocked(skill):
                log.info(
                    "skill %s matched but is block-tier — turn not captured",
                    getattr(skill, "name", "?"),
                )
                self._record_skill_decision(
                    user_text, decision, lang=lang,
                    vetoed_by=guards.VETO_BLOCK_TIER, skill=skill,
                )
                return None
            # Two music connectors, one domain: rematch BEFORE the
            # disconnected veto. Live 2026-08-19 17:13: plugin-spotify won
            # the trigger, the veto aborted capture, and the connected
            # YouTube Music sibling never ran — the live model then
            # announced a playlist with function_calls=0. A named service
            # still wins; veto only if the winner is still disconnected.
            skill = self._prefer_music_service(skill, user_text, ctx.registry)
            if self._paired_plugin_disconnected(skill):
                # Two connectors can serve one domain (Spotify and YouTube
                # Music both answer "spiel Musik"). A paired skill whose plugin
                # holds no usable credential must not capture the turn: it
                # would steer the model at a tool that can only answer "not
                # connected" while the connected sibling sits in the surface.
                log.info(
                    "skill %s matched but its plugin is not connected — turn "
                    "not captured, routing stays with the live tool surface",
                    getattr(skill, "name", "?"),
                )
                self._record_skill_decision(
                    user_text, decision, lang=lang,
                    vetoed_by=guards.VETO_PLUGIN_NOT_CONNECTED, skill=skill,
                )
                return None

            self._skill_match_band = decision.band
            self._skill_match_class = classify(skill)

            # A trigger hit keeps its historical unconditional capture: the
            # author wrote that phrase precisely so it would fire, and changing
            # that would be a behaviour regression, not a safety win.
            if decision.source == match_eval.SOURCE_TRIGGER:
                self._record_skill_decision(
                    user_text, decision, lang=lang, skill=skill, fired=True,
                )
                return skill

            # --- relevance channel: capture is a privilege, not a default ---
            self._skill_relevance = decision
            allowed, veto = may_capture(
                skill,
                decision.band,
                override=self._skill_autofire_override(skill),
                min_band=str(getattr(cfg, "auto_fire_min_band", "fire")),
            )
            if not allowed:
                log.info(
                    "relevance match %s (band=%s, class=%s) does not capture: %s",
                    getattr(skill, "name", "?"),
                    decision.band,
                    self._skill_match_class,
                    veto,
                )
                self._record_skill_decision(
                    user_text, decision, lang=lang, vetoed_by=veto, skill=skill,
                )
                return None

            # Fallback mirrors the SkillsConfig default (False since
            # 2026-08-12) so a duck-typed config cannot silently re-shadow.
            if bool(getattr(cfg, "relevance_shadow", False)):
                # Shadow mode: record what WOULD have happened, change nothing.
                # The narrowed candidate hint still ships, so the model keeps
                # the benefit while the maintainer reviews real decisions.
                log.info(
                    "relevance match %s (band=%s) SHADOWED — would have captured "
                    "the turn; review GET /api/skills/match-log",
                    getattr(skill, "name", "?"),
                    decision.band,
                )
                self._record_skill_decision(
                    user_text, decision, lang=lang, skill=skill,
                    vetoed_by=guards.VETO_SHADOW_MODE, shadow=True,
                )
                return None

            self._record_skill_decision(
                user_text, decision, lang=lang, skill=skill, fired=True,
            )
            return skill
        except Exception:  # noqa: BLE001
            return None

    def _skill_autofire_override(self, skill: Any) -> str | None:
        """The user's persisted per-skill auto-fire choice, if any."""
        try:
            from dodaios.skills.prefs import load_autofire_prefs

            return load_autofire_prefs().get(getattr(skill, "name", ""))
        except Exception:  # noqa: BLE001
            return None

    def _record_skill_decision(
        self,
        user_text: str,
        decision: Any,
        *,
        lang: str = "auto",
        vetoed_by: str = "",
        skill: Any | None = None,
        fired: bool = False,
        shadow: bool = False,
    ) -> None:
        """Log the decision to the ring and the bus. Never raises, never blocks.

        Emitted on EVERY evaluation, including "nothing matched" and every veto.
        That completeness is the point: until now each veto was a ``log.info``
        nobody reads, which is exactly why "my skill never fires" could not be
        diagnosed.
        """
        try:
            from dodaios.skills import match_log
            from dodaios.skills.autofire_policy import classify

            autofire_class = classify(skill) if skill is not None else ""
            match_log.record(
                utterance=user_text,
                decision=decision,
                lang=lang,
                vetoed_by=vetoed_by,
                autofire_class=autofire_class,
                fired=fired,
                shadow=shadow,
            )
        except Exception:  # noqa: BLE001
            return
        try:
            from dodaios.skills.match_log import utterance_hash
            from dodaios.skills.schema import SkillMatchEvaluated

            top = getattr(decision, "top", None)
            event = SkillMatchEvaluated(
                source_layer="brain.manager",
                utterance_hash=utterance_hash(user_text),
                lang=lang,
                source=str(getattr(decision, "source", "none")),
                band=str(getattr(decision, "band", "none")),
                winner=str(getattr(top, "skill_name", "") if top is not None else ""),
                autofire_class=autofire_class,
                vetoed_by=vetoed_by,
                fired=fired,
                shadow=shadow,
                elapsed_us=int(getattr(decision, "elapsed_us", 0) or 0),
                candidates=tuple(
                    (getattr(c, "skill_name", ""), round(float(getattr(c, "score", 0.0)), 4))
                    for c in (getattr(decision, "candidates", ()) or ())[:3]
                ),
            )
            loop = asyncio.get_running_loop()
            loop.create_task(self._bus.publish(event))
        except Exception:  # noqa: BLE001
            log.debug("SkillMatchEvaluated publish failed", exc_info=True)

    def _previous_user_turn_text(self, *, use_history: bool) -> str:
        """Return the latest bounded user message from this task's history."""
        override = _TURN_HISTORY_OVERRIDE.get()
        history = (
            tuple(override)
            if override is not None
            else tuple(self._history if use_history else ())
        )
        for message in reversed(history):
            if getattr(message, "role", None) != "user":
                continue
            content = getattr(message, "content", "")
            if isinstance(content, str) and content.strip():
                return content.strip()[-1_200:]
        return ""

    def _recent_user_turn_texts(self, count: int, *, use_history: bool) -> tuple[str, ...]:
        """The last ``count`` user messages of this task's history, newest first."""
        override = _TURN_HISTORY_OVERRIDE.get()
        history = (
            tuple(override)
            if override is not None
            else tuple(self._history if use_history else ())
        )
        found: list[str] = []
        for message in reversed(history):
            if len(found) >= count:
                break
            if getattr(message, "role", None) != "user":
                continue
            content = getattr(message, "content", "")
            if isinstance(content, str) and content.strip():
                found.append(content.strip()[-1_200:])
        return tuple(found)

    def _contextual_routing_state(
        self, user_text: str, *, use_history: bool
    ) -> tuple[str, tuple[str, ...]]:
        """Return bounded context and live tools inherited by a follow-up.

        The actual user message and tool arguments stay untouched. Only
        deterministic skill/plugin/MCP selection sees the previous user turn,
        and only when the shared planner identifies an explicit referential
        follow-up. An unrelated request therefore cannot replay an old action.
        """
        previous = self._previous_user_turn_text(use_history=use_history)
        if not previous:
            return user_text, ()
        if not is_contextual_follow_up(user_text, (previous,)):
            return user_text, ()

        try:
            plan = plan_turn(
                user_text,
                tool_names=tuple((getattr(self, "_tools", None) or {}).keys()),
                context=(previous,),
            )
        except Exception:  # noqa: BLE001 - context must never break a turn
            return user_text, ()
        live_tools = tuple(
            name
            for name in plan.required_capabilities
            if name in (getattr(self, "_tools", None) or {})
        )
        contextual = (
            f"Previous user request: {previous}\n"
            f"Current referential follow-up: {user_text}"
        )
        return contextual, live_tools

    @staticmethod
    def _skill_is_blocked(skill: Any) -> bool:
        """True for risk_policy block-tier skills — they must never capture a
        turn (mirrors the run-skill tool's block gate)."""
        fm = getattr(skill, "frontmatter", None)
        if fm is None:
            return True
        try:
            return fm.risk_policy.default_tier == "block"
        except Exception:  # noqa: BLE001
            return False

    def _prefer_music_service(self, skill: Any, user_text: str, registry: Any) -> Any:
        """Swap a matched MUSIC skill for its sibling when the resolver says the
        request belongs to the other service (see ``dodaios.core.music_service``).

        Reads ``[music] preferred_service``. Never raises and never swaps to a
        skill that is missing or whose plugin is not connected — a fault keeps
        the match as it was."""
        try:
            from dodaios.core.music_constants import MUSIC_PLUGIN_IDS
            from dodaios.core.music_service import resolve_music_service

            fm = getattr(skill, "frontmatter", None)
            plugin_id = str(getattr(fm, "plugin_id", "") or "").strip()
            if plugin_id not in MUSIC_PLUGIN_IDS:
                return skill
            connected = [
                pid for pid in MUSIC_PLUGIN_IDS if not self._plugin_disconnected(pid)
            ]
            music_cfg = getattr(self._config, "music", None)
            preferred = str(getattr(music_cfg, "preferred_service", "auto") or "auto")
            target = resolve_music_service(
                user_text, preferred=preferred, connected=connected, matched=plugin_id
            )
            if not target or target == plugin_id or target not in connected:
                return skill
            sibling = registry.get(f"plugin-{target}")
            if sibling is None:
                return skill
            log.info(
                "music request routed to %s instead of %s (preferred=%s, connected=%s)",
                target, plugin_id, preferred, connected,
            )
            return sibling
        except Exception as exc:  # noqa: BLE001 — a routing nicety must never break a turn
            log.debug("music preference routing skipped: %s", exc)
            return skill

    @classmethod
    def _paired_plugin_disconnected(cls, skill: Any, *, store: Any | None = None) -> bool:
        """True when ``skill`` is paired to a CATALOG plugin whose credential is
        absent or flagged for re-auth (see :meth:`_plugin_disconnected`)."""
        fm = getattr(skill, "frontmatter", None)
        plugin_id = str(getattr(fm, "plugin_id", "") or "").strip()
        if not plugin_id:
            return False
        return cls._plugin_disconnected(plugin_id, store=store)

    @staticmethod
    def _plugin_disconnected(plugin_id: str, *, store: Any | None = None) -> bool:
        """True when catalog plugin ``plugin_id`` holds no usable credential.

        Only catalog plugins are judged — every one of them authenticates, so
        "no token" really means "not connected". A community skill naming an
        unknown ``plugin_id`` is left alone: nothing here may veto a skill on
        a guess. Any store or catalog fault answers False for the same reason
        (a fault must never decide a turn). ``store`` is injectable for tests
        (a fake with ``load``); the default is the real TokenStore.

        The keyring read is synchronous and this sits on the turn path, so the
        answer is remembered per plugin for a short while: one read per
        plugin per :data:`_PAIRED_CONNECTION_TTL_S`, not one per matched turn.
        A connect made inside that window merely routes without the skill's
        guidance for a few seconds — the tool itself is callable at once."""
        if not plugin_id:
            return False
        now = time.monotonic()
        if store is None:
            cached = _m._PAIRED_CONNECTION_CACHE.get(plugin_id)
            if cached is not None and cached[0] > now:
                return cached[1]
        try:
            from dodaios.marketplace.catalog_data import load_catalog

            if load_catalog().by_id(plugin_id) is None:
                return False
            if store is None:
                from dodaios.marketplace.token_store import TokenStore

                store = TokenStore()
                remember = True
            else:
                remember = False
            tokens = store.load(plugin_id)
        except Exception:  # noqa: BLE001 — a store fault must not decide a turn
            return False
        disconnected = tokens is None or (
            not getattr(tokens, "access", None) or bool(getattr(tokens, "needs_reauth", False))
        )
        if remember:
            _m._PAIRED_CONNECTION_CACHE[plugin_id] = (now + _PAIRED_CONNECTION_TTL_S, disconnected)
        return disconnected

    def _render_skill_turn_hint(self) -> str | None:
        """Steering hint appended to the turn context on a skill-matched turn."""
        skill = self._skill_turn_match
        if skill is None:
            return None
        name = getattr(skill, "name", "")
        return (
            f"[Skill match] The user's request matches the installed skill "
            f"`{name}` — call the run-skill tool with skill_name=\"{name}\" "
            "now and follow the returned instructions, unless that is "
            "clearly wrong."
        )

    def _skill_stand_downs_allowed(self) -> bool:
        """May this turn's matched skill suppress the other deterministic paths?

        True for the historical case — an author's trigger, or an
        instruction-only skill at FIRE — and False for anything the relevance
        layer merely inferred about a tool-backed skill. In the False case the
        skill still injects its instructions, but ``run-skill`` stays visible and
        the local-action gate keeps precedence, which turns a wrong match from a
        turn hijack into a suggestion the model can decline.

        This distinction is the single most important safety property of the
        relevance layer: capture is not all-or-nothing.
        """
        skill = self._skill_turn_match
        if skill is None:
            return False
        try:
            from dodaios.skills.autofire_policy import stand_downs_allowed
            from dodaios.skills.match_eval import BAND_FIRE, SOURCE_TRIGGER
        except Exception:  # noqa: BLE001
            return True
        # An author-written trigger keeps its unconditional historical rights.
        if getattr(self, "_skill_relevance", None) is None:
            return True
        decision = self._skill_relevance
        if getattr(decision, "source", "") == SOURCE_TRIGGER:
            return True
        return stand_downs_allowed(skill, getattr(decision, "band", BAND_FIRE))

    def _drop_run_skill_when_inline_injected(self, tools: Any) -> Any:
        """Hide ``run-skill`` once a matched skill's instructions are already on
        the turn context (``_skill_injected_inline``).

        With the instructions inline (AD-S4) no tool call is needed; keeping
        run-skill visible only tempts a weak model into a redundant, garbled
        run-skill call — the gemini-fast ``<call:tool.run-skill ...>`` text leak
        (forensic 2026-06-24). Dropping it makes skill execution provider- and
        model-agnostic: every model just follows the injected instructions, no
        tool call required. No-op when the skill was not inline-injected, or the
        tool set is not a dict (intelligent-router lead path).

        Kept ONLY while the turn's match is entitled to the full stand-down. A
        relevance-inferred match on a tool-backed skill leaves ``run-skill``
        visible on purpose: dropping it is what removes the model's ability to
        signal "wrong skill", and the model needs that escape hatch exactly when
        nobody stated an intent for this skill.
        """
        if not getattr(self, "_skill_injected_inline", False):
            return tools
        if not isinstance(tools, dict):
            return tools
        if not self._skill_stand_downs_allowed():
            return tools
        return {k: v for k, v in tools.items() if k != "run-skill"}

    #: Cap on the conditionally-injected instruction text for a NARROW match.
    #: Bounded so one pathological skill body cannot flood a voice turn.
    _NARROW_INJECTION_CHAR_CAP = 60_000

    def _render_skill_candidate_hint(self, user_text: str = "") -> str | None:
        """Narrow the skill choice for a turn the matcher did NOT capture.

        The router's real problem was never that skills are invisible — it is
        that all the listed skills look equally plausible while ~26k tokens of
        tool schemas compete for attention. This block puts the candidates that
        actually scored right next to the user's message, where recency is
        worth more than position in a long cached list.

        2026-08-12 escalation ("skills never fire" rework): a name-and-blurb
        hint measurably did nothing — 60 NARROW hints shipped over 14 live days
        and the model called run-skill exactly zero times. The fast router
        model does not convert a suggestion into a tool round trip. So for a
        CLEAR top candidate that cannot dispatch anything, the hint now carries
        the skill's full rendered instructions in a conditional frame — the
        model only has to decide "is this what the user meant", not decide AND
        remember to call a tool (mirrors Claude Code loading a skill's whole
        instruction body once selected). The decision explicitly stays with
        the model: a wrong candidate is ignored, never executed, so a skill is
        still only ever used when it serves the request.

        A dispatching-class candidate (mission execution, block tier, macro
        body) NEVER gets its instructions inlined off an inferred match — its
        body is a process-start directive, and no matcher may authorize that
        (same line ``autofire_policy.may_capture`` draws). It keeps the plain
        named hint, where the model must consciously call ``run-skill``.

        Deliberately rides the PER-TURN context and never the cached system
        prefix: rewriting that prefix per turn would break prompt caching on
        every single turn, which costs far more than it could ever save.

        Returns ``None`` on a captured turn, a dead scorer, or a weak ranking —
        so the common case adds nothing at all.
        """
        decision = getattr(self, "_skill_relevance", None)
        if decision is None or self._skill_turn_match is not None:
            return None
        candidates = getattr(decision, "candidates", ()) or ()
        if not candidates:
            return None

        cfg = self._skills_config()
        limit = max(1, int(getattr(cfg, "narrow_candidates", 3)))
        try:
            from dodaios.skills.match_eval import BAND_NONE
            from dodaios.skills.skill_context import try_get_skill_context

            ctx = try_get_skill_context()
            if ctx is None:
                return None
            registry = ctx.registry
        except Exception:  # noqa: BLE001
            return None

        # (candidate, skill, blurb) triples for every scoring candidate.
        scored: list[tuple[Any, Any, str]] = []
        for candidate in candidates:
            if len(scored) >= limit:
                break
            if getattr(candidate, "band", BAND_NONE) == BAND_NONE:
                continue
            name = getattr(candidate, "skill_name", "")
            try:
                skill = registry.get(name)
            except Exception:  # noqa: BLE001
                continue
            frontmatter = getattr(skill, "frontmatter", None)
            if frontmatter is None:
                continue
            description = (getattr(frontmatter, "description", "") or "").strip()
            when_to_use = (getattr(frontmatter, "when_to_use", "") or "").strip()
            blurb = f"{description} {when_to_use}".strip()[:400]
            scored.append((candidate, skill, blurb))
        if not scored:
            return None

        conditional = self._render_conditional_narrow_injection(
            scored, ctx, user_text, decision
        )
        if conditional is not None:
            return conditional

        # Shared with the realtime session's own candidate hint — one wording,
        # so the suggestion does not change shape depending on which engine is
        # answering (dodaios/skills/prompt_injection.py).
        from dodaios.skills.prompt_injection import render_skill_candidate_hint

        return render_skill_candidate_hint(
            [(str(getattr(s, "name", "")), b) for _, s, b in scored]
        ) or None

    def _render_conditional_narrow_injection(
        self,
        scored: list[tuple[Any, Any, str]],
        ctx: Any,
        user_text: str,
        decision: Any,
    ) -> str | None:
        """Full instructions for a clear, non-dispatching top candidate.

        Returns ``None`` whenever the escalation conditions do not hold, so the
        caller falls back to the plain named hint. Never raises.
        """
        try:
            from dodaios.skills.autofire_policy import CLASS_DISPATCHING, classify
            from dodaios.skills.relevance import MARGIN_ABS

            top_candidate, top_skill, top_blurb = scored[0]
            if classify(top_skill) == CLASS_DISPATCHING:
                return None
            # Clear winner only: two near-tied candidates are genuine ambiguity
            # and stay a short list the model disambiguates from.
            margin = float(getattr(decision, "margin", 0.0) or 0.0)
            if len(scored) > 1 and margin < MARGIN_ABS:
                return None
            instructions = ctx.runner.render_instructions(
                top_skill,
                args={
                    "content": "",
                    "utterance": user_text,
                    "_trigger": "relevance-hint",
                },
            )
        except Exception:  # noqa: BLE001
            log.debug("conditional narrow injection failed", exc_info=True)
            return None
        if not instructions or not str(instructions).strip():
            return None
        text = str(instructions).strip()
        if len(text) > self._NARROW_INJECTION_CHAR_CAP:
            text = text[: self._NARROW_INJECTION_CHAR_CAP - 1] + "…"

        name = getattr(top_skill, "name", "")
        runner_up_lines = [
            f"- `{getattr(s, 'name', '')}` — {b}" for _, s, b in scored[1:]
        ]
        tail = (
            (
                "\nLower-scored alternatives (ranked suggestions, not a "
                "verdict):\n" + "\n".join(runner_up_lines) + "\n"
                "If one of those fits the request better, call the `run-skill` "
                "tool with that name instead."
            )
            if runner_up_lines
            else ""
        )
        return (
            f"[Likely skill match — decide, then act] The user's request "
            f"scored closest to the installed skill `{name}` — {top_blurb}\n"
            "Judge from the user's ACTUAL words: if they are asking for what "
            "this skill does — even loosely, in wording that is not the "
            "trigger phrase — follow the instructions below NOW with your "
            "available tools instead of answering freely, and never read them "
            "aloud. If the request is genuinely about something else, ignore "
            "this entire block and answer normally; do not mention the skill. "
            "A skill is only ever used when it truly serves the request.\n"
            f"--- skill instructions (`{name}`) ---\n"
            f"{text}\n"
            f"--- end of skill instructions ---{tail}"
        )

    def _render_skill_turn_injection(self, user_text: str) -> str | None:
        """Render the matched skill's instructions for direct turn injection.

        AD-S4: a matched turn short-circuits the run-skill round trip — the
        rendered instructions ride on the turn context, so the model executes
        them in this very turn (guaranteed invocation). Publishes
        ``SkillInvoked``. Falls back to the steering hint when rendering
        fails (the model can still call run-skill itself).

        Sets ``_skill_injected_inline`` True ONLY when the real instructions
        were injected (not the hint fallback) so the caller can hide run-skill
        for the turn (provider-agnostic execution, no tool-call leak).
        """
        self._skill_injected_inline = False
        skill = self._skill_turn_match
        if skill is None:
            return None
        name = getattr(skill, "name", "")
        try:
            from dodaios.skills.skill_context import try_get_skill_context

            ctx = try_get_skill_context()
            if ctx is None:
                return self._render_skill_turn_hint()
            instructions = ctx.runner.render_instructions(
                skill,
                args={
                    "content": self._skill_turn_content,
                    "utterance": user_text,
                    "_trigger": self._skill_turn_source,
                },
            )
        except Exception:  # noqa: BLE001
            log.warning(
                "skill instruction render failed for %s — hint fallback", name,
                exc_info=True,
            )
            return self._render_skill_turn_hint()
        self._publish_skill_invoked(name, source=self._skill_turn_source)
        # The real instructions are now inline — the model needs no run-skill
        # call; the caller drops that tool so a weak model cannot leak a garbled
        # tool call (provider-agnostic skill execution).
        self._skill_injected_inline = True
        from dodaios.agent_chat.lead_turn_contract import skill_instructions_block

        return skill_instructions_block(name, instructions)

    def _publish_skill_invoked(self, skill_name: str, *, source: str) -> None:
        """Fire-and-forget SkillInvoked publish (AD-S6 observability)."""
        try:
            from dodaios.skills.schema import SkillInvoked

            event = SkillInvoked(
                source_layer="brain.manager",
                skill_name=skill_name,
                source=source,
            )
            loop = asyncio.get_running_loop()
            loop.create_task(self._bus.publish(event))
        except Exception:  # noqa: BLE001
            log.debug("SkillInvoked publish failed", exc_info=True)

    async def _maybe_dispatch_skill_mission(
        self, user_text: str, *, trace_id: UUID | None = None
    ) -> str | None:
        """Dispatch an ``execution: mission`` skill as a worker brief (AD-S5).

        Returns the optimistic ACK string when the mission was dispatched, or
        ``None`` for inline skills / when dispatch is impossible (the caller
        then keeps the inline-injection path — AD-OE6: no silent drop).
        """
        skill = self._skill_turn_match
        if skill is None:
            return None
        fm = getattr(skill, "frontmatter", None)
        if fm is None or getattr(fm, "execution", "inline") != "mission":
            return None
        tool = self._tools.get("spawn_worker")
        if tool is None or self._tool_executor is None:
            log.warning(
                "mission skill %s matched but spawn_worker unavailable — "
                "falling back to inline execution",
                getattr(skill, "name", "?"),
            )
            return None
        name = getattr(skill, "name", "")
        try:
            from dodaios.skills.skill_context import try_get_skill_context

            ctx = try_get_skill_context()
            if ctx is None:
                return None
            instructions = ctx.runner.render_instructions(
                skill,
                args={
                    "content": self._skill_turn_content,
                    "utterance": user_text,
                    "_trigger": self._skill_turn_source,
                },
            )
        except Exception:  # noqa: BLE001
            log.warning(
                "mission skill %s could not render — inline fallback", name,
                exc_info=True,
            )
            return None
        args = {
            "utterance": (
                f"Execute the installed skill '{name}' as a background "
                f"mission. The user said: {user_text!r}\n\n"
                f"Skill instructions:\n{instructions}"
            ),
            "context_hints": [
                f"Dispatched deterministically from the skill system "
                f"(execution: mission, skill: {name})."
            ],
            "action": "",
            "target": "",
        }
        log.info("Mission skill dispatch: %s (%r)", name, user_text[:120])
        try:
            result = await self._tool_executor.execute(
                tool,
                args,
                user_utterance=user_text,
                trace_id=trace_id or uuid4(),
            )
        except Exception:  # noqa: BLE001
            log.warning("mission skill dispatch failed — inline fallback", exc_info=True)
            return None
        if not result.success:
            log.warning(
                "mission skill dispatch unsuccessful (%s) — inline fallback",
                result.error,
            )
            return None
        self._publish_skill_invoked(name, source=self._skill_turn_source)
        return str(result.output or "")
