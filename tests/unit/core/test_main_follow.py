"""Following main: fetch, fast-forward, rebuild, restart when idle — against a real git."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from dodaios.core import main_follow
from dodaios.core.main_follow import DIST, MainFollower

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


@pytest.fixture(autouse=True)
def _identity(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.invalid")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@example.invalid")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
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

    def follower(self, root: Path, *, enabled: bool = True) -> MainFollower:
        follower = MainFollower(
            root, enabled=lambda: enabled, idle=lambda: self.idle, restart=self._restart
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
