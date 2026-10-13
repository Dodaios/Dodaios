# Validator parity — the upload endpoint vs. the registry CI

**Status:** FINDINGS — measured 2026-08-14 ·
**Authority:** `scripts/validate.py` in `PersonalJarvis/marketplace` ·
**Compared against:** `functions/_lib/validate.ts` in the storefront ·
**Related:** [github-signin-implementation.md](github-signin-implementation.md) §4

## Why this file exists

The submit endpoint validates a submission, then opens a pull request that
CI validates again. When the endpoint is *stricter*, an author sees a clear
field error and fixes it — no harm. When the endpoint is *looser*, the
author gets `201 {prUrl}` and a success message, and the pull request then
fails CI and sits open forever. Nobody is watching that pull request: the
author thinks they published, and the maintainer sees a queue of red
strangers.

So the direction of a divergence decides whether it matters. Everything
below is a case where the endpoint accepts what CI rejects.

This is **not** a security hole. `validate.ts` says so itself, correctly:
CI remains the final authority and nothing bad merges. It is a usability
hole that produces orphaned pull requests — with one partial exception,
noted at the end.

## Divergences that produce an orphaned pull request

| # | Rule CI enforces | Where | Endpoint today |
|---|---|---|---|
| 1 | Reserved plugin ids (25 names incl. `github`, `slack`, `stripe`) | `RESERVED_PLUGIN_IDS` | not checked |
| 2 | Reserved skill names (32 incl. every `plugin-*`) | `RESERVED_SKILL_NAMES` | not checked |
| 3 | `skill_md` frontmatter must declare the same `name:` as the submission | `validate_skill` | not checked |
| 4 | `plugin_json.$schema` must equal the Agent Plugins v1.0.0 URL exactly | `validate_plugin` | not checked |
| 5 | `plugin_json.name` must equal the submission name | `validate_plugin` | not checked |
| 6 | `plugin_json.description` is **required** (not just length-capped) | `validate_plugin` | length checked only when present |
| 7 | `extensions["io.github.personaljarvis"]` is required (the namespace's earlier name; see "The extension namespace" below) | `validate_plugin` | not checked |
| 8 | `native_tool` is refused (repo-contributed code, not publishable) | `validate_plugin` | not checked |
| 9 | `auth.mode` must be one of the five known modes | `AUTH_MODES` | not checked |
| 10 | `mcp_auth_header_template` needs a `$plugin_…` placeholder and may embed no literal credential | `validate_plugin` | not checked |
| 11 | **No `http://` URL anywhere in the document**, recursively | `reject_http_urls` | only the MCP server url is checked |
| 12 | `headers` on a streamable-http server are refused | `validate_mcp_json` | not checked |
| 13 | Every `env` value must be a `$plugin_…` placeholder | `validate_mcp_json` | not checked |
| 14 | **No** argument may end in `@latest` | `validate_mcp_json` | passes if *any* argument looks pinned, so `npx foo@1.2.0 bar@latest` is accepted |
| 15 | `sse` transport is refused by name | `validate_mcp_json` | accepted — an sse server has a `url`, so it takes the hosted branch |
| 16 | Only `mcpServers` is read | `validate_mcp_json` | also accepts `servers` as an alias, which CI then cannot find |
| 17 | Size is measured on the **final file**: pretty-printed, `publisher` and `publisher_id` included | `validate_file` | measured on compact `JSON.stringify` of the value *before* the publisher fields are added |

Number 17 is the quiet one. Indentation on a nested manifest adds real
weight, so a submission that measures just under 128 KB at the endpoint can
cross the limit once written to disk — and it only bites the largest
submissions, which are also the ones an author least wants to redo.

Numbers 1 and 2 are the likeliest to be hit in practice: `github`,
`notion`, `slack` and `stripe` are exactly the names a newcomer reaches for.

## The one with a security edge

`SECRET_PATTERNS` has nine entries in CI and five at the endpoint. Missing:
`github_pat_…`, Google `AIza…` keys, JWTs, and `sk-` keys containing `-` or
`_`. A submission carrying one of those is accepted, and the App **commits
it to a branch** before CI ever runs. The pull request will fail and never
merge, but the credential is in the repository's history from that moment.

The registry repo is private today, which contains the blast radius. It is
scheduled to be reopened once the login path is green (spec §8 step 5), so
this should close before that happens.

## The extension namespace

The app writes `io.github.dodaios` and reads that namespace and its earlier
name `io.github.personaljarvis` alike
(`jarvis/marketplace/agent_plugins_loader.py`: `EXTENSION_NAMESPACES`,
`extension_of`). The registry does not yet:

| Registry file | Today | Effect of a manifest that uses only `io.github.dodaios` |
|---|---|---|
| `scripts/validate.py` (`EXTENSION_NAMESPACE`, `validate_plugin`) | requires `extensions["io.github.personaljarvis"]` | rule 7 fails: the submission is refused |
| `scripts/expand.py` (`EXTENSION_DIR`) | writes the usage card to `io.github.personaljarvis/usage-card.md` | none for the app: the card travels in the index as `usage_card` text |
| `scripts/build_index.py` (`EXTENSION_DIR`) | reads the usage card from `io.github.personaljarvis/` | a package whose card sits only in `io.github.dodaios/` is indexed without it |
| `scripts/export_rules.py` → `rules.json` | publishes one `extension_namespace` | a consumer of `rules.json` learns only the earlier name |

So that publishing keeps working unchanged, a submission from the app carries
its block under **both** keys, identical
(`PUBLISHED_EXTENSION_NAMESPACES`, applied in `publish.validate_draft`). The
registry validates the earlier key as it always has and ignores the new one;
app versions released before the rename read the earlier key from the index;
this version reads the new one. Because the two keys are validated by
different parties, the app refuses a manifest whose two blocks differ.

### What the registry needs, exactly

In `Dodaios/marketplace`, in one change:

1. `scripts/validate.py`: replace the single `EXTENSION_NAMESPACE` with
   `EXTENSION_NAMESPACES = ("io.github.dodaios", "io.github.personaljarvis")`.
   In `validate_plugin`, take the block from the first namespace present whose
   value is an object, and fail rule 7 only when none is. When both are
   present, require them to be equal (`==` on the parsed objects) and report
   `plugin_json.extensions: the two namespace blocks must be identical`
   otherwise. Every later rule (8, 9, 10) then runs on that one block.
2. `scripts/expand.py`: write the usage card to
   `io.github.dodaios/usage-card.md`. Leave an existing
   `io.github.personaljarvis/usage-card.md` in place for packages already
   expanded; do not rewrite published directories.
3. `scripts/build_index.py`: read the usage card from
   `io.github.dodaios/usage-card.md`, falling back to
   `io.github.personaljarvis/usage-card.md`.
4. `scripts/export_rules.py`: add `extension_namespaces` (the tuple above) to
   `rules.json` and keep `extension_namespace` with its current value, so a
   consumer that reads the old field keeps working.
5. Tests next to the validator: a plugin under each namespace alone passes; a
   plugin under both with equal blocks passes; under both with different
   blocks fails; under neither fails rule 7.
6. Do **not** rewrite the `plugin.json` of any published package, and do not
   change any published name: the index is a wire contract, and app versions
   released before the rename read `io.github.personaljarvis` from it.

Once that is live, the app can stop sending the copy by setting
`PUBLISHED_EXTENSION_NAMESPACES` to the current namespace only. From then on
a newly published plugin is no longer installable by an app version released
before the rename, which is the point at which that support ends; nothing
else depends on the copy.

## The fix that stops it recurring

`rules.json` is now generated from `validate.py` and published next to the
feed:

```
https://dodaios.github.io/marketplace/rules.json
```

It carries the data-driven half — limits, patterns, reserved names, the
launcher and auth allowlists, all nine secret patterns, the plugin schema
URL — with patterns written so Python `re` and ECMAScript both accept them
verbatim. The registry's validate workflow fails if the file drifts from
the validator, so it cannot go stale unnoticed.

Reading that file closes 1, 2, 4, 9 and the secret-pattern gap outright,
and gives 3, 5–8, 10–16 their constants. Those remaining ones are logic
rather than data and still need writing once against the table above.

Number 17 needs no shared data at all: measure the bytes of the exact JSON
the App is about to commit — pretty-printed, publisher fields included —
rather than the payload as received.

## Closed in `jarvis/marketplace/publish.py` (2026-08-15)

| # | Fix |
|---|---|
| 14 | `_validate_mcp` now rejects an `@latest`-suffixed stdio arg on its own, even when a different arg in the same command looks pinned. Previously `npx foo@1.2.0 bar@latest` passed because the check only asked "does *any* arg look pinned". |
| 16 | `_validate_mcp` reads only `mcpServers`; the undocumented `servers` alias (which CI has never recognized) is no longer accepted. |

Numbers 1–13 and 15 were left open: closing them well requires either data
this desktop app cannot fetch locally (`RESERVED_PLUGIN_IDS` /
`RESERVED_SKILL_NAMES` — see `rules.json` above, not yet consumed here) or a
change to the `mcp.json` shape this app's Publish form accepts. See
"the mcp.json `type` field gap" below — several of the remaining rows (9,
11 partial, 12, 13, 15, and would-be row 16's structural cousin) are
enforced correctly by `agent_plugins_loader.convert_package`, but that
function REQUIRES a `type: "streamable-http" | "stdio" | "sse"` key per
server (`docs/marketplace/agent-plugins-standard.md` line 21) that neither
`publish.py`'s `_validate_mcp` nor its own tests ever populate — the two
would need to agree on the mcp.json shape before delegation is safe. That is
a form/format decision, not a mechanical fix; flagged for the maintainer in
`status-checklist.md` §4 rather than guessed at here.

## A third comparison axis: this app's own local check vs. its own installer

The rows above are all "the storefront endpoint vs. registry CI". The
desktop app's in-app Publish tab (`publish.py::validate_draft`) is a THIRD
copy of similar rules, one hop earlier — and it had drifted from
`agent_plugins_loader.py`, the authority this same app uses at install time
(`community_install.install_community_skill`,
`bundled_skills.write_bundled_skills`). The failure mode is the same shape
as the table above, just one step earlier in the pipeline: a submission
passes the in-app "Check" and gets a 201, and only fails once someone
(possibly the very same publisher) tries to install it.

Found and closed 2026-08-15, by making `_validate_bundled_skills` and the
`kind: "skill"` branch of `validate_draft` call
`agent_plugins_loader.validate_bundled_skills` directly instead of
re-implementing a subset of it:

| Divergence | Where | Risk before the fix |
|---|---|---|
| Frontmatter `name`/`description` keys not required | `_frontmatter_keys` + local checks never enforced this | A skill missing either key passed the form, then failed `AgentPluginError` at install — for a STANDALONE skill submission, this could also mean it merges into the live index and is broken for every installer, not just the submitter. |
| "may only share the plugin's own name when it is the sole skill" rule | never implemented client-side (the local function had no `plugin_name` parameter at all) | A bundle could smuggle a skill under the plugin's own name alongside other skills, which the loader would refuse at install, again after merge. |
| `risk_policy` forbidden only checked for a plugin's *bundled* skills, never for a standalone `kind: "skill"` submission | `validate_draft`'s skill branch had no risk_policy check at all | A standalone skill declaring `risk_policy` passed the form outright — the loader still refuses it at install (defense in depth held), but the usability failure is identical to the rows above. |
| Error-accumulation bug: an invalid bundled skill was appended to the returned `skills` list in the same branch that recorded its error | old `_validate_bundled_skills` | Dormant under `validate_draft` (a non-empty `errors` list already forces `return None, errors`), but a latent trap for any future direct caller of the helper. |

All four close by construction now: `_validate_bundled_skills` is a thin
try/except around `agent_plugins_loader.validate_bundled_skills`, so there
is no second rule set left to drift.
