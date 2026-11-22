"""The follow-up orders the app writes to a coding thread after checking its output.

Two templates, filled only with what the checks found. They are text for the
agent, so they are English, and they are constants of the code: nothing a
prompt or a policy can rewrite. They carry no round number and no budget, so
the same finding always yields the same order.

Every order ends by asking for one closing line (``RESULT: ...``). That line is
a hint for stopping early. Whether the work is right is decided by the next
check, never by what the agent says.
"""

from __future__ import annotations

from typing import Any, Final

__all__ = ["AUTHOR_ID", "AUTHOR_NAME", "T1", "T2", "failing_checks", "weakened_checks"]

#: Who the thread shows as the writer of a follow-up order.
AUTHOR_ID: Final[str] = "output-gate"
AUTHOR_NAME: Final[str] = "Output check"

T1: Final[str] = "T1"
T2: Final[str] = "T2"

_SHOWN: Final[int] = 12
_EXCERPT_MAX: Final[int] = 300

_CLOSING: Final[str] = (
    "End your answer with exactly one of these lines:\n"
    "RESULT: fixed\n"
    "RESULT: cannot-fix: <why>\n"
    "RESULT: needs-decision: <the question the person has to answer>"
)


def failing_checks(names: list[str], *, where: str = "", pr: int = 0) -> str:
    """T1: the repository's checks fail on the work the turn left."""
    listed = "\n".join(f"- {name}" for name in names[:_SHOWN]) or "- (GitHub names none)"
    more = f"\n- and {len(names) - _SHOWN} more" if len(names) > _SHOWN else ""
    logs = (
        f"Read their logs first (`gh pr checks {pr}`, then `gh run view <id> --log-failed`)."
        if pr
        else "Read their logs first (`gh run list`, then `gh run view <id> --log-failed`)."
    )
    return (
        "The app checked the work you left. The repository's checks fail on it"
        + (f" ({where})" if where else "")
        + f":\n{listed}{more}\n\n"
        f"{logs} Fix only what makes these checks fail. Do not skip, delete or weaken a "
        "test or a check, and do not change what the checks run. If one fails for a reason "
        "that is not in your change, say so instead of working around it.\n\n" + _CLOSING
    )


def weakened_checks(findings: list[dict[str, Any]], *, base: str = "") -> str:
    """T2: the change weakens the repository's checks or touches an off-limits path."""
    lines: list[str] = []
    for finding in findings[:_SHOWN]:
        line = finding.get("line")
        at = f"{finding.get('path')}:{line}" if line else str(finding.get("path") or "")
        lines.append(f"- {finding.get('rule')} {at}: {finding.get('note')}")
        excerpt = str(finding.get("excerpt") or "").strip()
        if excerpt:
            lines.append("    " + excerpt[:_EXCERPT_MAX].replace("\n", "\n    "))
    more = f"\n- and {len(findings) - _SHOWN} more" if len(findings) > _SHOWN else ""
    start = f" (`{base[:12]}`)" if base else ""
    return (
        "The app checked the work you left. The change weakens the repository's checks or "
        "touches a path that is off limits:\n" + "\n".join(lines) + more + "\n\n"
        f"Restore these to what they were in the commit you started on{start}, and solve "
        "the task without them. If a test is wrong for the behaviour that was asked for, do "
        "not change it: say which test and why, and let the person decide.\n\n" + _CLOSING
    )
