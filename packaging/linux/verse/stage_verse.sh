#!/usr/bin/env bash
# Put the packaged Unreal Verse into the Linux AppImage and Debian package.
#
# docs/verse/unreal/work-packages.md WP22.6. Copies a full Verse payload
# (Verse-Linux-<version>.tar from `scripts/unreal/package.py full`) into the
# PyInstaller output packaging/linux/build.sh wraps, as <freeze dir>/verse/.
# build.sh copies that whole tree into the AppDir, so the payload rides in the
# normal AppImage and .deb.
#
# On first start the app installs the seed into the per-user Verse folder
# ($XDG_DATA_HOME/dodaios/verse, seed_verse_from_bundle in
# dodaios/core/installer_update.py) and verifies every file. Machines without
# a Vulkan 1.3 GPU keep it unused: the Verse reports "unsupported".
#
#   bash packaging/linux/verse/stage_verse.sh dist/verse/Verse-Linux-4.2.0.tar [dist/Jarvis]
set -eu

payload="${1:-}"
freeze_dir="${2:-dist/Jarvis}"
name="$(basename "${payload}")"

case "${name}" in
  Verse-Linux-[0-9]*.[0-9]*.[0-9]*.tar) ;;
  *) echo "[verse] ${name:-<none>} is not a Linux Verse payload (want Verse-Linux-<version>.tar)" >&2; exit 2 ;;
esac
if [ ! -d "${freeze_dir}" ]; then
  echo "[verse] no frozen app at ${freeze_dir}; freeze first (packaging/linux/build.sh)" >&2
  exit 2
fi
if ! tar -tf "${payload}" | grep -qx 'verse-tree.json'; then
  echo "[verse] ${name} has no verse-tree.json; build it with scripts/unreal/package.py full" >&2
  exit 2
fi
mkdir -p "${freeze_dir}/verse"
rm -f "${freeze_dir}/verse"/Verse-*.tar
cp "${payload}" "${freeze_dir}/verse/${name}"
echo "[verse] staged ${name} into ${freeze_dir}/verse"
