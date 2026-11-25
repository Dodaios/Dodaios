"""Reply-language handling and system-prompt assembly."""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from uuid import UUID

from dodaios.brain import manager as _m
from dodaios.brain import proactivity as _proactivity
from dodaios.brain.assistant_name import resolve_assistant_name
from dodaios.brain.identity import identity_block
from dodaios.brain.local_action_gate import LocalToolCall
from dodaios.brain.manager import (
    _CORE_CONTRACT,
    _CORE_MEMORY_MAX_CHARS,
    _PUBLISH_RESPONSE_EVENT,
    _REPLY_LANG_NAMES,
    _REPLY_LANGS,
    _TURN_HISTORY_OVERRIDE,
    _TURN_OVERRIDE,
    _WRITTEN_CHAT_RULES,
    _WRITTEN_CHAT_STYLE,
    _current_turn_language,
    _is_written_turn,
    _provider_down_phrase,
    _provider_identity_directive,
    _turn_phrase_language,
    log,
)
from dodaios.brain.persona_loader import load_effective_persona_prompt
from dodaios.core.config import normalize_force_spawn_mode
from dodaios.core.events import ResponseGenerated
from dodaios.core.response_style import CONVERSATIONAL_RESPONSE_STYLE
from dodaios.core.turn_language import (
    DEFAULT_LOCALE,
    TURN_LANGUAGE,
    conversation_language_from_history,
    resolve_conversation_language,
)
from dodaios.i18n import catalog as i18n_catalog
from dodaios.i18n.locales import is_known_language, language_name

if TYPE_CHECKING:
    from dodaios.brain.manager_parts._host_state import BrainHostState as _HostBase
else:
    _HostBase = object


class _PromptMixin(_HostBase):
    """Reply-language handling and system-prompt assembly."""

    @property
    def reply_language(self) -> str:
        """The active reply-language pin: ``auto`` | ``de`` | ``en`` | ``es``."""
        return self._reply_language

    @property
    def force_spawn_mode(self) -> str:
        """The live ``brain.routing.force_spawn_mode``: strict/balanced/permissive.

        The ONE live accessor for the setting. ``_should_force_spawn`` reads it
        here, and ``dodaios.brain.spawn_gate.active_force_spawn_mode`` reads it
        through the runtime reference to this manager — so the deterministic
        path and the LLM gate can never end up in different modes on the same
        turn. Unknown values normalise to the shipped default, never to a mode
        the user did not ask for.
        """
        return normalize_force_spawn_mode(
            getattr(self._config.brain.routing, "force_spawn_mode", "")
        )

    @property
    def conversation_language(self) -> str:
        """The sticky language of the conversation so far (any code, or "").

        de/en/es/pt or a language without translated phrases ("tr", "fr", ...);
        consumers narrow it with ``resolve_output_language``/``phrase_locale``.

        Read by the speech pipeline and threaded into deterministic tool
        readbacks so a thin interjection ("Now") stays in the running
        conversation's language instead of flipping the whole turn (forensic
        2026-06-18). Empty until a substantive turn establishes it; an explicit
        ``reply_language`` pin overrides it everywhere anyway.
        """
        return self._conversation_language

    def _update_turn_language(self, user_text: str) -> None:
        """Resolve this turn's language and maintain the sticky conversation
        language, applied at the top of ``generate()``.

        Stickiness and explicit corrections use the same central resolver as
        realtime and speech output, including evidence for a switch. A pin
        leaves ``_turn_detected_lang`` empty so ``_reply_language_directive``
        uses the pin; genuinely ambiguous text stays ``"unknown"`` so the
        directive keeps its soft "mirror the user" form.
        """
        if self._reply_language in _REPLY_LANG_NAMES:
            self._turn_detected_lang = ""
            return
        detected = resolve_conversation_language(
            self._reply_language,
            None,
            user_text,
            conversation_language=self._conversation_baseline(),
        )
        self._turn_detected_lang = detected
        if TURN_LANGUAGE.get() is not None:  # inside generate(): scope it to the turn
            TURN_LANGUAGE.set(detected)
        if is_known_language(detected):
            self._conversation_language = detected

    def _conversation_baseline(self) -> str:
        """The conversation language this turn continues.

        A chat turn carries its session's own history (``history_override``):
        its language comes from THAT conversation, so a crash, a restart or a
        turn in another chat or on voice never changes it (forensic
        2026-10-19: a Turkish chat answered in German, Spanish and English
        after errors). A classic turn without a known language yet replays the
        live history once.
        """
        history = _TURN_HISTORY_OVERRIDE.get()
        if history is not None:
            # Only this chat's own history: never a language another chat or
            # a voice call left in the shared field.
            return conversation_language_from_history(history)
        if self._conversation_language:
            return self._conversation_language
        return conversation_language_from_history(getattr(self, "_history", None) or ())

    def set_reply_language(self, lang: str) -> None:
        """Live-switch the reply-language pin (desktop "Languages" view).

        Takes effect on the next turn (the directive is rebuilt per call to
        ``_build_system_prompt``). Raises ``ValueError`` for unknown codes so a
        bad REST payload surfaces as a 4xx instead of silently no-op'ing.
        """
        code = lang.strip().lower() if isinstance(lang, str) else ""
        if code not in _REPLY_LANGS:
            raise ValueError(
                f"unknown reply language {lang!r} (allowed: {sorted(_REPLY_LANGS)})"
            )
        self._reply_language = code

    def _resolve_turn_lang(self) -> str:
        """The de/en/es/pt key this turn's output is localized to.

        The single authoritative resolver consumed by every ``ResponseGenerated``
        publish (success replies AND the total-failure apology) so the recorded
        transcript language is consistent and never the binary ``_looks_german``
        gate — which silently tags any non-German reply "en" and so drops Spanish
        (Runtime Output Language doctrine). An explicit pin wins; in auto mode it
        is THIS turn's language (set at the top of generate()), else the
        conversation's. A language without translated phrases, or none at all,
        is English (``DEFAULT_LOCALE``) — never German.
        """
        lang = self._reply_language
        if lang not in _REPLY_LANG_NAMES:
            turn = _current_turn_language(self)
            lang = turn if is_known_language(turn) else getattr(
                self, "_conversation_language", ""
            )
        return lang if lang in _REPLY_LANG_NAMES else DEFAULT_LOCALE

    def _next_provider_down_phrase(self, cause: str | None = None) -> str:
        """Localized 'I can't reach my model' apology + advance the rotation.

        Spoken when the whole provider chain fails. ``cause`` (a classified
        failure category) makes the phrase state WHY and the in-app fix —
        still voice-safe, no provider names/URLs — the detailed diagnostic
        stays logged, never spoken (live complaint 2026-06-01: the grok/
        Anthropic billing message was read aloud while Gemini was active).
        """
        phrase = _provider_down_phrase(
            self._resolve_turn_lang(), self._provider_down_idx, cause
        )
        self._provider_down_idx += 1
        return phrase

    async def _provider_down_reply(
        self, trace_uuid: UUID, cause: str | None = None
    ) -> str:
        """Total-failure apology, ALSO surfaced to the transcript.

        Normal calls publish the phrase as ``ResponseGenerated`` so the
        SessionRecorder records it as the turn's ``jarvis_text``. Internal
        realtime delegates transfer that event ownership to their session,
        which records what the user actually heard. The apology is deliberately
        NOT appended to conversation history because a provider outage must not
        pollute the LLM context for later turns.
        """
        phrase = self._next_provider_down_phrase(cause)
        # _next_provider_down_phrase already localized the phrase via
        # _resolve_turn_lang; resolving again here is deterministic (same pin /
        # detected-language inputs, the rotation index does not affect language)
        # and only tags the transcript's jarvis_lang — NEVER _looks_german, which
        # would mislabel a Spanish apology as English (Runtime Output Language).
        await self._publish_response_generated(trace_id=trace_uuid, text=phrase)
        return phrase

    async def _publish_response_generated(self, *, trace_id: UUID, text: str) -> None:
        """Publish the public response event unless this call is an internal reply."""
        if not _PUBLISH_RESPONSE_EVENT.get():
            return
        await self._bus.publish(
            ResponseGenerated(
                trace_id=trace_id,
                text=text,
                language=self._resolve_turn_lang(),
            )
        )

    def _mandatory_lang_directive(self, name: str) -> str:
        """The hard MANDATORY reply-language pin for a named language.

        Shared by an explicit ``brain.reply_language`` pin and the auto-mode
        per-turn pin (``_turn_detected_lang``) so both carry identical, strong
        wording that survives tool-synthesis.
        """
        return (
            f"REPLY LANGUAGE — MANDATORY: Always reply in {name}. Keep names, brands and "
            "technical identifiers (e.g. Anthropic, GitHub, paths, code) untranslated."
        )

    def _reply_language_directive(self) -> str:
        """The reply-language instruction appended last to the system prompt.

        Names the target language explicitly and is placed last so it wins by
        recency; it must start with "REPLY LANGUAGE" (``cli_prompt_context``
        cuts the block from there to the end). Pinned modes carve out proper
        nouns / brand names / technical identifiers so e.g. "Anthropic" or
        "GitHub" are never translated — the user's explicit requirement.
        """
        name = _REPLY_LANG_NAMES.get(self._reply_language)
        if name is not None:
            return self._mandatory_lang_directive(name)
        # auto mode: when THIS turn's language is confidently detected, pin it
        # HARD with the same MANDATORY wording as an explicit pin. A soft
        # "please mirror" line let the model anchor to German on clean English
        # input — most visibly on tool-synthesis turns, where the question is
        # far from the generation point.
        # ``_turn_detected_lang`` is set per turn by generate(); ambiguous text
        # detects as "unknown" (not in _REPLY_LANG_NAMES) and falls through to
        # the soft mirror. The pin only changes when the user's language
        # changes, so the cached system prefix stays stable within a
        # single-language conversation.
        # Any recognised language pins, not only the four with translated
        # phrases: a Turkish conversation is answered in Turkish.
        turn_name = language_name(_current_turn_language(self))
        if turn_name is not None:
            return self._mandatory_lang_directive(turn_name)
        return (
            "REPLY LANGUAGE: reply in the SAME language as the user's latest message "
            "(Portuguese means European Portuguese, never Brazilian). Keep names, brands and "
            "technical identifiers untranslated."
        )

    def _action_failed_phrase(self, user_text: str) -> str:
        """Localized leak-recovery fallback (live bug 2026-06-10 23:12).

        Spoken when a provider leaked a tool_use block as text and the
        recovery produced no speakable final. Was a hardcoded German string —
        an English turn ("What's weather like tomorrow?") was answered in
        German. A pinned reply language wins; ``auto`` follows the
        conversation; anything else is English.
        """
        return i18n_catalog.pick(_m._ACTION_FAILED_PHRASES, _turn_phrase_language(self, user_text))

    def _phrase_language(self, user_text: str) -> str:
        """The de/en/es/pt language of a system phrase for *user_text*."""
        return _turn_phrase_language(self, user_text)

    def _direct_ack_language(self, user_text: str) -> str:
        """Resolve ``de``/``en``/``es`` for a DIRECT fast-path acknowledgement.

        Mirrors :meth:`_action_failed_phrase`: an explicit ``reply_language``
        pin (the desktop "Languages" view) wins; otherwise the turn's language
        within the running conversation; anything else is English. The DIRECT
        path runs off the LLM, so this is the only place the turn language can
        be applied to the spoken acknowledgement.
        """
        return _turn_phrase_language(self, user_text)

    def _localize_direct_ack(
        self, call: LocalToolCall, raw_output: str, lang: str
    ) -> str:
        """Localize a deterministic DIRECT-path acknowledgement.

        The DIRECT local-action path surfaces the tool ``output`` VERBATIM to
        the user (no LLM re-render), so a tool's hardcoded German success string
        would otherwise reach an English/Spanish speaker untranslated (live bug
        2026-06-15: an English "open my explorer" turn was acknowledged in
        German). ``open_app`` is the one fast-path tool whose success output
        is a spoken acknowledgement; translate only its leading German verb and
        keep the suffix (the actual app / URL it reported). Any non-matching
        output — a future tool, a test stand-in — passes through unchanged.
        """
        if call.name != "open_app" or lang == "de":
            return raw_output
        de_prefix = _m._OPEN_APP_ACK_PREFIX["de"]
        target_prefix = _m._OPEN_APP_ACK_PREFIX.get(lang)
        if target_prefix is not None and raw_output.startswith(de_prefix):
            return target_prefix + raw_output[len(de_prefix):]
        return raw_output

    @staticmethod
    def _is_lead_turn() -> bool:
        """Is this prompt build for the lead conversation (either runner)?"""
        from dodaios.brain.lead_doctrine import LEAD_TURN

        override = _TURN_OVERRIDE.get()
        return bool(override is not None and override.lead) or LEAD_TURN.get()

    def _build_system_prompt(self) -> str:
        """Builds the system prompt with Jarvis-Agent-style workspace injection.

        Layer order (Jarvis-Agent priority map):
        1. SOUL.md           — Jarvis' own persona (who I am, tone rules)
        2. DODAIOS_PERSONA.md — voice persona incl. the hang-up contract
        3. USER.md           — about the user (name, communication style, values, …)
        4. people/           — list of known people in the user's environment
        5. CoreMemory        — legacy JSON facts (transitional, kept for back-compat)
        6. _CORE_CONTRACT    — honesty, routing and self-control facts
        7. REPLY LANGUAGE    — always last (machine contract)
        """
        private = _TURN_OVERRIDE.get()
        if private is not None and private.tool_context.get("tool_origin") == "society":
            # An agent's own notebooks are its profile source. Do not append
            # Jarvis' global USER.md, contacts, persona or ambient core memory.
            parts = [
                private.system_extra
                or "Your private agent context is unavailable; do not invent it.",
                _CORE_CONTRACT,
                getattr(self, "_evidence_directive", ""),
                # The briefing already carries the shared reply policy; sending
                # it twice costs ~2.3k characters on every society API turn.
                _WRITTEN_CHAT_RULES
                if CONVERSATIONAL_RESPONSE_STYLE in (private.system_extra or "")
                else _WRITTEN_CHAT_STYLE,
            ]
            identity = getattr(self, "_active_turn_identity", None)
            if identity:
                parts.append(_provider_identity_directive(identity[0], identity[1], "this agent"))
            parts.append(self._reply_language_directive())
            return "\n\n".join(part for part in parts if part)
        parts: list[str] = []

        # The assistant's identity, placed first so it frames everything: the
        # wake-word name (Dodaios is the app, never the assistant's
        # name) plus its character from SOUL.md, read through an mtime cache
        # so what the learning loop writes there reaches the next turn. The
        # realtime and GPT-Live instructions build the same block
        # (dodaios/brain/identity.py), so every surface answers "who are you"
        # the same way.
        name = resolve_assistant_name(getattr(self, "_config", None))
        parts.append(
            identity_block(
                getattr(self, "_config", None),
                path=getattr(getattr(self, "_soul", None), "path", None),
            )
        )

        # Persona block from DODAIOS_PERSONA.md incl. the hang-up contract.
        # The "effective" loader returns the user's custom system prompt when one
        # is set in Settings (data/custom_system_prompt.md), else the packaged
        # default. Read fresh each turn, so an edit/reset applies on the next turn
        # without a restart. Empty string when nothing is available — no crash.
        persona_block = load_effective_persona_prompt()
        if persona_block:
            parts.append(persona_block)

        # The lead conversation only (both runners): the operating doctrine, placed
        # right after the persona it refines. Constant text, so it stays in the
        # cached prefix; the ecosystem map follows the lead card below.
        lead_turn = self._is_lead_turn()
        if lead_turn:
            from dodaios.brain.lead_doctrine import LEAD_DOCTRINE

            parts.append(LEAD_DOCTRINE)

        # User's own standing-instructions file (CLAUDE.md equivalent),
        # named after the assistant (e.g. Assistant.md). Distinct from the persona: the
        # user writes personal preferences here, and the block is framed so they
        # refine behaviour but never override safety/confirmations. Read fresh each
        # turn -> an edit applies on the next turn, no restart. A read fault must
        # never break the prompt build.
        try:
            from dodaios.brain import agent_instructions as _agent_instructions

            prefs_block = _agent_instructions.render_for_prompt(getattr(self, "_config", None))
            if prefs_block:
                parts.append(prefs_block)
        except Exception:  # noqa: BLE001
            pass

        # How the person wants agents briefed ("I approve every PR myself",
        # "always with tests"), saved with agent-briefs-set. Read fresh each turn;
        # no block without wishes, so the cached prefix stays as it was.
        try:
            from dodaios.core.brief_wishes import prompt_block as _brief_wishes_block

            wishes_block = _brief_wishes_block()
            if wishes_block:
                parts.append(wishes_block)
        except Exception:  # noqa: BLE001 - a wishes fault never breaks a prompt build
            log.debug("agent brief wishes block unavailable", exc_info=True)

        if self._user_profile is not None:
            try:
                parts.append(self._user_profile.render_for_prompt())
            except Exception:  # noqa: BLE001
                pass

        # What Jarvis learned across earlier calls and chats (the background
        # review loop in dodaios/memory/learning). A cached snapshot that only
        # changes after a review writes, so it stays in the cached prefix.
        try:
            from dodaios.memory.learning.notebook import snapshot_block

            learned_block = snapshot_block()
            if learned_block:
                parts.append(learned_block)
        except Exception:  # noqa: BLE001 — a notebook fault never breaks a prompt build
            log.debug("learned notebook block unavailable", exc_info=True)

        if self._people is not None:
            try:
                people_block = self._people.render_for_prompt()
                if people_block:
                    parts.append(people_block)
            except Exception:  # noqa: BLE001
                pass

        # Chunk B (contacts): compact name-index of the user-curated contact
        # book (names + relationship only; e-mails/phones/address fetched on
        # demand via contact-lookup). None until Chunk A merges, "" when the
        # book is empty — either way no block is injected. Defensive try/except
        # so a store error never crashes the system-prompt build (AP-9-adjacent);
        # ``getattr`` guard tolerates __init__-bypassing tests (see _tools above).
        _contacts = getattr(self, "_contacts", None)
        if _contacts is not None:
            try:
                contacts_block = _contacts.render_for_prompt(max_chars=8_000)
                if contacts_block:
                    parts.append(contacts_block)
            except Exception:  # noqa: BLE001
                pass

        if self._core_memory is not None:
            # Mandatory: re-read BEFORE rendering. Otherwise the LLM only sees
            # facts that existed at init time — UI additions and remember-tool
            # writes from this process are in the file but not in the cache.
            try:
                self._core_memory.reload()
            except Exception:  # noqa: BLE001
                pass
            cm = self._core_memory.render_system_prompt_block()
            # A safety cap only (the 2500-character cost cap was retired): cut,
            # and mark the cut, only when the block really is longer.
            if len(cm) > _CORE_MEMORY_MAX_CHARS:
                cm = cm[:_CORE_MEMORY_MAX_CHARS] + "…"
            parts.append(cm)

        # Skills-Brain-Integration (Track B): surface the installed, active
        # user skills so the router-tier brain can actually choose ``run_skill``
        # for them. Without this block the ``run-skill`` tool is registered but
        # the brain never learns which skills exist, so it is never selected.
        # Static content (changes only on install/promote), so it stays in the
        # cached system prefix — mirrors the capability block below. Defensive try/except:
        # a renderer fault must never crash the system-prompt build. The lazy
        # import is intentional so a monkeypatched renderer resolves correctly.
        try:
            from dodaios.skills.prompt_injection import (
                render_available_skills_section,
            )
            from dodaios.skills.skill_context import try_get_skill_context

            _skill_ctx = try_get_skill_context()
            if _skill_ctx is not None:
                _skills_section = render_available_skills_section(_skill_ctx.registry)
                if _skills_section:
                    parts.append(_skills_section)
            elif not self._skills_omit_warned:
                # AD-S6: silently omitting the section was RC2 of "Jarvis
                # never calls a skill" — warn once per manager lifetime.
                self._skills_omit_warned = True
                log.warning(
                    "skills section omitted: skill context not initialized"
                )
        except Exception:  # noqa: BLE001
            if not self._skills_omit_warned:
                self._skills_omit_warned = True
                log.warning(
                    "skills section omitted: renderer failed", exc_info=True
                )

        # CLI first-class capabilities (design 2026-06-10, §5.3): list the
        # connected CLIs so the brain can pick them for matching requests.
        # Mirrors the skills section above. Rendered from the shared registry
        # published by the UI server; absent registry → section omitted.
        try:
            from dodaios.clis.prompt_section import render_connected_clis_section
            from dodaios.clis.shared import get_active_registry

            _cli_reg = get_active_registry()
            if _cli_reg is not None:
                _cli_section = render_connected_clis_section(_cli_reg)
                if _cli_section:
                    parts.append(_cli_section)
        except Exception:  # noqa: BLE001
            log.debug("connected-CLIs section omitted", exc_info=True)

        # The lead's team card (2026-09-03): the agent society's roster with
        # each agent's hands, plus the rule that "agent" means one of THEM.
        # Without it Jarvis answered "which agents do you have" from the
        # retired sub-agent system it was trained on while a freshly created
        # Gmail agent stood on the island. Rendered from the roster snapshot
        # (no IO), byte-stable between roster changes like the CLI section.
        # Skipped on a society agent's own turn: that turn carries its own
        # briefing (TurnOverride.system_extra), and a specialist must not be
        # told it is the lead.
        _turn_override = _TURN_OVERRIDE.get()
        if _turn_override is None or not _turn_override.system_extra:
            try:
                from dodaios.society.lead_card import lead_card_section, lead_live_tail

                _lead_card = lead_card_section(lead_name=name)
                if _lead_card:
                    parts.append(_lead_card)
                if not self._cache_optimized():
                    # Cache-optimized turns carry the live state in the tail.
                    _live = lead_live_tail()
                    if _live:
                        parts.append(_live)
            except Exception:  # noqa: BLE001 — the card is a convenience, never a turn breaker
                log.debug("lead card section omitted", exc_info=True)

        if lead_turn:
            # What exists in the app and how the lead reads it; generated from code,
            # byte-stable (dodaios/brain/lead_ecosystem.py).
            try:
                from dodaios.brain.lead_ecosystem import render_ecosystem_map

                parts.append(render_ecosystem_map())
            except Exception:  # noqa: BLE001 — the map is a convenience, never a turn breaker
                log.debug("ecosystem map omitted", exc_info=True)

        # Evidence gate directive (per-turn, AD-CLI8): forces a tool call
        # before any answer about an external-data domain. Empty on normal
        # turns; set by generate() when the gate returns require_tool.
        if self._evidence_directive:
            parts.append(self._evidence_directive)

        if self._system_prompt_extra:
            parts.append(self._system_prompt_extra)

        # Per-turn addendum (TurnOverride.system_extra): a surface's own
        # briefing for THIS turn only; empty on every other turn.
        if _turn_override is not None and _turn_override.system_extra:
            parts.append(_turn_override.system_extra)

        # The standing contract: honesty, research-versus-action routing and
        # self-control facts. The assistant's name is in the identity block.
        parts.append(_CORE_CONTRACT)

        # Initiative (2026-10-07): every other rule about the end of a reply
        # pulls towards "say nothing more", so without this the assistant never
        # brought a grounded idea. The level ([brain] proactivity) is static
        # between settings changes, so the rule stays in the cached prefix; the
        # dated plans it may draw on are per-turn and ride with the date below.
        parts.append(
            _proactivity.directive(_proactivity.current_level(getattr(self, "_config", None)))
        )
        if not self._cache_optimized():
            upcoming = self._upcoming_block()
            if upcoming:
                parts.append(upcoming)

        # Per-turn memory recall rides on the user message in cache-optimized
        # mode (keeps the cached system prefix stable), here otherwise.
        if self._memory_context_suffix and not self._cache_optimized():
            parts.append(self._memory_context_suffix)

        # Agentic IDE: while the user has the focused coding mode ON, this turn
        # is answered inside their open workspace — the folder, the codebase
        # profile, and what each named terminal (Mika, Nova, …) last printed.
        # Off / no session = empty string = no block, so this is inert for every
        # user who never opens the IDE. In cache-optimized mode the block rides
        # the per-turn user message instead (see _build_turn_context), because
        # it changes as the agents print and would otherwise break the cached
        # system prefix every turn.
        if not self._cache_optimized():
            agentic_block = self._agentic_focus_block()
            if agentic_block:
                parts.append(agentic_block)

        # Active-model self-awareness: tell THIS turn's actually-answering
        # provider/model who it is, so a "which model are you?" question gets an
        # honest answer instead of a guessed "Gemini" (forensic 2026-06-20: Grok
        # was live and answering yet claimed to be Gemini). Set per fallback-chain
        # attempt in generate(), where the real prov_name/model are known; absent
        # on non-turn prompt builds (compression / wiki-delta base) → no block.
        # Placed late for high recency; provider-stable across same-provider
        # turns, so it stays prompt-cache-friendly. On a fallback the block's
        # provider label changes between attempts within the turn, invalidating
        # the prefix cache for the second attempt — acceptable, since a fallback
        # is already a slow path (and matches the pre-existing per-turn mutable
        # flags). getattr: tolerates __new__-constructed test managers that bypass
        # __init__ (the attr is always set in __init__ for the production path).
        identity = getattr(self, "_active_turn_identity", None)
        if identity:
            parts.append(
                _provider_identity_directive(identity[0], identity[1], name)
            )

        # Written-turn style: typed chat answers are read on screen, so the
        # voice persona's spoken-output rules must not govern them. Without
        # this override the model drifts to emoji-heavy marketing copy.
        # Byte-stable per delivery mode, so the prompt cache stays warm.
        if _is_written_turn():
            parts.append(_WRITTEN_CHAT_STYLE)

        # Reply-language directive LAST — highest recency-salience, and
        # cli_prompt_context cuts it from "REPLY LANGUAGE" to the end.
        # Byte-stable across turns
        # (only changes on an explicit language switch), so it stays prompt-
        # cache-friendly.
        parts.append(self._reply_language_directive())

        return "\n\n".join(p for p in parts if p)

    def _cache_optimized(self) -> bool:
        """True when the cache-optimized prompt layout (Wave 2) is enabled."""
        perf = getattr(self._config, "performance", None)
        return bool(getattr(perf, "cache_optimized_prompt", False))

    def _is_pointer_intent(self, user_text: str) -> bool:
        """True when this is a deictic AI-Pointer turn ("worauf zeige ich?").

        Cheap regex gate, honoured only when ``[pointer].enabled``. Drives the
        per-turn grounding (scope images to the cursor crop, drop the full-screen
        screenshot tool) so the brain answers from the cursor, not a screen guess.
        """
        cfg = getattr(self._config, "pointer", None)
        if not bool(getattr(cfg, "enabled", True)):
            return False
        try:
            from dodaios.pointer.intent import is_pointing_intent  # noqa: PLC0415

            return is_pointing_intent(user_text)
        except Exception:  # noqa: BLE001 — gate must never block a turn
            return False

    def _start_pointer_task(self, user_text: str, is_smalltalk_turn: bool):
        """Launch the deictic AI-Pointer resolution as a background task (AP-9).

        Returns an ``asyncio.Task`` resolving to ``(prompt_block, crop_image)``, or
        ``None`` when the feature is disabled or the turn is smalltalk. The task
        does the regex deictic gate itself, so a non-pointing utterance completes
        instantly with ``("", None)`` and a headless host fast-skips before any
        worker-thread dispatch. Started before the vision-image await so it runs
        concurrently rather than serially on the hot path. See
        docs/plans/ai-pointer/DESIGN.md.
        """
        try:
            import asyncio  # noqa: PLC0415

            from dodaios.pointer.turn import resolve_turn_pointer

            cfg = getattr(self._config, "pointer", None)
            if not bool(getattr(cfg, "enabled", True)) or is_smalltalk_turn:
                return None
            return asyncio.create_task(
                resolve_turn_pointer(
                    user_text,
                    enabled=True,
                    timeout_s=float(getattr(cfg, "timeout_s", 0.12)),
                    crop_radius=int(getattr(cfg, "crop_radius", 64)),
                )
            )
        except Exception:  # noqa: BLE001 — never crash a turn on pointer setup
            log.debug("AI Pointer task launch skipped", exc_info=True)
            return None

    def _build_turn_context(self) -> str:
        """Per-turn dynamic context for the user message (cache-optimized mode).

        Date/time + wiki context. Empty in legacy mode
        (there these live in the system prompt instead). Riding on the user
        message keeps the cached system prefix byte-stable across turns, which
        is what actually lets the Gemini/Anthropic prompt cache hit.
        """
        if not self._cache_optimized():
            return ""
        from datetime import datetime

        # Deterministic English weekday. ``strftime('%A')`` renders the weekday
        # name in the process locale ("Freitag" on German Windows, "vendredi" on
        # French, a CJK string on a Chinese host), leaking a machine-locale,
        # often non-English token into the LLM context. Index a fixed English
        # tuple by ``weekday()`` (0=Monday) so the label reads the same English on
        # every OS. The date is ISO-8601 (unambiguous internationally, unlike a
        # dotted d.m.Y); wall-clock time stays local (``datetime.now``).
        _weekdays_en = (
            "Monday", "Tuesday", "Wednesday", "Thursday",
            "Friday", "Saturday", "Sunday",
        )
        _now = datetime.now()
        parts: list[str] = [
            # Date/time belongs per-turn, never in the cached prefix (also fixes
            # the missing BUG-005 date injection).
            f"[Current date and time: {_weekdays_en[_now.weekday()]}, "
            f"{_now.strftime('%Y-%m-%d %H:%M')}]"
        ]
        private = _TURN_OVERRIDE.get()
        if private is not None and private.tool_context.get("tool_origin") == "society":
            return "\n\n".join(parts)
        if self._memory_context_suffix:
            parts.append(self._memory_context_suffix)
        upcoming = self._upcoming_block()
        if upcoming:
            parts.append(upcoming)
        if private is None or not private.system_extra:
            from dodaios.society.lead_card import lead_live_tail

            parts.append(lead_live_tail())
        if self._is_lead_turn():
            # The repositories in play ([rsi] repo_index). Only inside a lead
            # turn: the prompt a CLI seat is handed is built outside one, and
            # that seat gets the index with its message instead.
            from dodaios.rsi.repo_cards import turn_context_note

            parts.append(turn_context_note())
        agentic_block = self._agentic_focus_block()
        if agentic_block:
            parts.append(agentic_block)
        return "\n\n".join(p for p in parts if p)

    @staticmethod
    async def _vault_recall(user_text: str) -> str:
        """Per-message memory recall, bounded to 150 ms so a busy disk never stalls a turn."""
        from dodaios.memory.vault.runtime import turn_block

        try:
            return await asyncio.wait_for(asyncio.to_thread(turn_block, user_text), timeout=0.15)
        except TimeoutError:
            log.info("memory vault: per-message recall skipped (over 150 ms)")
            return ""

    def _upcoming_block(self) -> str:
        """Dated plans from the notebooks for the next two weeks (initiative grounding).

        Pure cached read of the notebook files; ``""`` when initiative is off,
        nothing is dated, or anything fails, so it can never break a turn.
        """
        try:
            return _proactivity.upcoming_block(
                _proactivity.current_level(getattr(self, "_config", None))
            )
        except Exception:  # noqa: BLE001 — grounding is a convenience, never a turn breaker
            log.debug("initiative: upcoming block skipped", exc_info=True)
            return ""

    def _agentic_focus_block(self) -> str:
        """Workspace-awareness block while the Agentic IDE's focus mode is on.

        Pure in-memory read (the session's cached project profile + each
        terminal's ring buffer), so it stays off the latency budget (AP-9). Any failure degrades to no block — a coding-mode
        convenience must never be able to break a voice turn.
        """
        try:
            from dodaios.agentic_ide.context import focus_context_block

            return focus_context_block()
        except Exception:  # noqa: BLE001 - feature absent or mid-reload
            return ""
