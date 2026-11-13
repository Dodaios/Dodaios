#!/usr/bin/env python3
"""Prepare a release commit: bump the version and write the CHANGELOG section.

Used by ``.github/workflows/release-cut.yml`` (a manual, maintainer-only
dispatch — a release never happens by itself) and runnable locally::

    python scripts/ci/cut_release.py --bump patch      # 2.3.2 -> 2.3.3
    python scripts/ci/cut_release.py --version 2.4.0

The package version in ``pyproject.toml`` and ``dodaios/__init__.py`` stays
synchronized with the workspace entry in ``uv.lock``. The CHANGELOG takes the ``[Unreleased]``
notes when there are any; otherwise it is built from the Conventional Commit
subjects since the previous release tag (feat -> Added, fix -> Fixed,
perf/refactor -> Changed). The notes are also written to ``--notes-out`` for
the GitHub Release body. Prints the new version on the last line.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.ci.release_admit import run_command, versions  # noqa: E402

_SECTIONS = {"feat": "Added", "fix": "Fixed", "perf": "Changed", "refactor": "Changed"}
_SUBJECT = re.compile(r"^(?P<type>[a-z]+)(?:\([^)]*\))?(?P<bang>!)?: (?P<text>.+)$")
_RELEASE_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


def bump(version: str, part: str) -> str:
    major, minor, patch = (int(x) for x in version.split("."))
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def notes_from_commits(subjects: list[str]) -> str:
    grouped: dict[str, list[str]] = {"Added": [], "Changed": [], "Fixed": []}
    breaking: list[str] = []
    for subject in subjects:
        match = _SUBJECT.match(subject.strip())
        if not match:
            continue
        section = _SECTIONS.get(match.group("type"))
        text = match.group("text").strip()
        text = text[0].upper() + text[1:]
        if match.group("bang"):
            breaking.append(text)
        if section and text not in grouped[section]:
            grouped[section].append(text)
    parts: list[str] = []
    if breaking:
        parts.append("### Breaking\n\n" + "\n".join(f"- {t}" for t in breaking))
    for section, items in grouped.items():
        if items:
            parts.append(f"### {section}\n\n" + "\n".join(f"- {t}" for t in items))
    return "\n\n".join(parts) or "### Changed\n\n- Maintenance release."


def previous_tag(current: str, tags: list[str]) -> str:
    """The newest ``vX.Y.Z`` tag at or below ``current``, or ``""`` when there is none.

    Chosen by version, not by ``git describe``: a release tag names the
    frontend bundle commit that release-cut.yml puts on top of the release
    commit, so the tag is not on main and ``git describe`` from main skips it.
    It found v4.2.0, the last tag placed on main itself, so the notes of
    v5.0.0 and v5.1.0 repeated those of every release since v4.2.0.
    """
    limit = tuple(int(part) for part in current.split("."))
    best: tuple[tuple[int, ...], str] | None = None
    for tag in (line.strip() for line in tags):
        match = _RELEASE_TAG.match(tag)
        if not match:
            continue
        version = tuple(int(part) for part in match.groups())
        if version <= limit and (best is None or version > best[0]):
            best = (version, tag)
    return best[1] if best else ""


def commits_since_release(current: str, root: Path = REPO_ROOT) -> list[str]:
    """Subjects of the commits on HEAD since the release tag of ``current``.

    ``<tag>..HEAD`` leaves out the tag's bundle commit and everything below
    it, so it holds exactly the commits that landed after the release commit.
    """
    git = ["git", "-C", str(root)]
    tags = run_command([*git, "tag", "--list", "v*"], check=False).stdout.splitlines()
    last = previous_tag(current, tags)
    span = f"{last}..HEAD" if last else "HEAD"
    return run_command([*git, "log", "--no-merges", "--format=%s", span]).stdout.splitlines()


def split_unreleased(changelog: str) -> tuple[str, str, str]:
    """Return (head incl. '## [Unreleased]' line, unreleased body, rest)."""
    match = re.search(r"^## \[Unreleased\][^\n]*\n", changelog, re.MULTILINE)
    if not match:
        raise SystemExit("CHANGELOG.md has no '## [Unreleased]' heading")
    after = changelog[match.end() :]
    nxt = re.search(r"^## \[", after, re.MULTILINE)
    body = after[: nxt.start()] if nxt else after
    rest = after[nxt.start() :] if nxt else ""
    return changelog[: match.end()], body, rest


def section_notes(changelog: str, version: str) -> str:
    """The body of ``## [version]`` without its trailing ``---`` rule."""
    match = re.search(
        rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)", changelog, re.S | re.M
    )
    return (match.group(1) if match else "").strip().rstrip("-").strip()


def apply(version: str, notes: str, today: str, root: Path = REPO_ROOT) -> None:
    pyproject = root / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    lock = root / "uv.lock"
    lock_text = None
    if lock.is_file():
        project = tomllib.loads(text)["project"]
        lock_text = lock.read_text(encoding="utf-8")
        pattern = (
            rf'(?m)(^name = "{re.escape(project["name"])}"\nversion = ")[^"]+'
            r'("\nsource = \{ editable = "\." \})'
        )
        lock_text, count = re.subn(pattern, rf"\g<1>{version}\g<2>", lock_text)
        if count != 1:
            raise ValueError("uv.lock must contain exactly one editable project version")
    text = re.sub(r'(?m)^version = "[^"]+"', f'version = "{version}"', text, count=1)
    pyproject.write_bytes(text.encode("utf-8"))
    init = root / "dodaios" / "__init__.py"
    text = init.read_text(encoding="utf-8")
    text = re.sub(r'__version__ = "[^"]+"', f'__version__ = "{version}"', text, count=1)
    init.write_bytes(text.encode("utf-8"))
    changelog = root / "CHANGELOG.md"
    head, _body, rest = split_unreleased(changelog.read_text(encoding="utf-8"))
    section = f"## [{version}] — {today}\n\n{notes.strip()}\n\n---\n\n"
    changelog.write_bytes((head + "\n---\n\n" + section + rest).encode("utf-8"))
    if lock_text is not None:
        lock.write_bytes(lock_text.encode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--bump", choices=("patch", "minor", "major"))
    group.add_argument("--version")
    group.add_argument("--print-notes", metavar="X.Y.Z", help="Print a released section.")
    parser.add_argument("--notes-out", type=Path, default=Path("release-notes.md"))
    args = parser.parse_args(argv)
    if args.print_notes:
        print(
            section_notes(
                (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), args.print_notes
            )
        )
        return 0

    current, package = versions()
    if current != package:
        raise SystemExit(f"version drift: pyproject {current} vs jarvis {package}")
    new = args.version or bump(current, args.bump)
    if not re.fullmatch(r"\d+\.\d+\.\d+", new):
        raise SystemExit(f"not a SemVer version: {new}")
    if any(str(int(part)) != part for part in new.split(".")):
        raise SystemExit("SemVer components must not have leading zeroes")
    if tuple(map(int, new.split("."))) <= tuple(map(int, current.split("."))):
        raise SystemExit("release version must be greater than the current version")
    changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    if re.search(rf"^## \[{re.escape(new)}\]", changelog, re.MULTILINE):
        raise SystemExit("the requested version already has a CHANGELOG section")
    _head, body, _rest = split_unreleased(changelog)
    unreleased = body.strip().strip("-").strip()
    if not unreleased:
        unreleased = notes_from_commits(commits_since_release(current))
    apply(new, unreleased, dt.date.today().isoformat())
    args.notes_out.write_text(unreleased.strip() + "\n", encoding="utf-8")
    print(new)
    return 0


if __name__ == "__main__":
    sys.exit(main())
