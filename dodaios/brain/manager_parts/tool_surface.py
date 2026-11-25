"""Per-turn tool hiding, shortlisting and plugin relevance."""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Any, cast

from dodaios.brain import manager as _m
from dodaios.brain.local_action_gate import is_open_app_intent
from dodaios.brain.manager import (
    _ACTION_REQUEST_RE,
    _AGENTIC_IDE_WORKSPACE_TOOL_NAMES,
    _ARTIFACT_TOOL_NAME,
    _DETERMINISTIC_WRITE_TOOL_NAMES,
    _EXPLICIT_SKILL_REQUEST_RE,
    _INHERITABLE_ACTION_TOOL_NAMES,
    _SCREEN_TURN_HIDDEN_TOOL_NAMES,
    _SMALLTALK_HIDDEN_TOOL_NAMES,
    _SPAWN_TOOL_NAMES,
    _is_plain_knowledge_question,
    _looks_like_pc_control,
    log,
)
from dodaios.brain.tool_shortlist import (
    CORE_PRIORITY,
    DEFAULT_DIRECT,
    FIND_TOOLS_NAME,
    LEAD_DIRECT,
    ROLE_BASE,
    FindToolsTool,
    order_direct,
    plan_surface,
    tool_tokens,
)
from dodaios.core.protocols import BrainMessage, Tool

if TYPE_CHECKING:
    from dodaios.brain.manager_parts._host_state import BrainHostState as _HostBase
else:
    _HostBase = object


class _ToolSurfaceMixin(_HostBase):
    """Per-turn tool hiding, shortlisting and plugin relevance."""

    def _smalltalk_tool_override(self) -> dict[str, Tool]:
        """Tool set visible on a smalltalk turn: everything but the spawn vehicles.

        The 2026-05-01 incident this gate exists for was ONE tool class. The
        user said "es geht ab", the allowlist did not match, the LLM had the
        full surface and hallucinated a Jarvis-Agent spawn — Jarvis then claimed
        to have started tests it never started. Hiding ``spawn_worker`` /
        ``multi_spawn`` removes exactly that, and an unwanted background agent
        is the one tool whose wrong call is expensive and surprising.

        Hiding EVERYTHING else was the bug on the other side (2026-08-17
        review): smalltalk here is a substring allowlist, so a real request
        that merely reads as chit-chat arrived at the model with no action tool
        at all and could only be talked about. A tool the model declines to call
        is free; a tool it cannot see is the failure users report. The genuinely
        conversational turns still lose ``computer_use`` and the write/record
        tools further down the chain — see
        ``_hide_action_tools_on_signalless_turn``.

        A tool the deterministic layer mandated this turn is never hidden
        ("was steht heute an" can classify as smalltalk — AD-CLI8), and on a
        skill-matched turn (AD-S3) ``run-skill`` stays visible so a
        greeting-style trigger ("guten Morgen" → morning-routine) still fires.
        """
        hidden = _SMALLTALK_HIDDEN_TOOL_NAMES
        keep = {self._evidence_required_tool} if self._evidence_required_tool else set()
        if self._skill_turn_match is not None:
            keep.add("run-skill")
        return {
            n: t for n, t in self._tools.items()
            if n not in hidden or n in keep
        }

    def _image_turn_tool_override(self) -> dict[str, Tool]:
        """Tool surface for a turn that carries a CAPTURED SCREEN image.

        Historically hard ``{}`` — the reasoning being that pixels answer the
        turn and that emptying the surface is what keeps Screen Context and
        Computer-Use from both running for one utterance (docs/screen-context.md
        §3.1a, maintainer mandate 2026-08-02). The first exception was a WRITE
        mandate (code-review finding 2026-08-08): "erstell einen Ordner hier auf
        dem Desktop" matches the screen-intent phrase "hier auf dem", the
        explicit screen-context path attaches a screenshot, and a zeroed surface
        blinded the very run_shell call the local-outcome mandate requires.

        2026-08-17: the hide is now a narrow deny-list, because the boundary it
        was standing in for is enforced where it actually belongs. A turn can
        carry a screen image and still ask for an action — the image may come
        from an earlier utterance, from an explicit attach, or from a mixed
        request — and an emptied surface left the model describing a picture
        with no way to do the thing that was asked. ``computer_use`` therefore
        stays: every call runs through
        ``cu_gate.llm_computer_use_allowed`` first, which refuses a look request
        even inside a live desktop episode, so the two paths still cannot both
        run for one utterance. That gate reads the USER's utterance, never the
        model's reasoning, so untrusted on-screen text cannot unlock it either.

        What stays hidden is what injected screen text could otherwise start
        unattended: the spawn vehicles and the deterministic record writes
        (``_SCREEN_TURN_HIDDEN_TOOL_NAMES``) — minus any tool the deterministic
        layer mandated this turn.
        """
        keep = self._evidence_required_tool or ""
        return {
            n: t
            for n, t in self._tools.items()
            if (n not in _SCREEN_TURN_HIDDEN_TOOL_NAMES or n == keep)
            # MCP tools are namespaced ``server/tool``. Their JSON-Schema
            # unions brick Gemini (live 2026-08-31: Linear
            # ``issue_fields.value.type = [string, number, boolean]``) and
            # they bloat a look-at-screen prompt for every other provider.
            # A mandated tool still survives.
            and ("/" not in n or n == keep)
        }

    def _gate_screen_tool(
        self,
        tools: dict[str, Tool],
        *,
        user_text: str,
        has_image: bool,
        pointing_turn: bool = False,
    ) -> dict[str, Tool]:
        """Drop the on-demand ``screenshot`` tool on a turn that is not about the screen.

        The validation the screen-narration bug needed (live 2026-06-14): a
        small-talk / knowledge / cut-off fragment with no screen reference
        ("Kannst du mir sagen, was genau...") must not be able to invoke the
        screenshot function and then narrate the screen. Confirm the utterance
        is actually screen-related BEFORE offering the tool.

        The tool stays available when an image is already attached, on a pointer
        turn (which is by definition about the screen), or when the utterance
        carries a visual-reference marker — the same ``should_attach_screenshot``
        signal that gates passive image attach, so the marker-bearing screen
        questions of 2026-05-31 ("lies mir vor was oben links steht") keep it.
        Tradeoff: a genuinely screen-related question that matches no marker
        loses the auto-screenshot fallback; the prompt then steers the brain to
        say it cannot see the screen or ask, rather than fabricate one.
        """
        if not isinstance(tools, dict) or "screenshot" not in tools:
            return tools
        if pointing_turn or has_image:
            return tools
        from dodaios.brain.vision_gate import should_attach_screenshot

        if should_attach_screenshot(user_text):
            return tools
        return {n: t for n, t in tools.items() if n != "screenshot"}

    @staticmethod
    def _hide_screenshot_for_blind_brain(
        tools: dict[str, Tool],
        brain: Any,
        *,
        prov_name: str = "",
        model: str | None = "",
    ) -> dict[str, Tool]:
        """Drop the ``screenshot`` tool when the answering brain has no vision.

        A blind model that calls the tool is a guaranteed dead end: the
        capture succeeds, its own protocol layer drops the image ("Provider
        without vision support"), and the model honestly tells the user the
        picture came back unusable (live 2026-08-06 20:52, grok-4.5 tool
        loop). Gated on the runtime capability, never the provider name
        (AP-21); the chain-level vision skip only covers images attached
        BEFORE the turn, not ones a mid-loop tool call produces.
        """
        if not isinstance(tools, dict) or "screenshot" not in tools:
            return tools
        if getattr(brain, "supports_vision", False) is True:
            return tools
        log.info(
            "Hiding the screenshot tool from %s(%s): the model cannot "
            "inspect images, so a capture could only dead-end.",
            prov_name,
            model,
        )
        return {n: t for n, t in tools.items() if n != "screenshot"}

    def _shortlist_tools(
        self,
        tools: dict[str, Tool],
        brain: Any,
        *,
        system_prompt: str,
        history: Sequence[BrainMessage] | None,
        own_tools: Iterable[str] = (),
        direct_tools: frozenset[str] | None = None,
    ) -> tuple[dict[str, Tool], frozenset[str]]:
        """Decide which of the turn's tools the model is SHOWN.

        Returns ``(tools, deferred names)``. Every tool stays in the dict and
        stays callable; the deferred ones are not put in front of the model
        and are reached through ``find_tools``
        (``dodaios/brain/tool_shortlist.py``). With nothing deferred the dict comes back
        untouched.

        A brain-seat turn defers BY DEFAULT (``[brain] defer_tools``, on): only the
        frozen core (``DEFAULT_DIRECT``) is shown and every connected-server,
        plugin and rarer tool waits behind ``find_tools``, whatever the window.
        That is for selection quality and a stable prompt prefix; nothing becomes
        unreachable. A small-window model and a role-limited caller keep the
        rules below.

        Three reasons to defer, each on its own evidence:

        * **The window.** Live 2026-08-27: a local 32k model, 221 tools, a
          plain "Hallo" went out as 67,852 tokens and the server refused it.
          The first answer dropped what did not fit, largest first — which
          removed the richly described tools (a save tool with a real schema)
          before a parameterless list tool, and a dropped tool was gone for
          the turn. Now the everyday tools are shown first and the rest is
          deferred, not lost.
        * **A small model.** A window of ``_SMALL_WINDOW_TOKENS`` or less is
          a small model, and a small model picks badly from a long list even
          when the list fits: it is shown ``_SMALL_MODEL_DIRECT_TOOLS`` at
          most. Gated on the declared window, never a provider name (AP-21).
        * **The caller's role.** ``direct_tools`` names the tools an agent
          works with; it is shown those and its own hands, on any provider.

        The provider's own tool-count cap (``max_tools``) defers the same way.
        The tool a deterministic gate mandated this turn, ``run-skill`` on a
        skill match and the caller's own hands are always shown.
        """
        nothing: frozenset[str] = frozenset()
        # A real tool of that name leaves no room for the finder: show
        # everything, as before.
        if not isinstance(tools, dict) or not tools or FIND_TOOLS_NAME in tools:
            return tools, nothing
        try:
            window = int(getattr(brain, "context_window", 0) or 0)
        except (TypeError, ValueError):
            # A malformed context window means 'unknown'; no trimming then.
            window = 0
        try:
            max_tools = int(getattr(brain, "max_tools", 0) or 0)
        except (TypeError, ValueError):
            # A malformed tool limit means 'unknown'; no trimming then.
            max_tools = 0
        # Default deferral: on a brain seat with room to spare, show a small
        # frozen core and put every connected-server, plugin and rarer tool
        # behind ``find_tools``. Not about the window: with hundreds of tools
        # the choice gets worse and the prompt cache churns whenever the list
        # does. A small-window model keeps its own narrower rules below.
        small_window = 0 < window <= _m._SMALL_WINDOW_TOKENS
        defer_by_default = (
            direct_tools is None
            and not small_window
            and getattr(getattr(getattr(self, "_config", None), "brain", None), "defer_tools", True)
            is not False
        )
        if window <= 0 and max_tools <= 0 and direct_tools is None and not defer_by_default:
            return tools, nothing
        keep: set[str] = {name for name in own_tools if name in tools}
        mandated = getattr(self, "_evidence_required_tool", None)
        if mandated:
            keep.add(str(mandated))
        if getattr(self, "_skill_turn_match", None) is not None:
            keep.add("run-skill")
        used = (
            _m._approx_tokens(system_prompt)
            + _m._approx_history_tokens(history)
            + _m._CONTEXT_FIT_RESERVE_TOKENS
        )
        budget = max(window - used, 0) if window > 0 else None
        # One slot of a provider's count cap is held for ``find_tools``.
        limits = [max(max_tools - 1, 1)] if max_tools > 0 else []
        if 0 < window <= _m._SMALL_WINDOW_TOKENS:
            limits.append(_m._SMALL_MODEL_DIRECT_TOOLS + len(keep))
        max_direct = min(limits) if limits else 0
        only = None if direct_tools is None else {*direct_tools, *ROLE_BASE}
        priority: Iterable[str] = CORE_PRIORITY
        lead = False
        if defer_by_default:
            # The lead sees ``delegate`` where the other turns see the overlapping
            # hand-off tools (they wait behind ``find_tools``).
            lead = self._is_lead_turn()
            priority = LEAD_DIRECT if lead else DEFAULT_DIRECT
            only = set(priority)
        plan = plan_surface(
            tools,
            keep=keep,
            priority=priority,
            budget_tokens=budget,
            max_direct=max_direct,
            only=only,
        )
        if not plan.deferred:
            return tools, nothing
        reveal_tokens: int | None = None
        if budget is not None:
            # The finder and what it reveals need room of their own. When the
            # window is what forced the split, hold that room back and choose
            # again; otherwise the first lookup overflows the window that the
            # shown tools already fill to the brim.
            spent = sum(tool_tokens(name, tool) for name, tool in plan.direct.items())
            headroom = budget - spent
            if headroom < _m._REVEAL_RESERVE_TOKENS:
                reveal_tokens = min(_m._REVEAL_RESERVE_TOKENS, budget // 3)
                plan = plan_surface(
                    tools,
                    keep=keep,
                    priority=priority,
                    budget_tokens=max(budget - reveal_tokens - _m._FINDER_TOKENS, 0),
                    max_direct=max_direct,
                    only=only,
                )
            else:
                reveal_tokens = headroom - _m._FINDER_TOKENS
        surface: dict[str, Tool] = (
            order_direct(plan.direct, LEAD_DIRECT if lead else DEFAULT_DIRECT)
            if defer_by_default
            else dict(plan.direct)
        )
        surface[FIND_TOOLS_NAME] = cast(
            Tool, FindToolsTool(plan.deferred, reveal_tokens=reveal_tokens)
        )
        surface.update(plan.deferred)
        log.info(
            "Tool surface for %s: %d of %d tools shown, %d behind find_tools "
            "(window %s, prompt+history ~%d tokens, count limit %s). First deferred: %s",
            getattr(brain, "name", type(brain).__name__),
            len(plan.direct),
            len(tools),
            len(plan.deferred),
            window or "undeclared",
            used,
            min(limits) if limits else "none",
            ", ".join(list(plan.deferred)[:5]),
        )
        return surface, frozenset(plan.deferred)

    def _hide_spawn_on_knowledge_question(
        self, tools: dict[str, Tool], user_text: str
    ) -> dict[str, Tool]:
        """Remove the spawn tools from a PLAIN knowledge/factual question's tool
        surface so the router-LLM cannot reflexively delegate an answerable
        question to a background worker.

        Forensic 2026-06-27 (voice session 08:35): "Welche Unternehmen haben so
        viel Speicherplatz?" — a pure factual question — was answered by the LLM
        *choosing* ``spawn_worker`` ("ich ziehe einen Experten hinzu"), against
        the router prompt's own rule ("NIEMALS spawn_worker fuer eine Frage, die
        du mit 1-2 Suchanfragen beantworten kannst"). The deterministic
        force-spawn gate correctly stands down on such a turn, but it only
        *forces* spawns — it never *constrains* the LLM's own spawn reflex. This
        mirrors the smalltalk tool-hide (2026-05-01): the surest way to stop a
        wrong tool call is to not offer the tool. ``search_web`` / plugin reads /
        ``computer_use`` stay visible so the question is still answerable inline.

        Narrow on purpose (no collateral spawn loss): fires ONLY on an actual
        question (interrogative opener or "?") that carries NEITHER action intent
        NOR an artifact-build request, and NEVER when the user explicitly named a
        heavy-work vehicle ("Subagent" / "deep dive"). Pure regex + the existing
        deterministic detectors (AP-11 safe, provider-agnostic). Defensive: any
        fault returns the tools unchanged so a gate bug can never blind the brain.
        """
        if not isinstance(tools, dict):
            return tools
        try:
            t = (user_text or "").strip()
            if not _is_plain_knowledge_question(t):
                return tools
            # User explicitly named the vehicle → respect it, never hide (AD-S9).
            if self._is_explicit_heavy_request(t):
                return tools
            # A real desktop/action turn or an artifact-build request still needs
            # the spawn tools — only a pure ANSWER question loses them.
            if self._turn_has_action_intent(t) or self._research_wants_artifact(t):
                return tools
            return {n: tool for n, tool in tools.items() if n not in _SPAWN_TOOL_NAMES}
        except Exception:  # noqa: BLE001 — gate must never blind the brain
            log.debug("knowledge-question spawn-hide gate failed", exc_info=True)
            return tools

    def _hide_agentic_ide_tools_without_workspace(
        self, tools: dict[str, Tool]
    ) -> dict[str, Tool]:
        """Drop the pane-scoped Agentic-IDE tools when NO workspace is open.

        A capability gate, not a keyword guess: without an open workspace
        those tools can only fail, so hiding them loses nothing — and their
        schemas are ~10 KB of input re-sent on every tool-loop iteration.
        ``agentic-ide-status`` and ``agentic-ide-resume`` always stay (see
        _AGENTIC_IDE_WORKSPACE_TOOL_NAMES). Defensive: any fault returns
        the tools unchanged so a gate bug can never blind the brain.
        """
        if not isinstance(tools, dict):
            return tools
        try:
            if not any(n in tools for n in _AGENTIC_IDE_WORKSPACE_TOOL_NAMES):
                return tools
            from dodaios.agentic_ide.session import get_registry as _ide_registry

            if _ide_registry().session is not None:
                return tools
            return {
                n: tool
                for n, tool in tools.items()
                if n not in _AGENTIC_IDE_WORKSPACE_TOOL_NAMES
            }
        except Exception:  # noqa: BLE001 — gate must never blind the brain
            log.debug("agentic-ide workspace tool gate failed", exc_info=True)
            return tools

    def _hide_artifact_tool_without_request(
        self, tools: dict[str, Tool], user_text: str
    ) -> dict[str, Tool]:
        """Drop ``create_artifact`` from every turn that did not ask for one.

        Maintainer mandate (2026-08-11, renewed 2026-08-23 for artifacts): a
        page or picture is built when the user says they want to see
        something — never because the assistant judged an answer would look
        nicer as a dashboard. Prompt wording alone does not hold that line; a
        tool the model cannot see is a line it cannot cross, so the
        enforcement is structural. It also keeps a background mission on the
        strongest model from being started on a whim.

        The gate is ``dodaios.brain.artifact_gate.wants_artifact`` — pure regex,
        no model in the detection path (AP-11). Defensive: any fault returns
        the tools unchanged, so a gate bug can never blind the brain.
        """
        if not isinstance(tools, dict) or _ARTIFACT_TOOL_NAME not in tools:
            return tools
        try:
            from dodaios.brain.artifact_gate import wants_artifact  # noqa: PLC0415

            if wants_artifact(user_text or ""):
                return tools
            return {n: tool for n, tool in tools.items() if n != _ARTIFACT_TOOL_NAME}
        except Exception:  # noqa: BLE001 — gate must never blind the brain
            log.debug("artifact request gate failed", exc_info=True)
            return tools

    @staticmethod
    def _desktop_episode_is_live() -> bool:
        """True while a Computer-Use mission is running or has just ended.

        The one honest signal that the conversation context still holds a
        desktop plan a signalless turn could INHERIT: every launch route
        registers its mission (voice fast path, LLM tool, REST, scheduled). It
        is deliberately the same registry and the same window
        ``dodaios.brain.cu_gate`` consults for the mirror-image decision, so the
        two readings of "are we in a desktop episode" cannot drift apart.

        A failed probe answers "no episode": the default must be the full tool
        surface, never a blinded one.
        """
        try:
            from dodaios.brain.cu_gate import FOLLOW_UP_WINDOW_S  # noqa: PLC0415
            from dodaios.harness.cu_run_registry import (  # noqa: PLC0415
                has_recent_run,
            )

            return bool(has_recent_run(FOLLOW_UP_WINDOW_S))
        except Exception:  # noqa: BLE001 — never blind the brain on a probe
            log.debug("desktop-episode probe failed", exc_info=True)
            return False

    def _turn_reads_as_conversation(self, user_text: str) -> bool:
        """True when the turn's own SHAPE says it asks for no record to be written.

        Smalltalk or a plain question — the shapes the 2026-06-30 deep-dive
        found exposed to the write/record tools ("does my budget fit?"). Each
        detector is guarded on its own: ``_is_smalltalk`` needs the compiled
        routing patterns, and a manager built without them must degrade to
        "not obviously conversational" rather than take the whole gate down.
        """
        try:
            if self._is_smalltalk(user_text):
                return True
        except Exception:  # noqa: BLE001 — pattern cache unavailable
            log.debug("smalltalk probe failed in the signalless gate", exc_info=True)
        return _is_plain_knowledge_question(user_text)

    def _hide_action_tools_on_signalless_turn(
        self, tools: dict[str, Tool], user_text: str
    ) -> dict[str, Tool]:
        """Withhold the consequential tools a turn could only have INHERITED.

        Two distinct risks with two distinct pieces of evidence — and "the
        action regex did not fire" is neither of them. The forensics:

        1. **Inheritance (2026-06-27).** "Was geht ab?" → STT "Lask it up!" [en]
           conf 0.509 → the router-LLM, reading a 30k-token context full of the
           prior "open Discord, bridge-mine channel" command, re-ran that exact
           computer_use plan on a turn that asked for nothing. That risk needs
           something to inherit: a desktop episode that is live or just ended
           (``_desktop_episode_is_live``). Cold, there is no prior plan in the
           context to re-run.
        2. **Write reflex (deep-dive 2026-06-30).** A "does my budget fit?" turn
           carried google_calendar / contact-upsert / wiki-ingest /
           update_profile in its surface. The evidence there is the turn's own
           shape: smalltalk or a plain question asks for no record to be written
           (``_turn_reads_as_conversation``).

        What changed, and why (2026-08-17 review): the previous version hid both
        sets from EVERY turn that missed ``is_open_app_intent`` /
        ``_looks_like_pc_control`` / the capability registry. That regex knows
        "klick" and "Bildschirm"; it does not know "spiel Musik", "ruf Anna an"
        or "trag das in meinen Kalender ein" — so those turns reached the model
        with no vehicle at all and could only be talked about. Absence of a
        keyword is not evidence of absence of intent. A tool the model declines
        to call is free; a tool it cannot see is the bug users report.

        Both protections above still fire, on their own evidence. A genuine
        action signal (action-intent, artifact-build request, named spawn
        vehicle, request framing) short-circuits the gate, the read-only ``screenshot``
        tool is never hidden, and a tool the deterministic layer mandated this
        turn is never stripped (AD-CLI8). Pure regex + registry lookups, no
        model in the path (AP-11 safe). Any fault returns the tools unchanged so
        a gate bug can never blind the brain.
        """
        if not isinstance(tools, dict):
            return tools
        try:
            t = (user_text or "").strip()
            if not t:
                return tools
            # Any genuine ACTION signal keeps the consequential tools: an action
            # intent (open-app / PC-control / names the screen surface / registry
            # intent), an artifact-build request, an explicitly named spawn
            # vehicle — or REQUEST FRAMING. The last one is the same signal
            # ``_is_smalltalk`` already trusts to call a turn a command rather
            # than chit-chat: "Kannst du Anna anrufen?" is question-SHAPED and
            # would otherwise lose call-contact to the write-reflex half below,
            # and "kannst du das nochmal machen?" is the corrective follow-up
            # cu_gate's episode window exists to keep alive.
            if (
                self._turn_has_action_intent(t)
                or self._research_wants_artifact(t)
                or self._is_explicit_heavy_request(t)
                or _ACTION_REQUEST_RE.search(t)
            ):
                return tools
            hidden: set[str] = set()
            if self._desktop_episode_is_live():
                hidden |= _INHERITABLE_ACTION_TOOL_NAMES
            if self._turn_reads_as_conversation(t):
                hidden |= _DETERMINISTIC_WRITE_TOOL_NAMES
            if not hidden:
                return tools
            # NEVER strip a tool the deterministic layer already mandated this
            # turn (a say-do write via resolve_save_mandate, or a calendar/email
            # READ via the evidence gate), or those features regress (AD-CLI8).
            mandated = getattr(self, "_evidence_required_tool", "") or ""
            return {
                n: tool
                for n, tool in tools.items()
                if n not in hidden or n == mandated
            }
        except Exception:  # noqa: BLE001 — gate must never blind the brain
            log.debug("signalless-turn action-hide gate failed", exc_info=True)
            return tools

    def _hide_spawn_when_plugin_tool_handles_turn(
        self, tools: dict[str, Tool], user_text: str
    ) -> dict[str, Tool]:
        """Hide the spawn vehicles when a connected plugin tool's usage-card
        keywords match the turn, so the router-LLM uses that (router-only) plugin
        tool DIRECTLY instead of delegating to a worker that cannot reach it.

        Forensic 2026-06-27 (voice session 17:44): "Schau mal nach, was in meinem
        Google Calendar am 29. fuer Termine sind" — the router spawned a worker
        ("umfangreicheres Stueck Arbeit") which has NO google_calendar tool
        (plugin tools are router-tier only, AP-5/AP-14) and answered "kann ich
        nicht". The deterministic force-spawn gate stands down on such a turn, but
        it never constrains the LLM's own spawn reflex. A plugin-tool turn must
        never be delegated. Mirrors ``_hide_spawn_on_knowledge_question``: the
        surest way to stop a wrong spawn is to not offer the spawn tool. The
        matched plugin tool + ``search_web`` + reads stay visible, so the turn is
        still answerable inline.

        Narrow on purpose: stands down when the user explicitly named a heavy-work
        vehicle ("Subagent" / "deep dive") or asked to BUILD an artifact
        (file / report), both of which legitimately spawn. Pure regex + the
        usage-card keyword gate (AP-9 cached / AP-11 safe, provider-agnostic).
        Defensive: any fault returns the tools unchanged so a gate bug can never
        blind the brain.
        """
        if not isinstance(tools, dict):
            return tools
        try:
            t = (user_text or "").strip()
            if not t:
                return tools
            # An explicit heavy-work vehicle or an artifact-build request still
            # legitimately spawns — never hide the spawn vehicles there.
            if self._is_explicit_heavy_request(t) or self._research_wants_artifact(t):
                return tools
            from dodaios.marketplace.usage_cards.loader import load_usage_card

            # A tool in the surface whose usage card matches => this is a
            # plugin-tool turn. Native tools use their name as the card id
            # (google_calendar); namespaced plugin tools use the id before "/".
            for name in tools:
                pid = name.partition("/")[0]
                card = load_usage_card(pid)
                if card is not None and card.matches(t):
                    return {
                        n: tool
                        for n, tool in tools.items()
                        if n not in _SPAWN_TOOL_NAMES
                    }
            return tools
        except Exception:  # noqa: BLE001 — gate must never blind the brain
            log.debug("plugin-tool spawn-hide gate failed", exc_info=True)
            return tools

    def _hide_run_skill_on_pc_control_turn(
        self, tools: dict[str, Tool], user_text: str
    ) -> dict[str, Tool]:
        """Hide ``run-skill`` when the turn explicitly asks to operate THIS
        computer's screen (open an app/terminal, click, type into a program),
        so ``computer_use`` stays authoritative for the named desktop vehicle.

        Forensic 2026-07-02 (voice session 20:28, turn 1): "ein Terminal
        öffnen, Cloud-Code öffnen, … und für mich ein Prompt geben …
        kompletten Deep-Dive machen … ob es irgendwelche Bugs gibt" — an
        unambiguous desktop request (open a terminal, open Claude Code, type a
        prompt into it). The SKILLS-FIRST router rule ("when in doubt, call
        the skill") let the semantically-similar ``cloud-debug`` skill hijack
        the turn: run-skill returned its mission directive, the model followed
        neither it nor computer_use and spoke the dictated capability refusal
        ("mir fehlt dafür das passende Werkzeug"). The vehicle the user NAMED
        (the desktop) must outrank a loose skill CONTENT match — and the
        surest way to stop a wrong tool call is to not offer the tool (mirrors
        the knowledge-question / plugin-tool hides above).

        Narrow on purpose: fires ONLY when a deterministic pc-control /
        open-app signal is present AND ``computer_use`` is actually in the
        surface (a host without the CU harness keeps run-skill so the turn
        stays handleable). Stands down when the user literally says "skill" —
        an explicit skill request is its own vehicle. The deterministic
        trigger-match inline path (AD-S4) is untouched: a skill whose OWN
        trigger phrase matched rides the turn context before this gate and
        needs no run-skill call. Pure regex + existing detectors (AP-11 safe,
        provider-agnostic). Defensive: any fault returns the tools unchanged
        so a gate bug can never blind the brain.
        """
        if not isinstance(tools, dict):
            return tools
        try:
            t = (user_text or "").strip()
            if not t or "run-skill" not in tools or "computer_use" not in tools:
                return tools
            if not (is_open_app_intent(t) or _looks_like_pc_control(t)):
                return tools
            # User literally named a skill → that request wins, keep run-skill.
            if _EXPLICIT_SKILL_REQUEST_RE.search(t):
                return tools
            return {n: tool for n, tool in tools.items() if n != "run-skill"}
        except Exception:  # noqa: BLE001 — gate must never blind the brain
            log.debug("pc-control run-skill-hide gate failed", exc_info=True)
            return tools

    def _apply_plugin_relevance(
        self, user_text: str, tools: dict[str, Tool]
    ) -> dict[str, Tool]:
        """Drop plugin tools (namespaced ``<id>/<tool>``) irrelevant to this turn.

        Keyword-only, no LLM / no IO (AP-9). Native (non-namespaced) tools are
        untouched. Defensive: any failure returns the unfiltered dict so a gate
        bug can never blind the brain on the voice path.
        """
        try:
            from dodaios.marketplace.plugin_relevance import filter_plugin_tools

            kept = filter_plugin_tools(user_text, list(tools.values()))
            kept_names = {t.name for t in kept}
            return {name: t for name, t in tools.items() if t.name in kept_names}
        except Exception:  # noqa: BLE001
            log.debug("plugin relevance gate failed; using full tool set", exc_info=True)
            return tools

    def _suppress_plugins_covered_by_cli(
        self, tools: dict[str, Tool], user_text: str = ""
    ) -> dict[str, Tool]:
        """Hide plugin/native tools whose CLI counterpart is connected (req 4).

        A CLI runs a local subprocess and is cheaper than a plugin's MCP/API
        hop, so when a CLI for a service is active its plugin is removed from the
        turn's tool surface unless explicitly requested. Defensive: returns the tools
        unchanged on any fault (never blind the brain on the voice path).
        """
        try:
            from dodaios.clis.capability_provider import (
                suppress_plugin_tools_covered_by_cli,
            )

            return suppress_plugin_tools_covered_by_cli(tools, user_text)
        except Exception:  # noqa: BLE001
            log.debug("plugin-CLI suppression failed; full tool set", exc_info=True)
            return tools

    def _plugin_usage_cards_block(self, tools: dict[str, Tool]) -> str:
        """Markdown block of usage cards for the plugins active in this turn.

        Only the plugins whose tools are in ``tools`` (already relevance-gated)
        contribute, so the prompt stays small. Returns ``""`` when no plugin
        tools are active. Defensive: never raises on the prompt-build path.
        """
        try:
            from dodaios.marketplace.usage_cards.loader import load_usage_card

            plugin_ids: list[str] = []
            for name in tools:
                pid, sep, _ = name.partition("/")
                if sep and pid not in plugin_ids:
                    plugin_ids.append(pid)
            blocks: list[str] = []
            for pid in plugin_ids:
                card = load_usage_card(pid)
                if card and card.body:
                    blocks.append(f"### Plugin: {pid}\n{card.body}")
            if not blocks:
                return ""
            return "## Connected plugins — how to use them\n\n" + "\n\n".join(blocks)
        except Exception:  # noqa: BLE001
            log.debug("plugin usage-card block failed; omitting", exc_info=True)
            return ""
