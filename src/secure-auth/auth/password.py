from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHash

_ph = PasswordHasher(
    time_cost=3,
    memory_cost=64 * 1024,  # 64 MiB
    parallelism=2,
)


def hash_password(password: str) -> str:
    if not isinstance(password, str) or not password:
        raise ValueError("Password must be a non-empty string")
    return _ph.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    if not isinstance(password, str) or not isinstance(hashed, str):
        return False
    try:
        return _ph.verify(hashed, password)
    except (VerifyMismatchError, InvalidHash):
        return False


def needs_rehash(hashed: str) -> bool:
    if not isinstance(hashed, str):
        return True
    try:
        return _ph.check_needs_rehash(hashed)
    except InvalidHash:
        return True
