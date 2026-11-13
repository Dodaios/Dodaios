<div align="center">

<a href="https://dodaios.ai">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/brand/dodaios-logo-on-dark.svg" />
    <img src="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/brand/dodaios-logo-on-light.svg" alt="Dodaios" width="112" />
  </picture>
</a>

<h1>Dodaios</h1>

<!-- canonical tagline: word for word everywhere (docs/rename/repo-metadata-proposal.md) -->
<p><b>The open-source superagent for your desktop. One agent that runs all your other agents.</b></p>

<p>
  Say what you want, in a message or out loud. Dodaios does the work on your computer,<br />
  briefs your coding agents and checks what they did, looks after what you hand it,<br />
  and comes back with the result, or with the one question only you can answer.
</p>

<p>
  <a href="https://github.com/Dodaios/Dodaios/releases/latest"><img src="https://img.shields.io/github/v/release/Dodaios/Dodaios?label=release&amp;labelColor=0A0A0A&amp;color=FAFAFA" alt="Latest release" /></a>
  <a href="https://github.com/Dodaios/Dodaios/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache_2.0-FAFAFA?labelColor=0A0A0A" alt="License: Apache 2.0" /></a>
  <a href="https://github.com/Dodaios/Dodaios/stargazers"><img src="https://img.shields.io/github/stars/Dodaios/Dodaios?labelColor=0A0A0A&amp;color=FAFAFA&amp;logo=github" alt="GitHub stars" /></a>
  <a href="https://discord.gg/x7USduHxbc"><img src="https://img.shields.io/badge/discord-join-FAFAFA?labelColor=0A0A0A&amp;logo=discord&amp;logoColor=white" alt="Discord" /></a>
</p>

<p>
  <a href="https://dodaios.ai">Website</a> ·
  <a href="#install">Install</a> ·
  <a href="#documentation">Documentation</a> ·
  <a href="https://discord.gg/x7USduHxbc">Discord</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.zh-CN.md">简体中文</a>
</p>

</div>

<p align="center">
  <a href="https://github.com/Dodaios/Dodaios/blob/main/assets/demo/readme/dodaios-demo.mp4">
    <img src="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/demo/readme/dodaios-demo.gif" alt="A 55-second recording of Dodaios at work, in a workspace that is already in use. Four requests are typed into its chat. Asked how much was invoiced in October, Dodaios finds the billing export on the computer and answers with a table and a chart. Asked for a page to send to finance, it writes one; the chat shows a card of the page, and the page is opened. Asked to look after a project's tests, it takes that on as a standing task. Told that one invoice is a cent too high, it checks and starts a coding agent on Claude Fable 5.2; the agent's thread is opened in the Agentic IDE while the agent works, and its changes are reviewed as a diff. Back in the chat, Dodaios has checked the result itself and reports" width="100%" />
  </a>
</p>

<p align="center">
  <sub>A recording of the real app with Claude Fable 5.2 through a signed-in Claude Code: every answer and every change is real. The typing plays faster and the waits for the model are cut out. <a href="https://github.com/Dodaios/Dodaios/blob/main/assets/demo/readme/dodaios-demo.mp4"><b>Watch it with sound</b></a> (55 s). Music: <a href="https://archive.org/details/leerosevere_musicforpodcasts_6">“Making It Look Easy”</a> by Lee Rosevere, <a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>.</sub>
</p>

## A chatbot answers. An agent acts. A superagent runs your agents.

Dodaios is the one you talk to, and it runs the rest:

- **Your computer.** It uses the desktop, its own browser, a terminal and the
  services you connected.
- **Your coding agents.** It briefs Claude Code, Codex, Cursor CLI and six more
  in your projects, follows their work and checks the result before it
  reports.
- **Its own agents.** Long jobs, standing tasks and routines run in the
  background and come back as a result, a node you can open, or a question for
  you.

It answers in short messages, puts each question on a card, and gets in touch
only when something needs you: in the app, by voice, or on your phone.

Three things hold everywhere:

- **Your models, your accounts.** Use a plan you already pay for through the
  provider's own command-line tool, paste an API key, or run a local model.
  Chat, voice, computer use and agents can each use a different provider.
- **You set how much it does alone.** Each chat has a permission mode. A new
  chat starts at Bypass permissions: nothing asks, and only a blocked call is
  refused. In the asking modes, moving money, passwords and keys, deleting
  something for good and a first message in your name to someone new always
  wait for your yes. A routine that runs without you may only do what can be
  taken back, unless a rule you saved allows more.
- **Your files, on your computer.** Chats, memory, nodes, settings and results
  are files on the computer that runs Dodaios. There is no Dodaios account and
  no paid tier. A model or a connected service receives what it needs for its
  part of a request.

## Install

**Desktop app.** Download the installer for your system from the latest release:

| Windows | macOS | Linux |
| --- | --- | --- |
| [Dodaios-Setup-x64.exe](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-Setup-x64.exe) | [Apple Silicon](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-macOS-arm64.dmg) · [Intel](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-macOS-x64.dmg) | [AppImage, x86_64](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-Linux-x86_64.AppImage) |

Each release lists the checksums in `installers-SHA256SUMS.txt`. The Windows
installer is not code-signed yet; the
[code signing policy](https://github.com/Dodaios/Dodaios/blob/main/docs/code-signing-policy.md)
says where that stands.

**From a terminal.** The installer sets up its own Python environment, adds a
launcher and opens the app.

```powershell
# Windows (PowerShell)
irm https://raw.githubusercontent.com/Dodaios/Dodaios/main/install/install.ps1 | iex
```

```bash
# macOS and Linux
curl -fsSL https://raw.githubusercontent.com/Dodaios/Dodaios/main/install/install.sh | bash

# A Linux server without a screen
curl -fsSL https://raw.githubusercontent.com/Dodaios/Dodaios/main/install/install.sh | bash -s -- --headless
```

**With pipx.** The smaller server package, without a desktop launcher:

```bash
pipx install dodaios
```

**Then start it:**

```bash
dodaios            # the desktop app: window, voice and the on-screen overlay
dodaios serve      # browser interface only, for a server without a screen
dodaios update     # install the newest published release
```

The first start asks for three things: a name (it is also the wake word), one
model connection, and how you want to talk to it. Installing needs no provider.
Answers do.

It runs on 64-bit Windows, macOS and glibc-based Linux, on x86-64 and Arm64.
The terminal installer needs Python 3.11 to 3.14 and Git and fetches whichever
is missing. A graphics card is optional.
[Install guide](https://github.com/Dodaios/Dodaios/blob/main/docs/product/start-here/install-dodaios.md) ·
[Platform support](https://github.com/Dodaios/Dodaios/blob/main/docs/product/reference/platform-support.md) ·
[Running it on a server](https://github.com/Dodaios/Dodaios/blob/main/docs/headless-vps-deployment.md)

## What you get

### Coding agents, briefed and checked

<img src="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/readme/agentic-ide.png" alt="The Agentic IDE with a connected project: a thread for the coding agent, model and permission pickers, the branch, and a terminal in which the project's tests pass" width="100%" />

Ask for a change in one of your projects and Dodaios hands it to a coding
agent: Claude Code, Codex, Cursor CLI, OpenCode, Kimi Code, GLM Coding Plan,
Grok Build, Antigravity or DeepSeek Harness, the command-line tools you
install and sign in to yourself, each with the models, effort levels and
permission modes it really has. Dodaios writes the brief, opens the agent's
thread in the IDE, follows the work and checks the result before it tells you
it is done. A thread can get its own worktree on its own branch, and a team
thread puts two to eight agents on different models onto one task. Terminals,
changes, Git, files and a browser preview sit beside every thread.
[Agentic IDE](https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/agentic-ide.md) ·
[Team threads](https://github.com/Dodaios/Dodaios/blob/main/docs/agentic-ide-team-threads.md)

### Nodes: what it makes, kept current

<img src="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/demo/readme/dodaios-nodes.gif" alt="A 31-second recording of the Nodes section. It opens at the top of the section: the seven type cards Docs, Slides, Sheets, Visuals, Analytics, Whiteboard and Clips, each with a small picture of its kind, above the cards of seven nodes. The pointer passes over the type cards; Analytics narrows the list to the dashboard Shop sales, October, which opens with its revenue, orders and charts and is scrolled. Back in the library, the slide deck Q3 board update opens and goes from its title slide over two key figures to a bar chart" width="100%" />

Ask for a report, a deck, a budget or a dashboard, and Dodaios makes it as a
node: a page you can open, present and share, and that it can change again
later. There are seven types: Docs, Slides, Sheets, Visuals, Analytics,
Whiteboard and Clips. Tell it what a node should follow, and it keeps the node
current from your apps on a schedule. Pin comments anywhere on a node (type
them or dictate them) and send them together, and Dodaios revises it; or click Edit and change a text
yourself. Each node is one page that runs in a sandbox with the network off,
and the last twelve versions can be taken back.
[Nodes](https://github.com/Dodaios/Dodaios/blob/main/docs/nodes.md)

### Work that keeps going without you

Hand Dodaios something to look after, with no end date: a project's tests, an
inbox, an ads campaign, a server. It checks on it at a pace it sets itself,
keeps working notes, and writes only when something changed, something is
ready, or something needs you. A fixed job becomes a routine that runs on a
schedule, on an event or on a webhook, and a morning brief can gather your
mail, calendar, agents and deadlines. Bigger work goes to background agents
in isolated Git worktrees, and a result is reviewed before it counts as done.
All of it runs while Dodaios is running.
[Standing tasks](https://github.com/Dodaios/Dodaios/blob/main/docs/standing-tasks.md) ·
[Routines](https://github.com/Dodaios/Dodaios/blob/main/docs/routines.md) ·
[Background agents](https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/dodaios-agents.md)

### Your computer, your apps

<img src="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/readme/plugins.png" alt="The plugin catalog: GitHub, Vercel, Notion, Slack, Linear, Google Calendar, Gmail, Outlook, Dropbox, Google Drive and more" width="100%" />

- **Its own browser.** When it browses, a live view sits beside the chat: you
  watch it work and can take over at any moment. It can bring over the website
  logins of a browser you already use.
- **Computer use.** It reads the screen and uses the mouse and keyboard in
  desktop apps.
- **Plugins.** 47 services ship in the catalog, among them GitHub, Slack,
  Notion, Linear, Gmail, Google Calendar, Home Assistant and Spotify.
- **MCP servers and skills.** Add any Model Context Protocol server, or let
  another MCP client hand work to Dodaios. A skill is a written procedure the
  assistant follows; you can write one or ask for one.
- **The command line.** `dodaios` drives a running instance from a terminal, so
  a script or another coding agent can do everything the window can.

[Browser](https://github.com/Dodaios/Dodaios/blob/main/docs/browser-use.md) ·
[Computer use](https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/computer-use.md) ·
[Plugins](https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/plugins.md) ·
[MCP connections](https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/mcp-connections.md) ·
[Skills](https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/skills.md) ·
[CLI](https://github.com/Dodaios/Dodaios/blob/main/docs/dodaios-cli.md)

### Any model, yours

<img src="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/readme/connect.png" alt="The setup step Connect your AI: Claude, OpenAI, Google Gemini and xAI Grok with a subscription sign-in or an API key, and a free local model" width="100%" />

Claude, OpenAI, Google Gemini and xAI Grok connect with an API key or with a
plan you already pay for, through the provider's own command-line tool, which
signs you in. OpenRouter, LiteLLM, Google Vertex AI and NVIDIA NIM are there
as well. A local model runs through Ollama or any OpenAI-compatible server,
with no account and no key. Keys go into your system's keychain.
[Providers and API keys](https://github.com/Dodaios/Dodaios/blob/main/docs/product/personalize-and-connect/providers-and-api-keys.md) ·
[Local AI providers](https://github.com/Dodaios/Dodaios/blob/main/docs/product/personalize-and-connect/local-ai-providers.md)

### Wherever you are

Type, or say the wake word, or press your Call shortcut and talk. Voice runs
in one of two ways: a pipeline of speech recognition, the model and a voice,
each of them local or hosted, or one live model that listens and speaks.
Dictation types what you say into the app you are working in. Away from the
desk, the phone app continues the same conversation: it shows what waits for
your yes, takes voice notes and sends a push when something needs you. Your
private Telegram chat and Discord direct messages continue it too.
[Voice conversations](https://github.com/Dodaios/Dodaios/blob/main/docs/product/everyday-use/voice-conversations.md) ·
[Dictation](https://github.com/Dodaios/Dodaios/blob/main/docs/product/everyday-use/dictation.md) ·
[Phone app](https://github.com/Dodaios/Dodaios/blob/main/docs/mobile-companion.md)

### A memory you can read

Dodaios remembers short sentences about you and your work: how you like
answers, the people you mention, the projects you are on. All of it is one
file on your computer. You can read, correct, pin, export or forget every
entry. A changed fact closes the old one with a date instead of overwriting
it. Passwords and keys are never stored.
[Memory](https://github.com/Dodaios/Dodaios/blob/main/docs/product/knowledge-and-sharing/wiki-and-memory.md)

### The small things

<table>
  <tr>
    <td width="50%"><img src="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/readme/pets.png" alt="My Pets: the active pet Ember, a baby dragon, and a grid of pixel-art pets" width="100%" /></td>
    <td width="50%"><img src="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/readme/side-by-side.png" alt="Two sections side by side: the Agentic IDE with its terminal on the left, the list of command-line tools on the right" width="100%" /></td>
  </tr>
  <tr>
    <td valign="top"><b>Pets.</b> A pixel companion on your desktop that reacts while Dodaios listens, thinks and talks. Twenty are built in, and you can make your own. <a href="https://github.com/Dodaios/Dodaios/blob/main/docs/pets.md">Pets</a></td>
    <td valign="top"><b>Side by side.</b> Put up to four sections next to each other, for example a project and your command-line tools. The interface comes in English, German, Spanish, Chinese and Portuguese.</td>
  </tr>
</table>

Also in the app: tasks and reminders, a record of every run with its steps and
tool calls, and a page that shows what your usage cost.
[Tour of the app](https://github.com/Dodaios/Dodaios/blob/main/docs/product/start-here/desktop-app-tour.md)

## How a request runs

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/brand/how-a-request-runs-dark.svg" />
  <img src="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/brand/how-a-request-runs-light.svg" alt="You ask by voice or chat. Dodaios picks one of three routes: answer, act, or delegate to an agent. The action passes a risk check with the levels safe, monitor, ask you and block. Then it is done and every step is saved in the history." width="100%" />
</picture>

Every tool call a model proposes goes through one gate before it can touch
your computer or an account:

| Level | What happens |
| --- | --- |
| **Safe** | Runs without asking. |
| **Monitor** | Runs without asking and is marked for review. |
| **Ask** | Waits for a yes. No answer counts as no. |
| **Block** | Is refused. An approval cannot override it. |

How much runs without a question is set per chat, by its permission mode:

- **Bypass permissions**, where a new chat starts: nothing asks. Every call
  runs; only a block is refused, and so is an email that seems to carry a
  secret.
- **Ask before acting, Auto-accept edits, Always ask:** a consequential call
  shows a card with the app, the action and exactly what will be sent, and
  waits for Allow once, Always allow or Deny. Moving money, passwords and
  keys, deleting something for good and a first message in your name to
  someone new always ask here.

A routine or an event that runs without you may only do what can be taken
back. A send, a post, a payment or a delete without a trash waits for your
yes, unless a rule you saved covers it.

One approval covers one call, not the rest of the job. The gate is not a
sandbox and not an undo: it covers the tool calls Dodaios makes, and your
operating system's permissions still apply.
[Safety and approvals](https://github.com/Dodaios/Dodaios/blob/main/docs/product/privacy-safety-and-support/safety-and-approvals.md) ·
[Privacy and local data](https://github.com/Dodaios/Dodaios/blob/main/docs/product/privacy-safety-and-support/privacy-and-local-data.md) ·
[Security policy](https://github.com/Dodaios/Dodaios/blob/main/SECURITY.md)

## What runs where

| | Windows | macOS | Linux desktop | Linux server |
| --- | --- | --- | --- | --- |
| Chat, coding agents, nodes, tasks, memory, settings | Yes | Yes | Yes | In the browser |
| Desktop app | Yes | Yes | Yes | No |
| Voice with the computer's microphone | Yes | Needs permission | Needs PortAudio | Through the browser |
| Global shortcuts | Yes | Needs permission | X11 | No |
| Computer use | Yes | Needs permission | X11 | No |

Windows 11 is the system with recorded live checks. The macOS and Linux
desktop paths are built and covered by tests, and their live sign-off is still
open. A feature that cannot run on your system says so and leaves the rest
working.
[Platform support](https://github.com/Dodaios/Dodaios/blob/main/docs/product/reference/platform-support.md)

## Documentation

- [Welcome to Dodaios](https://github.com/Dodaios/Dodaios/blob/main/docs/product/start-here/welcome-to-dodaios.md): what it does and what it does not do
- [First-run setup](https://github.com/Dodaios/Dodaios/blob/main/docs/product/start-here/first-run-setup.md) and [your first chat](https://github.com/Dodaios/Dodaios/blob/main/docs/product/start-here/start-your-first-chat.md)
- [Troubleshooting](https://github.com/Dodaios/Dodaios/blob/main/docs/product/privacy-safety-and-support/troubleshooting.md)
- [Configuration reference](https://github.com/Dodaios/Dodaios/blob/main/docs/product/reference/configuration-reference.md) and [CLI reference](https://github.com/Dodaios/Dodaios/blob/main/docs/dodaios-cli-reference.md)
- [Architecture overview](https://github.com/Dodaios/Dodaios/blob/main/docs/architecture-overview.md), for people who want to change the code

The same guides are inside the app under **Docs**, with search.

## Contributing

Fixes, tests, accessibility work, platform reports and documentation are
welcome. The
[contributing guide](https://github.com/Dodaios/Dodaios/blob/main/CONTRIBUTING.md#your-first-contribution-in-10-minutes)
gets you from a fork to a passing check in about ten minutes. Good places to
start are the issues labelled
[good first issue](https://github.com/Dodaios/Dodaios/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22)
and
[help wanted](https://github.com/Dodaios/Dodaios/issues?q=is%3Aissue+is%3Aopen+label%3A%22help+wanted%22).
Questions and ideas go to [Discord](https://discord.gg/x7USduHxbc).

Thanks to everyone who has shipped something here:

<!-- contributors:start -->

<table>
<tr><td align="center"><a href="https://github.com/rubenluetke"><img src="https://avatars.githubusercontent.com/u/226271791?v=4&s=64" width="64" height="64" alt="rubenluetke"><br><sub><b>rubenluetke</b></sub></a></td><td align="center"><a href="https://github.com/dannyward630"><img src="https://avatars.githubusercontent.com/u/71604164?v=4&s=64" width="64" height="64" alt="dannyward630"><br><sub><b>dannyward630</b></sub></a></td><td align="center"><a href="https://github.com/dennisheidederamirez-coder"><img src="https://avatars.githubusercontent.com/u/338621144?v=4&s=64" width="64" height="64" alt="dennisheidederamirez-coder"><br><sub><b>dennisheidederamirez-coder</b></sub></a></td><td align="center"><a href="https://github.com/ANO3457"><img src="https://avatars.githubusercontent.com/u/187025195?v=4&s=64" width="64" height="64" alt="ANO3457"><br><sub><b>ANO3457</b></sub></a></td><td align="center"><a href="https://github.com/PilarJ"><img src="https://avatars.githubusercontent.com/u/2921746?v=4&s=64" width="64" height="64" alt="PilarJ"><br><sub><b>PilarJ</b></sub></a></td><td align="center"><a href="https://github.com/CodeByPeace"><img src="https://avatars.githubusercontent.com/u/228503734?v=4&s=64" width="64" height="64" alt="CodeByPeace"><br><sub><b>CodeByPeace</b></sub></a></td><td align="center"><a href="https://github.com/Idee-Wird-App"><img src="https://avatars.githubusercontent.com/u/330157118?v=4&s=64" width="64" height="64" alt="Idee-Wird-App"><br><sub><b>Idee-Wird-App</b></sub></a></td></tr> <!-- i18n-allow -->
<tr><td align="center"><a href="https://github.com/jaydenhawkes123"><img src="https://avatars.githubusercontent.com/u/7899343?v=4&s=64" width="64" height="64" alt="jaydenhawkes123"><br><sub><b>jaydenhawkes123</b></sub></a></td><td align="center"><a href="https://github.com/alibaba080290"><img src="https://avatars.githubusercontent.com/u/59247334?v=4&s=64" width="64" height="64" alt="alibaba080290"><br><sub><b>alibaba080290</b></sub></a></td><td align="center"><a href="https://github.com/tianxingjian2406"><img src="https://avatars.githubusercontent.com/u/247943876?v=4&s=64" width="64" height="64" alt="tianxingjian2406"><br><sub><b>tianxingjian2406</b></sub></a></td><td align="center"><a href="https://github.com/Uddoo"><img src="https://avatars.githubusercontent.com/u/19704816?v=4&s=64" width="64" height="64" alt="Uddoo"><br><sub><b>Uddoo</b></sub></a></td></tr> <!-- i18n-allow -->
</table>

<!-- contributors:end -->

## License

Dodaios is licensed under the
[Apache License 2.0](https://github.com/Dodaios/Dodaios/blob/main/LICENSE),
with the attribution in
[NOTICE](https://github.com/Dodaios/Dodaios/blob/main/NOTICE). The name and
the logo are covered by the
[trademark policy](https://github.com/Dodaios/Dodaios/blob/main/TRADEMARK.md),
not by the license.

Dodaios is an independent project. The products it works with, such as the
coding agents above, belong to their makers; that Dodaios supports a tool does
not mean its maker supports or approves of Dodaios.

Dodaios was called Personal Jarvis until October 2026. It is the same project
under the same license
([why the name changed](https://dodaios.ai/blog/personal-jarvis-is-now-dodaios/)).

Sponsors are in [SPONSORS.md](https://github.com/Dodaios/Dodaios/blob/main/SPONSORS.md).
