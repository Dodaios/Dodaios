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
# terminals stopped at "MCP servers need authentication").
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

for _ in $(seq 90); do curl -s -o /dev/null "http://127.0.0.1:$PORT/" && break; sleep 1; done
echo "started on port $PORT, log in $ROOT.log"
