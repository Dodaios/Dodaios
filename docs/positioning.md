# Positioning: what Dodaios stands for

Decided by the maintainer on 15 November 2026; the promise was last changed on
16 November 2026 (evening). The README, the website and
every launch text follow this page. What a public text may and may not say is
in [positioning-claims.md](positioning-claims.md).

## Who it is for

People who work with AI all day and already pay more than one AI company.
Most are developers and technical founders. They run coding agents every day
and use a chat assistant, a dictation tool and a documents tool beside them.

They have enough tools. Each company they pay now builds its own app for
everything, around its own models and its own account. So they work in two or
three places, and none knows what happened in the others.

## The promise

> **One voice-driven assistant that directs your models, your coding agents and your computer.**

Use it word for word, and never alone: the definition always follows.

> Dodaios is a locally installed, open-source Python program that runs as a
> desktop app or as a headless server with a browser UI on Windows, macOS and
> Linux. It turns a personal AI assistant into the control center for the work
> you do on your computer.
>
> At its core is a "lead" assistant you can talk to by voice (wake word,
> dictation, real-time spoken conversation and, as an early preview, phone
> calls), by chat or from a paired phone. It isn't tied to one provider and
> works with Claude, OpenAI, Gemini or local Ollama models. It handles tasks
> itself through tools, computer use, plugins, CLIs and MCP servers. Above all,
> it hands work off to coding agents. They run side by side in a built-in
> Agentic IDE as real Claude Code or Codex terminals, on your computer or on
> your own servers over SSH, each with a call sign you can address by name, plus
> Git integration and task splitting. There is also a "society" of persistent,
> named agents that message each other.
>
> Long-running work is covered by memory (about you, the people around you and
> the assistant's own persona), standing tasks, workflows, skills and opt-in
> life admin. The assistant also makes its own outputs, such as documents,
> slides, sheets and dashboards, and can propose and build the skills, routines
> and agents it is missing. A trust layer sets hard limits: outside Bypass
> permissions, moving money, handling credentials, permanent deletion and first
> contact with someone new always need your confirmation. In short, Dodaios is
> a voice-driven, locally running operating system for AI agents that makes one
> assistant the conductor of your models, your coding agents and your own
> computer.

The maintainer wrote the definition himself and settled on it late in the
evening of 16 November 2026. The one-liner is taken from its last sentence. It
presents Dodaios as one connected system: one assistant, reached by voice,
that directs the models, the coding agents and the computer. A few places were
adjusted so that each sentence is true in the code on main: phone calls are a
preview, the coding agents (not the assistant) reach servers over SSH, life
admin is opt-in, the self-building loop makes skills, routines and agents, and
the hard limits do not hold in a chat set to Bypass permissions
([positioning-claims.md](positioning-claims.md)). "Operating system for AI
agents" is a figure of speech for what the app coordinates. Do not use it to
say that Dodaios is an operating system, and do not name another product as
the comparison.

The README is built on it and kept short: the one-liner, the definition, one
recording that shows the definition at work, the install commands, and a few
lines on plans and keys, data, approvals and what is not finished. Everything
else is in `docs/`.

Earlier promises:

- Earlier in the evening of 16 November 2026: "Your AI-native office. Talk,
  write, build.", with the definition "Dodaios brings everything together: a
  voice assistant that knows your work, Nodes for docs, slides and sheets, and
  coding agents it runs for you. Open source, on your desktop, with the models
  you already use." The maintainer replaced it with his own definition, which
  says what the program is before what it holds.
- Until the evening of 16 November 2026: "Talk to one assistant. It runs your
  coding agents for you." It reduced Dodaios to one coding feature.
- Until the morning of 16 November 2026: "One workspace for everything you do
  with AI.", followed by a list of features in one sentence.

The problem it solves, in the reader's own day: the work is spread over a chat
app, a dictation app, a documents tool and a terminal per coding agent; none
of them knows what the others did; so the person copies between them and keeps
track. Dodaios puts it in one app on the computer, around one assistant that
keeps track.

Promise, definition and problem together hold the three things a model
maker's own app does not offer:

1. **Not one maker's.** Nine coding agents and eleven families of model
   providers work in one window.
2. **Yours.** Open source, on your computer, no Dodaios account, on the plans
   and keys you already have.
3. **One assistant, and you can talk to it.** It can look up what every agent
   did.

## The five pillars

Each is something a person would otherwise open another tool for.

| Pillar | What is there today |
| --- | --- |
| **An assistant that does the work** | Named by the person. 48 plugins, any MCP server, its own browser, computer use, a memory you can read, routines. It briefs coding agents and follows their work |
| **Your coding agents, side by side** | Nine agents as chat threads and terminals, four threads side by side, teams of two to eight, an editor and a Git client, terminal agents on your own servers |
| **Your voice, in every app** | A wake word, spoken conversation, dictation into any app. Wake word and dictation can run on the computer with no key |
| **Docs, decks, sheets and whiteboards** | Seven kinds of node, each with its own editor: made from a sentence, edited by hand |
| **With you when you leave the desk** | The same conversation in the phone app, in Telegram and in the person's own Slack app; with the person's Slack sign-in the assistant also reads and posts there |

## How it differs

The tool made for one job is usually better at that job. Dodaios differs in
what it joins, and in whose it is.

- **A model maker's own desktop app** covers much of the same ground with
  that maker's models and account. Dodaios runs that maker's coding agent
  too, next to the agents of other makers.
- **Most tools that run many coding agents** stop at code. Dodaios adds the
  assistant that briefs and follows them, the voice and the documents.
- **An AI code editor** is built around the file you edit. Dodaios is built
  around the work you hand out.
- **A dictation app** types what you say. Here the same voice also reaches
  an assistant that can act on it.
- **A launcher with AI** answers and starts things. Dodaios keeps the work:
  the threads, the documents, the memory.
- **Most assistants in a messenger** have no place to work in. Dodaios is
  the desktop that the messenger chat belongs to.

In November 2026 we knew of no product that joins all four of these:

- dictation into any app
- the coding agents of several makers
- documents that the assistant makes and a person edits
- a chat in a messenger

Each of the four has a strong specialist, and a reader judges each pillar
against it. So say what each part does, and never that it is the best at it.
