#!/bin/bash
# AI Pulse - control utility
PULSE_DIR="${CORE_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
[ -f "$PULSE_DIR/.env" ] && set -a && . "$PULSE_DIR/.env" && set +a

LOG_DIR="${LOG_DIR:-/var/log}"
MAX_PER_WINDOW="${MAX_PER_WINDOW:-12}"
TRIAGE_DIR="${THOUGHTS_DIR:-${LOG_DIR}/ai-pulse-thoughts}"

case "${1:-status}" in
    status)
        systemctl list-timers ai-pulse.timer --no-pager
        echo "---"
        CNT=$([ -f "${PULSE_DIR}/.pulse_counter" ] && wc -l < "${PULSE_DIR}/.pulse_counter" || echo 0)
        echo "Pulses in the last window: ${CNT}/${MAX_PER_WINDOW} (quota guard)"
        echo "Mode: $([ -f "${PULSE_DIR}/.pulse_pause" ] && echo 'PAUSED' || echo 'RUNNING')"
        # Triage stats (last 24h)
        if [ -d "$TRIAGE_DIR" ]; then
            TOTAL=$(find "$TRIAGE_DIR" -name "*.triage.json" -mtime -1 2>/dev/null | wc -l)
            SKIP=$(grep -l '"verdict":"SKIP"\|"verdict": "SKIP"' "$TRIAGE_DIR"/*.triage.json 2>/dev/null | wc -l)
            ESCALATED=$((TOTAL - SKIP))
            if [ "$TOTAL" -gt 0 ]; then
                echo "Last 24h: ${TOTAL} pulses -> ${SKIP} SKIP (free model) / ${ESCALATED} escalated"
            fi
        fi
        echo "---Last pulses---"
        tail -15 "${LOG_DIR}/ai-pulse.log"
        ;;
    pause)
        touch "${PULSE_DIR}/.pulse_pause"
        echo "PAUSED - remove ${PULSE_DIR}/.pulse_pause to resume"
        ;;
    resume)
        rm -f "${PULSE_DIR}/.pulse_pause"
        echo "RESUMED"
        ;;
    now)
        systemctl start ai-pulse.service
        sleep 3
        tail -5 "${LOG_DIR}/ai-pulse.log"
        ;;
    last)
        latest=$(ls -t "$TRIAGE_DIR"/*.log 2>/dev/null | head -1)
        echo "=== $latest ==="
        cat "$latest"
        ;;
    log)
        tail -100 "${LOG_DIR}/ai-pulse.log"
        ;;
    *)
        echo "Usage: $0 {status|pause|resume|now|last|log}"
        ;;
esac
