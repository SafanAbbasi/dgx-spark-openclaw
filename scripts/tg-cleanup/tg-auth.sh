#!/bin/bash
# Interactive auth — must be run from a terminal that can read input.
set -e
cd "$(dirname "$0")"
exec "${VENV_PY:-python3}" tg-auth.py
