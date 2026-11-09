"""The app-link Gauntlet runner: cases, scenarios, checks and the index it writes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.unreal import bridge_schema, parity_report
from tests.unit.verse_host.gauntlet import gauntlet

CASES = gauntlet.load_cases()


def test_every_case_names_a_gt_row_of_the_checklist() -> None:
    rows = {r.id: r for r in parity_report.parse_rows(parity_report.PARITY_FILE.read_text("utf-8"))}
    assert len({c.row for c in CASES}) == len(CASES)
    for case in CASES:
        assert case.row in rows, case.row
        assert "GT" in rows[case.row].kinds, f"{case.row} is not a GT row"


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.row)
def test_scenarios_are_valid_for_the_fake_bridge(case: gauntlet.Case) -> None:
    scenario = json.loads((gauntlet.SCENARIOS_DIR / case.scenario).read_text("utf-8"))
    assert bridge_schema.load().validate_scenario(scenario) == []
    last = scenario["steps"][-1]
    assert last["expect"]["type"] == "lifecycle.bye", "a scenario ends by quitting the game"


def test_a05_bounds_are_the_row_numbers() -> None:
    steps = json.loads((gauntlet.SCENARIOS_DIR / "a05_dormant_and_back.json").read_text("utf-8"))
    bounds = {
        s["expect"]["data"]["state"]: s["timeout_ms"]
        for s in steps["steps"]
        if "expect" in s and s["expect"].get("data", {}).get("state") == "dormant"
    }
    assert bounds == {"dormant": 1000}
    again = [s for s in steps["steps"] if "expect" in s and s["at_ms"] == 4000]
    assert again[0]["timeout_ms"] == 300


def test_test_names_map_to_parity_rows() -> None:
    case = gauntlet.Case("W-01", "x.json")
    assert case.test_name == "Verse.Parity.W.01"
    assert parity_report.unreal_row_id(case.test_name) == "W-01"


def test_data_checks_count_matching_frames() -> None:
    case = gauntlet.Case(
        "W-01",
        "x.json",
        data_checks=({"type": "progression.action", "match": {"action": "daily_visit"}, "eq": 1},),
    )
    report = {"received_data": {"progression.action": [{"action": "daily_visit"}, {"action": "x"}]}}
    assert gauntlet.check_data(case, report) == []
    report["received_data"]["progression.action"].append({"action": "daily_visit"})
    assert "expected 1 frames, got 2" in gauntlet.check_data(case, report)[0]
    assert gauntlet.check_data(case, {})[0].endswith("got 0")


def _report(**changes: object) -> dict:
    base = {"done": True, "expectations": [], "skipped": [], "invalid_from_verse": []}
    return {**base, **changes}


def test_evaluate_reports_every_kind_of_failure() -> None:
    case = gauntlet.Case("A-01", "a01_show.json")
    assert gauntlet.evaluate(case, _report(), 0, []) == []
    assert gauntlet.evaluate(case, {}, 0, [])[0].startswith("the fake bridge wrote no report")
    late = _report(
        expectations=[{"type": "lifecycle.state", "data": {}, "ok": False, "optional": False}]
    )
    assert "no lifecycle.state" in gauntlet.evaluate(case, late, 0, [])[0]
    optional = _report(expectations=[{"type": "x", "data": {}, "ok": False, "optional": True}])
    assert gauntlet.evaluate(case, optional, 0, []) == []
    problems = gauntlet.evaluate(case, _report(done=False, hung=True), 3, ["Fatal error"])
    assert len(problems) == 4


def test_game_command_for_the_editor_and_a_packaged_exe(tmp_path: Path) -> None:
    case = gauntlet.Case("A-01", "a01_show.json", game_args=("-VerseDeck=hangar",))
    kwargs = {
        "project": tmp_path / "Verse.uproject",
        "engine": tmp_path / "UE",
        "log_path": tmp_path / "l.log",
    }
    editor = gauntlet.game_command(case, exe=None, **kwargs)
    assert editor[0].endswith("UnrealEditor.exe")
    assert editor[2] == "-game"
    assert "-nullrhi" in editor
    assert "-VerseDeck=hangar" in editor
    packaged = gauntlet.game_command(case, exe=tmp_path / "Verse.exe", **kwargs)
    assert packaged[0].endswith("Verse.exe")
    assert "-game" not in packaged


def test_index_json_is_what_parity_report_reads(tmp_path: Path) -> None:
    ok = gauntlet.CaseResult(gauntlet.Case("A-01", "x"), passed=True)
    bad = gauntlet.CaseResult(gauntlet.Case("A-05", "x"), passed=False, problems=["late"])
    gauntlet.write_index([ok, bad], tmp_path)
    outcomes = parity_report.read_index(tmp_path)
    statuses = parity_report.build_report(
        parity_report.parse_rows(parity_report.PARITY_FILE.read_text("utf-8")), outcomes, []
    )
    by_id = {s.row.id: s.status for s in statuses}
    assert by_id["A-01"] == "green"
    assert by_id["A-05"] == "red"
    assert by_id["W-01"] == "missing"
