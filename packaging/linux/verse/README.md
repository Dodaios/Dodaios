# Verse on Linux: AppImage payload and nightly smoke

Installer integration (docs/verse/unreal/work-packages.md WP22.6):
`stage_verse.sh <Verse-Linux-<version>.tar> [dist/Jarvis]` copies the full
payload into the freeze output before `packaging/linux/build.sh` assembles the
AppDir. On first start the app installs it into `$XDG_DATA_HOME/dodaios/verse`
(`seed_verse_from_bundle`); the read-only AppImage keeps its copy.

Nightly smoke (WP22.7, `scripts/unreal/package.py linux-smoke`):

| File | Role |
|---|---|
| `smoke.Dockerfile` | Ubuntu 24.04 with the Vulkan loader, Xvfb, a window manager and a headless Wayland compositor; runs as a normal user |
| `linux_smoke.sh` | Inside the container: the `-nullrhi` server run through the smoke stages, a Vulkan first frame when a device exists, then the activation check; writes `result.json` |
| `activation_check.py` | X11 `_NET_ACTIVE_WINDOW` and Wayland `xdg_activation_v1` availability (architecture.md RK7) |

The container has no network; the packaged build is mounted read-only.
