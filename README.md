<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/brand/dodaios-logo-on-dark.svg" />
    <img alt="Dodaios" src="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/brand/dodaios-logo-on-light.svg" width="96" />
  </picture>
</p>

<h1 align="center">Dodaios</h1>

<!-- canonical tagline: keep in sync with GitHub description, dodaios.ai and X bio (docs/rename/repo-metadata-proposal.md) -->
<p align="center"><strong>The open-source superagent for your desktop. One agent that runs all your other agents.</strong></p>

<p align="center">
  <a href="#install">install</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/docs/product/start-here/welcome-to-dodaios.md">docs</a> ·
  <a href="https://dodaios.ai">dodaios.ai</a> ·
  <a href="https://discord.gg/x7USduHxbc">discord</a>
</p>

<p align="center">
  <a href="https://github.com/Dodaios/Dodaios/releases/latest"><img alt="Latest release" src="https://img.shields.io/github/v/release/Dodaios/Dodaios?label=release&amp;labelColor=0A0A0A&amp;color=F7F7F4" /></a>
  <a href="https://github.com/Dodaios/Dodaios/blob/main/LICENSE"><img alt="Apache 2.0" src="https://img.shields.io/badge/license-Apache_2.0-F7F7F4?labelColor=0A0A0A" /></a>
</p>

VIDEO_URL

Dodaios has two places. On one side is your agent: one conversation that
never ends. On the other side is an IDE where coding agents work for you.

- **One agent, one conversation.** Type or talk to it. Dodaios remembers you,
  keeps its own notes and skills, and runs your routines on a schedule.
- **Every coding agent at once.** Give a task to Claude Code, Codex or
  OpenCode in a thread, or run them side by side in a grid. They use the plans
  you already pay for. Each thread gets its own worktree, screenshots and pull
  request.
- **It asks before it acts.** Questions, approvals and finished work wait for
  you in one list. Nothing that can change your system runs without your yes.
- **It is yours.** No account, no paid tier, no cloud of its own. Use an API
  key, your Claude or ChatGPT plan, or a local model. Everything runs on your
  computer.

## Install

```powershell
# Windows (PowerShell)
irm https://raw.githubusercontent.com/Dodaios/Dodaios/main/install/install.ps1 | iex
```

```bash
# macOS and Linux
curl -fsSL https://raw.githubusercontent.com/Dodaios/Dodaios/main/install/install.sh | bash
```

You do not need Python, Git or a GPU. The installer opens the app. To update,
run it again. To start Dodaios later, use the desktop launcher or a terminal:

```bash
dodaios         # full desktop
```

To code with Dodaios, install and log in to a coding agent first, for example
`claude`, `codex` or `opencode`.

<details>
<summary>Desktop installers and servers</summary>

- [Windows (x64)](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-Setup-x64.exe)
- [macOS (Apple Silicon)](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-macOS-arm64.dmg)
- [macOS (Intel)](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-macOS-x64.dmg)
- [Linux (AppImage, x86_64)](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-Linux-x86_64.AppImage)

The macOS disk image is not notarized yet. On first launch, open **System
Settings > Privacy & Security** and click **Open Anyway**. Windows installers
are signed under our [code signing policy](https://github.com/Dodaios/Dodaios/blob/main/docs/code-signing-policy.md)
once the SignPath Foundation program approves the project. Free code signing
provided by SignPath.io, certificate by SignPath Foundation.

On a server without a screen, run `pip install dodaios` and `dodaios serve`,
then open `http://localhost:47821`. See the
[headless guide](https://github.com/Dodaios/Dodaios/blob/main/docs/headless-vps-deployment.md).

</details>

## Docs

[First run](https://github.com/Dodaios/Dodaios/blob/main/docs/product/start-here/first-run-setup.md) ·
[Agentic IDE](https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/agentic-ide.md) ·
[Voice](https://github.com/Dodaios/Dodaios/blob/main/docs/product/everyday-use/voice-conversations.md) ·
[Providers](https://github.com/Dodaios/Dodaios/blob/main/docs/product/personalize-and-connect/providers-and-api-keys.md) ·
[Safety](https://github.com/Dodaios/Dodaios/blob/main/docs/product/privacy-safety-and-support/safety-and-approvals.md) ·
[Privacy](https://github.com/Dodaios/Dodaios/blob/main/docs/product/privacy-safety-and-support/privacy-and-local-data.md) ·
[Troubleshooting](https://github.com/Dodaios/Dodaios/blob/main/docs/product/privacy-safety-and-support/troubleshooting.md)

## License

[Apache 2.0](https://github.com/Dodaios/Dodaios/blob/main/LICENSE). Releases up to and including 1.6.0 keep their original MIT license. See [NOTICE](https://github.com/Dodaios/Dodaios/blob/main/NOTICE) and the [trademark guidance](https://github.com/Dodaios/Dodaios/blob/main/TRADEMARK.md).
