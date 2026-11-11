"""Measure the machine on request and keep the last few minutes.

:mod:`resource_usage` sorts processes into agents; this module reads what it
sorts. One :class:`ResourceSampler` holds the previous reading (processor load
is a difference between two readings), the command lines it has already looked
up, the local connections it has seen, and a short history for the charts.

It samples **only when asked**. Nothing runs between requests, so a closed
panel costs nothing; a panel that polls every two seconds gets a fresh sample
each time, and one that comes back after a pause starts a new history rather
than drawing a line across the gap.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from dodaios.agentic_ide.resource_usage import (
    INTERPRETERS,
    LAUNCHERS,
    SHELLS,
    AgentSignature,
    KnownRoot,
    Link,
    Proc,
    build_usage,
    stem,
)
from dodaios.core.process_snapshot import ProcessRow, command_line, read_processes

_MB = 1024 * 1024
#: The app's own package, so its helper processes are recognised by module name.
_APP_PACKAGE = __name__.split(".")[0]
#: A request this soon after the last one gets the same answer.
MIN_INTERVAL_S = 1.0
#: After this long without a request the old reading is no base for a rate.
STALE_S = 20.0
#: How long the first request waits between its two readings.
PRIME_S = 0.4
#: Points kept for the charts: five minutes at one sample every two seconds.
HISTORY_POINTS = 150
#: Local connections are read at most this often and remembered this long.
LINKS_EVERY_S = 4.0
LINK_MEMORY_S = 45.0
#: Time one sample may spend looking up new command lines. Each lookup is a
#: system call or more, and on a busy machine a thousand of them take seconds;
#: what does not fit is looked up by the next samples, most telling first.
COMMAND_LINE_BUDGET_S = 0.3
_ROLES = {
    f"{_APP_PACKAGE}.ui.web.launcher": "core",
    f"{_APP_PACKAGE}.terminal.pty_host": "terminal_host",
    f"{_APP_PACKAGE}.agent_chat.turn_host": "thread_host",
}
_WINDOW_NAMES = ("webview", "webkit", "cef")
#: Programs that may only be the wrapper around something worth naming.
_WRAPPING_NAMES = INTERPRETERS | SHELLS | LAUNCHERS


@dataclass(slots=True)
class SystemReading:
    """The machine as a whole at one moment."""

    #: Per logical core: (busy seconds, total seconds) since boot.
    cores: list[tuple[float, float]]
    memory_total: int
    memory_available: int
    swap_total: int = 0
    swap_used: int = 0
    physical_cores: int = 0


@dataclass(slots=True)
class SampleContext:
    """What the app knows that the process table does not."""

    known_roots: Sequence[KnownRoot] = ()
    signatures: Sequence[AgentSignature] = ()
    #: Helper processes the app started detached (its terminal and thread hosts).
    host_pids: Sequence[int] = ()


@dataclass(slots=True)
class _Previous:
    at: float
    wall: float
    cpu: dict[tuple[int, float], float]
    cores: list[tuple[float, float]]


@dataclass(slots=True)
class _History:
    t: deque[float]
    series: dict[str, deque[float]] = field(default_factory=dict)
    agents: dict[str, tuple[deque[float | None], deque[float | None]]] = field(default_factory=dict)


def read_system() -> SystemReading:
    import psutil

    cores = []
    for times in psutil.cpu_times(percpu=True):
        total = float(sum(times))
        idle = float(times.idle) + float(getattr(times, "iowait", 0.0))
        cores.append((total - idle, total))
    memory = psutil.virtual_memory()
    swap_total = swap_used = 0
    try:
        swap = psutil.swap_memory()
        swap_total, swap_used = int(swap.total), int(swap.used)
    except (OSError, RuntimeError):  # some sandboxes forbid the read
        pass
    return SystemReading(
        cores=cores,
        memory_total=int(memory.total),
        memory_available=int(memory.available),
        swap_total=swap_total,
        swap_used=swap_used,
        physical_cores=int(psutil.cpu_count(logical=False) or 0),
    )


def _loopback(address: str) -> bool:
    bare = address.removeprefix("::ffff:")
    return bare.startswith("127.") or bare == "::1"


def read_links() -> list[Link]:
    """Pairs of processes joined by an open connection on this machine."""
    import psutil

    try:
        connections = psutil.net_connections(kind="tcp")
    except (psutil.Error, OSError, RuntimeError):  # macOS answers only a privileged caller
        return []
    endpoints: dict[int, int] = {}
    listening: set[int] = set()
    for item in connections:
        if not item.pid or not item.laddr:
            continue
        if item.status == psutil.CONN_LISTEN:
            listening.add(int(item.laddr.port))
        elif item.raddr and _loopback(item.laddr.ip) and _loopback(item.raddr.ip):
            endpoints[int(item.laddr.port)] = int(item.pid)
    links: dict[tuple[int, int], int] = {}
    for item in connections:
        if not item.pid or not item.raddr or not item.laddr or not _loopback(item.raddr.ip):
            continue
        peer = endpoints.get(int(item.raddr.port))
        if peer is None or peer == item.pid:
            continue
        local, remote = int(item.laddr.port), int(item.raddr.port)
        # The side that listens is the one whose port means something.
        port = (
            local if local in listening else remote if remote in listening else min(local, remote)
        )
        links.setdefault((min(item.pid, peer), max(item.pid, peer)), port)
    return [Link(pair[0], pair[1], port) for pair, port in links.items()]


class ResourceSampler:
    """One measured picture of the machine per request, with a short memory."""

    def __init__(
        self,
        *,
        read: Callable[[], list[ProcessRow]] = read_processes,
        read_command_line: Callable[[int], tuple[str, ...]] = command_line,
        system: Callable[[], SystemReading] = read_system,
        links: Callable[[], list[Link]] = read_links,
        gpu: Any = None,
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        own_pid: int | None = None,
    ) -> None:
        self._read = read
        self._read_command_line = read_command_line
        self._system = system
        self._links = links
        self._gpu = gpu
        self._clock = clock
        self._wall = wall
        self._sleep = sleep
        self._own_pid = own_pid if own_pid is not None else os.getpid()
        self._lock = threading.Lock()
        self._previous: _Previous | None = None
        self._payload: dict[str, Any] | None = None
        self._command_lines: dict[tuple[int, float], tuple[str, ...]] = {}
        self._link_seen: dict[tuple[int, int], tuple[int, float]] = {}
        self._links_at = float("-inf")
        self._history = _History(t=deque(maxlen=HISTORY_POINTS))
        self._owned_tools: dict[str, int] = {}

    # ------------------------------------------------------------ reading
    def _remember(self, rows: list[ProcessRow], system: SystemReading) -> None:
        self._previous = _Previous(
            at=self._clock(),
            wall=self._wall(),
            cpu={(row.pid, row.create_time): row.cpu_seconds for row in rows},
            cores=system.cores,
        )

    def _interesting(self, rows: list[ProcessRow], context: SampleContext) -> list[ProcessRow]:
        """Whose command line is worth a lookup, most telling first.

        First what could be a coding CLI or the app itself, because that decides
        which agents exist at all; then everything below a pane, a thread or the
        app, which names their tools; then the interpreters and shells elsewhere,
        one of which may turn out to run a CLI's script.
        """
        binaries = {binary for signature in context.signatures for binary in signature.binaries}
        own = stem(next((row.name for row in rows if row.pid == self._own_pid), ""))
        children: dict[int, list[ProcessRow]] = {}
        for row in rows:
            children.setdefault(row.ppid, []).append(row)
        below: set[int] = set()
        stack = [root.pid for root in context.known_roots]
        stack += [*context.host_pids, self._own_pid]
        while stack:
            for child in children.get(stack.pop(), ()):
                if child.pid not in below:
                    below.add(child.pid)
                    stack.append(child.pid)
        first: list[ProcessRow] = []
        second: list[ProcessRow] = []
        third: list[ProcessRow] = []
        for row in rows:
            name = stem(row.name)
            if name in binaries or name == own or name.startswith(_APP_PACKAGE):
                first.append(row)
            elif row.pid in below:
                second.append(row)
            elif name in _WRAPPING_NAMES:
                third.append(row)
        return [*first, *second, *third]

    def _fill_command_lines(self, rows: list[ProcessRow], context: SampleContext) -> None:
        alive = {(row.pid, row.create_time) for row in rows}
        for key in [key for key in self._command_lines if key not in alive]:
            del self._command_lines[key]
        deadline = time.perf_counter() + COMMAND_LINE_BUDGET_S
        for row in self._interesting(rows, context):
            key = (row.pid, row.create_time)
            if key in self._command_lines:
                continue
            if time.perf_counter() > deadline:
                break
            try:
                self._command_lines[key] = self._read_command_line(row.pid)
            except Exception:  # noqa: BLE001 - a process that ended mid-read
                self._command_lines[key] = ()

    def _current_links(self, alive: set[int]) -> list[Link]:
        now = self._clock()
        if now - self._links_at >= LINKS_EVERY_S:
            self._links_at = now
            try:
                for link in self._links():
                    self._link_seen[(link.pid_a, link.pid_b)] = (link.port, now)
            except Exception as exc:  # noqa: BLE001 - never worth failing a sample
                logger.debug("Resource sampler: connections unreadable: {}", exc)
        for pair, (_port, seen) in list(self._link_seen.items()):
            if now - seen > LINK_MEMORY_S or pair[0] not in alive or pair[1] not in alive:
                del self._link_seen[pair]
        return [Link(pair[0], pair[1], port) for pair, (port, _seen) in self._link_seen.items()]

    def _app_roots(self, procs: dict[int, Proc], context: SampleContext) -> list[int]:
        """This app's processes: its own tree and every helper started as a module of it."""
        roots = [pid for pid in context.host_pids if pid in procs]
        current = procs.get(self._own_pid)
        if current is not None:
            name = stem(current.name)
            while True:
                parent = procs.get(current.ppid)
                if parent is None or parent.create_time > current.create_time + 1.0:
                    break
                if stem(parent.name) != name and not _app_module(parent.cmdline):
                    break
                current = parent
            roots.append(current.pid)
        roots.extend(pid for pid, proc in procs.items() if _app_module(proc.cmdline))
        return roots

    # ----------------------------------------------------------- sampling
    def sample(self, context: SampleContext) -> dict[str, Any]:
        """The machine right now. Safe to call from several threads."""
        with self._lock:
            now = self._clock()
            previous = self._previous
            if self._payload is not None and previous is not None:
                if now - previous.at < MIN_INTERVAL_S:
                    return self._payload
            if previous is None or now - previous.at > STALE_S:
                self._reset_history()
                self._remember(self._read(), self._system())
                self._sleep(PRIME_S)
            self._payload = self._measure(context)
            return self._payload

    def _reset_history(self) -> None:
        self._history = _History(t=deque(maxlen=HISTORY_POINTS))

    def _measure(self, context: SampleContext) -> dict[str, Any]:
        previous = self._previous
        assert previous is not None  # noqa: S101 - sample() primes before measuring
        rows = self._read()
        system = self._system()
        now = self._clock()
        elapsed = max(0.05, now - previous.at)
        core_count = max(1, len(system.cores))
        self._fill_command_lines(rows, context)

        gpu_reading = None
        if self._gpu is not None:
            try:
                gpu_reading = self._gpu.read()
            except Exception as exc:  # noqa: BLE001 - the card is optional
                logger.debug("Resource sampler: GPU unreadable: {}", exc)
        gpu_total = gpu_reading.memory_total_mb * _MB if gpu_reading else 0.0
        gpu_ceiling = gpu_total or 64 * 1024 * _MB

        procs: dict[int, Proc] = {}
        for row in rows:
            key = (row.pid, row.create_time)
            before = previous.cpu.get(key)
            if before is None:
                # Started since the last look: all of its time falls in this window.
                spent = row.cpu_seconds if row.create_time >= previous.wall - 1.0 else 0.0
            else:
                spent = max(0.0, row.cpu_seconds - before)
            share, graphics = (0.0, 0)
            if gpu_reading is not None:
                share, graphics = gpu_reading.processes.get(row.pid, (0.0, 0))
                if graphics > gpu_ceiling:
                    graphics = 0  # a counter that reports more than the card holds
            procs[row.pid] = Proc(
                pid=row.pid,
                ppid=row.ppid,
                name=row.name,
                create_time=row.create_time,
                cpu_percent=min(100.0, spent / (elapsed * core_count) * 100.0),
                memory=row.memory,
                threads=row.threads,
                cmdline=self._command_lines.get(key, ()),
                gpu_memory=graphics,
                gpu_percent=share,
            )

        usage = build_usage(
            procs,
            known_roots=context.known_roots,
            signatures=context.signatures,
            app_roots=self._app_roots(procs, context),
            links=self._current_links(set(procs)),
            role_of=_role,
        )
        self._owned_tools = usage.pop("owned_tools")

        per_core: list[float] = []
        busy_sum = total_sum = 0.0
        for index, (busy, total) in enumerate(system.cores):
            before_busy, before_total = (
                previous.cores[index] if index < len(previous.cores) else (busy, total)
            )
            span = total - before_total
            used = busy - before_busy
            per_core.append(
                round(min(100.0, max(0.0, used / span * 100.0)), 1) if span > 0 else 0.0
            )
            busy_sum += max(0.0, used)
            total_sum += max(0.0, span)
        cpu_percent = min(100.0, busy_sum / total_sum * 100.0) if total_sum > 0 else 0.0
        memory_used = max(0, system.memory_total - system.memory_available)

        groups = usage["groups"]
        known_cpu = sum(groups[key]["cpu_percent"] for key in ("agents", "linked", "app"))
        known_memory = sum(groups[key]["memory_mb"] for key in ("agents", "linked", "app"))
        # What no listed process accounts for (the kernel, processes that ended
        # inside the window) belongs to "everything else", so the parts add up
        # to the machine's own figure.
        groups["other"]["cpu_percent"] = round(max(0.0, cpu_percent - known_cpu), 1)
        groups["other"]["memory_mb"] = round(max(0.0, memory_used / _MB - known_memory), 1)

        self._remember(rows, system)
        wall = self._wall()
        payload: dict[str, Any] = {
            "ts": wall,
            "interval_s": round(elapsed, 2),
            "platform": sys.platform,
            "system": {
                "cpu_percent": round(cpu_percent, 1),
                "per_core": per_core,
                "cores_logical": core_count,
                "cores_physical": system.physical_cores,
                "memory_total_mb": round(system.memory_total / _MB, 1),
                "memory_used_mb": round(memory_used / _MB, 1),
                "memory_percent": round(memory_used / system.memory_total * 100.0, 1)
                if system.memory_total
                else 0.0,
                "swap_total_mb": round(system.swap_total / _MB, 1),
                "swap_used_mb": round(system.swap_used / _MB, 1),
                "processes": len(rows),
                "gpu": gpu_reading.to_dict() if gpu_reading is not None else None,
            },
            **usage,
        }
        self._record(payload)
        payload["history"] = self._history_payload()
        return payload

    # ------------------------------------------------------------ history
    def _record(self, payload: dict[str, Any]) -> None:
        history = self._history
        history.t.append(round(payload["ts"], 2))
        system = payload["system"]
        gpu = system["gpu"]
        values = {
            "cpu": system["cpu_percent"],
            "memory": system["memory_percent"],
            "gpu": gpu["util_percent"] if gpu else 0.0,
        }
        total_mb = system["memory_total_mb"] or 1.0
        for key, group in payload["groups"].items():
            values[f"cpu.{key}"] = group["cpu_percent"]
            values[f"memory.{key}"] = round(group["memory_mb"] / total_mb * 100.0, 1)
        length = len(history.t)
        for key, value in values.items():
            series = history.series.get(key)
            if series is None:
                series = deque([0.0] * (length - 1), maxlen=HISTORY_POINTS)
                history.series[key] = series
            series.append(value)
        seen = set()
        for agent in payload["agents"]:
            seen.add(agent["id"])
            pair = history.agents.get(agent["id"])
            if pair is None:
                pair = (
                    deque([None] * (length - 1), maxlen=HISTORY_POINTS),
                    deque([None] * (length - 1), maxlen=HISTORY_POINTS),
                )
                history.agents[agent["id"]] = pair
            pair[0].append(agent["cpu_percent"])
            pair[1].append(agent["memory_mb"])
        for agent_id in list(history.agents):
            if agent_id in seen:
                continue
            del history.agents[agent_id]  # it ended; its line ends with it

    def _history_payload(self) -> dict[str, Any]:
        history = self._history
        return {
            "t": list(history.t),
            "series": {key: list(values) for key, values in history.series.items()},
            "agents": {
                agent_id: {"cpu": list(pair[0]), "memory": list(pair[1])}
                for agent_id, pair in history.agents.items()
            },
        }

    # ------------------------------------------------------------- ending
    def end_tools(self, ids: Sequence[str]) -> int:
        """End tools an agent started, by the handles the last sample gave out.

        Only a handle from the last sample is accepted, and only while the
        process behind it is still the one that was measured: an agent's tool
        can be ended from here, nothing else on the machine can.
        """
        import psutil

        with self._lock:
            wanted = [self._owned_tools[one] for one in ids if one in self._owned_tools]
            started = {
                self._owned_tools[one]: int(one.split(":")[1])
                for one in ids
                if one in self._owned_tools
            }
        victims: list[Any] = []
        for pid in wanted:
            try:
                process = psutil.Process(pid)
                if abs(int(process.create_time()) - started[pid]) > 1:
                    continue  # the id was reused by another process
                victims.extend([*process.children(recursive=True), process])
            except psutil.Error:  # it ended by itself, which is what was asked for
                continue
        for process in victims:
            try:
                process.terminate()
            except psutil.Error:  # already gone, or not ours to end; the count says how many were
                continue
        _gone, alive = psutil.wait_procs(victims, timeout=1.5)
        for process in alive:
            try:
                process.kill()
            except psutil.Error:  # it ended between the wait and the kill
                continue
        return len(victims)


def _app_module(cmdline: Sequence[str]) -> bool:
    """Was this process started as one of the app's own modules (``-m package.x``)?"""
    for index, part in enumerate(cmdline[1:5], start=1):
        if part == "-m" and index + 1 < len(cmdline):
            return cmdline[index + 1].startswith(f"{_APP_PACKAGE}.")
    return False


def _role(proc: Proc) -> str:
    """A short name for one of the app's processes; no path, no arguments."""
    name = stem(proc.name)
    for index, part in enumerate(proc.cmdline[:-1]):
        if part == "-m":
            module = proc.cmdline[index + 1]
            if module in _ROLES:
                return _ROLES[module]
            return ".".join(module.split(".")[-2:]).removeprefix(f"{_APP_PACKAGE}.")
    if any(part in name for part in _WINDOW_NAMES):
        return "window"
    return name
