#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -z "${APP_PORT:-}" ]]; then
    APP_PORT="$(
        python3 - <<'PYPORT'
import socket

with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    print(sock.getsockname()[1])
PYPORT
    )"
fi

export APP_PORT

API_URL="${API_URL:-http://127.0.0.1:${APP_PORT}}"

export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-secure-auth-e2e-$$}"

export JWT_SECRET_KEY="${JWT_SECRET_KEY:-$(
python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
)}"

export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-$(
python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(32))
PY
)}"

TMP_DIR="$(mktemp -d)"

cleanup() {
    rc=$?
    set +e

    if [ "$rc" -ne 0 ]; then
        echo
        echo "=== FAILURE DIAGNOSTICS ==="
        docker compose ps -a
        echo
        docker compose logs --no-color --tail=200
    fi

    docker compose down -v --remove-orphans >/dev/null 2>&1 || true
    rm -rf "$TMP_DIR"

    exit "$rc"
}

trap cleanup EXIT

pass() {
    printf 'PASS: %s\n' "$1"
}

fail() {
    printf 'FAIL: %s\n' "$1" >&2
    exit 1
}

expect_http() {
    label="$1"
    expected="$2"
    actual="$3"

    if [ "$actual" != "$expected" ]; then
        fail "$label expected HTTP $expected, got $actual"
    fi

    pass "$label (HTTP $actual)"
}

json_get() {
    python3 - "$1" "$2" <<'PY'
import json
import sys

path, key = sys.argv[1:3]

with open(path, encoding="utf-8") as handle:
    value = json.load(handle)[key]

if not isinstance(value, str) or not value:
    raise SystemExit(f"missing or invalid JSON field: {key}")

print(value)
PY
}

wait_ready() {
    for _ in $(seq 1 60); do
        body="$(
            curl -fsS "$API_URL/health/ready" 2>/dev/null || true
        )"

        if printf '%s' "$body" |
            grep -q '"status":"ready"'; then
            printf '%s\n' "$body"
            return 0
        fi

        sleep 1
    done

    fail "application did not become ready"
}

echo "=== COMPOSE CONFIGURATION ==="

PYTHON_PIN_COUNT="$(
    grep -Ec '^FROM python:3\.12-slim@sha256:[0-9a-f]{64}' Dockerfile
)"

[ "$PYTHON_PIN_COUNT" = "2" ] ||
    fail "Dockerfile Python base images are not digest-pinned"

pass "Dockerfile base images are digest-pinned"

docker compose config --format json > "$TMP_DIR/compose.json"

python3 - "$TMP_DIR/compose.json" "$APP_PORT" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    config = json.load(handle)

expected_app_port = str(sys.argv[2])

services = config["services"]

import re

digest_pattern = re.compile(r"@sha256:[0-9a-f]{64}$")

for service_name in ("db", "redis"):
    image = services[service_name].get("image", "")

    if not digest_pattern.search(image):
        raise SystemExit(
            f"{service_name} image is not digest-pinned: {image}"
        )

print("PASS: Compose service images are digest-pinned.")

for service_name, service in services.items():
    if service.get("container_name"):
        raise SystemExit(
            f"{service_name} uses a fixed container name"
        )

print("PASS: Compose avoids fixed container names.")

expected_pids = {
    "db": 256,
    "redis": 128,
    "migrate": 128,
    "app": 128,
}

for service_name, expected in expected_pids.items():
    service = services[service_name]

    if int(service.get("pids_limit") or 0) != expected:
        raise SystemExit(
            f"{service_name} has incorrect pids_limit"
        )

    logging = service.get("logging") or {}
    options = logging.get("options") or {}

    if logging.get("driver") != "json-file":
        raise SystemExit(
            f"{service_name} does not use bounded json-file logging"
        )

    if (
        str(options.get("max-size")) != "10m"
        or str(options.get("max-file")) != "3"
    ):
        raise SystemExit(
            f"{service_name} log rotation limits are incorrect"
        )

print("PASS: Compose PID and log limits are configured.")

if not services["app"].get("healthcheck"):
    raise SystemExit(
        "application Docker healthcheck is missing"
    )

print("PASS: application Docker healthcheck is configured.")

for service_name in ("db", "redis"):
    ports = services[service_name].get("ports") or []
    if ports:
        raise SystemExit(
            f"{service_name} unexpectedly publishes host ports: {ports}"
        )

app_ports = services["app"].get("ports") or []

if len(app_ports) != 1:
    raise SystemExit(
        f"app must publish exactly one host port, got: {app_ports}"
    )

port = app_ports[0]

if (
    str(port.get("target")) != "3000"
    or str(port.get("published")) != expected_app_port
    or port.get("host_ip") != "127.0.0.1"
):
    raise SystemExit(
        "app port is not restricted to "
        f"127.0.0.1:{expected_app_port}: {port}"
    )

print(
    "PASS: Compose host exposure is restricted "
    f"to 127.0.0.1:{expected_app_port}."
)

for service_name in ("app", "migrate"):
    service = services[service_name]

    cap_drop = {
        str(value).upper()
        for value in service.get("cap_drop", [])
    }

    if "ALL" not in cap_drop:
        raise SystemExit(
            f"{service_name} does not drop all Linux capabilities"
        )

    security_options = {
        str(value).lower()
        for value in service.get("security_opt", [])
    }

    if "no-new-privileges:true" not in security_options:
        raise SystemExit(
            f"{service_name} does not enforce no-new-privileges"
        )

    if service.get("read_only") is not True:
        raise SystemExit(
            f"{service_name} root filesystem is not read-only"
        )

    tmpfs_entries = service.get("tmpfs") or []

    tmpfs_paths = set()

    for entry in tmpfs_entries:
        if isinstance(entry, str):
            tmpfs_paths.add(entry.split(":", 1)[0])
        elif isinstance(entry, dict):
            target = entry.get("target")
            if target:
                tmpfs_paths.add(target)

    if "/tmp" not in tmpfs_paths:
        raise SystemExit(
            f"{service_name} does not provide a /tmp tmpfs"
        )

print("PASS: Compose runtime privileges are restricted.")
print("PASS: Compose root filesystems are read-only.")
PY

python3 scripts/check_compose_security.py

echo
echo "=== CLEAN START ==="

docker compose down -v --remove-orphans >/dev/null 2>&1 || true

docker compose build --pull
docker compose up -d

wait_ready >/dev/null
pass "application readiness"

APP_CONTAINER="$(docker compose ps -q app)"

[ -n "$APP_CONTAINER" ] ||
    fail "application container was not created"

APP_HEALTH=""

for _ in $(seq 1 30); do
    APP_HEALTH="$(
        docker inspect "$APP_CONTAINER" \
            --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}'
    )"

    [ "$APP_HEALTH" = "healthy" ] && break
    sleep 1
done

[ "$APP_HEALTH" = "healthy" ] ||
    fail "application Docker healthcheck did not become healthy"

pass "application Docker healthcheck"


MIGRATE_ID="$(docker compose ps -aq migrate)"

[ -n "$MIGRATE_ID" ] ||
    fail "migration container was not created"

MIGRATE_EXIT="$(
    docker inspect "$MIGRATE_ID" \
        --format '{{.State.ExitCode}}'
)"

[ "$MIGRATE_EXIT" = "0" ] ||
    fail "initial migration exited $MIGRATE_EXIT"

pass "initial migration"

echo
echo "=== CONTAINER RUNTIME HARDENING ==="

APP_UID="$(docker compose exec -T app id -u)"

[ "$APP_UID" != "0" ] ||
    fail "application container is running as root"

for service_name in app migrate; do
    container="$(docker compose ps -aq "$service_name")"

    [ -n "$container" ] ||
        fail "$service_name container was not created"

    configured_user="$(
        docker inspect "$container"             --format '{{.Config.User}}'
    )"

    case "$configured_user" in
        ""|0|root|0:0)
            fail "$container has an unsafe configured user"
            ;;
    esac
done

docker compose exec -T app sh -ec '
for tool in git gcc pytest black ruff; do
    if command -v "$tool" >/dev/null 2>&1; then
        echo "unexpected production tool: $tool" >&2
        exit 1
    fi
done
'

pass "containers run non-root"
pass "production image excludes build and development tools"

for service_name in app migrate; do
    container="$(docker compose ps -aq "$service_name")"

    [ -n "$container" ] ||
        fail "$service_name container was not created"

    read_only="$(
        docker inspect "$container"             --format '{{.HostConfig.ReadonlyRootfs}}'
    )"

    [ "$read_only" = "true" ] ||
        fail "$container root filesystem is not read-only"

    tmpfs_options="$(
        docker inspect "$container"             --format '{{index .HostConfig.Tmpfs "/tmp"}}'
    )"

    for option in noexec nosuid nodev; do
        case ",$tmpfs_options," in
            *",$option,"*)
                ;;
            *)
                fail "$container /tmp is missing $option"
                ;;
        esac
    done
done

if docker compose exec -T app sh -ec     'touch /app/.secure-auth-write-probe 2>/dev/null'
then
    docker compose exec -T app         rm -f /app/.secure-auth-write-probe || true
    fail "application could write to its read-only root filesystem"
fi

pass "application root filesystem rejects writes"

docker compose exec -T app sh -ec '
probe=/tmp/.secure-auth-tmpfs-probe
printf "ok" > "$probe"
test "$(cat "$probe")" = "ok"
rm -f "$probe"
'

pass "/tmp tmpfs remains writable"

SUFFIX="$(
python3 - <<'PY'
import secrets
print(secrets.token_hex(8))
PY
)"

EMAIL="compose-e2e-${SUFFIX}@example.com"
PASSWORD='SecurePass123!'

echo
echo "=== 1. REGISTER ==="

REGISTER_CODE="$(
    curl -sS \
        -o "$TMP_DIR/register.json" \
        -w '%{http_code}' \
        -X POST "$API_URL/auth/register" \
        -H 'Content-Type: application/json' \
        -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}"
)"

expect_http "registration" 201 "$REGISTER_CODE"

ACCESS1="$(json_get "$TMP_DIR/register.json" access_token)"
REFRESH1="$(json_get "$TMP_DIR/register.json" refresh_token)"

echo
echo "=== 2. PROTECTED ACCESS ==="

ME_CODE="$(
    curl -sS \
        -o "$TMP_DIR/me.json" \
        -w '%{http_code}' \
        "$API_URL/users/me" \
        -H "Authorization: Bearer $ACCESS1"
)"

expect_http "protected access" 200 "$ME_CODE"

echo
echo "=== 3. REFRESH ROTATION ==="

REFRESH_CODE="$(
    curl -sS \
        -o "$TMP_DIR/refresh.json" \
        -w '%{http_code}' \
        -X POST "$API_URL/auth/refresh" \
        -H 'Content-Type: application/json' \
        -d "{\"refresh_token\":\"$REFRESH1\"}"
)"

expect_http "refresh rotation request" 200 "$REFRESH_CODE"

ACCESS2="$(json_get "$TMP_DIR/refresh.json" access_token)"
REFRESH2="$(json_get "$TMP_DIR/refresh.json" refresh_token)"

[ "$REFRESH1" != "$REFRESH2" ] ||
    fail "refresh token did not rotate"

[ "$ACCESS1" != "$ACCESS2" ] ||
    fail "access token did not rotate"

pass "token rotation"

echo
echo "=== 4. OLD REFRESH REUSE ==="

REUSE_CODE="$(
    curl -sS \
        -o "$TMP_DIR/reuse.json" \
        -w '%{http_code}' \
        -X POST "$API_URL/auth/refresh" \
        -H 'Content-Type: application/json' \
        -d "{\"refresh_token\":\"$REFRESH1\"}"
)"

expect_http "old refresh reuse rejection" 401 "$REUSE_CODE"

echo
echo "=== 5. FAMILY REVOCATION ==="

FAMILY_CODE="$(
    curl -sS \
        -o "$TMP_DIR/family.json" \
        -w '%{http_code}' \
        -X POST "$API_URL/auth/refresh" \
        -H 'Content-Type: application/json' \
        -d "{\"refresh_token\":\"$REFRESH2\"}"
)"

expect_http "refresh family revocation" 401 "$FAMILY_CODE"

echo
echo "=== 6. FRESH LOGIN ==="

LOGIN_CODE="$(
    curl -sS \
        -o "$TMP_DIR/login.json" \
        -w '%{http_code}' \
        -X POST "$API_URL/auth/login" \
        -H 'Content-Type: application/json' \
        -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}"
)"

expect_http "fresh login" 200 "$LOGIN_CODE"

ACCESS3="$(json_get "$TMP_DIR/login.json" access_token)"
REFRESH3="$(json_get "$TMP_DIR/login.json" refresh_token)"

echo
echo "=== 7. LOGOUT ==="

LOGOUT_CODE="$(
    curl -sS \
        -o "$TMP_DIR/logout.json" \
        -w '%{http_code}' \
        -X POST "$API_URL/auth/logout" \
        -H 'Content-Type: application/json' \
        -H "Authorization: Bearer $ACCESS3" \
        -d "{\"refresh_token\":\"$REFRESH3\"}"
)"

expect_http "logout" 200 "$LOGOUT_CODE"

echo
echo "=== 8. ACCESS REVOCATION ==="

REVOKED_CODE="$(
    curl -sS \
        -o "$TMP_DIR/revoked.json" \
        -w '%{http_code}' \
        "$API_URL/users/me" \
        -H "Authorization: Bearer $ACCESS3"
)"

expect_http "revoked access rejection" 401 "$REVOKED_CODE"

echo
echo "=== 9. APP RESTART ==="

docker compose restart app >/dev/null
wait_ready >/dev/null

pass "application restart readiness"

echo
echo "=== 10. REVOCATION PERSISTENCE ==="

RESTART_REVOKED_CODE="$(
    curl -sS \
        -o "$TMP_DIR/restart-revoked.json" \
        -w '%{http_code}' \
        "$API_URL/users/me" \
        -H "Authorization: Bearer $ACCESS3"
)"

expect_http \
    "revocation survived application restart" \
    401 \
    "$RESTART_REVOKED_CODE"

echo
echo "=== 11. IDEMPOTENT MIGRATION ==="

docker start "$MIGRATE_ID" >/dev/null
MIGRATE_EXIT="$(docker wait "$MIGRATE_ID")"

[ "$MIGRATE_EXIT" = "0" ] ||
    fail "migration rerun exited $MIGRATE_EXIT"

pass "migration rerun"

echo
echo "=== 12. DATA PERSISTENCE ==="

PERSIST_CODE="$(
    curl -sS \
        -o "$TMP_DIR/persist.json" \
        -w '%{http_code}' \
        -X POST "$API_URL/auth/login" \
        -H 'Content-Type: application/json' \
        -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}"
)"

expect_http \
    "user data survived migration rerun" \
    200 \
    "$PERSIST_CODE"

wait_ready >/dev/null
pass "final readiness"

echo
docker compose ps -a

echo
echo "======================================"
echo "COMPOSE E2E SECURITY GATE: PASS"
echo "======================================"
