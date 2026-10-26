# README demo

`README.md` shows `dodaios-demo.gif` from this folder at the very top, above
the badges. It is embedded with an absolute
`https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/demo/readme/dodaios-demo.gif`
URL, because PyPI renders the README on its own domain and cannot resolve
repository paths (see `scripts/ci/check_readme_absolute_urls.py`).

## Requirements for the GIF

- File: `assets/demo/readme/dodaios-demo.gif`
- Size: at most 10 MB
- Width: 800 to 1200 px (the README displays it at 800 px)
- Length: 20 to 60 seconds
- Content: one concrete flow from prompt to result, recorded in the real app.
  No mock-ups and no motion-graphics montage.
- The first frame must show the app, not a black fade. GitHub shows only the
  first frame to visitors who turned on reduced motion.
- No private data on screen: no real names, email addresses, account ids or
  API keys.

Optionally put an MP4 with the same base name next to it
(`dodaios-demo.mp4`). The README does not embed it, since GitHub plays only
user-attachment videos inline.

## Current file

The current GIF is cut from the real Agentic IDE recording that the README also
shows as a video in "Run every coding agent at once" (three coding agents in
panes, the browser panel, files and a Git diff). It is 900 px wide, 8 frames
per second, about 31 seconds and 5 MB. It covers seconds 7 to 38.5 of the
recording, which leaves out the fade-in and the parts with failed-hook
messages.

How it was made, so it can be redone from a new recording:

```bash
ffmpeg -ss 7 -t 31.5 -i demo.mp4 -vf "fps=8,scale=900:-1:flags=lanczos,palettegen=max_colors=128:stats_mode=diff" pal.png
ffmpeg -ss 7 -t 31.5 -i demo.mp4 -i pal.png -lavfi "fps=8,scale=900:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle" raw.gif
npx gifsicle -O3 --lossy=80 raw.gif -o dodaios-demo.gif
```

`-ss` and `-t` pick a clean stretch: the first frame shows the app, not a black fade,
and no error output is on screen.
