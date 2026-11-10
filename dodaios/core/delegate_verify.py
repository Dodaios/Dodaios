"""Independent checks of delegated work: the lead's "did it really happen" step.

A worker that reports "done" is a claim. These checks read the evidence the
work left behind (the repository's diff, the file on disk, the evidence refs of
a society result) and answer ``verified`` / ``unverified`` / ``failed``. They
only read: nothing is run, started or changed, and no model is asked.

``verified``    every check passed and the work shows proof it works
``unverified``  nothing contradicts the claim but nothing proves it either
``failed``      a check found the claim false (empty diff, missing file, dead ref)
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Literal

__all__ = ["Check", "DelegateRecord", "Verification", "verify_record"]

log = logging.getLogger(__name__)

Verdict = Literal["verified", "unverified", "failed"]

_MAX_ARTIFACT_BYTES = 16_000_000
_MAGIC: dict[str, bytes] = {
    ".png": b"\x89PNG",
    ".jpg": b"\xff\xd8\xff",
    ".jpeg": b"\xff\xd8\xff",
    ".gif": b"GIF8",
    ".pdf": b"%PDF",
}
_EVENT_REF = re.compile(r"^(?:event:)?[0-9a-f]{32}$|^event:\S+$", re.I)


@dataclass(frozen=True, slots=True)
class Check:
    """One check. ``ok`` is ``None`` when it could not be made."""

    name: str
    ok: bool | None
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"check": self.name, "ok": self.ok, "detail": self.detail}


@dataclass(slots=True)
class DelegateRecord:
    """What a job left behind, as far as the caller could resolve it."""

    job_id: str
    kind: Literal["coding", "artifact", "society"]
    #: Folder the coding work ran in.
    cwd: str = ""
    artifact_path: str = ""
    #: The ``evidence`` refs a society result listed.
    evidence: list[str] = field(default_factory=list)
    #: The test command the job recorded and its outcome (``passed`` / ``failed``).
    test_command: str = ""
    test_result: str = ""
    #: Resolves a society event ref; ``None`` when no board is reachable.
    event_exists: Callable[[str], bool] | None = None


@dataclass(slots=True)
class Verification:
    job_id: str
    kind: str
    verdict: Verdict
    summary: str
    checks: list[Check] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "kind": self.kind,
            "verdict": self.verdict,
            "summary": self.summary,
            "evidence": [c.to_dict() for c in self.checks],
        }


def _verdict(checks: list[Check], *, proven: bool) -> Verdict:
    if any(c.ok is False for c in checks):
        return "failed"
    if proven and checks and all(c.ok for c in checks):
        return "verified"
    return "unverified"


def _git(args: list[str], cwd: Path) -> str | None:
    from dodaios.agentic_ide.git_local import git_out

    return git_out(args, cwd)


def _check_coding(record: DelegateRecord) -> Verification:
    checks: list[Check] = []
    folder = Path(record.cwd) if record.cwd else None
    if folder is None or not folder.is_dir():
        checks.append(Check("workspace", None, "the folder the job ran in is not reachable"))
        return Verification(
            record.job_id, "coding", "unverified", "The job's folder cannot be read.", checks
        )
    stat = _git(["diff", "--stat", "HEAD"], folder)
    status = _git(["status", "--porcelain"], folder)
    if stat is None and status is None:
        checks.append(Check("git", None, "not a git repository or git is unavailable"))
        return Verification(
            record.job_id, "coding", "unverified", "The folder's changes cannot be read.", checks
        )
    ahead = (_git(["rev-list", "--count", "origin/main..HEAD"], folder) or "0").strip()
    untracked = [ln for ln in (status or "").splitlines() if ln.startswith("??")]
    has_ahead = ahead not in ("", "0")
    changed = bool((stat or "").strip() or untracked or has_ahead)
    parts: list[str] = []
    if (stat or "").strip():
        parts.append((stat or "").strip().splitlines()[-1])
    if untracked:
        parts.append(f"{len(untracked)} new file(s)")
    if has_ahead:
        parts.append(f"{ahead} commit(s) ahead of main")
    checks.append(
        Check("changes", changed, "; ".join(parts) if changed else "no diff, new file or commit")
    )
    tests_ok: bool | None = None
    if record.test_command and record.test_result:
        tests_ok = record.test_result.lower() in ("passed", "pass", "ok", "success")
        checks.append(Check("tests", tests_ok, f"{record.test_command}: {record.test_result}"))
    else:
        checks.append(Check("tests", None, "no test run was recorded for this job"))
    verdict = _verdict(checks, proven=tests_ok is True)
    summary = {
        "verified": "Changes exist and the recorded tests passed.",
        "unverified": "Changes exist, but nothing proves they work (no recorded passing test).",
        "failed": "The claim does not hold; see the failed check.",
    }[verdict]
    return Verification(record.job_id, "coding", verdict, summary, checks)


class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags = 0
        self.text = 0
        self.media = False
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags += 1
        if tag in ("script", "style"):
            self._skip += 1
        if tag in ("img", "svg", "canvas", "video", "iframe"):
            self.media = True

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.text += len(data.strip())


def _check_artifact(record: DelegateRecord) -> Verification:
    path = Path(record.artifact_path)
    checks: list[Check] = []
    if not path.is_file():
        checks.append(Check("exists", False, f"no file at {path}"))
        return Verification(record.job_id, "artifact", "failed", "The file does not exist.", checks)
    size = path.stat().st_size
    checks.append(Check("exists", True, f"{size} bytes"))
    if size == 0:
        checks.append(Check("not_empty", False, "the file is empty"))
        return Verification(record.job_id, "artifact", "failed", "The file is empty.", checks)
    suffix = path.suffix.lower()
    if size > _MAX_ARTIFACT_BYTES:
        checks.append(Check("renders", None, "too large to inspect"))
    elif suffix in (".html", ".htm"):
        page = _Page()
        try:
            page.feed(path.read_text(encoding="utf-8", errors="replace"))
            page.close()
            sane = page.tags > 0 and (page.text > 0 or page.media)
            checks.append(
                Check(
                    "renders",
                    sane,
                    f"{page.tags} elements, {page.text} characters of text"
                    if sane
                    else "the page has no visible content",
                )
            )
        except Exception as exc:  # noqa: BLE001 - an unparsable page is the finding
            log.info("delegate verify: %s does not parse: %s", path, exc)
            checks.append(Check("renders", False, f"the page does not parse: {exc}"))
    elif suffix == ".json":
        try:
            json.loads(path.read_text(encoding="utf-8"))
            checks.append(Check("renders", True, "valid JSON"))
        except ValueError as exc:
            log.info("delegate verify: %s is not valid JSON: %s", path, exc)
            checks.append(Check("renders", False, f"invalid JSON: {exc}"))
    elif suffix in _MAGIC:
        ok = path.read_bytes()[:8].startswith(_MAGIC[suffix])
        checks.append(Check("renders", ok, f"{suffix} header {'matches' if ok else 'is wrong'}"))
    elif suffix in (".md", ".txt", ".csv", ".svg", ".css", ".js", ".py"):
        checks.append(Check("renders", True, "non-empty text file"))
    else:
        checks.append(Check("renders", None, f"{suffix or 'this'} type is not inspected"))
    verdict = _verdict(checks, proven=True)
    summary = {
        "verified": "The file exists, is not empty and looks sound.",
        "unverified": "The file exists and is not empty; its content could not be judged.",
        "failed": "The file is missing, empty or broken.",
    }[verdict]
    return Verification(record.job_id, "artifact", verdict, summary, checks)


def _ref_check(ref: str, record: DelegateRecord) -> Check:
    ref = ref.strip()
    if re.match(r"^https?://", ref, re.I):
        return Check(ref, None, "web link: not fetched")
    if _EVENT_REF.match(ref):
        if record.event_exists is None:
            return Check(ref, None, "the board is not reachable")
        found = record.event_exists(ref.removeprefix("event:"))
        return Check(ref, found, "board event found" if found else "no such board event")
    candidate = Path(ref)
    if not candidate.is_absolute() and record.cwd:
        candidate = Path(record.cwd) / ref
    if candidate.exists():
        return Check(ref, True, "exists")
    return Check(ref, False, "does not exist")


def _check_society(record: DelegateRecord) -> Verification:
    if not record.evidence:
        return Verification(
            record.job_id,
            "society",
            "unverified",
            "The result lists no evidence to check.",
            [Check("evidence", None, "no evidence refs listed")],
        )
    checks = [_ref_check(str(ref), record) for ref in record.evidence]
    verdict = _verdict(checks, proven=True)
    dead = [c.name for c in checks if c.ok is False]
    summary = {
        "verified": f"All {len(checks)} evidence ref(s) exist.",
        "unverified": "No evidence ref is wrong, but some could not be checked.",
        "failed": "Evidence ref(s) do not exist: " + ", ".join(dead[:5]),
    }[verdict]
    return Verification(record.job_id, "society", verdict, summary, checks)


def verify_record(record: DelegateRecord) -> Verification:
    """Run the checks for the job's kind. Blocking: call it off the event loop."""
    if record.kind == "coding":
        return _check_coding(record)
    if record.kind == "artifact":
        return _check_artifact(record)
    return _check_society(record)
