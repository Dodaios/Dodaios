# Repository metadata: one tagline everywhere

The README, the GitHub description, dodaios.ai and the X bio used four different
one-liners in October 2026 ("open-source agent OS for your desktop", "Your AI
assistant, built for the agentic era", "voice assistant that runs on your own
machine", "AI agent super-app"). This page fixes one canonical tagline and the
metadata that carries it. Related: [migration-plan.md](migration-plan.md).

## Canonical tagline

> **Dodaios is an open-source agent OS for your desktop: it runs your coding agents, browser and apps by voice or chat, on your own machine.**

The first half is the definition the maintainer chose on October 13, 2026. The
maintainer settled on the full sentence on October 26, 2026; the second half says
in concrete words what "agent OS" means. Use it word for word. The
README marks it with a `canonical tagline` comment.

## 1. GitHub description

Tagline plus the rename note, 162 characters (limit 350):

```text
Dodaios is an open-source agent OS for your desktop: it runs your coding agents, browser and apps by voice or chat, on your own machine. Formerly Personal Jarvis.
```

Website field: `https://dodaios.ai`.

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

- dodaios.ai: use the tagline as the page description (`<meta name="description">`
  and the Open Graph description). The page title uses its first half:
  "Dodaios — an open-source agent OS for your desktop". The hero heading stays
  as it is.
- X bio of @dodaios: the tagline word for word (136 characters, limit 160). The
  rename note does not fit as well, so it stays out of the bio. Set the profile
  link to `https://github.com/Dodaios/Dodaios` (it still pointed to the old
  repository on 2026-10-26).

## Applying it

GitHub description and topics:

```bash
gh repo edit Dodaios/Dodaios --description "<description above>" --homepage https://dodaios.ai
gh api -X PUT repos/Dodaios/Dodaios/topics -f "names[]=ai-agent" ...
```

The website lives in its own repository, and the X bio is changed in the X
settings.
