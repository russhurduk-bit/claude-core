#!/usr/bin/env python3
"""
Pulse Core - Telegram task queue.

Polls the owner's direct messages to the bot via the Telegram Bot API
(getUpdates). If a message looks like a task, it is stored in a local SQLite
queue and the owner gets an acknowledgement. The next agent session picks the
queue up.

Config comes from the environment (see .env.example).
"""
import os
import datetime
import sqlite3

import requests

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    pass

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
OWNER_ID = int(os.environ.get("OWNER_CHAT_ID", "0"))
CORE_DIR = os.environ.get("CORE_DIR", os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.environ.get("LOG_DIR", "/var/log")
QUEUE_DB = os.environ.get("QUEUE_DB", os.path.join(CORE_DIR, "data", "task_queue.db"))
OFFSET_FILE = os.path.join(CORE_DIR, ".update_offset")
LOG = os.path.join(LOG_DIR, "pulse-core-queue.log")


def log(msg):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG, "a") as f:
        f.write(f"[{ts}] {msg}\n")


def init_db():
    os.makedirs(os.path.dirname(QUEUE_DB), exist_ok=True)
    db = sqlite3.connect(QUEUE_DB)
    db.execute("""CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        message_id INTEGER,
        text TEXT,
        status TEXT DEFAULT 'pending',
        created_at TEXT,
        processed_at TEXT
    )""")
    db.commit()
    return db


def get_offset():
    try:
        with open(OFFSET_FILE) as f:
            return int(f.read().strip())
    except Exception:
        return 0


def save_offset(offset):
    with open(OFFSET_FILE, "w") as f:
        f.write(str(offset))


def get_updates(offset):
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
            params={"offset": offset, "timeout": 5, "allowed_updates": ["message"]},
            timeout=10
        )
        return r.json().get("result", [])
    except Exception:
        return []


def send_reply(text):
    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        data={"chat_id": OWNER_ID, "text": text, "parse_mode": "Markdown"},
        timeout=10
    )


# Simple heuristic: a message is a task if it contains an action verb or is long.
TASK_MARKERS = [
    "do", "make", "check", "find", "set up", "fix", "add", "create",
    "run", "send", "download", "install", "update", "need", "please", "can you",
]


def main():
    db = init_db()
    offset = get_offset()
    updates = get_updates(offset)

    new_tasks = 0
    for upd in updates:
        offset = upd["update_id"] + 1
        msg = upd.get("message", {})

        # Only from the owner, only text messages
        if msg.get("from", {}).get("id") != OWNER_ID:
            continue

        text = msg.get("text", "")
        if not text or text.startswith("/"):
            continue

        is_task = any(m in text.lower() for m in TASK_MARKERS) or len(text) > 30

        if is_task:
            db.execute(
                "INSERT INTO tasks (message_id, text, status, created_at) VALUES (?,?,?,?)",
                (msg.get("message_id"), text, "pending",
                 datetime.datetime.now(datetime.UTC).isoformat())
            )
            new_tasks += 1
            log(f"New task: {text[:80]}...")

    db.commit()
    save_offset(offset)

    if new_tasks > 0:
        pending = db.execute("SELECT COUNT(*) FROM tasks WHERE status='pending'").fetchone()[0]
        send_reply(f"\U0001F4E5 Queued {new_tasks} task(s). Pending: {pending}\n\n"
                   f"_Will be handled in the next agent session._")
        log(f"Queued {new_tasks} tasks, total pending: {pending}")

    db.close()


if __name__ == "__main__":
    main()
