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

<p align="center"><img src="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/demo/readme/dodaios-demo.gif" alt="Dodaios：三个编程智能体在 Agentic IDE 中并排工作，旁边是浏览器、文件和 Git 差异" width="800" /></p>

<p align="center">
  <a href="https://pypi.org/project/dodaios/"><img alt="PyPI" src="https://img.shields.io/pypi/v/dodaios?labelColor=0A0A0A&amp;color=F7F7F4" /></a>
  <a href="https://github.com/Dodaios/Dodaios/blob/main/LICENSE"><img alt="Apache 2.0" src="https://img.shields.io/badge/License-Apache_2.0-F7F7F4?labelColor=0A0A0A" /></a>
  <a href="https://github.com/Dodaios/Dodaios/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/Dodaios/Dodaios/actions/workflows/ci.yml/badge.svg" /></a>
  <a href="https://discord.gg/x7USduHxbc"><img alt="Discord" src="https://img.shields.io/badge/Discord-join-F7F7F4?labelColor=0A0A0A&amp;logo=discord&amp;logoColor=white" /></a>
</p>

<p align="center">
  <a href="#安装"><strong>安装</strong></a> ·
  <a href="#为什么选择-dodaios">为什么选择 Dodaios</a> ·
  <a href="#动嘴写代码">动嘴写代码</a> ·
  <a href="#从一句话到合并的拉取请求">工作流</a> ·
  <a href="#一个应用包含一切">功能</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/docs/product/start-here/welcome-to-dodaios.md">文档</a> ·
  <a href="https://dodaios.ai">官网</a> ·
  <a href="https://discord.gg/x7USduHxbc">Discord</a> ·
  <a href="https://x.com/dodaios">X</a>
</p>

<p align="center">如果 Dodaios 对你有用，在 GitHub 上点一个 <a href="https://github.com/Dodaios/Dodaios">Star</a> 能帮助更多人发现它。</p>

<p align="center"><sub>有 Claude 或 ChatGPT 订阅，或者有本地模型，就不需要 API 密钥。</sub></p>

---

## 安装

**Windows（PowerShell）**

```powershell
irm https://raw.githubusercontent.com/Dodaios/Dodaios/main/install/install.ps1 | iex
```

**macOS 和 Linux**

```bash
curl -fsSL https://raw.githubusercontent.com/Dodaios/Dodaios/main/install/install.sh | bash
```

无需预先安装任何东西，也不需要 GPU。准备一个 API 密钥、一个 Claude 或 ChatGPT 订阅，或一个本地模型即可。
桌面版安装包和服务器部署见[更多安装方式](#更多安装方式)。

## 为什么选择 Dodaios

- **本地运行，无需账号。** 应用和数据都留在你的电脑上。不用注册，你和模型之间也没有我们的云。
- **任意模型或订阅。** 托管模型、通过 Ollama 运行的本地模型，或者你已经付费的 Claude 和 ChatGPT 订阅。
- **多个编程智能体并排工作。** Claude Code、Codex、OpenCode 等在实时窗格中运行，你可以随时查看和指挥。
- **语音。** 自定义唤醒词、实时对话和听写，语音识别可以完全离线运行。

|  | Dodaios | 在不同终端里分别运行编程智能体 CLI | 托管的聊天助手 |
|---|---|---|---|
| 在你的电脑上运行 | 是。模型可以本地也可以托管 | CLI 在本地运行，模型通常是托管的 | 否，运行在服务商的云端 |
| 多个编程智能体并排 | 是，实时窗格，带呼号（T1、T2） | 每个智能体一个终端，手动切换 | 没有编程智能体窗格 |
| 语音 | 唤醒词、实时对话、听写 | 因工具而异 | 因服务商而异 |
| 开源 | 是，Apache 2.0 | 因工具而异：Codex CLI 和 OpenCode 开源，Claude Code 不开源 | 通常不开源 |

## 动嘴写代码

打开一个项目，在几个窗格里分别启动 Claude Code、Codex 或 OpenCode，然后直接对它们说话。每个窗格都有一个呼号，你可以像指挥团队一样指挥它们：

> “T1，跑一下测试。”<br />
> “T2，修复 T1 发现的问题。”<br />
> “T3，为这个版本写更新日志。”<br />
> “T2 现在在做什么？”

- **你开口，Dodaios 写提示词。** 它把你的一句话变成一份完整、了解项目上下文的任务说明，并输入到对应的窗格。
- **同一任务或分工。** “让 T1 和 T2 做同样的检查”会发送同一条指令；“让 T1 和 T2 分担这次审查”会分配不同的部分。
- **按需新开窗格。** 需要更多智能体时，Dodaios 会打开新窗格并下达任务。你没点名的窗格不会被动。
- **不靠猜。** 呼号不明确时，Dodaios 会先问你再发送；每个窗格都会显示你的指令是否真正送达。
- **挂断后工作继续。** 已经下达的指令仍会送达，通话结束后智能体也会继续工作。

它使用你已经付费的订阅，每个窗格仍然是一个真正的终端，你随时可以自己输入。详见
[Agentic IDE 指南](https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/agentic-ide.md#send-clear-work)。

## 从一句话到合并的拉取请求

1. **和主智能体一起规划。** 用语音或聊天说出你想要什么。主智能体会问清所需信息，再把工作交给合适的智能体或窗格。
2. **并行构建。** Claude Code、Codex、OpenCode 以及另外六个编程智能体在实时窗格中并排运行；需要的话，每个都在自己的分支和 git worktree 里工作。
3. **审查每一处改动。** 差异对比、源代码管理和编辑器就在窗格旁边，每一行在合并前你都能看到。
4. **在 Git 面板里发布。** 分支、拉取请求、CI 检查和合并，都不用切换到浏览器。
5. **把其余工作交出去。** 内置的或运行在 Hermes 和 OpenClaw 上的助理智能体，负责写发布说明、起草发布帖子，并按计划执行例程。
6. **全部记住。** 一个本地记忆知识库保存每次对话、每个智能体和每个项目的上下文，下次接着用。

## 一个应用包含一切

<table>
  <tr>
    <td width="33%"><strong>Agentic IDE</strong><br />所有编程智能体在实时终端窗格中并排运行。</td>
    <td width="33%"><strong>Git 与拉取请求</strong><br />内置差异对比、分支、PR 和 CI 检查。</td>
    <td width="33%"><strong>主智能体</strong><br />一个负责规划、分派并汇报结果的助手。</td>
  </tr>
  <tr>
    <td><strong>智能体团队</strong><br />拥有各自对话、工具、日程和记忆的专家。</td>
    <td><strong>Hermes 与 OpenClaw</strong><br />在你已经在用的开放智能体运行时上运行智能体。</td>
    <td><strong>语音</strong><br />唤醒词、实时对话、听写和电话通话。</td>
  </tr>
  <tr>
    <td><strong>电脑操控</strong><br />在你的桌面和浏览器中点击、输入和读取屏幕。</td>
    <td><strong>记忆</strong><br />一个由智能体读取、写入并引用的本地知识库。</td>
    <td><strong>插件、MCP 与技能</strong><br />40 多个一键集成，也可以接入你自己的。</td>
  </tr>
  <tr>
    <td><strong>任意模型</strong><br />云端模型、本地模型，或你的 Claude 和 ChatGPT 订阅。</td>
    <td><strong>例程</strong><br />智能体按计划完成重复性工作，无需你开口。</td>
    <td><strong>产出物（Artifacts）</strong><br />智能体生成的每份报告、页面和文件都集中在一处。</td>
  </tr>
</table>

**免费、开源，在你自己的电脑上运行。** 支持 Windows、macOS、Linux，以及无界面的服务器。
无需注册账号，中间也没有我们的云服务。任何可能改动你系统的操作都会先等待你的批准。

> **界面语言：** 桌面应用提供简体中文界面。可在首次启动的设置窗口中选择“中文”，
> 也可以随时在“设置 > 语言”中切换。

## 成倍放大的 Vibe Coding

https://github.com/user-attachments/assets/290a8687-f925-4bb1-ac4c-0f23ea948a07

<p align="center"><sub>Agentic IDE 的真实录屏：三个智能体同时工作，侧边栏里是你自己的 Chrome，还有文件、Git 差异和第二个工作区。</sub></p>

**Agentic IDE** 把一块屏幕变成一个编程车间。打开一个项目，把它拆分成多个窗格，再给每个窗格分配一个编程智能体。
每个窗格都有自己的呼号，你可以完全不用动手地指挥它们：

> *“让 T1 去写测试。”* · *“T2 在忙什么？”* · *“把修复方案发给所有窗格。”*

- **所有编程 CLI 尽在一处。** 直接使用你已有的订阅；Dodaios 会检测已安装的工具，一键在窗格中启动。
- **一份任务，多个智能体。** 把同一个任务发给多个窗格，对比它们交回的结果。
- **解放双手。** 在智能体打字的同时和 Dodaios 说话；它会按呼号把你的任务转达给对应的窗格。
- **随时接管。** 每个窗格都是一个真正的终端，你可以直接在里面输入。

[Agentic IDE 指南 →](https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/agentic-ide.md)

## 一支持续工作的智能体团队

**Dodaios 智能体**是你一键创建的长期专家——研究员、发布经理、营销文案，你的工作需要什么就创建什么。

- **每个智能体一个永不结束的对话。** 明天从你停下的地方继续。
- **它们会学习。** 智能体会从自己的工作中积累私有经验，越来越擅长你的任务。
- **它们按计划运行。** 给智能体设定一个例程，它就会主动完成工作。
- **它们交回真正的成果。** 文件、报告和计划都会出现在“产出物”中，每一次工具调用都清晰可见。
- **较长的行动在隔离环境中运行。** 编程行动在独立的 git worktree 中进行，可以拆分成并行的工作者，并在你看到结果前通过审查。

[智能体指南 →](https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/dodaios-agents.md) ·
[智能体如何学习 →](https://github.com/Dodaios/Dodaios/blob/main/docs/agent-society/self-learning.md) ·
[例程 →](https://github.com/Dodaios/Dodaios/blob/main/docs/routines.md)

## 和你的电脑说话

选一个你自己的唤醒词——“Hey Nova”“Computer”，什么都行——然后直接开口。

- **实时对话**，轮流发言自然流畅。可以让它打开网站、查看日历，或在一句话说到一半时派出一个智能体。
- **听写**把你说的话输入到任意应用中，并支持个人词典。
- **电话通话**使用你自己的号码：给 Dodaios 打电话，或者在你批准后让它替你给别人打电话。
- **本地语音**可完全离线运行；云端语音为可选项。

[语音指南 →](https://github.com/Dodaios/Dodaios/blob/main/docs/product/everyday-use/voice-conversations.md) ·
[听写 →](https://github.com/Dodaios/Dodaios/blob/main/docs/product/everyday-use/dictation.md)

## 连接一切

- **插件和 MCP。** 只需在浏览器中登录一次，即可从市场安装连接器，也可以添加任何 MCP 服务器。
- **命令行工具。** GitHub、Vercel、Supabase、Stripe、Docker、各类云 CLI 等，都能在应用中被检测到并完成登录。
- **技能。** 可复用的指令，当你的请求合适时 Dodaios 会自动调用。
- **渠道。** 通过 Telegram 和 Discord 联系 Dodaios。
- **你自己的脚本。** `dodaios` 命令和本地 API 让其他程序——以及其他智能体——拥有和你一样的控制能力。

[插件 →](https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/plugins.md) ·
[MCP →](https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/mcp-connections.md) ·
[CLI →](https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/cli-connections.md) ·
[Dodaios CLI →](https://github.com/Dodaios/Dodaios/blob/main/docs/dodaios-cli.md)

## 控制权在你手里

每个操作都要经过风险检查——**安全、监控、询问或阻止**。任何可能改变你系统的操作都会等待你的批准，
每次运行都会被记录，让你清楚看到到底发生了什么。密钥保存在操作系统的凭据存储中。
除非你连接了需要联网的服务，否则任何数据都不会离开你的电脑。

[安全与审批 →](https://github.com/Dodaios/Dodaios/blob/main/docs/product/privacy-safety-and-support/safety-and-approvals.md) ·
[隐私与本地数据 →](https://github.com/Dodaios/Dodaios/blob/main/docs/product/privacy-safety-and-support/privacy-and-local-data.md)

## 更多安装方式

[一行安装命令](#安装)是最快的方式。无需预先安装任何东西：如果缺少 Python，安装程序会为 Dodaios 单独下载一份私有副本；在 Windows 上 Git 也是如此，不需要管理员权限，也不会询问。随后它会注册桌面启动器并打开应用。再次运行即可更新现有安装。语言、唤醒词和模型都在应用内设置。

**你需要**一个 API 密钥、一个订阅或一个本地模型。使用语音时最好有麦克风。不需要 GPU。

**桌面版下载：** [Dodaios Windows 版（x64）](https://github.com/Dodaios/Dodaios/releases/latest/download/PersonalJarvis-Setup-x64.exe) ·
[Dodaios macOS 版（Apple 芯片）](https://github.com/Dodaios/Dodaios/releases/latest/download/PersonalJarvis-macOS-arm64.dmg) ·
[Dodaios macOS 版（Intel）](https://github.com/Dodaios/Dodaios/releases/latest/download/PersonalJarvis-macOS-x64.dmg) ·
[Dodaios Linux 版（AppImage，x86_64）](https://github.com/Dodaios/Dodaios/releases/latest/download/PersonalJarvis-Linux-x86_64.AppImage)

为了与现有安装保持兼容，下载文件仍保留原来的 `PersonalJarvis-` 文件名。

> **Windows：** SignPath Foundation 开源项目批准后，Windows 安装程序将按照[代码签名政策（Code signing policy）](https://github.com/Dodaios/Dodaios/blob/main/docs/code-signing-policy.md)签名。Free code signing provided by SignPath.io, certificate by SignPath Foundation.

> **macOS：** 磁盘映像尚未经过 Apple 公证，因此首次启动时需要前往
> **系统设置 > 隐私与安全性 > 仍要打开**（macOS 15；在 macOS 14 及更早版本上可以右键点按 > 打开）。
> 上面的一行安装命令不需要这一步。

**服务器：** 运行 `pip install dodaios` 和 `dodaios serve`，然后在浏览器中打开
`http://localhost:47821`。远程使用麦克风需要 HTTPS。
参见[无界面部署指南](https://github.com/Dodaios/Dodaios/blob/main/docs/headless-vps-deployment.md)。
在 Intel macOS 和 Windows ARM64 上手动用 pip/pipx 安装时，还需要配置
[原生软件包索引](https://github.com/Dodaios/Dodaios/blob/main/docs/product/start-here/install-dodaios.md#install-the-isolated-pypi-package)；
安装程序会自动完成这项配置。

## 第一步

1. 在应用中完成简短的设置：语言（可选择“中文”）、唤醒词（或键盘快捷键）以及一个模型。
2. 说出你的唤醒词并提出一个请求——*“和我一起规划一个小项目，问问你需要了解什么。”*
3. 在 **Agentic IDE** 中打开一个项目文件夹，或者创建你的第一个智能体。

## 兼容

- **模型：** OpenAI、Anthropic Claude、Google Gemini 和 Vertex AI、OpenRouter、NVIDIA、Ollama 以及任何兼容 OpenAI 接口的本地服务器，另外还支持你的 Claude Code 和 Codex 订阅。
- **编程智能体：** Claude Code、Codex、OpenCode、Kimi Code、GLM、Grok Build、Antigravity、Cursor CLI 和 DeepSeek Harness。
- **语音：** 语音识别支持本地 Whisper、OpenAI、Gemini、Groq、Deepgram 和 OpenRouter；语音合成支持 Piper（本地）、ElevenLabs、Cartesia、Inworld、Gemini 和 OpenRouter。

## 文档

文档目前为英文。

[快速开始](https://github.com/Dodaios/Dodaios/blob/main/docs/product/start-here/first-run-setup.md) · [应用导览](https://github.com/Dodaios/Dodaios/blob/main/docs/product/start-here/desktop-app-tour.md) · [语音](https://github.com/Dodaios/Dodaios/blob/main/docs/product/everyday-use/voice-conversations.md) · [听写](https://github.com/Dodaios/Dodaios/blob/main/docs/product/everyday-use/dictation.md) · [Agentic IDE](https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/agentic-ide.md) · [智能体](https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/dodaios-agents.md) · [电脑操控](https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/computer-use.md) · [服务商](https://github.com/Dodaios/Dodaios/blob/main/docs/product/personalize-and-connect/providers-and-api-keys.md) · [本地模型](https://github.com/Dodaios/Dodaios/blob/main/docs/product/personalize-and-connect/local-ai-providers.md) · [插件](https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/plugins.md) · [MCP](https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/mcp-connections.md) · [记忆](https://github.com/Dodaios/Dodaios/blob/main/docs/product/knowledge-and-sharing/wiki-and-memory.md) · [CLI](https://github.com/Dodaios/Dodaios/blob/main/docs/dodaios-cli.md) · [服务器](https://github.com/Dodaios/Dodaios/blob/main/docs/headless-vps-deployment.md) · [架构](https://github.com/Dodaios/Dodaios/blob/main/docs/architecture-overview.md) · [故障排查](https://github.com/Dodaios/Dodaios/blob/main/docs/product/privacy-safety-and-support/troubleshooting.md)

## 参与贡献

可以从一个 [good first issue](https://github.com/Dodaios/Dodaios/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22) 开始。如果目前没有，可以选择任何带有 [`help wanted`](https://github.com/Dodaios/Dodaios/issues?q=is%3Aissue+is%3Aopen+label%3A%22help+wanted%22) 或 [`area:docs`](https://github.com/Dodaios/Dodaios/issues?q=is%3Aissue+is%3Aopen+label%3Aarea%3Adocs) 标签的 issue，或者在 [Discussions](https://github.com/Dodaios/Dodaios/discussions) 里提问。[10 分钟完成你的第一次贡献](https://github.com/Dodaios/Dodaios/blob/main/CONTRIBUTING.md#your-first-contribution-in-10-minutes)会一步步带你完成。问题和想法请发到 [Discussions](https://github.com/Dodaios/Dodaios/discussions)，安全问题请参阅 [SECURITY.md](https://github.com/Dodaios/Dodaios/blob/main/SECURITY.md)。

如果 Dodaios 对你有用，**点一个 Star 能帮助更多人发现它。** 赞助者名单见 [SPONSORS.md](https://github.com/Dodaios/Dodaios/blob/main/SPONSORS.md)。
贡献者名单见[英文 README](https://github.com/Dodaios/Dodaios/blob/main/README.md#contribute)。

## 许可证

[Apache 2.0](https://github.com/Dodaios/Dodaios/blob/main/LICENSE)。1.6.0 及更早的版本保留其原来的 MIT 许可证。参见 [NOTICE](https://github.com/Dodaios/Dodaios/blob/main/NOTICE) 和[商标指南](https://github.com/Dodaios/Dodaios/blob/main/TRADEMARK.md)。
