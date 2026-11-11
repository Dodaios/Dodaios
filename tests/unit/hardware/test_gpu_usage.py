"""Reading the graphics card: the parsers, and the reader's honesty about having nothing."""

from __future__ import annotations

import sys

import pytest

from dodaios.hardware import gpu_usage
from dodaios.hardware.gpu_usage import GpuReader, GpuReading, parse_smi_gpus, parse_smi_processes

MB = 1024 * 1024


def test_the_largest_card_is_the_one_reported() -> None:
    output = "Small Card, 3, 100, 2048\nNVIDIA GeForce RTX 5070 Ti, 41, 3711, 16303\n"

    reading = parse_smi_gpus(output)

    assert reading is not None
    assert reading.name == "NVIDIA GeForce RTX 5070 Ti"
    assert reading.to_dict() == {
        "name": "NVIDIA GeForce RTX 5070 Ti",
        "util_percent": 41.0,
        "memory_used_mb": 3711.0,
        "memory_total_mb": 16303.0,
        "per_process": False,
    }


def test_output_that_is_not_a_table_is_no_reading() -> None:
    assert parse_smi_gpus("") is None
    assert parse_smi_gpus("NVIDIA-SMI has failed because it couldn't communicate") is None


def test_a_value_the_driver_withholds_reads_as_zero() -> None:
    reading = parse_smi_gpus("Card, [N/A], 512, 8192")
    assert reading is not None
    assert reading.util_percent == 0.0
    assert reading.memory_used_mb == 512.0


def test_compute_processes_are_read_by_process_id() -> None:
    found = parse_smi_processes("4242, 1500\n77, [N/A]\nnot a row\n")
    assert found == {4242: (0.0, 1500 * MB), 77: (0.0, 0)}


def test_a_machine_with_no_source_has_no_reading(monkeypatch) -> None:
    monkeypatch.setattr(gpu_usage.shutil, "which", lambda _name: None)
    monkeypatch.setattr(gpu_usage.sys, "platform", "linux")

    assert GpuReader().read() is None


def test_the_command_line_tool_is_asked_at_most_every_few_seconds(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake(arguments: list[str]) -> str:
        calls.append(arguments)
        if arguments[0].startswith("--query-gpu"):
            return "Card, 50, 1000, 8000\n"
        return "4242, 900\n"

    monkeypatch.setattr(gpu_usage.shutil, "which", lambda _name: "nvidia-smi")
    monkeypatch.setattr(gpu_usage.sys, "platform", "linux")
    monkeypatch.setattr(gpu_usage, "_run_smi", fake)
    reader = GpuReader()

    first = reader.read()
    second = reader.read()

    assert isinstance(first, GpuReading)
    assert first.processes == {4242: (0.0, 900 * MB)}
    assert first.per_process is True
    assert second is first
    assert len(calls) == 2


def test_a_tool_that_stops_answering_is_not_asked_again(monkeypatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(gpu_usage.shutil, "which", lambda _name: "nvidia-smi")
    monkeypatch.setattr(gpu_usage.sys, "platform", "linux")
    monkeypatch.setattr(gpu_usage, "_run_smi", lambda arguments: calls.append(arguments) or "")
    reader = GpuReader()

    assert reader.read() is None
    assert reader.read() is None
    assert len(calls) == 1


@pytest.mark.skipif(sys.platform != "win32", reason="the counters are a Windows facility")
def test_the_system_counters_answer_or_step_aside() -> None:
    reader = GpuReader()
    try:
        reading = reader.read()
        if reading is not None:  # a machine without any adapter has none
            assert 0.0 <= reading.util_percent <= 100.0
            assert reading.memory_used_mb >= 0.0
            assert all(share <= 100.0 and used >= 0 for share, used in reading.processes.values())
    finally:
        reader.close()


class _FakePdh:
    def PdhCollectQueryData(self, _query) -> int:  # noqa: N802 - the system's own name
        return 0


def _counters(values: dict[str, list[tuple[str, float]]]) -> gpu_usage._WindowsCounters:
    """The counter reader with the system call replaced by fixed rows."""
    counters = object.__new__(gpu_usage._WindowsCounters)
    counters._pdh = _FakePdh()
    counters._query = None
    counters._values = lambda key: values.get(key, [])  # type: ignore[method-assign]
    return counters


def test_counter_rows_become_a_reading_per_process() -> None:
    adapter = "luid_0x00000000_0x0000D2B4_phys_0"
    reading = _counters(
        {
            "engine": [
                # One process on two engines of one kind, and on another kind.
                (f"pid_4242_{adapter}_eng_0_engtype_3D", 30.0),
                (f"pid_4242_{adapter}_eng_1_engtype_3D", 15.0),
                (f"pid_4242_{adapter}_eng_2_engtype_VideoDecode", 20.0),
                (f"pid_77_{adapter}_eng_0_engtype_3D", 25.0),
                (f"pid_9_{adapter}_eng_0_engtype_3D", 0.0),
                ("not an engine row", 99.0),
            ],
            "process_memory": [(f"pid_4242_{adapter}", 2048 * MB), (f"pid_500_{adapter}", 64 * MB)],
            "adapter_memory": [(adapter, 3000 * MB), ("luid_0x0_0x1_phys_0", 100 * MB)],
        }
    ).read()

    assert reading is not None
    # A process's share is its busiest kind of engine, not the sum over kinds.
    assert reading.processes[4242] == (45.0, 2048 * MB)
    assert reading.processes[77] == (25.0, 0)
    assert reading.processes[500] == (0.0, 64 * MB)
    assert 9 not in reading.processes
    # The card's load is its busiest kind of engine over every process.
    assert reading.util_percent == 70.0
    assert reading.memory_used_mb == 3000.0
    assert reading.per_process is True


def test_a_machine_whose_counters_list_no_adapter_has_no_reading() -> None:
    assert _counters({}).read() is None
