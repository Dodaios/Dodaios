"""The owner's vault: any kind of secret, used by name, never shown to the assistant."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.agent_chat.credential_requests import CredentialSpec
from dodaios.agent_chat.service import AgentChatService, _redact_credentials
from dodaios.core.protocols import ToolResult
from dodaios.credential_broker import vault_guard
from dodaios.credential_broker.vault_guard import REFUSAL, hook_settings, touches_vault
from dodaios.society import credentials
from dodaios.society.credential_tool import (
    CREDENTIAL_TOOL_NAME,
    RequestCredentialTool,
    lead_credential_tools,
    usage_note,
)
from dodaios.society.credentials import SECRET_KINDS, CredentialError, CredentialVault
from dodaios.society.lead_shell import VaultShellTool, with_vault_shell
from dodaios.society.roster import LEAD_AGENT_ID
from dodaios.ui.web import trust_routes
from tests.fakes.fake_secret_store import FakeSecretStore

KEY = "AIzaSy" + "Q7c3k9TestOnlyValue0042"  # a test value shaped like a Google key
#: A multi-line value shaped like a PEM block, built here so no scanner reads it as a key.
_PEM_LABEL = "PRIVATE " + "KEY"
PEM = f"-----BEGIN {_PEM_LABEL}-----\nnot-a-real-key-just-test-lines\n-----END {_PEM_LABEL}-----"


@pytest.fixture
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> CredentialVault:
    store = CredentialVault(tmp_path / "credentials", secrets=FakeSecretStore())
    monkeypatch.setattr(credentials, "current_vault", lambda: store)
    return store


# ------------------------------------------------------------------ kinds and notes


def test_a_secret_keeps_its_kind_and_note_and_never_its_value(vault: CredentialVault) -> None:
    info = vault.store(
        LEAD_AGENT_ID,
        "GOOGLE_AI_STUDIO_API_KEY",
        KEY,
        label="Google AI Studio API key",
        kind="api_key",
        note="For the daily PR checks",
    )
    assert (info.kind, info.note) == ("api_key", "For the daily PR checks")
    index = next(vault._root.glob("*.json")).read_text(encoding="utf-8")
    assert KEY not in index and '"kind": "api_key"' in index
    # A replacement without kind or note keeps both.
    vault.store(LEAD_AGENT_ID, "GOOGLE_AI_STUDIO_API_KEY", KEY + "2")
    (row,) = vault.list(LEAD_AGENT_ID)
    assert (row.kind, row.note, row.label) == (
        "api_key",
        "For the daily PR checks",
        "Google AI Studio API key",
    )
    assert vault.values(LEAD_AGENT_ID)["GOOGLE_AI_STUDIO_API_KEY"] == KEY + "2"


def test_an_unknown_kind_reads_as_other_and_old_rows_still_load(vault: CredentialVault) -> None:
    assert vault.store(LEAD_AGENT_ID, "SOME_TOKEN", "abcdef123456", kind="banana").kind == "other"
    path = next(vault._root.glob("*.json"))
    body = json.loads(path.read_text(encoding="utf-8"))
    for row in body["credentials"]:
        row.pop("kind", None)
    path.write_text(json.dumps(body), encoding="utf-8")
    assert vault.list(LEAD_AGENT_ID)[0].kind == "other"
    assert set(SECRET_KINDS) >= {"api_key", "client_id", "client_secret", "private_key", "token"}


def test_only_a_private_key_may_span_lines(vault: CredentialVault) -> None:
    vault.store(LEAD_AGENT_ID, "DEPLOY_KEY", PEM, kind="private_key")
    assert vault.values(LEAD_AGENT_ID)["DEPLOY_KEY"] == PEM
    with pytest.raises(CredentialError):
        vault.store(LEAD_AGENT_ID, "API_KEY", "abc\ndef123", kind="api_key")


# ------------------------------------------------------------------ the guard


@pytest.mark.parametrize(
    "command",
    [
        "security find-generic-password -s dodaios -a __jarvis_vault__ -w",
        "/usr/bin/security find-generic-password -w -s dodaios",
        "security dump-keychain -d login.keychain",
        'python -c \'import keyring; print(keyring.get_password("dodaios", "x"))\'',
        "keyring get dodaios society_credential.jarvis.GITHUB_TOKEN",
        "cat ~/Dodaios/data/credentials.json",
        "secret-tool lookup service dodaios",
        "python -c 'from dodaios.core.config import get_secret; print(get_secret(\"x\"))'",
    ],
)
def test_reading_the_secret_store_is_refused(command: str) -> None:
    assert touches_vault(command)


@pytest.mark.parametrize(
    "command",
    [
        'curl -H "x-goog-api-key: $GOOGLE_AI_STUDIO_API_KEY" https://generativelanguage.googleapis.com/v1beta/models',
        "git status",
        "cat credentials.json",  # a project's own OAuth file, not Dodaios' store
        "ls ~/Library",
        "security list-keychains",
    ],
)
def test_ordinary_commands_pass(command: str) -> None:
    assert not touches_vault(command)


def _hook(payload: dict[str, Any]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - the guard file with this interpreter
        [sys.executable, vault_guard.__file__],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_the_claude_code_hook_blocks_a_vault_read_and_lets_the_rest_run() -> None:
    blocked = _hook(
        {"tool_name": "Bash", "tool_input": {"command": "security find-generic-password -w"}}
    )
    assert blocked.returncode == 2 and REFUSAL in blocked.stderr
    read = _hook(
        {"tool_name": "Read", "tool_input": {"file_path": "/Users/x/Dodaios/data/credentials.json"}}
    )
    assert read.returncode == 2
    assert _hook({"tool_name": "Bash", "tool_input": {"command": "ls"}}).returncode == 0
    assert (
        _hook({"tool_name": "Read", "tool_input": {"file_path": "/tmp/notes.md"}}).returncode == 0  # noqa: S108 - a test value, not a secret
    )
    settings = hook_settings("/opt/py/bin/python")
    (entry,) = settings["hooks"]["PreToolUse"]
    assert "Bash" in entry["matcher"] and "Read" in entry["matcher"]
    assert entry["hooks"][0]["command"].startswith('"/opt/py/bin/python" "')


def test_an_assistant_turn_on_claude_code_runs_the_guard(monkeypatch) -> None:
    from dodaios.agent_chat import runner_cli
    from dodaios.agent_chat.dodaios_harness import Identity

    # No Claude Code needed on the test machine: only the planned argv is read.
    monkeypatch.setattr(runner_cli, "claude_argv_prefix", lambda: ["claude"])

    identity = Identity(session_id="lead-chat", text="", compact="")
    plan = runner_cli._plan_claude_code(
        prompt="hi",
        cwd=Path("."),
        model="",
        effort="",
        permission_mode="bypass",
        resume=None,
        identity=identity,
        env={},
    )
    argv = list(plan.argv)
    settings = json.loads(argv[argv.index("--settings") + 1])
    assert "PreToolUse" in settings["hooks"]
    coding = runner_cli._plan_claude_code(
        prompt="hi",
        cwd=Path("."),
        model="",
        effort="",
        permission_mode="bypass",
        resume=None,
        identity=None,
        env={},
    )
    assert "--settings" not in list(coding.argv)


# ------------------------------------------------------------------ the lead's shell


class _Shell:
    name = "run_shell"
    description = "Runs a shell command"
    schema = {"type": "object"}
    risk_tier = "monitor"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def risk_tier_for_args(self, args: dict[str, Any]) -> str | None:
        return "ask" if "rm " in str(args.get("command")) else None

    async def execute(self, args: dict[str, Any], ctx: Any, *, extra_env: Any = None) -> ToolResult:
        self.calls.append({"args": args, "env": dict(extra_env or {})})
        printed = (extra_env or {}).get("GOOGLE_AI_STUDIO_API_KEY", "")
        return ToolResult(success=True, output={"stdout": f"key={printed}\n", "exit_code": 0})


def test_the_leads_shell_sets_the_secret_and_masks_its_value(vault: CredentialVault) -> None:
    vault.store(LEAD_AGENT_ID, "GOOGLE_AI_STUDIO_API_KEY", KEY, kind="api_key")
    inner = _Shell()
    tools = with_vault_shell({"run_shell": inner, "other": object()})
    shell = tools["run_shell"]
    assert isinstance(shell, VaultShellTool)
    assert with_vault_shell(tools)["run_shell"] is shell  # wrapped once
    # The safety layer judges the call exactly as before.
    assert shell.description == inner.description and shell.risk_tier == "monitor"
    assert shell.risk_tier_for_args({"command": "rm -rf x"}) == "ask"
    result = asyncio.run(shell.execute({"command": "echo $GOOGLE_AI_STUDIO_API_KEY"}, None))
    assert inner.calls[0]["env"] == {"GOOGLE_AI_STUDIO_API_KEY": KEY}
    assert KEY not in json.dumps(result.output)
    assert "[credential GOOGLE_AI_STUDIO_API_KEY]" in result.output["stdout"]


def test_the_leads_shell_refuses_to_read_the_store(vault: CredentialVault) -> None:
    inner = _Shell()
    shell = VaultShellTool(inner, LEAD_AGENT_ID)
    result = asyncio.run(shell.execute({"command": "security find-generic-password -w"}, None))
    assert not result.success and result.error == REFUSAL and inner.calls == []


def test_run_shell_puts_extra_variables_only_into_that_command() -> None:
    from dodaios.plugins.tool.run_shell import RunShellTool

    if sys.platform == "win32":
        pytest.skip("POSIX shell syntax")
    tool = RunShellTool()
    result = asyncio.run(
        tool.execute(
            {"command": 'printf %s "$VAULT_TEST_VALUE"'},
            None,
            extra_env={"VAULT_TEST_VALUE": "abc123"},
        )
    )
    assert result.output["stdout"] == "abc123"
    plain = asyncio.run(tool.execute({"command": 'printf %s "$VAULT_TEST_VALUE"'}, None))
    assert plain.output["stdout"] == ""


# ------------------------------------------------------------------ the lead's field


class _Chat:
    def __init__(self) -> None:
        self.saves: list[Any] = []
        self.specs: list[CredentialSpec] = []

    async def open_credential_request(self, session_id, spec, save, *, asker="", **_: Any) -> str:
        self.specs.append(spec)
        self.saves.append(save)
        return "rid-1"

    async def wait_credential_request(self, session_id, request_id, timeout_s=None):
        return None


def test_the_leads_field_stores_into_the_owners_vault(vault: CredentialVault, monkeypatch) -> None:
    from dodaios.society import runtime as runtime_mod

    chat = _Chat()
    rt = SimpleNamespace(
        lead_id=LEAD_AGENT_ID, chat_service=lambda: chat, cached_agent=lambda _a: None
    )
    monkeypatch.setattr(runtime_mod, "current_runtime", lambda: rt)
    tool = lead_credential_tools(SimpleNamespace(session_id="lead-chat"))[CREDENTIAL_TOOL_NAME]
    assert isinstance(tool, RequestCredentialTool)
    assert "run_shell" in tool.description and "society_shell" not in tool.description
    result = asyncio.run(
        tool.execute(
            {
                "env": "GOOGLE_AI_STUDIO_API_KEY",
                "label": "Google AI Studio API key",
                "kind": "api_key",
                "description": "For the daily PR checks",
            },
            None,
        )
    )
    assert result.output["status"] == "waiting"
    assert chat.specs[0].secret_kind == "api_key"  # noqa: S105 - a test value, not a secret
    asyncio.run(chat.saves[0](KEY))
    (row,) = vault.list(LEAD_AGENT_ID)
    assert (row.env, row.kind, row.note) == (
        "GOOGLE_AI_STUDIO_API_KEY",
        "api_key",
        "For the daily PR checks",
    )
    again = asyncio.run(
        tool.execute(
            {
                "env": "GOOGLE_AI_STUDIO_API_KEY",
                "label": "Google AI Studio API key",
                "description": "x",
            },
            None,
        )
    )
    assert again.output["status"] == "available"
    assert again.output["note"] == usage_note("GOOGLE_AI_STUDIO_API_KEY", "run_shell")
    assert KEY not in json.dumps(again.output)


def test_a_routine_or_a_missing_runtime_gets_no_field(monkeypatch) -> None:
    from dodaios.society import runtime as runtime_mod

    monkeypatch.setattr(runtime_mod, "current_runtime", lambda: None)
    assert lead_credential_tools(SimpleNamespace(session_id="lead-chat")) == {}


def test_a_restored_lead_field_saves_into_the_owners_vault(vault: CredentialVault) -> None:
    spec = CredentialSpec.build(
        "GOOGLE_AI_STUDIO_API_KEY",
        "Google AI Studio API key",
        "For checks",
        secret_kind="api_key",  # noqa: S106 - a test value, not a secret
    )
    assert spec.to_payload()["secret_kind"] == "api_key"  # noqa: S105 - a test value, not a secret
    assert AgentChatService._restore_credential_save("lead-chat", spec) is None  # noqa: SLF001
    save = AgentChatService._restore_credential_save("lead-chat", spec, LEAD_AGENT_ID)  # noqa: SLF001
    assert save is not None
    asyncio.run(save(KEY))
    assert vault.list(LEAD_AGENT_ID)[0].kind == "api_key"


def test_the_leads_chat_events_are_masked(vault: CredentialVault) -> None:
    vault.store(LEAD_AGENT_ID, "GOOGLE_AI_STUDIO_API_KEY", KEY)
    service = AgentChatService.__new__(AgentChatService)
    service.store = SimpleNamespace(
        get_session=lambda sid: SimpleNamespace(surface="jarvis" if sid == "lead-chat" else "code")
    )
    assert service._vault_owner("lead-chat") == LEAD_AGENT_ID  # noqa: SLF001
    assert service._vault_owner("thread-1") is None  # noqa: SLF001
    assert service._vault_owner("society:ada") == "ada"  # noqa: SLF001
    event = {"kind": "tool_result", "payload": {"output": f"the key is {KEY}"}}
    masked = asyncio.run(_redact_credentials("lead-chat", event, LEAD_AGENT_ID))
    assert KEY not in json.dumps(masked)


# ------------------------------------------------------------------ the vault page


@pytest.fixture
def http(vault: CredentialVault) -> TestClient:
    app = FastAPI()
    app.include_router(trust_routes.router)
    return TestClient(app)


def test_the_vault_page_lists_names_and_never_a_value(
    http: TestClient, vault: CredentialVault
) -> None:
    put = http.put(
        "/api/trust/vault/secrets/GOOGLE_AI_STUDIO_API_KEY",
        json={
            "value": KEY,
            "label": "Google AI Studio API key",
            "kind": "api_key",
            "note": "PR checks",
        },
    )
    assert put.status_code == 200 and KEY not in put.text
    login = http.put(
        "/api/trust/vault/logins",
        json={
            "label": "GitHub",
            "url": "https://github.com/login",
            "username": "ada@example.org",
            "password": "hunter2-hunter2",
        },
    )
    assert login.status_code == 200 and "hunter2" not in login.text
    body = http.get("/api/trust/vault")
    assert (
        KEY not in body.text and "hunter2" not in body.text and "ada@example.org" not in body.text
    )
    data = body.json()
    assert data["secrets"] == [
        {
            "env": "GOOGLE_AI_STUDIO_API_KEY",
            "label": "Google AI Studio API key",
            "kind": "api_key",
            "note": "PR checks",
            "present": True,
            "created_ms": data["secrets"][0]["created_ms"],
            "updated_ms": data["secrets"][0]["updated_ms"],
        }
    ]
    assert [row["domain"] for row in data["logins"]] == ["github.com"]
    assert "private_key" in data["kinds"]
    assert vault.values(LEAD_AGENT_ID) == {"GOOGLE_AI_STUDIO_API_KEY": KEY}
    assert http.delete("/api/trust/vault/secrets/GOOGLE_AI_STUDIO_API_KEY").status_code == 200
    assert http.delete("/api/trust/vault/secrets/GOOGLE_AI_STUDIO_API_KEY").status_code == 404
    assert http.delete("/api/trust/vault/logins/github").status_code == 200
    assert http.get("/api/trust/vault").json()["secrets"] == []


def test_the_vault_page_refuses_bad_names_and_marks_writes_owner_only(http: TestClient) -> None:
    bad = http.put("/api/trust/vault/secrets/path", json={"value": "abcdef123"})
    assert bad.status_code == 400 and "abcdef123" not in bad.text
    reserved = http.put("/api/trust/vault/secrets/PATH", json={"value": "abcdef123"})
    assert reserved.status_code == 400
    schema = http.app.openapi()["paths"]
    for path, verb in (
        ("/api/trust/vault/secrets/{env}", "put"),
        ("/api/trust/vault/secrets/{env}", "delete"),
        ("/api/trust/vault/logins", "put"),
        ("/api/trust/vault/logins/{key}", "delete"),
    ):
        assert schema[path][verb].get("x-jarvis-dangerous") is True


def test_the_lead_deletes_a_secret_once_the_job_is_done(
    vault: CredentialVault, monkeypatch
) -> None:
    from dodaios.society import runtime as runtime_mod

    rt = SimpleNamespace(
        lead_id=LEAD_AGENT_ID, chat_service=lambda: None, cached_agent=lambda _a: None
    )
    monkeypatch.setattr(runtime_mod, "current_runtime", lambda: rt)
    vault.store(LEAD_AGENT_ID, "GOOGLE_AI_STUDIO_API_KEY", KEY)
    tool = lead_credential_tools(SimpleNamespace(session_id="lead-chat"))[CREDENTIAL_TOOL_NAME]
    gone = asyncio.run(tool.execute({"env": "GOOGLE_AI_STUDIO_API_KEY", "forget": True}, None))
    assert gone.output["status"] == "deleted" and vault.list(LEAD_AGENT_ID) == []
    again = asyncio.run(tool.execute({"env": "GOOGLE_AI_STUDIO_API_KEY", "forget": True}, None))
    assert again.output["status"] == "not_stored"
    bad = asyncio.run(tool.execute({"env": "path", "forget": True}, None))
    assert not bad.success
