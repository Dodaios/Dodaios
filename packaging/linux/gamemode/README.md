# GameMode hooks: park Dodaios while a game runs

`dodaios-game-control` stops `dodaios.service` when Feral GameMode starts a
game and starts it again 120 s after the last game ends.

## Wiring

`~/.config/gamemode.ini`:

```ini
[custom]
start=/home/<user>/.local/bin/dodaios-game-start
end=/home/<user>/.local/bin/dodaios-game-end
script_timeout=10
```

`dodaios-game-start` and `dodaios-game-end` are two-line wrappers:
`exec ~/.local/bin/dodaios-game-control start` (or `end`). The `resume` action
runs from `dodaios-game-resume.service`, which the user timer
`dodaios-game-resume.timer` (`OnActiveSec=120s`) triggers.

## Behaviour

- `start`: when the service is active, it records that the service should come
  back, then requests the stop **without waiting** (`--no-block`). GameMode
  kills a hook after `script_timeout`, and a full stop can take the unit's
  `TimeoutStopSec`.
- `end`: (re)arms the 120 s resume timer when a service was parked.
- `resume`: does nothing while GameMode still reports a game or cannot be
  queried. Otherwise it waits up to 60 s for a stop still in progress, then
  starts the service.
- Every action logs to `~/gamemode-dodaios.log`.

## Install and roll back

```bash
cp ~/.local/bin/dodaios-game-control ~/.local/bin/dodaios-game-control.bak
install -m 0755 packaging/linux/gamemode/dodaios-game-control ~/.local/bin/dodaios-game-control
# roll back:
mv ~/.local/bin/dodaios-game-control.bak ~/.local/bin/dodaios-game-control
```

Test without a game: `gamemoderun sleep 20`, then read `~/gamemode-dodaios.log`.
