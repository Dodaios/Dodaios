"""Local-action fast path, computer-use background runs and pending confirmations."""
from __future__ import annotations

import asyncio
import time
from typing import Any
from uuid import UUID, uuid4

from dodaios.brain import manager as _m
from dodaios.brain.local_action_gate import HARNESS_NAME, LocalActionMode
from dodaios.brain.manager import (
    _MAX_CONFIRM_REASKS,
    _SCREEN_CONFIRM_TTL_S,
    _TURN_HISTORY_OVERRIDE,
    _TURN_OVERRIDE,
    _PendingScreenConfirm,
    _PendingVoiceConfirm,
    _takes_pending_appshot,
    _turn_phrase_language,
    log,
)
from dodaios.core.events import ActionExecuted, AnnouncementRequested
from dodaios.core.protocols import BrainMessage
from dodaios.voice.action_phrases import (
    CU_CANCEL_EXIT_CODE,
    CU_TOOL_OUTCOME_LAYER,
    OUTPUT_LANGUAGE_ENV_KEY,
    action_phrase,
    cu_failure_readback,
    cu_success_readback,
    extract_speakable_reason,
    localize_failure_reason,
)
from dodaios.voice.contextual_readback import render_readback


class _LocalActionMixin:
    """Local-action fast path, computer-use background runs and pending confirmations."""

    async def _run_local_action_fast_path(
        self,
        user_text: str,
        *,
        trace_id: UUID | None = None,
    ) -> str | None:
        """Execute narrow local actions before vision/provider work.

        The tools used here are intentionally hidden from ``self._tools`` so
        they never appear in the router LLM schema.
        """
        if _TURN_OVERRIDE.get() is not None:
            # Scoped chats must use their selected tools and approval context,
            # not the voice shortcut's global desktop/browser tool set.
            return None
        local_cfg = getattr(self._config, "local_action", None)
        if local_cfg is not None and not getattr(local_cfg, "enabled", True):
            return None
        if self._tool_executor is None:
            return None

        plan = _m.match_local_action(
            user_text,
            lang=self._spoken_reply_language(user_text),
            live_tool_names=self._live_tool_names(),
        )
        if plan is None:
            return None

        tid = trace_id or uuid4()
        if plan.mode == LocalActionMode.UNSUPPORTED:
            # The gate recognised an action request but no registered capability
            # covers it. Speak its deterministic rejection (response_text)
            # instead of dropping it and leaving the user with silence — the
            # gate docstring mandates "route straight to TTS, skipping brain".
            # Without this branch the plan fell through to `return None` and the
            # rejection copy was lost.
            return plan.response_text or None
        if plan.mode == LocalActionMode.DIRECT:
            outputs: list[str] = []
            timeout_s = float(getattr(local_cfg, "direct_timeout_s", 3.0))
            # The DIRECT path surfaces tool output verbatim (no LLM re-render),
            # so the spoken acknowledgement must be localized HERE — the
            # language pin/detection that governs LLM replies never reaches it.
            ack_lang = self._direct_ack_language(user_text)
            for call in plan.tool_calls:
                tool = self._local_action_tools.get(call.name)
                if tool is None:
                    return None
                try:
                    result = await asyncio.wait_for(
                        self._tool_executor.execute(
                            tool,
                            dict(call.args),
                            user_utterance=user_text,
                            trace_id=tid,
                        ),
                        timeout=timeout_s,
                    )
                except TimeoutError:
                    await self._bus.publish(ActionExecuted(
                        trace_id=tid,
                        tool_name=call.name,
                        success=False,
                        duration_ms=int(timeout_s * 1000),
                        error=f"timeout after {timeout_s:.3g}s",
                    ))
                    # Never speak the internal tool name + machine "timeout after
                    # 3s" string; a plain, localized line via the composer instead.
                    return await render_readback(
                        getattr(self, "_readback_composer", None),
                        instruction=(
                            "The action the user asked for took too long and was "
                            "stopped before it finished."
                        ),
                        language=ack_lang,
                        canned=lambda: action_phrase("action_timeout", ack_lang),
                    )
                if not result.success:
                    # NEVER return ``result.error`` verbatim — it is routinely the
                    # opaque ``exit N`` token (live forensic 2026-06-28: a harness
                    # failure was spoken as the bare "exit 1"). Route through the
                    # honest, localized, composer-backed readback instead.
                    return await self._honest_failure_readback(
                        result,
                        user_text=user_text,
                        situation=(
                            "An action the user asked for could not be completed."
                        ),
                        generic_key="action_failed_generic",
                        reason_key="action_failed_reason",
                        lang=ack_lang,
                    )
                if result.output is not None:
                    outputs.append(
                        self._localize_direct_ack(call, str(result.output), ack_lang)
                    )
            return "\n".join(outputs)

        if plan.mode == LocalActionMode.COMPUTER_USE:
            tool = self._local_action_tools.get("dispatch_to_harness")
            if tool is None:
                # Never swallow this silently (contract §7): the gate matched a
                # screen action but the fast path has no dispatcher. Falling
                # through to the full brain turn is correct — the `computer_use`
                # router tool carries its own preflight and speaks honestly —
                # but the drop must be visible in the log, not invisible.
                log.warning(
                    "CU fast path: 'dispatch_to_harness' is not registered in "
                    "_local_action_tools; handing the request to the brain turn "
                    "instead of running it deterministically (trace=%s)",
                    tid,
                )
                return None
            # Resolve the turn language ONCE here (while it is current) for the
            # availability refusal, the spoken cost messages, the immediate ACK,
            # and the background readback — the offloaded task runs after the
            # turn returns and must not read the per-turn state itself (live bug
            # 2026-06-15).
            cu_lang = self._direct_ack_language(user_text)
            # Availability preflight (GT-19). The harness only works once the
            # app wired its ComputerUseContext, and that happens only when
            # [computer_use].enabled AND a vision engine exist (factory.py).
            # Unwired, every step died deep inside the harness — but the ACK
            # below had already promised "Mach ich", so the user heard a
            # commitment, then nothing, then a failure up to 180 s later. Peek
            # the singleton BEFORE dispatching and refuse immediately and
            # honestly instead. Same guard the LLM tool path uses
            # (plugins/tool/computer_use_tool.py::execute).
            from dodaios.harness.computer_use_context import (  # noqa: PLC0415
                peek_computer_use_context,
            )
            if peek_computer_use_context() is None:
                log.warning(
                    "CU fast path: computer-use is not wired on this machine "
                    "([computer_use].enabled false or no vision engine); "
                    "refusing the screen action instead of acknowledging it "
                    "(trace=%s)",
                    tid,
                )
                return await render_readback(
                    getattr(self, "_readback_composer", None),
                    instruction=(
                        "Desktop control is switched off on this machine, so "
                        "you cannot do anything on the screen right now. It is "
                        "turned on with the config value "
                        "computer_use.enabled=true, followed by a restart."
                    ),
                    language=cu_lang,
                    canned=lambda: action_phrase("cu_not_wired", cu_lang),
                    latency_budget_ms=900,
                )
            # A multi-step CU mission ("navigate to amazon, search, click") needs a
            # generous OUTER cap — the harness has its own per-step timeout +
            # step-budget + no-progress/consecutive-failure guards, so this is only
            # a backstop. The old 30 s ``harness_timeout_s`` aborted legit
            # multi-step missions; the router-tool path already used 120 s. The
            # mission is OFFLOADED (immediate ACK), so a longer cap never blocks
            # the spoken turn. Honour a larger configured value if set.
            _configured_timeout = float(getattr(local_cfg, "harness_timeout_s", 30.0))
            timeout_s = max(_configured_timeout, 180.0)
            if _configured_timeout < 180.0:
                log.debug(
                    "CU offload: harness_timeout_s=%.0fs raised to 180s floor "
                    "(offloaded multi-step mission; harness has its own per-step + "
                    "step-budget + no-progress guards)",
                    _configured_timeout,
                )
            if self._cost_meter is not None:
                if self._cost_meter.is_in_cooldown():
                    return await render_readback(
                        getattr(self, "_readback_composer", None),
                        instruction=(
                            "A cost cooldown is active: the daily budget is used "
                            "up, so new requests resume only after the cooldown ends."
                        ),
                        language=cu_lang,
                        canned=lambda: action_phrase("cost_cooldown", cu_lang),
                    )
                if self._cost_meter.over_task_budget(tid):
                    return await render_readback(
                        getattr(self, "_readback_composer", None),
                        instruction=(
                            "The task budget for this conversation has been exceeded."
                        ),
                        language=cu_lang,
                        canned=lambda: action_phrase("task_budget", cu_lang),
                    )
                if self._cost_meter.over_daily_budget():
                    return await render_readback(
                        getattr(self, "_readback_composer", None),
                        instruction="The daily budget has been exceeded.",
                        language=cu_lang,
                        canned=lambda: action_phrase("daily_budget", cu_lang),
                    )
            # Wave-4 latency fix: Computer-Use is OFFLOADED off the voice turn.
            # Previously the harness was awaited inline for up to ~31 s, so a
            # "do it on screen" command froze the spoken turn the whole time.
            # Now we launch the harness as a BACKGROUND task and return an
            # immediate ACK (AD-OE1); its outcome — success, failure, or timeout
            # — is spoken at the next turn boundary via an
            # AnnouncementRequested(kind="completion") readback (AD-OE5/OE6, zero
            # silent drops). Harness identity comes from the gate; fall back to
            # the canonical in-process harness name (routes to ComputerUseHarness,
            # never a claude-cli worker spawn).
            #
            # Note: the result readback rides the announcement bus, which the
            # voice pipeline speaks. A text-chat-initiated Computer-Use command
            # therefore still executes and is ACK'd, but its result lands as a
            # voice announcement rather than in the chat transcript — an
            # acceptable trade for never freezing the spoken turn.
            # HARNESS_NAME ("screenshot") is the REGISTERED in-process CU harness
            # entry-point; "computer-use" is the router-tool name, NOT a harness,
            # so the old fallback would KeyError in HarnessManager if plan.harness
            # were ever empty. The gate always sets plan.harness=HARNESS_NAME, so
            # this is hygiene — but use the correct constant (review 2026-06-09).
            harness_name = plan.harness or HARNESS_NAME
            bg_tasks = getattr(self, "_cu_background_tasks", None)
            if bg_tasks is None:
                bg_tasks = set()
                self._cu_background_tasks = bg_tasks
            task = asyncio.create_task(
                self._run_computer_use_background(
                    tool=tool,
                    harness_name=harness_name,
                    # A follow-up/correction turn carries no task of its own —
                    # the goal inherits the recent turns that defined it.
                    prompt=self._cu_goal_with_context(plan.prompt or user_text),
                    timeout_s=timeout_s,
                    user_text=user_text,
                    trace_id=tid,
                    lang=cu_lang,
                ),
                name="computer-use-background",
            )
            # Keep a strong reference so the task is not garbage-collected
            # mid-flight, and drop it on completion.
            bg_tasks.add(task)
            task.add_done_callback(bg_tasks.discard)
            # Optimistic ACK (AD-OE1). On the turn-critical path, so a TIGHT
            # latency budget with the canned line as the instant fallback keeps
            # intent->ACK well under SLO. in_progress=True: the work has not
            # started, so a completion claim is rejected.
            return await render_readback(
                getattr(self, "_readback_composer", None),
                instruction=(
                    "You are about to carry out the user's request directly on "
                    "the screen, in the background, and will report back when done."
                ),
                language=cu_lang,
                canned=lambda: action_phrase("cu_dispatch_ack", cu_lang),
                facts={"user_request": user_text},
                in_progress=True,
                latency_budget_ms=900,
            )

        return None

    @staticmethod
    def _cu_failure_detail(output: Any) -> tuple[int | None, str | None]:
        """Pull ``(exit_code, human_detail)`` out of a CU harness failure result.

        ``dispatch_to_harness`` returns ``output`` as a dict with ``exit_code``
        plus ``stderr``/``stdout`` — and the screenshot loop writes the model's
        real ``fail`` reason into ``stderr`` (``"[cu] fail at <tag>: <reason>"``).
        We surface that reason so the readback can forward it instead of the
        opaque ``error="exit N"``. Best-effort: any non-dict / missing field
        yields ``(None, None)`` and the readback degrades to the exit-code phrase.
        """
        if not isinstance(output, dict):
            return None, None
        raw_code = output.get("exit_code")
        exit_code: int | None
        try:
            exit_code = int(raw_code) if raw_code is not None else None
        except (TypeError, ValueError):
            exit_code = None
        stderr = str(output.get("stderr") or "").strip()
        stdout = str(output.get("stdout") or "").strip()
        detail = stderr or stdout or None
        return exit_code, detail

    @staticmethod
    def _cu_failure_diagnostic(
        *, error: str | None, exit_code: int | None, detail: str | None
    ) -> str | None:
        """Compose the technical failure note for the TRANSCRIPT (never spoken).

        The voice readback is humanized via ``cu_failure_readback`` ("…didn't
        work on screen") — but the raw signal (the exit code plus the harness
        reason) is still valuable for debugging, so it is carried alongside on
        ``AnnouncementRequested.detail`` -> ``SpeechSpoken.detail`` and shown in
        the Transcription view (user request 2026-06-16). Returns None when
        there is nothing diagnostic to record (e.g. a successful run). Capped so
        the persisted payload stays small.
        """
        base = (error or "").strip() or (
            f"exit {exit_code}" if exit_code is not None else ""
        )
        reason = (detail or "").strip()
        note = f"{base} · {reason}" if base and reason else (base or reason)
        note = note.strip()
        return note[:300] if note else None

    async def _run_computer_use_background(
        self,
        *,
        tool: Any,
        harness_name: str,
        prompt: str,
        timeout_s: float,
        user_text: str,
        trace_id: UUID,
        lang: str,
    ) -> None:
        """Run the Computer-Use harness off the voice turn and speak the result.

        Launched fire-and-forget by ``_run_local_action_fast_path`` so the spoken
        turn ACKs immediately (AD-OE1) instead of blocking up to ~31 s on the
        harness. The outcome — success, failure, or timeout — is ALWAYS surfaced
        as an ``AnnouncementRequested(kind="completion")`` readback
        (AD-OE5/OE6: zero silent drops). Never raises — a background-task crash
        must not leak into the event loop.

        ``lang`` is captured at dispatch and threaded in: this task runs AFTER
        the turn returns, so ``self._turn_detected_lang`` may already belong to a
        later turn — reading it here would speak the wrong language (live bug
        2026-06-15: an English CU turn ended with the German "Erledigt.").
        """
        text: str
        # Technical failure note for the transcript (never spoken). Stays None
        # on success; the failure branch fills it with the exit code + reason.
        diag: str | None = None
        try:
            result = await asyncio.wait_for(
                self._tool_executor.execute(
                    tool,
                    {
                        "harness": harness_name,
                        "prompt": prompt,
                        "timeout_s": timeout_s,
                        # Thread the turn's language to the in-harness verifier so
                        # its spoken `proof` matches the frame's language (live bug
                        # 2026-06-27: a German turn read back an English proof).
                        "env": {OUTPUT_LANGUAGE_ENV_KEY: lang},
                    },
                    user_utterance=user_text,
                    trace_id=trace_id,
                ),
                timeout=timeout_s + 1.0,
            )
            if result.success:
                # FORWARD the verifier's on-screen observation (sitting in the
                # harness stdout) as the readback so an informational request
                # ("...and check which tabs I have open") is actually answered —
                # and NEVER ``str()`` the raw ``dispatch_to_harness`` result DICT
                # ({'harness': ..., 'exit_code': ..., 'stdout': ..., 'cost_usd':
                # ..., 'duration_ms': ...}), which used to leak verbatim into the
                # spoken/chat turn (live bug 2026-06-22, voice "geh in die
                # Einstellungen und öffne Bluetooth"; the scrubbed ``''`` key was
                # the blacklisted word "harness"). This is the SUCCESS sibling of
                # the ``cu_failure_readback`` humanization below and uses the same
                # static parse as the ``computer_use`` tool path — no LLM (AP-11).
                output = getattr(result, "output", None)
                stdout = output.get("stdout") if isinstance(output, dict) else None
                # The canned success line ALREADY forwards the verifier's signed
                # on-screen observation (or a plain "Done."). Use it as the
                # deterministic ground truth and let the composer only make it
                # sound natural — honesty_bound so it can rephrase but never
                # invent a detail the verifier did not report (ADR-0009). Off the
                # turn path, so a generous budget; instant canned fallback.
                canned_success = cu_success_readback(lang, stdout=stdout)
                text = await render_readback(
                    getattr(self, "_readback_composer", None),
                    instruction=(
                        "The user's on-screen request just succeeded; tell them "
                        "naturally, keeping any on-screen detail that was observed."
                    ),
                    language=lang,
                    canned=lambda: canned_success,
                    facts={"user_request": user_text, "result": canned_success},
                    honesty_bound=True,
                    latency_budget_ms=2500,
                )
            else:
                err = getattr(result, "error", None)
                exit_code, detail = self._cu_failure_detail(
                    getattr(result, "output", None)
                )
                # A user-initiated cancel (exit 130 — "auflegen" tripped the CU
                # cancel token) is NOT an outcome the user is waiting on: it is
                # the receipt of an abort they just triggered themselves. Speaking
                # "the action was cancelled" is redundant, and — because the
                # completion readback punches through the hangup gate (AD-OE5/OE6)
                # and each offloaded mission cancels independently — it spams the
                # phrase once per in-flight mission (live forensic 2026-06-27:
                # three CU missions cancelled by one F1+F2 hangup spoke it three
                # times). "auflegen" is a hard, immediately-silent kill-switch, so
                # drop the readback entirely. AD-OE6's zero-silent-drop guards
                # real outcomes (success / content failure / timeout) — those
                # still announce below — not a self-triggered abort.
                if exit_code == CU_CANCEL_EXIT_CODE:
                    log.info(
                        "CU background cancelled by user hangup (exit %d) — "
                        "no readback (auflegen = silent kill-switch)",
                        CU_CANCEL_EXIT_CODE,
                    )
                    return
                canned_failure = cu_failure_readback(
                    lang, error=err, exit_code=exit_code, detail=detail,
                )
                # The canned failure line is already humanized + scrubbed (no raw
                # exit code, only a speakable reason). Rephrase it naturally,
                # honesty_bound so the spoken reason stays faithful to what the
                # harness actually reported. Instant canned fallback.
                text = await render_readback(
                    getattr(self, "_readback_composer", None),
                    instruction=(
                        "The user's on-screen request did not work; tell them "
                        "plainly and kindly, keeping any reason that was given."
                    ),
                    language=lang,
                    canned=lambda: canned_failure,
                    facts={"user_request": user_text, "what_happened": canned_failure},
                    # Not a signed observation (ADR-0009 binds success readbacks);
                    # the digit + forbidden-vocab guards + strict persona keep it
                    # honest while allowing a natural failure phrasing.
                    honesty_bound=False,
                    latency_budget_ms=2500,
                )
                diag = self._cu_failure_diagnostic(
                    error=err, exit_code=exit_code, detail=detail,
                )
        except TimeoutError:
            _secs = f"{timeout_s:.0f}"
            text = await render_readback(
                getattr(self, "_readback_composer", None),
                instruction=(
                    "The on-screen task took too long and was stopped after "
                    f"{_secs} seconds."
                ),
                language=lang,
                canned=lambda: action_phrase("cu_timeout", lang, secs=_secs),
                facts={"seconds": _secs},
                latency_budget_ms=2000,
            )
            try:
                await self._bus.publish(ActionExecuted(
                    trace_id=trace_id,
                    tool_name="dispatch_to_harness",
                    success=False,
                    duration_ms=int((timeout_s + 1.0) * 1000),
                    error=f"timeout after {timeout_s:.3g}s",
                ))
            except Exception:  # noqa: BLE001
                log.debug("CU-background ActionExecuted publish failed", exc_info=True)
        except Exception as exc:  # noqa: BLE001 — a background crash must not leak
            log.error("Computer-Use background task failed: %r", exc, exc_info=True)
            text = await render_readback(
                getattr(self, "_readback_composer", None),
                instruction="Something went wrong while doing the task on screen.",
                language=lang,
                canned=lambda: action_phrase("cu_crashed", lang),
                latency_budget_ms=2000,
            )
        # Ground the finished outcome in the LIVE conversation history so the
        # model's NEXT turn knows the on-screen action ran and how it ended.
        # The outcome is offloaded fire-and-forget and only ever rode the
        # announcement bus (spoken, then gone) — it never re-entered _history,
        # so the model believed the screen action SUCCEEDED (it saw only the
        # optimistic ACK) and answered a follow-up "why didn't it work?" against
        # a stale unrelated error (live forensic 2026-06-30: a failed Spotify
        # screen action was explained with an old Google-Calendar auth error).
        self._append_cu_outcome_to_history(
            user_request=user_text, outcome_text=text, diagnostic=diag,
        )
        # AD-OE6 zero silent drops: ALWAYS speak the outcome at the next turn
        # boundary (announcement -> scrub_for_voice -> TTS).
        try:
            await self._bus.publish(AnnouncementRequested(
                text=text,
                priority="normal",
                language=lang,
                # A background Computer-Use task reports the user's requested
                # desktop action as the turn completion.
                kind="completion",
                detail=diag,
            ))
        except Exception:  # noqa: BLE001
            log.debug("CU-background completion announce failed", exc_info=True)

    def _append_cu_outcome_to_history(
        self,
        *,
        user_request: str,
        outcome_text: str,
        diagnostic: str | None,
        context_label: str = "on-screen-action",
    ) -> None:
        """Ground a finished background Computer-Use outcome in the live history.

        A desktop action is offloaded fire-and-forget, so its outcome lands AFTER
        the optimistic ACK ("On it, I'll do that on screen") was already appended
        as the turn's assistant message. Without this, ``_history`` shows only the
        ACK and the model never learns whether the screen action actually
        succeeded — so a later "why didn't it work?" is answered against whatever
        OTHER failure is still in context (live forensic 2026-06-30: a failed
        Spotify screen action was explained with a stale Google-Calendar auth
        error). Append an honest assistant note carrying the spoken outcome PLUS
        the real technical reason — which the humanized spoken readback hides — so
        the next turn is grounded in what actually happened. Pure in-memory
        append, no LLM, no IO (off the hot path anyway). ``user_request`` is
        accepted for call-site symmetry/debuggability; the ACK already names the
        request in history, so the note stays compact.
        """
        history = getattr(self, "_history", None)
        if history is None:
            return
        spoken = (outcome_text or "").strip()
        diag = (diagnostic or "").strip()
        if not spoken and not diag:
            return
        note = spoken
        if diag:
            # The spoken readback is humanized to "didn't work on screen"; the
            # model needs the REAL cause to answer a follow-up honestly. Mark it
            # clearly as a non-spoken background detail so the model treats it as
            # context, not as something it already said aloud.
            note = (
                f"{note}\n\n(Background {context_label} detail, not spoken aloud "
                f"— for your context on a follow-up: {diag})"
            ).strip()
        history.append(BrainMessage(role="assistant", content=note))
        if len(history) > self._HISTORY_MAX:
            self._history = history[-self._HISTORY_MAX:]

    def _last_exchange_text(self) -> str | None:
        """Last user+assistant exchange as an ingest source ('write THAT').

        ``_history`` entries are real :class:`BrainMessage` instances —
        ``role`` is one of ``user``/``assistant``/``system``/``tool`` and
        ``content`` is either a plain string or a list of multimodal blocks
        (dropped images etc.). Only plain-string user/assistant turns are
        usable ingest source text; anything else is skipped, never raises.
        """
        try:
            items = list(self._active_turn_history())[-4:]
        except Exception:  # noqa: BLE001 — history shape is provider-owned
            return None
        parts: list[str] = []
        for item in items:
            role = getattr(item, "role", None)
            text = getattr(item, "content", None)
            if role in ("user", "assistant") and isinstance(text, str) and text.strip():
                parts.append(f"{role}: {text.strip()}")
        return "\n".join(parts[-2:]) or None

    def _active_turn_history(self) -> list[BrainMessage]:
        """Return the context-local history when a caller supplied one."""
        override = _TURN_HISTORY_OVERRIDE.get()
        return list(override) if override is not None else self._history

    async def _persisted_session_exchange_text(self) -> str | None:
        """Return the latest persisted exchange from the active voice session.

        Realtime deliberately owns a small context-local history instead of
        sharing ``self._history``.  On its first delegated turn that history can
        therefore be empty even though the session recorder already contains a
        previous transcript.  Resolve the existing live runtime objects lazily
        and require an active session id before reading: an unscoped "latest"
        lookup could copy text from a different conversation into the Wiki.

        The runtime objects are intentionally accessed through
        :mod:`dodaios.core.runtime_refs`; the brain layer neither imports the web
        server nor depends on the concrete ``SessionStore`` type.  Any partially
        bootstrapped/headless runtime degrades to ``None``.
        """
        try:
            from dodaios.core import runtime_refs

            pipeline = runtime_refs.get_speech_pipeline()
            status_fn = getattr(pipeline, "voice_engine_status", None)
            status = status_fn() if callable(status_fn) else {}
            session_id = str(status.get("session_id") or "").strip()
            if not session_id:
                return None

            app = runtime_refs.get_web_app()
            store = getattr(getattr(app, "state", None), "session_store", None)
            get_latest = getattr(store, "get_latest_user_turn", None)
            if not callable(get_latest):
                return None

            turn = await asyncio.to_thread(get_latest, session_id=session_id)
        except Exception:  # noqa: BLE001 - persisted context is a soft fallback
            log.debug("Persisted session-history lookup failed", exc_info=True)
            return None

        parts: list[str] = []
        for role, value in (
            ("user", getattr(turn, "user_text", None)),
            ("assistant", getattr(turn, "jarvis_text", None)),
        ):
            if isinstance(value, str) and value.strip():
                parts.append(f"{role}: {value.strip()}")
        return "\n".join(parts) or None

    async def _on_cu_tool_completion(self, event: Any) -> None:
        """Mirror trusted asynchronous outcomes into the live brain history.

        The voice fast-path grounds its CU outcome inline (``_run_computer_use_
        background`` → :meth:`_append_cu_outcome_to_history`). The router-tier
        ``computer_use`` tool runs in its own module with NO ``_history`` access,
        so it tags its completion announcement with
        ``source_layer=CU_TOOL_OUTCOME_LAYER`` and we mirror it here — same
        grounding, so a text-chat / router-picked desktop action is in the
        model's next-turn context too. A ``kind="subagent"`` event is the signed
        terminal Jarvis-Agent readback and is also retained, including its
        mission id/result URI, so a later question can retrieve the real files.
        Other background announcements remain ignored.
        Never raises — a bus subscriber that throws would break the pipeline
        (AP-18). The fast-path leaves ``source_layer`` empty, so its outcome is
        NOT double-recorded here.
        """
        try:
            source_layer = getattr(event, "source_layer", "")
            kind = getattr(event, "kind", None)
            if source_layer == CU_TOOL_OUTCOME_LAYER:
                outcome_text = getattr(event, "text", "") or ""
                context_label = "on-screen-action"
            elif kind == "subagent":
                # Label with the wake-word-derived brand: the model quotes this
                # context in spoken answers, so a fixed product name would leak.
                try:
                    from dodaios.brain.assistant_name import agent_brand
                    from dodaios.core.config import load_config

                    brand = agent_brand(load_config())
                except Exception:  # noqa: BLE001 — labeling must not break the mirror
                    from dodaios.brain.assistant_name import agent_brand_from_name

                    brand = agent_brand_from_name("")
                outcome_text = (
                    f"{brand} mission result: "
                    f"{getattr(event, 'text', '') or ''}"
                )
                context_label = f"{brand} mission"
            else:
                return
            self._append_cu_outcome_to_history(
                user_request="",
                outcome_text=outcome_text,
                diagnostic=getattr(event, "detail", None),
                context_label=context_label,
            )
        except Exception:  # noqa: BLE001
            log.debug("Background completion history mirror failed", exc_info=True)

    async def _record_response_side_effects(
        self,
        *,
        user_text: str,
        response_text: str,
        use_history: bool,
        trace_id: UUID | None = None,
    ) -> None:
        """Apply the normal response side effects for non-provider paths too."""
        if use_history:
            self._history.append(BrainMessage(role="user", content=user_text))
            self._history.append(BrainMessage(role="assistant", content=response_text))
            if len(self._history) > 40:
                self._history = self._history[-40:]

        await self._publish_response_generated(
            trace_id=trace_id or uuid4(),
            text=response_text,
        )

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
                log.debug("Curator-Task nicht scheduled (kein Event-Loop)")

    def has_pending_voice_confirm(self) -> bool:
        """True while a two-turn voice confirmation is awaiting the user's yes/no.

        The speech pipeline consults this in ``_finish_after_response`` to keep
        the session open until the answer lands — otherwise (in single-turn mode)
        the turn finalizes and hangs up before the user can say "ja" (forensic
        2026-06-26). Mirrors how ``_background_mission_in_flight`` keeps a running
        mission's session alive.
        """
        screen_pending = getattr(self, "_pending_screen_confirms", {})
        if screen_pending:
            now = time.monotonic()
            expired = [
                key
                for key, pending in screen_pending.items()
                if pending.expires_at <= now
            ]
            for key in expired:
                screen_pending.pop(key, None)
        voice_screen_pending = any(
            surface == "voice" for surface, _conversation_id in screen_pending
        )
        return self._pending_voice_confirm is not None or voice_screen_pending

    async def _resolve_screen_context_turn(
        self,
        user_text: str,
        *,
        source_layer: str | None,
        conversation_id: str | None,
        allow_voice_confirm: bool,
        trace_id: UUID,
    ) -> Any:
        """Resolve a one-shot screen look and its optional next-turn consent.

        Screen consent is isolated by conversation surface and expires quickly.
        A bare confirmation can therefore authorize only the proposal the user
        just heard on that same surface; unrelated text drops the proposal and
        continues as a normal turn.
        """
        from dodaios.screen_context.intent import (  # noqa: PLC0415
            cancelled_reply,
            clarifying_question,
        )
        from dodaios.screen_context.turn import (  # noqa: PLC0415
            TurnScreenContext,
            screen_context_for_turn,
        )

        confirm_key = self._screen_confirm_key(
            source_layer=source_layer,
            conversation_id=conversation_id,
            allow_voice_confirm=allow_voice_confirm,
        )
        pending_map = getattr(self, "_pending_screen_confirms", None)
        if pending_map is None:
            pending_map = self._pending_screen_confirms = {}
        pending = pending_map.get(confirm_key)
        now = time.monotonic()
        if pending is not None and pending.expires_at <= now:
            pending_map.pop(confirm_key, None)
            pending = None

        if pending is not None:
            # Lazy import avoids pulling self-mod's confirmation graph into the
            # brain manager at module import time.
            from dodaios.voice.echo_confirmation import classify_response  # noqa: PLC0415

            verdict = classify_response(user_text, language=pending.lang)
            if verdict == "confirm":
                pending_map.pop(confirm_key, None)
                return await screen_context_for_turn(
                    "",
                    locale=pending.lang,
                    bus=self._bus,
                    force=True,
                    trace_id=trace_id,
                )
            if verdict == "veto":
                pending_map.pop(confirm_key, None)
                return TurnScreenContext(
                    status="cancelled", message=cancelled_reply(pending.lang)
                )
            if verdict == "ambiguous":
                pending.expires_at = now + _SCREEN_CONFIRM_TTL_S
                return TurnScreenContext(
                    status="clarify", question=clarifying_question(pending.lang)
                )
            pending_map.pop(confirm_key, None)

        locale = _turn_phrase_language(self, user_text)
        outcome = await screen_context_for_turn(
            user_text,
            locale=locale,
            bus=self._bus,
            trace_id=trace_id,
            allow_pending_appshot=_takes_pending_appshot(source_layer),
        )
        if outcome.status == "clarify":
            pending_map[confirm_key] = _PendingScreenConfirm(
                locale, now + _SCREEN_CONFIRM_TTL_S
            )
        return outcome

    @staticmethod
    def _screen_confirm_key(
        *,
        source_layer: str | None,
        conversation_id: str | None,
        allow_voice_confirm: bool,
    ) -> tuple[str, str]:
        # The layer that NAMES itself wins. allow_voice_confirm used to decide
        # this, which was fine only while voice was the sole surface passing
        # it — desktop chat passes it too since 6e6287b9, so keying on the flag
        # would drop both into one bucket and let a pending look proposal from
        # one surface answer for the other.
        surface = source_layer or ("voice" if allow_voice_confirm else "chat")
        return (surface, conversation_id or "default")

    def _has_pending_screen_confirm(
        self,
        *,
        source_layer: str | None,
        conversation_id: str | None,
        allow_voice_confirm: bool,
    ) -> bool:
        """Return whether this exact conversation owns a live look proposal."""
        key = self._screen_confirm_key(
            source_layer=source_layer,
            conversation_id=conversation_id,
            allow_voice_confirm=allow_voice_confirm,
        )
        pending = self._pending_screen_confirms.get(key)
        if pending is None:
            return False
        if pending.expires_at <= time.monotonic():
            self._pending_screen_confirms.pop(key, None)
            return False
        return True

    def _arm_voice_confirm(self, descriptor: dict[str, Any], user_text: str) -> None:
        """Turn N: record a deferred consequential action awaiting yes/no.

        ``descriptor`` is the tool-use loop's ``voice_confirm`` payload
        (``{"trace_id": str, "tool_name": str}``). The language is resolved once
        here (the turn's output language) and reused for both the classifier and
        the outcome phrasing on turn N+1.
        """
        trace_raw = descriptor.get("trace_id")
        try:
            tid = UUID(str(trace_raw))
        except (ValueError, TypeError):
            log.warning("voice-confirm: bad trace_id %r — not arming", trace_raw)
            return
        lang = _turn_phrase_language(self, user_text)
        self._pending_voice_confirm = _PendingVoiceConfirm(
            trace_id=tid, lang=lang, tool_name=str(descriptor.get("tool_name", "")),
        )
        log.info(
            "voice-confirm armed: tool=%s trace=%s lang=%s",
            self._pending_voice_confirm.tool_name, tid, lang,
        )

    async def _resume_voice_confirm(self, user_text: str) -> str | None:
        """Turn N+1: classify the user's yes/no and resolve the pending action.

        Returns the spoken OUTCOME when the turn is consumed by the confirmation;
        returns ``None`` when the pending action is dropped and the utterance must
        be processed as a normal turn (the user said something unrelated — they
        moved on, so the consequential action is abandoned, never executed).
        """
        pending = self._pending_voice_confirm
        if pending is None:
            return None
        # Lazy import: a top-level import of these would close a circular chain
        # (dodaios.voice.echo_confirmation → dodaios.core.self_mod → writer →
        # jarvis.brain → manager → echo_confirmation, half-initialized).
        from dodaios.voice.echo_confirmation import classify_response
        from dodaios.voice.tool_confirmation import format_confirm_outcome

        verdict = classify_response(user_text, language=pending.lang)

        if verdict == "confirm":
            self._pending_voice_confirm = None
            try:
                result = await self._tool_executor.execute_confirmed(
                    pending.trace_id, user_utterance=user_text,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("voice-confirm execute failed: %s", exc)
                # The user just said YES to this action; hearing only "that
                # didn't work" leaves them nothing to correct with. The same
                # opaque-token gate the result branch below relies on decides
                # whether the exception text is speakable at all.
                return format_confirm_outcome(
                    "failed",
                    pending.tool_name,
                    language=pending.lang,
                    detail=localize_failure_reason(
                        extract_speakable_reason(str(exc), None), pending.lang
                    )
                    or None,
                )
            kind = "done" if getattr(result, "success", False) else "failed"
            return format_confirm_outcome(
                kind,
                pending.tool_name,
                language=pending.lang,
                detail=(
                    None
                    if kind == "done"
                    # Raw ``error`` is routinely the opaque ``exit N`` token the
                    # tool layer emits; the gate turns that into no detail at
                    # all rather than a machine word in the user's ear. There is
                    # no composer on this path at all, so the cause is localized
                    # deterministically or it stays English forever.
                    else localize_failure_reason(
                        extract_speakable_reason(
                            getattr(result, "error", None),
                            getattr(result, "output", None),
                        ),
                        pending.lang,
                    )
                    or None
                ),
            )

        if verdict == "veto":
            self._pending_voice_confirm = None
            await self._cancel_pending_confirm(pending.trace_id)
            return format_confirm_outcome(
                "vetoed", pending.tool_name, language=pending.lang
            )

        if verdict == "ambiguous":
            pending.reasks += 1
            if pending.reasks > _MAX_CONFIRM_REASKS:
                self._pending_voice_confirm = None
                await self._cancel_pending_confirm(pending.trace_id)
                return format_confirm_outcome(
                    "timeout", pending.tool_name, language=pending.lang
                )
            return format_confirm_outcome(
                "unclear", pending.tool_name, language=pending.lang
            )

        # unknown: the user moved on. Drop the pending action (safe — never
        # executed) and let this utterance run as a normal turn.
        self._pending_voice_confirm = None
        await self._cancel_pending_confirm(pending.trace_id)
        return None

    async def _cancel_pending_confirm(self, trace_id: UUID) -> None:
        """Best-effort cancel of a deferred action — never breaks the turn."""
        try:
            await self._tool_executor.cancel_pending(trace_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("voice-confirm cancel failed: %s", exc)
