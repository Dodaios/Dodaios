#!/usr/bin/env bash
# Make sure a GitHub-hosted Linux runner can resolve its Ubuntu mirror.
#
#   bash scripts/ci/apt_resolver.sh
#
# Run it before anything that calls apt: `apt_install.sh` does, and so must a
# step that lets a tool call apt for it (`playwright install-deps`).
#
# When the runner's own resolver does not answer for the mirror, the job's
# network link is pointed at public resolvers and a warning says so. A healthy
# runner pays one name lookup and is not changed.
#
# Why. On 2026-11-11, for more than two hours, the resolver every hosted runner
# uses (168.63.129.16) timed out for azure.archive.ubuntu.com,
# archive.ubuntu.com and security.ubuntu.com, while pypi.org and github.com
# resolved in 10 ms. `apt-get update` waited out its timeouts for ten minutes
# and every Linux job of every pull request failed in its first step. A probe
# on a runner showed that 1.1.1.1 and 9.9.9.9 answered for the same names, and
# that apt finished in seconds once the job used them.
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
if timeout 15 getent ahosts "$mirror" >/dev/null 2>&1; then
  exit 0
fi

echo "::warning title=apt::The runner's resolver does not answer for $mirror. This job asks public resolvers instead."
link=$(ip -o route get 1.1.1.1 | sed -n 's/.* dev \([^ ]*\).*/\1/p')
if [ -n "$link" ]; then
  sudo resolvectl dns "$link" 1.1.1.1 9.9.9.9
  sudo resolvectl flush-caches || true
fi
