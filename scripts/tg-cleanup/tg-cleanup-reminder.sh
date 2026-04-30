#!/bin/bash
# Monthly reminder: runs the read-only scan and pings Telegram only if
# the scan finds chats worth cleaning up. Silent otherwise.
#
# The destructive part (tg-clean.sh --confirm) is intentionally NOT
# automated — the user runs it manually after reviewing the report.

set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
TSV="$DIR/tg-scan-report.tsv"
LOG="$DIR/tg-reminder.log"

# Run scan (writes the TSV; output captured for diagnostics)
bash "$DIR/tg-scan.sh" > "$LOG" 2>&1 || {
  # Scan failed — alert so you know the cron didn't silently break.
  printf '⚠️ Telegram cleanup scan FAILED. Check %s' "$LOG" \
    | bash "$DIR/../telegram-send.sh" || true
  exit 1
}

# Count by reason. wc -l on a no-newline last-line file undercounts by 1,
# but tg-scan.py always writes a trailing newline via csv.DictWriter.
TOTAL=$(( $(wc -l < "$TSV") - 1 ))
if [[ "$TOTAL" -le 0 ]]; then
  exit 0  # nothing to clean — stay silent
fi

STUB=$(awk -F'\t' 'NR>1 && $10=="stub-only"     {n++} END{print n+0}' "$TSV")
DEL=$(awk  -F'\t' 'NR>1 && $10=="deleted-account"{n++} END{print n+0}' "$TSV")

MSG=$(printf '📱 Telegram cleanup ready: %d chats (%d stubs + %d deleted accounts).\n\nTo clean: bash $DIR/tg-clean.sh --confirm' \
  "$TOTAL" "$STUB" "$DEL")

printf '%s' "$MSG" | bash "$DIR/../telegram-send.sh"
