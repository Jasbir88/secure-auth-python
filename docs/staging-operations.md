# Staging deployment operations

This runbook covers the private staging deployment of Secure Auth Python.

## Architecture

- FastAPI/Uvicorn application
- PostgreSQL persistent Docker volume
- Redis AOF persistent Docker volume
- Alembic migration service
- Tailscale Serve private HTTPS ingress
- PostgreSQL and Redis logical backups
- systemd health-monitor and backup timers

PostgreSQL and Redis expose no host ports.
The application remains bound to 127.0.0.1.

## Host prerequisites

Docker and Tailscale must be running.

Redis requires Linux memory overcommit:

    sysctl vm.overcommit_memory

Expected: vm.overcommit_memory = 1

Persistent configuration:

    echo 'vm.overcommit_memory = 1' | sudo tee /etc/sysctl.d/99-redis-overcommit.conf
    sudo sysctl -w vm.overcommit_memory=1

## Staging secrets

Create the ignored staging environment once:

    bash scripts/create_staging_env.sh

The resulting .env.staging must remain private and must never be committed.

## Staging lifecycle

    bash scripts/staging.sh up
    bash scripts/staging.sh verify
    bash scripts/staging.sh status
    bash scripts/staging.sh logs app
    bash scripts/staging.sh restart
    bash scripts/staging.sh stop
    bash scripts/staging.sh start
    bash scripts/staging.sh down

The down command retains persistent staging volumes.

## Private HTTPS

Enable and verify Tailscale Serve:

    bash scripts/staging_tailscale.sh enable
    bash scripts/staging_tailscale.sh verify
    bash scripts/staging_tailscale.sh status

Tailscale Serve must report tailnet only.
Tailscale Funnel must not be enabled.

## Pi-hole and MagicDNS

On this Pi-hole host, the tailnet DNS suffix is forwarded to
Tailscale MagicDNS at 100.100.100.100.

Validate Pi-hole before restarting it:

    sudo pihole-FTL dnsmasq-test

## Backup

Create a staging backup:

    bash scripts/backup_staging.sh

Backups are stored under backups/staging/<UTC timestamp>/.
Each backup contains PostgreSQL data, Redis state, checksums,
Alembic revision information, and recovery metadata.
Secrets are not included.

## Disaster recovery

Select the latest backup and run:

    bash scripts/restore_staging_backup.sh "$BACKUP_DIR"

A successful recovery ends with:

    DISASTER RECOVERY TEST: PASS

The recovery environment uses separate Docker volumes and port 3100.

## Monitoring

Run manually:

    bash scripts/monitor_staging.sh

Checks include application readiness, PostgreSQL, Redis,
Tailscale HTTPS, backup age, backup integrity, disk usage,
container resources, and restart counts.

Healthy result:

    STAGING MONITOR: PASS

## Structured logs

Request logs are emitted as JSON with request ID, method, path,
status code, duration, timestamp, and severity.

Authorization headers, query strings, passwords, and tokens are not logged.

View application logs:

    bash scripts/staging.sh logs app

## systemd automation

After deployment code is merged to main:

    sudo bash scripts/install_staging_systemd.sh

Then validate the units before enabling them.

Enable timers:

    sudo systemctl enable --now secure-auth-staging-monitor.timer secure-auth-staging-backup.timer

The monitor runs approximately every 10 minutes.
The backup runs daily around 03:30 local time.

## Full verification

Before merging deployment changes:

    bash scripts/verify_all.sh
    bash scripts/staging.sh verify
    bash scripts/staging_tailscale.sh verify
    bash scripts/monitor_staging.sh
    git diff --check

Required repository result:

    COMPOSE E2E SECURITY GATE: PASS
    FULL SECURITY VERIFICATION: PASS

## Rollback principle

Never delete persistent data merely to roll back application code.
Take a fresh backup before deployments involving database changes.
Record the deployed Git commit and verify health after deployment.

Alembic migrations are forward-managed. Rolling application code back
across an incompatible schema change requires explicit migration or
recovery planning rather than blindly checking out an older commit.
