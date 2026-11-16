#!/usr/bin/env bash
# Install system packages on a GitHub-hosted Linux runner.
#
#   bash scripts/ci/apt_install.sh [--no-install-recommends] <package>...
#
# `apt-get update` and `apt-get install`, after `apt_resolver.sh` has made sure
# the runner can resolve its Ubuntu mirror. See that file for why.
#
# Universe. `ubuntu-latest` moves to the Ubuntu 26.04 image from October 2026,
# one runner at a time. On such a runner apt found no libportaudio2 ("Unable
# to locate package") after a clean `apt-get update`, although 26.04 carries
# it in universe: the image's sources had no universe component (the v5.5.1
# release candidate's python-fast job, 2026-11-16). When apt knows no universe
# after the update, it is added to the runner's Ubuntu sources and apt updates
# once more. A runner that has universe is not changed.
set -euo pipefail

bash "$(dirname "$0")/apt_resolver.sh"

# The image's deb822 Ubuntu sources get universe on every Components line.
# A plain edit rather than add-apt-repository, which needs the system Python
# with python-apt and is not on every image.
add_universe() {
  local sources changed=""
  for sources in /etc/apt/sources.list.d/*.sources; do
    [ -f "$sources" ] && grep -q "ubuntu" "$sources" || continue
    sudo sed -i -E '/^Components:/{/universe/!s/$/ universe/}' "$sources"
    changed="$sources"
  done
  if [ -z "$changed" ]; then
    echo "::warning title=apt::No deb822 Ubuntu sources under /etc/apt/sources.list.d to add universe to."
  fi
}

sudo apt-get update -qq
# Captured first: `grep -q` on a pipe can end apt-cache with SIGPIPE.
policy="$(apt-cache policy)"
if ! grep -q "c=universe" <<<"$policy"; then
  echo "::notice title=apt::The runner's apt sources have no universe component; adding it."
  add_universe
  sudo apt-get update -qq
fi
sudo apt-get install -y -qq "$@"
