#!/usr/bin/env python3
"""LFS pointer, remote object and size gate of the ``unreal-static`` lane.

Fails when, among the checked paths (architecture.md 8.4, art-pipeline.md 10):

* a ``.uasset``, ``.umap`` or other LFS-routed file is committed as content,
  not as a Git LFS pointer;
* a pointer's object is missing on the remote (pushed without ``git lfs push``);
* one LFS object is larger than 50 MB (warns from 20 MB);
* the LFS objects a pull request adds sum to more than 200 MB
  (``DODAIOS_LFS_GROWTH_APPROVED=1`` is the integration owner's approval);
* a file that is not an LFS pointer is larger than 5 MB.

It reads blobs from Git, so it works with LFS off (``lfs: false`` checkout).

    python scripts/unreal/check_lfs.py --diff origin/main     # paths changed since the base
    python scripts/unreal/check_lfs.py                        # every tracked path in scope
    python scripts/unreal/check_lfs.py --no-remote            # skip the remote object check
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCOPE = ("unreal/", "art/verse/")
MB = 1024 * 1024
WARN_BYTES = 20 * MB
FAIL_BYTES = 50 * MB
PR_GROWTH_BYTES = 200 * MB
PLAIN_FAIL_BYTES = 5 * MB
#: Always binary in the Unreal tree; they must reach Git as LFS pointers.
BINARY_SUFFIXES = (".uasset", ".umap", ".ubulk", ".uexp", ".upk")
POINTER_HEAD = b"version https://git-lfs.github.com/spec/v1"
_OID = re.compile(rb"^oid sha256:([0-9a-f]{64})$", re.M)
_SIZE = re.compile(rb"^size (\d+)$", re.M)
GROWTH_ENV = "DODAIOS_LFS_GROWTH_APPROVED"


@dataclass(frozen=True)
class Pointer:
    path: str
    oid: str
    size: int


def git(*args: str, cwd: Path = REPO_ROOT, data: bytes | None = None) -> bytes:
    proc = subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=cwd,
        input=data,
        capture_output=True,
        check=True,
    )
    return proc.stdout


def parse_pointer(path: str, blob: bytes) -> Pointer | None:
    if not blob.startswith(POINTER_HEAD) or len(blob) > 1024:
        return None
    oid, size = _OID.search(blob), _SIZE.search(blob)
    if not oid or not size:
        return None
    return Pointer(path, oid.group(1).decode(), int(size.group(1)))


def changed_paths(base: str, cwd: Path = REPO_ROOT) -> list[str]:
    out = git("diff", "--name-only", "--diff-filter=AMR", f"{base}...HEAD", "--", *SCOPE, cwd=cwd)
    return [p for p in out.decode("utf-8").splitlines() if p]


def tracked_paths(cwd: Path = REPO_ROOT) -> list[str]:
    return [p for p in git("ls-files", "--", *SCOPE, cwd=cwd).decode("utf-8").splitlines() if p]


def lfs_routed(paths: Sequence[str], cwd: Path = REPO_ROOT) -> set[str]:
    if not paths:
        return set()
    out = git(
        "check-attr", "--stdin", "-z", "filter", cwd=cwd, data="\0".join(paths).encode() + b"\0"
    )
    parts = out.split(b"\0")
    routed = set()
    for i in range(0, len(parts) - 2, 3):
        if parts[i + 2] == b"lfs":
            routed.add(parts[i].decode("utf-8"))
    return routed


def blob_head(rev: str, path: str, cwd: Path = REPO_ROOT) -> tuple[int, bytes]:
    size = int(git("cat-file", "-s", f"{rev}:{path}", cwd=cwd).strip())
    head = git("cat-file", "blob", f"{rev}:{path}", cwd=cwd)[:1024] if size <= 1024 else b""
    return size, head


def check_paths(
    paths: Iterable[str], rev: str = "HEAD", cwd: Path = REPO_ROOT
) -> tuple[list[str], list[str], list[Pointer]]:
    """(errors, warnings, pointers) for ``paths`` as committed at ``rev``."""
    paths = sorted(set(paths))
    routed = lfs_routed(paths, cwd)
    errors: list[str] = []
    warnings: list[str] = []
    pointers: list[Pointer] = []
    for path in paths:
        try:
            size, head = blob_head(rev, path, cwd)
        except subprocess.CalledProcessError:
            continue  # deleted at rev
        pointer = parse_pointer(path, head) if head else None
        must_be_lfs = path in routed or path.lower().endswith(BINARY_SUFFIXES)
        if pointer:
            pointers.append(pointer)
            if pointer.size > FAIL_BYTES:
                errors.append(
                    f"{path}: LFS object of {pointer.size / MB:.1f} MB is over the 50 MB cap"
                )
            elif pointer.size > WARN_BYTES:
                warnings.append(
                    f"{path}: LFS object of {pointer.size / MB:.1f} MB (warn from 20 MB)"
                )
            if path not in routed:
                warnings.append(
                    f"{path}: an LFS pointer on a path .gitattributes does not route to LFS"
                )
            continue
        if must_be_lfs:
            errors.append(
                f"{path}: committed as content, not as a Git LFS pointer (run git lfs install)"
            )
        elif size > PLAIN_FAIL_BYTES:
            errors.append(
                f"{path}: {size / MB:.1f} MB plain file; over 5 MB must be an LFS pointer"
            )
    return errors, warnings, pointers


def growth_errors(pointers: Sequence[Pointer], env: dict[str, str] | None = None) -> list[str]:
    env = os.environ if env is None else env
    total = sum(p.size for p in {p.oid: p for p in pointers}.values())
    if total > PR_GROWTH_BYTES and env.get(GROWTH_ENV) != "1":
        return [f"LFS growth {total / MB:.1f} MB is over 200 MB; the integration owner approves it"]
    return []


# --- remote objects ---

Fetch = Callable[[str, bytes, dict[str, str]], dict]


def batch_url(remote_url: str) -> str:
    url = remote_url.strip()
    match = re.match(r"^git@([^:]+):(.+?)(?:\.git)?/?$", url)
    if match:
        url = f"https://{match.group(1)}/{match.group(2)}"
    url = re.sub(r"^https://[^@/]+@", "https://", url).rstrip("/")
    if not url.endswith(".git"):
        url += ".git"
    return f"{url}/info/lfs/objects/batch"


def _http_fetch(url: str, body: bytes, headers: dict[str, str]) -> dict:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")  # noqa: S310
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def missing_on_remote(
    pointers: Sequence[Pointer],
    remote_url: str,
    *,
    fetch: Fetch = _http_fetch,
    token: str | None = None,
) -> list[str]:
    """Paths whose object the remote's LFS batch API does not have."""
    unique = {p.oid: p for p in pointers}
    if not unique:
        return []
    headers = {
        "Accept": "application/vnd.git-lfs+json",
        "Content-Type": "application/vnd.git-lfs+json",
    }
    if token:
        headers["Authorization"] = (
            "Basic " + base64.b64encode(f"x-access-token:{token}".encode()).decode()
        )
    errors: list[str] = []
    items = list(unique.values())
    for start in range(0, len(items), 100):
        chunk = items[start : start + 100]
        body = json.dumps(
            {
                "operation": "download",
                "transfers": ["basic"],
                "objects": [{"oid": p.oid, "size": p.size} for p in chunk],
            }
        ).encode("utf-8")
        try:
            answer = fetch(batch_url(remote_url), body, headers)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            return [f"LFS batch API unreachable ({exc}); cannot prove the objects were pushed"]
        by_oid = {o.get("oid"): o for o in answer.get("objects", [])}
        for p in chunk:
            obj = by_oid.get(p.oid)
            if obj is None or obj.get("error") or "actions" not in obj:
                code = (obj or {}).get("error", {}).get("code", "absent")
                errors.append(
                    f"{p.path}: LFS object {p.oid[:12]} missing on the remote ({code}); "
                    "run git lfs push"
                )
    return errors


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--diff", metavar="BASE", help="Check paths changed since BASE (PR mode).")
    parser.add_argument("--no-remote", action="store_true", help="Skip the remote object check.")
    parser.add_argument("--remote", default="origin")
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args(argv)
    paths = args.paths or (changed_paths(args.diff) if args.diff else tracked_paths())
    errors, warnings, pointers = check_paths(paths)
    if args.diff:
        errors += growth_errors(pointers)
    if pointers and not args.no_remote:
        url = git("remote", "get-url", args.remote).decode().strip()
        errors += missing_on_remote(pointers, url, token=os.environ.get("GITHUB_TOKEN"))
    for line in warnings:
        print(f"check_lfs: warning: {line}")
    for line in errors:
        print(f"check_lfs: {line}")
    if errors:
        return 1
    print(f"check_lfs: clean ({len(paths)} paths, {len(pointers)} LFS pointers)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
