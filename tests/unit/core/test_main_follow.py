"""Following main: fetch, fast-forward, rebuild, restart when idle — against a real git."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Iterable
from pathlib import Path

import pytest

from dodaios.core import main_follow
from dodaios.core.main_follow import DIST, GitProcess, MainFollower, git_works_in

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


@pytest.fixture(autouse=True)
def _identity(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.invalid")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@example.invalid")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    # Long temp folders on Windows overflow MAX_PATH inside a bare repo's objects.
    (tmp_path / "gitconfig").write_text("[core]\n\tlongpaths = true\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True, encoding="utf-8"
    ).stdout.strip()


def _write(root: Path, rel: str, text: str) -> None:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(text.encode("utf-8"))


@pytest.fixture
def setup(tmp_path: Path) -> tuple[Path, Path]:
    """(the app's checkout on main, a second clone that lands new work on origin)."""
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    app = tmp_path / "app"
    _git(tmp_path, "clone", "-q", str(remote), str(app))
    _write(app, "dodaios/core/a.py", "A = 1\n")
    _write(app, f"{DIST}/index.html", "<html>v1</html>\n")
    _write(app, "README.md", "readme\n")
    _git(app, "add", ".")
    _git(app, "commit", "-q", "-m", "first")
    _git(app, "push", "-q", "-u", "origin", "main")
    other = tmp_path / "other"
    _git(tmp_path, "clone", "-q", str(remote), str(other))
    return app, other


def _land(other: Path, files: dict[str, str], subject: str) -> None:
    for rel, text in files.items():
        _write(other, rel, text)
    _git(other, "add", ".")
    _git(other, "commit", "-q", "-m", subject)
    _git(other, "push", "-q")


class Recorder:
    def __init__(self, idle: bool = True) -> None:
        self.idle = idle
        self.restarts = 0
        self.builds: list[bool] = []

    def follower(
        self,
        root: Path,
        *,
        enabled: bool = True,
        processes: Callable[[], Iterable[GitProcess] | None] = lambda: None,
    ) -> MainFollower:
        # By default the running processes cannot be told, so no lock is ever
        # removed on its own; the tests about that pass a lister of their own.
        follower = MainFollower(
            root,
            enabled=lambda: enabled,
            idle=lambda: self.idle,
            restart=self._restart,
            processes=processes,
        )

        def build(*, npm_install: bool) -> bool:
            self.builds.append(npm_install)
            return True

        follower._build = build  # type: ignore[method-assign]
        return follower

    def _restart(self) -> bool:
        self.restarts += 1
        return True


def test_does_nothing_unless_enabled(setup: tuple[Path, Path]) -> None:
    app, other = setup
    _land(other, {"dodaios/core/a.py": "A = 2\n"}, "feat: two")
    status = Recorder().follower(app, enabled=False).tick()
    assert not status.enabled and not status.eligible
    assert (app / "dodaios/core/a.py").read_text(encoding="utf-8") == "A = 1\n"


def test_a_branch_other_than_main_is_never_moved(setup: tuple[Path, Path]) -> None:
    app, other = setup
    _git(app, "switch", "-q", "-c", "feature")
    _land(other, {"dodaios/core/a.py": "A = 2\n"}, "feat: two")
    status = Recorder().follower(app).tick()
    assert not status.eligible and "feature" in status.reason
    assert _git(app, "rev-parse", "--abbrev-ref", "HEAD") == "feature"


def test_fast_forwards_and_restarts_for_python_once_idle(setup: tuple[Path, Path]) -> None:
    app, other = setup
    _land(other, {"dodaios/core/a.py": "A = 2\n"}, "feat: two")
    recorder = Recorder(idle=False)
    follower = recorder.follower(app)
    status = follower.tick()
    assert (app / "dodaios/core/a.py").read_text(encoding="utf-8") == "A = 2\n"
    assert status.last_subject == "feat: two" and status.restart_pending
    assert recorder.restarts == 0 and recorder.builds == []
    # Busy: the restart waits. Idle: the next round restarts.
    follower.tick()
    assert recorder.restarts == 0
    recorder.idle = True
    follower.tick()
    assert recorder.restarts == 1 and not follower.status.restart_pending


def test_a_frontend_change_rebuilds_and_a_local_bundle_never_blocks(
    setup: tuple[Path, Path],
) -> None:
    app, other = setup
    _write(app, f"{DIST}/index.html", "<html>local build</html>\n")
    _write(app, f"{DIST}/assets/leftover.js", "old\n")
    _land(
        other,
        {
            "dodaios/ui/web/frontend/src/App.tsx": "export {};\n",
            "dodaios/ui/web/frontend/package-lock.json": "{}\n",
            f"{DIST}/index.html": "<html>v2</html>\n",
        },
        "feat(ui): new view",
    )
    recorder = Recorder()
    status = recorder.follower(app).tick()
    assert status.reason == "" and status.blocked_by == []
    assert (app / f"{DIST}/index.html").read_text(encoding="utf-8") == "<html>v2</html>\n"
    assert not (app / f"{DIST}/assets/leftover.js").exists()
    assert recorder.builds == [True]
    assert not status.restart_pending and recorder.restarts == 0


def test_a_local_edit_the_update_would_overwrite_blocks_it(setup: tuple[Path, Path]) -> None:
    app, other = setup
    _write(app, "README.md", "my local notes\n")
    _land(other, {"README.md": "new readme\n"}, "docs: readme")
    head = _git(app, "rev-parse", "HEAD")
    status = Recorder().follower(app).tick()
    assert _git(app, "rev-parse", "HEAD") == head
    assert status.blocked_by == ["README.md"] and "README.md" in status.reason
    assert (app / "README.md").read_text(encoding="utf-8") == "my local notes\n"


def test_an_unrelated_local_edit_rides_along(setup: tuple[Path, Path]) -> None:
    app, other = setup
    _write(app, "README.md", "my local notes\n")
    _land(other, {"dodaios/core/b.py": "B = 1\n"}, "feat: b")
    status = Recorder().follower(app).tick()
    assert (app / "dodaios/core/b.py").exists() and status.blocked_by == []
    assert (app / "README.md").read_text(encoding="utf-8") == "my local notes\n"


def test_local_commits_on_main_are_left_alone(setup: tuple[Path, Path]) -> None:
    app, other = setup
    _write(app, "local.txt", "x\n")
    _git(app, "add", ".")
    _git(app, "commit", "-q", "-m", "local only")
    _land(other, {"dodaios/core/a.py": "A = 2\n"}, "feat: two")
    head = _git(app, "rev-parse", "HEAD")
    status = Recorder().follower(app).tick()
    assert _git(app, "rev-parse", "HEAD") == head
    assert "Local main has commits" in status.reason


def test_a_checkout_inside_another_is_not_followed(setup: tuple[Path, Path]) -> None:
    app, _ = setup
    status = Recorder().follower(app / "dodaios").tick()
    assert not status.eligible


def test_only_the_instance_with_ambient_duties_starts_one(monkeypatch: pytest.MonkeyPatch) -> None:
    class Dev:
        owns_ambient_duties = False

    monkeypatch.setattr(main_follow, "_follower", None)
    monkeypatch.setattr("dodaios.core.instance.current_instance", lambda: Dev())
    started = main_follow.start_follower(
        enabled=lambda: True, idle=lambda: True, restart=lambda: True
    )
    assert started is None and main_follow.get_follower() is None


def test_python_outside_the_app_needs_no_restart(setup: tuple[Path, Path]) -> None:
    app, other = setup
    _land(other, {"tests/test_x.py": "def test_x():\n    pass\n"}, "test: x")
    recorder = Recorder()
    status = recorder.follower(app).tick()
    assert (app / "tests/test_x.py").exists()
    assert not status.restart_pending and recorder.restarts == 0


def test_a_git_lock_waits_and_only_an_old_one_is_offered_for_removal(
    setup: tuple[Path, Path],
) -> None:
    app, other = setup
    _land(other, {"jarvis_extra.txt": "x\n"}, "chore: extra")
    lock = app / ".git" / "index.lock"
    lock.write_bytes(b"")
    follower = Recorder().follower(app)

    status = follower.tick()
    assert status.lock_since and not status.lock_stale
    assert "Another git command" in status.reason
    assert not follower.clear_stale_lock() and lock.exists()

    old = time.time() - main_follow.STALE_LOCK_S - 60
    os.utime(lock, (old, old))
    status = follower.tick()
    assert status.lock_stale and "stopped command" in status.reason
    assert not (app / "jarvis_extra.txt").exists()

    assert follower.clear_stale_lock() and not lock.exists()
    status = follower.tick()
    assert (app / "jarvis_extra.txt").exists()
    assert status.lock_since == 0 and status.reason == ""


# ------------------------------------------------------------------ killed git commands


def _age(path: Path) -> None:
    old = time.time() - main_follow.STALE_LOCK_S - 60
    os.utime(path, (old, old))


def test_writing_git_commands_get_the_long_timeout_and_reads_take_no_lock(
    setup: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    app, other = setup
    _write(app, f"{DIST}/index.html", "<html>local build</html>\n")
    _land(other, {f"{DIST}/index.html": "<html>v2</html>\n"}, "build(ui): bundle")
    calls: list[tuple[list[str], float, bool]] = []
    real_run = main_follow._run

    def recording(args: list[str], cwd: Path, **kwargs: object) -> subprocess.CompletedProcess:
        timeout = kwargs.get("timeout", main_follow._GIT_TIMEOUT_S)
        calls.append((args, float(timeout), bool(kwargs.get("read_only", False))))  # type: ignore[arg-type]
        return real_run(args, cwd, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(main_follow, "_run", recording)
    status = Recorder().follower(app).tick()
    assert status.reason == "" and status.head == status.remote

    def verb(args: list[str]) -> str:
        return args[3] if args[:3] == ["git", "-c", "core.quotePath=false"] else args[0]

    writes = {verb(args) for args, _, read_only in calls if not read_only}
    assert writes == {"checkout", "clean", "merge"}
    for args, timeout, read_only in calls:
        if verb(args) in writes:
            assert timeout == main_follow.GIT_WRITE_TIMEOUT_S >= 30 * 60, args
            assert not read_only
        else:
            assert read_only and timeout <= 120, args


def test_a_timeout_or_a_missing_program_is_a_failed_result_not_an_exception(
    tmp_path: Path,
) -> None:
    slow = main_follow._run(
        [sys.executable, "-c", "import time; time.sleep(30)"], tmp_path, timeout=0.5
    )
    assert slow.returncode != 0 and "timed out" in slow.stderr
    missing = main_follow._run(["dodaios-no-such-program-xyz"], tmp_path)
    assert missing.returncode != 0


def test_which_git_processes_count_as_working_in_the_checkout(tmp_path: Path) -> None:
    root = tmp_path / "app"
    elsewhere = str(tmp_path / "other")
    assert git_works_in(root, []) is False
    assert git_works_in(root, [GitProcess("git.exe", elsewhere, ["git", "status"])]) is False
    assert git_works_in(root, [GitProcess("git.exe", str(root / "sub"), ["git"])]) is True
    assert git_works_in(root, [GitProcess("git", elsewhere, ["git", "-C", str(root)])]) is True
    # Nothing can be read about it: it might be working here.
    assert git_works_in(root, [GitProcess("git.exe", None, None)]) is None
    assert git_works_in(root, [GitProcess("git.exe", None, ["git", "status"])]) is None
    assert git_works_in(root, None) is None
    # One that is known to work here answers, whatever else is unreadable.
    both = [GitProcess("git.exe", None, None), GitProcess("git.exe", str(root), ["git"])]
    assert git_works_in(root, both) is True


def test_a_stale_lock_no_git_process_holds_is_removed_by_itself(
    setup: tuple[Path, Path],
) -> None:
    app, other = setup
    _land(other, {"jarvis_extra.txt": "x\n"}, "chore: extra")
    lock = app / ".git" / "index.lock"
    lock.write_bytes(b"")
    _age(lock)
    status = Recorder().follower(app, processes=lambda: []).tick()
    assert not lock.exists() and (app / "jarvis_extra.txt").exists()
    assert status.lock_since == 0 and not status.lock_stale and status.reason == ""


def test_a_young_lock_is_never_removed_even_with_no_git_running(
    setup: tuple[Path, Path],
) -> None:
    app, other = setup
    _land(other, {"jarvis_extra.txt": "x\n"}, "chore: extra")
    lock = app / ".git" / "index.lock"
    lock.write_bytes(b"")
    status = Recorder().follower(app, processes=lambda: []).tick()
    assert lock.exists() and not (app / "jarvis_extra.txt").exists()
    assert "Another git command" in status.reason


@pytest.mark.parametrize(
    "seen",
    [
        pytest.param(lambda root: [GitProcess("git.exe", str(root), ["git", "merge"])], id="cwd"),
        pytest.param(
            lambda root: [GitProcess("git.exe", str(root.parent), ["git", "-C", str(root)])],
            id="dash-C",
        ),
        pytest.param(lambda root: [GitProcess("git.exe", None, None)], id="unreadable"),
        pytest.param(lambda root: None, id="cannot-list"),
    ],
)
def test_a_stale_lock_stays_while_a_git_process_may_work_in_the_checkout(
    setup: tuple[Path, Path], seen: Callable[[Path], list[GitProcess] | None]
) -> None:
    app, other = setup
    _land(other, {"jarvis_extra.txt": "x\n"}, "chore: extra")
    lock = app / ".git" / "index.lock"
    lock.write_bytes(b"")
    _age(lock)
    status = Recorder().follower(app, processes=lambda: seen(app)).tick()
    assert lock.exists() and not (app / "jarvis_extra.txt").exists()
    assert status.lock_stale and "stopped command" in status.reason


def _interrupted(app: Path, other: Path, readme: str) -> None:
    """origin/main moves on; a killed fast-forward already wrote some of its files."""
    _land(
        other,
        {
            "README.md": "new readme\n",
            "dodaios/core/new.py": "N = 1\n",
            "dodaios/core/a.py": "A = 2\n",
        },
        "feat: three files",
    )
    _write(app, "README.md", readme)
    _write(app, "dodaios/core/new.py", "N = 1\n")
    lock = app / ".git" / "index.lock"
    lock.write_bytes(b"")
    _age(lock)


def test_an_interrupted_fast_forward_is_finished_when_its_leftovers_match_origin(
    setup: tuple[Path, Path],
) -> None:
    app, other = setup
    _interrupted(app, other, readme="new readme\n")
    status = Recorder().follower(app, processes=lambda: []).tick()
    assert _git(app, "rev-parse", "HEAD") == _git(app, "rev-parse", "origin/main")
    assert status.reason == "" and status.blocked_by == []
    assert (app / "dodaios/core/a.py").read_text(encoding="utf-8") == "A = 2\n"
    assert _git(app, "status", "--porcelain") == ""


def test_an_interrupted_fast_forward_with_one_real_edit_is_left_alone(
    setup: tuple[Path, Path],
) -> None:
    app, other = setup
    _interrupted(app, other, readme="my own notes\n")
    head = _git(app, "rev-parse", "HEAD")
    status = Recorder().follower(app, processes=lambda: []).tick()
    assert _git(app, "rev-parse", "HEAD") == head
    assert sorted(status.blocked_by) == ["README.md", "dodaios/core/new.py"]
    assert (app / "README.md").read_text(encoding="utf-8") == "my own notes\n"
    assert (app / "dodaios/core/new.py").read_text(encoding="utf-8") == "N = 1\n"
    assert (app / "dodaios/core/a.py").read_text(encoding="utf-8") == "A = 1\n"
