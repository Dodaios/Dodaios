"""Close the issues that a merged fix already solved.

GitHub closes an issue on merge only when the pull request body says
``Fixes #<n>``. A fix whose title names the issue, ``fix(piper): ... (#1698)``,
left the issue open, and the person who filed it kept waiting for an answer
that had shipped. This script is the safety net behind the closing keywords
(.github/workflows/close-fixed-issues.yml):

``pr <number>``
    A merged pull request whose title is a fix (``fix:`` / ``fix(scope):``)
    or says ``fixes #<n>`` closes the open issues its title names. An issue
    the body only refers to (``Refs #<n>``) stays open.

``reports``
    A nightly review report lists its findings as sub-issues under a
    "Verified findings" heading. Once every finding listed there is closed,
    the report is closed too.

Every write goes through ``gh``. ``--dry-run`` prints the commands instead.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from typing import Any

Runner = Callable[[Sequence[str]], str]

# A conventional-commit fix type: "fix: ...", "fix(scope): ...", "fix!: ...".
_FIX_TITLE_RE = re.compile(r"^\s*fix(\([^)]*\))?!?:", re.IGNORECASE)
_ISSUE_REF_RE = re.compile(r"#(\d+)\b")
_CLOSING_RE = re.compile(
    r"\b(?:fix(?:es|ed)?|close[sd]?|resolve[sd]?)\s*:?\s+#(\d+)\b", re.IGNORECASE
)
_REFERS_RE = re.compile(
    r"\b(?:refs?|references|related to|part of|see)\s*:?\s+#(\d+)\b", re.IGNORECASE
)
_HEADING_RE = re.compile(r"^\s*#{1,6}\s")
_FINDINGS_HEADING_RE = re.compile(r"^\s*#{1,6}\s.*verified findings", re.IGNORECASE)
# A finding is a list item that starts with its issue: "- #1390: ...".
_FINDING_ITEM_RE = re.compile(r"^\s*[-*]\s+#(\d+)\b")
# Issue lookups per pull request; a title never names more.
_MAX_TITLE_ISSUES = 5


def gh(args: Sequence[str]) -> str:
    return subprocess.run(
        ["gh", *args], check=True, capture_output=True, text=True, encoding="utf-8"
    ).stdout


def _numbers(pattern: re.Pattern[str], text: str) -> list[int]:
    seen: list[int] = []
    for match in pattern.finditer(text or ""):
        number = int(match.group(1))
        if number not in seen:
            seen.append(number)
    return seen


def issues_fixed_by_title(title: str, body: str) -> list[int]:
    """Issues a merged pull request's title says it fixes."""
    referred = set(_numbers(_REFERS_RE, body)) | set(_numbers(_REFERS_RE, title))
    if _FIX_TITLE_RE.match(title or ""):
        named = _numbers(_ISSUE_REF_RE, title)
    else:
        named = _numbers(_CLOSING_RE, title)
    return [n for n in named if n not in referred][:_MAX_TITLE_ISSUES]


def report_findings(body: str) -> list[int]:
    """Sub-issues listed under a report's "Verified findings" heading."""
    findings: list[int] = []
    inside = False
    for line in (body or "").splitlines():
        if _FINDINGS_HEADING_RE.match(line):
            inside = True
            continue
        if inside and _HEADING_RE.match(line):
            inside = False
        if inside:
            match = _FINDING_ITEM_RE.match(line)
            if match and int(match.group(1)) not in findings:
                findings.append(int(match.group(1)))
    return findings


class Closer:
    def __init__(self, repo: str, run: Runner = gh, dry_run: bool = False) -> None:
        self.repo = repo
        self.run = run
        self.dry_run = dry_run
        self._issues: dict[int, dict[str, Any]] = {}

    def issue(self, number: int) -> dict[str, Any]:
        if number not in self._issues:
            raw = self.run(["api", f"repos/{self.repo}/issues/{number}"])
            self._issues[number] = json.loads(raw)
        return self._issues[number]

    def is_open_issue(self, number: int) -> bool:
        """True for an open issue; False for a pull request or a closed issue."""
        try:
            found = self.issue(number)
        except (subprocess.CalledProcessError, json.JSONDecodeError):
            return False
        return found.get("state") == "open" and "pull_request" not in found

    def close(self, number: int, comment: str) -> None:
        args = ["issue", "close", str(number), "--repo", self.repo, "--reason", "completed"]
        args += ["--comment", comment]
        if self.dry_run:
            print("dry run, not executed: gh " + " ".join(args[:7]))
        else:
            self.run(args)
            print(f"closed #{number}")
        self._issues.setdefault(number, {})["state"] = "closed"

    def close_fixed_by_pr(self, number: int) -> list[int]:
        pr = json.loads(self.run(["api", f"repos/{self.repo}/pulls/{number}"]))
        if not pr.get("merged_at"):
            print(f"PR #{number} is not merged: nothing to close.")
            return []
        base = pr.get("base") or {}
        if base.get("ref") != (base.get("repo") or {}).get("default_branch", "main"):
            print(f"PR #{number} did not merge into the default branch: nothing to close.")
            return []
        closed: list[int] = []
        for issue in issues_fixed_by_title(pr.get("title") or "", pr.get("body") or ""):
            if issue == number or not self.is_open_issue(issue):
                continue
            self.close(
                issue,
                f"Fixed by #{number}, which is merged into main. "
                "The fix ships with the next release. If the problem is still there "
                "on that release, please reopen this issue.",
            )
            closed.append(issue)
        if not closed:
            print(f"PR #{number} names no open issue it fixes.")
        return closed

    def close_finished_reports(self) -> list[int]:
        found = json.loads(
            self.run(
                [
                    "issue",
                    "list",
                    "--repo",
                    self.repo,
                    "--state",
                    "open",
                    "--limit",
                    "100",
                    "--search",
                    '"Verified findings" in:body',
                    "--json",
                    "number,body",
                ]
            )
        )
        closed: list[int] = []
        for report in found:
            findings = report_findings(report.get("body") or "")
            findings = [n for n in findings if n != report["number"]]
            if not findings:
                continue
            if any(self.is_open_issue(n) for n in findings):
                continue
            listed = ", ".join(f"#{n}" for n in findings)
            self.close(report["number"], f"Every finding of this report is closed: {listed}.")
            closed.append(report["number"])
        return closed


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--dry-run", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    pr = sub.add_parser("pr", help="close the open issues a merged fix names in its title")
    pr.add_argument("number", type=int)
    sub.add_parser("reports", help="close nightly reports whose findings are all closed")
    args = parser.parse_args(argv)
    if not args.repo:
        parser.error("--repo (or GITHUB_REPOSITORY) is required")
    closer = Closer(args.repo, dry_run=args.dry_run)
    if args.command == "pr":
        closer.close_fixed_by_pr(args.number)
    closer.close_finished_reports()
    return 0


if __name__ == "__main__":
    sys.exit(main())
