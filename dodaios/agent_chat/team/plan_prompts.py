"""What the coordinator tells each member in the planner-and-builder mode."""

from __future__ import annotations

from typing import Any, Final

from .prompts import (
    ANSWER_FINDINGS,
    NO_EDITS,
    VOTE_BLOCK,
    change_block,
    material,
    notes_text,
    quotes,
    verdict_block,
)
from .prompts import quote as _quote
from .signals import MAX_STEPS, PLAN_BLOCK, STEP_BLOCK

__all__ = [
    "build_step",
    "final_fix",
    "final_review",
    "plan_text",
    "review_plan",
    "review_step",
    "write_plan",
]

_DUTY: Final[dict[str, str]] = {"planner": "plans", "builder": "builds", "reviewer": "reviews"}


def _frame(name: str, team: list[tuple[str, str]], cwd: str, step: str) -> str:
    role = next((r for n, r in team if n == name), "reviewer")
    lineup = ", ".join(f"{n} {_DUTY.get(r, 'reviews')}" for n, r in team)
    return (
        f"You are {name}, the {role} in a team thread of {len(team)} coding agents: {lineup}. "
        "The planner owns an ordered plan of small steps; the builder builds one step per turn; "
        "a member other than the author reviews every plan and step. A coordinator relays "
        f"contributions; you cannot message each other. Project folder: {cwd}. No user answers "
        f"questions. Only your final message reaches the thread.\n\n{step}"
    )


def plan_text(steps: list[dict[str, Any]], *, current: int = 0) -> str:
    lines = []
    for number, step in enumerate(steps, start=1):
        status = str(step.get("status") or "open").replace("_", " ")
        mark = "  <- this step" if number == current else ""
        lines.append(f"{number}. [{status}] {step.get('title', '')}{mark}")
        if step.get("goal"):
            lines.append(f"   Goal: {step['goal']}")
        lines.append(f"   Done when: {step.get('done_when', '')}")
    return "\n".join(lines)


def _plan_format(reopen: bool) -> str:
    extra = ', "reopen": []' if reopen else ""
    return (
        f"end with this block, steps in order of work (at most {MAX_STEPS}):\n"
        f"```{PLAN_BLOCK}\n"
        '{"steps": [{"title": "short name", "goal": "what to change and where", '
        f'"done_when": "the check that proves the step"}}]{extra}}}\n'
        "```"
    )


def _revision(revision: dict[str, Any]) -> str:
    status = "is blocked" if revision.get("status") == "blocked" else "asks to change the plan"
    where = f"step {revision.get('step')} ({revision.get('title', '')})"
    lines = [f"While building {where} the builder {status}."]
    if revision.get("note"):
        lines.append(f"Note: {revision['note']}")
    if revision.get("plan_change"):
        lines.append(f"Change asked for: {revision['plan_change']}")
    return "\n".join(lines)


def write_plan(
    *,
    name: str,
    team: list[tuple[str, str]],
    cwd: str,
    task: str,
    current: list[dict[str, Any]] | None,
    previous: list[dict[str, Any]] | None,
    objections: dict[str, list[str]],
    revision: dict[str, Any] | None,
    unreadable: str,
    notes: list[str],
) -> str:
    parts: list[str] = []
    if revision is not None and current is not None:
        step = (
            "Your step: revise the plan. Accepted steps are built and reviewed; a step is "
            "matched by its title, so keep each accepted step's exact title and change the open "
            'steps as the request below needs. To rebuild an accepted step, list its number in '
            f'"reopen". {NO_EDITS} Explain the change briefly, then {_plan_format(True)}'
        )
        parts.append(_quote("the plan so far", plan_text(current)))
        parts.append(_quote("request by the builder", _revision(revision)))
    else:
        step = (
            "Your step: write the plan. Each step must be buildable and checkable in one turn; "
            "each done_when is a concrete check (a passing command, visible behaviour). "
            f"{NO_EDITS} Explain briefly, then {_plan_format(False)}"
        )
    if previous is not None and objections:
        step += (
            "\n\nReviewers objected to your last proposal: resolve each objection or keep the "
            "point with a one-line reason."
        )
        parts.append(_quote("your last proposal", plan_text(previous)))
        parts += quotes(
            [
                (f"objections by {member}", "\n".join(f"- {item}" for item in items))
                for member, items in objections.items()
            ]
        )
    if unreadable:
        step += (
            f"\n\nYour last reply had no plan the coordinator could read: {unreadable} "
            "End with the block exactly as shown."
        )
    text = _frame(name, team, cwd, step) + f"\n\nThe task:\n{task.strip()}"
    if parts:
        text += material(parts)
    return text + notes_text(notes)


def review_plan(
    *,
    name: str,
    team: list[tuple[str, str]],
    cwd: str,
    task: str,
    planner: str,
    steps: list[dict[str, Any]],
    revision: dict[str, Any] | None,
    notes: list[str],
) -> str:
    step = (
        f"Your step: review the plan by {planner}. Check that the steps solve the task, the "
        "order works, each step fits one turn and each done_when proves its step. Object only "
        f"to a defect that makes the result wrong, unsafe or unverifiable. {NO_EDITS} {VOTE_BLOCK}"
    )
    parts = []
    if revision is not None:
        step += (
            " This is a revision: accepted steps are already built and reviewed; judge whether "
            "the open steps meet the builder's request."
        )
        parts.append(_quote("request by the builder", _revision(revision)))
    parts.append(_quote(f"plan by {planner}", plan_text(steps)))
    return (
        _frame(name, team, cwd, step)
        + f"\n\nThe task:\n{task.strip()}"
        + material(parts)
        + notes_text(notes)
    )


def build_step(
    *,
    name: str,
    team: list[tuple[str, str]],
    cwd: str,
    task: str,
    steps: list[dict[str, Any]],
    number: int,
    findings: dict[str, list[dict[str, str]]],
    notes: list[str],
) -> str:
    current = steps[number - 1]
    step = (
        f'Your step: build step {number} of {len(steps)}, "{current.get("title", "")}". '
        "Build only this step in the project folder and verify it against its done_when. "
        "Final message: what changed, how verified, then this block:\n"
        f"```{STEP_BLOCK}\n"
        f'{{"step": {number}, "status": "done" or "blocked", "note": "one line", '
        '"plan_change": ""}\n'
        "```\n"
        '"blocked" = the step cannot be done as planned (stop, say why). A change the rest of '
        'the plan needs goes in "plan_change"; the planner then revises.'
    )
    parts = [_quote("the plan", plan_text(steps, current=number))]
    if findings:
        step += f"\n\nReviewers asked for changes to this step. {ANSWER_FINDINGS}"
        parts += quotes(
            [(f"findings by {member}", _findings(items)) for member, items in findings.items()]
        )
    return (
        _frame(name, team, cwd, step)
        + f"\n\nThe task:\n{task.strip()}"
        + material(parts)
        + notes_text(notes)
    )


_VERDICT_BLOCK: Final[str] = verdict_block("wrong or fails its check")


def _findings(items: list[dict[str, str]]) -> str:
    lines = []
    for item in items:
        severity = item.get("severity", "blocking")
        line = " ".join(f"- [{severity}] {item.get('where', '')} {item.get('issue', '')}".split())
        if item.get("fix"):
            line += f" (suggested fix: {item['fix']})"
        lines.append(line)
    return "\n".join(lines) or "None."


def _earlier(earlier: list[dict[str, str]]) -> str:
    return _quote(
        "your earlier findings",
        _findings(earlier) if earlier else "None: you approved the last round.",
    )


def review_step(
    *,
    name: str,
    team: list[tuple[str, str]],
    cwd: str,
    builder: str,
    steps: list[dict[str, Any]],
    number: int,
    report: str,
    change: dict[str, Any] | None,
    earlier: list[dict[str, str]] | None,
    notes: list[str],
) -> str:
    current = steps[number - 1]
    step = (
        f'Your step: review step {number} of {len(steps)}, "{current.get("title", "")}", '
        f"built by {builder}, against its done_when only. The report is a claim: read the files "
        f"and run the check yourself. {NO_EDITS} {_VERDICT_BLOCK}"
    )
    parts = [_quote("the plan", plan_text(steps, current=number))]
    if earlier is not None:
        step += (
            " In this further round, check that each earlier finding is resolved and nothing broke."
        )
        parts.append(_earlier(earlier))
    parts.append(_quote(f"report by {builder}", report or "No report was written."))
    parts.append(
        change_block(change, "change since this step started", "No file differs from before.")
    )
    return _frame(name, team, cwd, step) + material(parts) + notes_text(notes)


def final_review(
    *,
    name: str,
    team: list[tuple[str, str]],
    cwd: str,
    task: str,
    builder: str,
    steps: list[dict[str, Any]],
    report: str,
    change: dict[str, Any] | None,
    earlier: list[dict[str, str]] | None,
    planner: bool,
    notes: list[str],
) -> str:
    step = (
        "Your step: final review. All steps are built and accepted. Review the whole change "
        "against the task: done as asked, steps fit together, nothing later broke anything "
        "earlier, nothing missing. Read the files and run the checks yourself. "
    )
    if planner:
        step += "You wrote the plan: approve only when the result fulfils it and the task. "
    step += f"{NO_EDITS} {_VERDICT_BLOCK}"
    parts = [_quote("the plan", plan_text(steps))]
    if earlier is not None:
        step += " In this further round, check that each earlier finding is resolved."
        parts.append(_earlier(earlier))
        parts.append(_quote(f"report by {builder}", report or "No report was written."))
    parts.append(
        change_block(change, "change since the build started", "No file differs from before.")
    )
    return (
        _frame(name, team, cwd, step)
        + f"\n\nThe task:\n{task.strip()}"
        + material(parts)
        + notes_text(notes)
    )


def final_fix(
    *,
    name: str,
    team: list[tuple[str, str]],
    cwd: str,
    findings: dict[str, list[dict[str, str]]],
    notes: list[str],
) -> str:
    step = f"Your step: answer the final review of the whole change. {ANSWER_FINDINGS}"
    parts = quotes(
        [(f"findings by {member}", _findings(items)) for member, items in findings.items()]
    )
    return _frame(name, team, cwd, step) + material(parts) + notes_text(notes)
