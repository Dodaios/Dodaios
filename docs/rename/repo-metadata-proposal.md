# Repository metadata: one tagline everywhere

The README, the GitHub description, dodaios.ai and the X bio used four different
one-liners in October 2026 ("open-source agent OS for your desktop", "Your AI
assistant, built for the agentic era", "voice assistant that runs on your own
machine", "AI agent super-app"). This page fixes one canonical tagline and the
metadata that carries it. Related: [migration-plan.md](migration-plan.md).

## Canonical tagline

> **One workspace for everything you do with AI.**

The maintainer decided on November 15, 2026 that Dodaios stands for one
workspace in which everything a person does with AI happens.
[positioning.md](../positioning.md) has the whole of it: who it is for, the
five pillars, and the sentence that always follows the tagline:

> Claude Code, Codex, Cursor CLI and six more coding agents side by side, one
> assistant that runs them, voice and dictation, and docs, decks and sheets.
> Open source, on your computer, on the plans and keys you already have.

Use the tagline word for word. The README marks it with a `the promise`
comment.

What it replaced:

- "The open-source superagent for your desktop. One agent that runs all your
  other agents." (November 10, 2026). The assistant that runs the agents is
  now the first of five pillars.
- The README hook of November 14, 2026: "Say what you want. Dodaios runs
  Claude Code, Codex and seven more agents on your own plans, checks their
  work, and tells you what is done." Its coding agents are now the second
  pillar. "Checks their work" holds only for a terminal agent on the same
  computer, whose diff and recorded tests the assistant reads.
- "The open-source Jarvis that runs your coding agents for you." (#1680),
  which named a third party's registered trademark in the first line.

## 1. GitHub description

The tagline, what is in the workspace, and the rename note, 238 characters
(limit 350):

```text
One workspace for everything you do with AI: Claude Code, Codex and seven more coding agents side by side, one assistant that runs them, voice, and docs. Open source, on your computer, on your own plans and keys. Formerly Personal Jarvis.
```

Website field: `https://dodaios.ai`.

PyPI summary (`description` in `pyproject.toml`, shown under the name on
pypi.org; the README is the page's body):

```text
One workspace for everything you do with AI: your coding agents side by side, an assistant that runs them, voice and docs. Open source, on your computer.
```

## 2. Topics (at most 12)

The repository had 20 topics. GitHub search weighs a few precise topics better
than many broad ones, and `personal-jarvis` keeps the old name findable.

| Keep or add | Why |
|---|---|
| `ai-agent` | main category |
| `agent-orchestration` | runs many agents side by side |
| `coding-agent` | core use case |
| `ai-coding-assistant` | how people search for it |
| `claude-code` | the most used agent it runs |
| `voice-assistant` | voice is a main way to use it |
| `voice-coding` | coding by talking |
| `computer-use` | it operates the desktop and browser |
| `desktop-app` | what it is |
| `mcp` | plugin standard it speaks |
| `local-first` | new: runs on your own machine |
| `personal-jarvis` | new: the former name, for people searching for it |

Dropped: `llm`, `personal-assistant`, `privacy`, `self-hosted`,
`speech-recognition`, `speech-to-text`, `text-to-speech`, `voice-control`,
`wake-word`, `dictation`. They are either covered by a kept topic or describe a
part, not the product.

Considered and left out: `jarvis`. The name is a registered trademark of a
third party, which was one reason for the rename, so it should not be used as
a discovery term.

## 3. Website and X

- dodaios.ai: use the tagline as the hero heading and the page title
  ("Dodaios: one workspace for everything you do with AI"), and the sentence
  that follows it as the page description (`<meta name="description">` and the
  Open Graph description).
- X bio of @dodaios: "One workspace for everything you do with AI. Nine
  coding agents side by side, one assistant, voice, docs. Open source, on
  your computer." (136 characters, limit 160). Set the profile link to
  `https://github.com/Dodaios/Dodaios` (it still pointed to the old repository
  on 2026-10-26).

## Applying it

GitHub description and topics:

```bash
gh repo edit Dodaios/Dodaios --description "<description above>" --homepage https://dodaios.ai
gh api -X PUT repos/Dodaios/Dodaios/topics -f "names[]=ai-agent" ...
```

The website lives in its own repository, and the X bio is changed in the X
settings.
