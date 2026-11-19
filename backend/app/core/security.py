import hashlib
import re
import secrets

from pwdlib import PasswordHash

SESSION_COOKIE_NAME = "norma_session"
SESSION_COOKIE_PATH = "/api/v1"
_password_hasher = PasswordHash.recommended()
# An unknown email still performs one password verification.
_dummy_password_hash = _password_hasher.hash("not-a-user-password")


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> tuple[bool, str | None]:
    valid, replacement = _password_hasher.verify_and_update(
        password, password_hash if password_hash is not None else _dummy_password_hash
    )
    return valid and password_hash is not None, replacement


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def session_token_hash(token: str | None) -> str | None:
    if token is None or re.fullmatch(r"[A-Za-z0-9_-]{43}", token) is None:
        return None
    return hashlib.sha256(token.encode("ascii")).hexdigest()
