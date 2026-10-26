"""The starter gallery's data: every starter is a safe, valid agent template."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from dodaios.society import starters as starters_mod
from dodaios.society.agent_template import (
    TEMPLATE_KEYS,
    create_fields,
    scrub_text,
    validate_template,
)
from dodaios.society.capabilities import CapabilityKind, CapabilityRow
from dodaios.society.starters import (
    AREAS,
    ROUTINE_SCHEDULES,
    StarterError,
    load_starters,
    preview_payload,
    routine_schedule,
    starter_by_id,
    starter_payload,
    starter_template,
    template_summary,
    validate_starter,
)
from dodaios.tasks.cron_schedule import validate_cron

DATA = Path(starters_mod.__file__).with_name("starters")

#: Names that never belong in our own starter copy: other assistants and
#: agent products, and the trademarked name our lead used to carry.
FORBIDDEN_WORDS = (
    "jarvis",
    "chatgpt",
    "openai",
    "anthropic",
    "claude",
    "gemini",
    "copilot",
    "cursor",
    "codex",
    "openclaw",
    "hermes",
    "grok",
    "kimi",
    "perplexity",
    "notion",
)


def _raw_entries() -> list[tuple[str, dict]]:
    out = []
    for path in sorted(DATA.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        out += [(data["area"], entry) for entry in data["starters"]]
    return out


def test_the_gallery_is_big_enough_and_covers_every_area():
    starters = load_starters()
    assert 20 <= len(starters) <= 30
    assert {s.area for s in starters} == set(AREAS)
    assert len({s.id for s in starters}) == len(starters)
    # Area order is the display order.
    order = [AREAS.index(s.area) for s in starters]
    assert order == sorted(order)


def test_every_file_entry_loads_none_is_silently_dropped():
    raw = _raw_entries()
    assert len(raw) == len(load_starters())
    for area, entry in raw:
        assert validate_starter(entry, area) == [], entry.get("id")


@pytest.mark.parametrize("starter", load_starters(), ids=lambda s: s.id)
def test_every_starter_passes_template_validation(starter):
    template = starter_template(starter)
    assert validate_template(template) == []
    # And the installer accepts it as-is.
    fields = create_fields(template)
    assert fields["name"] == template["name"]


@pytest.mark.parametrize("starter", load_starters(), ids=lambda s: s.id)
def test_no_starter_widens_approvals_or_brings_a_seat(starter):
    template = dict(starter.template)
    assert set(template) <= TEMPLATE_KEYS
    for key in ("provider", "model", "account_id", "permission_ceiling", "approval_mode"):
        assert key not in template
    fields = create_fields(starter_template(starter))
    # Always-allow never travels; require_approval only adds confirmations.
    assert fields["approval_rules"]["always_allow"] == []
    assert fields.get("grant_mode", "all") == "all"
    assert fields.get("denies", []) == []


@pytest.mark.parametrize("starter", load_starters(), ids=lambda s: s.id)
def test_no_starter_names_a_machine_a_person_or_a_brand(starter):
    texts = [
        starter.outcome,
        starter.first_message,
        str(starter.template.get("instructions")),
        str(starter.template.get("title")),
        str(starter.template.get("name")),
    ]
    if starter.routine:
        texts += [starter.routine["title"], starter.routine["prompt"]]
    for text in texts:
        cleaned, findings = scrub_text(text, "starter")
        assert findings == [] and cleaned == text, (starter.id, text)
        words = set(re.findall(r"[a-z]+", text.lower()))
        assert not words & set(FORBIDDEN_WORDS), (starter.id, words & set(FORBIDDEN_WORDS))


def test_routines_use_valid_named_schedules():
    for when, expression in ROUTINE_SCHEDULES.items():
        validate_cron(expression, "Europe/Berlin")
        assert when
    with_routine = [s for s in load_starters() if s.routine]
    assert len(with_routine) >= 5
    schedule = routine_schedule(with_routine[0], "America/New_York")
    assert schedule == {
        "kind": "cron",
        "expression": ROUTINE_SCHEDULES[with_routine[0].routine["when"]],
        "timezone": "America/New_York",
    }
    no_routine = next(s for s in load_starters() if s.routine is None)
    assert routine_schedule(no_routine, "UTC") is None


def test_picked_tools_narrow_the_suggestion_and_never_widen_it():
    starter = starter_by_id("meeting-prep")
    assert starter.tools[0] == "plugin:google_calendar"
    narrowed = starter_template(starter, tools=["plugin:gmail", "core:run-shell"])
    assert narrowed["focus"] == ["plugin:gmail"]
    unticked = starter_template(starter, tools=[])
    assert "focus" not in unticked
    full = starter_template(starter)
    assert full["focus"] == list(starter.tools)
    # The catalogue itself stays untouched.
    assert "focus" not in starter.template


def test_a_picked_name_replaces_the_starter_name():
    starter = starter_by_id("researcher")
    assert starter_template(starter, name="  Ada   Scout ")["name"] == "Ada Scout"
    assert starter_template(starter, name="  ")["name"] == "Researcher"


def test_unknown_starter_is_a_starter_error():
    with pytest.raises(StarterError):
        starter_by_id("nope")


def _row(cap_id: str, connected: bool) -> CapabilityRow:
    kind = CapabilityKind(cap_id.split(":", 1)[0])
    return CapabilityRow(
        id=cap_id,
        kind=kind,
        label=cap_id.split(":", 1)[1].title(),
        one_liner="",
        risk_tier="read",
        connected=connected,
        tool_name=cap_id.split(":", 1)[1],
    )


def test_payload_marks_connected_and_missing_tools():
    starter = starter_by_id("meeting-prep")
    catalog = [_row("plugin:google_calendar", True), _row("plugin:gmail", False)]
    payload = starter_payload(starter, catalog)
    tools = {t["id"]: t for t in payload["tools"]}
    assert tools["plugin:google_calendar"] == {
        "id": "plugin:google_calendar",
        "label": "Google_Calendar",
        "available": True,
        "connected": True,
    }
    assert tools["plugin:gmail"]["available"] and not tools["plugin:gmail"]["connected"]
    assert not tools["core:search-web"]["available"]
    assert payload["routine"]["when"] == "weekday_morning"
    summary = payload["summary"]
    assert summary["tools"] == 3
    assert summary["routines"] == 1
    assert summary["asks_before"] == 3
    assert summary["skills"] is None
    assert summary["instructions_words"] > 10


def test_summary_counts_rules_and_skills():
    template = {
        "instructions": "Do it.\n\n- one\n- two\n* three",
        "skills": ["a", "b"],
        "focus": ["core:search-web"],
        "require_approval": ["plugin:gmail:send"],
        "grant_mode": "allowlist",
    }
    summary = template_summary(template)
    assert summary["instructions_rules"] == 3
    assert summary["skills"] == 2
    assert summary["tools"] == 1
    assert summary["asks_before"] == 1
    assert summary["limited_tools"] is True


def test_preview_reports_errors_without_creating_anything():
    bad = preview_payload({"schema": 1, "name": "x"}, [])
    assert not bad["ok"] and bad["errors"]
    not_object = preview_payload(["nope"], [])
    assert not not_object["ok"] and not_object["template"] is None
    good = preview_payload(
        {
            "schema": 1,
            "name": "Helper",
            "instructions": "Keep my notes.",
            "focus": ["core:search-web"],
        },
        [_row("core:search-web", True)],
    )
    assert good["ok"] and good["errors"] == []
    assert good["tools"][0]["connected"] is True
    assert good["summary"]["tools"] == 1


def test_a_broken_entry_is_skipped_not_fatal(tmp_path: Path, caplog):
    good = json.loads((DATA / "writing.json").read_text(encoding="utf-8"))
    good["starters"] = good["starters"][:1]
    broken = {
        "area": "ops",
        "starters": [
            {"id": "Bad Id", "icon": "x", "outcome": "", "first_message": "", "template": {}},
        ],
    }
    (tmp_path / "a.json").write_text(json.dumps(good), encoding="utf-8")
    (tmp_path / "b.json").write_text(json.dumps(broken), encoding="utf-8")
    (tmp_path / "c.json").write_text("{not json", encoding="utf-8")
    loaded = load_starters.__wrapped__(tmp_path)
    assert [s.id for s in loaded] == [good["starters"][0]["id"]]


def test_a_template_focus_in_the_data_is_refused():
    entry = dict(_raw_entries()[0][1])
    entry["template"] = {**entry["template"], "focus": ["core:search-web"]}
    assert any("focus" in problem for problem in validate_starter(entry, "coding"))
