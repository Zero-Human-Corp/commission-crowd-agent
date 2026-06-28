#!/usr/bin/env bash
# Tmux-based orchestration for the CCA Telegram Approval Daemon.
# Use this on nodes where systemd is unavailable or undesirable.
set -euo pipefail

PROJECT_DIR="/home/ubuntu/workspace/Zero-Human-Corp/commission-crowd-agent"
RUNTIME_DIR="/home/ubuntu/hermes-control/runtime"
LOG_FILE="${RUNTIME_DIR}/cca_telegram_daemon.log"
SESSION_NAME="cca-telegram-bot"
LAUNCHER="${PROJECT_DIR}/scripts/daemon_launcher.sh"

mkdir -p "${RUNTIME_DIR}"

# Idempotent session management: kill a stale session if it exists.
if tmux has-session -t "${SESSION_NAME}" 2>/dev/null; then
    echo "Stale tmux session '${SESSION_NAME}' found; killing and recreating."
    tmux kill-session -t "${SESSION_NAME}"
fi

# Create a detached tmux session that runs the daemon through the robust launcher.
# Note: bash is invoked explicitly because some project filesystems do not
# preserve the executable bit on shell scripts.
tmux new-session -d -s "${SESSION_NAME}" -n daemon \
    "exec /bin/bash '${LAUNCHER}' >> '${LOG_FILE}' 2>&1"

echo "CCA Telegram Approval Daemon started in tmux session '${SESSION_NAME}'."
echo "Attach with: tmux attach-session -t ${SESSION_NAME}"
echo "Live log: tail -f ${LOG_FILE}"
