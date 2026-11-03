"""Gate math, planning and seeding of scripts/unreal/balance.py (WP10.5, A10.4)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from scripts.unreal import balance

FIXTURE_RUN = Path(__file__).parent / "fixtures" / "balance_run"


@pytest.fixture(scope="module")
def cfg():
    return balance.load_config()


def _hand_wilson(k: int, n: int) -> tuple[float, float]:
    z = 1.959963984540054
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return centre - half, centre + half


def test_wilson_matches_the_hand_formula_and_a_known_value():
    lo, hi = balance.wilson(45, 60)
    assert (lo, hi) == pytest.approx(_hand_wilson(45, 60))
    assert lo == pytest.approx(0.6277, abs=1e-4)
    assert hi == pytest.approx(0.8422, abs=1e-4)
    assert balance.wilson(0, 0) is None
    assert balance.wilson(0, 10)[0] == 0.0
    assert balance.wilson(10, 10)[1] == pytest.approx(1.0)


def test_trials_for_half_width_gives_267_at_one_half():
    assert balance.trials_for_half_width(0.5) == 267
    assert balance.trials_for_half_width(0.75) == 201
    assert balance.trials_for_half_width(0.9) == 97


def test_sets_build_the_contract_pairings(cfg):
    ladder = [p.id for p in balance.build_pairings(["ladder"], cfg)]
    assert ladder[:3] == ["hard_vs_normal", "elite_vs_hard", "elite_vs_normal"]
    assert {"normal_vs_normal", "hard_vs_hard", "elite_vs_elite"} <= set(ladder)
    tricks = balance.build_pairings(["tricks"], cfg)
    assert len(tricks) == 17
    assert all(p.id.endswith("_vs_hard") and p.a["tier"] == "hard" for p in tricks)
    elite = [p.id for p in balance.build_pairings(["elite"], cfg)]
    assert "skilled_vs_elite" in elite and "skilled+spray_vs_elite" in elite and len(elite) == 18
    learning = [p.id for p in balance.build_pairings(["learning"], cfg)]
    assert "hard_vs_repeek" in learning and "hard-nolearn_vs_repeek" in learning
    assert "hard_vs_repeek.reset" in learning
    allp = [p.id for p in balance.build_pairings(["all"], cfg)]
    assert len(allp) == len(set(allp))
    assert "wall_opened_unseen" in allp and "destruction_storm" in allp
    assert "adaptive_vs_skilled" in allp and "average_vs_normal" in allp


def test_trick_filter_limits_the_queue_subset(cfg):
    picked = balance.build_pairings(["tricks"], cfg, ["spray", "camper"])
    assert [p.id for p in picked] == ["spray_vs_hard", "camper_vs_hard"]


def test_units_are_seeded_the_same_for_any_job_count(cfg):
    pairings = balance.build_pairings(["ladder"], cfg)
    units = balance.plan_units(pairings, 25, run_seed=7, bouts_per_match=10)
    assert sum(u.bouts for u in units if u.pairing.id == "hard_vs_normal") == 25
    seeds = {(u.pairing.id, u.match): u.seed for u in units}
    for jobs in (1, 2, 4):
        shards = balance.shard_units(units, jobs)
        assert len(shards) == jobs
        flat = {(u.pairing.id, u.match): u.seed for s in shards for u in s}
        assert flat == seeds
    other = balance.plan_units(pairings, 25, run_seed=8, bouts_per_match=10)
    assert [u.seed for u in other] != [u.seed for u in units]


def test_jobs_are_capped_at_the_machine_limit(cfg):
    units = balance.plan_units(balance.build_pairings(["all"], cfg), 10, 1, 10)
    assert len(balance.shard_units(units, 16)) == 4


def test_reset_pairing_stays_in_one_process(cfg):
    units = balance.plan_units(balance.build_pairings(["learning"], cfg), 20, 1, 10)
    shards = balance.shard_units(units, 4)
    holders = [k for k, s in enumerate(shards) if any(u.pairing.id.endswith(".reset") for u in s)]
    assert len(holders) == 1
    reset = [u for u in shards[holders[0]] if u.pairing.id.endswith(".reset")]
    assert [u.match for u in reset] == [0, 1]


def test_scenario_documents_validate_against_the_schema(cfg, tmp_path):
    units = balance.plan_units(balance.build_pairings(["all"], cfg), 4, 1, 10)
    for k, shard in enumerate(balance.shard_units(units, 4)):
        doc = balance.scenario_document("r", k, shard, cfg, tmp_path, {"hard": {}}, True)
        assert balance.validate(doc, "scenario.schema.json") == []


def test_command_is_the_dedicated_server_of_bot_md_11_1(tmp_path):
    cmd = balance.command_for(
        Path("E"), Path("P.uproject"), "/Game/M", tmp_path / "s.json", tmp_path / "l.log"
    )
    for flag in ("-server", "-nullrhi", "-nosound", "-unattended", "-benchmark", "-fps=60"):
        assert flag in cmd
    assert any(c.startswith("-VerseHarness=") for c in cmd)


def test_fixture_bouts_give_the_hand_calculated_metrics(cfg):
    bouts, _speed, _log, _out = balance.collect(FIXTURE_RUN)
    pairing = next(p for p in balance.build_pairings(["ladder"], cfg) if p.id == "hard_vs_normal")
    (m,) = balance.aggregate([pairing], bouts)
    assert m["bouts"] == 4 and m["kills"] == 60
    assert m["boutWinRateA"] == 0.75
    assert m["killShareA"] == 0.75
    assert m["killShareA95"] == pytest.approx(list(_hand_wilson(45, 60)), abs=1e-6)
    assert m["spawnSide0WinRate"] == 0.75
    assert m["kd"] == {"a": 3.0, "b": pytest.approx(1 / 3, abs=1e-6)}
    assert m["accuracy"] == {"a": 0.4, "b": 0.25}
    assert m["headshotShare"]["a"] == pytest.approx(9 / 45)
    assert m["knifeShare"]["b"] == 1.0
    assert m["spawnKills"] == 4
    assert m["timeToContactS"] == {"a": 6.0, "b": 6.0}
    assert m["engagementRangeHist"]["10-20"] == 45 and m["engagementRangeHist"]["0-5"] == 15
    # First half of the 800 s match: A 30 of 38 kills; second half: A 15 of 22.
    assert m["learningDelta"] == pytest.approx(15 / 22 - 30 / 38, abs=1e-6)
    assert m["fireAudit"]["a"]["Unclassified"] == 0


def test_gates_on_the_fixture_equal_the_hand_calculation(cfg, tmp_path):
    bouts, _speed, _log, _out = balance.collect(FIXTURE_RUN)
    metrics = balance.aggregate(balance.build_pairings(["ladder"], cfg), bouts)
    gates = {g.id: g for g in balance.evaluate_gates(metrics, cfg, static_root=tmp_path)}
    assert gates["BG1"].status == "pass"
    assert gates["BG1"].values == {
        "boutWinRateA": 0.75,
        "killShareLower": pytest.approx(0.6277, abs=1e-4),
    }
    assert gates["BG2"].status == "not_run"
    assert gates["F4"].status == "pass" and gates["F4"].values["unclassified"] == 0
    assert gates["BG12"].status == "pass" and gates["BG12"].values["contactMedianS"] == 6.0
    assert gates["F1"].status == "pass" and gates["F6"].status == "pass"
    # F3 comes from an automation run; without it BG11 is not a pass.
    assert gates["BG11"].status == "not_run" and "F3" in gates["BG11"].detail
    checks = {"F3": {"status": "pass", "detail": "20 seeds"}}
    gates = {
        g.id: g for g in balance.evaluate_gates(metrics, cfg, static_root=tmp_path, checks=checks)
    }
    assert gates["BG11"].status == "pass"


def _m(pid, **kw):
    base = {
        "id": pid,
        "bouts": 100,
        "kills": 400,
        "shots": 1000,
        "boutWinRateA": 0.5,
        "killShareA": 0.5,
        "killShareA95": [0.45, 0.55],
        "spawnSide0": [50, 100],
        "learningDelta": 0.0,
        "adaptiveTrace": [],
        "killWindowB": [0, 0],
        "resetWindow": {},
        "fireAudit": {},
        "timeToContactSamples": [10.0],
        "matchTimeS": 6000.0,
        "stuckEvents": 0,
        "botMsP99": None,
        "bearingWindows": [],
        "f7Violations": None,
    }
    base.update(kw)
    return base


def test_bg1_fails_on_the_lower_bound(cfg, tmp_path):
    metrics = [_m("hard_vs_normal", boutWinRateA=0.8, killShareA95=[0.55, 0.65])]
    gate = {g.id: g for g in balance.evaluate_gates(metrics, cfg, static_root=tmp_path)}["BG1"]
    assert gate.status == "fail" and "lower" in gate.detail


def test_bg4_and_bg5_use_the_trick_bounds(cfg, tmp_path):
    metrics = [
        _m("spray_vs_hard", boutWinRateA=0.5, killShareA95=[0.4, 0.55]),
        _m("camper_vs_hard", boutWinRateA=0.52, killShareA95=[0.4, 0.5]),
        _m("skilled_vs_elite", killShareA=0.40),
        _m("skilled+spray_vs_elite", killShareA=0.46),
    ]
    gates = {g.id: g for g in balance.evaluate_gates(metrics, cfg, static_root=tmp_path)}
    assert gates["BG4"].status == "fail" and "camper_vs_hard boutWinRateA" in gates["BG4"].detail
    assert gates["BG5"].status == "fail"
    metrics[3]["killShareA"] = 0.45
    gates = {g.id: g for g in balance.evaluate_gates(metrics, cfg, static_root=tmp_path)}
    assert gates["BG5"].status == "pass"


def test_bg6_bg7_bands(cfg, tmp_path):
    metrics = [
        _m("skilled_vs_elite", killShareA=0.46),
        _m("skilled_vs_normal", killShareA=0.70),
        _m("average_vs_normal", killShareA=0.66),
    ]
    gates = {g.id: g for g in balance.evaluate_gates(metrics, cfg, static_root=tmp_path)}
    assert gates["BG6"].status == "pass"
    assert gates["BG7"].status == "fail"


def test_bg8_bg9_bg10(cfg, tmp_path):
    metrics = []
    for opp in ("repeek", "watcher", "camper"):
        metrics.append(_m(f"hard_vs_{opp}", learningDelta=0.06, killShareA=0.60))
        metrics.append(_m(f"hard-nolearn_vs_{opp}", killShareA=0.56))
    metrics.append(_m("hard_vs_repeek.reset", resetWindow={"0": [30, 50], "1": [29, 50]}))
    metrics.append(_m("adaptive_vs_skilled", killWindowB=[15, 30], adaptiveTrace=[0.5, 0.53, 0.55]))
    metrics.append(_m("adaptive_vs_average", killWindowB=[11, 30], adaptiveTrace=[0.5, 0.56]))
    gates = {g.id: g for g in balance.evaluate_gates(metrics, cfg, static_root=tmp_path)}
    assert gates["BG8"].status == "pass"
    assert gates["BG9"].status == "pass"
    assert gates["BG10"].status == "fail"
    assert "adaptive_vs_average person kill share" in gates["BG10"].detail
    assert "largest step 0.060" in gates["BG10"].detail


def test_bg3_needs_the_mirrors_and_spawn_side(cfg, tmp_path):
    metrics = [
        _m("elite_vs_normal", boutWinRateA=0.92, killShareA=0.8),
        _m("normal_vs_normal", spawnSide0=[30, 50]),
        _m("hard_vs_hard", spawnSide0=[30, 50]),
        _m("elite_vs_elite", spawnSide0=[30, 50]),
    ]
    gates = {g.id: g for g in balance.evaluate_gates(metrics, cfg, static_root=tmp_path)}
    assert gates["BG3"].status == "fail" and "spawn side" in gates["BG3"].detail


def test_null_brain_runs_report_not_run_instead_of_fail(cfg, tmp_path):
    metrics = [
        _m(
            "hard_vs_normal",
            kills=0,
            shots=0,
            boutWinRateA=0.0,
            killShareA=None,
            killShareA95=None,
            timeToContactSamples=[],
        )
    ]
    gates = {g.id: g for g in balance.evaluate_gates(metrics, cfg, static_root=tmp_path)}
    assert gates["BG1"].status == "not_run" and "null brain" in gates["BG1"].detail
    assert gates["BG12"].status == "not_run"


def test_f4_f5_f7_l1(cfg, tmp_path):
    windows = [[0.0, 5.0, 100.0]] * 1000 + [[0.0, 100.0, 5.0]] * 1000
    metrics = [
        _m(
            "hard_vs_normal",
            fireAudit={"a": {"Unclassified": 2, "shots": 10}},
            bearingWindows=windows,
        ),
        _m("wall_opened_unseen", f7Violations=1),
    ]
    gates = {
        g.id: g
        for g in balance.evaluate_gates(
            metrics,
            cfg,
            static_root=tmp_path,
            l1_findings=["x: holds match-memory field"],
            nightly=True,
        )
    }
    assert gates["F4"].status == "fail"
    assert gates["F5"].status == "pass" and gates["F5"].values["excess"] == 0.0
    assert gates["F7"].status == "fail"
    assert gates["L1"].status == "fail"
    assert gates["BG11"].status == "fail"


def test_f5_statistic_is_true_minus_decoy():
    assert balance.f5_statistic([[10, 12, 200], [10, 200, 200], [0, 359, 180]]) == pytest.approx(
        2 / 3
    )
    assert balance.f5_statistic([]) is None


def test_l1_scan_finds_match_memory_in_new_files(tmp_path):
    old = tmp_path / "old.json"
    old.write_text("PeekHabits", encoding="utf-8")
    import os
    import time

    os.utime(old, (time.time() - 3600, time.time() - 3600))
    since = time.time() - 60
    (tmp_path / "SaveGames").mkdir()
    (tmp_path / "SaveGames" / "slot.sav").write_bytes(b"..PositionHeatmap..")
    hits = balance.l1_scan(
        [tmp_path], ["PositionHeatmap", "PeekHabits"], since, ['{"t":"duel.result"}']
    )
    assert len(hits) == 1 and "PositionHeatmap" in hits[0]
    # The run's own job folder is exempt; a bot log elsewhere is not.
    run = tmp_path / "Harness" / "balance" / "r1" / "job0"
    run.mkdir(parents=True)
    (run / "job0.log").write_text("PeekHabits", encoding="utf-8")
    (run / "bouts.jsonl").write_text("PeekHabits", encoding="utf-8")
    (tmp_path / "Bot").mkdir()
    (tmp_path / "Bot" / "bot.log").write_text("PeekHabits", encoding="utf-8")
    hits = balance.l1_scan(
        [tmp_path], ["PeekHabits"], since, exclude=[tmp_path / "Harness" / "balance" / "r1"]
    )
    assert len(hits) == 1 and "bot.log" in hits[0]
    assert balance.l1_scan([], ["PeekHabits"], since, ['{"PeekHabits":1}'])


def test_fire_audit_lines_are_attributed_by_server_window():
    text = (
        "x [VerseFireAudit] ServerTimeMs=1500 Mode=Visible bTargetVisible=1\n"
        '[VerseFireAudit] {"serverTimeMs": 2500, "mode": "EVerseBotFireMode::WallShot"}\n'
        "[VerseFireAudit] ServerTimeMs=2600 Mode=Guess\n"
        "[VerseFireAudit] ServerTimeMs=9000 Mode=Visible\n"
        "[VerseFireAudit] Mode=Visible\nnoise\n"
    )
    shots, unparsed = balance.parse_fire_audit(text)
    assert shots == [
        (1500.0, "Visible"),
        (2500.0, "WallShot"),
        (2600.0, "Unclassified"),
        (9000.0, "Visible"),
    ]
    assert unparsed == 1
    bouts = [
        {"bout": 0, "serverStartMs": 1000, "serverEndMs": 2000, "a": {}, "b": {}},
        {"bout": 1, "serverStartMs": 2000, "serverEndMs": 3000, "a": {}, "b": {}},
    ]
    assert balance.attribute_fire_audit(bouts, shots) == 1
    assert bouts[0]["fireAudit"] == {"Visible": 1}
    assert bouts[1]["fireAudit"] == {"WallShot": 1, "Unclassified": 1}


def test_f4_counts_window_attributed_shots_against_bot_shots(cfg):
    pairing = next(p for p in balance.build_pairings(["ladder"], cfg) if p.id == "hard_vs_normal")
    bout = {
        "pairing": pairing.id,
        "match": 0,
        "bout": 0,
        "spawnSideA": 0,
        "winner": "none",
        "durationS": 10.0,
        "kills": [],
        "a": {"shots": 3},
        "b": {"shots": 2},
        "fireAudit": {"Visible": 4},
    }
    (m,) = balance.aggregate([pairing], [bout])
    assert m["fireAudit"]["bots"] == {
        "Visible": 4,
        "Suppression": 0,
        "Prefire": 0,
        "WallShot": 0,
        "Unclassified": 1,
        "shots": 5,
    }
    assert balance.gate_f4({m["id"]: m}).status == "fail"
    bout["fireAudit"] = {"Visible": 4, "Prefire": 1}
    (m,) = balance.aggregate([pairing], [bout])
    assert balance.gate_f4({m["id"]: m}).status == "pass"
    assert balance.gate_f4({m["id"]: m}, unattributed=2).status == "fail"


def test_f4_with_no_bot_shot_is_not_run():
    m = _m("hard_vs_normal", fireAudit={"bots": {"Unclassified": 0, "shots": 0}})
    gate = balance.gate_f4({"hard_vs_normal": m})
    assert gate.status == "not_run" and "null brain" in gate.detail


def test_bg11_passes_only_when_every_part_passed():
    def parts(**states):
        return {g: balance.Gate(g, s, "") for g, s in states.items()}

    assert balance.gate_bg11(parts(F3="pass", F4="pass"), False).status == "pass"
    assert balance.gate_bg11(parts(F3="not_run", F4="pass"), False).status == "not_run"
    assert balance.gate_bg11(parts(F3="fail", F4="not_run"), False).status == "fail"
    nightly = parts(F3="pass", F4="pass", F5="pass", F7="not_run", L1="pass")
    gate = balance.gate_bg11(nightly, True)
    assert gate.status == "not_run" and "F7" in gate.detail


def _job(run: Path, k: int, units: list[dict], bouts: list[dict], speed: dict | None) -> None:
    job = run / f"job{k}"
    job.mkdir(parents=True)
    (job / "scenario.json").write_text(json.dumps({"units": units}), encoding="utf-8")
    (job / "bouts.jsonl").write_text("".join(json.dumps(b) + "\n" for b in bouts), encoding="utf-8")
    if speed is not None:
        (job / "speed.json").write_text(json.dumps(speed), encoding="utf-8")


def test_completeness_names_crashed_jobs_guards_and_short_units(tmp_path):
    run = tmp_path / "run"
    full = {"pairing": "p", "match": 0, "bouts": 2}
    short = {"pairing": "q", "match": 1, "bouts": 3}
    _job(run, 0, [full], [{"pairing": "p", "match": 0}] * 2, {"job": 0, "end": "all units played"})
    _job(
        run,
        1,
        [short],
        [{"pairing": "q", "match": 1}],
        {"job": 1, "end": "wall-clock guard reached"},
    )
    bouts = [{"pairing": "p", "match": 0}] * 2 + [{"pairing": "q", "match": 1}]
    speed = [json.loads((run / f"job{k}" / "speed.json").read_text()) for k in (0, 1)]
    results = [
        {"job": 0, "returncode": 0, "log": "l0"},
        {"job": 1, "returncode": 3, "log": "l1"},
    ]
    problems = balance.completeness(run, bouts, speed, results)
    assert any("job 1 exited 3" in p for p in problems)
    assert any("wall-clock guard" in p for p in problems)
    assert any("q#1: 1 of 3 bouts" in p for p in problems)
    assert not any("p#0" in p for p in problems)


def test_from_bouts_fails_a_short_run(tmp_path):
    run = tmp_path / "run"
    lines = (FIXTURE_RUN / "job0" / "bouts.jsonl").read_text(encoding="utf-8").splitlines()
    unit = {"pairing": "hard_vs_normal", "match": 0, "bouts": len(lines) + 1}
    _job(run, 0, [unit], [json.loads(x) for x in lines], {"job": 0, "end": "all units played"})
    code = balance.main(["--from-bouts", str(run), "--gates", "BG1", "--worktree", str(tmp_path)])
    assert code == 1
    report = json.loads((run / "report.json").read_text(encoding="utf-8"))
    assert report["incomplete"] == [
        f"unit hard_vs_normal#0: {len(lines)} of {len(lines) + 1} bouts"
    ]


def test_checks_from_automation_reports(tmp_path):
    report = tmp_path / "Automation" / "20261102-1"
    report.mkdir(parents=True)
    tests = [
        {"fullTestPath": "Verse.Bot.Fairness.Counterfactual.Seed1", "state": "Success"},
        {"fullTestPath": "Verse.Bot.Fairness.Counterfactual.Seed2", "state": "Fail"},
        {"fullTestPath": "Verse.Combat.Perception.F2.Opaque", "state": "Success"},
        {"fullTestPath": "Verse.Harness.World.TierAndPatch", "state": "Success"},
    ]
    (report / "index.json").write_text(json.dumps({"tests": tests}), encoding="utf-8-sig")
    checks = balance.checks_from_automation(tmp_path / "Automation")
    assert checks["F3"]["status"] == "fail" and "Seed2" in checks["F3"]["detail"]
    assert checks["F2"]["status"] == "pass"
    assert "BR1" not in checks
    assert balance.checks_from_automation(tmp_path / "missing") == {}


def test_l1_pairing_is_one_30_minute_match_without_a_kill_cap(cfg):
    (pairing,) = [p for p in balance.build_pairings(["fairness"], cfg) if p.id.endswith(".l1")]
    (unit,) = balance.plan_units([pairing], 200, 1, 10)
    doc = unit.to_json(cfg, None)
    assert doc["matchTimeLimitS"] == 1800.0 and doc["bouts"] == 1
    assert doc["killsToWin"] >= 1_000_000


def test_queue_bout_count_matches_the_workflow():
    workflow = (
        Path(__file__).resolve().parents[3] / ".github" / "workflows" / "unreal-gauntlet.yml"
    ).read_text(encoding="utf-8")
    assert f"--bouts {balance.QUEUE_BOUTS} " in workflow
    table = json.loads(balance.BOUT_TABLE_FILE.read_text(encoding="utf-8"))
    assert table["queueBouts"] == balance.QUEUE_BOUTS
    assert table["provisional"] and all(row["wallHours"] is None for row in table["gates"].values())


def test_report_matches_the_balance_schema(cfg, tmp_path):
    bouts, _speed, log, _out = balance.collect(FIXTURE_RUN)
    metrics = balance.aggregate(balance.build_pairings(["ladder"], cfg), bouts)
    gates = balance.evaluate_gates(metrics, cfg, static_root=tmp_path)
    report = balance.build_report(
        "r",
        1,
        ["ladder"],
        metrics,
        gates,
        bouts=4,
        jobs=1,
        patch=None,
        speed=None,
        fire_audit_log=log,
    )
    assert balance.validate(report, "balance.schema.json") == []
    json.dumps(report)


def test_from_bouts_cli_writes_a_report_and_passes(tmp_path):
    run = tmp_path / "run"
    (run / "job0").mkdir(parents=True)
    (run / "job0" / "bouts.jsonl").write_text(
        (FIXTURE_RUN / "job0" / "bouts.jsonl").read_text(encoding="utf-8"), encoding="utf-8"
    )
    code = balance.main(
        ["--from-bouts", str(run), "--gates", "BG1,F4", "--worktree", str(tmp_path)]
    )
    assert code == 0
    report = json.loads((run / "report.json").read_text(encoding="utf-8"))
    assert [g["id"] for g in report["gates"]] == ["BG1", "F4"]


def test_speed_summary_and_bout_table(cfg):
    speed = balance.speed_summary(
        [
            {"simS": 2400, "wallS": 100, "startupS": 30, "peakRamMb": 2000},
            {"simS": 2000, "wallS": 100},
        ]
    )
    assert speed["xRealTimePerProcess"] == 20.0 and speed["meetsTarget"]
    table = balance.bout_table(
        speed,
        kills_per_bout=22,
        bout_sim_s=240,
        jobs=4,
        pairings_per_gate=balance.pairings_per_gate(cfg),
    )
    assert table["gates"]["BG4"]["boutsPerPairing"] == 267
    assert table["gates"]["BG6"]["boutsPerPairing"] == math.ceil(257 / 22)
    assert table["fullWidthQueueBouts"] == 267
    assert table["queueBouts"] == balance.QUEUE_BOUTS
    assert table["queueHalfWidth"]["boutShare"] == pytest.approx(0.148, abs=0.002)
    assert table["gates"]["BG1"]["wallHours"] is not None and table["provisional"] is None
    rough = balance.bout_table(speed, provisional="null brain")
    assert rough["provisional"] == "null brain"
    assert all(row["wallHours"] is None for row in rough["gates"].values())
    assert balance.speed_summary([]) is None


def test_run_jobs_writes_scenarios_and_launches_under_the_lock(cfg, tmp_path):
    held = []

    class Lock:
        def __init__(self, label, command):
            held.append(label)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            held.append("released")

    class Proc:
        def wait(self, timeout=None):
            return 0

    launched = []
    units = balance.plan_units(balance.build_pairings(["ladder"], cfg), 2, 1, 10)
    shards = balance.shard_units(units, 2)
    result = balance.run_jobs(
        shards,
        cfg,
        tmp_path,
        "r",
        patch=None,
        trace_bearing=False,
        engine=Path("E"),
        project=Path("P"),
        launcher=lambda cmd, log: launched.append(cmd) or Proc(),
        lock_factory=Lock,
    )
    assert held == ["balance", "released"]
    assert len(launched) == 2 and all(r["returncode"] == 0 for r in result)
    assert (tmp_path / "job0" / "scenario.json").exists()
