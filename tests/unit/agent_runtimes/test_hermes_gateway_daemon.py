"""Hermes builds after 0.21 run ACP sessions in a per-profile gateway daemon.

``hermes acp`` starts that daemon detached and it keeps the environment it
was started with. A profile the data root's multiplexer serves reads its
credentials from files only, so the gateway token (process environment
only) never reached the model call: every turn answered "custom rejected your
API key". Each agent profile is standalone, gets a daemon started from its
own launch, and a daemon started for another launch is stopped first.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest

from dodaios.agent_runtimes import base, hermes
from dodaios.agent_runtimes.base import RuntimeTurn
from dodaios.agent_runtimes.model_map import ModelRoute

_GATEWAY = "http://127.0.0.1:47821/api/runtime-gateway/v1"
# Fake gateway tokens for assertions.
_FIRST, _SECOND, _SECRET = "jrg_" + "one", "jrg_" + "two", "jrg_" + "secret"


@pytest.fixture
def roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(base, "runtimes_root", lambda: tmp_path / "agent_runtimes")
    monkeypatch.setattr(base, "legacy_runtimes_root", lambda: tmp_path / "legacy_runtimes")
    return tmp_path


@pytest.fixture
def stopped(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    calls: list[Path] = []
    monkeypatch.setattr(hermes, "_stop_profile_gateway", lambda home: calls.append(home) or False)
    return calls


def _turn(workspace: Path, *, agent: str = "hermit", grant: str = _FIRST) -> RuntimeTurn:
    return RuntimeTurn(
        agent_id=agent,
        agent_name="Hermit",
        session_id=f"society:{agent}",
        workspace=workspace,
        route=ModelRoute("ollama", "qwen3", _GATEWAY, "chat_completions", grant),
        resume=None,
        auto_approve=True,
    )


def _launch(runtime: hermes.HermesRuntime, turn: RuntimeTurn):
    return asyncio.run(runtime._launch("hermes", turn, lambda: None))


def test_every_agent_profile_runs_its_own_gateway_daemon(roots):
    config = hermes.HermesRuntime().config_for(_turn(roots))
    assert config["gateway"]["standalone"] is True


def test_the_daemons_host_record_stays_in_dodaios_root(roots, stopped):
    launch = _launch(hermes.HermesRuntime(), _turn(roots))
    lock_dir = Path(launch.env["HERMES_GATEWAY_LOCK_DIR"])
    assert lock_dir == hermes.hermes_root() / "gateway-locks"
    assert lock_dir.is_dir()


def test_the_key_reaches_the_daemon_through_the_launch_environment_only(roots, stopped):
    launch = _launch(hermes.HermesRuntime(), _turn(roots, grant=_SECRET))
    assert launch.env["JARVIS_RUNTIME_API_KEY"] == _SECRET
    home = Path(launch.env["HERMES_HOME"])
    assert _SECRET not in (home / "config.yaml").read_text(encoding="utf-8")


def test_a_daemon_left_by_another_launch_is_stopped_before_the_turn(roots, stopped):
    runtime = hermes.HermesRuntime()
    first = _launch(runtime, _turn(roots))
    home = Path(first.env["HERMES_HOME"])
    # First launch of this app run: a daemon an earlier run left goes.
    assert stopped == [home]
    # The same launch again (the warm process is reused): the daemon stays.
    _launch(runtime, _turn(roots))
    assert stopped == [home]
    # A new token (revoked grant, app restart) or URL: the old daemon goes.
    _launch(runtime, _turn(roots, grant=_SECOND))
    assert stopped == [home, home]


def test_stopping_an_agent_stops_only_its_daemons(roots, stopped):
    runtime = hermes.HermesRuntime()
    ada = Path(_launch(runtime, _turn(roots, agent="ada")).env["HERMES_HOME"])
    bob = Path(_launch(runtime, _turn(roots, agent="bob")).env["HERMES_HOME"])
    stopped.clear()
    asyncio.run(runtime.stop("ada"))
    assert stopped == [ada]
    asyncio.run(runtime.stop())
    assert stopped == [ada, bob]
    asyncio.run(runtime.stop())  # nothing left to stop
    assert stopped == [ada, bob]


def _sleeper(*argv: str) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", *argv])


def test_the_recorded_hermes_gateway_process_is_stopped(tmp_path):
    proc = _sleeper("hermes_cli.main", "gateway", "run", "--idle-exit")
    try:
        record = {"pid": proc.pid, "kind": "hermes-gateway"}
        (tmp_path / "gateway.pid").write_text(json.dumps(record))
        assert hermes._stop_profile_gateway(tmp_path) is True
        assert proc.wait(timeout=10) is not None
    finally:
        proc.kill()


def test_a_reused_pid_is_never_stopped(tmp_path):
    proc = _sleeper("something", "else")
    try:
        (tmp_path / "gateway.pid").write_text(json.dumps({"pid": proc.pid}))
        assert hermes._stop_profile_gateway(tmp_path) is False
        assert proc.poll() is None
    finally:
        proc.kill()
        proc.wait(timeout=10)


@pytest.mark.parametrize("content", [None, "", "not json", '{"kind": "x"}', '{"pid": "x"}'])
def test_no_or_a_broken_record_stops_nothing(tmp_path, content):
    if content is not None:
        (tmp_path / "gateway.pid").write_text(content)
    assert hermes._stop_profile_gateway(tmp_path) is False
