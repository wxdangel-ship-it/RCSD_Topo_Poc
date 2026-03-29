#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${REPO_DIR:-${1:-$(pwd)}}"
REMOTE_NAME="${REMOTE_NAME:-origin}"
BRANCH="${BRANCH:-main}"
INTERNAL_GIT_URL="${INTERNAL_GIT_URL:-${2:-}}"

if [[ -d "$REPO_DIR/.git" ]]; then
  cd "$REPO_DIR"
  if [[ -n "$INTERNAL_GIT_URL" ]]; then
    git remote set-url "$REMOTE_NAME" "$INTERNAL_GIT_URL"
  fi
  git fetch "$REMOTE_NAME" "$BRANCH" --prune
  git checkout "$BRANCH"
  git pull --ff-only "$REMOTE_NAME" "$BRANCH"
else
  if [[ -z "$INTERNAL_GIT_URL" ]]; then
    echo "[BLOCK] INTERNAL_GIT_URL is required when REPO_DIR does not exist." >&2
    exit 2
  fi
  git clone --branch "$BRANCH" "$INTERNAL_GIT_URL" "$REPO_DIR"
  cd "$REPO_DIR"
fi

git rev-parse HEAD
git status -sb
