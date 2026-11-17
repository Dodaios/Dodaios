# Clips: the video editor

A Clips node (type `motion`) is a short video. The person edits it in the app's
clip editor; Dodaios edits the same clip through the `clip` tool. Both write one
spec, so every change the assistant makes shows up in the open editor (as an
undoable step) and every change the person makes is what the assistant reads.

## Features

Researched against common short-form and desktop editors (2026-11-17). The
design is Dodaios's own; the lists only fix what an editor of this kind needs.

| Priority | Feature | State |
|---|---|---|
| Must | Multi-track timeline: main track, text, overlay and audio tracks, captions | done |
| Must | Zoom, snapping, drag and drop, trim, split, delete, ripple delete | done |
| Must | Undo/redo, copy/paste, multi-select, keyboard shortcuts | done |
| Must | Crop, scale, position, rotate, speed (0.25x to 4x) | done |
| Must | Text layers with entrance and exit animations | done |
| Must | Auto captions by local speech recognition, editable, styled (word highlight) | done |
| Must | Volume, fades, background music, waveform display | done |
| Must | Formats 16:9, 9:16, 1:1, 4:5, safe-zone guide | done |
| Must | Real-time preview, MP4 export (720p, 1080p, 4K; 24/30/60 fps) | done |
| Must | Autosave, versions, restore | done (existing node store) |
| Should | Keyframes (zoom, position, rotation, opacity), transitions | done |
| Should | Filters and colour correction (brightness, contrast, saturation, warmth) | done |
| Should | Magnetic main track (pieces always back to back) | done |
| Should | Remove silences | done |
| Should | Music ducking under speech | done |
| Should | Caption style presets | done |
| Should | Platform presets (TikTok, Reels, Shorts, YouTube, feed) | done |
| Should | Filler-word removal (transcript-based cuts) | via `transcribe` + `split`/`delete` |
| Nice | Auto-reframe, highlight detection, beat sync, chroma key, stickers | deferred |
| Nice | Proxy editing, H.265/ProRes export, HDR | deferred |

## How it works

One renderer: `dodaios/nodes/kinds/motion.py` (cards, the player) and
`motion_media.py` (videos, layers, captions) draw the clip as a page in which
a frame is a pure function of time. The editor's preview, the stage and the
export all use that page:

- the preview is the page drawn from the unsaved spec, steered with
  `dodaios-film-seek` / `dodaios-film-time` messages;
- the export (`dodaios/nodes/clip/export.py`) opens the page headless with
  `?export=1`, asks it for every frame (`window.__clipFrame(t)` resolves once
  each visible video stands on its frame), captures it, encodes H.264 and mixes
  the sound separately (same volume, fade and ducking rules as the page).

Media files live in the node's folder (`media/<id>.<ext>`, with a poster, a
filmstrip and waveform peaks beside them). The page loads them from
`/clip-media/<node>/<file>`: GET/HEAD only, the id is random, so the sandboxed
page (opaque origin, no credential) can play them while every other route stays
shut to it. A file in a codec a browser cannot play is converted to H.264 on
import.

## Spec

```
{
  "format": "wide" | "square" | "tall" | "portrait",   // 16:9, 1:1, 9:16, 4:5
  "theme": "dark" | "light", "accent": color, "loop": bool,
  "scenes": [scene, ...],          // the main track, back to back
  "media": {"<id>": {kind: video|audio|image, name, file, seconds, width, height, audio}},
  "tracks": [{id, kind: text|overlay|audio, name?, muted?, hidden?, locked?, items: [...]}],
  "captions": {style: clean|bold|karaoke|boxed|none, position: bottom|middle|top,
               size: s|m|l, items: [{start, end, text, words?: [[s, e], ...]}]}
}
```

- A scene of type `video` is a piece of a library file: `media`, `in` (source
  start), `seconds` (length on the timeline), `speed`, `volume` (0 to 1),
  `muted`, `fade_in`, `fade_out`, `fit` (cover|contain), `zoom`, `x`, `y`
  (offset in % of the frame), `rotate`, `opacity`, `crop` {l,t,r,b} (fractions),
  `filter` (none|vivid|warm|cool|mono|fade|noir|film), `color` {brightness,
  contrast, saturation, warmth} (-100 to 100), `keys` [{t, zoom?, x?, y?,
  rotate?, opacity?}] (t inside the piece), `transition` (into this piece:
  cut|fade|slide|zoom|wipe|dip|blur). The source range is `in` to
  `in + seconds * speed`.
- Card scenes (title, text, bullets, stat, bars, quote, steps, image, chart,
  end) are as before.
- A track item has `id`, `start`, `seconds`:
  - text: `text`, `style` (title|subtitle|body|label|caption|quote), `size`,
    `x`, `y` (centre, % of frame), `align`, `color`, `bg`
    (none|shadow|box|pill), `font` (sans|serif|mono), `anim`
    (fade|rise|pop|slide|zoom|type|none), `out` (fade|rise|pop|slide|zoom|none), `keys`;
  - overlay: `media` (video or image), `x`, `y` (centre, %), `w` (width, % of
    frame), `radius`, the video timing fields, the look fields, `anim`, `out`;
  - audio: `media` (audio or video), the timing fields, `duck` (lowered to 30 %
    while a main-track piece with sound plays).
- Later tracks draw on top. Ids are kept; missing ones are given (`v1`, `t1`,
  `x1`, `a1`, `tr1`).

## Routes

Under `/api/nodes/{id}/clip`:

| Route | Does |
|---|---|
| `POST /media` | stores the uploaded file (body = bytes, `X-File-Name`), answers `{id, entry}`; the caller adds the entry to the spec |
| `POST /captions` | `{spec, language?}`: transcribes the speech of the clip as edited, answers `{items}` |
| `POST /transcribe` | `{media, in?, out?, language?}`: `{text, words: [{w, s, e}]}` in source time |
| `POST /silences` | `{media, in?, out?, min_silence?, pad?}`: `{silences: [[s, e]]}` in source time |
| `POST /export` | `{spec?, preset: 720p|1080p|2160p, fps: 24|30|60}`: `{job}` |
| `GET /export/{job}` | `{state, progress, file?, error?}`; `GET /export/{job}/file` the MP4; `DELETE` cancels |

`GET /clip-media/{node}/{file}` serves the library files (ranges supported).

## The `clip` tool

Operations: `guide`, `list`, `create`, `read` (the timeline with ids and
times), `edit` (actions, all or none), `import` (files on this computer into
the library), `transcribe`, `captions` (auto captions), `silences`, `look`
(frames at given times, as pictures), `export`, `revert`.

Edit actions (`{"do": ...}`): `add_clip`, `add_scene`, `add_text`,
`add_music`, `split`, `trim`, `delete` (`ripple`), `move`, `set`, `keyframe`,
`transition`, `captions`, `caption_edit`, `remove_silences`, `format`,
`duplicate`. The guide carries the editing doctrine (hook in the first two
seconds, a visual change every two to four seconds, captions of three to seven
words inside the safe zone, music at 20 to 30 % ducked under speech, look at
the result before answering).
