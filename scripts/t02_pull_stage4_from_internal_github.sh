#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

REPO_DIR="${REPO_DIR:-/mnt/d/Work/RCSD_Topo_Poc}"
REMOTE_NAME="${REMOTE_NAME:-origin}"
BRANCH="${BRANCH:-codex/t02-stage4-divmerge-virtual-polygon}"
INTERNAL_GIT_URL="${INTERNAL_GIT_URL:-https://github.com/wxdangel-ship-it/RCSD_Topo_Poc.git}"

echo "[RUN] Stage4 internal Git pull wrapper"
echo "[RUN] REPO_DIR=$REPO_DIR"
echo "[RUN] REMOTE_NAME=$REMOTE_NAME"
echo "[RUN] BRANCH=$BRANCH"
echo "[RUN] INTERNAL_GIT_URL=$INTERNAL_GIT_URL"

REMOTE_NAME="$REMOTE_NAME" \
BRANCH="$BRANCH" \
INTERNAL_GIT_URL="$INTERNAL_GIT_URL" \
bash "$SCRIPT_DIR/t01_pull_from_internal_github.sh" "$REPO_DIR" "$INTERNAL_GIT_URL"
