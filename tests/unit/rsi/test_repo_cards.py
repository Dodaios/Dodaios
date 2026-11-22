"""The repository board: slow facts in the background, the index without git."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from dodaios.rsi import repo_cards
from dodaios.rsi.repo_cards import RepoBoard

LEAD = "lead-1"


class _Threads:
    """The chat service as far as the board reads it."""

    def __init__(self) -> None:
        self.sessions: list[Any] = []
        self.running: set[str] = set()
        self.questions: set[str] = set()
        self.approvals: set[str] = set()
        self.listeners: list[Any] = []
        self.store = SimpleNamespace(list_sessions=self._list)

    def _list(self, limit: int = 200, *, surface: str | None = None) -> list[Any]:
        return list(self.sessions)

    def add(self, sid: str, cwd: str, *, state: str = "idle") -> None:
        self.sessions.append(SimpleNamespace(session_id=sid, cwd=cwd))
        {"busy": self.running, "question": self.questions, "approval": self.approvals}.get(
            state, set()
        ).add(sid)

    def is_running(self, sid: str) -> bool:
        return sid in self.running

    def pending_questions(self, sid: str) -> list[str]:
        return ["q"] if sid in self.questions else []

    def pending_approvals(self, sid: str) -> list[str]:
        return ["a"] if sid in self.approvals else []

    def add_event_listener(self, listener: Any) -> None:
        self.listeners.append(listener)


class _Git:
    """Stands in for every ``git`` read and counts them."""

    def __init__(self) -> None:
        self.repos = {
            "/code/notes": "github.com/acme/notes",
            "/code/shop": "github.com/acme/shop",
            "/code/infra": "github.com/acme/infra",
            "/elsewhere/notes-wt": "github.com/acme/notes",
        }
        self.dirty: set[str] = set()
        self.calls = 0

    def repo_of(self, folder: str) -> str:
        self.calls += 1
        return self.repos.get(folder, "")

    def state(self, folder: str) -> tuple[bool, bool]:
        self.calls += 1
        return (folder in self.dirty, False)


PROJECTS = [("notes", "/code/notes"), ("shop", "/code/shop"), ("infra", "/code/infra")]


@pytest.fixture
def threads() -> _Threads:
    return _Threads()


@pytest.fixture
def git() -> _Git:
    return _Git()


@pytest.fixture
def made(threads: _Threads, git: _Git, monkeypatch) -> RepoBoard:
    jobs: list[Any] = []
    board = RepoBoard(
        threads,
        projects=lambda: list(PROJECTS),
        repo_of=git.repo_of,
        git_state=git.state,
        recent_jobs=lambda _owner: list(jobs),
    )
    board.jobs = jobs  # type: ignore[attr-defined]
    # Refreshes run when the test says so, in the test's own thread.
    board.asked = 0  # type: ignore[attr-defined]

    def asked() -> bool:
        board.asked += 1  # type: ignore[attr-defined]
        return True

    monkeypatch.setattr(board, "request_refresh", asked)
    return board


def test_nothing_is_known_before_the_first_refresh_and_one_is_asked_for(made, threads):
    threads.add("t1", "/code/notes", state="busy")
    assert made.text(owner_session=LEAD) == ""
    assert made.asked == 1


def test_threads_are_counted_for_the_repository_of_their_folder(made, threads):
    made.refresh()
    threads.add("t1", "/code/notes", state="busy")
    threads.add("t2", "/code/notes/.worktrees/fix-a", state="busy")
    threads.add("t3", "/code/shop", state="question")
    threads.add("t4", "/code/shop", state="approval")
    threads.add("t5", "/code/infra")  # idle: not in play
    lines = made.text(owner_session=LEAD).splitlines()
    assert lines[0].startswith("[Repos, rev 1: 2 of 3 in play.")
    assert lines[1:] == ["shop: 2 wait for you", "notes: 2 busy", "Quiet: 1 repo."]


def test_rendering_reads_no_git(made, threads, git):
    made.refresh()
    threads.add("t1", "/code/notes", state="busy")
    before = git.calls
    made.text(owner_session=LEAD)
    made.text(owner_session=LEAD)
    assert git.calls == before


def test_the_revision_rises_only_when_the_content_changes(made, threads):
    made.refresh()
    threads.add("t1", "/code/notes", state="busy")
    first = made.text()
    assert made.text() == first
    threads.add("t2", "/code/notes", state="busy")
    changed = made.text()
    assert changed != first
    assert "rev 2:" in changed
    assert "notes: 2 busy" in changed


def test_a_thread_in_a_worktree_outside_its_repository_is_resolved_by_the_next_refresh(
    made, threads
):
    made.refresh()
    threads.add("t1", "/elsewhere/notes-wt", state="busy")
    assert made.text() == ""  # not known yet: nothing is guessed
    made.refresh()
    assert "notes: 1 busy" in made.text()


def test_flags_are_read_only_for_repositories_in_play(made, threads, git):
    git.dirty.add("/code/notes")
    git.dirty.add("/code/infra")
    made.refresh()
    threads.add("t1", "/code/notes", state="busy")
    made.text()  # notes is in play now: its flags are wanted
    calls = git.calls
    made.refresh()
    assert git.calls - calls == len(PROJECTS) + 1  # every project's repository, one state
    assert "notes: 1 busy; main dirty" in made.text()
    assert "infra" not in made.text().split("Quiet:")[0]


def test_a_repository_named_in_the_message_is_in_play(made):
    made.refresh()
    text = made.text(message="Can you look at the Shop checkout again?")
    assert "shop: idle" in text
    assert made.text(message="We went shopping yesterday.") == ""


def test_the_last_repositories_this_conversation_handed_work_to_are_in_play(made, threads):
    made.refresh()
    threads.add("t1", "/code/infra")
    made.jobs.append(SimpleNamespace(target="thread:t1"))
    made.jobs.append(SimpleNamespace(target="pane:x"))
    assert "infra: idle" in made.text(owner_session=LEAD)
    assert made.text() == ""  # without the conversation there is no "recent"


def test_a_conversation_is_handed_the_index_only_when_it_changed(made, threads):
    made.refresh()
    threads.add("t1", "/code/notes", state="busy")
    first = made.note_for(LEAD)
    assert "notes: 1 busy" in first
    assert made.note_for(LEAD) == ""
    assert made.note_for("another-conversation") != ""
    threads.add("t2", "/code/shop", state="question")
    assert "shop: 1 waits for you" in made.note_for(LEAD)


def test_an_unchanged_index_is_sent_again_after_many_turns_and_after_a_fresh_start(made, threads):
    made.refresh()
    threads.add("t1", "/code/notes", state="busy")
    assert made.note_for(LEAD)
    quiet = [made.note_for(LEAD) for _ in range(repo_cards.RESEND_EVERY - 1)]
    assert quiet == [""] * (repo_cards.RESEND_EVERY - 1)
    assert made.note_for(LEAD) != ""
    assert made.note_for(LEAD) == ""
    made.forget(LEAD)
    assert made.note_for(LEAD) != ""


def test_a_finished_turn_asks_for_a_refresh_and_other_events_do_not(made):
    made.on_event("t1", {"kind": "assistant_text"})
    assert made.asked == 0
    made.on_event("t1", {"kind": "turn_finished"})
    assert made.asked == 1


def test_two_refreshes_are_not_started_on_top_of_each_other(threads, git):
    now = [100.0]
    board = RepoBoard(
        threads, projects=lambda: list(PROJECTS), repo_of=git.repo_of, git_state=git.state,
        recent_jobs=lambda _owner: [], clock=lambda: now[0],
    )
    board.refresh()
    assert board.request_refresh() is False  # one just ran
    now[0] += repo_cards.MIN_REFRESH_GAP_S + 1
    board._refreshing = True
    assert board.request_refresh() is False  # one is running


def test_without_a_board_the_lead_gets_nothing_and_nothing_breaks():
    repo_cards.set_board(None)
    assert repo_cards.cli_note(LEAD, "hello") == ""
    assert repo_cards.turn_context_note() == ""


def test_a_failing_board_never_fails_the_turn(threads):
    def broken() -> list[Any]:
        raise RuntimeError("the library is gone")

    board = RepoBoard(threads, projects=broken, recent_jobs=lambda _owner: [])
    threads.store.list_sessions = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db"))
    repo_cards.set_board(board)
    try:
        assert repo_cards.cli_note(LEAD, "x") == ""
        assert repo_cards.turn_context_note() == ""
    finally:
        repo_cards.set_board(None)


def test_the_index_starts_only_when_its_setting_is_on(threads):
    off = SimpleNamespace(rsi=SimpleNamespace(enabled=True, repo_index=False))
    assert repo_cards.install(threads, off) is None
    assert threads.listeners == []
    made = repo_cards.install(threads, SimpleNamespace(rsi=SimpleNamespace(repo_index=True)))
    try:
        assert made is not None
        assert repo_cards.board() is made
        assert threads.listeners == [made.on_event]
    finally:
        repo_cards.set_board(None)


def test_the_setting_is_off_by_default_and_closed_to_self_change():
    from dodaios.core.config import JarvisConfig
    from dodaios.core.self_mod.forbidden import is_forbidden

    assert JarvisConfig().rsi.repo_index is False
    assert is_forbidden("rsi.repo_index")
