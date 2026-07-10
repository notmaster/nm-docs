#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "$ROOT/0d-scripts/python311.sh" "$ROOT/0d-scripts/nm-v6.py" self-test --target "$ROOT"
