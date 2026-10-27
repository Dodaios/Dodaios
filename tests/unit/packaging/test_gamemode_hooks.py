"""Guards for the GameMode hooks that park Dodaios while a game runs.

GameMode gives each hook ``script_timeout`` seconds (10 on the reference
machine). The start hook used to wait for the full service stop, which can
take up to the unit's TimeoutStopSec (60 s) and held the hook lock the end
hook needs. These tests run the real script with fake ``systemctl`` and
``gamemoded`` binaries first on PATH.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "packaging" / "linux" / "gamemode" / "dodaios-game-control"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("flock") is None,
    reason="the hook script needs bash and flock",
)

_FAKE_SYSTEMCTL = r"""#!/usr/bin/env bash
# Fake `systemctl --user`: records each call, models one service.
echo "$*" >> "$STUB_DIR/calls"
args=("$@")
[[ "${args[0]}" == "--user" ]] && args=("${args[@]:1}")
case "${args[0]}" in
  is-active)
    if [[ "${args[1]}" == "--quiet" ]]; then
      [[ -f "$STUB_DIR/active" ]]; exit $?
    fi
    # Scripted states for successive queries; the last one repeats.
    if [[ -s "$STUB_DIR/states" ]]; then
      state=$(head -n1 "$STUB_DIR/states")
      if [[ $(wc -l < "$STUB_DIR/states") -gt 1 ]]; then
        sed -i '1d' "$STUB_DIR/states"
      fi
    elif [[ -f "$STUB_DIR/active" ]]; then
      state=active
    else
      state=inactive
    fi
    echo "$state"
    [[ "$state" == active ]]; exit $?
    ;;
  stop)
    [[ " ${args[*]} " == *" dodaios.service "* ]] || exit 0
    if [[ -f "$STUB_DIR/active" && " ${args[*]} " != *" --no-block "* ]]; then
      sleep 30  # a real service stop can wait for the whole TimeoutStopSec
    fi
    rm -f "$STUB_DIR/active"
    ;;
  start)
    touch "$STUB_DIR/active"
    ;;
esac
exit 0
"""

_FAKE_GAMEMODED = r"""#!/usr/bin/env bash
cat "$STUB_DIR/gamemode_status" 2>/dev/null
exit "$(cat "$STUB_DIR/gamemode_rc" 2>/dev/null || echo 0)"
"""


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    stub = tmp_path / "stub"
    bin_dir = tmp_path / "bin"
    runtime = tmp_path / "run"
    home = tmp_path / "home"
    for path in (stub, bin_dir, runtime, home):
        path.mkdir()
    for name, body in (("systemctl", _FAKE_SYSTEMCTL), ("gamemoded", _FAKE_GAMEMODED)):
        exe = bin_dir / name
        exe.write_text(body)
        exe.chmod(0o755)
    return {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        "HOME": str(home),
        "XDG_RUNTIME_DIR": str(runtime),
        "DBUS_SESSION_BUS_ADDRESS": "unix:path=/nonexistent",
        "STUB_DIR": str(stub),
    }


def _run(env: dict[str, str], action: str, timeout: float = 20) -> tuple[subprocess.CompletedProcess[str], float]:
    started = time.monotonic()
    result = subprocess.run(
        ["bash", str(SCRIPT), action],
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return result, time.monotonic() - started


def _calls(env: dict[str, str]) -> list[str]:
    path = Path(env["STUB_DIR"]) / "calls"
    return path.read_text().splitlines() if path.exists() else []


def _marker(env: dict[str, str]) -> Path:
    return Path(env["XDG_RUNTIME_DIR"]) / "dodaios-gaming" / "was-active"


def test_start_returns_within_the_gamemode_script_timeout(env: dict[str, str]) -> None:
    (Path(env["STUB_DIR"]) / "active").touch()

    try:
        result, elapsed = _run(env, "start", timeout=8)
    except subprocess.TimeoutExpired:
        pytest.fail("the start hook waited for the whole service stop")

    assert result.returncode == 0, result.stderr
    assert elapsed < 5
    assert "--user stop --no-block dodaios.service" in _calls(env)
    assert _marker(env).exists()


def test_start_leaves_a_stopped_service_alone(env: dict[str, str]) -> None:
    result, _ = _run(env, "start")

    assert result.returncode == 0, result.stderr
    assert not any(" stop " in f" {call} " and "timer" not in call for call in _calls(env))
    assert not _marker(env).exists()


def test_end_arms_the_resume_timer_when_dodaios_was_parked(env: dict[str, str]) -> None:
    _marker(env).parent.mkdir(parents=True)
    _marker(env).touch()

    result, _ = _run(env, "end")

    assert result.returncode == 0, result.stderr
    assert "--user restart dodaios-game-resume.timer" in _calls(env)


def test_resume_waits_for_a_stop_still_in_progress(env: dict[str, str]) -> None:
    stub = Path(env["STUB_DIR"])
    _marker(env).parent.mkdir(parents=True)
    _marker(env).touch()
    (stub / "gamemode_status").write_text("gamemode is inactive\n")
    (stub / "states").write_text("deactivating\ndeactivating\ninactive\n")

    result, _ = _run(env, "resume")

    assert result.returncode == 0, result.stderr
    calls = _calls(env)
    start = calls.index("--user start dodaios.service")
    queries = [i for i, call in enumerate(calls) if call == "--user is-active dodaios.service"]
    assert len(queries) >= 3 and max(queries) < start
    assert not _marker(env).exists()


@pytest.mark.parametrize(
    ("status", "rc"),
    [("gamemode is active\n", "0"), ("", "1")],
    ids=["game-still-running", "gamemoded-unreachable"],
)
def test_resume_never_starts_while_a_game_may_be_running(
    env: dict[str, str], status: str, rc: str
) -> None:
    stub = Path(env["STUB_DIR"])
    _marker(env).parent.mkdir(parents=True)
    _marker(env).touch()
    (stub / "gamemode_status").write_text(status)
    (stub / "gamemode_rc").write_text(rc)

    result, _ = _run(env, "resume")

    assert result.returncode == 0, result.stderr
    assert "--user start dodaios.service" not in _calls(env)
    assert _marker(env).exists()
