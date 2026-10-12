"""`scripts/agent_land.py` asks GitHub to queue a green pull request."""

from __future__ import annotations

import json
import subprocess

from scripts import agent_land


class FakeGh:
    """Records every command and answers `gh pr view` / `gh pr merge`."""

    def __init__(self, view: dict | None, *, view_code: int = 0, merge_code: int = 0) -> None:
        self.view, self.view_code, self.merge_code = view, view_code, merge_code
        self.commands: list[list[str]] = []

    def __call__(self, cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        self.commands.append(cmd)
        if cmd[:3] == ["gh", "pr", "view"]:
            return subprocess.CompletedProcess(cmd, self.view_code, json.dumps(self.view), "")
        return subprocess.CompletedProcess(cmd, self.merge_code, "", "refused")


def test_a_ready_pull_request_is_queued_on_green_with_the_agents_own_login():
    gh = FakeGh({"number": 7, "isDraft": False, "labels": [{"name": "auto-merge"}]})
    assert agent_land.queue_when_green("claude/x", gh) is True
    assert gh.commands[-1] == ["gh", "pr", "merge", "claude/x", "--auto", "--squash"]


def test_a_draft_or_an_opted_out_pull_request_is_never_queued():
    for view in (
        {"number": 7, "isDraft": True, "labels": []},
        {"number": 7, "isDraft": False, "labels": [{"name": "no-auto-merge"}]},
        {"number": 7, "isDraft": False, "labels": [{"name": "needs-human"}]},
        {"number": 7, "isDraft": False, "labels": [{"name": "wip"}]},
    ):
        gh = FakeGh(view)
        assert agent_land.queue_when_green("claude/x", gh) is False
        assert all(cmd[:3] != ["gh", "pr", "merge"] for cmd in gh.commands), view


def test_a_refusal_or_an_unreadable_pull_request_never_fails_the_landing():
    refused = FakeGh({"number": 7, "isDraft": False, "labels": []}, merge_code=1)
    assert agent_land.queue_when_green("claude/x", refused) is False
    unreadable = FakeGh(None, view_code=1)
    assert agent_land.queue_when_green("claude/x", unreadable) is False
    assert len(unreadable.commands) == 1
