import time
from collections import defaultdict

MAX_ATTEMPTS = 5
WINDOW_SECONDS = 60

_attempts = defaultdict(list)


def can_attempt_login(username: str) -> bool:
    now = time.time()
    attempts = _attempts[username]

    # Remove expired attempts
    _attempts[username] = [
        ts for ts in attempts if now - ts < WINDOW_SECONDS
    ]

    return len(_attempts[username]) < MAX_ATTEMPTS


def record_failed_attempt(username: str) -> None:
    _attempts[username].append(time.time())
