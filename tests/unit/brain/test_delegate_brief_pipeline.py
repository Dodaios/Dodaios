"""``delegate`` and the brief pipeline: look first, a brief sent back, what travels on."""

from __future__ import annotations

from dodaios.core.protocols import ToolResult
from tests.unit.brain.test_delegate_tool import Fake, _ctx, _tool

CREATED = ToolResult(
    True,
    {
        "status": "created",
        "agents": [{"terminal_id": "thread:abc"}],
        "deliveries": [{"status": "accepted", "job_id": "job_thread1"}],
    },
)


async def test_the_briefs_parts_travel_unjoined_beside_the_prompt() -> None:
    workspace = Fake("workspace-orchestrate", CREATED)
    await _tool(workspace).execute(
        {
            "target": "coding_agent",
            "task": "Make uploads survive a slow connection.",
            "context": "Log: timed out after 10s.",
            "completion_criteria": "A timeout test passes.",
            "options": {"resolved": [{"said": "Hochladen", "means": "upload()"}]},  # i18n-allow
        },
        _ctx(),
    )
    [call] = workspace.calls
    assert call["_brief_parts"] == {
        "task": "Make uploads survive a slow connection.",
        "context": "Log: timed out after 10s.",
        "criteria": "A timeout test passes.",
    }
    assert call["_resolved_words"] == [{"said": "Hochladen", "means": "upload()"}]  # i18n-allow
    assert "resolved" not in call and "prepare" not in call


async def test_prepare_reads_the_kit_and_starts_nothing() -> None:
    workspace = Fake(
        "workspace-orchestrate",
        ToolResult(True, {"status": "prepared", "nothing_sent": True, "brief_kit": {"k": 1}}),
    )
    result = await _tool(workspace).execute(
        {
            "target": "coding_agent:Codex",
            "task": "the upload breaks on a slow connection",
            "options": {"prepare": True, "folder": "/work/notes"},
        },
        _ctx(),
    )
    [call] = workspace.calls
    assert call == {
        "action": "brief_kit", "prompt": "the upload breaks on a slow connection",
        "folder": "/work/notes", "cli": "Codex",
    }
    assert result.success and result.output["state"] == "prepared"
    assert result.output["job_id"] is None
    assert result.output["detail"]["brief_kit"] == {"k": 1}
    assert "without options.prepare" in result.output["next_step"]


async def test_prepare_for_a_pane_resolves_it_first() -> None:
    workspace = Fake(
        "workspace-orchestrate",
        [
            ToolResult(True, {"status": "resolved", "request_id": "r1",
                              "target": {"project_id": "p", "workspace_id": "w",
                                         "terminal_id": "pane:t2"}}),
            ToolResult(True, {"status": "prepared", "brief_kit": {}}),
        ],
    )
    result = await _tool(workspace).execute(
        {"target": "pane:T2", "task": "fix it", "options": {"prepare": True}}, _ctx()
    )
    assert [c["action"] for c in workspace.calls] == ["resolve", "brief_kit"]
    assert workspace.calls[1]["terminal_id"] == "pane:t2"
    assert result.output["state"] == "prepared"


async def test_a_brief_that_is_sent_back_is_not_a_failure_and_writes_no_job() -> None:
    sent_back = {
        "status": "needs_revision", "success": False,
        "reason": "The brief was not sent.", "fix": [{"code": "no_done"}], "brief_kit": {},
    }
    workspace = Fake("workspace-orchestrate", [ToolResult(False, sent_back), CREATED])
    tool = _tool(workspace)
    first = await tool.execute({"target": "coding_agent", "task": "fix it"}, _ctx())
    assert not first.success and first.output["state"] == "needs_revision"
    assert first.output["job_id"] is None
    assert first.output["detail"]["fix"] == [{"code": "no_done"}]
    assert "Revise the brief" in first.output["next_step"]

    second = await tool.execute(
        {"target": "coding_agent", "task": "fix it", "completion_criteria": "test x passes"},
        _ctx(),
    )
    assert second.success and second.output["job_id"] == "job_thread1"


async def test_a_team_threads_brief_passes_the_same_check(briefs_on, tmp_path) -> None:
    team = Fake("team_thread", ToolResult(True, {"status": "started", "job_id": "job_team1"}))
    tool = _tool(team)
    weak = {
        "target": "team_thread",
        "task": "Make the upload better somehow.\n1. Open client.py.\n2. Run `pytest`.\n3. Commit.",
        "options": {"cwd": str(tmp_path)},
    }
    first = await tool.execute(weak, _ctx())
    assert first.output["state"] == "needs_revision" and team.calls == []

    strong = {
        "target": "team_thread",
        "task": "Uploads time out on a slow connection; make them survive it.",
        "completion_criteria": "A test that simulates a timeout passes.",
        "options": {"cwd": str(tmp_path)},
    }
    second = await tool.execute(strong, _ctx())
    assert second.success and len(team.calls) == 1
