"""A linked, path-addressed model of the whole vault for the Memory section.

The older slug-addressed routes treat ``path.stem`` as a page's identity.
That breaks as soon as two files share a name, and the vault has 100+ agent
notebooks that are all called ``MEMORY.md`` and ``USER.md``: every one of
them resolved to the first match. This model keys every page by its
vault-relative POSIX path instead and keeps the slug only as a link target.

It is built from pages the route layer has already scanned and parsed, so
it does no I/O of its own. Everything is deterministic: link resolution,
mentions, related pages and empty-page detection are plain text work, never
a model call (AP-9/AP-11), so building it costs no key.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

import yaml

from dodaios.memory.wiki.wikilink import SEARCHABLE_DIRS, extract_wikilinks

#: Root pages that document or log the memory itself rather than hold
#: knowledge. They stay readable but never count as links or graph nodes:
#: ``log.md`` alone used to contribute ~2,100 of 2,244 "links".
SYSTEM_ROOT_PAGES: frozenset[str] = frozenset({"log.md", "memory.md", "schema.md", "index.md"})
TEMPLATE_DIRS: frozenset[str] = frozenset({"templates", "_templates", "99-templates"})
SOCIETY_DIR = "society"
NOTEBOOK_FILES: dict[str, str] = {"memory.md": "memory", "user.md": "profile"}

_DIR_KINDS: dict[str, str] = {
    "entities": "entity",
    "concepts": "concept",
    "projects": "project",
    "sessions": "session",
    "people": "person",
}
_TYPE_KINDS: dict[str, str] = {
    "entity": "entity",
    "concept": "concept",
    "project": "project",
    "session": "session",
    "person": "person",
}

_FRONTMATTER_RE = re.compile(r"\A﻿?---\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.DOTALL)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.*)$")
_RULE_RE = re.compile(r"^\s{0,3}(?:[-*_]\s*){3,}$")
_EMPTY_BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s*(?:\[[ xX]?\]\s*)?$")
_WORD_RE = re.compile(r"\w", re.UNICODE)
_LINK_TOKEN_RE = re.compile(r"(?<!\\)!?\[\[([^\]\n]+)\]\]")
_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_SNIPPET_RADIUS = 90
_SUMMARY_MAX = 220
#: Shortest title a plain-text mention may match. Shorter names ("AI", "Lea")
#: collide with ordinary words far too often to be worth a link.
_MENTION_MIN_CHARS = 4
_RELATED_LIMIT = 8


# ---------------------------------------------------------------- frontmatter


def read_properties(raw: str) -> dict[str, Any]:
    """Parse a page's YAML frontmatter into plain JSON-safe values.

    The page parser keeps frontmatter as ``key: value`` strings, which turns
    block lists (``aliases:`` followed by ``- the user``) into empty strings.
    Properties shown to a reader need the real values, so this parses the
    block with a YAML loader and falls back to the flat strings on bad YAML.
    """
    match = _FRONTMATTER_RE.match(raw)
    if not match:
        return {}
    block = match.group(1)
    try:
        loaded = yaml.safe_load(block)
    except yaml.YAMLError:  # silent-ok: hand-edited YAML falls back to the flat key: value read
        loaded = None
    if not isinstance(loaded, dict):
        flat: dict[str, Any] = {}
        for line in block.splitlines():
            key, sep, value = line.partition(":")
            if sep and key.strip() and not line.startswith((" ", "-")):
                flat[key.strip()] = value.strip()
        return flat
    return {str(key): _json_safe(value) for key, value in loaded.items()}


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    return str(value)


def _string_list(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        value = [part for part in re.split(r"[,\n]", value.strip("[] ")) if part.strip()]
    if not isinstance(value, list):
        return ()
    return tuple(str(item).strip().strip("'\"") for item in value if str(item).strip())


# --------------------------------------------------------------------- input


@dataclass(frozen=True, slots=True)
class SourcePage:
    """One scanned page as the route layer hands it in."""

    path: str
    body: str
    properties: Mapping[str, Any]
    page_type: str
    mtime: float
    size: int


@dataclass(frozen=True, slots=True)
class AgentInfo:
    """What the roster knows about an agent that owns a notebook folder."""

    agent_id: str
    name: str
    state: str  # active | archived | orphan


# -------------------------------------------------------------------- output


@dataclass(slots=True)
class PageRecord:
    path: str
    slug: str
    title: str
    kind: str
    group: str
    folder: str
    agent_id: str | None
    mtime: float
    size: int
    words: int
    empty: bool
    summary: str
    aliases: tuple[str, ...]
    tags: tuple[str, ...]
    body: str = field(repr=False)
    properties: Mapping[str, Any] = field(repr=False)

    def summary_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "slug": self.slug,
            "title": self.title,
            "kind": self.kind,
            "group": self.group,
            "folder": self.folder,
            "agent_id": self.agent_id,
            "mtime": self.mtime,
            "words": self.words,
            "empty": self.empty,
            "summary": self.summary,
            "tags": list(self.tags),
        }


@dataclass(frozen=True, slots=True)
class Link:
    source: str
    target: str | None
    raw: str
    kind: str  # link | mention
    context: str


@dataclass(slots=True)
class VaultModel:
    pages: dict[str, PageRecord]
    links: list[Link]
    agents: dict[str, AgentInfo]
    outgoing: dict[str, list[Link]]
    incoming: dict[str, list[Link]]
    resolver: _Resolver = field(repr=False)

    # ------------------------------------------------------------- queries

    def resolve(self, raw: str, source_path: str) -> str | None:
        """Which page a ``[[raw]]`` link written on ``source_path`` opens."""
        source = self.pages.get(source_path)
        if source is None:
            return None
        return self.resolver.resolve(raw, source)

    def rewrite_links(
        self, source_path: str, old_path: str, new_target: str, *, body: str | None = None
    ) -> tuple[str, int]:
        """``source_path``'s body with every link to ``old_path`` pointed at ``new_target``.

        ``body`` is the text to rewrite when the caller has a fresher copy than
        the model's; links resolve as they would on ``source_path``.

        ``new_target`` is the renamed page's vault path without ``.md``. A
        link written as a bare name stays a bare name; one with a folder
        keeps the folder form. Aliases (``|label``) and heading anchors
        (``#part``) survive untouched.
        """
        source = self.pages[source_path]
        count = 0

        def _swap(match: re.Match[str]) -> str:
            nonlocal count
            inner = match.group(1)
            if self.resolver.resolve(inner, source) != old_path:
                return match.group(0)
            target, bar, alias = inner.partition("|")
            name, hash_, anchor = target.partition("#")
            replacement = new_target if "/" in name else new_target.rsplit("/", 1)[-1]
            count += 1
            embed = "!" if match.group(0).startswith("!") else ""
            return f"{embed}[[{replacement}{hash_}{anchor}{bar}{alias}]]"

        return _LINK_TOKEN_RE.sub(_swap, source.body if body is None else body), count

    def stats(self) -> dict[str, int]:
        content = [p for p in self.pages.values() if p.group != "system"]
        resolved = [link for link in self.links if link.kind == "link" and link.target]
        return {
            "pages": len(content),
            "content_pages": sum(1 for p in content if not p.empty),
            "empty_pages": sum(1 for p in content if p.empty),
            "links": len(resolved),
            "mentions": sum(1 for link in self.links if link.kind == "mention"),
            "broken_links": sum(
                1 for link in self.links if link.kind == "link" and not link.target
            ),
        }

    def degree(self, path: str) -> int:
        return len({link.target for link in self.outgoing.get(path, []) if link.target}) + len(
            {link.source for link in self.incoming.get(path, [])}
        )

    def related(self, path: str, *, limit: int = _RELATED_LIMIT) -> list[dict[str, Any]]:
        """Pages two steps away through a shared neighbour, best first.

        A neighbour with many connections (a hub everyone links) says little
        about two pages that both touch it, so each shared neighbour adds
        ``1 / log(2 + degree)``.
        """
        direct = self._neighbours(path)
        scores: dict[str, float] = defaultdict(float)
        via: dict[str, str] = {}
        for neighbour in direct:
            weight = 1.0 / math.log(2 + self.degree(neighbour))
            for candidate in self._neighbours(neighbour):
                if candidate == path or candidate in direct:
                    continue
                record = self.pages.get(candidate)
                if record is None or record.empty or record.group == "system":
                    continue
                scores[candidate] += weight
                if candidate not in via or weight > scores[candidate] - weight:
                    via[candidate] = neighbour
        ranked = sorted(scores.items(), key=lambda item: (-item[1], self.pages[item[0]].title))
        return [
            {
                **self._ref(candidate),
                "score": round(score, 3),
                "via": self._ref(via[candidate]) if via.get(candidate) in self.pages else None,
            }
            for candidate, score in ranked[:limit]
        ]

    def page_links(self, path: str) -> dict[str, list[dict[str, Any]]]:
        """The four link lists the reader's side rail shows for one page."""
        outgoing: list[dict[str, Any]] = []
        mentions: list[dict[str, Any]] = []
        seen_out: set[tuple[str | None, str]] = set()
        for link in self.outgoing.get(path, []):
            # ``raw`` is kept per spelling so the reader can map every
            # ``[[written form]]`` in the body to the page it opens.
            key = (link.target, link.raw)
            if key in seen_out:
                continue
            seen_out.add(key)
            if link.kind == "mention":
                if any(m["path"] == link.target for m in mentions):
                    continue
                mentions.append({**self._ref(link.target or ""), "context": link.context})
            elif link.target:
                outgoing.append({**self._ref(link.target), "broken": False, "raw": link.raw})
            else:
                outgoing.append(
                    {
                        "path": None,
                        "title": _display_raw(link.raw),
                        "kind": None,
                        "broken": True,
                        "raw": link.raw,
                    }
                )
        backlinks: list[dict[str, Any]] = []
        mentioned_in: list[dict[str, Any]] = []
        seen_in: set[tuple[str, str]] = set()
        for link in self.incoming.get(path, []):
            key = (link.source, link.kind)
            if key in seen_in or link.source == path:
                continue
            seen_in.add(key)
            target = backlinks if link.kind == "link" else mentioned_in
            target.append({**self._ref(link.source), "context": link.context})
        backlinks.sort(key=lambda item: -self.pages[item["path"]].mtime)
        mentioned_in.sort(key=lambda item: -self.pages[item["path"]].mtime)
        return {
            "outgoing": outgoing,
            "backlinks": backlinks,
            "mentions": mentions,
            "mentioned_in": mentioned_in,
        }

    def graph(self, *, include_agents: bool = True) -> dict[str, Any]:
        visible = {
            path
            for path, record in self.pages.items()
            if record.group != "system"
            and not record.empty
            and (include_agents or record.group != "agents")
        }
        edges: dict[tuple[str, str], str] = {}
        for link in self.links:
            if link.target is None or link.source not in visible or link.target not in visible:
                continue
            if link.source == link.target:
                continue
            key = (link.source, link.target)
            # A real link outranks a plain-text mention of the same pair.
            if edges.get(key) != "link":
                edges[key] = link.kind
        degree: dict[str, int] = defaultdict(int)
        for source, target in edges:
            degree[source] += 1
            degree[target] += 1
        nodes = [
            {
                "id": path,
                "title": self.pages[path].title,
                "kind": self.pages[path].kind,
                "group": self.pages[path].group,
                "agent_id": self.pages[path].agent_id,
                "degree": degree.get(path, 0),
            }
            for path in sorted(visible)
        ]
        return {
            "nodes": nodes,
            "edges": [
                {"source": source, "target": target, "kind": kind}
                for (source, target), kind in sorted(edges.items())
            ],
        }

    # ------------------------------------------------------------ internals

    def _neighbours(self, path: str) -> set[str]:
        out = {link.target for link in self.outgoing.get(path, []) if link.target}
        inc = {link.source for link in self.incoming.get(path, [])}
        return {p for p in (out | inc) if p != path and p in self.pages}

    def _ref(self, path: str) -> dict[str, Any]:
        record = self.pages.get(path)
        if record is None:
            return {"path": path, "title": path, "kind": None, "group": None, "empty": True}
        return {
            "path": record.path,
            "title": record.title,
            "kind": record.kind,
            "group": record.group,
            "empty": record.empty,
            "agent_id": record.agent_id,
        }


# ------------------------------------------------------------------ building


def build_model(
    sources: Iterable[SourcePage], agents: Mapping[str, AgentInfo] | None = None
) -> VaultModel:
    """Classify, title and interlink every page of one scan."""
    known_agents = dict(agents or {})
    pages: dict[str, PageRecord] = {}
    folder_agents: dict[str, AgentInfo] = {}
    for source in sources:
        record = _record(source, known_agents)
        pages[record.path] = record
        if record.agent_id and (
            record.agent_id not in folder_agents
            or folder_agents[record.agent_id].name == _humanise(record.agent_id)
        ):
            folder_agents[record.agent_id] = known_agents.get(record.agent_id) or AgentInfo(
                agent_id=record.agent_id,
                name=_notebook_owner(record) or _humanise(record.agent_id),
                state="orphan",
            )
    for record in pages.values():
        if record.agent_id and record.kind in ("memory", "profile"):
            info = folder_agents[record.agent_id]
            record.title = f"{info.name} · {'Memory' if record.kind == 'memory' else 'Profile'}"

    resolver = _Resolver(pages)
    links: list[Link] = []
    for record in pages.values():
        if record.group == "system":
            continue
        linked_targets: set[str] = set()
        for raw in extract_wikilinks(record.body):
            target = resolver.resolve(raw, record)
            if target == record.path:
                continue
            if target:
                linked_targets.add(target)
            links.append(
                Link(
                    source=record.path,
                    target=target,
                    raw=raw,
                    kind="link",
                    context=_context(record.body, f"[[{raw}"),
                )
            )
        for target, needle in resolver.mentions(record, linked_targets):
            links.append(
                Link(
                    source=record.path,
                    target=target,
                    raw=needle,
                    kind="mention",
                    context=_context(record.body, needle),
                )
            )

    outgoing: dict[str, list[Link]] = defaultdict(list)
    incoming: dict[str, list[Link]] = defaultdict(list)
    for link in links:
        outgoing[link.source].append(link)
        if link.target:
            incoming[link.target].append(link)
    return VaultModel(
        pages=pages,
        links=links,
        agents=folder_agents,
        outgoing=dict(outgoing),
        incoming=dict(incoming),
        resolver=resolver,
    )


def _record(source: SourcePage, agents: Mapping[str, AgentInfo]) -> PageRecord:
    rel = PurePosixPath(source.path)
    parts = rel.parts
    top = parts[0].casefold() if len(parts) > 1 else ""
    name = rel.name
    folder = rel.parent.as_posix() if len(parts) > 1 else ""
    properties = dict(source.properties)
    agent_id: str | None = None

    if not top and name.casefold() in SYSTEM_ROOT_PAGES:
        group, kind = "system", "system"
    elif top in TEMPLATE_DIRS:
        group, kind = "system", "template"
    elif top == SOCIETY_DIR and len(parts) >= 3 and parts[1].casefold() != "shared":
        group = "agents"
        agent_id = parts[1]
        kind = NOTEBOOK_FILES.get(name.casefold(), "note") if len(parts) == 3 else "note"
    elif top == SOCIETY_DIR:
        group, kind = "agents", "shared"
    elif top == "sessions":
        group, kind = "journal", "session"
    else:
        group = "knowledge"
        kind = (
            _TYPE_KINDS.get(str(properties.get("type") or source.page_type or ""))
            or _DIR_KINDS.get(top)
            or "note"
        )

    body = source.body
    clean = readable_body(body)
    words = len(clean.split())
    title = _title(properties, body, rel.stem)
    aliases = _string_list(properties.get("aliases"))
    tags = _string_list(properties.get("tags"))
    return PageRecord(
        path=rel.as_posix(),
        slug=rel.stem,
        title=title,
        kind=kind,
        group=group,
        folder=folder,
        agent_id=agent_id,
        mtime=source.mtime,
        size=source.size,
        words=words,
        empty=is_empty_body(body),
        summary=_summary(clean),
        aliases=aliases,
        tags=tags,
        body=body,
        properties=properties,
    )


def readable_body(body: str) -> str:
    """The body without HTML comments (entry bookkeeping) and blank runs."""
    text = _COMMENT_RE.sub("", body)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def is_empty_body(body: str) -> bool:
    """True when a body has no prose: only headings, rules, comments, blanks.

    Frontmatter-only stubs and profile skeletons (headings with nothing under
    them) count as empty; a single real sentence does not.
    """
    for line in _COMMENT_RE.sub("", body).splitlines():
        stripped = line.strip()
        if not stripped or _HEADING_RE.match(line) or _RULE_RE.match(line):
            continue
        if _EMPTY_BULLET_RE.match(line):
            continue
        if _WORD_RE.search(stripped):
            return False
    return True


def _title(properties: Mapping[str, Any], body: str, stem: str) -> str:
    candidates = [str(properties.get("title") or "")]
    for line in body.splitlines():
        match = _HEADING_RE.match(line)
        if match and line.lstrip().startswith("# "):
            candidates.append(match.group(1))
            break
    for candidate in candidates:
        candidate = candidate.strip().strip("\"'")
        if candidate and "{{" not in candidate:
            return candidate
    return _humanise(stem)


def _notebook_owner(record: PageRecord) -> str:
    """The agent name a notebook's own title recorded (``"Vega — memory"``).

    The roster forgets agents that were removed outright; their notebooks
    still carry the name they were created under.
    """
    if record.kind not in ("memory", "profile"):
        return ""
    title = str(record.properties.get("title") or "").strip().strip("\"'")
    for suffix in (" — memory", " — user profile", " - memory", " - user profile"):
        if title.casefold().endswith(suffix):
            return title[: -len(suffix)].strip()
    return ""


def _humanise(stem: str) -> str:
    text = stem.replace("-", " ").replace("_", " ").strip()
    return text[:1].upper() + text[1:] if text else stem


def _summary(clean: str) -> str:
    """First prose paragraph, flattened, without Markdown decoration."""
    for block in re.split(r"\n\s*\n", clean):
        lines = [
            line
            for line in block.splitlines()
            if line.strip() and not _HEADING_RE.match(line) and not _RULE_RE.match(line)
        ]
        if not lines:
            continue
        text = " ".join(line.strip().lstrip("-*+> ").strip() for line in lines)
        text = _LINK_TOKEN_RE.sub(lambda m: _display_raw(m.group(1)), text)
        text = _MD_LINK_RE.sub(r"\1", text)
        text = re.sub(r"[*_`]+", "", text)
        text = " ".join(text.split())
        if not _WORD_RE.search(text):
            continue
        if len(text) > _SUMMARY_MAX:
            text = text[:_SUMMARY_MAX].rsplit(" ", 1)[0] + "…"
        return text
    return ""


def _display_raw(raw: str) -> str:
    target, _, alias = raw.partition("|")
    if alias.strip():
        return alias.strip()
    return target.strip().split("#", 1)[0].rsplit("/", 1)[-1].removesuffix(".md")


def _context(body: str, needle: str) -> str:
    # Comments go first, whole: cut mid-way by the window, notebook entry
    # markers would otherwise leak into the snippet as raw JSON.
    body = _COMMENT_RE.sub(" ", body)
    idx = body.find(needle)
    if idx < 0:
        idx = body.casefold().find(needle.casefold())
    if idx < 0:
        return ""
    start = max(0, idx - _SNIPPET_RADIUS)
    end = min(len(body), idx + len(needle) + _SNIPPET_RADIUS)
    text = body[start:end]
    text = _LINK_TOKEN_RE.sub(lambda m: _display_raw(m.group(1)), text)
    text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
    text = " ".join(text.split())
    if start > 0:
        text = "…" + text
    if end < len(body):
        text += "…"
    return text


class _Resolver:
    """Obsidian-style link resolution over path, file name, title and alias."""

    def __init__(self, pages: Mapping[str, PageRecord]) -> None:
        self._pages = pages
        self._by_path: dict[str, str] = {}
        self._by_stem: dict[str, list[str]] = defaultdict(list)
        self._by_name: dict[str, list[str]] = defaultdict(list)
        for path, record in pages.items():
            self._by_path[path.casefold().removesuffix(".md")] = path
            self._by_stem[record.slug.casefold()].append(path)
            if record.group == "knowledge":
                for name in (record.title, *record.aliases):
                    key = name.strip().casefold()
                    if key:
                        self._by_name[key].append(path)
        self._mention_index = self._build_mentions()

    def resolve(self, raw: str, source: PageRecord) -> str | None:
        target = raw.split("|", 1)[0].split("#", 1)[0].strip().replace("\\", "/")
        target = target.removesuffix(".md").strip("/")
        if not target:
            return None
        key = target.casefold()
        if "/" in key:
            if key in self._by_path:
                return self._by_path[key]
            key = key.rsplit("/", 1)[-1]
        candidates = self._by_stem.get(key) or self._by_name.get(key) or []
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]
        return min(candidates, key=lambda path: self._rank(path, source))

    def _rank(self, path: str, source: PageRecord) -> tuple[int, int, str]:
        record = self._pages[path]
        same_folder = 0 if record.folder == source.folder else 1
        top = path.split("/", 1)[0] if "/" in path else ""
        dir_rank = SEARCHABLE_DIRS.index(top) if top in SEARCHABLE_DIRS else len(SEARCHABLE_DIRS)
        return same_folder, dir_rank, path

    def _build_mentions(self) -> list[tuple[re.Pattern[str], str, str]]:
        """One pattern per knowledge name that is distinctive enough to match.

        Multi-word names match case-insensitively; a single word only as
        written, so the person "Ruben" links while the word "memory" in
        running text does not pull in a page titled "Memory".
        """
        names: dict[str, set[str]] = defaultdict(set)
        for path, record in self._pages.items():
            if record.group != "knowledge" or record.empty:
                continue
            for name in (record.title, *record.aliases):
                name = name.strip()
                if len(name) >= _MENTION_MIN_CHARS and _WORD_RE.search(name):
                    names[name].add(path)
        out: list[tuple[re.Pattern[str], str, str]] = []
        for name, paths in names.items():
            if len(paths) != 1:
                continue  # ambiguous plain text is not a link
            flags = re.IGNORECASE if " " in name else 0
            pattern = re.compile(rf"(?<![\w\[/]){re.escape(name)}(?![\w\]])", flags)
            out.append((pattern, name, next(iter(paths))))
        out.sort(key=lambda item: -len(item[1]))
        return out

    def mentions(
        self, record: PageRecord, already_linked: set[str]
    ) -> list[tuple[str, str]]:
        if record.empty or record.group == "system":
            return []
        text = _LINK_TOKEN_RE.sub(" ", _COMMENT_RE.sub(" ", record.body))
        found: list[tuple[str, str]] = []
        seen = set(already_linked) | {record.path}
        for pattern, _name, target in self._mention_index:
            if target in seen:
                continue
            match = pattern.search(text)
            if match:
                seen.add(target)
                found.append((target, match.group(0)))
        return found


__all__ = [
    "AgentInfo",
    "Link",
    "PageRecord",
    "SourcePage",
    "VaultModel",
    "build_model",
    "is_empty_body",
    "read_properties",
    "readable_body",
]
