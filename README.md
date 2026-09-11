# Secure Auth Python

A secure authentication service built with FastAPI.

## Features

- ✅ JWT authentication with access/refresh tokens
- ✅ Password hashing with Argon2
- ✅ Token blacklisting with Redis
- ✅ Rate limiting
- ✅ Logout from all devices

## Quick Start

```bash
# Clone
git clone https://github.com/Jasbir88/secure-auth-python.git
cd secure-auth-python

# Install dependencies
python -m pip install -r requirements.txt

# Run tests (no Docker needed!)
python -m pytest -q

# Check Docker's production JWT secret requirement (no containers started)
python scripts/check_compose_security.py
```

For Docker startup, first configure a random signing key using the
[security hardening guide](docs/security-hardening.md). Compose requires a
non-empty key, and the application rejects the public default or keys shorter
than 32 UTF-8 bytes in production. The guide includes Windows/Git Bash commands,
focused tests, and the access-token migration notes.
