"""Comments on a node, worked in by the assistant in the background.

The reader leaves numbered comments on a node's page (``bridge.py``) and sends
them together with one button. They reach the assistant as ONE request, and
that request runs as a quiet one-shot lead routine, not as a message in the
conversation: the reader asked for a change to the page, and sees it there.
The conversation stays as it was. Only a run that fails, or a comment the
assistant could not carry out, says so in the conversation.

Like a check-in the person asked for, the run is the person's own request for
right now, so it runs on the assistant's seat as it is, also when that seat
bills a key (``routine_runner._hold_unattended_run_off_keys``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Final

from dodaios.nodes.model import Node
from dodaios.nodes.types import NodeError

log = logging.getLogger(__name__)

#: Tag on the routine that works a batch of comments in: ``node-comments:<id>``.
#: Not ``node:``: that prefix belongs to the node's refresh routine
#: (``refresh.py``), which finds its own routine by it.
TAG_PREFIX: Final[str] = "node-comments:"
#: How many comments go out at once.
MAX_COMMENTS: Final[int] = 40
#: The scheduler's shortest delay; the run starts right away.
_START_DELAY_SECONDS: Final[float] = 1.0


@dataclass(frozen=True)
class NodeComment:
    """One comment the reader left on the node's page."""

    text: str
    #: The text the pin was put on; "" on a picture or on nothing.
    quote: str = ""
    #: The place in the node's own terms (``/slides/2``, ``§ Costs``); may be "".
    where: str = ""


def tag_for(node_id: str) -> str:
    return f"{TAG_PREFIX}{node_id}"


def is_comments_tag(tag: str) -> bool:
    return str(tag).startswith(TAG_PREFIX)


def _one_line(value: str) -> str:
    return " ".join(str(value).split())


def comments_prompt(node: Node, comments: list[NodeComment]) -> str:
    """The run's instruction (English, model-facing): every comment, numbered."""
    from dodaios.agent_chat.proactive_checks import NOTHING

    lines = []
    for number, comment in enumerate(comments, start=1):
        place = []
        if comment.quote:
            place.append(f'on "{_one_line(comment.quote)}"')
        if comment.where:
            place.append(f"({_one_line(comment.where)})")
        at = f" {' '.join(place)}" if place else ""
        lines.append(f"{number}.{at}: {comment.text.strip()}")
    listed = "\n".join(lines)
    return (
        f'The person left {len(comments)} comment(s) on the node "{node.title}" '
        f"(node id {node.id}, type {node.type}). Change the node as they say:\n\n"
        f"{listed}\n\n"
        f'Call the node tool with operation "get" and node "{node.id}" to see its content, '
        f'then once with operation "update", node "{node.id}" and every change together: '
        '"changes" for a few values, or the complete "spec" when most of it is new. Keep the '
        "structure and the wording of the parts the comments do not touch. Never create a "
        "second node, and do not send, change, book or delete anything outside this node.\n"
        "The person sees the change on the page, not in a chat. So when every comment is "
        f"worked in, reply with exactly {NOTHING} and nothing else. Only when a comment could "
        "not be carried out, reply with one short sentence in the person's language that "
        "says which one and why."
    )


async def send_comments(store: Any, node_id: str, comments: list[NodeComment]) -> str:
    """Start the background run that works ``comments`` into the node.

    Returns the routine's task id. Raises ``NodeError`` for an unknown node or
    no comment, ``RuntimeError`` when the society or its scheduler is not
    running.
    """
    from dodaios.agent_chat.proactive_checks import QUIET_TAG
    from dodaios.nodes.refresh import _lead, _services
    from dodaios.society.routines import build_task_spec, create_routine

    node = store.get(node_id)
    if node is None:
        raise NodeError(f"No node with id {node_id!r}.")
    kept = [c for c in comments if c.text.strip()][:MAX_COMMENTS]
    if not kept:
        raise NodeError("There is no comment to send.")
    runtime, task_store, scheduler = _services()
    lead = await _lead(runtime)
    spec = build_task_spec(
        lead,
        title=f"Comments: {node.title}",
        prompt=comments_prompt(node, kept),
        schedule={"kind": "after_delay", "delay_seconds": _START_DELAY_SECONDS},
    )
    spec = spec.model_copy(update={"tags": (*spec.tags, tag_for(node.id), QUIET_TAG)})
    task_id = await create_routine(task_store, scheduler, spec)
    log.info("node %s: %d comment(s) sent (task %s)", node.id, len(kept), task_id)
    return str(task_id)


__all__ = [
    "MAX_COMMENTS",
    "TAG_PREFIX",
    "NodeComment",
    "comments_prompt",
    "is_comments_tag",
    "send_comments",
    "tag_for",
]
