# What you upload — the two shapes

**For authors.** This is the reference the publish form, the CLI scaffold,
and the registry README all point at. The packaging policy is
[agent-plugins-standard.md](agent-plugins-standard.md); how a submission
travels is [community-registry.md](community-registry.md).

You publish one of two things. Pick by what you have, not by what sounds
bigger:

| | A **skill** | A **plugin** |
|---|---|---|
| What it is | Instructions for the model | A connection to a service, optionally with instructions |
| What it is made of | One Markdown file | A directory: manifest, MCP server, skills |
| Needs an account or token? | No | Usually yes |
| Runs code? | No | The MCP server does, on its own host or as a pinned launcher |

---

## A skill — one file

```
todo-triage/
└── SKILL.md
```

That is the whole thing. `SKILL.md` is Markdown with a YAML frontmatter
header on top:

```markdown
---
schema_version: "1"
name: todo-triage
description: Sort an inbox of tasks into today, this week, and later.
when_to_use: Use when the user asks what to work on next, or to tidy a task list.
category: productivity
---

Group open tasks by due date before answering. Say the count for each
group, then name at most three tasks in "today"...
```

`name` must match the directory name, and it is the name the store lists.
`description` and `when_to_use` are what the model reads to decide whether
the skill applies — write them for a reader who has never seen your work.

---

## A plugin — a directory

```
todo-fox/
├── plugin.json                  ← required: identity + the Jarvis block
├── mcp.json                     ← the server your plugin talks to
├── skills/                      ← optional: instructions that ship with it
│   ├── todo-triage/
│   │   └── SKILL.md
│   └── todo-weekly-review/
│       └── SKILL.md
├── io.github.dodaios/           ← everything specific to this client
│   └── usage-card.md
└── LICENSE
```

Only `plugin.json` is required by the standard. In practice a marketplace
plugin has `mcp.json` too, because that is what gives it tools; `skills/`
is what makes it *good* — the tools plus the instructions for using them
well, in one install.

**`plugin.json`** — the identity. Everything Dodaios-specific sits inside the
`io.github.dodaios` namespace, which every other client ignores:

```json
{
  "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
  "name": "todo-fox",
  "description": "Tasks and reminders from TodoFox",
  "version": "1.2.0",
  "license": "MIT",
  "extensions": {
    "io.github.dodaios": {
      "display_name": "TodoFox",
      "category": "Lists & Tasks",
      "logo_slug": "todofox",
      "auth": {
        "mode": "hosted_mcp_oauth_dcr",
        "discovery_url": "https://todofox.example/.well-known/oauth-authorization-server",
        "mcp_url": "https://mcp.todofox.example/mcp",
        "refresh_supported": true
      }
    }
  }
}
```

The namespace was called `io.github.personaljarvis` before the product was
renamed. A package written with it stays valid as it is: the app reads the
block under either key and the usage card from either directory, and a plugin
is the same plugin whichever one it uses, because its identity is its `name`.
Three rules keep the two in step:

- Publishing from the app (the Publish tab) sends the block under **both**
  keys, identical. The registry's validator and app versions released before
  the rename read only the earlier key, so a submission without it would be
  refused there (see [validator-parity.md](validator-parity.md), "The
  extension namespace").
- A pull request opened against the registry by hand needs the same: until
  the registry accepts `io.github.dodaios` on its own, keep the block under
  `io.github.personaljarvis` as well.
- A manifest that carries both keys must carry the same block under each.
  Two blocks that differ are refused at install, never merged.

**`mcp.json`** — exactly one server, either hosted over HTTPS:

```json
{
  "$schema": "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json",
  "mcpServers": {
    "todo-fox": {
      "type": "streamable-http",
      "url": "https://mcp.todofox.example/mcp"
    }
  }
}
```

…or launched locally, from `npx` / `uvx` / `docker` only, at a pinned
version, with tokens as placeholders and never as literals:

```json
{
  "mcpServers": {
    "todo-fox": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@todofox/mcp-server@1.2.0"],
      "env": { "TODOFOX_TOKEN": "$plugin_todo-fox_access_token" }
    }
  }
}
```

**`io.github.dodaios/usage-card.md`** — the words that decide *when*
your plugin is offered. Without it, Dodaios only reaches for the plugin when
a turn names it outright:

```markdown
---
keywords: todo, task, reminder, due date, checklist, todofox
---
Use the TodoFox tools when the user asks what is due, wants to add or
complete a task, or asks to plan a day. Prefer reading over writing unless
the user clearly asks to change something.
```

---

## Naming, versioning, ownership

- **Names** are 1–64 characters, lowercase `a-z 0-9 - .` only, starting and
  ending alphanumeric, no `--` or `..`. **No underscores** — `todo_fox` is
  invalid, `todo-fox` is right.
- **Versions** are SemVer and must increase on every update.
- The first accepted submission of a name **claims it**. Updates are
  accepted only from the same GitHub account.

## What is not accepted

| | Why |
|---|---|
| `scripts/` inside a skill | Executable code from an unreviewed author. Instructions and reference text only. |
| A skill that sets `risk_policy` | It decides which tools run without asking you. The built-in default applies instead. |
| `plugin.json` binding a `native_tool` | Native tools are Python inside the app; that tier is contributed to the main repo. |
| Plain `http://` anywhere | Your users' tokens travel over these URLs. |
| A stdio launcher other than `npx`/`uvx`/`docker`, or an unpinned version | Anything else is an arbitrary command line on a stranger's machine. |
| A token written into `headers` or `env` | Those files are public. Use a `$plugin_…` placeholder; Dodaios fills it at connect time. |
| A package with no components at all | It would be a card that collects a token and does nothing. |

Limits: 10 skills per package, 64 KB per `SKILL.md`.

## What happens after you upload

```
your directory ──► one submission file ──► automated checks ──► auto-merge
                                                                     │
                       plugins/<name>/… (the real Agent Plugins package)
                                                                     │
                       index.json ──► the store, in the app and on the web
```

Nothing is reviewed by a person. The checks stop credential smuggling,
plaintext endpoints, unpinned code and name hijacking — they cannot judge
whether your service is trustworthy. Every community entry is therefore
badged as unreviewed, and users see your exact MCP URL or launch command
before they install.
