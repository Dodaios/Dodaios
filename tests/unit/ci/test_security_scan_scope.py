"""The dependency scan sees every hash-pinned lock, and the browser helper's
lock carries no known-vulnerable version without a written reason.

The browser helper installs from its own lock (``dodaios/assets/browser``). That
lock sat outside the scan and outside the security floors of the app's own
lock, and fell thirteen packages behind them. Two things keep that from
recurring: every tracked lock that pins by hash is on the scanner's list, and a
package the audit found behind is either at a fixed version or named, at the
pinned version, in the ``osv-scanner.toml`` beside the lock.
"""

from __future__ import annotations

import datetime
import re
import subprocess
import tomllib
from pathlib import Path

import pytest
import yaml
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github" / "workflows" / "security.yml"
BROWSER = ROOT / "dodaios" / "assets" / "browser"

_HASH_LINE = re.compile(r"^\s+--hash=sha256:[0-9a-f]{64}", re.MULTILINE)
_PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;]+)", re.MULTILINE)
#: File names the scanner reads as a pip requirements file without being told.
_PIP_NAME = re.compile(r".*requirements.*\.txt")

#: The first release without the advisories the 2026-11-23 audit found in the
#: browser lock. A package may sit below its floor only with an exception.
ADVISORY_FLOORS = {
    "aiohttp": "3.14.4",
    "anyio": "4.14.2",
    "certifi": "2026.10.18",
    "mcp": "2.2.0",
    "multidict": "6.9.1",
    "oauthlib": "4.0.1",
    "opentelemetry-api": "1.45.2",
    "pillow": "13.0.0",
    "pyasn1": "0.6.5",
    "pyjwt": "2.15.0",
    "pypdf": "6.21.4",
    "soupsieve": "4.0.0",
    "urllib3": "2.8.0",
}


def _tracked(*patterns: str) -> list[str]:
    try:
        listed = subprocess.run(
            ["git", "ls-files", "--", *patterns],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        pytest.skip("not a git checkout")
    return [line for line in listed.stdout.splitlines() if line]


def _scan_lines() -> list[str]:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    args = workflow["jobs"]["osv-scanner"]["with"]["scan-args"]
    return [line.strip() for line in args.splitlines() if line.strip()]


def _scanned() -> dict[str, str]:
    """``path -> parser name`` ("" when the scanner infers it from the file name)."""
    scanned: dict[str, str] = {}
    for line in _scan_lines():
        flag, _, value = line.partition(" ")
        assert flag == "-L", f"unexpected scan argument: {line}"
        parser, _, path = value.strip().rpartition(":")
        scanned[path] = parser
    return scanned


def _pins(lock: Path) -> dict[str, list[str]]:
    pins: dict[str, list[str]] = {}
    for name, version in _PIN.findall(lock.read_text(encoding="utf-8")):
        pins.setdefault(name.lower(), []).append(version)
    return pins


def _exceptions() -> list[dict]:
    config = tomllib.loads((BROWSER / "osv-scanner.toml").read_text(encoding="utf-8"))
    return list(config.get("PackageOverrides", []))


def test_every_tracked_hash_pinned_lock_is_scanned() -> None:
    hash_pinned = [
        path
        for path in _tracked("*.txt", "*.lock")
        if _HASH_LINE.search((ROOT / path).read_text(encoding="utf-8", errors="replace"))
    ]
    scanned = _scanned()

    assert "requirements.txt" in hash_pinned
    assert f"{BROWSER.relative_to(ROOT).as_posix()}/requirements.lock" in hash_pinned
    missing = sorted(set(hash_pinned) - set(scanned))
    assert not missing, f"hash-pinned locks the dependency scan does not read: {missing}"


def test_every_scanned_file_exists_and_is_read_with_a_parser() -> None:
    for path, parser in _scanned().items():
        assert (ROOT / path).is_file(), f"the scan names a file that is not there: {path}"
        name = Path(path).name
        if parser:
            assert parser == "requirements.txt", f"{path}: unexpected parser {parser!r}"
        elif name not in {"package-lock.json", "uv.lock"}:
            # The scanner picks its parser from the file name. A pip lock under
            # another name has to say `requirements.txt:<path>`.
            assert _PIP_NAME.fullmatch(name), f"{path} needs `requirements.txt:` in front"


def test_the_browser_lock_is_at_a_fixed_version_or_says_why_not() -> None:
    pins = _pins(BROWSER / "requirements.lock")
    excepted = {(entry["name"].lower(), entry["version"]) for entry in _exceptions()}

    behind = []
    for name, floor in ADVISORY_FLOORS.items():
        assert name in pins, f"{name} left the browser lock; drop it from ADVISORY_FLOORS"
        for version in pins[name]:
            if Version(version) < Version(floor) and (name, version) not in excepted:
                behind.append(f"{name}=={version} (fixed in {floor})")
    assert not behind, f"known-vulnerable pins without an exception: {behind}"


def test_every_exception_names_a_pinned_version_and_gives_a_reason() -> None:
    pins = _pins(BROWSER / "requirements.lock")
    entries = _exceptions()

    assert entries, "the exceptions file lists the packages browser-use pins"
    for entry in entries:
        name = entry["name"].lower()
        label = f"{name}=={entry.get('version')}"
        # An exception for a version the lock no longer pins hides nothing and
        # explains nothing: it goes when the lock moves.
        assert entry.get("version") in pins.get(name, []), f"stale exception: {label}"
        assert entry.get("ecosystem") == "PyPI", label
        # Vulnerabilities of this one version only; never the whole package.
        assert entry.get("vulnerability") == {"ignore": True}, label
        assert "ignore" not in entry, label
        assert len(str(entry.get("reason", ""))) >= 40, f"{label} needs a reason"
        assert isinstance(entry.get("effectiveUntil"), datetime.date), f"{label} needs an end date"
        # Below its floor, or it would not need an exception at all.
        assert name in ADVISORY_FLOORS, f"{label}: no advisory floor recorded for it"
        assert Version(entry["version"]) < Version(ADVISORY_FLOORS[name]), label


def test_the_browser_locks_still_install_with_required_hashes() -> None:
    from dodaios.society.browser import install

    for lock in (BROWSER / "requirements.lock", BROWSER / "bootstrap.lock"):
        text = lock.read_text(encoding="utf-8")
        blocks = re.split(r"(?m)^(?=[A-Za-z0-9][A-Za-z0-9._-]*==)", text)[1:]
        assert blocks, lock.name
        unhashed = [block.split()[0] for block in blocks if "--hash=sha256:" not in block]
        assert not unhashed, f"{lock.name}: pip --require-hashes would refuse {unhashed}"

    pins = _pins(BROWSER / "requirements.lock")
    assert pins["browser-use"] == [install.BROWSER_USE_VERSION]
    assert pins["playwright"] == [install.PLAYWRIGHT_VERSION]
