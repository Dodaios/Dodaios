#!/usr/bin/env python3
"""Install the agent done gate's user-level Stop hooks (Codex, Kimi CLI).

Claude Code and OpenCode pick the gate up from the repository itself
(``.claude/settings.json``, ``.opencode/plugins/agent-done-gate.js``). Codex
trusts a hook per file path, so a hook in the repository would ask again in
every new worktree; Kimi CLI reads hooks only from the user config. For those
two this script copies ``scripts/agent_done_gate_launcher.py`` to
``~/.agent-done-gate/hook.py`` and registers it as their Stop hook.

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
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MARKER = ".agent-done-gate"


def home() -> Path:
    return Path(os.environ.get("AGENT_DONE_GATE_HOME") or Path.home())


def launcher_path() -> Path:
    return home() / MARKER / "hook.py"


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
    report: list[str] = []

    if args.uninstall:
        if launcher.exists() and not args.check:
            launcher.unlink()
        report.append(f"launcher removed: {launcher}")
    elif args.check:
        same = launcher.is_file() and launcher.read_bytes() == source.read_bytes()
        report.append(f"launcher {'current' if same else 'missing or stale'}: {launcher}")
    else:
        launcher.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, launcher)
        report.append(f"launcher installed: {launcher}")

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
