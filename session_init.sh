#!/bin/bash
# Pulse Core - Session Init
# Run at the start of each agent session. Prints pending tasks and key alerts.

CORE_DIR="${CORE_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
[ -f "$CORE_DIR/.env" ] && set -a && . "$CORE_DIR/.env" && set +a

QUEUE_DB="${QUEUE_DB:-${CORE_DIR}/data/task_queue.db}"
WATCH_SERVICES="${WATCH_SERVICES:-cloudflared render-worker content-generator}"

echo "Pulse Core - Session Init"
echo "=========================="

# Pending tasks
if [ -f "$QUEUE_DB" ]; then
    PENDING=$(sqlite3 "$QUEUE_DB" "SELECT COUNT(*) FROM tasks WHERE status='pending'" 2>/dev/null)
    if [ "${PENDING:-0}" -gt 0 ]; then
        echo ""
        echo "Pending tasks ($PENDING):"
        sqlite3 "$QUEUE_DB" "SELECT '  - ' || substr(text,1,80) || CASE WHEN length(text)>80 THEN '...' ELSE '' END FROM tasks WHERE status='pending' ORDER BY created_at DESC LIMIT 10" 2>/dev/null
        echo ""
    fi
fi

# Server alerts
DISK_PCT=$(df / | awk 'NR==2{print $5}' | tr -d '%')
if [ "$DISK_PCT" -gt 85 ]; then
    echo "WARNING: disk ${DISK_PCT}%"
fi

RAM_FREE=$(free -m | awk '/Mem:/{print $7}')
if [ "$RAM_FREE" -lt 1024 ]; then
    echo "WARNING: free RAM ${RAM_FREE}MB"
fi

# Failed services
for svc in $WATCH_SERVICES; do
    if ! systemctl is-active "$svc" > /dev/null 2>&1; then
        echo "DOWN: $svc is not running!"
    fi
done

echo ""
