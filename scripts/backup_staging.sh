#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

ENV_FILE=".env.staging"

[[ -f "$ENV_FILE" ]] || {
    echo "ERROR: $ENV_FILE is missing."
    exit 1
}

COMPOSE=(
    docker compose
    --env-file "$ENV_FILE"
    -p secure-auth-staging
    -f docker-compose.yml
    -f docker-compose.staging.yml
)

bash scripts/staging.sh verify >/dev/null

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_DIR="backups/staging/$STAMP"

umask 077
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

echo "=== POSTGRESQL BACKUP ==="

"${COMPOSE[@]}" exec -T db \
    pg_dump \
        -U postgres \
        -d auth_db \
        -Fc \
        --no-owner \
        --no-privileges \
    > "$BACKUP_DIR/postgres.dump"

test -s "$BACKUP_DIR/postgres.dump"

echo "PostgreSQL backup: PASS"

echo
echo "=== REDIS BACKUP ==="

"${COMPOSE[@]}" run \
    --rm \
    -T \
    --no-deps \
    -v "$ROOT_DIR/scripts/redis_snapshot.py:/tools/redis_snapshot.py:ro" \
    app \
    python /tools/redis_snapshot.py dump \
    > "$BACKUP_DIR/redis.jsonl"

touch "$BACKUP_DIR/redis.jsonl"

echo "Redis backup: PASS"

ALEMBIC_REVISION="$(
    "${COMPOSE[@]}" exec -T db \
        psql \
        -U postgres \
        -d auth_db \
        -At \
        -c 'SELECT version_num FROM alembic_version LIMIT 1;'
)"

USER_COUNT="$(
    "${COMPOSE[@]}" exec -T db \
        psql \
        -U postgres \
        -d auth_db \
        -At \
        -c 'SELECT COUNT(*) FROM users;'
)"

REFRESH_COUNT="$(
    "${COMPOSE[@]}" exec -T db \
        psql \
        -U postgres \
        -d auth_db \
        -At \
        -c 'SELECT COUNT(*) FROM refresh_tokens;'
)"

REDIS_COUNT="$(wc -l < "$BACKUP_DIR/redis.jsonl")"
GIT_COMMIT="$(git rev-parse HEAD)"

if [[ -n "$(git status --porcelain)" ]]; then
    WORKTREE_DIRTY=true
else
    WORKTREE_DIRTY=false
fi

/usr/bin/python3 - \
    "$BACKUP_DIR" \
    "$ALEMBIC_REVISION" \
    "$USER_COUNT" \
    "$REFRESH_COUNT" \
    "$REDIS_COUNT" \
    "$GIT_COMMIT" \
    "$WORKTREE_DIRTY" <<'PY'
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

(
    backup_dir,
    alembic_revision,
    user_count,
    refresh_count,
    redis_count,
    git_commit,
    worktree_dirty,
) = sys.argv[1:]

root = Path(backup_dir)

files = {}

for name in ("postgres.dump", "redis.jsonl"):
    path = root / name

    digest = hashlib.sha256(path.read_bytes()).hexdigest()

    files[name] = {
        "sha256": digest,
        "bytes": path.stat().st_size,
    }

manifest = {
    "created_at": datetime.now(UTC).isoformat(),
    "git_commit": git_commit,
    "working_tree_dirty": worktree_dirty == "true",
    "alembic_revision": alembic_revision,
    "counts": {
        "users": int(user_count),
        "refresh_tokens": int(refresh_count),
        "redis_records": int(redis_count),
    },
    "files": files,
    "secrets_included": False,
}

(root / "manifest.json").write_text(
    json.dumps(manifest, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY

chmod -R go-rwx "$BACKUP_DIR"

echo
echo "======================================"
echo "STAGING BACKUP: PASS"
echo "Backup directory: $BACKUP_DIR"
echo "Secrets included: NO"
echo "======================================"
