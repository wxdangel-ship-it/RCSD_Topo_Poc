#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${REPO_DIR:-${1:-/mnt/d/Work/RCSD_Topo_Poc}}"
REMOTE_NAME="${REMOTE_NAME:-origin}"
BRANCH="${BRANCH:-main}"
INTERNAL_GIT_URL="${INTERNAL_GIT_URL:-${2:-}}"

mkdir -p "$(dirname "$REPO_DIR")"

echo "[RUN] REPO_DIR=$REPO_DIR"
echo "[RUN] REMOTE_NAME=$REMOTE_NAME"
echo "[RUN] BRANCH=$BRANCH"

if [[ -d "$REPO_DIR/.git" ]]; then
  if [[ -n "$INTERNAL_GIT_URL" ]]; then
    if git -C "$REPO_DIR" remote get-url "$REMOTE_NAME" >/dev/null 2>&1; then
      git -C "$REPO_DIR" remote set-url "$REMOTE_NAME" "$INTERNAL_GIT_URL"
    else
      git -C "$REPO_DIR" remote add "$REMOTE_NAME" "$INTERNAL_GIT_URL"
    fi
  fi

  git -C "$REPO_DIR" fetch "$REMOTE_NAME" "$BRANCH" --prune

  if git -C "$REPO_DIR" show-ref --verify --quiet "refs/heads/$BRANCH"; then
    git -C "$REPO_DIR" checkout "$BRANCH"
  else
    git -C "$REPO_DIR" checkout -B "$BRANCH" "$REMOTE_NAME/$BRANCH"
  fi

  git -C "$REPO_DIR" pull --ff-only "$REMOTE_NAME" "$BRANCH"
else
  if [[ -z "$INTERNAL_GIT_URL" ]]; then
    echo "[BLOCK] INTERNAL_GIT_URL is required for first clone." >&2
    exit 2
  fi

  git clone --branch "$BRANCH" "$INTERNAL_GIT_URL" "$REPO_DIR"
fi

git -C "$REPO_DIR" rev-parse HEAD
git -C "$REPO_DIR" status -sb
