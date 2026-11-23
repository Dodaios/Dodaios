"""Skill finder: mini-agent for searching and installing skills.

The finder is a thin wrapper around:
1. The curated seed catalog (``catalog/seed_catalog.json``).
2. The ``BrainManager`` for semantically scoring the candidates.
3. The ``httpx`` client for downloading a selected SKILL.md.

Design principles:
- **Graceful degradation**: without a brain, search falls back to a
  heuristic (string matching). Without internet, ``install`` fails, but
  search keeps working (static catalog).
- **Trust filter before the brain**: the trust filter runs *before*
  brain ranking, so the brain doesn't waste tokens on candidates the user
  would reject anyway.
- **Stateless**: the finder holds no state — query history lives in the
  frontend, and later in the flight recorder.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from dodaios.core.paths import user_skills_dir

# ``search`` reads the seed through the module attribute so a test can swap
# ``load_catalog`` on ``dodaios.skills.catalog``; the direct name stays a
# re-export for callers that read the seed through the finder.
from dodaios.skills import catalog as _catalog_module
from dodaios.skills.catalog import load_catalog  # noqa: F401

log = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Value-Types
# ----------------------------------------------------------------------

TrustLevel = Literal["official", "verified", "community", "experimental"]
"""Trust levels for skill sources.

- ``official``: Anthropic, OpenAI, other first-party vendors.
- ``verified``: maintainer with a track record and 3000+ GitHub stars.
- ``community``: actively maintained, fewer stars, checkable.
- ``experimental``: prototype, solo dev, risk knowingly accepted by the user.
"""


TRUST_ORDER: dict[TrustLevel, int] = {
    "official": 0,
    "verified": 1,
    "community": 2,
    "experimental": 3,
}


@dataclass(frozen=True)
class SkillCandidate:
    """A match candidate from the catalog.

    Frozen for JSON serialization in responses + replay compatibility.
    """
    name: str
    title: str
    description: str
    source: str
    source_url: str
    raw_url: str | None
    trust: TrustLevel
    stars: int | None
    categories: tuple[str, ...]
    languages: tuple[str, ...]
    risk: str
    tags: tuple[str, ...]
    score: float = 0.0
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "source": self.source,
            "source_url": self.source_url,
            "raw_url": self.raw_url,
            "trust": self.trust,
            "stars": self.stars,
            "categories": list(self.categories),
            "languages": list(self.languages),
            "risk": self.risk,
            "tags": list(self.tags),
            "score": round(self.score, 3),
            "reason": self.reason,
        }

    @classmethod
    def from_catalog_entry(cls, entry: dict[str, Any]) -> SkillCandidate:
        return cls(
            name=str(entry["name"]),
            title=str(entry.get("title", entry["name"])),
            description=str(entry.get("description", "")),
            source=str(entry.get("source", "unknown")),
            source_url=str(entry.get("source_url", "")),
            raw_url=entry.get("raw_url"),
            trust=entry.get("trust", "community"),
            stars=entry.get("stars"),
            categories=tuple(entry.get("categories", [])),
            languages=tuple(entry.get("languages", [])),
            risk=str(entry.get("risk", "monitor")),
            tags=tuple(entry.get("tags", [])),
        )


@dataclass(frozen=True)
class SearchFilters:
    """Filters for the search — maps to the dropdown selection in the frontend."""
    query: str = ""
    trust: TrustLevel | Literal["any"] = "any"
    min_stars: int | None = None
    category: str | None = None
    language: str | None = None
    max_risk: str | None = None  # "safe", "monitor", "ask"
    limit: int = 10


# ----------------------------------------------------------------------
# Filter + Ranking
# ----------------------------------------------------------------------

_RISK_ORDER = {"safe": 0, "monitor": 1, "ask": 2, "block": 3}

# Slug rule for the install target directory — same shape as the paste-import
# guard in skills_routes (`_IMPORT_NAME_RE`), plus dots for spec-style names.
# No separator can pass, so `user_skills_dir() / name` stays inside the root.
# It ends in a letter or digit: Windows drops a trailing dot from a folder
# name, so "notes." would be written into the folder of the skill "notes".
_INSTALL_NAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,62}[A-Za-z0-9])?$")


def _passes_filter(entry: dict[str, Any], f: SearchFilters) -> bool:
    """Hard filter before ranking — excludes on trust/stars/category/risk."""
    # Trust
    if f.trust != "any":
        e_trust = entry.get("trust", "community")
        if TRUST_ORDER.get(e_trust, 99) > TRUST_ORDER.get(f.trust, 99):
            return False

    # Min stars (if given)
    if f.min_stars is not None:
        e_stars = entry.get("stars")
        if e_stars is None or e_stars < f.min_stars:
            # Official skills have ``stars = null`` — we let those pass
            # regardless of the star threshold (official > star metric).
            if entry.get("trust") != "official":
                return False

    # Category
    if f.category:
        cats = entry.get("categories", [])
        if f.category not in cats:
            return False

    # Language
    if f.language:
        langs = entry.get("languages", [])
        if f.language not in langs and "en" not in langs:
            # falls back to EN if the skill is bilingual
            return False

    # Risk
    if f.max_risk:
        e_risk = entry.get("risk", "monitor")
        if _RISK_ORDER.get(e_risk, 99) > _RISK_ORDER.get(f.max_risk, 99):
            return False

    return True


_WORD_RE = re.compile(r"\b\w{3,}\b", re.UNICODE)
_MATCH_WORD_RE = re.compile(r"\w+", re.UNICODE)

# A query token this long or longer may also PREFIX-match an entry token
# ("extract" finds "extraction"); shorter tokens ("pdf", "ui") match exactly.
_PREFIX_MIN_LEN = 4


def _tokenize(text: str) -> set[str]:
    return {w.lower() for w in _WORD_RE.findall(text)}


def _match_tokens(text: str) -> set[str]:
    """Lower-cased word tokens of a catalog field, no minimum length — a tag
    like "ui" or "git" must stay findable."""
    return {w.lower() for w in _MATCH_WORD_RE.findall(text)}


def _query_tokens(query: str) -> set[str]:
    """Tokens of the user's query for text matching.

    Every word of two or more characters counts, lower-cased ("PDf" → "pdf").
    A query made of single letters only keeps those, so a non-empty query can
    never silently turn into browse mode.
    """
    words = [w.lower() for w in _MATCH_WORD_RE.findall(query)]
    return {w for w in words if len(w) >= 2} or set(words)


def _token_hits(query_tokens: set[str], field_tokens: set[str]) -> set[str]:
    """Query tokens that match a field: exact, or as a prefix when long enough."""
    hits: set[str] = set()
    for q in query_tokens:
        if q in field_tokens:
            hits.add(q)
        elif len(q) >= _PREFIX_MIN_LEN and any(t.startswith(q) for t in field_tokens):
            hits.add(q)
    return hits


@dataclass(frozen=True)
class _TextMatch:
    """Outcome of matching a query against one catalog entry."""
    score: float
    labels: tuple[str, ...]

    @property
    def matched(self) -> bool:
        return self.score > 0.0

    def reason(self, trust: str) -> str:
        """Names WHAT matched ("name", "tag: pdf", ...). Without a text match
        (browse mode) the only thing that matched is the filter set."""
        if not self.matched:
            return f"Trust match ({trust})"
        return "Matches " + ", ".join(self.labels[:4])


_NO_MATCH = _TextMatch(score=0.0, labels=())

# Field weights: curated fields (name, title, tags) outrank prose.
_FIELD_WEIGHTS: dict[str, float] = {
    "name": 2.0,
    "title": 2.0,
    "tag": 2.0,
    "category": 1.5,
    "description": 1.0,
}
_MAX_FIELD_WEIGHT = max(_FIELD_WEIGHTS.values())


def _match_text(query_tokens: set[str], entry: dict[str, Any]) -> _TextMatch:
    """Token-wise, case-insensitive match of the query against an entry.

    Looks at name, title, description, tags and categories. Each query token
    scores the weight of the best field it hits, so one token found in three
    fields does not outrank three tokens found once. The score is normalised
    to [0, 1] by the number of query tokens — coverage matters.

    Returns a zero score with no labels when nothing matches: the caller
    drops such entries from a text search.
    """
    if not query_tokens:
        return _NO_MATCH

    best_per_token: dict[str, float] = {}
    labels: list[str] = []

    def _record(label: str, field: str, text: str) -> None:
        hits = _token_hits(query_tokens, _match_tokens(text))
        if not hits:
            return
        if label not in labels:
            labels.append(label)
        weight = _FIELD_WEIGHTS[field]
        for tok in hits:
            best_per_token[tok] = max(best_per_token.get(tok, 0.0), weight)

    _record("name", "name", str(entry.get("name", "")))
    _record("title", "title", str(entry.get("title", "")))
    for tag in entry.get("tags", []) or []:
        _record(f"tag: {tag}", "tag", str(tag))
    for cat in entry.get("categories", []) or []:
        _record(f"category: {cat}", "category", str(cat))
    _record("description", "description", str(entry.get("description", "")))

    if not best_per_token:
        return _NO_MATCH
    raw = sum(best_per_token.values())
    score = min(1.0, raw / (_MAX_FIELD_WEIGHT * len(query_tokens)))
    return _TextMatch(score=score, labels=tuple(labels))


def _score_heuristic(query_tokens: set[str], entry: dict[str, Any]) -> float:
    """Heuristic ranking without a brain — see ``_match_text``."""
    return _match_text(query_tokens, entry).score


def _heuristic_reason(query_tokens: set[str], entry: dict[str, Any]) -> str:
    """Human-readable reason for a hit — see ``_TextMatch.reason``."""
    return _match_text(query_tokens, entry).reason(
        str(entry.get("trust", "community"))
    )


# ----------------------------------------------------------------------
# Brain-backed ranking
# ----------------------------------------------------------------------

_RANK_SYSTEM_PROMPT = """You are a skill ranker for Dodaios. The user
is looking for a skill that solves their problem. You get a user query and a
list of candidates as JSON. Return ONLY a JSON array, sorted from best
to worst match. Each entry: {"name": "...", "score": 0.0-1.0, "reason": "short
sentence on why it fits"}. Nothing else, no Markdown, no prefix."""


async def _brain_rank(
    brain: Any,
    query: str,
    candidates: list[dict[str, Any]],
) -> dict[str, tuple[float, str]] | None:
    """Uses a brain (BrainManager instance) for ranking.

    Returns ``None`` when:
    - no brain was passed
    - the response wasn't parsable as JSON (falls back to the heuristic)
    - the brain raised an error
    """
    if brain is None:
        return None

    # Minimal prompt: only name + title + description + tags, to save tokens
    compact = [
        {
            "name": c["name"],
            "title": c.get("title"),
            "description": c.get("description"),
            "tags": c.get("tags", []),
        }
        for c in candidates[:30]  # hard cap — 30 candidates is plenty
    ]
    user_msg = (
        f"User query: {query!r}\n\n"
        f"Candidates:\n{json.dumps(compact, ensure_ascii=False)}\n\n"
        f"{_RANK_SYSTEM_PROMPT}"
    )

    try:
        # BrainManager.generate is the uniform call. No use_history — this
        # is a one-shot ranker, not part of the chat history.
        if hasattr(brain, "generate"):
            text = await brain.generate(user_msg, use_history=False)
        else:
            # Fallback: if someone passes a raw Brain-protocol impl, we could
            # go through the dispatcher here. MVP: BrainManager only.
            return None
    except Exception as exc:  # noqa: BLE001
        log.warning("Brain ranking failed: %s", exc)
        return None

    # Fish out the JSON — the brain may return it with whitespace or a prefix
    json_match = re.search(r"\[\s*\{.*?\}\s*\]", text, re.DOTALL)
    if not json_match:
        log.debug("Brain response contains no JSON array: %s", text[:200])
        return None
    try:
        parsed = json.loads(json_match.group(0))
    except json.JSONDecodeError as exc:
        log.debug("Brain-ranking JSON not parsable: %s", exc)
        return None

    out: dict[str, tuple[float, str]] = {}
    for item in parsed:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not isinstance(name, str):
            continue
        try:
            score = float(item.get("score", 0.0))
        except (TypeError, ValueError):
            score = 0.0
        reason = str(item.get("reason", "") or "")
        out[name] = (max(0.0, min(1.0, score)), reason)
    return out or None


# ----------------------------------------------------------------------
# Finder
# ----------------------------------------------------------------------

def _community_entries() -> list[dict[str, Any]]:
    """Community skills from the CACHED marketplace index, in seed-entry shape.

    Reads only the on-disk cache — search must stay fast and offline-safe, so
    the network fetch happens at the route edge (TTL-gated), never here. An
    unreadable or absent cache degrades to the seed catalog alone.
    """
    try:
        from dodaios.marketplace.community_source import cached_index

        index = cached_index()
    except Exception:  # noqa: BLE001 - a broken cache must not kill search
        log.warning("community skill entries unavailable", exc_info=True)
        return []
    if index is None:
        return []
    return [
        {
            "name": skill.name,
            "title": skill.title or skill.name,
            "description": skill.description,
            "source": "marketplace",
            "source_url": skill.source_url or "",
            "raw_url": skill.raw_url,
            "trust": "community",
            "stars": None,
            "categories": list(skill.categories),
            "languages": ["en"],
            "risk": "monitor",
            "tags": [],
        }
        for skill in index.skills
    ]


class SkillFinder:
    """Mini-agent for skill search and installation."""

    def __init__(self, brain: Any | None = None) -> None:
        self._brain = brain

    async def search(self, filters: SearchFilters) -> list[SkillCandidate]:
        """Filter + rank — returns up to ``filters.limit`` candidates.

        Two modes:
        - **Text search** (non-empty query): an entry must pass the hard
          filters AND match the query text (name/title/description/tags/
          categories, case-insensitive, token-wise). Entries that only pass
          the filters are dropped; when nothing matches the result is empty.
          The brain only re-ranks the textual matches — it never resurrects
          an entry the text match rejected.
        - **Browse** (empty query): hard filters only, no brain call.
        """
        catalog = list(_catalog_module.load_catalog())
        # Community entries join the pool AFTER the seed so a name the curated
        # catalog already lists cannot be shadowed by a marketplace upload.
        seen_names = {str(e.get("name")) for e in catalog}
        catalog.extend(
            e for e in _community_entries() if e["name"] not in seen_names
        )
        filtered = [e for e in catalog if _passes_filter(e, filters)]

        if not filtered:
            return []

        query = filters.query.strip()
        query_tokens = _query_tokens(query)
        if query and not query_tokens:
            # Punctuation-only query: nothing can match, and it must not
            # silently turn into browse mode.
            return []
        if query_tokens:
            pool = [
                (entry, match)
                for entry in filtered
                if (match := _match_text(query_tokens, entry)).matched
            ]
            if not pool:
                return []
            brain_scores = await _brain_rank(
                self._brain, query, [entry for entry, _ in pool]
            )
        else:
            pool = [(entry, _NO_MATCH) for entry in filtered]
            brain_scores = None

        candidates: list[SkillCandidate] = []
        for entry, match in pool:
            cand = SkillCandidate.from_catalog_entry(entry)
            heur_reason = match.reason(cand.trust)
            if brain_scores and cand.name in brain_scores:
                score, reason = brain_scores[cand.name]
                # Brain score weighted 0.7, heuristic score weighted 0.3 — so
                # a brain that under-rates an exact tag hit cannot bury it
                final_score = 0.7 * score + 0.3 * match.score
                final_reason = reason or heur_reason
            else:
                final_score = match.score
                final_reason = heur_reason

            # Trust bonus: on equal score, the more trustworthy one wins
            trust_bonus = (3 - TRUST_ORDER.get(cand.trust, 3)) * 0.01
            final_score += trust_bonus

            candidates.append(
                SkillCandidate(
                    **{**cand.__dict__, "score": final_score, "reason": final_reason}
                )
            )

        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates[: filters.limit]

    async def install(self, candidate: SkillCandidate) -> Path:
        """Installs a candidate into ``user_skills_dir()`` as a DRAFT.

        Strategy:
        - If ``raw_url`` is set, the SKILL.md is fetched directly.
        - Without ``raw_url``, the install fails with a clear message —
          the user then has to install manually (link in the frontend).

        The downloaded file is third-party text nobody here has read yet
        (AP-15), whether it comes from the shipped catalog or the community
        marketplace. It is stored with ``state: draft`` and switched on by the
        person in Skills; it never joins the active pool by being installed.

        Nothing is written unless the file is accepted: it must be UTF-8 text
        within the size limit, parse as a skill, read back as a draft, and
        name itself exactly as the entry that was installed (a file that
        calls itself something else would register under THAT name and could
        take the place of another skill).

        Returns the target path (``<user_skills>/<name>/SKILL.md``).
        Raises ``RuntimeError`` on a network error, a missing raw_url, or a
        refused file; the message is shown to the user.
        """
        if not candidate.raw_url:
            raise RuntimeError(
                f"No direct download available for '{candidate.name}'. "
                f"Open {candidate.source_url} and install manually."
            )
        # Fail-closed guards for UNTRUSTED candidates (the community index is
        # auto-merged registry data, and the catalog-install route accepts a
        # caller-supplied name):
        #  - https only — the download runs SERVER-side, so a plain-http or
        #    internal address would be an SSRF primitive;
        #  - the name becomes a directory under user_skills_dir(), and
        #    pathlib's `/` DISCARDS the base on an absolute right-hand side,
        #    so a non-slug name could write anywhere the process can.
        if not candidate.raw_url.lower().startswith("https://"):
            raise RuntimeError(
                f"Refusing non-https download URL: {candidate.raw_url}"
            )
        if not _INSTALL_NAME_RE.fullmatch(candidate.name or ""):
            raise RuntimeError(
                f"Skill name {candidate.name!r} is not a valid slug "
                "(letters, digits, '-', '_', '.'; max 64 chars)."
            )
        base = user_skills_dir().resolve()
        resolved_target = (base / candidate.name).resolve()
        if resolved_target.parent != base:
            raise RuntimeError(
                f"Skill name {candidate.name!r} resolves outside the skills "
                "directory."
            )
        from dodaios.skills.builtin import BUILTIN_SKILL_NAMES

        if candidate.name in BUILTIN_SKILL_NAMES:
            raise RuntimeError(
                f"'{candidate.name}' is a built-in skill name and cannot be "
                "installed from a catalog."
            )
        # Target structure: <user_skills>/<name>/SKILL.md. An existing file
        # is never replaced, whatever name the skill inside it goes by.
        target_dir = base / candidate.name
        target_file = target_dir / "SKILL.md"
        if target_file.exists():
            raise RuntimeError(
                f"Skill '{candidate.name}' already exists. Delete it before "
                "reinstalling."
            )

        content = await _download_skill_text(candidate.raw_url)

        from dodaios.skills.remote import hold_as_draft

        # Stamps ``state: draft`` and reads the result back with the loader;
        # raises (a RuntimeError) for a file that is not a skill or would not
        # stay a draft. Checked on a scratch copy: a refusal writes nothing.
        stamped, parsed = hold_as_draft(content)
        if parsed.name != candidate.name:
            raise RuntimeError(
                f"The downloaded file names itself {parsed.name!r}, not "
                f"{candidate.name!r}. A skill is installed under the name it "
                "is listed with, so this file was not installed."
            )

        # Write atomically; on a failure take back what this call created.
        created_dir = not target_dir.exists()
        tmp = target_file.with_suffix(".md.tmp")
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            tmp.write_text(stamped, encoding="utf-8")
            tmp.replace(target_file)
        except OSError as exc:
            tmp.unlink(missing_ok=True)
            if created_dir:
                try:
                    target_dir.rmdir()
                except OSError:  # not empty or already gone: nothing of ours is left
                    log.debug("skill install: %s not removed", target_dir, exc_info=True)
            raise RuntimeError(f"Could not write skill: {exc}") from exc

        if parsed.error:
            # A draft with a broken trigger: stored, shown with its error.
            log.warning(
                "Installed skill '%s' has a validation error: %s",
                candidate.name, parsed.error,
            )

        return target_file


async def _download_skill_text(raw_url: str) -> str:
    """Fetch one SKILL.md over https, never more than the size limit."""
    # httpx is in the runtime deps (mcp_routes etc.)
    import httpx

    from dodaios.core.http_guard import https_only_async
    from dodaios.skills.remote import MAX_REMOTE_SKILL_BYTES

    too_large = (
        f"The file at {raw_url} is larger than {MAX_REMOTE_SKILL_BYTES // 1024} KB "
        "and was not installed."
    )
    chunks: list[bytes] = []
    total = 0
    # The https check in ``install`` covers the URL the index gave us. The
    # guard covers every url after it: a publisher who controls the host also
    # controls its Location header, and one 302 would otherwise put this
    # download back on the loopback API or a metadata endpoint.
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(15.0),
        **https_only_async(),
    ) as client:
        try:
            async with client.stream("GET", raw_url) as resp:
                resp.raise_for_status()
                declared = resp.headers.get("content-length", "")
                if declared.isdigit() and int(declared) > MAX_REMOTE_SKILL_BYTES:
                    raise RuntimeError(too_large)
                async for chunk in resp.aiter_bytes():
                    total += len(chunk)
                    if total > MAX_REMOTE_SKILL_BYTES:
                        raise RuntimeError(too_large)
                    chunks.append(chunk)
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Download from {raw_url} failed: {exc}") from exc
    try:
        return b"".join(chunks).decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise RuntimeError(
            f"The file at {raw_url} is not UTF-8 text and was not installed."
        ) from exc


__all__ = [
    "SkillFinder",
    "SkillCandidate",
    "SearchFilters",
    "TrustLevel",
    "TRUST_ORDER",
]
