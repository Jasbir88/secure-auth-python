#!/usr/bin/env bash
set -uo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

MAX_BACKUP_AGE_HOURS="${MONITOR_BACKUP_MAX_AGE_HOURS:-26}"
MAX_DISK_PERCENT="${MONITOR_DISK_MAX_PERCENT:-90}"

FAILED=0

pass() {
    echo "PASS: $*"
}

warn() {
    echo "WARN: $*"
}

fail() {
    echo "FAIL: $*" >&2
    FAILED=1
}

echo "======================================"
echo "SECURE AUTH STAGING MONITOR"
echo "UTC: $(date -u +%FT%TZ)"
echo "======================================"

echo
echo "=== APPLICATION ==="

if bash scripts/staging.sh verify >/tmp/secure-auth-staging-check 2>&1; then
    pass "staging application and dependencies healthy"
else
    cat /tmp/secure-auth-staging-check >&2
    fail "staging verification failed"
fi

echo
echo "=== PRIVATE HTTPS ==="

if bash scripts/staging_tailscale.sh verify \
    >/tmp/secure-auth-tailscale-check 2>&1
then
    pass "Tailscale HTTPS healthy"
else
    cat /tmp/secure-auth-tailscale-check >&2
    fail "Tailscale HTTPS verification failed"
fi

echo
echo "=== BACKUP AGE ==="

LATEST_MANIFEST="$(
    find backups/staging \
        -mindepth 2 \
        -maxdepth 2 \
        -name manifest.json \
        -type f \
        2>/dev/null |
    sort |
    tail -n 1
)"

if [[ -z "$LATEST_MANIFEST" ]]; then
    fail "no staging backup manifest found"
else
    NOW="$(date +%s)"
    BACKUP_TIME="$(stat -c %Y "$LATEST_MANIFEST")"
    AGE_SECONDS=$((NOW - BACKUP_TIME))
    AGE_HOURS=$((AGE_SECONDS / 3600))

    if (( AGE_HOURS > MAX_BACKUP_AGE_HOURS )); then
        fail "latest backup is ${AGE_HOURS}h old"
    else
        pass "latest backup age ${AGE_HOURS}h"
    fi

    BACKUP_DIR="$(dirname "$LATEST_MANIFEST")"

    if python - "$BACKUP_DIR" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
manifest = json.loads(
    (root / "manifest.json").read_text(encoding="utf-8")
)

for name, expected in manifest["files"].items():
    path = root / name

    if not path.is_file():
        raise SystemExit(f"missing backup file: {name}")

    actual = hashlib.sha256(path.read_bytes()).hexdigest()

    if actual != expected["sha256"]:
        raise SystemExit(f"checksum mismatch: {name}")
PY
    then
        pass "latest backup checksums valid"
    else
        fail "latest backup integrity check failed"
    fi
fi

echo
echo "=== HOST STORAGE ==="

DISK_PERCENT="$(
    df -P "$ROOT_DIR" |
    awk 'NR == 2 {
        gsub("%", "", $5)
        print $5
    }'
)"

echo "Repository filesystem usage: ${DISK_PERCENT}%"

if (( DISK_PERCENT >= MAX_DISK_PERCENT )); then
    fail "filesystem usage reached ${DISK_PERCENT}%"
else
    pass "filesystem capacity healthy"
fi

echo
echo "=== CONTAINER RESOURCES ==="

COMPOSE=(
    docker compose
    --env-file .env.staging
    -p secure-auth-staging
    -f docker-compose.yml
    -f docker-compose.staging.yml
)

CONTAINER_IDS="$("${COMPOSE[@]}" ps -q)"

if [[ -n "$CONTAINER_IDS" ]]; then
    # Snapshot only: high CPU at one instant is informational,
    # not by itself an outage condition.
    docker stats \
        --no-stream \
        --format \
        'RESOURCE: {{.Name}} CPU={{.CPUPerc}} MEM={{.MemUsage}} PIDS={{.PIDs}}' \
        $CONTAINER_IDS || \
        warn "docker resource snapshot unavailable"

    for SERVICE in app db redis; do
        ID="$("${COMPOSE[@]}" ps -q "$SERVICE")"

        if [[ -n "$ID" ]]; then
            RESTARTS="$(
                docker inspect "$ID" \
                    --format '{{.RestartCount}}'
            )"

            echo "RESTARTS: $SERVICE=$RESTARTS"

            if (( RESTARTS > 0 )); then
                warn "$SERVICE has restarted $RESTARTS time(s)"
            fi
        fi
    done
else
    fail "no staging containers found"
fi

echo

if (( FAILED != 0 )); then
    logger \
        -p user.err \
        -t secure-auth-staging-monitor \
        "Secure Auth staging monitor FAILED. Run: journalctl -t secure-auth-staging-monitor"

    echo "======================================"
    echo "STAGING MONITOR: FAIL"
    echo "======================================"
    exit 1
fi

logger \
    -p user.info \
    -t secure-auth-staging-monitor \
    "Secure Auth staging monitor PASS"

echo "======================================"
echo "STAGING MONITOR: PASS"
echo "======================================"
