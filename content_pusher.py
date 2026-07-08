#!/usr/bin/env python3
"""
Pulse Core - Content Pusher.

Keeps the owner accountable to a content schedule: a themed prompt every morning
and an accountability check every evening. Cycles through a 30-day content plan.

Cron example:
  0 7  * * *  ->  content_pusher.py morning
  0 17 * * *  ->  content_pusher.py evening
"""
import os
import sys
import datetime

import requests

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    pass

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
OWNER_ID = int(os.environ.get("OWNER_CHAT_ID", "0"))
PLAN_START = os.environ.get("CONTENT_PLAN_START", "2026-01-01")

# 30-day content plan - one topic per day (generic business-automation niche).
CONTENT_THEMES = [
    "Case study: how a bot saves a client 120 hours/month",
    "3 things businesses still do by hand (a bot does in 0 sec)",
    "Demo: a bot that generates and publishes posts by itself",
    "How much does a business bot cost? (3 pricing tiers)",
    "The costly mistake: 3 managers instead of 1 automation",
    "Before/After: 4 hours of routine work -> now zero",
    "Automate your inbox in 30 minutes (tutorial)",
    "Case study: a scraper that collects leads in 5 minutes",
    "5 processes AI does better than a human",
    "Demo: an n8n workflow - request -> CRM -> reply in 3 sec",
    "Why a bot is cheaper than a full-time manager",
    "90% of businesses lose clients to slow replies",
    "Before/After: 8 employees -> 3 after automation",
    "Build an AI chatbot in a day (step by step)",
    "Case study: a voice bot that answers calls 24/7",
    "3 mistakes when choosing a CRM (and how automation fixes them)",
    "Demo: AI generates 30 short-form ideas in a minute",
    "How I automate businesses (the toolset I use)",
    "How much money a business loses without automation",
    "Before/After: manual posting vs automated",
    "Connect AI to a Telegram bot (tutorial)",
    "Case study: an auto-funnel that sells without a manager",
    "7 automation tools everyone should know",
    "Demo: a booking bot (calendar + payment)",
    "Free tools to automate a small business",
    "Why every business will use AI within a year",
    "Before/After: manual email vs automated",
    "How to start earning from automation (from scratch)",
    "Case study: a content generator for a Telegram channel",
    "Month in review: what I built, what I learned, what's next",
]

HOOKS = [
    "This founder spent 4 hours a day on busywork...",
    "3 things you do by hand every single day",
    "Watch what this bot can do",
    "How much does a business bot really cost?",
    "This one mistake costs businesses thousands a month",
    "I automate businesses - here's how",
    "8 employees became 3. The rest? Automated.",
    "This bot replies to clients faster than any human",
    "90% of founders still do this manually",
    "A bot vs a full-time manager: the real math",
]


def get_day_number():
    """Day of the content plan (0-29, then repeats)."""
    start = datetime.date.fromisoformat(PLAN_START)
    today = datetime.date.today()
    return (today - start).days % 30


def _send(msg):
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                  data={"chat_id": OWNER_ID, "text": msg, "parse_mode": "Markdown"},
                  timeout=10)


def morning_push():
    day = get_day_number()
    theme = CONTENT_THEMES[day % len(CONTENT_THEMES)]
    hook = HOOKS[day % len(HOOKS)]

    msg = f"""\U0001F3AC *Today's content (day {day + 1}/30)*

*Topic:* {theme}

*Hook (first 2 sec):*
"{hook}"

*Format:* 30-45 sec Reels/TikTok
*CTA:* "Checklist of 50 processes - link in bio"

\U0001F4F1 Record -> upload -> mark done
Batching: shoot 3-5 videos at once

_Didn't shoot yesterday? Do 2 today. Content = leads = revenue._"""
    _send(msg)


def evening_check():
    day = get_day_number()

    msg = f"""⏰ *Evening check - day {day + 1}*

Did you record a video today?

If yes - nice, one more tomorrow.
If not - don't put it off. 1 video = 30 seconds of shooting.

Every day without content = lost clients.
Top creators post a few times a month and build huge audiences.
You need 1 a day for the first month.

_New topic tomorrow._"""
    _send(msg)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "morning"
    if mode == "evening":
        evening_check()
    else:
        morning_push()
