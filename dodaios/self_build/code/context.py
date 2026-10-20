"""What every stage of the code builder works with, in one place (and one test seam)."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from ..records import BuildRecord
from .github import GitHub
from .runner import Runner
from .seat import Seat
from .store import CodeStore

#: Every branch the loop creates starts with this, and undo removes nothing else.
BRANCH_PREFIX: Final[str] = "dodaios/"
_SIGNATURE: Final[re.Pattern[str]] = re.compile(
    r"^code:(?P<repo>[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100})#(?P<number>\d+)$"
)


def signature(repo: str, number: int) -> str:
    return f"code:{repo}#{int(number)}"


def parse_signature(sig: str) -> tuple[str, int] | None:
    match = _SIGNATURE.match(sig.strip())
    if match is None:
        return None
    return match.group("repo"), int(match.group("number"))


def branch_name(number: int, title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40].strip("-")
    return f"{BRANCH_PREFIX}issue-{int(number)}" + (f"-{slug}" if slug else "")


def has_pull(record: Any) -> bool:
    """Has the build opened its pull request? (``artefact.stage == "pull_request"``)"""
    return record.artefact.get("stage") == "pull_request"


def land_repos(config: Any) -> frozenset[str]:
    """Repositories the person opted in to "land it" (merge after green CI)."""
    section = getattr(config, "self_build", None)
    repos = getattr(section, "code_land_repos", None) or []
    return frozenset(str(r).strip().lower() for r in repos if str(r).strip())


@dataclass
class Context:
    service: Any  # dodaios.self_build.service.SelfBuild
    store: CodeStore
    github: Callable[[], GitHub | None]
    runner: Runner
    #: The subscription seat for a coding run, or (None, why not).
    seat: Callable[[], Awaitable[tuple[Seat | None, str]]]
    idle: Callable[[], bool]
    #: The person's projects: objects with ``path``, ``name``, ``last_opened_at``.
    projects: Callable[[], list[Any]]
    #: The one model call before a run (``planner.plan``).
    plan: Callable[..., Awaitable[Any]] | None = None
    run_timeout_s: float = 45 * 60.0
    dodaios_root: Path | None = None
    _viewer: tuple[int, Any] | None = field(default=None, repr=False)
    #: Builds an undo asked to stop; the build stops at its next step.
    stopping: set[str] = field(default_factory=set)
    #: When each project's brief was last checked against its checkout.
    brief_checked: dict[str, float] = field(default_factory=dict)

    @property
    def ledger(self) -> Any:
        return self.service.ledger

    def config(self) -> Any:
        return self.service.config()

    def still(self, record: BuildRecord, *states: Any) -> bool:
        """Is the record still in one of ``states``? (Undo or pause may have moved it.)"""
        current = self.ledger.get(record.id)
        return current is not None and current.state in states
