#!/usr/bin/env python3
"""
Pulse Core - Creator video analyzer.

Downloads transcripts of a creator's recent videos, extracts actionable insights
with an LLM and stores them in the knowledge base (SQLite). Notifies the owner
when finished. Designed to run in the background.

Requires: yt-dlp on PATH, OPENAI_API_KEY in the environment.
"""
import os
import re
import time
import uuid
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
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
CORE_DIR = os.environ.get("CORE_DIR", os.path.dirname(os.path.abspath(__file__)))
RAG_DB = os.environ.get("RAG_DB", os.path.join(CORE_DIR, "data", "memory.db"))
LOG_DIR = os.environ.get("LOG_DIR", "/var/log")
LOG = os.path.join(LOG_DIR, "pulse-core-creators.log")
SUB_LANG = os.environ.get("SUBTITLE_LANG", "en")

# Creators to analyze - replace with your own handles.
CREATORS = {
    "creator_one": {
        "name": "Creator One",
        "handle": "@example_creator_one",
        "kb_tag": "kb,creator_one",
        "focus": "personal brand, short-form video, social media, content, sales, launches"
    },
    "creator_two": {
        "name": "Creator Two",
        "handle": "@example_creator_two",
        "kb_tag": "kb,creator_two",
        "focus": "AI coding agents, agent teams, MCP, n8n, automation, tooling"
    }
}


def log(msg):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG, "a") as f:
        f.write(f"[{ts}] {msg}\n")
    print(msg, flush=True)


def send_tg(text):
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                      data={"chat_id": OWNER_ID, "text": text, "parse_mode": "Markdown"},
                      timeout=10)
    except Exception:
        pass


def get_video_list(handle):
    """Scrape the channel's videos page for the most recent video ids/titles."""
    try:
        r = requests.get(
            f"https://www.youtube.com/{handle}/videos",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            timeout=15)
        videos, seen = [], set()
        matches = re.findall(r'"videoId":"([^"]{11})".*?"text":"([^"]{5,100})"', r.text)
        for vid_id, title in matches:
            if vid_id not in seen and not title.startswith('{'):
                seen.add(vid_id)
                videos.append({"id": vid_id, "title": title, "url": f"https://youtu.be/{vid_id}"})
        return videos[:40]
    except Exception as e:
        log(f"Error getting videos for {handle}: {e}")
        return []


def get_transcript(video_url):
    """Fetch a transcript using yt-dlp auto-generated subtitles."""
    vid_id = video_url.split("/")[-1].split("?")[0]
    try:
        subprocess.run(
            ["yt-dlp", "--skip-download", "--write-auto-sub", "--sub-lang", SUB_LANG,
             "--convert-subs", "srt", "-o", f"/tmp/yt_{vid_id}", video_url],
            capture_output=True, text=True, timeout=30
        )
        srt_file = f"/tmp/yt_{vid_id}.{SUB_LANG}.srt"
        if os.path.exists(srt_file):
            with open(srt_file) as f:
                text = f.read()
            text = re.sub(r'\d+\n\d{2}:\d{2}:\d{2},\d+ --> \d{2}:\d{2}:\d{2},\d+\n', '', text)
            text = re.sub(r'\n{2,}', '\n', text).strip()
            os.unlink(srt_file)
            return text
    except Exception:
        pass
    return None


def analyze_with_gpt(transcript, creator_name, focus):
    """Use a small chat model to extract insights from a transcript."""
    if not OPENAI_API_KEY or not transcript:
        return None

    prompt = f"""Analyze this video transcript from {creator_name}.
Focus: {focus}

Extract:
1. Key ideas (3-5 bullets)
2. Concrete tips/tools
3. What can be applied right now (actionable)

Be specific, no filler. Max 300 words.

Transcript (first 3000 chars):
{transcript[:3000]}"""

    try:
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}",
                     "Content-Type": "application/json"},
            json={
                "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 1000
            }, timeout=30)
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        log(f"LLM error: {e}")
        return None


def save_to_rag(title, content, tags):
    db = sqlite3.connect(RAG_DB)
    now = datetime.datetime.now(datetime.UTC).isoformat()
    db.execute(
        'INSERT INTO memories (id,title,content,type,tags,created_at,updated_at) '
        'VALUES (?,?,?,?,?,?,?)',
        (str(uuid.uuid4()), title, content, 'reference', tags, now, now))
    db.commit()
    db.close()


def main():
    log("=== Creator Analysis Started ===")

    total_analyzed = 0
    all_insights = {}

    for key, creator in CREATORS.items():
        log(f"\n--- {creator['name']} ({creator['handle']}) ---")

        videos = get_video_list(creator['handle'])
        log(f"Found {len(videos)} videos")

        insights_list = []
        for i, video in enumerate(videos[:30]):
            log(f"  [{i + 1}] {video['title']}")

            transcript = get_transcript(video['url'])
            if not transcript:
                log("    No transcript available")
                continue
            log(f"    Transcript: {len(transcript)} chars")

            analysis = analyze_with_gpt(transcript, creator['name'], creator['focus'])
            if analysis:
                insights_list.append(f"### {video['title']}\n{video['url']}\n\n{analysis}")
                total_analyzed += 1
                log("    Analyzed OK")

            time.sleep(2)  # Rate limit

        if insights_list:
            full_content = (f"## {creator['name']} - video analysis\n\n"
                            + "\n\n---\n\n".join(insights_list))
            save_to_rag(
                f"KB: {creator['name']} - analysis of {len(insights_list)} videos",
                full_content,
                creator['kb_tag']
            )
            all_insights[creator['name']] = insights_list
            log(f"Saved {len(insights_list)} analyses for {creator['name']}")

    msg = "\U0001F4DA *Creator content analysis complete*\n\n"
    msg += f"Analyzed {total_analyzed} videos\n\n"
    for name, insights in all_insights.items():
        msg += f"*{name}:* {len(insights)} videos\n"
    msg += "\nAll insights saved to the knowledge base."

    send_tg(msg)
    log(f"\n=== Done! Total: {total_analyzed} videos analyzed ===")


if __name__ == "__main__":
    main()
