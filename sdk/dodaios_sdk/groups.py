"""The plugin groups: which entry-point group takes which contract."""

from __future__ import annotations

from .brain import Brain
from .channel import ChannelAdapter
from .harness import Harness
from .realtime import RealtimeProvider
from .stt import STTProvider
from .tool import Tool
from .tts import TTSProvider
from .turn import TurnDetector
from .wakeword import WakeWordProvider

#: Slot name -> the Protocol a plugin class of that slot satisfies.
CONTRACTS: dict[str, type] = {
    "stt": STTProvider,
    "tts": TTSProvider,
    "brain": Brain,
    "wakeword": WakeWordProvider,
    "turn": TurnDetector,
    "harness": Harness,
    "channel": ChannelAdapter,
    "realtime": RealtimeProvider,
    "tool": Tool,
}

#: Dodaios reads both namespaces in one scan; new plugins use ``dodaios``.
NAMESPACES: tuple[str, ...] = ("dodaios", "jarvis")


def entry_point_group(slot: str) -> str:
    """The entry-point group a new plugin registers under, e.g. ``dodaios.tts``."""
    if slot not in CONTRACTS:
        raise KeyError(f"unknown plugin slot {slot!r}; known: {sorted(CONTRACTS)}")
    return f"dodaios.{slot}"


def check_plugin(slot: str, plugin_cls: type, **kwargs: object) -> object:
    """Build ``plugin_cls`` the way the host does and check it against its contract.

    Returns the instance. Raises ``TypeError`` when it does not satisfy the
    Protocol of ``slot``. Use it in a plugin's own tests.
    """
    instance = plugin_cls(**kwargs)
    if not isinstance(instance, CONTRACTS[slot]):
        raise TypeError(f"{plugin_cls.__name__} does not satisfy the {slot!r} contract")
    return instance


__all__ = ["CONTRACTS", "NAMESPACES", "check_plugin", "entry_point_group"]
