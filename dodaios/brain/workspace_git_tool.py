"""Application-owned git tool for coding workspaces, independent of any voice provider."""

from __future__ import annotations

from dodaios.core.protocols import ExecutionContext, ToolResult, WorkspaceOrchestrationGateway

# Operations that only look; everything else changes the repository.
_READS = frozenset({"state", "worktrees", "pull_requests"})
_OPS = (
    "state",
    "worktrees",
    "pull_requests",
    "worktree_create",
    "worktree_archive",
    "worktree_restore",
    "commit",
    "push",
    "pull_request",
)


class WorkspaceGitTool:
    name = "workspace-git"
    # The user's own repository actions: carried out when asked and logged.
    risk_tier = "monitor"
    is_action_tool = True
    description = (
        "Git for a coding workspace. state: branch, ahead/behind and the changed files. "
        "worktrees: its checkouts and the archived ones. pull_requests: the open pull "
        "requests and the ones of its branches, with their checks, review and merge-queue "
        "state (here marks the checked-out branch's). worktree_create: a new worktree on "
        "branch (a new branch from base, or an existing one); only when the user asks for a "
        "worktree. worktree_archive: put a worktree away (name it by branch or folder) with "
        "its uncommitted work saved; the branch and its commits stay. Ignored files are not "
        "saved: it refuses while there are any and names them; pass drop_ignored only "
        "after the user agreed to lose them. worktree_restore: "
        "bring an archived worktree back at its old path. commit: stage everything that is "
        "not ignored and commit with message. push: the checked-out branch, or branch. "
        "pull_request: push if needed and open one (title, draft). Name the workspace as in "
        "workspace-orchestrate (workspace or workspace_id); without one the visible workspace "
        "is used. A refusal carries git's own reason and changed nothing: pass it on. Say the "
        "result in a sentence and never read out file lists unless the user asks."
    )
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "op": {"type": "string", "enum": list(_OPS)},
            **{
                key: {"type": "string"}
                for key in ("project", "workspace", "project_id", "workspace_id")
            },
            "branch": {
                "type": "string",
                "description": (
                    "worktree_create: the branch (omit for a suggested name); push and "
                    "pull_request: another branch than the checked-out one."
                ),
            },
            "base": {
                "type": "string",
                "description": "worktree_create: what a new branch starts from (default HEAD).",
            },
            "worktree": {
                "type": "string",
                "description": (
                    "worktree_archive: branch or folder of the worktree; worktree_restore: "
                    "name or branch of the archived one."
                ),
            },
            "drop_ignored": {
                "type": "boolean",
                "description": (
                    "worktree_archive: delete the worktree's ignored files with it. Only "
                    "after the user agreed."
                ),
            },
            "message": {"type": "string", "description": "commit: the commit message."},
            "title": {"type": "string", "description": "pull_request: its title."},
            "draft": {"type": "boolean", "description": "pull_request: open it as a draft."},
        },
        "required": ["op"],
    }

    def __init__(self, gateway: WorkspaceOrchestrationGateway) -> None:
        self.gateway = gateway

    def risk_tier_for_args(self, args: dict) -> str:
        return "safe" if args.get("op") in _READS else "monitor"

    def read_only_for_args(self, args: dict) -> bool:
        return args.get("op") in _READS

    def describe_args(self, args: dict) -> dict:
        detail = args.get("message") or args.get("title") or args.get("worktree") or ""
        return {
            "level": "read" if args.get("op") in _READS else "modify",
            "project": str(args.get("project_id") or args.get("project") or ""),
            "workspace": str(args.get("workspace_id") or args.get("workspace") or ""),
            "agent": str(args.get("branch") or ""),
            "task": f"{args.get('op') or ''} {detail}".strip()[:240],
        }

    async def execute(self, args: dict, ctx: ExecutionContext) -> ToolResult:
        try:
            result = await self.gateway.run({**args, "action": "git"}, trace_id=str(ctx.trace_id))
        except ValueError as exc:
            # Invalid arguments go back to the model as the tool error.
            return ToolResult(success=False, output=None, error=str(exc))
        return ToolResult(
            success=result.get("success") is not False and result.get("status") == "ok",
            output=result,
        )
