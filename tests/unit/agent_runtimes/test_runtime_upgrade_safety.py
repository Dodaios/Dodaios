"""Runtime upgrades, start-up readiness and launcher resolution stay safe.

* An OpenClaw update that leaves the agent's database on an older schema gets
  OpenClaw's own migration (``openclaw doctor --fix``) with the Gateway
  stopped, then a restart; a migration that does not help is a readable
  error, never a Gateway that refuses every message.
* A Gateway that answers ``/healthz`` but has not finished its start-up
  inspection is waited for; a message it still refuses is sent again.
* Hermes is never started from a temporary folder on PATH.

Fakes only (``tests/fakes/fake_openclaw.py``, ``fake_acp_agent.py``): no
real runtime, no model call, nothing billed.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

import pytest

from dodaios.agent_chat import runner_cli as rc
from dodaios.agent_runtimes import base, hermes, openclaw
from dodaios.agent_runtimes.base import RuntimeTurn, RuntimeUnavailable, not_ready_kind
from dodaios.agent_runtimes.model_map import ModelRoute

from .test_acp_runner import _finished, _texts, _turn

_FAKE = Path(__file__).resolve().parents[2] / "fakes" / "fake_openclaw.py"
_LAUNCHER = [sys.executable, str(_FAKE)]
_BUILD = "OpenClaw 2026.10.8 (fake)"


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(base, "runtimes_root", lambda: tmp_path / "rt")
    monkeypatch.setattr(openclaw.OpenClawRuntime, "_installed_build", lambda self: _BUILD)
    folder = tmp_path / "rt" / "openclaw" / "hermit"
    folder.mkdir(parents=True)
    return folder


def _turn_for(workspace: Path) -> RuntimeTurn:
    return RuntimeTurn(
        agent_id="hermit",
        agent_name="Hermit",
        session_id="society:hermit",
        workspace=workspace,
        route=ModelRoute("ollama", "qwen3", "http://127.0.0.1:11434/v1", "chat_completions", None),
        resume=None,
        auto_approve=True,
    )


def _env(**extra: str) -> dict[str, str]:
    env = dict(os.environ)
    env.update(extra)
    return env


async def _start(runtime: openclaw.OpenClawRuntime, home: Path, env: dict[str, str]):
    return await runtime._start_gateway(
        _turn_for(home.parent), "hermit", home, openclaw._free_port(), "tok", "h", _LAUNCHER, env
    )


def _calls(home: Path) -> list[str]:
    path = home / "calls.log"
    return path.read_text(encoding="utf-8").splitlines() if path.is_file() else []


def _with_agent_db(home: Path) -> None:
    db = home / "state" / "agents" / "main" / "agent" / "openclaw-agent.sqlite"
    db.parent.mkdir(parents=True)
    db.write_bytes(b"")


# ------------------------------------------------- (a) data migration


def test_a_stale_agent_database_is_migrated_and_the_gateway_restarted(home):
    async def run() -> None:
        runtime = openclaw.OpenClawRuntime()
        gateway = await _start(runtime, home, _env(FAKE_OPENCLAW_MODE="schema-stale"))
        try:
            assert gateway.alive() and await openclaw._healthy(gateway.port)
            assert (home / "doctor.runs").read_text(encoding="utf-8") == "1"
            # Stopped, migrated, started again: in that order.
            calls = [line.split()[0] for line in _calls(home)]
            assert calls == ["gateway", "doctor", "gateway"]
            log = (home / "gateway.log").read_text(encoding="utf-8")
            assert "degraded" not in log and "recovered" in log
            assert "migrated" in (home / "doctor.log").read_text(encoding="utf-8")
            assert (home / "runtime-build.txt").read_text(encoding="utf-8").strip() == _BUILD
        finally:
            await runtime._stop_gateway(gateway)

    asyncio.run(run())


def test_a_migration_that_does_not_help_is_a_readable_error_without_a_gateway(home):
    async def run() -> None:
        runtime = openclaw.OpenClawRuntime()
        with pytest.raises(RuntimeUnavailable) as caught:
            await _start(runtime, home, _env(FAKE_OPENCLAW_MODE="schema-broken"))
        message = str(caught.value)
        assert "openclaw doctor --fix" in message
        assert "schema version 24" in message
        assert "not sent" in message
        # Exactly one repair attempt, and no Gateway left running.
        assert (home / "doctor.runs").read_text(encoding="utf-8") == "1"
        assert not (home / "gateway.pid").exists()
        assert runtime._gateways == {}
        assert "read-only" in (home / "doctor.log").read_text(encoding="utf-8")

    asyncio.run(run())


def test_a_version_change_migrates_before_the_gateway_starts(home):
    _with_agent_db(home)
    (home / "runtime-build.txt").write_text("OpenClaw 2026.9.8 (fake)\n", encoding="utf-8")

    async def run() -> None:
        runtime = openclaw.OpenClawRuntime()
        gateway = await _start(runtime, home, _env())
        try:
            assert [line.split()[0] for line in _calls(home)] == ["doctor", "gateway"]
            assert (home / "runtime-build.txt").read_text(encoding="utf-8").strip() == _BUILD
        finally:
            await runtime._stop_gateway(gateway)
        # The same release again: no migration.
        gateway = await _start(runtime, home, _env())
        try:
            assert [line.split()[0] for line in _calls(home)] == ["doctor", "gateway", "gateway"]
        finally:
            await runtime._stop_gateway(gateway)

    asyncio.run(run())


def test_a_new_agent_or_an_unrecorded_folder_is_not_migrated_up_front(home):
    _with_agent_db(home)  # data, but no release recorded yet

    async def run() -> None:
        runtime = openclaw.OpenClawRuntime()
        gateway = await _start(runtime, home, _env())
        try:
            assert [line.split()[0] for line in _calls(home)] == ["gateway"]
        finally:
            await runtime._stop_gateway(gateway)

    asyncio.run(run())
    assert not openclaw._upgraded_since_last_start(home / "missing", _BUILD)


def test_the_admission_state_reads_the_gateways_own_log():
    pending = (
        "[state/agent-admission] Agent main has not completed startup inspection and "
        "preparation. Inspection and writable admission continue after the Gateway "
        "listener binds."
    )
    recovered = "agent database recovered after background inspection and preparation"
    degraded = (
        '[state/agent-admission] agent database remains degraded agentId=main reason="OpenClaw '
        'agent database C:\\x\\openclaw-agent.sqlite uses schema version 24; run openclaw '
        'doctor --fix"'
    )
    assert openclaw.admission_state("") == "ready"  # older releases log none of it
    assert openclaw.admission_state(pending) == "pending"
    assert openclaw.admission_state(pending + "\n" + recovered) == "ready"
    assert openclaw.admission_state(pending + "\n" + degraded) == "degraded"
    # A config hint that names doctor --fix is no database problem.
    assert openclaw.admission_state("Run openclaw doctor --fix to drop legacy keys") == "ready"


# ------------------------------------------------- (b) start-up readiness


def test_a_gateway_is_handed_out_only_after_its_startup_inspection(home):
    async def run() -> None:
        runtime = openclaw.OpenClawRuntime()
        started = time.monotonic()
        gateway = await _start(
            runtime,
            home,
            _env(FAKE_OPENCLAW_MODE="admission-slow", FAKE_OPENCLAW_ADMISSION_S="1.5"),
        )
        try:
            assert time.monotonic() - started >= 1.4
            assert "recovered" in (home / "gateway.log").read_text(encoding="utf-8")
            assert not (home / "doctor.runs").exists()
        finally:
            await runtime._stop_gateway(gateway)

    asyncio.run(run())


def test_an_admission_that_never_ends_still_hands_out_the_gateway(home, monkeypatch):
    monkeypatch.setattr(openclaw, "_ADMISSION_WAIT_S", 0.5)

    async def run() -> None:
        runtime = openclaw.OpenClawRuntime()
        gateway = await _start(
            runtime,
            home,
            _env(FAKE_OPENCLAW_MODE="admission-slow", FAKE_OPENCLAW_ADMISSION_S="60"),
        )
        try:
            # The turn sends; a refusal is sent again by the runner.
            assert gateway.alive()
        finally:
            await runtime._stop_gateway(gateway)

    asyncio.run(run())


def test_runtime_refusals_are_classified():
    assert not_ready_kind(
        "UNAVAILABLE: Agent main has not completed startup inspection and preparation"
    ) == "starting"
    assert not_ready_kind(
        "openclaw-agent.sqlite uses schema version 24; stop active agents and run "
        "openclaw doctor --fix"
    ) == "repair"
    stores = "ACP session/new failed: Session stores for agent main are unavailable"
    assert not_ready_kind(stores) == "repair"
    assert not_ready_kind("model down") == ""
    assert not_ready_kind(None) == ""


@pytest.fixture
def quick_retries(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(rc, "_RUNTIME_READY_FIRST_DELAY_S", 0.05)
    monkeypatch.setattr(rc, "_RUNTIME_READY_MAX_DELAY_S", 0.1)
    counter = tmp_path / "refusals.txt"
    monkeypatch.setenv("FAKE_ACP_REFUSALS_FILE", str(counter))
    return counter


def test_a_message_refused_while_the_runtime_starts_is_sent_again(
    monkeypatch, tmp_path, quick_retries
):
    monkeypatch.setenv("FAKE_ACP_REFUSALS", "3")
    _, events, _, resumes = _turn(monkeypatch, tmp_path, "NOTREADY hello")
    assert _finished(events)["status"] == "done"
    assert _texts(events) == ["echo: NOTREADY hello"]
    assert quick_retries.read_text(encoding="utf-8") == "3"
    assert len(resumes) == 4  # three refusals, then the answer


def test_a_runtime_that_stays_not_ready_ends_the_turn_after_the_bound(
    monkeypatch, tmp_path, quick_retries
):
    monkeypatch.setattr(rc, "_RUNTIME_READY_WAIT_S", 0.4)
    monkeypatch.setenv("FAKE_ACP_REFUSALS", "1000")
    _, events, _, resumes = _turn(monkeypatch, tmp_path, "NOTREADY hello")
    finished = _finished(events)
    assert finished["status"] == "error"
    assert "startup inspection" in finished["error"]
    assert 2 <= len(resumes) < 20


def test_a_database_that_needs_repair_gets_one_restart_then_its_error(
    monkeypatch, tmp_path, quick_retries
):
    _, events, _, resumes = _turn(monkeypatch, tmp_path, "STALEDB hello")
    finished = _finished(events)
    assert finished["status"] == "error"
    assert "doctor --fix" in finished["error"]
    assert len(resumes) == 2


def test_other_errors_are_never_sent_again(monkeypatch, tmp_path, quick_retries):
    _, events, _, resumes = _turn(monkeypatch, tmp_path, "FAIL")
    assert _finished(events)["status"] == "error"
    assert len(resumes) == 1


# ------------------------------------------------- (c) Hermes launcher


def _launcher_in(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    launcher = folder / ("hermes.cmd" if os.name == "nt" else "hermes")
    launcher.write_text("", encoding="utf-8")
    launcher.chmod(0o755)
    return launcher


def _no_path_augment(monkeypatch: pytest.MonkeyPatch) -> None:
    import dodaios.core.path_augment as path_augment

    monkeypatch.setattr(path_augment, "ensure_cli_paths", lambda: [])


def _temp_is(monkeypatch: pytest.MonkeyPatch, *roots: Path) -> None:
    """Only ``roots`` count as temporary (pytest's own folder may be in Temp)."""
    import re

    monkeypatch.setattr(hermes, "_temp_roots", lambda: [hermes._norm(str(r)) for r in roots])
    monkeypatch.setattr(hermes, "_WINDOWS_TEMP", re.compile(r"(?!)"))


def test_hermes_from_a_temporary_audit_folder_never_runs(tmp_path, monkeypatch):
    temp = tmp_path / "Temp"
    audit = temp / "jarvis-hermes-audit-m1e61qu4" / "runtimes" / "hermes" / "bin"
    real = tmp_path / "Programs" / "hermes" / "bin"
    _launcher_in(audit)
    _launcher_in(real)
    monkeypatch.setattr(hermes, "_install_locations", lambda: [])
    _temp_is(monkeypatch, temp)
    monkeypatch.setenv("PATH", os.pathsep.join([str(audit), str(real)]))
    _no_path_augment(monkeypatch)
    found = hermes._binary()
    assert found is not None and Path(found).parent == real
    # Only the temporary one on PATH: Hermes counts as not installed.
    monkeypatch.setenv("PATH", str(audit))
    assert hermes._binary() is None


@pytest.mark.parametrize(
    "entry",
    [
        r"C:\Users\Ada\AppData\Local\Temp\jarvis-hermes-audit-m1e61qu4\runtimes\hermes\bin",
        r"C:\Users\ADA~1\AppData\Local\Temp\jarvis-hermes-audit-x\runtimes\hermes\bin",
    ],
)
def test_a_windows_temp_folder_is_recognised_under_any_profile_spelling(entry):
    assert hermes._in_temp(entry)
    assert not hermes._in_temp(r"C:\Users\Ada\AppData\Local\hermes\bin")


def test_the_official_install_answers_before_path(tmp_path, monkeypatch):
    managed = _launcher_in(tmp_path / "Local" / "hermes" / "bin")
    other = tmp_path / "elsewhere" / "bin"
    _launcher_in(other)
    monkeypatch.setattr(hermes, "_install_locations", lambda: [managed])
    _temp_is(monkeypatch)
    monkeypatch.setenv("PATH", str(other))
    _no_path_augment(monkeypatch)
    assert hermes._binary() == str(managed)
    # Without the official install, PATH answers.
    monkeypatch.setattr(hermes, "_install_locations", lambda: [tmp_path / "missing" / "hermes"])
    found = hermes._binary()
    assert found is not None and Path(found).parent == other


def test_the_windows_install_location_keeps_its_cmd_launcher(tmp_path, monkeypatch):
    monkeypatch.setattr(hermes, "is_windows", lambda: True)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    bin_dir = tmp_path / "hermes" / "bin"
    assert hermes._install_locations() == [bin_dir / "hermes.exe", bin_dir / "hermes.cmd"]


def test_the_user_path_is_never_edited_for_a_temporary_entry(tmp_path, monkeypatch):
    from dodaios.agent_runtimes import path_cleanup

    entry = r"C:\Users\Ada\AppData\Local\Temp\jarvis-hermes-audit-m1e61qu4\runtimes\hermes\bin"
    assert not path_cleanup.is_jarvis_hermes_bin(entry)
