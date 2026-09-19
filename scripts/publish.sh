#!/usr/bin/env bash
set -euo pipefail

# Run inside the main checkout; its credential configuration also covers worktrees.
output=$(cd "$1" && pwd)
target=$2
upstream_sha=$3
remote_ref=$(git ls-remote --heads origin refs/heads/release)
if [[ -n "$remote_ref" ]]; then
  git fetch --no-tags origin refs/heads/release:refs/remotes/origin/release
  git worktree add --detach "$target" refs/remotes/origin/release
else
  git worktree add --detach "$target" HEAD
  git -C "$target" switch --orphan generated-release
fi

# release is exclusively generated; protect the worktree's Git metadata.
rsync -a --delete --exclude=.git "$output/" "$target/"
git -C "$target" add --all
if git -C "$target" diff --cached --quiet; then
  echo 'Release unchanged'
  exit 0
fi
git -C "$target" commit -m "rules: Sync upstream ${upstream_sha:0:12}"
git -C "$target" push origin HEAD:refs/heads/release
