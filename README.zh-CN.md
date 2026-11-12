<div align="center">

<a href="https://dodaios.ai">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/brand/dodaios-logo-on-dark.svg" />
    <img src="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/brand/dodaios-logo-on-light.svg" alt="Dodaios" width="112" />
  </picture>
</a>

<h1>Dodaios</h1>

<p><b>把你的电脑变成一个 AI 智能体。</b></p>

<p>
  说话或打字都行。它会回答问题，操作你的桌面和应用，<br />
  并把耗时的工作交给在后台运行的智能体。<br />
  模型由你自带，有风险的操作它会先问你。
</p>

<p>
  <a href="https://github.com/Dodaios/Dodaios/releases/latest"><img src="https://img.shields.io/github/v/release/Dodaios/Dodaios?label=release&amp;labelColor=0A0A0A&amp;color=F7F7F4" alt="最新版本" /></a>
  <a href="https://github.com/Dodaios/Dodaios/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache_2.0-F7F7F4?labelColor=0A0A0A" alt="许可证：Apache 2.0" /></a>
  <a href="https://github.com/Dodaios/Dodaios/stargazers"><img src="https://img.shields.io/github/stars/Dodaios/Dodaios?labelColor=0A0A0A&amp;color=F7F7F4&amp;logo=github" alt="GitHub stars" /></a>
  <a href="https://discord.gg/x7USduHxbc"><img src="https://img.shields.io/badge/discord-join-F7F7F4?labelColor=0A0A0A&amp;logo=discord&amp;logoColor=white" alt="Discord" /></a>
</p>

<p>
  <a href="https://dodaios.ai">官网</a> ·
  <a href="#安装">安装</a> ·
  <a href="#文档">文档</a> ·
  <a href="https://discord.gg/x7USduHxbc">Discord</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.md">English</a>
</p>

</div>

<p align="center">
  <a href="https://github.com/Dodaios/Dodaios/blob/main/assets/demo/readme/dodaios-demo.gif">
    <img src="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/demo/readme/dodaios-demo.gif" alt="一段 59 秒的 Dodaios 录屏：首次启动设置、应用自带的导览、插件目录、在 Agentic IDE 中连接项目并在终端里运行测试、新增一条记忆、桌面宠物，以及两个区域并排显示" width="100%" />
  </a>
</p>

<p align="center">
  <sub>真实应用（5.0.0 版）的一次连续录制，以 1.4 倍速播放。录制时没有连接任何模型，所以你看到的是应用本身，没有智能体的回答。</sub>
</p>

## 它是什么

Dodaios 是一款桌面应用，支持 Windows、macOS 和 Linux。在没有屏幕的服务器上，同一个应用在浏览器里运行。你用聊天或语音把任务交给它：

- 简短的问题，立刻回答。
- 需要动用电脑的任务，通过工具完成：桌面、浏览器、终端，以及你连接的服务。
- 耗时的工作，交给一个在后台运行的智能体，完成后向你汇报。

有三点在任何地方都成立：

- **模型由你自带。** 用你已经在付费的订阅登录，粘贴一个 API 密钥，或者运行本地模型。聊天、语音、电脑操作和智能体可以各用不同的提供商。
- **先问再做。** 模型想发起的每一次工具调用都会得到一个风险等级。任何会改动你的系统或账号的操作，都要等你点头。
- **数据留在你这里。** 聊天记录、记忆、设置和结果都是运行 Dodaios 的那台电脑上的文件。没有 Dodaios 账号，也没有付费版。模型或已连接的服务只会收到完成它那部分工作所需的内容。

## 安装

**桌面应用。** 从最新版本下载适合你系统的安装包：

| Windows | macOS | Linux |
| --- | --- | --- |
| [Dodaios-Setup-x64.exe](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-Setup-x64.exe) | [Apple 芯片](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-macOS-arm64.dmg) · [Intel](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-macOS-x64.dmg) | [AppImage，x86_64](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-Linux-x86_64.AppImage) |

每个版本都在 `installers-SHA256SUMS.txt` 中列出校验和。Windows 安装包目前还没有代码签名，进展见[代码签名政策](https://github.com/Dodaios/Dodaios/blob/main/docs/code-signing-policy.md)。

**通过终端。** 安装脚本会创建自己的 Python 环境，添加启动器并打开应用。

```powershell
# Windows（PowerShell）
irm https://raw.githubusercontent.com/Dodaios/Dodaios/main/install/install.ps1 | iex
```

```bash
# macOS 和 Linux
curl -fsSL https://raw.githubusercontent.com/Dodaios/Dodaios/main/install/install.sh | bash

# 没有屏幕的 Linux 服务器
curl -fsSL https://raw.githubusercontent.com/Dodaios/Dodaios/main/install/install.sh | bash -s -- --headless
```

**使用 pipx。** 体积更小的服务端软件包，不带桌面启动器：

```bash
pipx install dodaios
```

**然后启动：**

```bash
dodaios            # 桌面应用：窗口、语音和屏幕上的悬浮层
dodaios serve      # 仅浏览器界面，适合没有屏幕的服务器
dodaios update     # 安装最新发布的版本
```

首次启动会问三件事：一个名字（它同时也是唤醒词）、一个模型连接，以及你想用什么方式和它交流。安装不需要任何提供商，得到回答才需要。

它运行在 64 位的 Windows、macOS 和基于 glibc 的 Linux 上，支持 x86-64 和 Arm64。终端安装脚本需要 Python 3.11 到 3.14 和 Git，缺哪个就自动获取哪个。显卡不是必需的。
[安装指南](https://github.com/Dodaios/Dodaios/blob/main/docs/product/start-here/install-dodaios.md) ·
[平台支持](https://github.com/Dodaios/Dodaios/blob/main/docs/product/reference/platform-support.md) ·
[在服务器上运行](https://github.com/Dodaios/Dodaios/blob/main/docs/headless-vps-deployment.md)

## 你会得到什么

### 任意模型，由你做主

<img src="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/readme/connect.png" alt="设置步骤“Connect your AI”：Claude、OpenAI、Google Gemini 和 xAI Grok 可用订阅登录或 API 密钥连接，另有免费的本地模型" width="100%" />

Claude、OpenAI、Google Gemini 和 xAI Grok 可以用你已有的订阅连接，也可以用 API 密钥。OpenRouter、LiteLLM、Google Vertex AI 和 NVIDIA NIM 同样可用。本地模型通过 Ollama 或任何兼容 OpenAI 的服务器运行，不需要账号，也不需要密钥。密钥保存在系统的钥匙串里。
[提供商与 API 密钥](https://github.com/Dodaios/Dodaios/blob/main/docs/product/personalize-and-connect/providers-and-api-keys.md) ·
[本地 AI 提供商](https://github.com/Dodaios/Dodaios/blob/main/docs/product/personalize-and-connect/local-ai-providers.md)

### 聊天和语音

打字，或者说出唤醒词，或者按下通话快捷键直接说。语音有两种运行方式。管线模式把语音识别、模型和语音合成串起来，每一环都可以是本地的或云端的。实时模式用一个能边听边说的实时模型。听写是另一项功能：它把你说的话输入到你正在使用的应用里。
[语音对话](https://github.com/Dodaios/Dodaios/blob/main/docs/product/everyday-use/voice-conversations.md) ·
[听写](https://github.com/Dodaios/Dodaios/blob/main/docs/product/everyday-use/dictation.md)

### 在你的项目里工作的编程智能体

<img src="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/readme/agentic-ide.png" alt="已连接项目的 Agentic IDE：与编程智能体的对话线程、模型和权限选择器、分支，以及测试全部通过的终端" width="100%" />

Agentic IDE 在你自己的项目文件夹里运行编程智能体：Claude Code、Codex、OpenCode、Kimi Code、GLM Coding Plan、Grok Build、Antigravity 和 DeepSeek Harness，每一个都带着它真正支持的模型、推理强度和权限模式。一个线程可以拥有自己的工作树和自己的分支。终端、改动、Git、文件和浏览器预览就在对话旁边。
[Agentic IDE](https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/agentic-ide.md)

### 不用你盯着也能干活的智能体

给一个智能体起个名字，写一句职责和一份长期指令。它有自己的一条对话、自己的模型和自己的一组工具，还能按计划、按事件或通过 webhook 运行例行任务。把几个智能体编成团队并指定一位负责人：你把目标告诉负责人，它来拆分工作、检查交回的结果，完成后向你汇报。耗时的一次性工作作为后台任务在隔离的 Git 工作树里运行，结果经过审查后才会报告为完成。
[智能体](https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/dodaios-agents.md) ·
[例行任务](https://github.com/Dodaios/Dodaios/blob/main/docs/routines.md) ·
[团队负责人](https://github.com/Dodaios/Dodaios/blob/main/docs/agent-society/team-leads.md)

### 它能使用的工具

<img src="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/readme/plugins.png" alt="插件目录：GitHub、Vercel、Notion、Slack、Linear、Google Calendar、Gmail、Outlook、Dropbox、Google Drive 等" width="100%" />

- **插件。** 目录里自带 47 个服务，包括 GitHub、Slack、Notion、Linear、Gmail、Google Calendar、Home Assistant 和 Spotify。
- **MCP 服务器和技能。** 可以添加任何 Model Context Protocol 服务器。技能是一份写下来的、助手会照着执行的流程，你可以自己写，也可以让它替你写。
- **电脑操作。** 它能读取屏幕并使用鼠标和键盘，在桌面应用和浏览器里都可以。
- **命令行。** `dodaios` 可以从终端驱动一个正在运行的实例，所以脚本或另一个编程智能体能做到窗口里能做的一切。

[插件](https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/plugins.md) ·
[MCP 连接](https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/mcp-connections.md) ·
[技能](https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/skills.md) ·
[电脑操作](https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/computer-use.md) ·
[CLI](https://github.com/Dodaios/Dodaios/blob/main/docs/dodaios-cli.md)

### 看得见的记忆

<img src="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/readme/memory.png" alt="记忆页面：按类别排列的六条记忆，其中一条已展开，显示它的来源以及固定、编辑、不再属实和遗忘等操作" width="100%" />

Dodaios 会记住关于你和你工作的简短句子：你喜欢怎样的回答、你提到的人、你正在做的项目。所有这些都保存在你电脑上的一个文件里。每一条你都可以查看、更正、固定、导出或让它遗忘。事实变了，旧的那条会带着日期被结束，而不是被覆盖。密码和密钥永远不会被保存。
[记忆](https://github.com/Dodaios/Dodaios/blob/main/docs/product/knowledge-and-sharing/wiki-and-memory.md)

### 一些小细节

<table>
  <tr>
    <td width="50%"><img src="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/readme/pets.png" alt="我的宠物：当前宠物 Ember（一条小龙）和一排像素风宠物" width="100%" /></td>
    <td width="50%"><img src="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/readme/side-by-side.png" alt="两个区域并排显示：左边是带终端的 Agentic IDE，右边是聊天" width="100%" /></td>
  </tr>
  <tr>
    <td valign="top"><b>宠物。</b>桌面上的一个像素小伙伴，会随着 Dodaios 聆听、思考和说话做出反应。内置二十个，你也可以自己做。<a href="https://github.com/Dodaios/Dodaios/blob/main/docs/pets.md">宠物</a></td>
    <td valign="top"><b>并排显示。</b>最多可以把四个区域放在一起，比如一个项目和一个聊天。界面提供英语、德语、西班牙语、中文和葡萄牙语。</td>
  </tr>
</table>

应用里还有：延续同一条对话的手机伴侣、任务和提醒、每次运行的步骤与工具调用记录，以及一个显示用量花费的页面。
[应用导览](https://github.com/Dodaios/Dodaios/blob/main/docs/product/start-here/desktop-app-tour.md)

## 一次请求的经过

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/brand/how-a-request-runs-dark.svg" />
  <img src="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/brand/how-a-request-runs-light.svg" alt="你用语音或聊天提出请求。Dodaios 在三条路线中选一条：回答、执行，或交给智能体。操作要通过风险检查，等级为安全、监控、询问你和阻止。然后完成，每一步都保存在历史记录里。" width="100%" />
</picture>

模型提出的每一次工具调用，在能碰到你的电脑或账号之前，都要先过同一道关卡：

| 等级 | 会发生什么 |
| --- | --- |
| **安全（Safe）** | 不询问，直接运行。 |
| **监控（Monitor）** | 不询问，直接运行，并标记为待查看。 |
| **询问（Ask）** | 等你同意。没有回应就当作拒绝。 |
| **阻止（Block）** | 被拒绝。批准也无法推翻。 |

一次批准只对应一次调用，不包括这项工作余下的部分。这道关卡不是沙箱，也不是撤销功能：它管的是 Dodaios 发起的工具调用，操作系统自身的权限仍然有效。
[安全与批准](https://github.com/Dodaios/Dodaios/blob/main/docs/product/privacy-safety-and-support/safety-and-approvals.md) ·
[隐私与本地数据](https://github.com/Dodaios/Dodaios/blob/main/docs/product/privacy-safety-and-support/privacy-and-local-data.md) ·
[安全政策](https://github.com/Dodaios/Dodaios/blob/main/SECURITY.md)

## 哪些功能在哪里可用

| | Windows | macOS | Linux 桌面 | Linux 服务器 |
| --- | --- | --- | --- | --- |
| 聊天、智能体、任务、记忆、设置 | 支持 | 支持 | 支持 | 在浏览器中 |
| 桌面应用 | 支持 | 支持 | 支持 | 不支持 |
| 使用电脑麦克风的语音 | 支持 | 需要授权 | 需要 PortAudio | 通过浏览器 |
| 全局快捷键 | 支持 | 需要授权 | X11 | 不支持 |
| 电脑操作 | 支持 | 需要授权 | X11 | 不支持 |

Windows 11 是有实机检查记录的系统。macOS 和 Linux 桌面的实现已经完成并有测试覆盖，实机验收尚未完成。某项功能在你的系统上无法运行时，它会明确告诉你，其余部分照常工作。
[平台支持](https://github.com/Dodaios/Dodaios/blob/main/docs/product/reference/platform-support.md)

## 文档

以下文档为英文。

- [欢迎使用 Dodaios](https://github.com/Dodaios/Dodaios/blob/main/docs/product/start-here/welcome-to-dodaios.md)：它做什么，不做什么
- [首次运行设置](https://github.com/Dodaios/Dodaios/blob/main/docs/product/start-here/first-run-setup.md)和[你的第一次聊天](https://github.com/Dodaios/Dodaios/blob/main/docs/product/start-here/start-your-first-chat.md)
- [故障排查](https://github.com/Dodaios/Dodaios/blob/main/docs/product/privacy-safety-and-support/troubleshooting.md)
- [配置参考](https://github.com/Dodaios/Dodaios/blob/main/docs/product/reference/configuration-reference.md)和 [CLI 参考](https://github.com/Dodaios/Dodaios/blob/main/docs/dodaios-cli-reference.md)
- [架构概览](https://github.com/Dodaios/Dodaios/blob/main/docs/architecture-overview.md)，写给想改代码的人

同样的指南也在应用内的 **Docs** 页面里，并且可以搜索。

## 参与贡献

欢迎修复问题、补充测试、改进无障碍、提交平台报告和完善文档。[贡献指南](https://github.com/Dodaios/Dodaios/blob/main/CONTRIBUTING.md#your-first-contribution-in-10-minutes)能让你在大约十分钟内从 fork 走到一次通过的检查。适合入手的是带有 [good first issue](https://github.com/Dodaios/Dodaios/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22) 和 [help wanted](https://github.com/Dodaios/Dodaios/issues?q=is%3Aissue+is%3Aopen+label%3A%22help+wanted%22) 标签的 issue。问题和想法请到 [Discord](https://discord.gg/x7USduHxbc)。

感谢每一位在这里交付过成果的人，名单见[英文 README 的贡献者墙](https://github.com/Dodaios/Dodaios/blob/main/README.md#contributing)。

## 许可证

Dodaios 采用 [Apache License 2.0](https://github.com/Dodaios/Dodaios/blob/main/LICENSE) 许可，署名信息见 [NOTICE](https://github.com/Dodaios/Dodaios/blob/main/NOTICE)。名称和标志受[商标政策](https://github.com/Dodaios/Dodaios/blob/main/TRADEMARK.md)约束，不在许可证的授权范围内。

Dodaios 在 2026 年 10 月之前叫 Personal Jarvis。同一个项目，同一个许可证（[为什么改名](https://dodaios.ai/blog/personal-jarvis-is-now-dodaios/)）。

赞助者见 [SPONSORS.md](https://github.com/Dodaios/Dodaios/blob/main/SPONSORS.md)。
