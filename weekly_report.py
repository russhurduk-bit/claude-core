#!/usr/bin/env python3
"""
Pulse Core - Weekly report.

A Sunday summary: what was recorded in the knowledge base this week, lead stats
and git activity across the tracked repositories. Delivered to the owner over
Telegram.
Cron example: 0 9 * * 0 (Sunday noon in a UTC+3 zone).
"""
import os
import json
import sqlite3
import datetime
import subprocess

import requests

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    pass

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
OWNER_ID = int(os.environ.get("OWNER_CHAT_ID", "0"))
CORE_DIR = os.environ.get("CORE_DIR", os.path.dirname(os.path.abspath(__file__)))
RAG_DB = os.environ.get("RAG_DB", os.path.join(CORE_DIR, "data", "memory.db"))
LEAD_STATE = os.environ.get("LEAD_STATE", os.path.join(CORE_DIR, "data", "lead_state.json"))

# Repositories to summarize git activity for (comma-separated absolute paths).
GIT_REPOS = [p for p in os.environ.get("GIT_REPOS", "").split(",") if p.strip()]


def get_week_memories():
    """Knowledge-base entries created in the last 7 days."""
    try:
        db = sqlite3.connect(RAG_DB)
        rows = db.execute("""
            SELECT title, type, created_at FROM memories
            WHERE created_at > datetime('now', '-7 days')
            ORDER BY created_at DESC
        """).fetchall()
        db.close()
        return rows
    except Exception:
        return []


def get_lead_stats():
    try:
        state = json.load(open(LEAD_STATE))
        return len(state.get("sentLeads", []))
    except Exception:
        return "?"


def get_git_activity():
    """Git commits per tracked repo over the last 7 days."""
    activity = []
    for dir_path in GIT_REPOS:
        try:
            result = subprocess.run(
                ["git", "-C", dir_path, "log", "--oneline", "--since=7 days ago"],
                capture_output=True, text=True, timeout=5
            )
            count = len(result.stdout.strip().split("\n")) if result.stdout.strip() else 0
            if count > 0:
                name = os.path.basename(dir_path.rstrip("/"))
                activity.append(f"• {name}: {count} commits")
        except Exception:
            pass
    return activity


def generate_report():
    memories = get_week_memories()
    leads = get_lead_stats()
    git = get_git_activity()

    now = datetime.datetime.now()
    week_start = (now - datetime.timedelta(days=7)).strftime("%d.%m")
    week_end = now.strftime("%d.%m.%Y")

    projects = [m for m in memories if m[1] == "project"]
    feedbacks = [m for m in memories if m[1] == "feedback"]

    msg = f"\U0001F4CA *Weekly report*\n{week_start} - {week_end}\n\n"

    msg += "*Metrics:*\n"
    msg += f"\U0001F4E1 Leads found: {leads}\n"
    msg += f"\U0001F9E0 Memory entries: {len(memories)}\n"
    msg += f"\U0001F4C1 Projects updated: {len(projects)}\n\n"

    if projects:
        msg += "*Done:*\n"
        for title, _, created in projects[:10]:
            msg += f"• {title}\n"
        msg += "\n"

    if git:
        msg += "*Git this week:*\n"
        for g in git:
            msg += f"{g}\n"
        msg += "\n"

    if feedbacks:
        msg += f"*Feedback recorded:* {len(feedbacks)} rules\n\n"

    msg += "_Open your agent session for details._"

    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                      data={"chat_id": OWNER_ID, "text": msg, "parse_mode": "Markdown"},
                      timeout=10)
        print("Report sent")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    generate_report()
