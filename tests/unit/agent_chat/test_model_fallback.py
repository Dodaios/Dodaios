"""A coding thread whose model hits its limit switches models in place and goes on."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest

from dodaios.agent_chat import model_fallback as mf
from dodaios.agent_chat import runner_cli

#: What claude 2.1.323 printed on this Mac on 2026-11-15 for a Fable 5.2 turn
#: while the Fable limit was spent (session ids shortened, usage trimmed).
FABLE_SENTENCE = (
    "You've hit your Fable limit · resets Nov 17 at 12am (Europe/Berlin). Switch to "
    "another model, or manage usage credits at "
    "https://claude.ai/settings/usage?from=cc_cli_limit_message, to continue."
)
RESET = 1794870000  # 2026-11-16T23:00:00Z = 17 Nov 00:00 in Berlin
#: The moment of the recording, three hours before RESET. The module's clock is
#: pinned here so RESET stays in the future however late the suite runs.
NOW = RESET - 3 * 3600
CLAUDE_LIMIT_STREAM = [
    {"type": "system", "subtype": "init", "model": "claude-fable-5-2", "session_id": "cd14"},
    {
        "type": "rate_limit_event",
        "rate_limit_info": {
            "status": "rejected",
            "resetsAt": RESET,
            "rateLimitType": "seven_day_overage_included",
            "overageStatus": "rejected",
            "overageDisabledReason": "out_of_credits",
            "isUsingOverage": False,
        },
        "session_id": "cd14",
    },
    {
        "type": "assistant",
        "message": {
            "id": "49f2",
            "model": "<synthetic>",
            "role": "assistant",
            "stop_reason": "stop_sequence",
            "type": "message",
            "usage": {"input_tokens": 0, "output_tokens": 0},
            "content": [{"type": "text", "text": FABLE_SENTENCE}],
        },
        "parent_tool_use_id": None,
        "session_id": "cd14",
        "error": "rate_limit",
        "is_api_error_message": True,
    },
    {
        "type": "result",
        "subtype": "success",
        "is_error": True,
        "terminal_reason": "api_error",
        "api_error_status": 429,
        "api_error_type": "rate_limit_error",
        "api_error": "usage_limit_reached",
        "result": FABLE_SENTENCE,
        "session_id": "cd14",
        "usage": {"input_tokens": 0, "output_tokens": 0},
        "total_cost_usd": 0,
    },
]


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch) -> None:
    mf.reset()
    monkeypatch.setattr(mf, "time", SimpleNamespace(time=lambda: NOW))
    monkeypatch.setattr(mf, "enabled", lambda: True)
    monkeypatch.setattr(mf, "_configured_chains", lambda: {})
    yield
    mf.reset()


# ------------------------------------------------------------- detection


def test_the_claude_stream_at_a_spent_limit_is_read_from_its_structured_lines() -> None:
    st = runner_cli._ClaudeState(turn_id="t1")
    events: list[dict[str, Any]] = []
    for line in CLAUDE_LIMIT_STREAM:
        events += runner_cli.translate_claude_line(json.loads(json.dumps(line)), st)

    assert st.limit.hit and st.limit.rejected and st.limit.usage_limit
    assert st.limit.resets_at == RESET
    assert st.status == "error" and st.error == FABLE_SENTENCE
    # The CLI's refusal is the error, never the agent's answer.
    assert not [e for e in events if e["kind"] == "assistant_text"]
    assert st.result_text == ""

    hit = mf.detect(st.error, st.limit, model="claude-fable-5-2")
    assert hit is not None
    assert (hit.kind, hit.family, hit.resets_at, hit.source) == ("usage", "Fable", RESET, "stream")


def test_a_sub_agents_limit_is_not_the_threads() -> None:
    st = runner_cli._ClaudeState(turn_id="t1")
    line = {**CLAUDE_LIMIT_STREAM[2], "parent_tool_use_id": "toolu_1"}
    runner_cli.translate_claude_line(line, st)
    assert not st.limit.hit


def test_without_a_stream_signal_the_words_decide() -> None:
    now = RESET - 30 * 3600
    assert mf.parse_reset(FABLE_SENTENCE, now=now) == RESET
    hit = mf.detect(FABLE_SENTENCE, None)
    assert hit is not None and (hit.kind, hit.family, hit.source) == ("usage", "Fable", "text")

    codex = "You've hit your usage limit. Upgrade to Pro or try again at Nov 21st, 2026 3:41 PM."
    hit = mf.detect(codex, None)
    assert hit is not None and hit.kind == "usage" and hit.family == ""
    assert hit.resets_at is not None


@pytest.mark.parametrize(
    "error",
    [
        "Something else broke",
        "Media file exceeds the 512 MiB import limit",
        "claude-cli exited with code 1.",
        "",
        None,
    ],
)
def test_other_failures_are_not_limits(error: str | None) -> None:
    assert mf.detect(error, mf.LimitSignal()) is None


def test_codex_limit_codes_and_reset_times_count() -> None:
    st = runner_cli._CodexState(turn_id="t1")
    runner_cli.translate_codex_line(
        {
            "type": "turn.failed",
            "error": {
                "message": "You've hit your usage limit.",
                "codex_error_info": "usage_limit_exceeded",
                "resets_in_seconds": 7200,
            },
        },
        st,
    )
    assert st.limit.usage_limit
    assert st.limit.resets_at is not None and st.limit.resets_at > NOW + 7000


def test_clock_resets_name_the_next_such_time() -> None:
    at = mf.parse_reset("You've hit your limit · resets 3pm (Europe/Berlin)", now=RESET)
    assert at is not None and 0 < at - RESET <= 86400


# ------------------------------------------------------------- the chain


def test_a_fable_limit_moves_on_to_opus_then_sonnet() -> None:
    hit = mf.LimitHit("usage", family="Fable")
    assert mf.candidates("claude-cli", "claude-fable-5-2", hit=hit) == [
        "claude-opus-5-5",
        "claude-sonnet-5-5",
    ]
    # Another Fable model is spent by the same "Fable limit".
    assert mf.candidates("claude-cli", "claude-fable-5-1", hit=hit) == [
        "claude-opus-5-5",
        "claude-sonnet-5-5",
    ]


def test_a_model_known_to_be_out_is_skipped_until_it_resets() -> None:
    mf.note_limited("claude-cli", "", "claude-fable-5-2", mf.LimitHit("usage", "Fable", RESET))
    mf.note_limited("claude-cli", "other-seat", "claude-sonnet-5-5", mf.LimitHit("usage"))
    hit = mf.LimitHit("usage", family="Opus")
    assert mf.candidates("claude-cli", "claude-opus-5-5", hit=hit) == ["claude-sonnet-5-5"]


def test_the_chain_is_configurable_per_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        mf,
        "_configured_chains",
        lambda: {"claude-cli": ["claude-opus-5-5", "claude-haiku-5-5"], "grok-cli": []},
    )
    assert mf.chain_for("claude-cli") == ("claude-opus-5-5", "claude-haiku-5-5")
    assert mf.chain_for("grok-cli") == ()  # an empty list switches it off
    assert mf.chain_for("codex-cli") == mf.DEFAULT_CHAINS["codex-cli"]
    assert mf.effective_chains()["claude-cli"] == ["claude-opus-5-5", "claude-haiku-5-5"]


def test_the_setting_is_on_by_default_and_reads_chains_from_config() -> None:
    from dodaios.core.config import AgenticIdeConfig

    cfg = AgenticIdeConfig()
    assert cfg.model_fallback is True and cfg.model_fallback_chains == {}
    cfg = AgenticIdeConfig(
        model_fallback_chains={"claude-cli": "claude-opus-5-5, claude-sonnet-5-5"}
    )
    assert cfg.model_fallback_chains == {"claude-cli": ["claude-opus-5-5", "claude-sonnet-5-5"]}
    assert AgenticIdeConfig(model_fallback_chains="nonsense").model_fallback_chains == {}


def test_the_switch_is_written_to_the_config_file(tmp_path: Any) -> None:
    import tomllib

    from dodaios.core import config_writer

    path = tmp_path / "dodaios.toml"
    path.write_text("[agentic_ide]\nfollow_main = true\n", encoding="utf-8")
    config_writer.set_agentic_ide_model_fallback(False, path=path)
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    assert data["agentic_ide"] == {"follow_main": True, "model_fallback": False}


def test_model_labels_are_short() -> None:
    assert mf.model_label("claude-opus-5-5") == "Opus 5.5"
    assert mf.model_label("claude-sonnet-5-5") == "Sonnet 5.5"
    assert mf.model_label("claude-fable-5-2") == "Fable 5.2"
    assert mf.model_label("") == "the default model"


# ------------------------------------------------------ the turn switches


class _Store:
    def __init__(self) -> None:
        self.updates: list[dict[str, Any]] = []

    def update_session(self, session_id: str, **fields: Any) -> None:
        self.updates.append({"session_id": session_id, **fields})


def _handle(
    events: list[dict[str, Any]], *, model: str = "claude-fable-5-2", surface: str = "agent"
) -> Any:
    async def emit(event: dict[str, Any]) -> None:
        events.append(event)

    store = _Store()
    return SimpleNamespace(
        turn_id="t1",
        session=SimpleNamespace(session_id="s1", model=model, surface=surface),
        emit=emit,
        cancel=asyncio.Event(),
        control_service=SimpleNamespace(store=store),
    )


@pytest.fixture(autouse=True)
def _plain_replace(monkeypatch: pytest.MonkeyPatch) -> None:
    """SimpleNamespace is no dataclass: ``replace`` copies it with the change."""

    def replace(obj: Any, **changes: Any) -> Any:
        if isinstance(obj, SimpleNamespace):
            return SimpleNamespace(**{**vars(obj), **changes})
        import dataclasses

        return dataclasses.replace(obj, **changes)

    monkeypatch.setattr(runner_cli, "replace", replace)


def _limited(model: str, resets_at: float | None = RESET, family: str = "") -> runner_cli._Outcome:
    signal = mf.LimitSignal(rejected=True, rate_limited=True, resets_at=resets_at)
    sentence = f"You've hit your {family} limit · resets Nov 17 at 12am (Europe/Berlin)."
    return runner_cli._Outcome(
        "error", sentence, {"output_tokens": 0}, None, f"conv-{model}", signal
    )


def _run(
    handle: Any,
    first: runner_cli._Outcome,
    answers: list[runner_cli._Outcome],
    *,
    started_work: bool = True,
) -> tuple[runner_cli._Outcome, Any, list[tuple[str, str, str | None]]]:
    runs: list[tuple[str, str, str | None]] = []

    async def run_again(moved: Any, prompt: str, conversation: str | None) -> runner_cli._Outcome:
        runs.append((moved.session.model, prompt, conversation))
        return answers.pop(0)

    result, after = asyncio.run(
        runner_cli._continue_on_fallback_model(
            handle,
            first,
            "claude-cli",
            {"claude": "seat-a"},
            started_work=lambda: started_work,
            run_again=run_again,
            user_text="fix the bug",
            resume="conv-0",
        )
    )
    return result, after, runs


def _notices(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e["payload"] for e in events if e["kind"] == "notice"]


def test_todays_fable_limit_switches_the_same_thread_to_opus_and_continues() -> None:
    events: list[dict[str, Any]] = []
    handle = _handle(events)
    done = runner_cli._Outcome("done", None, {"output_tokens": 40}, None, "conv-claude-fable-5-2")

    result, after, runs = _run(handle, _limited("claude-fable-5-2", family="Fable"), [done])

    assert (result.status, result.error) == ("done", None)
    # The same conversation, told to carry on, on Opus 5.5.
    assert runs == [
        ("claude-opus-5-5", mf.CONTINUE_PROMPT.format(model="Opus 5.5"), "conv-claude-fable-5-2")
    ]
    assert handle.control_service.store.updates == [
        {"session_id": "s1", "model": "claude-opus-5-5"}
    ]
    assert after.session.model == "claude-opus-5-5"
    assert {"kind": "session_updated", "model": "claude-opus-5-5"} in [
        {"kind": e["kind"], **e["payload"]} for e in events if e["kind"] == "session_updated"
    ]
    [notice] = _notices(events)
    assert notice["kind"] == mf.NOTICE_KIND
    assert (notice["limit_label"], notice["to_label"], notice["resets_at"]) == (
        "Fable",
        "Opus 5.5",
        RESET,
    )
    assert notice["turn_id"] == "t1"
    assert notice["text"].startswith("Fable limit reached until ")
    assert notice["text"].endswith("– continued on Opus 5.5.")


def test_a_turn_refused_before_it_started_sends_the_message_again() -> None:
    events: list[dict[str, Any]] = []
    done = runner_cli._Outcome("done", None, {}, None, "conv-1")
    _result, _after, runs = _run(
        _handle(events), _limited("claude-fable-5-2", family="Fable"), [done], started_work=False
    )
    assert runs == [("claude-opus-5-5", "fix the bug", "conv-claude-fable-5-2")]


def test_a_limited_fallback_walks_on_to_the_next_model() -> None:
    events: list[dict[str, Any]] = []
    done = runner_cli._Outcome("done", None, {}, None, "conv-x")
    result, after, runs = _run(
        _handle(events),
        _limited("claude-fable-5-2", family="Fable"),
        [_limited("claude-opus-5-5", family="Opus"), done],
    )
    assert [model for model, _prompt, _conv in runs] == ["claude-opus-5-5", "claude-sonnet-5-5"]
    assert result.status == "done" and after.session.model == "claude-sonnet-5-5"
    assert [n["to_label"] for n in _notices(events)] == ["Opus 5.5", "Sonnet 5.5"]


def test_when_every_model_is_limited_the_turn_stops_once_with_the_reset_time() -> None:
    events: list[dict[str, Any]] = []
    result, after, runs = _run(
        _handle(events),
        _limited("claude-fable-5-2", family="Fable"),
        [
            _limited("claude-opus-5-5", family="Opus"),
            _limited("claude-sonnet-5-5", family="Sonnet"),
        ],
    )
    # Each model once, then one stop.
    assert [model for model, _p, _c in runs] == ["claude-opus-5-5", "claude-sonnet-5-5"]
    assert result.status == "error"
    assert result.error.startswith("Usage limit reached on every model this thread can use")
    assert "resets at 2026-11-16T23:00Z" in result.error
    exhausted = [n for n in _notices(events) if n["kind"] == mf.EXHAUSTED_KIND]
    assert len(exhausted) == 1
    assert [m["label"] for m in exhausted[0]["models"]] == ["Fable", "Opus", "Sonnet"]
    assert exhausted[0]["resets_at"] == RESET
    # No switch went through: the thread stays on the model it had, not on
    # the last one the walk tried.
    assert after.session.model == "claude-fable-5-2"
    assert after.control_service.store.updates == []
    assert not [e for e in events if e["kind"] == "session_updated"]

    # The next turn on the thread does not walk the chain again.
    events2: list[dict[str, Any]] = []
    result2, _after2, runs2 = _run(
        _handle(events2, model=after.session.model),
        _limited("claude-fable-5-2", family="Fable"),
        [],
    )
    assert runs2 == []
    assert result2.status == "error" and "every model" in result2.error
    [stop] = _notices(events2)
    assert stop["kind"] == mf.EXHAUSTED_KIND and stop["resets_at"] == RESET


def test_another_failure_after_the_switch_stands() -> None:
    events: list[dict[str, Any]] = []
    handle = _handle(events)
    broke = runner_cli._Outcome("error", "Something else broke", {}, None, "conv-1")
    result, after, runs = _run(handle, _limited("claude-fable-5-2", family="Fable"), [broke])
    assert len(runs) == 1
    assert result.error == "Something else broke"
    assert not [n for n in _notices(events) if n["kind"] == mf.EXHAUSTED_KIND]
    # The model that broke is not kept: the next message runs where the thread was.
    assert after.session.model == "claude-fable-5-2"
    assert handle.control_service.store.updates == []


_NO_SUCH_MODEL = (
    "There's an issue with the selected model (claude-opus-5-5). It may not exist or you "
    "may not have access to it. Run --model to pick a different model."
)


def test_a_model_the_cli_cannot_run_is_skipped_and_never_kept() -> None:
    # A Sonnet thread went up to Fable, which failed with this sentence; the
    # thread was left stored on Fable and every later turn failed.
    events: list[dict[str, Any]] = []
    handle = _handle(events)
    unusable = runner_cli._Outcome("error", _NO_SUCH_MODEL, {}, None, "conv-1")
    done = runner_cli._Outcome("done", None, {}, None, "conv-2")
    result, after, runs = _run(
        handle, _limited("claude-fable-5-2", family="Fable"), [unusable, done]
    )
    assert [model for model, _p, _c in runs] == ["claude-opus-5-5", "claude-sonnet-5-5"]
    assert result.status == "done"
    assert after.session.model == "claude-sonnet-5-5"
    # Only the model that worked was stored.
    assert handle.control_service.store.updates == [
        {"session_id": "s1", "model": "claude-sonnet-5-5"}
    ]


def test_a_thread_whose_only_fallbacks_cannot_run_stays_on_its_model() -> None:
    events: list[dict[str, Any]] = []
    handle = _handle(events)
    unusable = runner_cli._Outcome("error", _NO_SUCH_MODEL, {}, None, "conv-1")
    result, after, runs = _run(
        handle, _limited("claude-fable-5-2", family="Fable"), [unusable, unusable]
    )
    assert len(runs) == 2 and result.status == "error"
    assert after.session.model == "claude-fable-5-2"
    assert handle.control_service.store.updates == []


@pytest.mark.parametrize(
    ("current", "family", "expected"),
    [
        # Down the chain, never up: an Opus limit is no reason to pay for Fable.
        ("claude-opus-5-5", "Opus", ["claude-sonnet-5-5"]),
        ("claude-sonnet-5-5", "Sonnet", []),
        ("claude-fable-5-2", "Fable", ["claude-opus-5-5", "claude-sonnet-5-5"]),
        # An alias of a chain model sits where its family does.
        ("opus", "Opus", ["claude-sonnet-5-5"]),
        # A model outside the chain tries it from the top.
        ("claude-haiku-4-5", "Haiku", ["claude-fable-5-2", "claude-opus-5-5", "claude-sonnet-5-5"]),
    ],
)
def test_a_limited_thread_walks_down_the_chain_from_its_own_model(
    current: str, family: str, expected: list[str]
) -> None:
    hit = mf.LimitHit("usage", family, RESET)
    assert mf.candidates("claude-cli", current, hit=hit) == expected


def test_an_opus_thread_at_its_limit_goes_on_on_sonnet_not_fable() -> None:
    events: list[dict[str, Any]] = []
    done = runner_cli._Outcome("done", None, {}, None, "conv-2")
    _result, after, runs = _run(
        _handle(events, model="claude-opus-5-5"),
        _limited("claude-opus-5-5", family="Opus"),
        [done],
    )
    assert [model for model, _p, _c in runs] == ["claude-sonnet-5-5"]
    assert after.session.model == "claude-sonnet-5-5"


def _rate_burst() -> runner_cli._Outcome:
    signal = mf.LimitSignal(rate_limited=True)
    return runner_cli._Outcome("error", "API Error: 429 rate_limit_error", {}, None, "c", signal)


@pytest.mark.parametrize(
    "first",
    [
        # The whole account is out: every model of the chain shares it.
        _limited("claude-fable-5-2", family=""),
        # A burst of requests: it passes in a minute or two.
        _rate_burst(),
    ],
    ids=["account-wide", "rate-burst"],
)
def test_a_limit_another_model_would_not_help_with_keeps_the_model(
    first: runner_cli._Outcome,
) -> None:
    events: list[dict[str, Any]] = []
    handle = _handle(events)
    result, after, runs = _run(handle, first, [])
    assert result is first and runs == [] and events == []
    assert after.session.model == "claude-fable-5-2"
    assert handle.control_service.store.updates == []


def test_a_tools_limit_text_is_not_the_models_limit() -> None:
    # A tool's own output ("npm ERR! 429", a sub-agent's "Fable limit") became
    # the turn's error when the CLI ended without words of its own.
    events: list[dict[str, Any]] = []
    tool_said = runner_cli._Outcome(
        "error",
        "You've hit your Fable limit · resets Nov 17 at 12am (Europe/Berlin).",
        {},
        None,
        "conv-1",
        None,
        tool_error=True,
    )
    result, after, runs = _run(_handle(events), tool_said, [])
    assert result is tool_said and runs == [] and events == []
    assert mf.limited_until("claude-cli", "seat-a", "claude-fable-5-2") is None


def test_a_family_named_by_the_limit_window_counts() -> None:
    signal = mf.LimitSignal(rejected=True, limit_type="seven_day_opus", resets_at=RESET)
    hit = mf.detect("You've hit your limit", signal, model="claude-opus-5-5")
    assert hit is not None and hit.family == "Opus" and mf.switch_helps(hit)


@pytest.mark.parametrize(
    "error",
    [
        _NO_SUCH_MODEL,
        '{"type":"error","error":{"type":"not_found_error","message":"model: claude-x"}}',
        "OAuth token has expired. Please obtain a new token or refresh your existing token.",
        "Invalid API key · Please run /login",
    ],
)
def test_a_model_or_login_the_cli_cannot_use_is_told_apart(error: str) -> None:
    assert mf.model_unusable(error)


@pytest.mark.parametrize("error", ["Something else broke", "", None, "npm ERR! 429"])
def test_other_failures_are_not_an_unusable_model(error: str | None) -> None:
    assert not mf.model_unusable(error)


def test_with_the_setting_off_the_limit_stands(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mf, "enabled", lambda: False)
    events: list[dict[str, Any]] = []
    first = _limited("claude-fable-5-2", family="Fable")
    result, after, runs = _run(_handle(events), first, [])
    assert result is first and runs == [] and events == []
    assert after.session.model == "claude-fable-5-2"
    # Still noted: a later look at the chain knows Fable is out.
    assert mf.limited_until("claude-cli", "seat-a", "claude-fable-5-2") == RESET


@pytest.mark.parametrize("surface", ["jarvis", "society"])
def test_only_coding_threads_switch_models(surface: str) -> None:
    events: list[dict[str, Any]] = []
    first = _limited("claude-fable-5-2", family="Fable")
    result, _after, runs = _run(_handle(events, surface=surface), first, [])
    assert result is first and runs == [] and events == []


def test_a_stopped_turn_does_not_switch() -> None:
    events: list[dict[str, Any]] = []
    handle = _handle(events)
    handle.cancel.set()
    first = _limited("claude-fable-5-2", family="Fable")
    result, _after, runs = _run(handle, first, [])
    assert runs == [] and result.status == "error"
    assert not _notices(events)


# ------------------------------------------------------ the lead's report


def test_the_report_to_the_lead_names_the_model_that_finished() -> None:
    switched = mf.switch_notice(
        mf.LimitHit("usage", "Fable", RESET), "claude-fable-5-2", "claude-opus-5-5", RESET
    )
    events = [
        {"kind": "turn_started", "payload": {"turn_id": "t1"}},
        {"kind": "notice", "payload": {**switched, "turn_id": "t1"}},
        {"kind": "notice", "payload": {**switched, "turn_id": "t0"}},
    ]
    line = mf.report_line(events, "t1")
    assert line.startswith("Finished on Opus 5.5: Fable hit its usage limit (until ")
    assert mf.report_line(events, "t9") == ""


def test_the_notice_names_the_reset_time_with_two_digit_hours() -> None:
    from datetime import datetime

    notice = mf.switch_notice(
        mf.LimitHit("usage", "Fable", RESET), "claude-fable-5-2", "claude-opus-5-5", RESET
    )
    moment = datetime.fromtimestamp(RESET)
    assert f"until {moment:%b} {moment.day}, {moment:%H:%M} – " in notice["text"]
