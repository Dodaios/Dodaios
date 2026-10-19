---
name: drive-dodaios-cli
description: >-
  Control a running Dodaios from a terminal agent with the `jarvis` CLI: brain
  provider, missions, config, wiki, skills, outputs. Trigger phrases: "control
  Dodaios", "drive Dodaios from the CLI", "switch Dodaios's brain provider",
  "dispatch a Dodaios mission".
---

- `jarvis` (aliases `jarvisctl`, `jctl`) speaks HTTP to a running instance; on the same machine auth is automatic. `jarvis system status` checks reachability; if nothing runs, `jarvis serve` starts a headless one.
- Remote host: `ssh -L 47821:127.0.0.1:47821 <host>`, or per call `--url http://127.0.0.1:47821 --key "$KEY"`.
- `--json` goes before the group (`jarvis --json missions list`); parse that, not the table.
- `--dry-run` prints the request and sends nothing. Destructive commands (any DELETE, `config set`, `missions dispatch`, `telephony outbound`) refuse without `--yes`.
- Every mounted REST route is also `jarvis api <tag> <op>`; discover with `--help` at any level.
- Never pass a secret as an argument; `--key -` reads it from stdin.
- Examples: `jarvis brain switch openai`, `jarvis --json config get brain.primary`, `jarvis missions dispatch "<task>" --yes`, `jarvis --json wiki recall "<query>"`.
