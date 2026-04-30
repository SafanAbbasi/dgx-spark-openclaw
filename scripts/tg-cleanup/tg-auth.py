#!/usr/bin/env python3
"""One-time interactive Telegram authentication.

Walks through phone-number entry, SMS code, and (if set) 2FA password,
then writes a session file alongside this script. Subsequent runs of
tg-scan / tg-clean reuse the session — no SMS required.
"""
import asyncio
import sys

from _common import load_config, session_path
from telethon import TelegramClient


async def main():
    cfg = load_config()
    client = TelegramClient(
        session_path(cfg),
        cfg["api_id"],
        cfg["api_hash"],
    )
    print("Connecting to Telegram...")
    print("You'll be prompted for:")
    print("  1. Your phone number (with country code, e.g. +18005551234)")
    print("  2. The login code Telegram texts you")
    print("  3. Your 2FA password if you have one set")
    print("")
    await client.start()
    me = await client.get_me()
    name = (me.first_name or "") + (" " + me.last_name if me.last_name else "")
    print(f"\nLogged in as: {name.strip()} (@{me.username or '—'})")
    print(f"Session file: {session_path(cfg)}.session")
    await client.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(1)
