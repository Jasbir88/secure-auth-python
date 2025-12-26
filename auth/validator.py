def is_valid_password(password: str) -> bool:
    if len(password) < 8:
        return False
    if password.islower() or password.isupper():
        return False
    if password.isalnum():
        return False
    return True
