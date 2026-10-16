#!/bin/bash
# Nightly publish job: regenerate the dashboard pages from Cowork's JSON logs
# and push the result. Invoked by the launchd job set up alongside this repo;
# safe to run by hand too. Output goes to both the terminal and
# .publish-logs/<date>.log.
#
# The push retries for a few minutes because launchd often fires this right
# after the Mac wakes, before Wi-Fi/DNS is back ("Could not resolve host").
# A commit that still can't be pushed stays local and goes out on the next run.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

LOG_DIR="$REPO_DIR/.publish-logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/$(date +%Y-%m-%d).log"

PUSH_ATTEMPTS="${PUSH_ATTEMPTS:-10}"
PUSH_DELAY="${PUSH_DELAY:-30}"

push_with_retry() {
  local n
  for ((n = 1; n <= PUSH_ATTEMPTS; n++)); do
    if git push origin main; then
      echo "pushed"
      return 0
    fi
    if [ "$n" -lt "$PUSH_ATTEMPTS" ]; then
      echo "push attempt $n/$PUSH_ATTEMPTS failed; retrying in ${PUSH_DELAY}s"
      sleep "$PUSH_DELAY"
    fi
  done
  echo "push failed after $PUSH_ATTEMPTS attempts; commit stays local until the next run"
  return 1
}

{
  echo "=== $(date '+%Y-%m-%d %H:%M:%S') ==="
  python3 scripts/generate.py

  git add time-stats.html time-detail.html time-kantata.html tasks.html
  if git diff --cached --quiet; then
    echo "no changes, skipping commit"
  else
    git commit -m "Nightly data refresh — $(date '+%Y-%m-%d %H:%M')"
  fi

  # Push whenever local is ahead, including commits left over from a failed push.
  if [ "$(git rev-list --count origin/main..HEAD)" -gt 0 ]; then
    push_with_retry
  fi
} 2>&1 | tee -a "$LOG_FILE"
