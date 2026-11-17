# README recordings

The README shows Dodaios at work in short recordings: one at the top, and one
for each pillar. They are in this folder:

| File | Where it plays | What it shows |
|---|---|---|
| `dodaios-demo.mp4` | at the top, in GitHub's video player from its upload of this file (see below); the caption links to the file | A question to the assistant, which answers from its memory; it starts a Claude Code agent, followed at work in the Agentic IDE, and reports back. 42 s, 1920 x 1080, 60 frames a second, H.264, no sound |
| `hero.webp` | not in the README since 17 November 2026 (kept for the history) | The clip that stood at the top on 16 November 2026: one request crosses the chat, two coding agents, a confirmation and a slide. 28 s, 1120 x 630, 60 frames a second |
| `assistant.webp` | not in the README since the evening of 16 November 2026 (kept for the feature tour and the history); was: The assistant | A question about a bank export on the computer, answered with the sums and a column chart. 12 s, 1120 x 630, 60 frames a second |
| `agents.webp` | not in the README since the evening of 16 November 2026 (kept for the feature tour and the history); was: Your coding agents | Three coding agents side by side, then the rail of coding agents in a thread's picker. 12 s, 1120 x 630, 60 frames a second |
| `nodes.webp` | not in the README since the evening of 16 November 2026 (kept for the feature tour and the history); was: Docs, decks, sheets and whiteboards | A slide deck made from one sentence, and its title changed by hand. 14 s, 1120 x 630, 60 frames a second |
| `telegram.webp` | Away from your desk | Not recorded yet: a real conversation with the assistant through Telegram ([The Telegram clip](#the-telegram-clip)). The phone-app clip that stood here until 16 November 2026 looked like a native app and was taken out |
| `voice.webp` | Your voice, in every app | Not recorded yet: it needs a real voice and microphone ([The voice clip](#the-voice-clip)) |
| `dodaios-demo.gif` | nowhere since 15 November 2026 | The clip that stood at the top before. The project page on PyPI of every release up to 5.3.3 still shows it from this path. Delete it once a newer release is on PyPI |

Each `.webp` is an animated WebP picture: it starts by itself, loops, has no
sound and needs no player. Browsers have shown it for years, it keeps the full
colours, and it is much smaller than a GIF of the same clip. The
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

### The video at the top (`dodaios-demo.mp4`), 17 November 2026

The maintainer wanted the video to start as an ordinary chat with the
assistant and then show the assistant starting a coding agent, followed in
the Agentic IDE. Two versions came before it that day: T1 and T2 in the
Grid, a slide, a deletion and the memory, with a still of the slide as the
picture at the top; then 62 seconds that opened in the IDE's chat, which
played at the top for a few hours. This one is 42 seconds of one take:

1. Dodaios, the assistant Nova: "What do you remember about Sam?" Nova
   answers from its memory (Sam from accounting wants each release note as
   one slide).
2. "Have Claude Code add a --json flag to trailhead's plan command, with
   tests." Nova starts a Claude Code agent: a chat of its own in the
   Agentic IDE.
3. The video switches to the IDE and follows that chat until it is done.
4. Back in Dodaios: Nova's report, with what it checked itself (the tests,
   both outputs, the commit).

From the Claude Code transcripts: the agent ran on Claude Opus 5.5, Nova on
Claude Fable 5.2 and Claude Opus 5.5.

GitHub plays a video in a README only from its own upload store
(`github.com/user-attachments/...`, checked against the `media-src` of
github.com's Content Security Policy, which allows neither
raw.githubusercontent.com nor release assets), and only a file dropped into
a comment or an editor on github.com gets there. The maintainer uploads
`dodaios-demo.mp4` in a comment on a pull request; the README has that
upload URL on a line of its own, which GitHub shows as its player. A new
video takes a new upload: the URL changes with the file.

How it was made, in a Linux container running as root:

- `clip-video-start.sh` starts a fresh instance (`demo-instance.sh`) and
  gives its home a Claude Code configuration that skips Claude Code's own
  warning about bypass mode and its LSP plugin offer, and loads none of the
  container's plugins.
- `clip-video-setup.cjs` does the first run and the warm-up, with
  `DEMO_WARMUP=0,1,2,3` (answer length, the profile, Sam's wish, a deck and
  a reminder), then once more with `DEMO_PARTS=warmup` and one request of
  its own in `DEMO_WARMUP_TEXTS` (a status doc): the start of the chat in
  the video is the end of that conversation.
- `clip-video-take.cjs` films the take (window 1280 x 720 at device scale
  1.5, `DEMO_WINDOW=1280x720 DEMO_SCALE=1.5`, and
  `DEMO_SCRUB=<instance home>=/home/alex`).
- `clip-video-cut.cjs <take> video <out.mp4>` with `clip-video-edit.cjs`
  (`CUT_ANSWER=4.5 CUT_SAID=3.8`) makes the master (CRF 14); the file in
  this folder is the master again with
  `-crf 24 -tune animation -preset slow`, 2.5 MB.

The second take of this version was used. The first asked "What's on my
plate this week?", and Nova offered to connect a calendar with a card that
then waited in the chat.

### The one clip at the top (`hero.webp`), evening of 16 November 2026

The maintainer cut the README down to one sentence, his definition of
Dodaios, one clip and the install. The clip shows one request crossing the
parts of the definition in a single take of 28 seconds: "Add --csv to ledger
list with two agents (code, tests), put a release note on a slide, and delete
ledger's old-exports folder for good." Nova (Claude Opus 5.5) starts two
Claude Code agents (Claude Sonnet 5); their threads open side by side in the
Agentic IDE and finish (12 tests pass); back in the chat the trust layer asks
before the permanent deletion and the person allows it once; the slide arrives
and opens; Nova reports. The chat is set to "Auto-accept edits" before the
take: in a new chat's Bypass permissions nothing asks, not even a permanent
deletion. An un-filmed warm-up tells Nova that the folder is backed up, or it
moves it to the trash or asks a question first.

The call signs of the Grid's terminals (T1, T2) are not in the clip: Claude
Code in a Grid terminal stops at its own warning about bypass mode when the
instance runs as root, so the take uses chat threads.

Scripts: `clip-reel-setup.cjs` (first run and warm-up), `clip-reel-probe.cjs`,
`clip-reel-take.cjs`, `clip-reel-cut.cjs` with `clip-reel-edit.cjs`,
`clip-reel-measure.cjs`, all on `clip-reel-common.cjs`. The WebP needed
`--quality 44` to stay under 5 MB at 1120 px and 60 frames a second.

### The clips of the afternoon of 16 November 2026

All were filmed on 16 November 2026 from `main` (5.5.0), on Linux, in
throwaway instances started by `demo-instance.sh` that were stopped
afterwards. Nova ran on Claude Opus 5.5 through Claude Code, signed in to a
Claude plan; the coding agents ran on Claude Sonnet 5 the same way. Every
answer, edit and test run is real. The models' answers differ from take to
take, so a new recording does not match these word for word.

The maintainer found the clips of 15 November too busy and not smooth
enough (the one at the top played at 24 frames a second). These follow
stricter rules: one idea per clip, 8 to 16 seconds, a small window so the
text reads at README size, every stretch filmed and played at 60 frames a
second at the speed it was filmed, waits for a model cut out with a short
dissolve. 60 is the most an animated WebP can show: browsers draw a frame
that lasts 10 ms or less for 100 ms.

The instances ran as root, which shows a notice that dictation apps cannot
type into the window; every take closes it with a click before it films.
The scrub that replaces the account name in the picture must skip `<style>`
and `<script>` text: as root it turned a node page's `:root` rule into
`:alex`, and decks showed unstyled. `clip-nodes2-common.cjs` and
`clip-assistant2-common.cjs` have that fix; `nodes-plugins-common.cjs` does
not yet.

### The clip at the top (`hero.webp`, `dodaios-demo.mp4`)

16 seconds. In a conversation that is already in use, the request "Have a
Sonnet agent add a --csv flag to ledger's list command and run the tests." is
typed. Nova answers that it puts a Sonnet 5 agent on it, with a link to the
agent's thread; one click opens the thread in the Agentic IDE, where the agent
edits the files and runs the tests (all 12 pass). Back in the chat, Nova
reports. The warm-up tells Nova once to start agents on `claude-sonnet-5`: on
Sonnet 5.5 the agents did all their work in single shell commands, so the
thread showed no edits.

Scripts: `clip-hero-record.cjs` (parts `setup`, `warmup`, `warmup-hero`,
`onehero`), cut with
`FILM_EDIT=clip-hero-edit-hero.js FILM_FPS=60 FILM_CRF=14 node clip-hero-render.cjs <take> hero-master.mp4`,
measured with `clip-hero-measure.py`.

### Your coding agents (`agents.webp`)

12 seconds from the same instance (`DEMO_PARTS=agents`): a third thread opens
beside two others, three Claude Code agents work in three columns on three
small tasks in the sample projects, the middle one finishes, then all three;
last, the thread's agent and model picker shows the rail of coding agents and
the models of Codex. The cut is `clip-hero-edit-agents.js`.

### The assistant (`assistant.webp`)

12 seconds: "How much did I spend on groceries each month this year? The bank
export is in Documents." Nova reads `Documents/bank-2026.csv`, a made-up bank
export with fictional shops that `clip-assistant2-bank.py` writes into the
instance's home folder before the warm-up, and answers with the sums and a
column chart; the pointer moves along the columns. Scripts:
`clip-assistant2-setup.cjs` (first run and warm-up),
`clip-assistant2-assistant.cjs` (the take), `clip-assistant2-cut.cjs` with
`clip-assistant2-edit.cjs`, `clip-assistant2-measure.cjs`, and
`clip-assistant2-ocr.py`, which checks the page's text for private values on
Linux (it does not see what is drawn on a canvas).

### Docs, decks, sheets and whiteboards (`nodes.webp`)

14 seconds: "Make a four-slide deck on brewing pour-over coffee". The deck's
card comes into the chat, opens large, a click on the title opens the editor,
and the title is typed over with "Pour-over, step by step"; the editor saves.
Scripts: `clip-nodes2-setup.cjs`, `clip-nodes2-take.cjs`, `clip-nodes2-cut.cjs`
with `clip-nodes2-edit.cjs`, `clip-nodes2-measure.cjs`. After a click on a
node card the stage shows "Nothing here yet" for about 0.2 s before it draws
the deck; the cut leaves that out.

### Earlier clips of 15 November 2026

The clips they replaced were made with `record.cjs` (parts `hero`, `picker`),
`edit-hero.js`, `edit-agents.js`, `clip-assistant.cjs`, `clip-nodes.cjs` and
`phone-take.cjs`; their last versions are in the history of this folder.

### The Telegram clip

Not recorded yet: Telegram needs a real phone and a person's Telegram
account. `telegram_take.py` does all but the phone part. It runs a throwaway
instance with its own new bot (the token is pasted into a hidden prompt and
never reaches the Keychain), warms it up, waits until the person's first
message pairs the bot, and films the desktop while the assistant answers. The
person records the phone's screen while sending one sentence ("Run the tests
in trailhead and tell me if anything fails.") and sends the recording to the
Mac; the script then cuts both, replaces the sender's Telegram name with the
persona in the desktop picture, and reads every frame for private text. It
refuses the bot of the app you use, because two readers of one bot conflict.
`--dry-run --fake-telegram` runs the whole take against a local stand-in for
Telegram, without a phone.

### The Slack clip

Not recorded yet: Slack needs a real phone and a person's Slack account.
`slack_take.py` does all but the phone part, with the same instance,
warm-up, filming and cut as `telegram_take.py`. It prints a link that opens
Slack's page to create an app from a manifest, with the app "Nova" filled in;
the person creates and installs it in a demo workspace and pastes its two
keys (the bot token and an app-level token with `connections:write`) into
hidden prompts. The keys are checked with Slack, kept in a file only the
person can read, and reach the instance only in its environment, never the
Keychain. The person records the phone's screen while sending the same
sentence in the direct message with Nova; that first message pairs them as
the owner. The script replaces the members' Slack names with the persona in
the desktop picture and reads every frame for private text. It refuses a
Slack app the app you use already runs, because two Socket Mode readers of
one app split its messages. `--dry-run --fake-slack` runs the whole take
against `tests/fakes/slack_standin.py`, a local stand-in for Slack, and
`selftest` checks the channel without a model.

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
python scripts/readme_demo/encode_webp.py hero-master.mp4 assets/demo/readme/hero.webp --width 1120 --fps 24
python scripts/readme_demo/encode_webp.py phone-master.mp4 assets/demo/readme/phone.webp --width 420 --quality 85
python scripts/readme_demo/encode_webp.py nodes-master.mp4 assets/demo/readme/nodes.webp
```

`encode_webp.py` reads the frames with ffmpeg and lets Pillow write the
animated WebP. Between whole pictures it stores only what changed, lossy, and
it stores a whole picture at least every 15 frames: without those, the small
errors pile up and stay on screen as faint blocks after a dissolve or a
scroll. Compare a new picture frame by frame with its master before it goes
in. Keep every picture under 5 MB: every version stays in the repository's
history. The video next to the hero picture is the master
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
