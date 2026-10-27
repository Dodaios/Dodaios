"""Block list for protected file paths (Risk Register #7 + #6).

Two levels:
- `is_blocked(path)`: single path against glob patterns.
- `filter_diff_paths(diff_text)`: extracts changed files from a
  `git diff --git` block, returns only the blocked ones.
- `check_prompt_for_blocked_paths(prompt)`: scans a mission prompt for
  path references that would be blocked (pre-spawn heuristic).

Patterns follow `fnmatch` glob syntax. The default list covers SSH/AWS/.env/SSL keys.
Extensible via `[phase6.safety].extra_blocked_globs` in jarvis.toml.

Important: Path-Guard is the SECOND line of defense. The Phase-5
`tool_executor` already has a risk-tier blacklist at the tool level; here
we guard specifically against worker diff outputs (mission level).
"""
from __future__ import annotations

import fnmatch
import re
from typing import Final

# Glob patterns against normalized POSIX paths (forward-slash; lowercase
# is not required — fnmatch is case-sensitive in POSIX style; we
# normalize backslashes to forward slashes).
DEFAULT_BLOCKED_GLOBS: Final[tuple[str, ...]] = (
    # SSH
    "**/.ssh",
    "**/.ssh/**",
    "**/id_rsa",
    "**/id_rsa.*",
    "**/id_ed25519",
    "**/id_ed25519.*",
    "**/id_ecdsa",
    "**/id_ecdsa.*",
    "**/known_hosts",
    "**/authorized_keys",
    # AWS
    "**/.aws",
    "**/.aws/**",
    # GitHub CLI
    "**/.config/gh",
    "**/.config/gh/**",
    "**/.config/gh/hosts.yml",
    # Generic credentials
    "**/credentials",
    "**/credentials.*",
    "**/.netrc",
    # Env-Files
    "**/.env",
    "**/.env.*",
    # Cert/Keys
    "**/*.pem",
    "**/*.key",
    "**/*.p12",
    "**/*.pfx",
    # Windows DPAPI / Vault
    "**/AppData/Roaming/Microsoft/Crypto/**",
    "**/AppData/Local/Microsoft/Vault/**",
    # Browser-Profile (Cookies / Saved-Logins)
    "**/AppData/Local/Google/Chrome/User Data/**/Login Data*",
    "**/AppData/Roaming/Mozilla/Firefox/Profiles/**/logins.json",
)


def _normalize(path: str) -> str:
    """Normalize a path to POSIX style for fnmatch."""
    # Backslashes -> forward slashes
    p = path.replace("\\", "/")
    # Remove double slashes
    while "//" in p:
        p = p.replace("//", "/")
    return p


def _basename_pattern(pattern: str) -> str:
    """Strip the leading ``**/`` so fnmatch also matches bare basenames.

    ``fnmatch.translate('**/.env')`` produces ``.*/\\.env\\Z`` — the slash is
    required, meaning ``.env`` (without a parent) would NOT match. We build
    a parallel pattern ``.env`` for basename comparison.
    """
    if pattern.startswith("**/"):
        return pattern[3:]
    return pattern


def is_blocked(
    path: str,
    *,
    extra_globs: tuple[str, ...] = (),
) -> bool:
    """True if `path` matches DEFAULT_BLOCKED_GLOBS or extra_globs.

    We match against both the full path AND the basename (last path
    segment). Rationale: fnmatch's ``**`` requires a slash, so a bare
    ``.env`` (without a parent) would NOT match ``**/.env``. We strip
    ``**/`` for the basename comparison (see ``_basename_pattern``).
    """
    norm = _normalize(path)
    basename = norm.rsplit("/", 1)[-1] if "/" in norm else norm

    for pattern in DEFAULT_BLOCKED_GLOBS:
        if fnmatch.fnmatch(norm, pattern):
            return True
        if fnmatch.fnmatch(basename, _basename_pattern(pattern)):
            return True
    for pattern in extra_globs:
        if fnmatch.fnmatch(norm, pattern):
            return True
        if fnmatch.fnmatch(basename, _basename_pattern(pattern)):
            return True
    return False


# Regex for extracting filenames from `diff --git a/path b/path` headers.
# Accepts both Unix and Windows paths. `(?P<a>...)` and `(?P<b>...)`
# capture the two paths independently (rename detection).
_DIFF_HEADER_RE: Final[re.Pattern[str]] = re.compile(
    r"^diff --git\s+a/(?P<a>\S+)\s+b/(?P<b>\S+)\s*$",
    re.MULTILINE,
)

# Git's C-style quoting for names holding tabs, quotes, backslashes,
# control characters and (with core.quotePath) non-ASCII bytes.
_C_ESCAPES: Final[dict[str, int]] = {
    "a": 7, "b": 8, "t": 9, "n": 10, "v": 11, "f": 12, "r": 13, '"': 34, "\\": 92,
}

#: Lines after the header that name a file on their own, up to end of line.
_NAME_LINE_PREFIXES: Final[tuple[tuple[str, bool], ...]] = (
    # (prefix, strip a/ or b/)
    ("--- ", True),
    ("+++ ", True),
    ("rename from ", False),
    ("rename to ", False),
    ("copy from ", False),
    ("copy to ", False),
)


def _unquote_c(text: str) -> tuple[str, str]:
    """Decode one C-quoted git name at the start of ``text``.

    Returns ``(name, rest)``; ``text`` must start with a double quote.
    """
    out = bytearray()
    index = 1
    while index < len(text):
        char = text[index]
        if char == '"':
            return out.decode("utf-8", "replace"), text[index + 1 :]
        if char == "\\" and index + 1 < len(text):
            nxt = text[index + 1]
            octal = text[index + 1 : index + 4]
            if len(octal) == 3 and all(c in "01234567" for c in octal):
                out.append(int(octal, 8) & 0xFF)
                index += 4
                continue
            out.append(_C_ESCAPES.get(nxt, ord(nxt) & 0xFF))
            index += 2
            continue
        out.extend(char.encode("utf-8"))
        index += 1
    return out.decode("utf-8", "replace"), ""


def _git_name(raw: str, *, strip_prefix: bool) -> str | None:
    """One file name from a ``---``/``+++``/rename/copy line's remainder."""
    raw = raw.rstrip("\r\n")
    if raw.startswith('"'):
        name, _rest = _unquote_c(raw)
    else:
        # Git ends an unquoted name that contains a space with a tab.
        name = raw.split("\t", 1)[0]
    if name == "/dev/null" or not name:
        return None
    if strip_prefix:
        if name[:2] not in ("a/", "b/"):
            return None
        name = name[2:]
    return name


def _header_names(rest: str) -> list[str]:
    """Both names from what follows ``diff --git `` (quoted, spaced or plain)."""
    names: list[str] = []
    if rest.startswith('"'):
        first, tail = _unquote_c(rest)
        names.append(first)
        tail = tail.lstrip(" ")
        if tail.startswith('"'):
            names.append(_unquote_c(tail)[0])
        else:
            names.append(tail)
    elif rest.endswith('"') and ' "' in rest:
        split = rest.rindex(' "')
        names.extend([rest[:split], _unquote_c(rest[split + 1 :])[0]])
    else:
        # Unquoted: `a/P b/P` when nothing was renamed (P may hold spaces);
        # a rename with spaces also has `rename from/to` lines, read below.
        half = (len(rest) - 1) // 2
        if len(rest) % 2 == 1 and rest[half] == " " and rest[2:half] == rest[half + 3 :]:
            names.extend([rest[:half], rest[half + 1 :]])
        else:
            names.extend(rest.split(" "))
    return [name[2:] for name in names if name[:2] in ("a/", "b/")]


def changed_diff_paths(diff_text: str) -> set[str]:
    """Every file name a `git diff` names, in any of git's spellings.

    Reads the ``diff --git`` header (plain, spaced or C-quoted), the
    ``---``/``+++`` lines and ``rename``/``copy`` lines, so a name with a
    space, a tab or non-ASCII bytes is still checked.
    """
    paths: set[str] = set()
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            paths.update(_header_names(line[len("diff --git ") :].rstrip()))
            continue
        for prefix, strip in _NAME_LINE_PREFIXES:
            if line.startswith(prefix):
                name = _git_name(line[len(prefix) :], strip_prefix=strip)
                if name:
                    paths.add(name)
                break
    return paths


def filter_diff_paths(
    diff_text: str,
    *,
    extra_globs: tuple[str, ...] = (),
) -> list[str]:
    """Extract all changed files from a `git diff` block,
    returning only the blocked ones.

    Args:
        diff_text: Output of `git diff HEAD` or `git diff <base>`.
        extra_globs: Additional fnmatch patterns (from jarvis.toml).

    Returns:
        List of blocked paths (deduplicated, sorted).
    """
    if not diff_text:
        return []
    paths: set[str] = set()
    for match in _DIFF_HEADER_RE.finditer(diff_text):
        for key in ("a", "b"):
            p = match.group(key)
            if is_blocked(p, extra_globs=extra_globs):
                paths.add(p)
    for p in changed_diff_paths(diff_text):
        if is_blocked(p, extra_globs=extra_globs):
            paths.add(p)
    return sorted(paths)


# Heuristic for pre-spawn: does not match every substring (which would cause
# false positives on "reading the ssh-config" — no concrete path), but only
# strings that look like file paths (slash, dot, backslash).
_PATH_TOKEN_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:[~./]|\b[A-Za-z]:\\)[\w\-./\\]+",
)


def check_prompt_for_blocked_paths(
    prompt: str,
    *,
    extra_globs: tuple[str, ...] = (),
) -> list[str]:
    """Scan a mission prompt for path tokens that would be blocked.

    Conservative: matches only strings that LOOK LIKE a path (slash, dot,
    or drive letter), NOT bare word substrings. Intended to avoid false
    positives on harmless mentions ("the env variable").

    Returns:
        List of blocked paths found (deduplicated).
    """
    if not prompt:
        return []
    found: set[str] = set()
    for match in _PATH_TOKEN_RE.finditer(prompt):
        token = match.group(0).rstrip(".,;:")
        if is_blocked(token, extra_globs=extra_globs):
            found.add(token)
    return sorted(found)


__all__ = [
    "DEFAULT_BLOCKED_GLOBS",
    "check_prompt_for_blocked_paths",
    "filter_diff_paths",
    "is_blocked",
]
