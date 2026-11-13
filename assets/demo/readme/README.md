# README demo

The README opens with one recording, `dodaios-demo.gif` in this folder. It is
linked with an absolute `raw.githubusercontent.com` URL so it also plays on
PyPI, where a GitHub video would not.

| | |
|---|---|
| Length | 60 s from a take of 6 min 46 s: clicks and typing at 1.15x, each wait for the model shortened to a few seconds (1.4x to 97x) |
| Picture | 960 x 540, 10 frames a second, 128 colours |
| Recorded from | Dodaios 5.1.0, a throwaway instance that was deleted afterwards |
| Model | Claude Fable 5.2 through Claude Code, signed in to a Claude plan. Every answer and change is real |

It is one take without a cut. It starts in a workspace that is in use, and
shows one piece of work from the request to the result:

1. Dodaios is asked in its chat about an invoice a customer says is one cent
   too high. It runs the project's own command, finds the cause and the other
   invoices with the same fault, and starts a coding agent on Fable 5.2 for the
   fix.
2. The agent's thread in the Agentic IDE is opened from the chat while the
   agent works, with the brief Dodaios wrote. When it is done, the change it
   made is shown.
3. Back in the chat, Dodaios checks the result itself and reports.
4. Dodaios is asked for an incident report and builds it as an artifact. The
   app opens the page when it is ready.

The model's answers differ from take to take, so a new recording does not
match this one word for word.

## How a take is built

A README shows the recording small, without sound, and starts it by itself.
The take follows what other products' recordings of this kind do:

- It opens on a request that is already being typed. Setting the app up is
  not part of it.
- The workspace is in use before the first frame: an earlier conversation,
  threads in two projects, an output. `record.cjs` does that work in a
  warm-up that is not recorded. It is real work too.
- A wait for the model is shortened, not cut out: the picture runs faster
  until the answer is there. `timeline.json` lists every stretch and its speed.
- The picture moves in on the part of the window that matters, and shows the
  whole window when the place changes.
- The result gets the last part of the take: the artifact is opened and
  scrolled. The take ends where it began, so the loop restarts without a jump.

## Requirements for a recording

- The real app, recorded from an isolated demo instance. No mock-ups, no
  motion-graphics montage, no text laid over the picture, no staged answers.
- Nothing private on screen: no real names, email addresses, account ids or
  keys, no error output and no warning cards. `record.cjs` replaces the name of
  the computer and the home folder of whoever records; `DEMO_SCRUB` takes more
  pairs (`text=replacement`, separated by commas).
- The first frame shows the app.

## Record it again

The interface changes often, so the recording is made by scripts in
`scripts/readme_demo/`. They need Linux or macOS, Node.js with Playwright,
ffmpeg, a Python environment that has Dodaios, `ptyprocess` and `pytest`, a
built frontend bundle, and Claude Code signed in to a Claude plan that has
Fable 5.2 (`DEMO_MODEL` names another model of the picker).

The instance gets a home folder of its own, so Claude Code there does not see
a login kept under your own home folder. On macOS the login is in your
Keychain; the instance script links the Keychain folder into the instance's
home folder so Claude Code finds it. On Linux, create a token with
`claude setup-token` and start the instance with it in
`CLAUDE_CODE_OAUTH_TOKEN`; the instance hands its environment to Claude Code.
The instance keeps its own keys in a file under its data folder and never
reads or writes the keys of the app you use. A run takes about twenty minutes
(building an artifact alone takes two to nine) and that much of the plan's usage: two threads, three requests to Dodaios, two
coding agents and two artifacts.

```sh
# 1. A throwaway first-run instance on port 47990, as a normal user.
#    It writes only under /tmp/dodaios-demo and DEMO_HOME, and never touches
#    your own app. DEMO_HOME is the home folder the instance sees; its path
#    can show in the picture, so choose one that reads well.
#    (Linux: put CLAUDE_CODE_OAUTH_TOKEN=... in front, see above.)
DEMO_HOME=/Users/Shared/demo PYTHON=/path/to/venv/bin/python \
  scripts/readme_demo/demo-instance.sh

# 2. In a second terminal: setup, warm-up and the take. It writes the frames,
#    list.txt (every frame with the time it stays on screen) and
#    timeline.json. DEMO_BROWSER=chrome uses an installed Chrome instead of
#    Playwright's own browser.
node scripts/readme_demo/record.cjs /tmp/dodaios-take

# 3. The full-size video (1920 x 1080, H.264, 60 fps) and the README's GIF.
#    Both come straight from the frames: a GIF made from the MP4 is a quarter
#    larger, because the video codec's noise counts as change.
cd /tmp/dodaios-take
ffmpeg -f concat -safe 0 -i list.txt \
  -vf "fps=60,format=yuv420p" \
  -c:v libx264 -preset slow -crf 19 -movflags +faststart -an dodaios-demo.mp4
ffmpeg -f concat -safe 0 -i list.txt \
  -vf "fps=10,scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128:stats_mode=diff[p];[b][p]paletteuse=dither=none:diff_mode=rectangle" \
  -loop 0 dodaios-demo.gif
```

`DEMO_SPEED` sets how fast clicks and typing play (1.15). The length a wait is
shortened to is the number given to `waiting()` in `record.cjs`.

Copy the GIF over the one in this folder. It is the only recording
`scripts/ci/check_repo_junk.py` lets into the repository; the MP4 stays out.

`record.cjs` clicks through the interface by its labels and asks the app's
own API whether a model is still at work. When a label or a flow changes, or
a turn cannot reach its model, the script stops at that step, says which one,
and saves a picture of the screen as `failure.png`. Start the instance again
before the next run: a take needs the first-run state. `DEMO_PARTS` runs only
some of the parts (`setup`, `warmup`, `take`).

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
