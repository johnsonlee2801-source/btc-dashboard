#!/usr/bin/env bash
# Commit and push files a data workflow regenerated, surviving a concurrent push.
#
# Usage: scripts/commit_generated.sh "<commit message>" <file>...
#
# The files are rebuilt whole on every run, so a line-level rebase cannot merge
# them: it either conflicts or splices two snapshots into invalid JSON. When the
# push is rejected, this run's copies are re-committed on top of the newest
# master instead. Runs of one workflow share a concurrency group and execute in
# order, so the run pushing last also holds the newest data.
set -euo pipefail

message=$1
shift
files=("$@")

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

saved=$(mktemp -d)
trap 'rm -rf "$saved"' EXIT
tar -cf "$saved/files.tar" -- "${files[@]}"

commit_saved() {
  tar -xf "$saved/files.tar"
  git add -- "${files[@]}"
  if git diff --cached --quiet; then
    echo "No changes in ${files[*]}"
    return 1
  fi
  git commit -q -m "$message"
}

commit_saved || exit 0
for attempt in 1 2 3 4; do
  if git push -q origin HEAD:master; then
    exit 0
  fi
  echo "Push rejected on attempt $attempt; re-committing this run's files on the newest master"
  sleep $((attempt * 3))
  git fetch -q origin master
  git reset -q --hard origin/master
  commit_saved || exit 0
done
echo "Push still failing after 4 attempts"
exit 1
