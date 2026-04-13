#!/usr/bin/env bash
set -euo pipefail

uv run pytest server/tests
