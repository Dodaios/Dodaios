"""One commit of a repository, read from git's objects: nothing is checked out or written.

A brief replay answers the lead's reads (the brief kit, the read-only folder
tools) from the repository as it was when the work started. An earlier version
moved one scratch checkout to each task's commit; between two tasks of a
comparison that rewrote hundreds to thousands of files, and a comparison
measures every task twice, so a round wrote tens of thousands of files and
starved the person's disk. This module reads the commit itself instead:

* the paths and sizes from ``git ls-tree -r -l``, once per commit;
* a file's text from one ``git cat-file --batch`` process;
* a search with ``git grep ... <commit>``.

Every git process runs at low priority (``process_utils.child_argv`` and
``child_creationflags``, below normal on Windows, ``nice`` on Unix), never
takes a lock (``GIT_OPTIONAL_LOCKS=0``), and only reads the person's clone: its
working tree, index, branches and worktrees stay as they are.

:class:`CommitFiles` answers what the brief kit asks (``repo_facts.RepoFiles``).
:func:`look` answers the app's read-only folder tools (``Read``, ``Ls``,
``Glob``, ``Grep`` of ``dodaios.agent_chat.tools``) the way those tools answer
on a checkout of the same commit: the same messages, limits and walk order,
pinned by a test against the tools themselves. What differs: only files the
commit tracks exist (no ignored or untracked files, no ``.git``), and a ``Grep``
first asks ``git grep -P`` which files can match, then runs the tool's own
expression on those.
"""

from __future__ import annotations

import fnmatch
import io
import logging
import os
import re
import subprocess
import threading
import time
from collections.abc import Iterator, Mapping
from pathlib import Path, PurePosixPath
from typing import IO, Any, Final

from dodaios.core.process_utils import child_argv, child_creationflags

__all__ = ["CommitFiles", "look"]

log = logging.getLogger(__name__)

_TIMEOUT_S: Final[float] = 60.0
_GREP_TIMEOUT_S: Final[float] = 1.5
#: A file read in full (a ``Read``, a ``Grep`` line by line): the tool reads it whole too.
_WHOLE: Final[int] = 1 << 62


def _env() -> dict[str, str]:
    return {**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0"}


def _text(blob: bytes) -> str:
    """Bytes as a file read in text mode gives them: UTF-8 (errors replaced), newlines as \\n."""
    return blob.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")


class CommitFiles:
    """The files of ``commit`` in the repository of ``clone``, by paths relative to its root."""

    def __init__(self, clone: Path, commit: str) -> None:
        #: The person's clone: the folder the lead names, read only through git.
        self.root = Path(clone)
        self.commit = commit
        self._sizes: dict[str, int] | None = None
        self._dirs: dict[str, dict[str, bool]] = {}
        self._batch: subprocess.Popen[bytes] | None = None
        self._lock = threading.Lock()
        self._index: Any = None

    # ------------------------------------------------------------------ git

    def _git(
        self, args: list[str], *, timeout: float = _TIMEOUT_S
    ) -> subprocess.CompletedProcess[bytes] | None:
        argv = child_argv(
            ["git", "-C", str(self.root), "-c", "core.quotePath=false", *args], background=True
        )
        try:
            return subprocess.run(  # noqa: S603 - fixed git argv, read only
                argv,
                capture_output=True,
                timeout=timeout,
                env=_env(),
                check=False,
                creationflags=child_creationflags(background=True),
            )
        except (OSError, subprocess.SubprocessError):  # no git, or too slow: no answer
            log.debug("self-improvement: git %s did not answer", args[:1], exc_info=True)
            return None

    def exists(self) -> bool:
        """Whether the clone holds the commit."""
        done = self._git(["cat-file", "-e", f"{self.commit}^{{commit}}"])
        return done is not None and done.returncode == 0

    def _listing(self) -> dict[str, int]:
        if self._sizes is not None:
            return self._sizes
        sizes: dict[str, int] = {}
        dirs: dict[str, dict[str, bool]] = {"": {}}
        done = self._git(["ls-tree", "-r", "-l", "-z", "--full-tree", self.commit])
        for row in (done.stdout if done is not None and done.returncode == 0 else b"").split(b"\0"):
            head, _, raw = row.partition(b"\t")
            parts = head.split()
            if len(parts) < 4 or parts[1] != b"blob":
                continue  # a submodule or a malformed row names no file
            rel = raw.decode("utf-8", errors="replace")
            sizes[rel] = int(parts[3]) if parts[3].isdigit() else 0
            parent = ""
            for part in rel.split("/")[:-1]:
                dirs.setdefault(parent, {})[part] = True
                parent = f"{parent}/{part}" if parent else part
                dirs.setdefault(parent, {})
            dirs.setdefault(parent, {})[rel.rsplit("/", 1)[-1]] = False
        self._sizes, self._dirs = sizes, dirs
        return sizes

    def _read_blob(self, rel: str) -> bytes | None:
        with self._lock:
            if self._batch is None or self._batch.poll() is not None:
                self._batch = subprocess.Popen(  # noqa: S603 - fixed git argv, read only
                    child_argv(
                        ["git", "-C", str(self.root), "cat-file", "--batch"], background=True
                    ),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    env=_env(),
                    creationflags=child_creationflags(background=True),
                )
            proc = self._batch
            stdin: IO[bytes] | None = proc.stdin
            stdout: IO[bytes] | None = proc.stdout
            if stdin is None or stdout is None:
                return None
            try:
                stdin.write(f"{self.commit}:{rel}\n".encode())
                stdin.flush()
                header = stdout.readline().split()
                if len(header) != 3 or header[1] != b"blob":
                    return None  # "missing", or a folder
                size = int(header[2])
                blob = stdout.read(size)
                stdout.read(1)  # the newline after the object
            except (OSError, ValueError):  # the process ended under us: the file is unreadable
                log.debug("self-improvement: git cat-file stopped", exc_info=True)
                return None
            return blob

    def close(self) -> None:
        """End the ``cat-file`` process."""
        with self._lock:
            proc, self._batch = self._batch, None
        if proc is None:
            return
        try:
            if proc.stdin is not None:
                proc.stdin.close()
            proc.wait(timeout=5)
        except (OSError, subprocess.SubprocessError):  # it would not end on its own
            proc.kill()

    # ------------------------------------------------------ repo_facts.RepoFiles

    @staticmethod
    def _clean(rel: str) -> str:
        return PurePosixPath(rel.replace("\\", "/")).as_posix().strip("/").removeprefix("./")

    def is_file(self, rel: str) -> bool:
        return self._clean(rel) in self._listing()

    def is_dir(self, rel: str) -> bool:
        self._listing()
        clean = self._clean(rel)
        return (clean if clean != "." else "") in self._dirs

    def entries(self, rel: str) -> dict[str, bool]:
        """Name -> is a folder, for the folder ``rel``."""
        self._listing()
        clean = self._clean(rel)
        return dict(self._dirs.get(clean if clean != "." else "", {}))

    def names(self, rel: str) -> list[str]:
        if not self.is_dir(rel):
            raise NotADirectoryError(rel)
        return list(self.entries(rel))

    def read(self, rel: str, limit: int = 200_000) -> str:
        clean = self._clean(rel)
        if clean not in self._listing():
            return ""
        blob = self._read_blob(clean)
        return _text(blob)[:limit] if blob is not None else ""

    def source(self, rel: str) -> str:
        """Within ``code_skeleton.read_source``'s bounds: a safe relative path, a small file."""
        from dodaios.agentic_ide import code_skeleton

        if not rel or rel.startswith(("/", "\\")) or ":" in rel[:3]:
            return ""
        if ".." in rel.replace("\\", "/").split("/"):
            return ""
        size = self._listing().get(self._clean(rel))
        if size is None or size > code_skeleton._MAX_SOURCE_BYTES:  # noqa: SLF001 - the same bound
            return ""
        return self.read(rel, _WHOLE)

    def index(self, wait_s: float) -> Any:
        from dodaios.agentic_ide import file_index

        if self._index is None:
            self._index = file_index.index_from_listing(self.root, self._listing())
        return self._index

    def files_with(self, word: str, stop_at: float) -> list[str] | None:
        left = stop_at - time.monotonic()
        if left <= 0.05:
            return []
        done = self._git(
            ["grep", "-I", "-i", "-l", "-F", "-e", word, self.commit],
            timeout=min(_GREP_TIMEOUT_S, left),
        )
        if done is None or done.returncode not in (0, 1):
            return None
        prefix = f"{self.commit}:"
        lines = done.stdout.decode("utf-8", errors="replace").splitlines()
        return [line.removeprefix(prefix) for line in lines]

    # ------------------------------------------------------------- folder tools

    def walk(self, rel: str, skip: frozenset[str]) -> Iterator[str]:
        """The files below ``rel`` in the order ``os.walk`` gives them on Windows (NTFS)."""
        clean = self._clean(rel)
        here = clean if clean != "." else ""
        listed = self.entries(here)
        names = sorted(listed, key=str.upper)
        for name in names:
            if not listed[name]:
                yield f"{here}/{name}" if here else name
        for name in names:
            if listed[name] and name not in skip:
                yield from self.walk(f"{here}/{name}" if here else name, skip)

    def could_match(self, pattern: str, rel: str) -> set[str] | None:
        """The files below ``rel`` that ``git grep -P`` finds ``pattern`` in; None: no answer."""
        where = self._clean(rel)
        done = self._git(
            [
                "grep",
                "-l",
                "-P",
                "-e",
                pattern,
                self.commit,
                "--",
                where if where not in ("", ".") else ".",
            ]
        )
        if done is None or done.returncode not in (0, 1):
            return None  # this git cannot match the expression: every file is read
        prefix = f"{self.commit}:"
        lines = done.stdout.decode("utf-8", errors="replace").splitlines()
        return {line.removeprefix(prefix) for line in lines}


def _inside(path: Path, root: Path) -> str | None:
    """``path`` relative to ``root`` (``""`` for the root itself), or None outside it."""
    mine = os.path.normcase(os.path.normpath(str(path)))
    base = os.path.normcase(os.path.normpath(str(root)))
    if mine == base:
        return ""
    if not mine.startswith(base.rstrip("\\/") + os.sep):
        return None
    return os.path.relpath(os.path.normpath(str(path)), os.path.normpath(str(root))).replace(
        "\\", "/"
    )


def look(files: CommitFiles, tool: str, args: Mapping[str, Any]) -> tuple[str, bool] | None:
    """What the app's read-only folder ``tool`` answers on a checkout of the commit.

    The folder is the person's clone, as the lead names it. ``None`` when the
    tool is no read-only folder tool or the call reaches outside the repository.
    """
    from dodaios.agent_chat import tools as app

    if tool not in app.READ_ONLY_TOOLS:
        return None
    cwd = files.root
    path = app.resolve_path(cwd, args.get("file_path" if tool == "Read" else "path"))
    rel = _inside(path, cwd)
    if rel is None:
        return None
    if tool == "Read":
        return _read(files, app, path, rel, args)
    if tool == "Ls":
        return _ls(files, app, path, rel)
    if tool == "Glob":
        return _glob(files, app, path, rel, args)
    return _grep(files, app, path, rel, args)


def _read(
    files: CommitFiles, app: Any, path: Path, rel: str, args: Mapping[str, Any]
) -> tuple[str, bool]:
    cwd = files.root
    if not files.is_file(rel):
        return f"File not found: {app._display(path, cwd)}", True  # noqa: SLF001
    lines = files.read(rel, _WHOLE).splitlines()
    offset = int(args.get("offset") or 1)
    limit = args.get("limit")
    start = max(0, offset - 1)
    end = start + int(limit) if limit else len(lines)
    chunk = lines[start:end]
    body = "\n".join(f"{start + i + 1}\t{line}" for i, line in enumerate(chunk))
    header = f"{app._display(path, cwd)} ({len(lines)} lines"  # noqa: SLF001
    if start or end < len(lines):
        header += f", showing {start + 1}-{min(end, len(lines))}"
    header += ")"
    return app._cap(header + "\n" + body, app._READ_CAP_CHARS), False  # noqa: SLF001


def _ls(files: CommitFiles, app: Any, path: Path, rel: str) -> tuple[str, bool]:
    if not files.is_dir(rel):
        return f"Not a directory: {app._display(path, files.root)}", True  # noqa: SLF001
    listed = files.entries(rel)
    entries = sorted(listed, key=lambda name: (not listed[name], name.lower()))
    limit = app._GLOB_MAX_RESULTS  # noqa: SLF001
    shown = [f"{name}/" if listed[name] else name for name in entries[:limit]]
    out = f"{path}\n" + "\n".join(shown)
    if len(entries) > len(shown):
        out += f"\n…and {len(entries) - len(shown)} more"
    return out, False


def _below(rel: str, under: str) -> str:
    return rel[len(under) + 1 :] if under else rel


def _glob(
    files: CommitFiles, app: Any, path: Path, rel: str, args: Mapping[str, Any]
) -> tuple[str, bool]:
    pattern = str(args.get("pattern") or "").strip()
    if not pattern:
        return "pattern is required", True
    if not files.is_dir(rel):
        return f"Not a directory: {app._display(path, files.root)}", True  # noqa: SLF001
    hits: list[str] = []
    for found in files.walk(rel, app._SKIP_DIRS):  # noqa: SLF001
        under = _below(found, rel)
        if fnmatch.fnmatch(under, pattern) or fnmatch.fnmatch(PurePosixPath(found).name, pattern):
            hits.append(under)
            if len(hits) >= app._GLOB_MAX_RESULTS:  # noqa: SLF001
                break
    if not hits:
        return f"No files match {pattern!r} under {path}", False
    return "\n".join(hits), False


def _grep(
    files: CommitFiles, app: Any, path: Path, rel: str, args: Mapping[str, Any]
) -> tuple[str, bool]:
    pattern = str(args.get("pattern") or "")
    if not pattern:
        return "pattern is required", True
    try:
        rx = re.compile(pattern)
    except re.error as exc:
        return f"Invalid regular expression: {exc}", True
    name_glob = str(args.get("glob") or "").strip() or None
    limit = min(int(args.get("max_results") or app._GREP_MAX_RESULTS), app._GREP_MAX_RESULTS)  # noqa: SLF001
    single = files.is_file(rel)
    found = [rel] if single else list(files.walk(rel, app._SKIP_DIRS)) if files.is_dir(rel) else []  # noqa: SLF001
    if not found:
        return f"Nothing to search at {app._display(path, files.root)}", True  # noqa: SLF001
    # Which files can match at all, asked of git once; the tool's own expression decides.
    keep = files.could_match(pattern, rel)
    hits: list[str] = []
    for each in found:
        name = PurePosixPath(each).name
        shown = name if single else _below(each, rel)
        if name_glob and not (
            fnmatch.fnmatch(name, name_glob) or fnmatch.fnmatch(shown, name_glob)
        ):
            continue
        if keep is not None and each not in keep:
            continue
        for no, line in enumerate(io.StringIO(files.read(each, _WHOLE)), start=1):
            if rx.search(line):
                hits.append(f"{shown}:{no}:{line.rstrip()[:300]}")
                if len(hits) >= limit:
                    break
        if len(hits) >= limit:
            break
    if not hits:
        return f"No matches for {pattern!r}", False
    out = "\n".join(hits)
    if len(hits) >= limit:
        out += f"\n…stopped at {limit} matches"
    return out, False
