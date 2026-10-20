"""Issue intake: which projects are the person's own, and which issues become cases.

A project qualifies when it is in the Agentic IDE's library, is a git
repository whose ``origin`` is on GitHub, that repository is owned by the
person or by an organisation they administer, the person can administer or
maintain it, it is not archived, and it is not Dodaios' own source (that goes
through the normal branch, pull request and done-gate path). Other people's
repositories are never polled, let alone written to.

Only projects the person works on are polled: opened in the IDE lately, or
with their own commits among the recent ones. Each is asked for issues at most
every :data:`INTAKE_EVERY_MS`, triaged in Python (:mod:`.triage`), and a fit
issue becomes a ``Kind.CODE`` case through ``service.admit``. At most one new
case per pass: rarely and correctly, never noisily.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from loguru import logger

from ..records import Kind, State
from . import brief as brief_mod
from . import commands, gitcmd
from .brief import Brief
from .context import Context, signature
from .github import OWN_PERMISSIONS, Issue, Snapshot, Viewer
from .triage import triage

INTAKE_EVERY_MS: Final[int] = 30 * 60_000
#: A brief's keys are checked against the checkout at most this often.
BRIEF_EVERY_S: Final[float] = 30 * 60.0
VIEWER_TTL_MS: Final[int] = 6 * 3_600_000
#: A project opened in the IDE within this many days counts as worked on.
RECENT_DAYS: Final[int] = 45
MAX_NEW_CASES: Final[int] = 1


@dataclass(frozen=True, slots=True)
class OwnedProject:
    folder: str
    name: str
    repo: str
    brief: Brief


def repo_of(folder: str | Path) -> str:
    """The GitHub repository ``origin`` fetches from and pushes to (both must agree)."""
    from dodaios.agentic_ide.github_link import REPO_RE

    fetch = gitcmd.origin_repo(folder)
    if not fetch or gitcmd.origin_repo(folder, push=True).lower() != fetch.lower():
        return ""
    return fetch if REPO_RE.match(fetch) else ""


def is_dodaios_source(folder: str | Path, dodaios_root: Path | None) -> bool:
    root = Path(folder)
    if (root / "dodaios" / "self_build").is_dir():
        return True
    if dodaios_root is None:
        return False
    try:
        from dodaios.agentic_ide.git_ops import same_repository

        return bool(same_repository(root, dodaios_root))
    except Exception:  # noqa: BLE001 - unknown counts as "not Dodaios" only if the marker said so
        logger.opt(exception=True).debug("self-build code: repository comparison failed")
        return False


def _repo_root(folder: str) -> str:
    top = gitcmd.out(["rev-parse", "--show-toplevel"], folder)
    return str(Path(top)) if top else ""


async def viewer(ctx: Context) -> Viewer | None:
    cached = ctx._viewer
    stamp = int(time.time() * 1000)
    if cached is not None and stamp - cached[0] < VIEWER_TTL_MS:
        return cached[1]
    api = ctx.github()
    if api is None:
        return None
    who = await asyncio.to_thread(api.viewer)
    if not who.login:
        return None
    ctx._viewer = (stamp, who)
    return who


def _brief(ctx: Context, folder: str, repo: str) -> Brief:
    """The project's brief, its keys checked at most every :data:`BRIEF_EVERY_S`."""
    key = folder.lower()
    stored = brief_mod.load(ctx.store, folder)
    checked = ctx.brief_checked.get(key, 0.0)
    if stored is not None and stored.repo == repo and time.monotonic() - checked < BRIEF_EVERY_S:
        return stored
    brief, _rebuilt = brief_mod.refresh(ctx.store, folder, repo=repo)
    ctx.brief_checked[key] = time.monotonic()
    return brief


def owned_projects(ctx: Context, who: Viewer) -> list[OwnedProject]:
    """Blocking: git calls and brief refreshes for the person's own projects."""
    out: list[OwnedProject] = []
    seen: set[str] = set()
    cutoff = time.time() - RECENT_DAYS * 86_400
    for project in ctx.projects():
        if getattr(project, "scratch", False) or getattr(project, "archived", False):
            continue
        folder = _repo_root(str(getattr(project, "path", "") or ""))
        if not folder or folder.lower() in seen:
            continue
        seen.add(folder.lower())
        repo = repo_of(folder)
        if not repo or not who.owns(repo) or is_dodaios_source(folder, ctx.dodaios_root):
            continue
        brief = _brief(ctx, folder, repo)
        recent = float(getattr(project, "last_opened_at", 0) or 0) >= cutoff
        mine = bool((brief.parts.get("activity") or {}).get("person_active"))
        if not (recent or mine):
            continue
        out.append(
            OwnedProject(
                folder=folder, name=str(getattr(project, "name", "")), repo=repo, brief=brief
            )
        )
    return out


def offerable(records: list[Any]) -> bool:
    """May an issue be offered again? Only when every earlier case never ran."""
    from .builder import NOT_RUN

    return all(r.state == State.FAILED and r.note.startswith(NOT_RUN) for r in records)


def _github_part(snap: Snapshot) -> dict[str, Any]:
    return {
        "open_issues": len(snap.issues),
        "issues": [f"#{i.number} {i.title}" for i in snap.issues[:10]],
        "open_pulls": [f"#{p.number} {p.title}" for p in snap.pulls[:10]],
        "permission": snap.permission,
    }


def _lang(ctx: Context) -> str:
    """The person's interface language (the card is read there)."""
    ui = getattr(ctx.config(), "ui", None)
    return str(getattr(ui, "language", "") or "en")


def title(ctx: Context, issue: Issue, repo: str) -> str:
    from dodaios.i18n import t

    return t(
        "self_build.code.title",
        _lang(ctx),
        number=issue.number,
        repo=repo,
        title=issue.title.strip()[:120],
    )


def case(ctx: Context, issue: Issue, repo: str, signal: str, brief: Brief) -> str:
    from dodaios.i18n import t

    tests = " && ".join(commands.shown(c) for c in brief.test_commands) or "-"
    return t(
        "self_build.code.case",
        _lang(ctx),
        number=issue.number,
        repo=repo,
        signal=signal,
        tests=tests,
        url=issue.url,
    )


async def poll(ctx: Context, project: OwnedProject, who: Viewer, *, budget: int) -> int:
    """Triage one repository's issues; returns how many cases were opened."""
    from dodaios.agentic_ide.github_link import GitHubError

    api = ctx.github()
    if api is None:
        return 0
    store, ledger, repo = ctx.store, ctx.ledger, project.repo
    try:
        snap = await asyncio.to_thread(api.snapshot, repo)
    except GitHubError as exc:
        logger.info("self-build code: issues of {} unreadable: {}", repo, exc)
        return 0
    await asyncio.to_thread(store.set_poll, repo)
    await asyncio.to_thread(store.set_part, project.brief.project_key, "github", _github_part(snap))
    if snap.archived or snap.permission.upper() not in OWN_PERMISSIONS:
        return 0
    if snap.repo.lower() != repo.lower():
        logger.info(
            "self-build code: {} answers as {}; skipped until origin is updated", repo, snap.repo
        )
        return 0
    profile = await asyncio.to_thread(store.profile, repo)
    opened = 0
    for issue in snap.issues:
        if opened >= budget:
            break
        sig = signature(repo, issue.number)
        if not offerable(await asyncio.to_thread(ledger.ever_for, sig)):
            continue  # one build per issue: a closed or failed one is not retried
        prev = await asyncio.to_thread(store.issue, repo, issue.number)
        if prev and prev["updated_at"] == issue.updated_at and prev["verdict"] == "unfit":
            continue
        verdict = triage(
            issue,
            login=who.login,
            profile=profile,
            pulls=snap.pulls,
            has_tests=bool(project.brief.test_commands),
        )
        data = {**issue.to_json(), "folder": project.folder, "base": snap.default_branch}
        if not verdict.fit:
            await asyncio.to_thread(
                store.put_issue,
                repo,
                issue.number,
                updated_at=issue.updated_at,
                verdict="unfit",
                reason=verdict.reason,
                issue=data,
            )
            continue
        admission = ctx.service.admit(Kind.CODE, sig)
        await asyncio.to_thread(
            store.put_issue,
            repo,
            issue.number,
            updated_at=issue.updated_at,
            verdict="fit",
            reason=f"{verdict.signal}; {admission.reason}",
            issue=data,
        )
        if admission.start is None:
            logger.debug("self-build code: {} not opened: {}", sig, admission.reason)
            if admission.reason in ("off", "paused"):
                break
            continue
        await asyncio.to_thread(
            ledger.open_case,
            Kind.CODE,
            sig,
            title(ctx, issue, repo),
            case=case(ctx, issue, repo, verdict.signal, project.brief),
            evidence=[issue.url or sig],
            state=admission.start,
        )
        logger.info("self-build code: opened {} as {} ({})", sig, admission.start, verdict.signal)
        opened += 1
    return opened


async def intake(ctx: Context, projects: list[OwnedProject], who: Viewer) -> int:
    opened = 0
    stamp = int(time.time() * 1000)
    for project in projects:
        if opened >= MAX_NEW_CASES:
            break
        last = await asyncio.to_thread(ctx.store.last_poll, project.repo)
        if stamp - last < INTAKE_EVERY_MS:
            continue
        opened += await poll(ctx, project, who, budget=MAX_NEW_CASES - opened)
    return opened
