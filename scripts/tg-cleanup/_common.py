"""Shared helpers for the Telegram cleanup scripts."""
import json
import os
from pathlib import Path

DIR = Path(__file__).resolve().parent
CONFIG_PATH = DIR / "config.json"
SESSION_NAME = None  # populated by load_config()
WHITELIST_PATH = DIR / "whitelist.txt"


def load_config():
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


def load_whitelist():
    """Return a set of lower-cased identifiers (username, name, or phone)
    that should never be deleted, even if the chat looks empty."""
    if not WHITELIST_PATH.exists():
        return set()
    out = set()
    for line in WHITELIST_PATH.read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        out.add(s.lower())
    return out


def session_path(cfg) -> str:
    return str(DIR / cfg["session_name"])
