#!/usr/bin/env python3
"""
Pulse Core - Content Monitor.

Watches a list of YouTube channels via their RSS feeds, stores newly published
videos in SQLite, derives lightweight follow-up tasks from the titles and
notifies the owner about fresh content. Cron example: every 6 hours.
"""
import os
import re
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
DB = os.environ.get("CONTENT_DB", os.path.join(CORE_DIR, "data", "content.db"))
LOG = os.path.join(LOG_DIR, "pulse-core-content.log")

# Channels to monitor - replace with your own handles.
YT_CHANNELS = [
    {"handle": "@example_creator_one", "name": "Creator One", "niche": "business/launches"},
    {"handle": "@example_creator_two", "name": "Creator Two", "niche": "agency/freelance"},
    {"handle": "@example_creator_three", "name": "Creator Three", "niche": "AI agents/automation"},
]


def log(msg):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG, "a") as f:
        f.write(f"[{ts}] {msg}\n")


def init_db():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    db = sqlite3.connect(DB)
    db.execute("""CREATE TABLE IF NOT EXISTS videos (
        id TEXT PRIMARY KEY,
        channel TEXT,
        title TEXT,
        url TEXT,
        published TEXT,
        analyzed INTEGER DEFAULT 0,
        insights TEXT,
        created_at TEXT
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS tasks_generated (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT,
        task TEXT,
        priority TEXT,
        status TEXT DEFAULT 'pending',
        created_at TEXT
    )""")
    db.commit()
    return db


def fetch_yt_rss(handle):
    """Resolve a channel handle to its id, then fetch the RSS feed."""
    try:
        r = requests.get(f"https://www.youtube.com/{handle}",
                         headers={"User-Agent": "Mozilla/5.0"},
                         timeout=10, allow_redirects=True)
        match = re.search(r'"channelId":"(UC[^"]+)"', r.text)
        if match:
            channel_id = match.group(1)
            rss = requests.get(
                f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}",
                timeout=10)
            return rss.text
    except Exception as e:
        log(f"Error fetching {handle}: {e}")
    return None


def parse_rss(xml_text):
    """Parse a YouTube RSS feed into a list of recent videos."""
    videos = []
    entries = re.findall(r'<entry>(.*?)</entry>', xml_text, re.DOTALL)
    for entry in entries[:5]:
        vid_id = re.search(r'<yt:videoId>(.*?)</yt:videoId>', entry)
        title = re.search(r'<title>(.*?)</title>', entry)
        published = re.search(r'<published>(.*?)</published>', entry)
        if vid_id and title:
            videos.append({
                'id': vid_id.group(1),
                'title': title.group(1),
                'url': f"https://youtu.be/{vid_id.group(1)}",
                'published': published.group(1) if published else ''
            })
    return videos


def send_telegram(text):
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                      data={"chat_id": OWNER_ID, "text": text, "parse_mode": "Markdown"},
                      timeout=10)
    except Exception:
        pass


def generate_tasks(db):
    """Derive simple follow-up tasks from recently analyzed video titles."""
    rows = db.execute("""
        SELECT channel, title, insights FROM videos
        WHERE analyzed=1 AND created_at > datetime('now', '-7 days')
        ORDER BY created_at DESC LIMIT 10
    """).fetchall()

    if not rows:
        return []

    tasks = []
    for channel, title, insights in rows:
        tl = title.lower()
        if any(w in tl for w in ['n8n', 'automation', 'agent']):
            tasks.append(("\U0001F7E2 Growth", f"Study '{title[:50]}' from {channel} - may help with gigs"))
        if any(w in tl for w in ['revenue', 'client', 'sales', 'funnel']):
            tasks.append(("\U0001F7E1 Important", f"Apply ideas from '{title[:50]}' - {channel}"))
        if any(w in tl for w in ['claude', 'gpt', 'cursor', 'new']):
            tasks.append(("\U0001F534 Urgent", f"New tool/update: '{title[:50]}' - check it"))

    return tasks[:5]


def main():
    log("Content monitor started")
    db = init_db()

    new_videos = 0
    for ch in YT_CHANNELS:
        xml = fetch_yt_rss(ch['handle'])
        if not xml:
            continue
        for v in parse_rss(xml):
            exists = db.execute("SELECT 1 FROM videos WHERE id=?", (v['id'],)).fetchone()
            if not exists:
                db.execute(
                    "INSERT INTO videos (id, channel, title, url, published, created_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (v['id'], ch['name'], v['title'], v['url'], v['published'],
                     datetime.datetime.now(datetime.UTC).isoformat()))
                new_videos += 1
                log(f"New video: {ch['name']} - {v['title']}")

    db.commit()

    if new_videos > 0:
        recent = db.execute("""
            SELECT channel, title, url FROM videos
            WHERE analyzed=0 ORDER BY created_at DESC LIMIT 5
        """).fetchall()

        msg = f"\U0001F4FA *New creator content* ({new_videos} videos)\n\n"
        for ch, title, url in recent:
            msg += f"*{ch}*\n{title}\n{url}\n\n"

        tasks = generate_tasks(db)
        if tasks:
            msg += "*\U0001F4CB Content-based tasks:*\n"
            for priority, task in tasks:
                msg += f"{priority} {task}\n"

        send_telegram(msg)
        log(f"Sent notification: {new_videos} new videos")
    else:
        log("No new videos")

    db.close()


if __name__ == "__main__":
    main()
