"""Which audio devices are virtual, asked from the operating system (macOS).

A virtual microphone (a camera or meeting app's audio device, a loopback
driver, a noise-removal "microphone") is listed like a real one and carries
sound only while its app feeds it. The automatic microphone choice passes such
inputs over, and until now it knew them by a list of product names. A name
list is always one product behind: an input the list did not know, with
"Microphone" in its name, ranked before a built-in microphone whose name is
localized.

CoreAudio knows the answer for every device: its transport type is
``kAudioDeviceTransportTypeVirtual`` for a device that is software only. This
module reads that property for all devices, by name.

It is meant to run in the device probe's own short-lived process
(``dodaios.audio.device_probe``), never in the app: the app's CoreAudio client
can be blocked by a stream that does not close, and a read behind that block
would not come back either.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import struct
import sys

#: ``kAudioDeviceTransportTypeVirtual``.
VIRTUAL = "virt"

_SYSTEM_OBJECT = 1  # kAudioObjectSystemObject
_ELEMENT_MAIN = 0
_UTF8 = 0x08000100  # kCFStringEncodingUTF8
_NAME_BYTES = 1024


def _fourcc(code: str) -> int:
    return int(struct.unpack(">I", code.encode("ascii"))[0])


def fourcc_text(value: int) -> str:
    """The four characters of a CoreAudio code, as text (``"virt"``)."""
    return struct.pack(">I", value & 0xFFFFFFFF).decode("ascii", "replace")


class _Address(ctypes.Structure):
    """``AudioObjectPropertyAddress``."""

    _fields_ = [
        ("selector", ctypes.c_uint32),
        ("scope", ctypes.c_uint32),
        ("element", ctypes.c_uint32),
    ]


def _address(selector: str) -> _Address:
    return _Address(_fourcc(selector), _fourcc("glob"), _ELEMENT_MAIN)


def _read_coreaudio() -> dict[str, str]:
    """Device name -> transport code, straight from CoreAudio. May raise."""
    audio_path = ctypes.util.find_library("CoreAudio")
    foundation_path = ctypes.util.find_library("CoreFoundation")
    if not audio_path or not foundation_path:
        return {}
    audio = ctypes.CDLL(audio_path)
    foundation = ctypes.CDLL(foundation_path)
    get_size = audio.AudioObjectGetPropertyDataSize
    get_size.argtypes = [
        ctypes.c_uint32,
        ctypes.POINTER(_Address),
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint32),
    ]
    get_size.restype = ctypes.c_int32
    get_data = audio.AudioObjectGetPropertyData
    get_data.argtypes = [
        ctypes.c_uint32,
        ctypes.POINTER(_Address),
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.c_void_p,
    ]
    get_data.restype = ctypes.c_int32
    get_c_string = foundation.CFStringGetCString
    get_c_string.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32]
    get_c_string.restype = ctypes.c_bool
    release = foundation.CFRelease
    release.argtypes = [ctypes.c_void_p]
    release.restype = None

    devices_address = _address("dev#")  # kAudioHardwarePropertyDevices
    size = ctypes.c_uint32(0)
    if get_size(_SYSTEM_OBJECT, ctypes.byref(devices_address), 0, None, ctypes.byref(size)) != 0:
        return {}
    count = size.value // ctypes.sizeof(ctypes.c_uint32)
    if count <= 0:
        return {}
    device_ids = (ctypes.c_uint32 * count)()
    if (
        get_data(
            _SYSTEM_OBJECT, ctypes.byref(devices_address), 0, None, ctypes.byref(size), device_ids
        )
        != 0
    ):
        return {}

    name_address = _address("lnam")  # kAudioObjectPropertyName
    transport_address = _address("tran")  # kAudioDevicePropertyTransportType
    transports: dict[str, str] = {}
    for device_id in device_ids:
        name_ref = ctypes.c_void_p()
        ref_size = ctypes.c_uint32(ctypes.sizeof(name_ref))
        if (
            get_data(
                device_id,
                ctypes.byref(name_address),
                0,
                None,
                ctypes.byref(ref_size),
                ctypes.byref(name_ref),
            )
            != 0
            or not name_ref.value
        ):
            continue
        buffer = ctypes.create_string_buffer(_NAME_BYTES)
        named = bool(get_c_string(name_ref, buffer, _NAME_BYTES, _UTF8))
        release(name_ref)
        if not named:
            continue
        code = ctypes.c_uint32(0)
        code_size = ctypes.c_uint32(ctypes.sizeof(code))
        if (
            get_data(
                device_id,
                ctypes.byref(transport_address),
                0,
                None,
                ctypes.byref(code_size),
                ctypes.byref(code),
            )
            != 0
        ):
            continue
        transports[buffer.value.decode("utf-8", "replace")] = fourcc_text(code.value)
    return transports


def read_transports() -> dict[str, str]:
    """Device name -> four-character transport code. Empty when it cannot be read.

    Only macOS answers. Every failure is an empty answer: the caller then knows
    no more than before and keeps its name list.
    """
    if sys.platform != "darwin":
        return {}
    try:
        return _read_coreaudio()
    except Exception:  # noqa: BLE001 - a missing answer is the documented degraded mode
        return {}


def virtual_device_names(transports: dict[str, str] | None = None) -> list[str]:
    """Names of the devices the operating system calls virtual, sorted."""
    known = read_transports() if transports is None else transports
    return sorted(name for name, code in known.items() if code == VIRTUAL)


__all__ = ["VIRTUAL", "fourcc_text", "read_transports", "virtual_device_names"]
