#!/usr/bin/env bash
# Starts a throwaway first-run Dodaios instance for the README recording.
#
#   scripts/readme_demo/demo-instance.sh
#
# Everything it writes lives under DEMO_ROOT (default /tmp/dodaios-demo): its
# own home folder, data folder and config file, on its own port. It never
# touches the app you use. Each start wipes that state, so the app comes up
# with nothing set up, and puts a small sample project into the home folder.
# DEMO_HOME moves that home folder elsewhere (a path that reads well in the
# picture, such as /home/demo); it is wiped at each start too.
#
# Needs a Python environment with Dodaios, ptyprocess (the terminal) and pytest
# (the sample project's tests), and a built frontend bundle (npm run build in
# dodaios/ui/web/frontend). Choose the interpreter with PYTHON.
# The recording talks to a real model through Claude Code, which must be
# installed and signed in. The instance runs with HOME=DEMO_HOME, so on Linux
# pass the login as CLAUDE_CODE_OAUTH_TOKEN (from `claude setup-token`); the
# environment reaches Claude Code unchanged. macOS keeps it in the Keychain.
# Run it as a normal user: as root the app shows an administrator notice.
set -eu

DEMO_ROOT="${DEMO_ROOT:-/tmp/dodaios-demo}"
DEMO_PORT="${DEMO_PORT:-47990}"
PYTHON="${PYTHON:-python}"
REPO="$(cd "$(dirname "$0")/../.." && pwd)"

if [ -z "$DEMO_ROOT" ] || [ "$DEMO_ROOT" = "/" ]; then
  echo "DEMO_ROOT must name a folder of its own" >&2
  exit 2
fi
if [ "$(id -u)" = "0" ]; then
  echo "warning: running as root, the app will show an administrator notice" >&2
fi

DEMO_HOME="${DEMO_HOME:-$DEMO_ROOT/home}"
DEMO_STATE="$DEMO_ROOT/state"
case "$DEMO_HOME" in
  ""|"/"|"${HOME:-/nonexistent}")
    echo "DEMO_HOME must name a folder of its own, not your home folder" >&2
    exit 2
    ;;
esac
PROJECT="$DEMO_HOME/projects/trailhead"

rm -rf "$DEMO_HOME" "$DEMO_STATE"
mkdir -p "$DEMO_STATE/data" "$PROJECT/src" "$PROJECT/tests"

# The config is the example one, with the data folder moved under DEMO_ROOT.
sed "s#^data_dir = \"./data\".*#data_dir = \"$DEMO_STATE/data\"#" \
  "$REPO/dodaios.toml.example" > "$DEMO_STATE/dodaios.toml"

# --- the sample project: a tiny hike planner with four tests -----------------
cat > "$PROJECT/README.md" <<'EOF'
# trailhead

A tiny command-line planner for day hikes: distance, climb and a pace estimate.

    python -m src.trailhead plan --distance 14.5 --climb 820

## Tests

    python -m pytest -q
EOF

cat > "$PROJECT/src/trailhead.py" <<'EOF'
"""Estimate how long a day hike takes."""
from __future__ import annotations

import argparse

FLAT_KMH = 4.5          # walking pace on level ground
CLIMB_M_PER_HOUR = 400  # extra time for every 400 m of ascent


def estimate_hours(distance_km: float, climb_m: float) -> float:
    """Naismith-style estimate: flat time plus time for the climb."""
    if distance_km < 0 or climb_m < 0:
        raise ValueError("distance and climb must not be negative")
    return distance_km / FLAT_KMH + climb_m / CLIMB_M_PER_HOUR


def format_plan(distance_km: float, climb_m: float) -> str:
    hours = estimate_hours(distance_km, climb_m)
    whole, minutes = int(hours), round((hours - int(hours)) * 60)
    return f"{distance_km:g} km, {climb_m:g} m up: about {whole} h {minutes:02d} min"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="trailhead")
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan", help="estimate a hike")
    plan.add_argument("--distance", type=float, required=True, help="kilometres")
    plan.add_argument("--climb", type=float, default=0.0, help="metres of ascent")
    args = parser.parse_args(argv)
    print(format_plan(args.distance, args.climb))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
EOF

cat > "$PROJECT/tests/test_trailhead.py" <<'EOF'
import pytest

from src.trailhead import estimate_hours, format_plan


def test_flat_walk_uses_the_walking_pace():
    assert estimate_hours(9, 0) == pytest.approx(2.0)


def test_climb_adds_time():
    assert estimate_hours(9, 400) == pytest.approx(3.0)


def test_negative_values_are_rejected():
    with pytest.raises(ValueError):
        estimate_hours(-1, 0)


def test_plan_is_readable():
    assert format_plan(14.5, 820) == "14.5 km, 820 m up: about 5 h 16 min"
EOF

: > "$PROJECT/src/__init__.py"
: > "$PROJECT/tests/__init__.py"
printf '__pycache__/\n.pytest_cache/\n' > "$PROJECT/.gitignore"

(
  cd "$PROJECT"
  git init -q -b main
  git -c user.name="Demo" -c user.email="demo@example.com" add -A
  git -c user.name="Demo" -c user.email="demo@example.com" commit -q \
    -m "Estimate hike time from distance and climb, with tests"
)

# --- the instance --------------------------------------------------------------
cd "$DEMO_HOME"
export HOME="$DEMO_HOME"
export JARVIS_DATA_DIR="$DEMO_STATE/data"
export JARVIS_CONFIG="$DEMO_STATE/dodaios.toml"
export PATH="$(dirname "$(command -v "$PYTHON")"):$PATH"

echo "demo instance: http://127.0.0.1:$DEMO_PORT/  (state in $DEMO_ROOT)"
exec "$PYTHON" -m dodaios.ui.web.launcher --headless --no-lock --port "$DEMO_PORT"
