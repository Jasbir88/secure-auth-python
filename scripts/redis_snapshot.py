"""Logical Redis dump/restore helper for staging recovery tests."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
import time

import redis.asyncio as redis

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")


async def dump() -> int:
    client = redis.from_url(REDIS_URL, decode_responses=False)
    now_ms = int(time.time() * 1000)
    count = 0

    try:
        async for key in client.scan_iter():
            payload = await client.dump(key)

            if payload is None:
                continue

            pttl = await client.pttl(key)

            record = {
                "key": base64.b64encode(key).decode("ascii"),
                "dump": base64.b64encode(payload).decode("ascii"),
                "expires_at_ms": (now_ms + pttl if pttl > 0 else None),
            }

            print(
                json.dumps(
                    record,
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            count += 1
    finally:
        await client.aclose()

    print(f"Redis records dumped: {count}", file=sys.stderr)
    return 0


async def restore() -> int:
    client = redis.from_url(REDIS_URL, decode_responses=False)
    restored = 0
    expired = 0

    try:
        await client.flushdb()

        for raw_line in sys.stdin:
            line = raw_line.strip()

            if not line:
                continue

            record = json.loads(line)

            key = base64.b64decode(record["key"])
            payload = base64.b64decode(record["dump"])

            expires_at_ms = record.get("expires_at_ms")

            if expires_at_ms is None:
                ttl_ms = 0
            else:
                ttl_ms = int(expires_at_ms) - int(time.time() * 1000)

                if ttl_ms <= 0:
                    expired += 1
                    continue

            await client.restore(
                key,
                ttl_ms,
                payload,
                replace=True,
            )

            restored += 1
    finally:
        await client.aclose()

    print(
        f"Redis records restored: {restored}; " f"expired since backup: {expired}",
        file=sys.stderr,
    )

    return 0


async def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in {
        "dump",
        "restore",
    }:
        print(
            "Usage: redis_snapshot.py dump|restore",
            file=sys.stderr,
        )
        return 2

    if sys.argv[1] == "dump":
        return await dump()

    return await restore()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
