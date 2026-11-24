"""dodaios_sdk: the contracts a Dodaios plugin implements.

Standard library only. One module per plugin group; see ``groups.CONTRACTS``.
"""

from __future__ import annotations

from .brain import Brain, BrainDelta, BrainMessage, BrainRequest, ImageBlock, ReasoningEffort
from .channel import ChannelAdapter, ChannelMedia, ChannelMessage, ChannelSession
from .common import AudioChunk, RiskTier
from .groups import CONTRACTS, NAMESPACES, check_plugin, entry_point_group
from .harness import Harness, HarnessResult, HarnessTask
from .realtime import (
    RealtimeEvent,
    RealtimeProvider,
    RealtimeSession,
    RealtimeSessionConfig,
    RealtimeUnavailableError,
)
from .stt import STTProvider, Transcript
from .tool import ExecutionContext, Tool, ToolResult
from .tts import TTSProvider
from .turn import TurnDetector
from .wakeword import WakeWordProvider

__version__ = "0.1.0"

__all__ = [
    "CONTRACTS",
    "NAMESPACES",
    "AudioChunk",
    "Brain",
    "BrainDelta",
    "BrainMessage",
    "BrainRequest",
    "ChannelAdapter",
    "ChannelMedia",
    "ChannelMessage",
    "ChannelSession",
    "ExecutionContext",
    "Harness",
    "HarnessResult",
    "HarnessTask",
    "ImageBlock",
    "RealtimeEvent",
    "RealtimeProvider",
    "RealtimeSession",
    "RealtimeSessionConfig",
    "RealtimeUnavailableError",
    "ReasoningEffort",
    "RiskTier",
    "STTProvider",
    "TTSProvider",
    "Tool",
    "ToolResult",
    "Transcript",
    "TurnDetector",
    "WakeWordProvider",
    "__version__",
    "check_plugin",
    "entry_point_group",
]
