"""A stand-in for Claude Code in stream-json mode, for the replay tests. No model.

    python fake_claude.py <mode> <out-dir> [claude's own arguments...]

It writes its arguments to ``argv.json``, reads the control handshake and the
user message from stdin (``stdin.jsonl``), then plays a turn:

* ``tool``: a line of text, a schema load (``ToolSearch``), a permission prompt
  whose answer it writes to ``answer.json``, then a call of the app's
  ``delegate`` tool; then it waits and, if nobody stopped it, writes
  ``ran-on.txt`` (what a tool run after the first move would be);
* ``text``: a text answer and the end of the turn;
* ``model``: like ``tool``, but on another model than it was asked for;
* ``brief``: asks for the brief kit (``delegate`` with ``options.prepare``), asks
  permission for it (the answer goes to ``answer.json``), and when it was allowed
  reads the kit as the replay's tool server would hand it over: the one answer
  file in the server's answers folder (``kit.txt``). Then it hands the work over
  with a brief that names ``dodaios/x.py``;
* ``look``: like ``brief``, but it searches the repository with ``Grep`` first
  (``look.txt`` gets the answer) instead of asking for the kit;
* ``hang``: starts, then thinks for 30 s without a move; if nobody stopped it,
  writes ``ran-on.txt``.
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
    if mode in ("brief", "look"):
        return brief(args, out, model, look=mode == "look")
    if mode == "hang":
        time.sleep(30)
        (out / "ran-on.txt").write_text("nobody stopped the replay", encoding="utf-8")
        return 0
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


KIT_CALL = {"target": "coding_agent", "task": "Fix the flicker", "options": {"prepare": True}}
BRIEF = "Stop the flicker when switching chats. Start in dodaios/x.py. Done: no flicker."


def _assistant(mid: str, model: str, content: list[dict]) -> None:
    emit({"type": "assistant", "message": {"id": mid, "model": model, "content": content}})


LOOK_CALL = {"pattern": "flicker", "path": ""}


def brief(args: list[str], out: Path, model: str, *, look: bool = False) -> int:
    config_file = Path(args[args.index("--mcp-config") + 1])
    (out / "mcp.json").write_text(config_file.read_text(encoding="utf-8"), encoding="utf-8")
    name, call = ("mcp__dodaios__Grep", LOOK_CALL) if look else ("mcp__dodaios__delegate", KIT_CALL)
    if look:
        # The lead searches its clone, which the test names in ``clone.txt``.
        call = {**LOOK_CALL, "path": (out / "clone.txt").read_text(encoding="utf-8").strip()}
    _assistant(
        "m1",
        model,
        [
            {"type": "text", "text": "On it."},
            {"type": "tool_use", "id": "t1", "name": name, "input": call},
        ],
    )
    emit(
        {
            "type": "control_request",
            "request_id": "r1",
            "request": {"subtype": "can_use_tool", "tool_name": name, "input": call},
        }
    )
    answer = sys.stdin.readline()
    (out / "answer.json").write_text(answer, encoding="utf-8")
    decision = json.loads(answer)["response"]["response"]["behavior"]
    if decision == "allow":
        # What the CLI would do next: call the tool server, which hands over the answer file.
        config = json.loads(Path(args[args.index("--mcp-config") + 1]).read_text())
        answers = Path(config["mcpServers"]["dodaios"]["args"][-1])
        deadline = time.monotonic() + 10
        found: list[Path] = []
        while not found and time.monotonic() < deadline:
            found = sorted(answers.glob("*.json"))
            time.sleep(0.05)
        text = json.loads(found[0].read_text(encoding="utf-8"))["text"] if found else ""
        (out / ("look.txt" if look else "kit.txt")).write_text(text, encoding="utf-8")
    _assistant(
        "m2",
        model,
        [
            {
                "type": "tool_use",
                "id": "t2",
                "name": "mcp__dodaios__delegate",
                "input": {"target": "coding_agent", "task": BRIEF},
            }
        ],
    )
    time.sleep(20)
    (out / "ran-on.txt").write_text("the turn went on past the brief", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
