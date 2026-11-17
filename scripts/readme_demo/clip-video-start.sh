#!/bin/bash
# Starts a fresh demo instance for the README video (clip-video-*.cjs), from
# this checkout, and stops the one it started before.
#
#   scripts/readme_demo/clip-video-start.sh
#
#   DEMO_ROOT   the instance's folder (default ~/demo-video); deleted first
#   DEMO_PORT   its port (default 48100)
#   PYTHON      the Python with Dodaios installed (default python3)
#
# Claude Code in the Grid's terminals gets a home of its own that skips its
# warning about bypass mode and its LSP plugin offer, and loads none of the
# plugins of the Claude Code session that runs this script (with them, the
# terminals stopped at "MCP servers need authentication"). trailhead gets an
# old build/ folder, which the video deletes for good.
set -e
ROOT="${DEMO_ROOT:-$HOME/demo-video}"
PORT="${DEMO_PORT:-48100}"
H="$ROOT/home/alex"
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
case "$ROOT" in ""|"/"|"$HOME") echo "DEMO_ROOT must be a folder of its own" >&2; exit 2;; esac

pkill -f "dodaios.ui.web.launcher .*--port $PORT" || true
pkill -f "$H/.dodaios-data" || true
pkill -f "$ROOT/state" || true
sleep 3
rm -rf "$ROOT" || { sleep 3; rm -rf "$ROOT"; }
mkdir -p "$ROOT"

cd "$REPO"
DEMO_PORT="$PORT" DEMO_ROOT="$ROOT" DEMO_HOME="$H" IS_SANDBOX=1 PYTHON="${PYTHON:-python3}" \
  nohup env -u CLAUDE_CODE_SYNC_PLUGINS -u CLAUDE_CODE_SYNC_SKILLS \
  scripts/readme_demo/demo-instance.sh > "$ROOT.log" 2>&1 &
for _ in $(seq 60); do [ -d "$H/projects/trailhead" ] && break; sleep 1; done

mkdir -p "$H/.claude"
cat > "$H/.claude/settings.json" <<'JSON'
{ "skipDangerousModePermissionPrompt": true, "theme": "dark" }
JSON
cat > "$H/.claude.json" <<JSON
{ "hasCompletedOnboarding": true, "bypassPermissionsModeAccepted": true, "theme": "dark",
  "lspRecommendationDisabled": true,
  "projects": { "$H/projects/trailhead": { "hasTrustDialogAccepted": true },
                "$H/projects/ledger": { "hasTrustDialogAccepted": true } } }
JSON

# An old build folder in trailhead, for the trust layer's permanent deletion.
B="$H/projects/trailhead/build"
mkdir -p "$B/lib/trailhead"
for f in trailhead-0.3.0-py3-none-any.whl trailhead-0.3.0.tar.gz; do head -c 40000 /dev/urandom > "$B/$f"; done
cp "$H"/projects/trailhead/src/*.py "$B/lib/trailhead/" 2>/dev/null || true
if ! grep -q "^build/" "$H/projects/trailhead/.gitignore" 2>/dev/null; then
  echo "build/" >> "$H/projects/trailhead/.gitignore"
  git -C "$H/projects/trailhead" -c user.name="Alex Rivera" -c user.email=alex@example.com \
    commit -qam "Ignore build output"
fi

for _ in $(seq 90); do curl -s -o /dev/null "http://127.0.0.1:$PORT/" && break; sleep 1; done
echo "started on port $PORT, log in $ROOT.log"
