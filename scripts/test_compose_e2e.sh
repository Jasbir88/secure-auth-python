#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

API_URL="${API_URL:-http://127.0.0.1:3000}"

export JWT_SECRET_KEY="${JWT_SECRET_KEY:-$(
python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
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

docker compose config --format json > "$TMP_DIR/compose.json"

python3 - "$TMP_DIR/compose.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    config = json.load(handle)

services = config["services"]

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
    or str(port.get("published")) != "3000"
    or port.get("host_ip") != "127.0.0.1"
):
    raise SystemExit(
        f"app port is not restricted to 127.0.0.1:3000: {port}"
    )

print("PASS: Compose host exposure is restricted.")
PY

python3 scripts/check_compose_security.py

echo
echo "=== CLEAN START ==="

docker compose down -v --remove-orphans >/dev/null 2>&1 || true

docker compose build --pull
docker compose up -d

wait_ready >/dev/null
pass "application readiness"

MIGRATE_EXIT="$(
    docker inspect auth-migrate \
        --format '{{.State.ExitCode}}'
)"

[ "$MIGRATE_EXIT" = "0" ] ||
    fail "initial migration exited $MIGRATE_EXIT"

pass "initial migration"

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

docker start auth-migrate >/dev/null
MIGRATE_EXIT="$(docker wait auth-migrate)"

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
