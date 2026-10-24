import pytest

from inquira.core import security
from inquira.core.config import get_settings


@pytest.fixture
def keys():
    s = get_settings()
    saved = (s.secret_key, list(s.previous_secret_keys))
    yield s
    s.secret_key, s.previous_secret_keys = saved


def test_rotation_keeps_secrets_and_sessions_valid(keys):
    keys.secret_key, keys.previous_secret_keys = "A" * 40, []
    token = security.encrypt_secret("sk-secret")
    session = security.create_session_token("user-1", 0)

    keys.secret_key, keys.previous_secret_keys = "B" * 40, ["A" * 40]  # rotate: old key kept as previous
    assert security.decrypt_secret(token) == "sk-secret"
    assert security.decode_session_token(session)["sub"] == "user-1"

    rotated = security.reencrypt_secret(token)
    keys.previous_secret_keys = []  # old key retired
    assert security.decrypt_secret(rotated) == "sk-secret"
    assert security.decrypt_secret(token) is None  # un-rotated data is unreadable without the old key
    assert security.decode_session_token(session) is None


def test_legacy_v1_ciphertext_still_decrypts(keys):
    import base64

    from cryptography.fernet import Fernet

    keys.secret_key, keys.previous_secret_keys = "C" * 40, []
    legacy = Fernet(base64.urlsafe_b64encode(security._derive_legacy("C" * 40, "fernet"))).encrypt(b"old").decode()
    assert security.decrypt_secret(legacy) == "old"


def test_unreadable_secret_raises_clear_error(keys):
    from inquira.core.errors import ApiError
    from inquira.db import AppSetting
    from inquira.services.settings_store import _secrets

    keys.secret_key = "D" * 40
    row = AppSetting(key="x", value={}, secret=security.encrypt_secret('{"api_key": "k"}'))
    keys.secret_key = "E" * 40
    with pytest.raises(ApiError) as exc:
        _secrets(row)
    assert exc.value.code == "secrets_unreadable"
