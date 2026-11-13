# README demo

The README opens with one recording of Dodaios at work. It is in this folder
in two forms:

| File | What it is for |
|---|---|
| `dodaios-demo.gif` | Plays by itself and without sound in the README. It is linked with an absolute `raw.githubusercontent.com` URL so it also plays on PyPI. 960 x 540, 10 frames a second |
| `dodaios-demo.mp4` | The same recording with its music, 1920 x 1080, 30 frames a second. The GIF links to it, and GitHub plays it on the file's page |

A short clip of the Nodes section, `dodaios-nodes.gif`, is the other
recording in this folder ([The Nodes clip](#the-nodes-clip)).

| | |
|---|---|
| Length | 55 s, cut from a take of 4 min 40 s |
| Recorded from | `main` of 13 November 2026 (after 5.1.0), a throwaway instance that was deleted afterwards |
| Model | Claude Fable 5.2 through Claude Code, signed in to a Claude plan, for Dodaios and for the coding agent it starts. Every answer and change is real |
| Music | "Making It Look Easy" by Lee Rosevere, from [Music For Podcasts 6](https://archive.org/details/leerosevere_musicforpodcasts_6), licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The licence asks for the credit, so the README names the piece under the recording |

It is about Dodaios itself, the assistant in its own chat, and shows four
requests in a row, in a workspace that is already in use:

1. "How much did we invoice in October, by customer?" Dodaios finds the
   billing export on the computer and answers with a table and a chart.
2. "Make that a page I can send to finance." Dodaios writes the page; the
   conversation gets a card of it, and the page is opened.
3. "Look after ledger's tests for me and tell me if one fails." Dodaios takes
   it on as a standing task, which the panel beside the conversation lists.
4. One invoice is a cent too high: Dodaios checks it and starts a coding
   agent for the fix. The agent's thread in the Agentic IDE is opened from the
   panel while the agent works, and its changes are reviewed as a diff. Back
   in the chat, Dodaios has checked the result itself and reports.

The model's answers differ from take to take, so a new recording does not
match this one word for word.

## What a recording must be

- A recording of the real app and nothing else: no title cards, no words laid
  over the picture, no stage around the window, no motion graphics. The
  maintainer turned down a designed film with captions on 13 November 2026.
- About Dodaios as the assistant you hand things to. It starts with everyday
  requests in its chat; the Agentic IDE comes at the end, and briefly.
- A workspace that is in use, never the first-run setup: `record.cjs` does a
  morning's work in a warm-up that is not filmed.
- No mock-ups and no staged answers. A wait for a model is cut out, never
  replaced by something else.
- Nothing private on screen: no real names, email addresses, account ids or
  keys, no error output and no warning cards. `record.cjs` replaces the name of
  the computer and the home folder of whoever records, and hides the meter
  that shows how much of the plan is used; `DEMO_SCRUB` takes more pairs
  (`text=replacement`, separated by commas).

## How it is made

Two things are kept apart: the footage and the cut.

- **The footage** is filmed by `record.cjs` from an isolated instance:
  2880 x 1620 frames of a 1200 x 675 window, in named stretches (`ask-numbers`,
  `wait-numbers`, `answer-numbers`, `card`, `page`, `thread`, `review` and so
  on). It also writes down when every key of a request was pressed and when
  Dodaios was done with each answer (`take.json`).
- **The cut** is `edit.js`. It keeps the take's own order and does three
  things: the typing plays at an even pace, the wait for a model is left out
  (the picture before it dissolves into the one in which the answer comes),
  and the rest plays a little faster. `film.html` draws the picture for any
  second of the video; `render.cjs` takes a picture of every frame and hands
  them to ffmpeg, which lays the music under them. The video is as long as
  the music.

## Make it again

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
reads or writes the keys of the app you use.

A whole run takes about eight minutes (setup and warm-up three, the take
five) and that much of the plan's usage: two threads, five requests to
Dodaios and two coding agents.

```sh
# 1. A throwaway first-run instance on port 47990, as a normal user.
#    It writes only under /tmp/dodaios-demo and DEMO_HOME, and never touches
#    your own app. DEMO_HOME is the home folder the instance sees; its path
#    can show in the picture, so choose one that reads well.
#    (Linux: put CLAUDE_CODE_OAUTH_TOKEN=... in front, see above.)
DEMO_HOME=/Users/Shared/demo PYTHON=/path/to/venv/bin/python \
  scripts/readme_demo/demo-instance.sh

# 2. In a second terminal: setup, warm-up and the take. It writes the frames
#    and take.json. DEMO_BROWSER=chrome uses an installed Chrome instead of
#    Playwright's own browser.
node scripts/readme_demo/record.cjs /tmp/dodaios-take

# 3. The music (2.3 MB; it is not in the repository).
curl -L -o /tmp/making-it-look-easy.mp3 \
  "https://archive.org/download/leerosevere_musicforpodcasts_6/Lee%20Rosevere%20-%20Music%20For%20Podcasts%206%20-%2005%20Making%20It%20Look%20Easy.mp3"
shasum -a 256 /tmp/making-it-look-easy.mp3
#    4f1bc622469d5c84ec76c61f04c2a594bf9cd80f88d93557e6994f12148df333

# 4. The video with its music, then the GIF from the same cut.
FILM_MUSIC=/tmp/making-it-look-easy.mp3 FILM_CRF=23 \
  node scripts/readme_demo/render.cjs /tmp/dodaios-take dodaios-demo.mp4
FILM_FPS=10 FILM_CRF=8 \
  node scripts/readme_demo/render.cjs /tmp/dodaios-take /tmp/gif-source.mp4
ffmpeg -i /tmp/gif-source.mp4 \
  -vf "fps=10,scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128:stats_mode=diff[p];[b][p]paletteuse=dither=none:diff_mode=rectangle" \
  -loop 0 dodaios-demo.gif
```

Copy both files over the ones in this folder. They are the only recordings
`scripts/ci/check_repo_junk.py` lets into the repository.

Look at a new take before you render it. `FILM_STILLS=6,12.5,31` writes single
pictures of the cut at those seconds, which is quicker than a video. The cut
finds its places by itself (the stretches by name, the typing by its keys,
the answers by the moment Dodaios was done), but how an answer comes differs
from take to take, so the seconds before and after that moment may need a new
number in `edit.js`. A notice of the app's own that happens to stand in the
picture (a toast, for example) is cut around the same way.

`record.cjs` clicks through the interface by its labels and asks the app's
own API whether a model is still at work. When a label or a flow changes, or
a turn cannot reach its model, the script stops at that step, says which one,
and saves a picture of the screen as `failure.png`. `DEMO_PARTS` runs only
some of the parts (`setup`, `warmup`, `take`).

A take that fails need not cost the warm-up. Stop the instance after
`DEMO_PARTS=setup,warmup`, copy `DEMO_HOME` and `/tmp/dodaios-demo/state`
away, and start the instance again with `DEMO_KEEP=1`, which wipes nothing.
Before each further attempt, stop it, copy both folders back and start it
with `DEMO_KEEP=1` again.

The instance runs the code of the Python environment you name. If that is a
checkout that follows `main` by itself, a merge in the middle of a take
changes the app under it: point `PYTHONPATH` at a checkout that stands still
(with its own built bundle) before you start the instance. Do nothing heavy
on the computer while a take films.

## Screenshots

The pictures in `assets/readme/` come from the same instance, right after the
take (1920 x 1280):

```sh
node scripts/readme_demo/stills.cjs /tmp/dodaios-stills plugins pets ide
# "connect" is the setup step: start the demo instance again first.
node scripts/readme_demo/stills.cjs /tmp/dodaios-stills connect
```

## The Nodes clip

`dodaios-nodes.gif` plays in the README's part about Nodes. It opens at the
top of the Nodes section, passes over the seven type cards, lets the
Analytics card narrow the list, opens the dashboard and scrolls it, and then
takes the slide deck from its title slide to the next. 960 x 600, 12 frames a
second, 31 s, from a 1440 x 900 window: at 1280 the type card "Whiteboard" is
cut short.

| | |
|---|---|
| Recorded from | `main` of 13 November 2026 (after 5.2.0), a throwaway instance that was deleted afterwards |
| Content | One node of each type, each the example its type ships with (`EXAMPLE` in `dodaios/nodes/kinds/*.py`), put into the node store by `seed_nodes.py`. No model made them, and no model runs in the clip |

The rules for the film hold here as well: the real app and nothing else, and
nothing private on screen. No Claude Code login is needed.

```sh
# 1. A throwaway instance, the same as for the film.
PYTHON=/path/to/venv/bin/python scripts/readme_demo/demo-instance.sh

# 2. In a second terminal: the seven nodes, with the instance's paths.
JARVIS_DATA_DIR=/tmp/dodaios-demo/state/data \
JARVIS_CONFIG=/tmp/dodaios-demo/state/dodaios.toml \
HOME=/tmp/dodaios-demo/home \
  /path/to/venv/bin/python scripts/readme_demo/seed_nodes.py

# 3. The take. It marks the first-run steps done, films the section and
#    writes cut.json: the WebM and the seconds the clip starts and ends in it.
node scripts/readme_demo/nodes.cjs /tmp/dodaios-nodes

# 4. The GIF. FILE, FROM and TO are the three values in cut.json.
ffmpeg -ss "$FROM" -to "$TO" -i "/tmp/dodaios-nodes/$FILE" \
  -vf "fps=12,scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128:stats_mode=diff[p];[b][p]paletteuse=dither=none:diff_mode=rectangle" \
  -loop 0 dodaios-nodes.gif
```

Copy the GIF over the one in this folder. Keep it under 5 MB: every version
stays in the repository's history.

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
