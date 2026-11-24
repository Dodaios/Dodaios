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

Loading a pull request runs its code on this machine: its npm scripts, its
build and its app, with the accounts of whoever runs this. So a pull request
is loaded only when its head commit is the tip of a branch of ``origin``
(only someone with push access puts it there) and, where ``gh`` answers,
when it comes from this repository and its author is an owner, member or
collaborator. Any other pull request is refused before anything of it is
checked out. ``--run-untrusted-code`` lifts the refusal for a person who has
read every changed file; an agent never passes it. Such a load never shares
the main checkout's ``node_modules``.

See docs/dev-preview.md.
"""

from __future__ import annotations

import argparse
import filecmp
import json
import os
import re
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
#: GitHub's ``author_association`` values of people who may push here.
TRUSTED_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})
UNTRUSTED_FLAG = "--run-untrusted-code"
#: The merge queue's own branches hold whatever was queued, forks included.
QUEUE_BRANCH_PREFIX = "refs/heads/gh-readonly-queue/"
_GITHUB_URL = re.compile(r"(?:^|[/@])github\.com[:/]+([\w.-]+)/([\w.-]+?)(?:\.git)?/?$")


def _git(*args: str, cwd: Path) -> str:
    out = subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    )
    return out.stdout.strip()


def main_checkout(start: Path) -> Path:
    """The main checkout, also when this runs from a linked worktree."""
    common = _git("rev-parse", "--path-format=absolute", "--git-common-dir", cwd=start)
    return Path(common).parent


def pull_request_number(target: str) -> str | None:
    """The number when ``target`` names a pull request, else ``None`` (a branch)."""
    target = target.strip().lstrip("#")
    return target if target.isdigit() else None


def fetch_spec(target: str) -> str:
    """The refspec that fetches ``target`` into :data:`PREVIEW_REF`."""
    number = pull_request_number(target)
    name = target.strip().lstrip("#")
    source = f"refs/pull/{number}/head" if number else f"refs/heads/{name}"
    return f"+{source}:{PREVIEW_REF}"


def _answer(cmd: list[str], cwd: Path, timeout: float = 120) -> str | None:
    """The output of a lookup, or ``None`` when it gave no answer."""
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout if proc.returncode == 0 else None


def on_origin_branch(repo: Path, sha: str) -> bool:
    """Whether ``sha`` is the tip of a branch of ``origin``.

    Only someone with push access puts a commit on a branch of this
    repository, and the head of a pull request from it is the tip of its
    branch. The head of a fork's pull request is on none. ``origin`` is asked
    now; no answer counts as no, so the check fails closed without a network.
    """
    listed = _answer(["git", "ls-remote", "--heads", "origin"], repo)
    for line in (listed or "").splitlines():
        tip, _, ref = line.partition("\t")
        if tip == sha and ref and not ref.startswith(QUEUE_BRANCH_PREFIX):
            return True
    return False


def origin_slug(repo: Path) -> str:
    """``owner/name`` of ``origin`` when it is on GitHub, else ``""``."""
    url = (_answer(["git", "remote", "get-url", "origin"], repo, 30) or "").strip()
    match = _GITHUB_URL.search(url)
    return f"{match.group(1)}/{match.group(2)}" if match else ""


def pull_request_facts(repo: Path, number: str) -> dict | None:
    """What GitHub says about the pull request, or ``None`` when ``gh`` does not answer."""
    gh, slug = shutil.which("gh"), origin_slug(repo)
    if not gh or not slug:
        return None
    query = (
        "{association: .author_association, head: .head.repo.full_name, "
        "base: .base.repo.full_name, sha: .head.sha}"
    )
    out = _answer([gh, "api", f"repos/{slug}/pulls/{number}", "--jq", query], repo, 60)
    try:
        facts = json.loads(out or "")
    except ValueError:
        return None
    return facts if isinstance(facts, dict) else None


def refusal(sha: str, *, on_branch: bool, facts: dict | None) -> str | None:
    """Why a pull request's code must not run here; ``None`` when it may.

    ``on_branch``: its head is the tip of a branch of ``origin``. ``facts``:
    GitHub's answer, ``None`` when there was none; then the branch check
    alone decides.
    """
    if not on_branch:
        return "its head commit is on no branch of this repository"
    if facts is None:
        return None
    if not facts.get("head") or facts.get("head") != facts.get("base"):
        return "it comes from another repository"
    association = str(facts.get("association") or "unknown")
    if association not in TRUSTED_ASSOCIATIONS:
        return f"its author is {association}, not an owner, member or collaborator"
    if facts.get("sha") != sha:
        return "it moved while it was being loaded; run the command again"
    return None


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


def prepare_worktree(
    repo: Path, target: str, *, run_untrusted: bool = False
) -> tuple[Path, str, bool]:
    """Fetch ``target`` and put the preview worktree on it.

    Returns (path, sha, trusted). A pull request whose code must not run
    here (:func:`refusal`) ends the run before anything of it is checked
    out, unless ``run_untrusted`` says a person decided otherwise; then
    ``trusted`` is False. A branch of ``origin`` is always trusted.
    """
    _git("fetch", "--quiet", "origin", fetch_spec(target), cwd=repo)
    sha = _git("rev-parse", PREVIEW_REF, cwd=repo)
    trusted = True
    number = pull_request_number(target)
    if number:
        why = refusal(
            sha, on_branch=on_origin_branch(repo, sha), facts=pull_request_facts(repo, number)
        )
        if why and not run_untrusted:
            raise SystemExit(
                f"pull request #{number} is not loaded: {why}.\n"
                "Loading it would run its code on this machine with your accounts. "
                "Read it on GitHub instead.\n"
                f"Only a person who has read every changed file may pass {UNTRUSTED_FLAG}; "
                "an agent never does (docs/dev-preview.md)."
            )
        if why:
            trusted = False
            print(f"WARNING: pull request #{number}: {why}. Its code runs on this machine now.")
    wt = repo / PREVIEW_DIR
    if not trusted:
        # Before any of that code is in the tree: no way into the main checkout.
        drop_shared_node_modules(wt)
    if (wt / ".git").exists():
        _git("checkout", "--quiet", "--force", "--detach", sha, cwd=wt)
    else:
        _git("worktree", "add", "--quiet", "--detach", str(wt), sha, cwd=repo)
    return wt, sha, trusted


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


def drop_shared_node_modules(wt: Path) -> None:
    """Take the link into the main checkout's node_modules out of ``wt``, if it has one."""
    link = wt / FRONTEND / "node_modules"
    if _is_link(link):
        _unlink_dir_link(link)


def _npm(*args: str, cwd: Path) -> None:
    npm = shutil.which("npm") or "npm"
    subprocess.run([npm, *args], cwd=cwd, check=True)


def ensure_node_modules(repo: Path, wt: Path, *, share: bool = True) -> str:
    """Borrow the main checkout's node_modules when the lockfiles match.

    ``share=False`` (code from outside the repository): never. A link into
    the main checkout would let that code's install and build write into
    the folder the person's own app is built from, so the link of an
    earlier load is taken away and the tree gets an install of its own.
    """
    fe = wt / FRONTEND
    main_fe = repo / FRONTEND
    link = fe / "node_modules"
    same_lock = (
        share
        and (main_fe / "node_modules").is_dir()
        and filecmp.cmp(fe / "package-lock.json", main_fe / "package-lock.json", shallow=False)
    )
    if same_lock and not _is_link(link) and link.exists():
        # An install of an earlier load, made from another lockfile or by code
        # from outside: not the main checkout's, so never passed off as it.
        shutil.rmtree(link, ignore_errors=True)
        same_lock = not link.exists()
    if same_lock:
        if _is_link(link):
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
    if not share:
        return "node_modules: own install (code from outside never shares the main checkout's)"
    return "node_modules: own install (the lockfile differs from main)"


def build_frontend(wt: Path, *, remember: bool = True) -> str:
    """Build the bundle unless this frontend tree was built already.

    ``remember=False`` (code from outside the repository): always build, and
    leave no record, so no later load takes over a bundle that code built.
    """
    tree = _git("rev-parse", f"HEAD:{FRONTEND.as_posix()}", cwd=wt)
    marker = Path(_git("rev-parse", "--absolute-git-dir", cwd=wt)) / "dev-preview-frontend"
    built = marker.read_text(encoding="utf-8").strip() if marker.exists() else ""
    if remember and built == tree and (wt / DIST / "index.html").exists():
        return "frontend: unchanged since the last load, build skipped"
    marker.unlink(missing_ok=True)
    _npm("run", "build", cwd=wt / FRONTEND)
    if remember:
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
    parser.add_argument(
        UNTRUSTED_FLAG,
        action="store_true",
        help="load a pull request from outside the repository: its code runs on this "
        "machine with your accounts. For a person who has read every changed file; "
        "an agent never passes it.",
    )
    args = parser.parse_args(argv)
    if not args.stop and not args.target:
        parser.error("name a pull request or a branch, or pass --stop")

    repo = main_checkout(Path.cwd())
    stopped = stop_dev_app()
    print(f"Dev app: stopped {stopped} process(es)")
    if args.stop:
        return 0

    wt, sha, trusted = prepare_worktree(repo, args.target, run_untrusted=args.run_untrusted_code)
    print(f"preview worktree: {wt} at {sha[:10]}")
    if not args.no_build:
        print(ensure_node_modules(repo, wt, share=trusted))
        print(build_frontend(wt, remember=trusted))
    pid = launch(repo, wt, app_interpreter(repo))
    branch = _git("rev-parse", "--abbrev-ref", "HEAD", cwd=repo)
    print(f"Dodaios Dev runs {args.target} ({sha[:10]}), pid {pid}. Window: 'Dodaios Dev'.")
    print(f"Your own Dodaios app is untouched; the main checkout is on '{branch}'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
