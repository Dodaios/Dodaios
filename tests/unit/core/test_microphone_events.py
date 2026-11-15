"""The two events that say the microphone cannot be heard, and that it can again.

The window builds its one notice from them (which input, why, and the button
that helps), so their fields and reasons are a contract with the frontend:
``src/lib/microphoneToast.ts`` mirrors the reasons.
"""

from __future__ import annotations

import re
from dataclasses import fields
from pathlib import Path

from dodaios.core.events import (
    MICROPHONE_TROUBLE_REASONS,
    PERMISSION_FEATURES,
    Event,
    MicrophoneRecovered,
    MicrophoneTrouble,
)
from dodaios.tasks.event_catalog import event_catalog

_TOAST_TS = (
    Path(__file__).resolve().parents[3]
    / "dodaios/ui/web/frontend/src/lib/microphoneToast.ts"
)


def _own_fields(event: type[Event]) -> list[str]:
    shared = {f.name for f in fields(Event)}
    return [f.name for f in fields(event) if f.name not in shared]


def test_the_trouble_event_says_which_input_and_why() -> None:
    assert _own_fields(MicrophoneTrouble) == ["reason", "device", "feature", "automatic"]
    assert MICROPHONE_TROUBLE_REASONS == ("not_answering", "silent")


def test_the_recovery_names_the_same_input() -> None:
    assert _own_fields(MicrophoneRecovered) == ["device"]


def test_the_feature_is_one_the_permission_layer_knows() -> None:
    """The capture passes its ``permission_feature`` on; the two lists must agree."""
    for feature in ("voice", "dictation", "wake_word"):
        assert feature in PERMISSION_FEATURES


def test_both_events_are_in_the_catalog_a_routine_can_react_to() -> None:
    catalog = event_catalog()
    assert catalog["MicrophoneTrouble"][-4:] == ["reason", "device", "feature", "automatic"]
    assert "MicrophoneRecovered" in catalog


def test_the_frontend_mirrors_the_reasons() -> None:
    source = _TOAST_TS.read_text(encoding="utf-8")
    match = re.search(
        r"export const MICROPHONE_TROUBLE_REASONS\s*=\s*\[(.*?)\]\s*as const", source, re.DOTALL
    )
    assert match, "MICROPHONE_TROUBLE_REASONS not found in microphoneToast.ts"
    mirrored = tuple(re.findall(r'"([a-z_]+)"', match.group(1)))
    assert mirrored == MICROPHONE_TROUBLE_REASONS
