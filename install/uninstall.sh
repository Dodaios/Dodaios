#!/usr/bin/env bash
# Personal Jarvis — macOS / Linux uninstaller
#
# Usage (from any POSIX shell), on a machine where Jarvis is installed:
#   bash ~/.dodaios/install/uninstall.sh
#   bash ~/.dodaios/install/uninstall.sh --dry-run   # preview only
#   bash ~/.dodaios/install/uninstall.sh --yes       # no prompt
# (an install never moved from its earlier name lives in ~/.personal-jarvis)
#
# It removes four things a plain folder-delete would miss:
#   1. the install folder (~/.dodaios, or ~/.personal-jarvis before the rename;
#      a link left at the earlier name is removed as a link, never followed)
#   2. the macOS app bundle or Linux application-menu entry
#   3. the login-autostart entry (~/.config/autostart or ~/Library/LaunchAgents)
#   4. the API keys saved in the OS keychain (service "dodaios", and
#      "personal-jarvis" from before the rename)
#
# Heavy logic lives in `python -m dodaios --uninstall` (cross-platform, tested).
# This bootstrap runs that for the autostart + keys (it asks for confirmation),
# then removes the folder itself from OUTSIDE the venv so nothing is locked.

set -euo pipefail

# Standalone fallback projections of dodaios/core/branding.py. These remain
# available even when a broken venv prevents importing the installed package.
DEFAULT_INSTALL_DIR_NAME=".dodaios"
LEGACY_INSTALL_DIR_NAME=".personal-jarvis"
MACOS_APP_DIR_NAME="Dodaios.app"
LEGACY_MACOS_APP_DIR_NAME="Personal Jarvis.app"
MACOS_BUNDLE_ID="com.personal-jarvis.desktop"
MACOS_AUTOSTART_LABEL="com.personal-jarvis.autostart"
LINUX_DESKTOP_ENTRY_FILE_NAME="dodaios.desktop"
LEGACY_LINUX_DESKTOP_ENTRY_FILE_NAMES="personal-jarvis.desktop"
KEYRING_SERVICE_NAME="dodaios"
LEGACY_KEYRING_SERVICE_NAMES="personal-jarvis"

# --- uninstall-dir begin (extracted by tests/unit/install/test_install_dir_move.py)
# DODAIOS_INSTALL_DIR and JARVIS_INSTALL_DIR are one option; the new name wins.
# Without either: the folder under its earlier name while that is a real
# directory (an install that was never moved), else the current one.
INSTALL_DIR="${DODAIOS_INSTALL_DIR:-${JARVIS_INSTALL_DIR:-}}"
if [ -z "$INSTALL_DIR" ]; then
    if [ -d "$HOME/$LEGACY_INSTALL_DIR_NAME" ] && [ ! -L "$HOME/$LEGACY_INSTALL_DIR_NAME" ]; then
        INSTALL_DIR="$HOME/$LEGACY_INSTALL_DIR_NAME"
    else
        INSTALL_DIR="$HOME/$DEFAULT_INSTALL_DIR_NAME"
    fi
fi
[ "$INSTALL_DIR" = "/" ] || INSTALL_DIR="${INSTALL_DIR%/}"
# --- uninstall-dir end
VENV_PYTHON="$INSTALL_DIR/.venv/bin/python"

if [ -t 1 ]; then
    GOLD=$(printf '\033[38;2;255;214;10m'); GREEN=$(printf '\033[38;2;122;200;140m')
    DIM=$(printf '\033[38;2;143;143;143m');  RED=$(printf '\033[38;2;224;122;110m')
    BOLD=$(printf '\033[1m'); RST=$(printf '\033[0m')
else
    GOLD=""; GREEN=""; DIM=""; RED=""; BOLD=""; RST=""
fi
step() { printf '\n%s  ●%s %s%s%s\n' "$GOLD" "$RST" "$BOLD" "$1" "$RST"; }
ok()   { printf '%s    ✓%s %s%s%s\n' "$GREEN" "$RST" "$DIM" "$1" "$RST"; }
note() { printf '%s      %s%s\n' "$DIM" "$1" "$RST"; }
err()  { printf '%s    ✗ %s%s\n' "$RED" "$1" "$RST"; }

# Stop every process still executing out of the install dir — the app itself
# (tray, server, worker). On POSIX the delete would succeed anyway, but a
# survivor would keep running from a removed tree (holding its port and mic)
# until reboot. Never touches this shell or its parent. Best effort.
stop_running_instances() {
    root="$1"
    pids=""
    if [ -d /proc ]; then
        # Linux: match the real executable path behind each /proc entry.
        for exe in /proc/[0-9]*/exe; do
            pid="${exe#/proc/}"; pid="${pid%/exe}"
            [ "$pid" = "$$" ] && continue
            [ "$pid" = "${PPID:-0}" ] && continue
            target=$(readlink "$exe" 2>/dev/null) || continue
            case "$target" in ("$root"/*) pids="$pids $pid" ;; esac
        done
    else
        # macOS/BSD: ps reports the full executable path in comm.
        #
        # The leading "(" on the case pattern is REQUIRED, not style: bash 3.2
        # — the version macOS still ships — cannot parse a bare `pattern)` case
        # arm inside a $( ) command substitution. Its parser takes that ")" as
        # the end of the substitution and the whole FILE fails to parse:
        #   uninstall.sh: line 57: syntax error near unexpected token `;;'
        # so not one line of the uninstaller runs. The optional leading "(" is
        # POSIX and works on every shell we target. Both arms carry it so a
        # future move in or out of a substitution stays safe.
        pids=$(ps -axo pid=,comm= 2>/dev/null | while read -r pid comm; do
            [ "$pid" = "$$" ] && continue
            [ "$pid" = "${PPID:-0}" ] && continue
            case "$comm" in ("$root"/*) printf '%s ' "$pid" ;; esac
        done) || true
    fi
    pids=$(printf '%s' "$pids" | tr -s ' ')
    [ -n "${pids# }" ] || return 0

    # shellcheck disable=SC2086 — word-splitting the PID list is intended
    kill $pids 2>/dev/null || true
    alive=""
    for _ in 1 2 3 4 5 6; do
        alive=""
        for pid in $pids; do
            kill -0 "$pid" 2>/dev/null && alive="$alive $pid"
        done
        [ -z "$alive" ] && break
        sleep 1
    done
    if [ -n "$alive" ]; then
        # shellcheck disable=SC2086
        kill -9 $alive 2>/dev/null || true
        sleep 1
    fi
    n=$(echo "$pids" | wc -w | tr -d ' ')
    ok "Stopped the running Dodaios app ($n process(es))."
}

# Remove the install folder, never through a link. A link (the one given, or
# the one a move to the current folder name left at the earlier name) is
# removed as a link, and only when it leads to this install; the folder it
# leads to is removed as a folder.
remove_install_dir() {
    # --- uninstall-remove begin (extracted by tests/unit/install/test_install_dir_move.py)
    given="$1"
    real_dir="$(cd -P "$given" 2>/dev/null && pwd -P)" || real_dir="$given"
    stop_running_instances "$real_dir"
    [ "$given" = "$real_dir" ] || stop_running_instances "$given"
    for link in "$given" "$HOME/$LEGACY_INSTALL_DIR_NAME" "$HOME/$DEFAULT_INSTALL_DIR_NAME"; do
        [ -L "$link" ] || continue
        link_target="$(cd -P "$link" 2>/dev/null && pwd -P)" || link_target=''
        [ "$link_target" = "$real_dir" ] || continue
        # rm on a symlink removes the link itself; it never descends into it.
        if ! rm -f -- "$link"; then
            err "Could not remove the link $link."
            exit 3
        fi
        note "removed the link $link"
    done
    if [ -L "$real_dir" ] || ! rm -rf -- "$real_dir"; then
        err "Could not fully remove $real_dir — something is still using files inside it."
        note 'Close every Dodaios window, then run this uninstaller again.'
        exit 3
    fi
    # --- uninstall-remove end
}

# Linux, without the venv: the login-autostart entry (current and earlier
# name) and the application-menu entry under its earlier name. Each one goes
# only when it starts this install, which its working folder (Path=) tells:
# an entry of another install on this machine is kept.
remove_linux_entries_of_install() {
    # --- uninstall-linux-entries begin (extracted by tests/unit/install/test_linux_entry_rename.py)
    install_real="$(cd -P "$1" 2>/dev/null && pwd -P)" || install_real="$1"
    apps_dir="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
    autostart_dir="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
    for entries_dir in "$autostart_dir" "$apps_dir"; do
        for name in $LINUX_DESKTOP_ENTRY_FILE_NAME $LEGACY_LINUX_DESKTOP_ENTRY_FILE_NAMES; do
            entry="$entries_dir/$name"
            # The current menu entry is this install's by name and goes anyway.
            [ "$entry" = "$apps_dir/$LINUX_DESKTOP_ENTRY_FILE_NAME" ] && continue
            [ -f "$entry" ] || continue
            entry_dir=$(sed -n 's/^Path=//p' "$entry" | head -n 1)
            entry_real="$(cd -P "$entry_dir" 2>/dev/null && pwd -P)" || entry_real="$entry_dir"
            if [ -n "$entry_dir" ] && [ "$entry_real" = "$install_real" ]; then
                rm -f -- "$entry"
                note "removed $entry"
            else
                note "kept $entry (it starts another install)"
            fi
        done
    done
    # --- uninstall-linux-entries end
}

step 'Uninstall Dodaios'
note "$INSTALL_DIR"

# Is this a dry run? Then never touch the folder. --yes/-y skips every prompt
# (required on a headless box where stdin is not a terminal).
DRY_RUN=0
ASSUME_YES=0
for a in "$@"; do
    [ "$a" = "--dry-run" ] && DRY_RUN=1
    { [ "$a" = "--yes" ] || [ "$a" = "-y" ]; } && ASSUME_YES=1
done

if [ ! -d "$INSTALL_DIR" ]; then
    err "No install found at $INSTALL_DIR — nothing to do."
    exit 0
fi

# 2 + 3 + 4: run the tested cleanup (app registration, autostart, and keys),
#            keeping the folder so we can delete it below. --keep-folder means
#            the venv is not self-deleted while it is still running.
RC=0
if [ -x "$VENV_PYTHON" ]; then
    if "$VENV_PYTHON" -m dodaios --uninstall --keep-folder "$@"; then RC=0; else RC=$?; fi
else
    err "Python environment missing — skipping autostart/key cleanup."
    note "The app registration and folder can still be removed; saved API keys may remain."
    if [ "$DRY_RUN" -eq 1 ]; then exit 0; fi
    if [ "$ASSUME_YES" -eq 0 ]; then
        printf 'Type '\''yes'\'' to delete %s: ' "$INSTALL_DIR"
        read -r ans
        [ "$ans" = "yes" ] || { note 'Cancelled.'; exit 1; }
    fi
    case "$(uname -s)" in
        Darwin)
            # Both install locations and both names, but only OUR bundle: the
            # DMG build has the same name and its own bundle id, and is not
            # ours to delete.
            for apps_dir in "/Applications" "$HOME/Applications"; do
                for app_dir_name in "$MACOS_APP_DIR_NAME" "$LEGACY_MACOS_APP_DIR_NAME"; do
                    app="$apps_dir/$app_dir_name"
                    [ -e "$app" ] || continue
                    app_id=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' \
                        "$app/Contents/Info.plist" 2>/dev/null || true)
                    if [ -n "$app_id" ] && [ "$app_id" != "$MACOS_BUNDLE_ID" ]; then
                        note "kept $app (a separately installed app)"
                        continue
                    fi
                    rm -rf -- "$app"
                done
            done
            # Without this the login item keeps firing at a deleted app.
            agent="$HOME/Library/LaunchAgents/${MACOS_AUTOSTART_LABEL}.plist"
            launchctl unload -w "$agent" >/dev/null 2>&1 || true
            rm -f -- "$agent"
            ;;
        Linux)
            rm -f -- "${XDG_DATA_HOME:-$HOME/.local/share}/applications/$LINUX_DESKTOP_ENTRY_FILE_NAME"
            remove_linux_entries_of_install "$INSTALL_DIR"
            ;;
    esac
    ok 'Removed the desktop app registration.'
    RC=0
fi

# Map the Python step's exit code HONESTLY. It returns 1 when the user
# declines at its prompt and 2 when the folder is not a Jarvis install - it
# printed the reason itself in both cases. ANY OTHER code means it CRASHED,
# most often a venv whose interpreter stopped resolving after a system Python
# upgrade (on macOS/Homebrew: "dyld: Library not loaded: @rpath/Python3...").
# Reporting a crash as "cancelled" hides a real failure behind a user-choice
# message and leaves the install standing with no clue why - which is exactly
# how a broken uninstall reads as "it just does nothing".
if [ "$RC" -eq 1 ]; then
    note 'Cancelled — nothing was changed.'
    exit 1
elif [ "$RC" -eq 2 ]; then
    exit 2
elif [ "$RC" -ne 0 ]; then
    err "The cleanup step failed (exit $RC) — nothing was changed."
    note 'Its own error is printed above. On macOS the usual cause is a venv'
    note 'broken by a system/Homebrew Python upgrade.'
    note 'To remove Dodaios anyway:'
    note "  rm -rf \"$INSTALL_DIR\""
    note "Saved API keys then stay in your OS keychain under \"$KEYRING_SERVICE_NAME\""
    note "and \"$LEGACY_KEYRING_SERVICE_NAMES\"."
    exit "$RC"
fi

# 1: delete the folder from OUTSIDE the venv. The Python step above already
#    stops the running app; anything (re)started since - and the no-venv
#    fallback path - is caught here again. A failed delete says plainly WHY.
if [ "$DRY_RUN" -eq 0 ]; then
    cd "$HOME"
    remove_install_dir "$INSTALL_DIR"
    ok "Removed $INSTALL_DIR"
    step 'Done. Dodaios has been uninstalled.'
fi
