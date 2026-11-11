#!/usr/bin/env bash
# Install system packages on a GitHub-hosted Linux runner.
#
#   bash scripts/ci/apt_install.sh [--no-install-recommends] <package>...
#
# `apt-get update` and `apt-get install`, after `apt_resolver.sh` has made sure
# the runner can resolve its Ubuntu mirror. See that file for why.
set -euo pipefail

bash "$(dirname "$0")/apt_resolver.sh"

sudo apt-get update -qq
sudo apt-get install -y -qq "$@"
