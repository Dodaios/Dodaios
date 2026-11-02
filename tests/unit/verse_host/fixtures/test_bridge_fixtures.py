"""Every verse.bridge/1 golden fixture validates against the shared schema (G0.11)."""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest

from scripts.unreal import bridge_schema

DATA = bridge_schema.DATA_DIR
SCHEMA = bridge_schema.load()


def _golden(type_: str) -> list[dict]:
    return bridge_schema.read_json(DATA / "messages" / f"{type_}.json")


def test_every_fixture_and_the_mirror_check_clean() -> None:
    assert bridge_schema.check_all() == []


@pytest.mark.parametrize(
    "check",
    [
        bridge_schema.check_messages,
        bridge_schema.check_replies,
        bridge_schema.check_cells,
        bridge_schema.check_scenarios,
    ],
)
def test_each_fixture_family_validates(check) -> None:
    assert check(SCHEMA, DATA) == []


def test_mirror_reads_the_same_fixtures() -> None:
    assert bridge_schema.check_mirror() == []
    mirrored = bridge_schema.Schema(
        bridge_schema.read_json(bridge_schema.MIRROR_DIR / bridge_schema.SCHEMA_FILE)
    )
    assert mirrored.messages == SCHEMA.messages


def test_catalogue_covers_every_contract_message() -> None:
    # bridge-protocol.md section 8, including the section 14 parity additions.
    contract = {
        "hello", "welcome", "ping", "pong", "subscribe", "unsubscribe", "resync",
        "roster.snapshot", "roster.delta",
        "screens.watch", "screens.meta", "screens.frame", "screens.gone",
        "chat_tails.watch", "chat_tails.update",
        "groups.snapshot", "groups.delta", "meetings.update", "meeting.start", "meeting.stop",
        "progression.snapshot", "progression.awarded", "progression.action", "duel.result",
        "pane.open", "agent.open", "ide.focus_terminal", "agent.create", "launcher.start",
        "launcher.options",
        "lifecycle.show", "lifecycle.hide", "lifecycle.pause", "lifecycle.resume", "lifecycle.quit",
        "panel.visibility", "panel.resize", "gpu.yield", "gpu.free", "settings.changed",
        "focus.app_took", "lifecycle.state", "lifecycle.ready", "focus.return_to_app",
        "window.state", "panel.stream_state", "lifecycle.bye",
        "agents.open_list", "group.open", "simulator.open", "ide.open", "launcher.cancel",
        "settings.set", "progression.told", "qa.exec", "companion.snapshot", "companion.update",
        "reply", "log",
    }  # fmt: skip
    assert set(SCHEMA.messages) == contract
    for type_ in contract:
        assert (DATA / "messages" / f"{type_}.json").is_file(), type_


def test_every_command_has_request_reply_pairs() -> None:
    for command in SCHEMA.commands():
        pairs = bridge_schema.read_json(DATA / "replies" / f"{command}.json")
        assert any(p["reply"]["data"]["ok"] for p in pairs), command


def test_error_codes_are_the_contract_set_and_each_has_a_golden_reply() -> None:
    codes = set(SCHEMA.document["x-error-codes"])
    assert codes == {
        "bad_request", "not_found", "conflict", "busy", "unavailable", "rate_limited", "internal"
    }  # fmt: skip
    seen = set()
    for path in (DATA / "replies").glob("*.json"):
        for pair in bridge_schema.read_json(path):
            data = pair["reply"]["data"]
            if not data["ok"]:
                seen.add(data["error"]["code"])
    assert seen == codes


def test_first_golden_frames_are_the_contract_examples() -> None:
    delta = _golden("roster.delta")[0]
    assert (delta["seq"], delta["base"]) == (57, 49)
    assert delta["data"]["remove"]["panes"] == ["ws_91:T3"]
    frame = _golden("screens.frame")[0]
    assert frame["data"]["rows_changed"][0]["runs"][0]["text"] == "✔ tests passed"
    assert _golden("welcome")[0]["data"]["limits"]["screens_max_panes"] == 8
    duel = _golden("duel.result")[0]["data"]
    assert (duel["outcome"], duel["score"]) == ("won", {"player": 10, "opponent": 7})


def test_unknown_enum_value_fails_golden_but_falls_back_for_a_live_reader() -> None:
    frame = copy.deepcopy(_golden("roster.delta")[0])
    frame["data"]["upsert"]["agents"][0]["duty"] = "on_leave"
    assert any("on_leave" in e for e in SCHEMA.validate_frame(frame))
    assert SCHEMA.validate_frame(frame, lenient=True) == []
    duty = SCHEMA.document["$defs"]["duty"]
    assert duty["x-fallback"] == "idle"


def test_unknown_field_fails_golden_but_is_ignored_by_a_live_reader() -> None:
    frame = copy.deepcopy(_golden("roster.snapshot")[0])
    frame["data"]["agents"][0]["mood"] = "calm"
    assert SCHEMA.validate_frame(frame)
    assert SCHEMA.validate_frame(frame, lenient=True) == []


def test_enum_without_fallback_stays_strict_for_live_readers() -> None:
    frame = copy.deepcopy(_golden("lifecycle.hide")[0])
    frame["data"]["reason"] = "sleep"
    assert SCHEMA.validate_frame(frame, lenient=True)


@pytest.mark.parametrize(
    ("type_", "mutate", "needle"),
    [
        ("roster.delta", lambda f: f.pop("base"), "base"),
        ("roster.delta", lambda f: f.update(base=f["seq"]), "not below seq"),
        ("subscribe", lambda f: f.pop("id"), "id"),
        ("reply", lambda f: f.pop("re"), "re"),
        ("welcome", lambda f: f.pop("seq"), "seq"),
        ("hello", lambda f: f.update(id="c-1"), "id"),
        ("screens.frame", lambda f: f["data"].update(cols=241), "241"),
        ("chat_tails.update", lambda f: f["data"]["lines"][1].update(text="x" * 81), "valid under"),
        ("meetings.update", lambda f: f["data"]["messages"][0].update(text="y" * 201), "long"),
        ("progression.action", lambda f: f["data"].update(action="duel_won"), "duel_won"),
        ("pane.open", lambda f: f["data"].update(pane_id="no-colon"), "does not match"),
    ],
)
def test_validator_rejects_broken_frames(type_, mutate, needle) -> None:
    frame = copy.deepcopy(_golden(type_)[0])
    mutate(frame)
    errors = SCHEMA.validate_frame(frame)
    assert errors and any(needle in e for e in errors), errors


def test_screens_frame_runs_must_fit_the_grid() -> None:
    frame = copy.deepcopy(_golden("screens.frame")[0])
    frame["data"]["rows_changed"][0]["runs"][1]["col"] = 10  # overlaps the first run
    assert any("overlaps" in e for e in SCHEMA.validate_frame(frame))
    frame = copy.deepcopy(_golden("screens.frame")[0])
    frame["data"]["rows_changed"][0]["row"] = 40
    assert any("outside" in e for e in SCHEMA.validate_frame(frame))


def test_snapshot_frames_carry_ref_cut_at_and_no_base() -> None:
    snap = copy.deepcopy(_golden("screens.frame")[1])
    assert snap["data"]["kind"] == "snapshot" and "base" not in snap
    assert SCHEMA.validate_frame(snap) == []
    del snap["data"]["ref"]
    assert SCHEMA.validate_frame(snap)
    snap = copy.deepcopy(_golden("screens.frame")[1])
    snap["base"] = 1
    assert SCHEMA.validate_frame(snap)


def test_reply_result_is_checked_against_its_command() -> None:
    pair = bridge_schema.read_json(DATA / "replies" / "screens.watch.json")[0]
    assert SCHEMA.validate_reply(pair["reply"], "screens.watch") == []
    broken = copy.deepcopy(pair["reply"])
    broken["data"]["result"]["bound"][0]["ref"] = 0
    assert SCHEMA.validate_reply(broken, "screens.watch")
    assert SCHEMA.validate_reply(pair["reply"], "roster.snapshot")


def test_scenario_validation_catches_bad_steps() -> None:
    scenario = bridge_schema.read_json(DATA / "scenarios" / "panel.json")
    assert SCHEMA.validate_scenario(scenario) == []
    bad = copy.deepcopy(scenario)
    bad["steps"][0]["frame"]["seq"] = 5
    assert SCHEMA.validate_scenario(bad)
    bad = copy.deepcopy(scenario)
    bad["steps"][0]["at_ms"] = 5000
    assert any("at_ms" in e for e in SCHEMA.validate_scenario(bad))
    bad = copy.deepcopy(scenario)
    bad["steps"].append({"at_ms": 9000, "frame": {"type": "hello", "data": {}}})
    assert SCHEMA.validate_scenario(bad)
    bad = copy.deepcopy(scenario)
    bad["steps"].append({"at_ms": 9000, "expect": {"type": "roster.delta"}, "timeout_ms": 10})
    assert SCHEMA.validate_scenario(bad)


def test_lenient_steps_are_really_off_contract() -> None:
    for path in (DATA / "scenarios").glob("*.json"):
        for step in bridge_schema.read_json(path)["steps"]:
            if step.get("lenient"):
                frame = {"seq": 3, "base": 2, "ts": 0.0, **step["frame"]}
                assert SCHEMA.validate_frame(frame), path.name
                assert SCHEMA.validate_frame(frame, lenient=True) == [], path.name


def test_mirror_check_reports_drift(tmp_path: Path) -> None:
    mirror = tmp_path / "bridge"
    shutil.copytree(DATA, mirror)
    assert bridge_schema.check_mirror(DATA, mirror) == []
    target = mirror / "messages" / "ping.json"
    target.write_text(json.dumps([{"type": "ping", "ts": 1.0, "data": {}}]), encoding="utf-8")
    (mirror / "messages" / "extra.json").write_text("[]", encoding="utf-8")
    problems = bridge_schema.check_mirror(DATA, mirror)
    assert "mirror differs: messages/ping.json" in problems
    assert "mirror has extra messages/extra.json" in problems


def test_fixture_text_is_english_and_names_no_real_people() -> None:
    # Synthetic data only (orchestration.md, visual tests): no e-mail addresses,
    # no user-profile paths, no URLs other than the loopback bridge.
    for path in DATA.rglob("*.json"):
        text = path.read_text(encoding="utf-8")
        assert "@" not in text, path
        assert "\\Users\\" not in text and "/home/" not in text, path


def test_cli_check_passes(capsys) -> None:
    assert bridge_schema.main([]) == 0
    assert "OK" in capsys.readouterr().out
