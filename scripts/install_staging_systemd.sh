#!/usr/bin/env bash
set -Eeuo pipefail

[[ "$EUID" -eq 0 ]] || {
    echo "Run with sudo:"
    echo "  sudo bash scripts/install_staging_systemd.sh"
    exit 1
}

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

RUN_USER="$(stat -c '%U' "$ROOT_DIR")"
RUN_GROUP="$(id -gn "$RUN_USER")"
RUN_HOME="$(getent passwd "$RUN_USER" | cut -d: -f6)"

/usr/bin/python3 - "$ROOT_DIR" "$RUN_USER" "$RUN_GROUP" "$RUN_HOME" <<'UNITPY'
from pathlib import Path
import sys

root_dir, run_user, run_group, run_home = sys.argv[1:]

units = {
    "secure-auth-staging-monitor.service": f"""[Unit]
Description=Secure Auth staging health monitor
After=docker.service tailscaled.service
Requires=docker.service

[Service]
Type=oneshot
User={run_user}
Group={run_group}
WorkingDirectory={root_dir}
Environment=HOME={run_home}
ExecStart=/usr/bin/bash {root_dir}/scripts/monitor_staging.sh
NoNewPrivileges=true
PrivateTmp=true
""",

    "secure-auth-staging-monitor.timer": """[Unit]
Description=Run Secure Auth staging monitor every 10 minutes

[Timer]
OnBootSec=3min
OnUnitActiveSec=10min
AccuracySec=1min
Persistent=true

[Install]
WantedBy=timers.target
""",

    "secure-auth-staging-backup.service": f"""[Unit]
Description=Secure Auth staging backup
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
User={run_user}
Group={run_group}
WorkingDirectory={root_dir}
Environment=HOME={run_home}
ExecStart=/usr/bin/bash {root_dir}/scripts/backup_staging.sh
NoNewPrivileges=true
PrivateTmp=true
""",

    "secure-auth-staging-backup.timer": """[Unit]
Description=Daily Secure Auth staging backup

[Timer]
OnCalendar=*-*-* 03:30:00
RandomizedDelaySec=5min
Persistent=true

[Install]
WantedBy=timers.target
""",
}

target = Path("/etc/systemd/system")

for name, body in units.items():
    (target / name).write_text(body, encoding="utf-8")

UNITPY

systemctl daemon-reload

echo "Systemd units installed."
echo "They have NOT been enabled automatically."
