#!/usr/bin/env bash
# deploy.sh — Deploy a Foundry-hosted agent version (no Docker / no Container Apps)
# Usage: ./deploy.sh [--agent-name <name>] [--prune-old-versions] [--keep <n>]
set -euo pipefail

if [[ -f .env ]]; then
  set -a && source .env && set +a
fi

echo "=================================================="
echo " PetStore Supply Chain Orchestrator — Foundry Hosted Deploy"
echo " Agent : ${AGENT_NAME:-petstoresupplychain-orchestrator-agent}"
echo "=================================================="

python3 deploy_foundry_agent.py "$@"
