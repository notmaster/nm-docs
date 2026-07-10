#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
"$ROOT/0d-scripts/check-workflow.sh"
"$ROOT/0d-scripts/test-workflow.sh"
exec "$ROOT/0d-scripts/python311.sh" "$ROOT/0d-scripts/nm-v6.py" verify --target "$ROOT"
