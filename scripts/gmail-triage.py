#!/usr/bin/env python3
"""Fetch last 24hr Inbox Gmail messages and emit a compact triage-ready listing.
Read-only: never modifies the inbox.

Pipeline:
  1. Fetch the last 24hr of Inbox messages via `gog gmail messages search`.
  2. Drop messages sent by the user (see USER_EMAILS / USER_NAMES).
  3. Group into "events" — primarily by threadId, but also merge distinct
     threads that share a normalized subject (catches Gmail mis-threading,
     calendar-invite vs scheduling chatter about the same meeting, etc).
     Keep the latest message per group so the LLM sees one representative
     per conversation/event.
  4. For each representative, fetch the metadata snippet, decode HTML
     entities, and emit a compact block the LLM can classify.
"""
import html
import json
import re
import subprocess
import sys

MAX_GROUPS = 50
SEARCH_QUERY = "in:inbox newer_than:1d"
MIN_SUBJECT_TOKENS_FOR_MERGE = 3  # avoid merging two unrelated "Invoice" threads

USER_EMAILS = {
    "your.email@example.com",
    "another.alias@example.com",
}
USER_NAMES = {"your name"}

# Strip invisible tracking characters (ZWSP, ZWNJ, CGJ, BOM, etc).
# Use explicit \u escapes so ASCII SPACE cannot land inside a range.
BIDI_RE = re.compile(
    "[͏"            # combining grapheme joiner
    "​-‏"      # ZWSP, ZWNJ, ZWJ, LRM, RLM
    "  "       # line sep, paragraph sep
    "‪- "      # embedding/override controls + NNBSP
    "⁠-⁯"      # word joiner + invisible operators
    "﻿]"            # ZWNBSP / BOM
)
FROM_RE = re.compile(r'\s*"?([^"<]*?)"?\s*<([^>]+)>\s*$')

# Strip leading reply/forward/invite markers (repeatable) and trailing " @ ..."
# tails that calendar invites add ("@ Thu Apr 30, 2026 2pm - 2:30pm (CDT) ...").
SUBJECT_PREFIX_RE = re.compile(
    r"^\s*(?:re|fwd|fw|updated invitation|updated|invitation(?:\s+from[^:]*)?|"
    r"accepted|declined|cancell?ed|tentative)\s*:\s*",
    re.IGNORECASE,
)
SUBJECT_AT_DATE_RE = re.compile(r"\s+@\s+.*$")


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


def normalize_subject(subject: str) -> str:
    if not subject:
        return ""
    s = clean(subject)
    # Strip repeating prefixes (Re: Fwd: Re: ...)
    prev = None
    while prev != s:
        prev = s
        s = SUBJECT_PREFIX_RE.sub("", s)
    s = SUBJECT_AT_DATE_RE.sub("", s)
    s = s.lower()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def group_key(msg: dict) -> str:
    ns = normalize_subject(msg.get("subject", ""))
    if ns and len(ns.split()) >= MIN_SUBJECT_TOKENS_FOR_MERGE:
        return f"subj:{ns}"
    return f"tid:{msg.get('threadId') or msg.get('id', '')}"


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


def main() -> int:
    print("=== Gmail Triage (last 24hr) ===")
    print("")

    raw = run_gog([
        "gmail", "messages", "search", SEARCH_QUERY,
        "--json", "--results-only", "--all",
    ], timeout=30)

    if not raw:
        print("  Could not reach Gmail. Check: gog gmail messages search 'in:inbox' --max 1")
        return 0

    try:
        msgs = json.loads(raw)
    except json.JSONDecodeError:
        msgs = []

    if not isinstance(msgs, list) or not msgs:
        print("  Inbox is clear — no messages in the last 24 hours.")
        return 0

    raw_count = len(msgs)

    # Drop self-sent before grouping so self-replies don't bloat counts.
    msgs = [m for m in msgs if not is_self(m.get("from", ""))]
    filtered_self = raw_count - len(msgs)

    # Group by event key; track total msg count + distinct threadIds per group.
    group_latest: dict[str, dict] = {}
    group_msg_count: dict[str, int] = {}
    group_thread_ids: dict[str, set[str]] = {}

    for m in msgs:
        k = group_key(m)
        group_msg_count[k] = group_msg_count.get(k, 0) + 1
        group_thread_ids.setdefault(k, set()).add(
            m.get("threadId") or m.get("id", "")
        )
        existing = group_latest.get(k)
        if existing is None or m.get("date", "") > existing.get("date", ""):
            group_latest[k] = m

    reps = sorted(
        group_latest.items(),
        key=lambda kv: kv[1].get("date", ""),
        reverse=True,
    )
    total = len(reps)
    truncated = total > MAX_GROUPS
    reps = reps[:MAX_GROUPS]

    if not reps:
        print("  Inbox is clear — no inbound messages in the last 24 hours.")
        print("")
        print(f"(Raw: {raw_count}, filtered self-sent: {filtered_self})")
        return 0

    for i, (gkey, m) in enumerate(reps, 1):
        mid = m.get("id", "")
        sender = clean(m.get("from", ""))
        subject = clean(m.get("subject", "(no subject)"))
        labels = [l for l in m.get("labels", []) if l != "INBOX"]
        msg_count = group_msg_count.get(gkey, 1)
        thread_count = len(group_thread_ids.get(gkey, set()) or {""})

        snippet = ""
        raw_msg = run_gog([
            "gmail", "get", mid,
            "--format", "metadata",
            "--json", "--results-only",
        ], timeout=15)
        if raw_msg:
            try:
                snippet = clean(
                    json.loads(raw_msg).get("message", {}).get("snippet", "")
                )[:240]
            except json.JSONDecodeError:
                pass

        print(f"[{i}] FROM: {sender}")
        print(f"    SUBJECT: {subject}")
        if labels:
            print(f"    LABELS: {', '.join(labels)}")
        if msg_count > 1:
            if thread_count > 1:
                print(
                    f"    GROUP: {msg_count} related messages across "
                    f"{thread_count} threads (showing latest)"
                )
            else:
                print(
                    f"    THREAD: {msg_count} messages in this thread "
                    f"(showing latest)"
                )
        if snippet:
            print(f"    SNIPPET: {snippet}")
        print("")

    suffix = f" (showing first {MAX_GROUPS})" if truncated else ""
    print(f"Total events: {total}{suffix}")
    print(f"(Raw messages: {raw_count}, self-sent filtered: {filtered_self})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
