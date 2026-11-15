"""Connect the GitHub plugin of a demo instance, for the README's Assistant clip.

    gh auth token | \
    PYTHON_KEYRING_BACKEND=keyring.backends.fail.Keyring \
    JARVIS_DATA_DIR=/tmp/dodaios-demo/state/data \
    JARVIS_CONFIG=/tmp/dodaios-demo/state/dodaios.toml \
    HOME=/tmp/dodaios-demo/home \
      python scripts/readme_demo/plugins_connect.py --token-stdin

Run it with the demo instance's environment (the paths demo-instance.sh
prints) while the instance is stopped, and start the instance again with
DEMO_KEEP=1: it reads its connections when it starts. The token comes on
standard input, so it is in no command line and in no shell history.

The plugin's own dialog takes a personal access token (``ghp_`` or
``github_pat_``) and refuses the login the GitHub CLI holds (``gho_``), which
is the kind of token the plugin's browser sign-in would have saved. So this
script saves that login the way the sign-in does: it asks GitHub whether the
token is good (the same question the dialog asks) and writes it with the
app's own ``TokenStore``. Nothing else is different: the app then finds the
plugin connected, opens GitHub's hosted MCP server with it and offers its
tools to the assistant.

The token is never printed. It is written only to the instance's own
``credentials.json`` under ``JARVIS_DATA_DIR``: the script stops before it
writes when the credential store of this process is anything else (the
Keychain of the app you use).
"""

from __future__ import annotations

import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

PLUGIN = "github"
WHO_AM_I = "https://api.github.com/user"


def stop(reason: str) -> None:
    print(f"not connected: {reason}", file=sys.stderr)
    raise SystemExit(1)


def token_from_caller() -> str:
    """The token from standard input (``--token-stdin``), GH_TOKEN, or the GitHub CLI."""
    if "--token-stdin" in sys.argv[1:]:
        token = sys.stdin.readline().strip()
    else:
        token = os.environ.get("GH_TOKEN", "").strip()
    if not token:
        try:
            done = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=False)
            token = done.stdout.strip()
        except OSError:
            token = ""
    if not token:
        stop("no token: pass it on standard input (--token-stdin), set GH_TOKEN, or sign the GitHub CLI in")
    return token


def main() -> None:
    data_dir = os.environ.get("JARVIS_DATA_DIR", "").strip()
    if not data_dir or not Path(data_dir).is_dir():
        stop("JARVIS_DATA_DIR must name the demo instance's data folder")
    if os.environ.get("PYTHON_KEYRING_BACKEND") != "keyring.backends.fail.Keyring":
        stop("PYTHON_KEYRING_BACKEND must be keyring.backends.fail.Keyring, as demo-instance.sh sets it")

    from dodaios.core import config
    from dodaios.marketplace.token_store import Tokens, TokenStore

    if config.credential_store_backend() != "file":
        stop("this process would write to the computer's own credential store")
    target = (config._resolve_writable_data_dir() / "credentials.json").resolve()
    if Path(data_dir).resolve() not in target.parents:
        stop(f"the credential file {target} is not under JARVIS_DATA_DIR")

    token = token_from_caller()
    request = urllib.request.Request(
        WHO_AM_I,
        headers={"Authorization": f"Bearer {token}", "User-Agent": "dodaios-readme-demo"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as answer:  # noqa: S310 - a fixed https address
            if answer.status != 200:
                stop(f"GitHub answered HTTP {answer.status}")
    except urllib.error.HTTPError as exc:
        stop(f"GitHub rejected the token (HTTP {exc.code})")
    except urllib.error.URLError as exc:
        stop(f"GitHub could not be reached ({type(exc.reason).__name__})")

    store = TokenStore()
    store.save(PLUGIN, Tokens(access=token))
    kept = store.load(PLUGIN)
    if kept is None or kept.access != token:
        stop("the token did not read back from the instance's store")
    if config.credential_store_backend() != "file":
        stop("the credential store changed while saving")
    print(f"{PLUGIN} connected: token kept in {target}")


if __name__ == "__main__":
    main()
