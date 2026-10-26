# Retiring the Personal Jarvis names: migration plan (proposal)

Status: **proposal only**. Nothing in this document is implemented by the pull
request that adds it. Each step needs a maintainer decision and its own pull
request.

Dodaios was called Personal Jarvis until October 2026. Some old names are still
in use because existing installs, scripts and links depend on them. This plan
lists how each one can be retired without breaking anyone. The full list of
remaining mentions is in [old-name-leftovers.md](old-name-leftovers.md).

## Where things stand (checked 2026-10-26, release v4.0.1)

| Name | Today | Who depends on it |
|---|---|---|
| Release assets `PersonalJarvis-*` | Published next to `Dodaios-*` copies with identical bytes (`scripts/ci/installer_aliases.py`, `INSTALLER_NAME_PAIRS` in `scripts/ci/release_assets.py`) | `releases/latest/download/...` links, the in-app updater of older installs |
| PyPI distribution | `dodaios` and `personal-jarvis` are both published as full packages at 4.0.1 | `pip install personal-jarvis`, pinned requirements |
| CLI command | `dodaios`, `jarvis` and `personal-jarvis` all start the app (`[project.scripts]` in `pyproject.toml`) | shell history, scripts, desktop launchers, docs |
| Control CLI | `dodaiosctl`, `jarvisctl`, `jctl` | scripts and other agents |
| Config file | `jarvis.toml` | every install |
| Other sources | `personal-jarvis-src.tar.gz`, `personal-jarvis.intoto.jsonl`, `personal-jarvis_<version>_amd64.deb` | package managers, provenance checks |

## Step 1: asset aliases (largely done)

1. Keep publishing both `Dodaios-*` and `PersonalJarvis-*` installers, as
   `installer_aliases.py` does today.
2. Switch the README and website download links to the `Dodaios-*` names once
   every currently supported release ships them. The `PersonalJarvis-*` links
   keep working through the alias, so this needs no redirect.
3. Add the same alias pattern for `personal-jarvis-src.tar.gz`,
   `personal-jarvis.intoto.jsonl` and the `.deb` package (`dodaios-src.tar.gz`
   already exists).
4. Stop publishing the `PersonalJarvis-*` copies only after the updater
   telemetry-free check in step 4 shows that no supported release reads them,
   and never before 12 months after the rename.

## Step 2: PyPI `personal-jarvis` to `dodaios`

1. Today both names carry the full package. That doubles the upload and splits
   the download numbers (pypistats, 2026-10-26: personal-jarvis 230 a week,
   dodaios 111 a week).
2. Proposal: from one release on, publish `personal-jarvis` as a thin
   transitional meta-package. It has no code, depends on `dodaios==<same
   version>`, and its long description says the project is now Dodaios.
3. Keep the meta-package version in lock-step with `dodaios`, so
   `pip install -U personal-jarvis` keeps updating real installs.
4. The `personal-jarvis` console script must stay available. It already lives in
   `dodaios`'s own `[project.scripts]`, so the meta-package does not need to
   declare it again.
5. Retire the meta-package (stop uploading, leave old versions up, never delete
   or yank them) after at least 12 months.

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
