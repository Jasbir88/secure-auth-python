#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

[[ $# -eq 1 ]] || {
    echo "Usage: $0 backups/staging/<timestamp>"
    exit 2
}

BACKUP_DIR="$(realpath "$1")"
ENV_FILE=".env.staging"

[[ -f "$ENV_FILE" ]] || {
    echo "ERROR: $ENV_FILE is missing."
    exit 1
}

[[ -d "$BACKUP_DIR" ]] || {
    echo "ERROR: backup directory does not exist."
    exit 1
}

echo "=== VERIFY BACKUP INTEGRITY ==="

/usr/bin/python3 - "$BACKUP_DIR" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])

manifest = json.loads(
    (root / "manifest.json").read_text(encoding="utf-8")
)

for name, metadata in manifest["files"].items():
    path = root / name

    if not path.is_file():
        raise SystemExit(f"Missing backup file: {name}")

    actual = hashlib.sha256(path.read_bytes()).hexdigest()

    if actual != metadata["sha256"]:
        raise SystemExit(
            f"Checksum mismatch for {name}"
        )

print("BACKUP INTEGRITY: PASS")
PY

export APP_PORT="${RECOVERY_PORT:-3100}"

COMPOSE=(
    docker compose
    --env-file "$ENV_FILE"
    -p secure-auth-recovery
    -f docker-compose.yml
    -f docker-compose.staging.yml
)

wait_health() {
    local service="$1"
    local container=""
    local health=""

    for _ in $(seq 1 60); do
        container="$("${COMPOSE[@]}" ps -q "$service")"

        if [[ -n "$container" ]]; then
            health="$(
                docker inspect "$container" \
                    --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}'
            )"

            [[ "$health" == "healthy" ]] && return 0
        fi

        sleep 1
    done

    echo "ERROR: $service did not become healthy."
    return 1
}

wait_app() {
    for _ in $(seq 1 60); do
        if curl \
            --fail \
            --silent \
            --show-error \
            "http://127.0.0.1:${APP_PORT}/health/ready" \
            >/dev/null 2>&1
        then
            return 0
        fi

        sleep 1
    done

    echo "ERROR: recovery application did not become ready."
    return 1
}

echo
echo "=== CREATE ISOLATED RECOVERY ENVIRONMENT ==="

"${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true

"${COMPOSE[@]}" build app migrate

"${COMPOSE[@]}" up -d db redis

wait_health db
wait_health redis

echo "RECOVERY INFRASTRUCTURE: READY"

echo
echo "=== RESTORE POSTGRESQL ==="

"${COMPOSE[@]}" exec -T db \
    pg_restore \
        --exit-on-error \
        --clean \
        --if-exists \
        --no-owner \
        --no-privileges \
        -U postgres \
        -d auth_db \
    < "$BACKUP_DIR/postgres.dump"

echo "POSTGRESQL RESTORE: PASS"

echo
echo "=== RESTORE REDIS ==="

"${COMPOSE[@]}" run \
    --rm \
    -T \
    --no-deps \
    -v "$ROOT_DIR/scripts/redis_snapshot.py:/tools/redis_snapshot.py:ro" \
    app \
    python /tools/redis_snapshot.py restore \
    < "$BACKUP_DIR/redis.jsonl"

echo "REDIS RESTORE: PASS"

echo
echo "=== START RECOVERED APPLICATION ==="

"${COMPOSE[@]}" up -d migrate app

wait_app

echo "RECOVERY APPLICATION: READY"

read -r EXPECTED_USERS EXPECTED_REFRESH EXPECTED_REDIS EXPECTED_REVISION < <(
    /usr/bin/python3 - "$BACKUP_DIR/manifest.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    manifest = json.load(handle)

print(
    manifest["counts"]["users"],
    manifest["counts"]["refresh_tokens"],
    manifest["counts"]["redis_records"],
    manifest["alembic_revision"],
)
PY
)

ACTUAL_USERS="$(
    "${COMPOSE[@]}" exec -T db \
        psql -U postgres -d auth_db -At \
        -c 'SELECT COUNT(*) FROM users;'
)"

ACTUAL_REFRESH="$(
    "${COMPOSE[@]}" exec -T db \
        psql -U postgres -d auth_db -At \
        -c 'SELECT COUNT(*) FROM refresh_tokens;'
)"

ACTUAL_REDIS="$(
    "${COMPOSE[@]}" exec -T redis \
        redis-cli DBSIZE
)"

ACTUAL_REVISION="$(
    "${COMPOSE[@]}" exec -T db \
        psql -U postgres -d auth_db -At \
        -c 'SELECT version_num FROM alembic_version LIMIT 1;'
)"

[[ "$ACTUAL_USERS" == "$EXPECTED_USERS" ]] || {
    echo "ERROR: user count mismatch"
    exit 1
}

[[ "$ACTUAL_REFRESH" == "$EXPECTED_REFRESH" ]] || {
    echo "ERROR: refresh-token count mismatch"
    exit 1
}

# Expiring Redis records may legitimately expire between backup and restore.
[[ "$ACTUAL_REDIS" -le "$EXPECTED_REDIS" ]] || {
    echo "ERROR: recovered Redis contains unexpected records"
    exit 1
}

[[ "$ACTUAL_REVISION" == "$EXPECTED_REVISION" ]] || {
    echo "ERROR: Alembic revision mismatch"
    exit 1
}

echo
echo "PASS: PostgreSQL user count restored"
echo "PASS: PostgreSQL refresh-token count restored"
echo "PASS: Redis state restored without unexpected keys"
echo "PASS: Alembic revision restored"
echo "PASS: recovered application health/readiness"
echo
echo "======================================"
echo "DISASTER RECOVERY TEST: PASS"
echo "Recovery URL: http://127.0.0.1:${APP_PORT}"
echo "======================================"

"${COMPOSE[@]}" ps
