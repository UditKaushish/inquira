"""Persisted workspace configuration: LLM provider and datasource.

Secrets (API keys, DB passwords) are encrypted with Fernet before they touch
the metadata database and are never returned by the API.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from typing import Any

from sqlalchemy.orm import Session

from inquira.core.config import get_settings
from inquira.core.errors import ApiError
from inquira.core.security import decrypt_secret, encrypt_secret
from inquira.db import AppSetting
from inquira.engine.llm.providers import PROVIDERS, LLMConfig
from inquira.engine.warehouse.adapters import ADAPTERS, build_warehouse
from inquira.engine.warehouse.base import Table, Warehouse

LLM_KEY = "llm"
DATASOURCE_KEY = "datasource"


def _get(db: Session, key: str) -> AppSetting | None:
    return db.get(AppSetting, key)


def _put(db: Session, key: str, value: dict[str, Any], secrets: dict[str, str] | None) -> AppSetting:
    row = _get(db, key) or AppSetting(key=key)
    row.value = value
    if secrets is not None:
        row.secret = encrypt_secret(json.dumps(secrets)) if secrets else None
    db.add(row)
    db.commit()
    return row


def _secrets(row: AppSetting) -> dict[str, str]:
    if not row.secret:
        return {}
    raw = decrypt_secret(row.secret)
    if raw is None:
        raise ApiError(
            500, "secrets_unreadable",
            "Stored credentials can't be decrypted. INQUIRA_SECRET_KEY probably changed: add the old key to "
            "INQUIRA_PREVIOUS_SECRET_KEYS, or re-enter the credentials in Settings.",
        )
    return json.loads(raw)


def rotate_secrets(db: Session) -> int:
    """Re-encrypt every stored secret with the current key. Returns how many rows changed."""
    from inquira.core.security import reencrypt_secret

    count = 0
    for row in db.query(AppSetting).filter(AppSetting.secret.isnot(None)):
        row.secret = reencrypt_secret(row.secret)
        count += 1
    db.commit()
    return count


# --------------------------------------------------------------------------- LLM


def load_llm_config(db: Session) -> LLMConfig | None:
    env = get_settings()
    if env.llm_provider:
        return LLMConfig(env.llm_provider, env.llm_model or "", env.llm_api_key, env.llm_base_url)
    row = _get(db, LLM_KEY)
    if not row or not row.value.get("provider"):
        return None
    return LLMConfig(
        provider=row.value["provider"],
        model=row.value.get("model") or "",
        api_key=_secrets(row).get("api_key"),
        base_url=row.value.get("base_url"),
    )


def save_llm_config(db: Session, provider: str, model: str, api_key: str | None, base_url: str | None) -> None:
    existing = _get(db, LLM_KEY)
    keep_key = api_key is None and existing is not None and existing.value.get("provider") == provider
    secrets = None if keep_key else ({"api_key": api_key} if api_key else {})
    _put(db, LLM_KEY, {"provider": provider, "model": model, "base_url": base_url or None}, secrets)


def public_llm(db: Session) -> dict[str, Any] | None:
    cfg = load_llm_config(db)
    if not cfg:
        return None
    return {"provider": cfg.provider, "model": cfg.model or PROVIDERS[cfg.provider].default_model,
            "base_url": cfg.base_url, "has_key": bool(cfg.api_key)}


# --------------------------------------------------------------------------- Datasource


def _split_secrets(kind: str, config: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    secret_names = {f.name for f in ADAPTERS[kind].fields if f.secret}
    public = {k: v for k, v in config.items() if k not in secret_names}
    secrets = {k: str(v) for k, v in config.items() if k in secret_names and v}
    return public, secrets


def load_datasource(db: Session) -> tuple[str, str, dict[str, Any]] | None:
    row = _get(db, DATASOURCE_KEY)
    if not row or not row.value.get("kind"):
        return None
    return row.value["kind"], row.value.get("name") or row.value["kind"], {
        **row.value.get("config", {}), **_secrets(row)}


def save_datasource(db: Session, kind: str, name: str, config: dict[str, Any]) -> None:
    current = load_datasource(db)
    if current and current[0] == kind:
        # Keep previously stored secrets when the form leaves them blank.
        for f in ADAPTERS[kind].fields:
            if f.secret and not config.get(f.name) and current[2].get(f.name):
                config[f.name] = current[2][f.name]
    public, secrets = _split_secrets(kind, config)
    _put(db, DATASOURCE_KEY, {"kind": kind, "name": name, "config": public}, secrets)
    invalidate_warehouse()


def public_datasource(db: Session) -> dict[str, Any] | None:
    ds = load_datasource(db)
    if not ds:
        return None
    kind, name, config = ds
    public, _ = _split_secrets(kind, config)
    return {"kind": kind, "name": name, "details": {k: str(v) for k, v in public.items() if v not in (None, "")}}


# --------------------------------------------------------------------------- Warehouse + schema cache

_SCHEMA_TTL = 600
_lock = threading.Lock()
_cache: dict[str, Any] = {"fingerprint": None, "warehouse": None, "schema": None, "schema_at": 0.0}


def _fingerprint(kind: str, config: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps([kind, config], sort_keys=True, default=str).encode()).hexdigest()


def invalidate_warehouse() -> None:
    with _lock:
        if _cache["warehouse"] is not None:
            _cache["warehouse"].close()
        _cache.update(fingerprint=None, warehouse=None, schema=None, schema_at=0.0)


def get_warehouse(db: Session) -> tuple[Warehouse, str] | None:
    ds = load_datasource(db)
    if not ds:
        return None
    kind, name, config = ds
    fp = _fingerprint(kind, config)
    with _lock:
        if _cache["fingerprint"] != fp:
            _cache.update(fingerprint=fp, warehouse=build_warehouse(kind, config), schema=None, schema_at=0.0)
        return _cache["warehouse"], name


def get_schema(db: Session, refresh: bool = False) -> list[Table]:
    wh = get_warehouse(db)
    if wh is None:
        return []
    warehouse, _ = wh
    with _lock:
        fresh = _cache["schema"] is not None and time.monotonic() - _cache["schema_at"] < _SCHEMA_TTL
        if fresh and not refresh:
            return _cache["schema"]
    schema = warehouse.introspect()
    with _lock:
        _cache.update(schema=schema, schema_at=time.monotonic())
    return schema
