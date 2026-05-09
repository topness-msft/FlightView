#!/bin/bash
# FlightView Kiosk Launcher with Auto-Recovery
# ------------------------------------------------
# Waits for the configured URL to be reachable, launches Chromium in kiosk
# mode, and watches for renderer crashes ("Aw, Snap" sad-doc page) or
# Chromium process death — restarting it automatically.
#
# Configurable via env vars:
#   KIOSK_URL         URL to load                 (default: http://localhost:5000)
#   KIOSK_DEBUG_PORT  Chrome DevTools port        (default: 9222)
#   KIOSK_LOG         Log file path               (default: ~/.local/share/flightview-kiosk.log)
#   KIOSK_PROBE_SEC   Seconds between health checks  (default: 30)
#   KIOSK_FAIL_LIMIT  Consecutive failures before restart (default: 2)

set -u

URL="${KIOSK_URL:-http://localhost:5000}"
PORT="${KIOSK_DEBUG_PORT:-9222}"
LOG="${KIOSK_LOG:-$HOME/.local/share/flightview-kiosk.log}"
PROBE_SEC="${KIOSK_PROBE_SEC:-30}"
FAIL_LIMIT="${KIOSK_FAIL_LIMIT:-2}"
WAIT_FOR_SERVER_SEC="${KIOSK_WAIT_SERVER_SEC:-180}"

mkdir -p "$(dirname "$LOG")"

log() {
    echo "[$(date '+%F %T')] $*" >>"$LOG"
}

wait_for_url() {
    log "waiting up to ${WAIT_FOR_SERVER_SEC}s for $URL"
    for _ in $(seq 1 "$WAIT_FOR_SERVER_SEC"); do
        if curl -fs -o /dev/null -m 2 "$URL"; then
            log "$URL is responsive"
            return 0
        fi
        sleep 1
    done
    log "WARN: $URL not responsive after ${WAIT_FOR_SERVER_SEC}s — launching anyway"
}

start_chromium() {
    # Note: Chromium ignores --disk-cache-dir=/dev/null on Wayland sometimes,
    # but the kiosk runs with disabled disk cache to keep RAM usage steady.
    chromium-browser \
        --kiosk \
        --noerrdialogs \
        --disable-infobars \
        --disable-translate \
        --no-first-run \
        --fast \
        --fast-start \
        --disable-features=TranslateUI \
        --disk-cache-dir=/dev/null \
        --remote-debugging-port="$PORT" \
        --remote-allow-origins="http://localhost:$PORT" \
        "$URL" >>"$LOG" 2>&1 &
    echo $!
}

# Returns 0 if Chromium tab(s) appear healthy, 1 otherwise.
# Detects:
#   * DevTools /json endpoint not responding (Chromium hung)
#   * No page-type targets at all
#   * Any page tab whose URL is chrome-error:// (sad doc / Aw Snap)
probe() {
    local tabs
    tabs="$(curl -fs -m 5 "http://localhost:$PORT/json" 2>/dev/null)" || return 1
    [ -n "$tabs" ] || return 1
    # Any crashed/error page?
    echo "$tabs" | grep -q 'chrome-error://' && return 1
    # At least one page tab present?
    echo "$tabs" | grep -q '"type": *"page"' || return 1
    return 0
}

kill_chromium() {
    local pid="$1"
    kill "$pid" 2>/dev/null || true
    for _ in 1 2 3 4 5; do
        kill -0 "$pid" 2>/dev/null || return 0
        sleep 1
    done
    kill -9 "$pid" 2>/dev/null || true
    # Belt-and-braces: nuke any stray kiosk-mode chromium too
    pkill -9 -f 'chromium.*--kiosk' 2>/dev/null || true
}

trap 'log "launcher received signal, exiting"; [ -n "${PID:-}" ] && kill "$PID" 2>/dev/null; exit 0' INT TERM

log "kiosk-launcher starting (URL=$URL, debug-port=$PORT)"
wait_for_url

while true; do
    log "starting chromium"
    PID=$(start_chromium)
    log "chromium PID=$PID"
    # Give Chromium time to come up before first probe
    sleep 15

    failures=0
    while kill -0 "$PID" 2>/dev/null; do
        sleep "$PROBE_SEC"
        if probe; then
            failures=0
        else
            failures=$((failures + 1))
            log "probe failed ($failures/$FAIL_LIMIT)"
            if [ "$failures" -ge "$FAIL_LIMIT" ]; then
                log "restart threshold hit — killing chromium"
                kill_chromium "$PID"
                break
            fi
        fi
    done

    log "chromium gone; respawning in 3s"
    sleep 3
done
