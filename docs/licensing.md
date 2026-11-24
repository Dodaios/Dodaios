# Licensing

## Current: MIT License

Dodaios project code is licensed under the [MIT License](../LICENSE),
starting with version 5.7.0. The attribution notice for adapted and bundled
work is in [`NOTICE`](../NOTICE). Third-party code, fonts, models, images, and
native libraries retain their own licenses.

MIT permits use, modification, and distribution, including commercial
distribution, on one condition: the copyright notice and the permission notice
are kept in all copies or substantial portions. This describes the project
code; bundled dependencies can impose additional obligations. MIT grants
rights in the code only, not in the name or the logo; those are covered by
[`TRADEMARK.md`](legal/TRADEMARK.md).

## Earlier releases keep their license, permanently

| Releases | License |
|----------|---------|
| up to and including 1.6.0 | MIT License |
| 2.0.0 up to and including 5.6.0 | Apache License 2.0 |
| from 5.7.0 on | MIT License |

A license cannot be revoked for a copy already obtained under it: that copy
keeps those rights forever, including the right to fork it. The texts those
releases shipped with are still in the history — `git show v1.6.0:LICENSE`,
`git show v5.6.0:LICENSE`.

A copy of a 2.0.0 to 5.6.0 release carries the terms of Apache 2.0: its
explicit patent grant (§3), its trademark carve-out (§6), and its
redistribution duties (§4: pass on the license, keep the notices, carry the
`NOTICE` file, mark the files you changed). MIT contains no equivalent express
patent grant.

## What it means for you

- **Users:** nothing to do.
- **Forks and redistributors:** anything you took from a release keeps that
  release's license (table above). From 5.7.0 on, keep `LICENSE`, the MIT
  copyright and permission notice, with your copies; carrying `NOTICE` along
  keeps the credits for the adapted third-party work.
- **Contributors:** by opening a pull request you agree your work is licensed to
  the project under the MIT License.

## What does NOT need changing

A license change applies going forward. It does not make past statements wrong,
and it creates no duty to hunt them down:

- **Videos, talks, streams, and old posts that name an earlier license.** They
  described the releases that existed when they were recorded, and for those
  releases the statement is still true. Leave them up. Adding a line to the
  description of the most-watched ones ("from 5.7 on: MIT") is courtesy, not a
  correction — taking them offline would look like something was wrong when
  nothing was.
- **Anything already downloaded, forked, or vendored.** It keeps the license it
  was obtained under, and no one has to be told.
- **Blog posts, press coverage, and third-party listings.** Not yours to fix.

What does have to be current is anything that states the license **as of
today**: this repository, package listings, app-store
descriptions, and pinned posts. Those are the checklist below.

## Third-party components

The warranty and liability disclaimers in an open-source license do not replace
its redistribution conditions. The project license also does not grant rights
in another party's trademarks. The project name and the assistant name chosen
by a user are separate labels; choosing an assistant name does not change any
bundled component's license.

### What builds from the corrected source include

The following describes the packaging corrections accompanying the linked
artifact audit. Previously published installers retain their original contents
until a separately verified release is published.

- The Python wheel carries the project and vendored component licenses in its
  distribution metadata. The desktop bundle also includes the `third_party/`
  license texts referenced by `NOTICE`.
- Each frontend build emits `THIRD_PARTY_NOTICES.txt` alongside its assets. It
  contains complete license texts for bundled packages and fonts, plus notices
  for copied source and artwork. These notices travel with the frontend in
  wheels and desktop bundles.
- The current onboarding terms are included in both wheel and desktop layouts.
  They describe the optional project-operated OAuth token broker as well as
  directly connected third-party services.

License files document permissions and conditions; they do not by themselves
prove that a particular native binary satisfies every condition. A source
checkout, a dependency installed by the user, and a frozen installer are
different distribution artifacts and must be assessed separately.

### Native libraries and models

Inspect the exact binaries in each release, including their transitive native
dependencies. In particular:

- `sherpa-onnx` has an Apache-2.0 top-level license, but some native builds
  include GPL-licensed eSpeak through `piper-phonemize`. Selecting sherpa rather
  than `piper1-gpl` does not establish that a distribution is free of GPL
  obligations. See the [upstream dependency discussion](https://github.com/k2-fsa/sherpa-onnx/issues/3731).
- PyAV's source license does not cover all bundled FFmpeg and codec binaries.
  Review the exact wheel's FFmpeg build options, external codecs, and any
  documented license exceptions. Preserve the notices and corresponding source
  or other materials required by the selected license route. See
  [FFmpeg's licensing guidance](https://ffmpeg.org/legal.html) and the
  [PyAV wheel discussion](https://github.com/PyAV-Org/PyAV/issues/2270).
- Downloaded voice and wake models have licenses separate from the engine that
  loads them. Record the model source, version, and applicable terms.

Keep an artifact-level inventory of component versions, file hashes, licenses,
upstream source/build references, and unresolved permissions. Claims of
commercial exceptions require the applicable grant, not only a package label
or a link to a vendor's sales page. Public source for this project alone is
not a substitute for the corresponding source of bundled third-party binaries.

The [v2.9.0 artifact inspection](legal/distribution-audit-2026-10-08.md)
records verified Windows and Linux package identities, observed components,
missing notices, and the limits of that inspection.

### Adapted source

The bundled Silero VAD model (`dodaios/assets/vad/`) carries its own MIT license
from its own authors and keeps it — the switch does not touch it, and no
dependency's terms change either. Nothing is relicensed by being included here.

The Agentic IDE thread work log contains portions adapted from
[T3 Code](https://github.com/pingdotgg/t3code) @ `e22c880`, MIT License,
Copyright (c) 2026 T3 Tools Inc. The full text ships in
[`third_party/t3code/LICENSE`](../third_party/t3code/LICENSE), and every adapted
file names its source in a header comment.

The Computers settings page (`dodaios/ui/web/frontend/src/views/computers/surface.tsx`
and `ComputerRow.tsx`) contains portions of the settings layout, environment row,
status dot and empty state adapted from T3 Code @ `12069ee` under the same MIT
license; both files name their source in a header comment. The connection features of the same page — several addresses per computer, the SSH-config and Tailscale suggestions, the on/off switch, automatic placement and GitHub sharing (`dodaios/computers/ssh_config.py`, `tailscale.py`, `placement.py`, `github_access.py`; `views/computers/RouteList.tsx`, `Placement.tsx`, `GithubAccess.tsx`, `machineKind.tsx`) — adapt further portions of T3 Code @ `12069ee`, each credited the same way.

The Agentic IDE explorer's coloured file-type icons
(`dodaios/ui/web/frontend/src/components/agentic/sidePanel/explorer/fileIconSprite.ts`
and `fileIcon.ts`) contain SVG symbols and file-name rules copied from
[@pierre/trees](https://www.npmjs.com/package/@pierre/trees) 1.0.0-beta.6,
Apache License 2.0, Copyright 2025 Pierre Computer Company, full text in
[`third_party/pierre-trees/LICENSE`](../third_party/pierre-trees/LICENSE), plus a
colour table adapted from T3 Code @ `31f9d83` under the MIT license above.

The files and folders a thread's answer names are drawn as file references
(`dodaios/ui/web/frontend/src/components/agentchat/FileRefChip.tsx` and
`fileRefs.ts`), and a path that is not in the thread's folder as written is
looked up in the project (`components/agentic/threads/projectPathMatch.ts`).
The reference's look, its label rules and the lookup rules are adapted from
T3 Code @ `2c4310eb` under the MIT license above; each file names its source
in a header comment.

A few well-separated portions of NousResearch/hermes-agent (MIT, Copyright (c)
2025 Nous Research) are adapted into the agent code. Each adapted block names
its upstream file and commit in a header comment; the license text and the list
of adapted files live in [`third_party/hermes-agent/`](../third_party/hermes-agent/).

## External distribution metadata

Package-manager listings and release descriptions should identify the license
of the artifact they actually distribute. A listing pinned to an older MIT
release retains that description until its artifact is updated. External
listings and repository social-preview settings are not updated by changing
this file; verify them separately when publishing a release.
