<div align="center">

<a href="https://dodaios.ai">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/brand/dodaios-logo-on-dark.svg" />
    <img src="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/brand/dodaios-logo-on-light.svg" alt="Dodaios" width="112" />
  </picture>
</a>

<h1>Dodaios</h1>

<!-- the promise and the definition, translated (English word for word in README.md; docs/positioning.md) -->
<p><b>Your AI-native office. Talk, write, build.</b><br />
你的 AI 原生办公套件。对话、写作、构建。</p>

<p>
  Dodaios 把一切连在一起：一个了解你工作的语音助手，<br />
  用于文档、幻灯片和表格的 Nodes，以及由它替你运行的编程智能体。<br />
  开源，运行在你的桌面上，使用你已经在用的模型。
</p>

<p>
  <a href="https://github.com/Dodaios/Dodaios/releases/latest"><img src="https://img.shields.io/github/v/release/Dodaios/Dodaios?label=release&amp;labelColor=0A0A0A&amp;color=FAFAFA" alt="最新版本" /></a>
  <a href="https://github.com/Dodaios/Dodaios/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache_2.0-FAFAFA?labelColor=0A0A0A" alt="许可证：Apache 2.0" /></a>
  <a href="https://github.com/Dodaios/Dodaios/stargazers"><img src="https://img.shields.io/github/stars/Dodaios/Dodaios?labelColor=0A0A0A&amp;color=FAFAFA&amp;logo=github" alt="GitHub stars" /></a>
  <a href="https://discord.gg/x7USduHxbc"><img src="https://img.shields.io/badge/discord-join-FAFAFA?labelColor=0A0A0A&amp;logo=discord&amp;logoColor=white" alt="Discord" /></a>
</p>

<p>
  <a href="#安装">安装</a> ·
  <a href="#为什么选-dodaios">为什么选 Dodaios</a> ·
  <a href="#你的套餐和密钥">你的套餐</a> ·
  <a href="#文档">文档</a> ·
  <a href="https://dodaios.ai">官网</a> ·
  <a href="https://discord.gg/x7USduHxbc">Discord</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.md">English</a>
</p>

</div>

<p align="center">
  <img src="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/demo/readme/hero.webp" alt="一段 16 秒的 Dodaios 工作录屏。在一段已在使用中的对话里，用户对助手 Nova 输入：Have a Sonnet agent add a --csv flag to ledger's list command and run the tests. Nova 回答说会派一个 Sonnet 5 智能体来做，回答里出现该智能体线程的链接。点一下，线程在 Agentic IDE 中打开：编码智能体修改文件并运行测试，12 个测试全部通过，一张卡片列出它改动的三个文件。回到对话，Nova 报告 ledger list --csv 现在会列出每张发票，它重新跑了测试，12 个全部通过，且没有提交任何内容。" width="100%" />
</p>

<p align="center">
  <sub>真实录屏，每秒 60 帧，按拍摄时的速度播放。等待模型的时间被剪掉。助手 Nova 使用 Claude Opus 5.5，并启动一个使用 Claude Sonnet 5 的 Claude Code 智能体，登录的是 Claude 套餐。代码改动和测试运行都是真实的。<a href="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/demo/readme/dodaios-demo.mp4"><b>下载视频</b></a>（MP4，2 MB）</sub>
</p>

## 为什么选 Dodaios

如果你每天都在用 AI 工作，你的工作多半分散在好几个地方：聊天助手在浏览器标签页里，听写是一个单独的应用，文档又在别处，每个编程智能体还各自运行在一个终端里。它们互相不知道对方做了什么，于是你只能在它们之间复制粘贴，自己盯着进度。

Dodaios 把这一切放进你电脑上的一个应用里，围绕一个替你盯着进度的助手。

- **对话。** 给助手打字，或者说出它的名字直接说话。它会回答，通过插件在你的应用里工作，并记住你告诉它的事。按住一个键，就能在任何其他应用里听写。
- **写作。** 要一份文档、幻灯片、表格或白板，它到手时内容已经填好。每种都有自己的编辑器，你可以手动修改。
- **构建。** 助手把编程工作交给 Claude Code、Codex 和另外七个编程智能体，回答它们的提问，并告诉你结果如何。最多四个并排运行。
- **属于你。** Apache 2.0，没有 Dodaios 账号，没有付费版。Dodaios 不出售模型访问权限：每个智能体都用你已有的套餐或密钥运行。你的聊天、记忆和文档都是你电脑上的文件。

它还能跟你到手机、Telegram 和 Slack 上，并在你不在时运行例行任务。每一部分在“它能做什么”下都有自己的小节。

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

Dodaios 运行在 64 位的 Windows、macOS 和基于 glibc 的 Linux 上。终端安装脚本支持 x86-64 和 Arm64，需要 Python 3.11 到 3.14 和 Git；它会获取缺少的 Python，缺少 Git 时会提出帮你安装。显卡不是必需的。
[安装指南](https://github.com/Dodaios/Dodaios/blob/main/docs/product/start-here/install-dodaios.md) ·
[平台支持](https://github.com/Dodaios/Dodaios/blob/main/docs/product/reference/platform-support.md) ·
[在服务器上运行](https://github.com/Dodaios/Dodaios/blob/main/docs/headless-vps-deployment.md)

</details>

## 它能做什么

### 对话：助手和你的语音

<p align="center">
  <img src="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/demo/readme/assistant.webp" alt="一段 12 秒的录屏。在一段已在使用中的对话里，用户对 Nova 输入：How much did I spend on groceries each month this year? The bank export is in Documents. Nova 说会去找银行导出文件，读取电脑上的文件后回答：1 月到 10 月共在食品杂货上花了 4,571.65 欧元，7 月最多，2 月最少。回答下方，对话里画出一张柱状图 Groceries per month, 2026，每月一根柱子；鼠标沿柱子移动，每根柱子显示金额，最后停在 7 月的 600.7 欧元。" width="100%" />
</p>

你给助手起名字，这个名字也是它的唤醒词（在这些录屏里叫 Nova）。它通过 48 个插件在你的应用里工作，比如 GitHub、Slack、Notion 和 Gmail，其中大多数仍标为“Preview”（预览版）；它也可以通过任何 MCP 服务器工作。它在自己的浏览器里浏览，用鼠标和键盘操作桌面应用，还会记下关于你和你工作的笔记，你可以查看和更正。编程工作它交给编程智能体，回答智能体的提问，并阅读它的报告。

[插件](https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/plugins.md) ·
[浏览器](https://github.com/Dodaios/Dodaios/blob/main/docs/browser-use.md) ·
[电脑操作](https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/computer-use.md) ·
[记忆](https://github.com/Dodaios/Dodaios/blob/main/docs/product/knowledge-and-sharing/wiki-and-memory.md) ·
[例行任务](https://github.com/Dodaios/Dodaios/blob/main/docs/routines.md) ·
[长期任务](https://github.com/Dodaios/Dodaios/blob/main/docs/standing-tasks.md)

<!-- The voice recording (voice.webp) needs a real voice and microphone; it is made
     with scripts/readme_demo/voice_take.py (assets/demo/readme/README.md). -->

说出唤醒词或按下你的通话快捷键，然后说话，助手会开口回答。在任何应用里按住听写键，你说的话就会连同标点一起打在那里。英语、德语、西班牙语和葡萄牙语里的“嗯”“呃”之类会被去掉。唤醒词和听写可以在你的电脑上运行，不需要密钥，也不需要账号。

[语音对话](https://github.com/Dodaios/Dodaios/blob/main/docs/product/everyday-use/voice-conversations.md) ·
[听写](https://github.com/Dodaios/Dodaios/blob/main/docs/product/everyday-use/dictation.md) ·
[唤醒词](https://github.com/Dodaios/Dodaios/blob/main/docs/product/personalize-and-connect/audio-and-wake-word.md)

### 写作：文档、幻灯片、表格和白板

<p align="center">
  <img src="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/demo/readme/nodes.webp" alt="一段 14 秒的录屏：与助手 Nova 的对话。用户输入：Make a four-slide deck on brewing pour-over coffee. 一张幻灯片的卡片进入对话，显示标题页 Brewing great pour-over coffee，Nova 的回答出现在下方。点一下卡片，幻灯片大幅打开。点一下标题，打开幻灯片编辑器，左侧是幻灯片缩略条，右侧是标题的字段。用户选中标题，输入 Pour-over, step by step，缩略条和字段随之变化，编辑器显示 Saved。" width="100%" />
</p>

要一份文档、幻灯片、表格或白板，它到手时内容已经填好。每种都有自己的编辑器，你可以手动修改：在文字里打字，改单元格，拖动方框。在白板上，你和助手在同一块画布上画。所有内容都可以导出为 HTML；装有 Chrome、Edge 等 Chromium 浏览器时，还可以导出为 PDF 或 PNG。

[节点](https://github.com/Dodaios/Dodaios/blob/main/docs/nodes.md)

### 构建：你的编程智能体

<p align="center">
  <img src="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/demo/readme/agents.webp" alt="一段 12 秒的 Dodaios Agentic IDE 录屏。两个编码智能体在两栏中工作；从线程列表中再打开第三个线程放在旁边，于是三个 Claude Code 智能体在两个示例项目的三个小任务上并排工作。中间的智能体修正了增值税的舍入方式，报告 7 个测试全部通过，并列出它修改的两个文件；随后三个都完成了，各自带有修改文件的卡片。最后，一个线程的智能体与模型选择器打开，侧边显示其他编码智能体，以及 Codex 的模型。" width="100%" />
</p>

**Claude Code · Codex · Cursor CLI · OpenCode · Kimi Code · GLM Coding Plan · Grok Build · Antigravity · DeepSeek Harness**

Agentic IDE 会在智能体工作时显示它的工具调用、diff、计划和提问。你可以并排打开最多四个线程，让二到八个智能体组成团队处理同一项任务，或者让一个线程在自己的 worktree 和分支上工作，旁边就是编辑器、Git 客户端和浏览器预览。终端智能体也可以通过 SSH 在你自己的 Linux 服务器上运行，你合上笔记本电脑后它还会继续工作。

[Agentic IDE](https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/agentic-ide.md) ·
[线程](https://github.com/Dodaios/Dodaios/blob/main/docs/agentic-ide-threads.md) ·
[团队线程](https://github.com/Dodaios/Dodaios/blob/main/docs/agentic-ide-team-threads.md)

### 离开电脑时

<!-- The recording of this section is a real conversation through Telegram;
     it goes here once it is filmed (assets/demo/readme/README.md). -->

你和助手的对话会跟着你走，你在路上说过的话，回来时就在桌面端的聊天里。

- **手机应用。** 由你自己的电脑提供的网页应用，通过你的家庭网络或 HTTPS 访问。用配对码配对后，你可以打字、发语音消息，并允许或拒绝正在等你同意的事。
- **Telegram。** 你和自己的 Telegram 机器人之间的私聊，在哪里都能用。文字、语音消息和照片都可以，请求会附带“Allow”和“Deny”按钮。
- **Slack。** 给你自己的 Slack 应用发私信，这个应用用一份现成的清单一键创建。只有你会收到回答。用你的 Slack 登录，助手还能在你的工作区里搜索、阅读和发帖。

[手机应用](https://github.com/Dodaios/Dodaios/blob/main/docs/mobile-companion.md) ·
[Slack 应用](https://github.com/Dodaios/Dodaios/blob/main/docs/slack-channel.md)

<br clear="right" />

## 你的套餐和密钥

Dodaios 不出售模型访问权限，也不会替你登录。它会启动每个编程智能体的官方命令行工具，每一个都由你自己登录。所以这些智能体用的是你已有的东西：

| 你有 | 就能运行 |
| --- | --- |
| 付费的 Claude 套餐（Pro 或更高） | Claude Code |
| ChatGPT 套餐 | Codex |
| Cursor 账号 | Cursor CLI |
| SuperGrok 或 X Premium+ | Grok Build |
| Google 账号（免费套餐有每周限额） | Antigravity |
| 你在 OpenCode 里设置的提供商 | OpenCode |
| Moonshot、Z.ai 或 DeepSeek 的密钥或套餐 | Kimi Code、GLM Coding Plan（对接 Z.ai 的 Claude Code）、DeepSeek Harness |

助手运行在你选择的模型上。Claude、OpenAI、Google Gemini 和 xAI Grok 可以用套餐或 API 密钥连接。OpenRouter、LiteLLM、Google Vertex AI、NVIDIA NIM 和 DeepSeek 用密钥连接。本地模型通过 Ollama 运行，不需要账号，也不需要密钥。你对每项服务的使用都遵循该服务自己的条款。
[提供商与 API 密钥](https://github.com/Dodaios/Dodaios/blob/main/docs/product/personalize-and-connect/providers-and-api-keys.md) ·
[本地模型](https://github.com/Dodaios/Dodaios/blob/main/docs/product/personalize-and-connect/local-ai-providers.md)

## 常见问题

**我的数据会离开我的电脑吗？**
聊天记录、记忆、文档和设置都是运行 Dodaios 的那台电脑上的文件。模型或已连接的服务，会得到它完成请求中自己那一部分所需的内容。登录 Google、Slack 或 Figma 插件，以及之后的每一次令牌刷新，都会经过本项目运行的一个小型令牌服务。Dodaios 不会自行上传它的日志。
[隐私与本地数据](https://github.com/Dodaios/Dodaios/blob/main/docs/product/privacy-safety-and-support/privacy-and-local-data.md)

**它会不经询问就行动吗？**
每个聊天都有一个权限模式。新聊天从“Bypass permissions”（跳过权限确认）开始，在这个模式下什么都不会询问。在会询问的模式下，转账、密码和密钥、永久删除某样东西，以及以你的名义给第一次联系的人发消息，总是要等你同意。
[安全与审批](https://github.com/Dodaios/Dodaios/blob/main/docs/product/privacy-safety-and-support/safety-and-approvals.md)

**要花钱吗？**
不用。没有 Dodaios 账号，也没有付费版。你照常向你的模型提供商付费。

**能在哪些系统上运行？**
Windows、macOS 和 Linux，界面有英语、德语、西班牙语、中文和葡萄牙语版本。目前只有 Windows 11 有记录在案的实机验收。
[平台支持](https://github.com/Dodaios/Dodaios/blob/main/docs/product/reference/platform-support.md)

## 文档

[功能导览](https://github.com/Dodaios/Dodaios/blob/main/docs/feature-tour.md)（英文）在一个页面上配图介绍了每个部分。同样的指南也在应用内的 **Docs** 页面里，并且可以搜索。

- [欢迎使用 Dodaios](https://github.com/Dodaios/Dodaios/blob/main/docs/product/start-here/welcome-to-dodaios.md)：它做什么，不做什么
- [首次运行设置](https://github.com/Dodaios/Dodaios/blob/main/docs/product/start-here/first-run-setup.md)和[你的第一次聊天](https://github.com/Dodaios/Dodaios/blob/main/docs/product/start-here/start-your-first-chat.md)
- [故障排查](https://github.com/Dodaios/Dodaios/blob/main/docs/product/privacy-safety-and-support/troubleshooting.md)
- [配置参考](https://github.com/Dodaios/Dodaios/blob/main/docs/product/reference/configuration-reference.md)和 [CLI 参考](https://github.com/Dodaios/Dodaios/blob/main/docs/dodaios-cli-reference.md)
- [架构概览](https://github.com/Dodaios/Dodaios/blob/main/docs/architecture-overview.md)，写给想改代码的人

## 参与贡献

欢迎修复问题、补充测试、改进无障碍、提交平台报告和完善文档。[贡献指南](https://github.com/Dodaios/Dodaios/blob/main/CONTRIBUTING.md#your-first-contribution-in-10-minutes)能让你在大约十分钟内从 fork 走到一次通过的检查。适合入手的是带有 [good first issue](https://github.com/Dodaios/Dodaios/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22) 和 [help wanted](https://github.com/Dodaios/Dodaios/issues?q=is%3Aissue+is%3Aopen+label%3A%22help+wanted%22) 标签的 issue。问题和想法请到 [Discord](https://discord.gg/x7USduHxbc)。如果 Dodaios 对你有用，给它点一个 [Star](https://github.com/Dodaios/Dodaios/stargazers)，能帮更多人找到它。

感谢每一位在这里交付过成果的人，名单见[英文 README 的贡献者墙](https://github.com/Dodaios/Dodaios/blob/main/README.md#contributing)。

## 许可证

Dodaios 采用 [Apache License 2.0](https://github.com/Dodaios/Dodaios/blob/main/LICENSE) 许可，署名信息见 [NOTICE](https://github.com/Dodaios/Dodaios/blob/main/NOTICE)。名称和标志受[商标政策](https://github.com/Dodaios/Dodaios/blob/main/TRADEMARK.md)约束，不在许可证的授权范围内。

Dodaios 是一个独立项目。它所配合使用的产品（例如上面提到的编程智能体）归其各自的开发者所有。Dodaios 支持某个工具，并不意味着该工具的开发者支持或认可 Dodaios。

Dodaios 在 2026 年 10 月之前叫 Personal Jarvis。同一个项目，同一个许可证（[为什么改名](https://dodaios.ai/blog/personal-jarvis-is-now-dodaios/)）。

赞助者见 [SPONSORS.md](https://github.com/Dodaios/Dodaios/blob/main/SPONSORS.md)。
