"""Shared Gmail auth health state — used by gmail-triage, gmail-draft-watcher,
and gmail-auth-check.

Writes a small JSON file tracking last successful auth, last failure, last
Telegram alert. Detects `invalid_grant` errors and pings Telegram on the
first failure (rate-limited to 6 hours so we don't spam).
"""
import json
import subprocess
import time
from pathlib import Path

_DIR = Path(__file__).resolve().parent
STATE_PATH = _DIR / "gmail-auth-state.json"
TELEGRAM_SEND = _DIR / "telegram-send.sh"
ACCOUNT = "your.email@example.com"
ALERT_RATE_LIMIT_S = 6 * 3600  # at most one alert per 6 hours

_recorded_this_run = False  # only write success to disk once per process


def read_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text())
    except Exception:
        return {}


def write_state(state: dict) -> None:
    tmp = STATE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(STATE_PATH)


def send_telegram(msg: str) -> None:
    try:
        subprocess.run(
            ["bash", str(TELEGRAM_SEND)],
            input=msg, text=True, timeout=30, check=False,
        )
    except Exception:
        pass


def detect_auth_error(stderr: str) -> bool:
    s = stderr or ""
    return "invalid_grant" in s or "Token has been expired or revoked" in s


def record_success() -> None:
    """Mark the current process as having seen a successful gog call.
    Idempotent within a single script run.
    Auto-detects login transitions: if previous state was 'broken', the success
    is treated as a fresh `gog login` (resets the 7-day refresh-token clock)."""
    global _recorded_this_run
    if _recorded_this_run:
        return
    _recorded_this_run = True

    state = read_state()
    now = int(time.time())
    prev_ok = state.get("last_known_ok", True)
    last_login_ts = state.get("last_login_ts", 0)

    # Bootstrap on first run, or transition from broken → ok
    if last_login_ts == 0 or not prev_ok:
        state["last_login_ts"] = now

    state["last_known_ok"] = True
    state["last_success_ts"] = now
    write_state(state)


def record_failure_and_alert(reason: str = "") -> None:
    """Mark auth as broken and send a Telegram alert (rate-limited to once per
    6 hours so a 15-min cron doesn't spam during a multi-day outage)."""
    state = read_state()
    now = int(time.time())
    last_alert = state.get("last_alert_ts", 0)

    state["last_known_ok"] = False
    state["last_failure_ts"] = now

    if now - last_alert >= ALERT_RATE_LIMIT_S:
        last_login = state.get("last_login_ts", 0)
        age = f"~{(now - last_login) // 86400}d" if last_login else "unknown duration"
        msg = (
            f"🚨 Gmail auth expired ({age} since last login).\n\n"
            f"Gmail Triage and Draft Watcher are blind until re-auth.\n\n"
            f"Run from your terminal:  gog login {ACCOUNT}"
        )
        send_telegram(msg)
        state["last_alert_ts"] = now

    write_state(state)
