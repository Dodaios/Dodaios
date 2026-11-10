"""verify_delegate: verified / unverified / failed from the evidence, never from the claim."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from dodaios.core.delegate_verify import DelegateRecord, verify_record
from dodaios.plugins.tool import verify_delegate as tool_mod
from dodaios.plugins.tool.verify_delegate import VerifyDelegateTool


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "a.txt").write_text("one\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "init")
    return tmp_path


def test_coding_with_no_changes_fails(repo: Path) -> None:
    out = verify_record(DelegateRecord("coding:x", "coding", cwd=str(repo)))
    assert out.verdict == "failed"
    assert next(c for c in out.checks if c.name == "changes").ok is False


def test_coding_with_a_diff_but_no_recorded_tests_is_unverified(repo: Path) -> None:
    (repo / "a.txt").write_text("two\n")
    out = verify_record(DelegateRecord("coding:x", "coding", cwd=str(repo)))
    assert out.verdict == "unverified"
    assert "1 file changed" in next(c for c in out.checks if c.name == "changes").detail


def test_coding_with_a_passing_recorded_test_is_verified(repo: Path) -> None:
    (repo / "new.py").write_text("x = 1\n")
    rec = DelegateRecord(
        "coding:x", "coding", cwd=str(repo), test_command="pytest -q", test_result="passed"
    )
    assert verify_record(rec).verdict == "verified"
    rec.test_result = "failed"
    assert verify_record(rec).verdict == "failed"


def test_coding_in_a_missing_folder_is_unverified(tmp_path: Path) -> None:
    rec = DelegateRecord("coding:x", "coding", cwd=str(tmp_path / "gone"))
    assert verify_record(rec).verdict == "unverified"


def _artifact(path: Path) -> str:
    return verify_record(DelegateRecord("a", "artifact", artifact_path=str(path))).verdict


def test_artifact_checks(tmp_path: Path) -> None:
    good = tmp_path / "page.html"
    good.write_text("<html><body><h1>Hello</h1></body></html>")
    assert _artifact(good) == "verified"
    empty = tmp_path / "empty.html"
    empty.write_text("")
    assert _artifact(empty) == "failed"
    blank = tmp_path / "blank.html"
    blank.write_text("<html><body></body></html>")
    assert _artifact(blank) == "failed"
    missing = tmp_path / "nope.html"
    assert _artifact(missing) == "failed"
    bad = tmp_path / "d.json"
    bad.write_text("{oops")
    assert _artifact(bad) == "failed"


def test_society_evidence_refs_must_exist(tmp_path: Path) -> None:
    real = tmp_path / "report.md"
    real.write_text("x")
    ok = verify_record(DelegateRecord("s", "society", evidence=[str(real)]))
    assert ok.verdict == "verified"
    dead = verify_record(DelegateRecord("s", "society", evidence=[str(real), str(tmp_path / "x")]))
    assert dead.verdict == "failed" and "x" in dead.summary
    none = verify_record(DelegateRecord("s", "society", evidence=[]))
    assert none.verdict == "unverified"
    link = verify_record(DelegateRecord("s", "society", evidence=["https://example.com/a"]))
    assert link.verdict == "unverified"
    ev = DelegateRecord("s", "society", evidence=["a" * 32], event_exists=lambda ref: False)
    assert verify_record(ev).verdict == "failed"


async def test_the_tool_resolves_artifact_ids_and_reports_unknown_ones(tmp_path: Path) -> None:
    page = tmp_path / "p.html"
    page.write_text("<p>hi</p>")
    tool = VerifyDelegateTool()
    res = await tool.execute({"job_id": f"artifact:{page}"}, None)  # type: ignore[arg-type]
    assert res.success and res.output["verdict"] == "verified"
    res = await tool.execute({"job_id": "weird"}, None)  # type: ignore[arg-type]
    assert res.output["verdict"] == "unverified" and "Unknown job id" in res.output["summary"]
    res = await tool.execute({"job_id": ""}, None)  # type: ignore[arg-type]
    assert not res.success


async def test_a_registered_resolver_takes_over_its_prefix() -> None:
    async def resolver(rest: str) -> DelegateRecord | str:
        return f"ledger says {rest} is gone"

    tool_mod.register_resolver("job", resolver)
    try:
        res = await VerifyDelegateTool().execute({"job_id": "job:7"}, None)  # type: ignore[arg-type]
        assert "ledger says 7 is gone" in res.output["summary"]
    finally:
        tool_mod._RESOLVERS.pop("job", None)
