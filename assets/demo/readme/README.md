# README demo

The README opens with one film that introduces Dodaios. It is in this folder
in two forms:

| File | What it is for |
|---|---|
| `dodaios-demo.gif` | Plays by itself and without sound in the README. It is linked with an absolute `raw.githubusercontent.com` URL so it also plays on PyPI. 800 x 450, 10 frames a second, on a plain stage |
| `dodaios-intro.mp4` | The same film with its music, 1920 x 1080, 30 frames a second. The GIF links to it, and GitHub plays it on the file's page |

| | |
|---|---|
| Length | 55 s, the length of the music. Cut from a take of 11 minutes |
| Recorded from | `main` of 13 November 2026 (after 5.1.0), a throwaway instance that was deleted afterwards |
| Models | Claude Fable 5.2 (Dodaios and one coding agent) and Claude Sonnet 5.5 (the other coding agent) through Claude Code, signed in to a Claude plan. Every answer and change is real |
| Music | "Making It Look Easy" by Lee Rosevere, from [Music For Podcasts 6](https://archive.org/details/leerosevere_musicforpodcasts_6), licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The licence asks for the credit, so the README names the piece under the film |

What the film shows, in order:

1. The name, and "Your super agent."
2. A request is typed into the chat with Dodaios: an invoice is one cent too
   high, and the other project needs a `--pace` option.
3. Dodaios finds the cause. The panel beside the conversation says what it is
   doing. Its answer names the two coding agents it started.
4. A click on an agent's name opens the agent's thread in the Agentic IDE.
   The first agent finishes; the other agent's thread is opened.
5. The first agent's changes in the review, as a diff.
6. Back in the chat: Dodaios has run the checks itself and reports.
7. Dodaios is asked for a dashboard and builds it as an artifact.
8. One second each of plugins, memory, the model picker and the desktop pet.
9. "Turn your computer into an AI agent.", the name, the repository's address.

The model's answers differ from take to take, so a new film does not match
this one word for word.

## How the film is made

Two things are kept apart: the footage and the cut.

- **The footage** is the real app, filmed by `record.cjs` from an isolated
  instance: 2880 x 1620 frames of a 1200 x 675 window, in named stretches
  (`ask`, `answer`, `thread`, `review-ledger`, `artifact`, `tour-plugins` and
  so on). Nothing is laid over it and nothing in it is staged. The workspace
  is in use before the first frame: the script does a morning's work in a
  warm-up that is not filmed.
- **The cut** is `edit.js`: which stretch is on screen when, how fast it
  plays, which part of the window the picture moves in on, and the few words
  above it. Every cut is on a beat of the music. `film.html` draws the
  picture for any second of the film (the stage, the cards, the words);
  `render.cjs` takes a picture of every frame and hands them to ffmpeg.

A wait for a model is shortened, never replaced: the footage runs faster until
the answer is there.

## Requirements for the footage

- The real app, filmed from an isolated demo instance. No mock-ups and no
  staged answers.
- Nothing private on screen: no real names, email addresses, account ids or
  keys, no error output and no warning cards. `record.cjs` replaces the name of
  the computer and the home folder of whoever records, and hides the meter
  that shows how much of the plan is used; `DEMO_SCRUB` takes more pairs
  (`text=replacement`, separated by commas).
- Words in the film say only what the footage under them shows.

## Make it again

The interface changes often, so the film is made by scripts in
`scripts/readme_demo/`. They need Linux or macOS, Node.js with Playwright,
ffmpeg, a Python environment that has Dodaios, `ptyprocess` and `pytest`, a
built frontend bundle (it also brings the two fonts of the film), and Claude
Code signed in to a Claude plan that has Fable 5.2 (`DEMO_MODEL` and
`DEMO_SECOND_MODEL` name other models of the picker).

The instance gets a home folder of its own, so Claude Code there does not see
a login kept under your own home folder. On macOS the login is in your
Keychain; the instance script links the Keychain folder into the instance's
home folder so Claude Code finds it. On Linux, create a token with
`claude setup-token` and start the instance with it in
`CLAUDE_CODE_OAUTH_TOKEN`; the instance hands its environment to Claude Code.
The instance keeps its own keys in a file under its data folder and never
reads or writes the keys of the app you use.

A whole run takes about twenty-five minutes, most of it two artifacts being
built (five to nine minutes each), and that much of the plan's usage: two
threads, four requests to Dodaios, three coding agents and two artifacts.

```sh
# 1. A throwaway first-run instance on port 47990, as a normal user.
#    It writes only under /tmp/dodaios-demo and DEMO_HOME, and never touches
#    your own app. DEMO_HOME is the home folder the instance sees; its path
#    can show in the picture, so choose one that reads well.
#    (Linux: put CLAUDE_CODE_OAUTH_TOKEN=... in front, see above.)
DEMO_HOME=/Users/Shared/demo PYTHON=/path/to/venv/bin/python \
  scripts/readme_demo/demo-instance.sh

# 2. In a second terminal: setup, warm-up, the take and the tour. It writes
#    the frames and take.json (every frame's time, the stretches, the places
#    the cut moves in on). DEMO_BROWSER=chrome uses an installed Chrome
#    instead of Playwright's own browser.
node scripts/readme_demo/record.cjs /tmp/dodaios-take

# 3. The music (2.3 MB; it is not in the repository).
curl -L -o /tmp/making-it-look-easy.mp3 \
  "https://archive.org/download/leerosevere_musicforpodcasts_6/Lee%20Rosevere%20-%20Music%20For%20Podcasts%206%20-%2005%20Making%20It%20Look%20Easy.mp3"
shasum -a 256 /tmp/making-it-look-easy.mp3
#    4f1bc622469d5c84ec76c61f04c2a594bf9cd80f88d93557e6994f12148df333

# 4. The film with its music, then the GIF: the same cut on a plain stage,
#    because drifting lights would change every pixel of every frame.
FILM_MUSIC=/tmp/making-it-look-easy.mp3 FILM_CRF=23 \
  node scripts/readme_demo/render.cjs /tmp/dodaios-take dodaios-intro.mp4
FILM_PLAIN=1 FILM_FPS=10 FILM_CRF=8 \
  node scripts/readme_demo/render.cjs /tmp/dodaios-take /tmp/plain.mp4
ffmpeg -i /tmp/plain.mp4 \
  -vf "fps=10,scale=800:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128:stats_mode=full[p];[b][p]paletteuse=dither=none:diff_mode=rectangle" \
  -loop 0 dodaios-demo.gif
```

Copy both files over the ones in this folder. They are the only recordings
`scripts/ci/check_repo_junk.py` lets into the repository.

Look at a new take before you render it. `FILM_STILLS=6,12.5,31` writes single
pictures of the cut at those seconds, which is quicker than a film. The cut
finds most things by itself (the stretches by name, the composer, the agent's
name and the review by the places `record.cjs` wrote down), but how long
Dodaios takes to answer and what it writes differ, so the speed of a stretch
or the part of the window shown may need a new number in `edit.js`.

`record.cjs` clicks through the interface by its labels and asks the app's
own API whether a model is still at work. When a label or a flow changes, or
a turn cannot reach its model, the script stops at that step, says which one,
and saves a picture of the screen as `failure.png`. `DEMO_PARTS` runs only
some of the parts (`setup`, `warmup`, `take`, `tour`); the tour alone adds
its footage to a take that is already in the folder.

A take that fails need not cost the warm-up. Stop the instance after
`DEMO_PARTS=setup,warmup`, copy `DEMO_HOME` and `/tmp/dodaios-demo/state`
away, and start the instance again with `DEMO_KEEP=1`, which wipes nothing.
Before each further attempt, stop it, copy both folders back and start it
with `DEMO_KEEP=1` again.

The instance runs the code of the Python environment you name. If that is a
checkout that follows `main` by itself, a merge in the middle of a take
changes the app under it: point `PYTHONPATH` at a checkout that stands still
(with its own built bundle) before you start the instance.

## Screenshots

The pictures in `assets/readme/` come from the same instance, right after the
take (1920 x 1280):

```sh
node scripts/readme_demo/stills.cjs /tmp/dodaios-stills memory plugins pets ide
# "connect" is the setup step: start the demo instance again first.
node scripts/readme_demo/stills.cjs /tmp/dodaios-stills connect
```

## A video with a player

GitHub plays a video inline in a README only when it is a user attachment; a
`<video>` tag or a link to a file in the repository is not turned into a
player. To show the MP4 with a player in the README itself, drop it into a
comment box on an issue or pull request of the repository, wait for the
upload and post the comment (an attachment in an unposted comment stays
private). The comment then holds a
`https://github.com/user-attachments/assets/...` URL. Put that URL on a line of its own in `README.md` and
`README.zh-CN.md`, in place of the GIF. GitHub accepts up to 10 MB for an
inline video on a free plan, and the player starts muted. PyPI shows such a
line as a bare link, which is why the README uses the GIF.

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
