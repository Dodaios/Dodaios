"""Agentic IDE fast paths: spawn, prompt delivery, close and briefing."""
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from dodaios.brain.assistant_name import resolve_assistant_name
from dodaios.brain.manager import (
    _CLI_ANSWER_MAX_WORDS,
    _CLI_QUESTION_TTL_S,
    _NAVIGATION_ACK,
    _available_terminal_kinds,
    _fanout_reply_line,
    _join_names,
    _PendingCliChoice,
    _recent_agent,
    _terminals_spawned_line,
    _turn_phrase_language,
    log,
)
from dodaios.voice.action_phrases import action_phrase

if TYPE_CHECKING:
    from dodaios.brain.manager_parts._host_state import BrainHostState as _HostBase
else:
    _HostBase = object


class _AgenticIdeMixin(_HostBase):
    """Agentic IDE fast paths: spawn, prompt delivery, close and briefing."""

    async def _run_navigation_fast_path(
        self,
        user_text: str,
        *,
        trace_id: UUID | None = None,
    ) -> str | None:
        """Move the desktop UI to a section on a clear navigation command.

        Navigation is a deterministic "dumb" action (AD-OE3): a spoken/typed
        "zeig die Socials" / "open settings" switches the active sidebar section
        WITHOUT the LLM, and crucially before the capability gate — which would
        otherwise refuse it ('social' is an external-integration marker) — and
        before force-spawn. Executes the ``navigate`` tool (which publishes
        ``NavigateSidebar`` for the frontend) and returns a short spoken
        confirmation. Returns ``None`` when the utterance is not a navigation
        request, so the normal path runs. Pure regex match, no LLM (AP-11).
        """
        from dodaios.brain.navigation_intent import match_navigation_intent

        section = match_navigation_intent(user_text)
        if section is None:
            return None
        # User mandate (2026-06-15): an EXPLICIT heavy-work trigger ("subagent",
        # "spawn", "openclaw", …) outranks this deterministic "dumb" navigation
        # fast-path — exactly as it outranks the skill guard (AD-S9). A nav-tail
        # combo like "Spawne einen Subagenten UND zeig mir die Socials" names the
        # execution vehicle, so it must reach force-spawn rather than merely
        # switch the sidebar section. Stand down and let the normal path spawn.
        if self._is_explicit_heavy_request(user_text):
            log.info(
                "navigation fast-path stands down — explicit heavy-work trigger "
                "in the utterance wins (mission, not a sidebar switch)."
            )
            return None
        # An addressed terminal outranks a sidebar switch, for the same reason
        # the desktop gate stands down for one a few lines below in ``generate``:
        # whichever gate holds the MORE SPECIFIC evidence wins. Naming a running
        # pane and telling it to do something is unambiguous; a section word that
        # happens to appear in the same breath is not.
        #
        # Live bug 2026-07-29 17:04 (BUG-121): "Kannst du mal bitte Terminal T7
        # prompten, … wieso das Resuming Feature nur bei claude Code Sessions
        # funktioniert … oder bei Open Codes oder bei anderen Sessions" opened
        # the Sessions section and returned. T7 was never briefed, and the live
        # model narrated the briefing anyway. ``match_navigation_intent`` now
        # binds its ingredients so that sentence no longer matches at all; this
        # is the second layer, because a matcher fix alone leaves the class open
        # for the next section word that lands next to a genuine cue.
        # <!-- i18n-allow: quoted spoken transcript of the failing utterance -->
        if self._agentic_ide_owns_turn(user_text):
            log.info(
                "navigation fast-path stands down — this turn addresses a "
                "running Agentic-IDE terminal (more specific evidence)."
            )
            return None
        tool = self._tools.get("navigate")
        if tool is None or self._tool_executor is None:
            return None
        tid = trace_id or uuid4()
        try:
            await self._tool_executor.execute(
                tool,
                {"section": section},
                user_utterance=user_text,
                trace_id=tid,
            )
        except Exception:  # noqa: BLE001 — navigation must never crash the turn
            log.warning(
                "navigation fast-path failed for section %r", section, exc_info=True
            )
            return None
        label = section.replace("-", " ").title()
        lang = self._spoken_reply_language(user_text)
        return _NAVIGATION_ACK.get(lang, _NAVIGATION_ACK["en"]).format(label=label)

    def _agentic_ide_owns_turn(self, user_text: str) -> bool:
        """True when this turn belongs to the open coding workspace.

        Asked by the deterministic gates that would otherwise consume the turn
        first — today the desktop/Computer-Use gate. The answer comes from
        ``intent.owns_turn``, the one precedence rule the force-spawn guard and
        the spawn gate already share, so a fourth opinion cannot appear here.

        Cost is a regex sweep over the in-memory session, no IO and no LLM
        (AP-9 / AP-11), so it is safe to ask on every turn of the voice hot
        path. Any fault answers "no": the workspace is an optional surface and
        must never be able to divert a turn away from the path that would
        otherwise have served it.
        """
        try:
            from dodaios.agentic_ide.intent import owns_turn

            return owns_turn(user_text)
        except Exception:  # noqa: BLE001 - optional surface, never fatal
            return False

    async def _run_society_inventory_fast_path(
        self, user_text: str, *, trace_id: UUID | None = None,
    ) -> str | None:
        """Answer a plain roster question from the actual read-only tool.

        This happens before generic routing, acknowledgements and worker
        selection. Never let a missing runtime turn a roster read into work.
        """
        from dodaios.society.intent import is_inventory_question

        if not is_inventory_question(user_text):
            return None
        out_lang = _turn_phrase_language(self, user_text)
        unavailable = {
            "de": "Ich kann die Agentenliste gerade nicht abrufen.",  # i18n-allow
            "en": "I cannot retrieve the agent roster right now.",
            "es": "No puedo consultar la lista de agentes ahora.",
            "pt": "Não consigo consultar a lista de agentes agora.",
        }.get(out_lang, "I cannot retrieve the agent roster right now.")
        tool = self._tools.get("society_status")
        if tool is None or self._tool_executor is None:
            return unavailable
        try:
            result = await self._tool_executor.execute(
                tool, {}, user_utterance=user_text,
                config_snapshot={"output_language": out_lang},
                trace_id=trace_id or uuid4(),
            )
        except Exception:  # noqa: BLE001 - preserve a truthful answer on storage failure
            log.warning("society inventory lookup failed", exc_info=True)
            return unavailable
        return str(result.output or unavailable)

    async def _run_agentic_ide_fast_path(
        self,
        user_text: str,
        *,
        trace_id: UUID | None = None,
        consume_pending_voice_attachments: bool = False,
    ) -> str | None:
        """Deliver a spoken instruction to the addressed Agentic-IDE terminal.

        The Agentic IDE's promise is that talking to a named pane makes that pane
        work. Leaving that to the LLM's tool choice made it unreliable in exactly
        the situation it matters most: on 2026-07-25 (voice session 15:47) "let
        Kai do a deep dive" was swallowed by the force-spawn heuristic and became
        an invisible background mission, and even without that collision a router
        that is busy deciding between a dozen tools sometimes just answers in
        prose. So the delivery is deterministic here, ahead of force-spawn — the
        same shape as the navigation and local-action fast-paths.

        What is NOT deterministic is the prompt itself: the composer
        (``agentic_ide.prompt_composer``) rewrites the spoken sentence into a
        briefed task with ``@file`` references. That is one bounded provider call
        with a regex fallback, so the instruction is delivered either way.

        Several panes may be addressed in one breath ("Iris und Bruno beide in
        Deep Dive geben"). They are served CONCURRENTLY and reported
        individually — see ``agentic_ide.fanout``, which exists because doing
        this in a loop cannot fit in a voice turn and cannot report a partial
        delivery honestly.

        Returns ``None`` whenever this turn is not an addressed terminal, so the
        normal path runs untouched.
        """
        try:
            from dodaios.agentic_ide import clarify as ide_clarify
            from dodaios.agentic_ide import intent as ide_intent
        except Exception:  # noqa: BLE001 - optional surface
            return None

        try:
            from dodaios.agentic_ide.session import get_registry

            registry = get_registry()
            session = registry.session
            if session is None:
                return None
            candidates = [t.name for t in session.terminals]
            # An answer to a pending "did you mean Ellis?" is claimed before
            # anything else. It names no pane on its own ("ja") and carries no
            # instruction, so every detector below would read it as ordinary
            # conversation and the task the user already spoke would be lost a
            # second time — which is worse than the silent miss the question
            # replaced, because it also cost them a turn.
            #
            # The window classifies the answer under every supported language
            # itself, so no per-turn language has to be resolved before it.
            answered = ide_clarify.WINDOW.resolve_answer(user_text)
            recent = getattr(self, "_last_ide_spawn", None)
            if (
                ide_intent.references_recent_fleet(user_text)
                and recent is not None
                and recent[0] == session.id
                and time.monotonic() - recent[2] <= 300.0
            ):
                recent_names = [name for name in recent[1] if session.find(name)]
                if recent_names:
                    candidates = recent_names
            addressed = ide_intent.detect_all(
                user_text, names=candidates
            )
            if not addressed:
                current = session.contextual_terminal()
                visible = ide_intent.detect_visible(
                    user_text,
                    terminal=current.name if current is not None else None,
                    names=candidates,
                )
                if visible is not None:
                    addressed = [visible]
        except Exception:  # noqa: BLE001 - detection must never break a turn
            return None

        # Naming the spawn vehicle outranks the workspace: "spawn an agent that
        # helps Kai" is a genuine background-worker request even with a
        # workspace open. Asked through the shared rule rather than through
        # ``names_spawn_vehicle`` directly, because that stand-down has two
        # exceptions now (coding mode is on; the spawn words describe a PANE's
        # work, "Alex should spawn sub-agents"), and a second hand-written copy
        # of it here would strand exactly those turns: the spawn gate would
        # refuse the mission, this fast path would refuse to type, and the user
        # would get silence. Passed THIS path's roster — it may include a
        # just-closed fleet the global one no longer lists.
        if ide_intent.spawn_vehicle_outranks_workspace(user_text, names=candidates):
            return None

        out_lang = _turn_phrase_language(self, user_text)

        # A clarified pane is briefed with the ORIGINAL utterance — the sentence
        # that actually carried the work — not with the "yes" that confirmed it.
        if answered is not None:
            panes, original = answered
            # Every pane the answer confirmed, not the first one: "Alex und
            # Blaike, macht beide …" is ONE instruction for two agents, and a
            # single "yes" has to brief both of them. Answering it with one
            # pane is how the second agent of an addressed pair was lost (live
            # 2026-07-27 19:07).
            live = [name for name in panes if session.find(name) is not None]
            if live:
                log.info(
                    "Agentic IDE: clarified call-sign(s) resolved to %s",
                    ", ".join(live),
                )
                return await self._deliver_agentic_ide_prompt(
                    session=session,
                    names=live,
                    utterance=original,
                    instruction="",
                    language=out_lang,
                    consume_pending_voice_attachments=(
                        consume_pending_voice_attachments
                    ),
                )

        if not addressed:
            # No pane was named with certainty — but the turn may still have
            # MEANT one. A call-sign arrives through speech recognition, and the
            # live 2026-07-27 failure was exactly this: "Ellis" came back as
            # "Ilies", scored just under the acting threshold, and this path
            # returned None without a word. Nothing reached the pane, nothing
            # was said, and the live model — which never learns any of this —
            # filled the silence by claiming an agent was working.
            #
            # Asking costs the user one word and cannot type a stranger's
            # sentence into a coding agent, so uncertainty resolves to a
            # question. ``detect_clarification`` decides when there is one to
            # ask; it stands down for anything that is not addressing the
            # workspace.
            # "Du hast es gar nicht gepromptet." names no pane and carries no
            # instruction, so everything above returns nothing — which is how
            # the user ended up saying it twice while Jarvis apologised and
            # promised a delivery it never made (BUG-121). The sentence is only
            # meaningful against the turn before it, so that is where the work
            # comes from.
            # <!-- i18n-allow: quotes the spoken sentence that failed -->
            retry = await self._retry_undelivered_agentic_ide_prompt(
                user_text,
                session=session,
                candidates=candidates,
                language=out_lang,
                consume_pending_voice_attachments=(
                    consume_pending_voice_attachments
                ),
            )
            if retry is not None:
                return retry
            return self._ask_which_agentic_ide_terminal(
                user_text, candidates=candidates, language=out_lang
            )
        found = addressed[0]

        # A question about a pane is read-only: answer it from what that pane
        # printed, and let the normal brain path phrase the answer with the
        # focus-context block (which already carries the transcript tail).
        if found.kind == ide_intent.KIND_REPORT:
            return None

        names = [item.terminal for item in addressed]

        # A turn addresses a FLEET, and speech recognition may have carried
        # only part of it across. "Alex und Blaike, macht beide einen Deep
        # Dive" resolves Alex and mangles Blake, and this path used to brief
        # Alex and say nothing at all about the rest — so the user heard one
        # agent confirmed and believed two were working (live 2026-07-27
        # 19:07). The pane that WAS understood still gets its brief; the one
        # that was not becomes a question appended to the same answer.
        leftover = self._agentic_ide_leftover_question(
            user_text, candidates=candidates, claimed=names, language=out_lang
        )

        # NOTHING is spoken between here and the delivery verdict below, and that
        # silence is the feature. A bridge line lived here for a few hours on
        # 2026-07-27 to fill the prompt writer's 10-21 s, and it produced the
        # worst possible failure the same day: announcements are not read out
        # verbatim on a live call — ``deliver_announcement`` hands the text to
        # the realtime model to RE-RENDER in its own words — and the model
        # rendered the in-progress line as a finished action ("I have forwarded
        # the bug to Alex") while nothing had reached the pane yet. On a turn
        # whose delivery then failed, that sentence was the only thing the
        # maintainer ever heard. Careful wording cannot fix this: any statement
        # made before the work is done is a claim a downstream model is free to
        # re-tense. So the only sentence this path emits is the per-pane verdict
        # at the end, derived from what was actually typed into which terminal.
        # Slow and true beats fast and wrong.

        # Two agents told to "split the work between you" must get DIFFERENT
        # briefs — the same sentence twice is two agents racing on one file.
        # Only an explicit request plans a split: it costs a provider call, and
        # "both of you run the tests" is one order for two agents. A division
        # the user enumerated THEMSELVES ("one fixes the macOS bug, one the
        # Linux bug") is exactly as explicit and takes the same path — without
        # it, both panes received the whole enumeration and raced on the first
        # slice (maintainer report 2026-08-12).
        assignments: dict[str, str] | None = None
        if len(names) > 1 and (
            ide_intent.wants_split(user_text)
            or ide_intent.distributes_tasks(found.instruction or user_text)
        ):
            try:
                from dodaios.agentic_ide import work_split as ide_split

                plan = await ide_split.split(
                    found.instruction or user_text,
                    session=session,
                    count=len(names),
                    conversation=self._agentic_ide_conversation(user_text),
                )
                assignments = {
                    name: item.task
                    for name, item in zip(names, plan.assignments, strict=False)
                }
                log.info(
                    "Agentic IDE fan-out: work split %s across %d panes (%s)",
                    plan.split_by, len(assignments),
                    ", ".join(a.area for a in plan.assignments),
                )
            except Exception:  # noqa: BLE001 - an unplanned fleet still works
                log.warning("Agentic IDE work split failed", exc_info=True)
                assignments = None

        verdict = await self._deliver_agentic_ide_prompt(
            session=session,
            names=names,
            utterance=user_text,
            instruction=found.instruction,
            language=out_lang,
            assignments=assignments,
            consume_pending_voice_attachments=consume_pending_voice_attachments,
        )
        if leftover is not None:
            # Armed only now: a question about the rest of the fleet is worth
            # asking once the panes that WERE understood are actually briefed,
            # and a delivery that failed on the way there should not leave a
            # question standing about work nobody received.
            need, question = leftover
            ide_clarify.WINDOW.arm(need, question=question)
            log.info(
                "Agentic IDE: briefed %s, asking about %s",
                ", ".join(names),
                " / ".join(need.offered),
            )
            return f"{verdict} {question}" if verdict else question
        return verdict

    def _agentic_ide_conversation(self, utterance: str) -> tuple[tuple[str, str], ...]:
        """The turns an addressed-pane instruction came out of, for the composer.

        A spoken order to a pane points back into the conversation constantly —
        "above all points two and three", "do that for the wake path too" — and
        the coding agent receives the composed brief and nothing else. Live
        2026-07-29 that gap produced a brief instructing two agents to
        "incorporate points 2 and 3 from the current context": a pointer to
        something they can never open, so the substance of the order reached
        neither of them.

        Read through ``_active_turn_history`` rather than ``self._history``
        directly, because a realtime call keeps its own bounded context and
        hands it to the delegated turn — on that path the shared buffer is
        empty and this is the ONLY place the previous turns exist.
        """
        from dodaios.agentic_ide import conversation as ide_conversation

        try:
            return ide_conversation.from_messages(
                self._active_turn_history(), exclude=utterance
            )
        except Exception:  # noqa: BLE001 - context is a bonus, never the turn
            log.debug("Agentic IDE: conversation context unavailable", exc_info=True)
            return ()

    def _agentic_ide_delivery_signals(
        self, session: Any
    ) -> tuple[Callable[[Any], None] | None, Callable[[Any], Awaitable[None]] | None]:
        """Put a SPOKEN delivery on screen: the writing beats, then the arrival.

        Writing a brief is 10-30 s of quality-tier model work, and nothing on
        screen said so when the order arrived by voice. Both signals existed
        already — the composer's ``STAGE_*`` beats and ``AgenticIdePromptSent``
        — but only the typed prompt bar's REST route published them, so a spoken
        "T5, look at the transcript" left the whole app looking untouched until
        the agent itself echoed the text half a minute later. Reported
        2026-08-13: the bar showed no thinking state, "so you think it did not
        work" — and then the pane was prompted 20 s later.

        Deliberately the SAME events, not a spoken line: the clients already
        render them (the pane's live status line, the delivery toast), and a
        sentence spoken before the work is done is a claim a downstream model
        re-tenses into "I have prompted T5" — the failure this whole path is
        built to avoid.

        Returns ``(None, None)`` without a bus. A publish that fails costs the
        line, never the brief.
        """
        bus = self._bus
        if bus is None:
            return None, None
        from dodaios.agentic_ide.session import prompt_sent_event
        from dodaios.core.events import AgenticIdeComposeProgress

        session_id = str(getattr(session, "id", "") or "")

        def _beat(notice: Any) -> None:
            from dodaios.agentic_ide.prompt_composer import print_notice

            # Keep the stdout/log line a headless install watches, exactly as
            # the REST route does — the socket beat is an addition to it.
            print_notice(
                notice, speaker=resolve_assistant_name(getattr(self, "_config", None))
            )
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:  # pragma: no cover - no loop, no clients
                return
            task = loop.create_task(
                bus.publish(
                    AgenticIdeComposeProgress(
                        session_id=session_id,
                        terminal=str(getattr(notice, "terminal", "") or ""),
                        stage=str(getattr(notice, "stage", "") or ""),
                        message=str(getattr(notice, "message", "") or ""),
                        kind=str(getattr(notice, "kind", "") or ""),
                        source_layer="brain.agentic_ide_prompt",
                    )
                )
            )
            # Fire-and-forget: a beat that cannot be delivered must never cost
            # the brief, nor a warning about an unobserved task at teardown.
            task.add_done_callback(lambda done: done.cancelled() or done.exception())

        async def _delivered(term: Any) -> None:
            await bus.publish(
                prompt_sent_event(
                    session, term, source_layer="brain.agentic_ide_prompt"
                )
            )

        return _beat, _delivered

    async def _deliver_agentic_ide_prompt(
        self,
        *,
        session: Any,
        names: list[str],
        utterance: str,
        instruction: str,
        language: str,
        assignments: dict[str, str] | None = None,
        consume_pending_voice_attachments: bool = False,
    ) -> str | None:
        """Compose and type one instruction into the addressed panes.

        Shared by the addressed-terminal path and by the answer to a "did you
        mean …?" question, so a clarified pane is briefed through exactly the
        same composer and reported by exactly the same verdict line. A second
        delivery site would be free to drift into announcing something it did
        not do, which is the failure class this whole area exists to prevent.

        No brain is pinned for the composer on purpose. An earlier version
        handed it this turn's FAST router model to save 4-5 s, but that
        optimised the wrong axis: the prompt is what the coding agent then
        works from for minutes, and the maintainer's decision on 2026-07-25
        was explicitly for the better prompt over the quicker handoff. The
        composer resolves a quality-tier model itself and degrades to its
        deterministic prompt when none is reachable.
        """
        from dodaios.agentic_ide import fanout as ide_fanout

        # Returning None here would hand the turn to the model with nothing to
        # go on, and a model asked about a pane it cannot see answers from the
        # user's own question — which is precisely how "I have let Alex know"
        # was spoken over a terminal that had received nothing (2026-07-27).
        # A delivery that did not happen is a fact worth saying out loud, so
        # every exit below carries one; ``deliver`` itself never raises for a
        # single pane, so reaching these means the whole fan-out fell over.
        on_progress, on_delivered = self._agentic_ide_delivery_signals(session)
        try:
            result = await ide_fanout.deliver(
                session=session,
                terminals=names,
                utterance=utterance,
                instruction=instruction,
                assignments=assignments,
                conversation=self._agentic_ide_conversation(utterance),
                include_pending_attachments=consume_pending_voice_attachments,
                on_progress=on_progress,
                on_delivered=on_delivered,
                # Hanging up ends the order (maintainer decision 2026-08-13).
                cancel_on_hangup=True,
            )
        except Exception:  # noqa: BLE001 - never crash the turn over a pane
            log.warning("Agentic IDE fast-path failed", exc_info=True)
            return action_phrase(
                "ide_prompt_sent_nobody", language, failed=_join_names(names, language)
            )

        if not result.deliveries:
            log.warning(
                "Agentic IDE fast-path: fan-out returned no verdicts for %s",
                ", ".join(names),
            )
            return action_phrase(
                "ide_prompt_sent_nobody", language, failed=_join_names(names, language)
            )
        return _fanout_reply_line(result, language)

    #: How long a "you never prompted it" complaint may reach back. Bounded to
    #: the running conversation: past this, "do it again" is a fresh request and
    #: replaying a stale sentence into a coding agent would be its own bug.
    _IDE_RETRY_WINDOW_S = 300.0

    async def _retry_undelivered_agentic_ide_prompt(
        self,
        user_text: str,
        *,
        session: Any,
        candidates: list[str],
        language: str,
        consume_pending_voice_attachments: bool = False,
    ) -> str | None:
        """Deliver the PREVIOUS turn's briefing when the user says it never went.

        Live failure 2026-07-29 17:04 (BUG-121). A briefing for T7 was consumed
        by the navigation gate; Jarvis said it had briefed T7 anyway. The user
        corrected it twice — "Du hast es gar nicht gepromptet", then "Das war
        noch nicht geprompted" — and both corrections produced nothing at all,
        because they name no pane and carry no instruction, so every detector
        returned None and the live model was left to answer alone. It apologised
        and promised a delivery it had no way to make. The third attempt only
        worked because the model happened to call the action tool by itself.
        <!-- i18n-allow: quotes the spoken sentences that failed -->

        A complaint is not proof, so the pane's OWN receipt decides. If
        ``last_prompt_at`` says the briefing did arrive, this answers with the
        clock time instead of typing the sentence a second time — an agent
        briefed twice is two agents' worth of work on one task, and the honest
        answer is what tells the user "it did not happen" from "I did not see it
        happen". Only a pane with no receipt in the window is briefed.
        """
        try:
            from dodaios.agentic_ide import intent as ide_intent
        except Exception:  # noqa: BLE001 - optional surface
            return None
        if not ide_intent.reports_undelivered(user_text):
            return None
        previous = self._previous_user_turn_text(use_history=True)
        if not previous:
            return None
        try:
            addressed = ide_intent.detect_all(previous, names=candidates)
        except Exception:  # noqa: BLE001 - detection must never break a turn
            return None
        wanted = [
            item.terminal
            for item in addressed
            if item.kind == ide_intent.KIND_PROMPT
        ]
        if not wanted:
            return None

        now = time.time()
        delivered: list[tuple[str, float]] = []
        missing: list[str] = []
        for name in wanted:
            term = session.find(name)
            if term is None:
                continue
            at = getattr(term, "last_prompt_at", None)
            if at is not None and now - float(at) <= self._IDE_RETRY_WINDOW_S:
                delivered.append((name, float(at)))
            else:
                missing.append(name)

        if not missing:
            if not delivered:
                return None
            name, at = delivered[0]
            log.info(
                "Agentic IDE: %s reported undelivered, but %s has a receipt "
                "from %s — answering with the time instead of re-sending",
                user_text[:60],
                name,
                time.strftime("%H:%M:%S", time.localtime(at)),
            )
            return action_phrase(
                "ide_prompt_already_delivered",
                language,
                name=name,
                time=time.strftime("%H:%M", time.localtime(at)),
            )

        log.info(
            "Agentic IDE: retrying an undelivered briefing for %s from the "
            "previous turn",
            ", ".join(missing),
        )
        return await self._deliver_agentic_ide_prompt(
            session=session,
            names=missing,
            utterance=previous,
            instruction="",
            language=language,
            consume_pending_voice_attachments=consume_pending_voice_attachments,
        )

    def _ask_which_agentic_ide_terminal(
        self,
        user_text: str,
        *,
        candidates: list[str],
        language: str,
    ) -> str | None:
        """Ask which pane was meant, or ``None`` when there is nothing to ask.

        The question is armed as a one-shot window: the user's next turn ("ja",
        "Ellis") delivers the ORIGINAL instruction to the confirmed pane, so
        clarifying costs one word rather than a repeated sentence.
        """
        try:
            from dodaios.agentic_ide import clarify as ide_clarify
        except Exception:  # noqa: BLE001 - optional surface
            return None
        try:
            need = ide_clarify.detect_clarification(user_text, names=candidates)
        except Exception:  # noqa: BLE001 - a detector fault stays silent
            return None
        if need is None:
            return None

        question = self._agentic_ide_clarify_question(need, language)
        ide_clarify.WINDOW.arm(need, question=question)
        log.info(
            "Agentic IDE: heard %r, asking whether %s was meant",
            " / ".join(item.spoken for item in need.uncertain),
            " / ".join(need.offered),
        )
        return question

    @staticmethod
    def _agentic_ide_clarify_question(
        need: Any, language: str, *, also: bool = False
    ) -> str:
        """The spoken question for one uncertain call-sign, or for a list.

        Three shapes, because they mean three different things and a user has
        to be able to answer each with one word: one pane offered ("did you
        mean Blake?"), one word that could be several panes ("Max OR
        Maggie?"), and several garbled names in one list ("Alex AND Blake?").
        Joining the last one with "or" would ask the user to pick between two
        agents they had just addressed together.
        """
        spoken = need.spoken
        if len(need.uncertain) > 1:
            heard = [item.spoken for item in need.uncertain]
            spoken = action_phrase("join_and", language).join(
                (", ".join(heard[:-1]), heard[-1])
            )

        offered = need.offered
        if len(need.uncertain) == 1 and len(offered) == 1:
            if also:
                return action_phrase(
                    "ide_terminal_clarify_also",
                    language,
                    spoken=spoken,
                    names=offered[0],
                )
            return action_phrase(
                "ide_terminal_clarify_one", language, spoken=spoken, name=offered[0]
            )
        # Alternatives for ONE word are offered with "or"; a list of separate
        # names is joined with "and", because both were meant.
        joiner = "join_and" if len(need.uncertain) > 1 else "join_or"
        joined = action_phrase(joiner, language).join(
            (", ".join(offered[:-1]), offered[-1])
        )
        return action_phrase(
            "ide_terminal_clarify_also" if also else "ide_terminal_clarify_many",
            language,
            spoken=spoken,
            names=joined,
        )

    def _agentic_ide_leftover_question(
        self,
        user_text: str,
        *,
        candidates: list[str],
        claimed: list[str],
        language: str,
    ) -> tuple[Any, str] | None:
        """A question about the addressees this turn named but did not resolve.

        Returns ``(need, question)`` when the utterance addressed panes BEYOND
        the ones about to be briefed, else ``None``. The caller arms it after
        the delivery, so the user hears which agents really got the work before
        being asked about the rest.

        Nothing is asked when every uncertain word points at a pane that is
        already being briefed — that is the same addressee reached twice, not a
        second one.
        """
        try:
            from dodaios.agentic_ide import clarify as ide_clarify
            from dodaios.agentic_ide import intent as ide_intent

            need = ide_clarify.detect_clarification(user_text, names=candidates)
        except Exception:  # noqa: BLE001 - a detector fault stays silent
            return None

        already = {name.casefold() for name in claimed}
        if need is not None and not all(
            all(name.casefold() in already for name in item.candidates)
            for item in need.uncertain
        ):
            return need, self._agentic_ide_clarify_question(need, language, also=True)

        # No word came close enough to name a pane — and a call-sign can be
        # mangled past every threshold there is ("Dave" for a pool that holds
        # none). What survives that is the COUNT the user stated out loud:
        # "both of you" says two agents were addressed however badly the names
        # travelled. Briefing one and saying nothing is the failure this
        # catches — the user hears one name confirmed and believes two are
        # working (live 2026-07-27 19:07).
        try:
            if not ide_intent.expects_several(user_text):
                return None
        except Exception:  # noqa: BLE001 - a detector fault stays silent
            return None
        if len(claimed) > 1:
            return None
        rest = tuple(name for name in candidates if name.casefold() not in already)
        if not rest:
            return None
        # Armed over every OTHER pane, so the next word ("Blake") delivers the
        # original task. A bare "yes" decides nothing here and must not: there
        # is no candidate to confirm, only panes to choose between.
        unresolved = ide_clarify.ClarificationNeeded(
            uncertain=(ide_clarify.UncertainName(spoken="", candidates=rest),),
            utterance=user_text,
            certain=tuple(claimed),
        )
        return unresolved, action_phrase(
            "ide_terminal_who_else", language, names=", ".join(claimed)
        )

    async def _brief_spawned_agentic_ide_fleet(
        self,
        session: Any,
        names: list[str],
        user_text: str,
    ) -> None:
        """Brief newly mounted Codex panes once their real input lines exist."""
        from dodaios.agentic_ide import fanout as ide_fanout
        from dodaios.agentic_ide import intent as ide_intent
        from dodaios.agentic_ide.fleet_actions import wait_for_prompt_ready

        instruction = ide_intent.spawn_instruction(user_text)
        # Read once, up front: this runs as a background task that outlives the
        # turn, and the history it reads keeps moving underneath it.
        spoken_before = self._agentic_ide_conversation(user_text)
        assignments: dict[str, str] | None = None

        # A brief BY KIND names its own panes ("prompt the claudes to fix the
        # tests, the codex should update the docs"), so it outranks both the
        # shared brief and a planned split: the user has already divided the
        # work, and every pane of a kind the brief does not name stays blank —
        # that silence is what was asked for. Without this, all panes of a
        # mixed fleet received the ENTIRE enumeration as their own task
        # (maintainer report 2026-08-12).
        try:
            group_tasks = ide_intent.spawn_group_tasks(user_text)
        except Exception:  # noqa: BLE001 - the shared brief is still usable
            log.warning("Agentic IDE spawned-fleet group parse failed", exc_info=True)
            group_tasks = {}
        if group_tasks:
            per_pane: dict[str, str] = {}
            for name in names:
                term = session.find(name)
                kind = str(getattr(term, "agent", "") or "") if term is not None else ""
                task = group_tasks.get(kind)
                if task:
                    per_pane[name] = task
            if per_pane:
                assignments = per_pane
                names = [name for name in names if name in per_pane]
                log.info(
                    "Agentic IDE spawned-fleet briefing: per-kind tasks for %s",
                    ", ".join(names),
                )

        # ``distributes_tasks`` reads the extracted TASK, never the utterance:
        # the fleet description counts panes with the same words ("one Codex").
        if assignments is None and len(names) > 1 and (
            ide_intent.wants_split(user_text)
            or ide_intent.distributes_tasks(instruction)
        ):
            try:
                from dodaios.agentic_ide import work_split as ide_split

                plan = await ide_split.split(
                    instruction,
                    session=session,
                    count=len(names),
                    conversation=spoken_before,
                )
                assignments = {
                    name: item.task
                    for name, item in zip(names, plan.assignments, strict=False)
                }
            except Exception:  # noqa: BLE001 - the common brief is still usable
                log.warning("Agentic IDE spawned-fleet split failed", exc_info=True)

        ready = await wait_for_prompt_ready(session, names)
        missing = [name for name in names if name not in ready]
        if missing:
            log.warning(
                "Agentic IDE spawned-fleet briefing: panes never became ready: %s",
                ", ".join(missing),
            )
        if not ready:
            return

        result = await ide_fanout.deliver(
            session=session,
            terminals=ready,
            utterance=user_text,
            instruction=instruction,
            assignments=assignments,
            conversation=spoken_before,
        )
        log.info(
            "Agentic IDE spawned-fleet briefing: %d of %d prompts delivered",
            len(result.delivered),
            len(names),
        )

    async def _run_agentic_ide_close_fast_path(
        self,
        user_text: str,
        *,
        trace_id: UUID | None = None,
    ) -> str | None:
        """Close an explicitly requested terminal fleet without model routing."""
        try:
            from dodaios.agentic_ide import intent as ide_intent
            from dodaios.agentic_ide.fleet_actions import (
                close_agent_terminals,
                terminals_closed_event,
            )
            from dodaios.agentic_ide.session import get_registry

            request = ide_intent.detect_close_fleet(user_text)
        except Exception:  # noqa: BLE001 - optional surface
            return None
        if request is None:
            return None

        out_lang = _turn_phrase_language(self, user_text)
        registry = get_registry()
        session = registry.session
        if session is None:
            return action_phrase("ide_terminals_none_to_close", out_lang)
        closed = await close_agent_terminals(registry, request.agent)
        if not closed:
            return action_phrase("ide_terminals_none_to_close", out_lang)
        if self._bus is not None:
            try:
                await self._bus.publish(
                    terminals_closed_event(
                        session,
                        closed,
                        source_layer="brain.agentic_ide_close",
                    )
                )
            except Exception:  # noqa: BLE001 - the terminals are already closed
                log.warning("Agentic IDE close: UI notification failed", exc_info=True)
        names = [term.name for term in closed]
        return action_phrase(
            "ide_terminals_closed",
            out_lang,
            count=len(names),
            names=_join_names(names, out_lang),
        )

    async def _run_agentic_ide_spawn_fast_path(
        self,
        user_text: str,
        *,
        trace_id: UUID | None = None,
    ) -> str | None:
        """Open N more coding terminals when the user asks for them out loud.

        "Spawn five more Claude Code terminals" is a workspace request, but it
        opens with the word the force-spawn heuristic reads as "dispatch a
        background agent" — so left to the router it becomes an invisible mission
        worker instead of five panes. ``intent.detect_spawn`` claims the turn
        (that precedence lives in ``intent.owns_turn``, which both routing gates
        already consult) and this path carries it out.

        Three things happen here that the REST route cannot do on its own:

        1. **A workspace is opened when none is running.** The folder is the most
           recently used one, and it is NAMED in the reply — it is an assumption,
           and the user has to be able to hear a wrong one.
        2. **The open UI is told.** Panes added from outside the workspace view
           are invisible to it (it fetches its state once, on mount), so the new
           pane list is published on the bus.
        3. **The view is brought forward.** This is also what STARTS the agents:
           ``add_terminals`` creates the registry entries, and each agent's
           pseudo-terminal spawns when its pane mounts.

        Returns ``None`` on every turn that is not a terminal-spawn request, so
        the normal path runs untouched.
        """
        try:
            from dodaios.agentic_ide import intent as ide_intent
            from dodaios.agentic_ide.session import (
                SessionError,
                get_registry,
                terminals_added_event,
            )
        except Exception:  # noqa: BLE001 - optional surface
            return None

        # A question asked last turn is answered BEFORE anything is parsed
        # again: "Codex" on its own is not a spawn request and would otherwise
        # fall through to the ordinary brain, leaving the user's answer — and
        # the fleet it was about — to evaporate.
        answered = self._answer_pending_cli_question(user_text)

        try:
            request = answered or ide_intent.detect_spawn(user_text)
        except Exception:  # noqa: BLE001 - detection must never break a turn
            return None
        if request is None:
            return None

        out_lang = _turn_phrase_language(self, user_text)
        from dodaios.voice.action_phrases import action_phrase

        # The name did not clearly reach one CLI. ASK — this is the maintainer's
        # directive of 2026-07-28 and the same rule the pane-name question
        # follows: whatever is unsure becomes a question rather than an action,
        # because the question costs one word and the guess costs an agent
        # working on the wrong plan until somebody notices.
        if request.uncertain_cli:
            unclear = request.uncertain_cli[0]
            self._pending_cli_choice = _PendingCliChoice(
                groups=tuple(request.groups),
                utterance=request.utterance,
                candidates=unclear.candidates,
                asked_at=time.monotonic(),
            )
            if len(unclear.candidates) == 1:
                return action_phrase(
                    "ide_terminal_kind_unclear_one",
                    out_lang,
                    spoken=unclear.spoken,
                    first=unclear.candidates[0],
                )
            return action_phrase(
                "ide_terminal_kind_unclear",
                out_lang,
                spoken=unclear.spoken,
                first=unclear.candidates[0],
                second=unclear.candidates[1],
            )

        registry = get_registry()
        folder_label: str | None = None
        #: Why a group of the fleet could not be opened, one sentence each.
        #: Spoken back with the panes that DID open — a fleet that came up short
        #: without saying so is the failure this whole path is shaped around.
        refused: list[str] = []
        # A CLI this app has no terminal kind for. It is answered even when it
        # is the ONLY thing that was asked for, which is why it is collected
        # before anything is opened.
        for unknown in request.unsupported:
            refused.append(
                action_phrase(
                    "ide_terminal_kind_unknown",
                    out_lang,
                    name=unknown,
                    available=_available_terminal_kinds(),
                )
            )

        if not request.groups:
            # Nothing openable was asked for — the only CLI named is one this
            # workspace does not have. Answering is the whole job here; opening
            # a substitute pane would grant a request that was just refused.
            return " ".join(refused) if refused else None

        try:
            if registry.session is None:
                # No workspace open: take the most recent one. Reading the
                # recents file is IO, so it goes to a thread — this path runs
                # inside a voice turn.
                from dodaios.agentic_ide import recents

                entries = await asyncio.to_thread(recents.load)
                if not entries:
                    return action_phrase("ide_terminals_nowhere", out_lang)
                recent = entries[0]
                fallback_agent = request.agent or _recent_agent(recent)
                # One spec per pane, group by group: "5 Codex and 3 Claude Code
                # terminals" is a mixed fleet, and collapsing it to one agent
                # opened five of the first kind and silently dropped the rest
                # (maintainer report 2026-07-26).
                specs = [
                    {"agent": group.agent or fallback_agent}
                    for group in request.groups
                    for _ in range(group.count)
                ]
                session = await registry.start(recent.path, specs)
                created = list(session.terminals)
                folder_label = recent.name
            else:
                created = []
                for group in request.groups:
                    # One group's failure is that GROUP's failure.
                    #
                    # A CLI that is not installed, or one whose binary vanished,
                    # raises here — and letting that leave the loop threw away
                    # every group behind it, including the ones that would have
                    # opened perfectly well. "Two Claude, one Codex and one GLM"
                    # then produced nothing but a sentence about GLM. Each group
                    # is attempted on its own and what could not be opened is
                    # named at the end, so a mixed fleet degrades pane by pane
                    # instead of all at once.
                    try:
                        opened, _capped = await registry.add_terminals(
                            group.count, agent=group.agent
                        )
                    except SessionError as exc:
                        log.info(
                            "Agentic IDE spawn: %s group refused: %s",
                            group.agent or "inherited",
                            exc,
                        )
                        refused.append(str(exc))
                        continue
                    created.extend(opened)
                    if _capped:
                        # A pane failed to open mid-fleet. Stop rather than
                        # asking for the next group and hitting the same
                        # failure — the readback already reports the shortfall.
                        break
        except SessionError as exc:
            # A missing CLI, an unreadable folder: every one of these already
            # carries a user-facing English sentence, and speaking it is more
            # useful than a generic failure.
            log.info("Agentic IDE spawn fast-path refused: %s", exc)
            return str(exc)
        except Exception:  # noqa: BLE001 - never crash the turn over a pane
            log.warning("Agentic IDE spawn fast-path failed", exc_info=True)
            return None

        if not created:
            # Nothing opened. If a group said WHY, that sentence is the answer;
            # otherwise the pane failed to start and the log says why.
            if refused:
                return " ".join(refused)
            return action_phrase("ide_terminals_open_failed", out_lang)

        session = registry.session
        if session is not None and self._bus is not None:
            try:
                await self._bus.publish(
                    terminals_added_event(
                        session, created, source_layer="brain.agentic_ide_spawn"
                    )
                )
                # Bring the workspace forward so the panes are SEEN appearing —
                # and so their agents boot, which only happens once a pane
                # mounts. A no-op when the view is already active.
                from dodaios.core.events import NavigateSidebar

                await self._bus.publish(
                    NavigateSidebar(
                        section="agentic-ide",
                        source_layer="brain.agentic_ide_spawn",
                        trace_id=trace_id or uuid4(),
                    )
                )
            except Exception:  # noqa: BLE001 - the panes exist either way
                log.warning("Agentic IDE spawn: UI notification failed", exc_info=True)

        names = [t.name for t in created]
        if session is not None:
            self._last_ide_spawn = (session.id, tuple(names), time.monotonic())

        briefing_queued = bool(
            session is not None and ide_intent.spawn_includes_task(user_text)
        )
        if briefing_queued and session is not None:
            tasks = getattr(self, "_ide_background_tasks", None)
            if tasks is None:
                tasks = set()
                self._ide_background_tasks = tasks
            task = asyncio.create_task(
                self._brief_spawned_agentic_ide_fleet(session, names, user_text),
                name="agentic-ide-spawned-fleet-briefing",
            )
            tasks.add(task)

            def _briefing_done(done: asyncio.Task[Any]) -> None:
                tasks.discard(done)
                if done.cancelled():
                    return
                try:
                    done.result()
                except Exception:  # noqa: BLE001 - background failure is logged
                    log.warning(
                        "Agentic IDE spawned-fleet briefing failed",
                        exc_info=True,
                    )

            task.add_done_callback(_briefing_done)
        log.info(
            "Agentic IDE spawn fast-path: opened %d pane(s) %s%s",
            len(names),
            names,
            f" in {folder_label}" if folder_label else "",
        )
        line = _terminals_spawned_line(
            names, requested=request.count, folder=folder_label, lang=out_lang
        )
        # A partial fleet says so in the same breath. The panes that opened are
        # already named; without this the ones that did not simply were not
        # mentioned, and a user who asked for four and got three had to count.
        if refused:
            line = f"{line} {' '.join(refused)}"
        if briefing_queued:
            line = f"{line} {action_phrase('ide_terminals_briefing_queued', out_lang)}"
        return line

    def _answer_pending_cli_question(self, user_text: str) -> Any | None:
        """The held fleet with its CLI filled in, or ``None``.

        Consumes the question either way. A question that has been answered,
        declined, or simply talked past must never open panes on a later turn —
        the same rule the pane-name window follows, and for the same reason: a
        forgotten "yes" that opens four terminals ten minutes later is worse
        than never having asked.

        Three shapes count as an answer, in falling directness: naming a CLI
        ("Codex", "Claude Code"), agreeing when only one was offered ("yes"),
        and naming its position ("the first one"). Anything longer than a few
        words is the user moving on.
        """
        pending = getattr(self, "_pending_cli_choice", None)
        if pending is None:
            return None
        text = (user_text or "").strip()
        if not text:
            return None
        if time.monotonic() - pending.asked_at > _CLI_QUESTION_TTL_S:
            self._pending_cli_choice = None
            return None
        if len(text.split()) > _CLI_ANSWER_MAX_WORDS:
            # Not an answer. The question is spent rather than left armed: the
            # user has moved on, and a stale question would answer a sentence
            # they never meant as one.
            self._pending_cli_choice = None
            return None

        from dodaios.agentic_ide import intent as ide_intent

        chosen: str | None = None
        # A CLI named outright wins, wherever in the short answer it sits.
        for size in (3, 2, 1):
            words = text.replace(",", " ").split()
            for start in range(len(words) - size + 1):
                agent = ide_intent.canonical_agent(" ".join(words[start : start + size]))
                if agent is not None:
                    chosen = agent
                    break
            if chosen is not None:
                break
        if chosen is None and len(pending.candidates) == 1:
            # "Yes" answers a question that offered exactly one name. With two
            # on the table it answers nothing, so it is not accepted there.
            from dodaios.agentic_ide.clarify import classify_short_answer

            if classify_short_answer(text) == "confirm":
                chosen = ide_intent.canonical_agent(pending.candidates[0])
        self._pending_cli_choice = None
        if chosen is None:
            return None

        from dodaios.agentic_ide.intent import SpawnGroup, SpawnTerminalsRequest

        groups = tuple(
            SpawnGroup(count=g.count, agent=g.agent or chosen) for g in pending.groups
        )
        if not groups:
            groups = (SpawnGroup(count=1, agent=chosen),)
        log.info(
            "Agentic IDE: the unclear CLI was answered with %s — opening %d pane(s)",
            chosen,
            sum(g.count for g in groups),
        )
        return SpawnTerminalsRequest(
            count=sum(g.count for g in groups),
            agent=groups[0].agent,
            # The ORIGINAL request, so a brief that rode along with it still
            # reaches the panes it was written for.
            utterance=pending.utterance,
            groups=groups,
        )
