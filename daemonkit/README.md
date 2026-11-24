# daemonkit

Keep one server process running per user. Start it at login and restart it after a crash, and let any client find it.

This is the shape tmux uses, and the shape most long-running agent tools use. One server owns the work. Clients attach to it: a desktop window, a terminal UI, a CLI or a script. Closing a client only detaches it, so the work keeps running.

daemonkit is the part of that which has nothing to do with your application:

| Piece | What it does |
|---|---|
| `Daemon.claim()` | Makes this process the one server, or raises `AlreadyRunning`. |
| `Claim.ready(port=…, token=…)` | Tells clients where to reach the server. |
| `Daemon.ensure_running()` | For clients: finds the server, or starts it and waits until it is ready. |
| `Daemon.stop()` | Stops the server and keeps its supervisor from starting it again. |
| `python -m daemonkit.supervise` | Restarts the server after a crash, waiting longer each time. Stands by while another instance runs. |
| `Daemon.install_service()` | Registers with systemd, launchd or the Windows Task Scheduler, so the server starts at login and comes back if the supervisor dies. |

It uses only the Python standard library (3.11+) and runs on Windows, macOS and Linux. It needs no administrator rights.

## Use it

```python
import sys
from daemonkit import Daemon, new_token

daemon = Daemon("my-bot", [sys.executable, "-m", "my_bot.server"])
```

In the server process:

```python
def main() -> None:
    with daemon.claim() as claim:        # AlreadyRunning if another server holds the name
        token = new_token()
        port = start_http_server(token)  # your code
        claim.ready(port=port, token=token)
        serve_forever()                  # your code; poll claim.stop_requested() if you like
```

In any client:

```python
record = daemon.ensure_running(timeout=30)   # starts it if needed
call(f"http://127.0.0.1:{record.port}", token=record.token)
```

Once, for example from a settings page:

```python
status = daemon.install_service()                 # start at login
status = daemon.install_service(start_at="boot")  # Linux: also without a login
print(status.mechanism, status.installed, status.detail)
```

To stop the server, call `daemon.stop(graceful=lambda record: ask_server_to_quit(record))`. The graceful call is optional. Without it, or if it fails, the server is terminated.

## How it decides things

- **Is it running?** The instance lock answers this. The OS releases it when the process dies, so a crash never leaves a stale "running" state. The record file only says where the server is.
- **Two clients start at once.** A launch lock makes the second one wait and find the first one's server.
- **Crash.** The supervisor starts the server again after 1 s, then 2 s, 4 s and so on up to 60 s. The pause resets once a run has lasted two minutes.
- **The server exits 0, or 78 (`EXIT_CONFIG`).** The supervisor does not restart it. Exit 78 when the server cannot run until its configuration is fixed.
- **The server exits 75 (`EXIT_ALREADY_RUNNING`).** The supervisor waits until the other instance is gone, then takes over.
- **Closing the terminal** that started it has no effect. The server runs in its own session and the supervisor ignores SIGHUP.

## Per platform

| | Linux | macOS | Windows |
|---|---|---|---|
| Service | systemd user unit, `Restart=on-failure` | `~/Library/LaunchAgents` agent, `KeepAlive` after a failure | Task Scheduler logon task, restart on failure |
| No permission for it | reported in `status.detail` | reported | falls back to the per-user `Run` registry value |
| Start without a login | yes, with `loginctl enable-linger` | no | no |
| State and log | `~/.local/state/<name>/` | `~/Library/Application Support/<name>/daemon/` | `%LOCALAPPDATA%\<name>\daemon\` |

There is no Windows service and no macOS LaunchDaemon. Both need administrator rights and run outside the user's session, where the user's keychain or credential store is generally out of reach.

## Rules for your server

- Do not put secrets in `Daemon(env=…)`. That environment travels on the supervisor's command line, and other local users can read command lines. Put the token in the record with `claim.ready(token=…)` instead: the record is readable only by its owner.
- Check the token on every request, with `token_matches(presented, expected)`.
- Listen on loopback (`127.0.0.1`) unless you mean to be reachable from other machines.
- A frozen app (PyInstaller and similar) has no `python -m`. Pass `supervisor_command=[sys.executable, "--supervise"]` and route that flag to `daemonkit.supervise.main()`.

## Take it into your project

You can copy the `daemonkit/` folder into your project as it is. Its imports are relative, so it works under any package name, for example `myapp/vendor/daemonkit`. The supervisor then runs as `python -m myapp.vendor.daemonkit.supervise`.

You can also install only this folder:

```bash
pip install "git+https://github.com/Dodaios/Dodaios#subdirectory=daemonkit"
```

License: MIT (see `LICENSE`).
