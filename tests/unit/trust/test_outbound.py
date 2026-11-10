"""The second look before anything leaves in the person's name."""

from __future__ import annotations

from dodaios.trust.outbound import OutboundFinding, asks, blocks, check_outbound, set_reviewer

KNOWN = lambda _values: True  # noqa: E731
UNKNOWN = lambda _values: False  # noqa: E731


def _send(**extra):
    return {"action": "send_message", "to": "ada@example.com", "subject": "Hi", **extra}


def test_a_clean_mail_to_a_known_recipient_has_no_findings() -> None:
    assert check_outbound("gmail", _send(body="See you at three."), recipients_known=KNOWN) == []


def test_a_read_is_never_checked() -> None:
    args = {"action": "list_messages", "query": "password reset"}
    assert check_outbound("gmail", args, recipients_known=UNKNOWN) == []


def test_a_secret_in_the_text_blocks_the_send() -> None:
    key = "sk-" + "a1" * 20
    findings = check_outbound("gmail", _send(body=f"here is the key {key}"), recipients_known=KNOWN)
    assert [f.code for f in findings] == ["secret"]
    assert blocks(findings) and not asks(findings)
    spelled = check_outbound(
        "gmail", _send(body="The password is hunter2x"), recipients_known=KNOWN
    )
    assert blocks(spelled)


def test_an_unknown_recipient_and_a_mistyped_domain_ask() -> None:
    args = {"action": "send_message", "to": "bob@gmial.com", "body": "hello"}
    findings = check_outbound("gmail", args, recipients_known=UNKNOWN)
    codes = {f.code: f for f in findings}
    assert set(codes) == {"unknown_recipient", "mistyped_domain"}
    assert codes["mistyped_domain"].detail == "bob@gmial.com → gmail.com"
    assert asks(findings) and not blocks(findings)


def test_a_harsh_tone_asks() -> None:
    shouting = check_outbound(
        "slack",
        {"action": "send_message", "channel": "#ops", "text": "FIX THIS NOW EVERYONE PLEASE"},
        recipients_known=KNOWN,
    )
    assert [f.code for f in shouting] == ["tone"] and shouting[0].detail == "shouting"
    swearing = check_outbound(
        "gmail", _send(body="this is bullshit, fix it"), recipients_known=KNOWN
    )
    assert [f.code for f in swearing] == ["tone"] and swearing[0].detail == "profanity"
    bangs = check_outbound("gmail", _send(body="Answer me!!!"), recipients_known=KNOWN)
    assert [f.code for f in bangs] == ["tone"]


def test_an_extra_reviewer_adds_findings_and_never_breaks_the_send() -> None:
    set_reviewer(lambda _tool, _args: [OutboundFinding("tone", "ask", "model")])
    try:
        found = check_outbound("gmail", _send(body="fine"), recipients_known=KNOWN)
        assert [(f.code, f.detail) for f in found] == [("tone", "model")]

        def boom(_tool, _args):
            raise RuntimeError("down")

        set_reviewer(boom)
        assert check_outbound("gmail", _send(body="fine"), recipients_known=KNOWN) == []
    finally:
        set_reviewer(None)
