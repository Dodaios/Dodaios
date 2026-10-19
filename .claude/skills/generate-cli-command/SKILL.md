---
name: generate-cli-command
description: >-
  Definition of done for a new or changed REST route in
  dodaios/ui/web/*_routes.py: make it reachable from the `jarvis` CLI. Use
  before committing route changes, or for "generate a CLI command" / "make
  this endpoint CLI-reachable".
---

1. `python scripts/ci/check_cli_coverage.py`: an unmounted router fails; mount it with `app.include_router(...)` in `dodaios/ui/web/server.py`.
2. Every route needs a router tag (becomes `jarvis api <tag>`), a function name that reads as the command (it becomes the operationId) and a one-line docstring (becomes `--help`). Destructive routes declare `openapi_extra={"x-jarvis-dangerous": True}` (`scripts/ci/check_danger_metadata.py`).
3. High-traffic routes also get a curated command in `dodaios/cli_ctl/commands/<domain>.py` (model: `missions.py`): register it with `app.add_typer` in `dodaios/cli_ctl/__main__.py`, add a new group name to `RESERVED_CONTROL_NAMES` in `dodaios/cli_ctl/reserved.py`, call `invoke.run(...)` with `dangerous=True` for destructive routes, and read secrets from a hidden prompt or stdin. Test with the `capture_api` fixture in `tests/unit/cli_ctl/test_commands_<domain>.py`.
4. `python scripts/ci/gen_cli_reference.py` regenerates `docs/jarvis-cli-reference.md`; commit it with the route.
