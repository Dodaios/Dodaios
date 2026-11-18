<div align="center">

<a href="https://dodaios.ai">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/brand/dodaios-logo-on-dark.svg" />
    <img src="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/brand/dodaios-logo-on-light.svg" alt="Dodaios" width="112" />
  </picture>
</a>

<h1>Dodaios</h1>

<!-- the promise and the intro, translated (English word for word in README.md; docs/positioning.md) -->
<p><b>All your coding agents, managed from one chat.</b><br />
你所有的编程智能体，在一个聊天里统一管理。</p>

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
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.md">English</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.ja.md">日本語</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.es.md">Español</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.hi.md">हिन्दी</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.ar.md">العربية</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.fr.md">Français</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.bn.md">বাংলা</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.pt-BR.md">Português (Brasil)</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.ru.md">Русский</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.id.md">Bahasa Indonesia</a>
</p>

</div>

> You have Claude Code in one terminal, Codex in another, and a chat tab where you copy plans back and forth. Dodaios ends that. It is a layer above all your coding agents: you say what you want, by voice or chat, and one assistant takes it from there. It writes the brief, launches the right agent in its built-in Agentic IDE, keeps watch while it works and tells you when it's done or needs you. Run five agents at once and still know exactly what each one did.
>
> Open source, and it runs on your computer. Works with your Claude or ChatGPT subscription, with API keys for Claude, OpenAI and Gemini, or with local Ollama models.

你在一个终端里开着 Claude Code，在另一个终端里开着 Codex，还有一个聊天标签页，用来把计划来回复制。Dodaios 终结了这一切。它是位于你所有编程智能体之上的一层：你用语音或聊天说出想要什么，一个助手就会接手。它撰写任务说明，在内置的 Agentic IDE 中启动合适的智能体，在其工作时持续关注，并在完成或需要你时通知你。同时运行五个智能体，依然清楚每一个做了什么。

开源，运行在你自己的电脑上。可使用你的 Claude 或 ChatGPT 订阅、Claude、OpenAI 和 Gemini 的 API 密钥，或本地 Ollama 模型。

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
