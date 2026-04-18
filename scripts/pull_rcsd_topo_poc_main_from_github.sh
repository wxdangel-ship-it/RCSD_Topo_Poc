#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="/mnt/d/Work/RCSD_Topo_Poc"
REMOTE_NAME="origin"
BRANCH="main"
GITHUB_URL="git@github.com:wxdangel-ship-it/RCSD_Topo_Poc.git"

echo "[RUN] REPO_DIR=$REPO_DIR"
echo "[RUN] REMOTE_NAME=$REMOTE_NAME"
echo "[RUN] BRANCH=$BRANCH"
echo "[RUN] GITHUB_URL=$GITHUB_URL"

bash "$SCRIPT_DIR/t01_pull_from_internal_github.sh" "$REPO_DIR" "$GITHUB_URL"
