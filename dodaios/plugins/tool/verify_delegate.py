"""verify_delegate: check delegated work against what it left behind.

A worker's "done" is a claim. This tool reads the evidence instead: a coding
job's diff in its folder (and the test run it recorded, if any), an artifact's
file (exists, not empty, parses), a society result's evidence refs (each one
exists). It answers ``verified`` / ``unverified`` / ``failed`` with the checks
behind the verdict. Read-only: it never runs a command, starts work or asks a
model (``dodaios.core.delegate_verify``).

Job ids it understands today (a job-ledger id plugs in through ``register_resolver``):

* ``coding:<pane history id>[:...]`` or ``pane:<id>`` — a coding pane's submission
* ``society:<event id>`` — an assignment to a named agent
* ``artifact:<file path>`` (or a bare file path) — a produced file
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

from dodaios.core.delegate_verify import DelegateRecord, verify_record
from dodaios.core.protocols import ExecutionContext, ToolResult

log = logging.getLogger(__name__)

#: ``prefix -> async resolver(rest) -> DelegateRecord | str`` (a ``str`` is the reason
#: the job cannot be resolved). Lets the jobs ledger hand its records in.
_RESOLVERS: dict[str, Callable[[str], Awaitable[DelegateRecord | str]]] = {}


def register_resolver(
    prefix: str, resolver: Callable[[str], Awaitable[DelegateRecord | str]]
) -> None:
    _RESOLVERS[prefix] = resolver


async def _resolve_coding(job_id: str, rest: str) -> DelegateRecord | str:
    from dodaios.agentic_ide.session import get_registry

    history_id = rest.split(":", 1)[0]
    found = get_registry().find_terminal("pane:" + history_id)
    if found is None:
        return "The coding pane is closed, so its folder cannot be read."
    owner, term = found
    cwd = getattr(term, "folder", "") or getattr(owner, "folder", "")
    if getattr(term, "computer_id", ""):
        return "This coding pane runs on another computer; its folder cannot be read here."
    return DelegateRecord(
        job_id,
        "coding",
        cwd=str(cwd or ""),
        test_command=str(getattr(term, "test_command", "") or ""),
        test_result=str(getattr(term, "test_result", "") or ""),
    )


async def _resolve_society(job_id: str, rest: str) -> DelegateRecord | str:
    from dodaios.society.delegation_wait import result_for
    from dodaios.society.runtime import current_runtime

    runtime = current_runtime()
    if runtime is None:
        return "The agent society is not running."
    request = await runtime.store.get_event(rest)
    if request is None:
        return "No such assignment on the board."
    result = await result_for(runtime.store, request)
    if result is None:
        return "The agent has not reported a result yet; there is nothing to verify."
    refs = [str(ref) for ref in (result.get("evidence") or [])]
    found: set[str] = set()
    for ref in refs:
        bare = ref.strip().removeprefix("event:")
        if re.fullmatch(r"[0-9a-fA-F]{32}", bare) and await runtime.store.get_event(bare):
            found.add(bare)
    return DelegateRecord(
        job_id, "society", evidence=refs, event_exists=lambda ref: ref in found
    )


async def _resolve_artifact(job_id: str, rest: str) -> DelegateRecord | str:
    return DelegateRecord(job_id, "artifact", artifact_path=rest)


async def resolve(job_id: str) -> DelegateRecord | str:
    prefix, _, rest = job_id.partition(":")
    custom = _RESOLVERS.get(prefix)
    if custom is not None:
        return await custom(rest)
    if prefix in ("coding", "pane") and rest:
        return await _resolve_coding(job_id, rest)
    if prefix == "society" and rest:
        return await _resolve_society(job_id, rest)
    if prefix == "artifact" and rest:
        return await _resolve_artifact(job_id, rest)
    if len(job_id) > 2 and (job_id[1:3] in (":\\", ":/") or job_id.startswith(("/", "~"))):
        return await _resolve_artifact(job_id, job_id)
    return (
        "Unknown job id. Use coding:<pane id>, society:<event id> or artifact:<file path>."
    )


class VerifyDelegateTool:
    read_only = True

    name = "verify_delegate"
    risk_tier = "safe"
    description = (
        "Check delegated work against the evidence it left behind, instead of trusting the "
        "worker's own report. Coding job (coding:<pane id>): the diff in its folder plus the "
        "test run it recorded. Artifact (artifact:<file path>): the file exists, is not empty "
        "and parses. Society result (society:<event id>): every listed evidence ref exists. "
        "Returns verified / unverified / failed with the checks. Read-only."
    )
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "job_id": {
                "type": "string",
                "description": "coding:<pane id>, society:<event id> or artifact:<file path>.",
            },
        },
        "required": ["job_id"],
    }

    async def execute(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        job_id = str(args.get("job_id") or "").strip()
        if not job_id:
            return ToolResult(success=False, output=None, error="job_id is empty")
        try:
            record = await resolve(job_id)
            if isinstance(record, str):
                return ToolResult(
                    success=True,
                    output={"job_id": job_id, "verdict": "unverified", "summary": record},
                )
            verification = await asyncio.to_thread(verify_record, record)
        except Exception as exc:  # noqa: BLE001 - a broken check is reported, never a crash
            log.warning("verify_delegate failed for %s", job_id, exc_info=True)
            return ToolResult(success=False, output=None, error=f"Verification failed: {exc}")
        return ToolResult(success=True, output=verification.to_dict())
