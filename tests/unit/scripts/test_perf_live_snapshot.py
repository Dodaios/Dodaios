"""Focused checks for the read-only live resource sampler."""

from scripts.perf_live_snapshot import _role, _summary


class _Process:
    def __init__(self, pid: int, name: str, args: list[str]) -> None:
        self.pid = pid
        self._name = name
        self._args = args

    def name(self) -> str:
        return self._name

    def cmdline(self) -> list[str]:
        return self._args


def test_roles_keep_hosted_agent_and_webview_separate() -> None:
    assert _role(_Process(10, "python.exe", []), 10) == "backend"
    assert _role(_Process(11, "msedgewebview2.exe", ["--type=gpu-process"]), 10) == (
        "webview:gpu-process"
    )
    assert _role(_Process(12, "codex.exe", []), 10) == "coding-agent"


def test_summary_aggregates_multiple_processes_in_one_role() -> None:
    def row(pid: int, cpu: float, rss: float) -> dict:
        return {
            "pid": pid,
            "scope": "jarvis-family",
            "role": "webview:renderer",
            "cpu_one_core_pct": cpu,
            "rss_mb": rss,
            "commit_mb": 20.0,
            "connections": {"established": 1, "listen": 0, "other": 0},
        }

    result = {
        "root_pid": 10,
        "duration_seconds": 2.0,
        "logical_cpus": 16,
        "other_backend_pids": [20],
        "health_probes": [],
        "samples": [
            {"processes": [row(11, 2, 100), row(12, 3, 200)]},
            {"processes": [row(11, 4, 110), row(12, 6, 210)]},
        ],
    }
    summary = _summary(result)
    line = next(line for line in summary.splitlines() if "webview:renderer" in line)
    assert "2  " in line
    assert "7.50/ 10.00" in line
    assert "320.0" in line
    assert "40.0" in line


def test_summary_separates_private_memory_from_commit_and_totals_the_app() -> None:
    def row(pid: int, role: str, scope: str, private: float | None, commit: float) -> dict:
        return {
            "pid": pid,
            "scope": scope,
            "role": role,
            "cpu_one_core_pct": 1.0,
            "rss_mb": 60.0,
            "private_mb": private,
            "peak_rss_mb": 900.0,
            "commit_mb": commit,
            "threads": 8,
            "connections": None,
        }

    processes = [
        row(10, "backend", "jarvis-family", 700.0, 1500.0),
        row(11, "dictation-preview", "jarvis-family", 50.0, 2100.0),
        row(12, "coding-agent", "external", None, 800.0),
    ]
    result = {
        "root_pid": 10,
        "label": "idle",
        "duration_seconds": 2.0,
        "logical_cpus": 16,
        "other_backend_pids": [],
        "health_probes": [],
        "samples": [{"processes": processes}],
    }

    summary = _summary(result)

    assert "label=idle" in summary.splitlines()[0]
    dictation = next(line for line in summary.splitlines() if "dictation-preview" in line)
    # A loaded model that lives in VRAM: almost no RAM, a large reservation.
    assert "50.0" in dictation
    assert "2100.0" in dictation
    agent = next(line for line in summary.splitlines() if "coding-agent" in line)
    assert "n/a" in agent  # private memory is read for the app's own tree only
    total = next(line for line in summary.splitlines() if line.startswith("app total"))
    assert "2 processes" in total
    assert "CPU 2.00% of one core" in total
    assert "private 750.0 MB" in total
    assert "commit 3600.0 MB" in total
