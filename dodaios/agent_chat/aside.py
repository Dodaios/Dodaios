"""Side questions (``/btw``): ask a coding thread's agent something without stopping it.

Claude Code's terminal has ``/btw <question>``: a quick question about the work
that the agent answers at once, while it goes on working, and that does not
become part of the conversation. Print mode (``claude -p``, what a thread runs)
does not have the command: typed into a thread it went to the running turn as
an ordinary message and turned the agent away from its work. Dodaios runs it
itself:

* The question goes to a **copy** of the thread's conversation:
  ``--resume <id> --fork-session --no-session-persistence``. The copy sees
  everything the conversation holds so far, answers once (``--max-turns 1``)
  and is not saved, so the thread's own conversation never learns of it and
  the running turn is not touched.
* The command line is the one the thread's turns run (same model, system
  prompt, tools and MCP servers), so the request reads the conversation from
  the prompt cache the thread already warmed instead of paying for all of it
  again. Only the permission mode differs: every tool call the copy tries is
  refused, as in the terminal, where a side question has no tools.
* The thread shows the question and its answer as one card (notices
  ``aside_asked`` / ``aside_answered``; ``aside_dismissed`` closes it). They
  are never sent to the agent.

Only Claude Code seats (Claude, GLM) can do this today; their typeahead lists
``/btw`` (:func:`suggestion`).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from pathlib import Path
from typing import Any, Final

log = logging.getLogger(__name__)

__all__ = [
    "ANSWERED",
    "ASKED",
    "COMMAND",
    "DISMISSED",
    "MAX_RUNNING",
    "RUNNERS",
    "ask",
    "dismiss",
    "parse",
    "suggestion",
    "takes",
]

#: The command, as typed.
COMMAND: Final[str] = "btw"
#: Notice kinds in the thread's timeline. Mirrored in
#: ``components/agentchat/reduce.ts``.
ASKED: Final[str] = "aside_asked"
ANSWERED: Final[str] = "aside_answered"
DISMISSED: Final[str] = "aside_dismissed"
#: The runners whose conversation can be copied for a side question.
RUNNERS: Final[frozenset[str]] = frozenset({"claude-cli", "glm-cli"})
#: Side questions one thread answers at once; a further one is refused.
MAX_RUNNING: Final[int] = 3
#: How long a side question may take before it is given up.
TIMEOUT_S: Final[float] = 240.0
#: How much of an answer the closing notice carries.
ANSWER_CHARS: Final[int] = 16_000
#: Longest line Claude Code's stream may write (a big tool result in the copy's history).
_LINE_LIMIT: Final[int] = 32 * 1024 * 1024

_PATTERN: Final[re.Pattern[str]] = re.compile(r"^\s*/btw(?:\s+(.*))?$", re.IGNORECASE | re.DOTALL)

#: What the copy is told above the question. It answers from what it knows.
_BRIEF: Final[str] = (
    "<side_question>\n"
    "The person asks a quick side question (/btw) while your work goes on in the "
    "main conversation. Answer it directly and briefly from what you already know "
    "in this conversation. Do not use any tools, and do not continue, change or "
    "plan the task: this answer is not part of the work.\n"
    "</side_question>\n\n"
)

#: Said when the copy wanted a tool instead of answering.
_NEEDED_TOOLS: Final[str] = (
    "The agent would have to look this up. A side question answers only from what "
    "the agent already knows; send it as a normal message instead."
)


def parse(text: str) -> str | None:
    """The question of a ``/btw`` message.

    ``""`` when none was typed after the command; ``None`` for any other text.
    """
    match = _PATTERN.match(text or "")
    if match is None:
        return None
    return (match.group(1) or "").strip()


def takes(session: Any, runner: str) -> bool:
    """Whether ``/btw`` in this chat is a side question (a coding thread on Claude Code)."""
    return getattr(session, "surface", "") == "agent" and runner in RUNNERS


def suggestion() -> Any:
    """The ``/btw`` row of a Claude Code thread's ``/`` list."""
    from dodaios.agent_chat.typeahead import GROUP_CLI, Suggestion

    return Suggestion(
        value=COMMAND,
        label=COMMAND,
        hint="Ask a quick side question; the agent keeps working",
        kind="command",
        group=GROUP_CLI,
        argument_hint="<question>",
    )


def _running(svc: Any) -> dict[str, dict[str, asyncio.Task[None]]]:
    live = getattr(svc, "_asides", None)
    if live is None:
        live = svc._asides = {}
    return live


async def ask(svc: Any, session_id: str, question: str, *, runner: str) -> str:
    """Start a side question; returns its id. The answer arrives as a notice.

    Raises ``ValueError`` for an empty question or when too many are open.
    """
    question = question.strip()
    if not question:
        raise ValueError("Type a question after /btw.")
    session = svc.store.get_session(session_id)
    if session is None:
        raise ValueError("No such thread.")
    open_here = _running(svc).setdefault(session_id, {})
    if len(open_here) >= MAX_RUNNING:
        raise ValueError(
            "Wait for an answer first: this thread already has three side questions open."
        )
    aside_id = uuid.uuid4().hex[:12]
    await svc.post_notice(
        session_id,
        {"kind": ASKED, "aside_id": aside_id, "text": question, "question": question},
    )
    task = asyncio.create_task(
        _answer(svc, session_id, aside_id, question, runner),
        name=f"aside-{session_id[-16:]}-{aside_id}",
    )
    open_here[aside_id] = task

    def _done(_task: asyncio.Task[None]) -> None:
        here = _running(svc).get(session_id)
        if here is not None:
            here.pop(aside_id, None)
            if not here:
                _running(svc).pop(session_id, None)

    task.add_done_callback(_done)
    return aside_id


async def dismiss(svc: Any, session_id: str, aside_id: str) -> bool:
    """Close a side question's card; a running one is stopped."""
    task = _running(svc).get(session_id, {}).get(aside_id)
    if task is not None:
        task.cancel()
    await svc.post_notice(session_id, {"kind": DISMISSED, "aside_id": aside_id})
    return True


async def _answer(svc: Any, session_id: str, aside_id: str, question: str, runner: str) -> None:
    started = time.monotonic()
    outcome: dict[str, Any]
    try:
        session = svc.store.get_session(session_id)
        if session is None:
            raise ValueError("The thread is gone.")
        plan, cwd = await _plan(session, runner, question)
        answer, status = await asyncio.wait_for(_run(plan, cwd), timeout=TIMEOUT_S)
        if status == "tools":
            outcome = {"status": "failed", "error": _NEEDED_TOOLS}
        elif not answer.strip():
            outcome = {"status": "failed", "error": "The agent gave no answer."}
        else:
            outcome = {"status": "done", "answer": answer[:ANSWER_CHARS]}
    except asyncio.CancelledError:  # dismissed: its card is gone, nothing is left to tell
        return
    except TimeoutError:  # told on the card: "no answer within four minutes"
        outcome = {"status": "failed", "error": "No answer within four minutes."}
    except Exception as exc:  # noqa: BLE001 — the card says what went wrong; the thread runs on
        log.warning("agent chat %s: side question failed", session_id, exc_info=True)
        outcome = {"status": "failed", "error": str(exc) or exc.__class__.__name__}
    outcome["duration_ms"] = int((time.monotonic() - started) * 1000)
    try:
        await svc.post_notice(session_id, {"kind": ANSWERED, "aside_id": aside_id, **outcome})
    except Exception:  # noqa: BLE001 — nothing else to tell
        log.warning("agent chat %s: side answer not posted", session_id, exc_info=True)


async def _plan(session: Any, runner: str, question: str) -> tuple[Any, Path]:
    """The thread's own command line, made into a one-answer copy of its conversation."""
    from dodaios.agent_chat import runner_cli
    from dodaios.agent_chat.thread_sessions import split_fork
    from dodaios.society.remote import placement_for_session

    if await placement_for_session(session) is not None:
        raise ValueError("Side questions work for threads on this computer only.")
    planner = runner_cli._PLANNERS.get(runner)
    if planner is None or runner not in RUNNERS:
        raise ValueError("This agent cannot answer side questions.")
    resume_id, fork_source = split_fork(getattr(session, "vendor_session", None))
    vendor = resume_id or fork_source
    cwd = runner_cli._resolved_cwd(session.cwd or Path.home())
    # The effort the thread's turns run on (``_run_cli_once``): the same
    # thinking settings keep the conversation's cached prefix usable.
    effort = ""
    if (session.effort or "").strip() and runner == "claude-cli":
        from dodaios.agent_chat.catalog import claude_model_efforts
        from dodaios.agent_chat.effort import effort_for_model

        effort = effort_for_model(
            session.provider, session.effort, claude_model_efforts(session.model)
        )
    with runner_cli.cli_catalog_scope(cwd=cwd, ignore_user_config=False):
        if runner in runner_cli._CLAUDE_CODE_RUNNERS:
            await asyncio.to_thread(runner_cli.warm_claude_capabilities)
        plan = planner(
            prompt=_BRIEF + question,
            cwd=cwd,
            model=session.model,
            effort=effort,
            permission_mode=session.permission_mode,
            resume=vendor,
            identity=None,
        )
        runner_cli.apply_speed(plan.argv, runner, getattr(session, "speed", ""))
        await asyncio.to_thread(runner_cli._carry_thread_conversation, runner, vendor, plan.env)
    _as_copy(plan.argv, has_conversation=bool(vendor))
    return plan, cwd


def _as_copy(argv: list[str], *, has_conversation: bool) -> None:
    """Turn a thread turn's command line into a one-answer, unsaved copy, in place.

    A thread's turn either resumes its conversation (``--resume <id>``) or
    starts one under a chosen id (``--session-id``). The copy forks the
    conversation, keeps nothing on disk and answers once. Every tool call
    asks first, and is refused (``_run``), whatever mode the thread runs in.
    """
    if not has_conversation and "--session-id" in argv:
        at = argv.index("--session-id")
        del argv[at : at + 2]
    if has_conversation and "--fork-session" not in argv:
        argv.append("--fork-session")
    if "--permission-mode" in argv:
        argv[argv.index("--permission-mode") + 1] = "default"
    argv += ["--no-session-persistence", "--max-turns", "1"]


async def _run(plan: Any, cwd: Path) -> tuple[str, str]:
    """Run the copy; ``(answer, status)`` where status is ``done`` or ``tools``."""
    from dodaios.core.process_utils import NO_WINDOW_CREATIONFLAGS

    proc = await asyncio.create_subprocess_exec(
        *plan.argv,
        cwd=str(cwd),
        env=plan.env,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        creationflags=NO_WINDOW_CREATIONFLAGS,
        limit=_LINE_LIMIT,
    )
    assert proc.stdin is not None and proc.stdout is not None and proc.stderr is not None
    # Read beside stdout: a full stderr pipe would stall the CLI.
    stderr = asyncio.create_task(proc.stderr.read())
    texts: list[str] = []
    result: dict[str, Any] | None = None
    wanted_tool = False

    async def write(line: str) -> None:
        assert proc.stdin is not None
        proc.stdin.write(line.encode("utf-8"))
        await proc.stdin.drain()

    try:
        if plan.control_init:
            await write(plan.control_init)
        if plan.stdin_text:
            await write(plan.stdin_text)
        while True:
            raw = await proc.stdout.readline()
            if not raw:
                break
            try:
                obj = json.loads(raw)
            except ValueError:  # a non-JSON line (a CLI warning) carries no answer
                continue
            if not isinstance(obj, dict):
                continue
            kind = obj.get("type")
            if kind == "control_request":
                request = obj.get("request") if isinstance(obj.get("request"), dict) else {}
                if request.get("subtype") == "can_use_tool":
                    wanted_tool = True
                frame = {
                    "type": "control_response",
                    "response": {
                        "subtype": "success",
                        "request_id": str(obj.get("request_id") or ""),
                        "response": {
                            "behavior": "deny",
                            "message": "A side question has no tools. Answer from what you know.",
                        },
                    },
                }
                await write(json.dumps(frame) + "\n")
            elif kind == "assistant":
                message = obj.get("message") if isinstance(obj.get("message"), dict) else {}
                for block in message.get("content") or []:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "text" and block.get("text"):
                        texts.append(str(block["text"]))
                    elif block.get("type") == "tool_use":
                        wanted_tool = True
            elif kind == "result":
                result = obj
                break
    except BaseException:
        # Dismissed, timed out or broken: the copy goes at once.
        if proc.returncode is None:
            proc.kill()
        raise
    finally:
        if proc.stdin and not proc.stdin.is_closing():
            proc.stdin.close()
        try:
            await asyncio.wait_for(proc.wait(), timeout=10)
        except TimeoutError:  # the copy did not exit after its answer: it is killed
            proc.kill()
            await proc.wait()
        try:
            err = await asyncio.wait_for(stderr, timeout=2)
        except (TimeoutError, asyncio.CancelledError):  # stderr only words a failure
            err = b""
    if result is None:
        tail = err.decode("utf-8", "replace").strip().splitlines()[-1:] or ["the agent stopped"]
        raise RuntimeError(f"No answer: {tail[0][:300]}")
    answer = str(result.get("result") or "").strip() or "\n\n".join(texts).strip()
    if result.get("is_error") and result.get("subtype") == "success" and answer:
        # A failed request reports its message as the result.
        raise RuntimeError(answer[:500])
    if wanted_tool and (result.get("subtype") == "error_max_turns" or not answer):
        return "", "tools"
    return answer, "done"
