# Personal Jarvis leftovers

Dodaios was called Personal Jarvis until October 2026. This file lists every
place in the repository that still contains the old name or an old URL, puts
each one in a category, and says what happened to it. It belongs to block B of
issue #850. The plan for retiring the compatibility names for good is a
separate proposal: [migration-plan.md](migration-plan.md).

## How the list was made

Run from the repository root:

```sh
git grep -n -I -E "PersonalJarvis|Personal Jarvis|personaljarvis\.ai|github\.com/PersonalJarvis" -- . ':!CHANGELOG.md' ':!docs/rename/'
```

`docs/rename/` is excluded because the files in this folder quote the old
names on purpose. Line numbers in the full table are those of this run.

## Categories

- **(a) Must stay.** A compatibility name or a fact about something that is
  still called that: release asset names (`PersonalJarvis-*`), executables
  (`PersonalJarvis.exe`), the macOS bundle of older installs
  (`Personal Jarvis.app`), mutex, registry and AppUserModelID names, legacy
  repository slugs the updater and installers accept
  (`scripts/ci/installer_aliases.py`), names of registered OAuth apps and
  certificates, the live token-broker host `token.personaljarvis.ai`, legal and
  trademark text, and test fixtures that check all of this. Comment and
  docstring prose inside code, script and config files is listed here too:
  this change touches no code, and rewording those comments is left for a
  follow-up.
- **(b) Old URL** that should point to the new one.
- **(c) Prose** that should say Dodaios.
- **(d) Historical.** Leave as written: supply-chain audit logs, dated audit
  and verification records, ADRs, recon snapshots, incident quotes.

## Summary

**Current tree: 910 hits on `main` at ad1a29656f with this PR's edits
applied, docs/rename excluded.** Line numbers are a snapshot of that tree and
drift as `main` moves; re-run the command above for current positions.

| Category | Hits | Notes |
| --- | ---: | --- |
| (a) must stay | 801 | Includes the "Formerly Personal Jarvis" lines in `README.md` and `README.zh-CN.md` (required by A2 of #850), the one-time "(formerly Personal Jarvis)" notes, and reworded lines that still name a legacy file or app |
| (b) old URL | 0 | |
| (c) prose | 0 | |
| (d) historical | 109 | |
| **Total** | **910** | |

Hits by area:

| Area | Hits |
| --- | ---: |
| Tests | 525 |
| docs/ | 164 |
| .github/, scripts/ | 74 |
| dodaios/ (app code, shipped plugin text, built bundle) | 68 |
| packaging/, install/, dodaios.spec | 52 |
| Other root files (launchers, configs, brand assets, wiki) | 25 |
| README.md, README.zh-CN.md | 2 |

For reference: the first run, on 2026-10-26 before any edits, found 916 hits
((a) 791, (b) 2, (c) 14, (d) 109).

What went away since: the two old-organization links in
`docs/code-signing-policy.md` (b), now pointing to the Dodaios organization;
the `Personal Jarvis.app` build paths and the dev shortcut names in
`docs/desktop-installers.md` and `docs/dev-instance.md`; the title of
`scripts/README-auto-push.md`; the old name in
`third_party/hermes-agent/README.md`; and the README links to the
`PersonalJarvis-*` downloads, which now point to the `Dodaios-*` copies. The
other (c) lines are now (a): the two README lines are the rename line A2 of
#850 asks for, and the rest were reworded so that the old name remains only
where it names a legacy file, bundle or app.

What came in: the one-time "(formerly Personal Jarvis)" notes in docs, and
lines added on `main` by other changes (tests, a workflow) and by the README
video notes. The dist bundle row names the current hashed file; `main`
rebuilds it after merges, so its name changes over time.

### Old URLs that were not category (b)

The URL patterns also match places where the old address is not a stale link:

- `token.personaljarvis.ai` is the OAuth token broker the app calls today
  (`_BROKER_BASE` in `dodaios/marketplace/publisher_clients.py`).
  `token.dodaios.ai` does not resolve, so the docs keep describing the real
  host. Moving the broker is a runtime change: (a).
- `github.com/PersonalJarvis/PersonalJarvis` in `docs/supply-chain/` is part of
  dated signing and verification logs (certificate identities, release URLs of
  that time): (d). GitHub redirects these URLs.
- The same URL in `.github/workflows/release-wrapper-smoke.yml` and in tests is
  a legacy slug the installers must keep accepting: (a).
- `personaljarvis.ai/marketplace/submit` in `docs/marketplace/publishing-plan.md`
  quotes what an old README promised: (d). It redirects to
  `dodaios.ai/marketplace/submit`, which returns 404, so a replacement would not
  help either.

### Left for a maintainer decision

- Product docs still say that macOS lists the app as **Personal Jarvis** "until
  the next installer" (`docs/product/start-here/install-dodaios.md`,
  `docs/product/reference/platform-support.md`,
  `docs/product/privacy-safety-and-support/permissions.md`,
  `control-key.md`, `troubleshooting.md`, `docs/macos-permissions.md`). The
  build now produces `Dodaios.app` and the source installer renames an old
  bundle once, but a downloaded `.dmg` app keeps its old name until its updater
  runs. Once every supported install has `Dodaios.app`, these lines can go.
- Comment and docstring prose in code, scripts and configs (headers such as
  "Personal Jarvis - Windows quick-install bootstrap"). The install scripts are
  signed release assets, so even a comment change there changes what users
  verify. Reword these in a separate code PR.
- `scripts/README-auto-push.md` shows the maintainer's real local checkout path,
  which still contains "Personal Jarvis". Only its title was changed.

## Full table

Consecutive hits of one file with the same category and action share a row.

| Path | Line(s) | Hits | Category | Action |
| --- | --- | ---: | :---: | --- |
| `.env.example` | 2 | 1 | (a) | Kept: comment/docstring prose in a code, script or config file (no code edits in this docs-only change; can be reworded in a follow-up) |
| `.gitattributes` | 61 | 1 | (a) | Kept: comment/docstring prose in a code, script or config file (no code edits in this docs-only change; can be reworded in a follow-up) |
| `.github/AGENT_WORKFLOW_AUDIT.md` | 8 | 1 | (d) | Kept: historical record (ADR, recon snapshot, incident quote, dated verification or plan quoting the past state) |
| `.github/dependabot.yml` | 1 | 1 | (a) | Kept: comment/docstring prose in a code, script or config file (no code edits in this docs-only change; can be reworded in a follow-up) |
| `.github/scripts/test-stargazer-map.mjs` | 12, 37 | 2 | (a) | Kept: runtime value or compatibility name (asset name, executable, legacy slug, mutex, registry key, User-Agent, persistent name, fixture) |
| `.github/workflows/desktop-installers.yml` | 1, 15, 16 | 3 | (a) | Kept: comment/docstring prose in a code, script or config file (no code edits in this docs-only change; can be reworded in a follow-up) |
| `.github/workflows/desktop-installers.yml` | 187, 214, 216, 234, 266, 567, 568, 569, 570 | 9 | (a) | Kept: runtime value or compatibility name (asset name, executable, legacy slug, mutex, registry key, User-Agent, persistent name, fixture) |
| `.github/workflows/merge-train.yml` | 51 | 1 | (a) | Kept: comment/docstring prose in a code, script or config file (no code edits in this docs-only change; can be reworded in a follow-up) |
| `.github/workflows/release-smoke.yml` | 154, 165, 180 | 3 | (a) | Kept: runtime value or compatibility name (asset name, executable, legacy slug, mutex, registry key, User-Agent, persistent name, fixture) |
| `.github/workflows/release-wrapper-smoke.yml` | 9 | 1 | (a) | Kept: comment/docstring prose in a code, script or config file (no code edits in this docs-only change; can be reworded in a follow-up) |
| `.github/workflows/release-wrapper-smoke.yml` | 108, 116, 119, 136, 169, 177, 180, 197 | 8 | (a) | Kept: runtime value or compatibility name (asset name, executable, legacy slug, mutex, registry key, User-Agent, persistent name, fixture) |
| `.github/workflows/sign-installer.yml` | 1, 892 | 2 | (a) | Kept: comment/docstring prose in a code, script or config file (no code edits in this docs-only change; can be reworded in a follow-up) |
| `.gitignore` | 145, 146 | 2 | (a) | Kept: runtime value or compatibility name (asset name, executable, legacy slug, mutex, registry key, User-Agent, persistent name, fixture) |
| `.gitignore` | 436 | 1 | (a) | Kept: comment/docstring prose in a code, script or config file (no code edits in this docs-only change; can be reworded in a follow-up) |
| `.mailmap` | 14 | 1 | (a) | Kept: comment/docstring prose in a code, script or config file (no code edits in this docs-only change; can be reworded in a follow-up) |
| `.pre-commit-config.yaml` | 1 | 1 | (a) | Kept: comment/docstring prose in a code, script or config file (no code edits in this docs-only change; can be reworded in a follow-up) |
| `README.md` | 18 | 1 | (a) | Must stay: required by A2 of #850 (the one-time "Formerly Personal Jarvis" line) |
| `README.zh-CN.md` | 18 | 1 | (a) | Must stay: required by A2 of #850 (the one-time "Formerly Personal Jarvis" line) |
| `TRADEMARK.md` | 8 | 1 | (a) | Kept: legal / trademark text |
| `assets/brand/banner.html` | 3 | 1 | (a) | Kept: runtime value or compatibility name (asset name, executable, legacy slug, mutex, registry key, User-Agent, persistent name, fixture) |
| `assets/brand/how-dodaios-works-v2.prompt.txt` | 9, 11 | 2 | (a) | Kept: runtime value or compatibility name (asset name, executable, legacy slug, mutex, registry key, User-Agent, persistent name, fixture) |
| `assets/brand/social-preview.html` | 73 | 1 | (a) | Kept: runtime value or compatibility name (asset name, executable, legacy slug, mutex, registry key, User-Agent, persistent name, fixture) |
| `build.bat` | 2, 9 | 2 | (a) | Kept: comment/docstring prose in a code, script or config file (no code edits in this docs-only change; can be reworded in a follow-up) |
| `dev.bat` | 2 | 1 | (a) | Kept: comment/docstring prose in a code, script or config file (no code edits in this docs-only change; can be reworded in a follow-up) |
| `docs/adr/0015-obsidian-setup-wizard.md` | 15 | 1 | (d) | Kept: historical record (ADR, recon snapshot, incident quote, dated verification or plan quoting the past state) |
| `docs/ci-pipeline.md` | 286 | 1 | (a) | Kept: Name of the registered "PersonalJarvis Merge Bot" GitHub App |
| `docs/ci-pipeline.md` | 475, 478 | 2 | (a) | Kept: release asset, executable, bundle or install-path name that must keep working |
| `docs/code-signing-policy.md` | 6 | 1 | (a) | Kept: one-time "(formerly Personal Jarvis)" note added in this PR |
| `docs/code-signing-policy.md` | 16 | 1 | (a) | Kept: release asset, executable, bundle or install-path name that must keep working |
| `docs/code-signing-policy.md` | 96 | 1 | (a) | Kept: SignPath artifact configuration pins this file and product name |
| `docs/desktop-installers.md` | 26, 27 | 2 | (a) | Kept: release asset, executable, bundle or install-path name that must keep working |
| `docs/desktop-installers.md` | 55 | 1 | (a) | Kept: table row for the legacy `PersonalJarvis` executable (the current one, `DodaiosApp`, is listed above it) |
| `docs/desktop-installers.md` | 66 | 1 | (a) | Kept: names `PersonalJarvis` as the earlier executable name |
| `docs/desktop-installers.md` | 101, 298 | 2 | (a) | Kept: release asset, executable, bundle or install-path name that must keep working |
| `docs/desktop-installers.md` | 385 | 1 | (a) | Kept: install directory of upgraded installs keeps the old name; the line also names `Programs\Dodaios` |
| `docs/desktop-installers.md` | 411, 413 | 2 | (a) | Kept: release asset, executable, bundle or install-path name that must keep working |
| `docs/dodaios-board/RECON.md` | 162 | 1 | (d) | Kept: historical record (ADR, recon snapshot, incident quote, dated verification or plan quoting the past state) |
| `docs/dodaios-control-api.md` | 3 | 1 | (a) | Kept: one-time "(formerly Personal Jarvis)" note added in this PR |
| `docs/dodaios-control-api.md` | 33 | 1 | (a) | Kept: Code-signing requirement of the legacy macOS bundle |
| `docs/dodaios-learning.md` | 174, 183 | 2 | (d) | Kept: historical record (ADR, recon snapshot, incident quote, dated verification or plan quoting the past state) |
| `docs/legal/TERMS.md` | 3 | 1 | (a) | Kept: legal / trademark text |
| `docs/legal/TERMS.md` | 22 | 1 | (a) | Kept: live OAuth token-broker host the code calls (`_BROKER_BASE`); renaming it is a runtime change |
| `docs/macos-permissions.md` | 7 | 1 | (a) | Kept: one-time "(formerly Personal Jarvis)" note added in this PR |
| `docs/macos-permissions.md` | 869 | 1 | (a) | Kept: name macOS shows for an existing `Personal Jarvis.app` bundle (maintainer to confirm once every install has `Dodaios.app`) |
| `docs/marketplace/google-oauth-setup.md` | 4 | 1 | (a) | Kept: Name of the registered Google OAuth client; clarification "the former name of Dodaios" added |
| `docs/marketplace/google-oauth-setup.md` | 19, 42 | 2 | (a) | Kept: live OAuth token-broker host the code calls (`_BROKER_BASE`); renaming it is a runtime change |
| `docs/marketplace/microsoft-oauth-setup.md` | 9 | 1 | (a) | Kept: Name of the registered Entra app; clarification added |
| `docs/marketplace/microsoft-oauth-setup.md` | 27, 54 | 2 | (a) | Kept: Name of the registered Entra app, which users see on the sign-in screen |
| `docs/marketplace/plugin-auth-audit.md` | 25 | 1 | (d) | Kept: dated plugin auth audit record (names of registered OAuth apps) |
| `docs/marketplace/plugin-auth-audit.md` | 29 | 1 | (a) | Kept: live OAuth token-broker host the code calls (`_BROKER_BASE`); renaming it is a runtime change |
| `docs/marketplace/plugin-auth-audit.md` | 30, 33 | 2 | (d) | Kept: dated plugin auth audit record (names of registered OAuth apps) |
| `docs/marketplace/plugin-auth-audit.md` | 37, 38, 39, 48 | 4 | (a) | Kept: live OAuth token-broker host the code calls (`_BROKER_BASE`); renaming it is a runtime change |
| `docs/marketplace/plugin-auth-audit.md` | 50, 51, 52, 53, 54, 55, 57 | 7 | (d) | Kept: dated plugin auth audit record (names of registered OAuth apps) |
| `docs/marketplace/plugin-auth-audit.md` | 58, 64 | 2 | (a) | Kept: live OAuth token-broker host the code calls (`_BROKER_BASE`); renaming it is a runtime change |
| `docs/marketplace/plugin-auth-audit.md` | 103, 104 | 2 | (d) | Kept: dated plugin auth audit record (names of registered OAuth apps) |
| `docs/marketplace/plugin-auth-audit.md` | 106 | 1 | (a) | Kept: live OAuth token-broker host the code calls (`_BROKER_BASE`); renaming it is a runtime change |
| `docs/marketplace/plugin-e2e-audit.json` | 249 | 1 | (a) | Kept: live OAuth token-broker host the code calls (`_BROKER_BASE`); renaming it is a runtime change |
| `docs/marketplace/plugin-e2e-audit.json` | 261, 266, 300, 360, 365, 399 | 6 | (d) | Kept: dated plugin auth audit record (names of registered OAuth apps) |
| `docs/marketplace/plugin-e2e-audit.json` | 603, 653, 703, 1188, 1678, 1976 | 6 | (a) | Kept: live OAuth token-broker host the code calls (`_BROKER_BASE`); renaming it is a runtime change |
| `docs/marketplace/portable-skills.md` | 50 | 1 | (d) | Kept: historical record (ADR, recon snapshot, incident quote, dated verification or plan quoting the past state) |
| `docs/marketplace/publishing-plan.md` | 28, 29 | 2 | (d) | Kept: historical record (ADR, recon snapshot, incident quote, dated verification or plan quoting the past state) |
| `docs/os-parity.md` | 14 | 1 | (a) | Kept: release asset, executable, bundle or install-path name that must keep working |
| `docs/os-parity.md` | 1186 | 1 | (a) | Kept: Name of the existing per-user macOS signing certificate |
| `docs/os-parity.md` | 1433 | 1 | (d) | Kept: dated live-verification record of the Windows dev-instance identity |
| `docs/os-parity.md` | 1448 | 1 | (a) | Kept: release asset, executable, bundle or install-path name that must keep working |
| `docs/os-parity.md` | 1449 | 1 | (a) | Kept: `PersonalJarvis-macOS-*` asset names; the bundle name on this line now says `Dodaios.app` |
| `docs/os-parity.md` | 1450 | 1 | (a) | Kept: release asset, executable, bundle or install-path name that must keep working |
| `docs/product/privacy-safety-and-support/control-key.md` | 19 | 1 | (a) | Kept: one-time "(formerly Personal Jarvis)" note added in this PR |
| `docs/product/privacy-safety-and-support/control-key.md` | 192 | 1 | (a) | Kept: name macOS shows for an existing `Personal Jarvis.app` bundle (maintainer to confirm once every install has `Dodaios.app`) |
| `docs/product/privacy-safety-and-support/permissions.md` | 34, 123 | 2 | (a) | Kept: name macOS shows for an existing `Personal Jarvis.app` bundle (maintainer to confirm once every install has `Dodaios.app`) |
| `docs/product/privacy-safety-and-support/privacy-and-local-data.md` | 18 | 1 | (a) | Kept: one-time "(formerly Personal Jarvis)" note added in this PR |
| `docs/product/privacy-safety-and-support/privacy-and-local-data.md` | 105 | 1 | (a) | Kept: live OAuth token-broker host the code calls (`_BROKER_BASE`); renaming it is a runtime change |
| `docs/product/privacy-safety-and-support/troubleshooting.md` | 18 | 1 | (a) | Kept: one-time "(formerly Personal Jarvis)" note added in this PR |
| `docs/product/privacy-safety-and-support/troubleshooting.md` | 201 | 1 | (a) | Kept: name macOS shows for an existing `Personal Jarvis.app` bundle (maintainer to confirm once every install has `Dodaios.app`) |
| `docs/product/reference/platform-support.md` | 124 | 1 | (a) | Kept: name macOS shows for an existing `Personal Jarvis.app` bundle (maintainer to confirm once every install has `Dodaios.app`) |
| `docs/product/start-here/install-dodaios.md` | 187 | 1 | (a) | Kept: name macOS shows for an existing `Personal Jarvis.app` bundle (maintainer to confirm once every install has `Dodaios.app`) |
| `docs/supply-chain/red-team-log.md` | 35, 56, 86, 147, 167, 213, 223, 261, 275, 286, 326, 347, 392, 423, 464, 589, 689, 699 | 18 | (d) | Kept: supply-chain audit log / dated verification record |
| `docs/supply-chain/threat-model.md` | 1, 8, 18, 40, 44, 67, 83, 94, 152, 200, 250 | 11 | (d) | Kept: supply-chain audit log / dated verification record |
| `docs/supply-chain/wave2-community-tests.md` | 11, 35, 43, 108, 188 | 5 | (d) | Kept: supply-chain audit log / dated verification record |
| `docs/supply-chain/wave2-key-ceremony.md` | 30, 115, 131, 246, 248, 329, 353, 411, 445 | 9 | (d) | Kept: supply-chain audit log / dated verification record |
| `docs/supply-chain/wave3-community-tests.md` | 13, 38, 46, 137, 153, 155, 157, 159, 161, 163, 192, 203, 223, 239, 242 | 15 | (d) | Kept: supply-chain audit log / dated verification record |
| `docs/supply-chain/wave3-reproducibility-protocol.md` | 20, 333 | 2 | (d) | Kept: supply-chain audit log / dated verification record |
| `docs/supply-chain/wave4-distribution.md` | 3, 4, 24, 37, 54, 57 | 6 | (d) | Kept: supply-chain audit log / dated verification record |
| `docs/supply-chain/wave5-audit-fixes-validation.md` | 25, 29, 30, 160, 165, 207, 246, 301, 317, 327 | 10 | (d) | Kept: supply-chain audit log / dated verification record |
| `docs/supply-chain/wave5-original-audit.md` | 3, 98, 108, 128, 130 | 5 | (d) | Kept: supply-chain audit log / dated verification record |
| `dodaios.spec` | 1, 9, 20, 55 | 4 | (a) | Kept: comment/docstring prose in a code, script or config file (no code edits in this docs-only change; can be reworded in a follow-up) |
| `dodaios.spec` | 56, 438, 443, 446 | 4 | (a) | Kept: runtime value or compatibility name (asset name, executable, legacy slug, mutex, registry key, User-Agent, persistent name, fixture) |
| `dodaios/agent_screen/runner/sandbox_runner.ps1` | 1 | 1 | (a) | Kept: comment/docstring prose in a code, script or config file (no code edits in this docs-only change; can be reworded in a follow-up) |
| `dodaios/agentic_ide/drops.py` | 311 | 1 | (a) | Kept: runtime value or compatibility name (asset name, executable, legacy slug, mutex, registry key, User-Agent, persistent name, fixture) |
| `dodaios/agentic_ide/github_link.py` | 125 | 1 | (a) | Kept: runtime value or compatibility name (asset name, executable, legacy slug, mutex, registry key, User-Agent, persistent name, fixture) |
| `dodaios/agentic_ide/orchestration.py` | 547 | 1 | (a) | Kept: comment/docstring prose in a code, script or config file (no code edits in this docs-only change; can be reworded in a follow-up) |
| `dodaios/autostart/windows.py` | 89 | 1 | (a) | Kept: runtime value or compatibility name (asset name, executable, legacy slug, mutex, registry key, User-Agent, persistent name, fixture) |
| `dodaios/brain/identity.py` | 36 | 1 | (a) | Kept: runtime value or compatibility name (asset name, executable, legacy slug, mutex, registry key, User-Agent, persistent name, fixture) |
| `dodaios/clis/catalog/seed_catalog.json` | 2104 | 1 | (a) | Kept: runtime value or compatibility name (asset name, executable, legacy slug, mutex, registry key, User-Agent, persistent name, fixture) |
| `dodaios/codex_app_server.py` | 2668 | 1 | (a) | Kept: runtime value or compatibility name (asset name, executable, legacy slug, mutex, registry key, User-Agent, persistent name, fixture) |
| `dodaios/core/branding.py` | 35, 36, 245 | 3 | (a) | Kept: runtime value or compatibility name (asset name, executable, legacy slug, mutex, registry key, User-Agent, persistent name, fixture) |
| `dodaios/core/installer_update.py` | 14, 163, 164, 165, 168 | 5 | (a) | Kept: runtime value or compatibility name (asset name, executable, legacy slug, mutex, registry key, User-Agent, persistent name, fixture) |
| `dodaios/core/instance.py` | 161 | 1 | (a) | Kept: comment/docstring prose in a code, script or config file (no code edits in this docs-only change; can be reworded in a follow-up) |
| `dodaios/live/product.py` | 15 | 1 | (a) | Kept: runtime value or compatibility name (asset name, executable, legacy slug, mutex, registry key, User-Agent, persistent name, fixture) |
| `dodaios/marketplace/plugins/azure/plugin.json` | 42 | 1 | (a) | Kept: shipped plugin text naming the registered Microsoft Entra app "Personal Jarvis" that admins approve |
| `dodaios/marketplace/plugins/microsoft-todo/plugin.json` | 43 | 1 | (a) | Kept: shipped plugin text naming the registered Microsoft Entra app "Personal Jarvis" that admins approve |
| `dodaios/marketplace/plugins/onedrive/plugin.json` | 43 | 1 | (a) | Kept: shipped plugin text naming the registered Microsoft Entra app "Personal Jarvis" that admins approve |
| `dodaios/marketplace/plugins/onenote/plugin.json` | 43 | 1 | (a) | Kept: shipped plugin text naming the registered Microsoft Entra app "Personal Jarvis" that admins approve |
| `dodaios/marketplace/plugins/outlook/plugin.json` | 45 | 1 | (a) | Kept: shipped plugin text naming the registered Microsoft Entra app "Personal Jarvis" that admins approve |
| `dodaios/marketplace/plugins/sharepoint/plugin.json` | 44 | 1 | (a) | Kept: shipped plugin text naming the registered Microsoft Entra app "Personal Jarvis" that admins approve |
| `dodaios/marketplace/plugins/teams/plugin.json` | 45 | 1 | (a) | Kept: shipped plugin text naming the registered Microsoft Entra app "Personal Jarvis" that admins approve |
| `dodaios/marketplace/publisher_clients.py` | 60, 63, 66, 69, 72 | 5 | (a) | Kept: comment/docstring prose in a code, script or config file (no code edits in this docs-only change; can be reworded in a follow-up) |
| `dodaios/marketplace/publisher_clients.py` | 100 | 1 | (a) | Kept: live OAuth token-broker host the code calls (`_BROKER_BASE`); renaming it is a runtime change |
| `dodaios/marketplace/revoke.py` | 4 | 1 | (a) | Kept: runtime value or compatibility name (asset name, executable, legacy slug, mutex, registry key, User-Agent, persistent name, fixture) |
| `dodaios/marketplace/seed_catalog.json` | 749, 789, 831, 872, 912, 952, 1016 | 7 | (a) | Kept: shipped plugin text naming the registered Microsoft Entra app "Personal Jarvis" that admins approve |
| `dodaios/marketplace/usage_cards/azure.md` | 13 | 1 | (a) | Kept: shipped plugin text naming the registered Microsoft Entra app "Personal Jarvis" that admins approve |
| `dodaios/marketplace/usage_cards/microsoft_todo.md` | 13 | 1 | (a) | Kept: shipped plugin text naming the registered Microsoft Entra app "Personal Jarvis" that admins approve |
| `dodaios/marketplace/usage_cards/onedrive.md` | 13 | 1 | (a) | Kept: shipped plugin text naming the registered Microsoft Entra app "Personal Jarvis" that admins approve |
| `dodaios/marketplace/usage_cards/onenote.md` | 13 | 1 | (a) | Kept: shipped plugin text naming the registered Microsoft Entra app "Personal Jarvis" that admins approve |
| `dodaios/marketplace/usage_cards/outlook.md` | 13 | 1 | (a) | Kept: shipped plugin text naming the registered Microsoft Entra app "Personal Jarvis" that admins approve |
| `dodaios/marketplace/usage_cards/sharepoint.md` | 13 | 1 | (a) | Kept: shipped plugin text naming the registered Microsoft Entra app "Personal Jarvis" that admins approve |
| `dodaios/marketplace/usage_cards/teams.md` | 13 | 1 | (a) | Kept: shipped plugin text naming the registered Microsoft Entra app "Personal Jarvis" that admins approve |
| `dodaios/memory/schema.sql` | 1 | 1 | (a) | Kept: comment/docstring prose in a code, script or config file (no code edits in this docs-only change; can be reworded in a follow-up) |
| `dodaios/memory/wiki/session_links.py` | 137 | 1 | (a) | Kept: comment/docstring prose in a code, script or config file (no code edits in this docs-only change; can be reworded in a follow-up) |
| `dodaios/memory/wiki/session_links.py` | 149 | 1 | (a) | Kept: runtime value or compatibility name (asset name, executable, legacy slug, mutex, registry key, User-Agent, persistent name, fixture) |
| `dodaios/platform/macos_input_source.py` | 7 | 1 | (a) | Kept: runtime value or compatibility name (asset name, executable, legacy slug, mutex, registry key, User-Agent, persistent name, fixture) |
| `dodaios/plugins/tool/calendar_bot.mjs` | 4 | 1 | (a) | Kept: comment/docstring prose in a code, script or config file (no code edits in this docs-only change; can be reworded in a follow-up) |
| `dodaios/setup/cli_path.py` | 53 | 1 | (a) | Kept: comment/docstring prose in a code, script or config file (no code edits in this docs-only change; can be reworded in a follow-up) |
| `dodaios/setup/desktop_integration.py` | 333 | 1 | (a) | Kept: runtime value or compatibility name (asset name, executable, legacy slug, mutex, registry key, User-Agent, persistent name, fixture) |
| `dodaios/setup/macos_signing_identity.py` | 44 | 1 | (a) | Kept: comment/docstring prose in a code, script or config file (no code edits in this docs-only change; can be reworded in a follow-up) |
| `dodaios/setup/macos_stub_launcher.c` | 8 | 1 | (a) | Kept: comment/docstring prose in a code, script or config file (no code edits in this docs-only change; can be reworded in a follow-up) |
| `dodaios/setup/onboarding_meta.py` | 59 | 1 | (a) | Kept: live OAuth token-broker host the code calls (`_BROKER_BASE`); renaming it is a runtime change |
| `dodaios/setup/wizard.py` | 1211 | 1 | (a) | Kept: live OAuth token-broker host the code calls (`_BROKER_BASE`); renaming it is a runtime change |
| `dodaios/skills/builtin/plugin-azure/SKILL.md` | 22 | 1 | (a) | Kept: shipped plugin text naming the registered Microsoft Entra app "Personal Jarvis" that admins approve |
| `dodaios/skills/builtin/plugin-microsoft_todo/SKILL.md` | 22 | 1 | (a) | Kept: shipped plugin text naming the registered Microsoft Entra app "Personal Jarvis" that admins approve |
| `dodaios/skills/builtin/plugin-onedrive/SKILL.md` | 22 | 1 | (a) | Kept: shipped plugin text naming the registered Microsoft Entra app "Personal Jarvis" that admins approve |
| `dodaios/skills/builtin/plugin-onenote/SKILL.md` | 22 | 1 | (a) | Kept: shipped plugin text naming the registered Microsoft Entra app "Personal Jarvis" that admins approve |
| `dodaios/skills/builtin/plugin-outlook/SKILL.md` | 22 | 1 | (a) | Kept: shipped plugin text naming the registered Microsoft Entra app "Personal Jarvis" that admins approve |
| `dodaios/skills/builtin/plugin-sharepoint/SKILL.md` | 22 | 1 | (a) | Kept: shipped plugin text naming the registered Microsoft Entra app "Personal Jarvis" that admins approve |
| `dodaios/skills/builtin/plugin-teams/SKILL.md` | 22 | 1 | (a) | Kept: shipped plugin text naming the registered Microsoft Entra app "Personal Jarvis" that admins approve |
| `dodaios/ui/desktop_app.py` | 6701 | 1 | (a) | Kept: comment/docstring prose in a code, script or config file (no code edits in this docs-only change; can be reworded in a follow-up) |
| `dodaios/ui/web/dist/assets/index-D0oKD7Wa.js` | 52 | 1 | (a) | Kept: built frontend bundle (generated) |
| `dodaios/ui/web/feedback_routes.py` | 381 | 1 | (a) | Kept: runtime value or compatibility name (asset name, executable, legacy slug, mutex, registry key, User-Agent, persistent name, fixture) |
| `dodaios/ui/web/frontend/src/__tests__/topbarUpdateButton.test.tsx` | 483, 524 | 2 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `dodaios/ui/web/frontend/src/__tests__/voiceBrandName.test.tsx` | 116 | 1 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `dodaios/ui/web/frontend/src/components/ToastLayer.test.tsx` | 31, 40 | 2 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `dodaios/ui/web/frontend/src/components/agentic/IdeProjectTree.panedrop.test.tsx` | 36 | 1 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `dodaios/ui/web/frontend/src/components/agentic/IdeProjectTree.project-reorder.test.tsx` | 63, 125 | 2 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `dodaios/ui/web/frontend/src/components/agentic/PaneChat.test.tsx` | 88, 164 | 2 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `dodaios/ui/web/frontend/src/components/agentic/PaneNotifications.test.tsx` | 47, 128 | 2 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `dodaios/ui/web/frontend/src/components/agentic/WorkspaceChats.test.tsx` | 23, 35, 93, 95, 115 | 5 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `dodaios/ui/web/frontend/src/components/agentic/WorkspaceTerminalGrid.transfer.test.tsx` | 47, 78, 133 | 3 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `dodaios/ui/web/frontend/src/components/agentic/explorerDrag.test.ts` | 26, 27, 57, 77, 84 | 5 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `dodaios/ui/web/frontend/src/components/layout/CodingModeBadge.test.tsx` | 25, 33 | 2 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `dodaios/ui/web/frontend/src/components/society/crewFeeds/codingFloor.test.ts` | 20, 67, 77 | 3 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `dodaios/ui/web/frontend/src/store/paneChat.test.ts` | 98, 196 | 2 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `dodaios/ui/web/frontend/src/store/workspacePanes.test.ts` | 21, 22 | 2 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `dodaios/ui/web/frontend/src/views/AssistantProfileView.test.tsx` | 28 | 1 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `dodaios/ui/web/frontend/src/views/settings/AppSettingsGroup.test.tsx` | 30, 44, 59 | 3 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `dodaios/ui/web/update_routes.py` | 442 | 1 | (a) | Kept: runtime value or compatibility name (asset name, executable, legacy slug, mutex, registry key, User-Agent, persistent name, fixture) |
| `install/README.md` | 41 | 1 | (a) | Kept: names the old `Personal Jarvis.app` bundle the installer renames once; the current bundle is `Dodaios.app` |
| `install/install-verify.ps1` | 1 | 1 | (a) | Kept: comment/docstring prose in a code, script or config file (no code edits in this docs-only change; can be reworded in a follow-up) |
| `install/install-verify.sh` | 2 | 1 | (a) | Kept: comment/docstring prose in a code, script or config file (no code edits in this docs-only change; can be reworded in a follow-up) |
| `install/install.ps1` | 1 | 1 | (a) | Kept: comment/docstring prose in a code, script or config file (no code edits in this docs-only change; can be reworded in a follow-up) |
| `install/install.ps1` | 224 | 1 | (a) | Kept: runtime value or compatibility name (asset name, executable, legacy slug, mutex, registry key, User-Agent, persistent name, fixture) |
| `install/install.sh` | 2 | 1 | (a) | Kept: comment/docstring prose in a code, script or config file (no code edits in this docs-only change; can be reworded in a follow-up) |
| `install/install.sh` | 57 | 1 | (a) | Kept: runtime value or compatibility name (asset name, executable, legacy slug, mutex, registry key, User-Agent, persistent name, fixture) |
| `install/installer.py` | 1 | 1 | (a) | Kept: comment/docstring prose in a code, script or config file (no code edits in this docs-only change; can be reworded in a follow-up) |
| `install/uninstall.ps1` | 1 | 1 | (a) | Kept: comment/docstring prose in a code, script or config file (no code edits in this docs-only change; can be reworded in a follow-up) |
| `install/uninstall.ps1` | 69, 70, 71 | 3 | (a) | Kept: runtime value or compatibility name (asset name, executable, legacy slug, mutex, registry key, User-Agent, persistent name, fixture) |
| `install/uninstall.sh` | 2 | 1 | (a) | Kept: comment/docstring prose in a code, script or config file (no code edits in this docs-only change; can be reworded in a follow-up) |
| `install/uninstall.sh` | 29 | 1 | (a) | Kept: runtime value or compatibility name (asset name, executable, legacy slug, mutex, registry key, User-Agent, persistent name, fixture) |
| `packaging/README.md` | 9 | 1 | (a) | Kept: release asset, executable, bundle or install-path name that must keep working |
| `packaging/README.md` | 22 | 1 | (a) | Kept: the launcher is also built as `PersonalJarvis` for old pins; the line explains that name |
| `packaging/linux/README.md` | 7, 141, 149, 161 | 4 | (a) | Kept: release asset, executable, bundle or install-path name that must keep working |
| `packaging/linux/build.sh` | 14, 158 | 2 | (a) | Kept: comment/docstring prose in a code, script or config file (no code edits in this docs-only change; can be reworded in a follow-up) |
| `packaging/linux/build.sh` | 159 | 1 | (a) | Kept: runtime value or compatibility name (asset name, executable, legacy slug, mutex, registry key, User-Agent, persistent name, fixture) |
| `packaging/macos/build.sh` | 11 | 1 | (a) | Kept: comment/docstring prose in a code, script or config file (no code edits in this docs-only change; can be reworded in a follow-up) |
| `packaging/native-crypto.json` | 16 | 1 | (d) | Kept: provenance record of a past build run (GitHub redirects the URL) |
| `packaging/pyinstaller_rthook_frozen.py` | 64, 70, 71 | 3 | (a) | Kept: runtime value or compatibility name (asset name, executable, legacy slug, mutex, registry key, User-Agent, persistent name, fixture) |
| `packaging/windows/Dodaios.iss` | 1, 22, 25, 56, 59, 63, 68, 95 | 8 | (a) | Kept: comment/docstring prose in a code, script or config file (no code edits in this docs-only change; can be reworded in a follow-up) |
| `packaging/windows/Dodaios.iss` | 231, 232 | 2 | (a) | Kept: runtime value or compatibility name (asset name, executable, legacy slug, mutex, registry key, User-Agent, persistent name, fixture) |
| `packaging/windows/build.ps1` | 4, 13, 16, 99, 160, 217 | 6 | (a) | Kept: runtime value or compatibility name (asset name, executable, legacy slug, mutex, registry key, User-Agent, persistent name, fixture) |
| `pyproject.toml` | 518 | 1 | (a) | Kept: comment/docstring prose in a code, script or config file (no code edits in this docs-only change; can be reworded in a follow-up) |
| `requirements.in` | 1 | 1 | (a) | Kept: comment/docstring prose in a code, script or config file (no code edits in this docs-only change; can be reworded in a follow-up) |
| `run-dev.bat` | 2, 5 | 2 | (a) | Kept: comment/docstring prose in a code, script or config file (no code edits in this docs-only change; can be reworded in a follow-up) |
| `run-dev.sh` | 2, 5 | 2 | (a) | Kept: comment/docstring prose in a code, script or config file (no code edits in this docs-only change; can be reworded in a follow-up) |
| `run.bat` | 2 | 1 | (a) | Kept: comment/docstring prose in a code, script or config file (no code edits in this docs-only change; can be reworded in a follow-up) |
| `run.sh` | 2 | 1 | (a) | Kept: comment/docstring prose in a code, script or config file (no code edits in this docs-only change; can be reworded in a follow-up) |
| `scripts/README-auto-push.md` | 21, 27, 35, 49, 55, 67, 100 | 7 | (a) | Kept: the maintainer's real local checkout path |
| `scripts/auto-push-eod.ps1` | 20, 43, 340, 350 | 4 | (a) | Kept: runtime value or compatibility name (asset name, executable, legacy slug, mutex, registry key, User-Agent, persistent name, fixture) |
| `scripts/brand-preview/contributing.html` | 6 | 1 | (a) | Kept: runtime value or compatibility name (asset name, executable, legacy slug, mutex, registry key, User-Agent, persistent name, fixture) |
| `scripts/brand-preview/hero.html` | 6, 38 | 2 | (a) | Kept: runtime value or compatibility name (asset name, executable, legacy slug, mutex, registry key, User-Agent, persistent name, fixture) |
| `scripts/brand-preview/index.html` | 6 | 1 | (a) | Kept: runtime value or compatibility name (asset name, executable, legacy slug, mutex, registry key, User-Agent, persistent name, fixture) |
| `scripts/brand-preview/readme.html` | 6 | 1 | (a) | Kept: runtime value or compatibility name (asset name, executable, legacy slug, mutex, registry key, User-Agent, persistent name, fixture) |
| `scripts/brand-preview/shot.ps1` | 17 | 1 | (a) | Kept: runtime value or compatibility name (asset name, executable, legacy slug, mutex, registry key, User-Agent, persistent name, fixture) |
| `scripts/ci/check_release_completeness.py` | 219 | 1 | (a) | Kept: runtime value or compatibility name (asset name, executable, legacy slug, mutex, registry key, User-Agent, persistent name, fixture) |
| `scripts/ci/installer_aliases.py` | 6 | 1 | (a) | Kept: runtime value or compatibility name (asset name, executable, legacy slug, mutex, registry key, User-Agent, persistent name, fixture) |
| `scripts/ci/privacy_gate/references/distribution-denylist.txt` | 33 | 1 | (a) | Kept: comment/docstring prose in a code, script or config file (no code edits in this docs-only change; can be reworded in a follow-up) |
| `scripts/ci/privacy_pre_push.py` | 12 | 1 | (a) | Kept: runtime value or compatibility name (asset name, executable, legacy slug, mutex, registry key, User-Agent, persistent name, fixture) |
| `scripts/ci/release_assets.py` | 35, 36, 37, 38, 71, 72, 76, 77 | 8 | (a) | Kept: runtime value or compatibility name (asset name, executable, legacy slug, mutex, registry key, User-Agent, persistent name, fixture) |
| `scripts/dodaios-config-drift-guard.ps1` | 434 | 1 | (a) | Kept: runtime value or compatibility name (asset name, executable, legacy slug, mutex, registry key, User-Agent, persistent name, fixture) |
| `scripts/drift-guard-daemon.ps1` | 16, 32 | 2 | (a) | Kept: runtime value or compatibility name (asset name, executable, legacy slug, mutex, registry key, User-Agent, persistent name, fixture) |
| `scripts/install-auto-push-task.ps1` | 15, 25 | 2 | (a) | Kept: runtime value or compatibility name (asset name, executable, legacy slug, mutex, registry key, User-Agent, persistent name, fixture) |
| `scripts/install-config-drift-guard-task.ps1` | 17, 29 | 2 | (a) | Kept: runtime value or compatibility name (asset name, executable, legacy slug, mutex, registry key, User-Agent, persistent name, fixture) |
| `scripts/make_app_icon.py` | 1 | 1 | (a) | Kept: comment/docstring prose in a code, script or config file (no code edits in this docs-only change; can be reworded in a follow-up) |
| `scripts/measure_boot.py` | 2 | 1 | (a) | Kept: comment/docstring prose in a code, script or config file (no code edits in this docs-only change; can be reworded in a follow-up) |
| `scripts/measure_desktop_boot.py` | 2 | 1 | (a) | Kept: comment/docstring prose in a code, script or config file (no code edits in this docs-only change; can be reworded in a follow-up) |
| `scripts/preflight.ps1` | 9 | 1 | (a) | Kept: runtime value or compatibility name (asset name, executable, legacy slug, mutex, registry key, User-Agent, persistent name, fixture) |
| `scripts/sandbox/new-dodaios-sandbox.ps1` | 3, 79 | 2 | (a) | Kept: runtime value or compatibility name (asset name, executable, legacy slug, mutex, registry key, User-Agent, persistent name, fixture) |
| `tests/conftest.py` | 210 | 1 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/ui/test_taskbar_pin_repair.py` | 23, 53 | 2 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `.github/workflows/frontend-bundle.yml` | 18 | 1 | (a) | Kept: name of the registered GitHub App ("PersonalJarvis Merge Bot") |
| `assets/demo/readme/README.md` | 11 | 1 | (a) | Kept: describes what the pre-rename Code by talking recording shows and says |
| `tests/contract/test_agent_template_share.py` | 96 | 1 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/contract/test_coding_image_handoff.py` | 170, 172 | 2 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/contract/test_live_product_knowledge.py` | 1 | 1 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/contract/test_workspace_dispatch_isolation.py` | 41, 107, 359, 463, 469, 474, 495, 529, 546, 562, 589 | 11 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/contract/test_workspace_orchestration.py` | 80, 139, 302, 316, 393, 399, 555, 562, 606, 622, 654, 689, 696, 711, 727, 990 | 16 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/contract/test_workspace_runtime_compatibility.py` | 24 | 1 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/integration/memory/test_three_triggers.py` | 236 | 1 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/integration/test_soul_routes.py` | 143, 154 | 2 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/integration/test_update_handover_real_os.py` | 16, 92, 124, 129, 188, 210, 212, 215, 218, 221, 223, 235, 240, 241, 254, 317, 333, 359, 383 | 19 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/integration/test_voice_mission_e2e_chatgpt.py` | 3 | 1 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/integration/test_web_surface_security.py` | 1 | 1 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/missions/test_injection_scanner.py` | 103 | 1 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/admin/test_executor_winget.py` | 168 | 1 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/agentic_ide/test_cli_title.py` | 79, 86, 91, 98, 99 | 5 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/agentic_ide/test_pane_notifications.py` | 53, 63 | 2 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/agentic_ide/test_recap.py` | 147 | 1 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/autostart/test_command.py` | 36 | 1 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/autostart/test_linux.py` | 20, 333 | 2 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/autostart/test_macos.py` | 22, 42, 116, 117 | 4 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/autostart/test_moved_install_paths.py` | 170 | 1 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/autostart/test_windows_scripts.py` | 25, 31, 34, 47, 84, 85, 91, 116, 127 | 9 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/autostart/test_windows_task.py` | 45, 65, 122, 127, 136, 181, 689 | 7 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/brain/test_computer_use_offload.py` | 508, 522, 556, 572 | 4 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/brain/test_identity.py` | 46, 54, 62, 115 | 4 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/brain/test_local_outcome_gate.py` | 22 | 1 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/brain/test_wiki_context_relevance.py` | 21 | 1 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/brain/test_wiki_language_bridge.py` | 32 | 1 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/brain/test_wiki_relevance.py` | 118 | 1 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/ci/test_check_frozen_macos_app.py` | 37, 47, 49, 60, 68, 76, 92 | 7 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/ci/test_flaky_report.py` | 12, 13, 142 | 3 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/ci/test_installer_aliases.py` | 55, 80, 81, 83 | 4 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/ci/test_privacy_pre_push.py` | 73, 82, 274 | 3 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/ci/test_release_smoke.py` | 32, 35, 92, 125, 170, 252 | 6 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/ci/test_rewrite_package.py` | 165, 587, 981 | 3 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/cli/test_command_name.py` | 38, 55 | 2 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/cli_ctl/test_commands_marketplace.py` | 28, 39 | 2 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/cli_ctl/test_commands_permissions.py` | 163, 245, 405, 475 | 4 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/computers/test_cloud_and_routes.py` | 28 | 1 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/core/test_background_service.py` | 416 | 1 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/core/test_branding.py` | 17, 18, 20, 23, 34, 56, 57, 59, 62, 64, 66, 68, 70, 73, 75, 76, 78, 82, 84, 97, 198 | 21 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/core/test_control_key.py` | 206, 207, 250, 251 | 4 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/core/test_desktop_entry.py` | 110, 112, 139, 143 | 4 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/core/test_identity_single_source.py` | 307, 671, 685, 687, 698, 749 | 6 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/core/test_installer_update.py` | 78, 79, 80, 81, 82, 83, 108, 109, 114, 120, 121, 122, 126, 174, 193, 215, 216, 219, 220, 227, 229, 234, 243, 253, 268, 270, 282, 303, 325, 327, 346, 363, 377, 390, 402, 432, 482, 489, 520, 522, 524, 526, 531, 539, 543, 545, 547, 555, 560, 574, 591, 606, 637, 662, 677, 709, 815, 836, 839, 856, 870, 884, 898, 915, 917, 919, 930, 936, 995, 1019, 1050, 1087, 1111, 1175, 1195, 1212, 1214, 1230, 1232, 1238, 1250, 1256, 1258, 1260, 1273, 1279, 1290, 1306, 1325, 1339, 1373, 1374, 1376, 1392, 1395, 1398, 1410, 1424 | 98 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/core/test_installer_update_http.py` | 36, 39 | 2 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/core/test_instance.py` | 104, 105, 110, 112, 114 | 5 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/core/test_spoken_names.py` | 28 | 1 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/core/test_update_contract.py` | 376, 386 | 2 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/cu/test_system_dialogs.py` | 54, 153, 154, 155 | 4 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/diagnostics/test_doctor_diagnostics.py` | 227 | 1 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/dictation/test_local_preview.py` | 455, 464, 484, 504 | 4 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/harness/test_cu_control_events.py` | 239 | 1 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/install/test_linux_entry_rename.py` | 77 | 1 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/marketplace/test_agent_plugins_loader.py` | 82 | 1 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/marketplace/test_catalog_seed.py` | 354, 359, 364 | 3 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/marketplace/test_community_agents.py` | 48 | 1 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/marketplace/test_community_contents.py` | 38, 68 | 2 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/marketplace/test_community_install_kinds.py` | 56 | 1 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/marketplace/test_community_routes.py` | 52, 78 | 2 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/marketplace/test_publish_issue.py` | 80, 89, 100, 105, 117, 133, 148 | 7 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/marketplace/test_token_broker.py` | 200 | 1 | (a) | Kept: live OAuth token-broker host the code calls (`_BROKER_BASE`); renaming it is a runtime change |
| `tests/unit/memory/learning/test_soul_learning.py` | 68, 75, 79 | 3 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/memory/wiki/test_fts_index.py` | 95, 292 | 2 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/memory/wiki/test_profile.py` | 65 | 1 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/memory/wiki/test_session_links.py` | 83, 98, 117, 119, 146, 148, 187, 194, 201 | 9 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/packaging/test_frozen_runtime_hook.py` | 184 | 1 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/packaging/test_linux_identity.py` | 156, 198, 204 | 3 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/packaging/test_macos_privacy_strings.py` | 499 | 1 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/packaging/test_spec_console_executables.py` | 4 | 1 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/platform/test_music_player.py` | 213 | 1 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/platform/test_permission_service_hardening.py` | 910 | 1 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/platform/test_permission_service_status_helpers.py` | 78, 272 | 2 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/platform/test_permissions.py` | 32, 172, 601, 629, 646, 668, 692 | 7 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/platform/test_permissions_state_api.py` | 41, 49, 50, 778, 1040, 1049, 1057, 1065, 1072, 1080 | 10 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/plugins/tool/test_delegate_to_agent.py` | 469 | 1 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/plugins/tool/test_wiki_list.py` | 39, 100 | 2 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/realtime/test_session.py` | 2862, 2872 | 2 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/scripts/test_check_public_docs_contract.py` | 15 | 1 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/self_mod/fixtures/minimal_dodaios.toml` | 1 | 1 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/self_mod/test_writer.py` | 204, 216 | 2 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/sessions/test_chat_titles.py` | 49, 50 | 2 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/setup/test_cli_path.py` | 267, 272 | 2 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/setup/test_desktop_integration.py` | 204, 266, 267, 364, 365, 387, 392, 399, 400 | 9 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/setup/test_macos_app_bundle.py` | 227, 342, 347, 595, 597, 607, 608, 1002 | 8 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/setup/test_macos_app_location.py` | 34, 88, 99, 216 | 4 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/setup/test_macos_app_rename.py` | 3, 67 | 2 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/setup/test_macos_dock.py` | 22 | 1 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/setup/test_macos_search_index.py` | 3, 98, 107, 117, 129, 139, 156, 177, 195, 206, 259, 270, 275, 287 | 14 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/setup/test_onboarding_meta.py` | 46 | 1 | (a) | Kept: live OAuth token-broker host the code calls (`_BROKER_BASE`); renaming it is a runtime change |
| `tests/unit/setup/test_wizard_terms.py` | 61 | 1 | (a) | Kept: live OAuth token-broker host the code calls (`_BROKER_BASE`); renaming it is a runtime change |
| `tests/unit/skills/test_finder_community_pool.py` | 25 | 1 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/society/test_agent_names.py` | 143, 146 | 2 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/speech/test_wake_dead_state.py` | 328 | 1 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/test_config_writer.py` | 40, 69 | 2 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/test_config_writer_brain_primary_sync.py` | 36 | 1 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/test_config_writer_brain_provider_model_sync.py` | 37 | 1 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/test_config_writer_computer_use_sync.py` | 36 | 1 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/test_config_writer_stt_sync.py` | 34 | 1 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/test_config_writer_tts_sync.py` | 39, 303 | 2 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/test_config_writer_worker_sync.py` | 38 | 1 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/ui/test_desktop_discoverability.py` | 131, 152 | 2 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/ui/test_icon_identity.py` | 15, 35, 171, 187, 192, 206, 245 | 7 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/ui/test_icon_window_ownership.py` | 48 | 1 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/ui/test_msix_redirection.py` | 45, 57, 63, 67, 72, 79, 95, 123, 138, 147, 161 | 11 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/ui/test_onboarding_routes.py` | 49 | 1 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/ui/test_relaunch_properties.py` | 50 | 1 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/ui/test_relauncher.py` | 28 | 1 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/ui/test_relauncher_frozen.py` | 5, 52, 55, 62, 73, 76, 79, 87, 101, 107, 109, 110, 116, 117, 121, 122, 132 | 17 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/ui/test_relauncher_update_contract.py` | 1134 | 1 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/ui/test_restart_launch_context.py` | 59 | 1 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/ui/test_start_menu_shortcut_target.py` | 31, 141, 149, 161, 178, 296, 343, 552 | 8 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/ui/web/test_permissions_snapshot.py` | 508, 511 | 2 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/ui/web/test_update_routes.py` | 80, 81, 87, 265, 328 | 5 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/ui/web/test_update_routes_frozen.py` | 31, 325, 544 | 3 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/voice/test_action_phrases.py` | 222, 629 | 2 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/web/test_local_only_install_has_every_tier.py` | 3 | 1 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `tests/unit/web/test_update_progress_route.py` | 169, 172 | 2 | (a) | Kept: test fixture or assertion of compatibility / legacy-name handling |
| `wiki/obsidian-vault/.obsidian/themes/Minimal/manifest.json` | 5 | 1 | (a) | Kept: cosmetic author field of the Obsidian theme manifest in `wiki/obsidian-vault`; left unchanged because this change touches only docs |
