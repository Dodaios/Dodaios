#!/usr/bin/env bash
# Nightly Linux smoke of the packaged Unreal Verse, run inside smoke.Dockerfile.
#
#   bash /smoke/linux_smoke.sh <seconds> <gpu|nogpu>
#
# 1. Server run: Verse.sh under -nullrhi (the game is its own listen server;
#    there is no Server target, decision C7) through the smoke stages
#    boot, hangar and a bot-vs-bot arena, for at most <seconds> plus start-up.
# 2. Vulkan first frame, only when a Vulkan device exists in the container.
# 3. Window activation: X11 (_NET_ACTIVE_WINDOW under a window manager) and
#    Wayland (the xdg_activation_v1 global of a headless compositor).
# Writes /out/result.json; scripts/unreal/package.py reads it.
set -u

seconds="${1:-60}"
mode="${2:-nogpu}"
out=/out
stages='boot,hangar,arena30s'
export XDG_RUNTIME_DIR=/tmp/xdg-verse
mkdir -p "${XDG_RUNTIME_DIR}"
chmod 700 "${XDG_RUNTIME_DIR}"

stages_ok() {
  log="$1"
  for stage in boot hangar arena30s; do
    grep -q "VerseSmoke: stage ${stage} OK" "${log}" 2>/dev/null || return 1
  done
  return 0
}

# --- 1. server run ----------------------------------------------------------
start=$(date +%s)
timeout --signal=TERM "$((seconds + 60))" /verse/Verse.sh -nullrhi -nosound -unattended \
  -VerseSmoke="${stages}" -log -abslog="${out}/nullrhi.log" >"${out}/nullrhi.stdout" 2>&1
server_rc=$?
server_seconds=$(( $(date +%s) - start ))
server_ok=false
if [ "${server_rc}" -eq 0 ] && stages_ok "${out}/nullrhi.log"; then server_ok=true; fi

# --- 2. Vulkan first frame --------------------------------------------------
vulkan='skip'
if [ "${mode}" = 'gpu' ] && vulkaninfo --summary >"${out}/vulkaninfo.txt" 2>&1; then
  Xvfb :99 -screen 0 1280x720x24 >/dev/null 2>&1 &
  xvfb_pid=$!
  sleep 2
  DISPLAY=:99 timeout --signal=TERM 120 /verse/Verse.sh -vulkan -windowed -ResX=1280 -ResY=720 \
    -nosound -unattended -VerseSmoke=boot -log -abslog="${out}/vulkan.log" >"${out}/vulkan.stdout" 2>&1
  if grep -Eq 'VerseSmoke: (first frame|stage boot OK)' "${out}/vulkan.log" 2>/dev/null; then
    vulkan='ok'
  else
    vulkan='fail'
  fi
  kill "${xvfb_pid}" 2>/dev/null
fi

# --- 3. activation ----------------------------------------------------------
Xvfb :98 -screen 0 1024x768x24 >/dev/null 2>&1 &
x_pid=$!
sleep 1
DISPLAY=:98 openbox >/dev/null 2>&1 &
wm_pid=$!
weston --backend=headless-backend.so --socket=wl-verse-smoke >/dev/null 2>&1 &
weston_pid=$!
sleep 3
python3 /smoke/activation_check.py --x11 :98 --wayland wl-verse-smoke >"${out}/activation.json" 2>"${out}/activation.err"
kill "${weston_pid}" "${wm_pid}" "${x_pid}" 2>/dev/null

python3 - "${out}" "${server_ok}" "${server_rc}" "${server_seconds}" "${vulkan}" <<'PY'
import json, sys
out, server_ok, rc, secs, vulkan = sys.argv[1:6]
try:
    activation = json.load(open(f"{out}/activation.json", encoding="utf-8"))
except (OSError, ValueError):
    activation = {"x11": "fail", "wayland": "fail", "detail": "activation check wrote nothing"}
problems = []
if server_ok != "true":
    problems.append(f"server run exit {rc} or a smoke stage was not reported OK")
if vulkan == "fail":
    problems.append("no Vulkan first frame although a device exists")
for name in ("x11", "wayland"):
    if activation.get(name) == "fail":
        problems.append(f"{name} activation is not available")
json.dump({"schema": "verse.linux-smoke/1", "server_ok": server_ok == "true",
           "server_exit": int(rc), "server_seconds": int(secs), "vulkan": vulkan,
           "activation": activation, "problems": problems},
          open(f"{out}/result.json", "w", encoding="utf-8"), indent=2)
PY
