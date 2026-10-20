"""A logged traceback never prints a token held in a local variable."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from dodaios.self_build.code import github

_REPO = Path(__file__).resolve().parents[3]

_SCRIPT = """
import dodaios  # must come first: it switches loguru's diagnose mode off
from loguru import logger

def graphql(token, query):
    raise RuntimeError("GitHub could not be reached.")

def call_github():
    token = "ghp_" + "S3CRET" * 6
    graphql(token, "query { viewer { login } }")

try:
    call_github()
except RuntimeError:
    logger.opt(exception=True).warning("pass failed")
"""


def test_logged_traceback_hides_frame_locals() -> None:
    env = {k: v for k, v in os.environ.items() if k != "LOGURU_DIAGNOSE"}
    env["PYTHONPATH"] = str(_REPO)
    result = subprocess.run(  # noqa: S603 - fixed interpreter and script
        [sys.executable, "-c", _SCRIPT],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(_REPO),
        timeout=120,
    )
    assert "pass failed" in result.stderr
    assert "RuntimeError" in result.stderr
    assert "S3CRET" not in result.stderr


def test_github_api_never_shows_its_token(monkeypatch) -> None:
    seen: list[str] = []

    def fake_graphql(token: str, query: str, variables: dict) -> dict:
        seen.append(token)
        return {"data": {"viewer": {"login": "me", "organizations": {"nodes": []}}}}

    monkeypatch.setattr(github.github_link, "graphql", fake_graphql)
    api = github.GitHubApi("ghp_realtoken")
    assert "ghp_realtoken" not in repr(api)
    assert "ghp_realtoken" not in repr(vars(api) if hasattr(api, "__dict__") else api._token)
    assert "ghp_realtoken" not in str(api._token)
    api.viewer()
    assert seen and set(seen) == {"ghp_realtoken"}  # the login and the organisations query
