"""The legacy Codex worker sends its prompt on stdin, never on argv."""

from __future__ import annotations

from pathlib import Path

from dodaios.missions.workers.codex_worker import _build_codex_cmd


def test_a_long_prompt_never_rides_on_the_command_line() -> None:
    prompt = "x" * 200_000
    cmd = _build_codex_cmd(
        prompt, sandbox="workspace-write", ask_for_approval="never", output_schema=None
    )
    assert prompt not in cmd
    assert cmd[-1] == "-"
    assert sum(len(part) + 1 for part in cmd) < 1000


def test_spawn_writes_the_prompt_to_stdin() -> None:
    source = Path("dodaios/missions/workers/codex_worker.py").read_text(encoding="utf-8")
    assert "stdin=asyncio.subprocess.PIPE" in source
    assert "proc.stdin.write(prompt.encode" in source
