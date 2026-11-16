"""The safety net that closes issues a merged fix or a finished report left open."""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Sequence
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "ci" / "close_fixed_issues.py"
_spec = importlib.util.spec_from_file_location("close_fixed_issues", _SCRIPT)
assert _spec and _spec.loader
cfi = importlib.util.module_from_spec(_spec)
sys.modules["close_fixed_issues"] = cfi
_spec.loader.exec_module(cfi)

REPO = "owner/repo"


class FakeGh:
    def __init__(self, pr: dict | None = None, issues: dict | None = None, reports=()):
        self.pr = pr or {}
        self.issues = issues or {}
        self.reports = list(reports)
        self.closed: list[int] = []

    def __call__(self, args: Sequence[str]) -> str:
        args = list(args)
        if args[:1] == ["api"] and "/pulls/" in args[1]:
            return json.dumps(self.pr)
        if args[:1] == ["api"] and "/issues/" in args[1]:
            number = int(args[1].rsplit("/", 1)[1])
            return json.dumps(self.issues[number])
        if args[:2] == ["issue", "list"]:
            return json.dumps(self.reports)
        if args[:2] == ["issue", "close"]:
            self.closed.append(int(args[2]))
            return ""
        raise AssertionError(f"unexpected gh call: {args}")


def merged(title: str, body: str = "") -> dict:
    return {
        "number": 1710,
        "title": title,
        "body": body,
        "merged_at": "2026-11-15T10:34:53Z",
        "base": {"ref": "main", "repo": {"default_branch": "main"}},
    }


OPEN = {"state": "open"}


def test_a_fix_title_closes_the_issue_it_names() -> None:
    fake = FakeGh(merged("fix(piper): the voice speaks (#1698)"), {1698: OPEN})
    assert cfi.Closer(REPO, fake).close_fixed_by_pr(1710) == [1698]
    assert fake.closed == [1698]


def test_a_feature_title_that_names_an_issue_closes_nothing() -> None:
    fake = FakeGh(merged("feat(chat): bubbles (#1698)"), {1698: OPEN})
    assert cfi.Closer(REPO, fake).close_fixed_by_pr(1710) == []


def test_a_closing_keyword_in_any_title_closes_the_issue() -> None:
    fake = FakeGh(merged("ci: retry the shard, fixes #1629"), {1629: OPEN})
    assert cfi.Closer(REPO, fake).close_fixed_by_pr(1710) == [1629]


def test_an_issue_the_body_only_refers_to_stays_open() -> None:
    fake = FakeGh(merged("fix(x): partial step (#450)", "Refs #450"), {450: OPEN})
    assert cfi.Closer(REPO, fake).close_fixed_by_pr(1710) == []


def test_closed_issues_and_pull_requests_are_left_alone() -> None:
    issues = {1: {"state": "closed"}, 2: {"state": "open", "pull_request": {}}}
    fake = FakeGh(merged("fix(x): y (#1) (#2)"), issues)
    assert cfi.Closer(REPO, fake).close_fixed_by_pr(1710) == []


def test_an_unmerged_pull_request_closes_nothing() -> None:
    pr = merged("fix(x): y (#1698)") | {"merged_at": None}
    fake = FakeGh(pr, {1698: OPEN})
    assert cfi.Closer(REPO, fake).close_fixed_by_pr(1710) == []


def test_a_dry_run_writes_nothing() -> None:
    fake = FakeGh(merged("fix(piper): y (#1698)"), {1698: OPEN})
    assert cfi.Closer(REPO, fake, dry_run=True).close_fixed_by_pr(1710) == [1698]
    assert fake.closed == []


REPORT = """Nightly review.

### Verified findings (sub-issues)
- #1543: flakes in the merge queue for PRs #1491 and #1530.
- #1390: SIGPIPE.

### Reviewed, not filed
- #999: an old note, not a finding.
"""


def test_findings_are_the_items_under_the_findings_heading() -> None:
    assert cfi.report_findings(REPORT) == [1543, 1390]
    assert cfi.report_findings("no heading\n- #1: x") == []


def test_a_report_closes_once_every_finding_is_closed() -> None:
    issues = {1543: {"state": "closed"}, 1390: {"state": "closed"}, 999: OPEN}
    fake = FakeGh(issues=issues, reports=[{"number": 1544, "body": REPORT}])
    assert cfi.Closer(REPO, fake).close_finished_reports() == [1544]


def test_a_report_with_an_open_finding_stays_open() -> None:
    issues = {1543: {"state": "closed"}, 1390: OPEN}
    fake = FakeGh(issues=issues, reports=[{"number": 1544, "body": REPORT}])
    assert cfi.Closer(REPO, fake).close_finished_reports() == []


def test_a_finding_closed_by_the_same_run_finishes_its_report() -> None:
    body = "### Verified findings\n- #1698: Piper is silent.\n"
    fake = FakeGh(
        merged("fix(piper): y (#1698)"),
        {1698: OPEN},
        reports=[{"number": 1700, "body": body}],
    )
    closer = cfi.Closer(REPO, fake)
    closer.close_fixed_by_pr(1710)
    assert closer.close_finished_reports() == [1700]
    assert fake.closed == [1698, 1700]
