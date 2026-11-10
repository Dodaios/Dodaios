#!/usr/bin/env python3
"""Regenerate the README's contributor wall from the GitHub API.

The wall lives between two HTML comment markers in ``README.md`` so the rest of
the file is never touched:

    <!-- contributors:start -->
    ...generated avatars...
    <!-- contributors:end -->

Run it with no arguments to rewrite the block in place, or with ``--check`` to
fail when the block is stale (that is the CI mode).

Three sources are merged, because any one of them hides people:

* The contributors API lists commit authors on the default branch. It lags a
  merge by minutes to hours, so the refresh that runs the moment a pull
  request lands used to report "up to date" and leave the new person off.
* Merged pull requests name the GitHub account that opened them, which is
  known the instant the pull request merges.
* Commits whose email GitHub could not link to an account come back as
  anonymous names. When every merged pull request with that git name was
  opened by one account, the commits are credited to that account. Otherwise
  they are left off the wall. Neither the name nor the email is written: a
  git name is often a family member's machine login, not the contributor.

Two kinds of accounts are deliberately excluded:

* GitHub Apps and bots (``type == "Bot"``, a ``[bot]`` suffix, or an
  ``app/`` login). Dependabot opening dependency bumps is not a contributor.
* The accounts in ``EXCLUDED_LOGINS``. ``Co-Authored-By: Claude
  <noreply@anthropic.com>`` trailers are attributed by GitHub to whichever
  account happens to own that address, which is a stranger to this repository.
  Crediting them on the README would be wrong twice over: it names the wrong
  person, and it presents an AI trailer as a human contributor.

Requires no dependencies. A token is optional but lifts the rate limit: the
script reads ``GITHUB_TOKEN`` (set for free inside GitHub Actions). With no
token it asks the ``gh`` CLI, which already holds a login on a developer
machine, and only then falls back to an unauthenticated request.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = "Dodaios/Dodaios"
README = Path(__file__).resolve().parents[2] / "README.md"

START = "<!-- contributors:start -->"
END = "<!-- contributors:end -->"

#: Accounts that the contributors API reports but that never contributed here.
#: See the module docstring for why the AI co-author trailer lands on a
#: third-party account.
EXCLUDED_LOGINS = frozenset({"claude"})

#: Avatars per row, matching the layout OpenClaw uses. Purely cosmetic.
PER_ROW = 7
AVATAR_PX = 64

#: Inline marker that scripts/ci/check_no_new_german.py skips.
LANGUAGE_GATE_ESCAPE = "i18n-allow"

_PR_QUERY = """
query($cursor: String) {
  repository(owner: "Dodaios", name: "Dodaios") {
    pullRequests(states: MERGED, first: 100, after: $cursor) {
      pageInfo { hasNextPage endCursor }
      nodes {
        author {
          login
          __typename
          ... on User { avatarUrl }
        }
        mergeCommit {
          author { name }
        }
      }
    }
  }
}
"""


def _headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "dodaios-contributors",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _read_json_with_gh(req: urllib.request.Request) -> object:
    """Use the ``gh`` login when no ``GITHUB_TOKEN`` is set.

    ``gh api`` reads credentials from the user's own keyring. The token never
    enters this process or the README.
    """
    cmd = ["gh", "api", "--method", req.get_method(), req.full_url]
    if req.data:
        # `--input -` is what makes gh treat stdin as the request body.
        cmd.extend(["--input", "-"])
    env = os.environ.copy()
    # gh colors JSON when it thinks stdout is a terminal, which is not JSON.
    env["NO_COLOR"] = "1"
    env["GH_FORCE_TTY"] = "0"
    proc = subprocess.run(  # noqa: S603 - fixed argv, URL built from REPO
        cmd,
        input=req.data,
        capture_output=True,
        check=False,
        env=env,
    )
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip()[:400]
        raise SystemExit(f"gh api failed ({proc.returncode}): {detail}")
    return json.loads(proc.stdout.decode("utf-8"))


def _read_json(req: urllib.request.Request) -> object:
    if not os.environ.get("GITHUB_TOKEN"):
        return _read_json_with_gh(req)
    try:
        # noqa justification: callers build the URL from the REPO constant or
        # post to the fixed GitHub GraphQL endpoint. No custom scheme can reach
        # here.
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
            return json.load(resp)
    except urllib.error.HTTPError as exc:  # pragma: no cover - network path
        raise SystemExit(f"GitHub API returned {exc.code}: {exc.reason}") from exc


def _keep(login: str, type_: str | None) -> bool:
    """Humans only. Bots and the mis-attributed co-author account stay off."""
    if not login or type_ == "Bot" or login.endswith("[bot]") or login.startswith("app/"):
        return False
    return login not in EXCLUDED_LOGINS


def fetch_commit_contributors() -> list[dict]:
    """Commit authors on the default branch, including anonymous git names."""
    people: list[dict] = []
    page = 1
    while page <= 20:
        url = f"https://api.github.com/repos/{REPO}/contributors?per_page=100&page={page}&anon=true"
        # S310: URL is the GitHub API built from the REPO constant, never user input.
        batch = _read_json(urllib.request.Request(url, headers=_headers()))  # noqa: S310
        if not isinstance(batch, list) or not batch:
            break
        people.extend(p for p in batch if isinstance(p, dict))
        if len(batch) < 100:
            break
        page += 1
    return people


def fetch_merged_pull_authors() -> list[dict]:
    """One entry per human who merged a pull request.

    ``contributions`` is the number of merged pull requests. ``git_names`` are
    the git author names on those merge commits, so commits GitHub stored
    under a local email can be attached to the account that opened the pull
    request.
    """
    by_login: dict[str, dict] = {}
    cursor: str | None = None
    for _ in range(20):
        payload = _read_json(
            urllib.request.Request(
                "https://api.github.com/graphql",
                data=json.dumps({"query": _PR_QUERY, "variables": {"cursor": cursor}}).encode(),
                headers={**_headers(), "Content-Type": "application/json"},
                method="POST",
            )
        )
        if not isinstance(payload, dict) or payload.get("errors"):
            detail = repr(payload)[:400]
            raise SystemExit(f"GitHub GraphQL returned errors: {detail}")
        connection = payload["data"]["repository"]["pullRequests"]
        for node in connection["nodes"] or []:
            author = node.get("author") or {}
            if author.get("__typename") != "User":
                continue
            login = author.get("login") or ""
            if not _keep(login, "User"):
                continue
            entry = by_login.get(login)
            if entry is None:
                entry = {
                    "login": login,
                    "avatar_url": author.get("avatarUrl") or "",
                    "type": "User",
                    "contributions": 0,
                    "git_names": set(),
                }
                by_login[login] = entry
            entry["contributions"] += 1
            merge = node.get("mergeCommit") or {}
            git_name = ((merge.get("author") or {}).get("name") or "").strip()
            if git_name:
                entry["git_names"].add(git_name)
        info = connection["pageInfo"]
        if not info.get("hasNextPage"):
            break
        nxt = info.get("endCursor")
        if not nxt or nxt == cursor:
            break
        cursor = nxt
    return list(by_login.values())


def combine(commit_people: list[dict], pr_people: list[dict]) -> list[dict]:
    """Every human who shipped something, most work first.

    A GitHub account is ranked by its commit count, or by its merged pull
    request count when the contributors index has not listed it yet. Anonymous
    git names fold into an account when exactly one merged-pull-request author
    used that name. Names that fold nowhere stay, without their email.
    """
    users: dict[str, dict] = {}
    for person in commit_people:
        if person.get("type") == "Anonymous":
            continue
        login = person.get("login") or ""
        if not _keep(login, person.get("type")):
            continue
        users[login] = {
            "login": login,
            "avatar_url": person.get("avatar_url") or "",
            "contributions": int(person.get("contributions") or 0),
        }

    name_to_logins: dict[str, set[str]] = {}
    for person in pr_people:
        login = person.get("login") or ""
        if not _keep(login, person.get("type") or "User"):
            continue
        pr_count = int(person.get("contributions") or 0)
        entry = users.get(login)
        if entry is None:
            users[login] = {
                "login": login,
                "avatar_url": person.get("avatar_url") or "",
                "contributions": pr_count,
            }
        else:
            if not entry["avatar_url"]:
                entry["avatar_url"] = person.get("avatar_url") or ""
            # A squash is one commit and one pull request. Adding the two
            # would rank the same work twice, so the larger figure wins.
            entry["contributions"] = max(entry["contributions"], pr_count)
        for git_name in person.get("git_names") or []:
            cleaned = str(git_name).strip()
            if cleaned:
                name_to_logins.setdefault(cleaned, set()).add(login)

    anon_counts: dict[str, int] = {}
    for person in commit_people:
        if person.get("type") != "Anonymous":
            continue
        name = str(person.get("name") or "").strip()
        if not name:
            continue
        anon_counts[name] = anon_counts.get(name, 0) + int(person.get("contributions") or 0)

    names: list[dict] = []
    for name, count in anon_counts.items():
        logins = name_to_logins.get(name, set())
        if len(logins) == 1:
            entry = users.get(next(iter(logins)))
            if entry is not None:
                entry["contributions"] = max(entry["contributions"], count)
                continue
        names.append({"name": name, "contributions": count})

    people = list(users.values()) + names
    people.sort(
        key=lambda person: (
            -int(person.get("contributions") or 0),
            (person.get("login") or person.get("name") or "").lower(),
        )
    )
    return people


def fetch_contributors() -> list[dict]:
    """Every human who shipped something here, most work first."""
    return combine(fetch_commit_contributors(), fetch_merged_pull_authors())


def _avatar_src(url: str) -> str:
    join = "&" if "?" in url else "?"
    return f"{url}{join}s={AVATAR_PX}"


def _user_cell(person: dict) -> str:
    """One table cell: the avatar with the GitHub login underneath."""
    login = person["login"]
    safe = html.escape(login, quote=True)
    return (
        f'<td align="center"><a href="https://github.com/{safe}">'
        f'<img src="{_avatar_src(person.get("avatar_url") or "")}" '
        f'width="{AVATAR_PX}" height="{AVATAR_PX}" alt="{safe}"><br>'
        f"<sub><b>{safe}</b></sub></a></td>"
    )


def _marked(line: str) -> str:
    # GitHub logins and real names are not prose: a login or a name made of
    # German words must not trip the output-language gate, so every row
    # carries its escape marker.
    return line + f" <!-- {LANGUAGE_GATE_ESCAPE} -->"


def render(people: list[dict]) -> str:
    """A table of GitHub accounts, ``PER_ROW`` to a row, name under each avatar.

    People with no linked account are left out. Their only identity is a git
    author name, which is often someone else's machine login, so printing it
    would name the wrong person.
    """
    accounts = [person for person in people if person.get("login")]
    if not accounts:
        return "_Nobody yet. That first square is yours._"
    rows = [
        _marked(
            "<tr>" + "".join(_user_cell(person) for person in accounts[i : i + PER_ROW]) + "</tr>"
        )
        for i in range(0, len(accounts), PER_ROW)
    ]
    return "\n".join(["<table>", *rows, "</table>"])


def splice(text: str, block: str) -> str:
    """Replace whatever sits between the markers with ``block``."""
    try:
        i = text.index(START) + len(START)
        j = text.index(END)
    except ValueError:
        raise SystemExit(
            f"README.md is missing the {START} / {END} markers - add the "
            f"Contributors section before running this.",
        ) from None
    return text[:i] + "\n\n" + block + "\n\n" + text[j:]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero when the block is stale instead of rewriting it",
    )
    args = ap.parse_args()

    current = README.read_text(encoding="utf-8")
    people = fetch_contributors()
    updated = splice(current, render(people))

    if updated == current:
        print(f"contributors: up to date ({len(people)} people)")
        return 0

    if args.check:
        print(
            f"contributors: README is STALE ({len(people)} people on GitHub). "
            f"Run `python scripts/ci/update_contributors.py` and commit the result.",
            file=sys.stderr,
        )
        return 1

    README.write_text(updated, encoding="utf-8", newline="\n")
    print(f"contributors: README updated ({len(people)} people)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
