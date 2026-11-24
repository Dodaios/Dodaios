#!/usr/bin/env bash
# Dodaios — macOS / Linux quick-install bootstrap (Stage 1)
#
# Usage (from any POSIX shell):
#   curl -fsSL https://raw.githubusercontent.com/Dodaios/Dodaios/main/install/install.sh | bash
#
# This bootstrap is intentionally small. It:
#   1. Uses Python 3.11+ and git when they are installed. A missing Python
#      is fetched as a self-contained per-user copy via uv (no sudo, no
#      prompt).
#   2. Offers to install a missing git, then re-checks in place.
#   3. Checks for Node.js 18+ (optional - a missing Node never blocks the install).
#   4. Clones (or updates) Dodaios into ~/.dodaios (an update moves an install
#      made under the earlier name ~/.personal-jarvis there).
#   5. Creates a Python venv, installs `rich` + `packaging`.
#   6. Hands control to install/installer.py (the Stage 2 orchestrator).
#
# All heavy logic lives in installer.py so it can be unit-tested and
# kept cross-platform.

set -euo pipefail

# --- install-option-names begin
# Every JARVIS_ option this script reads also answers to its DODAIOS_
# spelling. When both are set to different values the DODAIOS_ one wins, and
# the clash is named, never its values. The rest of this script, and
# installer.py after it, read the JARVIS_ spelling (dodaios/core/env_prefix.py
# does the same for the app). JARVIS_PAYLOAD_COMMIT is not an option: it is
# the signed commit the verifying installer hands over, and no second name
# may override it.
adopt_install_option_names() {
    local option new_name old_name new_value old_value
    for option in INSTALL_REPO INSTALL_REF INSTALL_DIR INSTALL_PREREQS INSTALL_YES \
        OFFICIAL_REPO_SLUG PYTHON PYTHON_SEARCH_DIRS NO_PYTHON_BOOTSTRAP INSTALL_ASCII; do
        new_name="DODAIOS_$option"
        old_name="JARVIS_$option"
        new_value="${!new_name:-}"
        old_value="${!old_name:-}"
        [ -n "$new_value" ] || continue
        if [ -n "$old_value" ] && [ "$old_value" != "$new_value" ]; then
            printf '%s and %s differ; using %s.\n' "$new_name" "$old_name" "$new_name" >&2
        fi
        export "$old_name=$new_value"
    done
}
adopt_install_option_names
# --- install-option-names end

# Standalone bootstrap projections of dodaios/core/branding.py. The branding
# contract test rejects drift because this script runs before Python is installed.
OFFICIAL_REPO_SLUG="${JARVIS_OFFICIAL_REPO_SLUG:-Dodaios/Dodaios}"
if [[ ! "$OFFICIAL_REPO_SLUG" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]; then
    printf 'JARVIS_OFFICIAL_REPO_SLUG must be an exact owner/repository slug\n' >&2
    exit 2
fi
REPO_URL="${JARVIS_INSTALL_REPO:-https://github.com/${OFFICIAL_REPO_SLUG}.git}"
LEGACY_OFFICIAL_REPO_SLUG="PersonalJarvis/PersonalJarvis"
CONFIG_FILE_NAME="dodaios.toml"
# An install keeps a config file under this earlier name; it is never renamed.
LEGACY_CONFIG_FILE_NAME="jarvis.toml"
MACOS_AUTOSTART_LABEL="com.personal-jarvis.autostart"
# Empty = the newest published release (resolve_install_ref below).
BRANCH="${JARVIS_INSTALL_REF:-}"
# --- install-dir-choice begin (extracted by tests/unit/install/test_install_dir_move.py)
# The checkout lives in ~/.dodaios. An install made under the earlier name
# keeps its directory for as long as that is a real directory, and an update
# run moves it (migrate_install_dir below). A directory given in
# JARVIS_INSTALL_DIR (or DODAIOS_INSTALL_DIR) is used as given, never moved.
DEFAULT_INSTALL_DIR_NAME=".dodaios"
LEGACY_INSTALL_DIR_NAME=".personal-jarvis"
CURRENT_INSTALL_DIR="$HOME/$DEFAULT_INSTALL_DIR_NAME"
LEGACY_INSTALL_DIR="$HOME/$LEGACY_INSTALL_DIR_NAME"
MIGRATE_LEGACY_INSTALL_DIR=0
if [ -n "${JARVIS_INSTALL_DIR:-}" ]; then
    INSTALL_DIR="$JARVIS_INSTALL_DIR"
elif [ -d "$LEGACY_INSTALL_DIR" ] && [ ! -L "$LEGACY_INSTALL_DIR" ]; then
    INSTALL_DIR="$LEGACY_INSTALL_DIR"
    MIGRATE_LEGACY_INSTALL_DIR=1
else
    INSTALL_DIR="$CURRENT_INSTALL_DIR"
fi
# --- install-dir-choice end
# The migration engine inside the release being installed. It is read from
# the fetched commit, never from the checkout that is about to change.
IDENTITY_ENGINE_PATH="dodaios/core/identity_migration.py"
PREREQUISITE_MODE="${JARVIS_INSTALL_PREREQS:-ask}"

# --- installer-ui begin (extracted by tests/unit/install/test_install_ui_shell.py)
# How the installer looks: one design across both stages and every platform.
# installer.py continues it (dodaios/setup/install_ui.py) and install.ps1 is
# its Windows twin; all three decide what the terminal can show by the same
# rules, written out in that Python module:
#   colour  off with NO_COLOR, TERM=dumb or when stdout is not a terminal
#           (FORCE_COLOR turns it back on); truecolor with COLORTERM or a
#           known modern terminal, 256 colours when TERM says so, else 16.
#   glyphs  ASCII with JARVIS_INSTALL_ASCII, TERM=linux/dumb/vt*, or a locale
#           that is not UTF-8; the full set otherwise.
#   motion  spinners only on a terminal, never in CI.
#   width   COLUMNS, else the terminal's, else 80.
# Nothing here waits for effect: a spinner redraws only while real work runs.
ui_truthy() {
    case "${1:-}" in ''|0|false|FALSE|False|no|NO|off|OFF) return 1 ;; *) return 0 ;; esac
}
UI_TTY=0
[ -t 1 ] && UI_TTY=1
UI_TERM="${TERM:-}"
if [ -n "${NO_COLOR:-}" ] || [ "$UI_TERM" = 'dumb' ]; then
    UI_COLOR=none
elif [ "$UI_TTY" -eq 1 ] || ui_truthy "${FORCE_COLOR:-}"; then
    case "${COLORTERM:-}:${TERM_PROGRAM:-}:$UI_TERM" in
        truecolor:*|24bit:*|*:iTerm.app:*|*:WezTerm:*|*:vscode:*|*:ghostty:*|*direct*) UI_COLOR=truecolor ;;
        *256*|*::) UI_COLOR=256 ;;
        *) UI_COLOR=16 ;;
    esac
    # Windows Terminal (it forwards WT_SESSION into WSL) and every Windows
    # console behind WSL draw 24-bit colour without saying so in COLORTERM.
    if [ "$UI_COLOR" = '256' ] && [ -n "${WT_SESSION:-}${WSL_DISTRO_NAME:-}" ]; then UI_COLOR=truecolor; fi
else
    UI_COLOR=none
fi
UI_LOCALE="${LC_ALL:-${LC_CTYPE:-${LANG:-}}}"
case "$UI_LOCALE" in
    *[Uu][Tt][Ff]-8*|*[Uu][Tt][Ff]8*) UI_GLYPHS=full ;;
    '')
        # No locale at all (a bare container): trust a terminal that names itself.
        if [ -n "${TERM_PROGRAM:-}${COLORTERM:-}" ]; then UI_GLYPHS=full; else UI_GLYPHS=ascii; fi
        ;;
    *) UI_GLYPHS=ascii ;;
esac
case "$UI_TERM" in linux|dumb|ansi|cons25|vt*) UI_GLYPHS=ascii ;; esac
if ui_truthy "${JARVIS_INSTALL_ASCII:-}"; then UI_GLYPHS=ascii; fi
UI_MOTION=0
if [ "$UI_TTY" -eq 1 ] && [ "$UI_TERM" != 'dumb' ] && ! ui_truthy "${CI:-}"; then UI_MOTION=1; fi
UI_COLS="${COLUMNS:-}"
case "$UI_COLS" in
    ''|*[!0-9]*)
        UI_COLS=$( { stty size </dev/tty; } 2>/dev/null | awk '{ print $2 }' ) || UI_COLS=''
        case "$UI_COLS" in ''|*[!0-9]*|0) UI_COLS=80 ;; esac
        ;;
esac
[ "$UI_COLS" -lt 20 ] && UI_COLS=20
UI_LAYOUT=$UI_COLS
[ "$UI_LAYOUT" -gt 88 ] && UI_LAYOUT=88

if [ "$UI_GLYPHS" = 'full' ]; then
    G_OK='✓'; G_FAIL='×'; G_SKIP='·'; G_RAIL='┃'; G_POINT='▸'; G_ELL='…'; G_BAR='━'
    UI_SPIN_FRAMES=('⠋' '⠙' '⠹' '⠸' '⠼' '⠴' '⠦' '⠧' '⠇' '⠏')
else
    G_OK='+'; G_FAIL='x'; G_SKIP='-'; G_RAIL='|'; G_POINT='>'; G_ELL='...'; G_BAR='#'
    UI_SPIN_FRAMES=('|' '/' '-' '\')
fi
G_WARN='!'
UI_ESC=$(printf '\033')

# Brand palette (docs/BRAND.md): signal gold, deep gold, the status colours.
# Plain text keeps the terminal's own foreground, so light themes read it too.
ui_sgr() { # $1 = truecolor parameters, $2 = 256-colour ones, $3 = 16-colour ones
    case "$UI_COLOR" in
        truecolor) printf '\033[%sm' "$1" ;;
        256) printf '\033[%sm' "$2" ;;
        16) printf '\033[%sm' "$3" ;;
    esac
}
C_GOLD=$(ui_sgr '38;2;255;214;10' '38;5;220' '33')
C_OK=$(ui_sgr '38;2;34;195;94' '38;5;35' '32')
C_WARN=$(ui_sgr '38;2;245;158;11' '38;5;214' '33')
C_BAD=$(ui_sgr '38;2;223;58;58' '38;5;167' '31')
C_MUTED=$(ui_sgr '38;2;138;138;138' '38;5;245' '90')
C_BOLD=$(ui_sgr '1' '1' '1')
C_RST=$(ui_sgr '0' '0' '0')
P_GOLD=$(ui_sgr '1;38;2;10;10;10;48;2;255;214;10' '1;38;5;232;48;5;220' '1;30;43')
P_BAD=$(ui_sgr '1;38;2;10;10;10;48;2;223;58;58' '1;38;5;232;48;5;167' '1;30;41')
# Typography the messages use, spelled out where only ASCII shows.
ui_text() {
    if [ "$UI_GLYPHS" = 'full' ]; then printf '%s' "$1"; return 0; fi
    printf '%s' "$1" | sed -e 's/—/-/g' -e 's/–/-/g' -e 's/…/.../g' -e 's/→/->/g' -e 's/·/-/g'
}
ui_dur() { # whole seconds -> "", "12s", "1m 05s"
    case "${1:-}" in ''|*[!0-9]*) return 0 ;; esac
    [ "$1" -lt 1 ] && return 0
    if [ "$1" -lt 60 ]; then printf '%ss' "$1"; return 0; fi
    printf '%sm %02ds' $(($1 / 60)) $(($1 % 60))
}
# $1 = the line, $2 = its visible width, $3 = text for the right edge.
ui_right() {
    if [ -z "${3:-}" ]; then printf '%s\n' "$1"; return 0; fi
    _ui_gap=$((UI_LAYOUT - 2 - $2 - ${#3}))
    [ "$_ui_gap" -lt 2 ] && _ui_gap=2
    printf '%s%*s%s%s%s\n' "$1" "$_ui_gap" '' "$C_MUTED" "$3" "$C_RST"
}
UI_IN_FAIL=0
UI_LAST_SECONDS=0
phase() { # $1 = "2/6", $2 = title
    UI_IN_FAIL=0
    printf '\n'
    if [ "$UI_COLOR" = 'none' ]; then
        printf '  [%s] %s\n' "$1" "$(ui_text "$2")"
    else
        printf '  %s %s %s  %s%s%s\n' "$P_GOLD" "$1" "$C_RST" "$C_BOLD" "$(ui_text "$2")" "$C_RST"
    fi
}
ok() { # $1 = text, $2 = whole seconds it took (optional), $3 = a quiet detail (a path)
    UI_IN_FAIL=0
    _ui_body=$(ui_text "$1")
    if [ -n "${3:-}" ]; then
        printf '     %s%s%s  %s  %s%s%s\n' "$C_OK" "$G_OK" "$C_RST" "$_ui_body" "$C_MUTED" "$3" "$C_RST"
        return 0
    fi
    ui_right "     $C_OK$G_OK$C_RST  $_ui_body" $((8 + ${#_ui_body})) "$(ui_dur "${2:-}")"
}
skip() { # something optional that is not there; the install goes on
    UI_IN_FAIL=0
    printf '     %s%s  %s%s\n' "$C_MUTED" "$G_SKIP" "$(ui_text "$1")" "$C_RST"
}
warn() {
    UI_IN_FAIL=0
    printf '     %s%s%s  %s\n' "$C_WARN$C_BOLD" "$G_WARN" "$C_RST" "$(ui_text "$1")"
}
# After err, the notes that follow hang on its red rail until the next step.
note() {
    if [ "$UI_IN_FAIL" -eq 1 ]; then
        printf '     %s%s%s  %s\n' "$C_BAD" "$G_RAIL" "$C_RST" "$(ui_text "$1")"
    else
        printf '        %s%s%s\n' "$C_MUTED" "$(ui_text "$1")" "$C_RST"
    fi
}
err() {
    UI_IN_FAIL=1
    printf '     %s%s%s  %s%s%s\n' "$C_BAD$C_BOLD" "$G_FAIL" "$C_RST" "$C_BOLD" "$(ui_text "$1")" "$C_RST"
}
stopped() { # the closing line of a run that stopped
    printf '\n'
    if [ "$UI_COLOR" = 'none' ]; then
        printf '  [STOPPED] %s\n' "$(ui_text "$1")"
    else
        printf '  %s STOPPED %s  %s\n' "$P_BAD" "$C_RST" "$(ui_text "$1")"
    fi
}
# The live line of a running step: $1 frame index, $2 label, $3 seconds so far.
ui_live() {
    _live_frame=${UI_SPIN_FRAMES[$(($1 % ${#UI_SPIN_FRAMES[@]}))]}
    _live_time=$(ui_dur "$3")
    [ -n "$_live_time" ] || _live_time='0s'
    _ui_gap=$((UI_LAYOUT - 10 - ${#2} - ${#_live_time}))
    if [ "$_ui_gap" -lt 2 ]; then
        # Never wrap the live line: a wrapped line cannot be redrawn in place.
        printf '\r\033[K     %s%s%s  %s%s%s' "$C_GOLD" "$_live_frame" "$C_RST" "$C_MUTED" "$_live_time" "$C_RST"
    else
        printf '\r\033[K     %s%s%s  %s%*s%s%s%s' "$C_GOLD" "$_live_frame" "$C_RST" "$2" "$_ui_gap" '' "$C_MUTED" "$_live_time" "$C_RST"
    fi
}
# Run a slow, otherwise-silent command behind a spinner and its elapsed time,
# so a long download never looks hung (maintainer report 2026-07-15). TTY
# only: a piped/CI run prints the label once and streams the command instead.
# Output is captured to a temp log whose tail is printed on failure, so errors
# are never swallowed. Sets UI_LAST_SECONDS. Do NOT wrap anything that may
# prompt (sudo): the background redirect would eat the prompt.
run_spin() {
    _spin_label=$(ui_text "$1"); shift
    _spin_t0=$SECONDS
    if [ "$UI_MOTION" -ne 1 ]; then
        printf '     %s%s  %s%s%s\n' "$C_MUTED" "$G_SKIP" "$_spin_label" "$G_ELL" "$C_RST"
        _spin_rc=0
        "$@" </dev/null || _spin_rc=$?
        UI_LAST_SECONDS=$((SECONDS - _spin_t0))
        [ "$_spin_rc" -eq 0 ] || err "$_spin_label failed (exit code $_spin_rc)"
        return $_spin_rc
    fi
    _spin_log=$(mktemp)
    "$@" </dev/null >"$_spin_log" 2>&1 &
    _spin_pid=$!
    _spin_i=0
    printf '\033[?25l'
    while kill -0 "$_spin_pid" 2>/dev/null; do
        ui_live "$_spin_i" "$_spin_label" $((SECONDS - _spin_t0))
        _spin_i=$((_spin_i + 1))
        sleep 0.12 2>/dev/null || sleep 1
    done
    _spin_rc=0
    wait "$_spin_pid" || _spin_rc=$?
    UI_LAST_SECONDS=$((SECONDS - _spin_t0))
    printf '\r\033[K\033[?25h'
    if [ "$_spin_rc" -ne 0 ]; then
        err "$_spin_label failed (exit code $_spin_rc)"
        # sed, not a `read` loop: the prompt-free guard test permits `read`
        # only inside the welcome gate and the prerequisite-bootstrap flow.
        tail -n 20 "$_spin_log" | sed -e "s/^/     $C_BAD$G_RAIL$C_RST  /"
    fi
    rm -f "$_spin_log"
    return $_spin_rc
}

# The hero: the hooded figure beside the pixel wordmark, the README banner
# drawn with half blocks (two pixels per text cell). '#' is gold on a
# vertical gradient and 's' the wordmark's drop shadow. Drawn with 256 or
# more colours, Unicode and room for it; otherwise a plain title stands in.
UI_MASCOT=(
'..........###.........'
'........######........'
'......########.##.....'
'....##.#######.#####..'
'...##.....####.####...'
'..##......#####.##....'
'.##.####...####.......'
'.#.#######..####......'
'..##########.###......'
'.#.######..##.###.....'
'#..#..###..##..##.....'
'#..#..###..###.###....'
'#..##.########.##.....'
'.#...#######.##.......'
'..###...#####.##......'
'...#####...####.##....'
'...########...#..####.'
'...###########..######'
'...############..#####'
'...#############..###.'
'...######.########....'
'...#####.#########....'
'...#####.########.....'
'....###...######......'
)
UI_WORDMARK=(
'#####....####...#####.....##....####...####....#####'
'######..######..######...####...####..######..######'
'##ss##..##ss##..##ss##..######..s##s..##ss##..##ssss'
'##..##..##..##..##..##..##ss##...##...##..##..#####.'
'##..##..##..##..##..##..######...##...##..##..s#####'
'##..##..##..##..##..##..######...##...##..##...sss##'
'######..######..######..##ss##..####..######..######'
'#####s..s####s..#####s..##..##..####..s####s..#####s'
'sssss....ssss...sssss...ss..ss..ssss...ssss...sssss.'
'....................................................'
)
# The gold of pixel row $1 in an image $2 rows tall, into _UI_GOLD (an SGR
# colour without its 38/48 prefix): #FFF07A at the top, #FFD60A in the
# middle, #B8860B at the bottom, as in the banner.
ui_gold() {
    _gold_t=$(($1 * 1000 / ($2 - 1)))
    if [ "$UI_COLOR" = 'truecolor' ]; then
        if [ "$_gold_t" -le 500 ]; then
            _UI_GOLD="2;255;$((240 - 26 * _gold_t / 500));$((122 - 112 * _gold_t / 500))"
        else
            _gold_t=$((_gold_t - 500))
            _UI_GOLD="2;$((255 - 71 * _gold_t / 500));$((214 - 80 * _gold_t / 500));$((10 + _gold_t / 500))"
        fi
    elif [ "$_gold_t" -lt 200 ]; then _UI_GOLD='5;228'
    elif [ "$_gold_t" -lt 400 ]; then _UI_GOLD='5;227'
    elif [ "$_gold_t" -lt 620 ]; then _UI_GOLD='5;220'
    elif [ "$_gold_t" -lt 820 ]; then _UI_GOLD='5;178'
    else _UI_GOLD='5;136'; fi
}
# One text row of an image into _UI_ART: $1/$2 its upper/lower pixel rows,
# $3 the upper row's index and $4 the image's height in pixel rows.
ui_art_row() {
    if [ "$UI_COLOR" = 'truecolor' ]; then _art_shadow='2;107;78;0'; else _art_shadow='5;94'; fi
    ui_gold "$3" "$4"; _art_gold_a=$_UI_GOLD
    ui_gold $(($3 + 1)) "$4"; _art_gold_b=$_UI_GOLD
    _UI_ART=''
    _art_last=''
    _art_x=0
    while [ "$_art_x" -lt "${#1}" ]; do
        case "${1:$_art_x:1}" in '#') _art_t=$_art_gold_a ;; s) _art_t=$_art_shadow ;; *) _art_t='' ;; esac
        case "${2:$_art_x:1}" in '#') _art_u=$_art_gold_b ;; s) _art_u=$_art_shadow ;; *) _art_u='' ;; esac
        if [ -z "$_art_t" ] && [ -z "$_art_u" ]; then
            _art_sgr='0'; _art_ch=' '
        elif [ -z "$_art_u" ]; then
            _art_sgr="0;38;$_art_t"; _art_ch='▀'
        elif [ -z "$_art_t" ]; then
            _art_sgr="0;38;$_art_u"; _art_ch='▄'
        else
            _art_sgr="0;38;$_art_t;48;$_art_u"; _art_ch='▀'
        fi
        if [ "$_art_sgr" != "$_art_last" ]; then
            _UI_ART="$_UI_ART$UI_ESC[${_art_sgr}m"
            _art_last=$_art_sgr
        fi
        _UI_ART="$_UI_ART$_art_ch"
        _art_x=$((_art_x + 1))
    done
    _UI_ART="$_UI_ART$UI_ESC[0m"
}
ui_hero() { # $1 = the line under the wordmark
    _hero_sub=$(ui_text "$1")
    _hero_meta=$(ui_text 'Open source · MIT · github.com/Dodaios/Dodaios')
    printf '\n'
    if [ "$UI_COLOR" = 'none' ] || [ "$UI_COLOR" = '16' ] || [ "$UI_GLYPHS" != 'full' ] \
        || [ "$UI_COLS" -lt 58 ]; then
        if [ "$UI_COLOR" = 'none' ]; then
            printf '  DODAIOS  %s\n  %s\n' "$_hero_sub" "$_hero_meta"
        else
            printf '  %s DODAIOS %s  %s%s%s\n  %s%s%s\n' "$P_GOLD" "$C_RST" "$C_BOLD" "$_hero_sub" \
                "$C_RST" "$C_MUTED" "$_hero_meta" "$C_RST"
        fi
        return 0
    fi
    if [ "$UI_COLS" -lt 80 ]; then
        # No room beside the figure: the wordmark alone, the words below it.
        _hero_y=0
        while [ "$_hero_y" -lt 10 ]; do
            ui_art_row "${UI_WORDMARK[$_hero_y]}" "${UI_WORDMARK[$((_hero_y + 1))]}" "$_hero_y" 8
            printf '  %s\n' "$_UI_ART"
            _hero_y=$((_hero_y + 2))
        done
        printf '  %s%s%s\n  %s%s%s\n' "$C_BOLD" "$_hero_sub" "$C_RST" "$C_MUTED" "$_hero_meta" "$C_RST"
        return 0
    fi
    _hero_y=0
    while [ "$_hero_y" -lt 12 ]; do
        ui_art_row "${UI_MASCOT[$((_hero_y * 2))]}" "${UI_MASCOT[$((_hero_y * 2 + 1))]}" $((_hero_y * 2)) 24
        _hero_left=$_UI_ART
        case "$_hero_y" in
            1|2|3|4|5)
                _hero_w=$(((_hero_y - 1) * 2))
                ui_art_row "${UI_WORDMARK[$_hero_w]}" "${UI_WORDMARK[$((_hero_w + 1))]}" "$_hero_w" 8
                _hero_right=$_UI_ART
                ;;
            7) _hero_right="$C_BOLD$_hero_sub$C_RST" ;;
            8) _hero_right="$C_MUTED$_hero_meta$C_RST" ;;
            *) _hero_right='' ;;
        esac
        printf '  %s   %s\n' "$_hero_left" "$_hero_right"
        _hero_y=$((_hero_y + 1))
    done
}
# --- installer-ui end

# One six-phase journey spans BOTH installer stages: this shell owns phases
# 1-3, installer.py continues with 4-6 — keep the numbering in sync there.
# The whole run is timed from here; installer.py reads the start and shows
# the total on its finale card.
JARVIS_INSTALL_STARTED_AT="${JARVIS_INSTALL_STARTED_AT:-$(date +%s)}"
export JARVIS_INSTALL_STARTED_AT

# A run that stops early ends on one clear line, and a spinner interrupted by
# Ctrl+C gives the cursor back. `exec` into installer.py replaces this shell,
# so a finished hand-off never reaches it.
ui_on_exit() {
    _exit_rc=$?
    [ "$UI_MOTION" -eq 1 ] && printf '\033[?25h'
    if [ "$_exit_rc" -ne 0 ]; then
        stopped 'The install stopped here. Nothing was launched; run the same command again once fixed.'
    fi
}
trap ui_on_exit EXIT

# The machine this runs on, for the line under the wordmark.
ui_platform() {
    case "$(uname -s 2>/dev/null || printf unknown)" in
        Darwin) printf 'macOS %s (%s)' "$(sw_vers -productVersion 2>/dev/null || printf '?')" "$(uname -m 2>/dev/null)" ;;
        Linux)
            _os_name=''
            if [ -r /etc/os-release ]; then
                _os_name=$(sed -n 's/^PRETTY_NAME="\{0,1\}\([^"]*\)"\{0,1\}$/\1/p' /etc/os-release | head -n 1)
            fi
            printf '%s (%s)' "${_os_name:-Linux}" "$(uname -m 2>/dev/null)"
            ;;
        *) uname -sm 2>/dev/null || printf 'this computer' ;;
    esac
}
if [ -e "$INSTALL_DIR/.git" ]; then
    ui_hero "Updating Dodaios on $(ui_platform)"
else
    ui_hero "Installing on $(ui_platform)"
fi

# -------------------------------------------------------------- welcome gate
# One clear question before anything touches the machine. Arrow keys (or
# y / n) choose, Enter confirms — nothing to type. `curl | bash` keeps stdin
# on the pipe, so the keys are read from /dev/tty; without a tty (CI,
# headless automation) the install proceeds — running the command was the
# explicit opt-in there. JARVIS_INSTALL_YES=1 skips the question entirely.
ask_welcome() {
    [ -n "${JARVIS_INSTALL_YES:-}" ] && return 0
    # `test -r/-w` uses access(2) and passes even when the process has no
    # controlling terminal (CI runners): actually try to open it, matching
    # the have_tty probe used later in this script.
    { { : </dev/tty; } 2>/dev/null && { : >/dev/tty; } 2>/dev/null; } || return 0
    _sel=0  # 0 = yes, 1 = no
    # The highlighted choice is a solid pill (gold Yes / red No; reverse video
    # where colour is off) with a ▸ marker, the other one is muted. The marker
    # survives even with no escapes at all, so the selection is never
    # ambiguous, and both renderings are the same visible width so the \r
    # redraw leaves no residue.
    _wg_yes=$P_GOLD; _wg_no=$P_BAD; _wg_off=$C_MUTED; _wg_rst=$C_RST
    if [ "$UI_COLOR" = 'none' ] && [ "$UI_TERM" != 'dumb' ]; then
        _wg_yes=$(printf '\033[7m'); _wg_no=$_wg_yes; _wg_rst=$(printf '\033[0m')
    fi
    _wg_q=$(ui_text 'Would you like to install Dodaios?')
    printf '\n     %s%s%s\n' "$C_MUTED" "$(ui_text '←/→ to choose · Enter to confirm · or press y / n')" "$C_RST" > /dev/tty
    while :; do
        if [ "$_sel" -eq 0 ]; then
            printf '\r  %s?%s  %s%s%s   %s %s Yes %s   %s   No  %s' \
                "$C_GOLD$C_BOLD" "$C_RST" "$C_BOLD" "$_wg_q" "$C_RST" "$_wg_yes" "$G_POINT" "$_wg_rst" "$_wg_off" "$_wg_rst" > /dev/tty
        else
            printf '\r  %s?%s  %s%s%s   %s   Yes %s   %s %s No  %s' \
                "$C_GOLD$C_BOLD" "$C_RST" "$C_BOLD" "$_wg_q" "$C_RST" "$_wg_off" "$_wg_rst" "$_wg_no" "$G_POINT" "$_wg_rst" > /dev/tty
        fi
        IFS= read -rsn1 _key < /dev/tty || return 0
        case "$_key" in
            $'\x1b')
                IFS= read -rsn2 -t 1 _rest < /dev/tty || _rest=''
                case "$_rest" in
                    '[C'|'[B') _sel=1 ;;
                    '[D'|'[A') _sel=0 ;;
                esac
                ;;
            y|Y) _sel=0; break ;;
            n|N) _sel=1; break ;;
            '') break ;;  # Enter confirms the highlighted choice
        esac
    done
    printf '\n' > /dev/tty
    if [ "$_sel" -eq 1 ]; then
        skip 'No problem: nothing was installed. Run the same command any time.'
        exit 0
    fi
}
ask_welcome

# -------------------------------------------------------------- preflight
phase '1/6' 'Prerequisites'

# --- python-detection begin -------------------------------------------------
# Covered by tests/unit/install/test_install_sh_python_detection.py.
#
# A bare PATH lookup is NOT enough on macOS: in a `curl | bash` session the
# profile files that put python.org / Homebrew interpreters on PATH are often
# never sourced, and Homebrew's versioned python@3.x kegs are keg-only (never
# linked onto PATH at all) — so we also probe the well-known install prefixes
# directly. We additionally remember the first too-old interpreter we saw, so
# a failure can say what WAS found: a field report read a bare "not found" as
# a false negative because `python3 --version` printed 3.8.2 (which reads
# "bigger" than 3.11 unless you know Python's version ordering).
#
# Escape hatches:
#   JARVIS_PYTHON              explicit interpreter; authoritative when set
#   JARVIS_PYTHON_SEARCH_DIRS  colon-separated dirs REPLACING the built-in
#                              off-PATH probe list (used by the tests)
PY_MIN_MINOR=11
PYTHON_EXE=""
FOUND_TOO_OLD=""

_py_try() {
    # Accept $1 if it runs and is Python >= 3.PY_MIN_MINOR: store its resolved
    # path in PYTHON_EXE and return 0. Otherwise remember the first too-old
    # version for the failure message and return 1.
    _exe="$1"
    _ver=$("$_exe" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])' 2>/dev/null) || return 1
    case "$_ver" in ''|*[!0-9.]*) return 1 ;; esac
    _major=${_ver%%.*}
    _minor=${_ver#*.}; _minor=${_minor%%.*}
    if [ "$_major" -gt 3 ] || { [ "$_major" -eq 3 ] && [ "$_minor" -ge "$PY_MIN_MINOR" ]; }; then
        PYTHON_EXE=$(command -v "$_exe" 2>/dev/null || printf '%s' "$_exe")
        return 0
    fi
    if [ -z "$FOUND_TOO_OLD" ]; then
        _path=$(command -v "$_exe" 2>/dev/null || printf '%s' "$_exe")
        FOUND_TOO_OLD="Python $_ver at $_path"
    fi
    return 1
}

find_python() {
    if [ -n "${JARVIS_PYTHON:-}" ]; then
        # An explicit pin is authoritative: never silently substitute another
        # interpreter for the one the user asked for.
        _py_try "$JARVIS_PYTHON"
        return $?
    fi
    # 3.13/3.12/3.11 before 3.14 (BUG-059): the local-voice native stack
    # (av / ctranslate2 / onnxruntime) publishes no cp314 wheels yet, so a
    # 3.14 venv boots fine but cannot install the local speech pack. 3.14
    # stays as a working core fallback; move it forward once wheels exist.
    for candidate in python3.13 python3.12 python3.11 python3.14 python3 python; do
        command -v "$candidate" >/dev/null 2>&1 || continue
        if _py_try "$candidate"; then return 0; fi
    done
    # Off-PATH probe: python.org framework installs and Homebrew prefixes
    # (Apple Silicon + Intel), including keg-only python@3.x kegs. Unmatched
    # globs stay literal and are filtered by the -x test; on Linux these
    # directories simply don't exist and the loop is a no-op.
    if [ -n "${JARVIS_PYTHON_SEARCH_DIRS:-}" ]; then
        # Colon-split without reading stdin, which still carries the piped
        # installer source in the public `curl | bash` path.
        _old_ifs=$IFS
        IFS=':'
        # shellcheck disable=SC2086 -- colon-splitting the override is the point
        set -- $JARVIS_PYTHON_SEARCH_DIRS
        IFS=$_old_ifs
        _probe_dirs=("$@")
    else
        _probe_dirs=(
            /opt/homebrew/bin
            /usr/local/bin
            /opt/homebrew/opt/python@3.*/bin
            /usr/local/opt/python@3.*/bin
            /Library/Frameworks/Python.framework/Versions/3.*/bin
        )
    fi
    for _dir in "${_probe_dirs[@]:-}"; do
        for _cand in "$_dir"/python3.1[1-9] "$_dir"/python3 "$_dir"/python; do
            [ -x "$_cand" ] || continue
            if _py_try "$_cand"; then return 0; fi
        done
    done
    return 1
}
# --- python-detection end ---------------------------------------------------

# --- prerequisite-bootstrap begin ------------------------------------------
# This block stays shell-native because Python may not exist yet. Tests extract
# it directly and exercise the retry/continuation state machine with fakes.
git_available() {
    _git_candidates=()
    _git_on_path=$(command -v git 2>/dev/null || true)
    if [ -n "$_git_on_path" ]; then _git_candidates+=("$_git_on_path"); fi
    _git_candidates+=(/opt/homebrew/bin/git /usr/local/bin/git /usr/bin/git)

    for _git_path in "${_git_candidates[@]}"; do
        [ -x "$_git_path" ] || continue
        # macOS ships a /usr/bin/git launcher even before the Command Line
        # Tools exist. Calling that launcher may open an unrelated system
        # dialog, so skip it and keep probing Homebrew's off-PATH locations.
        if [ "$(uname -s 2>/dev/null || true)" = 'Darwin' ] &&
           [ "$_git_path" = '/usr/bin/git' ] && command -v xcode-select >/dev/null 2>&1 &&
           ! xcode-select -p >/dev/null 2>&1; then
            continue
        fi
        "$_git_path" --version >/dev/null 2>&1 || continue
        _git_dir=${_git_path%/*}
        case ":$PATH:" in
            *":$_git_dir:"*) ;;
            *) PATH="$_git_dir:$PATH"; export PATH ;;
        esac
        return 0
    done
    return 1
}

# --- full-support Python bootstrap (maintainer mandate 2026-07-14) -----------
# The one-liner must leave NOTHING to install afterwards: when the host only
# offers a Python the native local-voice wheels do not cover yet (3.14+),
# fetch a self-contained CPython 3.13 via uv (per-user, no sudo) and use it
# for the venv — the speech pack then installs during THIS run.
_PY_BOOTSTRAP_TRIED=0
_PY_BOOTSTRAPPED=""

_bootstrap_target_version() {
    # Intel Macs: the native voice stack's last x86_64 wheels end at cp312
    # (ctranslate2/av; onnxruntime dropped Intel macOS entirely, BUG-061),
    # so 3.12 is the newest FULLY supported Python there. Everywhere else
    # 3.13 has complete wheel coverage.
    if [ "$(uname -s 2>/dev/null)" = "Darwin" ] && [ "$(uname -m 2>/dev/null)" = "x86_64" ]; then
        printf '3.12'
    else
        printf '3.13'
    fi
}

_py_full_support() {
    _mm=$("$1" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null) || return 1
    if [ "$(_bootstrap_target_version)" = "3.12" ]; then
        case "$_mm" in
            3.11|3.12) return 0 ;;
        esac
        return 1
    fi
    case "$_mm" in
        3.11|3.12|3.13) return 0 ;;
    esac
    return 1
}

bootstrap_full_support_python() {
    [ -n "${JARVIS_NO_PYTHON_BOOTSTRAP:-}" ] && return 1
    if [ -n "$_PY_BOOTSTRAPPED" ]; then
        PYTHON_EXE="$_PY_BOOTSTRAPPED"
        return 0
    fi
    [ "$_PY_BOOTSTRAP_TRIED" -eq 1 ] && return 1
    _PY_BOOTSTRAP_TRIED=1
    _uv=$(command -v uv 2>/dev/null || true)
    [ -z "$_uv" ] && [ -x "$HOME/.local/bin/uv" ] && _uv="$HOME/.local/bin/uv"
    if [ -z "$_uv" ]; then
        note "Fetching a self-contained Python $(_bootstrap_target_version) (per-user, no sudo)."
        run_spin 'Downloading the uv Python manager' \
            sh -c 'curl -LsSf https://astral.sh/uv/install.sh | UV_NO_MODIFY_PATH=1 sh' || return 1
        _uv="$HOME/.local/bin/uv"
        [ -x "$_uv" ] || return 1
    fi
    _target=$(_bootstrap_target_version)
    run_spin "Downloading Python $_target (about 30 MB)" \
        "$_uv" python install "$_target" || return 1
    _bp=$("$_uv" python find "$_target" 2>/dev/null) || return 1
    [ -x "$_bp" ] || return 1
    PYTHON_EXE="$_bp"
    _PY_BOOTSTRAPPED="$_bp"
    return 0
}

refresh_prerequisite_state() {
    PYTHON_EXE=""
    if find_python; then PYTHON_READY=1; else PYTHON_READY=0; fi
    # No Python at all: fetch the same per-user copy instead of asking for a
    # system package. It needs no sudo and changes nothing outside the user's
    # own folders, so there is nothing to ask about. The package-manager
    # prompt below stays the fallback when this download fails.
    if [ "$PYTHON_READY" -eq 0 ] && [ -z "${JARVIS_PYTHON:-}" ] \
        && [ "${PREREQUISITE_MODE:-ask}" != 'never' ]; then
        _first_fetch=0
        [ -z "$_PY_BOOTSTRAPPED" ] && _first_fetch=1
        if bootstrap_full_support_python; then
            PYTHON_READY=1
            if [ "$_first_fetch" -eq 1 ]; then
                ok "Fetched a self-contained Python $(_bootstrap_target_version) (per-user, no sudo)" "${UI_LAST_SECONDS:-}"
            fi
        fi
    fi
    # An explicit JARVIS_PYTHON pin is authoritative — never substituted.
    if [ "$PYTHON_READY" -eq 1 ] && [ -z "${JARVIS_PYTHON:-}" ] \
        && ! _py_full_support "$PYTHON_EXE"; then
        if bootstrap_full_support_python; then
            ok "Fetched a self-contained Python $(_bootstrap_target_version) (local voice fully supported)" "${UI_LAST_SECONDS:-}"
        else
            note 'No prebuilt local-voice packages for this Python yet: the core works,'
            note 'but the speech pack needs Python 3.11-3.13 (3.12 on Intel Macs).'
        fi
    fi
    if git_available; then GIT_READY=1; else GIT_READY=0; fi
    if [ "$PYTHON_READY" -eq 1 ] && [ "$GIT_READY" -eq 1 ]; then
        PREREQUISITES_READY=1
    else
        PREREQUISITES_READY=0
    fi
}

write_prerequisite_state() {
    _show_missing="${1:-0}"
    if [ "$PYTHON_READY" -eq 1 ]; then
        _py_ver=$("$PYTHON_EXE" -c 'import sys; print("Python %d.%d.%d" % sys.version_info[:3])' 2>/dev/null || printf '%s' "$PYTHON_EXE")
        ok "$_py_ver" '' "$PYTHON_EXE"
    elif [ "$_show_missing" -eq 1 ]; then
        err 'Python 3.11+ not found.'
        if [ -n "$FOUND_TOO_OLD" ]; then
            note "Closest match: $FOUND_TOO_OLD - too old: Dodaios needs 3.11+."
            note 'Python versions count 3.8 < 3.9 < 3.10 < 3.11.'
        fi
    fi
    if [ "$GIT_READY" -eq 1 ]; then
        _git_ver=$(git --version 2>/dev/null || printf 'git')
        _git_ver=${_git_ver#git version }
        ok "Git $_git_ver"
    elif [ "$_show_missing" -eq 1 ]; then
        err 'git not found.'
    fi
}

missing_prerequisite_labels() {
    _missing=""
    if [ "$PYTHON_READY" -eq 0 ]; then _missing='Python 3.11+'; fi
    if [ "$GIT_READY" -eq 0 ]; then
        if [ -n "$_missing" ]; then _missing="$_missing, Git"; else _missing='Git'; fi
    fi
    printf '%s' "$_missing"
}

has_install_tty() {
    { : </dev/tty; } 2>/dev/null && { : >/dev/tty; } 2>/dev/null
}

detect_prerequisite_manager() {
    PREREQ_MANAGER=""
    PREREQ_MANAGER_CMD=""
    case "$(uname -s 2>/dev/null || printf unknown)" in
        Darwin)
            for _brew in "$(command -v brew 2>/dev/null || true)" /opt/homebrew/bin/brew /usr/local/bin/brew; do
                if [ -n "$_brew" ] && [ -x "$_brew" ]; then
                    PREREQ_MANAGER='Homebrew'
                    PREREQ_MANAGER_CMD="$_brew"
                    return 0
                fi
            done
            ;;
        *)
            for _manager in apt-get dnf yum zypper pacman apk; do
                if command -v "$_manager" >/dev/null 2>&1; then
                    PREREQ_MANAGER="$_manager"
                    PREREQ_MANAGER_CMD="$_manager"
                    return 0
                fi
            done
            ;;
    esac
    return 1
}

request_prerequisite_consent() {
    _missing="$1"
    case "$PREREQUISITE_MODE" in
        auto)
            note 'Automatic prerequisite installation was enabled by JARVIS_INSTALL_PREREQS=auto.'
            return 0
            ;;
        never) return 1 ;;
        ask) ;;
        *)
            err "Invalid JARVIS_INSTALL_PREREQS value '$PREREQUISITE_MODE'. Use ask, auto, or never."
            return 1
            ;;
    esac
    if ! has_install_tty; then
        note 'This shell cannot ask for consent. Re-run interactively or set JARVIS_INSTALL_PREREQS=auto.'
        return 1
    fi

    note "Missing required software: $_missing."
    if [ -n "$PREREQ_MANAGER" ]; then
        note "Dodaios can install it with $PREREQ_MANAGER, wait, and continue this same run."
        note 'Continuing authorizes the package manager to accept the relevant package agreements.'
        _prompt='  Install the missing prerequisites now? [Y/n] '
    else
        note 'No supported package manager was found; Dodaios can keep this run open while you install it.'
        _prompt='  Show the manual path and keep checking this run? [Y/n] '
    fi
    printf '%s' "$_prompt" >/dev/tty
    IFS= read -r _answer </dev/tty || return 1
    case "$_answer" in ''|y|Y|yes|YES|Yes) return 0 ;; *) return 1 ;; esac
}

run_privileged() {
    # `curl | bash` makes stdin the remaining installer source. Package managers
    # must not consume it, even when they claim to be noninteractive.
    if [ "$(id -u)" -eq 0 ]; then
        "$@" </dev/null
    elif command -v sudo >/dev/null 2>&1; then
        sudo "$@" </dev/null
    else
        note 'Administrator access is required, but sudo is unavailable.'
        return 126
    fi
}

install_with_prerequisite_manager() {
    _python_ready="$1"
    _git_ready="$2"
    _log=$(mktemp "${TMPDIR:-/tmp}/jarvis-prerequisites.XXXXXX") || return 1
    _result=1

    case "$PREREQ_MANAGER" in
        Homebrew)
            _packages=()
            if [ "$_python_ready" -eq 0 ]; then _packages+=(python); fi
            if [ "$_git_ready" -eq 0 ]; then _packages+=(git); fi
            if "$PREREQ_MANAGER_CMD" install "${_packages[@]}" </dev/null >"$_log" 2>&1; then _result=0; fi
            ;;
        apt-get)
            _packages=()
            if [ "$_python_ready" -eq 0 ]; then _packages+=(python3 python3-venv); fi
            if [ "$_git_ready" -eq 0 ]; then _packages+=(git); fi
            if run_privileged env DEBIAN_FRONTEND=noninteractive apt-get update -qq >"$_log" 2>&1 &&
               run_privileged env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${_packages[@]}" >>"$_log" 2>&1; then
                _result=0
            fi
            ;;
        dnf|yum)
            _packages=()
            if [ "$_python_ready" -eq 0 ]; then _packages+=(python3); fi
            if [ "$_git_ready" -eq 0 ]; then _packages+=(git); fi
            if run_privileged "$PREREQ_MANAGER_CMD" -q -y install "${_packages[@]}" >"$_log" 2>&1; then _result=0; fi
            ;;
        zypper)
            _packages=()
            if [ "$_python_ready" -eq 0 ]; then _packages+=(python3); fi
            if [ "$_git_ready" -eq 0 ]; then _packages+=(git); fi
            if run_privileged zypper --non-interactive --quiet install "${_packages[@]}" >"$_log" 2>&1; then _result=0; fi
            ;;
        pacman)
            _packages=()
            if [ "$_python_ready" -eq 0 ]; then _packages+=(python); fi
            if [ "$_git_ready" -eq 0 ]; then _packages+=(git); fi
            if run_privileged pacman -Sy --noconfirm --needed "${_packages[@]}" >"$_log" 2>&1; then _result=0; fi
            ;;
        apk)
            _packages=()
            if [ "$_python_ready" -eq 0 ]; then _packages+=(python3 py3-pip); fi
            if [ "$_git_ready" -eq 0 ]; then _packages+=(git); fi
            if run_privileged apk add --no-progress "${_packages[@]}" >"$_log" 2>&1; then _result=0; fi
            ;;
    esac

    if [ "$_result" -eq 0 ]; then
        ok "$PREREQ_MANAGER finished installing prerequisites"
    else
        err "$PREREQ_MANAGER did not complete the prerequisite installation."
        tail -n 12 "$_log" 2>/dev/null || true
    fi
    rm -f "$_log"
    return "$_result"
}

start_manual_prerequisite_path() {
    write_manual_prerequisite_help
    if [ "$PYTHON_READY" -eq 0 ] &&
       [ "$(uname -s 2>/dev/null || true)" = 'Darwin' ] && command -v open >/dev/null 2>&1; then
        open 'https://www.python.org/downloads/macos/' >/dev/null 2>&1 || true
    fi
    if [ "$GIT_READY" -eq 0 ] &&
       [ "$(uname -s 2>/dev/null || true)" = 'Darwin' ] && command -v xcode-select >/dev/null 2>&1; then
        xcode-select --install >/dev/null 2>&1 || true
    fi
}

write_manual_prerequisite_help() {
    if [ "$PYTHON_READY" -eq 0 ]; then
        note 'Python: https://www.python.org/downloads/'
        note 'Linux: install Python 3.11+ plus its venv package from your distribution.'
        note 'Already installed somewhere unusual? Pin it for this run:'
        note '  curl -fsSL <this url> | JARVIS_PYTHON=/path/to/python3.12 bash'
    fi
    if [ "$GIT_READY" -eq 0 ]; then
        note 'Git:    https://git-scm.com/downloads'
    fi
}

install_missing_prerequisites() {
    detect_prerequisite_manager || true
    if [ -z "$PREREQ_MANAGER" ]; then
        start_manual_prerequisite_path
        return 1
    fi
    note "installing prerequisites with $PREREQ_MANAGER"
    install_with_prerequisite_manager "$PYTHON_READY" "$GIT_READY"
}

wait_for_prerequisites() {
    _attempt=0
    while [ "$_attempt" -lt 5 ]; do
        hash -r
        refresh_prerequisite_state
        if [ "$PREREQUISITES_READY" -eq 1 ]; then return 0; fi
        _attempt=$((_attempt + 1))
        if [ "$_attempt" -lt 5 ]; then sleep 2; fi
    done
    return 1
}

ensure_prerequisites() {
    refresh_prerequisite_state
    write_prerequisite_state 1
    if [ "$PREREQUISITES_READY" -eq 1 ]; then return 0; fi
    if [ -n "${JARVIS_PYTHON:-}" ] && [ "$PYTHON_READY" -eq 0 ]; then
        note "JARVIS_PYTHON is pinned to '$JARVIS_PYTHON' and is not a compatible interpreter."
        note 'Update or unset that pin before prerequisite installation.'
        return 1
    fi

    detect_prerequisite_manager || true
    _missing=$(missing_prerequisite_labels)
    if ! request_prerequisite_consent "$_missing"; then
        write_manual_prerequisite_help
        note 'Nothing was installed. Run this command again after adding the prerequisites.'
        return 1
    fi

    install_missing_prerequisites || true
    wait_for_prerequisites || true

    while [ "$PREREQUISITES_READY" -eq 0 ]; do
        err 'The required commands are still unavailable in this terminal.'
        write_manual_prerequisite_help
        if [ "$PREREQUISITE_MODE" = 'auto' ] || ! has_install_tty; then return 1; fi
        printf '%s' '  Finish any manual installer, then press Enter to re-check; R retries, Q stops: ' >/dev/tty
        IFS= read -r _answer </dev/tty || return 1
        case "$_answer" in
            q|Q|quit|QUIT|Quit) return 1 ;;
            r|R|retry|RETRY|Retry) install_missing_prerequisites || true ;;
        esac
        wait_for_prerequisites || true
    done

    write_prerequisite_state 0
    return 0
}
# Linux desktop-automation prerequisites (deep-dive 2026-07-15, H-01).
# Computer Use's window control on X11 is load-bearing on two small binaries
# the base install never provided: xdotool (foreground-window identity —
# without it every mission refuses with "cannot see the screen" before doing
# useful work) and wmctrl (focus / switch / maximize). The desktop window
# needs the distro GTK WebKit backend (python3-gi + WebKit GIR), and the
# OPTIONAL accessibility tree uses distro pyatspi. None of these are pip
# packages. Best-effort by design: a refusal or a failed package NEVER aborts
# the install — Computer Use degrades honestly at runtime and names what is
# missing. Skipped on --headless installs and when no graphical session is
# visible (a server has no desktop to automate).

linux_desktop_tool_packages() {
    # $1 = missing binaries ("xdotool wmctrl"), $2 = missing GI modules
    # ("gi webkit pyatspi"). Prints the distro package list for PREREQ_MANAGER.
    _pkgs=""
    for _bin in $1; do _pkgs="${_pkgs:+$_pkgs }$_bin"; done
    case "$PREREQ_MANAGER" in
        apt-get)
            case " $2 " in *" gi "*) _pkgs="${_pkgs:+$_pkgs }python3-gi" ;; esac
            # WebKit GIR is handled separately (4.1 with a 4.0 fallback).
            case " $2 " in *" pyatspi "*) _pkgs="${_pkgs:+$_pkgs }python3-pyatspi gir1.2-atspi-2.0" ;; esac
            ;;
        dnf|yum)
            case " $2 " in *" gi "*) _pkgs="${_pkgs:+$_pkgs }python3-gobject" ;; esac
            case " $2 " in *" webkit "*) _pkgs="${_pkgs:+$_pkgs }webkit2gtk4.1" ;; esac
            case " $2 " in *" pyatspi "*) _pkgs="${_pkgs:+$_pkgs }python3-pyatspi" ;; esac
            ;;
        zypper)
            case " $2 " in *" gi "*) _pkgs="${_pkgs:+$_pkgs }python3-gobject" ;; esac
            ;;
        pacman)
            case " $2 " in *" gi "*) _pkgs="${_pkgs:+$_pkgs }python-gobject" ;; esac
            case " $2 " in *" webkit "*) _pkgs="${_pkgs:+$_pkgs }webkit2gtk-4.1" ;; esac
            case " $2 " in *" pyatspi "*) _pkgs="${_pkgs:+$_pkgs }python-atspi" ;; esac
            ;;
        apk)
            case " $2 " in *" gi "*) _pkgs="${_pkgs:+$_pkgs }py3-gobject3" ;; esac
            case " $2 " in *" webkit "*) _pkgs="${_pkgs:+$_pkgs }webkit2gtk-4.1" ;; esac
            ;;
    esac
    printf '%s' "$_pkgs"
}

ensure_linux_desktop_tools() {
    [ "$(uname -s 2>/dev/null)" = "Linux" ] || return 0
    for _arg in "$@"; do
        if [ "$_arg" = "--headless" ]; then
            skip 'Desktop automation tools skipped (--headless).'
            return 0
        fi
    done
    if [ -z "${DISPLAY:-}" ] && [ -z "${WAYLAND_DISPLAY:-}" ]; then
        skip 'No graphical session detected - skipping the desktop automation tools.'
        note 'On an X11 desktop, window control needs xdotool + wmctrl (e.g. apt install xdotool wmctrl).'
        return 0
    fi

    _missing_bins=""
    command -v xdotool >/dev/null 2>&1 || _missing_bins='xdotool'
    command -v wmctrl >/dev/null 2>&1 || _missing_bins="${_missing_bins:+$_missing_bins }wmctrl"

    # GI modules are checked against the SYSTEM python3: the Linux venv links
    # to system site-packages (phase 3), so distro visibility is what counts.
    _missing_gi=""
    _sys_py=$(command -v python3 2>/dev/null || true)
    if [ -n "$_sys_py" ]; then
        "$_sys_py" -c 'import gi' >/dev/null 2>&1 || _missing_gi='gi'
        if ! "$_sys_py" -c 'import gi; gi.require_version("WebKit2", "4.1")' >/dev/null 2>&1 &&
           ! "$_sys_py" -c 'import gi; gi.require_version("WebKit2", "4.0")' >/dev/null 2>&1; then
            _missing_gi="${_missing_gi:+$_missing_gi }webkit"
        fi
        "$_sys_py" -c 'import pyatspi' >/dev/null 2>&1 || _missing_gi="${_missing_gi:+$_missing_gi }pyatspi"
    fi

    if [ -z "$_missing_bins" ] && [ -z "$_missing_gi" ]; then
        ok 'Desktop automation tools present (xdotool, wmctrl, webview, accessibility)'
        return 0
    fi

    detect_prerequisite_manager || true
    if [ -z "$PREREQ_MANAGER" ]; then
        note "Desktop automation tools missing: $_missing_bins $_missing_gi"
        note 'No supported package manager found - install xdotool + wmctrl manually for window control.'
        return 0
    fi

    _consent=0
    case "$PREREQUISITE_MODE" in
        auto) _consent=1 ;;
        never) ;;
        *)
            if has_install_tty; then
                note "Optional desktop tools for window control are missing: $_missing_bins $_missing_gi"
                note "Without them, asking Dodaios to click / type / switch windows cannot work on X11."
                printf '  Install them now with %s? [Y/n] ' "$PREREQ_MANAGER" >/dev/tty
                IFS= read -r _answer </dev/tty || _answer='n'
                case "$_answer" in ''|y|Y|yes|YES|Yes) _consent=1 ;; esac
            else
                note 'This shell cannot ask for consent - skipping the optional desktop tools.'
            fi
            ;;
    esac
    if [ "$_consent" -eq 0 ]; then
        skip 'Window-control tools skipped; add them any time, e.g.: sudo apt install xdotool wmctrl'
        return 0
    fi

    _pkgs=$(linux_desktop_tool_packages "$_missing_bins" "$_missing_gi")
    _dt_log=$(mktemp "${TMPDIR:-/tmp}/jarvis-desktop-tools.XXXXXX") || return 0
    _dt_ok=1
    if [ -n "$_pkgs" ]; then
        case "$PREREQ_MANAGER" in
            apt-get)
                # shellcheck disable=SC2086 — word splitting is intentional
                if run_privileged env DEBIAN_FRONTEND=noninteractive apt-get update -qq >"$_dt_log" 2>&1 &&
                   run_privileged env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq $_pkgs >>"$_dt_log" 2>&1; then
                    _dt_ok=0
                fi
                # WebKit GIR: package name differs across releases; try 4.1 then 4.0.
                case " $_missing_gi " in
                    *" webkit "*)
                        run_privileged env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq gir1.2-webkit2-4.1 >>"$_dt_log" 2>&1 ||
                            run_privileged env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq gir1.2-webkit2-4.0 >>"$_dt_log" 2>&1 || true
                        ;;
                esac
                ;;
            dnf|yum)
                # shellcheck disable=SC2086
                if run_privileged "$PREREQ_MANAGER_CMD" -q -y install $_pkgs >"$_dt_log" 2>&1; then _dt_ok=0; fi
                ;;
            zypper)
                # shellcheck disable=SC2086
                if run_privileged zypper --non-interactive --quiet install $_pkgs >"$_dt_log" 2>&1; then _dt_ok=0; fi
                ;;
            pacman)
                # shellcheck disable=SC2086
                if run_privileged pacman -Sy --noconfirm --needed $_pkgs >"$_dt_log" 2>&1; then _dt_ok=0; fi
                ;;
            apk)
                # shellcheck disable=SC2086
                if run_privileged apk add --no-progress $_pkgs >"$_dt_log" 2>&1; then _dt_ok=0; fi
                ;;
        esac
    fi
    if [ "$_dt_ok" -eq 0 ]; then
        ok 'desktop automation tools installed'
    else
        note 'Some desktop tools could not be installed - continuing; window control may be limited.'
        tail -n 6 "$_dt_log" 2>/dev/null || true
    fi
    rm -f "$_dt_log"
    return 0
}

# --- prerequisite-bootstrap end --------------------------------------------

if ! ensure_prerequisites; then
    err 'Prerequisite setup was not completed.'
    exit 1
fi

ensure_linux_desktop_tools "$@"

# Node.js 18+ — powers only the OPTIONAL agent worker CLIs (Claude Code
# / Codex) that heavy missions delegate to, plus the Node-based marketplace
# integrations. Everything else in Dodaios runs without it, so a missing Node
# must NEVER turn a new user away at the door: we note it and continue — the
# worker CLI can be added later in-app once Node is installed. Skipped
# entirely on the headless / tiny-VPS path (--headless): a cloud-only base
# install that never spawns a local CLI worker.
skip_node=0
for arg in "$@"; do
    if [ "$arg" = "--headless" ]; then skip_node=1; break; fi
done
if [ "$skip_node" -eq 1 ]; then
    skip 'Node.js check skipped (--headless): the cloud-only base install does not use it.'
else
    node_ok=0
    if command -v node >/dev/null 2>&1; then
        # `|| node_major=""` is load-bearing: under `set -e` + `pipefail` a
        # node that EXISTS but exits non-zero kills the whole installer right
        # here, silently, two phases before the end. `command -v` only proves
        # the name resolves - an asdf/volta/nvm shim with no version selected
        # (126), an x86_64 binary on arm64 (126), or a Gatekeeper-killed one
        # (137) all pass that test and then fail. Node is OPTIONAL, so a
        # broken one must degrade to "not found", never abort the install.
        node_major=$(node --version 2>/dev/null | sed -E 's/^v?([0-9]+).*/\1/') || node_major=""
        if [ -n "$node_major" ] && [ "$node_major" -ge 18 ] 2>/dev/null; then
            node_ok=1
        fi
    fi
    if [ "$node_ok" -eq 1 ]; then
        ok "Node.js $(node --version)"
    else
        skip 'Node.js 18+ not found: optional, Dodaios runs fine without it.'
        note 'It only powers the optional coding-agent worker (Claude Code / Codex).'
        note 'Install it any time ("brew install node" / https://nodejs.org/) and'
        note 'add the worker later in the app.'
    fi
fi

# -------------------------------------------------------------- clone / update
phase '2/6' 'Download'

# On a terminal, git paints its own "Receiving objects: NN%" progress so a
# slow download never looks hung (maintainer report 2026-07-15); a piped/CI
# run keeps --quiet for a clean log. Errors surface on stderr either way.
GIT_VERBOSITY='--quiet'
[ -t 2 ] && GIT_VERBOSITY='--progress'

# The payload is a single ~80 MB stream and git cannot resume a clone, so a
# flaky network kills installs two ways (maintainer's Mac, 2026-07-18:
# "Receiving objects: 45%" frozen for minutes, then "early EOF" /
# "unexpected disconnect while reading sideband packet"):
#   1. a stalled stream hangs silently -> low-speed limits turn that into a
#      fast, visible failure (under 1 KB/s for 30 s = dead connection);
#   2. a mid-transfer disconnect aborts the install -> retry a clean clone
#      up to 3 times before giving up with an honest message.
GIT_NET_OPTS='-c http.lowSpeedLimit=1024 -c http.lowSpeedTime=30'
# An install never downloads Git LFS objects: older releases carry LFS
# pointers for large binaries, and a ref pinned to one must not pull those.
GIT_LFS_SKIP_SMUDGE=1
export GIT_LFS_SKIP_SMUDGE

# Restyle git's raw transfer chatter into the installer's visual grammar
# (maintainer request 2026-07-18: phases 1-2 look polished, then raw
# "Cloning into ... / remote: Enumerating ..." breaks the look). Pure
# bookkeeping lines are dropped, live progress becomes ONE self-redrawing
# line with a bar (percent, volume and speed stay visible), and every
# error/unknown line still comes through - restyled, never swallowed.
git_stream_pretty() {
    if [ "$UI_COLOR" = 'none' ]; then _git_track='-'; else _git_track=$G_BAR; fi
    [ "$UI_GLYPHS" = 'full' ] && [ "$UI_COLOR" = 'none' ] && _git_track='─'
    # Records end at a carriage return (git redraws its progress with \r) and
    # each one is split on newlines here, in awk itself: a `tr` in front
    # would hold the stream in its pipe buffer and the bar would stall.
    awk -v RS='\r' -v gold="$C_GOLD" -v muted="$C_MUTED" -v bad="$C_BAD" -v rst="$C_RST" \
        -v rail="$G_RAIL" -v fill="$G_BAR" -v track="$_git_track" -v frames="${UI_SPIN_FRAMES[*]}" '
        BEGIN { nframes = split(frames, frame, " ") }
        function endlive() { if (live) { printf "\r\033[K"; live = 0 } }
        function liveline(label, line,   pct, extra, n, done_, i, bar, rest) {
            pct = 0
            if (match(line, /[0-9]+%/)) pct = substr(line, RSTART, RLENGTH - 1) + 0
            extra = ""
            if (match(line, /[0-9.]+ [KMGT]?iB \| [0-9.]+ [KMGT]?iB\/s/)) {
                extra = substr(line, RSTART, RLENGTH)
                sub(/ \| /, "  ", extra)
            }
            n = 24
            done_ = int(pct * n / 100)
            bar = ""; for (i = 0; i < done_; i++) bar = bar fill
            rest = ""; for (i = done_; i < n; i++) rest = rest track
            tick++
            printf "\r\033[K     %s%s%s  %-13s %s%s%s%s%s  %3d%%  %s%s%s", gold, frame[(tick % nframes) + 1], rst, label, gold, bar, muted, rest, rst, pct, muted, extra, rst
            fflush(); live = 1
        }
        function one(line) {
            if (line == "" || line ~ /^(Cloning into|remote: (Enumerating|Total)|Checking connectivity)/) return
            if (line ~ /^remote: (Counting|Compressing) objects:/) { liveline("Preparing", line); return }
            if (line ~ /^Receiving objects:/) { liveline("Downloading", line); return }
            if (line ~ /^Resolving deltas:/) { liveline("Unpacking", line); return }
            if (line ~ /^Updating files:/) { liveline("Writing files", line); return }
            endlive()
            if (line ~ /^(error|fatal):/) printf "     %s%s%s  %s\n", bad, rail, rst, line
            else printf "        %s%s%s\n", muted, line, rst
            fflush()
        }
        { n = split($0, part, "\n"); for (i = 1; i <= n; i++) one(part[i]) }
        END { endlive() }
    ' >&2
}

# On a TTY, run the git command through the restyler; piped/CI runs keep
# the plain --quiet transcript. Callers pass "$GIT_VERBOSITY" as usual -
# the pipe preserves the git exit code via PIPESTATUS (this is bash).
pretty_git() {
    if [ "$GIT_VERBOSITY" = '--progress' ]; then
        "$@" </dev/null 2>&1 | git_stream_pretty
        return "${PIPESTATUS[0]}"
    fi
    "$@" </dev/null
}

# --- install-ref begin (extracted by tests/unit/install/test_install_ref.py)
# Without JARVIS_INSTALL_REF an install follows the newest published release,
# the same thing the in-app updater moves to. A release tag carries the
# frontend bundle built from its own sources; main does not have to. main is
# the fallback when the release cannot be looked up (offline API, a fork
# without releases, no curl).
resolve_install_ref() {
    [ -n "$BRANCH" ] && return 0
    BRANCH=main
    command -v curl >/dev/null 2>&1 || return 0
    case "$REPO_URL" in
        *github.com/*) ;;
        *) return 0 ;;
    esac
    _ref_slug="${REPO_URL#*github.com/}"
    _ref_slug="${_ref_slug%.git}"
    _ref_tag="$(curl -fsSL --max-time 20 -H 'Accept: application/vnd.github+json' \
        "${INSTALLER_TEST_RELEASE_API:-https://api.github.com}/repos/$_ref_slug/releases/latest" 2>/dev/null \
        | sed -n 's/^[[:space:]]*"tag_name":[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1)" || _ref_tag=''
    if printf '%s' "$_ref_tag" | grep -Eq '^v[0-9]+\.[0-9]+\.[0-9]+$'; then
        BRANCH="$_ref_tag"
    fi
}

# codeload path of the ref: a release tag or a branch.
ref_archive_path() {
    case "$BRANCH" in
        v[0-9]*) printf 'refs/tags/%s' "$BRANCH" ;;
        *) printf 'refs/heads/%s' "$BRANCH" ;;
    esac
}
# --- install-ref end

clone_with_retry() {
    note 'About 80 MB: a few minutes on a slow connection.'
    _attempt=1
    while :; do
        # Attempt 1 uses git's default transport; later attempts force
        # HTTP/1.1 - the known cure for a family of "RPC failed; curl 28 /
        # early EOF" aborts that only bite the bulk pack stream while small
        # requests sail through (observed on the test Mac, 2026-07-18).
        _http_mode=''
        [ "$_attempt" -gt 1 ] && _http_mode='-c http.version=HTTP/1.1'
        # shellcheck disable=SC2086  # GIT_NET_OPTS/_http_mode word-split into -c pairs
        if pretty_git git $GIT_NET_OPTS $_http_mode clone "$GIT_VERBOSITY" --depth 1 --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR"; then
            return 0
        fi
        rm -rf "$INSTALL_DIR" 2>/dev/null || true
        if [ "$_attempt" -ge 3 ]; then
            warn 'git could not finish the download on this network (3 attempts).'
            return 1
        fi
        _attempt=$((_attempt + 1))
        warn "The download did not finish: retrying ($_attempt/3, compatibility transfer mode)."
        sleep 3
    done
}

# Last-resort transport when git cannot get the pack through AT ALL: a plain
# HTTPS archive download. The release asset (uploaded per release) supports
# HTTP ranges, so `curl -C -` RESUMES after every disconnect - even a
# crawling connection eventually finishes, which a restarted git clone never
# does. Falls back to the branch snapshot (codeload, not resumable) when no
# release asset is reachable. The tree lands WITHOUT .git metadata; the next
# installer run detects that and repairs it in place (salvage path), so
# updates keep working.
tarball_fallback() {
    command -v curl >/dev/null 2>&1 || return 1
    command -v tar >/dev/null 2>&1 || return 1
    case "$REPO_URL" in
        *github.com/*) ;;
        *) return 1 ;;
    esac
    _repo_path="${REPO_URL#*github.com/}"
    _repo_path="${_repo_path%.git}"
    _asset_base="https://github.com/$_repo_path/releases/latest/download"
    # The archive's current name first; releases cut before the rename only
    # carry the earlier one.
    _asset_names='dodaios-src.tar.gz personal-jarvis-src.tar.gz'
    _snapshot_url="https://codeload.github.com/$_repo_path/tar.gz/$(ref_archive_path)"
    if [ -n "${JARVIS_PAYLOAD_COMMIT:-}" ]; then
        # A verified install is pinned to ONE signed commit; the "latest"
        # release asset cannot honor that pin, so go straight to the
        # commit-addressed snapshot - the URL itself names the exact tree.
        _asset_names=''
        _snapshot_url="https://codeload.github.com/$_repo_path/tar.gz/$JARVIS_PAYLOAD_COMMIT"
    fi
    _tmp="${INSTALL_DIR%/}.payload.tar.gz"
    warn 'The git transfer keeps stalling on this network: switching to a resumable archive download.'
    _got=''
    for _asset_name in $_asset_names; do
        # A partial download of one archive must never be resumed as another.
        rm -f "$_tmp" 2>/dev/null || true
        _try=1
        while [ "$_try" -le 8 ]; do
            _rc=0
            curl -fL -# --speed-limit 1024 --speed-time 60 -C - -o "$_tmp" \
                "$_asset_base/$_asset_name" || _rc=$?
            if [ "$_rc" -eq 0 ]; then
                _got=1
                break
            fi
            # 22 = HTTP error (this archive is not on the release): try the next name.
            if [ "$_rc" -eq 22 ]; then break; fi
            note "archive download interrupted - resuming where it stopped ($_try/8) ..."
            _try=$((_try + 1))
            sleep 3
        done
        if [ -n "$_got" ]; then break; fi
    done
    if [ -z "$_got" ]; then
        rm -f "$_tmp" 2>/dev/null || true
        note 'no resumable release archive reachable - trying the direct snapshot (single stream)'
        curl -fL -# --speed-limit 1024 --speed-time 60 -o "$_tmp" "$_snapshot_url" || {
            rm -f "$_tmp" 2>/dev/null || true
            return 1
        }
    fi
    rm -rf "$INSTALL_DIR" 2>/dev/null || true
    mkdir -p "$INSTALL_DIR"
    if ! tar -xzf "$_tmp" -C "$INSTALL_DIR" --strip-components=1; then
        rm -f "$_tmp" 2>/dev/null || true
        return 1
    fi
    rm -f "$_tmp" 2>/dev/null || true
    note 'installed from the release archive (git metadata is repaired on a future update)'
    return 0
}

fetch_payload() {
    if clone_with_retry || tarball_fallback; then
        return 0
    fi
    err 'The download kept failing (the connection dropped mid-transfer).'
    note 'Check your internet connection (Wi-Fi, VPN, proxy), then run the installer'
    note 'again. It is safe to re-run and picks up where it makes sense.'
    return 1
}

# Self-heal a broken install dir (leftover non-git folder from an earlier or
# aborted install, or a checkout whose git state no longer updates): keep the
# old tree as a timestamped sibling backup — never delete — clone fresh, then
# carry the user's local state (data/, the config file, .env) into the new
# checkout. A stale folder must never require manual cleanup to install.
salvage_reclone() {
    local stale_backup
    # --- salvage-guard begin (extracted by tests/unit/install/test_install_stops_app_first.py)
    # Nothing is stopped or moved until the download server answers. Without a
    # connection the fresh copy cannot arrive, and an install that was moved
    # aside for nothing is worse than one that simply was not updated.
    # git is asked first. A network that lets no git transfer through still
    # reaches the archive download the installer falls back to, so a plain
    # HTTPS answer from the same host counts as well.
    _reachable=0
    # shellcheck disable=SC2086  # GIT_NET_OPTS must word-split into -c pairs
    if git $GIT_NET_OPTS ls-remote --quiet --heads "$REPO_URL" >/dev/null 2>&1; then
        _reachable=1
    else
        case "$REPO_URL" in
            *github.com/*)
                _probe_path="${REPO_URL#*github.com/}"
                if command -v curl >/dev/null 2>&1 \
                    && curl -fsIL --max-time 20 "https://github.com/${_probe_path%.git}" >/dev/null 2>&1; then
                    _reachable=1
                fi
                ;;
        esac
    fi
    if [ "$_reachable" -ne 1 ]; then
        err 'Cannot reach the download server right now; nothing was changed.'
        note 'Check your internet connection (Wi-Fi, VPN, proxy), then re-run the installer.'
        exit 1
    fi
    stop_running_app
    # --- salvage-guard end
    stale_backup="${INSTALL_DIR%/}.stale-$(date +%Y%m%d-%H%M%S)"
    if ! mv "$INSTALL_DIR" "$stale_backup"; then
        err "Cannot move the broken install folder aside ($INSTALL_DIR -> $stale_backup)."
        note 'Close any program using that folder (or move it yourself), then re-run.'
        exit 1
    fi
    note "moved the old directory to $stale_backup (nothing was deleted)"
    fetch_payload || exit 1
    # Everything a user can lose: config, credentials file-fallback + DBs
    # (inside data/), the dotenv, AND the wiki vault (its absence from this
    # list is what destroyed a user's wiki pages on 2026-07-20). A failed
    # copy is a loud warning pointing at the backup dir — never silent.
    # NOTE: a "skip when the destination exists" guard is WRONG for wiki —
    # the fresh clone ships a tracked seed wiki/ skeleton, so the guard
    # would silently never restore the user's real vault. Directories that
    # exist on both sides are overlay-MERGED (user files win over seed).
    # --- salvage-copy begin (extracted by tests/unit/install/test_install_salvage_copy.py)
    local item
    for item in data "$LEGACY_CONFIG_FILE_NAME" "$CONFIG_FILE_NAME" .env wiki; do
        [ -e "$stale_backup/$item" ] || continue
        if [ ! -e "$INSTALL_DIR/$item" ]; then
            if cp -R "$stale_backup/$item" "$INSTALL_DIR/$item"; then
                note "kept your $item from the previous install"
            else
                err "could NOT carry over $item - it is still safe in $stale_backup/$item; copy it back manually."
            fi
        elif [ -d "$stale_backup/$item" ] && [ -d "$INSTALL_DIR/$item" ]; then
            if cp -R "$stale_backup/$item/." "$INSTALL_DIR/$item/"; then
                note "merged your $item from the previous install over the fresh seed"
            else
                err "could NOT merge $item - it is still safe in $stale_backup/$item; copy it back manually."
            fi
        fi
    done
    # --- salvage-copy end
    ok 'Reinstalled fresh (your previous state is kept in the backup folder)'
}

# A checkout cloned before the GitHub rename still stores the old origin. Git
# fetches through GitHub's redirect, but the in-app updater identifies a managed
# install by this remote, so an untouched one loses its Update button. Only the
# stock repository is retargeted; an explicit repository override is left alone.
retarget_legacy_origin() {
    # --- retarget-legacy-origin begin
    if [ -z "${JARVIS_INSTALL_REPO:-}" ] && [ -z "${JARVIS_OFFICIAL_REPO_SLUG:-}" ]; then
        _origin="$(git -C "$INSTALL_DIR" config --get remote.origin.url 2>/dev/null || true)"
        _origin="$(printf '%s' "$_origin" | tr '[:upper:]' '[:lower:]')"
        _origin="${_origin%/}"
        _origin="${_origin%.git}"
        _legacy="$(printf '%s' "$LEGACY_OFFICIAL_REPO_SLUG" | tr '[:upper:]' '[:lower:]')"
        case "$_origin" in
            *github.com[:/]"$_legacy")
                if git -C "$INSTALL_DIR" remote set-url origin "$REPO_URL"; then
                    note 'pointed this install at the renamed repository'
                else
                    note 'could not update the stored repository address - continuing'
                fi
                ;;
        esac
    fi
    # --- retarget-legacy-origin end
}

# Stop any Dodaios still running out of THIS install. Called right before the
# checkout is replaced and again before its environment is rebuilt: a release
# may move or delete files the live app still loads, and an app left running
# across that keeps serving a half-old, half-new program until it falls over.
# Safe to call twice - the second call finds nothing left to stop.
#
# The installer refuses to do this to itself. Started from a terminal inside
# the app, its own parents run out of this install's environment; stopping
# them would end the installer mid-way with the app gone and nothing
# installed. It stops BEFORE anything was touched and says where to run it.
stop_running_app() {
    # --- stop-running-app begin (extracted by tests/unit/install/test_install_stops_app_first.py)
    _stop_venv="$INSTALL_DIR/.venv"
    if [ -x "$_stop_venv/bin/python" ]; then
        _stop_pid=$$
        _stop_depth=0
        while [ -n "$_stop_pid" ] && [ "$_stop_pid" -gt 1 ] 2>/dev/null && [ "$_stop_depth" -lt 32 ]; do
            # -ww: BSD ps cuts the command line at the terminal width, and
            # the stop below matches against the whole of it.
            _stop_args="$(ps -ww -o args= -p "$_stop_pid" 2>/dev/null || true)"
            case "$_stop_args" in
                *"$_stop_venv"*)
                    err 'this installer was started from inside the running app.'
                    note 'Updating stops the app, which would end this installer with it.'
                    note 'Nothing was changed. Run the install command again from a normal'
                    note 'terminal outside the app.'
                    exit 1
                    ;;
            esac
            _stop_parent="$(ps -o ppid= -p "$_stop_pid" 2>/dev/null | tr -d ' ' || true)"
            [ "$_stop_parent" = "$_stop_pid" ] && break
            _stop_pid="$_stop_parent"
            _stop_depth=$((_stop_depth + 1))
        done
        _stop_found=0
        if pkill -f "$_stop_venv" 2>/dev/null; then
            _stop_found=1
            note 'stopped the running Dodaios app for the update'
        fi
        if [ "$(uname -s 2>/dev/null)" = "Darwin" ]; then
            launchctl unload "$HOME/Library/LaunchAgents/${MACOS_AUTOSTART_LABEL}.plist" >/dev/null 2>&1 || true
        fi
        if [ "$_stop_found" -eq 1 ]; then
            # The signal only asks. Give the app a moment to be gone before
            # its files change under it; an app that ignores it is not waited
            # for longer than five seconds.
            _stop_ticks=0
            while [ "$_stop_ticks" -lt 50 ] && pgrep -f "$_stop_venv" >/dev/null 2>&1; do
                sleep 0.1
                _stop_ticks=$((_stop_ticks + 1))
            done
        fi
    fi
    # --- stop-running-app end
    return 0
}

# Move an install made under the earlier directory name to the current one.
# It runs once the app is stopped and before the checkout changes: nothing
# runs out of the directory, and the release about to be checked out is the
# one that knows the new name. The engine is that release's own copy, read
# from the fetched commit into a temporary file outside both directories and
# run isolated (-I), without writing bytecode (-B), from the home directory.
# It renames once and leaves a link at the old path, or changes nothing; the
# directory it reports is where the update goes on. Any failure goes on in
# place: an install under the earlier name is a valid state, not a broken one.
migrate_install_dir() {
    # --- migrate-install-dir begin (extracted by tests/unit/install/test_install_dir_move.py)
    [ "$MIGRATE_LEGACY_INSTALL_DIR" = 1 ] || return 0
    MIGRATE_LEGACY_INSTALL_DIR=0
    _mig_engine="$(mktemp "${TMPDIR:-/tmp}/dodaios-identity-migration.XXXXXX" 2>/dev/null)" || return 0
    _mig_report=''
    if git -C "$INSTALL_DIR" show "FETCH_HEAD:$IDENTITY_ENGINE_PATH" \
        </dev/null >"$_mig_engine" 2>/dev/null && [ -s "$_mig_engine" ]; then
        _mig_report="$(cd "$HOME" && "$PYTHON_EXE" -I -B "$_mig_engine" migrate \
            "$LEGACY_INSTALL_DIR" "$CURRENT_INSTALL_DIR" </dev/null 2>/dev/null)" || _mig_report=''
    fi
    rm -f "$_mig_engine"
    # One JSON object; Python reads it, so no path spelling can confuse a shell parser.
    _mig_parsed="$(printf '%s' "$_mig_report" | "$PYTHON_EXE" -I -B -c \
        'import json, sys; r = json.load(sys.stdin); print(r["outcome"]); print(r["effective"])' \
        2>/dev/null | tr -d '\r')" || _mig_parsed=''
    _mig_nl='
'
    _mig_outcome="${_mig_parsed%%"$_mig_nl"*}"
    _mig_dir="${_mig_parsed#*"$_mig_nl"}"
    if [ -z "$_mig_parsed" ] || [ "$_mig_outcome" = "$_mig_parsed" ] || [ ! -d "$_mig_dir" ]; then
        note "kept the install in $INSTALL_DIR (the move to $CURRENT_INSTALL_DIR did not run)"
        return 0
    fi
    case "$_mig_outcome" in
        migrated|link_restored|already_linked)
            note "moved the install to $_mig_dir (the old folder name still leads there)"
            ;;
        migrated_without_link)
            note "moved the install to $_mig_dir"
            ;;
        *)
            note "kept the install in $_mig_dir (it could not be renamed: $_mig_outcome)"
            ;;
    esac
    INSTALL_DIR="$_mig_dir"
    # --- migrate-install-dir end
    return 0
}

resolve_install_ref
note "Release $BRANCH into $INSTALL_DIR"
_fetch_t0=$SECONDS

# The fetch only writes inside .git, so the app keeps running through it: a
# failed download (offline, an outage) then leaves a working app behind. It is
# stopped at the last moment, right before the files it runs from change.
if [ -d "$INSTALL_DIR/.git" ]; then
    retarget_legacy_origin
    # shellcheck disable=SC2086  # GIT_NET_OPTS must word-split into -c pairs
    if pretty_git git $GIT_NET_OPTS -C "$INSTALL_DIR" fetch "$GIT_VERBOSITY" --depth 1 origin "$BRANCH" \
        && stop_running_app \
        && migrate_install_dir \
        && git -C "$INSTALL_DIR" checkout --quiet --detach FETCH_HEAD \
        && git -C "$INSTALL_DIR" reset --quiet --hard FETCH_HEAD; then
        ok "Updated the install to $BRANCH" $((SECONDS - _fetch_t0))
    else
        note 'existing checkout would not update (broken git state) - reinstalling in place.'
        salvage_reclone
    fi
elif [ -e "$INSTALL_DIR" ]; then
    note "$INSTALL_DIR exists but is not a git repo (leftover from an earlier install) - reinstalling in place."
    salvage_reclone
else
    fetch_payload || exit 1
    ok "Downloaded Dodaios $BRANCH" $((SECONDS - _fetch_t0))
fi

# WAVE 5 — payload-commit pin (axis E, Wave-5 audit Finding 2).
#
# install-verify.sh exports JARVIS_PAYLOAD_COMMIT containing the signed
# payload commit SHA (Wave 1+2+4-authenticated). If set, we bind the
# cloned tree to that exact commit so an attacker who flips `main` post-
# release cannot influence what we install. The signed SHA may be 40-char
# (git SHA-1) or 64-char (git SHA-256 repos).
if [ -n "${JARVIS_PAYLOAD_COMMIT:-}" ]; then
    if ! printf '%s' "$JARVIS_PAYLOAD_COMMIT" | grep -Eq '^[0-9a-f]{40}([0-9a-f]{24})?$'; then
        err "JARVIS_PAYLOAD_COMMIT is not a well-formed git SHA: '$JARVIS_PAYLOAD_COMMIT' — refusing."
        exit 1
    fi
    if [ ! -d "$INSTALL_DIR/.git" ]; then
        # Tarball-fallback install: the tree was fetched from the commit-
        # addressed archive URL, so the pin is embedded in the download
        # itself; there are no git objects to re-verify against.
        ok "pinned via commit-addressed archive (${JARVIS_PAYLOAD_COMMIT%"${JARVIS_PAYLOAD_COMMIT#????????????}"}…)"
    else
    # Shallow clones don't carry the full history; deepen to retrieve the
    # target SHA explicitly. `fetch <sha>` succeeds on most modern
    # github.com hosts (allowReachableSHA1InWant + uploadpack.allowAnySHA1InWant
    # are server defaults). Falls back to unshallow if direct-SHA fetch fails.
    if ! git -C "$INSTALL_DIR" fetch --quiet --depth 1 origin "$JARVIS_PAYLOAD_COMMIT" 2>/dev/null; then
        git -C "$INSTALL_DIR" fetch --quiet --unshallow origin || git -C "$INSTALL_DIR" fetch --quiet origin
    fi
    if ! git -C "$INSTALL_DIR" checkout --quiet --detach "$JARVIS_PAYLOAD_COMMIT"; then
        err "failed to checkout payload-commit ${JARVIS_PAYLOAD_COMMIT} — refusing."
        note 'the cloned tree does not contain the signed commit; release may be inconsistent.'
        exit 1
    fi
    # Defensive verify: assert HEAD is exactly the signed SHA byte-for-byte.
    ACTUAL_HEAD=$(git -C "$INSTALL_DIR" rev-parse HEAD)
    if [ "$ACTUAL_HEAD" != "$JARVIS_PAYLOAD_COMMIT" ]; then
        err "HEAD drift detected: pinned=${JARVIS_PAYLOAD_COMMIT}, actual=${ACTUAL_HEAD} — refusing."
        exit 1
    fi
        ok "pinned to signed commit ${JARVIS_PAYLOAD_COMMIT:0:12}…"
    fi
fi

# -------------------------------------------------------------- venv + bootstrap deps
phase '3/6' 'Python environment'

VENV_PATH="$INSTALL_DIR/.venv"
VENV_PYTHON="$VENV_PATH/bin/python"

# Update runs: stop any Dodaios still running out of THIS install before we
# touch its environment. A live app (often revived by the login autostart)
# keeps serving stale, half-updated features while pip rewrites the venv
# under it — the "app is already open but nothing works yet" field report
# (2026-07-14). The installer relaunches a fresh instance as its last step.
# The app was already stopped once before the checkout was replaced; this
# second call catches one the login autostart revived in between.
stop_running_app

# Rebuild the venv when the selected interpreter's major.minor changed
# (BUG-059 follow-up): the 3.13-first preference is useless for an EXISTING
# install whose venv is pinned to 3.14 — a stale venv keeps the local-voice
# wheel gap forever. Packages are reinstalled by the installer right after,
# so dropping the env loses nothing.
if [ -x "$VENV_PYTHON" ]; then
    _venv_mm=$("$VENV_PYTHON" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || printf 'unknown')
    _sel_mm=$("$PYTHON_EXE" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || printf 'selected')
    if [ "$_venv_mm" != "$_sel_mm" ]; then
        note "rebuilding the Python environment (Python $_venv_mm -> $_sel_mm)"
        rm -rf "$VENV_PATH"
    fi
fi
# Linux DESKTOP venvs include system site-packages (deep-dive 2026-07-15,
# H-01): the GTK webview backend (python3-gi) and the optional accessibility
# tree (pyatspi) are GObject-Introspection DISTRO packages that pip cannot
# install and an isolated venv cannot import. A --headless install uses
# neither, and linking the host's site-packages made pip treat whatever the
# host had installed (fastapi, uvicorn, opentelemetry, ...) as "already
# satisfied", so the server ran on host versions instead of the lockfile
# (#456) and `pip check` failed on host-only conflicts (#1018). Headless venvs
# therefore stay isolated. An existing venv whose setting does not match the
# profile is rebuilt once; packages are reinstalled by the installer right
# after, so nothing is lost.
_venv_isolated=0
if [ "$(uname -s 2>/dev/null)" = "Linux" ]; then
    _want_headless=0
    for _arg in "$@"; do
        case "$_arg" in
            --headless) _want_headless=1 ;;
            --with-desktop) _want_headless=0; break ;;
        esac
    done
    _venv_isolated=$_want_headless
    if [ -x "$VENV_PYTHON" ]; then
        if [ "$_venv_isolated" -eq 1 ] &&
           grep -qi 'include-system-site-packages *= *true' "$VENV_PATH/pyvenv.cfg" 2>/dev/null; then
            note 'rebuilding the Python environment (headless: isolated from host packages)'
            rm -rf "$VENV_PATH"
        elif [ "$_venv_isolated" -eq 0 ] &&
             grep -qi 'include-system-site-packages *= *false' "$VENV_PATH/pyvenv.cfg" 2>/dev/null; then
            note 'rebuilding the Python environment (linking distro webview/accessibility packages)'
            rm -rf "$VENV_PATH"
        fi
    fi
fi
UI_LAST_SECONDS=0
if [ ! -x "$VENV_PYTHON" ]; then
    if [ "$(uname -s 2>/dev/null)" = "Linux" ] && [ "$_venv_isolated" -eq 0 ]; then
        run_spin 'Virtual environment' "$PYTHON_EXE" -m venv --system-site-packages "$VENV_PATH"
    else
        run_spin 'Virtual environment' "$PYTHON_EXE" -m venv "$VENV_PATH"
    fi
fi
ok 'Virtual environment ready' "$UI_LAST_SECONDS"

# installer.py itself needs only the standard library and this checkout
# until its own phase 4 has run; an up-to-date pip installs that phase.
run_spin 'Installer tools (pip, packaging)' \
    "$VENV_PYTHON" -m pip install --quiet --upgrade pip packaging
ok 'Installer tools ready (pip, packaging)' "$UI_LAST_SECONDS"

# -------------------------------------------------------------- hand off
INSTALLER_PY="$INSTALL_DIR/install/installer.py"
if [ ! -f "$INSTALLER_PY" ]; then
    err "$INSTALLER_PY not found in the download."
    note 'The download seems incomplete. Please file a bug.'
    exit 1
fi

# The LFS skip is for this script's own git calls only. Drop it before the
# hand-off so the app installer.py launches (and every git it runs in the
# user's own repos) never inherits it.
unset GIT_LFS_SKIP_SMUDGE

cd "$INSTALL_DIR"
exec "$VENV_PYTHON" "$INSTALLER_PY" "$@"

