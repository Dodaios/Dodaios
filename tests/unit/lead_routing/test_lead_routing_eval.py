"""The lead routing eval plumbing: golden set, scoring, catalog drift check, live gate.

No model is called. The real lead catalog is built once (about ten seconds).
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from tests.eval.lead_routing import (
    LeadCatalog,
    Recording,
    build_lead_catalog,
    format_table,
    live,
    load_cases,
    load_recordings,
    score_case,
    score_cases,
    validate_cases,
)
from tests.eval.lead_routing.cases import CATEGORIES, FIXTURE_DIR, Case, Expect, parse_case
from tests.eval.lead_routing.scoring import missing_requirements
from tests.eval.lead_routing.validate import (
    catalog_problems,
    reference_payload,
    reference_recording,
)

REFERENCE = FIXTURE_DIR / "recorded" / "reference.json"


class _Tool:
    def __init__(self, tier: str = "monitor", props: dict | None = None) -> None:
        self.risk_tier = tier
        self.schema = {"type": "object", "properties": props or {}}
        self.description = "a tool"


def _catalog(**tools: _Tool) -> LeadCatalog:
    return LeadCatalog(tools=dict(tools), session_names=frozenset())


def _case(expect: dict, **kw: object) -> Case:
    raw = {"id": "c1", "category": "status", "lang": "en", "utterance": "u", "expect": expect}
    raw.update(kw)
    return parse_case(raw, "test")


@pytest.fixture(scope="module")
def catalog() -> LeadCatalog:
    return build_lead_catalog()


@pytest.fixture(scope="module")
def cases() -> list[Case]:
    return load_cases()


# ---- the golden set itself ---------------------------------------------------


def test_the_golden_set_is_well_formed_and_big_enough(cases: list[Case]) -> None:
    assert validate_cases(cases) == []
    assert len(cases) >= 150
    counts = Counter(c.category for c in cases)
    assert set(counts) == set(CATEGORIES), "every category needs cases"
    assert min(counts.values()) >= 6
    assert Counter(c.lang for c in cases).keys() == {"en", "de", "es", "pt"}


def test_the_set_is_mostly_english_and_german_with_real_umlauts(cases: list[Case]) -> None:
    langs = Counter(c.lang for c in cases)
    assert langs["en"] >= 60 and langs["de"] >= 40
    german = " ".join(c.utterance for c in cases if c.lang == "de")
    assert any(ch in german for ch in "äöüß")  # i18n-allow: umlaut check
    for fake in ("ae ", "oe ", "ue "):
        assert not any(f" {fake}" in f" {c.utterance} " for c in cases if c.lang == "de")


def test_answer_directly_cases_are_a_real_share(cases: list[Case]) -> None:
    plain = [c for c in cases if not c.expect.expects_tool]
    assert len(plain) >= 12
    assert all(not c.expect.args for c in plain)


def test_malformed_cases_are_rejected() -> None:
    with pytest.raises(ValueError, match="unknown keys"):
        parse_case({"id": "x", "category": "status", "lang": "en", "utterance": "u",
                    "expect": {"tool": "a"}, "oops": 1}, "t")
    with pytest.raises(ValueError, match="cannot expect arguments"):
        _case({"tool": "none", "args": {"a": 1}})
    with pytest.raises(ValueError, match="cannot be mixed"):
        _case({"tools": ["none", "gmail"]})
    assert validate_cases([_case({"tool": "a"}), _case({"tool": "a"})]) == ["c1: duplicate id"]


# ---- scoring -----------------------------------------------------------------


def test_scoring_tool_args_and_direct_answers() -> None:
    cat = _catalog(delegate_to_agent=_Tool())
    case = _case({"tool": "delegate_to_agent", "args": {"agent": "Scout"}})
    ok = score_case(case, Recording("delegate_to_agent", {"agent": "scout the researcher"}), cat)
    assert ok.passed and ok.tool_ok
    wrong_args = score_case(case, Recording("delegate_to_agent", {"agent": "Mailbox"}), cat)
    assert wrong_args.status == "wrong_args" and wrong_args.tool_ok
    wrong_tool = score_case(case, Recording("message_agent", {"target": "Scout"}), cat)
    assert wrong_tool.status == "wrong_tool" and not wrong_tool.tool_ok
    assert score_case(case, Recording(), cat).status == "wrong_tool"
    assert score_case(case, None, cat).detail == "no recorded response"

    direct = _case({"tool": "none"})
    assert score_case(direct, Recording(text="Canberra."), cat).passed
    spawned = score_case(direct, Recording("spawn_worker", {}), cat)
    assert spawned.status == "wrong_tool" and "no tool" in spawned.detail


def test_alternatives_wildcards_and_also_accept() -> None:
    cat = _catalog(find=_Tool())
    case = _case({"tools": ["find", "run"], "also_accept": ["board"], "args": {"*": "team"}})
    assert score_case(case, Recording("run", {"action_id": "POST /api/team-threads"}), cat).passed
    assert score_case(case, Recording("board", {"note": "my team"}), cat).passed
    assert score_case(case, Recording("find", {"query": "weather"}), cat).status == "wrong_args"
    enum_case = _case({"tool": "t", "args": {"action": ["send", "resolve"], "ok": True}})
    assert score_case(enum_case, Recording("t", {"action": "resolve", "ok": True}), cat).passed
    off = score_case(enum_case, Recording("t", {"action": "resolve", "ok": False}), cat)
    assert off.status == "wrong_args"


def test_a_failed_call_is_an_error_never_a_direct_answer() -> None:
    direct = _case({"tool": "none"})
    result = score_case(direct, Recording(error="TimeoutError: 90s"), _catalog())
    assert result.status == "error"
    assert not result.passed


def test_cases_wait_for_tools_that_do_not_exist_yet() -> None:
    case = _case({"tool": "work_board"}, requires=["work_board"])
    assert missing_requirements(case, _catalog()) == ["work_board"]
    skipped = score_case(case, Recording("work_board"), _catalog())
    assert skipped.status == "skipped"
    assert score_case(case, Recording("work_board"), _catalog(work_board=_Tool())).passed
    report = score_cases([case], {}, _catalog())
    assert report.summary()["cases"] == 0 and report.summary()["skipped"] == 1
    assert catalog_problems([case], _catalog()) == []


def test_report_per_category_and_table() -> None:
    cat = _catalog(a=_Tool(), b=_Tool())
    one = _case({"tool": "a"})
    two = parse_case({"id": "c2", "category": "memory", "lang": "de", "utterance": "u",
                      "expect": {"tool": "b"}}, "t")
    report = score_cases([one, two], {"c1": Recording("a"), "c2": Recording("a")}, cat, "seat-x")
    summary = report.summary()
    assert summary["passed"] == 1 and summary["cases"] == 2
    assert summary["categories"]["status"]["accuracy"] == 1.0
    assert summary["categories"]["memory"]["accuracy"] == 0.0
    table = format_table([report])
    assert "seat-x" in table and "memory" in table and "ALL" in table
    assert json.loads(json.dumps(report.to_json()))["results"][1]["status"] == "wrong_tool"


# ---- catalog drift -----------------------------------------------------------


def test_drift_check_flags_missing_tools_argument_keys_and_enum_values() -> None:
    cat = _catalog(
        gmail=_Tool("ask", {"action": {"enum": ["list_messages", "send_message"]}}),
        note=_Tool("safe", {"text": {}}),
    )
    gone = _case({"tool": "removed_tool"})
    assert "not in the lead catalog" in catalog_problems([gone], cat)[0]
    bad_key = _case({"tool": "note", "args": {"body": "x"}})
    assert "no argument 'body'" in catalog_problems([bad_key], cat)[0]
    bad_enum = _case({"tool": "gmail", "args": {"action": "archive"}})
    assert "no value 'archive'" in catalog_problems([bad_enum], cat)[0]
    not_ask = _case({"tool": "note", "approval": True})
    assert "tier 'safe'" in catalog_problems([not_ask], cat)[0]
    sends = _case({"tool": "gmail", "args": {"action": "list_messages"}, "effect": "action"})
    assert "only reads" in catalog_problems([sends], cat)[0]
    reads_but_sends = _case(
        {"tool": "gmail", "args": {"action": "send_message"}, "effect": "read"}
    )
    assert "not a read verb" in catalog_problems([reads_but_sends], cat)[0]


def test_every_case_of_the_golden_set_matches_the_real_lead_catalog(
    cases: list[Case], catalog: LeadCatalog
) -> None:
    """Catches catalog drift: a renamed or removed tool, argument or enum value."""
    assert catalog_problems(cases, catalog) == []


def test_the_catalog_is_the_lead_surface_not_the_machine(catalog: LeadCatalog) -> None:
    core = {"delegate_to_agent", "message_agent", "society_status", "memory-search"}
    assert core <= catalog.names
    assert not any(name.startswith("cli_") for name in catalog.names)


# ---- offline replay ----------------------------------------------------------


def test_reference_recording_is_in_sync_with_the_cases(cases: list[Case]) -> None:
    stored = json.loads(REFERENCE.read_text(encoding="utf-8"))
    assert stored == reference_payload(cases), (
        "tests/fixtures/lead_routing/recorded/reference.json is stale: run "
        "`python scripts/lead_routing_eval.py --write-reference`"
    )


def test_replaying_the_reference_scores_every_runnable_case(
    cases: list[Case], catalog: LeadCatalog
) -> None:
    seat, recordings = load_recordings(REFERENCE)
    assert seat == "reference" and set(recordings) == {c.id for c in cases}
    report = score_cases(cases, recordings, catalog, seat)
    assert report.failures() == []
    assert report.summary()["cases"] >= 100


def test_replaying_a_degraded_seat_is_measured_not_hidden(
    cases: list[Case], catalog: LeadCatalog
) -> None:
    """A seat that answers everything in text must fail every tool case and pass the plain ones."""
    recordings = {c.id: Recording(text="I think so.") for c in cases}
    summary = score_cases(cases, recordings, catalog, "chatty").summary()
    plain = sum(
        1 for c in cases if not c.expect.expects_tool and not missing_requirements(c, catalog)
    )
    assert summary["passed"] == plain
    assert summary["categories"]["answer_directly"]["accuracy"] == 1.0
    assert summary["categories"]["delegate_agent"]["accuracy"] == 0.0


def test_reference_recording_of_a_wildcard_case_mentions_the_target() -> None:
    case = _case(
        {"tool": "workspace-orchestrate", "args": {"action": ["send", "resolve"], "*": "T2"}}
    )
    rec = reference_recording(case)
    assert rec.tool == "workspace-orchestrate" and rec.input == {"action": "send", "task": "T2"}


# ---- the live gate -----------------------------------------------------------


@pytest.fixture
def keyless_background(monkeypatch: pytest.MonkeyPatch) -> None:
    from dodaios.brain import background_policy

    monkeypatch.setattr(background_policy, "_registry_probe", lambda _provider: None)
    monkeypatch.setattr(background_policy, "subscription_mode", lambda _candidates=(): False)


def test_live_never_runs_without_the_explicit_flag(keyless_background: None) -> None:
    gate = live.live_gate("openai", env={}, case_count=10, tokens_per_call=1000)
    assert not gate.allowed
    assert any(live.LIVE_ENV_FLAG in reason for reason in gate.reasons)
    assert "10 model calls" in gate.notice and "1,000 input tokens" in gate.notice


def test_live_never_runs_in_ci_even_with_the_flag(keyless_background: None) -> None:
    for marker in ("CI", "GITHUB_ACTIONS"):
        gate = live.live_gate("openai", env={live.LIVE_ENV_FLAG: "1", marker: "true"})
        assert not gate.allowed and "never run in CI" in gate.reasons[0]


def test_live_is_allowed_only_with_the_flag_outside_ci(keyless_background: None) -> None:
    gate = live.live_gate("openai", env={live.LIVE_ENV_FLAG: "1"}, case_count=3)
    assert gate.allowed and gate.billing == "api" and "BILLS" in gate.notice


def test_live_refuses_a_key_while_a_subscription_is_connected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dodaios.brain import background_policy

    monkeypatch.setattr(background_policy, "subscription_mode", lambda _candidates=(): True)
    monkeypatch.setattr(background_policy, "login_state", lambda _provider: False)
    env = {live.LIVE_ENV_FLAG: "1"}
    gate = live.live_gate("openai", env=env)
    assert not gate.allowed and "--allow-api-key" in gate.reasons[0]
    assert live.live_gate("openai", env=env, allow_api_key=True).allowed


def test_live_cases_without_an_offerable_tool_are_left_out(catalog: LeadCatalog) -> None:
    browser = _case({"tool": "society_browser"})
    assert not live.offerable(browser, catalog)  # session tool: name only, no schema
    assert live.offerable(_case({"tool": "none"}), catalog)
    assert live.offerable(_case({"tool": "memory-search"}), catalog)


def test_live_run_records_the_first_tool_call_and_closes_the_stream() -> None:
    import asyncio

    from dodaios.core.protocols import BrainDelta

    class FakeBrain:
        closed = False

        async def complete(self, req):  # noqa: ANN001, ANN201
            try:
                yield BrainDelta(content="Let me ")
                yield BrainDelta(tool_call={"name": "memory-search", "input": {"query": "x"}})
                yield BrainDelta(content="never read")
            finally:
                FakeBrain.closed = True

    cases = [_case({"tool": "memory-search"})]
    recordings = asyncio.run(live.run_live(cases, _catalog(), FakeBrain()))
    assert recordings["c1"] == Recording("memory-search", {"query": "x"})
    assert FakeBrain.closed


def test_live_run_turns_a_provider_failure_into_an_error_not_a_pass() -> None:
    import asyncio

    class Down:
        async def complete(self, req):  # noqa: ANN001, ANN201
            raise RuntimeError("provider down")
            yield  # pragma: no cover

    cases = [_case({"tool": "none"})]
    recordings = asyncio.run(live.run_live(cases, _catalog(), Down()))
    assert recordings["c1"].error.startswith("RuntimeError")
    assert score_case(cases[0], recordings["c1"], _catalog()).status == "error"


def test_expect_accepts() -> None:
    expect = Expect(tools=("a",), also_accept=("b",))
    assert expect.accepts("a") and expect.accepts("b") and not expect.accepts("c")
    assert not expect.accepts(None)
    assert Expect(tools=("none",)).accepts(None) and not Expect(tools=("none",)).accepts("a")


def test_fixture_dir_is_the_documented_one() -> None:
    assert FIXTURE_DIR == Path(__file__).resolve().parents[2] / "fixtures" / "lead_routing"
