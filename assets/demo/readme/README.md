# README demo

The README opens with one recording, `dodaios-demo.gif` in this folder. It is
linked with an absolute `raw.githubusercontent.com` URL so it also plays on
PyPI, where a GitHub video would not.

| | |
|---|---|
| Length | 71 s from a take of 155 s: clicks and typing at 1.4x, the waits for the model at 7x |
| Picture | 960 x 540, 12 frames a second, 128 colours |
| Recorded from | Dodaios 5.1.0 (main of November 13, 2026), a first-run instance that was thrown away afterwards |
| Model | Claude Opus 5.5 through Claude Code, signed in to a Claude plan. Every answer and change is real |

It shows Dodaios as a superagent, the one agent that runs the others. One take
without a cut, in this order:

1. The first-run setup (name, model connection, voice) and two stops of the
   app's own guided walk.
2. One request in the Dodaios chat, on Opus 5.5: start two Claude Code
   threads at once in the sample project, one adding a `--pace` option with
   tests, one writing a page of documentation. The panel beside the chat says
   what Dodaios is doing and lists both agents under Recent activity.
3. While the agents work, a second request: look after the project from now
   on and run its tests once a day. Dodaios answers it beside the running
   work, in a side thread.
4. A row of the panel opens the first agent's thread in the Agentic IDE, with
   the brief Dodaios wrote. Both threads finish, and their changes are
   reviewed.
5. Back in the chat: Dodaios' answer to the standing task, its report on both
   agents, which it checked itself, and the standing task under Looks after.

The model's answers differ from take to take, so a new recording does not
match this one word for word.

## Requirements for a recording

- The real app, recorded from an isolated demo instance. No mock-ups, no
  motion-graphics montage, no text laid over the picture, no staged answers.
- Nothing private on screen: no real names, email addresses, account ids or
  keys, no error output and no warning cards.
- The first frame shows the app.

## Record it again

The interface changes often, so the recording is made by scripts in
`scripts/readme_demo/`. They need Linux or macOS, Node.js with Playwright,
ffmpeg, a Python environment that has Dodaios, `ptyprocess` and `pytest`, a
built frontend bundle, and Claude Code signed in to a Claude plan that has
Opus 5.5 (`DEMO_MODEL` names another model of the picker).

The instance gets a home folder of its own, so Claude Code there does not see
a login kept under your own home folder. On macOS the login is in your
Keychain and works as it is. On Linux, create a token with
`claude setup-token` and start the instance with it in
`CLAUDE_CODE_OAUTH_TOKEN`; the instance hands its environment to Claude Code.
A take costs a few minutes of the plan's usage.

```sh
# 1. A throwaway first-run instance on port 47990, as a normal user.
#    It writes only under /tmp/dodaios-demo and never touches your own app.
#    (Linux: put CLAUDE_CODE_OAUTH_TOKEN=... in front, see above.)
PYTHON=/path/to/venv/bin/python scripts/readme_demo/demo-instance.sh

# 2. In a second terminal: the take, two to three minutes. It writes the
#    frames, list.txt (already timed at 1.4x, waits at 7x) and timeline.json.
node scripts/readme_demo/record.cjs /tmp/dodaios-take

# 3. The full-size video (1920 x 1080, H.264, 60 fps) and the README's GIF.
cd /tmp/dodaios-take
ffmpeg -f concat -safe 0 -i list.txt \
  -vf "fps=60,format=yuv420p" \
  -c:v libx264 -preset slow -crf 19 -movflags +faststart -an dodaios-demo.mp4
ffmpeg -i dodaios-demo.mp4 \
  -vf "fps=12,scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128:stats_mode=diff[p];[b][p]paletteuse=dither=none:diff_mode=rectangle" \
  -loop 0 dodaios-demo.gif
```

Copy the GIF over the one in this folder. It is the only recording
`scripts/ci/check_repo_junk.py` lets into the repository; the MP4 stays out.

`record.cjs` clicks through the interface by its labels and waits for the
model where the app shows it is done: the chat's stop button, a thread's
"Worked for" line. When a label or a flow changes, the script stops at that
step, says which one, and saves a picture of the screen as `failure.png`.
`DEMO_SPEED` and `DEMO_FAST` change the two speeds.

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
model.

| Recording | Shows |
|---|---|
| [Run every coding agent at once](https://github.com/user-attachments/assets/83c50d16-8c3c-420f-baab-e6d06381307b) | 38 s: three coding agents in panes, the Git panel and the browser preview |
| [A team of agents](https://github.com/user-attachments/assets/4c29df69-2114-4ed1-a220-703f6ff8386a) | 35 s: a new agent gets a research job, writes a brief and sets up a routine |
| [Code by talking](https://github.com/user-attachments/assets/1daa832e-a566-4f22-add6-8b21eb8aaaad) | 53 s with sound, recorded before the rename: the app and the voice still say Personal Jarvis, and some panes show German text |
| [Tour](https://github.com/user-attachments/assets/3cbe1d63-0ad4-4f39-88e9-9b56ede17f1c) | 54 s: a click-through of eight sections, one of which (Verse) has since been removed |
