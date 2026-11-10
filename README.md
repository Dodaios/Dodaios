# Dodaios

**English** · [简体中文](https://github.com/Dodaios/Dodaios/blob/main/README.zh-CN.md)

<!-- canonical tagline: keep in sync with GitHub description, dodaios.ai and X bio (docs/rename/repo-metadata-proposal.md) -->
**Dodaios is an open-source agent OS for your desktop: it runs your coding agents, browser and apps by voice or chat, on your own machine.**

Dodaios is one room for every AI agent you use: your coding agents, your
everyday assistants and the agents you build in Dodaios. You start, watch and
steer them from one app on your own computer. You also approve what they do.

The old name of Dodaios is Personal Jarvis. The project and the license did not
change ([why the new name](https://dodaios.ai/blog/personal-jarvis-is-now-dodaios/)).

## What does it cost?

Nothing. Dodaios has no account, no paid tier and no cloud of its own between
you and your models. Use what you already have: an API key, your Claude or
ChatGPT plan, or a local model. The code is under the Apache 2.0 license.

## Install

> [!NOTE]
> Dodaios uses the coding agents that are on your computer. To code with
> Dodaios, first install one of them and log in, for example `claude`, `codex`
> or `opencode`. For chat and voice, one API key or a local model is enough.

Windows (PowerShell):

```powershell
irm https://raw.githubusercontent.com/Dodaios/Dodaios/main/install/install.ps1 | iex
```

macOS and Linux:

```bash
curl -fsSL https://raw.githubusercontent.com/Dodaios/Dodaios/main/install/install.sh | bash
```

You do not need Python, Git or a GPU. If Python or Git is missing, the
installer downloads a private copy for Dodaios. It does not need administrator
rights. To update, run the installer again. At the end, the app opens and asks
for your language, your wake phrase and your model.

To start Dodaios later, use the desktop launcher or type this in a terminal:

```bash
dodaios
```

### Desktop installers

- [Windows (x64)](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-Setup-x64.exe)
- [macOS (Apple Silicon)](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-macOS-arm64.dmg)
- [macOS (Intel)](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-macOS-x64.dmg)
- [Linux (AppImage, x86_64)](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-Linux-x86_64.AppImage)

The macOS disk image is not notarized yet. On first launch, open **System
Settings > Privacy & Security** and click **Open Anyway**. Windows installers
are signed under our [code signing policy](https://github.com/Dodaios/Dodaios/blob/main/docs/code-signing-policy.md)
once the SignPath Foundation program approves the project. Free code signing
provided by SignPath.io, certificate by SignPath Foundation.

### On a server

```bash
pip install dodaios
dodaios serve
```

Then open `http://localhost:47821` in a browser. The
[headless deployment guide](https://github.com/Dodaios/Dodaios/blob/main/docs/headless-vps-deployment.md)
covers HTTPS for remote microphones. Intel Macs and Windows ARM64 need the
[native package index](https://github.com/Dodaios/Dodaios/blob/main/docs/product/start-here/install-dodaios.md#install-the-isolated-pypi-package).

## What is in the room

### Coding agents

Open a project and split the screen into panes. Each pane runs one of your
coding agents on your own plan. A pane is a real terminal, and you can type
into it.

Each pane has a call sign, for example T1 or T2. You can say "T1, run the
tests" or "T2, fix the errors that T1 finds". Diffs, an editor, Git and pull
requests are next to the panes. You read every change before it goes in.
[Agentic IDE](https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/agentic-ide.md)

### Everyday agents

Talk or type to Dodaios. It uses your browser, your apps and more than 40
integrations to do the task. If the task is code, Dodaios writes a full brief
and gives it to a coding agent. The work continues after you hang up.

### Dodaios agents

Make your own specialist agents with one click, for example a researcher, a
release manager or a writer. Each agent has one conversation that never ends.
It learns from its own work and runs routines on a schedule. You see every
tool call it makes. Agents can also run on Hermes and OpenClaw.
[Agents guide](https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/dodaios-agents.md)

### Approvals

Dodaios gives each action a risk level: safe, monitor, ask or block. An action
that can change your system waits for your approval. Dodaios keeps a record of
every run.
[Safety and approvals](https://github.com/Dodaios/Dodaios/blob/main/docs/product/privacy-safety-and-support/safety-and-approvals.md)

### More in the app

- **Voice.** Your own wake phrase, live conversations, dictation and phone calls. Speech recognition can run offline. [Voice](https://github.com/Dodaios/Dodaios/blob/main/docs/product/everyday-use/voice-conversations.md)
- **Memory.** A local wiki your agents read, write and cite. [Memory](https://github.com/Dodaios/Dodaios/blob/main/docs/product/knowledge-and-sharing/wiki-and-memory.md)
- **Artifacts.** One wall with every page, report and dashboard that your agents make.
- **Plugins, MCP and skills.** One-click integrations, any MCP server, command-line tools and reusable skills. [Plugins](https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/plugins.md)
- **Computer use.** Agents can use your desktop and your browser. [Computer use](https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/computer-use.md)
- **Verse.** A ship that you can walk through, with your agents on board. [Verse](https://github.com/Dodaios/Dodaios/blob/main/docs/verse/README.md)
- **Marketplace.** Agents, skills and plugins from the community. [Marketplace](https://github.com/Dodaios/Dodaios/blob/main/docs/marketplace/community-registry.md)

## What it works with

Coding agents: Claude Code, Codex, OpenCode, Kimi Code, GLM, Grok Build,
Antigravity, Cursor CLI and DeepSeek Harness.

Models: OpenAI, Claude, Gemini, OpenRouter, NVIDIA, Ollama and any
OpenAI-compatible server.

Systems: Windows, macOS, Linux, and servers without a screen.

## Some notes

Dodaios changes fast, so expect some bugs. If something breaks, please
[open an issue](https://github.com/Dodaios/Dodaios/issues). Dodaios runs on
your computer, and your data stays there
([privacy](https://github.com/Dodaios/Dodaios/blob/main/docs/product/privacy-safety-and-support/privacy-and-local-data.md)).

## Docs

- [First run](https://github.com/Dodaios/Dodaios/blob/main/docs/product/start-here/first-run-setup.md)
- [App tour](https://github.com/Dodaios/Dodaios/blob/main/docs/product/start-here/desktop-app-tour.md)
- [Voice](https://github.com/Dodaios/Dodaios/blob/main/docs/product/everyday-use/voice-conversations.md) and [dictation](https://github.com/Dodaios/Dodaios/blob/main/docs/product/everyday-use/dictation.md)
- [Agentic IDE](https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/agentic-ide.md)
- [Agents](https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/dodaios-agents.md) and [routines](https://github.com/Dodaios/Dodaios/blob/main/docs/routines.md)
- [MCP](https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/mcp-connections.md)
- [Command line](https://github.com/Dodaios/Dodaios/blob/main/docs/dodaios-cli.md)
- [Providers and API keys](https://github.com/Dodaios/Dodaios/blob/main/docs/product/personalize-and-connect/providers-and-api-keys.md) and [local models](https://github.com/Dodaios/Dodaios/blob/main/docs/product/personalize-and-connect/local-ai-providers.md)
- [Architecture](https://github.com/Dodaios/Dodaios/blob/main/docs/architecture-overview.md)
- [Troubleshooting](https://github.com/Dodaios/Dodaios/blob/main/docs/product/privacy-safety-and-support/troubleshooting.md)

## Contribute

Start with a [good first issue](https://github.com/Dodaios/Dodaios/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22).
If none are open, pick an issue labeled
[`help wanted`](https://github.com/Dodaios/Dodaios/issues?q=is%3Aissue+is%3Aopen+label%3A%22help+wanted%22),
or ask in [Discussions](https://github.com/Dodaios/Dodaios/discussions).
[Your first contribution in 10 minutes](https://github.com/Dodaios/Dodaios/blob/main/CONTRIBUTING.md#your-first-contribution-in-10-minutes)
walks you through it. Security reports follow
[SECURITY.md](https://github.com/Dodaios/Dodaios/blob/main/SECURITY.md).
Chat with us on [Discord](https://discord.gg/x7USduHxbc).

A star on GitHub helps other people find Dodaios. Sponsors are listed in
[SPONSORS.md](https://github.com/Dodaios/Dodaios/blob/main/SPONSORS.md).

### Contributors

Thanks to everyone who has shipped something here.

<!-- contributors:start -->

<table>
<tr><td align="center"><a href="https://github.com/rubenluetke10-beep"><img src="https://avatars.githubusercontent.com/u/226271791?v=4&s=64" width="64" height="64" alt="rubenluetke10-beep"><br><sub><b>rubenluetke10-beep</b></sub></a></td><td align="center"><a href="https://github.com/dannyward630"><img src="https://avatars.githubusercontent.com/u/71604164?v=4&s=64" width="64" height="64" alt="dannyward630"><br><sub><b>dannyward630</b></sub></a></td><td align="center"><a href="https://github.com/dennisheidederamirez-coder"><img src="https://avatars.githubusercontent.com/u/338621144?v=4&s=64" width="64" height="64" alt="dennisheidederamirez-coder"><br><sub><b>dennisheidederamirez-coder</b></sub></a></td><td align="center"><a href="https://github.com/ANO3457"><img src="https://avatars.githubusercontent.com/u/187025195?v=4&s=64" width="64" height="64" alt="ANO3457"><br><sub><b>ANO3457</b></sub></a></td><td align="center"><a href="https://github.com/PilarJ"><img src="https://avatars.githubusercontent.com/u/2921746?v=4&s=64" width="64" height="64" alt="PilarJ"><br><sub><b>PilarJ</b></sub></a></td><td align="center"><a href="https://github.com/CodeByPeace"><img src="https://avatars.githubusercontent.com/u/228503734?v=4&s=64" width="64" height="64" alt="CodeByPeace"><br><sub><b>CodeByPeace</b></sub></a></td><td align="center"><a href="https://github.com/Idee-Wird-App"><img src="https://avatars.githubusercontent.com/u/330157118?v=4&s=64" width="64" height="64" alt="Idee-Wird-App"><br><sub><b>Idee-Wird-App</b></sub></a></td></tr> <!-- i18n-allow -->
<tr><td align="center"><a href="https://github.com/jaydenhawkes123"><img src="https://avatars.githubusercontent.com/u/7899343?v=4&s=64" width="64" height="64" alt="jaydenhawkes123"><br><sub><b>jaydenhawkes123</b></sub></a></td><td align="center"><a href="https://github.com/alibaba080290"><img src="https://avatars.githubusercontent.com/u/59247334?v=4&s=64" width="64" height="64" alt="alibaba080290"><br><sub><b>alibaba080290</b></sub></a></td><td align="center"><a href="https://github.com/tianxingjian2406"><img src="https://avatars.githubusercontent.com/u/247943876?v=4&s=64" width="64" height="64" alt="tianxingjian2406"><br><sub><b>tianxingjian2406</b></sub></a></td><td align="center"><a href="https://github.com/Uddoo"><img src="https://avatars.githubusercontent.com/u/19704816?v=4&s=64" width="64" height="64" alt="Uddoo"><br><sub><b>Uddoo</b></sub></a></td></tr> <!-- i18n-allow -->
</table>

<!-- contributors:end -->

## License

[Apache 2.0](https://github.com/Dodaios/Dodaios/blob/main/LICENSE). Releases up to and including 1.6.0 keep their original MIT license. See [NOTICE](https://github.com/Dodaios/Dodaios/blob/main/NOTICE) and the [trademark guidance](https://github.com/Dodaios/Dodaios/blob/main/TRADEMARK.md).
