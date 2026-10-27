"""Exercise release shell boundaries without a repository, credentials or network."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from dodaios.core.process_utils import NO_WINDOW_CREATIONFLAGS

_SHA = "1" * 40
_FAKES = r"""
git() {
  printf 'git %s\n' "$*" >> "$TRACE_FILE"
  case "$1" in
    rev-parse)
      if [ "$2" = HEAD ]; then printf '%s\n' "$FAKE_SHA";
      else printf '%s\n' "$TAG_SHA"; fi ;;
    merge-base) return "$ANCESTOR_EXIT" ;;
    diff)
      case "$*" in
        *--quiet*) return "$BUNDLE_DIFF_EXIT" ;;
        *--name-only*) printf "$STAGED_PATHS" ;;
      esac ;;
    show-ref) return "$TAG_EXISTS" ;;
    show) printf '[project]\n' ;;
    checkout) : > checked-out ;;
  esac
  return 0
}
gh() {
  printf 'gh %s\n' "$*" >> "$TRACE_FILE"
  case "$1 $2" in
    'pr create') printf 'https://github.com/example/project/pull/1\n' ;;
    'pr merge') return "$LAND_EXIT" ;;
    'pr view') printf '%s\n' "$FAKE_SHA" ;;
    'workflow run') return 0 ;;
    'api graphql') return "$LAND_EXIT" ;;
    'run list') printf '123\n' ;;
    'run view') printf '\n' ;;
    'run watch') return "$WATCH_EXIT" ;;
    'issue list') printf '%s\n' "$OPEN_ISSUE" ;;
    'issue create'|'issue comment') return 0 ;;
    api\ *) printf '%s\n' "$GATE_STATE" ;;
    *) return 2 ;;
  esac
}
python3() {
  printf 'python3 %s\n' "$*" >> "$TRACE_FILE"
}
python() {
  printf 'python %s\n' "$*" >> "$TRACE_FILE"
  if [ "$1" = -c ]; then
    case "$2" in
      # The version in the resumed commit's parent, read from stdin.
      *stdin*) printf '%s\n' "$PARENT_VERSION" ;;
      *) if [ -f checked-out ]; then printf '%s\n' "$RESUME_VERSION";
         else printf '%s\n' "$BASE_VERSION"; fi ;;
    esac
  else return "$ADMIT_EXIT"; fi
}
"""


def _exercise(
    tmp_path: Path,
    step_names: list[str],
    *,
    workflow_name: str = "release-cut.yml",
    job_id: str = "cut",
    **overrides: str,
):
    bash = shutil.which("bash")
    if os.name == "nt":
        # System32/bash.exe enters WSL instead of the runner's Windows shell.
        git = shutil.which("git")
        roots = (Path(git).parent, Path(git).parent.parent / "bin") if git else ()
        bash = next(
            (str(root / "bash.exe") for root in roots if (root / "bash.exe").is_file()), None
        )
    if bash is None:
        pytest.skip("the workflow shell requires Bash")
    root = Path(__file__).resolve().parents[3]
    workflow = yaml.safe_load((root / ".github/workflows" / workflow_name).read_text("utf-8"))
    # Steps of the named job first; a release spans several jobs (cut, tag).
    steps = {step.get("name"): step for step in workflow["jobs"][job_id]["steps"]}
    for job in workflow["jobs"].values():
        for step in job.get("steps", []):
            steps.setdefault(step.get("name"), step)
    trace = tmp_path / "commands.txt"
    script = tmp_path / "release-test.sh"
    script.write_text(
        _FAKES + "\n".join(steps[name]["run"] for name in step_names),
        encoding="utf-8",
        newline="\n",
    )
    result = subprocess.run(
        [bash, "--noprofile", "--norc", "-e", "-o", "pipefail", script.name],
        cwd=tmp_path,
        env={
            **os.environ,
            "V": "1.2.3",
            "GITHUB_RUN_ID": "77",
            "GITHUB_RUN_ATTEMPT": "2",
            "GITHUB_REPOSITORY": "example/project",
            "TRACE_FILE": trace.name,
            "GITHUB_OUTPUT": "outputs.txt",
            "GITHUB_STEP_SUMMARY": "summary.txt",
            "RUNNER_TEMP": ".",
            "PATH": "",
            "BASH_ENV": "/dev/null",
            "TOKEN_IS_BOT": "true",
            "WATCH_EXIT": "0",
            "GATE_STATE": "success",
            "LAND_EXIT": "0",
            "ADMIT_EXIT": "0",
            "ANCESTOR_EXIT": "0",
            "FAKE_SHA": _SHA,
            "RESUME_SHA": _SHA,
            "BASE_VERSION": "1.2.3",
            "RESUME_VERSION": "1.2.3",
            "PARENT_VERSION": "1.2.2",
            "RELEASE_REF": "refs/tags/v1.2.3",
            "TAG_EXISTS": "1",
            "TAG_SHA": _SHA,
            "TAG_PUSHED": "true",
            "CANDIDATE": "release-cut/v1.2.3-77-2",
            "CANDIDATE_SHA": _SHA,
            "SHA": _SHA,
            "DIST": "dodaios/ui/web/dist",
            "BUNDLE_DIFF_EXIT": "0",
            "STAGED_PATHS": "",
            **overrides,
        },
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
        creationflags=NO_WINDOW_CREATIONFLAGS,
    )
    commands = trace.read_text("utf-8").splitlines() if trace.exists() else []
    return result, commands


_QUALIFY = "Qualify plugin auth and disclose preview plugins"


def test_release_qualification_is_strict_with_no_per_tag_exception(tmp_path):
    root = Path(__file__).resolve().parents[3]
    workflow = (root / ".github/workflows/ci.yml").read_text("utf-8")
    assert "refs/tags/v2.9.0" not in workflow  # the one-time exception is gone
    result, commands = _exercise(
        tmp_path,
        [_QUALIFY],
        workflow_name="ci.yml",
        job_id="release-qualification",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert commands == ["python scripts/ci/check_plugin_auth_contract.py --require-e2e-pass"]
    assert (tmp_path / "summary.txt").exists()


def test_release_qualification_fails_on_a_failing_auth_contract(tmp_path):
    result, _commands = _exercise(
        tmp_path,
        [_QUALIFY],
        workflow_name="ci.yml",
        job_id="release-qualification",
        ADMIT_EXIT="1",
    )
    assert result.returncode != 0
    assert not (tmp_path / "summary.txt").exists()


_CANDIDATE_TO_TAG = [
    "Open the candidate PR",
    "Wait for the candidate CI gate",
    "Land the candidate",
    "Admit the release commit",
    "Tag the admitted release",
]
_MAIN_CI = "gh workflow run ci.yml --ref main -f full=true -f include_macos=true"
_DISPATCH = "Dispatch the publishing workflows on the tag"
_PUBLISHERS = "python scripts/ci/release_assets.py dispatch --repo example/project --tag v1.2.3"


def _release_cut_jobs() -> dict:
    root = Path(__file__).resolve().parents[3]
    workflow = yaml.safe_load((root / ".github/workflows/release-cut.yml").read_text("utf-8"))
    return workflow["jobs"]


def test_a_tag_that_does_not_get_published_is_reported():
    # v3.1.0, v4.0.0 and v4.1.0 stayed drafts behind a pushed tag, unnoticed (#522).
    jobs = _release_cut_jobs()
    assert jobs["tag"]["outputs"]["tagged"] == "${{ steps.tag.outcome == 'success' }}"
    stranded = jobs["stranded"]
    assert stranded["needs"] == ["cut", "tag", "publish"]
    condition = stranded["if"]
    # always(): the report must run when publish failed, was skipped or cancelled.
    assert condition.startswith("always()")
    assert "needs.tag.outputs.tagged == 'true'" in condition
    assert "needs.publish.result != 'success'" in condition
    assert stranded["permissions"] == {"issues": "write"}


_STRANDED = "Open or update the stranded release issue"
_STRANDED_ENV = {"PUBLISH_RESULT": "failure", "RUN_URL": "https://example.test/runs/77"}


def test_a_stranded_tag_opens_an_issue_with_the_recovery_steps(tmp_path):
    result, commands = _exercise(
        tmp_path, [_STRANDED], job_id="stranded", OPEN_ISSUE="", **_STRANDED_ENV
    )
    assert result.returncode == 0, result.stdout + result.stderr
    trace = "\n".join(commands)
    assert "gh issue create --repo example/project --title Release v1.2.3 is tagged" in trace
    assert "gh issue comment" not in trace
    assert "gh run rerun <run id> --failed" in trace
    assert "release-finalize.yml --ref main -f tag=v1.2.3" in trace
    assert "::error::v1.2.3 is tagged but not published" in result.stdout


def test_a_second_failure_for_the_same_tag_comments_on_the_open_issue(tmp_path):
    result, commands = _exercise(
        tmp_path, [_STRANDED], job_id="stranded", OPEN_ISSUE="42", **_STRANDED_ENV
    )
    assert result.returncode == 0, result.stdout + result.stderr
    trace = "\n".join(commands)
    assert "gh issue comment 42 --repo example/project" in trace
    assert "gh issue create" not in trace


@pytest.mark.parametrize("token_is_bot", ["true", "false"])
def test_landing_always_dispatches_ci_for_the_merge_commit(tmp_path, token_is_bot):
    # A bot merge's push run can be dropped from the main-push group while it
    # still queues; the dispatched run has its own group.
    result, commands = _exercise(tmp_path, _CANDIDATE_TO_TAG, TOKEN_IS_BOT=token_is_bot)
    assert result.returncode == 0, result.stdout + result.stderr
    assert commands.count(_MAIN_CI) == 1
    assert commands.index(_MAIN_CI) < commands.index("git tag -a v1.2.3 -m v1.2.3")


@pytest.mark.parametrize(
    "token_is_bot,tag_pushed,dispatched",
    [
        # GITHUB_TOKEN tag push fires no tag events: dispatch the publishers.
        ("true", "true", True),
        # The release bot's new tag already started them: never twice.
        ("false", "true", False),
        # The tag existed before this run (resume): nothing started them.
        ("false", "false", True),
        ("true", "false", True),
    ],
)
def test_publishers_start_exactly_once(tmp_path, token_is_bot, tag_pushed, dispatched):
    result, commands = _exercise(
        tmp_path, [_DISPATCH], TOKEN_IS_BOT=token_is_bot, TAG_PUSHED=tag_pushed
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert commands[0] == "gh workflow run ci.yml --ref v1.2.3 -f full=true -f include_macos=true"
    assert (_PUBLISHERS in commands) is dispatched


@pytest.mark.parametrize(
    "overrides,success",
    [
        ({}, True),
        ({"WATCH_EXIT": "1"}, False),
        ({"GATE_STATE": "in_progress"}, False),
        ({"LAND_EXIT": "1"}, False),
        ({"ADMIT_EXIT": "1"}, False),
    ],
)
def test_only_a_green_candidate_can_land_and_publish(tmp_path, overrides, success):
    result, commands = _exercise(
        tmp_path,
        _CANDIDATE_TO_TAG,
        **overrides,
    )
    assert (result.returncode == 0) is success, result.stdout + result.stderr
    candidate = "git push origin HEAD:refs/heads/release-cut/v1.2.3-77-2"
    watch = "gh run watch 123 --exit-status --interval 30"
    # The candidate enters main's merge queue pinned to the tested head.
    merge = next(
        (c for c in commands if c.startswith("gh api graphql") and "enqueuePullRequest" in c
         and c.endswith(f"sha={_SHA}")),
        "enqueue missing",
    )
    assert commands.index(candidate) < commands.index(watch)
    assert any("--event pull_request" in command for command in commands)
    assert "git push origin HEAD:main" not in commands
    if overrides.get("WATCH_EXIT") or overrides.get("GATE_STATE"):
        assert merge not in commands
    if success:
        assert commands.index(watch) < commands.index(merge)
        assert commands.index(merge) < commands.index("git tag -a v1.2.3 -m v1.2.3")
        assert commands[-1] == "git push origin v1.2.3"
    else:
        assert not any(command.startswith("git tag ") for command in commands)


@pytest.mark.parametrize(
    "overrides,success",
    [
        ({}, True),
        ({"RESUME_SHA": "refs/heads/unmerged"}, False),
        ({"ANCESTOR_EXIT": "1"}, False),
        ({"RESUME_VERSION": "1.2.2"}, False),
        # A later commit on top of the version commit keeps the version (#529).
        ({"PARENT_VERSION": "1.2.3"}, False),
        ({"ADMIT_EXIT": "1"}, False),
        ({"TAG_EXISTS": "0", "TAG_SHA": "2" * 40}, False),
    ],
)
def test_resume_requires_merged_current_version_and_admission(tmp_path, overrides, success):
    result, commands = _exercise(
        tmp_path,
        [
            "Select an already merged version commit",
            "Admit the release commit",
            "Tag the admitted release",
        ],
        **overrides,
    )
    assert (result.returncode == 0) is success, result.stdout + result.stderr
    if overrides.get("ANCESTOR_EXIT") or overrides.get("RESUME_SHA"):
        assert not any(command.startswith("git checkout ") for command in commands)
    if success:
        assert commands[-1] == "git push origin v1.2.3"
        assert (tmp_path / "outputs.txt").read_text("utf-8") == (
            f"version=1.2.3\nsha={_SHA}\npushed=true\n"
        )
    else:
        assert not any(command.startswith("git tag ") for command in commands)
        assert "git push origin v1.2.3" not in commands


def test_resume_names_the_version_commit_when_given_a_later_one(tmp_path):
    result, commands = _exercise(
        tmp_path, ["Select an already merged version commit"], PARENT_VERSION="1.2.3"
    )
    assert result.returncode != 0
    assert "does not introduce v1.2.3" in result.stdout
    assert f"git log --format=%H %s -S## [1.2.3] {_SHA} -- CHANGELOG.md" in commands
    assert not (tmp_path / "outputs.txt").exists()


_TAG = "Tag the admitted release"
_ADD = "git add -f -A -- dodaios/ui/web/dist"
_COMMIT = "git commit -q -m chore(release): frontend bundle for v1.2.3"


def test_tag_carries_a_bundle_commit_on_the_admitted_commit(tmp_path):
    result, commands = _exercise(
        tmp_path,
        [_TAG],
        job_id="tag",
        BUNDLE_DIFF_EXIT="1",
        STAGED_PATHS="dodaios/ui/web/dist/index.html\\n",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    prune = "python3 scripts/ci/check_dist_consistency.py --staged --prune"
    assert commands.index(_ADD) < commands.index(prune) < commands.index(_COMMIT)
    assert commands.index(_COMMIT) < commands.index("git tag -a v1.2.3 -m v1.2.3")
    assert commands[-1] == "git push origin v1.2.3"


def test_tag_refuses_a_bundle_that_touches_anything_else(tmp_path):
    result, commands = _exercise(
        tmp_path,
        [_TAG],
        job_id="tag",
        BUNDLE_DIFF_EXIT="1",
        STAGED_PATHS="dodaios/ui/web/dist/index.html\\ndodaios/core/config.py\\n",
    )
    assert result.returncode != 0
    assert not any(command.startswith("git tag ") for command in commands)
    assert _COMMIT not in commands


def test_an_unchanged_bundle_tags_the_admitted_commit_itself(tmp_path):
    result, commands = _exercise(tmp_path, [_TAG], job_id="tag")
    assert result.returncode == 0, result.stdout + result.stderr
    assert _COMMIT not in commands
    assert commands[-1] == "git push origin v1.2.3"


def test_bundle_job_builds_without_secrets():
    root = Path(__file__).resolve().parents[3]
    jobs = yaml.safe_load((root / ".github/workflows/release-cut.yml").read_text("utf-8"))["jobs"]
    bundle = jobs["bundle"]
    assert bundle["permissions"] == {"contents": "read"}
    assert "environment" not in bundle
    assert "secrets." not in yaml.safe_dump(bundle)
    assert jobs["tag"]["needs"] == ["cut", "bundle"]
    assert "npm" not in yaml.safe_dump(jobs["tag"])
