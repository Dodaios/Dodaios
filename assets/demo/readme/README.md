# README demo

The README opens with one recording of Dodaios at work: one request that goes
to five coding agents. It is in this folder in two forms:

| File | What it is for |
|---|---|
| `dodaios-demo.gif` | Plays by itself and without sound in the README. It is linked with an absolute `raw.githubusercontent.com` URL so it also plays on PyPI. 960 x 540, 10 frames a second |
| `dodaios-demo.mp4` | The same recording as a video, 1920 x 1080, 30 frames a second, without sound. The GIF links to it, and GitHub plays it on the file's page |

A short clip of the Nodes section, `dodaios-nodes.gif`, is the other
recording in this folder ([The Nodes clip](#the-nodes-clip)).

| | |
|---|---|
| Length | 30 s, cut from a take of 2 min 9 s |
| Recorded from | `main` of 14 November 2026 (after 5.3.0), a throwaway instance that was deleted afterwards |
| Models | Dodaios on Claude Opus 5.5, its five coding agents on Claude Sonnet 5.5, all through Claude Code, signed in to a Claude plan. Every answer and every review is real |
| Project | A private demo repository on GitHub with five open pull requests. The agents read them with the GitHub CLI |
| Sound | None |

It shows one request to Dodaios, in a workspace that is already in use:

1. "Review the new PRs in acme-notes, one Sonnet agent per PR, and write me a
   report." Dodaios answers that it will list the open pull requests and put
   an agent on each.
2. The Agentic IDE is opened. A thread appears under the project for each
   pull request, with a spinner while its agent works.
3. Three of the threads are opened in turn: the brief Dodaios wrote, an agent
   that reads the diff and runs the tests, a finished review with its verdict.
4. Back in the chat, Dodaios posts the card of a report and an answer of two
   sentences: which pull requests are ready to merge, and which one is not.
5. The report is opened from its card: its summary, its key figures and a
   table with a verdict for each pull request.

The model's answers differ from take to take, so a new recording does not
match this one word for word. Which pull request the agents object to differs
as well.

## What a recording must be

- A recording of the real app and nothing else: no title cards, no words laid
  over the picture, no stage around the window, no motion graphics. The
  maintainer turned down a designed film with captions on 13 November 2026.
- About Dodaios as the one you hand things to. The request is made in its
  chat and the answer comes back there. The Agentic IDE is where the agents
  are seen at work.
- A workspace that is in use, never the first-run setup: `record.cjs` does a
  morning's work in a warm-up that is not filmed.
- No mock-ups and no staged answers. A wait for a model is cut out, never
  replaced by something else.
- Nothing private on screen: no real names, email addresses, account ids or
  keys, no error output and no warning cards. `record.cjs` replaces the name of
  the computer and the home folder of whoever records, and hides the meter
  that shows how much of the plan is used; `DEMO_SCRUB` takes more pairs
  (`text=replacement`, separated by commas). A report on pull requests names
  their author: give `DEMO_SCRUB` the name and the login of the GitHub account.
- Readable in a small player: the clip is filmed in a window of 960 x 540, so
  the GIF shows the app's text at its real size.

## How it is made

Two things are kept apart: the footage and the cut.

- **The footage** is filmed by `record.cjs` from an isolated instance, in
  named stretches (`ask-review`, `ack`, `to-ide`, `starting`, `watch-1` to
  `watch-3`, `finishing`, `done`, `to-chat`, `report`, `open-report`, `page`).
  It also writes down when every key of the request was pressed and the
  moments the cut needs: when an agent showed its next step, when the report
  and the answer came (`take.json`).
- **The cut** is `edit-agents.js`. It keeps the take's own order and does
  three things: the typing plays at an even pace, a wait for a model is left
  out (the picture before it dissolves into the one after it), and the rest
  plays a little faster. `film.html` draws the picture for any second of the
  video; `render.cjs` takes a picture of every frame and hands them to ffmpeg.

## Make it again

The interface changes often, so the recording is made by scripts in
`scripts/readme_demo/`. They need Linux or macOS, Node.js with Playwright,
ffmpeg, a Python environment that has Dodaios, `ptyprocess` and `pytest`, a
built frontend bundle, Claude Code signed in to a Claude plan, and the GitHub
CLI signed in to an account that can read a repository with a few open pull
requests. The CLI must be a current one: an old one fails on `gh pr view`
("Projects (classic) is being deprecated"), and the failed call shows in red
in the agents' threads.

The instance gets a home folder of its own, so Claude Code there does not see
a login kept under your own home folder. On macOS the login is in your
Keychain; the instance script links the Keychain folder into the instance's
home folder so Claude Code finds it. On Linux, create a token with
`claude setup-token` and start the instance with it in
`CLAUDE_CODE_OAUTH_TOKEN`; the instance hands its environment to Claude Code.
The GitHub login reaches the instance as `GH_TOKEN`. The instance keeps its
own keys in a file under its data folder and never reads or writes the keys of
the app you use.

Start the instance from a plain terminal. Started from the shell of a coding
agent, it inherits that agent's session variables and hands them on to the
agents it starts.

A whole run takes about six minutes (setup and warm-up three and a half, the
take two to three) and that much of the plan's usage: three threads and three
requests to Dodaios in the warm-up, then one request and five coding agents.

```sh
# 1. A throwaway first-run instance on port 47990, as a normal user.
#    It writes only under /tmp/dodaios-demo and DEMO_HOME, and never touches
#    your own app. DEMO_HOME is the home folder the instance sees; its path
#    can show in the picture, so choose one that reads well. DEMO_PR_REPO is
#    the repository with the open pull requests; it is cloned as a project.
#    (Linux: put CLAUDE_CODE_OAUTH_TOKEN=... in front, see above.)
DEMO_HOME=/Users/Shared/demo DEMO_PR_REPO=your-org/your-demo-repo \
  PYTHON=/path/to/venv/bin/python scripts/readme_demo/demo-instance.sh

# 2. In a second terminal: setup, warm-up and the take. It writes the frames
#    and take.json. DEMO_BROWSER=chrome uses an installed Chrome instead of
#    Playwright's own browser. DEMO_MODEL is the model of Dodaios itself.
DEMO_PARTS=setup,warmup,warmup-agents,agents DEMO_PR_PROJECT=your-demo-repo \
DEMO_WINDOW=960x540 DEMO_SCALE=2 DEMO_MODEL="Claude Opus 5.5" \
DEMO_SCRUB="Your Name=Alex Rivera,your-login=alexrivera" \
  node scripts/readme_demo/record.cjs /tmp/dodaios-take

# 3. The video, then the GIF from the same cut.
FILM_EDIT=edit-agents.js FILM_CRF=20 \
  node scripts/readme_demo/render.cjs /tmp/dodaios-take dodaios-demo.mp4
FILM_EDIT=edit-agents.js FILM_FPS=10 FILM_CRF=8 \
  node scripts/readme_demo/render.cjs /tmp/dodaios-take /tmp/gif-source.mp4
ffmpeg -i /tmp/gif-source.mp4 \
  -vf "fps=10,scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128:stats_mode=diff[p];[b][p]paletteuse=dither=none:diff_mode=rectangle" \
  -loop 0 dodaios-demo.gif
```

Copy both files over the ones in this folder. They are the only recordings
`scripts/ci/check_repo_junk.py` lets into the repository.

Look at a new take before you render it. `FILM_STILLS=6,12.5,24` writes single
pictures of the cut at those seconds, which is quicker than a video. The cut
finds its places by itself (the stretches by name, the typing by its keys,
the answers by the moments `record.cjs` wrote down), but a take differs from
the last one, so a number in `edit-agents.js` may need a new value.

`record.cjs` clicks through the interface by its labels and asks the app's
own API whether a model is still at work. When a label or a flow changes, or
a turn cannot reach its model, the script stops at that step, says which one,
and saves a picture of the screen as `failure.png`. `DEMO_PARTS` runs only
some of the parts (`setup`, `warmup`, `warmup-agents`, `agents`, `take`).

Not every take is one to keep. Of the seven filmed for this clip, one ended
without a report, and in the first a notice of the app's own stood in the
picture. What the scripts do about it:

- The warm-up asks Dodaios for answers of two sentences, the way a person
  would have said long ago, and for a short report. That uses enough different
  tools for the app's "Tool Dabbler" achievement to come up there, and not as
  a toast in the clip.
- The project with the pull requests is connected first, so its threads stand
  at the top of the thread list and do not fall below the small window.
- A look into a thread waits until the agent has shown its next step. How long
  an agent takes for a step differs a lot.

A take that fails need not cost the warm-up. Stop the instance after
`DEMO_PARTS=setup,warmup,warmup-agents`, copy `DEMO_HOME` and
`/tmp/dodaios-demo/state` away, and start the instance again with
`DEMO_KEEP=1`, which wipes nothing. Before each further attempt, stop it, copy
both folders back and start it with `DEMO_KEEP=1` again.

The instance runs the code of the Python environment you name. If that is a
checkout that follows `main` by itself, a merge in the middle of a take
changes the app under it: point `PYTHONPATH` at a checkout that stands still
(with its own built bundle) before you start the instance. Do nothing heavy
on the computer while a take films.

## The earlier film

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

## Screenshots

The pictures in `assets/readme/` come from the instance of the earlier film,
right after its take (1920 x 1280). The feature tour
(`docs/feature-tour.md`) shows them.

```sh
node scripts/readme_demo/stills.cjs /tmp/dodaios-stills plugins pets ide
# "connect" is the setup step: start the demo instance again first.
node scripts/readme_demo/stills.cjs /tmp/dodaios-stills connect
```

## The Nodes clip

`dodaios-nodes.gif` plays in the feature tour's part about Nodes
(`docs/feature-tour.md`). It opens at the top of the Nodes section, passes
over the seven type cards, lets the Analytics card narrow the list, opens the
dashboard and scrolls it, and then takes the slide deck two slides on, from
its title to a bar chart. 960 x 600, 12 frames a second, 31 s, from a
1440 x 900 window: at 1280 the type card "Whiteboard" is cut short.

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
