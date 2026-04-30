#!/bin/bash
# Safety wrapper for creating Gmail drafts.
#
# HARD INVARIANT: this script NEVER sends email. It only calls
# `gog gmail drafts create`. It explicitly refuses to forward any argument
# containing "send" as a standalone word. It post-verifies the created draft
# still exists as a draft (not sent), then logs the attempt.
#
# The cron agent prompt must instruct the LLM to use ONLY this wrapper for
# drafting. Direct calls to `gog gmail ... send` violate safety and should
# never appear.

set -euo pipefail

LOG="$(cd "$(dirname "$0")" && pwd)/gmail-draft-log.tsv"
export PATH="$HOME/.local/bin:$PATH"

THREAD_MSG_ID=""
TO=""
SUBJECT=""
BODY=""
QUOTE="0"

die() {
  echo "DRAFT-ERROR: $*" >&2
  exit 1
}

# Refuse flag names that look like send commands (e.g. --send, --send-now).
# Legitimate body/subject text containing "send" is unaffected — the guard
# only rejects flag tokens starting with `--` that contain the word "send".
for arg in "$@"; do
  if [[ "$arg" =~ ^--[a-zA-Z-]*send[a-zA-Z-]*($|=) ]]; then
    die "refused: suspicious flag containing 'send': $arg"
  fi
done

# Accept both `--key value` and `--key=value`.
EXPANDED=()
for arg in "$@"; do
  if [[ "$arg" =~ ^(--[A-Za-z0-9-]+)=(.*)$ ]]; then
    EXPANDED+=("${BASH_REMATCH[1]}" "${BASH_REMATCH[2]}")
  else
    EXPANDED+=("$arg")
  fi
done
set -- "${EXPANDED[@]}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --reply-to-message-id) THREAD_MSG_ID="$2"; shift 2 ;;
    --to) TO="$2"; shift 2 ;;
    --subject) SUBJECT="$2"; shift 2 ;;
    --body) BODY="$2"; shift 2 ;;
    --quote) QUOTE="1"; shift ;;
    *) die "unknown argument: $1" ;;
  esac
done

[[ -z "$THREAD_MSG_ID" ]] && die "missing --reply-to-message-id"
[[ -z "$TO" ]]             && die "missing --to"
[[ -z "$SUBJECT" ]]        && die "missing --subject"
[[ -z "$BODY" ]]           && die "missing --body"

# Build args — note: we hardcode `drafts create`. No `send` subcommand ever.
CREATE_ARGS=(
  gmail drafts create
  --reply-to-message-id="$THREAD_MSG_ID"
  --to="$TO"
  --subject="$SUBJECT"
  --body="$BODY"
  --json --results-only
)
if [[ "$QUOTE" = "1" ]]; then
  CREATE_ARGS+=(--quote)
fi

OUT=$(gog "${CREATE_ARGS[@]}" 2>&1) || die "gog drafts create failed: $OUT"

DRAFT_ID=$(echo "$OUT" | python3 -c "
import json, sys
try:
    d = json.loads(sys.stdin.read())
    # gog returns {'draftId': 'r123...', 'message': {...}} — draftId is our handle
    print(d.get('draftId') or d.get('id', ''))
except Exception:
    print('')
")

[[ -z "$DRAFT_ID" ]] && die "could not extract draft id from response: $OUT"

# Post-verify: the created resource must exist as a draft (not a sent message).
VERIFY=$(gog gmail drafts get "$DRAFT_ID" --json --results-only 2>&1) || \
  die "draft-get verification failed for $DRAFT_ID: $VERIFY"

VERIFY_STATUS=$(echo "$VERIFY" | python3 -c "
import json, sys
try:
    d = json.loads(sys.stdin.read())
    vid = d.get('id', '')
    m = d.get('message', {})
    tid = m.get('threadId', '')
    labels = m.get('labelIds', [])
    is_draft = 'DRAFT' in labels
    is_sent = 'SENT' in labels
    print(f'{vid}|{int(is_draft)}|{int(is_sent)}|{tid}')
except Exception as e:
    print(f'|0|0||{e}')
")

IFS='|' read -r VERIFY_ID IS_DRAFT IS_SENT VERIFY_THREAD <<< "$VERIFY_STATUS"
[[ "$VERIFY_ID" = "$DRAFT_ID" ]] || die "verification mismatch: expected=$DRAFT_ID got=$VERIFY_ID"
[[ "$IS_DRAFT" = "1" ]]          || die "draft $DRAFT_ID missing DRAFT label"
[[ "$IS_SENT" = "0" ]]           || die "CRITICAL: draft $DRAFT_ID appears as SENT — aborting"

TS=$(date '+%Y-%m-%dT%H:%M:%S%z')
printf '%s\tdraft_id=%s\tmsg_id=%s\tto=%s\tsubject=%s\n' \
  "$TS" "$DRAFT_ID" "$THREAD_MSG_ID" "$TO" "$SUBJECT" >> "$LOG"

# Record the draft in the watcher state file so the next poll does not
# re-draft the same thread.
STATE_FILE="$(cd "$(dirname "$0")" && pwd)/gmail-draft-state.json"
python3 - "$STATE_FILE" "$VERIFY_THREAD" "$DRAFT_ID" "$THREAD_MSG_ID" "$TO" "$SUBJECT" <<'PYEOF'
import json, os, sys, time

state_path, thread_id, draft_id, msg_id, to, subject = sys.argv[1:7]
if not thread_id:
    # Nothing to record — state is thread-keyed.
    sys.exit(0)

try:
    with open(state_path, 'r') as f:
        state = json.load(f)
except Exception:
    state = {'version': 1, 'drafts': {}}

state.setdefault('drafts', {})
state['drafts'][thread_id] = {
    'draft_id': draft_id,
    'message_id_basis': msg_id,
    'to': to,
    'subject': subject,
    'created_at_ms': int(time.time() * 1000),
}

tmp = state_path + '.tmp'
with open(tmp, 'w') as f:
    json.dump(state, f, indent=2)
os.replace(tmp, state_path)
PYEOF

echo "OK draft_id=$DRAFT_ID"
