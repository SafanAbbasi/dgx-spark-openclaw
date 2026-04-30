#!/usr/bin/env python3
"""Dry-run scanner for empty / abandoned Telegram private chats.

Walks all 1:1 private dialogs (no groups, channels, or bots) and flags
those that match one of these reasons:
  - deleted-account: the other user's account is gone (Telethon `deleted=True`,
    or the entity has no name/username/phone). Flagged regardless of message
    history because the counterparty is unreachable.
  - stub-only: every message is a 'Contact joined Telegram' service stub.

Anything with real messages, phone calls, or other service events is
preserved. Emits a TSV report to tg-scan-report.tsv with a `reason` column
so you can tell at a glance why each chat is on the list.

Read-only: never modifies anything in Telegram.
"""
import asyncio
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

from _common import DIR, load_config, load_whitelist, session_path
from telethon import TelegramClient
from telethon.tl.custom.dialog import Dialog
from telethon.tl.types import (
    MessageActionContactSignUp,
    MessageService,
    User,
)
# Phone calls are also service messages, but in a separate module.
try:
    from telethon.tl.types import MessageActionPhoneCall
except ImportError:  # very old telethon fallback
    MessageActionPhoneCall = None  # type: ignore

REPORT_PATH = DIR / "tg-scan-report.tsv"


def is_private_user_dialog(dialog: Dialog) -> bool:
    """True iff this is a 1:1 chat with another regular user (no bots,
    groups, channels, or self-saved-messages)."""
    if not dialog.is_user:
        return False
    entity = dialog.entity
    if not isinstance(entity, User):
        return False
    if getattr(entity, "bot", False):
        return False
    if getattr(entity, "is_self", False):
        return False
    return True


def is_deleted_account(entity) -> bool:
    """True iff the user's account is gone — either Telethon's explicit
    `deleted` flag, or all identity fields empty (no name, no username,
    no phone). Both signal an unreachable counterparty."""
    if bool(getattr(entity, "deleted", False)):
        return True
    no_name = not (getattr(entity, "first_name", "") or getattr(entity, "last_name", ""))
    no_username = not getattr(entity, "username", "")
    no_phone = not getattr(entity, "phone", "")
    return no_name and no_username and no_phone


def whitelist_match(dialog: Dialog, whitelist: set[str]) -> bool:
    if not whitelist:
        return False
    e = dialog.entity
    candidates = []
    name = ""
    if getattr(e, "first_name", None):
        name += e.first_name
    if getattr(e, "last_name", None):
        name += " " + e.last_name
    name = name.strip().lower()
    if name:
        candidates.append(name)
    if getattr(e, "username", None):
        candidates.append(e.username.lower())
    if getattr(e, "phone", None):
        candidates.append(e.phone.lower())
        candidates.append("+" + e.phone.lower())
    return any(c in whitelist for c in candidates)


async def is_deletable(client, dialog, scan_limit: int):
    """Return (is_candidate, total_seen, reason).

    A chat is a candidate only if every message is a service message
    of the 'Contact joined Telegram' kind. Any real message — or any
    other service action (phone call, group event, etc.) — preserves
    the chat. This is conservative on purpose; we'd rather skip a
    deletable chat than delete one that has call history."""
    total = 0
    has_call = False
    has_real = False
    has_other_service = False

    async for msg in client.iter_messages(dialog.id, limit=scan_limit):
        total += 1
        if not isinstance(msg, MessageService):
            has_real = True
            return False, total, "has-real-message"
        action = getattr(msg, "action", None)
        if MessageActionPhoneCall is not None and isinstance(action, MessageActionPhoneCall):
            has_call = True
            return False, total, "has-call"
        if isinstance(action, MessageActionContactSignUp):
            continue  # the canonical stub action; deletable
        # Any other service action (chat created, gift, history clear, etc.)
        has_other_service = True
        return False, total, f"other-service:{type(action).__name__ if action else 'unknown'}"

    return True, total, "stub-only"


def fmt_dt(dt) -> str:
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def main():
    cfg = load_config()
    whitelist = load_whitelist()
    client = TelegramClient(session_path(cfg), cfg["api_id"], cfg["api_hash"])
    await client.connect()
    if not await client.is_user_authorized():
        print("ERROR: not authorized. Run tg-auth.sh first.")
        sys.exit(1)

    print("Fetching dialog list...")
    dialogs = []
    async for d in client.iter_dialogs():
        dialogs.append(d)
    print(f"  total dialogs: {len(dialogs)}")

    private = [d for d in dialogs if is_private_user_dialog(d)]
    print(f"  private 1:1 chats with non-bot users: {len(private)}")

    candidates = []
    skipped_whitelist = 0
    skipped_reasons = {}  # reason -> count

    candidate_reason_counts = {}  # reason -> count, for summary
    for i, d in enumerate(private, 1):
        if whitelist_match(d, whitelist):
            skipped_whitelist += 1
            continue
        e = d.entity
        # Deleted-account check happens FIRST, regardless of message content.
        # The counterparty is unreachable — even calls / messages have nowhere
        # to go anymore.
        if is_deleted_account(e):
            reason = "deleted-account"
            total_seen = 0
        else:
            is_cand, total_seen, content_reason = await is_deletable(
                client, d, cfg.get("min_message_scan", 200)
            )
            if not is_cand:
                skipped_reasons[content_reason] = skipped_reasons.get(content_reason, 0) + 1
                continue
            reason = content_reason  # "stub-only"

        candidates.append({
            "dialog_id": d.id,
            "user_id": e.id,
            "first_name": getattr(e, "first_name", "") or "",
            "last_name": getattr(e, "last_name", "") or "",
            "username": getattr(e, "username", "") or "",
            "phone": getattr(e, "phone", "") or "",
            "is_contact": bool(getattr(e, "contact", False)),
            "service_message_count": total_seen,
            "last_activity": fmt_dt(d.date),
            "reason": reason,
        })
        candidate_reason_counts[reason] = candidate_reason_counts.get(reason, 0) + 1
        if i % 25 == 0:
            print(f"  scanned {i}/{len(private)} ... candidates so far: {len(candidates)}")

    # Sort: oldest activity first (most likely truly stale)
    candidates.sort(key=lambda c: c["last_activity"])

    fields = [
        "dialog_id", "user_id", "first_name", "last_name", "username",
        "phone", "is_contact", "service_message_count", "last_activity",
        "reason",
    ]
    with open(REPORT_PATH, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter="\t")
        w.writeheader()
        for c in candidates:
            w.writerow(c)

    print("")
    print("=" * 64)
    print(f"  Total private chats:            {len(private)}")
    for r, n in sorted(skipped_reasons.items(), key=lambda kv: -kv[1]):
        print(f"  Skipped ({r}):".ljust(32) + f"  {n}")
    print(f"  Skipped (whitelist):            {skipped_whitelist}")
    print(f"  CANDIDATES for cleanup:         {len(candidates)}")
    for r, n in sorted(candidate_reason_counts.items(), key=lambda kv: -kv[1]):
        print(f"    └─ {r}:".ljust(32) + f"  {n}")
    print("=" * 64)
    print(f"  Full report: {REPORT_PATH}")
    if candidates:
        print("")
        print("First 10 candidates (oldest activity first):")
        print(f"  {'name':<30} {'@username':<20} {'last activity':<22} svc-msgs")
        for c in candidates[:10]:
            name = (c["first_name"] + " " + c["last_name"]).strip() or "(no name)"
            u = "@" + c["username"] if c["username"] else "—"
            print(f"  {name[:30]:<30} {u[:20]:<20} {c['last_activity']:<22} {c['service_message_count']}")

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
