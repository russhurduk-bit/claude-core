#!/bin/bash
# Pulse Core - AI Pulse Agent
# Background "thinking" loop (e.g. every 30 min by day / 2h at night via timer).
# Wakes up, gathers infra context, runs a cheap triage on a free model, and only
# escalates to the expensive top-tier agent when triage says it's needed - which
# keeps LLM quota usage low.

set -uo pipefail

PULSE_DIR="${CORE_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
# Load local config if present
[ -f "$PULSE_DIR/.env" ] && set -a && . "$PULSE_DIR/.env" && set +a

LOG="${LOG_DIR:-/var/log}/ai-pulse.log"
THOUGHTS_DIR="${THOUGHTS_DIR:-${LOG_DIR:-/var/log}/ai-pulse-thoughts}"
PAUSE_FLAG="${PULSE_DIR}/.pulse_pause"
COUNTER_FILE="${PULSE_DIR}/.pulse_counter"
PROMPT_FILE="${PULSE_PROMPT:-${PULSE_DIR}/pulse_prompt.md}"
# LLM CLI used for the escalation step (must accept a prompt on stdin)
LLM_CLI="${LLM_CLI:-claude}"

# Quota guard: max escalations per rolling window.
MAX_PER_WINDOW="${MAX_PER_WINDOW:-12}"
WINDOW_HOURS="${WINDOW_HOURS:-5}"
BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
CHAT_ID="${OWNER_CHAT_ID:-}"

mkdir -p "$THOUGHTS_DIR"
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG"; }

# Kill-switch
if [ -f "$PAUSE_FLAG" ]; then
    log "PAUSED via $PAUSE_FLAG - skipping"
    exit 0
fi

# Rate-limit guard over the rolling window
NOW_TS=$(date -u +%s)
WINDOW_START=$((NOW_TS - WINDOW_HOURS * 3600))
touch "$COUNTER_FILE"
awk -v cutoff="$WINDOW_START" '$1 >= cutoff' "$COUNTER_FILE" > "${COUNTER_FILE}.tmp" && mv "${COUNTER_FILE}.tmp" "$COUNTER_FILE"
PULSES_IN_WINDOW=$(wc -l < "$COUNTER_FILE")
if [ "$PULSES_IN_WINDOW" -ge "$MAX_PER_WINDOW" ]; then
    log "RATE LIMIT: ${PULSES_IN_WINDOW}/${MAX_PER_WINDOW} pulses in ${WINDOW_HOURS}h - skip to protect quota"
    exit 0
fi
echo "$NOW_TS" >> "$COUNTER_FILE"

PULSE_ID="$(date -u +%Y%m%d-%H%M%S)"
THOUGHT_FILE="${THOUGHTS_DIR}/${PULSE_ID}.log"
TRIAGE_LOG="${THOUGHTS_DIR}/${PULSE_ID}.triage.json"

log "=== Pulse ${PULSE_ID} start (window: ${PULSES_IN_WINDOW}/${MAX_PER_WINDOW} per ${WINDOW_HOURS}h) ==="

# Gather context
CTX_FILE="$(mktemp)"
{
    echo "# Pulse Context (${PULSE_ID})"
    echo
    echo "## Time"
    echo "UTC: $(date -u '+%Y-%m-%d %H:%M:%S')"
    echo
    echo "## Server"
    free -h | head -2
    echo
    df -h / | head -2
    echo
    uptime
    echo
    echo "## Failed systemd units"
    systemctl --failed --no-pager --no-legend 2>/dev/null | head -20 || echo "none"
    echo
    echo "## Key services (active/inactive)"
    # n8n often runs in Docker rather than systemd - check via docker + healthz
    n8n_docker=$(docker ps --filter "name=^n8n$" --format '{{.Status}}' 2>/dev/null | head -1)
    n8n_http=$(curl -s -o /dev/null -w "%{http_code}" --max-time 3 "${N8N_HEALTH_URL:-http://127.0.0.1:5678/healthz}" 2>/dev/null)
    if [ -n "$n8n_docker" ] && [ "$n8n_http" = "200" ]; then
        echo "  n8n: active (docker: $n8n_docker, healthz 200)"
    else
        echo "  n8n: inactive (docker='$n8n_docker' http=$n8n_http)"
    fi
    for svc in ${WATCH_SERVICES:-cloudflared render-worker content-generator scraper}; do
        st=$(systemctl is-active "$svc" 2>/dev/null || echo "missing")
        echo "  $svc: $st"
    done
    echo
    echo "## Recent journal errors (30 min)"
    journalctl --since "30 minutes ago" -p err --no-pager 2>/dev/null | tail -30 || echo "none"
    echo
    echo "## Pending tasks from the owner"
    sqlite3 "${QUEUE_DB:-${PULSE_DIR}/data/task_queue.db}" "SELECT id,substr(text,1,120),created_at FROM tasks WHERE status='pending' ORDER BY id DESC LIMIT 5" 2>/dev/null || echo "no db/tasks"
    echo
    echo "## Last 3 pulses (what was done)"
    ls -t "${THOUGHTS_DIR}"/*.log 2>/dev/null | head -3 | while read f; do
        echo "### $(basename "$f" .log)"
        tail -5 "$f" 2>/dev/null
    done
} > "$CTX_FILE"

# === Stage 1: TRIAGE on a free model ===
# The triage ladder decides whether the senior agent is needed at all.
TRIAGE_JSON=$(cat "$CTX_FILE" | timeout 45 python3 "${PULSE_DIR}/pulse_triage.py" 2>/dev/null || echo '{"verdict":"NEED_CLAUDE","reason":"triage crashed","urgency":"normal"}')
echo "$TRIAGE_JSON" > "$TRIAGE_LOG"
TRIAGE_VERDICT=$(echo "$TRIAGE_JSON" | python3 -c "import json,sys; print(json.loads(sys.stdin.read()).get('verdict','NEED_CLAUDE'))" 2>/dev/null || echo "NEED_CLAUDE")
TRIAGE_REASON=$(echo "$TRIAGE_JSON" | python3 -c "import json,sys; print(json.loads(sys.stdin.read()).get('reason',''))" 2>/dev/null || echo "")
TRIAGE_MODEL=$(echo "$TRIAGE_JSON" | python3 -c "import json,sys; print(json.loads(sys.stdin.read()).get('_model','?'))" 2>/dev/null || echo "?")

log "triage=${TRIAGE_VERDICT} via=${TRIAGE_MODEL} reason=${TRIAGE_REASON:0:80}"

if [ "$TRIAGE_VERDICT" = "SKIP" ]; then
    # Triage says all clear - don't spend the expensive quota
    echo "SKIP by triage: ${TRIAGE_REASON}" > "$THOUGHT_FILE"
    rm -f "$CTX_FILE"
    find "$THOUGHTS_DIR" -name "*.log" -mtime +14 -delete 2>/dev/null
    find "$THOUGHTS_DIR" -name "*.triage.json" -mtime +14 -delete 2>/dev/null
    log "=== Pulse ${PULSE_ID} end (SKIPPED, quota untouched) ==="
    exit 0
fi

# === Stage 2: senior agent (only if triage said NEED_CLAUDE) ===
PROMPT_CAT="$(cat "$PROMPT_FILE" 2>/dev/null)
---
# TRIAGE VERDICT (free model ${TRIAGE_MODEL})
${TRIAGE_JSON}
---
# CURRENT CONTEXT
$(cat "$CTX_FILE")
---
Act. If something needs fixing - fix it via bash. End with a single JSON line in the required format."

# Use timeout so a stuck pulse doesn't accumulate
RESP=$(timeout 600 "$LLM_CLI" -p --output-format text --permission-mode bypassPermissions <<< "$PROMPT_CAT" 2>&1 || echo '{"status":"error","actions_taken":["LLM CLI timeout or failed"],"notify_owner":false,"notify_text":"","next_focus":"debug"}')

echo "$RESP" > "$THOUGHT_FILE"

# Extract the last JSON line for the decision
JSON_LINE=$(echo "$RESP" | grep -E '^\{.*"status".*\}$' | tail -1)
if [ -z "$JSON_LINE" ]; then
    JSON_LINE=$(echo "$RESP" | tail -1)
fi

STATUS=$(echo "$JSON_LINE" | python3 -c "import json,sys; print(json.loads(sys.stdin.read()).get('status','unknown'))" 2>/dev/null || echo "parse_error")
NOTIFY=$(echo "$JSON_LINE" | python3 -c "import json,sys; print(json.loads(sys.stdin.read()).get('notify_owner',False))" 2>/dev/null || echo "False")
NOTIFY_TEXT=$(echo "$JSON_LINE" | python3 -c "import json,sys; print(json.loads(sys.stdin.read()).get('notify_text',''))" 2>/dev/null || echo "")

log "pulse=${PULSE_ID} status=${STATUS} notify=${NOTIFY}"

# Notify the owner on Telegram if needed
if [ "$NOTIFY" = "True" ] && [ -n "$NOTIFY_TEXT" ] && [ -n "$BOT_TOKEN" ] && [ -n "$CHAT_ID" ]; then
    curl -s -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
        --data-urlencode "chat_id=${CHAT_ID}" \
        --data-urlencode "text=Pulse ${PULSE_ID}: ${NOTIFY_TEXT}" > /dev/null
    log "notified owner: ${NOTIFY_TEXT:0:100}"
fi

# Rotate thoughts older than 14 days
find "$THOUGHTS_DIR" -name "*.log" -mtime +14 -delete 2>/dev/null

rm -f "$CTX_FILE"
log "=== Pulse ${PULSE_ID} end ==="
