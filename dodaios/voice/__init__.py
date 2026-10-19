"""Voice UX layer for the self-mod pipeline (Phase 7.4+).

`dodaios/voice/` is newly introduced in Phase 7.4 — separate from the
`dodaios/speech/` pipeline stack. Rationale: the echo confirmation
is a UX layer that sits between the brain tool output and TTS;
no direct audio IO. Phase 7.6 will add an adapter between
`dodaios.speech.pipeline.SpeechPipeline` and `SelfModFlowController`.
"""
from __future__ import annotations

from .echo_confirmation import (
    classify_response,
    format_confirmation,
    format_outcome,
    is_sensitive_path,
)
from .self_mod_flow import (
    FlowSession,
    FlowState,
    SelfModFlowController,
)

__all__ = [
    "FlowSession",
    "FlowState",
    "SelfModFlowController",
    "classify_response",
    "format_confirmation",
    "format_outcome",
    "is_sensitive_path",
]
