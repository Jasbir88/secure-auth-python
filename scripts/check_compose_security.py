"""Validate security-sensitive Docker Compose configuration."""

import json
import os
import secrets
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


def main() -> int:
    root = Path(__file__).resolve().parents[1]

    base_environment = os.environ.copy()
    base_environment.pop("JWT_SECRET_KEY", None)
    base_environment.pop("POSTGRES_PASSWORD", None)

    jwt_key = secrets.token_urlsafe(48)
    postgres_password = secrets.token_urlsafe(32)

    valid_environment = {
        **base_environment,
        "JWT_SECRET_KEY": jwt_key,
        "POSTGRES_PASSWORD": postgres_password,
    }

    with TemporaryDirectory(
        prefix="secure-auth-compose-"
    ) as temporary:
        empty_env = Path(temporary) / "empty.env"
        empty_env.write_text("", encoding="utf-8")

        command = [
            "docker",
            "compose",
            "--env-file",
            str(empty_env),
            "-f",
            str(root / "docker-compose.yml"),
            "config",
            "--format",
            "json",
        ]

        def render(environment):
            return subprocess.run(
                command,
                cwd=root,
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )

        try:
            secret_cases = (
                (
                    "JWT_SECRET_KEY",
                    "JWT_SECRET_KEY must be set",
                ),
                (
                    "POSTGRES_PASSWORD",
                    "POSTGRES_PASSWORD must be set",
                ),
            )

            for name, expected_error in secret_cases:
                for label, value in (
                    ("unset", None),
                    ("empty", ""),
                ):
                    environment = valid_environment.copy()

                    if value is None:
                        environment.pop(name, None)
                    else:
                        environment[name] = value

                    result = render(environment)

                    if (
                        result.returncode == 0
                        or expected_error not in result.stderr
                    ):
                        print(
                            f"FAIL: Compose accepted {label} {name}."
                        )
                        return 1

                    print(
                        f"PASS: Compose rejects {label} {name}."
                    )

            result = render(valid_environment)

            if result.returncode != 0:
                print(
                    "FAIL: Compose could not render with "
                    "generated secrets."
                )
                return 1

            rendered = json.loads(result.stdout)

            expected_database_url = (
                "postgresql+psycopg2://postgres:"
                f"{postgres_password}@db:5432/auth_db"
            )

            db_environment = (
                rendered["services"]["db"]["environment"]
            )

            if (
                db_environment.get("POSTGRES_PASSWORD")
                != postgres_password
            ):
                print(
                    "FAIL: generated PostgreSQL password "
                    "was not propagated."
                )
                return 1

            for service_name in ("app", "migrate"):
                environment = rendered["services"][
                    service_name
                ]["environment"]

                if (
                    environment.get("ENVIRONMENT")
                    != "production"
                    or environment.get("JWT_SECRET_KEY")
                    != jwt_key
                    or environment.get("DATABASE_URL")
                    != expected_database_url
                ):
                    print(
                        "FAIL: generated production secrets "
                        f"were not propagated to {service_name}."
                    )
                    return 1

            print(
                "PASS: Compose propagates generated production "
                "secrets correctly."
            )

        except FileNotFoundError:
            print("Docker Compose CLI is required.")
            return 2
        except subprocess.TimeoutExpired:
            print("FAIL: Compose check timed out.")
            return 1
        except (ValueError, KeyError, TypeError):
            print(
                "FAIL: unexpected Compose JSON structure."
            )
            return 1

    print(
        "Compose security checks: PASS. "
        "No containers started; no secrets saved."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
