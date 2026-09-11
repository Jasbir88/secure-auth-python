# JWT security hardening: Windows / Git Bash study guide

These changes address the three outstanding security tasks.

| Control | Implementation | Focused verification |
| --- | --- | --- |
| Reject unsafe production secrets | `app/core/config.py`, `docker-compose.yml` | `tests/test_config_security.py` and `scripts/check_compose_security.py` |
| Bind access tokens to this API | `app/core/security.py`, `app/core/dependencies.py`, logout in `app/api/routes/auth.py` | `tests/test_jwt_claims.py`, `tests/integration/test_jwt_security.py` |
| Avoid skipping Argon2 for missing users | login in `app/api/routes/auth.py` | `tests/integration/test_login_verification.py` |

## 1. Use the project environment

From Git Bash:

```bash
cd ~/jasbir88/secure-auth-python
source .venv/Scripts/activate
python -m pip install -r requirements.txt
python -m pip check
```

No production signing key is needed to run the tests. The command below selects
test mode; existing fixtures use SQLite in memory and fake Redis when
`USE_DOCKER_DB` is unset.

## 2. Run the security tests and the full suite

```bash
env -u USE_DOCKER_DB ENVIRONMENT=test python -m pytest -q \
  tests/test_config_security.py \
  tests/test_jwt_claims.py \
  tests/integration/test_jwt_security.py \
  tests/integration/test_login_verification.py

env -u USE_DOCKER_DB ENVIRONMENT=test python -m pytest -q
git diff --check
```

Expected on this change: **50 focused tests** and **71 total tests** pass.
The pre-existing pytest configuration and Starlette/httpx deprecation warnings
are independent of these security fixes.

What the tests establish:

- Production settings reject the public default, missing, empty, whitespace-only,
  too-short, and padded secrets. Development/test defaults remain available.
- HS256 is the configured algorithm. Both issuer and audience must match, and
  `exp`, `iat`, `sub`, `jti`, `iss`, `aud`, `type`, and
  `token_version` must be present.
- The token type must be `access`; the version must be a positive integer.
  Protected routes use this shared validation policy.
- The revocation helper permits expired tokens only for bookkeeping; it still
  verifies the signature and identity. It is not used to authorize protected
  requests.
- Ordinary logout still blocks reuse of both the access and refresh tokens.
  The existing logout-all regression test remains part of the full suite.
- Missing-user, wrong-password, and successful logins each perform exactly one
  password verification. A matching dummy hash cannot authenticate a missing user.

## 3. Check Docker configuration without starting containers

```bash
python scripts/check_compose_security.py
```

This requires the Docker Compose CLI, but no running containers or Docker daemon.
It uses an empty temporary environment file to avoid reading your real `.env`.
It checks that unset and empty keys are rejected, then uses a temporary random
key to confirm that Compose passes production mode and that key into the app.
It captures the resolved configuration without printing it or saving a key.

Expected final line:

```text
Compose security checks: PASS. No containers started; no keys saved.
```

The same check runs in GitHub Actions. If the Docker CLI is unavailable locally,
use the successful CI check as the Compose verification; pytest itself does not
need Docker.

## 4. Prepare a persistent local key when you use Docker

Generate a separate ignored local environment file. This does not replace an
existing key or change your current `.env`:

```bash
python - <<'PY'
import os
import secrets
from pathlib import Path

path = Path(".env.jwt.local")
try:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    print("Keeping existing .env.jwt.local; key not replaced.")
else:
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as target:
        target.write("JWT_SECRET_KEY=" + secrets.token_urlsafe(48) + "\n")
    print("Created .env.jwt.local; key not displayed.")
PY

git check-ignore .env.jwt.local
```

Expected: Git reports `.env.jwt.local` as ignored. Never add this file to Git.

Validate the file against the actual production settings without printing it:

```bash
python - <<'PY'
import os
from dotenv import load_dotenv

if not load_dotenv(".env.jwt.local", override=True):
    raise SystemExit("Create .env.jwt.local first.")
os.environ["ENVIRONMENT"] = "production"
from app.core.config import settings

assert settings.ENVIRONMENT == "production"
print("Production JWT settings: PASS")
PY

env -u JWT_SECRET_KEY docker compose --env-file .env.jwt.local config --quiet
```

The explicit environment file must also be supplied to subsequent Docker Compose
commands. For a direct application process, set `ENVIRONMENT=production` and
provide `JWT_SECRET_KEY` through that process's environment or its private
`.env`. Do not use the development default for a production process.

Length validation cannot prove randomness. Generate a random key, and use separate
keys for separate security domains. The repeated characters used in boundary
tests are test inputs, not examples of strong production keys.

## 5. Review and merge

In the review branch, stage the changed files (the supplied `git apply --index`
command already does this), then run the repository hooks:

```bash
python -m pip install pre-commit
python -m pre_commit run
```

If a hook modifies a file, review and re-stage those changes before committing.
Commit the change and push the review branch, then open a pull request with
base `main` and compare `fix/jwt-security-hardening`. After local tests and
the GitHub checks pass, merge using a merge commit. Delete the remote branch,
then:

```bash
git switch main &&
git pull --ff-only &&
git fetch --prune &&
git branch -d fix/jwt-security-hardening &&
git status -sb
```

## Migration and study notes

Old access tokens without the newly required claims will receive HTTP 401 after
this update. Obtain a new token through login or a valid refresh token. Changing
the signing key also invalidates old access-token signatures; it does not itself
revoke opaque refresh tokens. No database schema migration is required.

One verification per login removes the obvious Argon2 early-exit difference; it
does not guarantee identical database/network latency or remove every possible
account-enumeration signal. The tests check work performed, not fragile timing
thresholds.

These are application-policy and configuration checks. SQLite and fake Redis
tests do not establish production database behavior, real Redis TTL behavior,
or rate-limit enforcement.

References:
- [PyJWT required claims](https://pyjwt.readthedocs.io/en/stable/usage.html#requiring-presence-of-claims)
- [Docker Compose interpolation](https://docs.docker.com/reference/compose-file/interpolation/)
- [OWASP authentication response guidance](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html#authentication-responses)
