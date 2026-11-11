"""How busy the graphics card is right now, overall and per process.

Two sources, because no single one covers every machine:

* **Windows** — the performance counters the system itself keeps for every
  adapter and every process (``GPU Engine``, ``GPU Process Memory``,
  ``GPU Adapter Memory``). They work for any vendor and are the only source of
  a per-process reading under the Windows display driver model.
* **``nvidia-smi``** — everywhere else, when it is on PATH: the card's load and
  memory, and per-process memory for compute processes.

A machine with neither has no reading, and :meth:`GpuReader.read` says so with
``None`` rather than a zero that would look like an idle card.

Nothing here runs unless :meth:`GpuReader.read` is called, and a reader that
failed once stops trying: a missing counter set does not come back.
"""

from __future__ import annotations

import contextlib
import ctypes
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

_MB = 1024 * 1024
_PDH_FMT_DOUBLE = 0x00000200
_PDH_FMT_NOCAP100 = 0x00008000
_PDH_MORE_DATA = 0x800007D2
_PID_RE = re.compile(r"pid_(\d+)_luid_(\w+?_\w+?)_phys_(\d+)(?:_eng_\d+_engtype_(.+))?$")
_ADAPTER_RE = re.compile(r"luid_(\w+?_\w+?)_phys_(\d+)")
#: ``nvidia-smi`` costs a process start; the card's load does not need it more often.
_SMI_MIN_INTERVAL_S = 4.0
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
_GPU_QUERY = "--query-gpu=name,utilization.gpu,memory.used,memory.total"


@dataclass(slots=True)
class GpuReading:
    """One look at the graphics card."""

    name: str = ""
    util_percent: float = 0.0
    memory_used_mb: float = 0.0
    memory_total_mb: float = 0.0
    #: pid -> (share of the card 0-100, dedicated memory in bytes)
    processes: dict[int, tuple[float, int]] = field(default_factory=dict)
    per_process: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "util_percent": round(min(100.0, self.util_percent), 1),
            "memory_used_mb": round(self.memory_used_mb, 1),
            "memory_total_mb": round(self.memory_total_mb, 1),
            "per_process": self.per_process,
        }


class _Value(ctypes.Union):
    _fields_ = [
        ("long_value", ctypes.c_long),
        ("double_value", ctypes.c_double),
        ("large_value", ctypes.c_longlong),
        ("wide_value", ctypes.c_wchar_p),
    ]


class _CounterValue(ctypes.Structure):
    _fields_ = [("status", ctypes.c_ulong), ("value", _Value)]


class _Item(ctypes.Structure):
    _fields_ = [("name", ctypes.c_wchar_p), ("value", _CounterValue)]


class _WindowsCounters:
    """One open counter query, kept between reads because load is a rate."""

    _PATHS = {
        "engine": r"\GPU Engine(*)\Utilization Percentage",
        "process_memory": r"\GPU Process Memory(*)\Dedicated Usage",
        "adapter_memory": r"\GPU Adapter Memory(*)\Dedicated Usage",
    }

    def __init__(self) -> None:
        self._pdh = ctypes.WinDLL("pdh")  # type: ignore[attr-defined]
        self._pdh.PdhOpenQueryW.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_void_p]
        self._pdh.PdhAddEnglishCounterW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        self._pdh.PdhCollectQueryData.argtypes = [ctypes.c_void_p]
        self._pdh.PdhGetFormattedCounterArrayW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        self._pdh.PdhCloseQuery.argtypes = [ctypes.c_void_p]
        for function in (
            self._pdh.PdhOpenQueryW,
            self._pdh.PdhAddEnglishCounterW,
            self._pdh.PdhCollectQueryData,
            self._pdh.PdhGetFormattedCounterArrayW,
            self._pdh.PdhCloseQuery,
        ):
            function.restype = ctypes.c_ulong
        self._query = ctypes.c_void_p()
        if self._pdh.PdhOpenQueryW(None, None, ctypes.byref(self._query)) != 0:
            raise OSError("could not open a performance counter query")
        self._counters: dict[str, ctypes.c_void_p] = {}
        for key, path in self._PATHS.items():
            handle = ctypes.c_void_p()
            status = self._pdh.PdhAddEnglishCounterW(self._query, path, None, ctypes.byref(handle))
            if status == 0:
                self._counters[key] = handle
        if "engine" not in self._counters and "adapter_memory" not in self._counters:
            self.close()
            raise OSError("this system keeps no graphics counters")
        self._pdh.PdhCollectQueryData(self._query)

    def close(self) -> None:
        if self._query:
            self._pdh.PdhCloseQuery(self._query)
            self._query = ctypes.c_void_p()

    def _values(self, key: str) -> list[tuple[str, float]]:
        handle = self._counters.get(key)
        if handle is None:
            return []
        size = ctypes.c_ulong(0)
        count = ctypes.c_ulong(0)
        fmt = _PDH_FMT_DOUBLE | _PDH_FMT_NOCAP100
        status = self._pdh.PdhGetFormattedCounterArrayW(
            handle, fmt, ctypes.byref(size), ctypes.byref(count), None
        )
        if status != _PDH_MORE_DATA or size.value == 0:
            return []
        buffer = ctypes.create_string_buffer(size.value)
        status = self._pdh.PdhGetFormattedCounterArrayW(
            handle, fmt, ctypes.byref(size), ctypes.byref(count), buffer
        )
        if status != 0:
            return []
        items = ctypes.cast(buffer, ctypes.POINTER(_Item))
        rows: list[tuple[str, float]] = []
        for index in range(count.value):
            item = items[index]
            if item.value.status == 0 and item.name:
                rows.append((item.name, float(item.value.value.double_value)))
        return rows

    def read(self) -> GpuReading | None:
        """The adapters as the system counts them; None when it counts none."""
        self._pdh.PdhCollectQueryData(self._query)
        reading = GpuReading(per_process=True)
        by_pid: dict[int, dict[str, float]] = {}
        by_engine: dict[tuple[str, str], float] = {}
        for name, value in self._values("engine"):
            match = _PID_RE.search(name)
            if match is None:
                continue
            pid, adapter, kind = int(match.group(1)), match.group(2), match.group(4) or ""
            kinds = by_pid.setdefault(pid, {})
            kinds[kind] = kinds.get(kind, 0.0) + value
            by_engine[(adapter, kind)] = by_engine.get((adapter, kind), 0.0) + value
        memory: dict[int, int] = {}
        for name, value in self._values("process_memory"):
            match = _PID_RE.search(name)
            if match is not None:
                pid = int(match.group(1))
                memory[pid] = memory.get(pid, 0) + int(value)
        for pid in set(by_pid) | set(memory):
            share = max(by_pid.get(pid, {"": 0.0}).values())
            used = memory.get(pid, 0)
            if share >= 0.05 or used > 0:
                reading.processes[pid] = (min(100.0, share), used)
        # The busiest engine of the busiest adapter is the card's load, the way
        # the system's own monitor reads it.
        reading.util_percent = min(100.0, max(by_engine.values(), default=0.0))
        adapters = [
            value for name, value in self._values("adapter_memory") if _ADAPTER_RE.search(name)
        ]
        if not adapters and not by_engine:
            return None  # the counters exist, but this machine has no adapter to count
        reading.memory_used_mb = max(adapters, default=0.0) / _MB
        return reading


def _run_smi(arguments: list[str]) -> str:
    try:
        result = subprocess.run(
            ["nvidia-smi", *arguments, "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=4,
            check=False,
            creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout if result.returncode == 0 else ""


def _number(text: str) -> float:
    try:
        return float(text.strip())
    except ValueError:
        return 0.0


def parse_smi_gpus(output: str) -> GpuReading | None:
    """The busiest card out of ``--query-gpu=name,utilization.gpu,memory.used,memory.total``."""
    best: GpuReading | None = None
    for line in output.splitlines():
        cells = [cell.strip() for cell in line.split(",")]
        if len(cells) < 4:
            continue
        reading = GpuReading(
            name=cells[0],
            util_percent=_number(cells[1]),
            memory_used_mb=_number(cells[2]),
            memory_total_mb=_number(cells[3]),
        )
        if best is None or reading.memory_total_mb > best.memory_total_mb:
            best = reading
    return best


def parse_smi_processes(output: str) -> dict[int, tuple[float, int]]:
    """``--query-compute-apps=pid,used_memory`` as pid -> (0.0, bytes)."""
    found: dict[int, tuple[float, int]] = {}
    for line in output.splitlines():
        cells = [cell.strip() for cell in line.split(",")]
        if len(cells) >= 2 and cells[0].isdigit():
            found[int(cells[0])] = (0.0, int(_number(cells[1]) * _MB))
    return found


class GpuReader:
    """Reads the card on demand and remembers what does not change."""

    def __init__(self) -> None:
        self._counters: _WindowsCounters | None = None
        self._counters_failed = sys.platform != "win32"
        self._smi = shutil.which("nvidia-smi") is not None
        self._card: GpuReading | None = None
        self._card_lookup: threading.Thread | None = None
        self._smi_at = 0.0
        self._smi_reading: GpuReading | None = None

    def _card_facts(self) -> GpuReading | None:
        """Name and size of the card. Asked once, off the caller's thread.

        The tool takes a second to start and the answer never changes, so the
        first readings go out without a name rather than wait for it.
        """
        if self._card is None and self._smi and self._card_lookup is None:
            self._card_lookup = threading.Thread(
                target=self._look_up_card, name="gpu-card-facts", daemon=True
            )
            self._card_lookup.start()
        return self._card

    def _look_up_card(self) -> None:
        card = parse_smi_gpus(_run_smi([_GPU_QUERY]))
        if card is None:
            self._smi = False
        self._card = card

    def _read_smi(self) -> GpuReading | None:
        now = time.monotonic()
        if self._smi_reading is not None and now - self._smi_at < _SMI_MIN_INTERVAL_S:
            return self._smi_reading
        reading = parse_smi_gpus(_run_smi([_GPU_QUERY]))
        if reading is None:
            self._smi = False
            return None
        reading.processes = parse_smi_processes(_run_smi(["--query-compute-apps=pid,used_memory"]))
        reading.per_process = bool(reading.processes)
        self._smi_at, self._smi_reading = now, reading
        return reading

    def read(self) -> GpuReading | None:
        """The card right now, or None when this machine offers no reading."""
        if not self._counters_failed:
            try:
                if self._counters is None:
                    self._counters = _WindowsCounters()
                reading = self._counters.read()
            except Exception as exc:  # noqa: BLE001 - a counter set that is absent or broken
                logger.debug("GPU counters unavailable: {}", exc)
                self._counters_failed = True
                self.close()
            else:
                if reading is not None:
                    card = self._card_facts()
                    if card is not None:
                        reading.name = card.name
                        reading.memory_total_mb = card.memory_total_mb
                    return reading
        if self._smi:
            return self._read_smi()
        return None

    def close(self) -> None:
        if self._counters is not None:
            with contextlib.suppress(Exception):
                self._counters.close()
            self._counters = None
