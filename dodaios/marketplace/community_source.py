"""Fetch and cache the community marketplace index.

The registry repo (Dodaios/marketplace) compiles every published
plugin, skill and agent template into one static ``index.json`` served from
GitHub Pages.
This module is the app's only reader of that feed: fetch with short
timeouts, validate into typed models, and persist the result under
``data/marketplace_index.json`` so browsing keeps working offline and on a
headless box (same doctrine as the seed catalogs).

Never called on the boot critical path (contract §7) — the Plugins view
triggers a TTL-gated refresh when it opens, plus an explicit refresh button.

Three things keep reading cheap:

- The parsed index is held in memory and reused as long as the cache file on
  disk is the one it was read from, so a poll costs a ``stat`` instead of
  parsing and validating the whole feed again.
- ``get_index(background=True)`` answers from an expired cache at once and
  revalidates behind the response. The store opens in milliseconds; the next
  poll shows what the revalidation brought.
- After a failed fetch the network is left alone for a short while. An
  offline machine then answers "stale" at once instead of waiting for the
  connect timeout on every poll.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from dodaios.core.http_guard import https_only_async

logger = logging.getLogger(__name__)

# Repo-root data/ — same resolution as dodaios/marketplace/catalog_data.py.
_CACHE_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "marketplace_index.json"

_FETCH_TIMEOUT = httpx.Timeout(connect=3.0, read=10.0, write=10.0, pool=10.0)
# How long a fetched index stays fresh before the next read revalidates it.
# The refresh endpoint bypasses this. Two minutes, not fifteen: the store view
# polls while it is open so a fresh publish shows up on its own, and the
# revalidation is a conditional GET (If-None-Match) — GitHub Pages answers a
# 304 with no body when nothing changed, so the short TTL costs the host a
# few hundred bytes per window, not a re-download of the index.
_CACHE_TTL_SECONDS = 120.0

# After a failed fetch, how long reads answer from what they have instead of
# trying the network again. Short: it only has to cover the polls of an open
# store, and the refresh button bypasses it.
_FAILURE_BACKOFF_SECONDS = 30.0

# One in-process fetch at a time — a double view-open must not race two
# downloads into the same cache file.
_fetch_lock = asyncio.Lock()

# The parsed cache file, kept as long as the file itself is unchanged:
# ``((path, mtime_ns, size), (fetched_at, index, etag))``.
_memory: tuple[tuple[str, int, int], tuple[float, CommunityIndex, str | None]] | None = None
# When the last fetch failed (``time.monotonic()``), or None.
_last_failure: float | None = None
# The running background revalidation, if any. Held so it is not collected
# mid-flight and so a second poll does not start another one.
_revalidation: asyncio.Task[None] | None = None


class _Tolerant(BaseModel):
    """``extra="allow"``: the index is produced by a NEWER registry than this
    client may be — unknown fields must never break browsing (BUG-016 class
    is catalog files rejected wholesale over one new field)."""

    model_config = ConfigDict(extra="allow")


class CommunityPluginEntry(_Tolerant):
    name: str
    publisher: str | None = None
    #: The publisher's numeric GitHub id. A login can be renamed and the freed
    #: handle re-registered by somebody else; the number stays with the account.
    publisher_id: int | None = None
    #: The registry's own pick: the store leads with these.
    featured: bool = False
    version: str | None = None
    published_at: str | None = None
    source_url: str | None = None
    # The raw Agent Plugins v1.0.0 manifests, embedded verbatim. Conversion
    # to a PluginSpec happens at INSTALL time (agent_plugins_loader), so a
    # malformed community entry degrades to one uninstallable card instead of
    # taking the whole index down.
    plugin_json: dict[str, Any]
    mcp_json: dict[str, Any] | None = None
    usage_card: str | None = None


# The Agent Plugins name rules (same as agent_plugins_loader.validate_spec_name
# and the registry CI). A skill's name later becomes a DIRECTORY under the
# user's skills folder, so this is a security boundary, not cosmetics: a name
# like "../../evil" or "C:/anywhere" must never survive index validation.
_SKILL_NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9.-]{0,62}[a-z0-9])?$")


# The two frontmatter profiles a published skill can carry. ``jarvis`` is this
# app's own schema (triggers, risk policy, execution mode); ``portable`` is a
# plain Agent Skill written for the open ecosystem — the format `npx skills`
# and every SKILL.md-reading agent consumes. Anything else is treated as
# unknown and falls back to ``jarvis``, which is what every entry published
# before the split was.
SKILL_FLAVORS: frozenset[str] = frozenset({"jarvis", "portable"})

# Ceilings for the publisher-written compatibility list. It is free text from
# an auto-merged submission that lands in the store UI, so it is bounded here
# rather than trusted: a hundred entries of a thousand characters each is a
# layout attack, not a fact about the skill.
_MAX_COMPATIBLE_AGENTS = 8
_MAX_AGENT_NAME_LEN = 32


class CommunitySkillEntry(_Tolerant):
    name: str
    title: str | None = None
    description: str = ""
    publisher: str | None = None
    publisher_id: int | None = None
    featured: bool = False
    version: str | None = None
    published_at: str | None = None
    categories: list[str] = Field(default_factory=list)
    source_url: str | None = None
    # Direct download of the SKILL.md — consumed by the existing
    # /api/skills/catalog/install route.
    raw_url: str | None = None
    #: Which frontmatter the SKILL.md carries (see ``SKILL_FLAVORS``). Absent
    #: on an index published by an older registry — the reader treats a missing
    #: value exactly like ``"jarvis"``.
    flavor: str | None = None
    #: Agents the publisher states the skill works in ("Claude Code", "Cursor",
    #: …). Display only: nothing in the app branches on it.
    compatible_agents: list[str] = Field(default_factory=list)

    @field_validator("raw_url")
    @classmethod
    def _https_only(cls, value: str | None) -> str | None:
        # The backend fetches this URL server-side at install time. Anything
        # but https is an SSRF vector (metadata endpoints, LAN admin pages),
        # so a non-https URL degrades the entry to "Manual" instead of being
        # fetched. The finder re-checks before the actual download.
        if value is not None and not value.lower().startswith("https://"):
            logger.warning("community index: dropping non-https raw_url %r", value)
            return None
        return value

    @field_validator("flavor")
    @classmethod
    def _known_flavor(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip().lower()
        if cleaned in SKILL_FLAVORS:
            return cleaned
        # A newer registry may invent a third profile. Forgetting the word is
        # right: the entry stays browsable and installable under the default,
        # instead of the whole index failing over one unknown string.
        logger.warning("community index: unknown skill flavor %r", value)
        return None

    @field_validator("compatible_agents", mode="before")
    @classmethod
    def _clean_agents(cls, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        cleaned: list[str] = []
        for item in value:
            if not isinstance(item, str):
                continue
            name = " ".join(item.split())[:_MAX_AGENT_NAME_LEN].strip()
            if name and name not in cleaned:
                cleaned.append(name)
            if len(cleaned) >= _MAX_COMPATIBLE_AGENTS:
                break
        return cleaned

    @property
    def is_portable(self) -> bool:
        """True when the SKILL.md is a plain Agent Skill, not a Jarvis one."""
        return self.flavor == "portable"


class CommunityAgentEntry(_Tolerant):
    """A published agent template (``kind: "agent"`` in the registry).

    ``agent`` is the template verbatim. It is validated at INSTALL time by
    ``dodaios.society.agent_template`` — the same rule the publisher's app
    applied — so one malformed entry degrades to one uninstallable card.
    """

    name: str
    title: str | None = None
    description: str = ""
    publisher: str | None = None
    publisher_id: int | None = None
    featured: bool = False
    version: str | None = None
    published_at: str | None = None
    categories: list[str] = Field(default_factory=list)
    source_url: str | None = None
    agent: dict[str, Any] = Field(default_factory=dict)


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class CommunityLookEntry(_Tolerant):
    """A published look (``kind: "look"``, docs/looks.md).

    The registry pins the archive's SHA-256 and size; the app downloads only
    from the hosts ``dodaios.ui.looks.install.ALLOWED_HOSTS`` names and checks
    the archive again as a pack before anything is unpacked into place.
    """

    name: str
    title: str | None = None
    description: str = ""
    publisher: str | None = None
    publisher_id: int | None = None
    featured: bool = False
    version: str | None = None
    published_at: str | None = None
    license: str | None = None
    attribution: str | None = None
    source_url: str | None = None
    preview_url: str | None = None
    archive_url: str
    sha256: str
    size_bytes: int

    @field_validator("name")
    @classmethod
    def _look_id(cls, value: str) -> str:
        from dodaios.ui.looks.manifest import LOOK_ID_RE, RESERVED_IDS

        if not LOOK_ID_RE.fullmatch(value) or value in RESERVED_IDS:
            raise ValueError("not a look id")
        return value

    @field_validator("archive_url")
    @classmethod
    def _archive_host(cls, value: str) -> str:
        from dodaios.ui.looks.install import allowed_url

        if not allowed_url(value):
            raise ValueError("archive_url must be https on an allowed host")
        return value

    @field_validator("preview_url")
    @classmethod
    def _preview_host(cls, value: str | None) -> str | None:
        from dodaios.ui.looks.install import allowed_url

        # A preview from anywhere else is dropped, never fetched.
        return value if value is None or allowed_url(value) else None

    @field_validator("sha256")
    @classmethod
    def _hex_digest(cls, value: str) -> str:
        value = value.strip().lower()
        if not _SHA256_RE.fullmatch(value):
            raise ValueError("sha256 must be 64 hex digits")
        return value

    @field_validator("size_bytes")
    @classmethod
    def _size(cls, value: int) -> int:
        from dodaios.ui.looks.install import MAX_ARCHIVE_BYTES

        if not 0 < value <= MAX_ARCHIVE_BYTES:
            raise ValueError("size_bytes is out of range")
        return value


class CommunityIndex(_Tolerant):
    revision: int = 0
    generated_at: str | None = None
    plugins: list[CommunityPluginEntry] = Field(default_factory=list)
    skills: list[CommunitySkillEntry] = Field(default_factory=list)
    #: Absent on an index from a registry older than agent templates.
    agents: list[CommunityAgentEntry] = Field(default_factory=list)
    #: Absent on an index from a registry older than looks.
    looks: list[CommunityLookEntry] = Field(default_factory=list)

    @field_validator("looks", mode="before")
    @classmethod
    def _drop_invalid_looks(cls, value: Any) -> list[Any]:
        if not isinstance(value, list):
            return []
        kept: list[Any] = []
        for item in value:
            try:
                kept.append(CommunityLookEntry.model_validate(item))
            except ValidationError as exc:
                # One bad entry costs exactly itself, never the whole index.
                name = item.get("name") if isinstance(item, dict) else None
                logger.warning("community index: dropping look %r: %s", name, exc.errors()[:1])
        return kept

    @field_validator("agents", mode="after")
    @classmethod
    def _drop_unsafe_agent_names(
        cls, value: list[CommunityAgentEntry]
    ) -> list[CommunityAgentEntry]:
        kept: list[CommunityAgentEntry] = []
        for entry in value:
            if _SKILL_NAME_RE.fullmatch(entry.name) and ".." not in entry.name:
                kept.append(entry)
            else:
                logger.warning("community index: dropping agent with unsafe name %r", entry.name)
        return kept

    @field_validator("skills", mode="after")
    @classmethod
    def _drop_unsafe_skill_names(
        cls, value: list[CommunitySkillEntry]
    ) -> list[CommunitySkillEntry]:
        kept: list[CommunitySkillEntry] = []
        for entry in value:
            if _SKILL_NAME_RE.fullmatch(entry.name) and ".." not in entry.name:
                kept.append(entry)
            else:
                # One malicious or malformed entry must cost exactly itself,
                # never the whole index (that would be a delisting DoS).
                logger.warning("community index: dropping skill with unsafe name %r", entry.name)
        return kept


#: How much of a derived description the store shows before it is cut.
_MAX_DERIVED_DESCRIPTION = 280
_HAS_WORD_RE = re.compile(r"\w")
_FRONTMATTER_RE = re.compile(r"\A﻿?---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.DOTALL)


def _one_paragraph(text: str) -> str:
    """Collapse whitespace and cut at a sentence end near the limit."""
    flat = " ".join(text.split())
    if len(flat) <= _MAX_DERIVED_DESCRIPTION:
        return flat
    cut = flat[:_MAX_DERIVED_DESCRIPTION]
    stop = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    if stop >= _MAX_DERIVED_DESCRIPTION // 2:
        return cut[: stop + 1]
    return cut.rsplit(" ", 1)[0].rstrip(",;:") + "…"


def skill_description(entry: CommunitySkillEntry) -> str:
    """The description to list a skill under.

    The registry copies the listing text from the submission form. When that
    text is unusable — it has shipped a bare YAML block marker (``"|"``) where
    a multi-line description should have been — the skill's own frontmatter
    still says what it does, and the feed embeds the file. Reading it there
    keeps a published skill from being listed as "No description yet."
    """
    listed = (entry.description or "").strip()
    if _HAS_WORD_RE.search(listed):
        return listed
    skill_md = getattr(entry, "skill_md", None)
    if not isinstance(skill_md, str):
        return ""
    match = _FRONTMATTER_RE.match(skill_md)
    if match is None:
        return ""
    try:
        import yaml

        meta = yaml.safe_load(match.group(1))
    except Exception:  # noqa: BLE001 - a broken frontmatter costs the fallback only
        return ""
    derived = meta.get("description") if isinstance(meta, dict) else None
    if not isinstance(derived, str) or not _HAS_WORD_RE.search(derived):
        return ""
    return _one_paragraph(derived)


def entry_files(entry: Any) -> list[dict[str, Any]] | None:
    """The published files the feed embeds for an entry, or None.

    ``[{"path", "size", "text"}]`` as the registry wrote them (``text`` is
    None for a file that is not UTF-8 text or is over the embed limit). None
    means the feed predates embedded files and the caller has to get the
    content another way.
    """
    raw = getattr(entry, "files", None)
    if not isinstance(raw, list):
        return None
    files: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        path = item.get("path")
        # A path is only ever shown, never opened, but a feed is outside
        # input: keep it relative and free of traversal anyway.
        if not isinstance(path, str) or not path or path.startswith(("/", "\\")):
            continue
        if ".." in path.replace("\\", "/").split("/"):
            continue
        text = item.get("text")
        size = item.get("size")
        files.append(
            {
                "path": path,
                "size": size if isinstance(size, int) and size >= 0 else 0,
                "text": text if isinstance(text, str) else None,
            }
        )
    return files


def reset_runtime_state() -> None:
    """Forget everything held in memory. For tests and a changed index URL."""
    global _memory, _last_failure, _revalidation
    _memory = None
    _last_failure = None
    if _revalidation is not None and not _revalidation.done():
        _revalidation.cancel()
    _revalidation = None


#: Former GitHub Pages addresses of the public registry. Pages does not follow
#: a repository or organization rename, so a config that saved one of these
#: reads the current deployment instead of a dead host.
_RETIRED_INDEX_URLS = frozenset({"https://personaljarvis.github.io/marketplace/index.json"})


def index_url() -> str:
    """The configured index URL (empty string = community section disabled)."""
    from dodaios.core.config import MarketplaceConfig, load_config

    try:
        url = str(load_config().marketplace.community_index_url).strip()
        return MarketplaceConfig().community_index_url if url in _RETIRED_INDEX_URLS else url
    except Exception:  # noqa: BLE001 - config trouble must not kill browsing
        logger.warning("community index: could not read config, using default")
        from dodaios.core.config import MarketplaceConfig

        return MarketplaceConfig().community_index_url


def _cache_stamp() -> tuple[str, int, int] | None:
    """What identifies the cache file as it is on disk right now."""
    try:
        stat = _CACHE_PATH.stat()
    except OSError:
        # No cache file yet, or it cannot be read: both mean "nothing cached".
        return None
    return (str(_CACHE_PATH), stat.st_mtime_ns, stat.st_size)


def _read_cache_raw() -> tuple[float, CommunityIndex, str | None] | None:
    """``(fetched_at, index, etag)`` — ``etag`` is None for a cache written
    before validators were stored, or when the host sent none.

    Answers from memory while the file is the one that was parsed: the feed
    embeds every published file, and validating it on each poll is the larger
    part of what a browse request costs.
    """
    global _memory
    stamp = _cache_stamp()
    if stamp is None:
        _memory = None
        return None  # no cache yet — the caller fetches the index
    if _memory is not None and _memory[0] == stamp:
        return _memory[1]
    try:
        raw = json.loads(_CACHE_PATH.read_text(encoding="utf-8-sig"))
        etag = raw.get("etag")
        hit = (
            float(raw["fetched_at"]),
            CommunityIndex.model_validate(raw["index"]),
            str(etag) if isinstance(etag, str) and etag else None,
        )
    except FileNotFoundError:
        return None  # removed between the stat and the read: the caller fetches
    except (OSError, ValueError, KeyError, ValidationError) as exc:
        logger.warning("community index: unreadable cache (%s) — refetching", exc)
        return None
    _memory = (stamp, hit)
    return hit


def _read_cache() -> tuple[float, CommunityIndex] | None:
    hit = _read_cache_raw()
    return (hit[0], hit[1]) if hit else None


def _write_cache(index: CommunityIndex, etag: str | None = None) -> None:
    """Atomic tmp+replace, like every other data/ writer in this repo.

    ``etag`` is the host's validator for this exact body; the next refresh
    after the TTL sends it back as ``If-None-Match`` so an unchanged index
    costs a 304 instead of a download.
    """
    global _memory
    fetched_at = time.time()
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _CACHE_PATH.with_suffix(".json.tmp")
        payload: dict[str, Any] = {
            "fetched_at": fetched_at,
            "index": index.model_dump(mode="json"),
        }
        if etag:
            payload["etag"] = etag
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_CACHE_PATH)
    except OSError as exc:
        # A read-only disk costs persistence, not the current browse.
        logger.warning("community index: cache write failed: %s", exc)
        return
    # The object just written is the parsed form of the file just written.
    stamp = _cache_stamp()
    _memory = (stamp, (fetched_at, index, etag)) if stamp is not None else None


def cached_index() -> CommunityIndex | None:
    """The last fetched index regardless of age, or None if never fetched."""
    hit = _read_cache()
    return hit[1] if hit else None


def _backing_off() -> bool:
    """True while the last failed fetch is recent enough to not try again."""
    return (
        _last_failure is not None and (time.monotonic() - _last_failure) < _FAILURE_BACKOFF_SECONDS
    )


async def _fetch(
    url: str,
    hit: tuple[float, CommunityIndex] | None,
    etag: str | None,
    *,
    force: bool,
    transport: httpx.AsyncBaseTransport | None,
) -> tuple[CommunityIndex | None, str]:
    """One round trip to the registry. The caller holds ``_fetch_lock``."""
    global _last_failure
    # Revalidate rather than re-download when we hold the host's validator.
    # An explicit refresh (force) asks for the body outright — the user
    # pressed the button because they suspect the cache, so a "still the
    # same" answer from a CDN edge would be the wrong kind of reassurance.
    headers = {"If-None-Match": etag} if (etag and hit and not force) else {}
    try:
        # The index URL is configuration, but its redirects are not: the
        # host on the other end picks them, so the chain stays on https.
        async with httpx.AsyncClient(
            timeout=_FETCH_TIMEOUT,
            follow_redirects=True,
            transport=transport,
            **https_only_async(),
        ) as client:
            response = await client.get(url, headers=headers)
            if response.status_code == 304 and hit:
                # Same body as cached: stamp it fresh for another TTL.
                _last_failure = None
                _write_cache(hit[1], etag)
                return hit[1], "fresh"
            response.raise_for_status()
            index = CommunityIndex.model_validate(response.json())
            new_etag = response.headers.get("etag") or None
    except (httpx.HTTPError, ValueError, ValidationError) as exc:
        logger.warning("community index: fetch failed (%s)", exc)
        _last_failure = time.monotonic()
        if hit:
            return hit[1], "stale"
        return None, "unavailable"

    _last_failure = None
    _write_cache(index, new_etag)
    return index, "fetched"


async def _revalidate(url: str, transport: httpx.AsyncBaseTransport | None) -> None:
    """Bring the cache up to date behind a response that was already sent."""
    try:
        async with _fetch_lock:
            raw_hit = _read_cache_raw()
            if raw_hit and (time.time() - raw_hit[0]) < _CACHE_TTL_SECONDS:
                return  # somebody refreshed it while this task waited its turn
            hit = (raw_hit[0], raw_hit[1]) if raw_hit else None
            etag = raw_hit[2] if raw_hit else None
            await _fetch(url, hit, etag, force=False, transport=transport)
    except Exception:  # noqa: BLE001 - nobody awaits this task; it must not raise
        logger.exception("community index: background revalidation failed")


def _revalidate_in_background(url: str, transport: httpx.AsyncBaseTransport | None) -> None:
    global _revalidation
    if _revalidation is not None and not _revalidation.done():
        return
    _revalidation = asyncio.get_running_loop().create_task(_revalidate(url, transport))


async def get_index(
    *,
    force: bool = False,
    background: bool = False,
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[CommunityIndex | None, str]:
    """Return ``(index, status)`` with status one of:

    - ``"disabled"``  — no index URL configured
    - ``"fresh"``     — served from a within-TTL cache, or the host confirmed
      the cached body is still current (304 Not Modified)
    - ``"fetched"``   — downloaded and cached just now
    - ``"revalidating"`` — ``background=True`` only: served from an expired
      cache at once, while a fetch brings it up to date behind the response
    - ``"stale"``     — network failed; serving the outdated cache honestly
    - ``"unavailable"`` — network failed and there is no cache at all

    ``background`` is for browsing, where an answer now beats a current answer
    in half a second. Anything that ACTS on the index (install, reading an
    entry's files) leaves it off and so never runs on an index older than the
    TTL without having asked the registry first: a delisted entry must stop
    being installable within minutes, not whenever the store is next opened.
    """
    url = index_url()
    if not url:
        return None, "disabled"

    if background and not force:
        raw_hit = _read_cache_raw()
        if raw_hit is not None:
            if (time.time() - raw_hit[0]) < _CACHE_TTL_SECONDS:
                return raw_hit[1], "fresh"
            if _backing_off():
                return raw_hit[1], "stale"
            _revalidate_in_background(url, transport)
            return raw_hit[1], "revalidating"
        if _backing_off():
            return None, "unavailable"

    async with _fetch_lock:
        raw_hit = _read_cache_raw()
        hit = (raw_hit[0], raw_hit[1]) if raw_hit else None
        etag = raw_hit[2] if raw_hit else None
        if hit and not force and (time.time() - hit[0]) < _CACHE_TTL_SECONDS:
            return hit[1], "fresh"
        return await _fetch(url, hit, etag, force=force, transport=transport)


__all__ = [
    "SKILL_FLAVORS",
    "CommunityAgentEntry",
    "CommunityIndex",
    "CommunityPluginEntry",
    "CommunitySkillEntry",
    "cached_index",
    "entry_files",
    "get_index",
    "index_url",
    "reset_runtime_state",
    "skill_description",
]
