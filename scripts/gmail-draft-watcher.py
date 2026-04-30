#!/usr/bin/env python3
"""Identify Gmail inbox messages that are candidates for a draft reply.

Gate logic:
  1. Skip messages sent by the user (same filter as gmail-triage).
  2. Skip threads already drafted within the last 24 hours (state file).
  3. Skip senders we have NO prior-reply history with (thread-history gate).

For each remaining candidate, emit a compact block that includes the full
message body so the cron agent can draft a reply.

The script itself never creates, sends, or modifies anything in Gmail. All
state it writes is to a local JSON file. Draft creation is delegated to the
`gmail-draft-create.sh` wrapper.
"""
import base64
import html
import json
import os
import re
import subprocess
import sys
import time

STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gmail-draft-state.json")
INBOX_QUERY = "in:inbox newer_than:1h"
SENT_HISTORY_QUERY = "in:sent newer_than:30d"
DRAFT_TTL_MS = 24 * 60 * 60 * 1000
MAX_BODY_CHARS = 3000
MAX_CANDIDATES = 10

USER_EMAILS = {
    "your.email@example.com",
    "another.alias@example.com",
}
USER_NAMES = {"your name"}

BIDI_RE = re.compile(
    "[͏​-‏ - ⁠-⁯﻿]"
)
FROM_RE = re.compile(r'\s*"?([^"<]*?)"?\s*<([^>]+)>\s*$')


def clean(s: str) -> str:
    if not s:
        return ""
    s = html.unescape(s)
    s = BIDI_RE.sub("", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def parse_from(raw: str):
    m = FROM_RE.match(raw or "")
    if m:
        return m.group(1).strip(), m.group(2).strip().lower()
    return "", (raw or "").strip().lower()


def is_self(from_str: str) -> bool:
    name, email = parse_from(from_str)
    if email in USER_EMAILS:
        return True
    if name and name.lower() in USER_NAMES:
        return True
    return False


def run_gog(args, timeout=20):
    try:
        out = subprocess.run(
            ["gog"] + args,
            capture_output=True, text=True, timeout=timeout,
        )
        if out.returncode != 0:
            from _auth_state import detect_auth_error, record_failure_and_alert
            if detect_auth_error(out.stderr):
                record_failure_and_alert(out.stderr)
            return None
        from _auth_state import record_success
        record_success()
        return out.stdout
    except Exception:
        return None


def load_state() -> dict:
    if not os.path.exists(STATE_PATH):
        return {"version": 1, "drafts": {}}
    try:
        with open(STATE_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {"version": 1, "drafts": {}}


def save_state(state: dict) -> None:
    # Prune stale entries on save so the file stays small.
    now = int(time.time() * 1000)
    drafts = state.get("drafts", {})
    state["drafts"] = {
        tid: d for tid, d in drafts.items()
        if now - d.get("created_at_ms", 0) < 7 * 24 * 60 * 60 * 1000
    }
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, STATE_PATH)


def b64url_decode(s: str) -> str:
    if not s:
        return ""
    s = s.replace("-", "+").replace("_", "/")
    padding = (-len(s)) % 4
    try:
        return base64.b64decode(s + "=" * padding).decode("utf-8", errors="replace")
    except Exception:
        return ""


def extract_plain_body(payload: dict) -> str:
    """Walk a Gmail payload tree, return the first text/plain body found."""
    mime = payload.get("mimeType", "")
    body = payload.get("body", {}) or {}
    data = body.get("data", "")

    if mime == "text/plain" and data:
        return b64url_decode(data)

    for part in payload.get("parts", []) or []:
        found = extract_plain_body(part)
        if found:
            return found

    # Fallback: if nothing text/plain, take the first text/html stripped of tags
    if mime == "text/html" and data:
        raw = b64url_decode(data)
        return re.sub(r"<[^>]+>", " ", raw)
    return ""


def main() -> int:
    print("=== Gmail Draft Candidates ===")
    print("")

    state = load_state()
    drafts_state = state.get("drafts", {})
    now_ms = int(time.time() * 1000)

    inbox_raw = run_gog([
        "gmail", "messages", "search", INBOX_QUERY,
        "--json", "--results-only", "--all",
    ], timeout=30)
    try:
        inbox = json.loads(inbox_raw or "[]")
    except json.JSONDecodeError:
        inbox = []
    if not isinstance(inbox, list):
        inbox = []

    if not inbox:
        print("(no inbound messages in the last hour)")
        save_state(state)
        return 0

    # Drop self-sent BEFORE grouping so the latest-in-thread is always inbound.
    inbox = [m for m in inbox if not is_self(m.get("from", ""))]
    if not inbox:
        print("(no inbound messages from others in the last hour)")
        save_state(state)
        return 0

    # Group by thread, keep latest inbound.
    by_thread: dict[str, dict] = {}
    for m in inbox:
        tid = m.get("threadId") or m.get("id", "")
        existing = by_thread.get(tid)
        if existing is None or m.get("date", "") > existing.get("date", ""):
            by_thread[tid] = m

    # Thread-history gate: fetch user's sent threads from the last 30 days.
    sent_raw = run_gog([
        "gmail", "messages", "search", SENT_HISTORY_QUERY,
        "--json", "--results-only", "--all",
    ], timeout=30)
    try:
        sent = json.loads(sent_raw or "[]")
    except json.JSONDecodeError:
        sent = []
    sent_thread_ids = {
        m.get("threadId") for m in sent if isinstance(m, dict) and m.get("threadId")
    }

    candidates = []
    skipped_new_sender = []
    skipped_already_drafted = []

    for tid, m in by_thread.items():
        # State gate: already drafted recently?
        prior = drafts_state.get(tid)
        if prior and now_ms - prior.get("created_at_ms", 0) < DRAFT_TTL_MS:
            skipped_already_drafted.append(m)
            continue
        # Thread-history gate: have we ever replied?
        if tid not in sent_thread_ids:
            skipped_new_sender.append(m)
            continue
        candidates.append(m)

    candidates.sort(key=lambda m: m.get("date", ""), reverse=True)
    candidates = candidates[:MAX_CANDIDATES]

    if not candidates:
        print("(no candidates after filters)")
        print(
            f"  skipped: new-sender={len(skipped_new_sender)} "
            f"already-drafted={len(skipped_already_drafted)}"
        )
        save_state(state)
        return 0

    for i, m in enumerate(candidates, 1):
        mid = m.get("id", "")
        tid = m.get("threadId") or mid
        sender = clean(m.get("from", ""))
        subject = clean(m.get("subject", "(no subject)"))
        _, sender_email = parse_from(m.get("from", ""))

        body = ""
        full_raw = run_gog([
            "gmail", "get", mid, "--format", "full",
            "--json", "--results-only",
        ], timeout=20)
        if full_raw:
            try:
                payload = json.loads(full_raw).get("message", {}).get("payload", {})
                body = clean(extract_plain_body(payload))[:MAX_BODY_CHARS]
            except Exception:
                body = ""

        reply_subject = subject if subject.lower().startswith("re:") else f"Re: {subject}"

        print(f"[{i}] MESSAGE_ID: {mid}")
        print(f"    THREAD_ID: {tid}")
        print(f"    FROM: {sender}")
        print(f"    SENDER_EMAIL: {sender_email}")
        print(f"    SUBJECT: {subject}")
        print(f"    REPLY_SUBJECT: {reply_subject}")
        if body:
            print(f"    BODY:")
            for line in body.splitlines():
                print(f"      {line}")
        print("")

    print(
        f"Candidates: {len(candidates)}  "
        f"(skipped new-sender: {len(skipped_new_sender)}, "
        f"already-drafted: {len(skipped_already_drafted)})"
    )
    save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
