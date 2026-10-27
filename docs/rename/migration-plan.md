# Retiring the Personal Jarvis names: migration plan (proposal)

Status: **proposal**, partly implemented. Each step needs a maintainer
decision and its own pull request; the steps marked done below have landed.

Dodaios was called Personal Jarvis until October 2026. Some old names are still
in use because existing installs, scripts and links depend on them. This plan
lists how each one can be retired without breaking anyone. The full list of
remaining mentions is in [old-name-leftovers.md](old-name-leftovers.md).

## Where things stand (checked 2026-10-26, release v4.0.1)

| Name | Today | Who depends on it |
|---|---|---|
| Release assets `PersonalJarvis-*` | Published next to `Dodaios-*` copies with identical bytes (`scripts/ci/installer_aliases.py`, `INSTALLER_NAME_PAIRS` in `scripts/ci/release_assets.py`) | `releases/latest/download/...` links, the in-app updater of older installs |
| PyPI distribution | `dodaios` is the package; after 4.1.2 `personal-jarvis` is a thin package that depends on `dodaios` at the same version (step 2) | `pip install personal-jarvis`, `uvx --from personal-jarvis`, pinned requirements |
| CLI command | `dodaios`, `jarvis` and `personal-jarvis` all start the app (`[project.scripts]` in `pyproject.toml`) | shell history, scripts, desktop launchers, docs |
| Control CLI | `dodaiosctl`, `jarvisctl`, `jctl` | scripts and other agents |
| Config file | `jarvis.toml` | every install |
| Other sources | `personal-jarvis-src.tar.gz` (next to `dodaios-src.tar.gz`), `personal-jarvis.intoto.jsonl`; the `.deb` is `dodaios_<version>_amd64.deb` after 4.1.2 | install scripts, provenance checks |
| Windows setup identity | After 4.1.2 built and signed as `Dodaios-Setup-x64.exe`, product name `Dodaios` (`docs/code-signing-policy.md`) | SmartScreen, file properties |

## Step 1: asset aliases (largely done)

1. Keep publishing both `Dodaios-*` and `PersonalJarvis-*` installers, as
   `installer_aliases.py` does today.
2. Switch the README and website download links to the `Dodaios-*` names once
   every currently supported release ships them. The `PersonalJarvis-*` links
   keep working through the alias, so this needs no redirect.
3. The `.deb` is named after its package (`dodaios_<version>_amd64.deb`,
   done): nothing downloads it by name, and every check accepts both
   spellings for older releases. `dodaios-src.tar.gz` already exists next to
   `personal-jarvis-src.tar.gz`.
4. Kept for now, each with a reason:
   * `PersonalJarvis-*` installers: the in-app updater of frozen installs from
     before the update contract (PR #567) asks for these names only.
   * `personal-jarvis-src.tar.gz`: install scripts from releases before
     `dodaios-src.tar.gz` existed fall back to it. It is published by
     `release-cut.yml`, which other work is changing; retire it with the
     installer copies.
   * `personal-jarvis.intoto.jsonl`: `install/install-verify.sh` and `.ps1`
     of every published release look the provenance up under this name. A
     rename needs a release that publishes both names first (a change to
     `sign-installer.yml` and both verify scripts), then the old name can go
     with the installer copies.
5. **Sunset (proposal for the maintainer):** stop publishing the
   `PersonalJarvis-*` copies after two more minor releases or on 2027-01-31,
   whichever comes later, and only once the download counts of step 4.5 show
   they are no longer used. The switch is one line:
   `PUBLISH_EARLIER_INSTALLER_NAMES = False` in `scripts/ci/release_assets.py`
   (the alias script, the checksum manifest, release finalization and the
   release smoke test all follow it). Releases already published keep their
   assets. The 12-month floor this plan proposed earlier is the maintainer's
   call; the date above is the earliest proposal.

## Step 2: PyPI `personal-jarvis` to `dodaios`

1. Today both names carry the full package. That doubles the upload and splits
   the download numbers (pypistats, 2026-10-26: personal-jarvis 230 a week,
   dodaios 111 a week).
2. Done after 4.1.2: `personal-jarvis` is a thin package
   (`scripts/ci/build_distributions.py`). It depends on `dodaios==<same
   version>`, maps every extra to the same `dodaios` extra, and its long
   description says the project is now Dodaios.
3. Its version moves in lock-step with `dodaios`, so
   `pip install -U personal-jarvis` keeps updating real installs.
4. It re-declares every `dodaios` console command (`jarvis`, `personal-jarvis`,
   `dodaios`, `jarvisctl`, ...) through a small launcher, because
   `uv tool install personal-jarvis` only links the commands of the package
   it was asked for. Each command starts the same entry point as in `dodaios`.
5. Known edge, measured with pip 24 and uv 0.11: plain
   `pip install -U personal-jarvis` over a full copy (4.1.2 or older) installs
   `dodaios` first and then uninstalls the old copy, which deletes the files
   both owned. The launcher then prints the repair,
   `python -m pip install --force-reinstall --no-deps dodaios==<version>`,
   and the PyPI page says the same. uv uninstalls first and is not affected;
   `install/installer.py` removes the old name first and is not affected. The
   clean move is `pip uninstall -y personal-jarvis` then
   `pip install --force-reinstall dodaios`.
6. Retire the thin package (stop uploading, leave old versions up, never
   delete or yank them) after at least 12 months.

## Step 3: a `dodaios` CLI next to `jarvis` (done)

`dodaios` is already the primary command. The remaining work is documentation
only:

1. Write `dodaios` in new docs and in the README. Mention `jarvis` once per page
   as the earlier name.
2. Never remove `jarvis`, `personal-jarvis`, `jarvisctl` or `jctl`. They cost
   nothing and removing them breaks scripts silently.
3. Never add a command that differs from the launcher only by case
   (`dodaiosapp`, `personaljarvis`): Windows paths ignore case (see the comment
   in `pyproject.toml`).
4. `jarvis.toml` keeps its name. A rename would need a read-both, write-new
   migration in the config loader, which is a functional change and out of scope
   here.

## Step 4: updater compatibility for installs up to 3.1.1

Installs up to and including 3.1.1 do not follow GitHub's repository redirect
when they check for updates, so they stopped seeing new releases after the
move to `Dodaios/Dodaios`.

1. These installs can only be reached by hand: they never see a new release,
   whatever its assets are called.
2. Keep the `PersonalJarvis-*` asset names anyway. Installs from after 3.1.1
   that predate the `Dodaios-*` aliases follow the redirect but look for the
   old names.
3. Tell users on 3.1.1 or older how to update by hand: run the one-line installer again. Put
   that sentence in the release notes and in the troubleshooting page.
4. Do not try to reach them by recreating the old repository (see the warning
   below).
5. Before dropping any old name, check the download counts of the
   `PersonalJarvis-*` assets of the last three releases. If they still get
   downloads, keep them.

## Never do this

**Never create a repository named `PersonalJarvis/PersonalJarvis`** (and never
rename another repository to that name). GitHub redirects the old URL to
`Dodaios/Dodaios` only as long as nothing exists at the old address. A new
repository there silently breaks every old link, the raw install URLs and the
update check of installs that follow the redirect.
