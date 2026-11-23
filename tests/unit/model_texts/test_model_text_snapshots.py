"""Snapshots of every text the lead and delegated agents read.

Text a model reads changes behaviour and cost as much as code does, so a change to
it must be visible in the diff and deliberate. Each text is rendered with a neutral
fixture and compared with ``tests/snapshots/model_texts/<name>.txt``. A text that
grows by more than 10 % against ``summary.json`` fails until the summary is
regenerated on purpose.

Regenerate after a deliberate change::

    python -m pytest tests/unit/model_texts --update-model-texts
"""
from __future__ import annotations

import difflib
import json
import os
import re

import pytest

from tests.unit.model_texts.texts import REPO, TEXTS

SNAP_DIR = REPO / "tests" / "snapshots" / "model_texts"
SUMMARY = SNAP_DIR / "summary.json"
GROWTH_LIMIT = 1.10
REGEN = "python -m pytest tests/unit/model_texts --update-model-texts"

_PERSONAL = (
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    re.compile(r"[A-Za-z]:\\Users\\", re.I),
    re.compile(r"/(?:home|Users)/[A-Za-z0-9_.-]+/"),
)

_RENDERED: dict[str, str] = {}


def _updating(config: pytest.Config) -> bool:
    return bool(config.getoption("--update-model-texts")) or (
        os.environ.get("DODAIOS_UPDATE_MODEL_TEXTS") == "1"
    )


def _normalise(text: str) -> str:
    return text.replace("\r\n", "\n").rstrip("\n") + "\n"


def _render(name: str) -> str:
    if name not in _RENDERED:
        _RENDERED[name] = _normalise(TEXTS[name]())
    return _RENDERED[name]


def _stats(text: str) -> dict[str, int]:
    return {"chars": len(text), "approx_tokens": round(len(text) / 4)}


def _write_summary() -> None:
    data = {name: _stats(_render(name)) for name in sorted(TEXTS)}
    SUMMARY.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


@pytest.mark.parametrize("name", sorted(TEXTS))
def test_text_matches_snapshot(name: str, request: pytest.FixtureRequest) -> None:
    text = _render(name)
    path = SNAP_DIR / f"{name}.txt"
    if _updating(request.config):
        SNAP_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        return
    assert path.exists(), f"no snapshot for {name}; create it with: {REGEN}"
    old = _normalise(path.read_text(encoding="utf-8"))
    if old != text:
        diff = "".join(
            difflib.unified_diff(
                old.splitlines(True), text.splitlines(True), f"snapshot/{name}.txt", f"now/{name}"
            )
        )
        pytest.fail(
            f"The text a model reads changed: {name}\n{diff}\n"
            f"If the change is deliberate, regenerate with:\n    {REGEN}\n"
            "(or set DODAIOS_UPDATE_MODEL_TEXTS=1) and commit the snapshots.",
            pytrace=False,
        )


@pytest.mark.parametrize("name", sorted(TEXTS))
def test_text_holds_no_personal_data(name: str) -> None:
    text = _render(name)
    for pattern in _PERSONAL:
        match = pattern.search(text)
        assert match is None, f"{name} holds personal-looking data: {match.group(0)!r}"


def test_texts_do_not_grow_unnoticed(request: pytest.FixtureRequest) -> None:
    if _updating(request.config):
        _write_summary()
        return
    assert SUMMARY.exists(), f"no summary.json; create it with: {REGEN}"
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    assert set(summary) == set(TEXTS), f"summary.json lists other texts; run: {REGEN}"
    grown = []
    for name, old in summary.items():
        now = len(_render(name))
        if now > old["chars"] * GROWTH_LIMIT:
            grown.append(f"{name}: {old['chars']} -> {now} chars (+{now / old['chars'] - 1:.0%})")
    assert not grown, (
        "A text a model reads grew by more than 10 % since summary.json:\n  "
        + "\n  ".join(grown)
        + f"\nEvery lead turn pays for it. If it is deliberate, run: {REGEN}"
    )


def test_summary_matches_snapshots(request: pytest.FixtureRequest) -> None:
    """summary.json is the record of what each text costs; keep it equal to the snapshots."""
    if _updating(request.config):
        return
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    stale = [
        n
        for n, s in summary.items()
        if s != _stats(_normalise((SNAP_DIR / f"{n}.txt").read_text(encoding="utf-8")))
    ]
    assert not stale, f"summary.json is out of date for {stale}; run: {REGEN}"
