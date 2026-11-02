# Verse on Linux: optional download and nightly smoke

The AppImage, the Debian package, `install.sh` and every app update carry no
Verse (docs/verse/unreal/README.md, Delivery; work-packages.md WP22.5,
WP22.6). The release carries `Verse-Linux-<version>.tar`, deltas and the
signed `verse-Linux-manifest.json` (`scripts/unreal/package.py full`, `delta`,
`manifest`). When the user presses "Download the Verse" on the launcher card,
the app (`dodaios/verse_host/install`) downloads it resumably, verifies it and
unpacks it into the user data folder (`<user data>/verse`); a read-only
AppImage stays untouched. Machines without a Vulkan 1.3 GPU are never offered
the download.

Nightly smoke (WP22.7, `scripts/unreal/package.py linux-smoke`):

| File | Role |
|---|---|
| `smoke.Dockerfile` | Ubuntu 24.04 with the Vulkan loader, Xvfb, a window manager and a headless Wayland compositor; runs as a normal user |
| `linux_smoke.sh` | Inside the container: the `-nullrhi` server run through the smoke stages, a Vulkan first frame when a device exists, then the activation check; writes `result.json` |
| `activation_check.py` | X11 `_NET_ACTIVE_WINDOW` and Wayland `xdg_activation_v1` availability (architecture.md RK7) |

The container has no network; the packaged build is mounted read-only.
