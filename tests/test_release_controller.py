import pytest

from scripts import release_staging as release


def test_invalid_image_reference_fails_closed():
    with pytest.raises(release.ReleaseError):
        release.immutable_image(
            "invalid-image-reference",
            "abc123",
        )


def test_build_release_targets_immutable_tag(monkeypatch):
    release_id = "abc123"
    seen = {}

    def fake_rendered_app_image(env):
        return "secure-auth-staging-app:" + env["RELEASE_CHANNEL"]

    def fake_compose(*args, env=None, **kwargs):
        seen["args"] = args
        seen["env"] = env
        return None

    monkeypatch.setattr(
        release,
        "rendered_app_image",
        fake_rendered_app_image,
    )
    monkeypatch.setattr(
        release,
        "compose",
        fake_compose,
    )
    monkeypatch.setattr(
        release,
        "image_id",
        lambda _image: "sha256:test-image",
    )
    monkeypatch.setattr(
        release,
        "image_revision",
        lambda _image: release_id,
    )

    current, immutable, image_id = release.build_release(release_id)

    assert current == ("secure-auth-staging-app:current")
    assert immutable == ("secure-auth-staging-app:abc123")
    assert image_id == "sha256:test-image"

    assert seen["args"] == (
        "build",
        "--pull",
        "app",
    )
    assert seen["env"]["RELEASE_CHANNEL"] == release_id
    assert seen["env"]["RELEASE_ID"] == release_id


def test_database_preflight_accepts_valid_credentials(
    monkeypatch,
    tmp_path,
):
    env_file = tmp_path / ".env.staging"
    env_file.write_text(
        "POSTGRES_PASSWORD=test-secret\n",
        encoding="utf-8",
    )

    calls = []

    monkeypatch.setattr(
        release,
        "ENV_FILE",
        env_file,
    )

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))

        class Result:
            returncode = 0
            stdout = "db-container\n" if "ps" in command else "1\n"
            stderr = ""

        return Result()

    monkeypatch.setattr(
        release,
        "run",
        fake_run,
    )

    release.verify_db_credentials()

    assert len(calls) == 2
    assert calls[1][1]["input_text"].endswith("test-secret\n")


def test_database_preflight_fails_closed(
    monkeypatch,
    tmp_path,
):
    env_file = tmp_path / ".env.staging"
    env_file.write_text(
        "POSTGRES_PASSWORD=wrong-secret\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        release,
        "ENV_FILE",
        env_file,
    )

    call_number = 0

    def fake_run(command, **kwargs):
        nonlocal call_number
        call_number += 1

        class Result:
            returncode = 0
            stdout = "db-container\n"
            stderr = ""

        result = Result()

        if call_number == 2:
            result.returncode = 2
            result.stdout = ""

        return result

    monkeypatch.setattr(
        release,
        "run",
        fake_run,
    )

    with pytest.raises(
        release.ReleaseError,
        match="credential preflight failed",
    ):
        release.verify_db_credentials()


def test_smtp_preflight_accepts_valid_credentials(
    monkeypatch,
    tmp_path,
):
    env_file = tmp_path / ".env.staging"
    env_file.write_text(
        "\n".join(
            [
                "SMTP_HOST=smtp.example.com",
                "SMTP_PORT=587",
                "SMTP_USERNAME=test@example.com",
                "SMTP_PASSWORD=test-app-password",
                "SMTP_FROM_EMAIL=test@example.com",
                "SMTP_STARTTLS=true",
                "SMTP_TIMEOUT_SECONDS=10",
                "",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        release,
        "ENV_FILE",
        env_file,
    )

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            assert host == "smtp.example.com"
            assert port == 587
            assert timeout == 10.0
            self.login_args = None
            self.starttls_called = False

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def ehlo(self):
            return 250, b"ok"

        def starttls(self, context=None):
            assert context is not None
            self.starttls_called = True
            return 220, b"ready"

        def login(self, username, password):
            assert username == "test@example.com"
            assert password == "test-app-password"
            return 235, b"authenticated"

        def noop(self):
            return 250, b"ok"

    monkeypatch.setattr(
        release.smtplib,
        "SMTP",
        FakeSMTP,
    )

    release.verify_smtp_credentials()


def test_smtp_preflight_fails_closed_on_authentication_error(
    monkeypatch,
    tmp_path,
):
    env_file = tmp_path / ".env.staging"
    env_file.write_text(
        "\n".join(
            [
                "SMTP_HOST=smtp.example.com",
                "SMTP_PORT=587",
                "SMTP_USERNAME=test@example.com",
                "SMTP_PASSWORD=wrong-password",
                "SMTP_FROM_EMAIL=test@example.com",
                "SMTP_STARTTLS=true",
                "SMTP_TIMEOUT_SECONDS=10",
                "",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        release,
        "ENV_FILE",
        env_file,
    )

    class BrokenSMTP:
        def __init__(self, host, port, timeout):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def ehlo(self):
            return 250, b"ok"

        def starttls(self, context=None):
            return 220, b"ready"

        def login(self, username, password):
            raise release.smtplib.SMTPAuthenticationError(
                535,
                b"authentication failed",
            )

    monkeypatch.setattr(
        release.smtplib,
        "SMTP",
        BrokenSMTP,
    )

    with pytest.raises(
        release.ReleaseError,
        match="SMTP credential preflight failed",
    ):
        release.verify_smtp_credentials()
