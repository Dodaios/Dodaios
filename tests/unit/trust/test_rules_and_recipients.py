"""Standing rules and the known-recipient ledger: persisted, revocable, limited."""

from __future__ import annotations

from pathlib import Path

import pytest

from dodaios.trust.recipients import KnownRecipients, normalize_recipient
from dodaios.trust.rules import TrustRules


def test_a_tool_rule_covers_every_call_of_that_tool(tmp_path: Path) -> None:
    rules = TrustRules(tmp_path / "rules.json")
    rule = rules.add(tool="mcp__dodaios__open-app", kind="tool", label="Open app")
    assert rule["tool"] == "open-app"
    assert rules.allows("open-app", {"name": "Spotify"}) == rule
    assert rules.allows("mcp__other__open-app", {"name": "x"}) == rule
    assert rules.allows("Bash", {"command": "ls"}) is None


def test_an_action_rule_covers_one_action_only(tmp_path: Path) -> None:
    rules = TrustRules(tmp_path / "rules.json")
    rules.add(tool="gmail", kind="action", target="modify_message", label="Gmail: label")
    assert rules.allows("gmail", {"action": "modify_message", "message_id": "m"}) is not None
    assert rules.allows("gmail", {"action": "list_messages"}) is None


def test_folder_and_command_rules_match_like_the_card(tmp_path: Path) -> None:
    rules = TrustRules(tmp_path / "rules.json")
    folder = str(tmp_path / "src")
    rules.add(tool="Edit", kind="folder", target=folder, label="src")
    rules.add(tool="Bash", kind="command", target="npm test", label="npm test")
    assert rules.allows("Edit", {"file_path": str(tmp_path / "src" / "a.py")}) is not None
    assert rules.allows("Edit", {"file_path": str(tmp_path / "other" / "a.py")}) is None
    assert rules.allows("Bash", {"command": "npm  test"}) is not None
    assert rules.allows("Bash", {"command": "npm test && rm -rf x"}) is None


def test_a_hard_limit_wins_over_every_rule(tmp_path: Path) -> None:
    rules = TrustRules(tmp_path / "rules.json")
    rules.add(tool="gmail", kind="tool", label="Gmail")
    rules.add(tool="Bash", kind="tool", label="Bash")
    assert rules.allows("gmail", {"action": "delete_message", "message_id": "m"}) is None
    assert rules.allows("Bash", {"command": "rm -rf build"}) is None
    assert rules.allows("gmail", {"action": "list_messages"}) is not None


def test_rules_persist_and_revoke(tmp_path: Path) -> None:
    path = tmp_path / "rules.json"
    first = TrustRules(path)
    rule = first.add(tool="Bash", kind="command", target="npm test", label="npm test")
    again = first.add(tool="bash", kind="command", target="NPM TEST", label="npm test")
    assert again["id"] == rule["id"], "the same rule is stored once"

    second = TrustRules(path)
    assert [r["id"] for r in second.items()] == [rule["id"]]
    assert second.revoke(rule["id"])["id"] == rule["id"]
    assert second.revoke(rule["id"]) is None
    assert TrustRules(path).items() == []


def test_a_rule_needs_a_tool_and_a_target(tmp_path: Path) -> None:
    rules = TrustRules(tmp_path / "rules.json")
    with pytest.raises(ValueError):
        rules.add(tool="", kind="tool")
    with pytest.raises(ValueError):
        rules.add(tool="Edit", kind="folder")
    with pytest.raises(ValueError):
        rules.add(tool="Edit", kind="everything")  # type: ignore[arg-type]


def test_recipients_normalise_and_persist(tmp_path: Path) -> None:
    assert normalize_recipient("Ada Lovelace <Ada@Example.com>") == "ada@example.com"
    ledger = KnownRecipients(tmp_path / "r.json")
    assert ledger.remember(["Ada <ADA@example.com>", "#ops"]) == ["ada@example.com", "#ops"]
    assert ledger.remember(["ada@example.com"]) == []
    assert ledger.knows("ada@example.com") and ledger.knows_all(["#ops", "ADA@example.com"])
    assert not ledger.knows("bob@example.com")
    assert KnownRecipients(tmp_path / "r.json").knows("#ops")
    assert ledger.forget("#ops") and not ledger.knows("#ops")
    assert [r["recipient"] for r in ledger.items()] == ["ada@example.com"]
