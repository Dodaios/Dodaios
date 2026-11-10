# Community registry — how the marketplace works

**Status:** live since 2026-08-12, store and storefront rebuilt 2026-11-10 ·
**Decisions:** [public-marketplace-analysis.md](public-marketplace-analysis.md) ·
**Packaging:** [agent-plugins-standard.md](agent-plugins-standard.md) ·
**Skills for other agents:** [portable-skills.md](portable-skills.md) ·
**Agents:** [agent-templates.md](agent-templates.md)

Anyone can publish plugins, skills and agent templates for Dodaios.
Besides a pull request, a submission can arrive as an issue — that is how
the app publishes after GitHub sign-in (see agent-templates.md, "Publishing
without a server"). Every submission
that passes automated checks is listed automatically — an open registry in
the ClawHub spirit, with **zero maintainer infrastructure**: GitHub pull
requests are the upload API, Actions is the validation pipeline, and Pages
is the CDN.

## The two repositories

| Repo | Role |
|---|---|
| `Dodaios/Dodaios` (this repo) | In-app half only: fetch the index, browse, one-click install, connect. Never hosts marketplace website code. |
| `Dodaios/marketplace` | The registry: `submissions/`, CI validation, auto-merge gate, ownership ledger (`registry.json`), compiled `index.json` on GitHub Pages, and the storefront at dodaios.ai/marketplace (`scripts/build_site.py`), rendered from that same index on every publish. |

```
submit form ──► PR (one submissions/<name>.json) ──► CI checks ──► auto-merge
                                                                      │
              plugins/<name>/…  skills/<name>/SKILL.md  ◄── bot expansion
                                                                      │
              Pages: index.json + storefront ◄── compile          app fetch
```

## App-side pieces (this repo)

| Piece | Where |
|---|---|
| Manifest → `PluginSpec` converter (the "loader wave") | `dodaios/marketplace/agent_plugins_loader.py` |
| Index fetch + TTL cache (`data/marketplace_index.json`), held parsed in memory, revalidated behind a browse | `dodaios/marketplace/community_source.py` |
| Install/uninstall persistence (`data/plugin_catalog.json`) | `dodaios/marketplace/community_install.py` |
| Usage cards second root (`data/usage_cards/`) | `dodaios/marketplace/usage_cards/loader.py` |
| REST: `GET/POST/DELETE /api/marketplace/community…` | `dodaios/ui/web/marketplace_routes.py` |
| The Marketplace section: store, entry pages | `frontend/src/views/MarketplaceView.tsx`, `frontend/src/views/marketplace/` |
| Publishing window | `frontend/src/components/marketplace/PublishStudio.tsx` |
| Community list inside Plugins + consent dialog | `frontend/src/views/PluginsCommunity.tsx` |
| Community skills in the Skill Finder pool | `dodaios/skills/finder.py` |
| Source URL override / kill switch | `jarvis.toml` → `[marketplace].community_index_url` (empty = off) |

An installed community plugin is a normal catalog entry with
`source: "community"` plus publisher/version provenance — it rides the
existing connect flows, relevance gate, and worker MCP bridge unchanged.
Never fetch the index on the boot critical path; the Plugins view triggers
the TTL-gated refresh.

### The store's API

| Call | What it does |
|---|---|
| `GET /api/marketplace/community` | The index with install state. Answers from the cache at once; an expired cache is revalidated behind the response and the status says `revalidating`. |
| `POST /api/marketplace/community/refresh` | Fetches the index now, whatever the cache says. |
| `GET /api/marketplace/community/{name}/contents` | The published files of a plugin, a skill or an agent, read out of the feed. |
| `POST /api/marketplace/community/install/{name}` | Installs by name; the app resolves the kind. Always asks the registry first when the cache is older than the TTL. |
| `DELETE /api/marketplace/community/install/{name}` | Removes an installed plugin or skill by name. An agent is removed in Agents. |

## Trust model (no human review — these carry the weight)

1. **Registry CI** (`scripts/validate.py` there): naming rules + reserved
   built-in names, https-only URLs, stdio launcher allowlist
   (`npx`/`uvx`/`docker`), `$plugin_…` placeholders only (no literal
   credentials anywhere), size limits, secret-pattern scan.
   The launcher allowlist covers its ARGUMENTS too, and has to: each of the
   three launchers has options that run anything at all (`npx -c`, `uvx
   --with`, `docker -v/--privileged`), so allowing only the name would allow
   everything. The package a launcher fetches must be a pinned name from its
   own registry — never a git ref, URL or path, all of which name code that
   changes after review — and env keys may not name the machinery that starts
   the server (`PATH`, `LD_PRELOAD`, …). The data half of these rules is
   published in `rules.json` so the other two layers read the values rather
   than retyping them.
2. **Ownership**: first merged submission claims the name in
   `registry.json`; updates auto-merge only from the same GitHub account
   and must increase the version. The auto-merge gate runs trusted
   base-branch code and never executes PR content.
3. **Client re-enforcement**: `agent_plugins_loader.py` re-applies every CI
   rule at install time, so a poisoned index cannot smuggle what CI would
   have rejected. Keep the two rule sets in sync.
4. **The entry page** (app and storefront): shows verbatim the MCP URL
   (where requests and the token go) or the stdio argv (what runs locally),
   and every published file, next to the install button. Nothing installs
   from a list row, and every page says the entry was not reviewed.
5. **Environment isolation**: a connected community plugin's stdio process
   starts WITHOUT the app's environment (`dodaios/mcp/env_isolation.py`) — it
   gets what a process needs to run and reach the network, plus its own
   token. A child process otherwise inherits every exported credential on the
   machine, which is one `os.environ` read away from code the user only ever
   saw in a dialog. Does not reach the delegated worker path, where the
   claude CLI starts the server itself.
6. Existing blast-radius limits apply unchanged: per-plugin connect
   isolation, per-turn relevance gate, `ToolExecutor` as the single
   execution path, skill Draft/Validated lifecycle.

Delisting a malicious entry = revert its submission in the registry repo;
the index redeploys in minutes. Installed copies are removed by the user
(Marketplace → the entry → Remove, or `dodaios marketplace remove <name>`).

## Feed contract

`https://dodaios.github.io/marketplace/index.json` — shape mirrored
by `CommunityIndex` in `community_source.py` (tolerant models: unknown
fields never break older apps). Plugins embed their Agent Plugins v1.0.0
manifests verbatim; skills carry a `raw_url` the existing skill-catalog
install downloads.
