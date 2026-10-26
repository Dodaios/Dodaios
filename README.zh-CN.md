<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/brand/dodaios-logo-on-dark.svg" />
    <img alt="Dodaios" src="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/brand/dodaios-logo-on-light.svg" width="112" />
  </picture>
</p>

<h1 align="center">Dodaios</h1>

<p align="center">
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.md">English</a> ·
  <strong>简体中文</strong>
</p>

<!-- canonical tagline: keep in sync with README.md, GitHub description, dodaios.ai and X bio (docs/rename/repo-metadata-proposal.md) -->
<p align="center"><strong>Dodaios 是一个面向桌面的开源智能体操作系统（Agent OS）：在你自己的电脑上，用语音或聊天驱动你的编程智能体、浏览器和应用。</strong></p>

<p align="center">原名 <strong>Personal Jarvis</strong>。同一个项目，同一个许可证，只是换了名字（<a href="https://dodaios.ai/blog/personal-jarvis-is-now-dodaios/">原因</a>）。</p>

https://github.com/user-attachments/assets/3364aa29-8f38-4d3e-b148-184ad16669ff

<p align="center">
  <a href="https://pypi.org/project/dodaios/"><img alt="PyPI" src="https://img.shields.io/pypi/v/dodaios?labelColor=0A0A0A&amp;color=F7F7F4" /></a>
  <a href="https://github.com/Dodaios/Dodaios/blob/main/LICENSE"><img alt="Apache 2.0" src="https://img.shields.io/badge/License-Apache_2.0-F7F7F4?labelColor=0A0A0A" /></a>
  <a href="https://github.com/Dodaios/Dodaios/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/Dodaios/Dodaios/actions/workflows/ci.yml/badge.svg" /></a>
  <a href="https://discord.gg/x7USduHxbc"><img alt="Discord" src="https://img.shields.io/badge/Discord-join-F7F7F4?labelColor=0A0A0A&amp;logo=discord&amp;logoColor=white" /></a>
</p>

<p align="center">
  <a href="#安装"><strong>安装</strong></a> ·
  <a href="#动嘴写代码">动嘴写代码</a> ·
  <a href="#同时运行所有编程智能体">Agentic IDE</a> ·
  <a href="#一支智能体团队">智能体</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/docs/product/start-here/welcome-to-dodaios.md">文档</a> ·
  <a href="https://dodaios.ai">官网</a> ·
  <a href="https://discord.gg/x7USduHxbc">Discord</a>
</p>

<p align="center">如果 Dodaios 对你有用，在 GitHub 上点一个 <a href="https://github.com/Dodaios/Dodaios">Star</a> 能帮助更多人发现它。</p>

**属于你，没有附加条件。** Dodaios 可以运行在 Windows、macOS、Linux 或没有屏幕的服务器上。没有账号，没有付费版本，你和模型之间也没有我们的云：准备一个 API 密钥、你已经付费的 Claude 或 ChatGPT 订阅，或一个本地模型即可。任何可能改动你系统的操作都会先等待你的批准。

## 安装

```powershell
# Windows（PowerShell）
irm https://raw.githubusercontent.com/Dodaios/Dodaios/main/install/install.ps1 | iex
```

```bash
# macOS 和 Linux
curl -fsSL https://raw.githubusercontent.com/Dodaios/Dodaios/main/install/install.sh | bash
```

无需预先安装任何东西，也不需要 GPU。安装程序会打开应用，语言、唤醒词和模型都在应用内设置。
桌面版安装包和服务器部署见[更多安装方式](#更多安装方式)。

## 为什么选择 Dodaios

- **本地运行，无需账号。** 应用和数据都留在你的电脑上。
- **任意模型或订阅。** 托管模型、通过 Ollama 运行的本地模型，或者你的 Claude 和 ChatGPT 订阅。
- **多个编程智能体并排工作。** Claude Code、Codex、OpenCode 等在实时窗格中运行，你可以随时查看和指挥。
- **语音。** 自定义唤醒词、实时对话和听写，语音识别可以完全离线运行。

|  | Dodaios | 在不同终端里分别运行编程智能体 CLI | 托管的聊天助手 |
|---|---|---|---|
| 在你的电脑上运行 | 是。模型可以本地也可以托管 | CLI 在本地运行，模型通常是托管的 | 否，运行在服务商的云端 |
| 多个编程智能体并排 | 是，实时窗格，带呼号（T1、T2） | 每个智能体一个终端，手动切换 | 没有编程智能体窗格 |
| 语音 | 唤醒词、实时对话、听写 | 因工具而异 | 因服务商而异 |
| 开源 | 是，Apache 2.0 | 因工具而异：Codex CLI 和 OpenCode 开源，Claude Code 不开源 | 通常不开源 |

## 动嘴写代码

https://github.com/user-attachments/assets/1daa832e-a566-4f22-add6-8b21eb8aaaad

对 Dodaios 说话，它会把工作交给你的编程智能体。在这段录像（录制于改名之前）中，一句话就启动了一个新的 Claude Code 会话，去研究应用的性能。在 Agentic IDE 中，每个窗格都有一个呼号，所以你也可以说“T1，跑一下测试”或“T2，修复 T1 发现的问题”。Dodaios 会把每句话变成一份完整、了解项目上下文的任务说明；呼号不明确时会先问你；挂断之后，工作仍会继续。
[工作原理](https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/agentic-ide.md#send-clear-work)

## 同时运行所有编程智能体

https://github.com/user-attachments/assets/83c50d16-8c3c-420f-baab-e6d06381307b

Agentic IDE 把一块屏幕变成一个满是编程智能体的房间。打开一个项目，分成几个窗格，在每个窗格里启动你已安装的任意编程工具，使用你已经付费的订阅。差异对比、编辑器、Git 和拉取请求就在窗格旁边，你可以在每一行代码合并之前审阅它；每个窗格也始终是一个可以直接输入的真实终端。
[Agentic IDE 指南](https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/agentic-ide.md)

## 一支智能体团队

https://github.com/user-attachments/assets/4c29df69-2114-4ed1-a220-703f6ff8386a

一键创建专门的智能体：研究员、发布经理、写作者。每个智能体都有一个永不结束的对话，会从自己的工作中学习，按计划运行例行任务，并把产出放进 Artifacts，每一次工具调用都清晰可见。智能体也可以运行在 Hermes 和 OpenClaw 上。
[智能体指南](https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/dodaios-agents.md)

## 其他功能

<table>
  <tr><td><b>语音</b></td><td>自定义唤醒词、实时双向对话、在任意应用中听写，以及电话。语音可以完全离线运行。<a href="https://github.com/Dodaios/Dodaios/blob/main/docs/product/everyday-use/voice-conversations.md">语音指南</a></td></tr>
  <tr><td><b>电脑操作</b></td><td>在你要求时点击、输入并读取你的桌面和浏览器。<a href="https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/computer-use.md">电脑操作</a></td></tr>
  <tr><td><b>记忆</b></td><td>一个本地 wiki，智能体可以读取、写入并引用。<a href="https://github.com/Dodaios/Dodaios/blob/main/docs/product/knowledge-and-sharing/wiki-and-memory.md">记忆</a></td></tr>
  <tr><td><b>插件、MCP 和技能</b></td><td>40 多个一键集成、任意 MCP 服务器、GitHub 和 Vercel 等命令行工具，以及可复用的技能。<a href="https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/plugins.md">插件</a></td></tr>
  <tr><td><b>控制权在你手里</b></td><td>每个操作都经过风险检查（safe、monitor、ask、block），每次运行都有记录，密钥保存在系统的凭据存储中。<a href="https://github.com/Dodaios/Dodaios/blob/main/docs/product/privacy-safety-and-support/safety-and-approvals.md">安全与审批</a></td></tr>
  <tr><td><b>兼容</b></td><td>OpenAI、Claude、Gemini、OpenRouter、NVIDIA、Ollama 以及任何兼容 OpenAI 的服务器；Claude Code、Codex、OpenCode、Kimi Code、GLM、Grok Build、Antigravity、Cursor CLI 和 DeepSeek Harness。</td></tr>
</table>

## 更多安装方式

如果缺少 Python 或 Git，一行安装命令会为 Dodaios 单独下载一份私有副本，不需要管理员权限。再次运行即可更新。安装完成后，从桌面启动器或终端启动 Dodaios：

```bash
dodaios         # 完整桌面版
```

更喜欢普通安装包？
[Windows（x64）](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-Setup-x64.exe) ·
[macOS（Apple 芯片）](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-macOS-arm64.dmg) ·
[macOS（Intel）](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-macOS-x64.dmg) ·
[Linux（AppImage，x86_64）](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-Linux-x86_64.AppImage)。
macOS 磁盘映像尚未经过 Apple 公证：首次启动时请打开 **系统设置 > 隐私与安全性**，点击 **仍要打开**。SignPath Foundation 开源项目批准后，Windows 安装程序将按照[代码签名政策（Code signing policy）](https://github.com/Dodaios/Dodaios/blob/main/docs/code-signing-policy.md)签名。Free code signing provided by SignPath.io, certificate by SignPath Foundation.

在服务器上运行 `pip install dodaios` 和 `dodaios serve`，然后打开 `http://localhost:47821`。[无界面部署指南](https://github.com/Dodaios/Dodaios/blob/main/docs/headless-vps-deployment.md)介绍了远程使用麦克风所需的 HTTPS，以及在 Intel Mac 和 Windows ARM64 上用 pip 安装时需要的[原生软件包索引](https://github.com/Dodaios/Dodaios/blob/main/docs/product/start-here/install-dodaios.md#install-the-isolated-pypi-package)。

## 文档

| 目标 | 从这里开始 |
|---|---|
| 入门 | [首次运行](https://github.com/Dodaios/Dodaios/blob/main/docs/product/start-here/first-run-setup.md) · [应用导览](https://github.com/Dodaios/Dodaios/blob/main/docs/product/start-here/desktop-app-tour.md) |
| 对话和听写 | [语音](https://github.com/Dodaios/Dodaios/blob/main/docs/product/everyday-use/voice-conversations.md) · [听写](https://github.com/Dodaios/Dodaios/blob/main/docs/product/everyday-use/dictation.md) |
| 智能体和自动化 | [Agentic IDE](https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/agentic-ide.md) · [智能体](https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/dodaios-agents.md) · [例行任务](https://github.com/Dodaios/Dodaios/blob/main/docs/routines.md) · [MCP](https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/mcp-connections.md) · [CLI](https://github.com/Dodaios/Dodaios/blob/main/docs/dodaios-cli.md) |
| 模型 | [服务商](https://github.com/Dodaios/Dodaios/blob/main/docs/product/personalize-and-connect/providers-and-api-keys.md) · [本地模型](https://github.com/Dodaios/Dodaios/blob/main/docs/product/personalize-and-connect/local-ai-providers.md) |
| 运行和排错 | [服务器](https://github.com/Dodaios/Dodaios/blob/main/docs/headless-vps-deployment.md) · [架构](https://github.com/Dodaios/Dodaios/blob/main/docs/architecture-overview.md) · [故障排除](https://github.com/Dodaios/Dodaios/blob/main/docs/product/privacy-safety-and-support/troubleshooting.md) · [隐私](https://github.com/Dodaios/Dodaios/blob/main/docs/product/privacy-safety-and-support/privacy-and-local-data.md) |

## 参与贡献

可以从一个 [good first issue](https://github.com/Dodaios/Dodaios/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22) 开始。如果目前没有，可以选择任何带有 [`help wanted`](https://github.com/Dodaios/Dodaios/issues?q=is%3Aissue+is%3Aopen+label%3A%22help+wanted%22) 或 [`area:docs`](https://github.com/Dodaios/Dodaios/issues?q=is%3Aissue+is%3Aopen+label%3Aarea%3Adocs) 标签的 issue，或者在 [Discussions](https://github.com/Dodaios/Dodaios/discussions) 里提问。[10 分钟完成你的第一次贡献](https://github.com/Dodaios/Dodaios/blob/main/CONTRIBUTING.md#your-first-contribution-in-10-minutes)会一步步带你完成。安全问题请参阅 [SECURITY.md](https://github.com/Dodaios/Dodaios/blob/main/SECURITY.md)。

在 GitHub 上点一个 Star 能帮助更多人发现 Dodaios。赞助者列在 [SPONSORS.md](https://github.com/Dodaios/Dodaios/blob/main/SPONSORS.md) 中。

## 许可证

[Apache 2.0](https://github.com/Dodaios/Dodaios/blob/main/LICENSE)。1.6.0 及更早的版本保留原来的 MIT 许可证。参见 [NOTICE](https://github.com/Dodaios/Dodaios/blob/main/NOTICE) 和[商标说明](https://github.com/Dodaios/Dodaios/blob/main/TRADEMARK.md)。
