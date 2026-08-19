#!/usr/bin/env bash
# One-paste publisher (macOS / Linux / Git Bash).
#
#   export GITHUB_TOKEN=ghp_your_token
#   curl -fsSL https://raw.githubusercontent.com/mueedmbrk/mueedmbrk/claude/github-projects-setup-vxelek/projects/publish.sh | bash

set -euo pipefail

if [ -z "${GITHUB_TOKEN:-}" ]; then
  echo "Set your token first:"
  echo '    export GITHUB_TOKEN=ghp_your_token_here'
  echo "Create one at https://github.com/settings/tokens (scope: repo)"
  exit 1
fi

BRANCH="claude/github-projects-setup-vxelek"
WORK="$(mktemp -d)"

echo "Cloning project branch..."
git clone -q --depth 1 --branch "$BRANCH" https://github.com/mueedmbrk/mueedmbrk.git "$WORK"

cd "$WORK/projects"
echo "Working in $(pwd)"
echo
bash ./create-repos.sh
