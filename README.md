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
pip install -r requirements.txt

# Run tests (no Docker needed!)
pytest -v

# Run with Docker
docker-compose up -d
