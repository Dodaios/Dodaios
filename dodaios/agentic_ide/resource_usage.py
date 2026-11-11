"""Who is using this computer: every running process, sorted into the agents that own it.

A process list answers "what runs". The question a person working with coding
agents has is a different one: *which agent* is behind the load, and *which of
its tools*. This module answers it from three facts per process (its parent,
its name, its command line) plus what the app already knows about its own
panes and threads:

* an **agent** is a pane, a thread, or a coding CLI found running anywhere on
  the machine. Its tree is everything it started.
* inside the tree, the CLI's own runtime is one line and every **tool** it
  started is another: an MCP server with everything below it, a test run, a
  build, a browser.
* a **linked app** is a program outside the tree that a tool talks to over a
  local connection, e.g. a 3D editor driven through its MCP server.
* what belongs to no agent is **this app**, or one of the **apps** running on
  the machine (every program gets a row, whether an agent uses it or not), or
  the **system** itself.

Pure: it takes plain rows and returns plain rows. Reading the machine is
``resource_sampler``'s job. No command line leaves this module, only a short
label derived from it (a module name, a script's name), because arguments can
hold tokens and file names.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

_MB = 1024 * 1024

#: Shells. Above the agent they are a wrapper; below it they are a command.
SHELLS = frozenset({"cmd", "powershell", "pwsh", "bash", "sh", "zsh", "fish", "dash", "wsl", "nu"})
#: Console plumbing that never does work of its own.
PLUMBING = frozenset({"conhost", "openconsole", "winpty-agent", "script", "login"})
#: Programs that only start another program.
LAUNCHERS = frozenset(
    {"npx", "npm", "pnpm", "pnpx", "yarn", "bunx", "uv", "uvx", "pipx", "env", "sudo", "nohup"}
    | {"time", "corepack"}
)
INTERPRETERS = frozenset(
    {"node", "python", "pythonw", "python3", "py", "bun", "deno", "ruby", "java", "javaw"}
    | {"dotnet", "php", "perl", "tsx", "ts-node"}
)
BROWSERS = frozenset(
    {"chrome", "msedge", "chromium", "firefox", "brave", "webkit", "msedgewebview2", "safari"}
    | {"headless_shell", "chrome-headless-shell"}
)
VERSION_CONTROL = frozenset({"git", "gh", "hg", "svn", "git-remote-https", "git-lfs"})
TESTS = frozenset(
    {"pytest", "vitest", "jest", "mocha", "playwright", "unittest", "tox", "nox", "cypress"}
    | {"ctest", "karma"}
)
BUILDS = frozenset(
    {"vite", "tsc", "webpack", "esbuild", "rollup", "turbo", "next", "pip", "cargo", "rustc"}
    | {"go", "gcc", "g++", "cc", "cl", "clang", "make", "cmake", "msbuild", "gradle", "mvn"}
    | {"ninja", "pyinstaller", "link", "ruff", "mypy", "eslint", "prettier", "tailwindcss"}
    | {"docker", "ffmpeg", "swc", "babel", "parcel", "bazel"}
)
#: Script and folder names that say nothing about what runs.
_GENERIC = frozenset(
    {"cli", "index", "main", "server", "bin", "run", "__main__", "app", "start", "dist", "build"}
    | {"lib", "src", "out", ".bin", "node_modules", "scripts", "cjs", "esm", "js", "launcher"}
    | {"entry", "cmd"}
)
_NPM_WRAPPERS = {"npm-cli": "npm", "npx-cli": "npx"}
_SCRIPT_SUFFIXES = (".js", ".mjs", ".cjs", ".ts", ".py", ".pyw", ".rb", ".jar", ".cmd", ".bat")
_PROGRAM_SUFFIXES = (*_SCRIPT_SUFFIXES, ".ps1", ".sh", ".exe")
_INLINE_CODE = frozenset({"-c", "-e", "-p", "--eval", "--print", "-"})
_VERSION_TAIL = re.compile(r"@[\w.^~*-]+$")
_MCP_PART = re.compile(r"(^|[-_.])mcp([-_.]server)?($|[-_.])", re.IGNORECASE)
_PROTOCOL_SCOPE = "modelcontextprotocol"
#: What a label derived from a command line may look like.
_LABEL = re.compile(r"[\w.+-]{1,40}")
#: Rows of one kind kept per agent; the rest are folded into one line.
MAX_ROWS = 14
#: Apps sent as rows of their own; the long tail of small ones is one figure.
APP_ROWS = 40
#: Parts listed inside one app.
APP_PARTS = 8
#: Programs whose children are programs of their own: the desktop shell and the
#: service managers. A browser started from the desktop is not "part of" it.
HOSTS = frozenset(
    {"explorer", "services", "wininit", "winlogon", "svchost", "sihost", "userinit", "smss"}
    | {"system"}
    | {"systemd", "init", "launchd", "gnome-shell", "plasmashell", "gnome-session-binary"}
    | {"xfce4-session", "cinnamon", "kwin_wayland", "kwin_x11"}
)
#: What the operating system itself runs; together they are one row.
SYSTEM_NAMES = frozenset(
    {"system", "registry", "memory compression", "secure system", "smss", "csrss", "wininit"}
    | {"winlogon", "services", "lsass", "lsaiso", "svchost", "fontdrvhost", "dwm", "sihost"}
    | {"taskhostw", "runtimebroker", "dllhost", "conhost", "spoolsv", "wudfhost", "ctfmon"}
    | {"userinit", "wmiprvse", "dashost", "audiodg", "searchhost", "startmenuexperiencehost"}
    | {"kthreadd", "systemd", "init", "launchd", "kernel_task", "dbus-daemon", "dbus-broker"}
    | {"windowserver", "loginwindow", "polkitd", "udisksd", "rtkit-daemon", "cron", "agetty"}
)
#: The row id of the operating system and of this app, beside agent and app ids.
SYSTEM_ROW = "system"
SELF_ROW = "self"
#: Kinds of part worth naming after what they run rather than after their program.
_NAMED_PARTS = frozenset({"mcp", "subagent", "test", "build", "runtime"})


@dataclass(slots=True)
class Proc:
    """One process as the sampler read it."""

    pid: int
    ppid: int
    name: str
    create_time: float
    #: Share of the whole machine since the last sample, 0-100.
    cpu_percent: float = 0.0
    memory: int = 0
    threads: int = 0
    cmdline: tuple[str, ...] = ()
    #: Dedicated graphics memory, where the platform reports it per process.
    gpu_memory: int = 0
    gpu_percent: float = 0.0


@dataclass(slots=True, frozen=True)
class AgentSignature:
    """How a coding CLI is recognised in a process list."""

    agent: str
    display_name: str
    binaries: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class KnownRoot:
    """A process the app started itself and can name: a pane or a thread turn."""

    pid: int
    id: str
    kind: str  # "pane" | "thread"
    agent: str
    agent_label: str
    label: str
    detail: str = ""
    workspace: str = ""


@dataclass(slots=True, frozen=True)
class Link:
    """Two processes holding the two ends of one local connection."""

    pid_a: int
    pid_b: int
    port: int


@dataclass(slots=True)
class Tally:
    """Summed load of a set of processes."""

    cpu: float = 0.0
    memory: int = 0
    count: int = 0
    threads: int = 0
    gpu_memory: int = 0
    gpu: float = 0.0

    def add(self, proc: Proc) -> None:
        self.cpu += proc.cpu_percent
        self.memory += proc.memory
        self.count += 1
        self.threads += proc.threads
        self.gpu_memory += proc.gpu_memory
        self.gpu += proc.gpu_percent

    def merge(self, other: Tally) -> None:
        self.cpu += other.cpu
        self.memory += other.memory
        self.count += other.count
        self.threads += other.threads
        self.gpu_memory += other.gpu_memory
        self.gpu += other.gpu

    def to_dict(self) -> dict[str, Any]:
        return {
            "cpu_percent": round(self.cpu, 1),
            "memory_mb": round(self.memory / _MB, 1),
            "processes": self.count,
            "threads": self.threads,
            "gpu_memory_mb": round(self.gpu_memory / _MB, 1),
            "gpu_percent": round(min(100.0, self.gpu), 1),
        }


@dataclass(slots=True)
class _Agent:
    id: str
    kind: str
    agent: str
    agent_label: str
    label: str
    detail: str
    workspace: str
    root: int
    pids: set[int] = field(default_factory=set)


@lru_cache(maxsize=4096)
def stem(name: str) -> str:
    """``Claude.EXE`` → ``claude``; a path is cut to its last part first."""
    base = re.split(r"[\\/]", name.strip().strip("\"'^"))[-1].lower()
    for suffix in _PROGRAM_SUFFIXES:
        if base.endswith(suffix) and len(base) > len(suffix):
            return base[: -len(suffix)]
    return base


def _words(cmdline: Sequence[str]) -> list[str]:
    """Arguments as single words. A shell's ``/c "npx -y pkg"`` is one argument."""
    words: list[str] = []
    for index, token in enumerate(cmdline[:12]):
        # The program's own path may hold spaces; everything after it is split.
        pieces = [token] if index == 0 else token.split()
        words.extend(piece.strip("^\"'") for piece in pieces)
    return [word for word in words if word]


def _path_parts(token: str) -> list[str]:
    return [part for part in re.split(r"[\\/]", token) if part]


def _is_option(token: str) -> bool:
    return token.startswith("-") or (token.startswith("/") and len(token) <= 3)


def _script_label(token: str) -> str:
    """A name for the script an interpreter runs, skipping names that say nothing."""
    for part in reversed(_path_parts(token)):
        name = part.lstrip("@") if part.startswith("@") else _VERSION_TAIL.sub("", stem(part))
        if not name or name in _GENERIC or name.endswith(":") or re.fullmatch(r"[\d.]+", name):
            continue
        # A label is a file's or a package's name. Anything else an argument
        # can hold (a setting, a URL, a sentence) is not shown.
        return _NPM_WRAPPERS.get(name, name) if _LABEL.fullmatch(name) else ""
    return ""


def _mcp_name(words: Sequence[str]) -> str | None:
    """The server's short name when a command line starts an MCP server."""
    for word in words:
        lowered = word.lower()
        if _is_option(word) or ("mcp" not in lowered and _PROTOCOL_SCOPE not in lowered):
            continue
        if "=" in word:
            continue  # a setting that mentions MCP, not a server being started
        parts = _path_parts(word)
        for index in range(len(parts) - 1, -1, -1):
            part = parts[index]
            owner = parts[index - 1].lstrip("@").lower() if index > 0 else ""
            bare = part if part.startswith("@") else _VERSION_TAIL.sub("", part)
            name = stem(bare).replace("_", "-")
            if owner == _PROTOCOL_SCOPE:
                return _server_name(name.removeprefix("server-"))
            if "mcp" not in name:
                continue
            if name.lstrip("@") in {"mcp", "mcp-server", "server-mcp"}:
                # "@playwright/mcp": the scope is the name.
                return _server_name(owner)
            if not _MCP_PART.search(name):
                continue
            short = _MCP_PART.sub(_join_around, name).strip("-.@")
            return _server_name(short.removeprefix("server-").removesuffix("-server"))
    return None


def _server_name(name: str) -> str:
    """A server's short name, or just "mcp" when what is left is not a name."""
    return name if _LABEL.fullmatch(name) else "mcp"


def _join_around(match: re.Match[str]) -> str:
    """Drop the ``mcp`` part of a name; keep one dash when it sat in the middle."""
    return "-" if match.group(1) and match.group(3) else ""


def describe(
    name: str, cmdline: Sequence[str], signatures: Sequence[AgentSignature] = ()
) -> tuple[str, str, bool]:
    """``(category, label, is_wrapper)`` for one process.

    A wrapper only starts something else, so a tool is named after the first
    process below it that is not one.
    """
    base = stem(name)
    words = _words(cmdline)
    mcp = _mcp_name([name, *words[1:]])
    if mcp is not None:
        return "mcp", mcp, False
    signature = match_agent(name, cmdline, signatures)
    if signature is not None:
        return "subagent", signature.display_name, False
    if base in PLUMBING or base in SHELLS:
        return "shell", base, True
    if base in LAUNCHERS:
        return _launcher(base, words[1:])
    if base in INTERPRETERS:
        label, rest = _interpreter_target(words[1:])
        if label in LAUNCHERS:
            return _launcher(label, rest)
        if not label:
            return "runtime", base, False
        return _category(label, "runtime"), label, False
    return _category(base, "command"), base, False


def _interpreter_target(arguments: Sequence[str]) -> tuple[str, Sequence[str]]:
    """What an interpreter runs, and the arguments after it."""
    for index, word in enumerate(arguments):
        if word in _INLINE_CODE:
            return "", ()
        if word == "-m" and index + 1 < len(arguments):
            module = arguments[index + 1].split(".")[0].lower()
            return (module if _LABEL.fullmatch(module) else ""), arguments[index + 2 :]
        if not _is_option(word):
            return _script_label(word), arguments[index + 1 :]
    return "", ()


def _launcher(base: str, rest: Sequence[str]) -> tuple[str, str, bool]:
    """``npm run build`` is worth naming; a bare ``npx`` only starts its package."""
    words = [word for word in rest if not _is_option(word)]
    if base in {"npm", "pnpm", "yarn"} and words:
        named = words[0] in {"run", "run-script"} and len(words) > 1
        script = words[1] if named else words[0]
        if re.fullmatch(r"[\w:.-]{1,32}", script):
            category = "test" if "test" in script else "build"
            return category, f"{base} run {script}" if named else f"{base} {script}", True
    return "shell", base, True


def _category(label: str, fallback: str) -> str:
    if label in TESTS:
        return "test"
    if label in BUILDS:
        return "build"
    if label in VERSION_CONTROL:
        return "vcs"
    if label in BROWSERS:
        return "browser"
    return fallback


def match_agent(
    name: str, cmdline: Sequence[str], signatures: Iterable[AgentSignature]
) -> AgentSignature | None:
    """The coding CLI this process is, or None.

    Either the executable carries the CLI's name, or an interpreter runs a
    script that does (``node …/codex/bin/codex.js``).
    """
    base = stem(name)
    script_parts: set[str] = set()
    if base in INTERPRETERS:
        for token in cmdline[1:4]:
            if _is_option(token):
                continue
            parts = _path_parts(token)[-4:]
            script_parts = {stem(part) for part in parts} | {
                part.lower().lstrip("@") for part in parts
            }
            break
    for signature in signatures:
        for binary in signature.binaries:
            if base == binary:
                return signature
            if script_parts & {binary, f"{binary}-code", f"{binary}-cli"}:
                return signature
    return None


class ProcessTree:
    """Parent and child links that survive a reused process id."""

    def __init__(self, procs: Mapping[int, Proc]) -> None:
        self.procs = procs
        self.children: dict[int, list[int]] = {}
        for proc in procs.values():
            parent = procs.get(proc.ppid)
            # A parent that started after its child is a recycled id (Windows
            # keeps the old number on the child for as long as it lives).
            if parent is None or parent.pid == proc.pid:
                continue
            if parent.create_time > proc.create_time + 1.0:
                continue
            self.children.setdefault(parent.pid, []).append(proc.pid)

    def parent(self, pid: int) -> int | None:
        proc = self.procs.get(pid)
        if proc is None:
            return None
        return proc.ppid if pid in self.children.get(proc.ppid, ()) else None

    def below(self, pid: int, stop: Iterable[int] = ()) -> list[int]:
        """``pid`` and everything under it, breadth first, not entering ``stop``."""
        blocked = stop if isinstance(stop, set | frozenset) else set(stop)
        seen = [pid]
        position = 0
        while position < len(seen):
            for child in self.children.get(seen[position], ()):
                if child not in blocked:
                    seen.append(child)
            position += 1
        return seen


def _core(tree: ProcessTree, agent: _Agent, signatures: Sequence[AgentSignature]) -> set[int]:
    """The processes that ARE the agent, as opposed to what it started.

    From the pane's first process down to the CLI itself: the shell that
    launched it, console plumbing beside it, and the CLI's own second process
    where it has one. A pane with no recognisable CLI is its first process.
    """
    procs = tree.procs
    own = [signature for signature in signatures if signature.agent == agent.agent]
    wanted = own or list(signatures)
    path: list[int] | None = None
    queue: list[list[int]] = [[agent.root]]
    while queue:
        trail = queue.pop(0)
        proc = procs[trail[-1]]
        if match_agent(proc.name, proc.cmdline, wanted) is not None:
            path = trail
            break
        if len(trail) > 1 and not describe(proc.name, proc.cmdline)[2]:
            continue  # a real program that is not the CLI: the CLI is not below it
        queue.extend([*trail, child] for child in tree.children.get(proc.pid, ()))
    core = set(path or [agent.root])
    for pid in list(core):
        for child in tree.children.get(pid, ()):
            if child not in agent.pids:
                continue
            child_proc = procs[child]
            second = path is not None and pid == path[-1]
            if stem(child_proc.name) in PLUMBING or (
                second and match_agent(child_proc.name, child_proc.cmdline, wanted) is not None
            ):
                core.add(child)
    return core


def _tool(
    tree: ProcessTree, root: int, pids: Sequence[int], signatures: Sequence[AgentSignature]
) -> dict[str, Any]:
    """One thing the agent started, named after the first real program in it."""
    procs = tree.procs
    tally = Tally()
    found: tuple[str, str] | None = None
    fallback: tuple[str, str] | None = None
    for pid in pids:
        proc = procs[pid]
        tally.add(proc)
        if found is not None or stem(proc.name) in PLUMBING:
            continue
        category, label, wrapper = describe(proc.name, proc.cmdline, signatures)
        if not wrapper:
            found = (category, label)
        elif fallback is None or (category != "shell" and fallback[0] == "shell"):
            fallback = (category, label)
    category, label = found or fallback or ("shell", stem(procs[root].name))
    return {
        "ids": [tool_id(procs[root])],
        "category": category,
        "label": label,
        "instances": 1,
        "started_at": procs[root].create_time,
        "_tally": tally,
        "_pids": list(pids),
    }


def tool_id(proc: Proc) -> str:
    """A handle for one process that a recycled process id cannot satisfy."""
    return f"{proc.pid}:{int(proc.create_time)}"


def _fold(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Same tool started several times is one line; the long tail is one line."""
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for tool in tools:
        key = (tool["category"], tool["label"])
        kept = merged.get(key)
        if kept is None:
            merged[key] = tool
            continue
        kept["ids"].extend(tool["ids"])
        kept["instances"] += 1
        kept["started_at"] = min(kept["started_at"], tool["started_at"])
        kept["_tally"].merge(tool["_tally"])
        kept["_pids"].extend(tool["_pids"])
    rows = sorted(merged.values(), key=lambda row: _weight(row["_tally"]), reverse=True)
    if len(rows) > MAX_ROWS:
        rest = rows[MAX_ROWS - 1 :]
        tail = {
            "ids": [],
            "category": "more",
            "label": "",
            "instances": sum(row["instances"] for row in rest),
            "started_at": min(row["started_at"] for row in rest),
            "_tally": Tally(),
            "_pids": [pid for row in rest for pid in row["_pids"]],
        }
        for row in rest:
            tail["_tally"].merge(row["_tally"])
        rows = [*rows[: MAX_ROWS - 1], tail]
    return rows


def _weight(tally: Tally) -> float:
    """Sort key that lets a busy process outrank a merely large one."""
    return tally.cpu * 200.0 + tally.memory / _MB


def _app_root(tree: ProcessTree, pid: int, taken: set[int]) -> int:
    """The top process of the program ``pid`` belongs to (a browser's main process)."""
    procs = tree.procs
    name = stem(procs[pid].name)
    current = pid
    while True:
        parent = tree.parent(current)
        if parent is None or parent in taken or stem(procs[parent].name) != name:
            return current
        current = parent


def _is_desktop_app(tree: ProcessTree, proc: Proc) -> bool:
    """A windowed program that shares a CLI's name: its desktop sibling, not the CLI.

    Such a program is built on a browser engine, which shows in its process
    tree: helper processes of the same name started with a ``--type=`` role.
    A CLI the desktop program starts in turn has no such role and still counts.
    """
    if _has_engine_role(proc):
        return True
    name = stem(proc.name)
    return any(
        stem(tree.procs[child].name) == name and _has_engine_role(tree.procs[child])
        for child in tree.children.get(proc.pid, ())
    )


def _has_engine_role(proc: Proc) -> bool:
    return any(argument.startswith("--type=") for argument in proc.cmdline[1:6])


def pretty(name: str) -> str:
    """``blender.exe`` → ``Blender``; a name with its own capitals is left alone."""
    base = re.split(r"[\\/]", name.strip())[-1]
    for suffix in (".exe", ".EXE", ".app"):
        base = base.removesuffix(suffix)
    return base[:1].upper() + base[1:] if base.islower() else base


def build_usage(
    procs: Mapping[int, Proc],
    *,
    known_roots: Sequence[KnownRoot] = (),
    signatures: Sequence[AgentSignature] = (),
    app_roots: Iterable[int] = (),
    links: Sequence[Link] = (),
    role_of: Callable[[Proc], str] | None = None,
) -> dict[str, Any]:
    """Sort every process into agents, linked apps, this app and everything else."""
    tree = ProcessTree(procs)
    agents: list[_Agent] = []
    owner: dict[int, _Agent] = {}

    app: set[int] = set()
    for pid in app_roots:
        if pid in procs:
            app.update(tree.below(pid))

    known = [named for named in known_roots if named.pid in procs]
    known_pids = {named.pid for named in known}
    for named in known:
        agent = _Agent(
            named.id,
            named.kind,
            named.agent,
            named.agent_label,
            named.label,
            named.detail,
            named.workspace,
            named.pid,
        )
        agent.pids = set(tree.below(named.pid, stop=known_pids - {named.pid}))
        agents.append(agent)
        for pid in agent.pids:
            owner[pid] = agent

    # A coding CLI nobody told us about: the topmost match starts an agent.
    for proc in sorted(procs.values(), key=lambda item: item.create_time) if signatures else ():
        if proc.pid in owner:
            continue
        signature = match_agent(proc.name, proc.cmdline, signatures)
        if signature is None or _is_desktop_app(tree, proc):
            continue
        agent = _Agent(
            f"process:{tool_id(proc)}",
            "background" if proc.pid in app else "external",
            signature.agent,
            signature.display_name,
            signature.display_name,
            "",
            "",
            proc.pid,
        )
        agent.pids = set(tree.below(proc.pid, stop=set(owner)))
        agents.append(agent)
        for pid in agent.pids:
            owner[pid] = agent

    agent_pids = set(owner)
    app -= agent_pids
    taken = agent_pids | app

    linked_of: dict[str, dict[int, tuple[int, int]]] = {}
    linked_pids: dict[int, set[int]] = {}
    for link in links:
        for inside, outside in ((link.pid_a, link.pid_b), (link.pid_b, link.pid_a)):
            agent_of = owner.get(inside)
            if agent_of is None or outside not in procs or outside in taken:
                continue
            root = _app_root(tree, outside, taken)
            if root not in linked_pids:
                linked_pids[root] = set(tree.below(root, stop=taken))
            linked_of.setdefault(agent_of.id, {}).setdefault(root, (link.port, inside))
    all_linked: set[int] = set().union(*linked_pids.values()) if linked_pids else set()
    users: dict[int, int] = {}
    for per_agent in linked_of.values():
        for root in per_agent:
            users[root] = users.get(root, 0) + 1

    agent_rows: list[dict[str, Any]] = []
    agents_total = Tally()
    owned: dict[str, int] = {}
    for agent in agents:
        core = _core(tree, agent, signatures)
        runtime = Tally()
        for pid in core:
            runtime.add(procs[pid])
        tools: list[dict[str, Any]] = []
        claimed = set(core)
        by_age = sorted(agent.pids - core, key=lambda item: procs[item].create_time)
        # First what the CLI started itself, then what lost its parent on the way.
        for direct in (True, False):
            for pid in by_age:
                if pid in claimed or (direct and tree.parent(pid) not in core):
                    continue
                members = [m for m in tree.below(pid, stop=claimed) if m in agent.pids]
                claimed.update(members)
                tools.append(_tool(tree, pid, members, signatures))
        total = Tally()
        for pid in agent.pids:
            total.add(procs[pid])
        agents_total.merge(total)
        tool_rows = _fold(tools)
        via_of = {pid: row for row in tool_rows for pid in row["_pids"]}
        linked_rows: list[dict[str, Any]] = []
        for root, (port, inside) in linked_of.get(agent.id, {}).items():
            tally = Tally()
            for pid in linked_pids[root]:
                tally.add(procs[pid])
            via = via_of.get(inside)
            linked_rows.append(
                {
                    "id": tool_id(procs[root]),
                    "label": pretty(procs[root].name),
                    "port": port,
                    "via": via["label"] if via else "",
                    "via_category": via["category"] if via else "",
                    "shared_with": users.get(root, 1) - 1,
                    **tally.to_dict(),
                }
            )
        linked_rows.sort(key=lambda row: (row["cpu_percent"], row["memory_mb"]), reverse=True)
        for row in tool_rows:
            tally = row.pop("_tally")
            row.pop("_pids")
            row.update(tally.to_dict())
            for one in row["ids"]:
                owned[one] = int(one.split(":")[0])
        agent_rows.append(
            {
                "id": agent.id,
                "kind": agent.kind,
                "agent": agent.agent,
                "agent_label": agent.agent_label,
                "label": agent.label,
                "detail": agent.detail,
                "workspace": agent.workspace,
                "pid": agent.root,
                "started_at": procs[agent.root].create_time,
                **total.to_dict(),
                "runtime": runtime.to_dict(),
                "tools": tool_rows,
                "linked": linked_rows,
            }
        )
    agent_rows.sort(key=lambda row: row["cpu_percent"] * 200.0 + row["memory_mb"], reverse=True)

    linked_total = Tally()
    for pid in all_linked:
        linked_total.add(procs[pid])

    app_total = Tally()
    app_parts: dict[str, Tally] = {}
    for pid in app:
        proc = procs[pid]
        app_total.add(proc)
        role = role_of(proc) if role_of is not None else stem(proc.name)
        app_parts.setdefault(role, Tally()).add(proc)

    other_total = Tally()
    for pid, proc in procs.items():
        if pid not in taken and pid not in all_linked:
            other_total.add(proc)

    apps, system = _apps(tree, taken)
    app_of = {pid: label for label, entry in apps.items() for pid in entry.pids}
    for agent_id, per_agent in linked_of.items():
        for linked_root in per_agent:
            label = app_of.get(linked_root)
            if label is not None and agent_id not in apps[label].used_by:
                apps[label].used_by.append(agent_id)
    ranked = sorted(apps.items(), key=lambda item: _weight(item[1].tally), reverse=True)
    more = Tally()
    for _label, entry in ranked[APP_ROWS:]:
        more.merge(entry.tally)

    loads = {row["id"]: _load(row) for row in agent_rows}
    loads[SELF_ROW] = _load(app_total.to_dict())
    loads[SYSTEM_ROW] = _load(system.tally.to_dict())
    app_rows: list[dict[str, Any]] = []
    for label, entry in ranked:
        row = {
            "id": f"app:{label}",
            "label": label,
            "instances": entry.instances,
            **entry.tally.to_dict(),
            "parts": _top(entry.parts, "label", APP_PARTS),
            "used_by": entry.used_by,
        }
        loads[row["id"]] = _load(row)
        if len(app_rows) < APP_ROWS:
            app_rows.append(row)

    return {
        "agents": agent_rows,
        "groups": {
            "agents": agents_total.to_dict(),
            "linked": linked_total.to_dict(),
            "app": app_total.to_dict(),
            "other": other_total.to_dict(),
        },
        "app": {**app_total.to_dict(), "parts": _top(app_parts, "role", MAX_ROWS)},
        "apps": app_rows,
        "app_count": len(ranked),
        "apps_more": more.to_dict(),
        "os": {**system.tally.to_dict(), "parts": _top(system.parts, "label", APP_PARTS)},
        "owned_tools": owned,
        "row_loads": loads,
    }


@dataclass(slots=True)
class _App:
    """One program on the machine: every process of it, under one name."""

    tally: Tally = field(default_factory=Tally)
    parts: dict[str, Tally] = field(default_factory=dict)
    pids: set[int] = field(default_factory=set)
    instances: int = 0
    used_by: list[str] = field(default_factory=list)


def _apps(tree: ProcessTree, taken: set[int]) -> tuple[dict[str, _App], _App]:
    """Every process that is no agent's and not this app's, as programs and the system.

    A program starts where the desktop shell or a service manager started
    something, and is everything below that point: a code editor with its
    language servers, a terminal with what runs in it. Several windows of the
    same program are one row.
    """
    procs = tree.procs
    rest = {pid for pid in procs if pid not in taken}
    starts: set[int] = set()
    for pid in rest:
        parent = tree.parent(pid)
        if parent is None or parent not in rest or stem(procs[parent].name) in HOSTS:
            starts.add(pid)
    apps: dict[str, _App] = {}
    system = _App()
    for pid in sorted(starts, key=lambda item: procs[item].create_time):
        name = stem(procs[pid].name)
        is_system = name in SYSTEM_NAMES or name.startswith("systemd-")
        entry = system if is_system else apps.setdefault(pretty(procs[pid].name) or "?", _App())
        entry.instances += 1
        for member in tree.below(pid, stop=starts):
            proc = procs[member]
            entry.pids.add(member)
            entry.tally.add(proc)
            category, label, _wrapper = describe(proc.name, proc.cmdline)
            part = label if category in _NAMED_PARTS else pretty(proc.name) or "?"
            entry.parts.setdefault(part, Tally()).add(proc)
    return apps, system


def _load(row: Mapping[str, Any]) -> tuple[float, float, float]:
    """What a row's history keeps per sample: processor %, memory MB, graphics %."""
    return (row["cpu_percent"], row["memory_mb"], row["gpu_percent"])


def _top(parts: Mapping[str, Tally], key: str, limit: int) -> list[dict[str, Any]]:
    ranked = sorted(parts.items(), key=lambda item: _weight(item[1]), reverse=True)
    return [{key: name, **tally.to_dict()} for name, tally in ranked[:limit]]
