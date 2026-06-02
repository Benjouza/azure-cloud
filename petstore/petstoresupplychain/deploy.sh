#!/usr/bin/env bash
# deploy.sh — Deploy a Foundry-hosted (Code) agent
# Usage: ./deploy.sh [--method source|container] [--prune-old-versions] [--keep <n>]
set -euo pipefail

if [[ -f .env.generated ]]; then
  set -a && source .env.generated && set +a
fi
if [[ -f .env ]]; then
  set -a && source .env && set +a
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${SCRIPT_DIR}/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="python3"
fi

$PYTHON deploy_foundry_agent.py "$@"
