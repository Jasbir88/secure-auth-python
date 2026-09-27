#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

TEMP_ROOT="$(mktemp -d)"

cleanup() {
    rm -rf "$TEMP_ROOT"
}

trap cleanup EXIT

python -m venv "$TEMP_ROOT/venv"

"$TEMP_ROOT/venv/bin/python" -m pip install -q \
    pip-tools==7.6.1

"$TEMP_ROOT/venv/bin/pip-compile" \
    --generate-hashes \
    --resolver=backtracking \
    --strip-extras \
    --no-emit-index-url \
    --no-emit-trusted-host \
    --output-file=requirements-runtime.lock \
    requirements-runtime.txt

python - <<'PY'
import hashlib
from pathlib import Path

source = Path("requirements-runtime.txt")
lock = Path("requirements-runtime.lock")

digest = hashlib.sha256(source.read_bytes()).hexdigest()
marker = f"# source-sha256: {digest}"

lines = lock.read_text(encoding="utf-8").splitlines()

lines = [
    line
    for line in lines
    if not line.startswith("# source-sha256:")
]

insert_at = 1 if lines and lines[0] == "#" else 0
lines.insert(insert_at, marker)

lock.write_text(
    "\n".join(lines) + "\n",
    encoding="utf-8",
)

print(f"Runtime lock regenerated.")
print(f"Source SHA-256: {digest}")
PY

python scripts/check_runtime_lock.py
