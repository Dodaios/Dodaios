"""The CLI version is read cheaply and read again when the binary changes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dodaios.rsi import harness_probe


@pytest.fixture(autouse=True)
def _fresh_cache():
    harness_probe._cache.clear()
    yield
    harness_probe._cache.clear()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2.1.330 (Claude Code)", "2.1.330"),
        ("codex-cli 0.154.0", "0.154.0"),
        ("v1.4", "1.4"),
        ("version: 3.0.0-beta.2", "3.0.0-beta.2"),
        ("no version here", ""),
        ("", ""),
    ],
)
def test_the_first_version_in_a_line_is_taken(text, expected):
    assert harness_probe.parse_version(text) == expected


@pytest.mark.parametrize(
    ("version", "line"),
    [("2.1.330", "2.1"), ("0.154.0", "0.154"), ("1.4", "1.4"), ("", ""), ("nightly", "")],
)
def test_the_version_line_drops_the_patch(version, line):
    assert harness_probe.version_line(version) == line


def _calls() -> tuple[list[str], object]:
    seen: list[str] = []

    def run(binary: str) -> str:
        seen.append(binary)
        return "9.9.9"

    return seen, run


def test_a_version_named_by_the_install_path_needs_no_process(tmp_path: Path):
    # The native installer keeps each release in a folder entry named after it
    # and points the command at it; the resolved path is what is read.
    real = tmp_path / "versions" / "2.1.330"
    real.parent.mkdir()
    real.write_text("#!/bin/sh\n", encoding="utf-8")
    seen, run = _calls()
    assert harness_probe.version_of(str(real), run=run) == "2.1.330"
    assert seen == []


def test_a_script_takes_the_version_of_its_package(tmp_path: Path):
    package = tmp_path / "node_modules" / "codex"
    (package / "bin").mkdir(parents=True)
    (package / "package.json").write_text(json.dumps({"version": "0.154.0"}), encoding="utf-8")
    script = package / "bin" / "codex.js"
    script.write_text("// cli\n", encoding="utf-8")
    seen, run = _calls()
    assert harness_probe.version_of(str(script), run=run) == "0.154.0"
    assert seen == []


def test_the_binary_is_asked_once_and_again_only_after_it_changed(tmp_path: Path):
    binary = tmp_path / "tool"
    binary.write_text("one\n", encoding="utf-8")
    seen, run = _calls()
    assert harness_probe.version_of(str(binary), run=run) == "9.9.9"
    assert harness_probe.version_of(str(binary), run=run) == "9.9.9"
    assert len(seen) == 1
    # An update replaces the file: another size, so the cached answer no longer applies.
    binary.write_text("two, and longer\n", encoding="utf-8")
    assert harness_probe.version_of(str(binary), run=run) == "9.9.9"
    assert len(seen) == 2


def test_an_unreadable_version_is_not_remembered(tmp_path: Path):
    binary = tmp_path / "tool"
    binary.write_text("x\n", encoding="utf-8")
    answers = iter(["", "1.2.3"])
    assert harness_probe.version_of(str(binary), run=lambda _b: next(answers)) == ""
    assert harness_probe.version_of(str(binary), run=lambda _b: next(answers)) == "1.2.3"


def test_a_missing_binary_has_no_version():
    assert harness_probe.version_of("/nonexistent/cli") == ""


def test_a_runner_without_a_binary_keeps_its_name(tmp_path: Path):
    harness = harness_probe.for_runner("codex-cli", binary_of=lambda _r: "")
    assert harness == harness_probe.Harness(name="codex-cli", version="", line="")


def test_a_runner_reports_name_version_and_line(tmp_path: Path):
    real = tmp_path / "versions" / "2.1.330"
    real.parent.mkdir()
    real.write_text("#!/bin/sh\n", encoding="utf-8")
    harness = harness_probe.for_runner("claude-cli", binary_of=lambda _r: str(real))
    assert harness == harness_probe.Harness(name="claude-cli", version="2.1.330", line="2.1")
