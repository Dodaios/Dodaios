"""The planner-and-builder mode of a team thread.

One member owns a living plan, one builds it a step at a time, the others
review. The coordinator (``engine.TeamThreads``) runs it as three phases:

    planning  the planner writes a plan version, the plan reviewers agree or object
    steps     the builder builds the first open step, the step reviewers check it
              against its ``done_when``; changes go back to the builder
    final     every member but the builder reviews the whole change

The plan is versioned: a builder that is blocked, or that asks for a change of
the plan, sends the planner a revision request, and the revised plan is
reviewed before building goes on. An accepted step keeps its status in the
next version unless the planner renames it or reopens it by number.

Everything is derived from the filed entries and the thread's ``work`` record,
so the mode pauses, resumes and survives a restart exactly like the peers.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Final

from . import plan_prompts
from .port import TurnResult
from .signals import parse_plan, parse_review, parse_step, parse_vote

if TYPE_CHECKING:
    from collections.abc import Callable

    from .port import TurnPort
    from .store import TeamThreadStore
    from .workspace import GitWorkspace

__all__ = ["PlannedWork", "default_roles", "plan_issues"]

_MAX_TEXT: Final[int] = 60_000


def default_roles(count: int) -> list[str]:
    """Member 1 plans, member 2 builds, every further member reviews."""
    return ["planner", "builder", *(["reviewer"] * max(0, count - 2))][:count]


def _key(title: str) -> str:
    return " ".join(str(title or "").lower().split())


def _carry(
    current: list[dict[str, Any]] | None, steps: list[dict[str, Any]], reopen: list[int]
) -> list[int]:
    """Steps of a new version that keep the "accepted" of the version they replace.

    A step is the same step when its title is; the planner reopens one by number.
    """
    pool: dict[str, list[int]] = {}
    for number, step in enumerate(current or [], start=1):
        if step.get("status") == "accepted" and number not in reopen:
            pool.setdefault(_key(step.get("title", "")), []).append(number)
    carried = []
    for number, step in enumerate(steps, start=1):
        if pool.get(_key(step.get("title", ""))):
            pool[_key(step["title"])].pop(0)
            carried.append(number)
    return carried


class PlannedWork:
    """The phases of the planner-and-builder mode, mixed into ``TeamThreads``."""

    if TYPE_CHECKING:  # provided by TeamThreads
        _store: TeamThreadStore
        _port: TurnPort
        _workspace: GitWorkspace
        _active: Callable[..., list[dict[str, Any]]]
        _work: Callable[..., dict[str, Any]]
        _notice: Callable[..., None]
        _halt: Callable[..., None]
        _batch: Callable[..., Any]
        _round: Callable[..., list[dict[str, Any]]]
        _change: Callable[..., Any]
        _change_summary: Callable[..., Any]
        _finish: Callable[..., None]

    # ------------------------------------------------------------ roles

    def _roles(self, team_id: str) -> dict[str, str]:
        return dict(self._work(team_id).get("roles") or {})

    def _lineup(self, team_id: str) -> list[tuple[str, str]]:
        roles = self._roles(team_id)
        return [(m["name"], roles.get(m["member_id"], "reviewer")) for m in self._active(team_id)]

    def _holder(self, team: dict[str, Any], role: str) -> dict[str, Any]:
        """The member that plans or builds; a reviewer takes the role over when it left."""
        team_id = team["team_id"]
        active = self._active(team_id)
        roles = self._roles(team_id)
        for member in active:
            if roles.get(member["member_id"]) == role:
                return member
        reviewers = [m for m in active if roles.get(m["member_id"]) not in ("planner", "builder")]
        if len(active) < 2 or not reviewers:
            # Nobody may plan and build at once: then nobody else checks the work.
            self._halt(team, "failed", "not_enough_members")
        successor = reviewers[0]
        roles[successor["member_id"]] = role
        work = self._work(team_id)
        work["roles"] = roles
        if role == "builder":
            work["builder"] = successor["member_id"]
        self._store.update(team_id, work=work)
        self._notice(
            team_id,
            team["phase"],
            "role_changed",
            {"member_id": successor["member_id"], "role": role},
        )
        return successor

    def _reviewers(self, team_id: str, *, fallback: str) -> list[dict[str, Any]]:
        """The members with the reviewer role, or the ``fallback`` role holder without one."""
        roles = self._roles(team_id)
        active = self._active(team_id)
        reviewers = [m for m in active if roles.get(m["member_id"]) == "reviewer"]
        return reviewers or [m for m in active if roles.get(m["member_id"]) == fallback]

    # ------------------------------------------------------------ the plan

    def _versions(
        self, team_id: str, entries: list[dict[str, Any]] | None = None
    ) -> list[dict[str, Any]]:
        """Every readable plan version, oldest first."""
        return [
            e
            for e in (self._store.entries(team_id) if entries is None else entries)
            if e["kind"] == "plan_version" and e["payload"].get("valid")
        ]

    def _adopted(self, team_id: str) -> dict[str, Any] | None:
        seq = int(self._work(team_id).get("plan_seq") or 0)
        return next((e for e in self._versions(team_id) if e["seq"] == seq), None) if seq else None

    @staticmethod
    def _checklist(plan: dict[str, Any], accepted: set[int]) -> list[dict[str, Any]]:
        return [
            {**step, "status": "accepted" if number in accepted else "open"}
            for number, step in enumerate(plan["payload"].get("steps") or [], start=1)
        ]

    def _current_checklist(self, team_id: str) -> list[dict[str, Any]] | None:
        plan = self._adopted(team_id)
        if plan is None:
            return None
        return self._checklist(plan, set(self._work(team_id).get("accepted") or []))

    def _plan_votes(self, team_id: str, plan: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            vote
            for vote in self._round(team_id, "plan_review", int(plan["round"]))
            if vote["payload"].get("plan_seq") == plan["seq"]
        ]

    def _step_entries(
        self,
        team_id: str,
        kind: str,
        version: int,
        number: int,
        round_no: int | None = None,
        *,
        entries: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        return [
            e
            for e in (self._store.entries(team_id) if entries is None else entries)
            if e["kind"] == kind
            and e["payload"].get("version") == version
            and e["payload"].get("number") == number
            and (round_no is None or e["round"] == round_no)
        ]

    # ------------------------------------------------------------ planning

    async def _phase_planning(self, team: dict[str, Any]) -> None:
        team_id = team["team_id"]
        round_no = int(team["work"].get("plan_round", 1))
        planner = self._holder(team, "planner")
        ids = {m["member_id"] for m in self._active(team_id)}
        filed = self._round(team_id, "plan_version", round_no)
        valid = [e for e in filed if e["payload"].get("valid") and e["author"] in ids]
        if not valid:
            await self._write_plan(team, planner, round_no, filed)
            return  # The loop comes back with the plan (or asks again).
        plan = valid[-1]
        voted = {v["author"] for v in self._plan_votes(team_id, plan)}
        reviewers = [
            m
            for m in self._reviewers(team_id, fallback="builder")
            if m["member_id"] != plan["author"]
        ]
        todo = [m for m in reviewers if m["member_id"] not in voted]
        lineup = self._lineup(team_id)
        names = {m["member_id"]: m["name"] for m in self._store.members(team_id)}
        revision = self._work(team_id).get("revision")
        steps = self._checklist(plan, set(plan["payload"].get("carried") or []))

        def record(member: dict[str, Any], result: TurnResult) -> dict[str, Any]:
            verdict = parse_vote(result.text)
            return {
                "text": verdict.text[:_MAX_TEXT],
                "agree": verdict.positive,
                "stated": verdict.stated,
                "objections": list(verdict.objections),
                "plan_seq": plan["seq"],
                "version": plan["payload"].get("version"),
            }

        await self._batch(
            team,
            todo,
            kind="plan_review",
            round_no=round_no,
            prompt=lambda m, notes: plan_prompts.review_plan(
                name=m["name"],
                team=lineup,
                cwd=team["cwd"],
                task=team["task"],
                planner=names.get(plan["author"], plan["author"]),
                steps=steps,
                revision=revision,
                notes=notes,
            ),
            record=record,
            guard=True,
        )
        ids = {m["member_id"] for m in self._active(team_id)}
        if plan["author"] not in ids:
            return  # The planner left while the others read: its successor writes again.
        votes = [v for v in self._plan_votes(team_id, plan) if v["author"] in ids]
        against = [v for v in votes if not v["payload"].get("agree")]
        if votes and not against:
            self._adopt_plan(team_id, plan, by_user=False)
            return
        if not votes:
            if not todo:
                raise RuntimeError("nobody is left to review the plan")
            return  # Its reviewers left; the loop asks the ones that are there.
        work = self._work(team_id)
        base = int(work.get("plan_base", 1))
        limits = self._store.get(team_id)["limits"]  # type: ignore[index]
        if round_no - base + 1 >= int(limits["plan_rounds"]):
            self._halt(
                team,
                "needs_input",
                "plan_disagreement",
                summary={
                    "rounds": round_no - base + 1,
                    "plan_seq": plan["seq"],
                    "plan_by": plan["author"],
                    "version": plan["payload"].get("version"),
                    "open": [
                        {
                            "member_id": v["author"],
                            "name": names.get(v["author"], v["author"]),
                            "items": list(v["payload"].get("objections") or []),
                        }
                        for v in against
                    ],
                },
            )
        work["plan_round"] = round_no + 1
        self._store.update(team_id, work=work)

    async def _write_plan(
        self,
        team: dict[str, Any],
        planner: dict[str, Any],
        round_no: int,
        filed: list[dict[str, Any]],
    ) -> None:
        team_id = team["team_id"]
        work = self._work(team_id)
        retry_from = int(work.get("plan_retry_from", 0))
        unreadable = [
            e
            for e in filed
            if e["seq"] > retry_from
            and e["author"] == planner["member_id"]
            and not e["payload"].get("valid")
        ]
        if len(unreadable) >= 2:
            # Asked once more and still no plan: never guess one out of the prose.
            self._halt(
                team,
                "needs_input",
                "plan_unreadable",
                note=str(unreadable[-1]["payload"].get("error") or ""),
            )
        current = self._current_checklist(team_id)
        revision = work.get("revision")
        base = int(work.get("plan_base", 1))
        names = {m["member_id"]: m["name"] for m in self._store.members(team_id)}
        previous = next(
            (e for e in reversed(self._versions(team_id)) if base <= int(e["round"]) < round_no),
            None,
        )
        objections: dict[str, list[str]] = {}
        if previous is not None:
            for vote in self._plan_votes(team_id, previous):
                if not vote["payload"].get("agree"):
                    objections[names.get(vote["author"], vote["author"])] = list(
                        vote["payload"].get("objections") or []
                    )
        lineup = self._lineup(team_id)

        def record(member: dict[str, Any], result: TurnResult) -> dict[str, Any]:
            reply = parse_plan(result.text)
            payload: dict[str, Any] = {
                "text": reply.text[:_MAX_TEXT],
                "valid": reply.valid,
                "error": reply.error,
            }
            if reply.valid:
                steps = [step.to_dict() for step in reply.steps]
                payload.update(
                    steps=steps,
                    reopen=list(reply.reopen),
                    carried=_carry(current, steps, list(reply.reopen)),
                    version=len(self._versions(team_id)) + 1,
                )
            return payload

        await self._batch(
            team,
            [planner],
            kind="plan_version",
            round_no=round_no,
            prompt=lambda m, notes: plan_prompts.write_plan(
                name=m["name"],
                team=lineup,
                cwd=team["cwd"],
                task=team["task"],
                current=current,
                previous=(
                    self._checklist(previous, set(previous["payload"].get("carried") or []))
                    if previous is not None
                    else None
                ),
                objections=objections,
                revision=revision if current is not None else None,
                unreadable=str(unreadable[-1]["payload"].get("error") or "") if unreadable else "",
                notes=notes,
            ),
            record=record,
            guard=True,
        )

    def _adopt_plan(self, team_id: str, plan: dict[str, Any], *, by_user: bool) -> None:
        work = self._work(team_id)
        base = int(work.get("plan_base", 1))
        current = self._current_checklist(team_id) or []
        done = {_key(step["title"]) for step in current if step["status"] == "accepted"}
        # An open step keeps the tree it started from, so its review still sees the
        # partial work of a blocked try; a reopened step starts from the tree as it is.
        work["step_base"] = {
            key: tree for key, tree in dict(work.get("step_base") or {}).items() if key not in done
        }
        work["plan_seq"] = plan["seq"]
        work["version"] = int(plan["payload"].get("version") or 1)
        work["accepted"] = list(plan["payload"].get("carried") or [])
        work.pop("revision", None)
        work.pop("step", None)
        work["step_round"] = 1
        self._store.update(team_id, work=work, phase="steps")
        self._notice(
            team_id,
            "planning",
            "plan_version_accepted_by_user" if by_user else "plan_version_agreed",
            {
                "rounds": int(plan["round"]) - base + 1,
                "by": plan["author"],
                "version": work["version"],
                "count": len(plan["payload"].get("steps") or []),
            },
        )

    def _start_revision(
        self, team: dict[str, Any], request: dict[str, Any], work: dict[str, Any] | None = None
    ) -> None:
        """Building waits; the planner writes the next plan version.

        ``work`` carries changes that must land in the same write (an accepted step).
        """
        team_id = team["team_id"]
        work = dict(work) if work is not None else self._work(team_id)
        work["revision"] = request
        work["plan_round"] = int(work.get("plan_round", 1)) + 1
        work["plan_base"] = work["plan_round"]
        work.pop("plan_retry_from", None)
        self._store.update(team_id, work=work, phase="planning")
        self._notice(
            team_id,
            "steps",
            "plan_revision",
            {
                "member_id": request.get("by", ""),
                "number": request.get("step", 0),
                "status": request.get("status", ""),
                "note": request.get("note", ""),
            },
        )

    # ------------------------------------------------------------ steps

    async def _phase_steps(self, team: dict[str, Any]) -> None:
        team_id = team["team_id"]
        plan = self._adopted(team_id)
        if plan is None:
            raise RuntimeError("the agreed plan is missing")
        version = int(plan["payload"].get("version") or 1)
        work = self._work(team_id)
        accepted = set(work.get("accepted") or [])
        steps = self._checklist(plan, accepted)
        pending = [n for n in range(1, len(steps) + 1) if n not in accepted]
        if not pending:
            work["final_round"] = 1
            self._store.update(team_id, work=work, phase="final")
            self._notice(team_id, "steps", "steps_done", {"count": len(steps)})
            return
        number = pending[0]
        if int(work.get("step") or 0) != number:
            work["step"] = number
            work["step_round"] = 1
            self._store.update(team_id, work=work)
        round_no = int(work.get("step_round") or 1)
        step = steps[number - 1]
        builder = self._holder(team, "builder")
        lineup = self._lineup(team_id)
        names = {m["member_id"]: m["name"] for m in self._store.members(team_id)}
        bases = dict(work.get("step_base") or {})

        if not self._step_entries(team_id, "step_build", version, number, round_no):
            if not work.get("baseline") or _key(step["title"]) not in bases:
                head = await asyncio.to_thread(self._workspace.snapshot, team["cwd"]) or ""
                work = self._work(team_id)
                if "baseline" not in work:
                    work["baseline"] = head
                    if not head:
                        self._notice(team_id, "steps", "no_git")
                bases = dict(work.get("step_base") or {})
                bases.setdefault(_key(step["title"]), head)
                work["step_base"] = bases
                self._store.update(team_id, work=work)
            base_tree = str(bases.get(_key(step["title"])) or "")
            findings: dict[str, list[dict[str, str]]] = {}
            if round_no > 1:
                for review in self._step_entries(
                    team_id, "step_review", version, number, round_no - 1
                ):
                    if not review["payload"].get("approve"):
                        findings[names.get(review["author"], review["author"])] = list(
                            review["payload"].get("findings") or []
                        )

            async def built(member: dict[str, Any], result: TurnResult) -> dict[str, Any]:
                report = parse_step(result.text)
                return {
                    "text": report.text[:_MAX_TEXT],
                    "version": version,
                    "number": number,
                    "title": step["title"],
                    "status": report.status,
                    "stated": report.stated,
                    "note": report.note,
                    "plan_change": report.plan_change,
                    **await self._change_summary(team["cwd"], base_tree),
                }

            await self._batch(
                team,
                [builder],
                kind="step_build",
                round_no=round_no,
                label=f"Team thread: build step {number} of {len(steps)}",
                prompt=lambda m, notes: plan_prompts.build_step(
                    name=m["name"],
                    team=lineup,
                    cwd=team["cwd"],
                    task=team["task"],
                    steps=steps,
                    number=number,
                    findings=findings,
                    notes=notes,
                ),
                record=built,
            )
            if not self._step_entries(team_id, "step_build", version, number, round_no):
                return  # The builder left; the loop seats another one.

        build = self._step_entries(team_id, "step_build", version, number, round_no)[-1]
        if build["payload"].get("status") == "blocked":
            self._start_revision(
                team,
                {
                    "step": number,
                    "title": step["title"],
                    "status": "blocked",
                    "note": build["payload"].get("note", ""),
                    "plan_change": build["payload"].get("plan_change", ""),
                    "by": build["author"],
                },
            )
            return

        reviewed = {
            r["author"]
            for r in self._step_entries(team_id, "step_review", version, number, round_no)
        }
        reviewers = [
            m
            for m in self._reviewers(team_id, fallback="planner")
            if m["member_id"] != builder["member_id"]
        ]
        todo = [m for m in reviewers if m["member_id"] not in reviewed]
        if todo:
            base_tree = str(
                dict(self._work(team_id).get("step_base") or {}).get(_key(step["title"])) or ""
            )
            change = await self._change(team["cwd"], base_tree) if base_tree else None
            earlier: dict[str, list[dict[str, str]]] = {}
            if round_no > 1:
                earlier = {
                    r["author"]: list(r["payload"].get("findings") or [])
                    for r in self._step_entries(
                        team_id, "step_review", version, number, round_no - 1
                    )
                }

            def record(member: dict[str, Any], result: TurnResult) -> dict[str, Any]:
                verdict = parse_review(result.text)
                return {
                    "text": verdict.text[:_MAX_TEXT],
                    "approve": verdict.positive,
                    "stated": verdict.stated,
                    "findings": [f.to_dict() for f in verdict.findings],
                    "version": version,
                    "number": number,
                    "title": step["title"],
                }

            await self._batch(
                team,
                todo,
                kind="step_review",
                round_no=round_no,
                label=f"Team thread: review step {number} of {len(steps)}",
                prompt=lambda m, notes: plan_prompts.review_step(
                    name=m["name"],
                    team=lineup,
                    cwd=team["cwd"],
                    builder=builder["name"],
                    steps=steps,
                    number=number,
                    report=str(build["payload"].get("text") or ""),
                    change=change,
                    earlier=earlier.get(m["member_id"], []) if round_no > 1 else None,
                    notes=notes,
                ),
                record=record,
                guard=True,
            )
        ids = {m["member_id"] for m in self._active(team_id)}
        if builder["member_id"] not in ids:
            return
        reviews = [
            r
            for r in self._step_entries(team_id, "step_review", version, number, round_no)
            if r["author"] in ids and r["author"] != builder["member_id"]
        ]
        if not reviews:
            if not todo:
                raise RuntimeError("nobody is left to review the step")
            return  # Its reviewers left; the loop asks the ones that are there.
        open_reviews = [r for r in reviews if not r["payload"].get("approve")]
        if not open_reviews:
            self._accept_step(team, version, number, round_no, by_user=False)
            return
        limits = self._store.get(team_id)["limits"]  # type: ignore[index]
        if round_no >= int(limits["review_rounds"]):
            self._halt(
                team,
                "needs_input",
                "step_disagreement",
                summary={
                    "rounds": round_no,
                    "number": number,
                    "title": step["title"],
                    "open": _open_points(open_reviews, names),
                },
            )
        work = self._work(team_id)
        work["step_round"] = round_no + 1
        self._store.update(team_id, work=work)

    def _accept_step(
        self, team: dict[str, Any], version: int, number: int, rounds: int, *, by_user: bool
    ) -> None:
        team_id = team["team_id"]
        plan = self._adopted(team_id)
        steps = list(plan["payload"].get("steps") or []) if plan else []
        title = steps[number - 1]["title"] if 0 < number <= len(steps) else ""
        if not 0 < number <= len(steps):
            raise RuntimeError(f"step {number} is not in the agreed plan")
        work = self._work(team_id)
        work["accepted"] = sorted(set(work.get("accepted") or []) | {number})
        if by_user:
            work["accepted_open"] = sorted(set(work.get("accepted_open") or []) | {_key(title)})
        work.pop("step", None)
        work["step_round"] = 1
        builds = self._step_entries(team_id, "step_build", version, number)
        asked = next((b for b in reversed(builds) if b["payload"].get("plan_change")), None)
        if asked is None:
            self._store.update(team_id, work=work)
        else:
            # The step is done, and the builder saw the rest of the plan needs a
            # change: accepted and sent to the planner in one write.
            self._start_revision(
                team,
                {
                    "step": number,
                    "title": title,
                    "status": "done",
                    "note": asked["payload"].get("note", ""),
                    "plan_change": asked["payload"].get("plan_change", ""),
                    "by": asked["author"],
                },
                work,
            )
        self._notice(
            team_id,
            "steps",
            "step_accepted_by_user" if by_user else "step_accepted",
            {"number": number, "version": version, "title": title, "rounds": rounds},
        )

    # ------------------------------------------------------------ final review

    async def _phase_final(self, team: dict[str, Any]) -> None:
        from .engine import _Halt  # noqa: PLC0415 - the engine imports this module

        team_id = team["team_id"]
        round_no = int(team["work"].get("final_round", 1))
        builder = self._holder(team, "builder")
        planner = self._holder(team, "planner")
        lineup = self._lineup(team_id)
        names = {m["member_id"]: m["name"] for m in self._store.members(team_id)}
        baseline = str(self._work(team_id).get("baseline") or "")
        reviewed = {r["author"] for r in self._round(team_id, "review", round_no)}
        reviewers = [m for m in self._active(team_id) if m["member_id"] != builder["member_id"]]
        todo = [m for m in reviewers if m["member_id"] not in reviewed]
        if todo:
            steps = self._current_checklist(team_id) or []
            change = await self._change(team["cwd"], baseline) if baseline else None
            if change is not None:
                work = self._work(team_id)
                work["final_files"] = change["files"][:200]
                work["final_stat"] = change["stat"][:8000]
                self._store.update(team_id, work=work)
            report = next(
                (
                    str(e["payload"].get("text") or "")
                    for e in reversed(self._store.entries(team_id))
                    if e["kind"] == "fix"
                ),
                "",
            )
            earlier = {
                r["author"]: list(r["payload"].get("findings") or [])
                for r in self._round(team_id, "review", round_no - 1)
            }

            def record(member: dict[str, Any], result: TurnResult) -> dict[str, Any]:
                verdict = parse_review(result.text)
                return {
                    "text": verdict.text[:_MAX_TEXT],
                    "approve": verdict.positive,
                    "stated": verdict.stated,
                    "findings": [f.to_dict() for f in verdict.findings],
                }

            await self._batch(
                team,
                todo,
                kind="review",
                round_no=round_no,
                label="Team thread: review the whole change",
                prompt=lambda m, notes: plan_prompts.final_review(
                    name=m["name"],
                    team=lineup,
                    cwd=team["cwd"],
                    task=team["task"],
                    builder=builder["name"],
                    steps=steps,
                    report=report,
                    change=change,
                    earlier=earlier.get(m["member_id"], []) if round_no > 1 else None,
                    planner=m["member_id"] == planner["member_id"],
                    notes=notes,
                ),
                record=record,
                guard=True,
            )
        ids = {m["member_id"] for m in self._active(team_id)}
        if builder["member_id"] not in ids:
            return
        reviews = [
            r
            for r in self._round(team_id, "review", round_no)
            if r["author"] in ids and r["author"] != builder["member_id"]
        ]
        if not reviews:
            if not todo:
                raise RuntimeError("nobody is left to review the change")
            return  # Its reviewers left; the loop asks the ones that are there.
        open_reviews = [r for r in reviews if not r["payload"].get("approve")]
        if not open_reviews:
            self._finish(team_id)
            raise _Halt
        limits = self._store.get(team_id)["limits"]  # type: ignore[index]
        if round_no >= int(limits["review_rounds"]):
            self._halt(
                team,
                "needs_input",
                "review_disagreement",
                summary={"rounds": round_no, "open": _open_points(open_reviews, names)},
            )
        if not self._round(team_id, "fix", round_no):
            findings = {
                names.get(r["author"], r["author"]): list(r["payload"].get("findings") or [])
                for r in open_reviews
            }

            async def fixed(member: dict[str, Any], result: TurnResult) -> dict[str, Any]:
                return {
                    "text": result.text[:_MAX_TEXT],
                    **await self._change_summary(team["cwd"], baseline),
                }

            await self._batch(
                team,
                [builder],
                kind="fix",
                round_no=round_no,
                label="Team thread: answer the final review",
                prompt=lambda m, notes: plan_prompts.final_fix(
                    name=m["name"], team=lineup, cwd=team["cwd"], findings=findings, notes=notes
                ),
                record=fixed,
            )
            if not self._round(team_id, "fix", round_no):
                return
        work = self._work(team_id)
        work["final_round"] = round_no + 1
        self._store.update(team_id, work=work)

    # ------------------------------------------------------------ the person decides

    def _accept_planned(self, team: dict[str, Any]) -> None:
        """Take the latest plan, the current step or the whole work as it is."""
        team_id = team["team_id"]
        work = team["work"]
        if team["reason"] == "plan_disagreement":
            base = int(work.get("plan_base", 1))
            plan = next(
                (e for e in reversed(self._versions(team_id)) if int(e["round"]) >= base), None
            )
            if plan is None:
                from .engine import TeamError  # noqa: PLC0415 - the engine imports this module

                raise TeamError("There is no plan to accept yet.")
            self._adopt_plan(team_id, plan, by_user=True)
        elif team["reason"] == "step_disagreement":
            plan = self._adopted(team_id)
            version = int(plan["payload"].get("version") or 1) if plan else 1
            self._accept_step(
                team,
                version,
                int(work.get("step") or 0),
                int(work.get("step_round") or 1),
                by_user=True,
            )
        else:
            self._finish(team_id, accepted_open=True)
            return
        self._store.update(team_id, state="running", reason="", note="")

    def _finish_planned(self, team_id: str, *, accepted_open: bool) -> None:
        team = self._store.get(team_id)
        assert team is not None
        work = dict(team["work"])
        work["accepted_open"] = list(work.get("accepted_open") or [])
        work["accepted_open_all"] = accepted_open
        entries = self._store.entries(team_id)
        findings = [
            f
            for e in entries
            if e["kind"] in ("step_review", "review")
            for f in e["payload"].get("findings") or []
        ]
        plan = self._adopted(team_id)
        last_change = next(
            (e["payload"] for e in reversed(entries) if e["kind"] in ("fix", "step_build")), {}
        )
        self._store.update(team_id, state="done", phase="done", reason="", note="", work=work)
        self._store.append(
            team_id,
            kind="summary",
            author="team",
            phase="done",
            payload={
                "outcome": "accepted_by_user" if accepted_open else "done",
                "mode": "planner_builder",
                "step_count": len(plan["payload"].get("steps") or []) if plan else 0,
                "version": int(work.get("version") or 0),
                "plan_versions": len(self._versions(team_id)),
                "step_rounds": sum(1 for e in entries if e["kind"] == "step_build"),
                "review_rounds": int(work.get("final_round", 1)),
                "open_steps": len(work["accepted_open"]),
                "builder": work.get("builder", ""),
                "finding_count": len(findings),
                "blocking": sum(1 for f in findings if f.get("severity") == "blocking"),
                "objections": sum(
                    len(e["payload"].get("objections") or [])
                    for e in entries
                    if e["kind"] == "plan_review"
                ),
                "files": list(work.get("final_files") or last_change.get("files") or []),
                "stat": str(work.get("final_stat") or last_change.get("stat") or ""),
            },
        )

    # ------------------------------------------------------------ reads

    def _plan_view(self, team: dict[str, Any], entries: list[dict[str, Any]]) -> dict[str, Any]:
        """The living plan as the board shows it: the newest version and each step's state."""
        team_id = team["team_id"]
        work = team["work"]
        roles = dict(work.get("roles") or {})
        active = self._active(team_id)
        versions = self._versions(team_id, entries)
        view: dict[str, Any] = {
            "version": 0,
            "seq": 0,
            "agreed": False,
            "author": "",
            "versions": len(versions),
            "revision": work.get("revision"),
            "steps": [],
        }
        if not versions:
            return view
        latest = versions[-1]
        agreed = latest["seq"] == int(work.get("plan_seq") or 0)
        accepted = (
            set(work.get("accepted") or [])
            if agreed
            else set(latest["payload"].get("carried") or [])
        )
        version = int(latest["payload"].get("version") or 1)
        open_titles = set(work.get("accepted_open") or [])
        builder = next(
            (m["member_id"] for m in active if roles.get(m["member_id"]) == "builder"), ""
        )
        current = int(work.get("step") or 0) if agreed and team["phase"] == "steps" else 0
        round_no = int(work.get("step_round") or 1)
        reviewers = [
            m["member_id"]
            for m in self._reviewers(team_id, fallback="planner")
            if m["member_id"] != builder
        ]
        steps = []
        for number, step in enumerate(latest["payload"].get("steps") or [], start=1):
            builds = self._step_entries(team_id, "step_build", version, number, entries=entries)
            status, holders = "open", []
            if number in accepted:
                status = "accepted"
            elif number == current:
                if not self._step_entries(
                    team_id, "step_build", version, number, round_no, entries=entries
                ):
                    status, holders = ("changes" if round_no > 1 else "building"), [builder]
                else:
                    done = {
                        r["author"]
                        for r in self._step_entries(
                            team_id, "step_review", version, number, round_no, entries=entries
                        )
                    }
                    status = "in_review"
                    holders = [r for r in reviewers if r not in done]
            steps.append(
                {
                    "number": number,
                    "title": step.get("title", ""),
                    "goal": step.get("goal", ""),
                    "done_when": step.get("done_when", ""),
                    "status": status,
                    "holders": [h for h in holders if h],
                    "rounds": max((b["round"] for b in builds), default=0),
                    "open_findings": number in accepted
                    and _key(step.get("title", "")) in open_titles,
                }
            )
        view.update(
            version=version,
            seq=latest["seq"],
            agreed=agreed,
            author=latest["author"],
            steps=steps,
        )
        return view

    def _planned_rounds(self, team: dict[str, Any]) -> dict[str, int]:
        work = team["work"]
        plan_round = int(work.get("plan_round", 1))
        return {
            "plan": max(0, plan_round - int(work.get("plan_base", 1)) + 1),
            "review": int(
                work.get("final_round", 0)
                if team["phase"] in ("final", "done")
                else work.get("step_round", 0)
            ),
            "step": int(work.get("step") or 0),
            # The keys of the board's bands: the plan round and the final round.
            "plan_round": plan_round,
            "final": int(work.get("final_round", 0)),
        }


def _open_points(reviews: list[dict[str, Any]], names: dict[str, str]) -> list[dict[str, Any]]:
    return [
        {
            "member_id": r["author"],
            "name": names.get(r["author"], r["author"]),
            "items": [
                (f"{f['where']}: " if f.get("where") else "") + f["issue"]
                for f in r["payload"].get("findings") or []
                if f.get("severity") == "blocking"
            ],
        }
        for r in reviews
    ]


def plan_issues(entries: list[dict[str, Any]], *, done: bool) -> list[dict[str, Any]]:
    """Everything the members caught in the plan and the steps, oldest first.

    An objection is settled once a later plan version was agreed or its author
    agreed later; a step finding once the team accepted that step or its
    reviewer approved a later round of it; a final finding once its reviewer
    approved a later round (or the work was done).
    """
    issues: list[dict[str, Any]] = []
    agreed = [
        e["seq"]
        for e in entries
        if e["kind"] == "notice" and e["payload"].get("code") == "plan_version_agreed"
    ]
    accepted = [
        (e["seq"], e["payload"].get("version"), e["payload"].get("number"))
        for e in entries
        if e["kind"] == "notice" and e["payload"].get("code") == "step_accepted"
    ]

    def later(entry: dict[str, Any], kind: str, field: str, same: Callable[[dict], bool]) -> bool:
        return any(
            e["kind"] == kind
            and e["seq"] > entry["seq"]
            and e["author"] == entry["author"]
            and e["payload"].get(field)
            and same(e)
            for e in entries
        )

    for entry in entries:
        payload = entry["payload"]
        if entry["kind"] == "plan_review":
            settled = any(seq > entry["seq"] for seq in agreed) or later(
                entry, "plan_review", "agree", lambda e: True
            )
            for text in payload.get("objections") or []:
                issues.append(
                    {
                        "seq": entry["seq"],
                        "stage": "plan",
                        "round": entry["round"],
                        "by": entry["author"],
                        "severity": "blocking",
                        "where": "",
                        "issue": text,
                        "fix": "",
                        "resolved": settled,
                    }
                )
        elif entry["kind"] == "step_review":
            version, number = payload.get("version"), payload.get("number")
            settled = any(
                seq > entry["seq"] and v == version and n == number for seq, v, n in accepted
            ) or later(
                entry,
                "step_review",
                "approve",
                lambda e, v=version, n=number: (
                    e["payload"].get("version") == v and e["payload"].get("number") == n
                ),
            )
            for finding in payload.get("findings") or []:
                issues.append(
                    {
                        "seq": entry["seq"],
                        "stage": "step",
                        "round": entry["round"],
                        "number": number,
                        "by": entry["author"],
                        **finding,
                        "resolved": settled,
                    }
                )
        elif entry["kind"] == "review":
            settled = done or later(entry, "review", "approve", lambda e: True)
            for finding in payload.get("findings") or []:
                issues.append(
                    {
                        "seq": entry["seq"],
                        "stage": "review",
                        "round": entry["round"],
                        "by": entry["author"],
                        **finding,
                        "resolved": settled,
                    }
                )
    return issues
