#!/bin/bash
# PULSE CORE - Daily Brain
# Runs every morning via cron. Collects server metrics, service and n8n health,
# disk alerts and recent git activity, then sends a morning briefing to the owner.

CORE_DIR="${CORE_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
# Load local config if present
[ -f "$CORE_DIR/.env" ] && set -a && . "$CORE_DIR/.env" && set +a

LOG="${LOG_DIR:-/var/log}/pulse-core.log"
BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
CHAT_ID="${OWNER_CHAT_ID:-}"

# Services to check (space-separated); override via WATCH_SERVICES in .env
WATCH_SERVICES="${WATCH_SERVICES:-cloudflared render-worker content-generator scraper}"
# Repositories to summarize git activity for (space-separated absolute paths)
GIT_REPOS="${GIT_REPOS:-}"
N8N_HEALTH_URL="${N8N_HEALTH_URL:-http://127.0.0.1:5678/healthz}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG"; }
log "=== Daily Brain started ==="

# 1. Server health
RAM=$(free -h | awk '/Mem:/{print $3"/"$2}')
DISK=$(df -h / | awk 'NR==2{print $3"/"$2" ("$5")"}')
LOAD=$(uptime | awk -F'load average:' '{print $2}' | xargs)
UPTIME=$(uptime -p)

# 2. Service status
SERVICES=""
for svc in $WATCH_SERVICES; do
    status=$(systemctl is-active "$svc" 2>/dev/null)
    if [ "$status" != "active" ]; then
        SERVICES="${SERVICES}[DOWN] $svc: $status\n"
    fi
done
[ -z "$SERVICES" ] && SERVICES="All services OK"

# 3. n8n health (HTTP)
N8N_STATUS=$(curl -s --max-time 5 "$N8N_HEALTH_URL" 2>/dev/null)
if [ "$N8N_STATUS" = '{"status":"ok"}' ]; then
    N8N="n8n OK"
else
    N8N="n8n not responding"
fi

# 4. Disk alert
DISK_PCT=$(df / | awk 'NR==2{print $5}' | tr -d '%')
DISK_WARN=""
if [ "$DISK_PCT" -gt 85 ]; then
    DISK_WARN="WARNING: disk ${DISK_PCT}% full!"
fi

# 5. Recent git activity (last 24h)
GIT_ACTIVITY=""
for dir in $GIT_REPOS; do
    if [ -d "$dir/.git" ]; then
        name=$(basename "$dir")
        commits=$(git -C "$dir" log --oneline --since="24 hours ago" 2>/dev/null | wc -l)
        if [ "$commits" -gt 0 ]; then
            last=$(git -C "$dir" log --oneline -1 --format="%s" 2>/dev/null)
            GIT_ACTIVITY="${GIT_ACTIVITY}- ${name}: ${commits} commit(s) - ${last}\n"
        fi
    fi
done
[ -z "$GIT_ACTIVITY" ] && GIT_ACTIVITY="No commits in the last 24h"

# 6. Build morning message
MSG="*Pulse Core - Morning briefing*
$(date '+%d.%m.%Y, %H:%M UTC')

*Server:*
- RAM: ${RAM} | Disk: ${DISK}
- Load: ${LOAD}
- ${UPTIME}
${DISK_WARN}

*Services:*
$(echo -e "$SERVICES")

*n8n:* ${N8N}

*Git (24h):*
$(echo -e "$GIT_ACTIVITY")

_Open an agent session for full analysis and tasks_"

# 7. Send to Telegram
if [ -n "$BOT_TOKEN" ] && [ -n "$CHAT_ID" ]; then
    curl -s -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
      -d "chat_id=${CHAT_ID}" \
      --data-urlencode "text=${MSG}" \
      -d "parse_mode=Markdown" > /dev/null 2>&1
fi

log "Daily Brain completed, message sent"
