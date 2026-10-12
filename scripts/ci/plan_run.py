#!/usr/bin/env python3
"""Size a CI run: which tier it is and how wide every job matrix gets.

The organisation has 60 concurrent jobs, 5 of them macOS. A run that fans out
to ~65 jobs with ~10 macOS legs fills that pool on its own; two agents pushing
at once queue everything behind it. So the width of a run follows what the
run has to prove, not what could be run:

``pr``     A pull request (or a branch run the merge train dispatched). Fast
           feedback: the whole Linux and Windows suite, every affected lane on
           Linux and Windows, no macOS, and without the slowest real-runtime
           leg. It is the admission ticket to the merge queue.
``queue``  A merge-queue group, or a push that reached main without one. The
           blocking proof of the exact tree main gets: everything ``pr`` runs
           plus one macOS leg per affected lane and the slow legs.
``full``   Nightly, a release tag, a manual full dispatch. The wide matrix:
           Intel macOS, the ARM runners, every interpreter, the macOS test
           shards. Unchanged in scope; it only stopped running per change.

``macos`` (nightly, tags, a dispatch with ``include_macos``) selects the wide
matrix on any tier: ``gh workflow run ci.yml --ref <branch> -f full=false
-f include_macos=true`` is how a branch gets macOS feedback before the queue.

``proven`` answers one question for a run on main: did the merge queue already
pass this exact commit? A queue group and the push that lands it share one
SHA, so re-running the suite on the push repeats finished work.

Usage::

    python scripts/ci/plan_run.py plan --event pull_request
    python scripts/ci/plan_run.py proven --repo owner/name --sha <sha>
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

LINUX = "ubuntu-latest"
WINDOWS = "windows-latest"
MACOS = "macos-latest"
MACOS_INTEL = "macos-15-intel"
MACOS_ARM = "macos-15"
LINUX_ARM = "ubuntu-24.04-arm"
WINDOWS_ARM = "windows-11-arm"

TIERS = ("pr", "queue", "full")
CI_WORKFLOW_PATH = ".github/workflows/ci.yml"

LINUX_SHARDS = 6
# Six Windows shards finish in about the time of the Linux ones plus the
# slower checkout; four made Windows the longest leg of every run.
WINDOWS_SHARDS = 6


def decide(event: str, *, full_input: bool = False, macos_input: bool = False) -> dict[str, Any]:
    """The run mode for a trigger: tier plus the flags the workflow reads."""
    full = macos = pr_mode = False
    if event in {"push", "merge_group"}:
        tier = "queue"
    elif event == "schedule":
        tier, full, macos = "full", True, True
    elif event == "workflow_dispatch":
        macos = macos_input
        if full_input:
            tier, full = "full", True
        else:
            # A branch run the merge train dispatched behaves like its pull request.
            tier, pr_mode = "pr", True
    else:
        tier, pr_mode = "pr", True
    return {
        "tier": tier,
        "full_mode": full,
        "macos": macos,
        "pr_mode": pr_mode,
        # One macOS leg per affected lane: in the queue, and wherever the
        # caller asked for macOS.
        "mac_lanes": tier == "queue" or macos,
    }


def matrices(tier: str, *, macos: bool) -> dict[str, Any]:
    """Every job matrix of ci.yml for a tier. ``macos`` adds the wide legs."""
    if tier not in TIERS:
        raise ValueError(f"unknown tier {tier!r}")
    mac_lanes = tier == "queue" or macos
    slow_legs = tier != "pr"
    base_os = [LINUX, WINDOWS]

    updater = [
        {"os": LINUX, "python": "3.11"},
        {"os": LINUX, "python": "3.12"},
        # The 3.12 Windows leg compiles the real Inno script and upgrades a
        # running install: the one handover proof a pull request keeps.
        {"os": WINDOWS, "python": "3.12"},
    ]
    if slow_legs:
        updater.append({"os": WINDOWS, "python": "3.11"})
    if mac_lanes:
        updater.append({"os": MACOS, "python": "3.12"})
    if macos:
        updater += [{"os": MACOS, "python": "3.11"}, {"os": MACOS_INTEL, "python": "3.12"}]

    # The two architectures without an upstream cryptography wheel come first;
    # the wide matrix adds the second interpreter and Apple Silicon.
    crypto = [{"runner": WINDOWS_ARM, "architecture": "arm64", "python": "3.12"}]
    if mac_lanes:
        crypto.append({"runner": MACOS_INTEL, "architecture": "x64", "python": "3.11"})
    if macos:
        crypto += [
            {"runner": MACOS_INTEL, "architecture": "x64", "python": "3.14"},
            {"runner": MACOS_ARM, "architecture": "arm64", "python": "3.11"},
            {"runner": MACOS_ARM, "architecture": "arm64", "python": "3.14"},
            {"runner": WINDOWS_ARM, "architecture": "arm64", "python": "3.14"},
        ]

    # The real Hermes install on Windows takes ~18 minutes: it would be the
    # longest job of every pull request, so it waits for the queue.
    e2e = [
        {"os": LINUX, "runtime": "hermes"},
        {"os": LINUX, "runtime": "openclaw"},
        {"os": WINDOWS, "runtime": "openclaw"},
    ]
    if slow_legs:
        e2e.append({"os": WINDOWS, "runtime": "hermes"})
    if mac_lanes:
        e2e += [{"os": MACOS, "runtime": "hermes"}, {"os": MACOS, "runtime": "openclaw"}]

    browser = list(base_os)
    if mac_lanes:
        browser.append(MACOS)
    if macos:
        browser += [LINUX_ARM, WINDOWS_ARM, MACOS_INTEL]

    return {
        # jarvisctl, dragdrop and the installer smoke stay off macOS unless
        # the wide matrix is on: nothing in them is macOS-specific.
        "os_matrix": base_os + ([MACOS] if macos else []),
        "lane_os": base_os + ([MACOS] if mac_lanes else []),
        "updater_matrix": updater,
        "crypto_matrix": crypto,
        "e2e_matrix": e2e,
        "browser_os": browser,
        # Skipped on a pull request; the queue proves the Apple Silicon
        # bundle, the wide matrix adds both Intel rows.
        "desktop_legs": "all" if macos else ("primary" if mac_lanes else "none"),
        "linux_shards": list(range(1, LINUX_SHARDS + 1)),
        "windows_shards": list(range(1, WINDOWS_SHARDS + 1)),
    }


def plan(event: str, *, full_input: bool = False, macos_input: bool = False) -> dict[str, Any]:
    mode = decide(event, full_input=full_input, macos_input=macos_input)
    return {**mode, **matrices(mode["tier"], macos=mode["macos"])}


def proven_by_queue(runs: list[dict[str, Any]], *, repo: str, sha: str) -> bool:
    """Whether a merge-queue CI run of this repository passed exactly ``sha``."""
    for run in runs:
        if (
            run.get("head_sha") == sha
            and run.get("event") == "merge_group"
            and run.get("status") == "completed"
            and run.get("conclusion") == "success"
            and run.get("path") == CI_WORKFLOW_PATH
            and ((run.get("head_repository") or {}).get("full_name")) == repo
        ):
            return True
    return False


def fetch_runs(repo: str, sha: str, token: str) -> list[dict[str, Any]]:
    url = (
        f"https://api.github.com/repos/{repo}/actions/workflows/ci.yml/runs"
        f"?head_sha={sha}&event=merge_group&status=success&per_page=20"
    )
    request = urllib.request.Request(  # noqa: S310 - fixed https host
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        payload = json.load(response)
    runs = payload.get("workflow_runs") if isinstance(payload, dict) else None
    return runs if isinstance(runs, list) else []


def is_proven(
    repo: str,
    sha: str,
    token: str,
    fetch: Callable[[str, str, str], list[dict[str, Any]]] = fetch_runs,
) -> bool:
    """Fail open: any doubt (no token, API error, odd payload) means not proven."""
    if not (repo and sha and token):
        return False
    try:
        return proven_by_queue(fetch(repo, sha, token), repo=repo, sha=sha)
    except (OSError, ValueError, urllib.error.URLError) as exc:
        print(f"::warning::could not ask for a merge-queue run of {sha}: {exc}")
        return False


def _render(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    return json.dumps(value, separators=(",", ":"))


def _emit(values: dict[str, Any]) -> None:
    lines = [f"{key}={_render(value)}" for key, value in values.items()]
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    print("\n".join(lines))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    plan_cmd = commands.add_parser("plan", help="Emit the tier, flags and matrices.")
    plan_cmd.add_argument("--event", required=True)
    plan_cmd.add_argument("--full", default="false", help="The dispatch input `full`.")
    plan_cmd.add_argument("--include-macos", default="false")
    proven_cmd = commands.add_parser("proven", help="Emit proven=true|false for a commit.")
    proven_cmd.add_argument("--repo", required=True)
    proven_cmd.add_argument("--sha", required=True)
    args = parser.parse_args(argv)

    if args.command == "plan":
        _emit(
            plan(
                args.event,
                full_input=args.full == "true",
                macos_input=args.include_macos == "true",
            )
        )
    else:
        token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
        _emit({"proven": is_proven(args.repo, args.sha, token)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
