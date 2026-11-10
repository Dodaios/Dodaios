# Looks

A look is an optional visual that takes the voice orb's place in the app: an
animation that reacts to what Dodaios does (listening, thinking, speaking) and
to how loud the microphone and the voice are. Looks come from the Community
Marketplace; Dodaios ships one example, **Pulse Ring**
(`dodaios/ui/looks/builtin/pulse-ring`).

A look can only draw. It runs in a sandboxed frame with no network, no access
to the app's API, no cookies and no storage. The app sends it the voice state
and the audio levels, and nothing else.

## The pack

A look is one folder whose name is its id:

```
pulse-ring/
  look.json      the manifest
  index.html     the entry page
  preview.svg    the picture the marketplace shows
  ...            scripts, styles, images, 3D models the page loads
```

`look.json` (format `dodaios-look/1`, checked by `dodaios/ui/looks/manifest.py`):

| Field | Required | Rule |
|-------|----------|------|
| `format` | yes | `"dodaios-look/1"` |
| `id` | yes | 2–48 lowercase letters, digits, dashes; equals the folder name; not `orb`, `none`, `default` |
| `name` | yes | up to 40 characters |
| `description` | no | up to 200 characters |
| `author` | yes | up to 60 characters |
| `version` | yes | `MAJOR.MINOR.PATCH` |
| `license` | yes | SPDX id, for example `Apache-2.0` or `Apache-2.0 AND CC-BY-4.0` |
| `entry` | no | relative path to an `.html` file, default `index.html` |
| `preview` | yes | relative path to a `.png`, `.jpg`, `.webp` or `.svg` file |
| `attribution` | no | credit line shown with the look, up to 200 characters |
| `homepage` | no | an `https://` link |

Limits of the whole pack (`dodaios/ui/looks/loader.py`):

- at most 25 MB and 300 files;
- file kinds: html, js, mjs, css, json, txt, md, png, jpg, jpeg, webp, svg,
  glb, gltf, bin, ktx2, hdr, woff2, wasm;
- file names use letters, digits, `_`, `.` and `-`, at most five folders deep;
- no links.

A pack that breaks a rule is not listed, and the reason is logged.

## Where looks live

- built-in: `dodaios/ui/looks/builtin/<id>/`
- installed: `<DATA_DIR>/looks/<id>/`

A built-in look wins over an installed one with the same id.

## Messages

The page talks to the app with `postMessage`. Every message is an object with
a `type`.

From the app to the look:

| `type` | Fields | When |
|--------|--------|------|
| `look:init` | `format`, `state`, `reducedMotion` | once, after the page has loaded |
| `look:state` | `state` | the voice state changed |
| `look:levels` | `input`, `output` (0–1) | about 30 times a second while a conversation runs |

`state` is one of `idle`, `connecting`, `listening`, `thinking`, `speaking`,
`paused`, `error`. A look must treat an unknown state like `idle`.
`reducedMotion` is true when the user asked the system for less motion; a look
should then keep still apart from the voice level.

From the look to the app:

| `type` | When |
|--------|------|
| `look:ready` | once the page can draw |

A look that does not send `look:ready` within five seconds, or whose page
fails, is replaced by the voice orb.

## What a look cannot do

- load anything from the network: scripts, models and fonts must be in the pack;
- call the app's API, read the user's data, keys or files;
- open windows, pop-ups or dialogs, or navigate the app;
- use the microphone or the camera: the levels come from the app.

## From the marketplace

A look is published as a zip archive of its pack (at the zip's root or in one
top folder). The registry's `index.json` lists it under `looks`:

| Field | Rule |
|-------|------|
| `name` | the look id; the pack's `id` must be the same |
| `archive_url` | https on `github.com`, `objects.githubusercontent.com`, `release-assets.githubusercontent.com`, `raw.githubusercontent.com` or `dodaios.github.io` |
| `sha256` | the archive's SHA-256, pinned by the registry |
| `size_bytes` | the archive's size, at most 27 MB |
| `preview_url` | optional, same hosts; any other host is dropped |
| `title`, `description`, `publisher`, `version`, `license`, `attribution`, `source_url` | shown on the entry's page |

Installing (`POST /api/marketplace/community/install/<name>`,
`dodaios/ui/looks/install.py`) downloads over https from those hosts only,
checks the SHA-256, refuses links, unsafe names, more than 300 files or more
than 25 MB unpacked, checks the pack like a built-in one and moves it into
`<DATA_DIR>/looks/<id>` with one rename. A name a built-in look owns is
refused. Removing it (`DELETE` on the same route) puts the orb back if it was
the active look. A look entry that breaks a rule is dropped from the feed
alone; the rest of the index stays.

## Making a look

1. Copy `dodaios/ui/looks/builtin/pulse-ring` and rename the folder.
2. Set your own `id`, `name`, `author` and `license` in `look.json`.
3. Draw in `index.html`: canvas, WebGL or SVG. Libraries such as Three.js go
   into the pack as files.
4. Keep the background transparent; the app draws the surface behind it.
