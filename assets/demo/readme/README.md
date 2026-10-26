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
per second, about 22 seconds and 3 MB. It joins seconds 7 to 17.2 and 20 to
31.5 of the recording. That leaves out the fade-in, the stretches with
failed-hook messages and two stretches where a "Prompt typed, not started"
notice sits at the bottom of a pane.

How it was made, so it can be redone from a new recording:

```bash
F="[0:v]trim=7:17.2,setpts=PTS-STARTPTS[a];[0:v]trim=20:31.5,setpts=PTS-STARTPTS[b];[a][b]concat=n=2:v=1[c];[c]fps=8,scale=900:-1:flags=lanczos"
ffmpeg -i demo.mp4 -filter_complex "$F,palettegen=max_colors=128:stats_mode=diff" pal.png
ffmpeg -i demo.mp4 -i pal.png -filter_complex "$F[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle" raw.gif
npx gifsicle -O3 --lossy=80 raw.gif -o dodaios-demo.gif
```

The two `trim` ranges pick clean stretches: the first frame shows the app, not a
black fade, and no error or warning notice is on screen. The usage meters of the
coding agents (for example "monthly limit") are part of their normal display.
