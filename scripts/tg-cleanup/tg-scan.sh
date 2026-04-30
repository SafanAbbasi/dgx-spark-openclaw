#!/bin/bash
set -e
cd "$(dirname "$0")"
exec "${VENV_PY:-python3}" tg-scan.py "$@"
