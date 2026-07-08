#!/usr/bin/env python3
"""
Pulse Core - Task Generator.

Builds a dynamic daily to-do list based on the day of week, live service health
and lightweight stats, then delivers it to the owner over Telegram.
Cron example: 5 5 * * * (08:05 in a UTC+3 zone).
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

# Services to health-check (comma-separated env, or edit the default list).
WATCH_SERVICES = [s for s in os.environ.get(
    "WATCH_SERVICES",
    "lead-parser,agent-telegram,agent-core,content-bot,worker-bot"
).split(",") if s.strip()]


def get_lead_stats():
    """Number of leads collected by the parser."""
    try:
        state = json.load(open(LEAD_STATE))
        return len(state.get("sentLeads", []))
    except Exception:
        return "?"


def check_services():
    """Return the list of services that are not active."""
    down = []
    for svc in WATCH_SERVICES:
        try:
            result = subprocess.run(["systemctl", "is-active", svc],
                                    capture_output=True, text=True, timeout=5)
            if result.stdout.strip() != "active":
                down.append(svc)
        except Exception:
            down.append(svc)
    return down


def generate_tasks():
    now = datetime.datetime.now()
    weekday = now.weekday()  # 0=Mon
    tasks = []

    # === REVENUE (always top priority) ===
    tasks.append(("\U0001F534", "Check the jobs board - any new orders/messages"))

    if weekday in [0, 2, 4]:  # Mon, Wed, Fri
        tasks.append(("\U0001F534", "Jobs board - respond to 3-5 relevant requests"))

    # === CONTENT (daily) ===
    tasks.append(("\U0001F7E1", "Record 1 short-form video from the content plan"))

    if weekday == 0:  # Monday
        tasks.append(("\U0001F7E1", "Plan content for the week - pick 7 topics"))

    if weekday == 6:  # Sunday
        tasks.append(("\U0001F7E2", "Review this week's content metrics"))

    # === CLIENTS ===
    if weekday in [1, 4]:  # Tue, Thu
        tasks.append(("\U0001F7E1", "Message 2-3 potential clients from parser leads"))

    # === LEARNING ===
    if weekday in [2, 5]:  # Wed, Sat
        tasks.append(("\U0001F7E2", "Watch a new tutorial and apply one idea"))

    return tasks


def send_tasks():
    tasks = generate_tasks()
    leads = get_lead_stats()
    down_services = check_services()

    now = datetime.datetime.now()
    msg = f"\U0001F4CB *Tasks for {now.strftime('%d.%m.%Y')}*\n\n"

    if down_services:
        msg += f"⚠️ *Down:* {', '.join(down_services)}\n\n"

    msg += f"\U0001F4CA Leads found: {leads}\n\n"

    for priority, task in tasks:
        msg += f"{priority} {task}\n\n"

    msg += "_Open your agent session for details._"

    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                      data={"chat_id": OWNER_ID, "text": msg, "parse_mode": "Markdown"},
                      timeout=10)
    except Exception as e:
        print(f"Error sending: {e}")


if __name__ == "__main__":
    send_tasks()
