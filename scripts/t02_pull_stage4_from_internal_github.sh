#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${REPO_DIR:-${1:-/mnt/d/Work/RCSD_Topo_Poc}}"
BRANCH="${BRANCH:-${2:-codex/t02-stage4-divmerge-virtual-polygon}}"
INTERNAL_GIT_URL="${INTERNAL_GIT_URL:-${3:-https://github.com/wxdangel-ship-it/RCSD_Topo_Poc.git}}"
REMOTE_NAME="${REMOTE_NAME:-${4:-origin}}"

mkdir -p "$(dirname "$REPO_DIR")"

echo "[RUN] Stage4 internal Git pull wrapper"
echo "[RUN] REPO_DIR=$REPO_DIR"
echo "[RUN] REMOTE_NAME=$REMOTE_NAME"
echo "[RUN] BRANCH=$BRANCH"
echo "[RUN] INTERNAL_GIT_URL=$INTERNAL_GIT_URL"

if [[ -z "$BRANCH" ]]; then
  echo "[BLOCK] BRANCH is required." >&2
  exit 2
fi

if [[ -z "$INTERNAL_GIT_URL" ]]; then
  echo "[BLOCK] INTERNAL_GIT_URL is required." >&2
  exit 2
fi

if ! git ls-remote --exit-code --heads "$INTERNAL_GIT_URL" "$BRANCH" >/dev/null 2>&1; then
  echo "[BLOCK] Remote branch not found: $BRANCH" >&2
  echo "[TIP] Override BRANCH or INTERNAL_GIT_URL if your internal mirror uses a different branch name or remote URL." >&2
  exit 3
fi

if [[ -d "$REPO_DIR/.git" ]]; then
  cd "$REPO_DIR"
  if git remote get-url "$REMOTE_NAME" >/dev/null 2>&1; then
    git remote set-url "$REMOTE_NAME" "$INTERNAL_GIT_URL"
  else
    git remote add "$REMOTE_NAME" "$INTERNAL_GIT_URL"
  fi

  git fetch "$REMOTE_NAME" "$BRANCH"
  if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
    git switch "$BRANCH"
  else
    git switch -c "$BRANCH" --track "$REMOTE_NAME/$BRANCH"
  fi
  git pull --ff-only "$REMOTE_NAME" "$BRANCH"
else
  git clone -o "$REMOTE_NAME" --branch "$BRANCH" "$INTERNAL_GIT_URL" "$REPO_DIR"
  cd "$REPO_DIR"
  git pull --ff-only "$REMOTE_NAME" "$BRANCH"
fi

git rev-parse HEAD
git status -sb
