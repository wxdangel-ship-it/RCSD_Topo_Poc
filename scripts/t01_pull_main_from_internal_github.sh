#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  scripts/t01_pull_main_from_internal_github.sh [remote] [branch] [internal_git_url]

Examples:
  scripts/t01_pull_main_from_internal_github.sh
  scripts/t01_pull_main_from_internal_github.sh origin main ssh://git.example.com/team/RCSD_Topo_Poc.git

Notes:
- Runs only inside an existing repo worktree.
- Blocks if the worktree is dirty or has untracked files.
- If internal_git_url is provided, updates the target remote URL before fetch/pull.
USAGE
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  usage
  exit 0
fi

REMOTE="${1:-origin}"
BRANCH="${2:-main}"
INTERNAL_GIT_URL="${INTERNAL_GIT_URL:-${3:-}}"
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"

if [ -z "$ROOT" ]; then
  echo "[BLOCK] Not inside a git repository."
  exit 2
fi

cd "$ROOT"

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "[BLOCK] Worktree is dirty. Commit/stash before pull."
  git status -sb
  exit 2
fi

if git ls-files --others --exclude-standard | grep -q .; then
  echo "[BLOCK] Untracked files exist. Commit/stash/clean before pull."
  git status -sb
  exit 2
fi

if [ -n "$INTERNAL_GIT_URL" ]; then
  git remote set-url "$REMOTE" "$INTERNAL_GIT_URL"
fi

git fetch "$REMOTE" --prune

if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
  git switch "$BRANCH"
else
  git switch -c "$BRANCH" --track "$REMOTE/$BRANCH"
fi

git pull --ff-only "$REMOTE" "$BRANCH"
git status -sb
git rev-parse HEAD
