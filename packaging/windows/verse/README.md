# Verse on Windows: an optional download, never in the installer

`Dodaios-Setup-x64.exe` and every app update carry no Verse
(docs/verse/unreal/README.md, Delivery; work-packages.md WP22.5, WP22.6).
The Verse is its own signed package on the release:

1. `scripts/unreal/package.py build --platform win64` packages the Win64
   Shipping build (IoStore chunk per deck). The `sign-windows` job of
   `.github/workflows/unreal-package.yml` signs its executables.
2. `package.py full` turns it into `Verse-Win64-<version>.tar`, `package.py
   delta` adds `Verse-Win64-<old>-to-<new>.delta.tar`, and `package.py
   manifest` writes `verse-Win64-manifest.json` (version, sizes, SHA-256 of
   every package). The release key signs it as `verse-Win64-manifest.json.sig`.
3. The first time someone opens the Verse, the launcher card shows the
   download size and a "Download the Verse" button. The app
   (`dodaios/verse_host/install`) verifies the signature, downloads the
   package resumably, checks its SHA-256 and every file of it, and unpacks it
   into `%LOCALAPPDATA%\Dodaios\verse`. Settings can remove it again.

Only an installed Verse gets updates, as delta packages when one fits. A
machine without a GPU is never offered the download; the Verse reports
`unsupported` and the rest of the app is unaffected.

## Local check of the whole flow

`scripts/unreal/ondemand_e2e.py --full Verse-Win64-<version>.tar` signs the
manifest with a throwaway key, serves a release list and the package from a
loopback HTTP server and drives the real `VerseInstaller`: `not_installed`,
offer, download with progress, verify, install, launch, uninstall,
`not_installed`. First numbers (2026-11-09, graybox build): the Shipping
payload is 419 MB (core 135 MB, binaries 254 MB, decks 27 MB in four chunks),
a one-chunk delta is 1.1 MB, the first frame arrives 2.2 s after engine start.
Deck chunks come from the `DA_DeckChunk_<Deck>` labels (`scripts/unreal/deck_labels.py`);
the engine's Map rules alone leave every package in chunk 0.
