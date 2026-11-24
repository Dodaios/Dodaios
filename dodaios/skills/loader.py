"""Skill loader: Markdown file → Skill.

The YAML frontmatter is found by ONE rule (:func:`frontmatter_span`) and read
with PyYAML. The same rule is used by the code that edits a frontmatter in
place (``registry._rewrite_state_in_frontmatter``), so the block that is
edited is always the block that is read back.

Broken files are NOT raised — they land as `DRAFT` with the `error`
field set on the skill. This lets the registry show a diagnosis without
killing the whole pipeline.
"""
from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path

try:
    import yaml
    _HAVE_YAML = True
except Exception:  # pragma: no cover
    yaml = None  # type: ignore
    _HAVE_YAML = False

from pydantic import ValidationError

from .portable import adapt_portable_frontmatter
from .schema import RESOURCE_KINDS, Skill, SkillFrontmatter, SkillLifecycleState

log = logging.getLogger(__name__)

SKILL_FILENAME = "SKILL.md"


def _body_hash(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _scan_resources(skill_root: Path) -> dict[str, tuple[str, ...]]:
    """Lists the bundle-resource sibling folders (references/scripts/assets/agents).

    Returns, per kind, the list of file paths *relative to the kind folder*,
    sorted. A missing folder lands as an empty tuple — the caller doesn't need to
    carry a defaultdict. Symlinks are dereferenced (``rglob`` follows them).
    """
    out: dict[str, tuple[str, ...]] = {}
    for kind in RESOURCE_KINDS:
        kind_dir = skill_root / kind
        if not kind_dir.is_dir():
            out[kind] = ()
            continue
        files: list[str] = []
        for p in kind_dir.rglob("*"):
            if p.is_file():
                # Path relative to the kind folder, forward slashes for UI consistency
                rel = p.relative_to(kind_dir).as_posix()
                files.append(rel)
        out[kind] = tuple(sorted(files))
    return out


# A frontmatter delimiter is a LINE of three or more dashes and nothing else.
# Dashes inside the block (a quoted value, a list item, a ruler in a block
# scalar) are text. The file must open with such a line.
_FM_OPEN_RE = re.compile(r"\A-{3,}[ \t]*\r?\n")
_FM_CLOSE_RE = re.compile(r"^-{3,}[ \t]*\r?$", re.MULTILINE)


def frontmatter_span(text: str) -> tuple[int, int, int] | None:
    """Where the YAML frontmatter of a SKILL.md lies, or ``None`` without one.

    Returns ``(start, end, body_start)``: ``text[start:end]`` is the YAML
    block between the two delimiter lines and ``text[body_start:]`` is
    everything after the closing delimiter line.

    This is the only place that decides where a frontmatter ends. The loader
    reads the block it names and the state rewriter edits the block it names.
    Two readers with two rules could disagree about the same file, and then a
    line written into "the frontmatter" by one would be body text, or part of
    a quoted value, to the other.
    """
    opening = _FM_OPEN_RE.match(text)
    if opening is None:
        return None
    closing = _FM_CLOSE_RE.search(text, opening.end())
    if closing is None:
        return None
    body_start = closing.end()
    if text.startswith("\n", body_start):
        body_start += 1
    return opening.end(), closing.start(), body_start


def _split_frontmatter(text: str) -> tuple[dict, str]:
    """Splits the YAML frontmatter from the Markdown body."""
    if not _HAVE_YAML:
        raise RuntimeError("PyYAML is not installed — skill parsing not possible.")

    span = frontmatter_span(text)
    if span is None:
        return {}, text
    start, end, body_start = span
    meta = yaml.safe_load(text[start:end]) or {}
    if not isinstance(meta, dict):
        raise ValueError("Frontmatter must be a YAML mapping")
    return meta, text[body_start:].lstrip("\n")


def parse_skill(path: Path) -> Skill:
    """Loads a single SKILL.md and returns a Skill.

    Never raises — errors land in the `error` field + DRAFT state.
    """
    path = Path(path)
    resources = _scan_resources(path.parent)

    try:
        # utf-8-sig transparently strips a leading BOM (ef bb bf) if present
        # and reads plain UTF-8 otherwise. Without this a BOM would shift the
        # leading ``---`` so neither python-frontmatter nor the manual splitter
        # recognise the frontmatter, dropping the skill to DRAFT with a
        # 'name required' error (seen on dodaios-doc-author/SKILL.md).
        raw = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        return Skill(
            path=path,
            frontmatter=None,
            body="",
            state=SkillLifecycleState.DRAFT,
            body_hash="",
            error=f"read failed: {exc}",
            resources=resources,
        )

    try:
        meta, body = _split_frontmatter(raw)
    except Exception as exc:  # noqa: BLE001
        return Skill(
            path=path,
            frontmatter=None,
            body=raw,
            state=SkillLifecycleState.DRAFT,
            body_hash=_body_hash(raw),
            error=f"frontmatter parse failed: {exc}",
            resources=resources,
        )

    portable = False
    ignored_fields: tuple[str, ...] = ()
    try:
        fm = SkillFrontmatter.model_validate(meta)
    except ValidationError as exc:
        # Second reading: a SKILL.md written for the open Agent Skills format
        # instead of for Jarvis. One foreign key used to park the whole file as
        # DRAFT — installed and dead — which is the wrong answer for a
        # marketplace that carries skills from the wider ecosystem. See
        # dodaios/skills/portable.py for what does and does not cross over.
        adapted = adapt_portable_frontmatter(meta)
        if adapted is None:
            return Skill(
                path=path,
                frontmatter=None,
                body=body,
                state=SkillLifecycleState.DRAFT,
                body_hash=_body_hash(body),
                error=f"frontmatter schema invalid: {exc}",
                resources=resources,
            )
        fm = adapted.frontmatter
        portable = True
        ignored_fields = adapted.ignored
        log.info(
            "skill %s read in portable mode; ignored frontmatter fields: %s",
            path,
            ", ".join(ignored_fields) or "none",
        )

    # Payload-Check pro Trigger (pattern/combo/cron passend zum type)
    trigger_errors: list[str] = []
    for t in fm.triggers:
        trigger_errors.extend(t.validate_payload())
    if trigger_errors:
        return Skill(
            path=path,
            frontmatter=fm,
            body=body,
            state=SkillLifecycleState.DRAFT,
            body_hash=_body_hash(body),
            error="; ".join(trigger_errors),
            resources=resources,
            portable=portable,
            ignored_fields=ignored_fields,
        )

    # Phase 7.5: if the frontmatter explicitly sets `state: draft`, honor it.
    # This deterministically puts Jarvis-Agent-authored skills into the DRAFT pool
    # and excludes them from the hot-reload active filter (Plan-§AD-8).
    final_state = (
        fm.state if fm.state is not None else SkillLifecycleState.VALIDATED
    )

    return Skill(
        path=path,
        frontmatter=fm,
        body=body,
        state=final_state,
        body_hash=_body_hash(body),
        error=None,
        resources=resources,
        portable=portable,
        ignored_fields=ignored_fields,
    )


def discover_skills(root: Path) -> list[Skill]:
    """Walks `root` recursively for SKILL.md files."""
    root = Path(root)
    if not root.exists():
        return []
    skills: list[Skill] = []
    for p in root.rglob(SKILL_FILENAME):
        try:
            skills.append(parse_skill(p))
        except Exception as exc:  # noqa: BLE001
            log.warning("parse_skill failed hard for %s: %s", p, exc)
            skills.append(
                Skill(
                    path=p,
                    frontmatter=None,
                    body="",
                    state=SkillLifecycleState.DRAFT,
                    body_hash="",
                    error=f"hard failure: {exc}",
                )
            )
    return skills
