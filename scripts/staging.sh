#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

ENV_FILE=".env.staging"

if [[ ! -f "$ENV_FILE" ]]; then
    echo "ERROR: $ENV_FILE is missing."
    echo "Run: bash scripts/create_staging_env.sh"
    exit 1
fi

COMPOSE=(
    docker compose
    --env-file "$ENV_FILE"
    -p secure-auth-staging
    -f docker-compose.yml
    -f docker-compose.staging.yml
)

wait_ready() {
    for _ in $(seq 1 60); do
        if curl \
            --fail \
            --silent \
            --show-error \
            http://127.0.0.1:3000/health/ready \
            >/dev/null 2>&1
        then
            return 0
        fi

        sleep 1
    done

    echo "ERROR: staging application did not become ready."
    return 1
}

case "${1:-}" in
    up)
        "${COMPOSE[@]}" config --quiet

        if [[ -f ".release-state/staging.json" ]]; then
            echo "Release-managed staging detected."
            echo "Using existing immutable current image."
            "${COMPOSE[@]}" up -d --no-build
        else
            "${COMPOSE[@]}" build --pull
            "${COMPOSE[@]}" up -d
        fi

        wait_ready

        echo "STAGING: READY"
        "${COMPOSE[@]}" ps
        ;;

    down)
        "${COMPOSE[@]}" down --remove-orphans
        echo "STAGING: STOPPED — persistent volumes retained"
        ;;

    stop)
        "${COMPOSE[@]}" stop
        echo "STAGING: STOPPED — containers and volumes retained"
        ;;

    start)
        "${COMPOSE[@]}" start
        wait_ready
        echo "STAGING: READY"
        ;;

    restart)
        "${COMPOSE[@]}" restart app
        wait_ready
        echo "STAGING APP: RESTARTED AND READY"
        ;;

    status)
        "${COMPOSE[@]}" ps
        ;;

    logs)
        "${COMPOSE[@]}" logs --tail=200 "${2:-app}"
        ;;

    verify)
        "${COMPOSE[@]}" config --quiet

        curl \
            --fail \
            --silent \
            --show-error \
            http://127.0.0.1:3000/health/ready

        echo

        APP_ID="$("${COMPOSE[@]}" ps -q app)"
        REDIS_ID="$("${COMPOSE[@]}" ps -q redis)"
        DB_ID="$("${COMPOSE[@]}" ps -q db)"

        [[ -n "$APP_ID" ]] || {
            echo "ERROR: app container missing"
            exit 1
        }

        [[ -n "$REDIS_ID" ]] || {
            echo "ERROR: redis container missing"
            exit 1
        }

        [[ -n "$DB_ID" ]] || {
            echo "ERROR: db container missing"
            exit 1
        }

        APP_HEALTH="$(
            docker inspect "$APP_ID" \
                --format '{{.State.Health.Status}}'
        )"

        [[ "$APP_HEALTH" == "healthy" ]] || {
            echo "ERROR: app health=$APP_HEALTH"
            exit 1
        }

        REDIS_APPENDONLY="$(
            "${COMPOSE[@]}" exec -T redis \
                redis-cli CONFIG GET appendonly |
                tail -n 1
        )"

        [[ "$REDIS_APPENDONLY" == "yes" ]] || {
            echo "ERROR: Redis AOF persistence is disabled"
            exit 1
        }

        echo "PASS: application healthy"
        echo "PASS: PostgreSQL persistent service running"
        echo "PASS: Redis AOF persistence enabled"
        echo "PASS: staging verification complete"
        ;;

    *)
        echo "Usage:"
        echo "  $0 up"
        echo "  $0 down"
        echo "  $0 stop"
        echo "  $0 start"
        echo "  $0 restart"
        echo "  $0 status"
        echo "  $0 logs [service]"
        echo "  $0 verify"
        exit 2
        ;;
esac
