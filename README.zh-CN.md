<div align="center">

<a href="https://dodaios.ai">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/brand/dodaios-logo-on-dark.svg" />
    <img src="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/brand/dodaios-logo-on-light.svg" alt="Dodaios" width="112" />
  </picture>
</a>

<h1>Dodaios</h1>

<!-- the hook, translated (English word for word in README.md; docs/rename/repo-metadata-proposal.md) -->
<p><b>替你调度编程智能体的开源 Jarvis。</b></p>

<p>
  用消息或直接说出你想要什么。Dodaios 给 Claude Code、Codex 等九个编程智能体写好任务说明，<br />
  检查它们的成果，然后带着简短的回答和完整的报告回来。
</p>

<p>
  <a href="https://github.com/Dodaios/Dodaios/releases/latest"><img src="https://img.shields.io/github/v/release/Dodaios/Dodaios?label=release&amp;labelColor=0A0A0A&amp;color=FAFAFA" alt="最新版本" /></a>
  <a href="https://github.com/Dodaios/Dodaios/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache_2.0-FAFAFA?labelColor=0A0A0A" alt="许可证：Apache 2.0" /></a>
  <a href="https://github.com/Dodaios/Dodaios/stargazers"><img src="https://img.shields.io/github/stars/Dodaios/Dodaios?labelColor=0A0A0A&amp;color=FAFAFA&amp;logo=github" alt="GitHub stars" /></a>
  <a href="https://discord.gg/x7USduHxbc"><img src="https://img.shields.io/badge/discord-join-FAFAFA?labelColor=0A0A0A&amp;logo=discord&amp;logoColor=white" alt="Discord" /></a>
</p>

<p>
  <a href="#安装">安装</a> ·
  <a href="#可以对它说的三句话">示例</a> ·
  <a href="#它如何工作">工作方式</a> ·
  <a href="#文档">文档</a> ·
  <a href="https://dodaios.ai">官网</a> ·
  <a href="https://discord.gg/x7USduHxbc">Discord</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.md">English</a>
</p>

</div>

<p align="center">
  <a href="https://github.com/Dodaios/Dodaios/blob/main/assets/demo/readme/dodaios-demo.mp4">
    <img src="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/demo/readme/dodaios-demo.gif" alt="一段 30 秒的 Dodaios 工作录屏，工作区里已有之前的对话和线程。用户在对话中输入一个请求：审阅 acme-notes 里新的 PR，每个 PR 派一个 Sonnet 智能体，并写一份报告。Dodaios 回答说它会列出这些拉取请求，随后最先启动的编程智能体出现在对话旁边的“Recent activity”里。点击其中一个，就在 Agentic IDE 里打开它的线程；项目 acme-notes 下为每个拉取请求列出一个线程，智能体工作时线程旁有转动的标记。再把两个线程并排打开，于是能同时看到三个智能体在工作：Dodaios 写的任务说明、阅读 diff 并运行测试的智能体，然后是它们完成的审阅。回到对话，Dodaios 发出一张报告卡片和两句话的回答：五个拉取请求中三个可以合并，两个需要先修改。最后打开并滚动这份报告：摘要、关键数字，以及给每个拉取请求一个结论的表格" width="100%" />
  </a>
</p>

<p align="center">
  <sub>真实应用的录屏，剪自一段 2 分 18 秒的录制：等待模型的时间被剪掉，其余部分加快五分之一。Dodaios 使用 Claude Opus 5.5，并通过已登录的 Claude Code 启动五个 Claude Sonnet 5.5 智能体。拉取请求、审阅和报告都是真实的。<a href="https://github.com/Dodaios/Dodaios/blob/main/assets/demo/readme/dodaios-demo.mp4"><b>以视频形式观看</b></a>（30 秒，每秒 60 帧，无声音）。</sub>
</p>

<p align="center">
  <a href="https://github.com/Dodaios/Dodaios"><img src="https://img.shields.io/github/stars/Dodaios/Dodaios?style=for-the-badge&amp;label=Star%20Dodaios&amp;logo=github&amp;labelColor=0A0A0A&amp;color=FAFAFA" alt="在 GitHub 上给 Dodaios 点 Star" /></a>
  <br />
  <sub>如果 Dodaios 对你有用，请给仓库点一个 Star。其他开发者就是这样找到它的。</sub>
</p>

## 安装

```bash
curl -fsSL https://raw.githubusercontent.com/Dodaios/Dodaios/main/install/install.sh | bash
```

这一行适用于 macOS 和 Linux。在 Windows 上，请在 PowerShell 中运行：

```powershell
irm https://raw.githubusercontent.com/Dodaios/Dodaios/main/install/install.ps1 | iex
```

安装脚本会创建自己的 Python 环境，添加启动器并打开应用。首次启动会问三件事：一个名字（它同时也是唤醒词）、一个模型连接，以及你想用什么方式和它交流。要把编程工作交出去，请至少安装一个编程智能体并登录，例如 Claude Code 或 Codex。

```bash
dodaios            # 桌面应用：窗口、语音和屏幕上的悬浮层
dodaios update     # 安装最新发布的版本
```

<details>
<summary>桌面安装包、pipx 和服务器</summary>

<br />

从最新版本下载适合你系统的安装包：

| Windows | macOS | Linux |
| --- | --- | --- |
| [Dodaios-Setup-x64.exe](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-Setup-x64.exe) | [Apple 芯片](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-macOS-arm64.dmg) · [Intel](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-macOS-x64.dmg) | [AppImage，x86_64](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-Linux-x86_64.AppImage) |

每个版本都在 `installers-SHA256SUMS.txt` 中列出校验和。Windows 安装包目前还没有代码签名，进展见[代码签名政策](https://github.com/Dodaios/Dodaios/blob/main/docs/code-signing-policy.md)。

用 pipx 可以得到体积更小的服务端软件包，不带桌面启动器。在没有屏幕的 Linux 服务器上，安装脚本接受 `--headless`，`dodaios serve` 只启动浏览器界面：

```bash
pipx install dodaios
curl -fsSL https://raw.githubusercontent.com/Dodaios/Dodaios/main/install/install.sh | bash -s -- --headless
dodaios serve      # 仅浏览器界面，适合没有屏幕的服务器
```

它运行在 64 位的 Windows、macOS 和基于 glibc 的 Linux 上，支持 x86-64 和 Arm64。终端安装脚本需要 Python 3.11 到 3.14 和 Git，缺哪个就自动获取哪个。显卡不是必需的。安装不需要任何提供商，得到回答才需要。
[安装指南](https://github.com/Dodaios/Dodaios/blob/main/docs/product/start-here/install-dodaios.md) ·
[平台支持](https://github.com/Dodaios/Dodaios/blob/main/docs/product/reference/platform-support.md) ·
[在服务器上运行](https://github.com/Dodaios/Dodaios/blob/main/docs/headless-vps-deployment.md)

</details>

## 可以对它说的三句话

**“Review the new PRs, one agent per PR, and tell me what to do.”（审阅新的 PR，每个 PR 派一个智能体，然后告诉我该怎么做。）**
Dodaios 查出未合并的拉取请求，给每一个启动一个编程智能体。它阅读它们的审阅，然后告诉你哪些可以合并、哪些要先修。上面的录屏就是这个请求，另外还要了一份报告。

**“Find the invoice from Kestrel in my mail, put its due date in my calendar and tell the team in Slack.”（在邮件里找到 Kestrel 的发票，把到期日记进日历，并在 Slack 里告诉团队。）**
一个请求，三个应用。Gmail、Google Calendar 和 Slack 都在插件目录的 47 项服务之中。在会询问的权限模式下，以你的名义发出的消息要等你同意。

**“Every weekday at 9, run the tests in ledger and tell me if one fails.”（每个工作日 9 点运行 ledger 的测试，有失败就告诉我。）**
带时间的请求会变成一项例行任务。只要 Dodaios 在运行，它就按这个时间表执行，测试失败时你会收到消息。

## 它如何工作

1. **说。** 输入一条消息，或者说出唤醒词然后开口。这是同一场对话，Dodaios 记得你告诉过它的事。
2. **分派。** Dodaios 写好任务说明并开始工作。编程交给你项目里的编程智能体，每个都在 Agentic IDE 里有自己的线程，并排进行。其他工作交给它自己的后台智能体、它的浏览器或你连接的应用。
3. **检查。** 它跟进工作，并在宣布完成之前亲自检查结果：diff、测试、页面。
4. **汇报。** 你在对话里得到简短的回答，完整的内容是一个可以打开的页面，只有需要你的时候它才会提问。

它能独自做多少，由你决定。每个对话都有一个权限模式，从“Bypass permissions”（什么都不问）到“Always ask”（始终询问）。
[安全与审批](https://github.com/Dodaios/Dodaios/blob/main/docs/product/privacy-safety-and-support/safety-and-approvals.md)

## 支持的编程智能体

**Claude Code · Codex · Cursor CLI · OpenCode · Kimi Code · GLM Coding Plan · Grok Build · Antigravity · DeepSeek Harness**

九个编程智能体，各自通过自己的命令行工具运行。由你自己安装并登录，所以它用的是你已经在付费的套餐，以及它真正具备的模型、推理强度和权限模式。一个线程可以在自己的分支上拥有独立的 worktree，团队线程可以让二到八个使用不同模型的智能体共同完成一项任务。
[Agentic IDE](https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/agentic-ide.md) ·
[团队线程](https://github.com/Dodaios/Dodaios/blob/main/docs/agentic-ide-team-threads.md)

Dodaios 自己运行在你选择的模型上：Claude、OpenAI、Google Gemini 或 xAI Grok（用 API 密钥或你已经在付费的套餐），OpenRouter、LiteLLM、Google Vertex AI 或 NVIDIA NIM，或者通过 Ollama 运行的本地模型，不需要账号，也不需要密钥。
[提供商与 API 密钥](https://github.com/Dodaios/Dodaios/blob/main/docs/product/personalize-and-connect/providers-and-api-keys.md)

## 它还能做什么

- **语音。** 说出唤醒词，或者按下通话快捷键，然后开口。听写会把你说的话输入到你正在使用的应用里。[语音](https://github.com/Dodaios/Dodaios/blob/main/docs/product/everyday-use/voice-conversations.md)
- **看得见的记忆。** 关于你和你工作的简短句子，保存在你电脑上的一个文件里。每一条你都可以更正、置顶、导出或让它忘掉。[记忆](https://github.com/Dodaios/Dodaios/blob/main/docs/product/knowledge-and-sharing/wiki-and-memory.md)
- **例行任务和常设任务。** 按时间表、按事件或由 webhook 触发的工作，以及它持续照看的事情：项目的测试、收件箱、服务器。[例行任务](https://github.com/Dodaios/Dodaios/blob/main/docs/routines.md) · [常设任务](https://github.com/Dodaios/Dodaios/blob/main/docs/standing-tasks.md)
- **47 个插件。** GitHub、Slack、Notion、Linear、Gmail、Google Calendar、Home Assistant、Spotify 等，以及任意 MCP 服务器。[插件](https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/plugins.md)
- **节点。** 它制作并保持最新的报告、幻灯片、表格和仪表盘。[节点](https://github.com/Dodaios/Dodaios/blob/main/docs/nodes.md)
- **它自己的浏览器和你的桌面。** 你可以看着它浏览，并随时接手。它也能在桌面应用里使用鼠标和键盘。[浏览器](https://github.com/Dodaios/Dodaios/blob/main/docs/browser-use.md) · [电脑操作](https://github.com/Dodaios/Dodaios/blob/main/docs/product/extend-and-automate/computer-use.md)
- **离开电脑时。** 手机应用、你的私人 Telegram 聊天和 Discord 私信都能继续同一场对话。[手机应用](https://github.com/Dodaios/Dodaios/blob/main/docs/mobile-companion.md)
- **属于你。** 聊天记录、记忆、节点和设置都是你电脑上的文件。没有 Dodaios 账号，也没有付费版。[隐私与本地数据](https://github.com/Dodaios/Dodaios/blob/main/docs/product/privacy-safety-and-support/privacy-and-local-data.md)

[功能导览](https://github.com/Dodaios/Dodaios/blob/main/docs/feature-tour.md)（英文）配图介绍了全部内容：每个部分做什么、一次工具调用在执行前如何被检查，以及哪些功能在哪个系统上可用。

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

Dodaios 是一个独立项目。它所配合使用的产品（例如上面提到的编程智能体）归其各自的开发者所有；Dodaios 支持某个工具，并不意味着该工具的开发者支持或认可 Dodaios。

Dodaios 在 2026 年 10 月之前叫 Personal Jarvis。同一个项目，同一个许可证（[为什么改名](https://dodaios.ai/blog/personal-jarvis-is-now-dodaios/)）。

赞助者见 [SPONSORS.md](https://github.com/Dodaios/Dodaios/blob/main/SPONSORS.md)。
