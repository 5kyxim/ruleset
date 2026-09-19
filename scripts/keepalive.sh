#!/usr/bin/env bash
set -euo pipefail

last_commit=$(git log -1 --format=%ct)
now=$(date +%s)
if (( now - last_commit >= 30 * 86400 )); then
  date -u +%Y-%m-%dT%H:%M:%SZ > .github/keepalive
  git add .github/keepalive
  git commit -m 'automation: Record scheduled maintenance activity'
  git push origin HEAD:refs/heads/main
fi
