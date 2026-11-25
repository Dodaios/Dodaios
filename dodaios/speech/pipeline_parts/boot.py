"""Pipeline run loop, boot status and warm-up phases.

Moved out of ``pipeline.py`` without a behaviour change. Module-level names
of the pipeline are read through ``_pl`` at call time so the pipeline module
stays the one place that owns and patches them.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from dodaios.speech import pipeline as _pl

if TYPE_CHECKING:
    import asyncio

    from dodaios.core.protocols import AudioChunk


if TYPE_CHECKING:
    from dodaios.speech.pipeline_parts._host_state import SpeechPipelineHostState as _HostBase
else:
    _HostBase = object


class BootWarmupMixin(_HostBase):
    """Pipeline run loop, boot status and warm-up phases."""

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def run(self) -> None:
        # Capture the loop that owns ``_call_event`` / ``_hangup_event`` before
        # warm-up. UI controls can become clickable while warm-up is still in
        # progress, so recording it later would leave a small unsafe window.
        self._runtime_loop = asyncio.get_running_loop()
        await self._warmup()
        # Permanent-Vision: Background-Refresh-Loop hier im Pipeline-Event-Loop
        # starten. Ohne das kriegt `VisionContextProvider.current()` nie einen
        # gecachten Frame und der Router-Brain sieht den Screen nicht. Fehler
        # beim Start duerfen die Voice-Session nicht toeten — Text-Only-
        # Fallback greift weiter.
        if self._vision_provider is not None:
            try:
                await self._vision_provider.start()
                _pl.log.info("VisionContextProvider Background-Loop gestartet.")
            except Exception as exc:  # noqa: BLE001
                _pl.log.error(
                    "VisionContextProvider.start() fehlgeschlagen — "
                    "Router laeuft ohne Screen-Kontext: %s",
                    exc,
                    exc_info=True,
                )
        # Dictation wants BOTH key edges; call/hangup keep the single-fire-on-
        # release contract. One producer for boot and live re-arm.
        hotkey_bindings, ptt_events = self._build_hotkey_bindings()
        _pl.log.info(
            "Pipeline ready. CALL=[%s] HANGUP=[%s] DICTATE=[%s/%s] "
            "DICTATE-TOGGLE=[%s] PASTE-LAST=[%s] OWW=%s "
            "WAKE=%s (threshold=%.2f) WHISPER-WAKE=%s TURN-MODE=%s",
            ", ".join(self._call_hotkeys),
            ", ".join(self._hangup_hotkeys),
            ", ".join(self._dictate_hotkeys) or "off",
            self._dictate_mode,
            ", ".join(getattr(self, "_dictate_toggle_hotkeys", None) or []) or "off",
            ", ".join(getattr(self, "_paste_last_hotkeys", None) or []) or "off",
            "on" if self._openwakeword_enabled else "off",
            list(self._wake._keywords),
            self._wake._threshold,
            "on" if self._whisper_wake_enabled else "off",
            # Observability for the single-turn vs conversation pendulum: the
            # mode was previously invisible in the log, which made it impossible
            # to tell from telemetry whether a `turn_complete` hangup was the
            # configured single-turn behavior or a regression. See
            # feedback_voice_session_mode + BUG-009-style env-propagation traps.
            "conversation (until 'auflegen'/idle/hotkey)"
            if self._continue_listening_after_response
            else "single-turn (fresh wake per turn)",
        )
        def _log_task_exit(task: asyncio.Task) -> None:
            # Asyncio verschluckt Task-Exceptions sonst silent — wir hatten
            # genau diesen Bug 2026-04-26 (Mic-Open mit ungueltiger Sample-Rate
            # killte den Wake-Task ohne ein einziges Log).
            if task.cancelled():
                return
            exc = task.exception()
            if exc is not None:
                _pl.log.error(
                    "Pipeline-Task '%s' beendet mit Exception: %s",
                    task.get_name(),
                    exc,
                    exc_info=exc,
                )

        async with _pl.HotkeyTrigger(hotkey_bindings, push_to_talk=ptt_events) as trigger:
            # Kept for the hold-key watchdog (``_watch_dictation_hold_key``),
            # which asks the live trigger whether the chord is physically down.
            self._hotkey_trigger = trigger
            hotkey_task = asyncio.create_task(self._hotkey_loop(trigger), name="hotkey")
            hotkey_task.add_done_callback(_log_task_exit)
            # Live keybind re-arm: set_keybinds() flips _hotkey_reload_event and
            # this task re-registers the new combos in place (no app restart).
            hotkey_reload_task = asyncio.create_task(
                self._hotkey_reload_loop(trigger), name="hotkey-reload"
            )
            hotkey_reload_task.add_done_callback(_log_task_exit)
            wake_task = (
                asyncio.create_task(self._wake_loop(), name="wake")
                if self._wake_listening_enabled()
                else None
            )
            if wake_task is not None:
                wake_task.add_done_callback(_log_task_exit)
            else:
                _pl.log.info(
                    "Wake listener disabled; microphone stays closed until a hotkey call."
                )
            main_task = asyncio.create_task(self._state_loop(), name="state")
            main_task.add_done_callback(_log_task_exit)

            try:
                await main_task
            finally:
                self._hotkey_trigger = None
                tasks_to_cancel: list[asyncio.Task] = [hotkey_task, hotkey_reload_task]
                if wake_task is not None:
                    tasks_to_cancel.append(wake_task)
                for t in tasks_to_cancel:
                    t.cancel()
                for t in tasks_to_cancel:
                    try:
                        await t
                    except (asyncio.CancelledError, Exception):  # noqa: S110
                        # Shutdown has already cancelled these owned tasks.
                        pass
                if self._vision_provider is not None:
                    try:
                        await self._vision_provider.stop()
                    except Exception as exc:  # noqa: BLE001
                        _pl.log.debug("VisionContextProvider.stop() swallow: %s", exc)
                # Phase-B confirmation-audio render is fire-and-forget; cancel it
                # here so it is never orphaned past pipeline shutdown.
                await self._cancel_warmup_background()

    async def _emit_boot_status(self, *, ready: bool, detail: str = "") -> None:
        """Publish a VoiceBootStatus on the bus (guarded — never breaks boot).

        ``ready=False`` is emitted at the very start of warm-up; ``ready=True``
        only once ALL deferred loaders (wake model + VAD + TTS client) have
        completed, from ``_warmup_deferred_loaders`` — the first honest moment
        the user can both be heard AND get a spoken reply. (It runs after Phase A
        has returned, so the wake loop is already listening by then.)
        """
        if self._bus is None:
            return
        try:
            await self._bus.publish(_pl.VoiceBootStatus(ready=ready, detail=detail))
        except Exception as exc:  # noqa: BLE001 — status signal never breaks boot
            _pl.log.warning("VoiceBootStatus(ready=%s) publish failed: %s", ready, exc)

    async def _cancel_warmup_background(self) -> None:
        """Cancel + await the fire-and-forget warm-up tasks on shutdown.

        Three background tasks run off the wake-critical path: Phase B (the ACK +
        task-ack confirmation-audio pre-render), the deferred wake/VAD/TTS
        loaders (``_warmup_deferred_loaders``), and the boot-ready audio cue
        (``_warmup_ready_cue_task``, created at the end of the deferred loaders).
        When ``run()`` is cancelled (the normal desktop-shutdown path) all must
        be cancelled and awaited, otherwise they are orphaned: under
        ``pythonw.exe`` there is no stderr to surface the "Task exception was
        never retrieved" warning, and a late TTS render could write stale PCM
        into ``_ack_pcm`` / ``_task_ack_pcm`` after a live TTS-provider switch
        already cleared them. Guarded so shutdown never raises.
        """
        self._dictation_warmup_shutdown = True
        for attr in (
            "_warmup_background_task",
            "_warmup_ready_cue_task",
            "_deferred_warmup_task",
            "_dictation_warmup_task",
            "_voice_stt_warmup_task",
            "_audio_topology_task",
        ):
            task = getattr(self, attr, None)
            if task is None:
                continue
            if not task.done():
                task.cancel()
            try:
                # Bounded: a wedged native call inside a background worker
                # (e.g. a PortAudio re-init mid-refresh) must not hang the
                # whole shutdown; the orphaned worker dies with the process.
                await asyncio.wait_for(asyncio.shield(task), timeout=2.0)
            except TimeoutError:
                _pl.log.warning(
                    "Warm-up background task %s did not stop within 2s.", attr
                )
            except (asyncio.CancelledError, Exception):  # noqa: BLE001, S110
                # Shutdown is best-effort after the bounded wait above.
                pass
            setattr(self, attr, None)

    async def _warmup(self) -> None:
        _pl.log.info("Warm-up: Whisper / Silero / Wake-Word / TTS …")
        await self._emit_boot_status(ready=False, detail="warmup_start")

        # --- Phase A: start the wake LOOP, nothing else -------------------
        # Phase A blocks on the absolute minimum so the wake loop is listening
        # fast: the audio-device table settling (BUG-014 guard) and the wake
        # start. The heavy VAD / STT / TTS loads are deliberately NOT here — they
        # move to the background ``_warmup_deferred_loaders`` so they never gate
        # wake-loop start. NOTE: a started wake loop is NOT the same as "ready to
        # converse"; honest readiness (incl. TTS) is signalled later, from the
        # deferred loaders (see below).
        phase_a_start = time.monotonic()
        await self._warmup_phase_a()
        phase_a_ms = (time.monotonic() - phase_a_start) * 1000.0
        _pl.log.info("Warm-up Phase A (critical listening path) done in %.0f ms.", phase_a_ms)
        # Honest readiness (2026-06-29): Phase A only starts the wake LOOP — it
        # does NOT mean the user can hold a conversation yet (VAD + TTS, and the
        # custom-wake Whisper model, are still loading in
        # _warmup_deferred_loaders below). Readiness is therefore NOT signalled
        # here. BOTH the VoiceBootStatus(ready=True) and the audible "you can
        # speak" cue now fire at the END of _warmup_deferred_loaders — the first
        # moment wake (model) + VAD + TTS are ALL genuinely up. Previously the
        # openWakeWord path flipped ready in Phase A and the custom-phrase path
        # flipped it right after the wake model alone — either way the UI said
        # "ready" while TTS was still loading, so the user spoke and nothing came
        # back ("it says ready but I can't talk"). ready=False was already
        # emitted at warmup_start above, so the UI stays in its honest
        # "starting up / preparing to listen" state until the deferred loaders
        # complete.

        # --- Phase B: confirmation audio, off the critical path -----------
        # Pre-rendering the ACK + ~20 task-ack phrases used to dominate warm-up
        # (~20 sequential TTS round-trips). Fire it as a background task so it
        # never delays the ready signal; if the wake word fires before the ACK
        # is cached, the chime above plays instead.
        self._warmup_background_task = asyncio.create_task(
            self._warmup_phase_b(), name="warmup-confirmation-audio"
        )
        _pl.log.info("Warm-up Phase A complete — confirmation audio rendering in background.")

    def _log_audio_topology_done(self, task: asyncio.Task) -> None:
        """A silently dead hot-swap watcher must leave a diagnostic (BUG-102)."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            _pl.log.warning("Audio topology watcher died: %s", exc)

    def _log_warmup_ready_cue_done(self, task: asyncio.Task) -> None:
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # noqa: BLE001
            _pl.log.warning("Warm-up ready cue failed: %s", exc)

    async def _warmup_phase_a(self) -> None:
        """Bring up ONLY the wake-critical listening path, then return.

        The wake loop is started the moment this returns, so it must block on
        the absolute minimum: the audio-device table settling (BUG-014 guard)
        and the OpenWakeWord model starting. That is everything the wake path
        needs to hear "Hey Jarvis" and spawn the orb.

        The heavy VAD / STT / TTS-client loads are deliberately NOT here. Each
        of them lazy-imports a large C-extension (onnxruntime for the wake model
        and Silero-VAD, ctranslate2 for local Whisper); run concurrently inside
        the boot storm they serialize on the Python import lock and starve to
        7-24 s (measured: ``wake-start=14187, vad-load=12672``). Because the wake
        loop used to start only after the WHOLE warm-up finished, gating it on
        those loads left the wake word dead for that entire window — the
        "~10 s delay / nothing spawns" regression. They are only needed AFTER a
        wake and are lazy-safe (each object re-ensures its model on first use),
        so they move to a background deferred task (``_warmup_deferred_loaders``)
        that never gates wake readiness.
        """
        async def _start_wake() -> None:
            if self._openwakeword_enabled:
                await self._wake.start()

        # return_exceptions=True (inside _gather_timed): a slow/failing loader
        # must not abort the other. The per-loader timing exposes which one
        # dominates the wake-critical warm-up (boot-perf forensic).
        timings, results = await _pl._gather_timed(
            [
                ("audio-stabilize", self._stabilize_audio_devices),
                ("wake-start", _start_wake),
            ]
        )
        _pl.log.info(
            "Warm-up Phase A (wake-critical) per-loader (ms): %s",
            ", ".join(
                f"{name}={timings[name]:.0f}"
                for name in sorted(timings, key=lambda n: -timings[n])
            ),
        )
        for name, res in zip(("audio-stabilize", "wake-start"), results, strict=True):
            if isinstance(res, Exception):
                _pl.log.warning("Warm-up Phase A task '%s' failed: %s", name, res)

        # Heavy model loads move off the wake-ready path — fire-and-forget so a
        # wake can fire (and the orb spawn) while they are still loading. A wake
        # that arrives first simply triggers a one-off lazy load on the VAD/STT
        # object instead of waiting out the whole warm-up. Cancelled on shutdown
        # via ``_cancel_warmup_background``.
        self._deferred_warmup_task = asyncio.create_task(
            self._warmup_deferred_loaders(), name="warmup-deferred-loaders"
        )

    async def _warmup_deferred_loaders(self) -> None:
        """Background pre-load of the FULL conversational stack (wake model +
        VAD + TTS), then signal HONEST readiness.

        Runs OFF the wake-critical path (see ``_warmup_phase_a``): the wake loop
        is already listening by the time this starts, so a wake mid-load just
        triggers a one-off lazy load on the VAD/STT/TTS object. What this owns is
        the *honest* readiness signal — ``VoiceBootStatus(ready=True)`` and the
        audible "you can speak" cue fire ONLY at the very end, once wake (model),
        VAD endpointing AND the TTS reply path are all initialized. Flipping
        ready before TTS was up was the "it says ready but I can't talk" bug
        (2026-06-29).

        Ordering / GIL: the wake-model load is the one heavy CUDA/GIL step, kept
        FIRST and ALONE (racing it against the VAD load serialized both on the
        import + CUDA-init lock to ~11.8 s — forensic 2026-06-22). The TTS client
        init is network-bound (releases the GIL on I/O), so it is kicked off
        CONCURRENTLY with the wake warm-up to overlap its latency instead of
        paying it sequentially afterwards. VAD loads after the wake model. Every
        load is guarded so one slow/failing load never strands readiness — it
        will lazy-load / fall back on first use.
        """
        deferred_t0 = time.monotonic()

        # TTS client init is network-bound → overlap it with the (CUDA-heavy)
        # wake warm-up rather than adding it on afterwards. Idempotent: a later
        # lazy ``_ensure_client`` on first synth is a harmless no-op.
        async def _init_tts() -> None:
            await asyncio.to_thread(self._tts._ensure_client)

        tts_task = asyncio.create_task(_init_tts(), name="warmup-tts-init")
        try:
            # PRIORITY: pre-warm the WAKE model FIRST and ALONE. For a custom wake
            # phrase (stt_match / rolling-whisper) ``self._stt`` IS the wake model,
            # and until it is in memory + warmed the wake loop cannot transcribe.
            # Prime with one REAL inference (not just the model load): the first
            # transcribe is cold (CUDA kernel JIT / cuDNN algo search), and that
            # cost used to land on the user's first "Hey Jarvis" (swallowed wake,
            # forensic 2026-06-28). ``warm_up`` pays it here; falls back to
            # ``_ensure_model``.
            if self._stt is not None:
                _wake_t0 = time.monotonic()
                try:
                    _prime = getattr(self._stt, "warm_up", None)
                    await asyncio.to_thread(
                        _prime if callable(_prime) else self._stt._ensure_model
                    )
                    _pl.log.info(
                        "Wake-model pre-warm done in %.0f ms (priority, no GIL race).",
                        (time.monotonic() - _wake_t0) * 1000.0,
                    )
                except Exception as exc:  # noqa: BLE001 — lazy load on first use still works
                    _pl.log.warning("Wake-model pre-warm failed (will lazy-load): %s", exc)

            # Join the concurrently-running TTS init (started before the wake warm).
            tts_err: Exception | None = None
            try:
                await tts_task
            except Exception as exc:  # noqa: BLE001 — lazy load on first synth still works
                tts_err = exc
                _pl.log.warning("Warm-up deferred loader 'tts-init' failed: %s", exc)

            _pl.log.info(
                "Warm-up deferred loaders done in %.0f ms (tts-init=%s).",
                (time.monotonic() - deferred_t0) * 1000.0,
                "ok" if tts_err is None else "failed",
            )

            # --- HONEST READINESS: the full stack is up (or attempted) ------
            # Wake model warmed + VAD loaded + TTS client init done → the user
            # can now actually be heard AND get a spoken reply. Signal ready and
            # play the audible cue here, exactly once, at the first truthful
            # moment. Even on a failed VAD/TTS load we still flip ready (each
            # lazy-loads / falls back on first use) rather than stranding the UI
            # in "starting up" forever. The cue is fire-and-forget so a
            # slow/wedged output device never sits between ready=True and a
            # responsive wake loop.
            await self._emit_boot_status(ready=True, detail="listening")
            self._warmup_ready_cue_task = asyncio.create_task(
                self._play_ready_cue(), name="warmup-ready-cue"
            )
            self._warmup_ready_cue_task.add_done_callback(self._log_warmup_ready_cue_done)
            # Hot-swap watcher (BUG-102): starts only AFTER honest readiness —
            # never on the boot critical path (AP-26). Polls the out-of-process
            # device probe and refreshes PortAudio when a headset is plugged
            # in or pulled, so mic and speaker follow the user's devices at
            # runtime on every OS instead of dying on a frozen device table.
            # ``getattr`` default keeps ``__new__``-built test/hot-reload
            # instances (which skip ``__init__``) working.
            if getattr(self, "_audio_topology_task", None) is None:
                from dodaios.audio.topology import watch_topology

                self._audio_topology_task = asyncio.create_task(
                    watch_topology(self._player, self._output_device),
                    name="audio-topology-watch",
                )
                self._audio_topology_task.add_done_callback(
                    self._log_audio_topology_done
                )
            # Warming voice/wake STT above does not warm dictation's separate,
            # prompt-free provider. Start it only AFTER honest readiness so its
            # model load + first CUDA decode can never delay boot (AP-26).
            self._schedule_dictation_warmup()
            # Same for a local utterance engine that is not the wake engine.
            self._ensure_voice_stt_warmup()
        finally:
            # Never orphan the concurrently-started TTS init: if this deferred
            # task is cancelled (desktop shutdown) before the ``await tts_task``
            # join above is reached, CancelledError propagates straight here. Cancel
            # + await it so a late ``_ensure_client`` failure can't surface as an
            # unretrieved-exception warning under pythonw.exe. No-op on the normal
            # path (tts_task already awaited → done). Swallowed; re-raises the
            # original CancelledError after cleanup.
            if not tts_task.done():
                tts_task.cancel()
                try:
                    await tts_task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001, S110
                    # Preserve the original cancellation after owned-task cleanup.
                    pass

    async def _warmup_phase_b(self) -> None:
        """Background pre-render of confirmation audio (never blocks ready).

        Order matters: the wake ACK "Ja?" is rendered first (highest priority —
        it is the immediate wake feedback), then the task-ack phrases are
        rendered concurrently. Fully guarded; any failure degrades to the chime.
        """
        bg_start = time.monotonic()
        await self._prerender_ack_phrase()
        await self._prerender_task_acks()
        bg_ms = (time.monotonic() - bg_start) * 1000.0
        _pl.log.info("Warm-up Phase B (confirmation audio) done in %.0f ms.", bg_ms)

    async def _prerender_ack_phrase(self) -> None:
        """Cache the wake-ACK phrase ("Ja?") PCM, or fall back to the chime."""
        # Skip the ACK pre-render when the phrase is empty (user preference: no
        # spoken wake reaction, chime only). Gemini-TTS would raise an API error
        # on "" anyway.
        if not self._ack_phrase:
            _pl.log.info("ACK phrase disabled — chime only on wake.")
            self._ack_pcm = b""
            return
        try:
            _pl.log.info("Pre-rendering ACK phrase '%s' …", self._ack_phrase)
            chunks: list[AudioChunk] = []
            async for c in self._tts.synthesize(self._ack_phrase):
                chunks.append(c)
            self._ack_pcm = b"".join(c.pcm for c in chunks)
            _pl.log.info("ACK phrase cached (%d KB).", len(self._ack_pcm) // 1024)
        except Exception as exc:  # noqa: BLE001
            _pl.log.warning("ACK pre-render failed (%s) — chime only as feedback.", exc)
            self._ack_pcm = b""

    async def _stabilize_audio_devices(self) -> None:
        """Wait for the audio device enumeration to settle, then re-resolve the
        output device against the now-fresh PortAudio table.

        Permanent cure for the post-reboot device-index drift (BUG-014 class):
        Jarvis can autostart before Windows finishes enumerating audio
        endpoints, freezing a partial table that points the speaker index at a
        stale/silent device. Fully guarded — must never block or break boot.
        """
        try:
            # If the launcher prefetched the (blocking ~1.5 s) device settle in a
            # daemon thread at boot, reuse its already-settled result instead of
            # re-paying the poll wait on the wake-critical path. Falls back to a
            # fresh settle when no prefetch ran / it is still polling — identical
            # to today's behavior, so this can only help, never slow boot.
            from dodaios.audio.device_init import get_prefetched_audio_result

            info = get_prefetched_audio_result()
            if info is None:
                info = await asyncio.to_thread(_pl.wait_for_stable_audio_devices)
            _pl.log.info(
                "Audio-Geräte stabilisiert: %d Geräte (stable=%s, %.1fs, %d reinit).",
                info.get("device_count", 0),
                info.get("stable"),
                info.get("waited_s", 0.0),
                info.get("reinits", 0),
            )
            self._player.set_device(self._output_device)
        except Exception as exc:  # noqa: BLE001 — audio robustness never breaks boot
            _pl.log.warning("Audio-Geräte-Stabilisierung übersprungen (%s).", exc)

    async def _play_ready_cue(self) -> None:
        """Play the ascending boot-ready tone once. Silent no-op on a headless
        VPS / when no output device exists, or when the global "Sound effects"
        switch is off — never raises."""
        await self._play_earcon(_pl.READY_PCM)

    async def _prerender_task_acks(self) -> None:
        phrases = _pl.iter_all_start_ack()
        _pl.log.info("Pre-rendere %d Task-Ack-Phrasen …", len(phrases))

        async def _render_one(lang: str, phrase: str) -> bool:
            """Render + cache one phrase. Returns True on a non-empty cache.

            Each call writes a distinct ``(lang, phrase)`` key into the shared
            dict; the write sits between two awaits, so the cooperative
            event-loop scheduler never preempts it (these are asyncio tasks on
            one loop, not OS threads) — concurrent writes are safe without a
            lock. A single failure degrades to no cache entry → chime fallback,
            never raises.
            """
            try:
                chunks: list[AudioChunk] = []
                try:
                    it = self._tts.synthesize(phrase, language_code=self._bcp47(lang))
                except TypeError:
                    it = self._tts.synthesize(phrase)
                async for c in it:
                    chunks.append(c)
                pcm = b"".join(c.pcm for c in chunks)
                if pcm:
                    self._task_ack_pcm[(lang, phrase)] = pcm
                    return True
            except Exception as exc:  # noqa: BLE001
                _pl.log.warning(
                    "Task-Ack pre-render '%s' (%s) fehlgeschlagen: %s", phrase, lang, exc
                )
            return False

        # Render all phrases concurrently — the dominant warm-up cost was these
        # ~20 sequential TTS round-trips. _render_one never raises, so a plain
        # gather is enough (no return_exceptions needed).
        results = await asyncio.gather(*(_render_one(lang, phrase) for lang, phrase in phrases))
        ok = sum(1 for r in results if r)
        _pl.log.info("Task-Ack-Cache: %d/%d Phrasen bereit.", ok, len(phrases))
