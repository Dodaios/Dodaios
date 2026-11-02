"""Installs and updates never download the Unreal LFS objects (WP22.6, A22.4)."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
POINTER = (
    "version https://git-lfs.github.com/spec/v1\noid sha256:" + "ab" * 32 + "\nsize 123456789\n"
)


def test_lfsconfig_excludes_the_unreal_tree() -> None:
    text = (REPO / ".lfsconfig").read_text(encoding="utf-8")
    assert "fetchexclude = unreal/**" in text


def test_the_release_source_archive_carries_no_unreal_path(tmp_path: Path) -> None:
    attr = subprocess.run(
        [
            "git",
            "-C",
            str(REPO),
            "check-attr",
            "export-ignore",
            "--",
            "unreal/Verse/Verse.uproject",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert attr.stdout.strip().endswith("export-ignore: set")
    archive = tmp_path / "src.tar"
    subprocess.run(
        [
            "git",
            "-C",
            str(REPO),
            "archive",
            "--format=tar",
            "-o",
            str(archive),
            "HEAD",
            "--",
            "unreal",
            "install",
        ],
        check=True,
    )
    with tarfile.open(archive) as handle:
        names = handle.getnames()
    assert names and not [n for n in names if n.startswith("unreal")]


def test_install_scripts_set_git_lfs_skip_smudge_before_any_clone() -> None:
    ps1 = (REPO / "install/install.ps1").read_text(encoding="utf-8")
    sh = (REPO / "install/install.sh").read_text(encoding="utf-8")
    first_ps1_git = min(ps1.index("& git @GitNetOpts"), ps1.index("& git -C"))
    assert ps1.index("$env:GIT_LFS_SKIP_SMUDGE = '1'") < first_ps1_git
    assert sh.index("export GIT_LFS_SKIP_SMUDGE") < sh.index("pretty_git git $GIT_NET_OPTS")


def test_follow_main_git_calls_skip_lfs_smudge(monkeypatch, tmp_path: Path) -> None:
    from dodaios.core import main_follow

    seen: list[dict] = []

    def fake_run(args, **kwargs):
        seen.append(kwargs["env"])
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(main_follow.subprocess, "run", fake_run)
    main_follow._git(["fetch", "--quiet", "origin", "main"], tmp_path)
    main_follow._git_write(["merge", "--ff-only", "origin/main"], tmp_path)
    assert [env.get("GIT_LFS_SKIP_SMUDGE") for env in seen] == ["1", "1"]


def test_update_route_git_calls_skip_lfs_smudge(monkeypatch, tmp_path: Path) -> None:
    from dodaios.ui.web import update_routes

    seen: list[dict | None] = []

    async def fake_run(cmd, *, cwd, timeout_s, on_stderr_line=None, env=None):
        seen.append(env)
        return 0, "", ""

    monkeypatch.setattr(update_routes, "_run", fake_run)
    asyncio.run(update_routes._git(["fetch", "origin"], cwd=tmp_path))
    assert seen and seen[0]["GIT_LFS_SKIP_SMUDGE"] == "1"


@pytest.mark.skipif(shutil.which("git-lfs") is None, reason="git-lfs is not installed")
def test_a_clone_with_the_installer_setting_downloads_no_lfs_object(tmp_path: Path) -> None:
    """A repo whose ``unreal/**`` holds an LFS pointer to an object no server has.

    With ``GIT_LFS_SKIP_SMUDGE=1`` the clone succeeds and keeps the pointer:
    zero bytes of the object were asked for. Without it, smudging tries to
    fetch the object and the checkout fails.
    """
    origin = tmp_path / "origin"
    (origin / "unreal/Verse/Content").mkdir(parents=True)
    env = dict(
        os.environ,
        GIT_CONFIG_NOSYSTEM="1",
        HOME=str(tmp_path),
        GIT_AUTHOR_NAME="t",
        GIT_AUTHOR_EMAIL="t@example.invalid",
        GIT_COMMITTER_NAME="t",
        GIT_COMMITTER_EMAIL="t@example.invalid",
    )
    lfs = [
        "-c",
        "filter.lfs.smudge=git-lfs smudge -- %f",
        "-c",
        "filter.lfs.process=git-lfs filter-process",
        "-c",
        "filter.lfs.required=true",
        "-c",
        "core.hooksPath=" + str(tmp_path / "nohooks"),
    ]

    def git(*args: str, cwd: Path, extra: dict | None = None, check: bool = True):
        return subprocess.run(
            ["git", *lfs, *args],
            cwd=cwd,
            env={**env, **(extra or {})},
            capture_output=True,
            text=True,
            check=check,
        )

    git("init", "-q", "-b", "main", cwd=origin)
    (origin / ".gitattributes").write_text(
        "*.uasset filter=lfs diff=lfs merge=lfs -text\n", encoding="utf-8"
    )
    (origin / "readme.txt").write_text("app\n", encoding="utf-8")
    git("add", ".gitattributes", "readme.txt", cwd=origin)
    # Store the pointer itself as the blob (no clean filter), as LFS would.
    blob = subprocess.run(
        ["git", "hash-object", "-w", "--stdin"],
        cwd=origin,
        env=env,
        input=POINTER,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    git(
        "update-index",
        "--add",
        "--cacheinfo",
        f"100644,{blob},unreal/Verse/Content/Big.uasset",
        cwd=origin,
    )
    git("commit", "-q", "-m", "init", cwd=origin)

    skipped = tmp_path / "skipped"
    done = git(
        "clone",
        "-q",
        "--depth",
        "1",
        origin.as_uri(),
        str(skipped),
        cwd=tmp_path,
        extra={"GIT_LFS_SKIP_SMUDGE": "1"},
        check=False,
    )
    assert done.returncode == 0, done.stderr
    content = (skipped / "unreal/Verse/Content/Big.uasset").read_text(encoding="utf-8")
    assert content.replace("\r\n", "\n") == POINTER

    smudged = tmp_path / "smudged"
    done = git(
        "clone", "-q", "--depth", "1", origin.as_uri(), str(smudged), cwd=tmp_path, check=False
    )
    assert done.returncode != 0  # it tried to download the object
