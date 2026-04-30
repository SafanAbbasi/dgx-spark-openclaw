#!/bin/bash
# Fetches last 24hr of Inbox Gmail messages and prints them in a compact
# format for the LLM to triage into 5 buckets. Read-only.

export PATH="$HOME/.local/bin:$PATH"
export TZ="America/Chicago"

exec python3 $(dirname "$0")/gmail-triage.py
