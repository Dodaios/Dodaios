"""scripts/unreal/parity_report.py: rows, id matching and the report states."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.unreal import parity_report as pr

TABLE = """
## 1. How a row passes

| Id | Feature | Today | Check |
|---|---|---|---|
| X-99 | ignored, section 1 | n/a | `AT` |

## 2. Mounts

| Id | Feature | Today | Unreal acceptance check |
|---|---|---|---|
| A-01 | First | `a.tsx:1` | `VT`: x; `GT`: y |
| A-02 | Second | n/a | `AT` |
| D-07 | Third | n/a | `AT` |

## 20. Gaps

| Id | Feature | Today | Check |
|---|---|---|---|
| G-01 | ignored, section 20 | n/a | `AT` |
"""


def _index(tmp_path: Path, tests: dict[str, str], name: str = "run") -> Path:
    folder = tmp_path / name
    folder.mkdir()
    payload = {"tests": [{"fullTestPath": n, "state": s} for n, s in tests.items()]}
    (folder / "index.json").write_text(json.dumps(payload), encoding="utf-8")
    return folder


def test_rows_come_from_sections_2_to_19_with_their_kinds() -> None:
    rows = pr.parse_rows(TABLE)
    assert [r.id for r in rows] == ["A-01", "A-02", "D-07"]
    assert rows[0].kinds == ("GT", "VT")
    assert rows[1].kinds == ("AT",)


def test_the_real_checklist_has_245_rows() -> None:
    rows = pr.parse_rows(pr.PARITY_FILE.read_text(encoding="utf-8"))
    assert len(rows) == 245
    assert len({r.id for r in rows}) == 245


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Verse.Parity.D.07", "D-07"),
        ("Verse.Parity.Duel.D07", "D-07"),
        ("Verse.Parity.D_07.Case2", "D-07"),
        ("Verse.Parity.Q.12.Nullrhi", "Q-12"),
        ("Verse.Combat.D.07", None),
        ("Verse.Parity.Nothing", None),
    ],
)
def test_unreal_ids(name: str, expected: str | None) -> None:
    assert pr.unreal_row_id(name) == expected


def test_pytest_ids() -> None:
    assert pr.pytest_row_id("test_parity_k_02_never_pulls_focus") == "K-02"
    assert pr.pytest_row_id("test_other_k_02") is None


def test_status_green_red_missing(tmp_path: Path) -> None:
    rows = pr.parse_rows(TABLE)
    folder = _index(
        tmp_path,
        {
            "Verse.Parity.A.01": "Success",
            "Verse.Parity.A.02": "Success",
            "Verse.Parity.A.02.Second": "Fail",
        },
    )
    statuses = pr.build_report(rows, pr.read_index(folder), [])
    assert {s.row.id: s.status for s in statuses} == {
        "A-01": "green",
        "A-02": "red",
        "D-07": "missing",
    }
    assert pr.summary_line(statuses) == "1/3 green"


def test_junit_results_count_for_the_row(tmp_path: Path) -> None:
    xml = tmp_path / "j.xml"
    xml.write_text(
        '<testsuite><testcase classname="t.test_x" name="test_parity_d_07_ok"/>'
        '<testcase classname="t.test_x" name="test_parity_a_01_bad"><failure/></testcase>'
        "</testsuite>",
        encoding="utf-8",
    )
    statuses = pr.build_report(pr.parse_rows(TABLE), [], pr.read_junit(xml))
    assert {s.row.id: s.status for s in statuses} == {
        "A-01": "red",
        "A-02": "missing",
        "D-07": "green",
    }


def test_main_writes_the_report_and_fails_while_rows_are_open(tmp_path: Path, capsys) -> None:
    parity = tmp_path / "parity.md"
    parity.write_text(TABLE, encoding="utf-8")
    folder = _index(tmp_path, {"Verse.Parity.A.01": "Success"})
    out = tmp_path / "out"
    code = pr.main(["--parity-file", str(parity), "--index", str(folder), "--out", str(out)])
    assert code == 1
    assert capsys.readouterr().out.strip().endswith("1/3 green")
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert report["missing"] == 2
    assert "A-02" in (out / "report.md").read_text(encoding="utf-8")


def test_main_exits_zero_when_every_row_is_green(tmp_path: Path) -> None:
    parity = tmp_path / "parity.md"
    parity.write_text(TABLE, encoding="utf-8")
    folder = _index(
        tmp_path,
        {
            "Verse.Parity.A.01": "Success",
            "Verse.Parity.A.02": "Success",
            "Verse.Parity.D.07": "Success",
        },
    )
    assert (
        pr.main(
            ["--parity-file", str(parity), "--index", str(folder), "--out", str(tmp_path / "o")]
        )
        == 0
    )
