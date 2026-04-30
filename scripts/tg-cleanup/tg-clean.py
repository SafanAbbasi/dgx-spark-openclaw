#!/usr/bin/env python3
"""Delete the candidates listed in tg-scan-report.tsv.

Default mode: dry-run preview. Pass --confirm to actually delete.

Deletes "for me only" — the other person sees nothing change. Throttled
with a configurable sleep between deletes; transparently handles
FloodWaitError by sleeping the requested duration and retrying.
"""
import argparse
import asyncio
import csv
import sys
from datetime import datetime
from pathlib import Path

from _common import DIR, load_config, session_path
from telethon import TelegramClient
from telethon.errors import FloodWaitError

REPORT_PATH = DIR / "tg-scan-report.tsv"
LOG_PATH = DIR / "tg-clean-log.tsv"


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--confirm", action="store_true",
                   help="Actually perform deletions. Without this flag the script previews only.")
    p.add_argument("--limit", type=int, default=None,
                   help="Cap number of deletions this run (debug).")
    return p.parse_args()


def load_candidates():
    if not REPORT_PATH.exists():
        print(f"ERROR: {REPORT_PATH} not found. Run tg-scan.sh first.")
        sys.exit(1)
    rows = []
    with open(REPORT_PATH, "r") as f:
        r = csv.DictReader(f, delimiter="\t")
        for row in r:
            rows.append(row)
    return rows


def log_deletion(row: dict, status: str, error: str = ""):
    new_log = not LOG_PATH.exists()
    with open(LOG_PATH, "a", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        if new_log:
            w.writerow(["ts", "status", "user_id", "name", "username", "error"])
        name = (row.get("first_name", "") + " " + row.get("last_name", "")).strip()
        w.writerow([
            datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z"),
            status,
            row.get("user_id", ""),
            name,
            row.get("username", ""),
            error,
        ])


async def delete_one(client, row, dry_run: bool):
    user_id = int(row["user_id"])
    name = (row.get("first_name", "") + " " + row.get("last_name", "")).strip() or "(no name)"
    username = "@" + row["username"] if row.get("username") else "—"

    reason = row.get("reason", "?")
    if dry_run:
        print(f"  [dry-run] would delete [{reason}]: {name:<30} {username}")
        return "preview", ""

    while True:
        try:
            entity = await client.get_input_entity(user_id)
            await client.delete_dialog(entity)
            print(f"  deleted: {name:<30} {username}")
            return "deleted", ""
        except FloodWaitError as e:
            print(f"  flood-wait: sleeping {e.seconds + 1}s and retrying...")
            await asyncio.sleep(e.seconds + 1)
        except Exception as e:
            return "error", repr(e)


async def main():
    args = parse_args()
    cfg = load_config()
    rows = load_candidates()

    if args.limit:
        rows = rows[: args.limit]

    print(f"Loaded {len(rows)} candidate(s) from {REPORT_PATH.name}")

    if not args.confirm:
        print("DRY-RUN — pass --confirm to actually delete.")
    else:
        print("LIVE MODE — deletions will be performed.")
        print("")
        ans = input(f"Type DELETE to confirm deletion of {len(rows)} chats: ").strip()
        if ans != "DELETE":
            print("Aborted (no confirmation).")
            sys.exit(1)

    client = TelegramClient(session_path(cfg), cfg["api_id"], cfg["api_hash"])
    await client.connect()
    if not await client.is_user_authorized():
        print("ERROR: not authorized. Run tg-auth.sh first.")
        sys.exit(1)

    sleep_s = float(cfg.get("delete_sleep_seconds", 1.5))
    deleted = 0
    errors = 0
    previews = 0

    for i, row in enumerate(rows, 1):
        status, err = await delete_one(client, row, dry_run=not args.confirm)
        if status == "deleted":
            deleted += 1
            log_deletion(row, status)
        elif status == "preview":
            previews += 1
        else:
            errors += 1
            log_deletion(row, status, err)
            print(f"  ERROR on {row.get('user_id')}: {err}")
        if args.confirm and i < len(rows):
            await asyncio.sleep(sleep_s)

    print("")
    print("=" * 64)
    if args.confirm:
        print(f"  Deleted: {deleted}    Errors: {errors}")
        print(f"  Log:     {LOG_PATH}")
    else:
        print(f"  Previewed: {previews}  (no deletions performed)")
        print(f"  Re-run with --confirm to actually delete.")
    print("=" * 64)

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
