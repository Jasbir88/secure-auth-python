from auth.password import hash_password, verify_password, needs_rehash
from auth.validator import is_valid_password


def test_password_hashing():
    pwd = "Secure@123"
    hashed = hash_password(pwd)
    assert pwd != hashed


def test_password_verification():
    pwd = "Secure@123"
    hashed = hash_password(pwd)
    assert verify_password(pwd, hashed) is True
    assert verify_password("WrongPass!", hashed) is False


def test_password_validation():
    assert is_valid_password("Secure@123") is True
    assert is_valid_password("short") is False
    assert is_valid_password("alllowercase") is False
    assert is_valid_password("NOLOWER123!") is False


def test_unicode_password():
    pwd = "Sëcürê@123"
    hashed = hash_password(pwd)
    assert verify_password(pwd, hashed) is True


def test_empty_password_invalid():
    assert is_valid_password("") is False


def test_blacklisted_passwords():
    assert is_valid_password("password") is False
    assert is_valid_password("Password123") is False
    assert is_valid_password("admin123") is False


def test_needs_rehash_roundtrip():
    pwd = "Secure@123"
    hashed = hash_password(pwd)
    assert needs_rehash(hashed) is False


def test_verify_defensive_inputs():
    pwd = "Secure@123"
    hashed = hash_password(pwd)

    assert verify_password(None, hashed) is False
    assert verify_password(pwd, None) is False
    assert verify_password(123, hashed) is False
    assert verify_password(pwd, "not-a-hash") is False


def test_whitespace_passwords():
    pwd = " Secure@123 "
    hashed = hash_password(pwd)
    assert verify_password(pwd, hashed) is True


def test_unicode_roundtrip():
    pwd = "Sëcürê@123"
    hashed = hash_password(pwd)
    assert verify_password(pwd, hashed) is True
