"""The tool server of a lead replay: it lists the lead's tools and runs none of them.

A replay of a lead turn must offer the model the tools the lead has, under the
names the lead sees (``mcp__dodaios__<tool>``), or its first move would be
chosen from another list. It must also never run one: a replay is a
measurement, and a tool of the lead acts on the person's apps and accounts.

So the replay's CLI gets this server instead of the app's: a stdio MCP server
started from a file that holds the lead's tool list as the app's own server
lists it (name, description, input schema, read-only hint, the always-load
mark). Every call is answered with an error that says nothing ran, and the
replay stops the CLI at its first tool call anyway. Nothing here can reach the
app, the gateway or a credential.

**Calls that only read can be answered.** A brief replay (``brief_replay``)
answers the calls by which the lead reads the repository before it writes a
brief (:func:`served`): the brief kit (``delegate`` with ``options.prepare``
for a coding agent, which in the app only reads the repository and sends
nothing, :func:`asks_kit`) and the read-only folder tools (:data:`LOOKUPS`).
The replay that started this server writes the answer for such a call into the
answers folder, under the call's key (:func:`call_key`); the server waits for
that file and returns its text. Every other call, a call the replay did not
answer, and every call of a server started without an answers folder, gets
``NOT_RUN``.

    python -m dodaios.rsi.bench.replay_tools <tools.json> [<answers folder>]
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

__all__ = [
    "ANSWER_WAIT_S",
    "LOOKUPS",
    "NOT_RUN",
    "asks_kit",
    "build_server",
    "call_key",
    "load",
    "main",
    "served",
]

#: What a call gets back.
NOT_RUN: Final = "Not run: this is a benchmark replay, and no tool runs in it."
#: How long the server waits for the answer to a call a replay answers.
ANSWER_WAIT_S: Final[float] = 120.0
#: The targets whose ``options.prepare`` asks for the brief kit (``delegate``'s
#: ``_BRIEFED_KINDS`` and the words it takes for them).
_BRIEFED_TARGETS: Final[frozenset[str]] = frozenset({"coding_agent", "pane", "team_thread", "team"})


#: The lead's folder tools that only read (``agent_chat.tools.READ_ONLY_TOOLS``).
LOOKUPS: Final[frozenset[str]] = frozenset({"Read", "Ls", "Glob", "Grep"})


def served(name: str, arguments: Mapping[str, Any] | None) -> bool:
    """Whether a replay may answer this call: one that only reads and sends nothing."""
    return name in LOOKUPS or asks_kit(name, arguments)


def asks_kit(name: str, arguments: Mapping[str, Any] | None) -> bool:
    """Whether this call asks for the brief kit, which reads the repository and sends nothing."""
    if name != "delegate" or not isinstance(arguments, Mapping):
        return False
    options = arguments.get("options")
    if not isinstance(options, Mapping) or not options.get("prepare"):
        return False
    head = str(arguments.get("target") or "").partition(":")[0]
    return head.strip().lower().replace("-", "_").replace(" ", "_") in _BRIEFED_TARGETS


def call_key(name: str, arguments: Mapping[str, Any] | None) -> str:
    """The name of a call's answer file: the same for the same tool and arguments."""
    blob = json.dumps(
        {"name": name, "arguments": dict(arguments or {})},
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


def _answer(
    answers: Path, name: str, arguments: Mapping[str, Any] | None
) -> tuple[str, bool] | None:
    """The answer the replay wrote for this call and whether it is an error; waited for."""
    path = answers / f"{call_key(name, arguments)}.json"
    stop_at = time.monotonic() + ANSWER_WAIT_S
    while time.monotonic() < stop_at:
        if path.is_file():
            try:
                found = json.loads(path.read_text(encoding="utf-8"))
                return str(found["text"]), bool(found.get("error"))
            except (OSError, ValueError, KeyError, TypeError):  # half written: read it again
                pass
        time.sleep(0.05)
    return None


def load(path: Path | str) -> list[dict[str, Any]]:
    """The tool rows of a file: ``[{name, description, inputSchema, readOnly, meta}]``."""
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError("a replay tool file holds a list of tools")
    return [row for row in rows if isinstance(row, dict) and str(row.get("name") or "")]


def build_server(rows: list[dict[str, Any]], answers: Path | None = None) -> Any:
    import mcp.types as types
    from mcp.server.lowlevel import Server

    from dodaios.core.branding import MCP_TOOLS_SERVER_NAME

    server: Any = Server(MCP_TOOLS_SERVER_NAME)

    @server.list_tools()
    async def _list_tools() -> list[Any]:
        tools: list[Any] = []
        for row in rows:
            schema = row.get("inputSchema")
            meta = row.get("meta")
            tools.append(
                types.Tool(
                    name=str(row["name"]),
                    description=str(row.get("description") or ""),
                    inputSchema=schema
                    if isinstance(schema, dict) and schema
                    else {
                        "type": "object",
                        "properties": {},
                    },
                    annotations=types.ToolAnnotations(readOnlyHint=bool(row.get("readOnly"))),
                    _meta=dict(meta) if isinstance(meta, dict) and meta else None,
                )
            )
        return tools

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any] | None) -> Any:
        if answers is not None and served(name, arguments):
            found = await asyncio.to_thread(_answer, answers, name, arguments)
            if found is not None:
                text, error = found
                return types.CallToolResult(
                    content=[types.TextContent(type="text", text=text)], isError=error
                )
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=NOT_RUN)], isError=True
        )

    return server


async def _serve(rows: list[dict[str, Any]], answers: Path | None) -> None:
    import anyio
    from mcp.server.stdio import stdio_server

    stdin = stdout = None
    # A windowed interpreter may start with no standard streams; the pipes are there.
    if sys.stdin is None:
        stdin = anyio.wrap_file(
            io.TextIOWrapper(os.fdopen(0, "rb", closefd=False), encoding="utf-8", errors="replace")
        )
    if sys.stdout is None:
        stdout = anyio.wrap_file(
            io.TextIOWrapper(os.fdopen(1, "wb", closefd=False), encoding="utf-8")
        )
    server = build_server(rows, answers)
    async with stdio_server(stdin=stdin, stdout=stdout) as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) not in (1, 2):
        print(
            "usage: python -m dodaios.rsi.bench.replay_tools <tools.json> [<answers folder>]",
            file=sys.stderr,
        )
        return 2
    answers = Path(args[1]) if len(args) == 2 else None
    asyncio.run(_serve(load(args[0]), answers))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
