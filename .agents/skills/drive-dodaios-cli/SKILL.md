---
name: drive-dodaios-cli
description: >-
  Use when a terminal agent needs to control a running Dodaios instance: switch
  the brain provider, dispatch or inspect missions, read or write config, search
  the wiki, manage skills, browse outputs. Trigger phrases: "control Dodaios",
  "drive Dodaios from the CLI", "switch Dodaios's brain provider", "dispatch a
  Dodaios mission".
---

# Drive Dodaios from the CLI

`dodaios` (older names: `jarvis`, `jarvisctl`, `jctl`) is an HTTP client for a
**running** Dodaios. Full guide: `docs/dodaios-cli.md`.

- **Auth is automatic** on the same machine. `dodaios system status` says whether
  Dodaios is reachable; if not, start it (`dodaios serve` for headless) instead
  of retrying. For a remote box, tunnel the port to loopback
  (`ssh -L 47821:127.0.0.1:47821 <host>`).
- **Discover:** `dodaios --help`, `dodaios <group> --help`. Every REST route is
  also reachable as `dodaios api <tag> <op>`.
- **Read with `--json`** placed before the group (`dodaios --json missions list`)
  and parse that, not the table.
- **`--dry-run`** prints the exact request and sends nothing.
- **Destructive commands** (any `DELETE`, `config set`, `missions dispatch`,
  `telephony outbound`) refuse without `--yes`. Add it only when you mean it.
- **Never pass a secret as an argument**; `auth login` reads it from a hidden
  prompt or stdin (`--key -`).

```bash
dodaios brain switch openai
dodaios --json config get brain.primary
dodaios missions dispatch "summarize today's PRs" --yes
dodaios --json wiki recall "insurance policy"
```
