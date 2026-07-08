#!/usr/bin/env python3
"""
Pulse Core - Telegram listener.

Checks for new direct messages from the owner via an external Telegram user CLI
and logs them for processing. Meant to run as a cron job every few minutes.

The Telegram user CLI is an external tool; point TG_CLI at your own binary/script
(it is expected to accept: <cli> --account <n> read <peer> --limit <n>).
"""
import os
import shlex
import subprocess
import datetime

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    pass

OWNER_USERNAME = os.environ.get("OWNER_TG_USERNAME", "@owner")
TG_CLI = os.environ.get("TG_CLI", "")  # e.g. "node ./tg-cli.js"
TG_ACCOUNT = os.environ.get("TG_ACCOUNT", "1")
CORE_DIR = os.environ.get("CORE_DIR", os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.environ.get("LOG_DIR", "/var/log")
STATE_FILE = os.path.join(CORE_DIR, ".last_msg_id")
LOG_FILE = os.path.join(LOG_DIR, "pulse-core-listener.log")


def log(msg):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a") as f:
        f.write(f"[{ts}] {msg}\n")


def get_last_msg_id():
    try:
        with open(STATE_FILE) as f:
            return int(f.read().strip())
    except Exception:
        return 0


def save_last_msg_id(mid):
    with open(STATE_FILE, "w") as f:
        f.write(str(mid))


def read_messages():
    """Read the latest messages from the owner via the external Telegram CLI."""
    if not TG_CLI:
        log("TG_CLI not configured - skipping read")
        return ""
    cmd = shlex.split(TG_CLI) + ["--account", TG_ACCOUNT, "read", OWNER_USERNAME, "--limit", "5"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return result.stdout


def main():
    log("Listener check started")
    try:
        read_messages()
        log("Messages checked OK")
    except Exception as e:
        log(f"Error: {e}")


if __name__ == "__main__":
    main()
