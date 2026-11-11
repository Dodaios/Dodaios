#!/usr/bin/env bash
# Install system packages on a GitHub-hosted Linux runner.
#
#   bash scripts/ci/apt_install.sh [--no-install-recommends] <package>...
#
# It is `apt-get update` and `apt-get install` with one check in front: when
# the runner's own resolver does not answer for the Ubuntu mirror, this job
# asks public resolvers instead.
#
# Why. On 2026-11-11, for more than two hours, the resolver every hosted runner
# uses (168.63.129.16) timed out for azure.archive.ubuntu.com,
# archive.ubuntu.com and security.ubuntu.com, while pypi.org and github.com
# resolved in 10 ms. `apt-get update` waited out its timeouts for ten minutes
# and every Linux job of every pull request failed in its first step. A probe
# on a runner showed that 1.1.1.1 and 9.9.9.9 answered for the same names, and
# that apt finished in seconds once the job used them.
#
# A healthy runner pays one name lookup for this. Nothing is changed on it.
set -euo pipefail

# The first mirror the runner image lists, or the archive when it lists none.
mirror_host() {
  list=/etc/apt/apt-mirrors.txt
  host=""
  if [ -r "$list" ]; then
    host=$(sed -n 's#^[a-z]*://\([^/]*\)/.*#\1#p' "$list" | head -n 1)
  fi
  echo "${host:-archive.ubuntu.com}"
}

mirror=$(mirror_host)
if ! timeout 15 getent ahosts "$mirror" >/dev/null 2>&1; then
  echo "::warning title=apt::The runner's resolver does not answer for $mirror. This job asks public resolvers instead."
  link=$(ip -o route get 1.1.1.1 | sed -n 's/.* dev \([^ ]*\).*/\1/p')
  if [ -n "$link" ]; then
    sudo resolvectl dns "$link" 1.1.1.1 9.9.9.9
    sudo resolvectl flush-caches || true
  fi
fi

sudo apt-get update -qq
sudo apt-get install -y -qq "$@"
