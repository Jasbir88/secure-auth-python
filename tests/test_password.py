from auth.password import hash_password, verify_password
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
