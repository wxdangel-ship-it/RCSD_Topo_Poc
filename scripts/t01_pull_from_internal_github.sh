#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${REPO_DIR:-${1:-$(pwd)}}"
REMOTE_NAME="${REMOTE_NAME:-origin}"
BRANCH="${BRANCH:-main}"
INTERNAL_GIT_URL="${INTERNAL_GIT_URL:-${2:-}}"

if [[ -d "$REPO_DIR/.git" ]]; then
  cd "$REPO_DIR"
  if [[ -z "$INTERNAL_GIT_URL" ]]; then
    INTERNAL_GIT_URL="$(git remote get-url "$REMOTE_NAME" 2>/dev/null || true)"
  fi
  if [[ -z "$INTERNAL_GIT_URL" ]]; then
    echo "[BLOCK] INTERNAL_GIT_URL is required when repo exists but remote '$REMOTE_NAME' is missing." >&2
    exit 2
  fi
  if [[ -n "$(git status --porcelain)" ]]; then
    echo "[BLOCK] worktree is dirty; please commit/stash local changes before pull." >&2
    git status -sb >&2
    exit 2
  fi
  git remote set-url "$REMOTE_NAME" "$INTERNAL_GIT_URL"
  git fetch "$REMOTE_NAME" "$BRANCH" --prune
  if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
    git checkout "$BRANCH"
  else
    git checkout -B "$BRANCH" "$REMOTE_NAME/$BRANCH"
  fi
  git branch --set-upstream-to="$REMOTE_NAME/$BRANCH" "$BRANCH" >/dev/null 2>&1 || true
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
