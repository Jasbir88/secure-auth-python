from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_ph = PasswordHasher()


def hash_password(password: str) -> str:
    """
    Hash a password using Argon2.
    Returns a string-safe encoded hash.
    """
    return _ph.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    """
    Verify a password against an Argon2 hash.
    """
    try:
        return _ph.verify(hashed, password)
    except VerifyMismatchError:
        return False
