#!/usr/bin/env bash
set -euo pipefail

uv run uvicorn server.app:app --host 127.0.0.1 --port 4000
