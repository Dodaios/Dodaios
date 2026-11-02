# Verse in the Windows installer

The packaged Unreal Verse ships inside `Dodaios-Setup-x64.exe`
(docs/verse/unreal/work-packages.md WP22.6):

1. `scripts/unreal/package.py build --platform win64` packages the Win64
   Shipping build (IoStore chunk per deck), `package.py full` turns it into
   `Verse-Win64-<version>.tar`.
2. `stage_verse.ps1 -Payload <tar>` copies that file into `dist\Jarvis\verse\`
   after the freeze. `Dodaios.iss` packs everything below `dist\Jarvis`, so no
   extra installer page or script is needed.
3. On first start the app installs the seed into `%LOCALAPPDATA%\Dodaios\verse`
   (`seed_verse_from_bundle` in `dodaios/core/installer_update.py`), checks
   every file against `verse-tree.json` and removes the seed.

Later Verse updates arrive as delta packages from the release
(`Verse-Win64-<old>-to-<new>.delta.tar`), verified against the signed
`verse-SHA256SUMS.txt`. A machine without a GPU never installs or downloads
the Verse; the app runs as before and the Verse reports `unsupported`.
