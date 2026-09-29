"""Verify that the runtime lock belongs to the current source requirements."""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "requirements-runtime.txt"
LOCK = ROOT / "requirements-runtime.lock"

MARKER_RE = re.compile(
    r"^# source-sha256: ([0-9a-f]{64})$",
    re.MULTILINE,
)


def main() -> int:
    if not SOURCE.is_file():
        print("FAIL: requirements-runtime.txt is missing.")
        return 1

    if not LOCK.is_file():
        print("FAIL: requirements-runtime.lock is missing.")
        return 1

    expected = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    lock_text = LOCK.read_text(encoding="utf-8")

    match = MARKER_RE.search(lock_text)

    if match is None:
        print("FAIL: requirements-runtime.lock has no source SHA-256 marker.")
        print("Run: bash scripts/update_runtime_lock.sh")
        return 1

    actual = match.group(1)

    if actual != expected:
        print(
            "FAIL: requirements-runtime.lock is stale relative to "
            "requirements-runtime.txt."
        )
        print(f"Expected source SHA-256: {expected}")
        print(f"Lock source SHA-256:     {actual}")
        print("Run: bash scripts/update_runtime_lock.sh")
        return 1

    print("PASS: runtime lock matches source requirements.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
