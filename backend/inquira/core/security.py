"""Password hashing, session tokens, and encryption of stored secrets."""

from __future__ import annotations

import base64
import hashlib
import logging
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from inquira.core.config import get_settings

log = logging.getLogger(__name__)
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
    return jwt.encode(payload, _derive_hkdf(settings.secret_key, b"inquira-jwt-v2"), algorithm=_JWT_ALG)


def decode_session_token(token: str) -> dict | None:
    # Accept tokens signed with the current or any previous key, so rotating keys doesn't sign everyone out.
    for key in _signing_keys():
        try:
            return jwt.decode(token, key, algorithms=[_JWT_ALG], issuer=_ISSUER, options={"require": ["exp", "sub"]})
        except jwt.InvalidSignatureError:
            continue
        except jwt.PyJWTError:
            return None
    return None


# --------------------------------------------------------------------------- key derivation
#
# INQUIRA_SECRET_KEY is the root secret. Independent subkeys are derived per purpose with HKDF.
# Keys listed in INQUIRA_PREVIOUS_SECRET_KEYS stay valid for verification and decryption, which
# makes rotation safe: set the new key, move the old one to PREVIOUS, run `inquira rotate-secrets`.
# The original v1 derivation (sha256(purpose:secret)) is still accepted so existing installs keep working.


def _derive_hkdf(secret: str, info: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=b"inquira", info=info).derive(secret.encode())


def _derive_legacy(secret: str, purpose: str) -> bytes:
    return hashlib.sha256(f"{purpose}:{secret}".encode()).digest()


def _all_secrets() -> list[str]:
    settings = get_settings()
    return [settings.secret_key, *[k for k in settings.previous_secret_keys if k]]


def _signing_keys() -> list[bytes]:
    keys = []
    for secret in _all_secrets():
        keys += [_derive_hkdf(secret, b"inquira-jwt-v2"), _derive_legacy(secret, "jwt")]
    return keys


def _fernet() -> MultiFernet:
    # The first key encrypts; every key can decrypt.
    keys = []
    for secret in _all_secrets():
        keys += [_derive_hkdf(secret, b"inquira-fernet-v2"), _derive_legacy(secret, "fernet")]
    return MultiFernet([Fernet(base64.urlsafe_b64encode(k)) for k in keys])


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(token: str) -> str | None:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        log.error("A stored secret could not be decrypted with INQUIRA_SECRET_KEY or INQUIRA_PREVIOUS_SECRET_KEYS")
        return None


def reencrypt_secret(token: str) -> str:
    """Re-encrypt with the current key (raises InvalidToken if no known key can read it)."""
    return _fernet().rotate(token.encode()).decode()
