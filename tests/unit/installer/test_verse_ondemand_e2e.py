"""The on-demand end-to-end script drives the real installer against a local server (A22.7)."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.unreal import ondemand_e2e, package


def test_download_flow_runs_from_not_installed_to_not_installed(tmp_path: Path) -> None:
    stage = tmp_path / "stage"
    for rel, data in {
        "Verse.exe": b"launcher",
        "Verse/Content/Paks/pakchunk0-Windows.ucas": b"core" * 50_000,
    }.items():
        path = stage / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    full = tmp_path / "Verse-Win64-4.2.0.tar"
    package.make_full(stage, version="4.2.0", platform="Win64", out=full)
    out = tmp_path / "report.json"
    code = ondemand_e2e.main(["--full", str(full), "--no-launch", "--out", str(out)])
    report = json.loads(out.read_text(encoding="utf-8"))
    assert code == 0
    assert [s["status"] for s in report["states"]] == [
        "not_installed",
        "installed",
        "installed",
        "not_installed",
    ]
    assert report["install_result"]["status"] == "installed"
    assert report["uninstall_result"]["leftovers"] == []
