# OpenCode over ACP

Dodaios can answer through the official OpenCode binary instead of a hosted
chat API. The brain provider talks the Agent Client Protocol directly:

1. `initialize`
2. `session/new` (or `session/load` for a saved session)
3. `session/set_config_option` for the picked model and effort, when the
   session offers those options
4. `session/prompt`, streaming every `session/update` back as a brain delta

The exchange is the same one OpenMausBot's `opencode acp` driver makes.

## Characteristics

- No Dodaios API key is read or stored. OpenCode resolves its own providers and
  logins, and its free Zen models work signed out.
- The brain turn runs in a throwaway temporary directory with every permission
  request denied, so a conversational turn cannot read or write user files.
- Both conversational mode and `structured_prompts=True` are supported.

## Configuration

The provider registers as `opencode` in the brain registry, exposes its model
list through the provider card, and is switchable from the brain picker. Model
selection happens per turn through ACP config options, not through a CLI flag.

## Verification

The integration is covered by the brain, ACP seat, and worker unit tests. A
live run against OpenCode 2.2.5 streams `ready` and reports token usage.
