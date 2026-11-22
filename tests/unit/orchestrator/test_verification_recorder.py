"""The run recorder: what a delegated coding run is bound to, and how its turn ended."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from dodaios.orchestrator.verification import recorder as rec
from dodaios.orchestrator.verification import store as vstore
from dodaios.orchestrator.verification.store import VerificationStore
from dodaios.rsi.harness_probe import Harness
from dodaios.rsi.repo_identity import RepoRef

THREAD = "thread-1"


class _Log:
    """The part of the chat store the recorder reads."""

    def __init__(self) -> None:
        self.sessions: dict[str, Any] = {}
        self.events: dict[str, list[dict[str, Any]]] = {}

    def get_session(self, session_id: str) -> Any | None:
        return self.sessions.get(session_id)

    def list_events(self, session_id: str, *, after_seq: int = 0, tail: int | None = None):
        return list(self.events.get(session_id, []))


class _Service:
    """A chat service as far as a listener sees it: stored events, in order."""

    def __init__(self) -> None:
        self.store = _Log()
        self.listeners: list[Any] = []
        self.store.sessions[THREAD] = SimpleNamespace(
            cwd="/repos/notes", provider="claude-cli", model="claude-fable-5-2", effort="high"
        )

    def add_event_listener(self, listener: Any) -> None:
        self.listeners.append(listener)

    def is_running(self, session_id: str) -> bool:
        return session_id in getattr(self, "running", set())

    def emit(self, kind: str, payload: dict[str, Any], ts_ms: int, session: str = THREAD):
        log = self.store.events.setdefault(session, [])
        event = {"seq": len(log) + 1, "ts_ms": ts_ms, "kind": kind, "payload": payload}
        log.append(event)
        for listener in self.listeners:
            listener(session, event)
        return event


def _probe(runner: str) -> Harness:
    return Harness(name=runner, version="2.1.330", line="2.1")


def _describe(_folder: str) -> RepoRef:
    return RepoRef(repo_id="github.com/acme/notes", base_sha="abc123", isolated=True)


@pytest.fixture
def service() -> _Service:
    return _Service()


@pytest.fixture(autouse=True)
def _no_worktree_maker_left_behind():
    """``install`` sets the process's worktree maker; no test hands it to the next."""
    from dodaios.orchestrator.verification import workdir

    yield
    workdir.set_dirs(None)


@pytest.fixture
def store():
    made = VerificationStore(":memory:")
    try:
        yield made
    finally:
        made.close()


@pytest.fixture
def recorder(service, store):
    made = rec.RunRecorder(store, service, probe=_probe, describe=_describe, boot_id="boot-a")
    service.add_event_listener(made.on_event)
    return made


def _start(service: _Service, turn: str = "turn-1", ts_ms: int = 1_000) -> None:
    service.emit("user_message", {"text": "brief", "author": {"agent_id": "lead"}}, ts_ms)
    service.emit(
        "turn_started",
        {"turn_id": turn, "provider": "claude-cli", "model": "claude-fable-5-2",
         "effort": "high", "runner": "claude-cli", "surface": "agent"},
        ts_ms + 1,
    )


def _finish(service: _Service, turn: str = "turn-1", ts_ms: int = 9_000, status: str = "done"):
    service.emit(
        "turn_finished",
        {"turn_id": turn, "status": status, "duration_ms": 8_000, "cost_usd": 0.42,
         "usage": {"input_tokens": 1200, "output_tokens": 300, "cache_read_input_tokens": 900}},
        ts_ms,
    )


BRIEF = "Fix the crash in @dodaios/agent_chat/service.py when a turn ends."


def test_a_run_is_bound_at_the_start_and_closed_when_its_turn_ends(service, store, recorder):
    # As in the app: the turn has started before the order is noted.
    _start(service)
    recorder.note_submission(job_id="job_1", session_id=THREAD, prompt=BRIEF, started_ms=1_000)
    recorder.process_pending()
    run = store.get("job_1")
    assert run["state"] == vstore.RUNNING
    assert run["repo_id"] == "github.com/acme/notes"
    assert run["base_sha"] == "abc123"
    assert run["isolated"] == 1
    assert run["workdir"] == "/repos/notes"
    assert run["primary_domain"] == "backend"
    assert run["domain_source"] == "paths"
    assert run["turn_id"] == "turn-1"
    assert run["runner"] == "claude-cli"
    assert run["harness_version"] == "2.1.330"
    assert run["harness_line"] == "2.1"
    assert run["boot_id"] == "boot-a"

    service.emit("context_usage", {"turn_id": "turn-1", "model": "claude-fable-5-2"}, 5_000)
    service.emit(
        "tool_call",
        {"turn_id": "turn-1", "name": "Edit", "input": {"file_path": "web/src/App.tsx"}},
        6_000,
    )
    _finish(service)
    recorder.process_pending()
    run = store.get("job_1")
    assert run["state"] == vstore.ENDED
    assert run["turn_status"] == "done"
    assert run["model_resolved"] == "claude-fable-5-2"
    assert (run["tokens_in"], run["tokens_out"], run["tokens_cached"]) == (1200, 300, 900)
    assert run["cost_usd"] == pytest.approx(0.42)
    assert run["wall_ms"] == 8_000
    assert run["ended_ms"] == 9_000
    # The files really changed say frontend; the tag from the brief stays as it was.
    assert run["domain_post"] == "frontend"
    assert run["primary_domain"] == "backend"
    assert [s["step"] for s in store.steps("job_1")] == ["bound", "turn_started", "turn_finished"]


def test_the_owner_and_the_request_come_from_the_jobs_ledger(service, store, recorder, ledger):
    ledger.create(
        "ide_submission", job_id="job_1", owner_session="lead-1", owner_turn="lead-turn-7",
        root_span_id="root-9",
    )
    _start(service)
    recorder.note_submission(job_id="job_1", session_id=THREAD, prompt=BRIEF, started_ms=1_000)
    recorder.process_pending()
    run = store.get("job_1")
    assert (run["owner_session"], run["owner_turn"], run["root_span_id"]) == (
        "lead-1", "lead-turn-7", "root-9",
    )


def test_earlier_turns_of_the_same_thread_are_not_this_run(service, store, recorder):
    _start(service, turn="old-turn", ts_ms=100)
    _finish(service, turn="old-turn", ts_ms=200)
    _start(service, turn="turn-2", ts_ms=5_000)
    recorder.note_submission(job_id="job_2", session_id=THREAD, prompt=BRIEF, started_ms=5_000)
    recorder.process_pending()
    run = store.get("job_2")
    assert run["state"] == vstore.RUNNING
    assert run["turn_id"] == "turn-2"


def test_an_event_seen_in_the_log_and_again_live_counts_once(service, store, recorder):
    _start(service)
    recorder.note_submission(job_id="job_1", session_id=THREAD, prompt=BRIEF, started_ms=1_000)
    # Stored and delivered before the order was handled: read once from the
    # log by the catch-up, then handed over a second time from the queue.
    service.emit("session_updated", {"model": "claude-opus-5-5"}, 2_000)
    recorder.process_pending()
    assert store.get("job_1")["mixed_model"] == 1
    assert [s["step"] for s in store.steps("job_1")].count("model_switched") == 1


def test_a_turn_that_already_ended_is_closed_from_the_log(service, store, recorder):
    _start(service)
    _finish(service, status="error")
    recorder.note_submission(job_id="job_1", session_id=THREAD, prompt=BRIEF, started_ms=1_000)
    recorder.process_pending()
    run = store.get("job_1")
    assert run["state"] == vstore.ENDED
    assert run["turn_status"] == "error"


def test_only_a_plain_message_counts_as_the_person_stepping_in(service, store, recorder):
    _start(service)
    recorder.note_submission(job_id="job_1", session_id=THREAD, prompt=BRIEF, started_ms=1_000)
    recorder.process_pending()
    nudge = {"text": "keep going", "turn_id": "turn-1", "steered": True}
    service.emit("user_message", nudge, 2_000)
    recorder.process_pending()
    assert store.get("job_1")["person_intervened"] == 0
    service.emit("user_message", {"text": "stop, do it differently"}, 3_000)
    recorder.process_pending()
    assert store.get("job_1")["person_intervened"] == 1


def test_a_new_order_closes_a_run_whose_end_was_never_seen(service, store, recorder):
    _start(service)
    recorder.note_submission(job_id="job_1", session_id=THREAD, prompt=BRIEF, started_ms=1_000)
    recorder.process_pending()
    _start(service, turn="turn-2", ts_ms=20_000)
    recorder.note_submission(job_id="job_2", session_id=THREAD, prompt=BRIEF, started_ms=20_000)
    recorder.process_pending()
    assert store.get("job_1")["state"] == vstore.INTERRUPTED
    assert store.steps("job_1")[-1]["step"] == "superseded"
    assert store.get("job_2")["turn_id"] == "turn-2"


def test_events_of_threads_without_a_run_are_not_queued(service, recorder):
    service.emit("turn_started", {"turn_id": "t"}, 1, session="someone-elses-thread")
    service.emit("assistant_text", {"text": "hello"}, 2)
    assert recorder.process_pending() == 0


def test_a_restart_picks_an_open_run_up_from_the_thread_log(service, store, recorder):
    _start(service)
    recorder.note_submission(job_id="job_1", session_id=THREAD, prompt=BRIEF, started_ms=1_000)
    recorder.process_pending()
    # The app restarts: the turn ends while no recorder listens.
    service.listeners.clear()
    _finish(service)
    again = rec.RunRecorder(store, service, probe=_probe, describe=_describe, boot_id="boot-b")
    again._resume()
    run = store.get("job_1")
    assert run["state"] == vstore.ENDED
    assert run["turn_status"] == "done"


def test_a_restart_closes_a_run_whose_thread_is_gone(service, store, recorder):
    _start(service)
    recorder.note_submission(job_id="job_1", session_id=THREAD, prompt=BRIEF, started_ms=1_000)
    recorder.process_pending()
    service.store.sessions.clear()
    again = rec.RunRecorder(store, service, probe=_probe, describe=_describe)
    again._resume()
    assert store.get("job_1")["state"] == vstore.INTERRUPTED
    assert store.steps("job_1")[-1]["step"] == "thread_gone"


def test_a_failure_while_recording_never_reaches_the_caller(service, store):
    def broken(_folder: str) -> RepoRef:
        raise RuntimeError("git is gone")

    made = rec.RunRecorder(store, service, probe=_probe, describe=broken)
    made.note_submission(job_id="job_1", session_id=THREAD, prompt=BRIEF, started_ms=1_000)
    assert made.process_pending() == 1
    assert store.get("job_1") is None


def test_noting_an_order_is_a_no_op_while_recording_is_off():
    rec.set_recorder(None)
    rec.note_submission(job_id="job_1", session_id=THREAD, prompt=BRIEF, started_ms=1)


def test_recording_starts_only_when_the_setting_is_on(service, tmp_path):
    off = SimpleNamespace(rsi=SimpleNamespace(enabled=False))
    assert rec.install(service, tmp_path, off) is None
    assert rec.install(service, tmp_path, SimpleNamespace()) is None
    assert not (tmp_path / "verification.db").exists()
    assert service.listeners == []

    made = rec.install(service, tmp_path, SimpleNamespace(rsi=SimpleNamespace(enabled=True)))
    try:
        assert made is not None
        assert rec.recorder() is made
        assert (tmp_path / "verification.db").is_file()
        assert service.listeners == [made.on_event]
    finally:
        if made is not None:
            made.stop()
            made.store.close()
        rec.set_recorder(None)


def test_the_config_section_is_off_by_default_and_closed_to_self_change():
    from dodaios.core.config import JarvisConfig
    from dodaios.core.self_mod.forbidden import is_forbidden

    assert JarvisConfig().rsi.enabled is False
    assert JarvisConfig().rsi.verify == "off"
    assert is_forbidden("rsi.enabled")
    assert is_forbidden("rsi.verify")


def test_the_recorder_takes_its_verify_mode_from_the_setting(service, tmp_path):
    config = SimpleNamespace(rsi=SimpleNamespace(enabled=True, verify="observe"))
    made = rec.install(service, tmp_path, config)
    try:
        assert made is not None
        assert made._verify == "observe"
    finally:
        if made is not None:
            made.stop()
            made.store.close()
        rec.set_recorder(None)


def _installed(service, tmp_path, **settings):
    return rec.install(service, tmp_path, SimpleNamespace(rsi=SimpleNamespace(**settings)))


def _uninstall(made) -> None:
    from dodaios.orchestrator.verification import workdir

    held = workdir.dirs()
    workdir.set_dirs(None)
    if made is not None:
        made.stop()
        made.store.close()
    elif held is not None:
        held._store.close()
    rec.set_recorder(None)


@pytest.mark.parametrize(
    ("settings", "making"),
    [
        ({"enabled": True, "verify": "observe", "worktree_per_run": True}, True),
        ({"enabled": True, "verify": "off", "worktree_per_run": True}, False),
        ({"enabled": True, "verify": "observe", "worktree_per_run": False}, False),
        ({"enabled": True}, False),
    ],
)
def test_threads_get_their_own_worktree_only_while_output_is_verified(
    service, tmp_path, settings, making
):
    from dodaios.orchestrator.verification import workdir

    made = _installed(service, tmp_path, **settings)
    try:
        dirs = workdir.dirs()
        assert dirs is not None
        assert dirs._making is making
    finally:
        _uninstall(made)


def test_the_settings_for_worktrees_reach_the_one_that_makes_them(service, tmp_path):
    from dodaios.core.config import RsiConfig
    from dodaios.orchestrator.verification import workdir

    assert RsiConfig().worktree_per_run is True
    assert RsiConfig().shared_checkout_repos == []
    section = RsiConfig(
        enabled=True, verify="observe", shared_checkout_repos=["github.com/Acme/Notes"]
    )
    made = rec.install(service, tmp_path, SimpleNamespace(rsi=section))
    try:
        dirs = workdir.dirs()
        assert dirs is not None
        assert dirs._making is True
        assert dirs._shared == {"github.com/acme/notes"}
        # What the one that puts worktrees away asks about a thread.
        service.running = {THREAD}
        assert dirs._thread_exists(THREAD) is True
        assert dirs._thread_exists("gone") is False
        assert dirs._idle_ms(THREAD) == 0
        service.running = set()
        service.store.sessions[THREAD].updated_ms = 1_000
        service.store.sessions[THREAD].last_message_ms = 2_000
        assert dirs._idle_ms(THREAD) > 60_000
        assert dirs._idle_ms("gone") == 0
    finally:
        _uninstall(made)


def test_with_recording_off_only_worktrees_put_away_earlier_are_served(service, tmp_path):
    from dodaios.orchestrator.verification import workdir

    off = {"enabled": False, "verify": "observe", "worktree_per_run": True}
    # Never switched on: no record, nothing to restore, nothing opened.
    assert _installed(service, tmp_path, **off) is None
    assert workdir.dirs() is None
    # Switched on once, with nothing put away: still nothing to serve.
    store = VerificationStore(tmp_path / "verification.db")
    store.add_workdir(
        "/repos/notes/.worktrees/agent-a", repo_id="r", root="/repos/notes", branch="agent/a",
        base_sha="abc", created_ms=1,
    )
    store.bind_workdir("/repos/notes/.worktrees/agent-a", THREAD)
    assert _installed(service, tmp_path, **off) is None
    assert workdir.dirs() is None
    # One was put away: its thread must find it again, and nothing new is made.
    store.close_workdir("/repos/notes/.worktrees/agent-a", 5, branch="agent/a", head_sha="abc")
    store.close()
    try:
        assert _installed(service, tmp_path, **off) is None
        dirs = workdir.dirs()
        assert dirs is not None
        assert dirs._making is False
        assert rec.recorder() is None
        assert service.listeners == []
    finally:
        _uninstall(None)


def test_the_judges_of_a_run_are_core_paths_of_the_app():
    from dodaios.self_change.surfaces import is_core_path

    for path in (
        "dodaios/orchestrator/verification/cheat_scan.py",
        "dodaios/rsi/domains.py",
        "dodaios/self_build/code/judge.py",
        "dodaios/agent_chat/team/workspace.py",
    ):
        assert is_core_path(path), path


def test_a_thread_order_is_noted_with_the_id_of_its_job(ledger):
    from dodaios.agentic_ide.chat_threads import ChatThreads

    noted: list[dict[str, Any]] = []

    class _Notes:
        def note_submission(self, **order: Any) -> None:
            noted.append(order)

    rec.set_recorder(_Notes())  # type: ignore[arg-type]
    try:
        job_id = ChatThreads(chat=lambda: None)._ledger(THREAD, "Claude Code", BRIEF, None, 1_000)
    finally:
        rec.set_recorder(None)
    assert job_id is not None
    assert noted == [
        {"job_id": job_id, "session_id": THREAD, "prompt": BRIEF, "started_ms": 1_000}
    ]
    assert ledger.get(job_id).kind == "ide_submission"


def test_a_thread_order_goes_through_unchanged_while_recording_is_off(ledger):
    from dodaios.agentic_ide.chat_threads import ChatThreads

    rec.set_recorder(None)
    job_id = ChatThreads(chat=lambda: None)._ledger(THREAD, "Claude Code", BRIEF, None, 1_000)
    assert ledger.get(job_id).state == "running"


def test_a_run_is_recorded_from_the_real_chat_store_and_a_real_checkout(tmp_path, store):
    """The shapes the recorder reads are the ones the chat store really writes."""
    import subprocess

    from dodaios.agent_chat.events import make_event
    from dodaios.agent_chat.store import AgentChatStore

    repo = tmp_path / "repo"
    repo.mkdir()
    for args in (
        ["init", "-q", "-b", "main"],
        ["config", "user.email", "t@example.com"],
        ["config", "user.name", "T"],
        ["commit", "-q", "--allow-empty", "-m", "first"],
    ):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()

    chat = AgentChatStore(tmp_path / "agent_chat.db")
    session = chat.create_session(
        provider="codex-cli", model="", effort="medium", cwd=str(repo), surface="agent"
    )
    service = SimpleNamespace(store=chat)
    made = rec.RunRecorder(store, service, probe=_probe)

    def emit(kind: str, payload: dict[str, Any]) -> None:
        stored = chat.append_event(session.session_id, make_event(kind, payload))
        made.on_event(session.session_id, stored)

    emit(
        "turn_started",
        {"turn_id": "t1", "provider": "codex-cli", "model": "", "runner": "codex-cli"},
    )
    made.note_submission(
        job_id="job_real", session_id=session.session_id, prompt="Tidy docs/guide.md", started_ms=0
    )
    emit("turn_finished", {"turn_id": "t1", "status": "done", "duration_ms": 5, "usage": {}})
    made.process_pending()

    run = store.get("job_real")
    assert run["state"] == vstore.ENDED
    assert run["base_sha"] == head
    assert run["repo_id"].startswith("path:")
    assert run["isolated"] == 0
    assert run["primary_domain"] == "docs"
    assert (run["runner"], run["harness_version"]) == ("codex-cli", "2.1.330")
    # Codex names no answering model in its stream: the field stays empty, not guessed.
    assert run["model_resolved"] == ""
