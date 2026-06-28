#!/usr/bin/env bash
# Robust launcher for the CCA Telegram Approval Daemon.
# Prefers the project venv if it exists and has a real Python interpreter;
# otherwise falls back to the system python3. The daemon loads its own
# environment from .env and /home/ubuntu/hermes-control/secrets/shared.env.
set -euo pipefail

PROJECT_DIR="/home/ubuntu/workspace/Zero-Human-Corp/commission-crowd-agent"
VENV_PYTHON="${PROJECT_DIR}/.venv/bin/python"

if [[ -x "${VENV_PYTHON}" ]]; then
    PYTHON="${VENV_PYTHON}"
else
    PYTHON="$(command -v python3)"
fi

export PYTHONPATH="${PROJECT_DIR}/src:${PYTHONPATH:-}"
cd "${PROJECT_DIR}"

exec "${PYTHON}" -m scripts.telegram_approval_daemon "$@"
