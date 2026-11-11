"""Installs and updates never download Git LFS objects.

Older releases carry LFS pointers for large binaries. An install pinned to
one of them, an update across them or a rollback onto them must keep the
pointers instead of pulling the objects.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def test_install_scripts_set_git_lfs_skip_smudge_before_any_clone() -> None:
    ps1 = (REPO / "install/install.ps1").read_text(encoding="utf-8")
    sh = (REPO / "install/install.sh").read_text(encoding="utf-8")
    first_ps1_git = min(ps1.index("& git @GitNetOpts"), ps1.index("& git -C"))
    assert ps1.index("$env:GIT_LFS_SKIP_SMUDGE = '1'") < first_ps1_git
    assert sh.index("export GIT_LFS_SKIP_SMUDGE") < sh.index("pretty_git git $GIT_NET_OPTS")


def test_install_scripts_drop_git_lfs_skip_smudge_before_the_hand_off() -> None:
    ps1 = (REPO / "install/install.ps1").read_text(encoding="utf-8")
    sh = (REPO / "install/install.sh").read_text(encoding="utf-8")
    ps1_drop = ps1.index("Remove-Item Env:GIT_LFS_SKIP_SMUDGE")
    sh_drop = sh.index("unset GIT_LFS_SKIP_SMUDGE")
    # After the last git call of the shell stage, before installer.py runs.
    assert ps1.rindex("& git ") < ps1_drop < ps1.index("& $VenvPython $InstallerPy")
    assert (
        sh.rindex('git -C "$INSTALL_DIR"')
        < sh_drop
        < sh.index('exec "$VENV_PYTHON" "$INSTALLER_PY"')
    )


def test_app_launch_env_has_no_git_lfs_skip_smudge() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_installer_under_test", REPO / "install/installer.py"
    )
    assert spec and spec.loader
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    env = installer.app_launch_env({"GIT_LFS_SKIP_SMUDGE": "1", "PATH": "x"})
    assert "GIT_LFS_SKIP_SMUDGE" not in env
    assert env["PATH"] == "x"


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
