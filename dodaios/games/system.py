"""What this PC can do for games: GPU, CPU, RAM and the monitors.

Read once per process and cached: none of it changes while the app runs
often enough to matter, and the probes (nvidia-smi, PowerShell) take a moment.
Every probe fails soft to ``None`` so a headless or non-Windows host still
answers.
"""

from __future__ import annotations

import logging
import platform
import re
import subprocess
import sys
from functools import lru_cache
from typing import Any

log = logging.getLogger(__name__)


def _cpu_name() -> str | None:
    if sys.platform == "win32":
        try:
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
            )
            value, _ = winreg.QueryValueEx(key, "ProcessorNameString")
            return str(value).strip() or None
        except OSError:
            log.debug("games.system: CPU name not in the registry", exc_info=True)
    return platform.processor() or None


def _gpus() -> list[dict[str, Any]]:
    from dodaios.hardware.detection import _detect_nvidia_gpus

    found = [{"name": g.name, "vram_gb": round(g.vram_mb / 1024, 1)} for g in _detect_nvidia_gpus()]
    if found or sys.platform != "win32":
        return found
    # Any vendor on Windows. AdapterRAM is a 32-bit field (caps at 4 GB), so
    # VRAM is left out rather than reported wrong.
    try:
        out = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
    except (OSError, subprocess.SubprocessError):
        log.debug("games.system: video controller query failed", exc_info=True)
        return []
    names = [line.strip() for line in out.splitlines() if line.strip()]
    skip = re.compile(r"basic display|remote|virtual|parsec|meta", re.I)
    return [{"name": name, "vram_gb": None} for name in names if not skip.search(name)]


def _ram_gb() -> float | None:
    try:
        import psutil

        return round(psutil.virtual_memory().total / 1024**3)
    except ImportError:  # psutil is optional; the page shows RAM as unknown
        return None


def _monitors_windows() -> list[dict[str, Any]]:
    import ctypes
    from ctypes import wintypes

    class DISPLAY_DEVICEW(ctypes.Structure):  # noqa: N801 - Win32 name
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("DeviceName", wintypes.WCHAR * 32),
            ("DeviceString", wintypes.WCHAR * 128),
            ("StateFlags", wintypes.DWORD),
            ("DeviceID", wintypes.WCHAR * 128),
            ("DeviceKey", wintypes.WCHAR * 128),
        ]

    class DEVMODEW(ctypes.Structure):  # noqa: N801 - Win32 name
        _fields_ = [
            ("dmDeviceName", wintypes.WCHAR * 32),
            ("dmSpecVersion", wintypes.WORD),
            ("dmDriverVersion", wintypes.WORD),
            ("dmSize", wintypes.WORD),
            ("dmDriverExtra", wintypes.WORD),
            ("dmFields", wintypes.DWORD),
            ("dmPositionX", wintypes.LONG),
            ("dmPositionY", wintypes.LONG),
            ("dmDisplayOrientation", wintypes.DWORD),
            ("dmDisplayFixedOutput", wintypes.DWORD),
            ("dmColor", wintypes.SHORT),
            ("dmDuplex", wintypes.SHORT),
            ("dmYResolution", wintypes.SHORT),
            ("dmTTOption", wintypes.SHORT),
            ("dmCollate", wintypes.SHORT),
            ("dmFormName", wintypes.WCHAR * 32),
            ("dmLogPixels", wintypes.WORD),
            ("dmBitsPerPel", wintypes.DWORD),
            ("dmPelsWidth", wintypes.DWORD),
            ("dmPelsHeight", wintypes.DWORD),
            ("dmDisplayFlags", wintypes.DWORD),
            ("dmDisplayFrequency", wintypes.DWORD),
            ("dmICMMethod", wintypes.DWORD),
            ("dmICMIntent", wintypes.DWORD),
            ("dmMediaType", wintypes.DWORD),
            ("dmDitherType", wintypes.DWORD),
            ("dmReserved1", wintypes.DWORD),
            ("dmReserved2", wintypes.DWORD),
            ("dmPanningWidth", wintypes.DWORD),
            ("dmPanningHeight", wintypes.DWORD),
        ]

    user32 = ctypes.windll.user32
    attached = 0x1
    primary = 0x4
    current = -1  # ENUM_CURRENT_SETTINGS
    monitors: list[dict[str, Any]] = []
    index = 0
    while True:
        device = DISPLAY_DEVICEW()
        device.cb = ctypes.sizeof(device)
        if not user32.EnumDisplayDevicesW(None, index, ctypes.byref(device), 0):
            break
        index += 1
        if not device.StateFlags & attached:
            continue
        mode = DEVMODEW()
        mode.dmSize = ctypes.sizeof(mode)
        if not user32.EnumDisplaySettingsW(device.DeviceName, current, ctypes.byref(mode)):
            continue
        max_w, max_h, max_hz = mode.dmPelsWidth, mode.dmPelsHeight, mode.dmDisplayFrequency
        n = 0
        probe = DEVMODEW()
        probe.dmSize = ctypes.sizeof(probe)
        while user32.EnumDisplaySettingsW(device.DeviceName, n, ctypes.byref(probe)):
            n += 1
            if probe.dmPelsWidth * probe.dmPelsHeight > max_w * max_h:
                max_w, max_h = probe.dmPelsWidth, probe.dmPelsHeight
            # Highest refresh at the resolution in use, not at some lower mode.
            same_size = (probe.dmPelsWidth, probe.dmPelsHeight) == (
                mode.dmPelsWidth,
                mode.dmPelsHeight,
            )
            if same_size and probe.dmDisplayFrequency > max_hz:
                max_hz = probe.dmDisplayFrequency
            if n > 2000:
                break
        monitors.append(
            {
                "name": f"Display {len(monitors) + 1}",
                "primary": bool(device.StateFlags & primary),
                "width": int(mode.dmPelsWidth),
                "height": int(mode.dmPelsHeight),
                "refresh_hz": _nominal_hz(int(mode.dmDisplayFrequency)),
                "max_width": int(max_w),
                "max_height": int(max_h),
                "max_refresh_hz": _nominal_hz(int(max_hz)),
            }
        )
    monitors.sort(key=lambda m: not m["primary"])
    return monitors


def _nominal_hz(hz: int) -> int:
    """59 -> 60, 143 -> 144: Windows reports fractional rates rounded down."""
    common = {
        24,
        30,
        48,
        60,
        75,
        90,
        100,
        120,
        144,
        165,
        170,
        180,
        200,
        240,
        280,
        300,
        360,
        480,
        540,
    }
    return hz + 1 if hz not in common and hz + 1 in common else hz


def _monitors() -> list[dict[str, Any]]:
    if sys.platform != "win32":
        return []
    try:
        return _monitors_windows()
    except (OSError, AttributeError, ValueError):
        log.debug("games.system: monitor enumeration failed", exc_info=True)
        return []


def gpu_tier(gpus: list[dict[str, Any]]) -> str | None:
    """A rough class for picking a preset: entry, mid, high or enthusiast.

    From VRAM when it is known, else from the model number in the name
    (RTX 4090 / RX 7900 → enthusiast). ``None`` when nothing says.
    """
    best: str | None = None
    order = ["entry", "mid", "high", "enthusiast"]
    for gpu in gpus:
        tier = _tier_of(gpu)
        if tier and (best is None or order.index(tier) > order.index(best)):
            best = tier
    return best


def _rank(value: float, steps: tuple[float, float, float]) -> str:
    """entry / mid / high / enthusiast for ``value`` against three thresholds."""
    mid, high, top = steps
    if value >= top:
        return "enthusiast"
    if value >= high:
        return "high"
    return "mid" if value >= mid else "entry"


def _tier_of(gpu: dict[str, Any]) -> str | None:
    name = str(gpu.get("name") or "").lower()
    vram = gpu.get("vram_gb")
    m = re.search(r"(?:rtx|gtx)\s*(\d{4})", name) or re.search(r"rx\s*(\d{4})", name)
    if m:
        model = int(m.group(1))
        series, rank = model // 1000, model % 100
        if "rx" in name and "rtx" not in name:
            # RX 7900 / 7600: the class is the hundreds digit.
            return _rank((model % 1000) // 10, (60, 70, 90))
        if series >= 3:
            return _rank(rank, (60, 70, 80))
        return "mid" if rank >= 70 else "entry"
    if isinstance(vram, (int, float)):
        return _rank(vram, (6, 10, 16))
    return None


@lru_cache(maxsize=1)
def system_info() -> dict[str, Any]:
    gpus = _gpus()
    monitors = _monitors()
    tier = gpu_tier(gpus)
    recommended = {
        "enthusiast": "epic",
        "high": "quality",
        "mid": "balanced",
        "entry": "competitive",
    }
    return {
        "os": platform.system(),
        "cpu": _cpu_name(),
        "ram_gb": _ram_gb(),
        "gpus": gpus,
        "monitors": monitors,
        "gpu_tier": tier,
        "recommended_preset": recommended.get(tier or "", None),
    }
