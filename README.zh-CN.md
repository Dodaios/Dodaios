<div align="center">

<a href="https://dodaios.ai">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/brand/dodaios-logo-on-dark.svg" />
    <img src="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/brand/dodaios-logo-on-light.svg" alt="Dodaios" width="112" />
  </picture>
</a>

<h1>Dodaios</h1>

<!-- the promise and the definition, translated (English word for word in README.md; docs/positioning.md) -->
<p><b>One voice-driven assistant that directs your models, your coding agents and your computer.</b><br />
一个用语音驱动的助手，指挥你的模型、你的编程智能体和你的电脑。</p>

<p>
  <a href="https://github.com/Dodaios/Dodaios/releases/latest"><img src="https://img.shields.io/github/v/release/Dodaios/Dodaios?label=release&amp;labelColor=0A0A0A&amp;color=FAFAFA" alt="最新版本" /></a>
  <a href="https://github.com/Dodaios/Dodaios/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache_2.0-FAFAFA?labelColor=0A0A0A" alt="许可证：Apache 2.0" /></a>
  <a href="https://github.com/Dodaios/Dodaios/stargazers"><img src="https://img.shields.io/github/stars/Dodaios/Dodaios?labelColor=0A0A0A&amp;color=FAFAFA&amp;logo=github" alt="GitHub stars" /></a>
  <a href="https://discord.gg/x7USduHxbc"><img src="https://img.shields.io/badge/discord-join-FAFAFA?labelColor=0A0A0A&amp;logo=discord&amp;logoColor=white" alt="Discord" /></a>
</p>

<p>
  <a href="https://trendshift.io/repositories/91076?utm_source=repository-badge&amp;utm_medium=badge&amp;utm_campaign=badge-repository-91076" target="_blank" rel="noopener noreferrer"><img src="https://trendshift.io/api/badge/repositories/91076" alt="Dodaios%2FDodaios | Trendshift" width="250" height="55"/></a>
</p>

<p>
  <a href="#安装">安装</a> ·
  <a href="#你的套餐和密钥">你的套餐</a> ·
  <a href="#文档">文档</a> ·
  <a href="https://dodaios.ai">官网</a> ·
  <a href="https://discord.gg/x7USduHxbc">Discord</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.md">English</a>
</p>

</div>

> Dodaios is a locally installed, open-source Python program that runs as a desktop app or as a headless server with a browser UI on Windows, macOS and Linux. It turns a personal AI assistant into the control center for the work you do on your computer.
>
> At its core is a "lead" assistant you can talk to by voice (wake word, dictation, real-time spoken conversation and, as an early preview, phone calls), by chat or from a paired phone. It isn't tied to one provider and works with Claude, OpenAI, Gemini or local Ollama models. It handles tasks itself through tools, computer use, plugins, CLIs and MCP servers. Above all, it hands work off to coding agents. They run side by side in a built-in Agentic IDE as real Claude Code or Codex terminals, on your computer or on your own servers over SSH, each with a call sign you can address by name, plus Git integration and task splitting. There is also a "society" of persistent, named agents that message each other.
>
> Long-running work is covered by memory (about you, the people around you and the assistant's own persona), standing tasks, workflows, skills and opt-in life admin. The assistant also makes its own outputs, such as documents, slides, sheets and dashboards, and can propose and build the skills, routines and agents it is missing. A trust layer sets hard limits: outside Bypass permissions, moving money, handling credentials, permanent deletion and first contact with someone new always need your confirmation. In short, Dodaios is a voice-driven, locally running operating system for AI agents that makes one assistant the conductor of your models, your coding agents and your own computer.

Dodaios 是一个安装在本地的开源 Python 程序，可以作为桌面应用运行，也可以作为带浏览器界面的无屏幕服务器运行，支持 Windows、macOS 和 Linux。它把一个个人 AI 助手变成你在电脑上所做工作的控制中心。

它的核心是一个“主”助手，你可以用语音（唤醒词、听写、实时语音对话，以及尚处早期预览的电话通话）、用聊天，或者从已配对的手机上和它交流。它不绑定某一家提供商，可以使用 Claude、OpenAI、Gemini 或本地的 Ollama 模型。它通过工具、电脑操作、插件、命令行工具和 MCP 服务器自己完成任务。最重要的是，它会把工作交给编程智能体。这些智能体在内置的 Agentic IDE 里并排运行，是真正的 Claude Code 或 Codex 终端，可以在你的电脑上，也可以通过 SSH 在你自己的服务器上；每个终端都有一个呼号，你可以按名字指挥它，此外还有 Git 集成和任务拆分。另外还有一个由持久存在、各有名字的智能体组成的“社会”，它们之间可以互相发消息。

长期的工作靠这些来承接：记忆（关于你、你身边的人，以及助手自己的人设）、长期任务、工作流、技能，以及需要你主动开启的生活事务管理。助手还会制作自己的产出，比如文档、幻灯片、表格和仪表盘，并且能提议并构建它还缺少的技能、例行任务和智能体。信任层设有硬性限制：在“Bypass permissions”（跳过权限确认）模式之外，转账、处理凭据、永久删除，以及第一次联系某个新的人，总是需要你确认。简而言之，Dodaios 是一个用语音驱动、在本地运行的 AI 智能体操作系统，它让一个助手成为你的模型、你的编程智能体和你自己电脑的指挥。

https://github.com/user-attachments/assets/37cdc5a5-30d6-49c8-92ff-3454a075569f

<p align="center">
  <sub>A real recording at 60 frames a second, played at the speed it was filmed; the waits for the models are cut out. It was recorded with Claude Fable 5.2 and Claude Opus 5.5 through Claude Code. The code change, test runs and commit are real. <a href="https://github.com/Dodaios/Dodaios/blob/main/assets/demo/readme/dodaios-demo.mp4"><b>Watch the video</b></a> (MP4, 42 s, 2.5 MB)</sub>
</p>

## 安装

macOS 和 Linux：

```bash
curl -fsSL https://raw.githubusercontent.com/Dodaios/Dodaios/main/install/install.sh | bash
```

Windows，在 PowerShell 中：

```powershell
irm https://raw.githubusercontent.com/Dodaios/Dodaios/main/install/install.ps1 | iex
```

安装脚本会创建自己的 Python 环境，添加启动器并打开应用。首次启动时，你给助手起个名字（它同时也是唤醒词），连接一个模型，并选择你想怎样和它交流。要做编程工作，请至少安装一个编程智能体并登录，例如 Claude Code 或 Codex。

```bash
dodaios            # 启动桌面应用
dodaios update     # 安装最新版本
```

<details>
<summary>桌面安装包、pipx 和服务器</summary>

<br />

从最新版本下载适合你系统的安装包：

| Windows | macOS | Linux |
| --- | --- | --- |
| [Dodaios-Setup-x64.exe](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-Setup-x64.exe) | [Apple 芯片](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-macOS-arm64.dmg) · [Intel](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-macOS-x64.dmg) | [AppImage，x86_64](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-Linux-x86_64.AppImage) |

每个版本都在 `installers-SHA256SUMS.txt` 中列出校验和。安装包目前还没有签名：Windows 会显示警告，macOS 会要求你在“系统设置”的“隐私与安全性”中允许这个应用一次。[代码签名政策](https://github.com/Dodaios/Dodaios/blob/main/docs/code-signing-policy.md)说明了目前的进展。

用 pipx 可以得到体积更小的服务端软件包，不带桌面启动器。在没有屏幕的 Linux 服务器上，安装脚本接受 `--headless`，`dodaios serve` 只启动浏览器界面：

```bash
pipx install dodaios
curl -fsSL https://raw.githubusercontent.com/Dodaios/Dodaios/main/install/install.sh | bash -s -- --headless
dodaios serve      # 仅浏览器界面，适合没有屏幕的服务器
```

Dodaios 运行在 64 位的 Windows、macOS 和基于 glibc 的 Linux 上。终端安装脚本支持 x86-64 和 Arm64，需要 Python 3.11 到 3.14 和 Git；它会获取缺少的 Python，缺少 Git 时会提出帮你安装。显卡不是必需的。目前只有 Windows 11 有记录在案的实机验收。
[安装指南](https://github.com/Dodaios/Dodaios/blob/main/docs/product/start-here/install-dodaios.md) ·
[平台支持](https://github.com/Dodaios/Dodaios/blob/main/docs/product/reference/platform-support.md) ·
[在服务器上运行](https://github.com/Dodaios/Dodaios/blob/main/docs/headless-vps-deployment.md)

</details>

## 你的套餐和密钥

Dodaios 不花钱：没有 Dodaios 账号，也没有付费版。它不出售模型访问权限，也不会替你登录。它会启动每个编程智能体的官方命令行工具，每一个都由你自己登录，所以这些智能体用的是你已有的套餐和密钥。例如，Claude Code 需要付费的 Claude 套餐。你对每项服务的使用都遵循该服务自己的条款。
[提供商与 API 密钥](https://github.com/Dodaios/Dodaios/blob/main/docs/product/personalize-and-connect/providers-and-api-keys.md)

## 须知

- **你的数据。** 聊天记录、记忆、文档和设置都是运行 Dodaios 的那台电脑上的文件。模型或已连接的服务，会得到它完成请求中自己那一部分所需的内容。登录 Google、Slack 或 Figma 插件会经过本项目运行的一个小型令牌服务。
  [隐私与本地数据](https://github.com/Dodaios/Dodaios/blob/main/docs/product/privacy-safety-and-support/privacy-and-local-data.md)
- **先询问。** 新聊天从“Bypass permissions”（跳过权限确认）开始，在这个模式下什么都不会询问。选择一个会询问的模式后，上面的四项硬性限制总是要等你同意。
  [安全与审批](https://github.com/Dodaios/Dodaios/blob/main/docs/product/privacy-safety-and-support/safety-and-approvals.md)
- **尚未完成的部分。** 电话通话需要你自己的 Twilio 号码，目前是早期预览。大多数插件仍带有“Preview”（预览版）标记。手机应用是由你的电脑提供的网页应用。

## 文档

[功能导览](https://github.com/Dodaios/Dodaios/blob/main/docs/feature-tour.md)（英文）在一个页面上配图介绍了每个部分。同样的指南也在应用内的 **Docs** 页面里，并且可以搜索。
[首次运行设置](https://github.com/Dodaios/Dodaios/blob/main/docs/product/start-here/first-run-setup.md) ·
[故障排查](https://github.com/Dodaios/Dodaios/blob/main/docs/product/privacy-safety-and-support/troubleshooting.md) ·
[架构概览](https://github.com/Dodaios/Dodaios/blob/main/docs/architecture-overview.md)

## 参与贡献

欢迎修复问题、补充测试、提交平台报告和完善文档。[贡献指南](https://github.com/Dodaios/Dodaios/blob/main/CONTRIBUTING.md#your-first-contribution-in-10-minutes)能让你在大约十分钟内从 fork 走到一次通过的检查。问题和想法请到 [Discord](https://discord.gg/x7USduHxbc)。

感谢每一位在这里交付过成果的人，名单见[英文 README 的贡献者墙](https://github.com/Dodaios/Dodaios/blob/main/README.md#contributing)。

## 许可证

Dodaios 采用 [Apache License 2.0](https://github.com/Dodaios/Dodaios/blob/main/LICENSE) 许可，署名信息见 [NOTICE](https://github.com/Dodaios/Dodaios/blob/main/NOTICE)。名称和标志受[商标政策](https://github.com/Dodaios/Dodaios/blob/main/TRADEMARK.md)约束。Dodaios 是一个独立项目：它所配合使用的产品归其各自的开发者所有，Dodaios 支持某个工具，并不意味着该工具的开发者认可 Dodaios。Dodaios 在 2026 年 10 月之前叫 Personal Jarvis（[为什么改名](https://dodaios.ai/blog/personal-jarvis-is-now-dodaios/)）。赞助者见 [SPONSORS.md](https://github.com/Dodaios/Dodaios/blob/main/SPONSORS.md)。
