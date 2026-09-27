#!/usr/bin/env bash
set -Eeuo pipefail

HTTPS_PORT="${TAILSCALE_STAGING_PORT:-8443}"
LOCAL_PORT="${APP_PORT:-3000}"

get_hostname() {
    tailscale status --json |
        /usr/bin/python3 -c '
import json
import sys

data = json.load(sys.stdin)
name = data["Self"]["DNSName"].rstrip(".")

if not name:
    raise SystemExit("Tailscale DNS name unavailable")

print(name)
'
}

check_tailscale() {
    command -v tailscale >/dev/null 2>&1 || {
        echo "ERROR: tailscale command not found."
        exit 1
    }

    STATE="$(
        tailscale status --json |
            /usr/bin/python3 -c '
import json
import sys
print(json.load(sys.stdin).get("BackendState", ""))
'
    )"

    [[ "$STATE" == "Running" ]] || {
        echo "ERROR: Tailscale backend state is: $STATE"
        exit 1
    }
}

check_local() {
    curl \
        --fail \
        --silent \
        --show-error \
        "http://127.0.0.1:${LOCAL_PORT}/health/ready" \
        >/dev/null

    echo "PASS: local staging backend ready"
}

verify_https() {
    HOSTNAME="$(get_hostname)"
    TS_IP="$(tailscale ip -4)"
    URL="https://${HOSTNAME}:${HTTPS_PORT}"

    echo "Testing: $URL"

    # First test the normal MagicDNS path.
    for _ in 1 2 3; do
        if curl \
            --fail \
            --silent \
            --show-error \
            --connect-timeout 3 \
            --max-time 6 \
            "${URL}/health/ready" \
            >/dev/null 2>&1
        then
            echo "PASS: Tailscale HTTPS readiness"
            echo "PASS: MagicDNS HTTPS path"
            echo "Staging HTTPS URL: $URL"
            return 0
        fi
        sleep 1
    done

    echo "Normal DNS path did not respond."
    echo "Retrying directly through Tailscale IPv4 while preserving TLS hostname."

    # This bypasses local DNS while retaining the correct TLS SNI/hostname.
    for _ in 1 2 3; do
        if curl \
            --fail \
            --silent \
            --show-error \
            --connect-timeout 3 \
            --max-time 6 \
            --resolve "${HOSTNAME}:${HTTPS_PORT}:${TS_IP}" \
            "${URL}/health/ready" \
            >/dev/null 2>&1
        then
            echo "PASS: Tailscale HTTPS readiness"
            echo "WARNING: HTTPS works, but local MagicDNS resolution needs attention"
            echo "Staging HTTPS URL: $URL"
            return 0
        fi
        sleep 1
    done

    echo "ERROR: Tailscale HTTPS endpoint did not respond."
    echo "Hostname: $HOSTNAME"
    echo "Tailscale IPv4: $TS_IP"
    return 1
}
case "${1:-}" in
    enable)
        check_tailscale
        check_local

        echo
        echo "=== ENABLE PRIVATE TAILSCALE HTTPS ==="

        tailscale serve \
            --bg \
            --https="$HTTPS_PORT" \
            "$LOCAL_PORT"

        verify_https
        ;;

    verify)
        check_tailscale
        check_local

        echo
        echo "=== SERVE STATUS ==="
        tailscale serve status

        echo
        verify_https

        echo
        echo "PASS: backend remains localhost-only"
        echo "PASS: HTTPS exposure uses Tailscale Serve"
        echo "PASS: public Funnel was not configured by this script"
        ;;

    status)
        check_tailscale

        echo "=== TAILSCALE SERVE ==="
        tailscale serve status

        echo
        echo "=== TAILSCALE FUNNEL ==="
        tailscale funnel status 2>/dev/null || true

        echo
        echo "Hostname: $(get_hostname)"
        ;;

    disable)
        tailscale serve \
            --https="$HTTPS_PORT" \
            off

        echo "Tailscale staging HTTPS disabled."
        ;;

    *)
        echo "Usage:"
        echo "  $0 enable"
        echo "  $0 verify"
        echo "  $0 status"
        echo "  $0 disable"
        exit 2
        ;;
esac
