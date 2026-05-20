#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "Running automatic environment setup and migration helper..."
python setup_env.py --serve

echo "Setup completed successfully."
