"""Check Compose's secret requirement without starting containers or printing keys."""

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

    with TemporaryDirectory(prefix="secure-auth-compose-") as temporary:
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
            for label, environment in (
                ("unset", base_environment),
                ("empty", {**base_environment, "JWT_SECRET_KEY": ""}),
            ):
                result = render(environment)
                if (
                    result.returncode == 0
                    or "JWT_SECRET_KEY must be set" not in result.stderr
                ):
                    print(
                        f"FAIL: Compose did not reject the {label} secret as expected."
                    )
                    return 1
                print(f"PASS: Compose rejects an {label} JWT secret.")

            test_key = secrets.token_urlsafe(48)
            result = render({**base_environment, "JWT_SECRET_KEY": test_key})
            if result.returncode != 0:
                print("FAIL: Compose could not render with a generated test key.")
                return 1
            rendered = json.loads(result.stdout)
            app_environment = rendered["services"]["app"]["environment"]
            if (
                app_environment.get("ENVIRONMENT") != "production"
                or app_environment.get("JWT_SECRET_KEY") != test_key
            ):
                print(
                    "FAIL: Compose did not pass production mode and the supplied key."
                )
                return 1
            print("PASS: Compose passes production mode and a generated test key.")
        except FileNotFoundError:
            print("Docker Compose CLI is required; no configuration was checked.")
            return 2
        except subprocess.TimeoutExpired:
            print("FAIL: Compose configuration check timed out.")
            return 1
        except (ValueError, KeyError, TypeError):
            print("FAIL: Compose did not return the expected JSON configuration.")
            return 1

    print("Compose security checks: PASS. No containers started; no keys saved.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
