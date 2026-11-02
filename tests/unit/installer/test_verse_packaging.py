"""Packaging, chunks, toolchain pins, Linux smoke and disk hygiene (WP22.1-22.3, 22.7-22.9)."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import secrets
import shutil
import subprocess
import time
from pathlib import Path

import pytest
import yaml

from scripts.unreal import _common as common
from scripts.unreal import package

REPO = Path(__file__).resolve().parents[3]


def _load_activation():
    # packaging/ is not a Python package (and its name is taken by a library).
    path = REPO / "packaging/linux/verse/activation_check.py"
    spec = importlib.util.spec_from_file_location("verse_activation_check", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


activation = _load_activation()


# ------------------------------------------------------------------ 22.1 pins
def test_toolchain_pins_name_every_installable_part() -> None:
    pins = common.load_toolchains()
    assert pins["engine"]["version"] == "5.7.1"
    assert pins["visual_studio"]["components"]
    linux = pins["linux"]
    assert linux["sdk"] in linux["installer_url"]
    assert re.fullmatch(r"[0-9a-f]{64}", linux["installer_sha256"])
    assert linux["installer_bytes"] > 0
    assert linux["engine_component"].endswith("UnrealGame.target")


def test_ddc_policy_is_local_and_capped() -> None:
    ddc = package.load_ddc()
    assert ddc["shared"] is False
    assert ddc["cap_gb"] == 40
    assert ddc["alert_free_gb"] == 40
    assert package.ddc_args(ddc) == [f"-ddc={ddc['graph']}"]
    assert package.ddc_env(ddc, {})[ddc["local_path_env"]] == ddc["local_path"]


def test_verify_reports_the_missing_linux_engine_part(tmp_path: Path) -> None:
    probe = package.VerifyProbe(
        run=lambda *a, **k: common.Completed(0, "linux"),
        exists=lambda p: False,
        which=lambda name: "docker",
    )
    checks = {
        c["name"]: c for c in package.verify_packaging(["linux"], engine=tmp_path, probe=probe)
    }
    assert checks["chunks"]["status"] == "ok"
    assert checks["ddc"]["status"] == "ok"
    assert checks["linux-engine"]["status"] == "fail"
    assert "Target Platforms, Linux" in checks["linux-engine"]["fix"]
    assert checks["docker"]["status"] == "ok"
    win_only = package.verify_packaging(["win64"], engine=tmp_path, probe=probe)
    assert {c["name"] for c in win_only} == {"chunks", "ddc"}


# ------------------------------------------------------ 22.2 BuildCookRun
def test_buildcookrun_is_shipping_iostore_chunked_and_compressed(tmp_path: Path) -> None:
    command = package.buildcookrun_command(
        package.PLATFORMS["win64"],
        "Shipping",
        engine=tmp_path,
        project=tmp_path / "Verse.uproject",
        archive=tmp_path / "out",
        ddc=package.load_ddc(),
    )
    for flag in (
        "-target=Verse",
        "-platform=Win64",
        "-clientconfig=Shipping",
        "-iostore",
        "-pak",
        "-compressed",
        "-manifests",
        "-nodebuginfo",
        "-nocompileeditor",
        "-prereqs",
        "-ddc=InstalledDerivedDataBackendGraph",
    ):
        assert flag in command
    assert command[0].endswith("RunUAT.bat") and command[1] == "BuildCookRun"
    linux = package.buildcookrun_command(
        package.PLATFORMS["linux"],
        "Shipping",
        engine=tmp_path,
        project=tmp_path / "p",
        archive=tmp_path / "o",
    )
    assert "-platform=Linux" in linux and "-prereqs" not in linux
    assert not any("Harness" in part for part in command + linux)


def test_the_game_target_on_disk_has_no_harness() -> None:
    assert package.harness_problems(REPO, package.PLATFORMS["win64"], None) == []


def test_harness_detection_in_target_objects_and_binaries(tmp_path: Path) -> None:
    source = tmp_path / "unreal/Verse/Source"
    source.mkdir(parents=True)
    (source / "Verse.Target.cs").write_text(
        '// VerseHarness lives in the editor target only\nExtraModuleNames.Add("Verse");\n',
        encoding="utf-8",
    )
    spec = package.PLATFORMS["win64"]
    staged = tmp_path / "staged"
    (staged / "Verse/Binaries/Win64").mkdir(parents=True)
    exe = staged / "Verse/Binaries/Win64/Verse-Win64-Shipping.exe"
    exe.write_bytes(b"MZ" + b"\0" * 100)
    (staged / "Verse/Content/Paks").mkdir(parents=True)
    (staged / "Verse/Content/Paks/pakchunk0-Windows.ucas").write_bytes(b"VerseHarness")
    assert package.harness_problems(tmp_path, spec, staged) == []

    exe.write_bytes(b"MZ" + "VerseHarness".encode("utf-16-le"))
    (tmp_path / "unreal/Verse/Intermediate/Build/Win64/x64/Verse/Shipping/VerseHarness").mkdir(
        parents=True
    )
    (source / "Verse.Target.cs").write_text(
        'ExtraModuleNames.Add("VerseHarness");\n', encoding="utf-8"
    )
    problems = package.harness_problems(tmp_path, spec, staged)
    assert len(problems) == 3
    assert any("Verse.Target.cs" in p for p in problems)
    assert any("Shipping objects" in p for p in problems)
    assert any("Verse-Win64-Shipping.exe carries VerseHarness" in p for p in problems)


# ---------------------------------------------------- 22.3 chunks, size, PSO
def test_every_deck_level_gets_its_own_chunk() -> None:
    chunks = package.load_chunks()
    by_name = {c["name"]: c for c in chunks["chunks"]}
    assert by_name["core"]["id"] == 0 and by_name["core"]["maps"] == []
    for deck in ("Bridge", "Ops", "Engineering", "Hangar"):
        assert by_name[deck.lower()]["maps"] == [f"/Game/Verse/Decks/{deck}/LV_{deck}"]
    block = package.chunk_ini_block(chunks)
    assert "bGenerateChunks=True" in block
    assert 'PrimaryAssetId="Map:LV_Hangar",Rules=(Priority=14,ChunkId=4' in block
    assert block.count("+PrimaryAssetRules=") == 4


def test_chunk_rule_problems_catch_broken_rules() -> None:
    broken = {
        "schema": "verse.chunks/1",
        "size_gate": {"payload_max_bytes": 1, "delta_typical_max_bytes": 0},
        "chunks": [
            {"id": 1, "name": "a", "maps": ["/Game/Verse/Decks/Ops/LV_Ops"]},
            {"id": 1, "name": "a", "maps": ["/Game/Verse/Decks/Ops/LV_Ops", "/Game/Other"]},
        ],
    }
    problems = package.chunk_rule_problems(broken)
    assert "chunk 0 (core) is required" in problems
    assert "chunk ids must be unique" in problems
    assert "chunk names must be unique" in problems
    assert "a map belongs to exactly one chunk" in problems
    assert any("/Game/Other" in p for p in problems)
    assert any("delta_typical_max_bytes" in p for p in problems)


def test_missing_chunk_config_lists_what_the_ini_lacks(tmp_path: Path) -> None:
    chunks = package.load_chunks()
    (tmp_path / "Config").mkdir()
    assert len(package.missing_chunk_config(tmp_path, chunks)) == 8
    (tmp_path / "Config/DefaultGame.ini").write_text(
        package.chunk_ini_block(chunks), encoding="utf-8"
    )
    assert package.missing_chunk_config(tmp_path, chunks) == []


def test_size_report_groups_bytes_by_deck_chunk(tmp_path: Path) -> None:
    paks = tmp_path / "Verse/Content/Paks"
    paks.mkdir(parents=True)
    files = {
        "global.utoc": 10,
        "global.ucas": 20,
        "pakchunk0-Windows.utoc": 5,
        "pakchunk0-Windows.ucas": 100,
        "pakchunk0-Windows.pak": 1,
        "pakchunk4-Windows.ucas": 300,
        "pakchunk4optional-Windows.ucas": 7,
        "pakchunk9-Windows.ucas": 2,
    }
    for name, size in files.items():
        (paks / name).write_bytes(b"x" * size)
    (tmp_path / "Verse.exe").write_bytes(b"x" * 50)
    report = package.size_report(tmp_path, package.load_chunks(), platform="Win64")
    assert report["chunks"]["global"] == {"bytes": 30, "files": 2}
    assert report["chunks"]["core"] == {"bytes": 106, "files": 3}
    assert report["chunks"]["hangar"] == {"bytes": 307, "files": 2}
    assert report["chunks"]["binaries"] == {"bytes": 50, "files": 1}
    assert report["unknown_chunk_files"] == ["pakchunk9-Windows.ucas"]
    assert report["total_bytes"] == sum(files.values()) + 50
    assert report["within_payload_cap"] is True
    assert report["deck_chunks_present"] == ["hangar"]
    assert report["deck_chunks_missing"] == ["bridge", "engineering", "ops"]
    assert report["pso_cache_shipped"] is False
    (tmp_path / "Verse/Content/PipelineCaches").mkdir()
    (tmp_path / "Verse/Content/PipelineCaches/Verse_Win64.spc").write_bytes(b"p")
    assert package.size_report(tmp_path, package.load_chunks(), platform="Win64")[
        "pso_cache_shipped"
    ]


def test_pso_expand_writes_into_the_engine_required_build_folder(tmp_path: Path) -> None:
    shk, shipped = package.pso_paths(tmp_path, package.PLATFORMS["win64"])
    assert shipped == tmp_path / "unreal/Verse/Build/Windows/PipelineCaches"
    assert shk.parts[-4:] == ("Windows", "Verse", "Metadata", "PipelineCaches")
    command = package.pso_expand_command(
        tmp_path,
        tmp_path / "p",
        [tmp_path / "a.upipelinecache"],
        [tmp_path / "b.shk"],
        shipped / "Verse_Win64.spc",
    )
    assert command[2:4] == ["-run=ShaderPipelineCacheTools", "expand"]
    assert command[-6].endswith("Verse_Win64.spc")


def test_cold_start_marker_wait(tmp_path: Path) -> None:
    log = tmp_path / "game.log"
    log.write_text("LogInit: start\nVerseSmoke: stage boot OK\n", encoding="utf-8")
    # The boot stage is not the first frame.
    assert not package.FIRST_FRAME.search(log.read_text(encoding="utf-8"))
    log.write_text("LogInit: start\nVerseSmoke: first frame\n", encoding="utf-8")
    ticks = iter([0.0, 0.0, 0.4])
    seconds = package.wait_for_marker(
        log,
        package.FIRST_FRAME,
        timeout_s=8,
        alive=lambda: True,
        clock=lambda: next(ticks),
        sleep=lambda s: None,
    )
    assert seconds == 0.4
    log.write_text("LogInit: start\n", encoding="utf-8")
    assert (
        package.wait_for_marker(
            log, package.FIRST_FRAME, timeout_s=8, alive=lambda: False, sleep=lambda s: None
        )
        is None
    )


def _bridge_report(**overrides) -> dict:
    report = {
        "received": {"hello": 1, "lifecycle.ready": 1},
        "sent": {"welcome": 1},
        "expectations": [{"type": "lifecycle.ready", "ok": True, "optional": False}],
        "invalid_from_verse": [],
    }
    report.update(overrides)
    return report


def test_bridge_problems_need_the_handshake_and_lifecycle_ready() -> None:
    assert package.bridge_problems(_bridge_report(), require_ready=True) == []
    assert package.bridge_problems(None, require_ready=False)
    no_hello = package.bridge_problems(_bridge_report(sent={}), require_ready=False)
    assert no_hello == ["no hello/welcome handshake (the bridge sent no welcome)"]
    not_ready = _bridge_report(
        expectations=[{"type": "lifecycle.ready", "ok": False, "optional": True}]
    )
    assert package.bridge_problems(not_ready, require_ready=False) == []
    assert package.bridge_problems(not_ready, require_ready=True) == [
        "no lifecycle.ready after the first frame"
    ]
    scenario = package.bridge_scenario(ready_timeout_s=12)
    assert scenario["steps"] == [
        {"at_ms": 0, "expect": {"type": "lifecycle.ready"}, "timeout_ms": 12000, "optional": False}
    ]


TEST_TOKEN = secrets.token_hex(8)
FAKE_BRIDGE_STANDIN = """
import argparse, json, os, sys, time
p = argparse.ArgumentParser()
for name in ("--scenario", "--report", "--discovery"):
    p.add_argument(name)
p.add_argument("--once", action="store_true")
a = p.parse_args()
scenario = json.load(open(a.scenario, encoding="utf-8"))
json.dump({"url": "ws://127.0.0.1:1/api/verse/bridge", "token": os.environ["DODAIOS_VERSE_TOKEN"]},
          open(a.discovery, "w", encoding="utf-8"))
time.sleep(0.3)
json.dump({"received": {"hello": 1}, "sent": {"welcome": 1}, "invalid_from_verse": [],
           "expectations": [{"type": scenario["steps"][0]["expect"]["type"], "ok": True}]},
          open(a.report, "w", encoding="utf-8"))
"""


def test_fake_bridge_run_hands_url_and_token_to_the_game(tmp_path: Path) -> None:
    script = tmp_path / "fake_bridge.py"
    script.write_text(FAKE_BRIDGE_STANDIN, encoding="utf-8")
    run = package.FakeBridgeRun(
        tmp_path / "out", token=TEST_TOKEN, ready_timeout_s=5, fake_bridge=script
    )
    with run:
        env = run.env({})
    assert env == {
        package.BRIDGE_ENV: "ws://127.0.0.1:1/api/verse/bridge",
        package.TOKEN_ENV: TEST_TOKEN,
    }
    assert package.bridge_problems(run.report, require_ready=True) == []
    with pytest.raises(common.UnrealScriptError, match="fake bridge"):
        with package.FakeBridgeRun(
            tmp_path / "o2",
            token=TEST_TOKEN,
            ready_timeout_s=1,
            fake_bridge=tmp_path / "missing.py",
        ):
            pass


# ------------------------------------------------------------ 22.7 Linux
def test_docker_smoke_command_is_offline_and_read_only(tmp_path: Path) -> None:
    command = package.docker_smoke_command(
        tmp_path / "Linux", tmp_path / "out", seconds=60, gpu=False, name="verse-smoke-test"
    )
    assert command[:3] == ["docker", "run", "--rm"]
    assert command[command.index("--network") + 1] == "none"
    assert f"{tmp_path / 'Linux'}:/verse:ro" in command
    assert command[-3:] == ["/smoke/linux_smoke.sh", "60", "nogpu"]
    assert "--gpus" not in command
    # The fake bridge and its golden data reach the container read-only.
    assert f"{REPO / 'scripts'}:/repo/scripts:ro" in command
    assert f"{package.BRIDGE_DATA_DIR}:/repo/unreal/Verse/Tests/Data/bridge:ro" in command
    gpu = package.docker_smoke_command(tmp_path, tmp_path, seconds=60, gpu=True)
    assert gpu[gpu.index("--gpus") + 1] == "all" and gpu[-1] == "gpu"


def test_linux_smoke_evaluation(tmp_path: Path) -> None:
    assert package.evaluate_linux_smoke(tmp_path)["pass"] is False
    (tmp_path / "result.json").write_text(
        json.dumps(
            {
                "server_ok": True,
                "vulkan": "skip",
                "problems": [],
                "activation": {"x11": "ok", "wayland": "ok"},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "nullrhi.log").write_text("VerseSmoke: stage boot OK\n", encoding="utf-8")
    # No bridge report: the handshake never happened.
    assert package.evaluate_linux_smoke(tmp_path)["pass"] is False
    (tmp_path / "bridge-server-report.json").write_text(
        json.dumps(_bridge_report()), encoding="utf-8"
    )
    assert package.evaluate_linux_smoke(tmp_path)["pass"] is True
    (tmp_path / "nullrhi.log").write_text("LogWindows: Error: Fatal error!\n", encoding="utf-8")
    result = package.evaluate_linux_smoke(tmp_path)
    assert result["pass"] is False and result["problems"]


def test_linux_smoke_scripts_parse_under_bash() -> None:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("no bash")
    for script in ("linux_smoke.sh", "stage_verse.sh"):
        path = REPO / "packaging/linux/verse" / script
        assert subprocess.run([bash, "-n", str(path)], check=False).returncode == 0


def test_activation_parsers_and_statuses() -> None:
    xprop = "_NET_SUPPORTED(ATOM) = _NET_WM_NAME, _NET_ACTIVE_WINDOW, _NET_CLIENT_LIST\n"
    assert activation.x11_supports_activation(xprop)
    assert not activation.x11_supports_activation("_NET_SUPPORTED(ATOM) = _NET_WM_NAME\n")
    assert not activation.x11_supports_activation("_NET_SUPPORTED:  not found.\n")
    info = "interface: 'wl_compositor', version: 6\ninterface: 'xdg_activation_v1', version: 1\n"
    assert activation.wayland_supports_activation(info)

    def run(command, env):
        if command[0] == "xprop":
            return 0, xprop
        return 0, "interface: 'wl_shm', version: 1\n"

    assert activation.check_x11(":98", run)[0] == "ok"
    assert activation.check_wayland("wl-0", run)[0] == "fail"
    assert activation.check_x11(None, run)[0] == "skip"
    assert activation.check_wayland("wl-0", lambda c, e: (1, ""))[0] == "skip"
    assert activation.main(["--x11", ":98"], run) == 0
    assert activation.main(["--x11", ":98", "--wayland", "wl-0"], run) == 1


# ------------------------------------------------------------ 22.9 hygiene
def _file(path: Path, size: int, age_s: float, now: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    os.utime(path, (now - age_s, now - age_s))


def test_ddc_prune_removes_oldest_first_down_to_the_cap(tmp_path: Path) -> None:
    now = time.time()
    _file(tmp_path / "a", 400, 300, now)
    _file(tmp_path / "b/c", 300, 200, now)
    _file(tmp_path / "d", 300, 100, now)
    total, prune = package.plan_ddc_prune(tmp_path, cap_bytes=500)
    assert total == 1000
    assert prune == [tmp_path / "a", tmp_path / "b/c"]
    assert package.plan_ddc_prune(tmp_path / "missing", 1) == (0, [])


def test_hygiene_plans_intermediate_pruning_and_alerts(tmp_path: Path) -> None:
    now = time.time()
    _file(tmp_path / "wt-old/unreal/Verse/Intermediate/Build/x.obj", 10, 10 * 86400, now)
    _file(tmp_path / "wt-new/unreal/Verse/Intermediate/Build/x.obj", 10, 60, now)
    (tmp_path / "wt-none").mkdir()
    ddc = dict(package.load_ddc(), local_path=str(tmp_path / "ddc"), zen_data_path="")
    _file(tmp_path / "ddc/old", 10, 100, now)
    plan = package.plan_hygiene(ddc, worktrees_root=tmp_path, now=now, free_gb=lambda p: 12.0)
    assert plan.intermediate_prune == [tmp_path / "wt-old/unreal/Verse/Intermediate"]
    assert plan.ddc_prune == []
    assert plan.alert is True
    removed = package.apply_hygiene(plan)
    assert removed == 1
    assert not (tmp_path / "wt-old/unreal/Verse/Intermediate").exists()
    assert (tmp_path / "wt-new/unreal/Verse/Intermediate").exists()
    healthy = package.plan_hygiene(ddc, worktrees_root=tmp_path, now=now, free_gb=lambda p: 500)
    assert healthy.alert is False


def test_a_locked_intermediate_folder_does_not_stop_the_prune(tmp_path: Path) -> None:
    plan = package.HygienePlan(intermediate_prune=[tmp_path / "a", tmp_path / "b"])
    removed: list[Path] = []

    def remove_tree(folder: Path) -> None:
        if folder.name == "a":
            raise PermissionError("in use")
        removed.append(folder)

    assert package.apply_hygiene(plan, remove_tree=remove_tree) == 1
    assert removed == [tmp_path / "b"]


def test_hygiene_plans_again_inside_the_lock_and_fails_over_a_zen_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import argparse

    now = time.time()
    stale = tmp_path / "wt/unreal/Verse/Intermediate"
    _file(stale / "x.obj", 10, 10 * 86400, now)
    zen = tmp_path / "zen"
    _file(zen / "cas.ucas", 50, 10, now)
    ddc = dict(
        package.load_ddc(),
        local_path=str(tmp_path / "ddc"),
        zen_data_path=str(zen),
        cap_gb=0,
        alert_free_gb=0,
    )
    monkeypatch.setattr(package, "load_ddc", lambda: ddc)

    class Lock:
        def __init__(self, *args) -> None:
            pass

        def __enter__(self):
            # The worktree became active while the job waited in the queue.
            _file(stale / "fresh.obj", 10, 0, time.time())
            return self

        def __exit__(self, *exc) -> None:
            return None

    monkeypatch.setattr(package.with_lock, "MachineLock", Lock)
    options = argparse.Namespace(worktrees=tmp_path, apply=True)
    assert package.cmd_hygiene(options) == 4  # the Zen store is over its cap
    assert stale.is_dir()


# ---------------------------------------------------- 22.8 workflow policy
def _workflow() -> dict:
    return yaml.safe_load((REPO / ".github/workflows/unreal-package.yml").read_text("utf-8"))


def test_package_workflow_never_runs_self_hosted_for_pull_requests() -> None:
    workflow = _workflow()
    triggers = workflow.get("on") or workflow.get(True)
    assert "pull_request" not in triggers and "pull_request_target" not in triggers
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["concurrency"]["group"] == "unreal-build"


def test_no_secret_reaches_the_self_hosted_runner() -> None:
    for name, job in _workflow()["jobs"].items():
        runs_on = job["runs-on"]
        if isinstance(runs_on, list) and "self-hosted" in runs_on:
            dumped = yaml.safe_dump(job)
            assert "secrets." not in dumped, name
            assert job["permissions"] == {"contents": "read"}, name
            assert "environment" not in job, name


def test_signing_and_release_jobs_follow_the_existing_paths() -> None:
    jobs = _workflow()["jobs"]
    assert jobs["sign-windows"]["runs-on"] == "windows-latest"
    signpath = [
        s for s in jobs["sign-windows"]["steps"] if s.get("uses", "").startswith("signpath/")
    ]
    assert signpath and re.fullmatch(r"signpath/[\w-]+@[0-9a-f]{40}", signpath[0]["uses"])
    assert jobs["sign-manifest"]["environment"] == "release-signing"
    assert "offline-ceremony.pub" in yaml.safe_dump(jobs["sign-manifest"])
    writers = [n for n, j in jobs.items() if j.get("permissions", {}).get("contents") == "write"]
    # A failed Linux leg must not hold back the Windows payload.
    for name in ("sign-windows", "assemble", "sign-manifest", "release"):
        assert "!cancelled()" in jobs[name]["if"], name
    assert writers == ["release"]
    assert "--clobber" not in yaml.safe_dump(jobs["release"])


def test_workflow_policy_check_stays_green() -> None:
    from scripts.ci import check_workflow_policy as policy

    workflows = {
        path.name: yaml.safe_load(path.read_text(encoding="utf-8"))
        for path in (REPO / ".github/workflows").glob("*.yml")
    }
    findings = [f for f in policy.audit(workflows) if "unreal-package" in f]
    assert findings == []


# --------------------------------------------------- 22.6 installer staging
def test_stage_scripts_reject_a_wrong_payload_name(tmp_path: Path) -> None:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("no bash")
    script = REPO / "packaging/linux/verse/stage_verse.sh"
    bad = subprocess.run(
        [bash, str(script), str(tmp_path / "Verse-Win64-1.0.0.tar"), str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert bad.returncode == 2 and "not a Linux Verse payload" in bad.stderr


def test_stage_script_copies_a_linux_payload(tmp_path: Path) -> None:
    bash = shutil.which("bash")
    if bash is None or shutil.which("tar") is None:
        pytest.skip("no bash or tar")
    stage = tmp_path / "stage"
    stage.mkdir()
    (stage / "Verse.sh").write_bytes(b"#!/bin/sh\n")
    payload = tmp_path / "Verse-Linux-4.2.0.tar"
    package.make_full(stage, version="4.2.0", platform="Linux", out=payload)
    freeze = tmp_path / "Jarvis"
    freeze.mkdir()
    done = subprocess.run(
        [
            bash,
            str(REPO / "packaging/linux/verse/stage_verse.sh"),
            payload.name,  # relative: GNU tar reads "C:/..." as a remote host
            freeze.name,
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert (freeze / "verse" / payload.name).read_bytes() == payload.read_bytes()
