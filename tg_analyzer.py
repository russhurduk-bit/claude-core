#!/usr/bin/env python3
"""
Pulse Core - Telegram channel analyzer.

Reads (read-only) a set of watched Telegram chats via an external Telegram user
CLI, scans messages for keywords of interest (opportunities, jobs, tools) and
pushes a short digest of findings to the owner. Runs every couple of hours.

Watched chats and the private channel id are configurable via the environment,
so no personal identifiers are hard-coded.
"""
import os
import re
import shlex
import subprocess
import datetime

import requests

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    pass

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
OWNER_ID = int(os.environ.get("OWNER_CHAT_ID", "0"))
PRIVATE_CHANNEL_ID = os.environ.get("PRIVATE_CHANNEL_ID", "")
TG_CLI = os.environ.get("TG_CLI", "")           # e.g. "node ./tg-cli.js"
TG_ACCOUNT = os.environ.get("TG_READ_ACCOUNT", "3")  # a read-only account
LOG_DIR = os.environ.get("LOG_DIR", "/var/log")
LOG = os.path.join(LOG_DIR, "pulse-core-analyzer.log")

# Chats to monitor (read-only). Edit these for your own use.
WATCH_CHATS = [
    {"chat": "@example_jobs_board", "name": "Jobs board",
     "keywords": ["automation", "bot", "telegram", "n8n", "ai", "neural",
                  "parser", "scraper", "developer", "python", "node",
                  "freelance", "urgent"]},
]
if PRIVATE_CHANNEL_ID:
    WATCH_CHATS.append(
        {"chat": PRIVATE_CHANNEL_ID, "name": "Private channel",
         "keywords": ["new", "tool", "api", "free", "trend", "earn"]}
    )


def log_msg(msg):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG, "a") as f:
        f.write(f"[{ts}] {msg}\n")


def read_chat(chat_id, limit=30):
    if not TG_CLI:
        log_msg("TG_CLI not configured - skipping read")
        return ""
    try:
        cmd = shlex.split(TG_CLI) + ["--account", TG_ACCOUNT, "read", str(chat_id), "--limit", str(limit)]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return result.stdout
    except Exception as e:
        log_msg(f"Error reading {chat_id}: {e}")
        return ""


def send_alert(text):
    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        data={"chat_id": OWNER_ID, "text": text, "parse_mode": "Markdown"},
        timeout=10
    )


def main():
    log_msg("Analyzer started")
    findings = []

    for watch in WATCH_CHATS:
        messages = read_chat(watch["chat"])
        if not messages:
            continue

        for line in messages.split("\n"):
            line_lower = line.lower()
            matched_keywords = [kw for kw in watch["keywords"] if kw in line_lower]

            if matched_keywords and len(line) > 20:
                # Skip bot messages and system lines
                if "bot" in line_lower[:30] or "=== " in line:
                    continue
                clean = re.sub(r'\[msg#\d+\]:', '', line).strip()
                if len(clean) > 15:
                    findings.append({
                        "source": watch["name"],
                        "keywords": matched_keywords,
                        "text": clean[:200]
                    })

    if findings:
        # Deduplicate and limit
        seen, unique = set(), []
        for f in findings:
            key = f["text"][:50]
            if key not in seen:
                seen.add(key)
                unique.append(f)
        unique = unique[:7]

        msg = "\U0001F50D *Pulse Core - Telegram findings*\n\n"
        for f in unique:
            tags = ", ".join(f["keywords"][:3])
            msg += f"*{f['source']}* [{tags}]\n{f['text']}\n\n"
        msg += "_Review and decide whether it's worth pursuing._"
        send_alert(msg)
        log_msg(f"Sent {len(unique)} findings")
    else:
        log_msg("No relevant findings")


if __name__ == "__main__":
    main()
