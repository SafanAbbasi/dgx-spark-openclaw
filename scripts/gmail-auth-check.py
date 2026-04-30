#!/usr/bin/env python3
"""Daily Gmail auth health probe + re-auth reminder.

Hits a trivial Gmail API endpoint to test whether the OAuth refresh token
is still valid:
  - Success → records success. If we're at day 6 of the 7-day refresh
    window, pings Telegram with a one-day-ahead reminder.
  - Failure → if it's an `invalid_grant`, pings Telegram with an urgent
    alert (rate-limited to once per 6 hours by the shared helper).

Designed to be silent on healthy days — the only Telegram pings are the
day-6 reminder and the urgent expired alert.
"""
import subprocess
import sys
import time

from _auth_state import (
    ACCOUNT,
    detect_auth_error,
    read_state,
    record_failure_and_alert,
    record_success,
    send_telegram,
)

WARN_DAY = 6  # day of the 7-day window to send the heads-up reminder


def probe() -> tuple[bool, str]:
    try:
        r = subprocess.run(
            ["gog", "gmail", "messages", "search", "in:inbox",
             "--max", "1", "--json", "--results-only"],
            capture_output=True, text=True, timeout=30,
        )
        return r.returncode == 0, r.stderr or ""
    except Exception as e:
        return False, str(e)


def main() -> int:
    ok, stderr = probe()
    if ok:
        record_success()
        state = read_state()
        last_login = state.get("last_login_ts", 0)
        if last_login:
            age_days = (int(time.time()) - last_login) // 86400
            if age_days == WARN_DAY:
                send_telegram(
                    f"🔑 Gmail re-auth due tomorrow (day {WARN_DAY}/7).\n\n"
                    f"Run from your terminal:  gog login {ACCOUNT}"
                )
        return 0

    if detect_auth_error(stderr):
        record_failure_and_alert(stderr)
        return 1

    # Some other error — not an auth issue. Stay silent (transient network etc).
    return 0


if __name__ == "__main__":
    sys.exit(main())
