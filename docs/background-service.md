# Background agent service

Routines, chat channels and the self-improvement learning keep running after
the desktop app is closed.

## What the user sees

- Closing the app (the window's X, or **Quit** in the tray) with something to
  keep — an armed routine, a running Telegram / Discord channel, or the
  self-improvement learning the person has not stopped — starts a small
  windowless service. A tray icon ("agents keep running in the
  background") shows it is there, with **Open** and **Stop background
  agents**.
- Opening the app again takes over from the service in a couple of seconds.
  Nothing has to be stopped by hand.
- With nothing to keep, closing the app stops everything, as before.
- The learning is periodic (one round at most every 20 hours, when the person
  has been away for 15 minutes; [self-improvement.md](self-improvement.md)),
  so while it is not stopped the service stays for as long as the computer
  runs. Stopping the loop on the Self-improvement page, or turning **Keep
  agents running after closing** off, ends that. The setting is the general
  rule for every background process, not a switch of the learning.
- **Quit and stop background agents** in the app's tray menu quits without
  the hand-off.
- **Settings → App settings → Keep agents running after closing** turns the
  hand-off off. The same card shows what a quit would keep right now, and
  offers **At login, start only the background agents** (needs "Launch app at
  login"), which starts the service instead of the window after a reboot.

## How it works

The service is the existing headless backend
(`python -m dodaios.ui.web.launcher --background-service`, which implies
`--headless`) with no window, no microphone, no wake word and no overlay
(`DODAIOS_VOICE=0`). It runs the same task scheduler, channel stack, agent
society runtime and Agentic IDE re-attach as a headless install.

Exactly one of desktop app and service runs at a time. Both go through the
single-instance lock (`data/jarvis.lock`):

1. **Hand-off on quit** (`DesktopApp._hand_off_to_background_service` →
   `dodaios.core.background_service.hand_off_on_quit`). On a real quit, if
   `[background] keep_agents_running` is on and `work_from_state` finds an
   armed routine, a run in flight, a started channel or learning (the backend
   has a self-improvement loop, `app.state.self_improvement`, and
   `NightService.learning()` holds: the person has not stopped it and this app
   may write `bench.db`), the desktop spawns the service detached
   (`--after-pid <desktop pid>`). A restart, an update, a
   declined Terms gate or a failed backend skip it. Only the default instance
   hands off; a dev instance stops with its window.
2. **Service boot** (`launcher._prepare_background_service`). It waits for the
   desktop pid to exit, steps aside when a desktop launch is already waiting,
   and takes the lock without evicting anyone, BEFORE it binds the port.
   It writes `user_data_dir()/background/service{suffix}.json` and the usual
   instance sidecar.
3. **Hand-back on launch** (`launcher._take_over_from_background_service` →
   `take_over_from_service`). A desktop launch that finds the service drops
   `handover{suffix}.request`; the service polls that file every 0.5 s,
   lets routine runs already in flight finish and ends a running learning
   round (`launcher._hand_back`, up to 30 s for both together), shuts down and
   releases the lock; the desktop takes it and boots normally. The round is
   halted at once (`NightService.halt`): no model call starts, the call in
   flight is cut (a replay's CLI is stopped, a task-building call cancelled;
   its result is void and never reused), and the round's remaining steps run
   without a model and write its report, as when the person comes back. A
   round that does not end in the 30 s stops with the service: it wrote no
   report and no `last_ms`, every file it wrote is written in whole SQLite
   transactions, and the next round runs again. A service that
   does not let go within 45 s is stopped. The service writes its marker the
   moment it holds the lock, and removes it and the instance sidecar before
   releasing the lock, so a desktop reopened mid-boot always finds it. A file carries the
   request (not HTTP) because it works while the service is still booting
   and needs no credentials.
4. **Self-exit.** The service checks every 5 minutes that it still has work
   and exits after two empty checks. Learning stays work until the person
   stops the loop. Its teardown is capped at 30 s, then the
   process ends hard — an invisible process holding the lock is the one thing
   it must never become.

Log: `<data dir>/jarvis_background.log`, next to `jarvis_desktop.log`.

The desktop app sees what the service did: both run the same backend on the
same data directory, so the rounds, measurements and learned values the
service wrote (`bench.db`, the self-change registry, the parameter files) are
on the Self-improvement page when the app opens again.

## The learning round in the service

A round needs nothing the window gives. The person-away check
(`self_build.code.idle.person_idle`) reads the operating system's input idle
time, which a windowless process of the same login session reads the same way
(`GetLastInputInfo` on Windows, `ioreg` on macOS, the D-Bus, X11 and logind
readings on Linux); Dodaios' own activity stamps start empty in a fresh
process and so leave the decision to the OS reading. Task building asks the
assistant's provider through the backend's event loop, the replays start the
lead's CLI with `NO_WINDOW_CREATIONFLAGS` (no console window flashes up from
the windowless process), and the budget rules are the same as in the app.

## Limits

- Spoken routines (`speak` actions) fail in the service: there is no voice
  without the app. Agent routines and chat channels are unaffected.
- A turn that is running in the desktop at the moment of quitting is
  interrupted, as before; the service starts fresh. A routine run in the
  service that needs longer than 30 s after the app reopens is cut off. The Agentic IDE's coding
  agents are unaffected — they live in the PTY host.
- macOS draws no menu-bar icon for the service (status items need the main
  thread, which the service's event loop owns). Open the app to stop it, or
  turn the setting off.

## Verifying

- Unit: `tests/unit/core/test_background_service.py` (learning as the only
  work starts the service on quit; not when the person stopped the loop, the
  setting is off or the instance is a dev instance; the idle check keeps a
  service with learning; a hand-back during a running round halts it and waits
  for its report, and gives up after the drain time), and
  `tests/unit/rsi/test_night.py` / `test_first_move.py` (a halt cuts the call
  in flight, starts no new call or round, and the round still writes its
  report).
- Live round trip on an isolated dev instance (`DODAIOS_DATA_DIR` and
  `LOCALAPPDATA` pointed at a temp folder, `--port` set): start the service
  with `--after-pid` of a short-lived process, confirm it boots only after
  that process exits, fire an `after_delay` task through `POST /api/tasks`,
  then call `launcher._take_over_from_background_service()` and confirm the
  lock is returned, the service exits with code 0 and the marker is gone.
  Measured 2026-10-01 on Windows 11: hand-back 2.4 s, process gone at 2.4 s
  (in-process spawn) and 11.7 s (detached spawn, 5 s exit-hook flush). Same
  round trip in Docker `python:3.11-slim` (no display, no tray): hand-back
  3.1 s, exit code 0.
