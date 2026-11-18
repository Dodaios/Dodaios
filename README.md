<div align="center">

<a href="https://dodaios.ai">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/brand/dodaios-logo-on-dark.svg" />
    <img src="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/brand/dodaios-logo-on-light.svg" alt="Dodaios" width="112" />
  </picture>
</a>

<h1>Dodaios</h1>

<!-- the promise and the definition: word for word everywhere (docs/positioning.md) -->
<p><b>One voice-driven assistant that directs your models, your coding agents and your computer.</b></p>

<p>
  <a href="https://github.com/Dodaios/Dodaios/releases/latest"><img src="https://img.shields.io/github/v/release/Dodaios/Dodaios?label=release&amp;labelColor=0A0A0A&amp;color=FAFAFA" alt="Latest release" /></a>
  <a href="https://github.com/Dodaios/Dodaios/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache_2.0-FAFAFA?labelColor=0A0A0A" alt="License: Apache 2.0" /></a>
  <a href="https://github.com/Dodaios/Dodaios/stargazers"><img src="https://img.shields.io/github/stars/Dodaios/Dodaios?labelColor=0A0A0A&amp;color=FAFAFA&amp;logo=github" alt="GitHub stars" /></a>
  <a href="https://discord.gg/x7USduHxbc"><img src="https://img.shields.io/badge/discord-join-FAFAFA?labelColor=0A0A0A&amp;logo=discord&amp;logoColor=white" alt="Discord" /></a>
</p>

<p>
  <a href="https://trendshift.io/repositories/91076?utm_source=repository-badge&amp;utm_medium=badge&amp;utm_campaign=badge-repository-91076" target="_blank" rel="noopener noreferrer"><img src="https://trendshift.io/api/badge/repositories/91076" alt="Dodaios%2FDodaios | Trendshift" width="250" height="55"/></a>
</p>

<p>
  <a href="#install">Install</a> ·
  <a href="#your-plans-and-keys">Your plans</a> ·
  <a href="#documentation">Documentation</a> ·
  <a href="https://dodaios.ai">Website</a> ·
  <a href="https://discord.gg/x7USduHxbc">Discord</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.zh-CN.md">简体中文</a>
</p>

</div>

Dodaios is a locally installed, open-source Python program that runs as a
desktop app or as a headless server with a browser UI on Windows, macOS and
Linux. It turns a personal AI assistant into the control center for the work
you do on your computer.

At its core is a "lead" assistant you can talk to by voice (wake word,
dictation, real-time spoken conversation and, as an early preview, phone
calls), by chat or from a paired phone. It isn't tied to one provider and
works with Claude, OpenAI, Gemini or local Ollama models. It handles tasks
itself through tools, computer use, plugins, CLIs and MCP servers. Above all,
it hands work off to coding agents. They run side by side in a built-in
Agentic IDE as real Claude Code or Codex terminals, on your computer or on
your own servers over SSH, each with a call sign you can address by name, plus
Git integration and task splitting. There is also a "society" of persistent,
named agents that message each other.

Long-running work is covered by memory (about you, the people around you and
the assistant's own persona), standing tasks, workflows, skills and opt-in
life admin. The assistant also makes its own outputs, such as documents,
slides, sheets and dashboards, and can propose and build the skills, routines
and agents it is missing. A trust layer sets hard limits: outside Bypass
permissions, moving money, handling credentials, permanent deletion and first
contact with someone new always need your confirmation. In short, Dodaios is
a voice-driven, locally running operating system for AI agents that makes one
assistant the conductor of your models, your coding agents and your own
computer.

https://github.com/user-attachments/assets/37cdc5a5-30d6-49c8-92ff-3454a075569f

<p align="center">
  <sub>A real recording at 60 frames a second, played at the speed it was filmed; the waits for the models are cut out. It was recorded with Claude Fable 5.2 and Claude Opus 5.5 through Claude Code. The code change, test runs and commit are real. <a href="https://github.com/Dodaios/Dodaios/blob/main/assets/demo/readme/dodaios-demo.mp4"><b>Watch the video</b></a> (MP4, 42 s, 2.5 MB)</sub>
</p>

## Install

macOS and Linux:

```bash
curl -fsSL https://raw.githubusercontent.com/Dodaios/Dodaios/main/install/install.sh | bash
```

Windows, in PowerShell:

```powershell
irm https://raw.githubusercontent.com/Dodaios/Dodaios/main/install/install.ps1 | iex
```

The installer sets up its own Python environment, adds a launcher and opens
the app. On the first start you give the assistant a name (it is also the
wake word), connect one model and choose how you want to talk to it. For
coding work, install at least one coding agent, such as Claude Code or Codex,
and sign in to it.

```bash
dodaios            # start the desktop app
dodaios update     # install the newest release
```

<details>
<summary>Desktop installers, pipx and servers</summary>

<br />

Download the installer for your system from the latest release:

| Windows | macOS | Linux |
| --- | --- | --- |
| [Dodaios-Setup-x64.exe](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-Setup-x64.exe) | [Apple Silicon](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-macOS-arm64.dmg) · [Intel](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-macOS-x64.dmg) | [AppImage, x86_64](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-Linux-x86_64.AppImage) |

Each release lists the checksums in `installers-SHA256SUMS.txt`. The
installers are not signed yet: Windows shows a warning, and macOS asks you to
allow the app once in System Settings, under Privacy & Security. The
[code signing policy](https://github.com/Dodaios/Dodaios/blob/main/docs/code-signing-policy.md)
says where that stands.

With pipx you get the smaller server package, without a desktop launcher. On a
Linux server without a screen, the installer takes `--headless`, and
`dodaios serve` starts only the browser interface:

```bash
pipx install dodaios
curl -fsSL https://raw.githubusercontent.com/Dodaios/Dodaios/main/install/install.sh | bash -s -- --headless
dodaios serve      # browser interface only, for a server without a screen
```

Dodaios runs on 64-bit Windows, macOS and glibc-based Linux. The terminal
installer works on x86-64 and Arm64 and needs Python 3.11 to 3.14 and Git; it
fetches a missing Python and offers to install a missing Git. A graphics card
is optional. So far only Windows 11 has a recorded live sign-off.
[Install guide](https://github.com/Dodaios/Dodaios/blob/main/docs/product/start-here/install-dodaios.md) ·
[Platform support](https://github.com/Dodaios/Dodaios/blob/main/docs/product/reference/platform-support.md) ·
[Running it on a server](https://github.com/Dodaios/Dodaios/blob/main/docs/headless-vps-deployment.md)

</details>

## Your plans and keys

Dodaios costs nothing: no Dodaios account, no paid tier. It sells no model
access and never signs in for you. It starts each coding agent's official
command-line tool, and you sign in to each one yourself, so the agents run on
the plans and keys you already have. Claude Code, for example, needs a paid
Claude plan. Your use of each service follows that service's own terms.
[Providers and API keys](https://github.com/Dodaios/Dodaios/blob/main/docs/product/personalize-and-connect/providers-and-api-keys.md)

## Good to know

- **Your data.** Chats, memory, documents and settings are files on the
  computer that runs Dodaios. A model or a connected service gets what it
  needs for its part of a request. Signing in to the Google, Slack or Figma
  plugin goes through a small token service that the project runs.
  [Privacy and local data](https://github.com/Dodaios/Dodaios/blob/main/docs/product/privacy-safety-and-support/privacy-and-local-data.md)
- **Asking first.** A new chat starts at Bypass permissions, where nothing
  asks. Pick an asking mode and the four hard limits above always wait for
  your yes.
  [Safety and approvals](https://github.com/Dodaios/Dodaios/blob/main/docs/product/privacy-safety-and-support/safety-and-approvals.md)
- **Not finished.** Phone calls need your own Twilio number and are an early
  preview. Most plugins still carry a Preview badge. The phone app is a web
  app that your computer serves.

## Documentation

The [feature tour](https://github.com/Dodaios/Dodaios/blob/main/docs/feature-tour.md)
shows every part on one page, with pictures. The same guides are in the app
under **Docs**, with search.
[First-run setup](https://github.com/Dodaios/Dodaios/blob/main/docs/product/start-here/first-run-setup.md) ·
[Troubleshooting](https://github.com/Dodaios/Dodaios/blob/main/docs/product/privacy-safety-and-support/troubleshooting.md) ·
[Architecture](https://github.com/Dodaios/Dodaios/blob/main/docs/architecture-overview.md)

## Contributing

Fixes, tests, platform reports and documentation are welcome. The
[contributing guide](https://github.com/Dodaios/Dodaios/blob/main/CONTRIBUTING.md#your-first-contribution-in-10-minutes)
gets you from a fork to a passing check in about ten minutes. Questions and
ideas go to [Discord](https://discord.gg/x7USduHxbc).

Thanks to everyone who has shipped something here:

<!-- contributors:start -->

<a href="https://github.com/rubenluetke"><img src="https://avatars.githubusercontent.com/u/226271791?v=4&s=96" width="48" height="48" alt="rubenluetke" title="rubenluetke"></a> <a href="https://github.com/dannyward630"><img src="https://avatars.githubusercontent.com/u/71604164?v=4&s=96" width="48" height="48" alt="dannyward630" title="dannyward630"></a> <a href="https://github.com/dennisheidederamirez-coder"><img src="https://avatars.githubusercontent.com/u/338621144?v=4&s=96" width="48" height="48" alt="dennisheidederamirez-coder" title="dennisheidederamirez-coder"></a> <a href="https://github.com/ANO3457"><img src="https://avatars.githubusercontent.com/u/187025195?v=4&s=96" width="48" height="48" alt="ANO3457" title="ANO3457"></a> <a href="https://github.com/PilarJ"><img src="https://avatars.githubusercontent.com/u/2921746?v=4&s=96" width="48" height="48" alt="PilarJ" title="PilarJ"></a> <a href="https://github.com/Idee-Wird-App"><img src="https://avatars.githubusercontent.com/u/330157118?v=4&s=96" width="48" height="48" alt="Idee-Wird-App" title="Idee-Wird-App"></a> <a href="https://github.com/CodeByPeace"><img src="https://avatars.githubusercontent.com/u/228503734?v=4&s=96" width="48" height="48" alt="CodeByPeace" title="CodeByPeace"></a> <a href="https://github.com/jaydenhawkes123"><img src="https://avatars.githubusercontent.com/u/7899343?v=4&s=96" width="48" height="48" alt="jaydenhawkes123" title="jaydenhawkes123"></a> <a href="https://github.com/alibaba080290"><img src="https://avatars.githubusercontent.com/u/59247334?v=4&s=96" width="48" height="48" alt="alibaba080290" title="alibaba080290"></a> <a href="https://github.com/dovellx"><img src="https://avatars.githubusercontent.com/u/109219673?u=fdc67e8b78b3aa9cd5fb58f3c5a55c3445585c9e&v=4&s=96" width="48" height="48" alt="dovellx" title="dovellx"></a> <!-- i18n-allow -->
<a href="https://github.com/eljeffeg"><img src="https://avatars.githubusercontent.com/u/161904?u=38ce201214d8460536ec43ebb967955704d51345&v=4&s=96" width="48" height="48" alt="eljeffeg" title="eljeffeg"></a> <a href="https://github.com/martiroca06"><img src="https://avatars.githubusercontent.com/u/229811558?v=4&s=96" width="48" height="48" alt="martiroca06" title="martiroca06"></a> <a href="https://github.com/morfeus48235-glitch"><img src="https://avatars.githubusercontent.com/u/297425892?v=4&s=96" width="48" height="48" alt="morfeus48235-glitch" title="morfeus48235-glitch"></a> <a href="https://github.com/Oscar-Williams"><img src="https://avatars.githubusercontent.com/u/319719771?u=43c7bbf42a4f99b44a66bae0c1972b7ed72c44f2&v=4&s=96" width="48" height="48" alt="Oscar-Williams" title="Oscar-Williams"></a> <a href="https://github.com/Sgangalossa"><img src="https://avatars.githubusercontent.com/u/336517156?u=0a255499355232fbf86ae8f56c11ec59c43f76b9&v=4&s=96" width="48" height="48" alt="Sgangalossa" title="Sgangalossa"></a> <a href="https://github.com/tianxingjian2406"><img src="https://avatars.githubusercontent.com/u/247943876?v=4&s=96" width="48" height="48" alt="tianxingjian2406" title="tianxingjian2406"></a> <a href="https://github.com/Uddoo"><img src="https://avatars.githubusercontent.com/u/19704816?v=4&s=96" width="48" height="48" alt="Uddoo" title="Uddoo"></a> <a href="https://github.com/Virtuluso-azores"><img src="https://avatars.githubusercontent.com/u/263487091?v=4&s=96" width="48" height="48" alt="Virtuluso-azores" title="Virtuluso-azores"></a> <a href="https://github.com/xiangnuans"><img src="https://avatars.githubusercontent.com/u/24558814?v=4&s=96" width="48" height="48" alt="xiangnuans" title="xiangnuans"></a> <a href="https://github.com/YannisG23"><img src="https://avatars.githubusercontent.com/u/132681092?u=f7c0391b17c8490513e6bf5571256291527c12ff&v=4&s=96" width="48" height="48" alt="YannisG23" title="YannisG23"></a> <!-- i18n-allow -->

<!-- contributors:end -->

## License

[Apache License 2.0](https://github.com/Dodaios/Dodaios/blob/main/LICENSE),
with the attribution in
[NOTICE](https://github.com/Dodaios/Dodaios/blob/main/NOTICE). The name and
the logo are covered by the
[trademark policy](https://github.com/Dodaios/Dodaios/blob/main/TRADEMARK.md).
Dodaios is an independent project: the products it works with belong to their
makers, and supporting a tool does not mean its maker approves of Dodaios.
Until October 2026 it was called Personal Jarvis
([why the name changed](https://dodaios.ai/blog/personal-jarvis-is-now-dodaios/)).
Sponsors are in [SPONSORS.md](https://github.com/Dodaios/Dodaios/blob/main/SPONSORS.md).
