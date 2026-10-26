# Release notes: highlights first (proposal)

Status: **proposal only**. The release notes are generated in code, so this
document changes no workflow or script.

## Where the notes come from today

- `scripts/ci/cut_release.py` builds the notes for a new tag from the
  `[Unreleased]` section of `CHANGELOG.md`, or from Conventional Commit
  subjects. `.github/workflows/release-cut.yml` writes them to `notes.md` and
  uses them as the body of the release-candidate pull request
  (`gh pr create --body-file`).
- `scripts/ci/release_assets.py` (finalize) takes the CHANGELOG section of the
  tag through `section_notes(changelog, tag[1:])`, which lives in
  `cut_release.py`, and publishes it with `gh release edit --notes-file`.

## What readers see

31 of the 52 published releases (v1.0.0 to v2.8.0) start with a
`## Supply-chain status` block. That block came from an inline heredoc in
`.github/workflows/sign-installer.yml` and was removed on 2026-10-03, so
releases from v2.9.0 on no longer start with it. The newer notes start with
Conventional Commit headings, which are written for maintainers, not for
users who want to know what is new.

## Proposed order

```markdown
## Highlights

- <the one change a user will notice first, in one sentence>
- <second>
- <third>

<optional: one GIF or a user-attachments video of the main highlight>

## Changes

<the CHANGELOG section as today>

<details>
<summary>Supply chain and verification</summary>

Signatures, checksums, SBOM and provenance, as listed in the release assets.

</details>
```

## How it could be built later

1. Add an optional `### Highlights` list at the top of each version in
   `CHANGELOG.md`. Writing it stays a human task: three bullets in plain words.
2. Let `section_notes` (in `cut_release.py`, used by `release_assets.py`) move that
   list to the top under `## Highlights`. If it is missing, the notes stay as
   they are today.
3. Put any verification text into a collapsed `<details>` block at the end.
4. Old releases could get the same order by editing their notes by hand with
   `gh release edit <tag> --notes-file`. Their supply-chain block would then
   go into `<details>`. This changes only the text, never the assets.

Each of these steps is a change to release code and needs its own pull request.
