"""One-time import of the memory stores the vault replaces (ADR-0044, chunk 4).

Sources, all read-only (nothing is moved or deleted here):

- wiki vault entity pages (``entities/*.md``, the ``## Facts`` bullets) and
  active project pages (``projects/*.md``, the goal);
- the assistant's learned notebooks (``society/jarvis/USER.md``, ``MEMORY.md``);
- ``core_memory.json`` (user facts and projects; settings are skipped);
- ``workspace/USER.md`` (name, form of address, languages, time zone).

Every imported memory has ``origin="imported"`` and a source naming its
file, so the Memory section can show and filter them. The vault records that
the import ran; it never runs twice on its own.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from dodaios.memory.vault.runtime import guess_kind
from dodaios.memory.vault.store import MemoryVault

log = logging.getLogger(__name__)

META_KEY = "legacy_import"
CONFIDENCE = 0.7
MAX_CHARS = 600
DORMANT_DAYS = 45

_LINK_LABEL = re.compile(r"\[\[[^\]|]+\|([^\]]+)\]\]")
_LINK = re.compile(r"\[\[([^\]]+)\]\]")
_INFERRED = re.compile(r"\s*\*\(inferred\)\*\s*$")
_SENSITIVE = re.compile(
    r"\b(health|illness|diagnos\w*|therapy|medication|depress\w*|anxiety|heartbreak|"
    r"religio\w*|god|church|politic\w*|sexual\w*|diet)\b",
    re.I,
)
_ENTITY_KIND = {"person": "relationship", "place": "reference", "organization": "reference"}
_PROJECT_OPEN = {"active", "paused", ""}


@dataclass
class LegacyReport:
    added: int = 0
    existing: int = 0
    skipped: int = 0
    by_source: dict[str, int] = field(default_factory=dict)

    def count(self, source: str, action: str) -> None:
        if action == "added":
            self.added += 1
            self.by_source[source] = self.by_source.get(source, 0) + 1
        elif action == "existing":
            self.existing += 1
        else:
            self.skipped += 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "added": self.added,
            "existing": self.existing,
            "skipped": self.skipped,
            "by_source": dict(self.by_source),
        }


def clean(text: str) -> str:
    """Wiki markup out: links become their label, the inferred marker goes."""
    text = _LINK_LABEL.sub(r"\1", text)
    text = _LINK.sub(lambda m: m.group(1).rsplit("/", 1)[-1].replace("-", " "), text)
    text = _INFERRED.sub("", text)
    return " ".join(text.split()).strip()


def _sections(body: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current = ""
    for line in body.splitlines():
        if line.startswith("## "):
            current = line[3:].strip().casefold()
            sections.setdefault(current, [])
        elif current:
            sections[current].append(line)
    return sections


def _title(body: str, fallback: str) -> str:
    for line in body.splitlines():
        if line.startswith("# "):
            return clean(line[2:])
    return fallback.replace("-", " ").title()


def _bullets(lines: Iterable[str]) -> list[str]:
    return [clean(line.strip()[2:]) for line in lines if line.strip().startswith("- ")]


def _page(path: Path) -> tuple[dict[str, Any], str]:
    from dodaios.memory.frontmatter import parse_frontmatter

    try:
        return parse_frontmatter(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        log.info("memory vault import: could not read %s - %s", path, exc)
        return {}, ""


class _Writer:
    def __init__(self, vault: MemoryVault, report: LegacyReport) -> None:
        self.vault = vault
        self.report = report

    def add(
        self,
        text: str,
        kind: str,
        *,
        source: str,
        file: str,
        entities: Iterable[str] = (),
        ended: str | None = None,
    ) -> None:
        text = " ".join(text.split())
        if len(text) < 3:
            return
        if len(text) > MAX_CHARS:
            text = text[: MAX_CHARS - 1].rsplit(" ", 1)[0] + "…"
        try:
            result = self.vault.remember(
                text,
                kind,
                entities=tuple(entities),
                origin="imported",
                source={"via": "legacy-import", "from": source, "file": file},
                confidence=CONFIDENCE,
                sensitivity="sensitive" if _SENSITIVE.search(text) else "normal",
            )
        except ValueError as exc:
            log.info("memory vault import: skipped %r - %s", text[:60], exc)
            self.report.count(source, "skipped")
            return
        self.report.count(source, result.action)
        if ended and result.action == "added" and result.memory is not None:
            self.vault.invalidate(result.memory.id, reason="dormant", when=ended)


def _import_wiki(writer: _Writer, root: Path, user_names: set[str]) -> None:
    for path in sorted((root / "entities").glob("*.md")):
        meta, body = _page(path)
        slug = str(meta.get("slug") or path.stem)
        title = _title(body, slug)
        aliases = {str(a).casefold() for a in (meta.get("aliases") or [])}
        is_user = bool({slug.casefold(), title.casefold(), *aliases} & user_names)
        kind = "profile" if is_user else _ENTITY_KIND.get(str(meta.get("entity_kind")), "reference")
        file = f"entities/{path.name}"
        for fact in _bullets(_sections(body).get("facts", [])):
            text = fact
            if not is_user and title.casefold() not in fact.casefold():
                text = f"{title}: {fact}"
            writer.add(text, kind, source="wiki", file=file, entities=() if is_user else (title,))
    for path in sorted((root / "projects").glob("*.md")):
        meta, body = _page(path)
        if str(meta.get("status") or "").casefold() not in _PROJECT_OPEN:
            continue
        title = _title(body, str(meta.get("slug") or path.stem))
        sections = _sections(body)
        goal = " ".join(
            clean(line) for line in sections.get("goal", []) + sections.get("summary", [])
        ).strip()
        if goal:
            writer.add(
                f"{title}: {goal}",
                "project",
                source="wiki",
                file=f"projects/{path.name}",
                entities=(title,),
                ended=_dormant_since(meta, writer.vault.now()),
            )


def _dormant_since(meta: dict[str, Any], now: str) -> str | None:
    """The last activity of a project idle for over DORMANT_DAYS, else None.

    The old wiki never closed a project, so most "active" pages are months
    old one-off tasks; they arrive as history instead of current projects.
    """
    last = str(meta.get("last_activity") or meta.get("started") or "")[:10]
    try:
        idle = date.fromisoformat(now[:10]) - date.fromisoformat(last)
    except ValueError:
        return None
    return f"{last}T00:00:00+00:00" if idle.days > DORMANT_DAYS else None


def _import_notebooks(writer: _Writer, root: Path) -> None:
    from dodaios.memory.learning.notebook import JarvisNotebook

    try:
        books = JarvisNotebook(root).entries()
    except Exception as exc:  # noqa: BLE001 — a broken notebook skips this source only
        log.info("memory vault import: notebooks unreadable - %s", exc)
        return
    for target, default in (("user", "profile"), ("memory", "reference")):
        for entry in books.get(target, []):
            text = clean(str(getattr(entry, "text", "") or ""))
            kind = guess_kind(text)
            writer.add(
                text,
                kind if kind != "profile" else default,
                source="notebook",
                file=f"society/jarvis/{target.upper()}.md",
            )


def _import_core_memory(writer: _Writer, data_dir: Path) -> None:
    path = data_dir / "core_memory.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    for key, kind in (("user_facts", "profile"), ("current_projects", "project")):
        block = data.get(key)
        if not isinstance(block, dict):
            continue
        for label, value in block.items():
            values = value if isinstance(value, list) else [value]
            for item in values:
                if isinstance(item, dict):
                    item = item.get("fact") or item.get("text") or ""
                text = str(item or "").strip()
                if text:
                    writer.add(
                        text if label in ("general", "") else f"{label}: {text}",
                        kind if kind == "project" else guess_kind(text),
                        source="core-memory",
                        file="core_memory.json",
                    )


def _import_user_profile(writer: _Writer, data_dir: Path) -> None:
    from dodaios.memory.frontmatter import parse_frontmatter

    path = data_dir / "workspace" / "USER.md"
    try:
        meta, _body = parse_frontmatter(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return
    identity = meta.get("identity") if isinstance(meta.get("identity"), dict) else {}
    lines = []
    if identity.get("name"):
        lines.append(f"The user's name is {identity['name']}.")
    if identity.get("preferred_address"):
        lines.append(f"How the user wants to be addressed: {identity['preferred_address']}.")
    if identity.get("primary_language"):
        lines.append(f"The user's main language: {identity['primary_language']}.")
    languages = [str(x) for x in identity.get("languages") or [] if x]
    if languages:
        lines.append(f"The user speaks: {', '.join(languages)}.")
    if identity.get("timezone"):
        lines.append(f"The user's time zone is {identity['timezone']}.")
    for text in lines:
        writer.add(text, "profile", source="user-profile", file="workspace/USER.md")


def user_names(data_dir: Path) -> set[str]:
    """Names the user's own wiki page may carry."""
    names = {"user", "the user"}
    from dodaios.memory.frontmatter import parse_frontmatter

    try:
        meta, _ = parse_frontmatter((data_dir / "workspace" / "USER.md").read_text("utf-8"))
        name = (meta.get("identity") or {}).get("name")
        if name:
            names.add(str(name).casefold())
    except (OSError, UnicodeDecodeError, AttributeError):
        pass  # no profile file: only the generic names identify the user page
    return names


def import_legacy(vault: MemoryVault, *, wiki_root: Path | None, data_dir: Path) -> LegacyReport:
    """Copy every legacy source into ``vault``; safe to run again (it dedupes)."""
    report = LegacyReport()
    writer = _Writer(vault, report)
    _import_user_profile(writer, data_dir)
    _import_core_memory(writer, data_dir)
    if wiki_root is not None and wiki_root.is_dir():
        _import_notebooks(writer, wiki_root)
        _import_wiki(writer, wiki_root, user_names(data_dir))
    vault.set_meta(META_KEY, json.dumps({"at": vault.now(), **report.to_dict()}))
    return report


def import_once(vault: MemoryVault, *, wiki_root: Path | None, data_dir: Path) -> bool:
    """Run :func:`import_legacy` unless this vault already did; True if it ran."""
    if vault.get_meta(META_KEY) is not None:
        return False
    report = import_legacy(vault, wiki_root=wiki_root, data_dir=data_dir)
    log.info("memory vault: imported the old memory - %s", report.to_dict())
    return True
