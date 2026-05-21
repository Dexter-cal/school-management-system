#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "Checking for local changes..."
if ! git diff --quiet --ignore-submodules -- || ! git diff --cached --quiet --ignore-submodules --; then
  echo
  echo "Local changes were detected, so update.sh stopped before pulling from GitHub."
  echo "Commit or stash your changes first, then run update.sh again."
  exit 1
fi

BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
if [[ -z "$BRANCH" ]]; then
  echo "Could not detect the current Git branch."
  exit 1
fi

echo "Fetching updates from origin/$BRANCH..."
git fetch origin "$BRANCH"

echo "Pulling latest changes..."
git pull --ff-only origin "$BRANCH"

echo "Refreshing the local environment..."
python setup_env.py

echo
echo "Update complete. You can now run start.sh."
