"""The packages this install just published, shown in the store at once.

A submission reaches everyone through the registry: an intake issue, the
automated checks, a commit, the feed rebuild. That takes a minute or two.
The person who pressed Publish should not have to wait for it to see their
package, so the app keeps its own short list of what it submitted and the
store shows those entries right away, marked as "being checked".

Each record follows its intake issue:

* ``checking`` — the issue is open and the checks have not answered yet.
* ``failed`` — the checks refused it. The findings are kept so the store and
  the studio can say what to fix; the issue itself is never the place the
  person has to go.
* ``published`` — the checks passed; the entry reaches the feed shortly.

A record is dropped as soon as the live feed lists that name at that
version: from then on the real entry is shown instead.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any

import httpx

from dodaios.core.branding import HTTP_USER_AGENT

log = logging.getLogger(__name__)

_FILE_NAME = "own_submissions.json"
_HTTP_TIMEOUT = httpx.Timeout(connect=5.0, read=15.0, write=15.0, pool=15.0)
_GITHUB_API = "https://api.github.com"
#: Labels the registry intake sets (scripts/intake.py in Dodaios/marketplace).
LABEL_PUBLISHED = "published"
LABEL_NEEDS_CHANGES = "needs-changes"
#: A record the feed never confirmed is forgotten after this long.
_MAX_AGE_SECONDS = 7 * 24 * 3600
#: The issue is asked at most this often per record.
_MIN_CHECK_INTERVAL = 10.0

_lock = threading.Lock()


def _path() -> Path:
    from dodaios.core.paths import runtime_data_dir

    return runtime_data_dir() / "marketplace" / _FILE_NAME


def _load() -> list[dict[str, Any]]:
    path = _path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError):
        log.warning("own submissions: unreadable %s, starting empty", path)
        return []
    if not isinstance(data, list):
        return []
    now = time.time()
    return [
        item
        for item in data
        if isinstance(item, dict)
        and isinstance(item.get("name"), str)
        and now - float(item.get("submitted_at") or 0) < _MAX_AGE_SECONDS
    ]


def _save(records: list[dict[str, Any]]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _key(kind: str, name: str) -> str:
    return f"{kind}:{name}"


def record(
    normalized: dict[str, Any], result: dict[str, Any], publisher: str | None
) -> dict[str, Any]:
    """Remember a submission that was just filed. Replaces an older record
    of the same package (a new version, or a second try after a refusal)."""
    kind = str(normalized.get("kind") or "")
    name = str(normalized.get("name") or "")
    entry: dict[str, Any] = {
        "kind": kind,
        "name": name,
        "version": str(normalized.get("version") or ""),
        "title": str(normalized.get("title") or "") or _plugin_title(normalized) or name,
        "description": str(normalized.get("description") or "") or _plugin_description(normalized),
        "categories": list(normalized.get("categories") or []),
        "publisher": publisher,
        "issue_url": result.get("issue_url") or result.get("pr_url"),
        "issue_number": result.get("issue_number"),
        "state": "checking",
        "problems": [],
        "submitted_at": time.time(),
        "checked_at": 0.0,
    }
    with _lock:
        records = [r for r in _load() if _key(r["kind"], r["name"]) != _key(kind, name)]
        records.append(entry)
        _save(records)
    return entry


def previous_failed_issue(kind: str, name: str) -> int | None:
    """The intake issue of an earlier, refused try of this package, if any."""
    with _lock:
        for item in _load():
            same = _key(item["kind"], item["name"]) == _key(kind, name)
            if same and item.get("state") == "failed":
                number = item.get("issue_number")
                return number if isinstance(number, int) else None
    return None


def _plugin_title(normalized: dict[str, Any]) -> str:
    from dodaios.marketplace.agent_plugins_loader import extension_of

    plugin_json = normalized.get("plugin_json")
    if not isinstance(plugin_json, dict):
        return ""
    extension = extension_of(plugin_json) or {}
    title = extension.get("display_name") if isinstance(extension, dict) else None
    return str(title or "")


def _plugin_description(normalized: dict[str, Any]) -> str:
    plugin_json = normalized.get("plugin_json")
    if isinstance(plugin_json, dict):
        return str(plugin_json.get("description") or "")
    agent = normalized.get("agent")
    if isinstance(agent, dict):
        return str(agent.get("summary") or agent.get("description") or "")
    return ""


def pending(index: Any | None) -> list[dict[str, Any]]:
    """The records still worth showing, after dropping what the feed lists.

    ``index`` is the community index (``None`` when it is unavailable, in
    which case nothing is dropped).
    """
    with _lock:
        records = _load()
        if index is None:
            return records
        live = {
            (entry.name, entry.version or "")
            for entry in [*index.plugins, *index.skills, *index.agents]
        }
        kept = [r for r in records if (r["name"], r.get("version") or "") not in live]
        if len(kept) != len(records):
            _save(kept)
        return kept


def find(name: str, version: str) -> dict[str, Any] | None:
    with _lock:
        for item in _load():
            if item["name"] == name and (item.get("version") or "") == version:
                return item
    return None


def _problems_from_comment(body: str) -> list[str]:
    """The validator's findings from the intake's answer, as plain lines.

    The intake answers with a fenced report whose lines read
    ``  - /home/runner/.../submissions/x.json: skill_md: problem``; the path
    prefix means nothing to the author and is cut.
    """
    problems: list[str] = []
    for line in body.splitlines():
        found = re.match(r"^\s*-\s+(.*)$", line)
        if not found:
            continue
        text = re.sub(r"^\S*submissions/[^:]+\.json:\s*", "", found.group(1)).strip()
        if text:
            problems.append(text)
    if not problems:
        bold = re.search(r"\*\*(.+?)\*\*", body)
        if bold:
            problems.append(bold.group(1).strip())
    return problems[:10]


async def refresh_from_issue(
    name: str,
    version: str,
    repo: str,
    token: str | None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any] | None:
    """Ask the intake issue how the checks went and store the answer."""
    item = find(name, version)
    if item is None:
        return None
    number = item.get("issue_number")
    if not isinstance(number, int) or not repo:
        return item
    if time.time() - float(item.get("checked_at") or 0) < _MIN_CHECK_INTERVAL:
        return item
    headers = {
        "User-Agent": HTTP_USER_AGENT,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, transport=transport) as client:
            r = await client.get(f"{_GITHUB_API}/repos/{repo}/issues/{number}", headers=headers)
            if r.status_code != 200:
                return item
            issue = r.json()
            labels = {str(label.get("name")) for label in issue.get("labels") or []}
            state = item.get("state", "checking")
            problems: list[str] = list(item.get("problems") or [])
            if LABEL_PUBLISHED in labels:
                state, problems = "published", []
            elif LABEL_NEEDS_CHANGES in labels:
                state = "failed"
                c = await client.get(
                    f"{_GITHUB_API}/repos/{repo}/issues/{number}/comments",
                    params={"per_page": 100},
                    headers=headers,
                )
                if c.status_code == 200:
                    comments = [x for x in c.json() if isinstance(x, dict)]
                    if comments:
                        problems = _problems_from_comment(str(comments[-1].get("body") or ""))
    except (httpx.HTTPError, ValueError) as exc:
        log.info("own submissions: issue check failed: %s", exc)
        return item
    with _lock:
        records = _load()
        for record_item in records:
            if record_item["name"] == name and (record_item.get("version") or "") == version:
                record_item.update(state=state, problems=problems, checked_at=time.time())
                item = record_item
        _save(records)
    return item


async def close_issue(
    repo: str,
    number: int,
    token: str,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> None:
    """Close the intake issue of a refused try once a new try replaces it.

    The author of an issue may close it, so the signed-in user's token is
    enough. Best effort: a failure leaves an open issue and nothing else.
    """
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, transport=transport) as client:
            await client.patch(
                f"{_GITHUB_API}/repos/{repo}/issues/{number}",
                json={"state": "closed", "state_reason": "not_planned"},
                headers={
                    "User-Agent": HTTP_USER_AGENT,
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
    except httpx.HTTPError as exc:
        log.info("own submissions: could not close the old issue: %s", exc)
