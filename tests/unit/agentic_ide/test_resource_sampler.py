"""The sampler: rates from two readings, a short history, and a narrow way to end a tool.

Everything it reads is injected, so these tests state exact machines: a
process that used half a core for one second on a four-core machine is 12.5 %
of that machine, whatever the host running the test is doing.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import replace

from dodaios.agentic_ide.resource_sampler import (
    HISTORY_POINTS,
    ROW_POINTS,
    ResourceSampler,
    SampleContext,
    SystemReading,
)
from dodaios.agentic_ide.resource_usage import AgentSignature, Link
from dodaios.core.process_snapshot import ProcessRow
from dodaios.hardware.gpu_usage import GpuReading

MB = 1024 * 1024
SIGNATURES = [AgentSignature("claude", "Claude Code", ("claude",))]


class Machine:
    """A four-core computer whose clock and processes the test moves by hand."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.busy = 0.0
        self.rows: dict[int, ProcessRow] = {}
        self.command_lines: dict[int, tuple[str, ...]] = {}
        self.command_line_reads: list[int] = []
        self.links: list[Link] = []
        self.gpu: GpuReading | None = None
        self.memory_available = 6000 * MB
        self.add(900, 1, "DodaiosApp.exe", ("DodaiosApp.exe", "-m", "dodaios.ui.web.launcher"))

    def add(self, pid, ppid, name, cmdline=(), *, mb=0.0, born=None) -> None:
        self.rows[pid] = ProcessRow(
            pid=pid,
            ppid=ppid,
            name=name,
            create_time=self.now - 500 if born is None else born,
            cpu_seconds=0.0,
            memory=int(mb * MB),
            threads=2,
        )
        self.command_lines[pid] = tuple(cmdline)

    def advance(self, seconds: float, work: dict[int, float] | None = None) -> None:
        """Let time pass; ``work`` is processor seconds each process used."""
        self.now += seconds
        for pid, spent in (work or {}).items():
            self.rows[pid].cpu_seconds += spent
            self.busy += spent

    def read(self) -> list[ProcessRow]:
        return [replace(row) for row in self.rows.values()]

    def command_line(self, pid: int) -> tuple[str, ...]:
        self.command_line_reads.append(pid)
        return self.command_lines.get(pid, ())

    def system(self) -> SystemReading:
        total = self.now  # each core has existed for ``now`` seconds
        return SystemReading(
            cores=[(self.busy / 4, total)] * 4,
            memory_total=16000 * MB,
            memory_available=self.memory_available,
            physical_cores=2,
        )

    def sampler(self) -> ResourceSampler:
        gpu = type("Gpu", (), {"read": lambda _self: self.gpu})()
        return ResourceSampler(
            read=self.read,
            read_command_line=self.command_line,
            system=self.system,
            links=lambda: list(self.links),
            gpu=gpu,
            clock=lambda: self.now,
            wall=lambda: self.now,
            sleep=lambda seconds: self.advance(seconds),
            own_pid=900,
        )


def _with_agent(machine: Machine) -> None:
    machine.add(30, 1, "claude.exe", ("claude.exe",), mb=400)
    machine.add(31, 30, "python.exe", ("python.exe", "-m", "pytest"), mb=800)


def test_processor_share_is_the_difference_between_two_readings() -> None:
    machine = Machine()
    _with_agent(machine)
    sampler = machine.sampler()
    context = SampleContext(signatures=SIGNATURES)

    sampler.sample(context)
    machine.advance(2.0, {31: 1.0, 900: 0.4})
    payload = sampler.sample(context)

    (agent,) = payload["agents"]
    # One processor second in two seconds on four cores.
    assert agent["tools"][0]["cpu_percent"] == 12.5
    assert agent["cpu_percent"] == 12.5
    assert payload["app"]["cpu_percent"] == 5.0
    assert payload["system"]["cpu_percent"] == 17.5
    assert payload["system"]["per_core"] == [17.5] * 4
    assert payload["system"]["cores_logical"] == 4
    assert payload["interval_s"] == 2.0


def test_the_first_request_already_has_a_rate() -> None:
    machine = Machine()
    _with_agent(machine)
    sampler = machine.sampler()
    started = machine.now

    payload = sampler.sample(SampleContext(signatures=SIGNATURES))

    assert machine.now > started  # it took two readings a moment apart
    assert payload["agents"][0]["cpu_percent"] == 0.0
    assert len(payload["history"]["t"]) == 1


def test_a_process_started_inside_the_window_counts_in_full() -> None:
    machine = Machine()
    _with_agent(machine)
    sampler = machine.sampler()
    context = SampleContext(signatures=SIGNATURES)
    sampler.sample(context)

    machine.advance(2.0)
    machine.add(32, 30, "rg.exe", ("rg.exe",), born=machine.now - 1.0)
    machine.rows[32].cpu_seconds = 0.8
    machine.busy += 0.8
    payload = sampler.sample(context)

    tools = {tool["label"]: tool for tool in payload["agents"][0]["tools"]}
    assert tools["rg"]["cpu_percent"] == 10.0


def test_the_groups_add_up_to_the_machine() -> None:
    machine = Machine()
    _with_agent(machine)
    machine.add(60, 1, "chrome.exe", mb=900)
    sampler = machine.sampler()
    context = SampleContext(signatures=SIGNATURES)
    sampler.sample(context)

    # 0.6 processor seconds nobody in the table accounts for (the kernel).
    machine.advance(2.0, {31: 1.0})
    machine.busy += 0.6
    payload = sampler.sample(context)

    groups = payload["groups"]
    parts = sum(group["cpu_percent"] for group in groups.values())
    assert parts == payload["system"]["cpu_percent"]
    assert groups["other"]["cpu_percent"] == 7.5
    assert payload["system"]["memory_used_mb"] == 10000.0
    assert sum(group["memory_mb"] for group in groups.values()) == 10000.0
    assert payload["system"]["memory_percent"] == 62.5


def test_requests_in_quick_succession_share_one_sample() -> None:
    machine = Machine()
    sampler = machine.sampler()
    context = SampleContext(signatures=SIGNATURES)

    first = sampler.sample(context)
    machine.advance(0.3)
    assert sampler.sample(context) is first
    machine.advance(1.0)
    assert sampler.sample(context) is not first


def test_history_grows_per_sample_and_restarts_after_a_pause() -> None:
    machine = Machine()
    _with_agent(machine)
    sampler = machine.sampler()
    context = SampleContext(signatures=SIGNATURES)

    sampler.sample(context)
    for _ in range(3):
        machine.advance(2.0, {31: 0.8})
        payload = sampler.sample(context)
    history = payload["history"]
    agent_id = payload["agents"][0]["id"]
    assert len(history["t"]) == 4
    assert history["series"]["cpu"] == [0.0, 10.0, 10.0, 10.0]
    assert history["series"]["cpu.agents"] == [0.0, 10.0, 10.0, 10.0]
    assert history["rows"][agent_id]["cpu"] == [0.0, 10.0, 10.0, 10.0]
    assert history["rows"][agent_id]["memory"] == [1200.0] * 4
    assert "gpu" not in history["rows"][agent_id]  # it never used the card
    assert history["rows"]["self"]["cpu"] == [0.0] * 4
    assert history["rows"]["system"]["memory"][-1] > 0
    assert set(history["series"]) >= {"memory", "gpu", "memory.agents", "cpu.other", "cpu.app"}

    machine.advance(120.0)
    payload = sampler.sample(context)
    assert len(payload["history"]["t"]) == 1


def test_history_is_bounded_and_an_agent_that_appears_late_is_padded() -> None:
    machine = Machine()
    sampler = machine.sampler()
    context = SampleContext(signatures=SIGNATURES)
    sampler.sample(context)
    machine.advance(2.0)
    sampler.sample(context)
    _with_agent(machine)
    for _ in range(HISTORY_POINTS + 5):
        machine.advance(2.0)
        payload = sampler.sample(context)

    history = payload["history"]
    assert len(history["t"]) == HISTORY_POINTS
    assert all(len(series) == HISTORY_POINTS for series in history["series"].values())
    (agent_id,) = [row["id"] for row in payload["agents"]]
    line = history["rows"][agent_id]
    assert history["row_points"] == ROW_POINTS
    assert len(line["cpu"]) == ROW_POINTS  # a row carries its recent past only

    del machine.rows[30], machine.rows[31]
    machine.advance(2.0)
    assert set(sampler.sample(context)["history"]["rows"]) == {"self", "system"}


def test_a_late_agent_has_no_points_before_it_existed() -> None:
    machine = Machine()
    sampler = machine.sampler()
    context = SampleContext(signatures=SIGNATURES)
    sampler.sample(context)
    machine.advance(2.0)
    sampler.sample(context)
    _with_agent(machine)
    machine.advance(2.0)
    payload = sampler.sample(context)

    line = payload["history"]["rows"][payload["agents"][0]["id"]]
    assert line["cpu"] == [None, None, 0.0]


def test_a_command_line_is_looked_up_once() -> None:
    machine = Machine()
    _with_agent(machine)
    machine.add(60, 1, "chrome.exe")
    sampler = machine.sampler()
    context = SampleContext(signatures=SIGNATURES)

    sampler.sample(context)
    reads = list(machine.command_line_reads)
    machine.advance(2.0)
    sampler.sample(context)

    assert machine.command_line_reads == reads
    assert sorted(reads) == [30, 31, 900]  # a browser's arguments tell nothing here


def test_graphics_memory_is_attributed_and_an_impossible_reading_dropped() -> None:
    machine = Machine()
    _with_agent(machine)
    machine.gpu = GpuReading(
        name="Card",
        util_percent=40.0,
        memory_used_mb=3000,
        memory_total_mb=8000,
        processes={31: (35.0, 2000 * MB), 900: (1.0, 900_000 * MB)},
        per_process=True,
    )
    sampler = machine.sampler()
    payload = sampler.sample(SampleContext(signatures=SIGNATURES))

    assert payload["system"]["gpu"]["util_percent"] == 40.0
    assert payload["agents"][0]["gpu_memory_mb"] == 2000.0
    assert payload["agents"][0]["gpu_percent"] == 35.0
    assert payload["app"]["gpu_memory_mb"] == 0.0
    assert payload["history"]["series"]["gpu"] == [40.0]
    assert payload["history"]["rows"][payload["agents"][0]["id"]]["gpu"] == [35.0]


def test_a_machine_without_a_readable_card_says_so() -> None:
    machine = Machine()
    payload = machine.sampler().sample(SampleContext())
    assert payload["system"]["gpu"] is None


def test_a_connection_is_remembered_between_reads_and_dropped_with_its_process() -> None:
    machine = Machine()
    _with_agent(machine)
    machine.add(50, 1, "blender.exe", mb=2000)
    machine.links = [Link(31, 50, 9876)]
    sampler = machine.sampler()
    context = SampleContext(signatures=SIGNATURES)

    assert sampler.sample(context)["agents"][0]["linked"][0]["label"] == "Blender"
    machine.links = []  # the socket closed between two commands
    machine.advance(6.0)
    assert sampler.sample(context)["agents"][0]["linked"][0]["label"] == "Blender"
    del machine.rows[50]
    machine.advance(2.0)
    assert sampler.sample(context)["agents"][0]["linked"] == []


def test_the_apps_detached_helpers_count_as_the_app() -> None:
    machine = Machine()
    machine.add(20, 1, "pythonw.exe", ("pythonw.exe", "-m", "dodaios.terminal.pty_host"), mb=5)
    machine.add(21, 1, "helper.exe", mb=7)
    payload = machine.sampler().sample(SampleContext(host_pids=[21]))

    roles = {part["role"] for part in payload["app"]["parts"]}
    assert roles == {"core", "terminal_host", "helper"}
    assert payload["app"]["processes"] == 3


def _child(code: str) -> subprocess.Popen[bytes]:
    return subprocess.Popen([sys.executable, "-c", code])  # noqa: S603 - the test's own child


def test_ending_a_tool_takes_only_a_handle_from_the_last_sample() -> None:
    victim = _child("import time; time.sleep(60)")
    bystander = _child("import time; time.sleep(60)")
    try:
        machine = Machine()
        machine.add(30, 1, "claude.exe", ("claude.exe",))
        import psutil

        born = psutil.Process(victim.pid).create_time()
        machine.add(victim.pid, 30, "python.exe", ("python.exe", "x.py"), born=born)
        machine.add(bystander.pid, 1, "python.exe", ("python.exe", "y.py"))
        sampler = machine.sampler()
        payload = sampler.sample(SampleContext(signatures=SIGNATURES))
        (handle,) = payload["agents"][0]["tools"][0]["ids"]

        assert sampler.end_tools([f"{bystander.pid}:{int(time.time())}", "1:1"]) == 0
        assert bystander.poll() is None
        assert sampler.end_tools([f"{os.getpid()}:{int(time.time())}"]) == 0
        assert sampler.end_tools([handle]) == 1
        assert victim.wait(timeout=10) is not None
        assert bystander.poll() is None
    finally:
        for child in (victim, bystander):
            if child.poll() is None:
                child.kill()
            child.wait(timeout=10)


def test_a_reused_process_id_is_not_ended() -> None:
    stranger = _child("import time; time.sleep(60)")
    try:
        machine = Machine()
        machine.add(30, 1, "claude.exe", ("claude.exe",))
        # The table says this id belongs to a tool that started long ago; the
        # process holding the id now started a moment ago.
        machine.add(stranger.pid, 30, "python.exe", ("python.exe", "x.py"), born=12345.0)
        sampler = machine.sampler()
        payload = sampler.sample(SampleContext(signatures=SIGNATURES))
        (handle,) = payload["agents"][0]["tools"][0]["ids"]

        assert sampler.end_tools([handle]) == 0
        assert stranger.poll() is None
    finally:
        stranger.kill()
        stranger.wait(timeout=10)


def test_an_app_is_a_row_with_its_own_line() -> None:
    machine = Machine()
    machine.add(700, 1, "explorer.exe", mb=90)
    machine.add(710, 700, "blender.exe", mb=2000)
    machine.add(711, 710, "blender.exe", ("blender.exe", "--worker"), mb=300)
    sampler = machine.sampler()
    context = SampleContext(signatures=SIGNATURES)

    sampler.sample(context)
    machine.advance(2.0, {710: 1.6, 711: 0.4})
    payload = sampler.sample(context)

    apps = {row["label"]: row for row in payload["apps"]}
    assert apps["Blender"]["cpu_percent"] == 25.0
    assert apps["Blender"]["memory_mb"] == 2300.0
    assert apps["Blender"]["processes"] == 2
    assert payload["history"]["rows"]["app:Blender"]["cpu"] == [0.0, 25.0]
    assert payload["history"]["rows"]["app:Explorer"]["memory"] == [90.0, 90.0]


def test_what_no_process_accounts_for_is_the_systems() -> None:
    machine = Machine()
    machine.add(4, 0, "System", mb=10)
    machine.add(60, 1, "chrome.exe", mb=900)
    sampler = machine.sampler()
    context = SampleContext(signatures=SIGNATURES)
    sampler.sample(context)

    machine.advance(2.0, {60: 0.4})
    machine.busy += 0.8  # the kernel: no process shows it
    payload = sampler.sample(context)

    assert payload["os"]["cpu_percent"] == 10.0
    assert payload["system"]["cpu_percent"] == 15.0
    # Memory in use that no process holds (cache, drivers) is the system's too,
    # so the rows add up to the meter.
    rows = (
        sum(row["memory_mb"] for row in payload["apps"])
        + payload["os"]["memory_mb"]
        + payload["app"]["memory_mb"]
    )
    assert rows == payload["system"]["memory_used_mb"] == 10000.0
    assert payload["history"]["rows"]["system"]["cpu"] == [0.0, 10.0]
