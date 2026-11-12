# README demo

The README opens with one recording, `dodaios-demo.gif` in this folder. It is
linked with an absolute `raw.githubusercontent.com` URL so it also plays on
PyPI, where a GitHub video would not.

| | |
|---|---|
| Length | 59 s, played at 1.4x the speed of the take |
| Picture | 960 x 540, 12 frames a second, 128 colours |
| Recorded from | Dodaios 5.0.0, a first-run instance that was thrown away afterwards |
| Model | None connected. The recording shows the app, not an agent's answers |

It is one take without a cut, in this order: the first-run setup (name, model
connection, voice), two stops of the app's own guided walk, the plugin catalog,
a project connected in the Agentic IDE with its tests run in the terminal, a
new memory, the desktop pets, and two sections side by side.

## Requirements for a recording

- The real app, recorded from an isolated demo instance. No mock-ups, no
  motion-graphics montage, no text laid over the picture.
- Nothing private on screen: no real names, email addresses, account ids or
  keys, no error output and no warning cards.
- The first frame shows the app.

## Record it again

The interface changes often, so the recording is made by scripts in
`scripts/readme_demo/`. They need Linux or macOS, Node.js with Playwright,
ffmpeg, a Python environment that has Dodaios, `ptyprocess` and `pytest`, and
a built frontend bundle.

```sh
# 1. A throwaway first-run instance on port 47990, as a normal user.
#    It writes only under /tmp/dodaios-demo and never touches your own app.
PYTHON=/path/to/venv/bin/python scripts/readme_demo/demo-instance.sh

# 2. In a second terminal: the take. It writes the frames and list.txt.
node scripts/readme_demo/record.cjs /tmp/dodaios-take

# 3. The full-size video (1920 x 1080, H.264, 60 fps) and the README's GIF.
cd /tmp/dodaios-take
ffmpeg -f concat -safe 0 -i list.txt \
  -vf "setpts=PTS/1.4,fps=60,format=yuv420p" \
  -c:v libx264 -preset slow -crf 19 -movflags +faststart -an dodaios-demo.mp4
ffmpeg -i dodaios-demo.mp4 \
  -vf "fps=12,scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128:stats_mode=diff[p];[b][p]paletteuse=dither=none:diff_mode=rectangle" \
  -loop 0 dodaios-demo.gif
```

Copy the GIF over the one in this folder. It is the only recording
`scripts/ci/check_repo_junk.py` lets into the repository; the MP4 stays out.

`record.cjs` clicks through the interface by its labels. When a label or a
flow changes, the script stops at that step, says which one, and saves a
picture of the screen as `failure.png`.

## Screenshots

The pictures in `assets/readme/` come from the same instance, right after the
take (1920 x 1280):

```sh
node scripts/readme_demo/stills.cjs /tmp/dodaios-stills memory plugins pets ide
# "connect" is the setup step: start the demo instance again first.
node scripts/readme_demo/stills.cjs /tmp/dodaios-stills connect
```

## A video with a player

GitHub plays a video inline only when it is a user attachment. To show the
full-size MP4 with a player, upload it in a comment on an issue or pull request
and post the comment (an attachment in an unposted comment stays private).
Then put the `user-attachments` URL on a line of its own in `README.md` and
`README.zh-CN.md`. GitHub accepts up to 10 MB for an inline video.

## Earlier recordings

These were uploaded for the README before November 2026 and are no longer
linked from it. They are real recordings of agents at work with a connected
model, which the current GIF does not show.

| Recording | Shows |
|---|---|
| [Run every coding agent at once](https://github.com/user-attachments/assets/83c50d16-8c3c-420f-baab-e6d06381307b) | 38 s: three coding agents in panes, the Git panel and the browser preview |
| [A team of agents](https://github.com/user-attachments/assets/4c29df69-2114-4ed1-a220-703f6ff8386a) | 35 s: a new agent gets a research job, writes a brief and sets up a routine |
| [Code by talking](https://github.com/user-attachments/assets/1daa832e-a566-4f22-add6-8b21eb8aaaad) | 53 s with sound, recorded before the rename: the app and the voice still say Personal Jarvis, and some panes show German text |
| [Tour](https://github.com/user-attachments/assets/3cbe1d63-0ad4-4f39-88e9-9b56ede17f1c) | 54 s: a click-through of eight sections, one of which (Verse) has since been removed |
