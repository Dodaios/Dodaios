#!/usr/bin/env python3
"""Merge freeze: one open pull request may hold main still for a while.

A change that rewrites much of the tree (a package move, a mass rename) needs
main to stand still until it lands, or every merge in between makes it
conflict and restarts its CI. Its author puts the label ``merge-freeze`` on
that pull request. While the label is younger than ``FREEZE_HOURS``:

- ``scripts/agent_done_gate.py`` tells other agents to wait (verdict WAIT);
- ``scripts/agent_land.py`` does not request auto-merge for other PRs;
- the merge train does not enqueue other PRs.

An older label no longer counts, so a session that died cannot hold main
forever; the merge train comments on such a pull request once.

stdlib only. ``gh_json`` is any callable that runs ``gh <args>`` and returns
the parsed JSON (or ``None`` on failure), so tests pass a fake.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

FREEZE_LABEL = "merge-freeze"
FREEZE_HOURS = 2.0

GhJson = Callable[[list[str]], object]


@dataclass(frozen=True)
class Freeze:
    number: int
    title: str
    since: datetime | None
    age_hours: float
    expired: bool


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def labelled_at(events: object, label: str = FREEZE_LABEL) -> datetime | None:
    """When ``label`` was last added, from a ``/issues/<n>/events`` listing."""
    if not isinstance(events, list):
        return None
    stamps = [
        parse_time(event.get("created_at"))
        for event in events
        if isinstance(event, dict)
        and event.get("event") == "labeled"
        and (event.get("label") or {}).get("name") == label
    ]
    stamps = [stamp for stamp in stamps if stamp is not None]
    return max(stamps) if stamps else None


def issue_events(repo: str, number: int, gh_json: GhJson, *, pages: int = 10) -> list[dict]:
    """Every event of an issue or pull request, oldest first, across pages.

    One page holds 100 events; a busy pull request has more, and the label
    event that matters is usually on the last page.
    """
    found: list[dict] = []
    for page in range(1, pages + 1):
        batch = gh_json(["api", f"repos/{repo}/issues/{number}/events?per_page=100&page={page}"])
        if not isinstance(batch, list):
            break
        found.extend(event for event in batch if isinstance(event, dict))
        if len(batch) < 100:
            break
    return found


def freezes(
    repo: str,
    gh_json: GhJson,
    *,
    now: datetime | None = None,
    hours: float = FREEZE_HOURS,
) -> list[Freeze]:
    """Every open pull request labelled ``merge-freeze``, oldest label first."""
    now = now or datetime.now(UTC)
    listed = gh_json(
        [
            "pr",
            "list",
            "-R",
            repo,
            "--state",
            "open",
            "--label",
            FREEZE_LABEL,
            "--json",
            "number,title",
        ]
    )
    found: list[Freeze] = []
    for pr in listed if isinstance(listed, list) else []:
        number = int(pr.get("number") or 0)
        if not number:
            continue
        since = labelled_at(issue_events(repo, number, gh_json))
        # Unknown label time counts as expired: a freeze must never hold main forever.
        age = (now - since).total_seconds() / 3600 if since else hours
        found.append(Freeze(number, str(pr.get("title") or ""), since, age, age >= hours))
    return sorted(found, key=lambda freeze: -freeze.age_hours)


def active_freeze(
    repo: str,
    gh_json: GhJson,
    *,
    now: datetime | None = None,
    hours: float = FREEZE_HOURS,
    exempt: int | None = None,
) -> Freeze | None:
    """The freeze that holds ``exempt`` back right now, if any.

    A pull request that holds a freeze itself is held by none: two freezing
    pull requests must not lock each other out.
    """
    live = [freeze for freeze in freezes(repo, gh_json, now=now, hours=hours) if not freeze.expired]
    if exempt is not None and any(freeze.number == exempt for freeze in live):
        return None
    return live[0] if live else None


def describe(freeze: Freeze) -> str:
    left = max(0.0, FREEZE_HOURS - freeze.age_hours)
    return (
        f"merge freeze held by PR #{freeze.number} ({freeze.title}); "
        f"it lapses in {left * 60:.0f} min at the latest"
    )


def gh_json_cli(args: list[str]) -> object:
    """Run ``gh`` and parse its JSON output; ``None`` when it fails."""
    try:
        out = subprocess.run(  # noqa: S603
            ["gh", *args],  # noqa: S607
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    try:
        return json.loads(out.stdout or "null")
    except ValueError:
        return None
