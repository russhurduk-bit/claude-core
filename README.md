# Pulse Core

A personal automation "pulse" - a set of small, independent scripts that keep an
eye on your infrastructure, watch for opportunities and content, queue tasks from
Telegram, and nudge you through a daily routine. Everything is glued together
with cron/systemd timers and SQLite; there is no framework and no always-on
service beyond the timers you choose to enable.

The headline component is a **two-stage AI pulse**: a cheap free-tier model
triages the current server state on every tick and only escalates to an
expensive top-tier agent when something actually needs attention - so quota is
spent only when it matters.

## Components

### The AI pulse (cost-aware autonomous loop)
- **`pulse_agent.sh`** - the loop. Enforces a kill-switch and a rolling-window
  rate limit, gathers infra context (memory, disk, failed units, journal errors,
  service health, pending tasks, recent activity), runs triage, and escalates to
  the senior LLM CLI only on `NEED_CLAUDE`. Fixes are applied via shell; a
  Telegram ping is sent when the owner needs to know.
- **`pulse_triage.py`** - the cheap filter. Calls a ladder of free OpenRouter
  models (with a Groq fallback) and returns a strict JSON verdict:
  `SKIP` or `NEED_CLAUDE` with an urgency. Fails safe to `NEED_CLAUDE`.
- **`pulse_ctl.sh`** - operator CLI: `status | pause | resume | now | last | log`,
  including triage stats (how many pulses were handled by the free model vs.
  escalated).

### Telegram I/O
- **`tg_task_queue.py`** - polls the owner's DMs via the Bot API, detects
  actionable messages heuristically, stores them in a SQLite queue and
  acknowledges them.
- **`tg_listener.py`** - reads the owner's latest messages via an external
  Telegram user CLI (configurable).
- **`tg_analyzer.py`** - read-only scan of watched chats for keyword-matched
  opportunities, then a digest to the owner.

### Content & knowledge
- **`content_monitor.py`** - watches YouTube channels via RSS, records new videos
  in SQLite, derives follow-up tasks from titles, and notifies.
- **`analyze_creators.py`** - pulls transcripts (yt-dlp), extracts insights with
  an LLM, and stores them in the knowledge base.
- **`content_pusher.py`** - a 30-day content plan: a themed prompt each morning
  and an accountability check each evening.

### Daily rhythm
- **`task_generator.py`** - builds a day-of-week-aware to-do list plus a service
  health snapshot and lead stats.
- **`weekly_report.py`** - a Sunday summary of knowledge-base entries, leads and
  git activity.
- **`daily_brain.sh`** - a morning server/service/git briefing over Telegram.
- **`session_init.sh`** - a start-of-session banner: pending tasks and key
  alerts.

## Design notes

- **Standalone scripts.** Each file is runnable on its own and configured purely
  through environment variables (loaded from `.env` if present). This makes them
  trivial to schedule individually with cron or systemd timers.
- **Cost control by design.** The triage/escalate split is the core idea: the
  expensive model is a last resort, guarded by both a triage verdict and a hard
  rate limit.
- **Fail safe.** Triage errors escalate rather than silently skip; missing config
  degrades gracefully (e.g. reads are skipped when no CLI is configured).
- **No secrets in code.** Tokens, chat IDs, API keys and paths all come from the
  environment. See `.env.example`.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # fill in tokens, IDs and paths
chmod +x *.sh
```

Then wire the pieces into cron or systemd timers, e.g.:

```cron
*/5  * * * *  /opt/pulse-core/tg_task_queue.py
0    7 * * *  /opt/pulse-core/content_pusher.py morning
0   17 * * *  /opt/pulse-core/content_pusher.py evening
5    5 * * *  /opt/pulse-core/task_generator.py
0    9 * * 0  /opt/pulse-core/weekly_report.py
0    5 * * *  /opt/pulse-core/daily_brain.sh
0  */6 * * *  /opt/pulse-core/content_monitor.py
```

The AI pulse (`pulse_agent.sh`) is best driven by a systemd timer at your chosen
cadence; `pulse_ctl.sh` manages it at runtime.

## Configuration

See **`.env.example`** for the full list. Key variables:

| Variable | Purpose |
| --- | --- |
| `TELEGRAM_BOT_TOKEN`, `OWNER_CHAT_ID` | Telegram bot + recipient |
| `OPENROUTER_API_KEY`, `GROQ_API_KEY` | Free-tier triage providers |
| `OPENAI_API_KEY` | Transcript analysis |
| `TG_CLI` | External Telegram user CLI for reads (optional) |
| `WATCH_SERVICES`, `GIT_REPOS` | What health/git snapshots cover |
| `RAG_DB`, `QUEUE_DB`, `CONTENT_DB` | SQLite locations |
| `LLM_CLI`, `PULSE_PROMPT` | Senior-agent CLI and its prompt file |
| `MAX_PER_WINDOW`, `WINDOW_HOURS` | Escalation rate limit |

> Note: `pulse_prompt.md` (the senior-agent instructions) is user-supplied and
> intentionally not included; point `PULSE_PROMPT` at your own.

## Tech stack

Python 3.11+, Bash, SQLite, cron/systemd, `requests`, `python-dotenv`, `yt-dlp`
(optional, for transcripts). LLMs via OpenRouter / Groq / OpenAI.
