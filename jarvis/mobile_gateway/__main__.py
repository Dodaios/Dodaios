"""Pair and manage phones: ``python -m jarvis.mobile_gateway <command>``.

pair       issue a five-minute code and show it as a QR code
devices    list paired phones
revoke ID  revoke a phone's key
firewall   print the Windows firewall command for the gateway port
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import subprocess
import sys
from pathlib import Path

from jarvis.core.config import MobileGatewayConfig, load_config

from .devices import DeviceStore
from .tls import ensure_certificate, fingerprint

_DETECT_IPV6 = (
    "Get-NetIPAddress -AddressFamily IPv6 -AddressState Preferred "
    "| Where-Object { $_.SuffixOrigin -ne 'Random' -and $_.PrefixOrigin -ne 'WellKnown' } "
    "| Sort-Object InterfaceMetric | Select-Object -ExpandProperty IPAddress"
)


def _config(path: str) -> MobileGatewayConfig:
    cfg = load_config(Path(path))
    integrations = getattr(cfg, "integrations", None)
    mobile = getattr(integrations, "mobile", None)
    return mobile if isinstance(mobile, MobileGatewayConfig) else MobileGatewayConfig()


def detect_public_ipv6() -> str:
    """The PC's stable (non-temporary) global IPv6 address, or ``""``."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", _DETECT_IPV6],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):  # no ipconfig: pair then asks for public_host
        return ""
    for line in out.splitlines():
        try:
            addr = ipaddress.IPv6Address(line.strip().split("%")[0])
        except ValueError:  # not an address token; keep scanning
            continue
        if addr.is_global:
            return str(addr)
    return ""


def pairing_payload(host: str, port: int, fp: str, code: str) -> str:
    return json.dumps({"v": 1, "h": host, "p": port, "f": fp, "c": code}, separators=(",", ":"))


def _cmd_pair(cfg: MobileGatewayConfig) -> int:
    data_dir = Path(cfg.data_dir)
    host = cfg.public_host or detect_public_ipv6()
    if not host:
        print("No global IPv6 address found. Set [integrations.mobile] public_host.")
        return 1
    cert, _ = ensure_certificate(data_dir)
    code = DeviceStore(data_dir).issue_code(cfg.pairing_ttl_s)
    payload = pairing_payload(host, cfg.port, fingerprint(cert), code)
    minutes = int(cfg.pairing_ttl_s // 60)
    print(f"Pairing code: {code}  (valid {minutes} minutes, single use)")
    print(f"Address: [{host}]:{cfg.port}")
    print(f"Paste into the app manually:\n{payload}")
    try:
        import segno
    except ImportError:  # segno is optional; the text payload above still pairs
        print("(QR image unavailable: 'pip install segno')")
        return 0
    png = data_dir / "pairing-qr.png"
    segno.make(payload, error="m").save(str(png), scale=10, border=4)
    print(f"QR code: {png}")
    if sys.platform == "win32":
        os.startfile(png)  # noqa: S606 — opens the image viewer for the user
    return 0


def _cmd_devices(cfg: MobileGatewayConfig) -> int:
    devices = DeviceStore(Path(cfg.data_dir)).devices()
    if not devices:
        print("No paired devices.")
    for d in devices:
        state = "revoked" if d.revoked else "active"
        print(f"{d.device_id}  {d.name:<24} {state}")
    return 0


def _cmd_revoke(cfg: MobileGatewayConfig, device_id: str) -> int:
    if DeviceStore(Path(cfg.data_dir)).revoke(device_id):
        print(f"Device {device_id} revoked.")
        return 0
    print(f"No active device {device_id}.")
    return 1


def _cmd_firewall(cfg: MobileGatewayConfig) -> int:
    print("Run in an administrator PowerShell:")
    print(
        f'New-NetFirewallRule -DisplayName "Dodaios Mobile Gateway" -Direction Inbound '
        f"-Protocol TCP -LocalPort {cfg.port} -Action Allow -Profile Any"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m jarvis.mobile_gateway")
    parser.add_argument("--config", default="jarvis.toml")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("pair")
    sub.add_parser("devices")
    revoke = sub.add_parser("revoke")
    revoke.add_argument("device_id")
    sub.add_parser("firewall")
    args = parser.parse_args(argv)

    cfg = _config(args.config)
    if args.command == "pair":
        return _cmd_pair(cfg)
    if args.command == "devices":
        return _cmd_devices(cfg)
    if args.command == "revoke":
        return _cmd_revoke(cfg, args.device_id)
    return _cmd_firewall(cfg)


if __name__ == "__main__":
    raise SystemExit(main())
