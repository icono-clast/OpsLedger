#!/bin/bash
# Nightly publish job: regenerate the dashboard pages from Cowork's JSON logs
# and push the result. Invoked by the launchd job set up alongside this repo;
# safe to run by hand too. No-ops (skips the push) if nothing changed.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

LOG_DIR="$REPO_DIR/.publish-logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/$(date +%Y-%m-%d).log"

{
  echo "=== $(date '+%Y-%m-%d %H:%M:%S') ==="
  python3 scripts/generate.py

  git add time-stats.html time-detail.html time-kantata.html tasks.html
  if git diff --cached --quiet; then
    echo "no changes, skipping commit"
  else
    git commit -m "Nightly data refresh — $(date '+%Y-%m-%d %H:%M')"
    git push origin main
    echo "pushed"
  fi
} >> "$LOG_FILE" 2>&1
