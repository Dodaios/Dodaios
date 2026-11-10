"""REST API for the voice orb — start or end a conversation without speaking.

Endpoints (mounted by the WebServer in ``_build_app()``):

    GET  /api/voice/state   → is a speech pipeline running, what it is doing,
                              and whether the browser should hold the call.
    POST /api/voice/call    → arm a wake-style voice session (the click-shaped
                              wake word — same path as the call hotkey).
    POST /api/voice/hangup  → hard-stop the voice channel (same contract as the
                              hangup hotkey).
    POST /api/voice/warm    → warm the next call's cold parts (imports, the
                              provider transport, TTS/STT clients) while the
                              pointer is still on its way to the button.
    GET  /api/voice/voices  → the voices the CURRENT voice path can speak with
                              (realtime provider or classic TTS) and the one
                              in use; PUT picks one.

The click path is deliberately the SAME one the call hotkey and the chats
"Speak in this conversation" button take — ``SpeechPipeline.request_voice_session``
— so a click on the orb can never behave differently from the wake word beyond
skipping the audio trigger. Under the CLI-first contract these routes also make
the orb's actions scriptable as ``jarvis api voice <op>``.

No Brain dependency; on a headless install (no microphone, voice disabled) the
state endpoint answers honestly and the actions 503 instead of 500-ing.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/voice", tags=["voice"])


class BrowserStartupFailure(BaseModel):
    """A bounded correlation token; no microphone data or failure text."""

    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(
        min_length=36, max_length=36,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    )


@router.post("/startup-failed")
async def voice_startup_failed(body: BrowserStartupFailure) -> dict[str, bool]:
    """Release a pending wake request when browser audio could not start."""
    from dodaios.live.runtime import browser_startup_failed

    return {"acknowledged": browser_startup_failed(body.request_id)}


def _pipeline() -> Any:
    """The live SpeechPipeline, or ``None`` (headless / voice disabled)."""
    try:
        from dodaios.core.runtime_refs import get_speech_pipeline

        return get_speech_pipeline()
    except Exception:  # noqa: BLE001 — a missing runtime ref is "no pipeline"
        return None


def _browser_call(request: Request, pipeline: Any) -> bool:
    """Whether the browser that presses Start should hold the call itself.

    True only on a host that will never run a speech pipeline of its own — no
    pipeline AND no desktop shell (a desktop app that is still booting has no
    pipeline yet, and a browser-held call there would be a second microphone
    owner) — and whose ``/ws/audio`` would accept the call. Without a config
    attached to the app the answer is False: it cannot be read, so it is not
    offered.
    """
    if pipeline is not None:
        return False
    state = request.app.state
    if bool(getattr(state, "native_file_actions", False)):
        return False
    cfg = getattr(state, "config", None) or getattr(state, "cfg", None)
    if cfg is None:
        return False
    from dodaios.browser_voice.route import browser_voice_enabled

    return browser_voice_enabled(cfg)


@router.get("/state")
async def voice_state(request: Request) -> dict[str, Any]:
    """Whether voice is available here, and what the pipeline is doing now.

    ``voice_state`` is the fine-grained state every voice surface renders
    (idle / connecting / listening / thinking / speaking / paused / error) —
    the same value ``SystemStateChanged`` carries, read straight from the
    supervisor. It exists because that event is a one-shot signal: a client
    that mounts, reconnects or survives a backend restart after the last
    transition never sees it and keeps whatever it heard last. A window that
    was showing LISTENING when the socket dropped went on claiming the user
    was being heard for the rest of its life (field report 2026-08-25). This
    is the REST mirror those surfaces reconcile against.

    Clamped to ``idle`` whenever the pipeline is not ACTIVE: a fine-grained
    state without a running session is unearned detail, never the truth. A
    running session whose supervisor cannot be read answers ``unknown`` rather
    than a guess — the caller leaves a live call alone on anything but ``idle``.

    ``browser_call`` tells a browser on a host without a speech pipeline (a
    VPS, ``jarvis serve``) to hold the call itself over ``/ws/audio`` instead
    of asking this host to arm a microphone it does not have (issue #399).
    """
    from dodaios.live.runtime import active

    pipeline = _pipeline()
    browser_call = _browser_call(request, pipeline)
    sessions = active()
    if sessions:
        phase = getattr(sessions[0], "phase", "listening")
        if phase not in {"speaking", "thinking", "listening"}:
            phase = "speaking" if sessions[0].playback_active else "listening"
        return {
            "available": True,
            "state": "active",
            "voice_state": phase,
            "browser_call": browser_call,
        }
    if pipeline is None:
        return {
            "available": False,
            "state": "unavailable",
            "voice_state": "idle",
            "browser_call": browser_call,
        }
    state = str(getattr(getattr(pipeline, "_state", None), "name", "unknown")).lower()
    supervisor = getattr(pipeline, "_supervisor", None)
    supervisor_state = str(getattr(supervisor, "state", "") or "").lower() or "unknown"
    return {
        "available": True,
        "state": state,
        "voice_state": supervisor_state if state == "active" else "idle",
        "browser_call": browser_call,
    }


@router.post("/call")
async def voice_call() -> dict[str, Any]:
    """Start a voice conversation — functionally the wake word, by click.

    ``armed`` is ``False`` when the pipeline refused — that is an answer, not
    an error — and ``reason`` then names why, from
    ``dodaios.speech.start_refusal``, so the control can say what actually
    stopped the start. ``reason`` is ``""`` when the call was armed.
    """
    pipeline = _pipeline()
    if pipeline is None or not hasattr(pipeline, "start_voice_session"):
        raise HTTPException(status_code=503, detail="voice-pipeline-unavailable")
    reason = str(pipeline.start_voice_session() or "")
    return {"armed": not reason, "reason": reason}


@router.get("/mic-mute")
def voice_mic_mute() -> dict[str, Any]:
    """Whether the microphone is muted for the assistant (the call stays open)."""
    pipeline = _pipeline()
    if pipeline is None or not hasattr(pipeline, "is_muted"):
        raise HTTPException(status_code=503, detail="voice-pipeline-unavailable")
    return {"muted": bool(pipeline.is_muted)}


@router.post("/mic-mute")
async def voice_mic_mute_toggle() -> dict[str, Any]:
    """Mute or unmute the microphone for the assistant; returns the new state.

    Input only: the assistant finishes what it is saying and the call stays
    open. Same flip as the bar's mic button (``VoiceMuteToggleRequested``).
    """
    pipeline = _pipeline()
    if pipeline is None or not hasattr(pipeline, "toggle_mute"):
        raise HTTPException(status_code=503, detail="voice-pipeline-unavailable")
    return {"muted": bool(await pipeline.toggle_mute("call_card"))}


@router.post("/hangup")
async def voice_hangup() -> dict[str, Any]:
    """End the running voice conversation — the hangup key's contract."""
    from dodaios.live.runtime import active, close_all

    if active():
        await close_all()
        return {"stopped": True}
    pipeline = _pipeline()
    if pipeline is None or not hasattr(pipeline, "request_voice_hangup"):
        raise HTTPException(status_code=503, detail="voice-pipeline-unavailable")
    return {"stopped": bool(pipeline.request_voice_hangup())}


def _config(request: Request) -> Any:
    state = request.app.state
    return getattr(state, "config", None) or getattr(state, "cfg", None)


@router.post("/warm")
async def voice_warm(request: Request) -> dict[str, bool]:
    """Warm what the next call needs; answers at once (issue #154).

    The composer calls this when the pointer reaches the call button. The
    work runs in the background and is debounced, so a hovering pointer
    cannot start it twice. Nothing here bills a provider.
    """
    from dodaios.speech.call_warmup import call_warmer

    started = await call_warmer().kick(_pipeline(), _config(request))
    return {"warming": started}


# ── Voice choice ──────────────────────────────────────────────────────────────


class VoiceChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    voice: str = Field(min_length=1, max_length=200)


def _voice_path(cfg: Any, pipeline: Any) -> tuple[str, str]:
    """``(path, provider)``: which engine speaks the next (or running) call.

    ``path`` is ``"live"`` (a Live-surface provider), ``"realtime"`` (another
    realtime provider) or ``"tts"`` (the classic pipeline). A running session
    wins over configuration; without one the configured mode decides.
    """
    mode = ""
    provider = ""
    status_fn = getattr(pipeline, "voice_engine_status", None)
    if callable(status_fn):
        try:
            status = status_fn() or {}
        except Exception:  # noqa: BLE001 — a status that cannot be read is "not active"
            status = {}
        if status.get("session_active"):
            mode = str(status.get("active_session_mode") or "")
            provider = str(status.get("active_session_provider") or "")
        if not mode:
            mode = str(status.get("configured_mode") or "")
    if not mode:
        mode = str(getattr(getattr(cfg, "voice", None), "mode", "") or "pipeline")
    if mode != "realtime":
        return "tts", ""
    if not provider:
        realtime = getattr(getattr(cfg, "brain", None), "realtime", None)
        provider = str(getattr(realtime, "provider", "") or "").strip()
    if not provider:
        return "tts", ""
    from dodaios.ui.web.provider_spec import get_spec

    spec = get_spec(provider)
    if spec is not None and getattr(spec, "configuration_surface", "") == "live":
        return "live", provider
    return "realtime", provider


def _live_voices(cfg: Any) -> tuple[list[dict[str, str]], str]:
    from dodaios.plugins.realtime.openai_subscription_live import SUBSCRIPTION_VOICES
    from dodaios.ui.web.live_routes import LIVE_API_VOICES, _profile_for_runtime

    profile = _profile_for_runtime(cfg)
    if profile.auth_mode == "chatgpt_subscription":
        names: tuple[str, ...] = tuple(SUBSCRIPTION_VOICES)
        current = str(profile.subscription_voice or "")
    else:
        names = LIVE_API_VOICES
        current = str(profile.voice or "")
    return [{"id": name, "label": name.capitalize()} for name in names], current


@router.get("/voices")
def voice_voices(request: Request) -> dict[str, Any]:
    """The voices the current voice path offers, and the one in use.

    One list for the call window's picker, whatever speaks: a Live-surface
    provider (its profile voice), another realtime provider (its curated
    catalog) or the classic TTS provider (its curated or per-model voices).
    ``applies`` says whether a pick reaches a running call (``"now"``) or the
    next one (``"next_call"``). An engine without a choice answers an empty
    list; that is an answer, not an error.
    """
    cfg = _config(request)
    pipeline = _pipeline()
    path, provider = _voice_path(cfg, pipeline)
    if path == "live":
        voices, current = _live_voices(cfg)
        return {
            "path": path, "provider": provider, "voices": voices,
            "current": current, "default": "", "applies": "next_call",
        }
    if path == "realtime":
        from dodaios.brain.model_catalog import REALTIME_VOICES
        from dodaios.ui.web.provider_routes import _current_realtime_selection

        _model, current = _current_realtime_selection(cfg, provider)
        voices = [
            {"id": v.id, "label": v.label} for v in REALTIME_VOICES.get(provider, [])
        ]
        return {
            "path": path, "provider": provider, "voices": voices,
            "current": current, "default": "", "applies": "now",
        }
    from dodaios.ui.web.provider_routes import _active_tts, _tts_voice_entries

    tts_provider = str(_active_tts(request) or "")
    if not tts_provider:
        return {
            "path": path, "provider": "", "voices": [],
            "current": "", "default": "", "applies": "now",
        }
    try:
        entries, _model, default = _tts_voice_entries(tts_provider, "")
    except HTTPException:
        # A provider without a curated voice list has no choice to offer.
        entries, default = [], ""
    persisted = str(getattr(getattr(cfg, "tts", None), "voice_de", "") or "")
    ids = {str(e["id"]) for e in entries}
    return {
        "path": path,
        "provider": tts_provider,
        "voices": [{"id": str(e["id"]), "label": str(e["id"])} for e in entries],
        "current": persisted if persisted in ids else "",
        "default": default,
        "applies": "now",
    }


@router.put("/voices")
async def voice_voices_set(body: VoiceChoice, request: Request) -> dict[str, Any]:
    """Pick a voice for the current voice path; persists and applies.

    Delegates to the one writer each path already has, so the call window
    and the settings pages can never disagree about where a voice lives.
    """
    cfg = _config(request)
    path, provider = _voice_path(cfg, _pipeline())
    voice = body.voice.strip()
    if path == "live":
        from dodaios.ui.web.live_routes import _profile_for_runtime, save_live_profile

        profile = _profile_for_runtime(cfg)
        field = "subscription_voice" if profile.auth_mode == "chatgpt_subscription" else "voice"
        voices, _current = _live_voices(cfg)
        if voice not in {v["id"] for v in voices}:
            raise HTTPException(status_code=422, detail="unknown-voice")
        await save_live_profile(profile.model_copy(update={field: voice}), request)
        return {
            "ok": True, "path": path, "provider": provider,
            "voice": voice, "applies": "next_call",
        }
    if path == "realtime":
        from dodaios.ui.web.provider_routes import RealtimeOptionsBody, set_realtime_options

        await set_realtime_options(provider, RealtimeOptionsBody(voice=voice), request)
        return {"ok": True, "path": path, "provider": provider, "voice": voice, "applies": "now"}
    from dodaios.ui.web.provider_routes import TtsVoiceBody, _active_tts, set_tts_voice_selection

    await set_tts_voice_selection(TtsVoiceBody(voice=voice), request)
    return {
        "ok": True, "path": path, "provider": str(_active_tts(request) or ""),
        "voice": voice, "applies": "now",
    }
