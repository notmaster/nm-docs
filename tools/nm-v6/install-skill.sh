#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
exec "$ROOT/tools/nm-v6/python311.sh" "$ROOT/tools/nm-v6/nm_v6.py" install-skill "$@"
