#!/usr/bin/env bash
# Install Ubuntu packages on a CI runner, surviving a mirror host whose name
# does not resolve.
#
# Usage: scripts/ci/apt_install.sh [apt-get install options] <package>...
#
# The hosted runner's apt sources name their hosts directly
# (/etc/apt/sources.list*) or through a mirror list
# (mirror+file:/etc/apt/apt-mirrors.txt). On 2026-11-11 security.ubuntu.com
# stopped resolving on the runners for more than an hour, and every package
# download routed to it failed, so `apt-get install` exited 100 before a single
# test ran, on every pull request. An archive mirror carries the same pockets
# (including -security), so a host that does not resolve is swapped for one
# that does. Nothing changes while every host resolves.
set -euo pipefail

files=""
for f in /etc/apt/apt-mirrors.txt /etc/apt/sources.list /etc/apt/sources.list.d/*; do
  if [ -f "$f" ]; then files="$files $f"; fi
done

if [ -n "$files" ]; then
  # shellcheck disable=SC2086 # the list is word-split on purpose
  hosts=$(grep -ohE 'https?://[^/[:space:]]+' $files 2>/dev/null | sed -E 's#^https?://##' | sort -u || true)
  good=""
  bad=""
  for host in $hosts; do
    if getent hosts "$host" >/dev/null 2>&1; then
      # Prefer an archive mirror as the stand-in.
      case "$host" in
        (*archive*) good="$host" ;;
        (*) if [ -z "$good" ]; then good="$host"; fi ;;
      esac
    else
      bad="$bad $host"
    fi
  done
  if [ -n "$bad" ] && [ -n "$good" ]; then
    for host in $bad; do
      echo "apt_install: $host does not resolve; using $good instead"
      # shellcheck disable=SC2086
      sudo sed -i "s#://$host#://$good#g" $files
    done
  fi
fi

sudo apt-get -o Acquire::Retries=3 update -qq
sudo apt-get -o Acquire::Retries=3 install -y -qq "$@"
