"""The assistant's commands for rituals: what it can call, and what each one asks for."""

from __future__ import annotations

from dodaios.commands.registry import get_registry

BASE = "/api/agent-chat/lead/rituals"


def _commands() -> dict[str, object]:
    return {cmd.id: cmd for cmd in get_registry() if cmd.id.startswith("ritual-")}


def test_the_five_commands_and_the_routes_behind_them() -> None:
    commands = _commands()
    assert {cid: (cmd.method, cmd.path) for cid, cmd in commands.items()} == {
        "ritual-list": ("GET", BASE),
        "ritual-create": ("POST", BASE),
        "ritual-update": ("PATCH", f"{BASE}/{{ritual_id}}"),
        "ritual-remove": ("DELETE", f"{BASE}/{{ritual_id}}"),
        "ritual-run": ("POST", f"{BASE}/{{ritual_id}}/run"),
    }
    # The person ordered a ritual: only removing one asks again.
    assert [cid for cid, cmd in commands.items() if cmd.dangerous] == ["ritual-remove"]
    # None of them is a background worker's business.
    assert not any(cmd.worker_allowed for cmd in commands.values())


def test_writing_one_asks_for_a_name_a_phrase_and_sorted_steps() -> None:
    create = _commands()["ritual-create"]
    assert create.params["required"] == ["name", "phrases", "steps"]
    step = create.params["properties"]["steps"]["items"]
    assert step["required"] == ["when", "text"]
    assert step["properties"]["when"]["enum"] == ["now", "ahead"]
    # A step that is one tool call may carry it, so it is done without a model.
    call = step["properties"]["call"]
    assert call["required"] == ["tool", "args", "says"]
    assert "exactly ONE call" in call["description"]
    # The description tells the model when a ritual is the right thing.
    assert "SAYING a short phrase" in create.description
    assert "Do not run the steps now" in create.description


def test_changing_one_sends_only_what_changes() -> None:
    update = _commands()["ritual-update"]
    assert update.params["required"] == ["ritual_id"]
    assert {"enabled", "steps", "phrases", "window_from"} <= set(update.params["properties"])
    assert "keep each step's id" in update.description


def test_starting_one_by_name_leaves_the_gathering_to_the_ritual() -> None:
    run = _commands()["ritual-run"]
    assert "do not gather it yourself" in run.description
    assert "id or its exact name" in run.params["properties"]["ritual_id"]["description"]
