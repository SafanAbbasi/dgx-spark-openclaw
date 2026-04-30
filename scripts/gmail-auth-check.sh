#!/bin/bash
# Thin launcher for the daily Gmail auth health check.
set -e
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$PATH"
exec python3 ./gmail-auth-check.py
