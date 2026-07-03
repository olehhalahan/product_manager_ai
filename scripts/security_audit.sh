#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

python3 -m pip install --upgrade pip pip-audit >/dev/null
python3 -m pip install -r requirements.txt >/dev/null

echo "Running pip-audit against requirements.txt..."
python3 -m pip_audit -r requirements.txt --desc on

echo "Security audit passed."
