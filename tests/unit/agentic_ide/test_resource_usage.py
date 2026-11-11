"""Sorting a process list into agents, their tools, linked apps and the rest.

The contract the resource view depends on: every process lands in exactly one
group, a tool is named after what actually runs (not the shell around it), no
command line leaves the module, and a process outside an agent's tree is linked
to it only by a real connection.
"""

from __future__ import annotations

import json

import pytest

from dodaios.agentic_ide.resource_usage import (
    APP_ROWS,
    MAX_ROWS,
    AgentSignature,
    KnownRoot,
    Link,
    Proc,
    build_usage,
    describe,
    match_agent,
    pretty,
    stem,
)

MB = 1024 * 1024
SIGNATURES = [
    AgentSignature("claude", "Claude Code", ("claude",)),
    AgentSignature("codex", "Codex", ("codex",)),
]


def proc(
    pid: int,
    ppid: int,
    name: str,
    *cmdline: str,
    cpu: float = 0.0,
    mb: float = 0.0,
    born: float | None = None,
) -> Proc:
    return Proc(
        pid=pid,
        ppid=ppid,
        name=name,
        create_time=float(pid if born is None else born),
        cpu_percent=cpu,
        memory=int(mb * MB),
        threads=1,
        cmdline=(name, *cmdline) if cmdline else (),
    )


def table(*procs: Proc) -> dict[int, Proc]:
    return {item.pid: item for item in procs}


@pytest.mark.parametrize(
    ("name", "cmdline", "expected"),
    [
        ("uvx.exe", ("uvx", "blender-mcp"), ("mcp", "blender")),
        ("blender-mcp.exe", (), ("mcp", "blender")),
        (
            "cmd.exe",
            ("cmd", "/d", "/s", "/c", "npx ^-y^ ^@modelcontextprotocol/server-github^"),
            ("mcp", "github"),
        ),
        ("node.exe", ("node", "npx-cli.js", "-y", "@playwright/mcp@latest"), ("mcp", "playwright")),
        ("cmd.exe", ("cmd", "/c", "mcp-server-git"), ("mcp", "git")),
        ("python.exe", ("python", "-m", "notebooklm_mcp.server"), ("mcp", "notebooklm")),
        ("node", ("node", "/x/chrome-devtools-mcp/build/index.js"), ("mcp", "chrome-devtools")),
        ("python.exe", ("python", "-m", "pytest", "tests"), ("test", "pytest")),
        (
            "node.exe",
            ("node", r"C:\w\node_modules\vite\bin\vite.js", "--port", "1"),
            ("build", "vite"),
        ),
        ("python.exe", ("python", r"C:\work\scripts\dev_preview.py"), ("runtime", "dev_preview")),
        ("python.exe", ("python", "-c", "import secret_thing"), ("runtime", "python")),
        ("node.exe", ("node", "plugins.tools@servers.app.enabled=true"), ("runtime", "node")),
        ("python.exe", ("python", "https://example.com/run?token=abc"), ("runtime", "python")),
        ("git.exe", (), ("vcs", "git")),
        ("chrome.exe", ("chrome", "--headless"), ("browser", "chrome")),
        ("blender.exe", ("blender", "--background"), ("command", "blender")),
        ("node.exe", ("node", r"C:\n\@openai\codex\bin\codex.js"), ("subagent", "Codex")),
    ],
)
def test_a_process_is_named_after_what_it_runs(name, cmdline, expected) -> None:
    category, label, wrapper = describe(name, cmdline, SIGNATURES)
    assert (category, label) == expected
    assert wrapper is False


@pytest.mark.parametrize(
    ("name", "cmdline", "label"),
    [
        ("bash.exe", ("bash", "-c", "source snapshot && eval x"), "bash"),
        ("conhost.exe", ("conhost", "0x4"), "conhost"),
        ("uv.exe", ("uv", "run", "thing"), "uv"),
        ("node.exe", ("node", "npm-cli.js", "run", "build"), "npm run build"),
    ],
)
def test_a_wrapper_is_marked_so_the_tool_is_named_below_it(name, cmdline, label) -> None:
    category, found, wrapper = describe(name, cmdline, SIGNATURES)
    assert wrapper is True
    assert found == label


def test_a_setting_that_mentions_mcp_does_not_start_a_server() -> None:
    line = ("tool.exe", "-c", "mcp_servers.apps@bundled.enabled=true", "app-server")
    category, label, _ = describe("tool.exe", line)
    assert (category, label) == ("command", "tool")


def test_a_folder_that_merely_contains_the_letters_is_not_an_mcp_server() -> None:
    category, label, _ = describe("python.exe", ("python", r"C:\mcps\tool\server.py"))
    assert category == "runtime"
    assert label == "tool"


def test_a_cli_is_recognised_by_executable_or_by_script() -> None:
    assert match_agent("claude.exe", (), SIGNATURES).agent == "claude"
    script = ("node", r"C:\npm\node_modules\@anthropic-ai\claude-code\cli.js")
    assert match_agent("node.exe", script, SIGNATURES).agent == "claude"
    assert match_agent("node.exe", ("node", "server.js"), SIGNATURES) is None
    assert match_agent("claudette.exe", (), SIGNATURES) is None


def test_names() -> None:
    assert stem(r"C:\Tools\Claude.EXE") == "claude"
    assert pretty("blender.exe") == "Blender"
    assert pretty("GoogleDriveFS.exe") == "GoogleDriveFS"


def _pane_tree() -> dict[int, Proc]:
    return table(
        proc(1, 0, "System"),
        proc(10, 1, "DodaiosApp.exe", "-m", "dodaios.ui.web.launcher", cpu=1.0, mb=500),
        proc(11, 10, "msedgewebview2.exe", "--type=renderer", cpu=2.0, mb=300),
        proc(20, 1, "pythonw.exe", "-m", "dodaios.terminal.pty_host", mb=5),
        # A pane: the CLI, its console, an MCP server, a test run and an idle shell.
        proc(30, 20, "claude.exe", "--resume", cpu=3.0, mb=400),
        proc(31, 30, "conhost.exe", "0x4", mb=1),
        proc(32, 30, "uvx.exe", "blender-mcp", mb=1),
        proc(33, 32, "uv.exe", "tool", "uvx", "blender-mcp", mb=2),
        proc(34, 33, "blender-mcp.exe", cpu=0.5, mb=40),
        proc(35, 30, "bash.exe", "-c", "source snap && eval pytest", mb=1),
        proc(36, 35, "python.exe", "-m", "pytest", "tests", cpu=20.0, mb=800),
        proc(37, 36, "python.exe", "-c", "from multiprocessing import spawn", cpu=5.0, mb=200),
        proc(38, 30, "bash.exe", "-c", "source snap && eval true", mb=1),
        proc(39, 30, "bash.exe", "-c", "source snap && eval true", mb=1),
        # Outside every tree: the editor the MCP server drives, and a stranger.
        proc(50, 1, "blender.exe", cpu=30.0, mb=2000),
        proc(51, 50, "blender.exe", "--worker", cpu=1.0, mb=100),
        proc(60, 1, "chrome.exe", cpu=4.0, mb=900),
        # A coding CLI started in some other terminal.
        proc(70, 1, "WindowsTerminal.exe", mb=50),
        proc(71, 70, "node.exe", r"C:\n\@openai\codex\bin\codex.js", cpu=1.5, mb=150),
        proc(72, 71, "codex.exe", cpu=0.5, mb=60),
        proc(73, 72, "rg.exe", "TODO", cpu=2.0, mb=10),
    )


def _usage(**extra):
    roots = [KnownRoot(30, "pane:abc", "pane", "claude", "Claude Code", "T1", "Fix login", "web")]
    options = {
        "known_roots": roots,
        "signatures": SIGNATURES,
        "app_roots": [10, 20],
        "links": [Link(34, 51, 9876)],
    }
    options.update(extra)
    return build_usage(_pane_tree(), **options)


def test_a_pane_is_split_into_its_runtime_and_its_tools() -> None:
    pane = next(row for row in _usage()["agents"] if row["id"] == "pane:abc")

    assert (pane["kind"], pane["label"], pane["detail"], pane["workspace"]) == (
        "pane",
        "T1",
        "Fix login",
        "web",
    )
    assert pane["runtime"]["processes"] == 2  # the CLI and its console
    assert pane["runtime"]["memory_mb"] == 401.0
    tools = {(tool["category"], tool["label"]): tool for tool in pane["tools"]}
    assert set(tools) == {("mcp", "blender"), ("test", "pytest"), ("shell", "bash")}
    assert tools[("test", "pytest")]["cpu_percent"] == 25.0
    assert tools[("test", "pytest")]["processes"] == 3  # the shell around it counts
    assert tools[("mcp", "blender")]["memory_mb"] == 43.0
    # Two idle shells are one line, and ending it ends both.
    assert tools[("shell", "bash")]["instances"] == 2
    assert len(tools[("shell", "bash")]["ids"]) == 2
    assert pane["processes"] == 10
    assert pane["cpu_percent"] == 28.5


def test_an_app_reached_over_a_local_connection_is_linked_not_owned() -> None:
    usage = _usage()
    pane = next(row for row in usage["agents"] if row["id"] == "pane:abc")

    (linked,) = pane["linked"]
    assert linked["label"] == "Blender"
    assert linked["port"] == 9876
    assert (linked["via"], linked["via_category"]) == ("blender", "mcp")
    assert linked["processes"] == 2  # the whole program, not the one socket's process
    assert linked["cpu_percent"] == 31.0
    assert usage["groups"]["linked"]["memory_mb"] == 2100.0
    # Its load is shown beside the agent, never added to the agent's own.
    assert pane["memory_mb"] < 2000


def test_without_a_connection_nothing_is_linked() -> None:
    usage = _usage(links=[])
    assert all(row["linked"] == [] for row in usage["agents"])
    assert usage["groups"]["linked"]["processes"] == 0
    assert any(row["label"] == "Blender" for row in usage["apps"])


def test_a_cli_nobody_started_here_is_found_by_name() -> None:
    usage = _usage()
    (outside,) = [row for row in usage["agents"] if row["kind"] == "external"]

    assert outside["agent"] == "codex"
    assert outside["label"] == "Codex"
    assert outside["runtime"]["processes"] == 2  # the script and its native half
    assert [(tool["category"], tool["label"]) for tool in outside["tools"]] == [("command", "rg")]


def test_every_process_lands_in_exactly_one_group() -> None:
    usage = _usage()
    groups = usage["groups"]

    assert sum(group["processes"] for group in groups.values()) == len(_pane_tree())
    assert groups["app"]["processes"] == 3  # the pane's tree is not the app's
    assert {part["role"] for part in usage["app"]["parts"]} == {
        "dodaiosapp",
        "msedgewebview2",
        "pythonw",
    }
    assert groups["agents"]["processes"] == 13


def test_no_command_line_leaves_the_module() -> None:
    text = json.dumps(_usage())
    for secret in ("secret_thing", "source snap", "codex.js", "--resume", "TODO"):
        assert secret not in text


def test_only_tools_of_agents_can_be_ended() -> None:
    owned = _usage()["owned_tools"]
    assert set(owned.values()) == {32, 35, 38, 39, 73}


def test_a_recycled_parent_id_does_not_adopt_a_stranger() -> None:
    procs = table(
        proc(30, 1, "claude.exe", born=500.0),
        # Its recorded parent id is 30, but that number was handed to the CLI
        # long after this process started.
        proc(40, 30, "old-service.exe", born=100.0, mb=10),
    )
    usage = build_usage(procs, signatures=SIGNATURES)
    (agent,) = usage["agents"]
    assert agent["processes"] == 1
    assert usage["groups"]["other"]["processes"] == 1


def test_a_long_tail_of_tools_is_folded_into_one_line() -> None:
    procs = [proc(30, 1, "claude.exe", mb=100)]
    procs += [
        proc(100 + index, 30, f"tool{index}.exe", mb=index + 1) for index in range(MAX_ROWS + 6)
    ]
    usage = build_usage(table(*procs), signatures=SIGNATURES)
    tools = usage["agents"][0]["tools"]

    assert len(tools) == MAX_ROWS
    assert tools[-1]["category"] == "more"
    assert tools[-1]["instances"] == 7
    assert sum(tool["processes"] for tool in tools) == MAX_ROWS + 6


def test_a_nested_known_root_keeps_its_own_tree() -> None:
    procs = table(
        proc(30, 1, "claude.exe"),
        proc(31, 30, "bash.exe", "-c", "x"),
        proc(32, 31, "codex.exe"),
        proc(33, 32, "rg.exe"),
    )
    roots = [
        KnownRoot(30, "pane:a", "pane", "claude", "Claude Code", "T1"),
        KnownRoot(32, "thread:b", "thread", "codex", "Codex", "Review"),
    ]
    usage = build_usage(procs, known_roots=roots, signatures=SIGNATURES)
    by_id = {row["id"]: row for row in usage["agents"]}

    assert by_id["pane:a"]["processes"] == 2
    assert by_id["thread:b"]["processes"] == 2


def test_a_desktop_program_with_a_clis_name_is_not_an_agent() -> None:
    procs = table(
        proc(80, 1, "claude.exe", mb=200),
        proc(81, 80, "claude.exe", "--type=renderer", mb=300),
        proc(82, 80, "claude.exe", "--type=gpu-process", mb=100),
        # The CLI itself, started from inside the desktop program, still counts.
        proc(83, 80, "claude.exe", "--print", "--output-format", "stream-json", mb=250),
        proc(84, 83, "rg.exe", mb=5),
    )
    usage = build_usage(procs, signatures=SIGNATURES)

    (agent,) = usage["agents"]
    assert agent["pid"] == 83
    assert agent["processes"] == 2
    assert usage["groups"]["other"]["processes"] == 3


def _desktop() -> dict[int, Proc]:
    """A Windows desktop: the shell, a service manager, and what they started."""
    return table(
        proc(4, 0, "System", mb=1),
        proc(5, 4, "Registry", mb=60),
        proc(600, 1, "wininit.exe"),
        proc(610, 600, "services.exe", mb=8),
        proc(611, 610, "svchost.exe", "-k", "netsvcs", cpu=1.0, mb=40),
        proc(612, 610, "svchost.exe", "-k", "DcomLaunch", mb=30),
        proc(613, 612, "RuntimeBroker.exe", mb=20),
        proc(620, 610, "MsMpEng.exe", cpu=6.0, mb=600),
        proc(700, 1, "explorer.exe", mb=90),
        # A 3D editor with a render worker and a script it runs.
        proc(710, 700, "blender.exe", cpu=30.0, mb=2000),
        proc(711, 710, "blender.exe", "--worker", cpu=5.0, mb=300),
        proc(712, 710, "python.exe", r"C:\tools\bake_textures.py", cpu=2.0, mb=100),
        # Two windows of one browser.
        proc(720, 700, "chrome.exe", cpu=1.0, mb=400),
        proc(721, 720, "chrome.exe", "--type=renderer", mb=500),
        proc(730, 700, "chrome.exe", mb=300),
        # A terminal the person works in.
        proc(740, 700, "WindowsTerminal.exe", mb=50),
        proc(741, 740, "pwsh.exe", mb=60),
        proc(742, 741, "node.exe", r"C:\w\node_modules\vite\bin\vite.js", cpu=3.0, mb=250),
        # An agent, and this app.
        proc(800, 1, "DodaiosApp.exe", "-m", "dodaios.ui.web.launcher", mb=500),
        proc(810, 800, "claude.exe", "--print", cpu=4.0, mb=400),
        proc(811, 810, "uvx.exe", "blender-mcp", mb=2),
    )


def _desktop_usage(**extra):
    options = {"signatures": SIGNATURES, "app_roots": [800]}
    options.update(extra)
    return build_usage(_desktop(), **options)


def test_every_program_is_a_row_whether_an_agent_uses_it_or_not() -> None:
    usage = _desktop_usage()
    apps = {row["label"]: row for row in usage["apps"]}

    assert set(apps) == {"Blender", "Chrome", "WindowsTerminal", "MsMpEng", "Explorer"}
    assert usage["app_count"] == 5
    # The whole program: its workers and the script it runs.
    assert apps["Blender"]["processes"] == 3
    assert apps["Blender"]["cpu_percent"] == 37.0
    assert apps["Blender"]["memory_mb"] == 2400.0
    assert {part["label"]: part["processes"] for part in apps["Blender"]["parts"]} == {
        "Blender": 2,
        "bake_textures": 1,
    }
    # Two windows of one program are one row.
    assert apps["Chrome"]["instances"] == 2
    assert apps["Chrome"]["processes"] == 3
    assert apps["Chrome"]["memory_mb"] == 1200.0
    # What runs in a terminal belongs to the terminal.
    assert {part["label"] for part in apps["WindowsTerminal"]["parts"]} == {
        "WindowsTerminal",
        "Pwsh",
        "vite",
    }
    assert [row["label"] for row in usage["apps"]][0] == "Blender"  # heaviest first


def test_the_desktop_shell_does_not_swallow_what_it_started() -> None:
    explorer = next(row for row in _desktop_usage()["apps"] if row["label"] == "Explorer")
    assert explorer["processes"] == 1
    assert explorer["memory_mb"] == 90.0


def test_the_operating_systems_own_processes_are_one_row() -> None:
    usage = _desktop_usage()
    system = usage["os"]

    assert system["processes"] == 7  # System, Registry, wininit, services, 2 svchost, the broker
    assert system["memory_mb"] == 159.0
    assert {part["label"] for part in system["parts"]} >= {"Svchost", "Registry", "RuntimeBroker"}
    # A service that is a product of its own is an app, not "the system".
    assert any(row["label"] == "MsMpEng" for row in usage["apps"])


def test_rows_and_groups_cover_every_process_exactly_once() -> None:
    usage = _desktop_usage()
    listed = (
        sum(row["processes"] for row in usage["apps"])
        + usage["apps_more"]["processes"]
        + usage["os"]["processes"]
        + usage["app"]["processes"]
        + sum(row["processes"] for row in usage["agents"])
    )
    assert listed == len(_desktop())
    assert usage["groups"]["other"]["processes"] == listed - 3  # minus this app and the agent


def test_an_app_an_agent_is_connected_to_says_who_uses_it() -> None:
    usage = _desktop_usage(links=[Link(811, 711, 9876)])
    blender = next(row for row in usage["apps"] if row["label"] == "Blender")
    (agent,) = usage["agents"]

    assert blender["used_by"] == [agent["id"]]
    assert agent["linked"][0]["label"] == "Blender"
    # In the chart it counts as a connected app; in the list it is still an app.
    assert usage["groups"]["linked"]["memory_mb"] == 2400.0
    assert all(row["used_by"] == [] for row in usage["apps"] if row["label"] != "Blender")


def test_every_row_has_a_load_for_its_history() -> None:
    usage = _desktop_usage()
    loads = usage["row_loads"]

    assert loads["app:Blender"] == (37.0, 2400.0, 0.0)
    assert loads["self"] == (0.0, 500.0, 0.0)
    assert loads["system"] == (1.0, 159.0, 0.0)
    assert usage["agents"][0]["id"] in loads


def test_the_long_tail_of_small_apps_is_one_figure() -> None:
    procs = [proc(700, 1, "explorer.exe", mb=10)]
    procs += [
        proc(1000 + index, 700, f"tool{index}.exe", mb=index + 1) for index in range(APP_ROWS + 9)
    ]
    usage = build_usage(table(*procs))

    assert len(usage["apps"]) == APP_ROWS
    assert usage["app_count"] == APP_ROWS + 10
    assert usage["apps_more"]["processes"] == 10
    # The folded ones still have a history, so a row that grows shows its past.
    assert len([key for key in usage["row_loads"] if key.startswith("app:")]) == APP_ROWS + 10


def test_no_command_line_leaves_an_app_row() -> None:
    procs = table(
        proc(700, 1, "explorer.exe"),
        proc(710, 700, "ChatApp.exe", mb=10),
        proc(
            711,
            710,
            "node.exe",
            "plugins.tools@servers.app.enabled=true",
            "--token",
            "s3cret",
            mb=5,
        ),
    )
    text = json.dumps(build_usage(procs))
    assert "enabled" not in text
    assert "s3cret" not in text
