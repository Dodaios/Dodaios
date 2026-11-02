"""A10.1 and A10.2: the unreal-static checks fail each planted case; workflows are fork-safe."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml

from scripts.unreal import check_build_dag, check_forbidden_names, check_lfs

REPO = Path(__file__).resolve().parents[3]
WORKFLOWS = REPO / ".github" / "workflows"
UNREAL_WORKFLOWS = (
    "unreal-static.yml",
    "unreal-build.yml",
    "unreal-gauntlet.yml",
    "unreal-perf.yml",
)
#: A made-up word that is only ever forbidden by the test's own hash list.
PLANTED = "zorblaxion"


def _git(cwd: Path, *args: str, data: bytes | None = None) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, input=data, capture_output=True, check=True
    ).stdout.decode()


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "ci@example.invalid")
    _git(tmp_path, "config", "user.name", "ci")
    (tmp_path / "unreal" / "Verse").mkdir(parents=True)
    (tmp_path / "unreal" / "Verse" / ".gitattributes").write_text(
        "*.uasset filter=lfs diff=lfs merge=lfs -text\n"
        "*.umap filter=lfs diff=lfs merge=lfs -text\n",
        encoding="utf-8",
    )
    (tmp_path / "unreal" / "Verse" / "README.txt").write_text("base\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    return tmp_path


def _pointer(oid: str, size: int) -> bytes:
    return f"version https://git-lfs.github.com/spec/v1\noid sha256:{oid}\nsize {size}\n".encode()


def _commit(repo: Path, rel: str, data: bytes) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write the blob as-is (no LFS filter in the test repo): -c filter.lfs.* off.
    path.write_bytes(data)
    _git(
        repo,
        "-c",
        "filter.lfs.process=",
        "-c",
        "filter.lfs.clean=cat",
        "-c",
        "filter.lfs.required=false",
        "add",
        rel,
    )
    _git(repo, "commit", "-q", "-m", f"add {rel}")


# --- forbidden names ---


def test_a_planted_name_fails_through_a_test_only_hash(tmp_path):
    hash_file = tmp_path / "planted.sha256"
    hash_file.write_text("\n".join(sorted(check_forbidden_names.entry_hashes(PLANTED))) + "\n")
    hashes = check_forbidden_names.load_hashes(hash_file)
    assert check_forbidden_names.scan_text(f"class AZorblaxionRifle; // {PLANTED}", hashes)
    assert check_forbidden_names.scan_text("UVerseBalanceGauntletController", hashes) == []
    # The real list never contains the planted word.
    assert not check_forbidden_names.scan_text(PLANTED, check_forbidden_names.load_hashes())


def test_forbidden_names_cli_takes_an_extra_hash_file(tmp_path, monkeypatch, capsys):
    hash_file = tmp_path / "planted.sha256"
    hash_file.write_text("\n".join(sorted(check_forbidden_names.entry_hashes(PLANTED))) + "\n")
    target = REPO / "unreal" / "Verse" / "Harness" / "schema" / "bout.schema.json"
    rel = target.relative_to(REPO).as_posix()
    assert check_forbidden_names.main(["--hash-file", str(hash_file), rel]) == 0
    monkeypatch.setattr(check_forbidden_names, "REPO_ROOT", tmp_path)
    (tmp_path / "unreal").mkdir()
    (tmp_path / "unreal" / "x.cpp").write_text(f"// the {PLANTED} carbine\n", encoding="utf-8")
    assert check_forbidden_names.main(["--hash-file", str(hash_file), "unreal/x.cpp"]) == 1
    assert "forbidden name" in capsys.readouterr().out


@pytest.mark.parametrize(
    "folder", ["Renders", "renders", "Screenshots", "Evidence", "models", "Build"]
)
def test_banned_folder_names_fail_in_any_case(folder):
    found = check_forbidden_names.scan_folders([f"unreal/Verse/Content/{folder}/T_A.uasset"])
    assert found and folder in found[0]


def test_the_engine_build_folder_is_the_one_exception():
    assert check_forbidden_names.scan_folders(["unreal/Verse/Build/Windows/Verse.ico"]) == []
    assert check_forbidden_names.scan_folders(["unreal/Verse/Build/Renders/x.png"])
    assert check_forbidden_names.scan_folders(["dodaios/build/x.py"]) == []


def test_engine_sample_content_fails():
    assert check_forbidden_names.scan_folders(["unreal/Verse/Content/StarterContent/a.uasset"])
    assert check_forbidden_names.scan_folders(
        ["unreal/Verse/Content/Chars/SKM_Manny_Simple.uasset"]
    )


# --- LFS ---


def test_a_non_pointer_uasset_fails(repo):
    _commit(repo, "unreal/Verse/Content/Verse/A.uasset", b"\x00\x01binary uasset content")
    errors, _warnings, pointers = check_lfs.check_paths(
        ["unreal/Verse/Content/Verse/A.uasset"], cwd=repo
    )
    assert errors and "not as a Git LFS pointer" in errors[0]
    assert pointers == []


def test_a_51_mb_lfs_object_fails_and_21_mb_warns(repo):
    _commit(repo, "unreal/Verse/Content/Big.uasset", _pointer("a" * 64, 51 * 1024 * 1024))
    _commit(repo, "unreal/Verse/Content/Mid.uasset", _pointer("b" * 64, 21 * 1024 * 1024))
    errors, warnings, pointers = check_lfs.check_paths(
        ["unreal/Verse/Content/Big.uasset", "unreal/Verse/Content/Mid.uasset"], cwd=repo
    )
    assert len(pointers) == 2
    assert any("Big.uasset" in e and "50 MB" in e for e in errors)
    assert any("Mid.uasset" in w for w in warnings)
    assert not any("Mid.uasset" in e for e in errors)


def test_a_big_plain_file_fails(repo):
    _commit(repo, "unreal/Verse/Data/huge.json", b"0" * (6 * 1024 * 1024))
    errors, _w, _p = check_lfs.check_paths(["unreal/Verse/Data/huge.json"], cwd=repo)
    assert errors and "5 MB" in errors[0]


def test_pr_growth_over_200_mb_needs_approval():
    pointers = [check_lfs.Pointer(f"p{i}", f"{i:064x}", 45 * 1024 * 1024) for i in range(5)]
    assert check_lfs.growth_errors(pointers, env={})
    assert check_lfs.growth_errors(pointers, env={check_lfs.GROWTH_ENV: "1"}) == []


def test_a_pointer_whose_object_is_missing_on_the_remote_fails():
    present, missing = "c" * 64, "d" * 64
    seen = {}

    def fetch(url, body, headers):
        seen["url"] = url
        objs = json.loads(body)["objects"]
        return {
            "objects": [
                {"oid": o["oid"], "size": o["size"], "actions": {"download": {}}}
                if o["oid"] == present
                else {
                    "oid": o["oid"],
                    "size": o["size"],
                    "error": {"code": 404, "message": "Object does not exist"},
                }
                for o in objs
            ]
        }

    pointers = [
        check_lfs.Pointer("a.uasset", present, 10),
        check_lfs.Pointer("b.uasset", missing, 10),
    ]
    errors = check_lfs.missing_on_remote(
        pointers, "https://github.com/Dodaios/Dodaios.git", fetch=fetch
    )
    assert len(errors) == 1 and "b.uasset" in errors[0] and "404" in errors[0]
    assert seen["url"] == "https://github.com/Dodaios/Dodaios.git/info/lfs/objects/batch"


def test_batch_url_forms():
    assert (
        check_lfs.batch_url("git@github.com:Dodaios/Dodaios.git")
        == "https://github.com/Dodaios/Dodaios.git/info/lfs/objects/batch"
    )
    assert (
        check_lfs.batch_url("https://token@github.com/Dodaios/Dodaios")
        == "https://github.com/Dodaios/Dodaios.git/info/lfs/objects/batch"
    )


def test_an_unreachable_remote_fails_closed():
    def fetch(url, body, headers):
        raise OSError("offline")

    errors = check_lfs.missing_on_remote(
        [check_lfs.Pointer("a", "e" * 64, 1)], "https://x/y", fetch=fetch
    )
    assert errors and "unreachable" in errors[0]


# --- Build.cs DAG ---


def test_a_new_build_cs_edge_fails(tmp_path):
    source = REPO / "unreal" / "Verse" / "Source"
    copy = tmp_path / "Source"
    for path in source.rglob("*.Build.cs"):
        target = copy / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    assert check_build_dag.main(["--source", str(copy)]) == 0
    gore = copy / "VerseGore" / "VerseGore.Build.cs"
    text = gore.read_text(encoding="utf-8")
    gore.write_text(text.replace('"VerseCore"', '"VerseCore", "VerseCombat"', 1), encoding="utf-8")
    assert check_build_dag.main(["--source", str(copy)]) == 1


# --- workflows (A10.2) ---


def _load(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def _triggers(workflow: dict) -> dict:
    on = workflow.get("on", workflow.get(True))
    if isinstance(on, str):
        return {on: None}
    if isinstance(on, list):
        return {k: None for k in on}
    return on or {}


FORK_GUARD = "github.event.pull_request.head.repo.full_name == github.repository"


def fork_findings(name: str, workflow: dict) -> list[str]:
    """Self-hosted jobs reachable from a fork pull request."""
    triggers = _triggers(workflow)
    findings = []
    if "pull_request_target" in triggers:
        findings.append(f"{name}: pull_request_target is never allowed on an Unreal lane")
    for job_id, job in workflow.get("jobs", {}).items():
        runs_on = job.get("runs-on", [])
        labels = [runs_on] if isinstance(runs_on, str) else list(runs_on)
        if "self-hosted" not in labels:
            continue
        if "pull_request" in triggers and FORK_GUARD not in str(job.get("if", "")):
            findings.append(f"{name}/{job_id}: self-hosted job runs on fork pull requests")
    return findings


@pytest.mark.parametrize("name", UNREAL_WORKFLOWS)
def test_no_self_hosted_job_runs_for_a_fork_pull_request(name):
    assert fork_findings(name, _load(name)) == []


def test_the_fork_check_catches_an_unguarded_job():
    bad = {True: {"pull_request": {}}, "jobs": {"b": {"runs-on": ["self-hosted", "windows"]}}}
    assert fork_findings("bad.yml", bad)
    target = {True: {"pull_request_target": {}}, "jobs": {}}
    assert fork_findings("t.yml", target)


@pytest.mark.parametrize("name", UNREAL_WORKFLOWS)
def test_unreal_workflows_follow_the_policy(name):
    workflow = _load(name)
    assert "permissions" in workflow
    assert workflow["permissions"] == {"contents": "read"}
    for job in workflow["jobs"].values():
        assert "timeout-minutes" in job
        for step in job.get("steps", []):
            uses = step.get("uses")
            if uses:
                ref = uses.split("@", 1)[1]
                assert len(ref) == 40 and all(c in "0123456789abcdef" for c in ref), uses
            if "actions/checkout" in (uses or ""):
                assert step["with"]["persist-credentials"] is False
            assert "${{" not in step.get("run", ""), f"{name}: expression inside run (use env)"


def test_static_lane_is_hosted_fast_and_lfs_off():
    job = _load("unreal-static.yml")["jobs"]["static"]
    assert job["runs-on"] == "ubuntu-24.04"
    assert job["timeout-minutes"] <= 5
    checkout = job["steps"][0]
    assert checkout["with"]["lfs"] is False
