from auth.password import hash_password, verify_password
from auth.validator import is_valid_password


def test_password_hashing():
    pwd = "Secure@123"
    hashed = hash_password(pwd)
    assert pwd.encode() != hashed


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

