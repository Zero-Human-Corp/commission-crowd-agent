#!/usr/bin/env bash
set -euo pipefail

echo "=== Running dev checks for commission-crowd-agent ==="
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}/.."

if [ ! -d ".venv" ]; then
    echo "Creating .venv ..."
    python3.11 -m venv .venv
fi

source .venv/bin/activate

echo "--- Installing package ---"
pip install -q -e ".[dev]"

echo "--- Ruff check ---"
ruff check src tests

echo "--- Ruff format check ---"
ruff format --check src tests

echo "--- MyPy type check ---"
mypy src

echo "--- pytest ---"
pytest

echo "=== All checks passed ==="
