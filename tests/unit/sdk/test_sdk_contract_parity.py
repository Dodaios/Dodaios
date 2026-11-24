"""The SDK contracts and the in-app contracts must stay structurally identical.

``sdk/dodaios_sdk`` is a standalone copy (the app is not wired onto it, see
sdk/README.md); this test is what keeps the two from drifting.
"""

from __future__ import annotations

import dataclasses
import inspect
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "sdk"))

import dodaios_sdk  # noqa: E402

from dodaios.channels import base as app_channels  # noqa: E402
from dodaios.core import protocols as app_protocols  # noqa: E402
from dodaios.realtime import protocol as app_realtime  # noqa: E402

_DATACLASSES = [
    "AudioChunk",
    "Transcript",
    "ImageBlock",
    "BrainMessage",
    "BrainRequest",
    "BrainDelta",
    "HarnessTask",
    "HarnessResult",
    "ExecutionContext",
    "ToolResult",
    "ChannelMedia",
    "ChannelMessage",
    "ChannelSession",
    "RealtimeEvent",
    "RealtimeSessionConfig",
]
_PROTOCOLS = [
    "STTProvider",
    "TTSProvider",
    "Brain",
    "WakeWordProvider",
    "TurnDetector",
    "Harness",
    "Tool",
    "ChannelAdapter",
    "RealtimeProvider",
    "RealtimeSession",
]


def _app(name: str) -> Any:
    for module in (app_protocols, app_channels, app_realtime):
        if hasattr(module, name):
            return getattr(module, name)
    raise AssertionError(name)


def _default(f: dataclasses.Field[Any]) -> Any:
    if f.default is not dataclasses.MISSING:
        return f.default
    if f.default_factory is not dataclasses.MISSING:
        return f.default_factory()  # type: ignore[misc]
    return dataclasses.MISSING


@pytest.mark.parametrize("name", _DATACLASSES)
def test_dataclass_fields_match(name: str) -> None:
    sdk_cls, app_cls = getattr(dodaios_sdk, name), _app(name)
    sdk_fields, app_fields = dataclasses.fields(sdk_cls), dataclasses.fields(app_cls)
    assert [f.name for f in sdk_fields] == [f.name for f in app_fields]
    for a, b in zip(sdk_fields, app_fields, strict=True):
        assert str(a.type) == str(b.type), f"{name}.{a.name} type"
        if a.name not in {"trace_id", "timestamp_ns", "connected_at_ns"}:  # generated values
            assert _default(a) == _default(b), f"{name}.{a.name} default"


def _members(cls: type) -> dict[str, Any]:
    return {
        n: v
        for n, v in vars(cls).items()
        if not n.startswith("_") and (inspect.isfunction(v) or isinstance(v, property))
    }


@pytest.mark.parametrize("name", _PROTOCOLS)
def test_protocol_shape_matches(name: str) -> None:
    sdk_cls, app_cls = getattr(dodaios_sdk, name), _app(name)
    assert set(getattr(sdk_cls, "__annotations__", {})) == set(
        getattr(app_cls, "__annotations__", {})
    )
    sdk_members, app_members = _members(sdk_cls), _members(app_cls)
    assert set(sdk_members) == set(app_members)
    for member, fn in sdk_members.items():
        if isinstance(fn, property):
            continue
        a = inspect.signature(fn)
        b = inspect.signature(app_members[member])
        assert [(p.name, p.kind, p.default) for p in a.parameters.values()] == [
            (p.name, p.kind, p.default) for p in b.parameters.values()
        ], f"{name}.{member} parameters"
        assert inspect.iscoroutinefunction(fn) == inspect.iscoroutinefunction(
            app_members[member]
        ), f"{name}.{member} async-ness"


def test_literals_match() -> None:
    assert dodaios_sdk.RiskTier == app_protocols.RiskTier
    assert dodaios_sdk.ReasoningEffort == app_protocols.ReasoningEffort
    assert (
        app_realtime.RealtimeEventType
        == __import__("dodaios_sdk.realtime", fromlist=["x"]).RealtimeEventType
    )


def test_groups_cover_every_app_slot() -> None:
    slots = {g.split(".", 1)[1] for g in app_protocols.PLUGIN_GROUPS} | {"turn"}
    assert slots == set(dodaios_sdk.CONTRACTS)
