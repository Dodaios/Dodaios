"""Capability probe (17.4, architecture 1.1): can this machine run the Verse?

Windows: a hardware D3D12 adapter with shader model 6 and at least 6 GB of
dedicated VRAM. Linux: a Vulkan 1.3 device that is not a CPU device. No
such device means ``unsupported``; the rest of the app is untouched.

The GPU check runs in a short-lived child process (``python -m
dodaios.verse_host.probe``) so a driver fault cannot take the app down and
no D3D12 device lives in the app process. Results are cached per run.

Install check: the first existing ``Verse`` executable of
:func:`candidate_executables` (``DODAIOS_VERSE_EXE``, the installed build
under ``<DATA_DIR>/verse/build`` that the on-demand download writes
(``install_port``), a dev staged build under ``unreal/Verse/Saved/StagedBuilds``).
The installer and app updates never carry the Verse, so a fresh install is
``not_installed`` until the user downloads it.

``DODAIOS_VERSE_PROBE=pass`` or ``=fail`` overrides the GPU check (tests,
CI runners without a GPU).
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .env import getenv

MIN_VRAM_MB = 6 * 1024
PROBE_TIMEOUT_S = 20.0


@dataclass
class GpuReport:
    ok: bool
    api: str = ""
    adapter: str = ""
    vram_mb: int = 0
    shader_model: str = ""
    reason: str = ""
    adapters: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------- Windows


def _probe_d3d12() -> GpuReport:  # pragma: no cover - needs a Windows GPU
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", ctypes.c_uint32),
            ("Data2", ctypes.c_uint16),
            ("Data3", ctypes.c_uint16),
            ("Data4", ctypes.c_ubyte * 8),
        ]

    def guid(text: str) -> GUID:
        import uuid

        u = uuid.UUID(text)
        g = GUID()
        g.Data1, g.Data2, g.Data3 = u.fields[0], u.fields[1], u.fields[2]
        g.Data4[:] = list(u.bytes[8:])
        return g

    class DXGI_ADAPTER_DESC1(ctypes.Structure):  # noqa: N801
        _fields_ = [
            ("Description", wintypes.WCHAR * 128),
            ("VendorId", wintypes.UINT),
            ("DeviceId", wintypes.UINT),
            ("SubSysId", wintypes.UINT),
            ("Revision", wintypes.UINT),
            ("DedicatedVideoMemory", ctypes.c_size_t),
            ("DedicatedSystemMemory", ctypes.c_size_t),
            ("SharedSystemMemory", ctypes.c_size_t),
            ("AdapterLuidLow", wintypes.DWORD),
            ("AdapterLuidHigh", wintypes.LONG),
            ("Flags", wintypes.UINT),
        ]

    def vcall(obj: ctypes.c_void_p, index: int, restype: Any, *argtypes: Any) -> Any:
        vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        proto = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
        return proto(vtable[index])

    def release(obj: ctypes.c_void_p) -> None:
        if obj:
            vcall(obj, 2, ctypes.c_ulong)(obj)

    try:
        dxgi = ctypes.WinDLL("dxgi")
        d3d12 = ctypes.WinDLL("d3d12")
    except OSError as exc:
        return GpuReport(False, "d3d12", reason=f"no D3D12 runtime: {exc}")

    factory = ctypes.c_void_p()
    iid_factory = guid("770aae78-f26f-4dba-a829-253c83d1b387")
    hr = dxgi.CreateDXGIFactory1(ctypes.byref(iid_factory), ctypes.byref(factory))
    if hr != 0:
        return GpuReport(False, "d3d12", reason=f"CreateDXGIFactory1 failed {hr & 0xFFFFFFFF:#x}")
    iid_device = guid("189819f1-1db6-4b57-be54-1821339b85f7")
    best: GpuReport | None = None
    adapters: list[dict[str, Any]] = []
    try:
        enum = vcall(factory, 12, ctypes.c_long, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p))
        index = 0
        while True:
            adapter = ctypes.c_void_p()
            if enum(factory, index, ctypes.byref(adapter)) != 0:
                break
            index += 1
            try:
                desc = DXGI_ADAPTER_DESC1()
                vcall(adapter, 10, ctypes.c_long, ctypes.POINTER(DXGI_ADAPTER_DESC1))(
                    adapter, ctypes.byref(desc)
                )
                software = bool(desc.Flags & 2)
                vram_mb = int(desc.DedicatedVideoMemory // (1024 * 1024))
                row = {"name": desc.Description, "vram_mb": vram_mb, "software": software}
                adapters.append(row)
                if software:
                    continue
                device = ctypes.c_void_p()
                hr = d3d12.D3D12CreateDevice(
                    adapter, 0xC000, ctypes.byref(iid_device), ctypes.byref(device)
                )
                if hr != 0:
                    row["d3d12"] = False
                    continue
                try:
                    sm = ctypes.c_uint32(0x60)
                    check = vcall(
                        device, 13, ctypes.c_long, ctypes.c_int, ctypes.c_void_p, wintypes.UINT
                    )
                    hr = check(device, 7, ctypes.byref(sm), ctypes.sizeof(sm))
                    model = sm.value if hr == 0 else 0
                finally:
                    release(device)
                row["shader_model"] = f"{model >> 4}.{model & 0xF}"
                ok = model >= 0x60 and vram_mb >= MIN_VRAM_MB
                report = GpuReport(
                    ok,
                    "d3d12",
                    desc.Description,
                    vram_mb,
                    row["shader_model"],
                    "" if ok else ("needs 6 GB VRAM" if model >= 0x60 else "needs shader model 6"),
                )
                if best is None or (report.ok, report.vram_mb) > (best.ok, best.vram_mb):
                    best = report
            finally:
                release(adapter)
    finally:
        release(factory)
    if best is None:
        best = GpuReport(False, "d3d12", reason="no hardware D3D12 adapter")
    best.adapters = adapters
    return best


# ---------------------------------------------------------------------- Linux


def parse_vulkaninfo(text: str) -> GpuReport:
    """``vulkaninfo --summary`` output -> the best Vulkan 1.3 non-CPU device."""
    best: GpuReport | None = None
    device: dict[str, str] = {}
    devices: list[dict[str, str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("GPU") and stripped.rstrip(":").split()[0].startswith("GPU"):
            if device:
                devices.append(device)
            device = {}
            continue
        if "=" in stripped:
            key, _, value = stripped.partition("=")
            device[key.strip()] = value.strip()
    if device:
        devices.append(device)
    for d in devices:
        api = d.get("apiVersion", "0.0")
        parts = [int(p) for p in api.split(" ")[0].split(".")[:2] if p.isdigit()]
        major, minor = (parts + [0, 0])[:2]
        kind = d.get("deviceType", "")
        ok = (major, minor) >= (1, 3) and "CPU" not in kind
        report = GpuReport(
            ok,
            "vulkan",
            d.get("deviceName", ""),
            0,
            "",
            "" if ok else ("CPU device" if "CPU" in kind else "needs Vulkan 1.3"),
        )
        if best is None or report.ok > best.ok:
            best = report
    return best or GpuReport(False, "vulkan", reason="no Vulkan device")


def _probe_vulkan() -> GpuReport:  # pragma: no cover - needs a Linux GPU
    try:
        out = subprocess.run(
            ["vulkaninfo", "--summary"],
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return GpuReport(False, "vulkan", reason=f"vulkaninfo unavailable: {exc}")
    return parse_vulkaninfo(out.stdout)


def probe_gpu_here() -> GpuReport:
    if sys.platform == "win32":
        return _probe_d3d12()
    if sys.platform.startswith("linux"):
        return _probe_vulkan()
    return GpuReport(False, "", reason="platform not supported yet")


# ---------------------------------------------------------------------- cached API

_cache: GpuReport | None = None


def probe_gpu(*, refresh: bool = False) -> GpuReport:
    """The GPU verdict, from a child process, cached for this app run."""
    global _cache
    override = getenv("DODAIOS_VERSE_PROBE").strip().lower()
    if override in ("pass", "fail"):
        return GpuReport(override == "pass", "override", reason=f"DODAIOS_VERSE_PROBE={override}")
    if _cache is not None and not refresh:
        return _cache
    try:
        out = subprocess.run(
            [sys.executable, "-m", "dodaios.verse_host.probe", "--json"],
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT_S,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        data = json.loads(out.stdout.strip().splitlines()[-1])
        _cache = GpuReport(**data)
    except (OSError, subprocess.TimeoutExpired, ValueError, IndexError, TypeError) as exc:
        _cache = GpuReport(False, reason=f"probe failed: {exc}")
    return _cache


def exe_name() -> str:
    return "Verse.exe" if sys.platform == "win32" else "Verse.sh"


def candidate_executables() -> list[Path]:
    out: list[Path] = []
    env = getenv("DODAIOS_VERSE_EXE")
    if env:
        out.append(Path(env))
    try:
        from dodaios.core.config import DATA_DIR

        out.append(Path(DATA_DIR) / "verse" / "build" / exe_name())
    except Exception:  # noqa: BLE001,S110 - no data dir in some test contexts
        pass
    app_root = Path(__file__).resolve().parents[2]
    platform_dir = "Windows" if sys.platform == "win32" else "Linux"
    out.append(app_root / "unreal" / "Verse" / "Saved" / "StagedBuilds" / platform_dir / exe_name())
    return out


def find_executable() -> Path | None:
    for path in candidate_executables():
        if path.is_file():
            return path
    return None


@dataclass
class Capability:
    status: str  # "ok", "not_installed", "unsupported"
    exe: str | None
    gpu: GpuReport
    checked_at: float


def check(*, refresh: bool = False) -> Capability:
    exe = find_executable()
    gpu = probe_gpu(refresh=refresh)
    if not gpu.ok:
        status = "unsupported"
    elif exe is None:
        status = "not_installed"
    else:
        status = "ok"
    return Capability(status, str(exe) if exe else None, gpu, time.time())


def main() -> int:  # pragma: no cover - run as a child process
    report = probe_gpu_here()
    print(json.dumps(asdict(report)))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
