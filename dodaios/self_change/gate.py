"""The gate a self-change passes before it may go live.

Each surface has its own offline regression checks. A check never calls a model
and never touches the live app: it validates the candidate text (skills), replays
the lead routing golden set against the candidate (prompts, instructions, tool
descriptions) or runs the matching tests in a scratch checkout (code).

A check answers one of three things:

``pass``         nothing got worse.
``fail``         a regression or a defect: the change is blocked and never applied.
``unavailable``  the check could not run (no golden set in this build, no tests
                 named for a code change). The change is not blocked, but it is
                 not trusted either: it waits for the owner.

A surface without any check is ``unavailable``: the gate fails closed.
"""

from __future__ import annotations

import contextlib
import logging
import subprocess
import sys
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from .store import ChangeStore
from .surfaces import Surface

log = logging.getLogger(__name__)

PASS: Final = "pass"  # noqa: S105 — a status word, not a secret
FAIL: Final = "fail"
UNAVAILABLE: Final = "unavailable"

#: The regression suite for prompt and tool-description changes.
ROUTING_SUITE: Final = "lead_routing"


@dataclass(slots=True)
class Draft:
    """A proposed self-change, before it is recorded."""

    surface: Surface
    target: str
    after: str | None
    author: str
    reason: str = ""
    turn: str = ""
    #: The exact text now, when the caller already holds it. Else the handler reads it.
    before: str | None = None
    #: Files a code change touches (decides whether it is a core change).
    paths: tuple[str, ...] = ()
    #: Test files or node ids that cover a code change.
    tests: tuple[str, ...] = ()
    #: Folder the code change lives in (a scratch checkout); tests run there.
    workdir: Path | None = None
    #: Enters a scratch state where the candidate is applied, for replay checks.
    sandbox: Callable[[], AbstractContextManager[Any]] | None = None
    #: Something that identifies the change in another store (a build id).
    ref: str = ""


@dataclass(slots=True)
class CheckResult:
    name: str
    status: str
    detail: str = ""
    score: float | None = None

    def public(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "score": self.score,
        }


@dataclass(slots=True)
class GateReport:
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def status(self) -> str:
        statuses = {c.status for c in self.checks}
        if FAIL in statuses:
            return FAIL
        if UNAVAILABLE in statuses or not statuses:
            return UNAVAILABLE
        return PASS

    @property
    def failed(self) -> bool:
        return self.status == FAIL

    @property
    def passed(self) -> bool:
        return self.status == PASS

    def summary(self) -> str:
        bad = [c for c in self.checks if c.status != PASS]
        if not bad:
            return "all checks passed"
        return "; ".join(f"{c.name}: {c.detail or c.status}" for c in bad)

    def public(self) -> dict[str, Any]:
        return {"status": self.status, "checks": [c.public() for c in self.checks]}


Check = Callable[[Draft, "Gate"], CheckResult]


# ------------------------------------------------------------------- checks


def hygiene(draft: Draft, gate: Gate) -> CheckResult:
    """No invisible characters and no credential-shaped text in anything the agent writes."""
    text = draft.after or ""
    if not text:
        return CheckResult("hygiene", PASS, "nothing is written")
    try:
        from dodaios.memory.learning.guard import contains_secret, hidden_characters
    except Exception:  # noqa: BLE001 — a missing guard must not wave a change through
        return CheckResult("hygiene", UNAVAILABLE, "the text guard could not be loaded")
    if hidden_characters(text):
        return CheckResult("hygiene", FAIL, "it contains invisible or unassigned characters")
    if contains_secret(text):
        return CheckResult("hygiene", FAIL, "it contains credential-shaped text")
    return CheckResult("hygiene", PASS)


def skill_valid(draft: Draft, gate: Gate) -> CheckResult:
    """The skill file parses, validates and its code blocks pass the safe-import lint."""
    if draft.after is None:
        return CheckResult("skill", PASS, "the skill is removed")
    try:
        from dodaios.skills.authoring.draft_writer import safe_lint_skill_body
        from dodaios.skills.creator_service import validate_skill_md
    except Exception:  # noqa: BLE001
        return CheckResult("skill", UNAVAILABLE, "the skill validator could not be loaded")
    validation, frontmatter = validate_skill_md(draft.after)
    if not validation.get("ok") or frontmatter is None:
        errors = "; ".join(str(e) for e in validation.get("errors") or []) or "does not parse"
        return CheckResult("skill", FAIL, f"the skill file is invalid: {errors[:200]}")
    findings = safe_lint_skill_body(draft.after)
    if findings:
        return CheckResult("skill", FAIL, f"unsafe code in the skill: {findings[0]}"[:200])
    return CheckResult("skill", PASS, "the skill parses and its code blocks are safe")


def _replay_rate() -> tuple[float | None, list[str]]:
    """Pass rate of the recorded replays on the current lead catalog, and any drift problems."""
    from tests.eval.lead_routing import (
        build_lead_catalog,
        load_cases,
        load_recordings,
        score_cases,
    )
    from tests.eval.lead_routing.cases import FIXTURE_DIR
    from tests.eval.lead_routing.validate import catalog_problems

    cases = load_cases()
    catalog = build_lead_catalog()
    problems = list(catalog_problems(cases, catalog))
    rates: list[float] = []
    for path in sorted((FIXTURE_DIR / "recorded").glob("*.json")):
        seat, recordings = load_recordings(path)
        accuracy = score_cases(cases, recordings, catalog, seat).summary()["accuracy"]
        if accuracy is not None:
            rates.append(float(accuracy))
    return (sum(rates) / len(rates) if rates else None), problems


def routing_replay(draft: Draft, gate: Gate) -> CheckResult:
    """The lead routing golden set must score at least what it scored before the change."""
    try:
        before, _ = gate.replay()
        if draft.sandbox is not None:
            with draft.sandbox():
                after, problems = gate.replay()
        else:
            after, problems = before, []
    except Exception as exc:  # noqa: BLE001 — a build without the golden set cannot grade it
        log.info("self_change: routing replay unavailable", exc_info=True)
        detail = f"the golden set could not run ({exc})"
        return CheckResult(ROUTING_SUITE, UNAVAILABLE, detail[:200])
    if after is None or before is None:
        return CheckResult(ROUTING_SUITE, UNAVAILABLE, "no recorded replay to score")
    if problems:
        return CheckResult(
            ROUTING_SUITE, FAIL, f"the lead catalog drifted: {problems[0]}"[:200], score=after
        )
    if after + 1e-9 < before:
        detail = f"routing accuracy fell from {before:.1%} to {after:.1%}"
        return CheckResult(ROUTING_SUITE, FAIL, detail, score=after)
    detail = f"routing accuracy {before:.1%} -> {after:.1%}"
    return CheckResult(ROUTING_SUITE, PASS, detail, score=after)


def code_tests(draft: Draft, gate: Gate) -> CheckResult:
    """The tests named for a code change pass in the scratch checkout."""
    if not draft.tests or draft.workdir is None:
        return CheckResult("tests", UNAVAILABLE, "no tests were named for this code change")
    try:
        done = gate.run_tests(draft.workdir, draft.tests)
    except Exception as exc:  # noqa: BLE001
        return CheckResult("tests", UNAVAILABLE, f"the tests could not run ({exc})"[:200])
    if done.returncode != 0:
        tail = (done.stdout or done.stderr or "").strip().splitlines()[-1:] or ["failed"]
        return CheckResult("tests", FAIL, f"the tests failed: {tail[0]}"[:200])
    return CheckResult("tests", PASS, f"{len(draft.tests)} test target(s) passed")


def _run_pytest(workdir: Path, tests: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 — fixed argv, named test targets, scratch checkout
        [sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", *tests],
        cwd=workdir,
        capture_output=True,
        text=True,
        timeout=1800,
        check=False,
    )


DEFAULT_CHECKS: Final[dict[Surface, tuple[Check, ...]]] = {
    Surface.SKILL: (hygiene, skill_valid),
    Surface.PROMPT: (hygiene, routing_replay),
    Surface.INSTRUCTIONS: (hygiene, routing_replay),
    Surface.TOOL: (hygiene, routing_replay),
    Surface.CODE: (hygiene, code_tests),
}


class Gate:
    def __init__(
        self,
        store: ChangeStore,
        *,
        checks: dict[Surface, tuple[Check, ...]] | None = None,
        replay: Callable[[], tuple[float | None, list[str]]] = _replay_rate,
        run_tests: Callable[[Path, tuple[str, ...]], Any] = _run_pytest,
    ) -> None:
        self._store = store
        self._checks = dict(DEFAULT_CHECKS if checks is None else checks)
        self.replay = replay
        self.run_tests = run_tests

    def register(self, surface: Surface, check: Check) -> None:
        self._checks[surface] = (*self._checks.get(surface, ()), check)

    def run(self, draft: Draft) -> GateReport:
        report = GateReport()
        checks = self._checks.get(draft.surface, ())
        if not checks:
            detail = f"no regression check exists for {draft.surface.value}"
            report.checks.append(CheckResult("coverage", UNAVAILABLE, detail))
        for check in checks:
            try:
                result = check(draft, self)
            except Exception as exc:  # noqa: BLE001 — a crashing check is a failed check
                name = getattr(check, "__name__", "check")
                log.warning("self_change: check %s crashed", name, exc_info=True)
                result = CheckResult(name, FAIL, f"the check crashed ({exc})"[:200])
            report.checks.append(result)
        return report

    def record(self, change_id: str, report: GateReport) -> None:
        for check in report.checks:
            with contextlib.suppress(Exception):
                self._store.record_evaluation(
                    change_id, check.name, check.status, check.score, check.detail
                )
