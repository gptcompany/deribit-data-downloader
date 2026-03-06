#!/bin/bash
# Wrapper: run sync and send summary to Discord (optional)
set -euo pipefail

DISCORD_WEBHOOK_HISTORY="${DISCORD_WEBHOOK_HISTORY:-${DISCORD_WEBHOOK_CRON:-${DISCORD_WEBHOOK_CRONY:-${DISCORD_WEBHOOK_URL:-}}}}"
DISCORD_NOTIFY_ON_SUCCESS="${DISCORD_NOTIFY_ON_SUCCESS:-1}"
DISCORD_NOTIFY_ON_FAILURE="${DISCORD_NOTIFY_ON_FAILURE:-1}"
NO_DISCORD="${NO_DISCORD:-0}"

CURRENCY="${1:-}"

TMP_OUTPUT="$(mktemp -t deribit-sync.XXXXXX)"
cleanup() { rm -f "$TMP_OUTPUT"; }
trap cleanup EXIT

json_escape() {
    local s="${1:-}"
    s="${s//\\/\\\\}"
    s="${s//\"/\\\"}"
    s="${s//$'\n'/\\n}"
    printf '%s' "$s"
}

send_discord() {
    local msg="${1:-}"
    [ -z "${DISCORD_WEBHOOK_HISTORY:-}" ] && return 0
    [ "${NO_DISCORD}" = "1" ] && return 0

    local payload
    if command -v jq &> /dev/null; then
        payload="$(jq -nc --arg content "$msg" '{content:$content}')"
    else
        payload="{\"content\":\"$(json_escape "$msg")\"}"
    fi

    curl -fsS -m 10 -X POST -H "Content-Type: application/json" \
        -d "$payload" "$DISCORD_WEBHOOK_HISTORY" >/dev/null 2>&1 || true
}

build_summary() {
    local lines
    lines="$(grep -E "Sync BTC|Sync ETH|Synced [0-9,]+ new trades|Warning: [0-9,]+ trades failed to parse|Final batch:" "$TMP_OUTPUT" 2>/dev/null || true)"
    if [ -z "$lines" ]; then
        lines="$(tail -n 5 "$TMP_OUTPUT" 2>/dev/null || true)"
    fi
    if [ -n "$lines" ]; then
        echo "$lines" | head -n 12 | awk '{print substr($0,1,200)}'
    fi
}

set +e
EXIT_CODE=0
if [ -n "${CURRENCY}" ]; then
    deribit-data sync --currency "${CURRENCY}" 2>&1 | tee "$TMP_OUTPUT"
    EXIT_CODE=${PIPESTATUS[0]}
else
    deribit-data sync --currency BTC 2>&1 | tee "$TMP_OUTPUT"
    BTC_EXIT=${PIPESTATUS[0]}
    deribit-data sync --currency ETH 2>&1 | tee -a "$TMP_OUTPUT"
    ETH_EXIT=${PIPESTATUS[0]}
    if [ "$BTC_EXIT" -ne 0 ] || [ "$ETH_EXIT" -ne 0 ]; then
        EXIT_CODE=1
    fi
fi
set -e

SUMMARY="$(build_summary)"
if [ "$EXIT_CODE" -eq 0 ]; then
    if [ "${DISCORD_NOTIFY_ON_SUCCESS}" = "1" ]; then
        if [ -n "${SUMMARY:-}" ]; then
            send_discord "${SUMMARY}"
        else
            send_discord "Deribit sync completed"
        fi
    fi
else
    if [ "${DISCORD_NOTIFY_ON_FAILURE}" = "1" ]; then
        if [ -n "${SUMMARY:-}" ]; then
            send_discord "Deribit sync FAILED\n${SUMMARY}"
        else
            send_discord "Deribit sync FAILED"
        fi
    fi
fi

exit "$EXIT_CODE"
