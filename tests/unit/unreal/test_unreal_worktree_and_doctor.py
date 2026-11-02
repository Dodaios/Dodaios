"""worktree.py and doctor.py of scripts/unreal (G0.6, G0.1); git and the box are faked."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.unreal import _common as common
from scripts.unreal import doctor, worktree

# --- worktree.py -------------------------------------------------------------


@pytest.mark.parametrize(
    "slug", ["wp01-2-recoil-curve", "wp22-1-installer", "wp02-4a-rewind", "int-wire-combat"]
)
def test_plan_slugs_are_accepted(slug):
    assert worktree.validate_slug(slug) == slug


@pytest.mark.parametrize(
    "slug", ["wp23-1-x", "wp1-1-x", "wp01-x", "WP01-1-x", "wp01-1-", "feature-x", "wp01-1-a_b"]
)
def test_other_slugs_are_refused(slug):
    with pytest.raises(common.UnrealScriptError):
        worktree.validate_slug(slug)


def test_short_ids_have_at_most_twelve_characters_and_never_collide():
    assert worktree.short_id("wp01-2-recoil-curve") == "wp01-2-recoi"
    assert worktree.short_id("int-a") == "int-a"
    taken = {"wp01-2-recoi", "wp01-2-rec-2"}
    chosen = worktree.short_id("wp01-2-recoil-curve", taken=taken.__contains__)
    assert chosen == "wp01-2-rec-3"
    assert len(chosen) <= worktree.MAX_ID
    assert not worktree.short_id("wp01-2-abcde-x").endswith("-")


class _Git:
    def __init__(self, fail=None, branch_exists=False, listing=""):
        self.calls: list[list[str]] = []
        self.fail = fail
        self.branch_exists = branch_exists
        self.listing = listing

    def __call__(self, command, capture=False, **_kw):
        self.calls.append(command)
        if command[0] == "git" and "rev-parse" in command:
            return common.Completed(0 if self.branch_exists else 1)
        if command[0] == "git" and command[3:5] == ["worktree", "list"]:
            return common.Completed(0, self.listing)
        if self.fail and self.fail in command:
            return common.Completed(1, "", "boom")
        return common.Completed(0)


def test_new_fetches_branches_off_origin_main_and_fetches_every_lfs_object(tmp_path):
    git = _Git()
    path = worktree.new("wp05-3-blood-decal", root=tmp_path, runner=git)
    assert path == tmp_path / "wp05-3-blood"
    commands = [c[3:] for c in git.calls]
    assert commands[0] == ["fetch", "origin"]
    assert ["worktree", "add", "-b", "claude/verse-wp05-3-blood-decal", str(path),
            "origin/main"] in commands
    last = git.calls[-1]
    assert last[1:3] == ["-C", str(path)]
    assert last[3:] == ["config", "lfs.fetchexclude", ""]


def test_new_refuses_an_existing_branch_and_a_bad_id(tmp_path):
    with pytest.raises(common.UnrealScriptError, match="already exists"):
        worktree.new("int-x", root=tmp_path, runner=_Git(branch_exists=True))
    with pytest.raises(common.UnrealScriptError, match="--id"):
        worktree.new("int-x", root=tmp_path, wt_id="far-too-long-id", runner=_Git())


def test_new_stops_when_the_fetch_fails(tmp_path):
    git = _Git(fail="fetch")
    with pytest.raises(common.UnrealScriptError, match="git fetch origin failed"):
        worktree.new("int-x", root=tmp_path, runner=git)
    assert not any("add" in c for c in git.calls)


def _listing(*paths: Path) -> str:
    return "".join(f"worktree {p}\nHEAD 0\nbranch refs/heads/x\n\n" for p in paths)


def test_remove_cleans_then_unlinks_node_modules_then_removes_the_worktree(tmp_path, monkeypatch):
    main, tree = tmp_path / "main", tmp_path / "wt" / "int-x"
    for folder in (main, tree / "dodaios" / "ui" / "node_modules", tree / "real" / "nm"):
        folder.mkdir(parents=True)
    link = tree / "dodaios" / "ui" / "node_modules"
    monkeypatch.setattr(worktree, "_is_link", lambda p: p == link)
    order: list[str] = []
    git = _Git(listing=_listing(main, tree))

    def runner(command, capture=False, **kw):
        if command[:3] == ["cmd", "/c", "rmdir"]:
            order.append(f"unlink {Path(command[3]).name}")
            return common.Completed(0)
        if "remove" in command:
            order.append("git worktree remove")
        return git(command, capture=capture, **kw)

    monkeypatch.setattr(worktree, "_WINDOWS", True)
    worktree.remove(str(tree), runner=runner, cleaner=lambda p: order.append(f"clean {p.name}"))
    assert order == ["clean int-x", "unlink node_modules", "git worktree remove"]
    assert not any("--force" in c for c in git.calls)


def test_remove_never_touches_the_main_checkout_or_a_foreign_folder(tmp_path):
    main, other = tmp_path / "main", tmp_path / "other"
    main.mkdir()
    other.mkdir()
    git = _Git(listing=_listing(main))
    with pytest.raises(common.UnrealScriptError, match="main checkout"):
        worktree.remove(str(main), runner=git, cleaner=lambda p: pytest.fail("cleaned"))
    with pytest.raises(common.UnrealScriptError, match="not a worktree"):
        worktree.remove(str(other), runner=git, cleaner=lambda p: pytest.fail("cleaned"))


def test_the_link_walk_never_descends_into_node_modules_or_build_output(tmp_path, monkeypatch):
    plain = tmp_path / "a" / "node_modules"
    nested = plain / "pkg" / "node_modules"
    hidden = tmp_path / "unreal" / "Verse" / "Intermediate" / "node_modules"
    for folder in (nested, hidden):
        folder.mkdir(parents=True)
    monkeypatch.setattr(worktree, "_is_link", lambda p: p in (nested, hidden))
    assert list(worktree.node_modules_links(tmp_path)) == []


# --- doctor.py ---------------------------------------------------------------

PINS = json.loads(common.TOOLCHAINS_FILE.read_text(encoding="utf-8"))
ENGINE = Path("E:/UE")
VS = Path("E:/VS")
WINDOWS_SDK_JSON = {
    "MainVersion": "10.0.22621.0",
    "BannedVisualCppVersions": ["14.44.0-14.44.35210", "14.40.0-14.43.99999"],
}


def _box(cl="19.44.35229", vs="17.14.37827.9", lfs="3.7.1", release=533509, linux_root=None,
         missing=()):
    files = {
        ENGINE / "Engine" / "Build" / "Build.version": json.dumps(
            {"MajorVersion": 5, "MinorVersion": 7, "PatchVersion": 1}),
        ENGINE / "Engine/Config/Windows/Windows_SDK.json": json.dumps(WINDOWS_SDK_JSON),
        ENGINE / "Engine/Config/Linux/Linux_SDK.json": json.dumps(
            {"MainVersion": PINS["linux"]["sdk"]}),
        common.project_file(common.REPO_ROOT): json.dumps({"EngineAssociation": "5.7"}),
    }
    sdk_root = Path(PINS["windows_sdk"]["root"])
    ref_root = Path(PINS["netfx"]["reference_root"])
    cl_path = VS / "VC" / "Tools" / "MSVC" / "14.44.35207" / "bin" / "Hostx64" / "x64" / "cl.exe"
    present = {doctor.VSWHERE, cl_path, sdk_root / "Include" / "10.0.22621.0",
               sdk_root / "Lib" / "10.0.22621.0", ref_root / "v4.6.2", ref_root / "v4.8.1"}
    env = {common.ENGINE_ENV: str(ENGINE)}
    if linux_root:
        env["LINUX_MULTIARCH_ROOT"] = linux_root
        present.add(Path(linux_root) / "x86_64-unknown-linux-gnu" / "bin" / "clang++.exe")
    present -= set(missing)

    def run(command, capture=False, **_kw):
        if command[0] == str(doctor.VSWHERE):
            return common.Completed(0, json.dumps([{
                "installationPath": str(VS), "installationVersion": vs,
                "productId": "Microsoft.VisualStudio.Product.BuildTools"}]))
        if command[0] == str(cl_path):
            return common.Completed(0, "", f"Microsoft (R) C/C++ Optimizing Compiler Version "
                                           f"{cl} for x64\n")
        if command[:3] == ["git", "lfs", "version"]:
            return common.Completed(0, f"git-lfs/{lfs} (GitHub; windows amd64)\n")
        return common.Completed(1)

    def read_text(path):
        if path in files:
            return files[path]
        raise OSError(path)

    return doctor.Probe(
        run=run,
        exists=lambda p: p in present,
        read_text=read_text,
        listdir=lambda p: ["14.44.35207"] if p == VS / "VC" / "Tools" / "MSVC" else [],
        env=env,
        free_gb=lambda _p: 200.0,
        netfx_release=lambda: release,
        is_windows=True,
    )


def _status(checks):
    return {c.name: c.status for c in checks}


def test_this_box_as_of_today_is_green_for_win64(tmp_path, monkeypatch):
    monkeypatch.setenv("DODAIOS_LOCK_DIR", str(tmp_path))
    probe = _box()
    probe.env["DODAIOS_LOCK_DIR"] = str(tmp_path)
    checks = doctor.diagnose(["win64"], probe=probe, pins=PINS)
    assert [c for c in checks if c.status == "fail"] == []
    assert _status(checks)["linux-toolchain"] == "skip"


def test_a_missing_linux_toolchain_is_red_with_a_fix(tmp_path):
    probe = _box()
    probe.env["DODAIOS_LOCK_DIR"] = str(tmp_path)
    linux = next(c for c in doctor.diagnose(probe=probe, pins=PINS) if c.name == "linux-toolchain")
    assert linux.status == "fail" and "LINUX_MULTIARCH_ROOT" in linux.detail
    assert PINS["linux"]["sdk"] in linux.fix


def test_an_installed_linux_toolchain_is_green(tmp_path):
    root = f"E:/UnrealToolchains/{PINS['linux']['sdk']}"
    probe = _box(linux_root=root)
    probe.env["DODAIOS_LOCK_DIR"] = str(tmp_path)
    assert _status(doctor.diagnose(probe=probe, pins=PINS))["linux-toolchain"] == "ok"


@pytest.mark.parametrize(
    ("kwargs", "name"),
    [
        ({"cl": "19.44.35207"}, "msvc"),  # inside the engine's banned range
        ({"cl": "19.42.34433"}, "msvc"),
        ({"vs": "17.8.0"}, "visual-studio"),
        ({"lfs": "3.4.0"}, "git-lfs"),
        ({"release": 528040}, "netfx-runtime"),
        ({"missing": [Path(PINS["netfx"]["reference_root"]) / "v4.6.2"]}, "netfx-targeting"),
        ({"missing": [Path(PINS["windows_sdk"]["root"]) / "Lib" / "10.0.22621.0"]},
         "windows-sdk"),
    ],
)
def test_each_wrong_tool_turns_its_check_red(tmp_path, kwargs, name):
    probe = _box(**kwargs)
    probe.env["DODAIOS_LOCK_DIR"] = str(tmp_path)
    assert _status(doctor.diagnose(["win64"], probe=probe, pins=PINS))[name] == "fail"


def test_low_disk_and_a_wrong_engine_are_red(tmp_path):
    probe = _box()
    probe.env["DODAIOS_LOCK_DIR"] = str(tmp_path)
    probe.free_gb = lambda _p: 12.0
    pins = json.loads(json.dumps(PINS))
    pins["engine"]["version"] = "5.7.2"
    status = _status(doctor.diagnose(["win64"], probe=probe, pins=pins))
    assert status["disk"] == "fail"
    assert status["engine"] == "fail"


def test_version_ranges_follow_the_engine_file_format():
    assert doctor.in_range("14.44.35207", "14.44.0-14.44.35210")
    assert not doctor.in_range("14.44.35229", "14.44.0-14.44.35210")
    assert doctor.in_range("10.0.22621.0", "10.0.22621.0")


def test_the_pins_match_the_plan_and_the_shared_limits():
    assert PINS["schema"] == "verse.toolchains/1"
    assert PINS["engine"]["version"] == "5.7.1"
    assert PINS["disk"]["min_free_gb"] == common.MIN_FREE_GB
    assert PINS["msvc"]["family"] == "14.44"


def test_the_pins_match_the_installed_engine_when_there_is_one():
    engine = common.engine_root()
    sdk = engine / "Engine" / "Config" / "Windows" / "Windows_SDK.json"
    if not sdk.is_file():
        pytest.skip("no Unreal install on this machine")
    windows = json.loads(sdk.read_text(encoding="utf-8-sig"))
    linux = json.loads((engine / "Engine/Config/Linux/Linux_SDK.json").read_text("utf-8-sig"))
    assert windows["MainVersion"] == PINS["windows_sdk"]["version"]
    assert linux["MainVersion"] == PINS["linux"]["sdk"]
    assert not any(doctor.in_range(PINS["msvc"]["min_version"], s)
                   for s in windows["BannedVisualCppVersions"])
