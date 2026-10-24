"""Password hashing, session tokens, and encryption of stored secrets."""

from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet, InvalidToken

from inquira.core.config import get_settings

_hasher = PasswordHasher()  # argon2id with library defaults (OWASP recommended)
_JWT_ALG = "HS256"
_ISSUER = "inquira"
# Used to equalise timing when the email doesn't exist.
_DUMMY_HASH = _hasher.hash("inquira-dummy-password")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def create_session_token(user_id: str, token_version: int) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "ver": token_version,
        "iss": _ISSUER,
        "iat": now,
        "exp": now + timedelta(minutes=settings.session_ttl_minutes),
    }
    return jwt.encode(payload, _signing_key(), algorithm=_JWT_ALG)


def decode_session_token(token: str) -> dict | None:
    try:
        return jwt.decode(
            token, _signing_key(), algorithms=[_JWT_ALG], issuer=_ISSUER, options={"require": ["exp", "sub"]}
        )
    except jwt.PyJWTError:
        return None


def _derive(purpose: str) -> bytes:
    return hashlib.sha256(f"{purpose}:{get_settings().secret_key}".encode()).digest()


def _signing_key() -> bytes:
    return _derive("jwt")


def _fernet() -> Fernet:
    return Fernet(base64.urlsafe_b64encode(_derive("fernet")))


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(token: str) -> str | None:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return None
