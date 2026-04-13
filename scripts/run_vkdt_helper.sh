#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SESSION_DIR="${VKDT_AGENT_SESSION_DIR:-$ROOT_DIR/.vkdt-agent-session}"

exec python3 "$ROOT_DIR/native/vkdt_agent_bridge_helper.py" --session-dir "$SESSION_DIR"
