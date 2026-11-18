"""The browser reads freely and asks at the one click that commits something.

Regression for the dead end of 2026-11-16: a read task ("search flights, do
not book anything") and an explicit cancellation both ended at once in
``fresh approval required`` with no card. The task's wording decided the gate,
and a chat in Bypass answered the gate's ticket itself, which the agent's own
gate then refused.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from dodaios.core.protocols import ToolResult
from dodaios.society.browser.commit_gate import (
    CommitMemory,
    blocker_hint,
    commit_step,
)
from dodaios.society.browser.commit_target import describe_node, describe_target

PLAY = "https://play.google.com/store/account/subscriptions"
PAGE_TEXT = (
    "Abo kündigen? SuperGrok 33,99 €/Monat. "  # i18n-allow: page text
    "Dein Abo endet am 1. Dezember."  # i18n-allow: page text
)
CANCEL = {
    "tag": "button",
    "type": "",
    "role": "",
    "href": "",
    "label": "Abo kündigen",  # i18n-allow: a page label
    "context": PAGE_TEXT,
    "field": "",
    "in_dialog": "1",
}


def _button(label: str, context: str = "", **extra: str) -> dict[str, str]:
    return {"tag": "button", "type": "", "role": "", "href": "", "label": label,
            "context": context, "field": "", **extra}


# ------------------------------------------------------------------ what commits


@pytest.mark.parametrize(
    ("label", "kind"),
    [
        ("Cancel subscription", "cancel"),
        ("Abo kündigen", "cancel"),  # i18n-allow: a page label
        ("Buy now", "buy"),
        ("Zahlungspflichtig bestellen", "buy"),  # i18n-allow: a page label
        ("Place your order", "buy"),
        ("Book now", "book"),
        ("Send", "send"),
        ("Nachricht senden", "send"),  # i18n-allow: a page label
        ("Post", "publish"),
        ("Delete account", "close_account"),
        ("Authorize app", "authorize"),
        ("Zugriff erlauben", "authorize"),  # i18n-allow: a page label
        ("Datei löschen", "delete"),  # i18n-allow: a page label
        ("Confirm", "confirm"),
        ("Bestätigen", "confirm"),  # i18n-allow: a page label
    ],
)
def test_a_committing_control_is_recognised_by_its_own_label(label, kind):
    step = commit_step("click", {"index": 4}, _button(label), PLAY)
    assert step is not None and step.kind == kind
    assert step.host == "play.google.com"


@pytest.mark.parametrize(
    "label",
    [
        "Search", "Next", "Show flights", "Business", "Cancel", "Close", "Sign in",
        "Filters", "Sort by price", "Details", "Keep subscription", "Manage",
        "Booking details", "View post",
        "Suchen", "Weiter", "Abbrechen",  # i18n-allow: page labels
    ],
)
def test_ordinary_page_work_is_not_a_commit(label):
    assert commit_step("click", {"index": 1}, _button(label), PLAY) is None


def test_a_plain_yes_commits_only_what_its_dialog_is_about():
    assert commit_step("click", {}, _button("Yes"), PLAY) is None
    saved = _button("OK", "Your filters were saved.", in_dialog="1")
    assert commit_step("click", {}, saved, PLAY) is None
    asked = _button("Yes", "Cancel subscription? SuperGrok", in_dialog="1")
    step = commit_step("click", {}, asked, PLAY)
    assert step is not None and step.kind == "cancel"
    # The same words around a step of a form are not a question to answer.
    in_form = _button("OK", "Cancel subscription or keep it")
    assert commit_step("click", {}, in_form, PLAY) is None
    for label in ("Continue", "Next", "Weiter"):  # i18n-allow: page labels
        step_of_form = _button(label, "Jetzt buchen und bezahlen", in_dialog="1")  # i18n-allow
        assert commit_step("click", {}, step_of_form, PLAY) is None


def test_a_link_that_only_opens_a_page_is_not_a_commit():
    link = _button("Cancel subscription", tag="a", href="/subscriptions/cancel")
    assert commit_step("click", {}, link, PLAY) is None
    assert commit_step("click", {}, {**link, "role": "button"}, PLAY) is not None
    assert commit_step("click", {}, {**link, "href": "#"}, PLAY) is not None


def test_a_cookie_banner_is_not_an_acceptance_card():
    banner = _button("Accept all", "We use cookies to improve your experience.")
    assert commit_step("click", {}, banner, PLAY) is None
    terms = _button("Accept", "Terms of service for the new plan")
    assert commit_step("click", {}, terms, PLAY).kind == "accept"


def test_enter_in_a_search_field_is_free_and_enter_on_a_send_form_asks():
    search = _button("Search", field="search q Search flights")
    assert commit_step("send_keys", {"keys": "Enter"}, search, PLAY) is None
    send = _button("Send message", "To: Sam", field="text body")
    assert commit_step("send_keys", {"keys": "Enter"}, send, PLAY).kind == "send"
    assert commit_step("send_keys", {"keys": "Tab"}, send, PLAY) is None


def test_no_label_no_gate_and_other_actions_never_commit():
    assert commit_step("click", {"index": 2}, None, PLAY) is None
    assert commit_step("input", {"text": "Cancel subscription"}, CANCEL, PLAY) is None
    assert commit_step("navigate", {"url": PLAY}, CANCEL, PLAY) is None


def test_the_card_says_what_is_clicked_where_and_what_the_page_says():
    step = commit_step("click", {"index": 7}, CANCEL, PLAY)
    assert step.summary.startswith('Click "Abo kündigen" on play.google.com: ')  # i18n-allow
    assert "SuperGrok 33,99 €/Monat" in step.summary


def test_the_card_quotes_a_dialog_or_a_typed_message_but_not_a_forms_field_labels():
    """Seen live: a form's text is its field labels, which says nothing about the click."""
    form = _button("Submit order", "Customer name: Telephone: E-mail address: Submit order")
    step = commit_step("click", {"index": 9}, form, "https://httpbin.org/forms/post")
    assert step.kind == "send" and step.context == ""
    assert step.summary == 'Click "Submit order" on httpbin.org'
    message = _button("Enter", "See you at eight", type="composer", field="textbox")
    typed = commit_step("send_keys", {"keys": "Enter"}, message, PLAY)
    # Enter in a message box with text in it sends that text: the card quotes it.
    assert typed.kind == "send" and typed.context == "See you at eight"
    assert typed.summary == "Press Enter on play.google.com: See you at eight"


def test_one_yes_covers_the_confirming_click_of_the_same_action_only():
    memory = CommitMemory(window_s=120)
    first = commit_step("click", {}, CANCEL, PLAY)
    memory.note(first, approved=True, now=10.0)
    yes = _button("Yes", "Abo kündigen?", in_dialog="1")  # i18n-allow: page text
    confirm = commit_step("click", {}, yes, PLAY)
    assert memory.covers(confirm, now=20.0)
    assert not memory.covers(confirm, now=200.0)
    other_page = commit_step("click", {}, CANCEL, PLAY + "/google-one")
    assert not memory.covers(other_page, now=20.0)
    buy = commit_step("click", {}, _button("Buy now"), PLAY)
    assert not memory.covers(buy, now=20.0)


# ------------------------------------------------------------------ the worker's read


def _node(tag, text="", attrs=None, parent=None, ax_name=""):
    return SimpleNamespace(
        tag_name=tag,
        attributes=attrs or {},
        parent_node=parent,
        ax_node=SimpleNamespace(name=ax_name, role="") if ax_name else None,
        get_all_children_text=lambda: text,
    )


def test_the_worker_reads_label_and_dialog_text_from_the_page():
    page_text = "Abo kündigen?  SuperGrok 33,99 €/Monat"  # i18n-allow: page text
    dialog = _node("div", page_text, {"role": "dialog"})
    wrap = _node("div", "", parent=dialog)
    button = _node("button", "  Abo\n kündigen ", parent=wrap)  # i18n-allow: a page label
    target = describe_node(button)
    assert target["label"] == "Abo kündigen"  # i18n-allow: a page label
    assert target["context"] == "Abo kündigen? SuperGrok 33,99 €/Monat"  # i18n-allow
    icon = describe_node(_node("button", "", {"aria-label": "Delete"}, ax_name="Delete"))
    assert icon["label"] == "Delete" and icon["context"] == ""
    assert target["in_dialog"] == "1" and icon["in_dialog"] == ""
    form = _node("form", "Name Send", {})
    assert describe_node(_node("button", "Send", parent=form))["in_dialog"] == ""


async def test_the_worker_describes_an_indexed_click_and_never_fails_the_action():
    button = _node("button", "Buy now")

    async def by_index(index):
        assert index == 3
        return button

    session = SimpleNamespace(get_element_by_index=by_index)
    target = await describe_target({"click": {"index": 3}}, session, None)
    assert target["label"] == "Buy now"

    async def broken(index):
        raise RuntimeError("stale index")

    gone = SimpleNamespace(get_element_by_index=broken)
    assert await describe_target({"click": {"index": 3}}, gone, None) is None
    assert await describe_target({"scroll": {"down": True}}, session, None) is None

    points = []

    async def page():
        return SimpleNamespace(evaluate=_evaluate)

    async def _evaluate(script, point=None):
        if point is not None:
            points.append(point)
            return {"tag": "button", "label": "Pay now", "context": "", "field": ""}
        return {"tag": "button", "label": "Send", "context": "", "field": "text"}

    typed = await describe_target({"send_keys": {"keys": "Enter"}}, session, page)
    assert typed["label"] == "Send"
    # A model that clicks by coordinates names no element: the control under
    # the point is read, with the screenshot's pixels scaled to the viewport.
    scaled = SimpleNamespace(llm_screenshot_size=(1000, 500), _original_viewport_size=(2000, 1000))
    by_point = await describe_target(
        {"click": {"coordinate_x": 100, "coordinate_y": 50}}, scaled, page
    )
    assert by_point["label"] == "Pay now" and points == [[200, 100]]
    assert commit_step("click", {"coordinate_x": 100}, by_point, PLAY).kind == "buy"


# ------------------------------------------------------------------ the run


@pytest.fixture
async def rt(tmp_path, monkeypatch):
    from dodaios.society.runtime import SocietyRuntime

    monkeypatch.setattr("dodaios.core.config.get_jarvis_agent_secret", lambda _: None)
    runtime = SocietyRuntime(tmp_path, seed_starter_team=False)
    await runtime.ensure_started()
    runtime.browser.live.model_resolver = lambda _: SimpleNamespace(complete=lambda *_: None)

    async def execute(tool, args, **kwargs):
        return await tool.execute(args, None)

    runtime.browser.live.executor = SimpleNamespace(execute=execute)
    try:
        yield runtime
    finally:
        await runtime.close()


def _answer_cards(rt, *, approve, seen):
    """The person: answers each pending approval card once it shows up."""

    async def person():
        while True:
            for item in await rt.approvals.pending():
                seen.append(item)
                await rt.approvals.resolve(item.id, approve=approve)
            await asyncio.sleep(0.05)

    return asyncio.create_task(person())


async def _run_steps(rt, steps, *, task="Do it", trace="turn-1"):
    """Run ``execute_live`` for the lead with a browser that proposes ``steps``."""
    from dodaios.society.browser.bridge import execute_live

    applied, verdicts = [], []

    async def run(agent, *, action, **kwargs):
        for name, params, target in steps:
            async def apply(name=name, target=target):
                applied.append(name if target is None else target["label"])
                return {}

            verdict = await action(
                {"action": {name: params}, "url": PLAY, "target": target, "apply": apply}
            )
            verdicts.append(verdict)
            if not verdict["ok"]:
                raise RuntimeError(verdict["error"])
        return {"ok": True, "final_result": "done", "urls": [PLAY], "artifacts": []}

    rt.browser.live.run = run
    lead = await rt.roster.get(rt.lead_id)
    result = await execute_live(
        rt, lead, rt.browser, {"task": task}, SimpleNamespace(trace_id=trace, config={})
    )
    return result, applied, verdicts


async def test_a_read_task_runs_without_any_approval(rt):
    """(a) Search, open, read, fill a search form: nobody is asked."""
    steps = [
        ("navigate", {"url": "https://www.google.com/travel/flights"}, None),
        ("input", {"index": 2, "text": "MUC"}, None),
        ("click", {"index": 5}, _button("Business")),
        ("send_keys", {"keys": "Enter"}, _button("Search", field="search q")),
        ("click", {"index": 9}, _button("Search")),
        ("extract", {"query": "prices"}, None),
    ]
    result, applied, _ = await _run_steps(
        rt, steps, task="Search Google Flights MUC to SFO in business. Do not book anything."
    )
    assert result.success
    assert len(applied) == len(steps)
    assert await rt.approvals.items() == []
    assert "consequential" not in result.output


def test_the_wording_of_a_task_no_longer_gates_the_live_browser():
    """(a) "Do not book anything" used to read as a booking and ask up front."""
    from dodaios.society.browser.tool import BrowserTool

    live = BrowserTool(SimpleNamespace(), "jarvis", SimpleNamespace(_python=None))
    for task in (
        "Search business flights MUC to SFO. Do not book anything, no personal data.",
        "Cancel the SuperGrok subscription in Google Play",
    ):
        assert live.risk_tier_for_args({"task": task}) is None
    # The one-shot runner cannot pause inside a run: it still asks up front.
    one_shot = BrowserTool(SimpleNamespace(), "jarvis", SimpleNamespace(_python="python"))
    assert one_shot.risk_tier_for_args({"task": "Buy the ticket and pay"}) == "ask"


async def test_a_cancellation_asks_at_the_final_click_and_goes_on_after_yes(rt):
    """(b) The card names the click; the yes runs exactly that click."""
    seen = []
    person = _answer_cards(rt, approve=True, seen=seen)
    try:
        result, applied, _ = await _run_steps(
            rt,
            [
                ("navigate", {"url": PLAY}, None),
                ("click", {"index": 3}, _button("SuperGrok")),
                ("click", {"index": 7}, CANCEL),
                ("extract", {"query": "confirmation"}, None),
            ],
            task="Cancel SuperGrok in Google Play",
        )
    finally:
        person.cancel()
    assert result.success
    assert applied == ["navigate", "SuperGrok", "Abo kündigen", "extract"]  # i18n-allow
    assert len(seen) == 1
    card = seen[0]
    assert card.capability == "core:browser"
    assert 'Click "Abo kündigen" on play.google.com' in card.summary  # i18n-allow
    assert "SuperGrok 33,99 €/Monat" in card.summary
    assert card.action["commit"]["kind"] == "cancel"
    assert card.action["resume_in_place"] is True
    done = result.output["consequential"]
    assert [(row["label"], row["decision"]) for row in done] == [
        ("Abo kündigen", "approved")  # i18n-allow: a page label
    ]


async def test_one_action_is_one_card_and_another_subscription_asks_again(rt):
    """Explicitly asked for: one confirmation per action, never a loop of cards."""
    seen = []
    person = _answer_cards(rt, approve=True, seen=seen)
    other = PLAY + "/google-one"
    from dodaios.society.browser.bridge import execute_live

    applied = []

    async def run(agent, *, action, **kwargs):
        for url, target in (
            (PLAY, CANCEL),
            (PLAY, _button("Ja, kündigen", "Abo kündigen?")),  # i18n-allow: a page label
            (other, CANCEL),
        ):
            async def apply(label=target["label"]):
                applied.append(label)
                return {}

            verdict = await action(
                {"action": {"click": {"index": 1}}, "url": url, "target": target, "apply": apply}
            )
            assert verdict["ok"]
        return {"ok": True, "urls": [PLAY, other], "artifacts": []}

    rt.browser.live.run = run
    lead = await rt.roster.get(rt.lead_id)
    try:
        result = await execute_live(
            rt, lead, rt.browser, {"task": "Cancel both"},
            SimpleNamespace(trace_id="t", config={}),
        )
    finally:
        person.cancel()
    assert result.success and len(applied) == 3
    assert len(seen) == 2


async def test_a_no_clicks_nothing_and_says_which_click_was_refused(rt):
    """(c) Declined: the click never runs and the result names it."""
    seen = []
    person = _answer_cards(rt, approve=False, seen=seen)
    try:
        result, applied, verdicts = await _run_steps(
            rt,
            [("navigate", {"url": PLAY}, None), ("click", {"index": 7}, CANCEL)],
            task="Cancel SuperGrok in Google Play",
        )
    finally:
        person.cancel()
    assert not result.success
    assert applied == ["navigate"]
    assert len(seen) == 1
    assert result.output["reason"] == "declined"
    assert result.output["consequential"][0]["decision"] == "declined"
    assert "declined" in result.error and "Abo kündigen" in result.error  # i18n-allow
    assert "Nothing was clicked" in result.error
    assert verdicts[-1]["ok"] is False
    # The refusal holds for the rest of this turn: no second try on another way.
    again, applied_again, _ = await _run_steps(rt, [("navigate", {"url": PLAY}, None)])
    assert not again.success and applied_again == []


async def test_an_unanswered_card_is_a_next_action_not_a_dead_error(rt, monkeypatch):
    """(d) Nobody answered: the result says what waits and what to do."""

    async def nobody(runtime, approval_id, session):
        await runtime.approvals.resolve(approval_id, approve=False, note="Browser task ended")
        return False

    monkeypatch.setattr("dodaios.society.browser.bridge.wait_for_browser_approval", nobody)
    result, applied, _ = await _run_steps(rt, [("click", {"index": 7}, CANCEL)])
    assert not result.success and applied == []
    assert result.output["reason"] == "approval_required"
    assert "Nobody answered" in result.error and "Abo kündigen" in result.error  # i18n-allow
    assert "call society_browser again" in result.error


async def test_an_agent_in_bypass_commits_without_a_card_and_the_result_says_so(rt):
    from dodaios.society.browser.bridge import execute_live

    agent, _ = await rt.roster.create(name="Free hand", provider="openai")
    assert str(agent.approval_mode) == "bypass"

    async def run(agent, *, action, **kwargs):
        async def apply():
            return {}

        verdict = await action(
            {"action": {"click": {"index": 1}}, "url": PLAY, "target": CANCEL, "apply": apply}
        )
        assert verdict["ok"]
        return {"ok": True, "artifacts": []}

    rt.browser.live.run = run
    result = await execute_live(
        rt, agent, rt.browser, {"task": "Cancel"}, SimpleNamespace(trace_id="t", config={})
    )
    assert result.success
    assert await rt.approvals.items() == []
    assert result.output["consequential"][0]["by"] == "rule"


# ------------------------------------------------------------------ the tool's own gate


async def _lead_browser(rt, monkeypatch, *, mode="bypass", ran=None):
    from dodaios.society.surface import browser_tool_for_session

    session = SimpleNamespace(
        session_id="root-chat", surface="jarvis", provider="p", model="m", permission_mode=mode
    )
    rt.chat_service = lambda: SimpleNamespace(store=SimpleNamespace(get_session=lambda _: session))

    async def execute(runtime, caller, jobs, args, ctx, *, read_only=False):
        if ran is not None:
            ran.append(args["task"])
        return ToolResult(True, {"ok": True}, None)

    monkeypatch.setattr("dodaios.society.browser.bridge.execute_live", execute)
    tool = await browser_tool_for_session("root-chat")
    assert tool is not None
    return tool


async def test_a_read_task_in_a_bypass_chat_starts_without_a_gate(rt, monkeypatch):
    """(a) The case of 2026-11-16: it ended in ``fresh approval required``."""
    ran = []
    tool = await _lead_browser(rt, monkeypatch, ran=ran)
    task = "Search Google Flights for business flights MUC to SFO. Do not book anything."
    assert tool.risk_tier_for_args({"task": task}) == "monitor"
    # What the chat's bridge hands the gate in Bypass.
    result = await tool.execute({"task": task}, SimpleNamespace(approved_by="chat-bypass"))
    assert result.success and ran == [task]
    assert await rt.approvals.items() == []


async def test_a_gate_that_wants_a_person_raises_the_card_itself(rt, monkeypatch):
    """(d) A policy that asks never ends in a bare error: it asks, then runs."""
    ran, seen = [], []
    await rt.roster.update(rt.lead_id, {"approval_rules": {"require_approval": ["core:browser"]}})
    tool = await _lead_browser(rt, monkeypatch, ran=ran)
    person = _answer_cards(rt, approve=True, seen=seen)
    try:
        result = await tool.execute(
            {"task": "Read the headline", "url": "https://example.org"},
            SimpleNamespace(approved_by="chat-bypass", trace_id="t"),
        )
    finally:
        person.cancel()
    assert result.success and ran == ["Read the headline"]
    assert len(seen) == 1
    assert seen[0].summary == "society_browser: Read the headline; https://example.org"
    assert seen[0].action["chat_session_id"] == "root-chat"


async def test_a_declined_or_unanswered_gate_says_what_was_asked(rt, monkeypatch):
    """(d) Declined or unanswered: what was asked, the approval id, the next step."""
    from dodaios.society import surface

    ran, seen = [], []
    await rt.roster.update(rt.lead_id, {"approval_rules": {"require_approval": ["core:browser"]}})
    tool = await _lead_browser(rt, monkeypatch, ran=ran)
    person = _answer_cards(rt, approve=False, seen=seen)
    try:
        declined = await tool.execute(
            {"task": "Read the headline"}, SimpleNamespace(approved_by="chat-bypass")
        )
    finally:
        person.cancel()
    assert not declined.success and ran == []
    assert declined.output["reason"] == "declined"
    assert declined.output["approval_id"] == seen[0].id
    assert "Read the headline" in declined.error

    monkeypatch.setattr(surface, "IN_PLACE_APPROVAL_TIMEOUT_S", 0.2)
    silent = await tool.execute(
        {"task": "Read the headline"}, SimpleNamespace(approved_by="chat-bypass")
    )
    assert not silent.success and ran == []
    assert silent.output["reason"] == "approval_required"
    assert silent.output["approval_id"]
    assert "Read the headline" in silent.output["what"]
    assert "call the tool again" in silent.output["next_action"]
    for result in (declined, silent):
        assert "fresh approval required" not in str(result.error)
    # No card stays open for a call that has already returned.
    assert await rt.approvals.pending() == []


# ------------------------------------------------------------------ real blockers


def test_a_run_stopped_at_a_sign_in_or_a_check_names_the_next_step():
    tools = {"takeover_tool": "request_browser_takeover", "login_tool": "society_request_login"}
    login = blocker_hint(
        {"ok": False, "final_result": "The page asks to sign in to Google.",
         "urls": ["https://accounts.google.com/signin"]},
        **tools,
    )
    assert login["blocked_on"] == "login"
    assert login["page"] == "https://accounts.google.com/signin"
    assert "request_browser_takeover" in login["next_action"]
    assert "society_request_login" in login["next_action"]
    code = blocker_hint({"ok": False, "errors": ["Needs the 2FA verification code"]}, **tools)
    assert code["blocked_on"] == "two_factor"
    check = blocker_hint({"ok": False, "final_result": "A CAPTCHA blocks the page"}, **tools)
    assert check["blocked_on"] == "human_verification"
    assert blocker_hint({"ok": True, "final_result": "Signed in and read it"}, **tools) is None
    assert blocker_hint({"ok": False, "error": "Model timed out"}, **tools) is None


async def test_the_planner_reads_the_next_step_instead_of_a_bare_retry(monkeypatch):
    import json

    import mcp.types as types

    from dodaios.mcp import dodaios_tools_server as server

    tool = SimpleNamespace(
        name="society_browser", description="Browser", risk_tier="monitor",
        is_action_tool=True, input_schema={"type": "object"},
    )
    blocked = {"ok": False, "blocked_on": "login", "next_action": "Call request_browser_takeover"}

    async def execute(name, args, request):
        return ToolResult(False, blocked, "Browser task did not complete successfully")

    monkeypatch.setattr(
        server, "_gateway", lambda: SimpleNamespace(catalog=lambda: [tool], execute=execute)
    )
    request = types.CallToolRequest(
        params=types.CallToolRequestParams(name="society_browser", arguments={"task": "Read"})
    )
    response = await server.build_server().request_handlers[types.CallToolRequest](request)
    body = json.loads(response.root.content[0].text)
    assert body["retry"] == "Call request_browser_takeover"
    assert body["result"]["blocked_on"] == "login"


# ------------------------------------------------------------------ the card in the chat


async def test_the_conversation_shows_the_card_and_how_it_ended(rt, monkeypatch):
    """The ask used to wait in the browser panel only; the chat showed nothing."""
    notices, seen = [], []

    async def post(agent, payload):
        notices.append((agent.agent_id, payload))

    monkeypatch.setattr(rt, "post_chat_notice", post)
    person = _answer_cards(rt, approve=True, seen=seen)
    try:
        result, _, _ = await _run_steps(rt, [("click", {"index": 7}, CANCEL)])
    finally:
        person.cancel()
    assert result.success
    assert [payload["kind"] for _, payload in notices] == [
        "approval_request", "approval_request_done",
    ]
    agent_id, card = notices[0]
    assert agent_id == rt.lead_id
    assert card["approval_id"] == seen[0].id and card["status"] == "pending"
    assert card["label"] == "Abo kündigen"  # i18n-allow: a page label
    assert card["where"] == "play.google.com"
    assert "SuperGrok 33,99 €/Monat" in card["detail"]
    assert card["browser"] is True
    assert notices[1][1] == {
        "kind": "approval_request_done", "approval_id": seen[0].id, "status": "approved",
    }


async def test_a_gate_card_in_the_conversation_closes_as_declined(rt, monkeypatch):
    notices, seen = [], []

    async def post(agent, payload):
        notices.append(payload)

    monkeypatch.setattr(rt, "post_chat_notice", post)
    await rt.roster.update(rt.lead_id, {"approval_rules": {"require_approval": ["core:browser"]}})
    tool = await _lead_browser(rt, monkeypatch)
    person = _answer_cards(rt, approve=False, seen=seen)
    try:
        result = await tool.execute(
            {"task": "Read the headline"}, SimpleNamespace(approved_by="chat-bypass")
        )
    finally:
        person.cancel()
    assert not result.success
    assert notices[0]["kind"] == "approval_request"
    assert notices[0]["text"] == "society_browser: Read the headline"
    assert notices[-1] == {
        "kind": "approval_request_done", "approval_id": seen[0].id, "status": "declined",
    }


# ------------------------------------------------------------------ money, accounts, the dark web


async def _bypass_agent_run(rt, steps):
    """An agent in Bypass runs ``steps`` (``(url, name, params, target)``)."""
    from dodaios.society.browser.bridge import execute_live

    agent, _ = await rt.roster.create(name="Free hand", provider="openai")
    assert str(agent.approval_mode) == "bypass"
    applied, verdicts = [], []

    async def run(agent, *, action, **kwargs):
        for url, name, params, target in steps:
            async def apply(name=name):
                applied.append(name)
                return {}

            verdict = await action(
                {"action": {name: params}, "url": url, "target": target, "apply": apply}
            )
            verdicts.append(verdict)
            if not verdict["ok"]:
                raise RuntimeError(verdict["error"])
        return {"ok": True, "artifacts": []}

    rt.browser.live.run = run
    result = await execute_live(
        rt, agent, rt.browser, {"task": "Do it"}, SimpleNamespace(trace_id="t", config={})
    )
    return result, applied, verdicts


async def test_a_purchase_asks_even_in_bypass(rt):
    """The person, 2026-11-18: buying with the card asks in every mode, Bypass too."""
    seen = []
    person = _answer_cards(rt, approve=True, seen=seen)
    try:
        result, applied, _ = await _bypass_agent_run(
            rt,
            [("https://shop.example/checkout", "click", {"index": 4},
              _button("Place your order", "Total 49,99 €"))],
        )
    finally:
        person.cancel()
    assert result.success and applied == ["click"]
    assert len(seen) == 1
    assert seen[0].action["commit"]["kind"] == "buy"
    assert seen[0].action["commit"]["severity"] == "confirm"
    assert result.output["consequential"][0]["by"] == "user"


async def test_a_standing_always_allow_does_not_silence_a_purchase(rt):
    await rt.roster.update(rt.lead_id, {"approval_rules": {"always_allow": ["core:browser:*"]}})
    seen = []
    person = _answer_cards(rt, approve=False, seen=seen)
    try:
        result, applied, _ = await _run_steps(
            rt, [("click", {"index": 4}, _button("Buy now"))], task="Buy it"
        )
    finally:
        person.cancel()
    assert not result.success and applied == [] and len(seen) == 1


async def test_a_message_in_bypass_still_runs_without_a_card(rt):
    result, applied, _ = await _bypass_agent_run(
        rt, [("https://mail.example/", "click", {"index": 2}, _button("Send"))]
    )
    assert result.success and applied == ["click"]
    assert await rt.approvals.items() == []


async def test_typing_a_card_number_asks_even_in_bypass_and_never_quotes_it(rt):
    seen = []
    person = _answer_cards(rt, approve=True, seen=seen)
    field = {**_button("Card number"), "tag": "input", "field": "cc-number cardnumber"}
    try:
        result, applied, _ = await _bypass_agent_run(
            rt,
            [
                ("https://shop.example/pay", "input", {"index": 3, "text": "Ruth"},
                 {**_button("Name"), "tag": "input", "field": "cc-name"}),
                ("https://shop.example/pay", "input",
                 {"index": 4, "text": "4111 1111 1111 1111"}, field),
            ],
        )
    finally:
        person.cancel()
    assert result.success and applied == ["input", "input"]
    assert len(seen) == 1
    assert seen[0].action["commit"]["kind"] == "payment_details"
    assert "4111" not in seen[0].summary
    assert "Enter payment details" in seen[0].summary


@pytest.mark.parametrize(
    "url", ["http://abcdefghijklmnop.onion/", "https://market.onion.ws/listing"]
)
async def test_the_dark_web_is_refused_in_every_mode_without_a_card(rt, monkeypatch, url):
    notices = []

    async def post(agent, payload):
        notices.append(payload)

    monkeypatch.setattr(rt, "post_chat_notice", post)
    result, applied, verdicts = await _bypass_agent_run(
        rt, [("https://duckduckgo.com/", "navigate", {"url": url}, None)]
    )
    assert not result.success and applied == []
    assert "dark-web" in verdicts[0]["error"] and "Do not try another way" in verdicts[0]["error"]
    assert await rt.approvals.items() == []
    assert notices and notices[-1]["kind"] == "action_blocked"
    assert notices[-1]["category"] == "dark_web"


@pytest.mark.parametrize(
    ("label", "kind"),
    [
        ("Delete my account", "close_account"),
        ("Konto löschen", "close_account"),  # i18n-allow: a page label
        ("Transfer", "transfer"),
        ("Jetzt überweisen", "transfer"),  # i18n-allow: a page label
        ("Delete", "delete"),
    ],
)
def test_account_and_transfer_clicks_have_their_own_kind(label, kind):
    step = commit_step("click", {"index": 1}, _button(label), "https://bank.example/")
    assert step is not None and step.kind == kind
