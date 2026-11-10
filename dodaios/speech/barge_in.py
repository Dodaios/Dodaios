"""One barge-in policy for every voice path (issue #153).

Barge-in — the assistant falls silent the moment the person starts talking —
already exists twice: the classic STT→brain→TTS path listens on a second
microphone stream while TTS plays (``SpeechPipeline._barge_monitor``) and the
desktop realtime path inspects the frames the half-duplex session would drop
(``_active_realtime_session``). Both run the same local detector
(``dodaios.realtime.desktop.DesktopRealtimeBargeInDetector``), but each path
carried its own copy of the detector's tuning, so a change to how eagerly the
assistant yields the floor had to be made in two places and could drift.

This module is that tuning, read once from ``[voice] barge_in``:

* ``normal`` (default): the proven conservative policy — 1.5 s grace after
  output starts (the detector calibrates its echo floor on those frames, so
  the assistant's own voice on open speakers is never mistaken for the
  person; BUG-084), Silero 0.97 over 12 consecutive frames (~380 ms).
* ``fast``: the assistant yields sooner — 0.8 s grace and 8 frames
  (~250 ms) at 0.95. The echo floor, the RMS pre-gate and the echo
  correlation check stay on, so this is still not a bare VAD.
* ``off``: the assistant finishes what it is saying. The detectors are still
  built (the realtime path uses one for its echo accounting) but can never
  confirm a barge.

Nothing here touches audio; it only hands the detector its numbers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

PROFILE_NORMAL: Final[str] = "normal"
PROFILE_FAST: Final[str] = "fast"
PROFILE_OFF: Final[str] = "off"
PROFILES: Final[tuple[str, ...]] = (PROFILE_NORMAL, PROFILE_FAST, PROFILE_OFF)

#: A confirmation count no real call reaches: the detector never fires.
_NEVER_FRAMES: Final[int] = 1_000_000_000


@dataclass(frozen=True, slots=True)
class BargeInProfile:
    """The detector tuning one profile stands for."""

    name: str
    grace_s: float
    speech_threshold: float
    consecutive_frames: int

    @property
    def enabled(self) -> bool:
        return self.name != PROFILE_OFF

    def detector_kwargs(self, *, grace_s: float | None = None) -> dict[str, Any]:
        """Keyword arguments for ``DesktopRealtimeBargeInDetector``.

        ``grace_s`` lets a caller keep a grace of its own (the realtime
        thinking-phase detector uses a token grace because nothing plays).
        """
        if not self.enabled:
            return {
                "grace_s": self.grace_s if grace_s is None else grace_s,
                "speech_threshold": 1.0,
                "consecutive_frames": _NEVER_FRAMES,
            }
        return {
            "grace_s": self.grace_s if grace_s is None else grace_s,
            "speech_threshold": self.speech_threshold,
            "consecutive_frames": self.consecutive_frames,
        }


_PROFILES: Final[dict[str, BargeInProfile]] = {
    PROFILE_NORMAL: BargeInProfile(PROFILE_NORMAL, 1.5, 0.97, 12),
    PROFILE_FAST: BargeInProfile(PROFILE_FAST, 0.8, 0.95, 8),
    PROFILE_OFF: BargeInProfile(PROFILE_OFF, 1.5, 1.0, _NEVER_FRAMES),
}


def profile_named(name: object) -> BargeInProfile:
    """The profile called ``name``; anything unknown is ``normal``."""
    key = str(name or "").strip().lower()
    return _PROFILES.get(key, _PROFILES[PROFILE_NORMAL])


def profile_for(config: Any) -> BargeInProfile:
    """The profile ``[voice] barge_in`` selects (``normal`` when unset).

    ``VoiceConfig`` keeps unknown keys (``extra="allow"``), so the setting
    needs no schema change and an older config simply has none.
    """
    voice = getattr(config, "voice", None)
    return profile_named(getattr(voice, "barge_in", None))


__all__ = [
    "PROFILES",
    "PROFILE_FAST",
    "PROFILE_NORMAL",
    "PROFILE_OFF",
    "BargeInProfile",
    "profile_for",
    "profile_named",
]
