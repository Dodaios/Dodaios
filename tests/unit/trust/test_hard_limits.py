"""The hard limits: pattern code that names what always asks."""

from __future__ import annotations

import pytest

from dodaios.trust.hard_limits import (
    HARD_LIMITS,
    NO_RULE_LIMITS,
    hard_limit_for,
    is_outbound,
    recipients_of,
)

KNOWN = lambda _values: True  # noqa: E731 — every recipient is known
UNKNOWN = lambda _values: False  # noqa: E731 — nobody is known


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("stripe", {"action": "charge", "amount": 500}),
        ("bank", {"action": "transfer", "to_account": "DE12"}),
        ("shop", {"action": "purchase", "item": "x"}),
        ("broker", {"action": "place_order", "symbol": "ACME"}),
        ("run_shell", {"command": "stripe payouts create --amount 100"}),
    ],
)
def test_moving_money_is_a_hard_limit(tool: str, args: dict) -> None:
    assert hard_limit_for(tool, args, recipients_known=KNOWN) == "money"


def test_reading_a_payment_provider_is_not_money() -> None:
    assert hard_limit_for("stripe", {"action": "list_charges"}, recipients_known=KNOWN) is None


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("profile", {"action": "set_password", "user": "ada"}),
        ("vault", {"action": "read_secret", "name": "db"}),
        ("some_api", {"password": "hunter2-correct-horse"}),
        ("some_api", {"api_key": "sk-" + "x" * 30}),
        ("run_shell", {"command": "cat ~/.env"}),
        ("run_shell", {"command": "gh auth token"}),
        ("run_shell", {"command": "export OPENAI_KEY=abc"}),
    ],
)
def test_credentials_are_a_hard_limit(tool: str, args: dict) -> None:
    assert hard_limit_for(tool, args, recipients_known=KNOWN) == "credentials"


def test_plumbing_tokens_are_not_credentials() -> None:
    """``page_token`` and ``session_key`` are pagination, not secrets."""
    assert hard_limit_for("gmail", {"action": "list_messages", "page_token": "abc"}) is None
    assert hard_limit_for("drive", {"action": "list_files", "session_key": "k"}) is None


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("gmail", {"action": "delete_message", "message_id": "m1"}),
        ("google_drive", {"action": "delete_file", "file_id": "f1"}),
        ("run_shell", {"command": "rm -rf build"}),
        ("run_shell", {"command": "Remove-Item -Recurse -Force .\\dist"}),
        ("run_shell", {"command": "git push --force origin main"}),
        ("run_shell", {"command": "git reset --hard HEAD~3"}),
        ("db", {"action": "drop_table", "table": "users"}),
    ],
)
def test_deleting_for_good_is_a_hard_limit(tool: str, args: dict) -> None:
    assert hard_limit_for(tool, args, recipients_known=KNOWN) == "permanent_delete"


def test_recoverable_organising_is_not_a_hard_limit() -> None:
    assert hard_limit_for("gmail", {"action": "trash_message", "message_id": "m1"}) is None
    assert hard_limit_for("gmail", {"action": "modify_message", "message_id": "m1"}) is None
    assert hard_limit_for("google_calendar", {"action": "delete_event", "event_id": "e"}) is None
    assert hard_limit_for("run_shell", {"command": "rm notes.txt.bak"}) is None


def test_a_first_message_to_someone_asks_and_a_known_one_does_not() -> None:
    args = {"action": "send_message", "to": "Ada <ada@example.com>", "body": "hi"}
    assert hard_limit_for("gmail", args, recipients_known=UNKNOWN) == "new_recipient"
    assert hard_limit_for("gmail", args, recipients_known=KNOWN) is None
    # A send with no recipient at all (the tool will refuse it) has no limit.
    assert hard_limit_for("gmail", {"action": "send_message"}, recipients_known=UNKNOWN) is None


def test_recipients_are_read_from_every_address_field() -> None:
    args = {
        "action": "send_message",
        "to": "a@x.com, b@x.com",
        "cc": ["c@x.com", {"email": "d@x.com"}],
        "arguments": {"bcc": "e@x.com"},
    }
    assert recipients_of("gmail", args) == ["a@x.com", "b@x.com", "c@x.com", "d@x.com", "e@x.com"]


def test_internal_agent_messages_are_not_outbound() -> None:
    assert not is_outbound("message_agent", {"action": "send", "to": "ada"})
    assert not is_outbound("spawn_worker", {"action": "post", "channel": "x"})
    assert is_outbound("slack", {"action": "send_message", "channel": "#ops"})
    assert is_outbound("send_sms", {"to": "+491234"})


def test_an_mcp_prefix_never_hides_a_tool() -> None:
    assert hard_limit_for("mcp__dodaios__gmail", {"action": "delete_message"}) == "permanent_delete"


def test_the_limit_names_are_stable() -> None:
    assert HARD_LIMITS == ("money", "credentials", "permanent_delete", "new_recipient")
    assert NO_RULE_LIMITS == {"money", "credentials", "permanent_delete"}
