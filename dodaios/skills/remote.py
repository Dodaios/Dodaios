"""A SKILL.md that came from somewhere else lands as a draft (AP-15).

A skill is text the assistant follows, and its frontmatter can ask for more
than that: a trigger that fires by itself, a schedule, a turn of the
conversation. A file from a link, the skill catalog or the community
marketplace is third-party content nobody on this machine has read yet, so it
never reaches the active pool on its own. It is stored with ``state: draft``
and the person switches it on in Skills (``POST /api/skills/{name}/enable``),
which is the reviewed promotion every other draft goes through.

:func:`hold_as_draft` is the one place that makes this true for every route
that stores remote text: it stamps the state and then asks the loader, the
same reader the registry uses, what the stamped file IS. Only a file that
reads back as a draft with a usable frontmatter is handed on. The check runs
on a copy in a scratch folder, so a refused file leaves nothing behind in the
skills directory.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from .loader import SKILL_FILENAME, parse_skill
from .schema import Skill, SkillLifecycleState

__all__ = ["MAX_REMOTE_SKILL_BYTES", "RemoteSkillRefused", "hold_as_draft"]

#: Ceiling for a downloaded SKILL.md. A skill is prose; the limit exists so a
#: hostile address cannot stream megabytes into the skills folder, not because
#: real files come close to it. Same size the store uses when it shows an
#: entry's files before the install.
MAX_REMOTE_SKILL_BYTES = 256 * 1024


class RemoteSkillRefused(RuntimeError):
    """A downloaded skill that must not be stored; the message is user-facing."""


def hold_as_draft(content: str) -> tuple[str, Skill]:
    """``content`` with ``state: draft`` set, and how the loader reads it.

    Returns ``(text to store, parsed skill)``. Raises
    :class:`RemoteSkillRefused` when the text is too large, is not a readable
    skill, or would not load as a draft once stored.
    """
    from .registry import _rewrite_state_in_frontmatter

    if len(content.encode("utf-8")) > MAX_REMOTE_SKILL_BYTES:
        raise RemoteSkillRefused(
            f"SKILL.md is larger than {MAX_REMOTE_SKILL_BYTES // 1024} KB."
        )
    # No byte-order mark and one line-break style, so the copy checked here
    # and the file written afterwards are read the same way on every platform.
    text = content.removeprefix("﻿").replace("\r\n", "\n").replace("\r", "\n")
    stamped = _rewrite_state_in_frontmatter(text, SkillLifecycleState.DRAFT.value)

    with tempfile.TemporaryDirectory(prefix="dodaios-skill-") as scratch:
        staged = Path(scratch) / "skill" / SKILL_FILENAME
        staged.parent.mkdir()
        staged.write_text(stamped, encoding="utf-8")
        parsed = parse_skill(staged)

    if parsed.frontmatter is None:
        raise RemoteSkillRefused(f"SKILL.md could not be read: {parsed.error}")
    if parsed.state is not SkillLifecycleState.DRAFT:
        # The stamp did not hold. Nothing downloaded may become live by the
        # way its frontmatter is written, so the file is not stored at all.
        raise RemoteSkillRefused(
            "SKILL.md could not be stored as a draft: its frontmatter does not "
            "keep the state it was given."
        )
    return stamped, parsed
