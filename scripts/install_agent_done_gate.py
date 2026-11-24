#!/usr/bin/env python3
"""Install the agent done gate's user-level Stop hooks (Codex, Kimi CLI).

Claude Code and OpenCode pick the gate up from the repository itself
(``.claude/settings.json``, ``.opencode/plugins/agent-done-gate.js``). Codex
trusts a hook per file path, so a hook in the repository would ask again in
every new worktree; Kimi CLI reads hooks only from the user config. For those
two this script copies ``scripts/agent_done_gate_launcher.py`` to
``~/.agent-done-gate/hook.py`` and registers it as their Stop hook.

A user-level hook fires in every folder, so the launcher runs the gate of a
registered checkout only. This script registers the primary checkout it is
run from in ``~/.agent-done-gate/repos.json``; the launcher runs that
checkout's ``scripts/agent_done_gate.py`` for the checkout and its linked
worktrees, and nothing for any other repository. Running it again on a
machine set up before the registry existed replaces the launcher and adds
the registration.

    python scripts/install_agent_done_gate.py            # install / refresh
    python scripts/install_agent_done_gate.py --check    # report only
    python scripts/install_agent_done_gate.py --uninstall

Idempotent; it never touches other hooks. Codex asks once to trust the new
hook (``/hooks`` in the Codex TUI).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MARKER = ".agent-done-gate"
REGISTRY_NAME = "repos.json"


def home() -> Path:
    return Path(os.environ.get("AGENT_DONE_GATE_HOME") or Path.home())


def launcher_path() -> Path:
    return home() / MARKER / "hook.py"


def registry_path() -> Path:
    return home() / MARKER / REGISTRY_NAME


def same_path(path: str | Path) -> str:
    """A form of ``path`` two spellings of one folder share (as in the launcher)."""
    return os.path.normcase(os.path.realpath(str(path)))


def primary_checkout(root: Path | None = None) -> Path:
    """The checkout whose gate the launcher runs for this repository: the
    parent of the git common dir, so a run from a linked worktree registers
    the checkout that worktree belongs to. Without git, or in a layout with
    no such checkout, the folder this script lives in."""
    root = REPO_ROOT if root is None else root
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--path-format=absolute", "--git-common-dir"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return root
    common = Path(proc.stdout.strip()) if proc.returncode == 0 and proc.stdout.strip() else None
    if common is None or common.name != ".git":
        return root
    return common.parent


def registered_repos() -> list[str]:
    """The registered checkouts as written; an unreadable registry is empty."""
    try:
        data = json.loads(registry_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    repos = data.get("repos") if isinstance(data, dict) else None
    if not isinstance(repos, list):
        return []
    return [item for item in repos if isinstance(item, str) and item]


def is_registered(checkout: Path) -> bool:
    return same_path(checkout) in {same_path(item) for item in registered_repos()}


def write_registry(repos: list[str]) -> None:
    path = registry_path()
    if not repos:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"repos": repos}, indent=2) + "\n", encoding="utf-8")


def register(checkout: Path) -> bool:
    """Add ``checkout`` to the registry; True when the file changed."""
    if is_registered(checkout):
        return False
    write_registry(sorted({*registered_repos(), checkout.resolve().as_posix()}))
    return True


def unregister(checkout: Path) -> bool:
    """Take ``checkout`` out of the registry; True when the file changed."""
    kept = [item for item in registered_repos() if same_path(item) != same_path(checkout)]
    if len(kept) == len(registered_repos()):
        return False
    write_registry(kept)
    return True


def python_command() -> str:
    """An interpreter call that works from cmd, PowerShell and sh alike."""
    if sys.platform == "win32" and shutil.which("py"):
        return "py -3"
    exe = sys.executable
    return f'"{exe}"' if " " in exe else exe


def hook_command(dialect: str) -> str:
    return f'{python_command()} "{launcher_path().as_posix()}" {dialect}'


# --------------------------------------------------------------------------
# Codex: ~/.codex/hooks.json
# --------------------------------------------------------------------------


def codex_file() -> Path:
    return home() / ".codex" / "hooks.json"


def codex_install(data: dict) -> tuple[dict, bool]:
    hooks = data.setdefault("hooks", {})
    stop = hooks.setdefault("Stop", [])
    wanted = {"type": "command", "command": hook_command("codex"), "timeout": 600}
    for group in stop:
        for hook in group.get("hooks", []):
            if MARKER in str(hook.get("command", "")):
                if hook == wanted:
                    return data, False
                hook.clear()
                hook.update(wanted)
                return data, True
    stop.append({"hooks": [wanted]})
    return data, True


def codex_uninstall(data: dict) -> tuple[dict, bool]:
    stop = (data.get("hooks") or {}).get("Stop") or []
    changed = False
    for group in stop:
        before = len(group.get("hooks", []))
        group["hooks"] = [h for h in group.get("hooks", []) if MARKER not in str(h.get("command"))]
        changed |= len(group["hooks"]) != before
    data.get("hooks", {})["Stop"] = [g for g in stop if g.get("hooks")]
    if not data.get("hooks", {}).get("Stop"):
        data.get("hooks", {}).pop("Stop", None)
    return data, changed


# --------------------------------------------------------------------------
# Kimi CLI: ~/.kimi-code/config.toml (older builds: ~/.kimi/config.toml)
# --------------------------------------------------------------------------


def kimi_file() -> Path | None:
    for folder in (".kimi-code", ".kimi"):
        path = home() / folder / "config.toml"
        if path.is_file():
            return path
    return None


def _toml_string(value: str) -> str:
    return json.dumps(value)  # a JSON string is a valid TOML basic string


KIMI_BEGIN = f"# {MARKER} begin: an agent stops only when its work has landed"
KIMI_END = f"# {MARKER} end"


def kimi_block() -> str:
    return "\n".join(
        [
            "",
            KIMI_BEGIN,
            "[[hooks]]",
            'event = "Stop"',
            f"command = {_toml_string(hook_command('kimi'))}",
            "timeout = 600",
            KIMI_END,
            "",
        ]
    )


def kimi_strip(text: str) -> str:
    """The config without our block (between the begin and end comments)."""
    pattern = re.compile(rf"\n?{re.escape(KIMI_BEGIN)}\n.*?{re.escape(KIMI_END)}\n?", re.S)
    return pattern.sub("\n", text).rstrip("\n") + "\n"


# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--uninstall", action="store_true")
    args = parser.parse_args(argv)

    launcher = launcher_path()
    source = REPO_ROOT / "scripts" / "agent_done_gate_launcher.py"
    checkout = primary_checkout()
    report: list[str] = []

    if args.uninstall:
        if launcher.exists() and not args.check:
            launcher.unlink()
        report.append(f"launcher removed: {launcher}")
        if is_registered(checkout) and not args.check:
            unregister(checkout)
        report.append(f"gate no longer runs for: {checkout}")
    elif args.check:
        same = launcher.is_file() and launcher.read_bytes() == source.read_bytes()
        report.append(f"launcher {'current' if same else 'missing or stale'}: {launcher}")
        known = is_registered(checkout)
        state = "registered" if known else "NOT registered (its gate does not run)"
        report.append(f"checkout {state}: {checkout}")
    else:
        launcher.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, launcher)
        report.append(f"launcher installed: {launcher}")
        added = register(checkout)
        report.append(f"checkout {'registered' if added else 'already registered'}: {checkout}")

    codex = codex_file()
    if codex.parent.is_dir():
        try:
            data = json.loads(codex.read_text("utf-8")) if codex.is_file() else {}
        except ValueError:
            data = None
        if data is None:
            report.append(f"codex: {codex} is not valid JSON; left alone")
        else:
            change = codex_uninstall if args.uninstall else codex_install
            data, changed = change(data)
            if changed and not args.check:
                codex.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            state = "would change" if args.check and changed else ("updated" if changed else "ok")
            report.append(f"codex: {codex} {state}")
            if changed and not args.uninstall and not args.check:
                report.append("codex: trust the new Stop hook once (`/hooks` in the Codex TUI)")
    else:
        report.append("codex: not installed")

    kimi = kimi_file()
    if kimi is not None:
        text = kimi.read_text("utf-8")
        new = kimi_strip(text) if MARKER in text else text
        if not args.uninstall:
            new = new.rstrip("\n") + "\n" + kimi_block()
        changed = new != text
        if changed and not args.check:
            kimi.write_text(new, encoding="utf-8")
        state = "would change" if args.check and changed else ("updated" if changed else "ok")
        report.append(f"kimi: {kimi} {state}")
    else:
        report.append("kimi: not installed")

    print("\n".join(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
