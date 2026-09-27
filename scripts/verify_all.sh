#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

TEMP_ROOT="$(mktemp -d)"

cleanup() {
    rm -rf "$TEMP_ROOT"
}

trap cleanup EXIT

echo "======================================"
echo "SECURE AUTH — FULL VERIFICATION"
echo "======================================"

echo
echo "=== 1. STATIC CHECKS ==="

bash -n scripts/test_compose_e2e.sh
bash -n scripts/update_runtime_lock.sh
bash -n scripts/verify_all.sh
/usr/bin/python3 -m py_compile scripts/release_staging.py
git diff --check

python scripts/check_runtime_lock.py

echo "STATIC CHECKS: PASS"

echo
echo "=== 2. LOCAL PYTHON ENVIRONMENT ==="

python -m pip check
python -m pytest -q

echo "PYTHON TESTS: PASS"

echo
echo "=== 3. HASH-LOCK INSTALL ==="

python -m venv "$TEMP_ROOT/runtime"

"$TEMP_ROOT/runtime/bin/python" -m pip install \
    --require-hashes \
    -r requirements-runtime.lock

"$TEMP_ROOT/runtime/bin/python" -m pip check

echo "HASH-LOCK INSTALL: PASS"

echo
echo "=== 4. DEPENDENCY SECURITY AUDIT ==="

python -m venv "$TEMP_ROOT/audit"

"$TEMP_ROOT/audit/bin/python" -m pip install -q \
    pip-audit==2.10.1

"$TEMP_ROOT/audit/bin/python" -m pip_audit \
    --strict \
    -r requirements-runtime.lock

echo "DEPENDENCY AUDIT: PASS"

echo
echo "=== 5. COMPOSE SECURITY CONFIGURATION ==="

python scripts/check_compose_security.py

echo "COMPOSE SECURITY CONFIG: PASS"

echo
echo "=== 6. PRODUCTION COMPOSE E2E ==="

bash scripts/test_compose_e2e.sh

echo
echo "======================================"
echo "FULL SECURITY VERIFICATION: PASS"
echo "======================================"
