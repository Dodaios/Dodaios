<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/brand/dodaios-logo-on-dark.svg" />
    <img alt="Dodaios" src="assets/brand/dodaios-logo-on-light.svg" width="112" />
  </picture>
</p>

<h1 align="center">Dodaios</h1>

<p align="center">
  <strong>English</strong> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.zh-CN.md">简体中文</a>
</p>

<p align="center">
  <strong>Dodaios is an open-source agent OS for your desktop.</strong><br />
  It is the layer between you and your AI agents: it runs them, remembers for them, connects their tools and keeps you in control.
</p>

<p align="center">
  <a href="https://pypi.org/project/personal-jarvis/"><img alt="PyPI" src="https://img.shields.io/pypi/v/personal-jarvis?labelColor=0A0A0A&amp;color=F7F7F4" /></a>
  <a href="https://github.com/Dodaios/Dodaios/blob/main/LICENSE"><img alt="Apache 2.0" src="https://img.shields.io/badge/License-Apache_2.0-F7F7F4?labelColor=0A0A0A" /></a>
  <a href="https://github.com/Dodaios/Dodaios/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/Dodaios/Dodaios/actions/workflows/ci.yml/badge.svg" /></a>
  <a href="https://discord.gg/x7USduHxbc"><img alt="Discord" src="https://img.shields.io/badge/Discord-join-F7F7F4?labelColor=0A0A0A&amp;logo=discord&amp;logoColor=white" /></a>
</p>

<p align="center">
  <a href="#install"><strong>Install</strong></a> ·
  <a href="#from-one-prompt-to-a-merged-pull-request">Workflow</a> ·
  <a href="#everything-in-one-app">Features</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/docs/product/start-here/welcome-to-dodaios.md">Docs</a> ·
  <a href="https://dodaios.ai">Website</a> ·
  <a href="https://discord.gg/x7USduHxbc">Discord</a> ·
  <a href="https://x.com/dodaios">X</a>
</p>

<p align="center"><sub>No API key needed if you have a Claude or ChatGPT subscription, or a local model. Formerly Personal Jarvis.</sub></p>

---

## Install

**Windows (PowerShell)**

```powershell
irm https://raw.githubusercontent.com/Dodaios/Dodaios/main/install/install.ps1 | iex
```

**macOS and Linux**

```bash
curl -fsSL https://raw.githubusercontent.com/Dodaios/Dodaios/main/install/install.sh | bash
```

You do not need to install anything first. If Python is missing, the
installer downloads a private copy just for Dodaios, and on Windows it does the
same for Git, without administrator rights or questions. It then adds the
desktop launcher and opens the app. If you run it again, it updates your
existing installation. You choose your language, wake
phrase and models inside the app.

You need one API key, a subscription or a local model. A microphone helps for
voice. You do not need a GPU. Desktop installers and the server setup are under
[more ways to install](#more-ways-to-install).

## From one prompt to a merged pull request

1. **Plan with the lead agent.** Say what you want, by voice or in chat. The lead agent asks what it needs and hands the work to the right agent or pane.
2. **Build in parallel.** Claude Code, Codex, OpenCode and six more coding agents run side by side in live panes, each on its own branch in its own git worktree if you want.
3. **Review every change.** Diffs, source control and an editor sit next to the panes, so you read each line before it lands.
4. **Ship from the Git panel.** Branches, pull requests, CI checks and merges, without switching to the browser.
5. **Hand off the rest.** Assistant agents, built in or running on Hermes and OpenClaw, write the release notes, draft the launch posts and keep their routines going.
6. **Remember it all.** A local memory wiki keeps the context of every chat, agent and project for next time.

## Everything in one app

<table>
  <tr>
    <td width="33%"><strong>Agentic IDE</strong><br />Every coding agent in live terminal panes, side by side.</td>
    <td width="33%"><strong>Git and pull requests</strong><br />Diffs, branches, PRs and CI checks built in.</td>
    <td width="33%"><strong>Lead agent</strong><br />One assistant that plans, delegates and reports back.</td>
  </tr>
  <tr>
    <td><strong>Agent team</strong><br />Specialists with their own chat, tools, schedule and memory.</td>
    <td><strong>Hermes and OpenClaw</strong><br />Run agents on the open agent runtimes you already use.</td>
    <td><strong>Voice</strong><br />Wake word, live conversations, dictation and phone calls.</td>
  </tr>
  <tr>
    <td><strong>Computer use</strong><br />Clicks, types and reads your desktop and browser.</td>
    <td><strong>Memory</strong><br />A local wiki your agents read, write and cite.</td>
    <td><strong>Plugins, MCP and skills</strong><br />More than 40 one-click integrations, or bring your own.</td>
  </tr>
  <tr>
    <td><strong>Any model</strong><br />Hosted, local, or your Claude and ChatGPT subscriptions.</td>
    <td><strong>Routines</strong><br />Agents do recurring work on a schedule, without being asked.</td>
    <td><strong>Artifacts</strong><br />Every report, page and file your agents make, in one place.</td>
  </tr>
</table>

It is free and open source, and it runs on your own machine: Windows, macOS,
Linux, or a server without a screen. You do not need an account, and there is
no cloud of ours between you and your models. Every action that could change
your system waits for your approval.

## Run every coding agent at once

https://github.com/user-attachments/assets/290a8687-f925-4bb1-ac4c-0f23ea948a07

<p align="center"><sub>A real recording of the Agentic IDE: three agents at work, your own Chrome in the side panel, files, Git diff and a second workspace.</sub></p>

The Agentic IDE turns one screen into a room full of coding agents. You open a
project, split the screen into panes, and give each pane its own coding agent.
Every pane gets a short call sign such as T1 or T2, so you can steer them
without touching the keyboard. You might say "Tell T1 to write the tests",
"What is T2 working on?" or "Send the fix plan to all panes".

- Dodaios finds the coding tools you already have installed and starts any of
  them in a pane with one key. You keep using the subscriptions you pay for.
- You can send the same task to several panes and compare what comes back.
- You can talk to Dodaios while the agents type, and it passes your brief to the
  right pane by its call sign.
- Every pane is a real terminal, so you can type into it yourself at any time.

The [Agentic IDE guide](https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/agentic-ide.md) has the details.

## A team of agents that keeps working

Dodaios Agents are specialists you create with one click and keep for as long as
you like: a researcher, a release manager, a marketing writer, or whatever your
work needs.

- Each agent has one chat that never ends, so tomorrow you continue where you
  stopped today.
- Agents keep private notes on what they learned from their own work, and they
  get better at your tasks over time.
- Give an agent a routine and it does the work on schedule, without being asked.
- Files, reports and plans they produce land in Artifacts, and you can see every
  tool they used along the way.
- Longer coding missions run in their own copy of your repository (a git
  worktree), can split into parallel workers, and pass a review before you see
  the result.

Read more in the [Agents guide](https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/dodaios-agents.md),
[how agents learn](https://github.com/Dodaios/Dodaios/blob/main/docs/agent-society/self-learning.md)
and [routines](https://github.com/Dodaios/Dodaios/blob/main/docs/routines.md).

## Talk to your computer

You pick your own wake phrase, such as "Hey Nova", "Computer" or anything else,
and then you talk.

- Conversations are live and take turns naturally. Mid-sentence you can ask it
  to open a website, check your calendar or start an agent.
- Dictation types what you say into any app and learns your words from a
  personal dictionary.
- Phone calls go through your own number. You can call Dodaios, or let it call
  someone for you once you approve.
- Speech recognition and voices can run fully offline. Hosted voices are
  optional.

Read more in the [voice guide](https://github.com/Dodaios/Dodaios/blob/main/docs/product/everyday-use/voice-conversations.md)
and the [dictation guide](https://github.com/Dodaios/Dodaios/blob/main/docs/product/everyday-use/dictation.md).

## Connect your tools

- Install plugins from the marketplace with one sign-in in your browser, or add
  any MCP server yourself.
- Dodaios finds command-line tools such as GitHub, Vercel, Supabase, Stripe,
  Docker and the cloud CLIs, and signs you in to them from the app.
- Skills are reusable instructions that Dodaios picks up when your request fits
  one.
- You can reach Dodaios from Telegram and Discord.
- The `jarvis` command and a local API give your own scripts, and other agents,
  the same control you have.

Read more about [plugins](https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/plugins.md),
[MCP](https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/mcp-connections.md),
[command-line tools](https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/cli-connections.md)
and the [Dodaios CLI](https://github.com/Dodaios/Dodaios/blob/main/docs/dodaios-cli.md).

## You stay in control

Every action Dodaios takes passes a risk check with four levels: safe, monitor,
ask and block. Anything that could change your system waits for your approval,
and every run is recorded, so you can see later exactly what happened. Your keys
are kept in your operating system's credential store. Nothing leaves your
machine unless you connect a service that needs it.

Read more about [safety and approvals](https://github.com/Dodaios/Dodaios/blob/main/docs/product/privacy-safety-and-support/safety-and-approvals.md)
and [privacy and local data](https://github.com/Dodaios/Dodaios/blob/main/docs/product/privacy-safety-and-support/privacy-and-local-data.md).

## More ways to install

The [one-line installer](#install) is the quickest way in. After it has run,
open Dodaios from the desktop launcher or from a terminal:

```bash
jarvis          # full desktop
```

If you prefer a regular desktop installer, download one here:

- [Windows](https://github.com/Dodaios/Dodaios/releases/latest/download/PersonalJarvis-Setup-x64.exe)
- [macOS on Apple Silicon](https://github.com/Dodaios/Dodaios/releases/latest/download/PersonalJarvis-macOS-arm64.dmg)
- [macOS on Intel](https://github.com/Dodaios/Dodaios/releases/latest/download/PersonalJarvis-macOS-x64.dmg)
- [Linux AppImage](https://github.com/Dodaios/Dodaios/releases/latest/download/PersonalJarvis-Linux-x86_64.AppImage)

Windows installers are signed under our
[code signing policy](https://github.com/Dodaios/Dodaios/blob/main/docs/code-signing-policy.md)
once the SignPath Foundation program approves the project. Free code signing
provided by SignPath.io, certificate by SignPath Foundation.

The macOS disk image is not notarized by Apple yet. The first time you open it
on macOS 15, go to **System Settings > Privacy & Security** and click **Open
Anyway**. Up to macOS 14, right-click the app and choose **Open**. The one-line
installer above does not need this step.

To run Dodaios on a server, use `pip install dodaios` and `dodaios serve`,
then open `http://localhost:47821` in a browser. Using a microphone from another
computer needs HTTPS. The [headless deployment guide](https://github.com/Dodaios/Dodaios/blob/main/docs/headless-vps-deployment.md)
explains the setup. If you install with pip or pipx by hand on an Intel Mac or
on Windows ARM64, you also need the
[native package index](https://github.com/Dodaios/Dodaios/blob/main/docs/product/start-here/install-dodaios.md#install-the-isolated-pypi-package).
The installer sets that up for you.

## First steps

1. Finish the short setup in the app. Pick your language, a wake phrase (or a
   keyboard shortcut instead) and one model.
2. Say your wake phrase and ask for something, for example "Plan a small project
   with me and ask what you need to know."
3. Open a project folder in the Agentic IDE, or create your first agent.

## Works with

- **Models:** OpenAI, Anthropic Claude, Google Gemini and Vertex AI, OpenRouter, NVIDIA, Ollama and any OpenAI-compatible local server, plus your Claude Code and Codex subscriptions.
- **Coding agents:** Claude Code, Codex, OpenCode, Kimi Code, GLM, Grok Build, Antigravity, Cursor CLI and DeepSeek Harness.
- **Speech:** local Whisper, OpenAI, Gemini, Groq, Deepgram and OpenRouter for listening; Piper (local), ElevenLabs, Cartesia, Inworld, Gemini and OpenRouter voices for speaking.

## Docs

- **Getting started:** [quick start](https://github.com/Dodaios/Dodaios/blob/main/docs/product/start-here/first-run-setup.md), [app tour](https://github.com/Dodaios/Dodaios/blob/main/docs/product/start-here/desktop-app-tour.md)
- **Everyday use:** [voice](https://github.com/Dodaios/Dodaios/blob/main/docs/product/everyday-use/voice-conversations.md), [dictation](https://github.com/Dodaios/Dodaios/blob/main/docs/product/everyday-use/dictation.md), [memory](https://github.com/Dodaios/Dodaios/blob/main/docs/product/knowledge-and-sharing/wiki-and-memory.md)
- **Agents and automation:** [agentic IDE](https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/agentic-ide.md), [agents](https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/dodaios-agents.md), [computer use](https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/computer-use.md), [plugins](https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/plugins.md), [MCP](https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/mcp-connections.md), [CLI](https://github.com/Dodaios/Dodaios/blob/main/docs/dodaios-cli.md)
- **Models:** [providers](https://github.com/Dodaios/Dodaios/blob/main/docs/product/personalize-and-connect/providers-and-api-keys.md), [local models](https://github.com/Dodaios/Dodaios/blob/main/docs/product/personalize-and-connect/local-ai-providers.md)
- **Running and fixing:** [server](https://github.com/Dodaios/Dodaios/blob/main/docs/headless-vps-deployment.md), [architecture](https://github.com/Dodaios/Dodaios/blob/main/docs/architecture-overview.md), [troubleshooting](https://github.com/Dodaios/Dodaios/blob/main/docs/product/privacy-safety-and-support/troubleshooting.md)

## Contribute

A good place to start is a [good first issue](https://github.com/Dodaios/Dodaios/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22) and the guide to [your first contribution in 10 minutes](https://github.com/Dodaios/Dodaios/blob/main/CONTRIBUTING.md#your-first-contribution-in-10-minutes). Questions and ideas go to [discussions](https://github.com/Dodaios/Dodaios/discussions), and security reports follow [SECURITY.md](https://github.com/Dodaios/Dodaios/blob/main/SECURITY.md).

If Dodaios is useful to you, a star on GitHub helps other people find it. Sponsors are listed in [SPONSORS.md](https://github.com/Dodaios/Dodaios/blob/main/SPONSORS.md).

<!-- contributors:start -->

<a href="https://github.com/rubenluetke10-beep"><img src="https://avatars.githubusercontent.com/u/226271791?v=4&s=48" width="48" height="48" alt="rubenluetke10-beep"></a>

<!-- contributors:end -->

## License

[Apache 2.0](https://github.com/Dodaios/Dodaios/blob/main/LICENSE). Releases up to and including 1.6.0 keep their original MIT license. See [NOTICE](https://github.com/Dodaios/Dodaios/blob/main/NOTICE) and the [trademark guidance](https://github.com/Dodaios/Dodaios/blob/main/TRADEMARK.md).
