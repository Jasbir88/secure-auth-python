import re
from pathlib import Path

_BLACKLIST_PATH = Path(__file__).with_name("password_blacklist.txt")


def _load_blacklist() -> set[str]:
    try:
        return {
            line.strip().lower()
            for line in _BLACKLIST_PATH.read_text().splitlines()
            if line.strip()
        }
    except FileNotFoundError:
        return set()


_PASSWORD_BLACKLIST = _load_blacklist()


def is_valid_password(password: str) -> bool:
    if not password:
        return False

    if password.lower() in _PASSWORD_BLACKLIST:
        return False

    if len(password) < 8:
        return False
    if not re.search(r"[A-Z]", password):
        return False
    if not re.search(r"[a-z]", password):
        return False
    if not re.search(r"\d", password):
        return False
    if not re.search(r"[^\w\s]", password):
        return False

    return True
