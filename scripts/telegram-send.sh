#!/bin/bash
# Send a Telegram message to the configured user via OpenClaw.
# Body comes from stdin (to preserve newlines and quoting).
#
# Usage: printf 'line 1\nline 2\n' | bash telegram-send.sh
#
# Setup: replace YOUR_TELEGRAM_CHAT_ID below with your numeric Telegram
# chat id (the same one you use in `openclaw cron add --to`).

set -euo pipefail

CHAT_ID="YOUR_TELEGRAM_CHAT_ID"
MSG="$(cat)"

if [[ -z "${MSG//[[:space:]]/}" ]]; then
  echo "telegram-send: refusing to send empty message" >&2
  exit 2
fi

exec openclaw message send \
  --channel telegram \
  --target "$CHAT_ID" \
  --message "$MSG"
