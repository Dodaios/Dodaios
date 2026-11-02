#!/usr/bin/env python3
"""Check that this box has the toolchain the Unreal Verse needs. Installs nothing.

Reads the pins in ``unreal/Toolchain/toolchains.json`` and the engine's own
requirement files (``Engine/Config/Windows/Windows_SDK.json`` and
``Engine/Config/Linux/Linux_SDK.json``), then checks the engine version, the
Visual Studio Build Tools, the MSVC compiler (the real ``cl.exe`` version,
which is what the engine compares with its banned list), the Windows SDK,
.NET Framework and its targeting packs, git-lfs, the Linux cross toolchain,
free disk space and the lock folder (docs/verse/unreal/orchestration.md 0.1).

    python scripts/unreal/doctor.py                  # every check
    python scripts/unreal/doctor.py --target win64   # skip the Linux toolchain
    python scripts/unreal/doctor.py --json

Exit code 0 when no check fails, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.unreal import _common as common
from scripts.unreal import with_lock

VSWHERE = Path("C:/Program Files (x86)/Microsoft Visual Studio/Installer/vswhere.exe")
NETFX_KEY = r"SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full"


@dataclass
class Check:
    name: str
    status: str  # "ok" | "fail" | "skip"
    detail: str
    fix: str = ""


def version_tuple(text: str) -> tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"\d+", text))


def in_range(version: str, spec: str) -> bool:
    """``spec`` is ``low-high`` as in the engine's SDK files (inclusive)."""
    low, _, high = spec.partition("-")
    value = version_tuple(version)
    return version_tuple(low) <= value <= version_tuple(high or low)


@dataclass
class Probe:
    """Everything doctor reads from the machine; the tests replace it."""

    run: Callable[..., common.Completed] = common.run
    exists: Callable[[Path], bool] = Path.exists
    read_text: Callable[[Path], str] = lambda p: p.read_text(encoding="utf-8-sig")
    listdir: Callable[[Path], list[str]] = lambda p: sorted(os.listdir(p)) if p.is_dir() else []
    env: dict | None = None
    free_gb: Callable[[Path], float] = common.free_gb
    netfx_release: Callable[[], int | None] = lambda: _registry_release()
    is_windows: bool = os.name == "nt"

    def getenv(self, name: str) -> str:
        return (os.environ if self.env is None else self.env).get(name, "")


def _registry_release() -> int | None:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, NETFX_KEY) as key:
            return int(winreg.QueryValueEx(key, "Release")[0])
    except (ImportError, OSError, ValueError):
        return None


def _engine_json(engine: Path, relative: str, probe: Probe) -> dict:
    try:
        return json.loads(probe.read_text(engine / relative))
    except (OSError, ValueError):
        return {}


def check_engine(pins: dict, engine: Path, probe: Probe, project: Path) -> list[Check]:
    want = pins["engine"]["version"]
    try:
        data = json.loads(probe.read_text(engine / "Engine" / "Build" / "Build.version"))
        have = f"{data['MajorVersion']}.{data['MinorVersion']}.{data['PatchVersion']}"
    except (OSError, ValueError, KeyError):
        return [Check("engine", "fail", f"no Unreal Engine at {engine}",
                      f"install UE {want} from the launcher or set {common.ENGINE_ENV}")]
    checks = [Check("engine", "ok" if have == want else "fail", f"UE {have} at {engine}",
                    "" if have == want else f"install UE {want}")]
    try:
        association = json.loads(probe.read_text(project)).get("EngineAssociation", "")
    except (OSError, ValueError):
        association = ""
    want_assoc = pins["engine"]["association"]
    checks.append(Check("uproject", "ok" if association == want_assoc else "fail",
                        f"EngineAssociation {association or '?'} (want {want_assoc})"))
    return checks


def _vs_installs(probe: Probe) -> list[dict]:
    if not probe.exists(VSWHERE):
        return []
    result = probe.run([str(VSWHERE), "-products", "*", "-all", "-format", "json", "-utf8"],
                       capture=True)
    try:
        return json.loads(result.stdout) if result.returncode == 0 else []
    except ValueError:
        return []


def cl_version(cl: Path, probe: Probe) -> str | None:
    """The toolset version of ``cl.exe`` (compiler 19.44.35229 -> 14.44.35229)."""
    result = probe.run([str(cl)], capture=True)
    match = re.search(r"Version 19\.(\d+)\.(\d+)", result.stderr + result.stdout)
    return f"14.{match.group(1)}.{match.group(2)}" if match else None


def check_msvc(pins: dict, engine: Path, probe: Probe) -> list[Check]:
    installs = _vs_installs(probe)
    want_vs = pins["visual_studio"]["min_version"]
    good_vs = [i for i in installs
               if version_tuple(i.get("installationVersion", "0")) >= version_tuple(want_vs)]
    if not good_vs:
        found = ", ".join(i.get("installationVersion", "?") for i in installs) or "none"
        return [Check("visual-studio", "fail", f"VS 2022 {want_vs}+ not found (found: {found})",
                      "install Visual Studio 2022 Build Tools with the C++ x64 workload")]
    checks = [Check("visual-studio", "ok",
                    ", ".join(f"{i.get('productId', '?').rsplit('.', 1)[-1]} "
                              f"{i.get('installationVersion')}" for i in good_vs))]
    sdk = _engine_json(engine, "Engine/Config/Windows/Windows_SDK.json", probe)
    banned = sdk.get("BannedVisualCppVersions", [])
    family, minimum = pins["msvc"]["family"], pins["msvc"]["min_version"]
    seen: list[str] = []
    for install in good_vs:
        tools = Path(install["installationPath"]) / "VC" / "Tools" / "MSVC"
        for folder in probe.listdir(tools):
            if not folder.startswith(family + "."):
                seen.append(folder)
                continue
            cl = tools / folder / "bin" / "Hostx64" / "x64" / "cl.exe"
            version = cl_version(cl, probe) if probe.exists(cl) else None
            seen.append(f"{folder} (cl {version or '?'})")
            if not version:
                continue
            if any(in_range(version, spec) for spec in banned):
                continue
            if version_tuple(version) >= version_tuple(minimum):
                return checks + [Check("msvc", "ok", f"MSVC {version} in {tools / folder}")]
    return checks + [Check(
        "msvc", "fail",
        f"no MSVC {family} at {minimum}+ outside the engine's banned list "
        f"(found: {', '.join(seen) or 'none'})",
        f"add the MSVC v143 {family} x64/x86 build tools in the Visual Studio Installer",
    )]


def check_windows_sdk(pins: dict, engine: Path, probe: Probe) -> list[Check]:
    want = pins["windows_sdk"]["version"]
    root = Path(pins["windows_sdk"]["root"])
    missing = [sub for sub in ("Include", "Lib") if not probe.exists(root / sub / want)]
    engine_main = _engine_json(engine, "Engine/Config/Windows/Windows_SDK.json", probe).get(
        "MainVersion", want)
    detail = f"Windows SDK {want} at {root}"
    if engine_main != want:
        return [Check("windows-sdk", "fail",
                      f"pin {want} differs from the engine's MainVersion {engine_main}",
                      "update unreal/Toolchain/toolchains.json")]
    if missing:
        return [Check("windows-sdk", "fail", f"{detail}: missing {', '.join(missing)}",
                      f"add the Windows 11 SDK {want} in the Visual Studio Installer")]
    return [Check("windows-sdk", "ok", detail)]


def check_netfx(pins: dict, probe: Probe) -> list[Check]:
    spec = pins["netfx"]
    release = probe.netfx_release()
    checks = []
    if release is None or release < spec["min_release"]:
        checks.append(Check("netfx-runtime", "fail",
                            f".NET Framework release {release} < {spec['min_release']}",
                            f"install .NET Framework {spec['runtime']}"))
    else:
        checks.append(Check("netfx-runtime", "ok",
                            f".NET Framework release {release} ({spec['runtime']}+)"))
    root = Path(spec["reference_root"])
    missing = [p for p in spec["targeting_packs"] if not probe.exists(root / p)]
    checks.append(Check(
        "netfx-targeting", "fail" if missing else "ok",
        f"targeting packs {', '.join(spec['targeting_packs'])}"
        + (f": missing {', '.join(missing)}" if missing else ""),
        "add the .NET Framework targeting packs in the Visual Studio Installer" if missing else "",
    ))
    return checks


def check_git_lfs(pins: dict, probe: Probe) -> list[Check]:
    want = pins["git_lfs"]["min_version"]
    result = probe.run(["git", "lfs", "version"], capture=True)
    match = re.search(r"git-lfs/(\d+\.\d+\.\d+)", result.stdout)
    if result.returncode != 0 or not match:
        return [Check("git-lfs", "fail", "git lfs not found", f"install git-lfs {want}+")]
    have = match.group(1)
    ok = version_tuple(have) >= version_tuple(want)
    return [Check("git-lfs", "ok" if ok else "fail", f"git-lfs {have} (want {want}+)",
                  "" if ok else f"update git-lfs to {want}+")]


def check_linux(pins: dict, engine: Path, probe: Probe) -> list[Check]:
    spec = pins["linux"]
    engine_main = _engine_json(engine, "Engine/Config/Linux/Linux_SDK.json", probe).get(
        "MainVersion", spec["sdk"])
    if engine_main != spec["sdk"]:
        return [Check("linux-toolchain", "fail",
                      f"pin {spec['sdk']} differs from the engine's {engine_main}",
                      "update unreal/Toolchain/toolchains.json")]
    root = probe.getenv(spec["env"]).strip()
    fix = (f"install the engine's Linux cross toolchain {spec['sdk']} and set "
           f"{spec['env']} to its folder")
    if not root:
        return [Check("linux-toolchain", "fail", f"{spec['env']} is not set", fix)]
    path = Path(root)
    clang = path / "x86_64-unknown-linux-gnu" / "bin" / "clang++.exe"
    if not probe.exists(clang):
        return [Check("linux-toolchain", "fail", f"no {clang}", fix)]
    if spec["sdk"] not in str(path):
        return [Check("linux-toolchain", "fail",
                      f"{spec['env']}={root} does not name {spec['sdk']}", fix)]
    return [Check("linux-toolchain", "ok", f"{spec['sdk']} at {root}")]


def check_disk(pins: dict, worktree: Path, probe: Probe) -> list[Check]:
    want = pins["disk"]["min_free_gb"]
    free = probe.free_gb(worktree)
    return [Check("disk", "ok" if free >= want else "fail", f"{free:.0f} GB free (want {want})",
                  "" if free >= want else "remove merged worktrees with worktree.py remove")]


def check_lock_dir(probe: Probe) -> list[Check]:
    folder = with_lock.lock_dir(probe.env)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        marker = folder / f".doctor-{os.getpid()}"
        marker.write_text("ok", encoding="utf-8")
        marker.unlink()
    except OSError as error:
        return [Check("lock-dir", "fail", f"{folder} not writable: {error}")]
    return [Check("lock-dir", "ok", str(folder))]


def diagnose(
    targets: Sequence[str] = ("win64", "linux"),
    *,
    probe: Probe | None = None,
    pins: dict | None = None,
    worktree: Path = common.REPO_ROOT,
) -> list[Check]:
    probe = probe or Probe()
    pins = pins or common.load_toolchains()
    engine = common.engine_root(probe.env)
    checks: list[Check] = []
    if not probe.is_windows:
        checks.append(Check("windows", "skip", "not Windows: engine and MSVC checks skipped"))
    else:
        checks += check_engine(pins, engine, probe, common.project_file(worktree))
        checks += check_msvc(pins, engine, probe)
        checks += check_windows_sdk(pins, engine, probe)
        checks += check_netfx(pins, probe)
        if "linux" in targets:
            checks += check_linux(pins, engine, probe)
        else:
            checks.append(Check("linux-toolchain", "skip", "not requested (--target win64)"))
    checks += check_git_lfs(pins, probe)
    checks += check_disk(pins, worktree, probe)
    checks += check_lock_dir(probe)
    return checks


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--target", choices=["all", "win64", "linux"], default="all")
    parser.add_argument("--json", action="store_true")
    options = parser.parse_args(argv)
    targets = ("win64", "linux") if options.target == "all" else (options.target,)
    checks = diagnose(targets)
    failed = [c for c in checks if c.status == "fail"]
    if options.json:
        print(json.dumps({"ok": not failed, "checks": [asdict(c) for c in checks]}, indent=1))
    else:
        for c in checks:
            print(f"{c.status.upper():5} {c.name:16} {c.detail}")
            if c.fix and c.status == "fail":
                print(f"{'':22}fix: {c.fix}")
        print("doctor: GREEN" if not failed else f"doctor: RED ({len(failed)} failing)")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
