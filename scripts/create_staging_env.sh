#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

ENV_FILE=".env.staging"

if [[ -e "$ENV_FILE" && "${1:-}" != "--force" ]]; then
    echo "ERROR: $ENV_FILE already exists."
    echo "Use --force only if you intentionally want to rotate staging secrets."
    exit 1
fi

umask 077

python - <<'PY'
import secrets
from pathlib import Path

path = Path(".env.staging")

content = "\n".join(
    [
        "COMPOSE_PROJECT_NAME=secure-auth-staging",
        f"POSTGRES_PASSWORD={secrets.token_urlsafe(32)}",
        f"JWT_SECRET_KEY={secrets.token_urlsafe(48)}",
        "",
    ]
)

path.write_text(content, encoding="utf-8")
PY

chmod 600 "$ENV_FILE"

echo "Staging environment created: $ENV_FILE"
echo "Permissions:"
stat -c '%a %n' "$ENV_FILE"
