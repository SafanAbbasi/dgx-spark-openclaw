#!/bin/bash
# Thin launcher for the Gmail draft candidate watcher.
export PATH="$HOME/.local/bin:$PATH"
export TZ="America/Chicago"
exec python3 $(dirname "$0")/gmail-draft-watcher.py
