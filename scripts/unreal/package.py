#!/usr/bin/env python3
"""Package, chunk, delta, smoke-test and keep the disk clean for the Unreal Verse.

Work package WP22 (docs/verse/unreal/work-packages.md). Every Unreal run goes
through the machine lock (``with_lock.py``); nothing here calls UBT or UAT
outside it.

    python scripts/unreal/package.py verify [--target all|win64|linux]
    python scripts/unreal/package.py build --platform win64 [--config Shipping]
    python scripts/unreal/package.py report --platform win64 [--archive DIR]
    python scripts/unreal/package.py chunks              # the ini block of the deck chunks
    python scripts/unreal/package.py pso --platform win64 --collected DIR
    python scripts/unreal/package.py full --stage DIR --version 4.2.0 --platform Win64 --out F
    python scripts/unreal/package.py delta --old OLD.tar --stage DIR --version 4.2.1 --out F
    python scripts/unreal/package.py apply --root DIR (--full F | --delta F) [--log F]
    python scripts/unreal/package.py cold-start --platform win64
    python scripts/unreal/package.py linux-smoke [--seconds 60]
    python scripts/unreal/package.py hygiene [--apply] [--worktrees C:/demo]

Outputs that are evidence (size report, cold-start JSON, delta apply log) go
to ``unreal/Verse/Saved/Harness/proof/WP22/<sub-task>/`` (work-packages 0.4).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tarfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dodaios.core import installer_update as verse_update
from scripts.unreal import _common as common
from scripts.unreal import with_lock

TOOLCHAIN_DIR = common.UNREAL_ROOT / "Toolchain"
CHUNKS_FILE = TOOLCHAIN_DIR / "chunks.json"
DDC_FILE = TOOLCHAIN_DIR / "ddc.json"
LINUX_SMOKE_DIR = common.REPO_ROOT / "packaging" / "linux" / "verse"
SMOKE_IMAGE = "dodaios-verse-smoke:1"

GB = 1_000_000_000
MB = 1_000_000


@dataclass(frozen=True)
class PlatformSpec:
    key: str  # command-line name
    ue: str  # UAT -platform
    staged: str  # folder BuildCookRun archives into
    launcher: str  # file the person starts
    cook: str  # cooked platform name


PLATFORMS: dict[str, PlatformSpec] = {
    "win64": PlatformSpec("win64", "Win64", "Windows", "Verse.exe", "Windows"),
    "linux": PlatformSpec("linux", "Linux", "Linux", "Verse.sh", "Linux"),
}
CONFIGS = ("Shipping", "Development")


def proof_dir(worktree: Path, sub_task: str) -> Path:
    return worktree / "unreal" / "Verse" / "Saved" / "Harness" / "proof" / "WP22" / sub_task


def archive_root(worktree: Path, config: str) -> Path:
    return worktree / "unreal" / "Verse" / "Saved" / "Package" / config


def staged_dir(worktree: Path, spec: PlatformSpec, config: str) -> Path:
    return archive_root(worktree, config) / spec.staged


def write_json(path: Path, data: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# 22.1 Toolchain pins and verify
# --------------------------------------------------------------------------- #
def load_chunks(path: Path = CHUNKS_FILE) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    problems = chunk_rule_problems(data)
    if problems:
        raise common.UnrealScriptError(f"{path}: {'; '.join(problems)}")
    return data


def chunk_rule_problems(data: Mapping[str, Any]) -> list[str]:
    problems: list[str] = []
    if data.get("schema") != "verse.chunks/1":
        problems.append("schema must be verse.chunks/1")
    chunks = list(data.get("chunks") or [])
    ids = [c.get("id") for c in chunks]
    if 0 not in ids:
        problems.append("chunk 0 (core) is required")
    if len(set(ids)) != len(ids):
        problems.append("chunk ids must be unique")
    names = [c.get("name") for c in chunks]
    if len(set(names)) != len(names):
        problems.append("chunk names must be unique")
    maps = [m for c in chunks for m in c.get("maps", [])]
    if len(set(maps)) != len(maps):
        problems.append("a map belongs to exactly one chunk")
    for path in maps:
        if not re.fullmatch(r"/Game/Verse/Decks/[A-Za-z]+/LV_[A-Za-z]+", path):
            problems.append(f"{path} is not a deck level (/Game/Verse/Decks/<Deck>/LV_<Deck>)")
    gate = data.get("size_gate") or {}
    for key in ("payload_max_bytes", "delta_typical_max_bytes"):
        if not isinstance(gate.get(key), int) or gate[key] <= 0:
            problems.append(f"size_gate.{key} must be a positive integer")
    return problems


def load_ddc(path: Path = DDC_FILE) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != "verse.ddc/1" or data.get("shared") is not False:
        raise common.UnrealScriptError(f"{path}: want schema verse.ddc/1 and shared false")
    if not 0 < int(data.get("cap_gb", 0)) <= 100:
        raise common.UnrealScriptError(f"{path}: cap_gb must be between 1 and 100")
    return data


def ddc_args(ddc: Mapping[str, Any]) -> list[str]:
    return [f"-ddc={ddc['graph']}"]


def ddc_env(ddc: Mapping[str, Any], base: Mapping[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if base is None else base)
    env[ddc["local_path_env"]] = ddc["local_path"]
    return env


@dataclass
class VerifyProbe:
    run: Callable[..., common.Completed] = common.run
    exists: Callable[[Path], bool] = Path.exists
    which: Callable[[str], str | None] = shutil.which


def verify_packaging(
    targets: Sequence[str], *, engine: Path, probe: VerifyProbe | None = None
) -> list[dict]:
    """Packaging checks on top of ``doctor.py``: pins, Linux engine part, Docker."""
    probe = probe or VerifyProbe()
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str, fix: str = "") -> None:
        checks.append(
            {
                "name": name,
                "status": "ok" if ok else "fail",
                "detail": detail,
                "fix": "" if ok else fix,
            }
        )

    try:
        chunks = load_chunks()
        add("chunks", True, f"{len(chunks['chunks'])} chunks in {CHUNKS_FILE.name}")
    except (OSError, ValueError, common.UnrealScriptError) as exc:
        add("chunks", False, str(exc), "fix unreal/Toolchain/chunks.json")
    try:
        ddc = load_ddc()
        add("ddc", True, f"{ddc['graph']}, cap {ddc['cap_gb']} GB, {ddc['local_path']}")
    except (OSError, ValueError, KeyError, common.UnrealScriptError) as exc:
        add("ddc", False, str(exc), "fix unreal/Toolchain/ddc.json")
    if "linux" in targets:
        marker = engine / "Engine" / "Binaries" / "Linux" / "UnrealGame.target"
        add(
            "linux-engine",
            probe.exists(marker),
            f"{marker}",
            "add the Linux target platform to the engine install once (launcher: UE 5.7, "
            "Options, Target Platforms, Linux)",
        )
        docker = probe.which("docker")
        ok = (
            bool(docker)
            and probe.run(
                [docker or "docker", "info", "--format", "{{.OSType}}"], capture=True
            ).returncode
            == 0
        )
        add(
            "docker",
            ok,
            docker or "docker not on PATH",
            "start Docker Desktop with Linux containers (the Linux smoke runs in one)",
        )
    return checks


def cmd_verify(options: argparse.Namespace) -> int:
    from scripts.unreal import doctor

    targets = ("win64", "linux") if options.target == "all" else (options.target,)
    checks = [
        {"name": c.name, "status": c.status, "detail": c.detail, "fix": c.fix}
        for c in doctor.diagnose(targets)
    ]
    checks += verify_packaging(targets, engine=common.engine_root())
    for check in checks:
        common.log(f"{check['status'].upper():5} {check['name']:16} {check['detail']}")
        if check["status"] == "fail" and check["fix"]:
            common.log(f"{'':22}fix: {check['fix']}")
    failed = [c for c in checks if c["status"] == "fail"]
    common.log("verify: GREEN" if not failed else f"verify: RED ({len(failed)} failing)")
    return 0 if not failed else 1


# --------------------------------------------------------------------------- #
# 22.2 BuildCookRun, 22.3 chunks and PSO cache
# --------------------------------------------------------------------------- #
def chunk_ini_block(chunks: Mapping[str, Any]) -> str:
    """The config lines that put every deck level in its own IoStore chunk.

    ``Config/DefaultGame.ini`` belongs to the integration owner, so this block
    is what WP22's contract change request asks to merge.
    """
    lines = [
        "[/Script/UnrealEd.ProjectPackagingSettings]",
        "bGenerateChunks=True",
        "bShareMaterialShaderCode=True",
        "bSharedMaterialNativeLibraries=True",
        "",
        "[/Script/Engine.AssetManagerSettings]",
        '+PrimaryAssetTypesToScan=(PrimaryAssetType="Map",AssetBaseClass=/Script/Engine.World,'
        'bHasBlueprintClasses=False,bIsEditorOnly=True,Directories=((Path="/Game/Verse/Decks")),'
        "Rules=(Priority=-1,ChunkId=-1,bApplyRecursively=True,CookRule=Unknown))",
    ]
    for chunk in sorted(chunks["chunks"], key=lambda c: c["id"]):
        for path in chunk.get("maps", []):
            name = path.rsplit("/", 1)[-1]
            priority = 10 + chunk["id"]
            lines.append(
                f'+PrimaryAssetRules=(PrimaryAssetId="Map:{name}",Rules=(Priority={priority},'
                f"ChunkId={chunk['id']},bApplyRecursively=True,CookRule=AlwaysCook))"
            )
    return "\n".join(lines) + "\n"


def missing_chunk_config(project_dir: Path, chunks: Mapping[str, Any]) -> list[str]:
    """Lines of :func:`chunk_ini_block` that ``DefaultGame.ini`` does not have yet."""
    try:
        text = (project_dir / "Config" / "DefaultGame.ini").read_text(encoding="utf-8")
    except OSError:
        text = ""
    have = {line.strip() for line in text.splitlines()}
    wanted = [line for line in chunk_ini_block(chunks).splitlines() if line and "=" in line]
    return [line for line in wanted if line not in have]


def buildcookrun_command(
    spec: PlatformSpec,
    config: str,
    *,
    engine: Path,
    project: Path,
    archive: Path,
    ddc: Mapping[str, Any] | None = None,
) -> list[str]:
    command = [
        str(common.run_uat_bat(engine)),
        "BuildCookRun",
        f"-project={project}",
        "-target=Verse",
        f"-platform={spec.ue}",
        f"-clientconfig={config}",
        "-build",
        "-cook",
        "-stage",
        "-pak",
        "-iostore",
        "-compressed",
        "-manifests",
        "-archive",
        f"-archivedirectory={archive}",
        "-nodebuginfo",
        "-unattended",
        "-utf8output",
        "-nocompileeditor",
        "-NoP4",
        f"-ubtargs=-MaxParallelActions={common.MAX_PARALLEL_ACTIONS}",
    ]
    if spec.key == "win64":
        command.append("-prereqs")
    if ddc:
        command += ddc_args(ddc)
    return command


def editor_build_command(engine: Path, project: Path) -> list[str]:
    return [
        str(common.build_bat(engine)),
        "VerseEditor",
        "Win64",
        "Development",
        f"-Project={project}",
        "-WaitMutex",
        "-NoHotReloadFromIDE",
        f"-MaxParallelActions={common.MAX_PARALLEL_ACTIONS}",
    ]


_HARNESS_MARKERS = (b"VerseHarness", "VerseHarness".encode("utf-16-le"))


def harness_problems(worktree: Path, spec: PlatformSpec, staged: Path | None) -> list[str]:
    """Where the harness shows up in a Shipping build; empty means it is absent."""
    problems: list[str] = []
    source = worktree / "unreal" / "Verse" / "Source"
    try:
        target_cs = (source / "Verse.Target.cs").read_text(encoding="utf-8")
    except OSError:
        target_cs = ""
    code = "\n".join(line.split("//", 1)[0] for line in target_cs.splitlines())
    if "VerseHarness" in code:
        problems.append("Verse.Target.cs lists VerseHarness")
    intermediate = worktree / "unreal" / "Verse" / "Intermediate" / "Build" / spec.ue
    if intermediate.is_dir():
        for folder in intermediate.rglob("VerseHarness"):
            parts = {p.lower() for p in folder.parts}
            if folder.is_dir() and "shipping" in parts and "verseeditor" not in parts:
                problems.append(f"Shipping objects of VerseHarness at {folder}")
    if staged is not None and staged.is_dir():
        for binary in staged.rglob("*"):
            if not binary.is_file() or binary.suffix.lower() in {".pak", ".utoc", ".ucas"}:
                continue
            if binary.suffix.lower() not in {".exe", ".dll", ".so", ""}:
                continue
            data = binary.read_bytes()
            if any(marker in data for marker in _HARNESS_MARKERS):
                problems.append(f"{binary.relative_to(staged).as_posix()} carries VerseHarness")
    return problems


_PAK_NAME = re.compile(
    r"^(?:pakchunk(?P<id>\d+)(?:optional)?(?:s\d+)?-[A-Za-z0-9]+|(?P<global>global))"
    r"\.(?:pak|utoc|ucas|sig)$",
    re.IGNORECASE,
)


def size_report(staged: Path, chunks: Mapping[str, Any], *, platform: str) -> dict[str, Any]:
    """Bytes per deck chunk plus binaries; the size gate of A22.1 for the full payload."""
    names = {c["id"]: c["name"] for c in chunks["chunks"]}
    groups: dict[str, dict[str, Any]] = {}

    def add(group: str, path: Path) -> None:
        entry = groups.setdefault(group, {"bytes": 0, "files": 0})
        entry["bytes"] += path.stat().st_size
        entry["files"] += 1

    unknown: list[str] = []
    pso = False
    for path in sorted(p for p in staged.rglob("*") if p.is_file()):
        match = _PAK_NAME.match(path.name)
        if match and match.group("global"):
            add("global", path)
        elif match:
            chunk_id = int(match.group("id"))
            if chunk_id not in names:
                unknown.append(path.name)
            add(names.get(chunk_id, f"chunk{chunk_id}"), path)
        else:
            if path.suffix.lower() == ".spc" or "PipelineCaches" in path.parts:
                pso = True
            add("binaries", path)
    total = sum(g["bytes"] for g in groups.values())
    cap = chunks["size_gate"]["payload_max_bytes"]
    decks = [c["name"] for c in chunks["chunks"] if c.get("maps")]
    return {
        "schema": "verse.size-report/1",
        "platform": platform,
        "chunks": groups,
        "total_bytes": total,
        "payload_max_bytes": cap,
        "within_payload_cap": total <= cap,
        "deck_chunks_present": sorted(d for d in decks if d in groups),
        "deck_chunks_missing": sorted(d for d in decks if d not in groups),
        "unknown_chunk_files": unknown,
        "pso_cache_shipped": pso,
    }


def pso_expand_command(
    engine: Path, project: Path, collected: Sequence[Path], shk: Sequence[Path], out: Path
) -> list[str]:
    """``ShaderPipelineCacheTools expand``: recorded PSOs + cook shader keys -> ``.spc``."""
    return [
        str(common.editor_cmd(engine)),
        str(project),
        "-run=ShaderPipelineCacheTools",
        "expand",
        *(str(p) for p in collected),
        *(str(p) for p in shk),
        str(out),
        "-unattended",
        "-nullrhi",
        "-nosplash",
        "-NoP4",
        "-stdout",
    ]


def pso_paths(worktree: Path, spec: PlatformSpec) -> tuple[Path, Path]:
    """(cooked shader key folder, the engine-required shipped cache folder)."""
    project_dir = worktree / "unreal" / "Verse"
    shk = project_dir / "Saved" / "Cooked" / spec.cook / "Verse" / "Metadata" / "PipelineCaches"
    shipped = project_dir / "Build" / spec.staged / "PipelineCaches"
    return shk, shipped


def cmd_build(options: argparse.Namespace) -> int:
    spec = PLATFORMS[options.platform]
    worktree = options.worktree.resolve()
    engine = common.engine_root()
    project = common.project_file(worktree)
    archive = archive_root(worktree, options.config)
    chunks = load_chunks()
    missing = missing_chunk_config(project.parent, chunks)
    if missing:
        common.log(
            f"chunks: DefaultGame.ini lacks {len(missing)} chunk lines; every deck lands "
            "in chunk 0 until the integration owner merges `package.py chunks`"
        )
        if options.require_chunks:
            return 1
    if spec.key == "linux" and not os.environ.get("LINUX_MULTIARCH_ROOT", "").strip():
        return common.exit_with(
            common.UnrealScriptError(
                "LINUX_MULTIARCH_ROOT is not set (package.py verify --target linux)"
            )
        )
    common.require_free_disk(worktree)
    try:
        ddc = load_ddc()
    except (OSError, ValueError, common.UnrealScriptError) as exc:
        return common.exit_with(exc)
    env = ddc_env(ddc)
    steps = []
    if not options.skip_editor:
        steps.append(("build editor", editor_build_command(engine, project)))
    steps.append(
        (
            f"package {spec.key} {options.config}",
            buildcookrun_command(
                spec, options.config, engine=engine, project=project, archive=archive, ddc=ddc
            ),
        )
    )
    for label, command in steps:
        common.log(f"{label}: {' '.join(command)}")
        started = time.monotonic()
        code = with_lock.run_locked(
            command, label=f"{label} ({worktree.name})", cwd=worktree, env=env
        )
        common.log(f"{label}: exit {code} in {(time.monotonic() - started) / 60:.1f} min")
        if code != 0:
            return code
    staged = staged_dir(worktree, spec, options.config)
    out = proof_dir(worktree, "22.2")
    problems = harness_problems(worktree, spec, staged) if options.config == "Shipping" else []
    report = size_report(staged, chunks, platform=spec.ue)
    report["harness_problems"] = problems
    path = write_json(out / f"size-{spec.key}-{options.config}.json", report)
    common.log(f"size report: {path} total {report['total_bytes'] / MB:.1f} MB")
    for problem in problems:
        common.log(f"PROBLEM {problem}")
    return 0 if not problems and report["within_payload_cap"] else 1


def cmd_report(options: argparse.Namespace) -> int:
    spec = PLATFORMS[options.platform]
    worktree = options.worktree.resolve()
    staged = options.archive or staged_dir(worktree, spec, options.config)
    report = size_report(staged, load_chunks(), platform=spec.ue)
    report["harness_problems"] = harness_problems(worktree, spec, staged)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["within_payload_cap"] and not report["harness_problems"] else 1


def cmd_chunks(_options: argparse.Namespace) -> int:
    print(chunk_ini_block(load_chunks()), end="")
    return 0


def cmd_pso(options: argparse.Namespace) -> int:
    spec = PLATFORMS[options.platform]
    worktree = options.worktree.resolve()
    shk_dir, shipped = pso_paths(worktree, spec)
    collected = sorted(Path(options.collected).glob("*.upipelinecache"))
    shk = sorted(shk_dir.glob("*.shk"))
    if not collected or not shk:
        return common.exit_with(
            common.UnrealScriptError(
                f"need recorded *.upipelinecache in {options.collected} "
                f"(play a build with -logPSO) and cooked *.shk in {shk_dir}"
            )
        )
    out = shipped / f"Verse_{spec.ue}.spc"
    out.parent.mkdir(parents=True, exist_ok=True)
    command = pso_expand_command(
        common.engine_root(), common.project_file(worktree), collected, shk, out
    )
    return with_lock.run_locked(command, label=f"pso {spec.key}", cwd=worktree)


# --------------------------------------------------------------------------- #
# 22.4 Full payloads and deltas
# --------------------------------------------------------------------------- #
def _add_bytes(archive: tarfile.TarFile, name: str, data: bytes) -> None:
    import io

    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mtime = 0
    info.mode = 0o644
    archive.addfile(info, io.BytesIO(data))


def _add_file(archive: tarfile.TarFile, name: str, path: Path) -> None:
    info = tarfile.TarInfo(name)
    info.size = path.stat().st_size
    info.mtime = 0
    info.mode = 0o755 if os.access(path, os.X_OK) and path.suffix in {"", ".sh"} else 0o644
    with path.open("rb") as handle:
        archive.addfile(info, handle)


def _json_bytes(data: Any) -> bytes:
    return (json.dumps(data, indent=2, sort_keys=True) + "\n").encode("utf-8")


def make_full(stage: Path, *, version: str, platform: str, out: Path) -> dict[str, Any]:
    """A full payload tar of a staged build (uncompressed: IoStore is compressed already)."""
    tree = verse_update.build_verse_tree(stage, version=version, platform=platform)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(out, "w", format=tarfile.PAX_FORMAT) as archive:
        _add_bytes(archive, verse_update.VERSE_TREE_FILE, _json_bytes(tree))
        for rel in tree["files"]:
            _add_file(archive, f"files/{rel}", stage / rel)
    return {
        "kind": "full",
        "version": tree["version"],
        "platform": platform,
        "files": len(tree["files"]),
        "bytes": out.stat().st_size,
        "tree": tree,
    }


def read_payload_tree(source: Path) -> dict[str, Any]:
    """The tree of a previous version: a full payload tar or an installed version folder."""
    if source.is_dir():
        return json.loads((source / verse_update.VERSE_TREE_FILE).read_text(encoding="utf-8"))
    with tarfile.open(source, "r:") as archive:
        member = archive.getmember(verse_update.VERSE_TREE_FILE)
        handle = archive.extractfile(member)
        if handle is None:
            raise common.UnrealScriptError(f"{source} has no {verse_update.VERSE_TREE_FILE}")
        return json.loads(handle.read().decode("utf-8"))


def make_delta(
    old_tree: Mapping[str, Any],
    stage: Path,
    *,
    version: str,
    out: Path,
    typical_max_bytes: int = 300 * MB,
) -> dict[str, Any]:
    """A delta tar from ``old_tree`` to the staged build: only changed or new files."""
    platform = str(old_tree["platform"])
    tree = verse_update.build_verse_tree(stage, version=version, platform=platform)
    old_files = old_tree["files"]
    changed = [
        rel
        for rel, entry in tree["files"].items()
        if old_files.get(rel, {}).get("sha256") != entry["sha256"]
    ]
    reuse = [rel for rel in tree["files"] if rel not in set(changed)]
    removed = sorted(set(old_files) - set(tree["files"]))
    header = {
        "schema": verse_update.VERSE_DELTA_SCHEMA,
        "platform": platform,
        "from": old_tree["version"],
        "to": tree["version"],
        "from_tree_sha256": verse_update.verse_tree_digest(dict(old_tree)),
        "files": changed,
        "reuse": reuse,
        "removed": removed,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(out, "w", format=tarfile.PAX_FORMAT) as archive:
        _add_bytes(archive, verse_update.VERSE_DELTA_FILE, _json_bytes(header))
        _add_bytes(archive, verse_update.VERSE_TREE_FILE, _json_bytes(tree))
        for rel in changed:
            _add_file(archive, f"files/{rel}", stage / rel)
    size = out.stat().st_size
    return {
        "kind": "delta",
        "from": header["from"],
        "to": header["to"],
        "platform": platform,
        "changed": len(changed),
        "reused": len(reuse),
        "removed": len(removed),
        "bytes": size,
        "typical_max_bytes": typical_max_bytes,
        "within_typical": size <= typical_max_bytes,
        "changed_files": changed,
    }


def cmd_full(options: argparse.Namespace) -> int:
    result = make_full(
        options.stage, version=options.version, platform=options.platform, out=options.out
    )
    result.pop("tree")
    print(json.dumps(result, indent=2))
    return 0


def cmd_delta(options: argparse.Namespace) -> int:
    gate = load_chunks()["size_gate"]["delta_typical_max_bytes"]
    result = make_delta(
        read_payload_tree(options.old),
        options.stage,
        version=options.version,
        out=options.out,
        typical_max_bytes=gate,
    )
    print(json.dumps(result, indent=2))
    if not result["within_typical"]:
        common.log(
            f"delta is {result['bytes'] / MB:.0f} MB, over the typical "
            f"{gate / MB:.0f} MB budget (A22.1)"
        )
    return 0


def cmd_apply(options: argparse.Namespace) -> int:
    root = options.root
    started = time.monotonic()
    entry: dict[str, Any] = {"root": str(root), "before": verse_update.verse_current(root)}
    try:
        if options.full:
            entry["result"] = verse_update.install_verse_full(root, options.full)
        else:
            entry["result"] = verse_update.apply_verse_delta(root, options.delta)
        entry["status"] = "applied"
    except verse_update.VerseUpdateError as exc:
        entry["status"] = "rolled_back"
        entry["error"] = str(exc)
    entry["after"] = verse_update.verse_current(root)
    after = entry["after"]
    entry["verify_problems"] = (
        verse_update.verify_verse_tree(verse_update.verse_version_dir(root, after["version"]))
        if after
        else ["nothing installed"]
    )
    entry["seconds"] = round(time.monotonic() - started, 3)
    if options.log:
        with Path(options.log).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
    print(json.dumps(entry, indent=2, sort_keys=True))
    return 0 if entry["status"] == "applied" and not entry["verify_problems"] else 1


# --------------------------------------------------------------------------- #
# A22.2 Cold start
# --------------------------------------------------------------------------- #
FIRST_FRAME = re.compile(r"VerseSmoke: (?:first frame|stage boot OK)")


def wait_for_marker(
    log_path: Path,
    pattern: re.Pattern[str],
    *,
    timeout_s: float,
    alive: Callable[[], bool],
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> float | None:
    """Seconds until ``pattern`` appears in ``log_path``; ``None`` on timeout or exit."""
    started = clock()
    while clock() - started < timeout_s:
        try:
            if pattern.search(log_path.read_text(encoding="utf-8", errors="replace")):
                return clock() - started
        except OSError:
            pass
        if not alive():
            return None
        sleep(0.05)
    return None


def cmd_cold_start(options: argparse.Namespace) -> int:
    spec = PLATFORMS[options.platform]
    worktree = options.worktree.resolve()
    staged = options.archive or staged_dir(worktree, spec, options.config)
    exe = staged / spec.launcher
    if not exe.is_file():
        return common.exit_with(common.UnrealScriptError(f"no packaged game at {exe}"))
    out = proof_dir(worktree, "22.3")
    log_path = out / f"cold-start-{common.run_stamp()}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        str(exe),
        "-windowed",
        "-ResX=1280",
        "-ResY=720",
        "-WinX=-32000",
        "-WinY=-32000",
        "-VerseSmoke=boot",
        "-unattended",
        "-log",
        f"-abslog={log_path}",
    ]
    token = secrets.token_hex(16)
    with with_lock.MachineLock(f"cold start ({worktree.name})", command):
        process = subprocess.Popen(
            command, cwd=str(staged), env=dict(os.environ, DODAIOS_VERSE_TOKEN=token)
        )
        try:
            seconds = wait_for_marker(
                log_path,
                FIRST_FRAME,
                timeout_s=options.timeout,
                alive=lambda: process.poll() is None,
            )
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
    report = size_report(staged, load_chunks(), platform=spec.ue)
    result = {
        "schema": "verse.cold-start/1",
        "platform": spec.ue,
        "config": options.config,
        "seconds_to_first_frame": None if seconds is None else round(seconds, 3),
        "budget_s": 8.0,
        "pass": seconds is not None and seconds <= 8.0,
        "pso_cache_shipped": report["pso_cache_shipped"],
        "log": str(log_path),
    }
    path = write_json(out / f"cold-start-{spec.key}.json", result)
    common.log(f"cold start: {result['seconds_to_first_frame']} s ({path})")
    return 0 if result["pass"] else 1


# --------------------------------------------------------------------------- #
# 22.7 Linux smoke in a container
# --------------------------------------------------------------------------- #
def docker_smoke_command(
    staged: Path,
    out: Path,
    *,
    seconds: int,
    gpu: bool,
    image: str = SMOKE_IMAGE,
    name: str | None = None,
) -> list[str]:
    command = [
        "docker",
        "run",
        "--rm",
        "--name",
        name or f"verse-smoke-{secrets.token_hex(4)}",
        "--network",
        "none",
        "-v",
        f"{staged}:/verse:ro",
        "-v",
        f"{LINUX_SMOKE_DIR}:/smoke:ro",
        "-v",
        f"{out}:/out",
    ]
    if gpu:
        command += ["--gpus", "all", "-e", "NVIDIA_DRIVER_CAPABILITIES=all"]
    command += [image, "bash", "/smoke/linux_smoke.sh", str(seconds), "gpu" if gpu else "nogpu"]
    return command


def docker_gpu_available(run: Callable[..., common.Completed] = common.run) -> bool:
    result = run(["docker", "info", "--format", "{{json .Runtimes}}"], capture=True)
    return result.returncode == 0 and "nvidia" in result.stdout


def evaluate_linux_smoke(out: Path) -> dict[str, Any]:
    """Read the container's ``result.json`` and the logs it wrote."""
    from scripts.unreal import test as automation

    try:
        result = json.loads((out / "result.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"pass": False, "problems": ["the container wrote no result.json"]}
    problems = list(result.get("problems") or [])
    for log_name in ("nullrhi.log", "vulkan.log"):
        problems += [f"{log_name}: {line}" for line in automation.scan_log(out / log_name)]
    result["problems"] = problems
    result["pass"] = bool(result.get("server_ok")) and not problems
    return result


def cmd_linux_smoke(options: argparse.Namespace) -> int:
    worktree = options.worktree.resolve()
    staged = options.archive or staged_dir(worktree, PLATFORMS["linux"], options.config)
    if not (staged / "Verse.sh").is_file():
        return common.exit_with(common.UnrealScriptError(f"no packaged Linux game at {staged}"))
    out = proof_dir(worktree, "22.7") / common.run_stamp()
    out.mkdir(parents=True, exist_ok=True)
    build = [
        "docker",
        "build",
        "-t",
        SMOKE_IMAGE,
        "-f",
        str(LINUX_SMOKE_DIR / "smoke.Dockerfile"),
        str(LINUX_SMOKE_DIR),
    ]
    if common.run(build).returncode != 0:
        return common.exit_with(common.UnrealScriptError("docker build of the smoke image failed"))
    command = docker_smoke_command(staged, out, seconds=options.seconds, gpu=docker_gpu_available())
    code = with_lock.run_locked(command, label="linux smoke", cwd=worktree)
    result = evaluate_linux_smoke(out)
    result["exit_code"] = code
    write_json(out / "summary.json", result)
    common.log("linux smoke: PASS" if result["pass"] else f"linux smoke: FAIL {result['problems']}")
    return 0 if result["pass"] and code == 0 else 1


# --------------------------------------------------------------------------- #
# 22.9 Disk hygiene
# --------------------------------------------------------------------------- #
def folder_bytes(folder: Path) -> int:
    total = 0
    for path in folder.rglob("*"):
        try:
            if path.is_file() and not path.is_symlink():
                total += path.stat().st_size
        except OSError:
            continue
    return total


def newest_mtime(folder: Path) -> float:
    """Newest file write below ``folder`` (folders themselves do not count)."""
    newest = 0.0
    for path in folder.rglob("*"):
        try:
            if path.is_file():
                newest = max(newest, path.stat().st_mtime)
        except OSError:
            continue
    return newest


@dataclass
class HygienePlan:
    ddc_bytes: int = 0
    ddc_cap_bytes: int = 0
    ddc_prune: list[Path] = field(default_factory=list)
    intermediate_prune: list[Path] = field(default_factory=list)
    free_gb: float = 0.0
    alert: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "ddc_bytes": self.ddc_bytes,
            "ddc_cap_bytes": self.ddc_cap_bytes,
            "ddc_prune_files": len(self.ddc_prune),
            "intermediate_prune": [str(p) for p in self.intermediate_prune],
            "free_gb": round(self.free_gb, 1),
            "alert": self.alert,
        }


def plan_ddc_prune(ddc_dir: Path, cap_bytes: int) -> tuple[int, list[Path]]:
    """Oldest-first files of a file-system DDC to delete until it fits ``cap_bytes``."""
    if not ddc_dir.is_dir():
        return 0, []
    files = []
    for path in ddc_dir.rglob("*"):
        try:
            if path.is_file() and not path.is_symlink():
                stat = path.stat()
                files.append((max(stat.st_atime, stat.st_mtime), stat.st_size, path))
        except OSError:
            continue
    total = sum(size for _, size, _ in files)
    prune: list[Path] = []
    excess = total - cap_bytes
    for _, size, path in sorted(files):
        if excess <= 0:
            break
        prune.append(path)
        excess -= size
    return total, prune


def plan_intermediate_prune(worktrees_root: Path, *, max_age_days: float, now: float) -> list[Path]:
    """``unreal/Verse/Intermediate`` folders of worktrees untouched for ``max_age_days``."""
    found: list[Path] = []
    if not worktrees_root.is_dir():
        return found
    for worktree in sorted(p for p in worktrees_root.iterdir() if p.is_dir()):
        for intermediate in (worktree / "unreal" / "Verse" / "Intermediate",):
            if intermediate.is_dir() and not intermediate.is_symlink():
                if now - newest_mtime(intermediate) > max_age_days * 86400:
                    found.append(intermediate)
    return found


def plan_hygiene(
    ddc: Mapping[str, Any],
    *,
    worktrees_root: Path,
    now: float | None = None,
    free_gb: Callable[[Path], float] = common.free_gb,
) -> HygienePlan:
    current = time.time() if now is None else now
    cap = int(ddc["cap_gb"]) * GB
    total, prune = plan_ddc_prune(Path(ddc["local_path"]), cap)
    zen = Path(ddc.get("zen_data_path", ""))
    if ddc.get("zen_data_path") and zen.is_dir():
        total += folder_bytes(zen)
    free = free_gb(worktrees_root)
    return HygienePlan(
        ddc_bytes=total,
        ddc_cap_bytes=cap,
        ddc_prune=prune,
        intermediate_prune=plan_intermediate_prune(
            worktrees_root, max_age_days=float(ddc["intermediate_max_age_days"]), now=current
        ),
        free_gb=free,
        alert=free < float(ddc["alert_free_gb"]),
    )


def apply_hygiene(
    plan: HygienePlan,
    *,
    remove_file: Callable[[Path], None] = Path.unlink,
    remove_tree: Callable[[Path], None] = shutil.rmtree,
) -> int:
    removed = 0
    for path in plan.ddc_prune:
        try:
            remove_file(path)
            removed += 1
        except OSError:
            continue
    for folder in plan.intermediate_prune:
        remove_tree(folder)
        removed += 1
    return removed


def cmd_hygiene(options: argparse.Namespace) -> int:
    ddc = load_ddc()
    plan = plan_hygiene(ddc, worktrees_root=options.worktrees)
    summary = plan.as_dict()
    if options.apply:
        # The lock guarantees no build, cook or editor is writing while we prune.
        with with_lock.MachineLock("disk hygiene", "package.py hygiene --apply"):
            summary["removed"] = apply_hygiene(plan)
    print(json.dumps(summary, indent=2))
    if plan.ddc_bytes > plan.ddc_cap_bytes and not plan.ddc_prune:
        common.log("DDC over its cap in the Zen store: run the Zen server's gc")
    if plan.alert:
        common.log(
            f"ALERT only {plan.free_gb:.0f} GB free (want {ddc['alert_free_gb']}); "
            "remove merged worktrees (worktree.py remove)"
        )
        return 3
    return 0


# --------------------------------------------------------------------------- #
def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = top.add_subparsers(dest="command", required=True)

    def with_worktree(p: argparse.ArgumentParser) -> argparse.ArgumentParser:
        p.add_argument("--worktree", type=Path, default=common.REPO_ROOT)
        return p

    p = with_worktree(sub.add_parser("verify", help="toolchain and packaging prerequisites"))
    p.add_argument("--target", choices=["all", "win64", "linux"], default="all")
    p.set_defaults(func=cmd_verify)

    for name, func in (
        ("build", cmd_build),
        ("report", cmd_report),
        ("cold-start", cmd_cold_start),
    ):
        p = with_worktree(sub.add_parser(name))
        p.add_argument("--platform", choices=sorted(PLATFORMS), required=True)
        p.add_argument("--config", choices=CONFIGS, default="Shipping")
        if name == "build":
            p.add_argument("--skip-editor", action="store_true")
            p.add_argument("--require-chunks", action="store_true")
        else:
            p.add_argument("--archive", type=Path)
        if name == "cold-start":
            p.add_argument("--timeout", type=float, default=60.0)
        p.set_defaults(func=func)

    sub.add_parser("chunks", help="config block of the deck chunks").set_defaults(func=cmd_chunks)

    p = with_worktree(sub.add_parser("pso", help="expand the shipped PSO cache"))
    p.add_argument("--platform", choices=sorted(PLATFORMS), required=True)
    p.add_argument("--collected", type=Path, required=True)
    p.set_defaults(func=cmd_pso)

    p = sub.add_parser("full", help="full payload tar of a staged build")
    p.add_argument("--stage", type=Path, required=True)
    p.add_argument("--version", required=True)
    p.add_argument("--platform", choices=["Win64", "Linux"], required=True)
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(func=cmd_full)

    p = sub.add_parser("delta", help="delta tar from a previous payload to a staged build")
    p.add_argument("--old", type=Path, required=True)
    p.add_argument("--stage", type=Path, required=True)
    p.add_argument("--version", required=True)
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(func=cmd_delta)

    p = sub.add_parser("apply", help="install a full payload or apply a delta")
    p.add_argument("--root", type=Path, required=True)
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--full", type=Path)
    group.add_argument("--delta", type=Path)
    p.add_argument("--log", type=Path)
    p.set_defaults(func=cmd_apply)

    p = with_worktree(sub.add_parser("linux-smoke", help="container smoke of the Linux build"))
    p.add_argument("--config", choices=CONFIGS, default="Development")
    p.add_argument("--archive", type=Path)
    p.add_argument("--seconds", type=int, default=60)
    p.set_defaults(func=cmd_linux_smoke)

    p = sub.add_parser("hygiene", help="DDC cap, Intermediate pruning, free-space alert")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--worktrees", type=Path, default=Path("C:/demo"))
    p.set_defaults(func=cmd_hygiene)
    return top


def main(argv: Sequence[str] | None = None) -> int:
    options = parser().parse_args(argv)
    try:
        return int(options.func(options))
    except (common.UnrealScriptError, verse_update.VerseUpdateError) as error:
        return common.exit_with(error)


if __name__ == "__main__":
    sys.exit(main())
