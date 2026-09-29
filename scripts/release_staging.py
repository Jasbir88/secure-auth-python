#!/usr/bin/env python3
"""Safe staging release and rollback controller."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import smtplib
import ssl
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env.staging"
STATE_DIR = ROOT / ".release-state"
STATE_FILE = STATE_DIR / "staging.json"
LOCK_FILE = STATE_DIR / "staging-operation.lock"


class ReleaseError(RuntimeError):
    """Controlled release-operation failure."""


COMPOSE_BASE = [
    "docker",
    "compose",
    "--env-file",
    str(ENV_FILE),
    "-p",
    "secure-auth-staging",
    "-f",
    str(ROOT / "docker-compose.yml"),
    "-f",
    str(ROOT / "docker-compose.staging.yml"),
]


def run(
    command: list[str],
    *,
    env: dict[str, str] | None = None,
    capture: bool = False,
    check: bool = True,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=capture,
        check=check,
        input=input_text,
    )


def output(command: list[str], *, env=None) -> str:
    result = run(
        command,
        env=env,
        capture=True,
    )
    return result.stdout.strip()


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def release_env(
    *,
    release_id: str,
    channel: str = "current",
) -> dict[str, str]:
    env = os.environ.copy()
    env["RELEASE_ID"] = release_id
    env["RELEASE_CHANNEL"] = channel
    return env


def compose(
    *args: str,
    env: dict[str, str] | None = None,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    return run(
        [*COMPOSE_BASE, *args],
        env=env,
        capture=capture,
    )


def ensure_prerequisites() -> None:
    if not ENV_FILE.is_file():
        raise ReleaseError("ERROR: .env.staging is missing.")

    STATE_DIR.mkdir(mode=0o700, exist_ok=True)
    os.chmod(STATE_DIR, 0o700)


def acquire_lock():
    ensure_prerequisites()

    handle = LOCK_FILE.open("a+")
    try:
        fcntl.flock(
            handle.fileno(),
            fcntl.LOCK_EX | fcntl.LOCK_NB,
        )
    except BlockingIOError:
        handle.close()
        raise ReleaseError("ERROR: another staging release/backup operation is active.")

    return handle


def git_head() -> str:
    return output(["git", "rev-parse", "HEAD"])


def git_branch() -> str:
    return output(["git", "branch", "--show-current"])


def git_dirty() -> bool:
    return bool(output(["git", "status", "--porcelain"]))


def require_clean_main() -> str:
    branch = git_branch()

    if branch != "main":
        raise ReleaseError(f"ERROR: releases require branch main; current={branch}")

    if git_dirty():
        raise ReleaseError("ERROR: working tree is dirty; refusing deployment.")

    run(
        [
            "git",
            "fetch",
            "--quiet",
            "origin",
            "main",
        ]
    )

    local = git_head()
    remote = output(["git", "rev-parse", "origin/main"])

    if local != remote:
        raise ReleaseError(
            "ERROR: local main is not exactly origin/main; "
            "pull the latest main before deploying."
        )

    return local


def staging_env_value(name: str) -> str:
    """Read one value from the controlled staging env file."""
    for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)

        if key != name:
            continue

        value = value.strip()

        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]

        if not value:
            break

        return value

    raise ReleaseError(f"ERROR: {name} is missing from .env.staging.")


def verify_db_credentials() -> None:
    """Prove .env.staging authenticates before deployment."""
    password = staging_env_value("POSTGRES_PASSWORD")

    result = run(
        [
            *COMPOSE_BASE,
            "ps",
            "-q",
            "db",
        ],
        capture=True,
        check=False,
    )

    container = result.stdout.strip()

    if result.returncode != 0 or not container:
        raise ReleaseError("ERROR: staging database container is unavailable.")

    # PostgreSQL .pgpass escapes backslashes and colons.
    escaped = password.replace("\\", "\\\\").replace(":", "\\:")

    pgpass = "127.0.0.1:5432:" f"auth_db:postgres:{escaped}\n"

    shell = """
set -eu
file="$(mktemp)"
trap 'rm -f "$file"' EXIT
chmod 600 "$file"
cat > "$file"
PGPASSFILE="$file" \
    psql \
    -h 127.0.0.1 \
    -U postgres \
    -d auth_db \
    -At \
    -c 'SELECT 1;'
"""

    probe = run(
        [
            "docker",
            "exec",
            "-i",
            container,
            "sh",
            "-c",
            shell,
        ],
        input_text=pgpass,
        capture=True,
        check=False,
    )

    if probe.returncode != 0 or probe.stdout.strip() != "1":
        raise ReleaseError(
            "ERROR: .env.staging PostgreSQL credential "
            "preflight failed; refusing deployment."
        )

    print("PASS: .env.staging PostgreSQL " "credentials authenticate")


def verify_smtp_credentials() -> None:
    """Prove staging SMTP connectivity, TLS, and authentication."""
    host = staging_env_value("SMTP_HOST")
    username = staging_env_value("SMTP_USERNAME")
    password = staging_env_value("SMTP_PASSWORD")
    from_email = staging_env_value("SMTP_FROM_EMAIL")

    try:
        port = int(staging_env_value("SMTP_PORT"))
    except ValueError as exc:
        raise ReleaseError("ERROR: SMTP_PORT must be an integer.") from exc

    try:
        timeout = float(staging_env_value("SMTP_TIMEOUT_SECONDS"))
    except ValueError as exc:
        raise ReleaseError("ERROR: SMTP_TIMEOUT_SECONDS must be numeric.") from exc

    if not 1 <= port <= 65535:
        raise ReleaseError("ERROR: SMTP_PORT is outside the valid range.")

    if not 0 < timeout <= 60:
        raise ReleaseError(
            "ERROR: SMTP_TIMEOUT_SECONDS must be greater than 0 and at most 60."
        )

    starttls_raw = staging_env_value("SMTP_STARTTLS").lower()

    if starttls_raw not in {"true", "false"}:
        raise ReleaseError("ERROR: SMTP_STARTTLS must be true or false.")

    starttls = starttls_raw == "true"

    if "@" not in from_email:
        raise ReleaseError("ERROR: SMTP_FROM_EMAIL is not a valid email address.")

    try:
        with smtplib.SMTP(
            host,
            port,
            timeout=timeout,
        ) as smtp:
            smtp.ehlo()

            if starttls:
                smtp.starttls(context=ssl.create_default_context())
                smtp.ehlo()

            smtp.login(
                username,
                password,
            )

            code, _message = smtp.noop()

            if code != 250:
                raise ReleaseError(
                    "ERROR: SMTP server did not accept authenticated NOOP."
                )

    except ReleaseError:
        raise
    except (
        OSError,
        smtplib.SMTPException,
    ) as exc:
        raise ReleaseError(
            "ERROR: staging SMTP credential preflight failed; " "refusing deployment."
        ) from exc

    print("PASS: staging SMTP TLS/authentication preflight")


def db_revision() -> str:
    return output(
        [
            *COMPOSE_BASE,
            "exec",
            "-T",
            "db",
            "psql",
            "-U",
            "postgres",
            "-d",
            "auth_db",
            "-At",
            "-c",
            ("SELECT version_num " "FROM alembic_version LIMIT 1;"),
        ]
    )


def rendered_app_image(
    env: dict[str, str],
) -> str:
    raw = output(
        [
            *COMPOSE_BASE,
            "config",
            "--format",
            "json",
        ],
        env=env,
    )

    config = json.loads(raw)
    return str(config["services"]["app"]["image"])


def immutable_image(
    current_image: str,
    release_id: str,
) -> str:
    repository, separator, _tag = current_image.rpartition(":")

    if not separator:
        raise ReleaseError(f"ERROR: unexpected image reference: {current_image}")

    return f"{repository}:{release_id}"


def image_id(image: str) -> str:
    return output(
        [
            "docker",
            "image",
            "inspect",
            image,
            "--format",
            "{{.Id}}",
        ]
    )


def image_revision(image: str) -> str:
    return output(
        [
            "docker",
            "image",
            "inspect",
            image,
            "--format",
            ("{{index .Config.Labels " '"org.opencontainers.image.revision"}}'),
        ]
    )


def running_app_image_id() -> str | None:
    result = subprocess.run(
        [*COMPOSE_BASE, "ps", "-q", "app"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    container = result.stdout.strip()

    if not container:
        return None

    return output(
        [
            "docker",
            "inspect",
            container,
            "--format",
            "{{.Image}}",
        ]
    )


def read_state() -> dict[str, Any] | None:
    if not STATE_FILE.is_file():
        return None

    with STATE_FILE.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_state(state: dict[str, Any]) -> None:
    STATE_DIR.mkdir(mode=0o700, exist_ok=True)

    temporary = STATE_FILE.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            state,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    os.chmod(temporary, 0o600)
    temporary.replace(STATE_FILE)


def latest_backup() -> str:
    manifests = sorted((ROOT / "backups" / "staging").glob("*/manifest.json"))

    if not manifests:
        raise ReleaseError("ERROR: backup command completed but no manifest exists.")

    return str(manifests[-1].parent.relative_to(ROOT))


def create_backup() -> str:
    print("\n=== PRE-OPERATION BACKUP ===")

    env = os.environ.copy()
    env["SECURE_AUTH_OPERATION_LOCK_HELD"] = "1"

    run(
        ["bash", "scripts/backup_staging.sh"],
        env=env,
    )

    backup = latest_backup()

    print(f"Backup recorded: {backup}")
    return backup


def verify_staging() -> None:
    print("\n=== POST-DEPLOY VERIFICATION ===")

    run(["bash", "scripts/staging.sh", "verify"])
    run(
        [
            "bash",
            "scripts/staging_tailscale.sh",
            "verify",
        ]
    )
    run(["bash", "scripts/monitor_staging.sh"])


def build_release(
    release_id: str,
) -> tuple[str, str, str]:
    current_env = release_env(
        release_id=release_id,
        channel="current",
    )
    immutable_env = release_env(
        release_id=release_id,
        channel=release_id,
    )

    current = rendered_app_image(current_env)
    immutable = rendered_app_image(immutable_env)

    expected_immutable = immutable_image(
        current,
        release_id,
    )

    if immutable != expected_immutable:
        raise ReleaseError(
            "ERROR: immutable release image reference "
            f"does not match expectation: {immutable}"
        )

    print("\n=== BUILD IMMUTABLE RELEASE ===")
    print(f"Release: {release_id}")
    print(f"Current pointer: {current}")
    print(f"Immutable image: {immutable}")

    # Build directly to the immutable Git-SHA tag.
    # Do not mutate the :current deployment pointer yet.
    compose(
        "build",
        "--pull",
        "app",
        env=immutable_env,
    )

    immutable_id = image_id(immutable)
    revision = image_revision(immutable)

    if revision != release_id:
        raise ReleaseError("ERROR: image release label mismatch: " f"{revision!r}")

    print("PASS: immutable image label matches Git SHA")
    print("PASS: current image pointer remains unchanged")

    return current, immutable, immutable_id


def retag_and_restart(
    source_image: str,
    current_image: str,
    *,
    release_id: str,
) -> None:
    if image_revision(source_image) != release_id:
        raise ReleaseError("ERROR: rollback image release label mismatch.")

    run(
        [
            "docker",
            "tag",
            source_image,
            current_image,
        ]
    )

    env = release_env(release_id=release_id)

    compose(
        "up",
        "-d",
        "--no-deps",
        "--force-recreate",
        "--no-build",
        "app",
        env=env,
    )


def rollback_failed_deploy(
    *,
    previous_image_id: str | None,
    current_image: str,
    before_revision: str,
) -> bool:
    after_revision = db_revision()

    if after_revision != before_revision:
        print("\nROLLBACK BLOCKED: database revision changed.")
        print(f"Before: {before_revision}")
        print(f"After:  {after_revision}")
        print(
            "Use the disaster-recovery plan; "
            "the controller will not downgrade PostgreSQL."
        )
        return False

    if not previous_image_id:
        print(
            "\nROLLBACK UNAVAILABLE: previous running "
            "application image was not found."
        )
        return False

    print("\nDatabase revision unchanged; restoring " "previous application image.")

    run(
        [
            "docker",
            "tag",
            previous_image_id,
            current_image,
        ]
    )

    compose(
        "up",
        "-d",
        "--no-deps",
        "--force-recreate",
        "--no-build",
        "app",
    )

    run(["bash", "scripts/staging.sh", "verify"])

    print("AUTOMATIC CODE ROLLBACK: PASS")
    return True


def command_deploy() -> None:
    lock = acquire_lock()

    try:
        release_id = require_clean_main()

        print("\n=== DATABASE CREDENTIAL PREFLIGHT ===")
        verify_db_credentials()

        print("\n=== SMTP CREDENTIAL PREFLIGHT ===")
        verify_smtp_credentials()

        state = read_state()
        before_revision = db_revision()

        if state and state.get("current"):
            expected_revision = state["current"].get("db_revision")

            if expected_revision and expected_revision != before_revision:
                raise ReleaseError(
                    "ERROR: database revision drift detected; "
                    "release state does not match the database."
                )

        previous_running_image = running_app_image_id()
        backup = create_backup()

        current_image = ""
        immutable = ""
        immutable_id = ""

        try:
            (
                current_image,
                immutable,
                immutable_id,
            ) = build_release(release_id)

            env = release_env(
                release_id=release_id,
                channel=release_id,
            )

            print("\n=== DATABASE MIGRATION ===")

            compose(
                "run",
                "--rm",
                "--no-deps",
                "migrate",
                env=env,
            )

            after_revision = db_revision()

            print("Database revision: " f"{before_revision} -> {after_revision}")

            print("\n=== ACTIVATE RELEASE ===")

            compose(
                "up",
                "-d",
                "--no-deps",
                "--force-recreate",
                "--no-build",
                "app",
                env=env,
            )

            verify_staging()

            # Verification succeeded. Only now advance the
            # mutable deployment pointer to this immutable image.
            run(
                [
                    "docker",
                    "tag",
                    immutable,
                    current_image,
                ]
            )

            if image_id(current_image) != immutable_id:
                raise ReleaseError("ERROR: current image pointer verification failed.")

            print(
                "PASS: current image pointer advanced " "after successful verification"
            )

        except Exception:
            if current_image:
                rollback_failed_deploy(
                    previous_image_id=previous_running_image,
                    current_image=current_image,
                    before_revision=before_revision,
                )
            raise

        previous = state.get("current") if state else None

        new_state = {
            "version": 1,
            "current": {
                "release_id": release_id,
                "image": immutable,
                "image_id": immutable_id,
                "deployed_at": utc_now(),
                "db_revision": after_revision,
                "backup_before_deploy": backup,
            },
            "previous": previous,
        }

        write_state(new_state)

        print("\n======================================")
        print("STAGING RELEASE: PASS")
        print(f"Release: {release_id}")
        print(f"Image: {immutable}")
        print(f"Database revision: {after_revision}")
        print("======================================")

    finally:
        lock.close()


def command_rollback() -> None:
    lock = acquire_lock()

    try:
        state = read_state()

        if not state:
            raise ReleaseError("ERROR: no release state exists.")

        current = state.get("current")
        previous = state.get("previous")

        if not current or not previous:
            raise ReleaseError("ERROR: no previous release is available.")

        database = db_revision()

        if database != current["db_revision"]:
            raise ReleaseError("ERROR: database revision drift detected.")

        if previous["db_revision"] != database:
            raise ReleaseError(
                "ROLLBACK BLOCKED: previous release used "
                "a different Alembic revision. "
                "Automatic database downgrade is forbidden."
            )

        backup = create_backup()

        env = release_env(release_id=current["release_id"])
        current_pointer = rendered_app_image(env)

        print("\n=== CODE ROLLBACK ===")
        print(f"Current:  {current['release_id']}")
        print(f"Previous: {previous['release_id']}")

        retag_and_restart(
            previous["image"],
            current_pointer,
            release_id=previous["release_id"],
        )

        verify_staging()

        new_current = dict(previous)
        new_current["deployed_at"] = utc_now()
        new_current["backup_before_deploy"] = backup

        new_state = {
            "version": 1,
            "current": new_current,
            "previous": current,
        }

        write_state(new_state)

        print("\n======================================")
        print("STAGING CODE ROLLBACK: PASS")
        print(f"Active release: {previous['release_id']}")
        print("Database was not modified.")
        print("======================================")

    finally:
        lock.close()


def command_status() -> None:
    ensure_prerequisites()

    state = read_state()

    print("=== RELEASE STATE ===")

    if not state:
        print("State: not initialized")
    else:
        print(
            json.dumps(
                state,
                indent=2,
                sort_keys=True,
            )
        )

    print("\n=== LIVE DATABASE ===")

    try:
        print(f"Alembic revision: {db_revision()}")
    except subprocess.CalledProcessError:
        print("Alembic revision: unavailable")

    print("\n=== LIVE APPLICATION ===")

    running = running_app_image_id()

    if not running:
        print("Application container: unavailable")
        return

    print(f"Image ID: {running}")

    try:
        revision = image_revision(running)
    except subprocess.CalledProcessError:
        revision = ""

    print("Release label: " + (revision or "unavailable"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description=("Deploy, inspect, or safely roll back " "Secure Auth staging.")
    )

    parser.add_argument(
        "action",
        choices=(
            "deploy",
            "status",
            "rollback",
        ),
    )

    args = parser.parse_args()

    try:
        if args.action == "deploy":
            command_deploy()
        elif args.action == "rollback":
            command_rollback()
        else:
            command_status()

    except ReleaseError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print(
            f"ERROR: command failed with exit code " f"{exc.returncode}",
            file=sys.stderr,
        )
        return exc.returncode or 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
