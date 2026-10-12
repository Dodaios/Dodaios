"""Why a click-started voice conversation was refused.

One vocabulary for ``SpeechPipeline.start_voice_session``, the
``POST /api/voice/call`` answer and the sentence the voice controls show. The
empty string means "armed"; every other value names the one thing that stopped
the start, so the person is told that reason and never a guess.

Mirrored by ``VOICE_START_REFUSALS`` in
``jarvis/ui/web/frontend/src/lib/voiceStartRefusal.ts`` (parity:
``tests/unit/speech/test_voice_start_refusal_parity.py``).
"""

from __future__ import annotations

#: A voice session is already open, or push-to-talk is recording.
BUSY = "busy"
#: Voice is muted.
MUTED = "muted"
#: A dictation holds the microphone.
DICTATION = "dictation"
#: A browser-held call owns the microphone.
MICROPHONE_IN_USE = "microphone_in_use"
#: The operating system has not granted the microphone.
MICROPHONE = "microphone"
#: The pipeline could not take the request (its event loop is gone).
UNAVAILABLE = "unavailable"

VOICE_START_REFUSALS: tuple[str, ...] = (
    BUSY,
    MUTED,
    DICTATION,
    MICROPHONE_IN_USE,
    MICROPHONE,
    UNAVAILABLE,
)
