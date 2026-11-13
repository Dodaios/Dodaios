# Agentic IDE: thread layout

The Agentic IDE has two layouts, switched with the rounded switch in the
middle of the window caption:

- **Terminal grid** — workspaces of terminal panes, each running a coding CLI.
- **Threads** — one conversation with a coding agent at a time.

Switching never stops anything: the grid stays mounted behind the thread view,
so its terminals keep running and come back exactly as they were.

## What a thread is

A thread is an agent-chat session on the IDE's own surface (`agent`). The
coding CLI — Claude Code, Codex, OpenCode, Grok Build, Antigravity, … — is
driven through its own binary (`dodaios/agent_chat/runner_cli.py`), so its
tools, skills, MCP servers, permissions and subscription login are the CLI's,
and the conversation is the CLI's own session (resumed with its own id). No
second harness sits in between.

A thread belongs to a project: the one it was started in, else the deepest
connected project folder that holds the thread's folder.

## Sidebar

On top, three start rows: New thread, New team thread (both in the project in
view, else the first one) and Dodaios Live. Below, "Pinned" and "Projects"
(its folder icon connects another folder), each project with its threads,
newest first. A thread is named by the title its
CLI gave the conversation (Claude Code's session title, Codex's thread name —
`cli_title` on `GET /api/agent-chat/sessions?surface=agent`), until the person
renames it; before the CLI names it, the first message is the name. The row
starts with the CLI's logo; its end shows how long ago it last moved, a spinner
while it works, an amber dot while it waits for an approval and a blue dot for
news since it was last opened.

## Thread view

- **New thread:** the top row, or the pen on a hovered project row. The empty thread asks what
  to build in the project; the project name is a picker.
- **Title bar:** an open thread has the same controls as a grid pane's
  header: review the changes in the thread's folder, show them in the Git
  tab, more actions (rename, new thread, archive), fold the app sidebar to
  its rail for more room, a new thread in the project, and close — which
  moves the thread to the archive (not while it works or waits for an
  approval). After the title stands the thread's code (`#3f9a2c`); a click
  copies it for Dodaios (see "Pointing Dodaios at a coding agent").
- **Conversation:** the person's messages on the right, the agent's answer as
  reading text, the work in between as folded rows ("Ran 3 commands, read 2
  files") that open to each call, its diff or its output. A running turn ends
  in a live "Working for 12s" line; a finished one says how long it worked and
  which files it changed. When the agent has written its message but still
  waits for background tasks it started (a test run, a push), the line says
  so instead: "Waiting for 2 background tasks · 21m 40s", with the tasks
  named. The agent picks up again when they finish. Grok Build's stream
  names only the tasks its tool results mention (a background shell, a
  sub-agent, a `monitor`); when it waits on work none of them named, the
  wait shows one task called "background work". While tasks are open the turn
  waits as long as they run; there is no clock.
- **When a turn ends:** as soon as the CLI sent its final answer, is idle
  and has nothing running in the background. A background task that ends
  after an answer wakes the agent again, and its next answer still belongs
  to the turn. Behind the finished turn the CLI shuts down by itself
  (SessionEnd/Stop hooks, a session-file flush); it is ended only after it
  printed nothing for two minutes (15 s once the thread's next turn waits
  for it). Stop also ends that wait. A process the CLI left behind that
  still holds its output open does not hold the turn either.
- **Composer:** one toolbar — coding agent and model, reasoning effort, access
  mode — beside the paperclip and the send button. A new thread starts on the
  agent, model, effort and access the person picked last (else the newest
  thread's). Files and images go in by drop, paste or paperclip; `/` `@` `$`
  open the typeahead where the CLI offers it. An approval or a question the
  agent waits on opens at the top of the composer. A message sent while the
  turn is open goes into that turn on Claude Code and GLM, pictures included:
  while the agent works, and while it waits for its background tasks after
  an answer. It shows in the turn as the person's own line and the agent
  answers it at once; the wait for the tasks goes on. Every other coding
  agent, and a message with tool picks, queues it as the next turn; after
  Stop the queue waits.
- **Under the composer:** a strip that says where the agent works — the
  current checkout or a fresh git worktree for a new thread — and on which
  branch (the base of the worktree, or the branch to switch the checkout to).
- **Caption buttons:** at the right end of the window caption, beside the
  window buttons. In threads there are two: the terminal drawer, then the side
  panel. The grid has only the side panel button, since its panes are
  terminals already. A shut side panel leaves no rail on the window edge. Its
  button gets an amber dot while an agent of the active workspace waits for
  the person.
- **Terminal drawer:** plain shells under the conversation, in the open
  thread's folder, one tab each. The first press starts the folder's first
  shell, the next one hides the drawer without ending anything, and the top
  edge drags to resize. Threads that share a folder share its shells, and they
  keep running while the person moves between threads or back to the grid.
  Closing a tab ends that shell, and the drawer goes down with the folder's
  last one.
- Changes, files, git and more terminals live in the IDE's side panel, as in
  the grid layout.

## Questions, approvals and plans

Every coding agent gets the same cards at the top of the composer
(`dodaios/agent_chat/turn_prompts.py`):

| Moment | Claude Code, GLM | Every other CLI (Codex, Antigravity, Grok Build, OpenCode, Kimi, Cursor, DeepSeek Harness) |
|---|---|---|
| The agent has a question | Its own `AskUserQuestion` opens the question card mid-turn; the answers go back on the control protocol and it keeps working | It ends its reply with a `jarvis-ask` block (the protocol rides in front of every prompt); the card opens when the turn ends and the answers are the next message |
| The plan is ready | `ExitPlanMode` opens a plan card with the plan itself; **Build it** switches the thread to the runner's build mode and the same turn starts building | A turn that finished in plan mode opens a plan card; **Build it** switches the thread to the runner's build mode and sends the go-ahead |
| A tool needs permission | The approval card (Approve, Always allow, Decline) | The CLI cannot ask from a headless run: the access mode decides, as each mode's description says |

The question card is the question and nothing else: no header row. It shows
the question, the agent's options as lettered rows (its recommendation first)
and a row for a typed answer behind the next letter. Its foot holds **Skip**,
which leaves that question to the agent, beside the main button; a series of
questions adds a dot per question on the left, **Back**, a review step before
one **Send answers**, and a small menu that leaves every open question to the
agent's recommendations. The same card is drawn on the front page, in the IDE
and in an agent's chat. Claude Code writes its recommendation into an option's
label ("… (Recommended)"); the card takes the suffix off and puts that option
first, under its own mark.

What stays of a card once it is answered, skipped or closed depends on the
view. A thread in the IDE and the work view keep one quiet line with the
answers, which opens into the questions. The conversation with the assistant
(the front page, an agent's chat) keeps nothing: the card is gone the moment
the person sends it, and comes back only when the answer did not get through.
A reply the person typed to answer the card stays as their own bubble. **Keep planning** closes a plan card so the person can type
what to change. A card nobody answered closes when the person sends another
message instead. Cards are rebuilt from the session's event log, so they
survive reopening the thread and restarting the app.

## Threads a Dodaios agent starts

A Dodaios agent can start a thread too ("let Opus 5.5 build this in the
website project"). It picks the coding agent, model and folder the person
named — looking into the folder first when it needs context — and writes the
brief itself. The thread then appears under its project like any other; the
agent's messages carry its name above the bubble, so the person sees exactly
what it asked and what came back, and can step in at any time.

The agent's own chat shows a line that opens the thread. When a turn the
agent started finishes, asks a question, presents a plan or waits for an
approval, the agent is woken with the result: it checks the work, answers the
question or plan card, sends a follow-up, and tells the person the outcome.
A thread an agent opens runs with full access (bypass permissions), so it does
not stop for approvals; the person can lower that in the composer. A turn the
person types into the thread is theirs and wakes no agent. After 25 automatic
updates for one thread the agent stops following it until the person writes
in the agent's chat again.

## Coding agents Dodaios starts for you

When you ask Dodaios for a new coding agent, by voice or in its chat ("start
two Claude Code agents in the website project and let them fix the tests"),
each agent opens as a thread, not as a terminal pane. The IDE opens in Chat,
so the new agent is where you look. Dodaios opens a terminal pane in the grid
only when you ask for one: a terminal, a pane, or the grid.

- **Where:** the folder of the workspace you named or see, else the project
  you named, else the folder you gave. No workspace has to be open. For a new
  project Dodaios makes the folder first; the thread connects it as a project.
- **Which agent:** the coding agent you named, else the one that has the
  model you named ("a Fable 5.2 agent"), else the one your newest thread runs
  on, else the first one installed.
- **Model and effort:** the ones you named ("Fable 5.2 on max"), else the
  coding agent's own defaults.
- **Access:** the app's default access mode, the one a grid pane opens in
  too. For Claude Code and Codex that is the mode that never asks (bypass
  permissions, full access). You can lower it in the thread's composer.
- **What you see:** after a spoken request the IDE comes forward in Chat on
  the new thread. Dodaios's chat adds no line for the start: you asked for it,
  and the thread is in the IDE.
- **The result:** when the turn Dodaios started finishes, fails, asks a
  question or waits for an approval, Dodaios tells you in the conversation
  that asked, in its own words, followed by its report card when it wrote
  one. The thread's own result is Dodaios's material and is not drawn in the
  chat. Only when no answer of Dodaios takes it up (you stopped the waiting
  turn, or the wait was lost in a restart) does the chat keep one line,
  "Claude Code is finished", that opens the thread
  (`components/agentchat/agentResults.ts`). A turn you type into the thread
  yourself is yours.
- **Later:** Dodaios can send a follow-up to the thread, read it, stop its
  turn and list it in its status ("how far are they"). Answering the thread's
  cards and archiving it stay with you.
- **Fallback:** a coding CLI you added yourself has no chat mode. Dodaios
  opens it as a pane and says so.

The code is `dodaios/agentic_ide/chat_threads.py`. The tool is
`workspace-orchestrate`: `create` and `open_workspace`, with `mode` `chat` or
`grid`, `model` and `effort`. The lead reaches it as `delegate` with the target
`coding_agent`. The app's own routes that open a grid workspace or grid
terminals are not offered as app actions, so a model cannot open a grid for a
new agent by another way.

## Pointing Dodaios at a coding agent

When you say "agent" to Dodaios, it takes that as a coding agent: a thread or
a pane of the Agentic IDE. It means something else only when the conversation
says so (a named Dodaios agent such as a Scout, for example).

Dodaios reaches every thread, not only the ones that work right now:

- **By its code.** Every thread has a code, six characters such as `#3f9a2c`.
  It stands after the title in the thread's title bar; a click copies it. The
  thread's menu and its row menu in the sidebar have "Copy code for Dodaios"
  too. Give Dodaios the code ("look at #3f9a2c") and it knows which agent you
  mean. The code is the start of the thread's id, so it never changes and
  every thread that exists has one.
- **By words.** "The agent that fixed the Safari cookie" is enough: Dodaios
  searches the titles and the messages of all threads, old ones included, and
  asks when several fit.
- **Reading in.** Dodaios then reads the thread: its newest messages first,
  and the whole conversation in pages when it needs the history.

In its answer Dodaios names a coding agent as a link: the thread's title with
the coding agent's logo behind it. A click opens the thread in the Agentic
IDE. The link always shows the thread's current title, also after a rename; a
thread that was deleted leaves plain words.

For the model this is `workspace-orchestrate` `find` (`code`, or `query`, or
neither for the newest threads; `project`, `workspace` or `folder` narrow it).
A code also works as `terminal_id` for `observe`, `context`, `send`,
`interrupt` and `watch`. `context` pages through a thread with the `cursor`
it returns. Every thread row carries `link`, the markdown
`[title](thread:<session id>)` the chat draws as the link above
(`dodaios/agentic_ide/thread_finder.py`, `GET /api/agent-chat/thread-links/{ref}`,
`CodingAgentLink.tsx`).

## Team threads

The people icon on a project row gives one task to several coding agents on
different models. They plan alone, challenge each other, agree on one plan,
and one builds while the others review, all in one shared thread:
[`agentic-ide-team-threads.md`](agentic-ide-team-threads.md).

## Restarts do not stop a thread

A thread's coding CLI does not run as a child of the app. It runs in the
turn host (`dodaios/agent_chat/turn_host.py`), a small background process
that the app starts on first use and talks to over a loopback socket. The
terminal grid keeps its agents in the PTY host the same way. The host keeps
every line the CLI prints and streams them to the app.

- **Restart, update, crash:** the CLI keeps working. The next app start
  attaches again. It feeds the lines the old app already handled back into
  the translator without showing them twice, then carries the turn on live:
  new output, approval cards, the real ending.
- **Quit:** the turn stays open while the CLI works. A turn that ends while
  no app is attached is written to a spool folder, and the next start shows
  its answer.
- **Stop** ends the CLI; the turn reads stopped within about two seconds,
  even when a process the CLI started still holds its output open.
- **Another app process takes over** (a second start of the same instance):
  the old process hands its turns over without ending them.
- **Input after the answer:** Claude Code reads its input on while it waits
  for background tasks. The host keeps that input open while an app reads
  the turn, and the app closes it when the turn is over. A turn no app has
  read for two minutes gets it closed by the host, so the CLI still ends.
- **App updates:** the host outlives the app, so it can run older code. The
  app replaces a host of another build at the next thread start at which
  the host holds no turn; a host with turns is never touched.

## Scrolling back in a grid pane

A grid pane is xterm.js, and its scrollback lives in that xterm instance. The
instance is built again each time the pane is joined: after a switch of
workspace, a reload, an app restart, and whenever the grid was unmounted. It is
built from the replay that `ReplayBuffer` (`dodaios/agentic_ide/transcript.py`)
hands to the viewer, so the pane can be scrolled back exactly as far as that
replay reaches.

The replay has two parts:

- **The screen.** The last 128 KB of the agent's raw output
  (`REPLAY_LIMIT_CHARS`). A resize drops it, because cursor moves made for one
  grid do not fit another, and the agent is asked to paint again.
- **The history.** Every row that scrolled off the top of the screen, kept as
  text and colour by `ScrollbackMirror` (`dodaios/agentic_ide/scrollback.py`).
  It holds 10,000 rows (`HISTORY_LIMIT_ROWS`, the same number as the pane's
  own `scrollback` option) and at most 1 MB (`HISTORY_LIMIT_CHARS`). Text fits
  any grid, so a resize keeps it.

`ScrollbackMirror` replays the output onto a grid the way xterm does, and that
is how it knows which rows scrolled off. It must know the pane's size for this:
every place that resizes a PTY also calls `ReplayBuffer.resize`. The app and
the PTY host each keep one buffer per pane; after an app restart the host's
replay fills the app's.

A pane on the alternate screen (Claude Code with its fullscreen renderer, an
editor) gets the screen part only. There the CLI scrolls its own conversation
and the wheel is sent to it.

What the person sees:

| What happens | Are the earlier rows still there? |
|---|---|
| A switch between Chat and Grid, or to another workspace and back | Yes |
| The pane is resized, maximized or moved | Yes. The agent draws its current screen again for the new size; the rows above it stay |
| The window is reloaded, or the app is closed and opened while the agent keeps running | Yes. The PTY host keeps them with the agent |
| The pane is restarted or closed, or the computer restarts | No. The rows belong to the process that printed them. A resumed CLI prints what it shows of its own conversation |

The book button in the pane header opens the conversation the CLI recorded.
That record does not have the 10,000-row limit.

Known limits. A CLI that answers a resize by painting only part of its screen
(Codex) leaves the rows that were on screen at that moment out of the next
viewer's replay; the rows above them are there. And xterm does two things on a
resize that the mirror does not repeat (see the module docstring of
`scrollback.py`), so a few rows next to the screen can appear twice.

Two tests hold the mirror to xterm. `tests/unit/agentic_ide/test_scrollback.py`
writes `tests/fakes/terminal_scrollback_cases.json`: for each case, the output
steps and the replay the mirror makes of them. The frontend test
`terminalScrollbackReplay.test.ts` plays each case through the real xterm
twice, once as a pane that stayed and once as a pane built from that replay,
and compares the rows. Run the backend test with `UPDATE_SCROLLBACK_CASES=1`
after a deliberate change to the mirror's output, then run the frontend test.

Right after the app starts, it attaches to the host on its own, before any
window opens a chat, so a waiting approval shows up without delay.

Only thread turns run there. A turn running as Dodaios, a goal turn and a
helper turn without tools need state inside the app and stay its children.
An installed (frozen) build starts the host by running its own executable
with `--turn-host`, since it has no `python -m`. Processes that are not the
desktop app or the web launcher, such as tests and scripts, never start or
attach to the host. Logs: `logs/turn_host.log` in the Dodaios data folder.

## Platforms

Nothing in the thread layout is OS-specific: paths are compared
case-insensitively only for Windows drive paths, the terminal drawer opens the
platform's default shell, and the git calls run the same `git` everywhere. The
layout choice, the last agent pick and the drawer's height are kept in the
browser's storage and fall back to defaults when storage is blocked. Drawer
shells are never kept: a reload does not restart them.
