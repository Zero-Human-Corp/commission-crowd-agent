#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}/../.."

source .venv/bin/activate
echo "=== CCA Request Approval ==="
python -m commission_crowd_agent.cli request-approval "$@"
