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
* ``Co-authored-by`` trailers on the default branch. A contribution from a
  pull request that was closed and landed in another one names its author
  only there, and neither source above counts co-authors. The trailers are
  read from the local history (the checkout must be complete), and GitHub
  resolves their emails to accounts, the way it shows co-authors on a
  commit. A co-author whose email no account claims stays off the wall.

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
ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"

START = "<!-- contributors:start -->"
END = "<!-- contributors:end -->"

#: Accounts that the contributors API reports but that never contributed here.
#: See the module docstring for why the AI co-author trailer lands on a
#: third-party account.
EXCLUDED_LOGINS = frozenset({"claude"})

#: Co-author addresses of AI coding agents. Their trailers credit a tool, not
#: a person, so they are dropped before GitHub is asked who owns an address.
AI_AGENT_EMAILS = frozenset({"noreply@anthropic.com", "cursoragent@cursor.com"})

#: Commits per GraphQL query when co-author emails are resolved.
RESOLVE_BATCH = 50

#: The wall is one flow of avatars with no table and no names, the way
#: OpenClaw shows its contributors: GitHub wraps it to the width of the page.
#: Avatars per source line only keeps README.md readable.
PER_LINE = 10
#: Shown size. The image is fetched at twice this, so it stays sharp on a
#: high-density screen.
AVATAR_PX = 48

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


def _trailer_emails(values: str) -> list[str]:
    """The addresses in ``Co-authored-by`` values, lower case, people only.

    AI agents (``AI_AGENT_EMAILS``) and bots (``[bot]`` in the address) are
    dropped: they are tools, and the wall thanks people.
    """
    emails: list[str] = []
    for value in values.split("\x1e"):
        value = value.strip()
        if "<" not in value or not value.endswith(">"):
            continue
        email = value[value.rindex("<") + 1 : -1].strip().lower()
        if not email or email in AI_AGENT_EMAILS or "[bot]" in email:
            continue
        if email not in emails:
            emails.append(email)
    return emails


def coauthored_commits(log: str) -> dict[str, list[str]]:
    """``sha -> co-author emails`` for every commit that credits a person.

    ``log`` is ``git log --format=%H%x1f<trailer values>%x1d``: a record per
    commit, the hash and its ``Co-authored-by`` values separated by 0x1f,
    the values among themselves by 0x1e.
    """
    commits: dict[str, list[str]] = {}
    for record in log.split("\x1d"):
        sha, _, values = record.strip().partition("\x1f")
        emails = _trailer_emails(values)
        if sha and emails:
            commits[sha] = emails
    return commits


def credit_coauthors(commits: dict[str, list[str]], resolved: dict[str, list[dict]]) -> list[dict]:
    """One entry per account credited as a co-author, counted per commit.

    ``resolved`` maps a hash to the commit's authors as GitHub resolved them
    (``email`` and ``user``). Only an author whose address is one of that
    commit's co-author trailers counts; the git author is counted by the
    contributors API already.
    """
    by_login: dict[str, dict] = {}
    for sha, emails in commits.items():
        wanted = set(emails)
        seen: set[str] = set()
        for author in resolved.get(sha) or []:
            email = str(author.get("email") or "").strip().lower()
            user = author.get("user") or {}
            login = str(user.get("login") or "")
            if email not in wanted or not _keep(login, "User") or login in seen:
                continue
            seen.add(login)
            entry = by_login.setdefault(
                login,
                {
                    "login": login,
                    "avatar_url": user.get("avatarUrl") or "",
                    "type": "User",
                    "contributions": 0,
                },
            )
            entry["contributions"] += 1
    return list(by_login.values())


def _git(*args: str) -> str:
    proc = subprocess.run(  # noqa: S603 - fixed git argv, no user input
        ["git", "-C", str(ROOT), *args],  # noqa: S607 - git from PATH
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {proc.stderr.strip()[:400]}")
    return proc.stdout


def _resolve_commit_authors(shas: list[str]) -> dict[str, list[dict]]:
    """Ask GitHub who each commit's authors are, ``RESOLVE_BATCH`` at a time."""
    owner, name = REPO.split("/")
    resolved: dict[str, list[dict]] = {}
    for start in range(0, len(shas), RESOLVE_BATCH):
        batch = shas[start : start + RESOLVE_BATCH]
        fields = "\n".join(
            f'c{i}: object(oid: "{sha}") {{ ... on Commit {{ authors(first: 20) '
            f"{{ nodes {{ email user {{ login avatarUrl }} }} }} }} }}"
            for i, sha in enumerate(batch)
        )
        query = f'query {{ repository(owner: "{owner}", name: "{name}") {{\n{fields}\n}} }}'
        payload = _read_json(
            urllib.request.Request(
                "https://api.github.com/graphql",
                data=json.dumps({"query": query}).encode(),
                headers={**_headers(), "Content-Type": "application/json"},
                method="POST",
            )
        )
        if not isinstance(payload, dict) or payload.get("errors"):
            detail = repr(payload)[:400]
            raise SystemExit(f"GitHub GraphQL returned errors: {detail}")
        repository = payload["data"]["repository"]
        for i, sha in enumerate(batch):
            commit = repository.get(f"c{i}") or {}
            resolved[sha] = list(((commit.get("authors") or {}).get("nodes")) or [])
    return resolved


def fetch_coauthor_credits() -> list[dict]:
    """Accounts credited in ``Co-authored-by`` trailers on the checked-out branch."""
    if _git("rev-parse", "--is-shallow-repository").strip() == "true":
        raise SystemExit(
            "update_contributors.py reads co-authors from the git history: run it "
            "in a complete clone (the workflow checks out with fetch-depth: 0)."
        )
    log = _git("log", "--format=%H%x1f%(trailers:key=Co-authored-by,valueonly,separator=%x1e)%x1d")
    commits = coauthored_commits(log)
    if not commits:
        return []
    return credit_coauthors(commits, _resolve_commit_authors(list(commits)))


def combine(
    commit_people: list[dict], pr_people: list[dict], coauthors: list[dict] | None = None
) -> list[dict]:
    """Every human who shipped something, most work first.

    A GitHub account is ranked by its commit count, or by its merged pull
    request count when the contributors index has not listed it yet, plus the
    commits it is credited on as a co-author. Anonymous git names fold into an
    account when exactly one merged-pull-request author used that name. Names
    that fold nowhere stay, without their email.
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

    for person in coauthors or []:
        login = person.get("login") or ""
        if not _keep(login, person.get("type") or "User"):
            continue
        count = int(person.get("contributions") or 0)
        entry = users.get(login)
        if entry is None:
            users[login] = {
                "login": login,
                "avatar_url": person.get("avatar_url") or "",
                "contributions": count,
            }
        else:
            if not entry["avatar_url"]:
                entry["avatar_url"] = person.get("avatar_url") or ""
            # A co-authored commit is one the person did not author, so it
            # adds to what the other sources counted.
            entry["contributions"] += count

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
    return combine(
        fetch_commit_contributors(), fetch_merged_pull_authors(), fetch_coauthor_credits()
    )


def _avatar_src(url: str) -> str:
    join = "&" if "?" in url else "?"
    return f"{url}{join}s={AVATAR_PX * 2}"


def _avatar(person: dict) -> str:
    """One avatar linked to the profile. The login is its alt text and tooltip."""
    login = person["login"]
    safe = html.escape(login, quote=True)
    return (
        f'<a href="https://github.com/{safe}">'
        f'<img src="{_avatar_src(person.get("avatar_url") or "")}" '
        f'width="{AVATAR_PX}" height="{AVATAR_PX}" alt="{safe}" title="{safe}"></a>'
    )


def _marked(line: str) -> str:
    # GitHub logins and real names are not prose: a login or a name made of
    # German words must not trip the output-language gate, so every line
    # carries its escape marker.
    return line + f" <!-- {LANGUAGE_GATE_ESCAPE} -->"


def render(people: list[dict]) -> str:
    """The avatar wall: linked avatars side by side, ``PER_LINE`` to a line.

    The lines form one paragraph, so GitHub flows the avatars into as many
    rows as the page is wide. The login shows on hover, not under the
    avatar. People with no linked account are left out. Their only identity
    is a git author name, which is often someone else's machine login, so
    printing it would name the wrong person.
    """
    accounts = [person for person in people if person.get("login")]
    if not accounts:
        return "_Nobody yet. That first square is yours._"
    return "\n".join(
        _marked(" ".join(_avatar(person) for person in accounts[i : i + PER_LINE]))
        for i in range(0, len(accounts), PER_LINE)
    )


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
