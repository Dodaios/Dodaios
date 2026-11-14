<div align="center">

<a href="https://dodaios.ai">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/brand/dodaios-logo-on-dark.svg" />
    <img src="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/brand/dodaios-logo-on-light.svg" alt="Dodaios" width="112" />
  </picture>
</a>

<h1>Dodaios</h1>

<!-- the hook: word for word everywhere (docs/rename/repo-metadata-proposal.md) -->
<p><b>Say what you want. Dodaios runs Claude Code, Codex and seven more agents<br />
on your own plans, checks their work, and tells you what is done.</b></p>

<p>
  Type it or say it out loud. You get a short answer in the chat<br />
  and the full report as a page. Open source, no account.
</p>

<p>
  <a href="https://github.com/Dodaios/Dodaios/releases/latest"><img src="https://img.shields.io/github/v/release/Dodaios/Dodaios?label=release&amp;labelColor=0A0A0A&amp;color=FAFAFA" alt="Latest release" /></a>
  <a href="https://github.com/Dodaios/Dodaios/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache_2.0-FAFAFA?labelColor=0A0A0A" alt="License: Apache 2.0" /></a>
  <a href="https://github.com/Dodaios/Dodaios/stargazers"><img src="https://img.shields.io/github/stars/Dodaios/Dodaios?labelColor=0A0A0A&amp;color=FAFAFA&amp;logo=github" alt="GitHub stars" /></a>
  <a href="https://discord.gg/x7USduHxbc"><img src="https://img.shields.io/badge/discord-join-FAFAFA?labelColor=0A0A0A&amp;logo=discord&amp;logoColor=white" alt="Discord" /></a>
</p>

<p>
  <a href="#install">Install</a> ·
  <a href="#three-things-to-say-to-it">Examples</a> ·
  <a href="#how-it-works">How it works</a> ·
  <a href="#documentation">Documentation</a> ·
  <a href="https://dodaios.ai">Website</a> ·
  <a href="https://discord.gg/x7USduHxbc">Discord</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.zh-CN.md">简体中文</a>
</p>

</div>

<p align="center">
  <a href="https://github.com/Dodaios/Dodaios/blob/main/assets/demo/readme/dodaios-demo.mp4">
    <img src="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/demo/readme/dodaios-demo.gif" alt="A 30-second recording of Dodaios at work, in a workspace that is already in use. One request is typed into its chat: review the new PRs in acme-notes, one Sonnet agent per PR, and write me a report. Dodaios answers that it will list the pull requests, and the first coding agents appear beside the conversation under Recent activity. A click on one of them opens its thread in the Agentic IDE, where the project acme-notes lists a thread for each pull request, each with a spinner while its agent works. Two more threads are opened side by side, so three agents are seen at work at once: the brief Dodaios wrote, the agents reading the diffs and running the tests, and then their finished reviews. Back in the chat, Dodaios posts the card of a report and an answer of two sentences: three of the five pull requests are ready to merge, and two need changes first. The report is opened and scrolled: its summary, its key figures and a table with a verdict for each pull request" width="100%" />
  </a>
</p>

<p align="center">
  <sub>A recording of the real app, cut from a take of 2 min 18 s: the waits for the models are cut out and the rest plays a fifth faster. Dodaios runs on Claude Opus 5.5 and starts five Claude Sonnet 5.5 agents through a signed-in Claude Code. The pull requests, the reviews and the report are real. <a href="https://github.com/Dodaios/Dodaios/blob/main/assets/demo/readme/dodaios-demo.mp4"><b>Watch it as a video</b></a> (30 s, 60 frames a second, no sound).</sub>
</p>

<p align="center">
  <a href="https://github.com/Dodaios/Dodaios"><img src="https://img.shields.io/github/stars/Dodaios/Dodaios?style=for-the-badge&amp;label=Star%20Dodaios&amp;logo=github&amp;labelColor=0A0A0A&amp;color=FAFAFA" alt="Star Dodaios on GitHub" /></a>
  <br />
  <sub>If Dodaios is useful to you, star the repository. A star is how other developers find it.</sub>
</p>

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/Dodaios/Dodaios/main/install/install.sh | bash
```

That line is for macOS and Linux. On Windows, in PowerShell:

```powershell
irm https://raw.githubusercontent.com/Dodaios/Dodaios/main/install/install.ps1 | iex
```

The installer sets up its own Python environment, adds a launcher and opens
the app. The first start asks for three things: a name (it is also the wake
word), one model connection, and how you want to talk to it. To hand out
coding work, install at least one coding agent and sign in to it, for example
Claude Code or Codex.

```bash
dodaios            # the desktop app: window, voice and the on-screen overlay
dodaios update     # install the newest published release
```

<details>
<summary>Desktop installers, pipx and servers</summary>

<br />

Download the installer for your system from the latest release:

| Windows | macOS | Linux |
| --- | --- | --- |
| [Dodaios-Setup-x64.exe](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-Setup-x64.exe) | [Apple Silicon](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-macOS-arm64.dmg) · [Intel](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-macOS-x64.dmg) | [AppImage, x86_64](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-Linux-x86_64.AppImage) |

Each release lists the checksums in `installers-SHA256SUMS.txt`. The Windows
installer is not code-signed yet; the
[code signing policy](https://github.com/Dodaios/Dodaios/blob/main/docs/code-signing-policy.md)
says where that stands.

With pipx you get the smaller server package, without a desktop launcher. On a
Linux server without a screen, the installer takes `--headless`, and
`dodaios serve` starts the browser interface only:

```bash
pipx install dodaios
curl -fsSL https://raw.githubusercontent.com/Dodaios/Dodaios/main/install/install.sh | bash -s -- --headless
dodaios serve      # browser interface only, for a server without a screen
```

It runs on 64-bit Windows, macOS and glibc-based Linux, on x86-64 and Arm64.
The terminal installer needs Python 3.11 to 3.14 and Git and fetches whichever
is missing. A graphics card is optional. Installing needs no provider. Answers
do.
[Install guide](https://github.com/Dodaios/Dodaios/blob/main/docs/product/start-here/install-dodaios.md) ·
[Platform support](https://github.com/Dodaios/Dodaios/blob/main/docs/product/reference/platform-support.md) ·
[Running it on a server](https://github.com/Dodaios/Dodaios/blob/main/docs/headless-vps-deployment.md)

</details>

## Three things to say to it

**"Review the new PRs, one agent per PR, and tell me what to do."**
Dodaios looks up the open pull requests and starts a coding agent for each.
It reads their reviews and tells you which to merge and which to fix first.
The recording above is this request, with a report asked for as well.

**"Find the invoice from Kestrel in my mail, put its due date in my calendar and tell the team in Slack."**
One request, three apps. Gmail, Google Calendar and Slack are among the 47
services in the plugin catalog. In a permission mode that asks, the message
in your name waits for your yes.

**"Every weekday at 9, run the tests in ledger and tell me if one fails."**
A request with a time becomes a routine. It runs on that schedule while
Dodaios is running, and you hear from it when a test fails.

## How it works

1. **Talk.** Type a message, or say the wake word and speak. It is one
   conversation, and Dodaios remembers what you told it.
2. **Delegate.** Dodaios writes the brief and starts the work. Coding goes to
   coding agents in your project, each in its own thread of the Agentic IDE,
   side by side. Other work goes to its own background agents, its browser or
   your connected apps.
3. **Verify.** It follows the work and checks the result itself before it
   calls anything done: the diff, the tests, the page.
4. **Report.** You get a short answer in the chat, the long version as a page
   you can open, and a question only when it needs you.

You set how much it does alone. Each chat has a permission mode, from Bypass
permissions, where nothing asks, to Always ask.
[Safety and approvals](https://github.com/Dodaios/Dodaios/blob/main/docs/product/privacy-safety-and-support/safety-and-approvals.md)

## Supported coding agents

**Claude Code · Codex · Cursor CLI · OpenCode · Kimi Code · GLM Coding Plan · Grok Build · Antigravity · DeepSeek Harness**

Nine coding agents, each through its own command-line tool. You install it and
sign in yourself, so it runs on the plan you already pay for, with the models,
effort levels and permission modes it really has. A thread can get its own
worktree on its own branch, and a team thread puts two to eight agents on
different models onto one task.
[Agentic IDE](https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/agentic-ide.md) ·
[Team threads](https://github.com/Dodaios/Dodaios/blob/main/docs/agentic-ide-team-threads.md)

Dodaios itself runs on the model you choose: Claude, OpenAI, Google Gemini or
xAI Grok with an API key or a plan you already pay for, OpenRouter, LiteLLM,
Google Vertex AI or NVIDIA NIM, or a local model through Ollama with no
account and no key.
[Providers and API keys](https://github.com/Dodaios/Dodaios/blob/main/docs/product/personalize-and-connect/providers-and-api-keys.md)

## What else it does

- **Voice.** Say the wake word or press your Call shortcut and talk. Dictation types what you say into the app you are working in. [Voice](https://github.com/Dodaios/Dodaios/blob/main/docs/product/everyday-use/voice-conversations.md)
- **Memory you can read.** Short sentences about you and your work, in one file on your computer. You can correct, pin, export or forget every entry. [Memory](https://github.com/Dodaios/Dodaios/blob/main/docs/product/knowledge-and-sharing/wiki-and-memory.md)
- **Routines and standing tasks.** Work on a schedule, on an event or on a webhook, and things it keeps looking after: a project's tests, an inbox, a server. [Routines](https://github.com/Dodaios/Dodaios/blob/main/docs/routines.md) · [Standing tasks](https://github.com/Dodaios/Dodaios/blob/main/docs/standing-tasks.md)
- **47 plugins.** GitHub, Slack, Notion, Linear, Gmail, Google Calendar, Home Assistant, Spotify and more, and any MCP server. [Plugins](https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/plugins.md)
- **Nodes.** Reports, decks, sheets and dashboards that it makes and keeps current. [Nodes](https://github.com/Dodaios/Dodaios/blob/main/docs/nodes.md)
- **Its own browser and your desktop.** You watch it browse and can take over at any moment. It also uses the mouse and keyboard in desktop apps. [Browser](https://github.com/Dodaios/Dodaios/blob/main/docs/browser-use.md) · [Computer use](https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/computer-use.md)
- **Away from the desk.** The phone app, your private Telegram chat and Discord direct messages continue the same conversation. [Phone app](https://github.com/Dodaios/Dodaios/blob/main/docs/mobile-companion.md)
- **Yours.** Chats, memory, nodes and settings are files on your computer. There is no Dodaios account and no paid tier. [Privacy and local data](https://github.com/Dodaios/Dodaios/blob/main/docs/product/privacy-safety-and-support/privacy-and-local-data.md)

The [feature tour](https://github.com/Dodaios/Dodaios/blob/main/docs/feature-tour.md) has all of it, with pictures:
what each part does, how a tool call is checked before it runs, and what runs
on which system.

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

<a href="https://github.com/rubenluetke"><img src="https://avatars.githubusercontent.com/u/226271791?v=4&s=96" width="48" height="48" alt="rubenluetke" title="rubenluetke"></a> <a href="https://github.com/dannyward630"><img src="https://avatars.githubusercontent.com/u/71604164?v=4&s=96" width="48" height="48" alt="dannyward630" title="dannyward630"></a> <a href="https://github.com/dennisheidederamirez-coder"><img src="https://avatars.githubusercontent.com/u/338621144?v=4&s=96" width="48" height="48" alt="dennisheidederamirez-coder" title="dennisheidederamirez-coder"></a> <a href="https://github.com/ANO3457"><img src="https://avatars.githubusercontent.com/u/187025195?v=4&s=96" width="48" height="48" alt="ANO3457" title="ANO3457"></a> <a href="https://github.com/PilarJ"><img src="https://avatars.githubusercontent.com/u/2921746?v=4&s=96" width="48" height="48" alt="PilarJ" title="PilarJ"></a> <a href="https://github.com/Idee-Wird-App"><img src="https://avatars.githubusercontent.com/u/330157118?v=4&s=96" width="48" height="48" alt="Idee-Wird-App" title="Idee-Wird-App"></a> <a href="https://github.com/CodeByPeace"><img src="https://avatars.githubusercontent.com/u/228503734?v=4&s=96" width="48" height="48" alt="CodeByPeace" title="CodeByPeace"></a> <a href="https://github.com/jaydenhawkes123"><img src="https://avatars.githubusercontent.com/u/7899343?v=4&s=96" width="48" height="48" alt="jaydenhawkes123" title="jaydenhawkes123"></a> <a href="https://github.com/alibaba080290"><img src="https://avatars.githubusercontent.com/u/59247334?v=4&s=96" width="48" height="48" alt="alibaba080290" title="alibaba080290"></a> <a href="https://github.com/dovellx"><img src="https://avatars.githubusercontent.com/u/109219673?u=fdc67e8b78b3aa9cd5fb58f3c5a55c3445585c9e&v=4&s=96" width="48" height="48" alt="dovellx" title="dovellx"></a> <!-- i18n-allow -->
<a href="https://github.com/eljeffeg"><img src="https://avatars.githubusercontent.com/u/161904?u=38ce201214d8460536ec43ebb967955704d51345&v=4&s=96" width="48" height="48" alt="eljeffeg" title="eljeffeg"></a> <a href="https://github.com/martiroca06"><img src="https://avatars.githubusercontent.com/u/229811558?v=4&s=96" width="48" height="48" alt="martiroca06" title="martiroca06"></a> <a href="https://github.com/morfeus48235-glitch"><img src="https://avatars.githubusercontent.com/u/297425892?v=4&s=96" width="48" height="48" alt="morfeus48235-glitch" title="morfeus48235-glitch"></a> <a href="https://github.com/Oscar-Williams"><img src="https://avatars.githubusercontent.com/u/319719771?u=43c7bbf42a4f99b44a66bae0c1972b7ed72c44f2&v=4&s=96" width="48" height="48" alt="Oscar-Williams" title="Oscar-Williams"></a> <a href="https://github.com/Sgangalossa"><img src="https://avatars.githubusercontent.com/u/336517156?u=0a255499355232fbf86ae8f56c11ec59c43f76b9&v=4&s=96" width="48" height="48" alt="Sgangalossa" title="Sgangalossa"></a> <a href="https://github.com/tianxingjian2406"><img src="https://avatars.githubusercontent.com/u/247943876?v=4&s=96" width="48" height="48" alt="tianxingjian2406" title="tianxingjian2406"></a> <a href="https://github.com/Uddoo"><img src="https://avatars.githubusercontent.com/u/19704816?v=4&s=96" width="48" height="48" alt="Uddoo" title="Uddoo"></a> <a href="https://github.com/Virtuluso-azores"><img src="https://avatars.githubusercontent.com/u/263487091?v=4&s=96" width="48" height="48" alt="Virtuluso-azores" title="Virtuluso-azores"></a> <a href="https://github.com/YannisG23"><img src="https://avatars.githubusercontent.com/u/132681092?u=f7c0391b17c8490513e6bf5571256291527c12ff&v=4&s=96" width="48" height="48" alt="YannisG23" title="YannisG23"></a> <!-- i18n-allow -->

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
