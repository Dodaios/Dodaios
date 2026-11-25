"""Force-spawn decisions and recovery of leaked spawn/tool calls."""
from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from dodaios.brain.local_action_gate import is_open_app_intent, requires_external_integration
from dodaios.brain.manager import (
    _BUILD_VERB_RE,
    _CLI_TOOL_PREFIX,
    _CU_CONTEXT_MAX_MESSAGE_CHARS,
    _CU_CONTEXT_MAX_MESSAGES,
    _DOC_NOUN_RE,
    _NAMED_FILE_RE,
    _NON_SPAWN_SOURCE_LAYERS,
    _NOTHING_FOUND_PHRASE,
    _TURN_HISTORY_OVERRIDE,
    _WHISPER_FP_EXACT_ONLY,
    _WHISPER_FP_PREFIX_OK,
    _cli_failure_reason,
    _extract_leaked_spawn_call,
    _extract_leaked_tool_call,
    _is_conversational_coaching,
    _is_instructional_question,
    _is_opinion_advice_question,
    _is_spawn_decline,
    _is_spawn_feature_reference,
    _looks_like_pc_control,
    _render_recovered_tool_output,
    _safe_recovered_text,
    _trigger_names_vehicle,
    _turn_phrase_language,
    log,
)
from dodaios.brain.spawn_gate import effort_warrants_delegation
from dodaios.core.config import FORCE_SPAWN_MODE_BALANCED, FORCE_SPAWN_MODE_PERMISSIVE
from dodaios.core.protocols import Tool
from dodaios.voice.action_phrases import (
    action_phrase,
    extract_speakable_reason,
    localize_failure_reason,
)
from dodaios.voice.contextual_readback import render_readback

if TYPE_CHECKING:
    from dodaios.brain.manager_parts._host_state import BrainHostState as _HostBase
else:
    _HostBase = object


class _SpawnMixin(_HostBase):
    """Force-spawn decisions and recovery of leaked spawn/tool calls."""

    def _is_explicit_heavy_request(self, user_text: str) -> bool:
        """Return whether the user semantically requested a heavy worker."""
        text = (user_text or "").strip()
        if not text or _is_spawn_decline(text) or _is_spawn_feature_reference(text):
            return False
        trigger = self._get_force_spawn_pattern().search(text)
        if trigger is None:
            return False
        if _trigger_names_vehicle(trigger.group(0)):
            return True
        return not _looks_like_pc_control(text)

    def _should_force_spawn(
        self, user_text: str, *, source_layer: str | None = None
    ) -> bool:
        """Deterministic spawn guard for action requests.

        Wave-4 migration: previously ``_should_force_sub_jarvis`` with
        ``spawn_sub_jarvis`` tool lookup. The Sub-Jarvis tier was replaced by
        the Jarvis-Agent bridge — see docs/jarvis-agents-bridge.md §11.

        Order (the real evaluation sequence — keep this in sync with the body):
          0. Conversational source (drag-dropped mission recap) → False.
          1. Fatal preconditions, in order → False: empty text; no
             spawn_worker tool/executor; Whisper-FP sentinel; < 6 chars; no
             viable heavy-worker provider. These run FIRST — a spawn is then
             impossible or the transcript is noise.
          2. Explicit spawn DECLINE (``_is_spawn_decline``) → False. **MUST
             precede step 3** — the user negated the very trigger word the hoist
             matches; checking it after the hoist would force-spawn the OPPOSITE
             of "don't spawn a subagent" (live bug 2026-06-19, Turn 2).
          3. Explicit heavy-work trigger (``force_spawn_phrases``) → True. The
             user named the vehicle (AD-S9 / 2026-06-15 mandate); wins over
             every AMBIGUOUS-spawn disambiguation guard below.
          4. Disambiguation stand-downs → False: instructional question;
             opinion/advice question; conversational coaching
             (``_is_conversational_coaching``); pointer; navigation; smalltalk;
             open-app; installed skill; connected-CLI capability; PC control.
          5. The force-spawn mode decides what is left (``force_spawn_mode``):
             ``balanced`` (default) and ``permissive`` first run the EFFORT
             test — a multi-step artefact brief → True (mandate 2026-08-18).
             ``strict`` skips it and stays explicit-only, so everything the
             trigger in step 3 did not catch → False (mandate 2026-07-21).
             ``permissive`` additionally keeps the legacy heuristic: action
             verb / external marker → True.
          6. Otherwise → False.
        """
        # A drag-dropped mission recap is a CONVERSATION about a FINISHED job,
        # never new work — answer it inline regardless of what the quoted card
        # text contains (doom-loop fixed 2026-06-16; see
        # ``_NON_SPAWN_SOURCE_LAYERS``). Checked first so a leaked spawn trigger
        # in the verbatim title cannot reach the explicit-trigger hoist below.
        if source_layer is not None and source_layer in _NON_SPAWN_SOURCE_LAYERS:
            return False
        t = (user_text or "").strip()
        if not t:
            return False
        from dodaios.society.lead_card import society_owns_task

        if society_owns_task(t):
            return False
        if "spawn_worker" not in self._tools or self._tool_executor is None:
            return False
        # BUG-LIVE-04 (Recon-Agent 3, 2026-05-16): Whisper transcribes
        # background TV / music / silence into well-known sentinel strings
        # ("Untertitelung des ZDF für funk", "Vielen Dank fürs Zuschauen",
        # "Musik", "Applaus", "you", "Tschüss", "Bis zum nächsten Mal").
        # In permissive mode these matched action verbs and triggered
        # heavy worker spawns that hung 630s and produced "Mission
        # fehlgeschlagen" announcements — without the user having said
        # anything. Filter the well-known seeds before the verb match.
        lowered = t.lower().rstrip(".!? ").strip()
        # H2 (2026-05-17): exact-only bucket runs first because it's the
        # cheap O(1) set lookup; prefix bucket needs an O(N) sweep.
        # `log` is the module-level logger bound at L73 -- BUG-026 fix.
        if lowered in _WHISPER_FP_EXACT_ONLY:
            log.info(
                "force_spawn skipped: Whisper FP exact-only seed %r",
                lowered,
            )
            return False
        for _seed in _WHISPER_FP_PREFIX_OK:
            if lowered == _seed or lowered.startswith(_seed + " "):
                log.info(
                    "force_spawn skipped: Whisper FP prefix seed %r",
                    _seed,
                )
                return False
        # Minimum-length gate: anything shorter than 6 chars after
        # stripping is almost certainly a Whisper artefact, not an
        # intentional command.
        if len(lowered) < 6:
            return False
        # Force-spawn viability follows the WORKER, not the talker. The heavy
        # worker is selected from [brain.sub_jarvis].provider and runs regardless
        # of which provider talks to the user (dodaios/missions/init.py
        # _select_subagent_worker_kind). The original BUG-017 (2026-05-13) guard
        # gated on brain.primary, which silenced EVERY action request the moment
        # the user switched the talker to grok / openai / codex / openrouter —
        # re-introducing the "Das kann ich nicht ausführen" refusal through the
        # LLM fallback path (live bug class, forensic 2026-06-07). See
        # _heavy_worker_provider_viable.
        if not self._heavy_worker_provider_viable():
            return False
        # Explicit spawn DECLINE wins over EVERYTHING below, including the
        # negation-blind explicit-trigger hoist: when the user literally says
        # "don't spawn a subagent" / "talk to me directly", the trigger word
        # ("Subagent"/"spawn") they negated must NOT be read as a request. This
        # is checked BEFORE the hoist precisely because the hoist substring-
        # matches that same word and would force-spawn the opposite of the
        # user's intent. Live bug 2026-06-19 (voice session 18:41, Turn 2).
        if _is_spawn_decline(t):
            log.info("force-spawn skipped: explicit spawn decline — answer inline")
            return False
        # The user NAMING the auto-spawn feature (complaining about it, asking to
        # fix it) is talk ABOUT the feature, not a command. "Auto-Spawn" carries
        # the substring "spawn" that the negation-blind vehicle hoist below matches
        # at the hyphen boundary; without this stand-down, complaining about
        # auto-spawn force-spawns the very thing complained about. Checked BEFORE
        # the hoist, exactly like the decline guard. Live bug 2026-07-01 (voice
        # session 21:26:44): "Auto-Spawn, das müssen wir erstmal fixen" spawned a
        # full Opus mission whose heartbeats then spoke out of nowhere.
        if _is_spawn_feature_reference(t):
            log.info(
                "force-spawn skipped: auto-spawn feature named, not commanded — inline"
            )
            return False
        # An open Agentic-IDE terminal that is being ADDRESSED owns the turn.
        # Checked BEFORE the explicit-trigger hoist for the same reason the two
        # guards above are: the hoist matches a DEPTH marker, and "let Kai do a
        # deep dive" carries one while meaning the exact opposite of a background
        # mission. Live bug 2026-07-25 (voice session 15:47): that sentence
        # dispatched a Codex worker into a fresh worktree while the terminal
        # called Kai sat idle and the user saw nothing happen.
        #
        # ``owns_turn`` stands down when the user NAMES the spawn vehicle, so an
        # explicit "spawn an agent that helps Kai" still force-spawns — the
        # workspace claims ambiguous turns, never explicit delegation.
        try:
            from dodaios.agentic_ide.intent import owns_turn as _ide_owns_turn

            if _ide_owns_turn(t):
                log.info(
                    "force-spawn skipped: an open Agentic-IDE terminal is "
                    "addressed — the workspace handles this turn"
                )
                return False
        except Exception:  # noqa: BLE001 — optional surface, never breaks routing
            pass
        # User mandate (2026-06-15, "when I say subagent it MUST spawn"): an
        # EXPLICIT heavy-work trigger that NAMES the execution vehicle
        # ("subagent", "spawn", "openclaw", "delegate") is an UNAMBIGUOUS request
        # to dispatch a worker, so it is checked FIRST — ahead of every
        # disambiguation guard below (instructional / pointer / navigation /
        # smalltalk / open-app / skill). Those guards exist only to suppress
        # AMBIGUOUS, implicit spawns; they must never veto a request in which the
        # user literally named the vehicle. Before this hoist, an explicit
        # "Starte Jarvis-Agent" / "Spawne einen Subagenten und zeig …" was swallowed
        # by the open-app / navigation guard and never spawned ("sometimes saying
        # subagent doesn't spawn a subagent"). The fatal preconditions above (no
        # tool/executor, Whisper-FP seed, min length, worker not viable) still
        # win — they mean a spawn is impossible or the transcript is noise.
        #
        # A DEPTH marker ("deep dive", "gründlich", "umfassend", …) is NOT a
        # vehicle name — it describes thoroughness and OVERLAPS with computer-use
        # requests. It still force-spawns on its own ("Mach einen Deep Dive in
        # meine Google Cloud Kosten") BUT it must NOT override an explicit
        # on-screen / computer / browser request: "Mach einen Deep Dive mit
        # Computer Use in meinem Chrome Browser …" is a Computer-Use turn, not a
        # background mission. When the depth marker co-occurs with a pc-control
        # signal we hand the computer-use-vs-spawn decision to the LLM router (it
        # owns computer_use + the SYSTEM_PROMPT rule "Bildschirm/Browser bedienen
        # ist computer_use, kein spawn_worker") instead of letting the keyword
        # decide. This reuses the existing pc-control detector — no new
        # signal-word list, no widening of force_spawn_phrases.
        _trigger = self._get_force_spawn_pattern().search(t)
        if self._is_explicit_heavy_request(t):
            return True
        if _trigger is not None:
            log.info(
                "force-spawn deferred to LLM: depth trigger %r + computer-use "
                "request — router decides computer_use vs spawn",
                _trigger.group(0),
            )
            return False
        verb_re, marker_re, _smalltalk_re = self._get_routing_patterns()
        if _is_instructional_question(t):
            return False
        # Opinion / advice / recommendation / decision questions, and casual
        # question-openers, are CONVERSATION — the brain answers them inline,
        # never a heavy-worker spawn. Guards the verb-collision false positive
        # where an everyday word ("Frage" -> "frag", the filler "halt") trips
        # has_action_intent and pushes a pure chat turn into
        # _is_generic_subagent_work. Live bug 2026-06-19 (emigration turn). The
        # explicit heavy-work trigger hoisted above still wins, so "spawn a
        # subagent and tell me what you'd recommend" dispatches as asked.
        if _is_opinion_advice_question(t):
            log.info(
                "force-spawn skipped: opinion/advice/conversational question — inline"
            )
            return False
        # Conversational coaching ("hilf mir, intelligent zu fragen / klarer zu
        # denken") is talk, not work — the brain answers inline and asks the
        # user smart questions back. Guards the same verb-collision class as the
        # opinion guard above: the coaching OBJECT is itself an action verb
        # ("fragen" -> "frag"/"frage") that trips has_action_intent ->
        # _is_generic_subagent_work. Live bug 2026-06-19 (voice session 18:41,
        # Turn 1). The explicit heavy-work trigger hoisted above still wins.
        if _is_conversational_coaching(t):
            log.info(
                "force-spawn skipped: conversational coaching request — inline"
            )
            return False
        # AI Pointer: a deictic "what is this?" is a Q&A about the element under
        # the cursor — answered inline from the pushed pointer context, NEVER a
        # heavy-worker spawn. Guard here so a pointing verb like "zeige" cannot
        # fall through to the permissive verb heuristic or generic-subagent
        # detection. See docs/plans/ai-pointer/DESIGN.md.
        try:
            from dodaios.pointer.intent import is_pointing_intent  # noqa: PLC0415

            if is_pointing_intent(t):
                return False
        except Exception:  # noqa: BLE001 — pointer gate must never block routing
            pass
        # UI navigation ("zeig die Socials", "open settings") is a deterministic
        # dumb action handled by the navigation fast-path in generate() — never a
        # heavy worker spawn. Guard here too so a navigation verb cannot fall
        # through to the generic-subagent heuristic. See ADR-0011 "Navigate tool".
        try:
            from dodaios.brain.navigation_intent import (  # noqa: PLC0415
                match_navigation_intent,
            )

            if match_navigation_intent(t) is not None:
                return False
        except Exception:  # noqa: BLE001 — nav gate must never block routing
            pass
        # Greeting-aware smalltalk check (live bug 2026-06-07): a greeting prefix
        # ("Hallo, öffne ...") must NOT block the spawn of the real command that  # i18n-allow
        # follows it. _is_smalltalk strips the greeting and re-evaluates.
        if self._is_smalltalk(t):
            return False
        # Opening / launching an app is ALWAYS a computer-use task — a sub-agent
        # worker runs in an isolated git worktree and has no desktop. The
        # deterministic match_local_action path routes these to computer-use
        # first; this guard is defense-in-depth so a conjugated open verb
        # ("öffnest") can never fall through to a force-spawn (live bug
        # 2026-06-08: "Ich möchte, dass du mir Hermes Agent öffnest, also …").
        # BUT a genuine build-a-deliverable request ("build me a website",
        # "generate a landing page for the product launch") must NOT be vetoed by
        # an is_open_app_intent false positive (it trips on "launch" / English
        # phrasings) — building a file/site/app is a mission, not opening an app.
        # _research_wants_artifact requires a build VERB, so a real "open X"
        # command (no build verb) still stands down to computer-use here.
        if is_open_app_intent(t) and not self._research_wants_artifact(t):
            return False
        # NOTE: the EXPLICIT heavy-work trigger check (AD-S9, 2026-06-10) was
        # hoisted to the top of this method (above every disambiguation guard)
        # per the 2026-06-15 user mandate — see the comment there. It used to sit
        # here, between the open-app guard and the skill guard, which let the
        # open-app / navigation guards veto an explicit "Starte Jarvis-Agent" /
        # "Spawne … und zeig …" before the trigger was ever evaluated.
        # Skill-aware guard (AD-S3, 2026-06-09 rebuild): an utterance that
        # matches an installed, active skill is the skill's turn — never a
        # heavy-worker spawn. generate() sets _skill_turn_match early; the
        # direct probe is defense-in-depth for callers outside generate().
        if self._skill_turn_match is not None or self._match_skill_for_turn(t) is not None:
            log.info("force-spawn skipped: utterance matches an installed skill")
            return False
        # A request to CREATE a skill is authored inline by the create-skill
        # tool (one bounded LLM call, lands as a draft) — never a background
        # mission, even when the skill-creator builtin is disabled and no skill
        # captured the turn above.
        if getattr(self, "_skill_meta_turn", ""):
            log.info(
                "force-spawn skipped: skill %s request — the skill tools own it",
                self._skill_meta_turn,
            )
            return False
        # A connected CLI's capability already covers this intent → prefer its
        # cli_<name> tool, never a Computer-Use spawn (the CLI does it headless,
        # no browser login). Mirrors the skill guard above for the CLI surface
        # that capability_provider.sync_registry registers on connect. The
        # explicit heavy-work trigger (hoisted to the top of this method) still
        # wins, so the user can force a worker with "spawn"/"deep dive".
        try:
            from dodaios.core.capabilities import get_registry  # noqa: PLC0415

            _cap = get_registry().resolve_intent(t)
            if _cap is not None and _cap.source == "cli":
                log.info(
                    "force-spawn skipped: connected CLI %s covers the intent", _cap.id
                )
                return False
        except Exception:  # noqa: BLE001 — capability lookup must never break routing
            pass
        # A pc-control request (incl. an explicit "am Bildschirm / on screen")
        # is computer-use, not a sub-agent — stand down. BUT a build-a-deliverable
        # request that merely mentions the screen ("bau mir eine Website und zeig
        # sie am Bildschirm") must still spawn the mission, so the artifact build
        # wins over this stand-down (mirrors the open-app guard above).
        # Proxy for "the brain can drive the desktop directly": this used to
        # check ``dispatch_to_harness`` (removed from the router set 2026-06-28),
        # so it now checks the live desktop tool ``computer_use``. Without the
        # update the guard would never fire and a pure pc-control request could
        # wrongly force a sub-agent spawn.
        if (
            "computer_use" in self._tools
            and _looks_like_pc_control(t)
            and not self._research_wants_artifact(t)
        ):
            return False
        # User-Mandate 2026-05-14: the permissive router used to spawn on every
        # spawn_verb hit ("schreib", "mach", "zeig", "lies", ...), which fired
        # heavy workers for everyday utterances, so strict became the default:
        # spawn only when the user explicitly names a heavy-work trigger
        # ("Jarvis-Agent", "Sub-Agent", "spawn", "deep dive", "gründliche
        # Recherche", ...). Since 2026-08-18 the default is `balanced` — strict
        # plus the effort route below — and the legacy verb/marker heuristic
        # stays available via `brain.routing.force_spawn_mode = "permissive"`.
        mode = self.force_spawn_mode
        if mode in (FORCE_SPAWN_MODE_BALANCED, FORCE_SPAWN_MODE_PERMISSIVE):
            # The EFFORT route (maintainer mandate 2026-08-18: "the goal is that
            # he just DOES things without being told. Right now he doesn't even
            # do the things you DO tell him."). Explicit-only left Jarvis unable
            # to start work on its own judgement — "Bau mir eine Website mit
            # Flask und einer Startseite" reached this line and became talk.
            #
            # This is the retired build-a-deliverable gate coming back NARROWER,
            # not the retired gate coming back. That one fired on
            # ``_research_wants_artifact`` alone — a build verb plus an artefact
            # noun — so a bare "erstell ein Skript" dispatched a mission. The
            # effort test demands the same deliverable PLUS a request shape,
            # PLUS no cheap-scope word, PLUS the conversational stand-downs,
            # PLUS a substance signal and two scope signals in total. It is
            # deliberately reused from ``spawn_gate`` rather than restated here,
            # so the deterministic path and the LLM gate judge effort with ONE
            # test (the same reason ``addressed_pane_blocks_spawn`` delegates to
            # ``intent.owns_turn``).
            #
            # Every stand-down above still wins: this runs last, after the
            # smalltalk / Whisper-FP / instructional / opinion / coaching /
            # pointer / skill / capability / pc-control guards.
            if effort_warrants_delegation(t):
                log.info(
                    "force-spawn: %s mode — the turn is a multi-step artefact "
                    "brief, delegating without a delegation keyword: %r",
                    mode,
                    t[:80],
                )
                return True
        if mode != FORCE_SPAWN_MODE_PERMISSIVE:
            # Maintainer mandate 2026-07-21 (voice session 07:46): a background
            # agent starts ONLY on an explicit request — the user names the
            # vehicle or a delegation/depth trigger (``force_spawn_phrases``;
            # the AD-S9 hoist above already returned True for those). Every
            # IMPLICIT strict-mode spawn path is retired:
            #   - generic sub-agent work (``_is_generic_subagent_work``,
            #     2026-06-01): its ``has_action_intent`` verb catalogue collides
            #     with everyday nouns — the live trigger for this mandate was
            #     "…wann die beste Zeit ist, um … bei Hacker News und Post
            #     abzusetzen", where the noun "Post" matched the action verb
            #     "post" and dispatched a full mission for an info question;
            #   - heavy research with an artifact deliverable (Option A,
            #     2026-06-15) and the build-a-deliverable gate (2026-06-21):
            #     a build command without delegation wording no longer spawns
            #     silently — the router LLM answers inline or OFFERS a
            #     background agent (``dodaios.brain.spawn_gate``), and the
            #     user's confirming yes unlocks exactly one spawn.
            # The legacy verb/marker heuristic stays available via
            # ``force_spawn_mode = "permissive"``. In ``balanced`` the effort
            # route above already had its say, so reaching here means the turn
            # is neither an explicit request nor a multi-step artefact brief.
            log.info(
                "force-spawn skipped: %s mode needs an explicit delegation "
                "trigger — none in %r",
                mode,
                t[:80],
            )
            return False
        if verb_re.search(t):
            return True
        if marker_re.search(t):
            return True
        return False

    def _is_generic_subagent_work(self, t: str) -> bool:
        """True iff the utterance is generic, sub-agent-fulfillable work.

        Mirrors the capability gate's class exactly — an action the registry
        recognises that no capability resolves. A specific external integration
        the worker cannot satisfy (mail/calendar/Spotify/social/delivery) is
        excluded so it keeps the honest refusal. Defensive: an unavailable/empty
        registry returns False (mirrors the empty-registry guard in
        _check_unsupported_intent).

        RETIRED from the spawn decision 2026-07-21 (strict mode is
        explicit-only): ``has_action_intent``'s verb catalogue collides with
        everyday nouns ("Post" → verb "post"), which dispatched a full mission
        for a plain info question. Kept as a classifier for the refusal gate's
        mirror logic and tests.
        """
        if requires_external_integration(t):
            return False
        try:
            from dodaios.core.capabilities import get_registry  # type: ignore[import]

            reg = get_registry()
            if not getattr(reg, "all", lambda: ())():
                return False
            return bool(reg.has_action_intent(t) and reg.resolve_intent(t) is None)
        except Exception:  # noqa: BLE001 — registry error must not block spawn decision
            return False

    def _research_wants_artifact(self, t: str) -> bool:
        """True iff a (heavy-research) request asks for a BUILT ARTIFACT — a
        file / report / document — rather than a spoken/written ANSWER.

        Option A (2026-06-15): research whose deliverable is an ANSWER goes
        INLINE via the router's search_web tool (fast, no critic friction);
        research that builds a verifiable file OFFLOADS to a mission (the
        Worker->Critic pipeline grades artifacts via git diff). The
        discriminator: a named file / "into a file" instruction on its own, OR a
        build/produce verb paired with a document noun. A research/analysis verb
        (recherchier/analysier/compare/...) is NOT a build verb, so "research X
        and compare Y" (an answer) does not match — it stays inline. Pure regex
        (AP-11 safe, cross-platform); empty/blank text → False.
        """
        text = t or ""
        if not text.strip():
            return False
        if _NAMED_FILE_RE.search(text):
            return True
        return bool(_BUILD_VERB_RE.search(text) and _DOC_NOUN_RE.search(text))

    def _heavy_worker_provider_viable(self) -> bool:
        """True when a heavy-worker backend can run a force-spawn, decoupled from
        the talker provider (``brain.primary``).

        The worker is ``[brain.sub_jarvis].provider`` (dodaios/missions/init.py
        ``_select_subagent_worker_kind``) and is chosen independently of which
        provider talks to the user. A configured worker provider always maps to a
        real worker (claude-api -> ClaudeDirectWorker, codex -> CodexDirectWorker,
        else the Jarvis-Agent/default path), so it is viable for ANY talker — this is
        what lets the user switch ``brain.primary`` to gemini / openai / codex
        without silencing every action request (AP-6: never couple routing to a
        hardcoded talker provider).

        Only the LEGACY no-worker-configured path keeps the conservative
        ``brain.primary in {claude-api, gemini}`` check, because there the mission
        factory may fall back to the Gemini API worker, which 403s on an account
        without Gemini access (the original BUG-017, 2026-05-13)."""
        try:
            sub = getattr(self._config.brain, "worker", None)
            worker_provider = (getattr(sub, "provider", "") or "").strip().lower()
        except Exception:  # noqa: BLE001 — config hiccup must not block dispatch
            return True
        if worker_provider:
            return True
        try:
            primary = (self._config.brain.primary or "").strip().lower()
        except Exception:  # noqa: BLE001
            primary = ""
        return primary in ("claude-api", "gemini")

    async def _honest_failure_readback(
        self,
        result: Any,
        *,
        user_text: str,
        situation: str,
        generic_key: str,
        reason_key: str,
        lang: str | None = None,
    ) -> str:
        """Honest, localized, opaque-token-free spoken readback for a FAILURE.

        The single place every deterministic failure path (the DIRECT local
        action, the force-spawn, the leaked-spawn / leaked-tool recovery) turns a
        failed ``ToolResult`` into something speakable. It guarantees the user
        NEVER hears the raw ``ToolResult.error`` — which is routinely the opaque
        ``"exit N"`` token (``dispatch_to_harness`` → ``f"exit {code}"``) that was
        read out verbatim before (live forensic 2026-06-28: a harness failure was
        spoken as the bare "exit 1").

        It mirrors the Computer-Use path (:func:`cu_failure_readback`):

        1. Pull a *human* reason from the result (stderr/stdout/error) via
           :func:`extract_speakable_reason` — a bare ``exit N`` / numeric /
           diagnostic token yields ``None``.
        2. Route through the context-aware readback composer so the spoken line
           reacts to THIS situation (no stock phrasing, the maintainer's
           standing requirement) — handing it ONLY the clean reason as a fact,
           never the opaque token.
        3. Fall back to a localized canned phrase (de/en/es) — the reason
           variant when a clean reason exists, the generic one otherwise — so an
           en/es turn never gets a hardcoded German string and a failure is
           never silently dropped.
        """
        lang = lang or self._direct_ack_language(user_text)
        reason = extract_speakable_reason(
            getattr(result, "error", None), getattr(result, "output", None)
        )
        if reason:
            facts: dict[str, object] | None = {"reason": reason}
            instruction = f"{situation} The reason given was: {reason}"
            # The composer rephrases the English cause itself — but only while
            # it has a live model. The canned floor gets the cause already in
            # the turn's language, so a dead flash slot cannot produce a
            # half-translated sentence (live 2026-08-20: the Gemini ack slot
            # answered 404 and then 429, and every readback came out canned).
            spoken_reason = localize_failure_reason(reason, lang)
            canned = lambda: action_phrase(  # noqa: E731
                reason_key, lang, reason=spoken_reason
            )
        else:
            facts = None
            instruction = situation
            canned = lambda: action_phrase(generic_key, lang)  # noqa: E731
        return await render_readback(
            getattr(self, "_readback_composer", None),
            instruction=instruction,
            language=lang,
            canned=canned,
            facts=facts,
        )

    def _cu_goal_with_context(self, goal: str) -> str:
        """Append bounded recent conversation context to a Computer-Use goal.

        The deterministic local-action gate ships the raw current utterance as
        the mission goal. Without the turns that defined the task, a follow-up
        or correction turn hands the loop a vacuous goal and the verifier
        passes against it (live forensic 2026-07-15 07:59: after a failed
        Discord-announcement mission, "Ihr macht es doch mit Computer-Use."  # i18n-allow: quoted German speech input from the forensic
        became the whole goal — the loop opened Discord's Friends view and
        announced success). Delegated turns carry their history in
        ``_TURN_HISTORY_OVERRIDE``; classic turns fall back to the live
        ``self._history``. No history → the goal stays bare.
        """
        history = _TURN_HISTORY_OVERRIDE.get()
        if history is None:
            history = tuple(getattr(self, "_history", None) or ())
        lines: list[str] = []
        for message in history[-_CU_CONTEXT_MAX_MESSAGES:]:
            role = "User" if getattr(message, "role", "") == "user" else "Assistant"
            content = " ".join(str(getattr(message, "content", "") or "").split())
            if not content:
                continue
            if len(content) > _CU_CONTEXT_MAX_MESSAGE_CHARS:
                content = f"{content[:_CU_CONTEXT_MAX_MESSAGE_CHARS]} …"
            lines.append(f"{role}: {content}")
        if not lines:
            return goal
        context = "\n".join(lines)
        return (
            f"{goal}\n\n"
            "CONVERSATION CONTEXT (recent turns, oldest first — the goal above "
            "may refer back to these):\n"
            f"{context}"
        )

    def _spoken_reply_language(self, user_text: str) -> str:
        """Language for a fixed spoken phrase this manager renders itself.

        Resolved through the SAME call the router and every other spoken layer
        make (``resolve_output_language`` with the pin, this turn's detected
        language, the conversation stickiness and ``DEFAULT_LOCALE``), so a
        canned phrase can never speak a different language than the reply
        (AGENTS.md: the output language is decided once per turn).
        """
        # getattr: lightweight managers built without __init__ (fakes, early
        # boot paths) carry no turn state yet — that simply means "none known".
        return _turn_phrase_language(self, user_text or "")

    def _spawn_ack_language(self, user_text: str) -> str:
        """Resolve the language for the spoken spawn acknowledgement.

        A pinned reply language (``brain.reply_language``, any supported
        language) wins; otherwise detect from the user's words. The
        spawn-announcement composer speaks every supported reply language;
        undetectable text falls back to English, never German.
        """
        return self._spoken_reply_language(user_text)

    def _build_history_hints(
        self,
        *,
        max_turns: int = 20,
        max_chars_per_msg: int = 4_000,
    ) -> list[str]:
        """Formats the last N turn pairs as compact ``context_hints``.

        Conversation memory bridge to the Jarvis-Agent worker (bug fix 2026-04-30,
        wave-4 rebrand): the worker is architecturally stateless. Without this
        bridge it does not know the previous turns, even when the user
        explicitly refers to them ("erklaer mir das genauer",
        "was war der zweite Punkt?").

        One hint is emitted per user/assistant turn pair.
        Truncated to ``max_chars_per_msg`` to prevent long replies from
        bloating the worker context.
        """
        history = self._active_turn_history()
        if not history:
            return []
        recent = history[-(2 * max_turns):]
        hints: list[str] = []
        for i in range(0, len(recent) - 1, 2):
            u = recent[i]
            a = recent[i + 1]
            if u.role != "user" or a.role != "assistant":
                continue
            u_text = str(u.content)[:max_chars_per_msg]
            a_text = str(a.content)[:max_chars_per_msg]
            hints.append(f"Earlier turn — User: {u_text!r} | Assistant: {a_text!r}")
        if hints:
            hints.insert(0, "Conversation context (recent turns, newest last):")
        return hints

    async def _force_spawn_worker(
        self,
        user_text: str,
        *,
        trace_id: UUID | None = None,
        source_layer: str | None = None,
    ) -> str | None:
        """Starts ``spawn_worker`` deterministically, without LLM tool-choice.

        Wave-4 migration: previously ``_force_spawn_sub_jarvis`` with the
        ``spawn_sub_jarvis`` tool. The Sub-Jarvis tier was replaced by the
        Jarvis-Agent bridge — see docs/jarvis-agents-bridge.md §11.

        Returns:
            ``None`` when the heuristic does not trigger or the tool is absent.
            Otherwise the Jarvis-Agent output (the mission manager delivers a
            TTS-safe shortened summary via the voice listener path). The caller
            (``generate``) forwards the string as the final brain response.
        """
        if not self._should_force_spawn(user_text, source_layer=source_layer):
            return None

        tool = self._tools.get("spawn_worker")
        if tool is None or self._tool_executor is None:
            return None

        tid = trace_id or uuid4()
        context_hints: list[str] = [
            "Deterministically delegated: the user's turn matched an explicit "
            "delegation trigger (or the opt-in permissive verb heuristic).",
        ]
        # Bug fix 2026-04-30: pass conversation history to the worker so
        # follow-up questions ("erklaer das genauer") do not spawn into a
        # void. The stateless worker stays architecturally compliant — it
        # receives a snapshot of the last turns as a hint, not the full
        # manager state.
        context_hints.extend(self._build_history_hints())
        # Phase 5 (opt-in): include active-window hint so the Jarvis-Agent worker
        # knows which app the user is currently working in. Default OFF
        # (costs 200-400 ms latency, not worth it for every spawn). 250 ms
        # timeout in the module; failure mode 4 (pywinauto crash) is caught.
        try:
            from dodaios.brain.vision_context import get_active_window_hint

            vision_cfg = getattr(self._config, "vision", None)
            hint = await get_active_window_hint(config=vision_cfg)
        except Exception as exc:  # noqa: BLE001
            log.debug("Vision-Context-Probe failed (non-fatal): %s", exc)
            hint = None
        if hint:
            context_hints.append(hint)

        args = {
            "utterance": user_text,
            "context_hints": context_hints,
            # Empty action: the force-spawn heuristic has no LLM
            # interpretation. The spawn tool's announcement composer then
            # phrases the spoken ACK itself (flash-LLM with the delegation
            # persona, deterministic bilingual fallback) — see
            # dodaios/brain/ack_brain/spawn_announcement.py. Live regression
            # 2026-05-26 / redesign 2026-06-10: no canned template phrases.
            "action": "",
            "target": "",
            # Turn language for the spoken ACK: honour a reply-language pin,
            # otherwise detect from the user's words.
            "language": self._spawn_ack_language(user_text),
        }
        log.info("Force-spawn worker: %r", user_text[:160])
        # Stamp the turn's resolved output language so spawn_worker drives the
        # spoken ACK + mission language from the ONE authoritative resolver on
        # the force-spawn path too (the tool-use loop does this for brain
        # function-calls; this caller must do it itself or ctx.config is empty
        # and the language silently falls back — Runtime Output Language).
        out_lang = _turn_phrase_language(self, user_text)
        result = await self._tool_executor.execute(
            tool,
            args,
            user_utterance=user_text,
            config_snapshot={"output_language": out_lang},
            trace_id=tid,
        )
        if not result.success:
            return await self._honest_failure_readback(
                result,
                user_text=user_text,
                situation="The background helper the user asked for could not be started.",
                generic_key="spawn_failed_generic",
                reason_key="spawn_failed_reason",
                lang=out_lang,
            )
        return str(result.output or "")

    async def _recover_leaked_spawn(
        self,
        response_text: str,
        *,
        user_text: str,
        trace_id: UUID,
        allowed_tools: Mapping[str, Tool],
    ) -> str | None:
        """Execute a ``spawn_worker`` call a provider leaked as TEXT.

        Root cause (live repro 2026-05-24, mission "erstelle mir eine Datei
        test-opus.md"): Gemini intermittently emits the ``spawn_worker``
        tool_use block as the response content instead of invoking it. The raw
        JSON then reaches TTS as "Es trat ein Fehler auf" and the delegated
        Opus-4.7 sub-agent never runs — even though the brain *decided* to
        delegate. This is a provider function-calling leak, independent of the
        force-spawn heuristic (which stays strict).

        If ``response_text`` carries such a leaked call, run it through the same
        tool path ``_force_spawn_worker`` uses and return the spawn ACK;
        otherwise return ``None`` (caller keeps the original text).
        """
        leaked = _extract_leaked_spawn_call(response_text)
        if leaked is None:
            return None
        tool = allowed_tools.get("spawn_worker")
        if tool is None or self._tool_executor is None:
            return None

        utterance = str(leaked.get("utterance") or user_text).strip() or user_text
        context_hints = [
            "Recovered from a leaked tool_use block: the brain emitted the "
            "spawn_worker call as text instead of executing it (provider "
            "function-calling leak). Re-dispatched deterministically so the "
            "sub-agent runs and the user is not left with a spoken error.",
            *self._build_history_hints(),
        ]
        args = {
            "utterance": utterance,
            "context_hints": context_hints,
            # Prefer the brain-leaked interpretation; the spawn tool's
            # announcement composer validates the leaked spoken_ack (if any)
            # and otherwise phrases the ACK itself.
            "action": str(leaked.get("action") or ""),
            "target": str(leaked.get("target") or ""),
            "spoken_ack": str(leaked.get("spoken_ack") or ""),
            "language": (
                str(leaked.get("language") or "")
                or self._spawn_ack_language(user_text)
            ),
        }
        log.warning(
            "Recovered leaked spawn_worker tool-call from brain text "
            "(provider function-calling leak): %r", user_text[:160],
        )
        # Same authoritative-language stamping as the force-spawn path: without
        # a config snapshot ctx.config is empty and spawn_worker's language
        # falls back instead of honoring the resolver (Runtime Output Language).
        out_lang = _turn_phrase_language(self, user_text)
        result = await self._tool_executor.execute(
            tool, args, user_utterance=user_text,
            config_snapshot={"output_language": out_lang},
            trace_id=trace_id,
        )
        if not result.success:
            return await self._honest_failure_readback(
                result,
                user_text=user_text,
                situation="The background helper the user asked for could not be started.",
                generic_key="spawn_failed_generic",
                reason_key="spawn_failed_reason",
                lang=out_lang,
            )
        return _safe_recovered_text(result.output or "")

    async def _recover_leaked_tool(
        self,
        response_text: str,
        *,
        user_text: str,
        trace_id: UUID,
        allowed_tools: Mapping[str, Tool],
    ) -> str | None:
        """Execute ANY tool a provider leaked as TEXT (generalises spawn-only).

        Root cause (live repro 2026-05-25, voice "oeffne den Editor"): Gemini
        emits the ``tool_use`` block (``open_app`` / ``dispatch_to_harness`` /
        ``cli_*`` …) as response *text* instead of invoking it. The
        spawn-only :meth:`_recover_leaked_spawn` ignored every non-spawn tool,
        so the raw JSON reached TTS (scrubbed to silence) and the action never
        ran — while plain chit-chat (no tool) worked fine.

        ``spawn_worker`` keeps its specialised path (history hints, ACK).
        Every other leaked tool runs through the same ``ToolExecutor`` a
        structured tool_use would take. Returns a speakable result string, or
        ``None`` if there is no leak / the tool is not runnable.
        """
        parsed = _extract_leaked_tool_call(response_text)
        if parsed is None:
            return None
        name, inp = parsed
        if name == "spawn_worker":
            return await self._recover_leaked_spawn(
                response_text,
                user_text=user_text,
                trace_id=trace_id,
                allowed_tools=allowed_tools,
            )
        if self._tool_executor is None:
            return None
        tool = allowed_tools.get(name)
        if tool is None:
            return None
        log.warning(
            "Recovered leaked %s tool-call from brain text "
            "(provider function-calling leak): %r", name, user_text[:160],
        )
        result = await self._tool_executor.execute(
            tool, inp, user_utterance=user_text, trace_id=trace_id,
        )
        if not result.success:
            # A failed cli_<name> call carries the real cause in stderr; speak
            # it instead of the bare "exit N" error token (live repro
            # 2026-06-17, gcloud billing budgets list -> exit 1).
            if name.startswith(_CLI_TOOL_PREFIX):
                return _safe_recovered_text(
                    _cli_failure_reason(
                        result.output,
                        result.error,
                        language=self._spoken_reply_language(user_text),
                    )
                )
            return await self._honest_failure_readback(
                result,
                user_text=user_text,
                situation="An action the user asked for could not be carried out.",
                generic_key="action_failed_generic",
                reason_key="action_failed_reason",
            )
        # A read tool (search_web, wiki-recall, …) returns STRUCTURED data, not
        # a spoken sentence. Render it to speakable text — ``str(result.output)``
        # on a dict put a ``{``-prefixed repr on the wire that the streaming
        # guard dropped as a "leak", so a successful search dead-ended in the
        # canned action-failed phrase (live repro 2026-06-14 "Was hältst du von
        # exp.com?"). See :func:`_render_recovered_tool_output`.
        spoken = _render_recovered_tool_output(result.output)
        if spoken:
            return spoken
        # Tool ran but produced nothing speakable (e.g. an empty search). Give a
        # real spoken sentence, never silence and never the failure phrase.
        lang = self._spoken_reply_language(user_text)
        return _NOTHING_FOUND_PHRASE.get(lang, _NOTHING_FOUND_PHRASE["en"])

    def _cancel_all_background_tasks(self) -> int:
        """Cancels all running background Jarvis-Agent tasks.

        Matches via `task.get_name()` against the "jarvis-agent-" prefix (legacy
        naming convention, kept for byte-for-byte agreement with the
        `spawn_worker` tool's `create_task(...)` call).
        Returns the number of cancelled tasks.
        """
        cancelled = 0
        try:
            running = asyncio.all_tasks()
        except RuntimeError:
            # No running event loop (sync context) — nothing to cancel.
            return 0
        for task in running:
            name = task.get_name() or ""
            if name.startswith("jarvis-agent-") and not task.done():
                task.cancel()
                cancelled += 1
        log.info("Cancelled %d background worker task(s)", cancelled)
        return cancelled
