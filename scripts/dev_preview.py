#!/usr/bin/env python3
"""Load a pull request or a branch into the Dodaios Dev app.

The person's own Dodaios app always runs ``main`` from the main checkout.
Pull requests and branches are tried in the Dev app (``--instance dev``), a
second desktop app with its own data and ports, started from ONE reused
preview worktree. Loading the next pull request replaces the previous one.

    python scripts/dev_preview.py 1423       # pull request #1423
    python scripts/dev_preview.py feat/x     # a branch on origin
    python scripts/dev_preview.py main       # current origin/main
    python scripts/dev_preview.py --stop     # close the Dev app

See docs/dev-preview.md.
"""

from __future__ import annotations

import argparse
import filecmp
import json
import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

PREVIEW_DIR = Path(".claude") / "worktrees" / "dev-preview"
PREVIEW_REF = "refs/dev-preview/head"
FRONTEND = Path("dodaios") / "ui" / "web" / "frontend"
DIST = Path("dodaios") / "ui" / "web" / "dist"
DEV_DATA_DIR = "data-dev"
RUNNING_META = ".jarvis-running"
DEV_STATE_SUFFIX = ".dev.json"
HELPER_MODULES = ("dodaios.agent_chat.turn_host", "dodaios.terminal.pty_host")
BOOT_TIMEOUT_S = 240
IS_WINDOWS = os.name == "nt"


def _git(*args: str, cwd: Path) -> str:
    out = subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    )
    return out.stdout.strip()


def main_checkout(start: Path) -> Path:
    """The main checkout, also when this runs from a linked worktree."""
    common = _git("rev-parse", "--path-format=absolute", "--git-common-dir", cwd=start)
    return Path(common).parent


def fetch_spec(target: str) -> str:
    """The refspec that fetches ``target`` into :data:`PREVIEW_REF`."""
    target = target.strip().lstrip("#")
    source = f"refs/pull/{target}/head" if target.isdigit() else f"refs/heads/{target}"
    return f"+{source}:{PREVIEW_REF}"


def is_dev_process(cmdline: list[str]) -> bool:
    """True for the Dev app's launcher or one of its own helper hosts.

    The launcher carries ``--instance dev``; its helper hosts carry a
    ``--state`` file that ends in ``.dev.json``. The default app's processes
    match neither, so they are never touched.
    """
    joined = " ".join(cmdline)
    if "dodaios.ui.web.launcher" in joined:
        for i, arg in enumerate(cmdline):
            if arg == "--instance" and i + 1 < len(cmdline) and cmdline[i + 1] == "dev":
                return True
            if arg == "--instance=dev":
                return True
        return False
    if any(module in joined for module in HELPER_MODULES):
        for i, arg in enumerate(cmdline):
            if arg == "--state" and i + 1 < len(cmdline):
                return cmdline[i + 1].endswith(DEV_STATE_SUFFIX)
    return False


def _read_meta(data_dir: Path) -> dict:
    try:
        return json.loads((data_dir / RUNNING_META).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def stop_dev_app() -> int:
    """Stop the Dev app and its helper hosts. Returns how many processes ended."""
    import psutil

    victims = []
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            if proc.pid != os.getpid() and is_dev_process(proc.info["cmdline"] or []):
                victims.append(proc)
        except (psutil.Error, TypeError):
            continue
    tree = []
    for proc in victims:
        try:
            tree.extend(proc.children(recursive=True))
        except psutil.Error:
            pass
        tree.append(proc)
    for proc in tree:
        try:
            proc.terminate()
        except psutil.Error:
            pass
    _, alive = psutil.wait_procs(tree, timeout=15)
    for proc in alive:
        try:
            proc.kill()
        except psutil.Error:
            pass
    return len(victims)


def prepare_worktree(repo: Path, target: str) -> tuple[Path, str]:
    """Fetch ``target`` and put the preview worktree on it. Returns (path, sha)."""
    _git("fetch", "--quiet", "origin", fetch_spec(target), cwd=repo)
    sha = _git("rev-parse", PREVIEW_REF, cwd=repo)
    wt = repo / PREVIEW_DIR
    if (wt / ".git").exists():
        _git("checkout", "--quiet", "--force", "--detach", sha, cwd=wt)
    else:
        _git("worktree", "add", "--quiet", "--detach", str(wt), sha, cwd=repo)
    return wt, sha


def _is_link(path: Path) -> bool:
    try:
        st = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(st.st_mode):
        return True
    attrs = getattr(st, "st_file_attributes", 0)
    return bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _unlink_dir_link(path: Path) -> None:
    # A junction is removed with rmdir; this never touches the target's files.
    if IS_WINDOWS:
        os.rmdir(path)
    else:
        os.unlink(path)


def _npm(*args: str, cwd: Path) -> None:
    npm = shutil.which("npm") or "npm"
    subprocess.run([npm, *args], cwd=cwd, check=True)


def ensure_node_modules(repo: Path, wt: Path) -> str:
    """Borrow the main checkout's node_modules when the lockfiles match."""
    fe = wt / FRONTEND
    main_fe = repo / FRONTEND
    link = fe / "node_modules"
    same_lock = (main_fe / "node_modules").is_dir() and filecmp.cmp(
        fe / "package-lock.json", main_fe / "package-lock.json", shallow=False
    )
    if same_lock:
        if _is_link(link) or link.exists():
            return "node_modules: shared with the main checkout"
        if IS_WINDOWS:
            subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(main_fe / "node_modules")],
                check=True,
                capture_output=True,
            )
        else:
            link.symlink_to(main_fe / "node_modules", target_is_directory=True)
        return "node_modules: shared with the main checkout"
    if _is_link(link):
        # Never let npm install into the main checkout's node_modules.
        _unlink_dir_link(link)
    _npm("ci", "--no-audit", "--no-fund", cwd=fe)
    return "node_modules: own install (the lockfile differs from main)"


def build_frontend(wt: Path) -> str:
    """Build the bundle unless this frontend tree was built already."""
    tree = _git("rev-parse", f"HEAD:{FRONTEND.as_posix()}", cwd=wt)
    marker = Path(_git("rev-parse", "--absolute-git-dir", cwd=wt)) / "dev-preview-frontend"
    built = marker.read_text(encoding="utf-8").strip() if marker.exists() else ""
    if built == tree and (wt / DIST / "index.html").exists():
        return "frontend: unchanged since the last load, build skipped"
    _npm("run", "build", cwd=wt / FRONTEND)
    marker.write_text(tree, encoding="utf-8")
    return "frontend: built"


def app_interpreter(repo: Path) -> str:
    """The interpreter of the running default app, else this one.

    The default app may run from an app bundle (macOS): its executable is the
    bundle's launcher, which takes neither ``-c`` nor ``-m``. Then this
    interpreter starts the Dev app.
    """
    pid = _read_meta(repo / "data").get("pid")
    if pid:
        try:
            import psutil

            exe = psutil.Process(int(pid)).exe()
        except Exception as exc:
            print(f"default app interpreter unknown ({exc}); using {sys.executable}")
        else:
            if is_python(exe):
                return exe
            print(f"the default app runs from {exe}, not a Python; using {sys.executable}")
    return sys.executable


def is_python(exe: str) -> bool:
    """Whether ``exe`` runs Python code given on its command line.

    An interpreter under another name counts (the Windows app's
    ``DodaiosApp.exe`` is one), so the executable is asked, not its name.
    """
    try:
        probe = subprocess.run(
            [exe, "-c", "import sys"], capture_output=True, timeout=30, check=False,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return probe.returncode == 0


def launch(repo: Path, wt: Path, exe: str) -> int:
    data_dir = repo / DEV_DATA_DIR
    data_dir.mkdir(exist_ok=True)
    env = dict(os.environ)
    env["JARVIS_DATA_DIR"] = str(data_dir)
    env["JARVIS_INSTANCE"] = "dev"
    env.pop("PYTHONPATH", None)
    origin = subprocess.run(
        [exe, "-c", "import dodaios; print(dodaios.__file__)"],
        cwd=wt, env=env, capture_output=True, text=True, check=True,
    ).stdout.strip()
    if not Path(origin).resolve().is_relative_to(wt.resolve()):
        raise SystemExit(f"the Dev app would load {origin}, not the preview worktree")
    log = open(data_dir / "dev_preview.log", "ab")  # noqa: SIM115 - handed to the child
    flags = 0
    if IS_WINDOWS:
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    proc = subprocess.Popen(
        [exe, "-m", "dodaios.ui.web.launcher", "--instance", "dev"],
        cwd=wt, env=env, stdout=log, stderr=log, stdin=subprocess.DEVNULL,
        creationflags=flags, start_new_session=not IS_WINDOWS,
    )
    log_path = data_dir / "dev_preview.log"
    started = time.time() - 1
    deadline = time.monotonic() + BOOT_TIMEOUT_S
    while time.monotonic() < deadline:
        # The launcher may re-exec itself, so the app's own record of its pid
        # and port counts, not the pid started here.
        meta = _read_meta(data_dir)
        if meta.get("port") and float(meta.get("started_at") or 0) >= started:
            return int(meta["pid"])
        if proc.poll() not in (None, 0):
            raise SystemExit(f"the Dev app exited during boot; see {log_path}")
        time.sleep(1)
    raise SystemExit(f"the Dev app did not come up in {BOOT_TIMEOUT_S} s; see {log_path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("target", nargs="?", help="pull request number, branch name, or main")
    parser.add_argument("--stop", action="store_true", help="close the Dev app")
    parser.add_argument("--no-build", action="store_true", help="skip the frontend build")
    args = parser.parse_args(argv)
    if not args.stop and not args.target:
        parser.error("name a pull request or a branch, or pass --stop")

    repo = main_checkout(Path.cwd())
    stopped = stop_dev_app()
    print(f"Dev app: stopped {stopped} process(es)")
    if args.stop:
        return 0

    wt, sha = prepare_worktree(repo, args.target)
    print(f"preview worktree: {wt} at {sha[:10]}")
    if not args.no_build:
        print(ensure_node_modules(repo, wt))
        print(build_frontend(wt))
    pid = launch(repo, wt, app_interpreter(repo))
    branch = _git("rev-parse", "--abbrev-ref", "HEAD", cwd=repo)
    print(f"Dodaios Dev runs {args.target} ({sha[:10]}), pid {pid}. Window: 'Dodaios Dev'.")
    print(f"Your own Dodaios app is untouched; the main checkout is on '{branch}'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
