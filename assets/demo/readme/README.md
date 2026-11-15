# README recordings

The README shows Dodaios at work in short recordings: one at the top, and one
for each pillar. They are in this folder:

| File | Where it plays | What it shows |
|---|---|---|
| `hero.webp` | at the top | One request to the assistant crosses the chat, the Agentic IDE with three coding agents side by side, and a slide deck changed by hand. 33 s, 1280 x 720, 30 frames a second |
| `dodaios-demo.mp4` | linked from the clip at the top | The same recording as a video, 1920 x 1080, 60 frames a second, without sound. GitHub plays it on the file's page |
| `assistant.webp` | An assistant that does the work | The assistant answers a question with the GitHub plugin. 15 s, 1280 x 720 |
| `agents.webp` | Your coding agents, side by side | Three coding agents side by side, then the rail of coding agents in a thread's picker. 15 s, 1280 x 720 |
| `nodes.webp` | Docs, decks, sheets and whiteboards | A whiteboard made from a sentence and changed by hand. 16 s, 1280 x 720 |
| `phone.webp` | With you when you leave the desk | The phone app: a request, two approvals tapped, the answer. 13 s, 420 x 908 |
| `voice.webp` | Your voice, in every app | Not recorded yet: it needs a real voice and microphone ([The voice clip](#the-voice-clip)) |
| `dodaios-demo.gif` | nowhere since 15 November 2026 | The clip that stood at the top before. The project page on PyPI of every release up to 5.3.3 still shows it from this path. Delete it once a newer release is on PyPI |

Each `.webp` is an animated WebP picture: it starts by itself, loops, has no
sound and needs no player. Browsers have shown it for years, it is about half
the size of a GIF at twice the frame rate, and it keeps the full colours. The
README links every picture with an absolute `raw.githubusercontent.com` URL,
so it also plays on PyPI.

Every recording is of the real app in a throwaway instance, with real models
at work on real projects: a private demo repository with five open pull
requests, and two small sample projects. The person in them is Alex Rivera,
and the assistant is called Nova.

## What a recording must be

- A recording of the real app and nothing else: no title cards, no words laid
  over the picture, no stage around the window, no motion graphics. The
  maintainer turned down a designed film with captions on 13 November 2026.
- A workspace that is in use, never the first-run setup: a warm-up that is not
  filmed does a morning's work first.
- No mock-ups and no staged answers. A wait for a model is cut out (the
  picture before it dissolves into the one after it), never replaced by
  something else.
- Nothing private on screen: no real names, email addresses, account ids or
  keys. The scripts replace the name of the computer and the home folder of
  whoever records, and `DEMO_SCRUB` takes more pairs (`text=replacement`,
  separated by commas). A model copies what it reads into what it writes (the
  author of a pull request into a slide's speaker notes, for example), so the
  scrub covers the values of text fields too. Check every take for leaks
  before it is cut.
- It must move the way the app does on a screen. The first clip at the top
  was filmed at 30 frames a second, its shots played up to twice as fast, and
  its pointer jumped to a place and stood there: the maintainer said it looked
  like two frames a second (14 November 2026). So every stretch with movement
  is filmed at 60 frames a second, the cut plays the footage at the speed it
  was filmed at (the whole cut may play up to a quarter faster, never single
  shots), the pointer travels at a person's pace, and more than a seconds
  counter changes in the picture.
- Measure before it goes in: decode the video, count per second how much of
  the picture changes, and look for the longest stretch in which nothing
  does. Stills show what is in the picture, not how it moves.
- Readable at the size the README shows it, about 830 pixels wide: the window
  is small (about 1000 to 1200 points wide) and the frames are 1920 x 1080.

## The clips

All were filmed on 15 November 2026 from `main` (between 5.3.2 and 5.3.3), in throwaway
instances started by `demo-instance.sh` that were stopped afterwards. Nova ran
on Claude Opus 5.5 through Claude Code, signed in to a Claude plan; the coding
agents in the hero take ran on Claude Sonnet 5.5 the same way. Every answer,
review, edit and test run is real. The models' answers differ from take to
take, so a new recording does not match these word for word.

### The clip at the top (`hero.webp`, `dodaios-demo.mp4`)

33 seconds, cut from a take of about three minutes: one request crosses the
chat, the Agentic IDE and a slide deck.

1. In a conversation that is already in use, the request is typed: "Review
   the new PRs in acme-notes, one Sonnet agent per PR, and put the verdicts
   on a slide deck." Five coding agents start and show up under "Recent
   activity".
2. A click opens the first agent's thread in the Agentic IDE, and "Open side
   by side" puts two more beside it: three agents read the diffs and run the
   tests, then finish.
3. Back in the chat, Nova answers under the card of the slide deck it made.
4. The deck opens, goes a slide on, and the title of that slide is changed by
   hand to "What we merge this week". Then the deck is presented.

The deck's end was filmed a second time on the same instance, with no model
at work: in the first take the model had copied the author of the pull
requests into a slide's speaker notes, where the scrub did not reach yet.

Make it again: `record.cjs` with `DEMO_PARTS=setup,warmup,warmup-hero,picker,hero`
films the footage (its header lists the settings; the instance needs
`DEMO_PR_REPO`, a repository with a few open pull requests), and
`FILM_EDIT=edit-hero.js FILM_FPS=60 FILM_CRF=14 node render.cjs <take> hero-master.mp4`
cuts it. `measure-hero.py` measures the movement and lays out a contact
sheet. `DEMO_PARTS=deck` films only the deck's end again, with no model at
work.

### Your coding agents, side by side (`agents.webp`)

15 seconds from the same take: two more threads open beside the first, three
agents work on three pull requests in three columns, and the first review
arrives; then the agent and model control of a thread shows its rail of
coding agents (Claude Code, Codex, OpenCode and more) and their models. It
plays at the speed it was filmed at and loops without a jump. The cut is
`edit-agents.js` (`FILM_EDIT=edit-agents.js` for `render.cjs`).

### An assistant that does the work (`assistant.webp`)

15 seconds: the Plugins catalog with GitHub connected, then "Which acme-notes
PRs are still open, and which should I look at first?" in the chat. While
Nova works, the line under its name in the side panel says "Working in
GitHub" (the conversation itself draws no steps); the answer lists the five
pull requests as GitHub links and says where to start. The instance reaches
GitHub only through the plugin: `plugins_connect.py` puts a token into the
instance's own credential file, never into the system keychain.

### Docs, decks, sheets and whiteboards (`nodes.webp`)

16 seconds: "Put our launch plan on a whiteboard: research, build, beta,
launch". The whiteboard's card comes into the chat; the card opens the board
in its editor; the Launch box is dragged below Beta, Beta is renamed "Private
beta", and the board saves itself. The feature tour shows the same clip.

The Nodes and assistant clips share one instance and one set of scripts:
`nodes-plugins-setup.cjs` (first run and a warm-up), `seed_nodes.py
--workspace` (sample nodes for the library), `clip-nodes.cjs` and
`clip-assistant.cjs` (the takes), `nodes-plugins-cut.cjs` with the cuts in
`nodes-plugins-edit.cjs`, `nodes-plugins-measure.cjs`, and
`nodes-plugins-ocr.py`, which reads every frame for names that must not be in
it. They film a 1024 x 576 window at a device scale of 1.875.

### With you when you leave the desk (`phone.webp`)

13 seconds of the phone app in a phone-sized browser (390 x 844 at scale 2),
paired with the instance by a code. The conversation began at the desk: Nova
found a rounding fault in a small invoicing project and added a test that
catches it. On the phone: "Go ahead, fix it and run the tests." Two approval
cards come up, an edit of `invoice.py` and the test run, and each is allowed
with a tap; Nova answers that all seven tests pass. For the cards, the
conversation was set to "Ask before acting" (a new chat starts at "Bypass
permissions", where nothing asks). Taps and drags are real touch events.
Scripts: `phone-take.cjs`, `edit-phone.js`, `phone-film.html`,
`phone-render.cjs`, `phone-measure.py`.

### The voice clip

Not recorded yet: dictation needs a real voice and a microphone, and the
recording is the maintainer's own. `voice_take.py` does all but the speaking.
It records only the Dodaios window with the microphone, after a test
recording that checks the frame rate, the sound and the picture for private
text, and then cuts the waits by itself. The clip shows dictation into the
chat with the microphone button of the message field (a live waveform, then
"Transcribing…", then the sentence without its "uh"), and Nova's answer.
Dictation by the hold key leaves the field idle, and the Dodaios Bar keeps
itself out of screen recordings, so neither would show the listening.
`voice_take_synthetic.py` makes a made-up take to test the cut without a
person.

## Instances

The scripts film throwaway instances, never the app you use. They need Linux
or macOS, Node.js with Playwright, ffmpeg, a Python environment that has
Dodaios, a built frontend bundle, Claude Code signed in to a Claude plan, and
for the hero take the GitHub CLI signed in to an account that can read a
repository with a few open pull requests. The CLI must be a current one: an
old one fails on `gh pr view` ("Projects (classic) is being deprecated"), and
the failed call shows in red in the agents' threads.

```sh
# A first-run instance on its own port, data folder and home folder.
DEMO_PORT=47990 DEMO_ROOT=/tmp/dodaios-demo DEMO_HOME=/Users/Shared/demo \
DEMO_PR_REPO=your-org/your-demo-repo PYTHON=/path/to/venv/bin/python \
  scripts/readme_demo/demo-instance.sh
```

- The instance gets a home folder of its own, so Claude Code there does not
  see a login kept under yours. On macOS the login is in the Keychain: the
  script links the Keychain folder into the instance's home, and Claude Code
  finds the login only when `USER` and `LOGNAME` are set (without them every
  turn says "Not logged in"). On Linux, create a token with
  `claude setup-token` and start the instance with it in
  `CLAUDE_CODE_OAUTH_TOKEN`.
- Start it from a plain terminal, or with `env -i` and an explicit
  environment. Started from the shell of a coding agent, it inherits that
  agent's session variables and hands them on to the agents it starts.
- It runs the code of the Python environment you name. If that is a checkout
  that follows `main` by itself, a merge in the middle of a take changes the
  app under it: point `PYTHONPATH` at a checkout that stands still, with its
  own built bundle.
- A take that fails need not cost the warm-up: stop the instance after the
  warm-up, copy `DEMO_HOME` and `DEMO_ROOT/state` away, and start it again
  with `DEMO_KEEP=1`, which wipes nothing.
- Do nothing heavy on the computer while a take films, and look at its load
  first (`uptime`): above about five, the frames come unevenly and every
  model answers late. A take at 60 frames a second writes 150 to 700 MB of
  pictures; delete a failed one at once.
- Every model turn runs on the plan you signed in to. A take with its warm-up
  costs a few minutes of it.

## Make the pictures

Each recording is cut into a master video first (60 frames a second, nearly
without loss), and the README picture is made from the master:

```sh
python scripts/readme_demo/encode_webp.py hero-master.mp4 assets/demo/readme/hero.webp --width 1280 --fps 30
python scripts/readme_demo/encode_webp.py phone-master.mp4 assets/demo/readme/phone.webp --width 560 --fps 30
```

`encode_webp.py` reads the frames with ffmpeg and lets Pillow write the
animated WebP, storing only what changed from one frame to the next. Keep the
picture at the top under 5 MB and the others under 2 MB: every version stays
in the repository's history. The video next to the hero picture is the master
again, smaller:

```sh
ffmpeg -i hero-master.mp4 -c:v libx264 -preset slow -crf 23 -pix_fmt yuv420p \
  -movflags +faststart -an assets/demo/readme/dodaios-demo.mp4
```

Copy the files over the ones in this folder. They are the only recordings
`scripts/ci/check_repo_junk.py` lets into the repository; a new one needs a
line in `scripts/ci/repo-junk-allowlist.txt`.

## Screenshots

The pictures in `assets/readme/` come from the instance of the earlier film,
right after its take (1920 x 1280). The feature tour
(`docs/feature-tour.md`) shows them.

```sh
node scripts/readme_demo/stills.cjs /tmp/dodaios-stills plugins pets ide
# "connect" is the setup step: start the demo instance again first.
node scripts/readme_demo/stills.cjs /tmp/dodaios-stills connect
```

## Earlier clips at the top

From 14 to 15 November 2026 the README opened with a clip of 30 seconds: one
request to five coding agents and the report that came back. It was replaced
in place; [its last version](https://github.com/Dodaios/Dodaios/blob/0946e91c62f92a7b96e57391a514b0ced502bc4d/assets/demo/readme/dodaios-demo.mp4)
is in the history, and `dodaios-demo.gif` is its GIF.

Until 14 November 2026 the README opened with a longer film of 55 seconds:
four requests in a row to Dodaios (a question answered from a file with a
chart, a page made from the answer, a standing task, a fault handed to a
coding agent). It was replaced in place, so it is no longer in this folder;
[its last version](https://github.com/Dodaios/Dodaios/blob/8c0d31b3c096561b2770fcbaf4f34f5270abb4b6/assets/demo/readme/dodaios-demo.mp4)
is in the history. Its music is "Making It Look Easy" by Lee Rosevere, from
[Music For Podcasts 6](https://archive.org/details/leerosevere_musicforpodcasts_6),
licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

The scripts still make it: the `take` part of `record.cjs` films it at the
default window size, and `edit.js` is its cut.

```sh
DEMO_HOME=/Users/Shared/demo PYTHON=/path/to/venv/bin/python \
  scripts/readme_demo/demo-instance.sh
node scripts/readme_demo/record.cjs /tmp/dodaios-take     # setup, warmup, take
curl -L -o /tmp/making-it-look-easy.mp3 \
  "https://archive.org/download/leerosevere_musicforpodcasts_6/Lee%20Rosevere%20-%20Music%20For%20Podcasts%206%20-%2005%20Making%20It%20Look%20Easy.mp3"
shasum -a 256 /tmp/making-it-look-easy.mp3
#    4f1bc622469d5c84ec76c61f04c2a594bf9cd80f88d93557e6994f12148df333
FILM_MUSIC=/tmp/making-it-look-easy.mp3 FILM_CRF=23 \
  node scripts/readme_demo/render.cjs /tmp/dodaios-take film.mp4
```

The film is as long as its music, and the licence asks for the credit
wherever the film is shown.

## A video with a player

GitHub plays a video inline in a README only when it is a user attachment; a
`<video>` tag or a link to a file in the repository is not turned into a
player. To show the MP4 with a player in the README itself, drop it into a
comment box on an issue or pull request of the repository, wait for the
upload and post the comment (an attachment in an unposted comment stays
private). The comment then holds a
`https://github.com/user-attachments/assets/...` URL. Put that URL on a line of its own in `README.md` and
`README.zh-CN.md`, in place of the picture. GitHub accepts up to 10 MB for an
inline video on a free plan, and the player starts muted. PyPI shows such a
line as a bare link, which is why the README uses animated pictures.

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
