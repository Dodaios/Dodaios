"""The standalone Conductor server refuses foreign callers.

``python -m conductor serve`` exposes a job API that runs shell commands.
It used to have no authentication and ``allow_origins=["*"]`` with
credentials, so any page the user opened (another localhost port, a LAN
page, a ``file://`` page) could create a shell job and run it. These tests
pin the lock: Host allowlist, Origin allowlist, bearer token, and no side
effect on a refused request.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conductor.api.app import create_app
from conductor.core.store import ConductorStore

# Security-boundary suite: present our own credentials, no injected Origin.
pytestmark = pytest.mark.no_auto_web_auth

TOKEN = "test-token-" + "x" * 32
AUTH = {"Authorization": f"Bearer {TOKEN}"}

SHELL_JOB = {
    "name": "probe",
    "spec": {"type": "shell", "command": f'"{sys.executable}" -c "print(1)"',
             "timeout_s": 10},
    "schedule": {"type": "manual"},
    "enabled": True,
}


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CONDUCTOR_API_TOKEN", TOKEN)
    monkeypatch.delenv("CONDUCTOR_CORS_ORIGINS", raising=False)
    monkeypatch.delenv("CONDUCTOR_ALLOWED_HOSTS", raising=False)
    app = create_app(store=ConductorStore(tmp_path / "c.sqlite"), start_scheduler=False)
    with TestClient(app, base_url="http://127.0.0.1:7777") as c:
        yield c


def _job_count(c: TestClient) -> int:
    r = c.get("/api/conductor/jobs", headers=AUTH)
    assert r.status_code == 200
    return r.json()["summary"]["total"]


def _run_count(c: TestClient) -> int:
    r = c.get("/api/conductor/runs", headers=AUTH)
    assert r.status_code == 200
    return r.json()["total"]


@pytest.mark.parametrize("origin", [
    "http://127.0.0.1:8011",     # page on another localhost port
    "http://192.168.1.50:8012",  # LAN page
    "null",                      # file:// page
    "https://example.com",       # public site
])
def test_browser_origin_cannot_create_or_run_a_shell_job(client, origin):
    before_jobs, before_runs = _job_count(client), _run_count(client)
    h = {"Origin": origin}

    pre = client.options("/api/conductor/jobs", headers={
        **h, "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type"})
    assert "access-control-allow-origin" not in pre.headers

    r = client.post("/api/conductor/jobs", json=SHELL_JOB, headers=h)
    assert r.status_code == 403
    assert "access-control-allow-origin" not in r.headers
    # Even holding the token, a foreign page is refused.
    r = client.post("/api/conductor/jobs", json=SHELL_JOB, headers={**h, **AUTH})
    assert r.status_code == 403

    assert _job_count(client) == before_jobs
    assert _run_count(client) == before_runs


def test_seed_job_cannot_be_triggered_cross_origin(client):
    jobs = client.get("/api/conductor/jobs", headers=AUTH).json()["jobs"]
    if not jobs:
        pytest.skip("no seed jobs planted")
    r = client.post(f"/api/conductor/jobs/{jobs[0]['id']}/run", json={},
                    headers={"Origin": "null"})
    assert r.status_code == 403
    assert _run_count(client) == 0


@pytest.mark.parametrize("headers", [
    {},                                          # no Origin, no token
    {"Authorization": "Bearer wrong"},
    {"Authorization": TOKEN},                    # token without scheme
])
def test_non_browser_client_needs_the_token(client, headers):
    before = _job_count(client)
    assert client.post("/api/conductor/jobs", json=SHELL_JOB, headers=headers).status_code == 401
    assert client.get("/api/conductor/runs", headers=headers).status_code == 401
    assert _job_count(client) == before


def test_dns_rebinding_host_is_refused(client):
    r = client.post("/api/conductor/jobs", json=SHELL_JOB,
                    headers={**AUTH, "Host": "attacker.example:7777"})
    assert r.status_code == 400


def test_token_holder_can_create_and_run(client):
    r = client.post("/api/conductor/jobs", json=SHELL_JOB, headers=AUTH)
    assert r.status_code == 201
    r = client.post(f"/api/conductor/jobs/{r.json()['id']}/run", json={}, headers=AUTH)
    assert r.status_code == 200
    assert r.json()["run_id"]


def test_health_and_webhook_stay_reachable_without_bearer(client):
    assert client.get("/api/health").status_code == 200
    # The webhook URL token is its own auth: unknown token → 404, not 401.
    r = client.post("/api/conductor/hooks/" + "u" * 40, json={},
                    headers={"Host": "hooks.example.org"})
    assert r.status_code == 404


def test_explicit_cors_origin_is_the_only_browser_origin(tmp_path, monkeypatch):
    monkeypatch.setenv("CONDUCTOR_API_TOKEN", TOKEN)
    ui = "http://localhost:5173"
    app = create_app(store=ConductorStore(tmp_path / "c.sqlite"),
                     start_scheduler=False, cors_origins=[ui])
    with TestClient(app, base_url="http://127.0.0.1:7777") as c:
        pre = c.options("/api/conductor/jobs", headers={
            "Origin": ui, "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type"})
        assert pre.status_code == 200
        assert pre.headers["access-control-allow-origin"] == ui
        assert "access-control-allow-credentials" not in pre.headers
        r = c.post("/api/conductor/jobs", json=SHELL_JOB, headers={"Origin": ui, **AUTH})
        assert r.status_code == 201
        assert c.post("/api/conductor/jobs", json=SHELL_JOB,
                      headers={"Origin": "http://localhost:5174", **AUTH}).status_code == 403
