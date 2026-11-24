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

    python -m dodaios.rsi.bench.replay_tools <tools.json>
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import sys
from pathlib import Path
from typing import Any, Final

__all__ = ["NOT_RUN", "build_server", "load", "main"]

#: What a call gets back.
NOT_RUN: Final = "Not run: this is a benchmark replay, and no tool runs in it."


def load(path: Path | str) -> list[dict[str, Any]]:
    """The tool rows of a file: ``[{name, description, inputSchema, readOnly, meta}]``."""
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError("a replay tool file holds a list of tools")
    return [row for row in rows if isinstance(row, dict) and str(row.get("name") or "")]


def build_server(rows: list[dict[str, Any]]) -> Any:
    import mcp.types as types
    from mcp.server.lowlevel import Server

    from dodaios.core.branding import MCP_TOOLS_SERVER_NAME

    server: Any = Server(MCP_TOOLS_SERVER_NAME)

    @server.list_tools()  # type: ignore[misc, no-untyped-call]
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

    @server.call_tool()  # type: ignore[misc, no-untyped-call]
    async def _call_tool(name: str, arguments: dict[str, Any] | None) -> Any:
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=NOT_RUN)], isError=True
        )

    return server


async def _serve(rows: list[dict[str, Any]]) -> None:
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
    server = build_server(rows)
    async with stdio_server(stdin=stdin, stdout=stdout) as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python -m dodaios.rsi.bench.replay_tools <tools.json>", file=sys.stderr)
        return 2
    asyncio.run(_serve(load(args[0])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
