"""A stand-in for Claude Code in stream-json mode, for the replay tests. No model.

    python fake_claude.py <mode> <out-dir> [claude's own arguments...]

It writes its arguments to ``argv.json``, reads the control handshake and the
user message from stdin (``stdin.jsonl``), then plays a turn:

* ``tool``: a line of text, a schema load (``ToolSearch``), a permission prompt
  whose answer it writes to ``answer.json``, then a call of the app's
  ``delegate`` tool; then it waits and, if nobody stopped it, writes
  ``ran-on.txt`` (what a tool run after the first move would be);
* ``text``: a text answer and the end of the turn;
* ``model``: like ``tool``, but on another model than it was asked for.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path


def emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main() -> int:
    mode, out = sys.argv[1], Path(sys.argv[2])
    args = sys.argv[3:]
    (out / "argv.json").write_text(json.dumps(args), encoding="utf-8")
    lines = [sys.stdin.readline(), sys.stdin.readline()]
    (out / "stdin.jsonl").write_text("".join(lines), encoding="utf-8")
    asked = args[args.index("--model") + 1] if "--model" in args else ""
    model = "another-model" if mode == "model" else f"{asked}-20991231"
    emit({"type": "system", "subtype": "init", "model": model, "session_id": "s1"})
    emit(
        {
            "type": "stream_event",
            "event": {"type": "message_start", "message": {"id": "m1"}},
        }
    )
    emit(
        {
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "On it: Scout researches the apps."},
            },
        }
    )
    if mode == "text":
        emit(
            {
                "type": "assistant",
                "message": {
                    "id": "m1",
                    "model": model,
                    "content": [{"type": "text", "text": "On it: Scout researches the apps."}],
                },
            }
        )
        emit({"type": "result", "subtype": "success", "result": "done", "session_id": "s1"})
        time.sleep(30)
        return 0
    emit(
        {
            "type": "assistant",
            "message": {
                "id": "m1",
                "model": model,
                "content": [
                    {"type": "text", "text": "On it: Scout researches the apps."},
                    {
                        "type": "tool_use",
                        "id": "t0",
                        "name": "ToolSearch",
                        "input": {"query": "select:mcp__dodaios__delegate"},
                    },
                ],
            },
        }
    )
    emit(
        {
            "type": "control_request",
            "request_id": "r1",
            "request": {"subtype": "can_use_tool", "tool_name": "Write", "input": {}},
        }
    )
    (out / "answer.json").write_text(sys.stdin.readline(), encoding="utf-8")
    emit(
        {
            "type": "assistant",
            "message": {
                "id": "m2",
                "model": model,
                "content": [
                    {
                        "type": "tool_use",
                        "id": "t1",
                        "name": "mcp__dodaios__delegate",
                        "input": {"target": "agent:Scout", "task": "compare note apps"},
                    }
                ],
            },
        }
    )
    time.sleep(20)
    (out / "ran-on.txt").write_text("the turn went on past its first move", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
