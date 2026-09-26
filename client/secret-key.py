import secrets

for name in [
    "SECRET_KEY",
    "TOKEN_HASH_KEY",
    "FIELD_ENCRYPTION_KEY",
    "JWT_SIGNING_KEY",
]:
    print(f"{name}={secrets.token_urlsafe(64)}")
