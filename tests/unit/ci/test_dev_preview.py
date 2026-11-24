"""`scripts/dev_preview.py`: pull requests run in the Dev app, never in the person's own app."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from scripts import dev_preview as dp

LAUNCHER = ["DodaiosApp.exe", "-m", "dodaios.ui.web.launcher"]

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")


@pytest.mark.parametrize(
    ("target", "spec"),
    [
        ("1423", "+refs/pull/1423/head:refs/dev-preview/head"),
        ("#1423", "+refs/pull/1423/head:refs/dev-preview/head"),
        ("feat/x", "+refs/heads/feat/x:refs/dev-preview/head"),
        ("main", "+refs/heads/main:refs/dev-preview/head"),
    ],
)
def test_fetch_spec(target: str, spec: str) -> None:
    assert dp.fetch_spec(target) == spec


@pytest.mark.parametrize(
    "cmdline",
    [
        [*LAUNCHER, "--instance", "dev"],
        [*LAUNCHER, "--instance=dev"],
        ["x.exe", "-m", "dodaios.agent_chat.turn_host", "--state", r"C:\x\turn_host.dev.json"],
        ["x.exe", "-m", "dodaios.terminal.pty_host", "--state", "/x/pty_host.dev.json"],
    ],
)
def test_dev_processes_are_recognised(cmdline: list[str]) -> None:
    assert dp.is_dev_process(cmdline)


@pytest.mark.parametrize(
    "cmdline",
    [
        LAUNCHER,
        [*LAUNCHER, "--headless"],
        ["DodaiosApp.exe", "-m", "dodaios.agent_chat.turn_host", "--state", r"C:\x\turn_host.json"],
        ["pythonw.exe", "-m", "dodaios.terminal.pty_host", "--state", "/x/pty_host.json"],
        ["python.exe", "serve.py", "--instance", "dev"],
        [],
    ],
)
def test_default_app_processes_are_never_matched(cmdline: list[str]) -> None:
    assert not dp.is_dev_process(cmdline)


def test_an_app_bundle_launcher_is_not_taken_for_the_interpreter(tmp_path, monkeypatch) -> None:
    """The macOS app runs from a bundle launcher that takes neither ``-c`` nor ``-m``."""
    import sys
    import types

    launcher = tmp_path / "DodaiosApp"
    launcher.write_text("#!/bin/sh\nexit 2\n", encoding="utf-8")
    launcher.chmod(0o755)
    running = {"exe": str(launcher)}
    fake_psutil = types.SimpleNamespace(
        Process=lambda _pid: types.SimpleNamespace(exe=lambda: running["exe"])
    )
    monkeypatch.setitem(sys.modules, "psutil", fake_psutil)
    monkeypatch.setattr(dp, "_read_meta", lambda _data: {"pid": 4242})

    if sys.platform != "win32":
        assert dp.app_interpreter(tmp_path) == sys.executable
    # An interpreter under any name is the app's own and is used.
    running["exe"] = sys.executable
    assert dp.app_interpreter(tmp_path) == sys.executable
    assert dp.is_python(sys.executable) is True
    assert dp.is_python(str(tmp_path / "missing")) is False


# --------------------------------------------------------------------------
# A pull request from outside the repository is never run
# --------------------------------------------------------------------------


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return done.stdout.strip()


def _commit(repo: Path, text: str) -> str:
    (repo / "file.txt").write_text(text, encoding="utf-8")
    _git(repo, "add", "--", "file.txt")
    _git(repo, "commit", "-q", "--no-verify", "-m", f"chore: {text}")
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def remote(tmp_path: Path, monkeypatch) -> dict:
    """``origin`` with two pull requests: #8 from one of its branches, #7 from a fork.

    A fork's pull request reaches ``origin`` only as ``refs/pull/<n>/head``:
    its head commit is on no branch there.
    """
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    clone = tmp_path / "clone"
    _git(tmp_path, "init", "-q", "-b", "main", str(clone))
    for key, value in (
        ("user.email", "test@example.invalid"),
        ("user.name", "Test"),
        ("commit.gpgsign", "false"),
    ):
        _git(clone, "config", key, value)
    _commit(clone, "base")
    _git(clone, "remote", "add", "origin", str(origin))
    _git(clone, "push", "-q", "origin", "main")
    _git(clone, "switch", "-q", "-c", "feat/x")
    own = _commit(clone, "a branch of this repository")
    _git(clone, "push", "-q", "origin", "feat/x", f"{own}:refs/pull/8/head")
    _git(clone, "switch", "-q", "--detach")
    fork = _commit(clone, "a fork")
    _git(clone, "push", "-q", "origin", f"{fork}:refs/pull/7/head")
    _git(clone, "switch", "-q", "main")
    # GitHub is never asked in these tests unless one of them says what it answers.
    monkeypatch.setattr(dp, "pull_request_facts", lambda _repo, _number: None, raising=False)
    return {"clone": clone, "origin": origin, "own": own, "fork": fork}


def _facts(sha: str, /, **changes: str) -> dict:
    facts = {"association": "OWNER", "head": "acme/widget", "base": "acme/widget", "sha": sha}
    return {**facts, **changes}


@pytest.mark.parametrize(
    ("on_branch", "changes", "word"),
    [
        (False, None, "on no branch"),
        (False, {}, "on no branch"),
        (True, {"head": "stranger/widget"}, "another repository"),
        (True, {"head": ""}, "another repository"),
        (True, {"association": "CONTRIBUTOR"}, "CONTRIBUTOR"),
        (True, {"association": "FIRST_TIME_CONTRIBUTOR"}, "FIRST_TIME_CONTRIBUTOR"),
        (True, {"association": "NONE"}, "NONE"),
        (True, {"association": ""}, "unknown"),
        (True, {"sha": "b" * 40}, "moved"),
    ],
)
def test_code_from_outside_is_refused(on_branch: bool, changes: dict | None, word: str) -> None:
    facts = None if changes is None else _facts("a" * 40, **changes)
    why = dp.refusal("a" * 40, on_branch=on_branch, facts=facts)
    assert why is not None and word in why


@pytest.mark.parametrize("association", ["OWNER", "MEMBER", "COLLABORATOR"])
def test_a_pull_request_of_someone_with_push_access_may_run(association: str) -> None:
    facts = _facts("a" * 40, association=association)
    assert dp.refusal("a" * 40, on_branch=True, facts=facts) is None
    # Without an answer from GitHub the branch check alone decides.
    assert dp.refusal("a" * 40, on_branch=True, facts=None) is None


@pytest.mark.parametrize(
    ("url", "slug"),
    [
        ("https://github.com/acme/widget.git", "acme/widget"),
        ("git@github.com:acme/widget.git", "acme/widget"),
        ("ssh://git@github.com/acme/widget", "acme/widget"),
        ("https://github.com/acme/widget/", "acme/widget"),
        ("https://example.com/acme/widget.git", ""),
        ("https://notgithub.com/acme/widget.git", ""),
        ("https://github.com.example.com/acme/widget", ""),
        ("/srv/git/widget.git", ""),
        ("", ""),
    ],
)
def test_github_is_asked_about_origin_only(url: str, slug: str, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(dp, "_answer", lambda *_args, **_kw: url + "\n" if url else None)
    assert dp.origin_slug(tmp_path) == slug


@needs_git
def test_only_the_tip_of_a_branch_of_origin_counts(remote: dict) -> None:
    clone = remote["clone"]
    assert dp.on_origin_branch(clone, remote["own"]) is True
    assert dp.on_origin_branch(clone, remote["fork"]) is False
    # The merge queue's own branch holds a queued fork's code: no proof either.
    queue = "refs/heads/gh-readonly-queue/main/pr-7-abc"
    _git(clone, "push", "-q", "origin", f"{remote['fork']}:{queue}")
    assert dp.on_origin_branch(clone, remote["fork"]) is False


@needs_git
def test_without_an_answer_from_origin_nothing_is_trusted(remote: dict) -> None:
    clone = remote["clone"]
    _git(clone, "remote", "set-url", "origin", str(remote["origin"]) + "-gone")
    assert dp.on_origin_branch(clone, remote["own"]) is False


@needs_git
def test_a_fork_pull_request_is_refused_before_anything_of_it_is_checked_out(
    remote: dict,
) -> None:
    clone = remote["clone"]
    with pytest.raises(SystemExit) as stop:
        dp.prepare_worktree(clone, "7")
    message = str(stop.value)
    assert "#7" in message and "--run-untrusted-code" in message
    assert not (clone / dp.PREVIEW_DIR).exists()


@needs_git
def test_a_pull_request_from_a_branch_of_the_repository_is_loaded(remote: dict) -> None:
    clone = remote["clone"]
    wt, sha, trusted = dp.prepare_worktree(clone, "#8")
    assert (sha, trusted) == (remote["own"], True)
    assert _git(wt, "rev-parse", "HEAD") == remote["own"]
    # A branch of origin needs no proof: pushing to it is the proof.
    assert dp.prepare_worktree(clone, "feat/x")[1:] == (remote["own"], True)


@needs_git
def test_github_saying_it_is_from_outside_refuses_it_even_on_a_branch(
    remote: dict, monkeypatch
) -> None:
    clone, own = remote["clone"], remote["own"]
    for changes in ({"head": "stranger/widget"}, {"association": "CONTRIBUTOR"}):
        monkeypatch.setattr(
            dp, "pull_request_facts", lambda _repo, _number, c=changes: _facts(own, **c)
        )
        with pytest.raises(SystemExit):
            dp.prepare_worktree(clone, "8")
    monkeypatch.setattr(dp, "pull_request_facts", lambda _repo, _number: _facts(own))
    assert dp.prepare_worktree(clone, "8")[2] is True


@needs_git
def test_the_flag_loads_it_as_untrusted_and_takes_the_shared_link_away_first(
    remote: dict, capsys
) -> None:
    clone = remote["clone"]
    wt, _sha, _trusted = dp.prepare_worktree(clone, "8")
    main_modules = clone / dp.FRONTEND / "node_modules"
    main_modules.mkdir(parents=True)
    (main_modules / "keep.txt").write_text("from the main checkout", encoding="utf-8")
    for root in (clone, wt):
        (root / dp.FRONTEND).mkdir(parents=True, exist_ok=True)
        (root / dp.FRONTEND / "package-lock.json").write_text("{}", encoding="utf-8")
    assert "shared" in dp.ensure_node_modules(clone, wt)
    link = wt / dp.FRONTEND / "node_modules"
    assert dp._is_link(link)

    wt, sha, trusted = dp.prepare_worktree(clone, "7", run_untrusted=True)

    assert (sha, trusted) == (remote["fork"], False)
    assert "WARNING" in capsys.readouterr().out
    assert not link.exists() and not dp._is_link(link)
    assert (main_modules / "keep.txt").read_text(encoding="utf-8") == "from the main checkout"


def _frontends(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A main checkout with installed node_modules and a preview tree with the same lockfile."""
    repo, wt = tmp_path / "main", tmp_path / "preview"
    for root in (repo, wt):
        (root / dp.FRONTEND).mkdir(parents=True)
        (root / dp.FRONTEND / "package-lock.json").write_text("{}", encoding="utf-8")
    main_modules = repo / dp.FRONTEND / "node_modules"
    main_modules.mkdir()
    (main_modules / "keep.txt").write_text("from the main checkout", encoding="utf-8")
    return repo, wt, main_modules


def test_code_from_outside_never_gets_the_node_modules_of_the_main_checkout(
    tmp_path: Path, monkeypatch
) -> None:
    repo, wt, main_modules = _frontends(tmp_path)
    link = wt / dp.FRONTEND / "node_modules"
    installs: list[tuple[str, ...]] = []

    def npm(*args: str, cwd: Path) -> None:
        assert not dp._is_link(link), "npm ran through a link into the main checkout"
        installs.append(args)
        (cwd / "node_modules").mkdir()
        (cwd / "node_modules" / "own.txt").write_text("an own install", encoding="utf-8")

    monkeypatch.setattr(dp, "_npm", npm)

    # The same lockfile as main: a trusted load shares, an untrusted one never does.
    assert "own install" in dp.ensure_node_modules(repo, wt, share=False)
    assert installs and installs[0][0] == "ci"
    assert link.is_dir() and not dp._is_link(link)

    # The next trusted load does not take that install for the main checkout's.
    assert "shared" in dp.ensure_node_modules(repo, wt)
    assert dp._is_link(link) and (link / "keep.txt").exists()
    assert not (link / "own.txt").exists()

    # And an untrusted load after it takes the link away before npm runs.
    installs.clear()
    assert "own install" in dp.ensure_node_modules(repo, wt, share=False)
    assert installs and not dp._is_link(link)
    assert sorted(p.name for p in main_modules.iterdir()) == ["keep.txt"]


def test_a_build_of_code_from_outside_is_never_reused(tmp_path: Path, monkeypatch) -> None:
    wt = tmp_path / "preview"
    (wt / dp.DIST).mkdir(parents=True)
    (wt / dp.DIST / "index.html").write_text("<html>", encoding="utf-8")
    git_dir = tmp_path / "gitdir"
    git_dir.mkdir()
    marker = git_dir / "dev-preview-frontend"
    marker.write_text("tree-1", encoding="utf-8")
    builds: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        dp, "_git", lambda *args, cwd: str(git_dir) if "--absolute-git-dir" in args else "tree-1"
    )
    monkeypatch.setattr(dp, "_npm", lambda *args, cwd: builds.append(args))

    assert "skipped" in dp.build_frontend(wt)
    assert builds == []
    assert dp.build_frontend(wt, remember=False) == "frontend: built"
    assert builds == [("run", "build")]
    assert not marker.exists(), "a later load would have reused the bundle that code built"
    assert dp.build_frontend(wt) == "frontend: built"
    assert marker.read_text(encoding="utf-8") == "tree-1"


@needs_git
def test_the_command_stops_at_a_fork_pull_request_and_runs_nothing_of_it(
    remote: dict, monkeypatch
) -> None:
    clone = remote["clone"]
    calls: list[tuple[str, dict]] = []

    def record(name: str, answer: object):
        def call(*_args: object, **kwargs: object) -> object:
            calls.append((name, kwargs))
            return answer

        return call

    monkeypatch.setattr(dp, "stop_dev_app", lambda: 0)
    monkeypatch.setattr(dp, "main_checkout", lambda _start: clone)
    monkeypatch.setattr(dp, "ensure_node_modules", record("npm", "node_modules: test"))
    monkeypatch.setattr(dp, "build_frontend", record("build", "frontend: test"))
    monkeypatch.setattr(dp, "app_interpreter", lambda _repo: "python")
    monkeypatch.setattr(dp, "launch", record("launch", 4242))

    with pytest.raises(SystemExit) as stop:
        dp.main(["7"])
    assert "--run-untrusted-code" in str(stop.value)
    assert calls == [], "the code of the fork was installed, built or started"

    assert dp.main(["8"]) == 0
    assert calls == [("npm", {"share": True}), ("build", {"remember": True}), ("launch", {})]

    calls.clear()
    assert dp.main(["7", "--run-untrusted-code"]) == 0
    assert calls == [("npm", {"share": False}), ("build", {"remember": False}), ("launch", {})]
