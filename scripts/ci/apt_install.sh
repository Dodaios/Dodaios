#!/usr/bin/env bash
# Install Ubuntu packages on a GitHub-hosted runner.
#
# The runner image already pulls the main archive from Azure's Ubuntu mirror
# (mirror+file:/etc/apt/apt-mirrors.txt), but the security pocket still points
# at security.ubuntu.com. When Canonical's security host is unreachable, every
# `apt-get install` fails on its security-pocket packages and every Linux job
# goes red. Azure mirrors the security pocket too, so it is used for that
# pocket as well. Packages are signature-checked by apt either way.
#
# Usage: scripts/ci/apt_install.sh <package> [<package> ...]
set -euo pipefail

for f in /etc/apt/sources.list /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources; do
  [ -f "$f" ] || continue
  sudo sed -i -E 's#https?://security\.ubuntu\.com/ubuntu/?#http://azure.archive.ubuntu.com/ubuntu/#g' "$f"
done

sudo apt-get -o Acquire::Retries=3 update -qq
sudo apt-get -o Acquire::Retries=3 install -y -qq --no-install-recommends "$@"
