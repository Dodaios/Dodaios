"""M5 per-step diagnostics regressions (offline, no GUI, no billable calls).

Proves the structured, privacy-conscious evidence trail:

* the judge prompt carries the follow-the-link addendum (no hardcoding of a
  generic shortcut, navigation semantics only);
* the engine's local-only detector is per-mission (normal missions keep the
  prior chain);
* the click_element success output carries UIA evidence (label/role/rect,
  window handle, match count, shallow/deep stability) without secrets;
* the navigation oracle corroboration repairs the M5 false reject and keeps
  rejecting the premature intermediate done.
"""

from __future__ import annotations

import pytest

import dodaios.cu.engine as engine_mod
from dodaios.cu.navigation_oracle import navigation_oracle_verdict


def test_judge_prompt_has_navigation_addendum_without_hardcoded_shortcut() -> None:
    assert "FOLLOW-THE-LINK" in engine_mod._NAVIGATION_JUDGE_ADDENDUM
    assert "intermediate" in engine_mod._NAVIGATION_JUDGE_ADDENDUM.lower()
    # The generic judge must not hardcode the M5 hosts as a pass rule.
    assert "iana.org" not in engine_mod._JUDGE_SYSTEM
    assert "example.com" not in engine_mod._JUDGE_SYSTEM


def test_oracle_repairs_m5_false_reject_with_full_chain() -> None:
    goal = (
        "Open Chrome and navigate to example.com. Then click the 'Learn more' "
        "link on the Example Domain page. Finish once the destination page is shown."
    )
    history = ["step 5: click_element('Learn more') -> OK"]
    labels = ["Example Domains", "IANA"]
    field_hint = '"Address and search bar" currently contains "https://iana.org/help/example-domains"'
    applicable, done, proof = navigation_oracle_verdict(
        goal, history, labels, "Example Domains - IANA", field_hint,
    )
    assert applicable and done
    # The repaired proof must quote destination evidence, not invent a page.
    assert "iana.org/help/example-domains" in proof


def test_oracle_keeps_rejecting_premature_intermediate_done() -> None:
    goal = (
        "Open Chrome and navigate to example.com. Then click the 'Learn more' "
        "link on the Example Domain page. Finish once the destination page is shown."
    )
    applicable, done, reason = navigation_oracle_verdict(
        goal, [], ["Example Domain", "Learn more"], "Example Domain",
    )
    assert applicable and not done
    assert "still on the" in reason


async def test_click_element_success_carries_uia_evidence() -> None:
    from types import SimpleNamespace

    from dodaios.core.protocols import ExecutionContext
    from dodaios.plugins.tool import click_element as ce

    class _Node:
        def __init__(self) -> None:
            self.role = "Hyperlink"
            self.name = "Learn more"
            self.bounds = (950, 700, 120, 24)
            self.enabled = True
            self.automation_id = ""
            self.focused = False

    class _Obs:
        nodes = (_Node(),)

    class _Vision:
        async def observe(self) -> _Obs:
            return _Obs()

    recorded: list[tuple[int, int, str, bool]] = []

    def _fake_click(x: int, y: int, button: str, double: bool, **kw: object) -> None:
        recorded.append((x, y, button, double))

    import uuid

    from dodaios.core.protocols import UIANode

    tool = ce.ClickElementTool(vision_source=_Vision())
    ctx = SimpleNamespace(
        trace_id=uuid.uuid4(), user_utterance="cu", config={}, memory_read=None,
    )
    import dodaios.plugins.tool.click_element as ce_mod
    from types import SimpleNamespace as _NS

    orig_click = ce_mod._click_windows
    orig_sig = ce_mod._foreground_window_signature
    orig_os = ce_mod.os
    ce_mod._click_windows = _fake_click  # type: ignore[assignment]
    ce_mod._foreground_window_signature = lambda: ("handle", 4242, (0, 0, 100, 100))  # type: ignore[assignment]
    ce_mod.os = _NS(name="nt")  # type: ignore[assignment]
    try:
        result = await tool.execute({"name": "Learn more"}, ctx)  # type: ignore[arg-type]
    finally:
        ce_mod._click_windows = orig_click  # type: ignore[assignment]
        ce_mod._foreground_window_signature = orig_sig  # type: ignore[assignment]
        ce_mod.os = orig_os  # type: ignore[assignment]
    assert result.success is True
    out = str(result.output or "")
    assert "Learn more" in out
    assert "role=Hyperlink" in out
    assert "rect=(950,700,120,24)" in out
    assert "window=4242" in out
    assert "matches=1" in out
    assert "stability=" in out
    # No secrets, no screenshots in the evidence string.
    assert "sk-" not in out and "token" not in out.lower()
    assert recorded == [(1010, 712, "left", False)]


def test_step_diag_is_privacy_conscious() -> None:
    proof = engine_mod._redact_proof("  line1\nline2  with   spaces  ", 220)
    assert proof == "line1 line2 with spaces"
    long_proof = engine_mod._redact_proof("x" * 500, 220)
    assert len(long_proof) <= 220
