#!/usr/bin/env bash
set -euo pipefail

# Default remote URL frozen from the user's confirmed WSL pull command.
REPO_DIR="${REPO_DIR:-${1:-/mnt/d/Work/RCSD_Topo_Poc}}"
REMOTE_NAME="${REMOTE_NAME:-origin}"
BRANCH="${BRANCH:-main}"
INTERNAL_GIT_URL="${INTERNAL_GIT_URL:-${2:-https://github.com/wxdangel-ship-it/RCSD_Topo_Poc.git}}"

mkdir -p "$(dirname "$REPO_DIR")"

echo "[RUN] REPO_DIR=$REPO_DIR"
echo "[RUN] REMOTE_NAME=$REMOTE_NAME"
echo "[RUN] BRANCH=$BRANCH"

if [[ -d "$REPO_DIR/.git" ]]; then
  cd "$REPO_DIR"
  if [[ -n "$INTERNAL_GIT_URL" ]]; then
    if git remote get-url "$REMOTE_NAME" >/dev/null 2>&1; then
      git remote set-url "$REMOTE_NAME" "$INTERNAL_GIT_URL"
    else
      git remote add "$REMOTE_NAME" "$INTERNAL_GIT_URL"
    fi
  fi

  git fetch "$REMOTE_NAME"
  git switch "$BRANCH" || git switch -c "$BRANCH" --track "$REMOTE_NAME/$BRANCH"
  git pull --ff-only "$REMOTE_NAME" "$BRANCH"
else
  if [[ -z "$INTERNAL_GIT_URL" ]]; then
    echo "[BLOCK] INTERNAL_GIT_URL is required for first clone." >&2
    exit 2
  fi

  git clone "$INTERNAL_GIT_URL" "$REPO_DIR"
  cd "$REPO_DIR"
  git fetch "$REMOTE_NAME"
  git switch "$BRANCH" || git switch -c "$BRANCH" --track "$REMOTE_NAME/$BRANCH"
  git pull --ff-only "$REMOTE_NAME" "$BRANCH"
fi

git rev-parse HEAD
git status -sb
