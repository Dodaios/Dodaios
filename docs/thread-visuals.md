# Visuals in a coding thread

A coding CLI is built for a terminal, where nothing can be drawn: it explains
a flow in words, saves a chart and names the file. A thread of the Agentic IDE
draws what an answer shows, as a figure in the conversation, for every coding
agent (Claude Code, Codex, Antigravity, Grok Build, OpenCode, Kimi, Cursor and
the external runtimes). No vendor has to support it: the agent writes ordinary
Markdown, and the thread draws it.

## What is drawn

| The agent writes | The thread shows |
|------------------|------------------|
| A fenced `mermaid` block | The diagram, in the app's colours. A text that is no diagram stays a code block. |
| A fenced `svg` block (or an unlabelled block that is one complete `<svg>`) | The drawing. |
| A fenced `html` block | The page or fragment, laid out, as tall as its content. |
| `![title](chart.png)`, a picture in the thread's folder or a temp folder | The picture. |
| `![title](report.html)`, a self-contained HTML file in the thread's folder or a temp folder | The page, as a figure with the title as its caption. |
| A picture, a video or a sound at a web address (`![title](https://…/chart.png)`) | A link that opens in the browser. Drawing an answer loads nothing from another host. |

A figure takes the height of what is in it, up to 640 px; a taller one scrolls
inside. Pointing at a figure shows its tools: the source, a copy button and a
full view. While a block is still being written its place is held, so no
half-drawn markup passes by.

A page is shown only for image syntax (`![…](…)`), the explicit "show this". A
plain link to an HTML file, a file name in the text and a tool result never
turn into a page: a web project names its own pages all the time.

## Colours

A visual can name the chat's colours instead of fixing its own: `var(--fg)`,
`var(--muted)`, `var(--line)`, `var(--surface)`, `var(--accent)`, `var(--ok)`,
`var(--warn)`, `var(--bad)`. Such a visual (or one that brings a light and a
dark look of its own, by `prefers-color-scheme` or `[data-theme]`) is drawn
straight on the conversation's surface in the current palette, including a
design the person made. Any other visual expects a white page and gets one, in
both palettes, so dark text on no background stays readable.

## What may run

Every visual is drawn in a sandboxed frame with an opaque origin: it cannot
reach the app's storage or API. A Content-Security-Policy, placed in front of
everything the author wrote, blocks every fetch. The visual's own scripts do
not run. The one script the policy allows carries a nonce made for that frame
and reports the content's height, so the figure fits.

A page with scripts says so in its foot and offers **Run scripts**. A running
script can navigate its own frame to a web address, so running is the reader's
choice and never the default (issue #346).

## Which files

The chat stores a shown file when the answer arrives (`chat-media-…` in the
run archive), so the figure stays as it was when the agent's file changes or
is deleted. Allowed places:

- the thread's folder, as for every chat;
- for coding threads also the computer's temp folders (`tempfile.gettempdir()`
  and `/tmp`), so an agent that only wants to show a chart does not put it
  into the person's repository. Only an explicit link reaches there; a file
  merely named in the text is looked for in the thread's folder only, and a
  link that resolves outside (a symlink) is refused.

A page larger than 2 MB is not shown. A file anywhere else stays a link that
opens beside the conversation on a click.

## What the agents are told

`VISUALS_GUIDE` in `dodaios/agent_chat/thread_visuals.py` says what the thread
draws, when a picture is worth it, the colour names, that scripts wait for a
click and where to save a file. Claude Code (and GLM) read it in their system
prompt; every other CLI gets it in front of the message, next to the question
block (`ASK_PROTOCOL`). Only coding threads are told: the assistant's own
conversation and plain chats keep their prompts.

## Code

| Part | File |
|------|------|
| The guide and its delivery | `dodaios/agent_chat/thread_visuals.py`, `dodaios/agent_chat/runner_cli.py` |
| Storing shown files, temp folders, pages | `dodaios/agent_chat/media.py`, `dodaios/agent_chat/service.py` |
| The figure, the frame and its policy | `dodaios/ui/web/frontend/src/components/outputs/RenderedFence.tsx` |
| Diagrams | `components/outputs/MermaidFence.tsx`, `lib/mermaidRender.ts` |
| A stored page | `components/outputs/PagePreview.tsx`, `components/agentchat/MediaPreview.tsx` |
| Chat wiring, the held place while writing | `components/agentchat/ChatMarkdown.tsx`, `lib/visualFence.ts` |

The same figure draws `html`, `svg` and `mermaid` blocks in the assistant's
conversation and in a Markdown file opened in Artifacts. Charts from numbers
are a block of their own: [`chat-charts.md`](chat-charts.md).
