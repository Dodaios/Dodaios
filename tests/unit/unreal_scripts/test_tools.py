"""netcode.py, perf.py, capture.py, done_check.py and check_bot_isolation.py (WP10.3, 10.7,
10.8, 10.10, 10.11)."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import numpy as np
import pytest

from scripts.unreal import capture, check_bot_isolation, done_check, netcode, perf

# --- netcode ---


def test_netcode_commands_put_lag_on_the_clients_and_iris_on_both():
    cfg = netcode.load_config()
    server = netcode.server_command(Path("E"), Path("P"), cfg, Path("s.log"), 120, iris=False)
    client = netcode.client_command(Path("E"), Path("P"), cfg, Path("c.log"), 120, True, 1000)
    assert "-server" in server and "-UseIrisReplication=0" in server
    assert "-game" in client and "-nullrhi" in client and "-UseIrisReplication=1" in client
    execs = next(c for c in client if c.startswith("-ExecCmds="))
    assert (
        "Net PktLag=60" in execs and "Net PktLagVariance=10" in execs and "Net PktLoss=1" in execs
    )
    assert any(c == f"127.0.0.1:{cfg['port']}" for c in client)


def test_netcode_log_parsing_and_gates():
    server = netcode.parse_log(
        "LogNet: Join succeeded: A\nLogNet: Join succeeded: B\n"
        "[VerseCounter] reconcileAccepted=40\n*** Server: Error for X at Time=1\n"
    )
    clients = [
        netcode.parse_log(
            "*** Client: Error for P at Time=3\n" * 4 + "[VerseCounter] reconcileFailures=0"
        ),
        netcode.parse_log("*** Client: Error for P at Time=3\n" * 2),
    ]
    result = netcode.evaluate(server, clients, 120, netcode.load_config()["gates"])
    assert result["pass"]
    assert result["correctionsPerClientMinute"] == 1.5
    assert result["reconcile"]["reconcileAccepted"] == 40
    clients.append(netcode.parse_log("Fatal error: boom"))
    assert not netcode.evaluate(server, clients, 120, netcode.load_config()["gates"])["pass"]
    lonely = netcode.parse_log("LogNet: Join succeeded: A\n")
    assert not netcode.evaluate(lonely, [], 120, netcode.load_config()["gates"])["pass"]


def test_netcode_parse_run_reads_each_variant(tmp_path):
    for variant in ("iris-on", "iris-off"):
        d = tmp_path / variant
        d.mkdir()
        (d / "server.log").write_text("Join succeeded\nJoin succeeded\n", encoding="utf-8")
        (d / "client0.log").write_text("", encoding="utf-8")
    out = netcode.parse_run(tmp_path, netcode.load_config(), 120)
    assert set(out) == {"iris-on", "iris-off"} and all(v["pass"] for v in out.values())


# --- perf ---


def _csv(path: Path, frames: list[float], game: float = 3.0) -> Path:
    rows = ["FrameTime,GameThreadTime,RenderThreadTime,GPUTime,Exclusive/GameThread/Physics"]
    rows += [f"{f},{game},4.0,7.0,1.2" for f in frames]
    rows += ["[HasHeaderRowAtEnd],1", "FrameTime,GameThreadTime"]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def test_perf_csv_stats(tmp_path):
    frames = [8.0] * 99 + [20.0]
    stats = perf.frame_stats(perf.read_csv(_csv(tmp_path / "a.csv", frames)))
    assert stats["frames"] == 100
    assert stats["frameMsAvg"] == pytest.approx(8.12)
    assert stats["fpsAvg"] == pytest.approx(1000 / 8.12, abs=1e-3)
    assert stats["frameMsP99"] == pytest.approx(8.12, abs=1e-6)
    assert stats["physicsMsAvg"] == 1.2 and stats["gpuMsAvg"] == 7.0


def test_perf_budgets_and_stability(tmp_path):
    budgets = perf.load_json(perf.BUDGETS_FILE)
    stats = {"fpsAvg": 125.0, "frameMsP99": 10.5, "gameThreadMsAvg": 3.0, "physicsMsAvg": 1.0}
    rows = perf.check_budgets(stats, {"vramMbPeak": 5000.0, "ramMbPeak": None}, budgets, "1440p")
    status = {r["budget"]: r["status"] for r in rows}
    assert status["fpsAvg"] == "pass" and status["vramMbPeak"] == "pass"
    assert status["ramMbPeak"] == "not_measured"
    slow = perf.check_budgets({**stats, "fpsAvg": 100.0}, {}, budgets, "1440p")
    assert {r["budget"]: r["status"] for r in slow}["fpsAvg"] == "fail"
    a = {"stats": {"fpsAvg": 120.0, "frameMsP99": 10.0}}
    assert perf.compare(a, {"stats": {"fpsAvg": 117.0, "frameMsP99": 10.2}})["pass"]
    assert not perf.compare(a, {"stats": {"fpsAvg": 110.0, "frameMsP99": 10.0}})["pass"]


def test_perf_quiet_hours():
    quiet = {"start": "01:00", "end": "06:00", "idleMinutes": 5}
    night = dt.datetime(2026, 11, 3, 2, 0)
    assert perf.quiet_reason(quiet, now=night, idle=600) is None
    assert "used the machine" in perf.quiet_reason(quiet, now=night, idle=30)
    assert "outside" in perf.quiet_reason(quiet, now=dt.datetime(2026, 11, 3, 14, 0), idle=600)
    assert perf.in_window(dt.time(23, 30), "22:00", "02:00")


def test_perf_command_keeps_the_window_off_screen():
    profile = {"resX": 2560, "resY": 1440}
    cmd = perf.command_for(Path("E"), Path("P"), perf.REPLAY_FILE, profile, Path("o"), Path("l"))
    assert "-WinX=-20000" in cmd and "-VersePerf" in cmd and "-csvGpuStats" in cmd
    assert "-ResX=2560" in cmd and "-d3d12" in cmd


# --- capture ---


def _image(rgb_counts: dict[tuple[int, int, int], int]) -> np.ndarray:
    pixels = [c for c, n in rgb_counts.items() for _ in range(n)]
    return np.array(pixels, dtype=np.uint8).reshape(1, -1, 3)


def test_palette_shares_and_caps():
    img = _image(
        {
            (0x0B, 0x0C, 0x0E): 40,
            (0x16, 0x17, 0x1A): 25,
            (0x2A, 0x2D, 0x31): 15,
            (0x3B, 0x3F, 0x47): 8,
            (0x5E, 0x63, 0x68): 7,
            (0xF2, 0xF4, 0xF5): 5,
        }
    )
    result = capture.measure(img)
    assert result["shares"]["void_black"] == pytest.approx(0.40)
    assert result["shares"]["work_light"] == pytest.approx(0.05)
    assert result["bannedPixels"] == 0
    assert result["pass"]


def test_palette_caps_fail_on_too_much_amber_and_banned_cyan():
    amber = capture.measure(_image({(0x0B, 0x0C, 0x0E): 98, (0xF2, 0xA3, 0x3A): 2}))
    assert {c["role"]: c["status"] for c in amber["caps"]}["amber"] == "fail"
    cyan = capture.measure(_image({(0x0B, 0x0C, 0x0E): 99, (0x20, 0xC0, 0xE0): 1}))
    assert cyan["bannedPixels"] == 1 and not cyan["pass"]


def test_banned_pixel_rule_edges():
    px = np.array([[[0, 255, 255], [128, 0, 255], [10, 10, 10], [255, 0, 0], [0, 0, 15]]], np.uint8)
    mask = capture.banned_mask(px)[0]
    assert list(mask) == [True, True, False, False, False]


def test_capture_measures_a_png_file(tmp_path):
    from PIL import Image

    Image.fromarray(np.full((8, 8, 3), 0x0B, np.uint8)).save(tmp_path / "v.png")
    assert capture.measure_file(tmp_path / "v.png")["pixels"] == 64


def test_proof_dir_layout(tmp_path):
    path = capture.proof_dir(tmp_path, "WP10", "10.8")
    assert path == tmp_path / "unreal" / "Verse" / "Saved" / "Harness" / "proof" / "WP10" / "10.8"
    with pytest.raises(capture.common.UnrealScriptError):
        capture.proof_dir(tmp_path, "wp10", "10.8")


def test_views_group_by_map_and_every_view_is_well_formed():
    doc = json.loads(capture.CAMERAS_FILE.read_text(encoding="utf-8"))
    groups = capture.views_by_map(doc)
    assert "/Game/Verse/Decks/Hangar/LV_Hangar" in groups
    assert all(
        len(v["location"]) == 3 and len(v["rotation"]) == 3 for vs in groups.values() for v in vs
    )
    assert list(capture.views_by_map(doc, ["hangar_floor"])) == [
        "/Game/Verse/Decks/Hangar/LV_Hangar"
    ]


# --- done_check ---


def test_done_check_lanes_by_path():
    assert done_check.needed_lanes(["dodaios/x.py"]) == []
    assert done_check.needed_lanes(["docs/verse/unreal/README.md"]) == ["static"]
    assert done_check.needed_lanes(["unreal/Verse/Source/VerseBot/A.cpp"]) == ["static", "build"]
    assert done_check.is_visible(["unreal/Verse/Content/Verse/A.uasset"])


def test_done_check_verdicts(tmp_path):
    runs = {
        "unreal-static.yml": [{"status": "completed", "conclusion": "success", "createdAt": "1"}],
        "unreal-build.yml": [{"status": "completed", "conclusion": "failure", "createdAt": "1"}],
    }

    def fake(cmd):
        return json.dumps(runs[cmd[cmd.index("--workflow") + 1]])

    assert done_check.evaluate(["x.py"], "c", tmp_path, fake)["verdict"] == "n/a"
    assert done_check.evaluate(["docs/verse/unreal/a.md"], "c", tmp_path, fake)["verdict"] == "DONE"
    red = done_check.evaluate(["unreal/Verse/Source/A.cpp"], "c", tmp_path, fake)
    assert red["verdict"] == "NOT DONE"
    runs["unreal-build.yml"][0]["conclusion"] = "success"
    visible = done_check.evaluate(["unreal/Verse/Content/A.uasset"], "c", tmp_path, fake)
    assert visible["verdict"] == "NOT DONE" and "screenshot" in visible["problems"][0]
    shot = tmp_path / "unreal" / "Verse" / "Saved" / "Harness" / "proof" / "WP11" / "11.1"
    shot.mkdir(parents=True)
    (shot / "a.png").write_bytes(b"png")
    assert (
        done_check.evaluate(["unreal/Verse/Content/A.uasset"], "c", tmp_path, fake)["verdict"]
        == "DONE"
    )


# --- check_bot_isolation (F1, F6) ---


def _source(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize(
    "code",
    [
        "APawn* P = UGameplayStatics::GetPlayerPawn(this, 0);",
        "auto* C = GetWorld()->GetFirstPlayerController();",
        "for (TActorIterator<AVerseCharacter> It(GetWorld()); It; ++It) {}",
        "UGameplayStatics::GetAllActorsOfClass(this, ACharacter::StaticClass(), Out);",
        "APawn* Them = OtherController->GetPawn();",
        "auto* Asc = UAbilitySystemGlobals::GetAbilitySystemComponentFromActor(Target);",
        "GetWorld()->LineTraceSingleByChannel(Hit, A, B, ECC_Visibility);",
    ],
)
def test_f1_flags_every_truth_read(tmp_path, code):
    root = _source(tmp_path, {"VerseBot/Private/Brain/X.cpp": f"void F() {{ {code} }}\n"})
    assert check_bot_isolation.check_isolation(root)


def test_f1_allows_own_pawn_sight_channel_comments_and_tests(tmp_path):
    root = _source(
        tmp_path,
        {
            "VerseBot/Private/Brain/X.cpp": (
                "// GetPlayerPawn would be cheating\nvoid F() { APawn* Me = GetPawn(); "
                'const char* S = "GetPlayerController"; '
                "W->LineTraceSingleByChannel(H, A, B, VerseSight); "
                "auto* Mine = UAbilitySystemGlobals::"
                "GetAbilitySystemComponentFromActor(GetPawn()); }\n"
            ),
            "VerseBot/Private/Tests/Fakes/FakeWorld.cpp": (
                "APawn* P = UGameplayStatics::GetPlayerPawn(this, 0);"
            ),
            "VerseBot/Private/Belief/VersePieceBelief.cpp": "auto S = Query->GetPieceState(Index);",
        },
    )
    assert check_bot_isolation.check_isolation(root) == []


def test_f1_piece_state_and_eqs_context(tmp_path):
    root = _source(
        tmp_path,
        {
            "VerseBot/Private/Brain/Plan.cpp": "auto S = Query->GetPieceState(Index);",
            "VerseBot/Private/Eqs/Ctx.cpp": (
                "class UCtx : public UEnvQueryContext { AVerseCharacter* T; };"
            ),
        },
    )
    found = check_bot_isolation.check_isolation(root)
    assert any("piece-state" in f for f in found) and any("eqs-context" in f for f in found)


MODEL = "VerseHarness/Private/Balance/VerseModelController.cpp"


def test_f6_symmetry(tmp_path):
    root = _source(
        tmp_path,
        {
            MODEL: "void T(const FVersePerceptFrame& F) {}",
            "VerseBot/Private/Hearing.cpp": "float HearingRangeM = 25.0f;",
        },
    )
    found = check_bot_isolation.check_symmetry(root)
    assert any("hearing-literal" in f for f in found)
    assert any("hearing-source" in f for f in found)
    fixed = _source(
        tmp_path,
        {
            "VerseBot/Private/Hearing.cpp": "float RangeM = Table->HearingRangeFor(Tag); "
            "// UVerseAudibilityTable"
        },
    )
    (fixed / "VerseBot/Private/Hearing.cpp").write_text(
        "float Hearing = UVerseAudibilityTable::RangeFor(Tag, RangeM);", encoding="utf-8"
    )
    assert check_bot_isolation.check_symmetry(fixed) == []
    cheat = _source(
        tmp_path,
        {
            MODEL: "void T(const FVersePerceptFrame& F) { "
            "UGameplayStatics::GetPlayerPawn(this, 0); }"
        },
    )
    assert any("F6.model.player-pawn" in f for f in check_bot_isolation.check_symmetry(cheat))


def test_the_repo_itself_is_clean():
    assert check_bot_isolation.check_isolation() == []
    assert check_bot_isolation.check_symmetry() == []
