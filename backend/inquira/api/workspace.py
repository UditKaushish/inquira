"""Settings (LLM + datasource), schema, knowledge base and audit log."""

from __future__ import annotations

import time
from dataclasses import asdict
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from inquira.api.deps import admin_user, current_user
from inquira.core.errors import ApiError, not_found
from inquira.db import KnowledgeDoc, Message, User, get_db
from inquira.engine.demo import DEMO_KNOWLEDGE, DEMO_SUGGESTIONS
from inquira.engine.llm.providers import PROVIDERS, LLMConfig, build_llm
from inquira.engine.warehouse.adapters import ADAPTERS, build_warehouse
from inquira.services import settings_store

router = APIRouter()


class LlmIn(BaseModel):
    provider: str
    model: str = Field("", max_length=120)
    api_key: str | None = Field(None, max_length=500)
    base_url: str | None = Field(None, max_length=500)


class DatasourceTestIn(BaseModel):
    kind: str
    config: dict[str, Any] = {}


class DatasourceIn(DatasourceTestIn):
    name: str = Field(min_length=1, max_length=120)


class KnowledgeIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    kind: Literal["metric", "glossary", "note"] = "note"
    content: str = Field(min_length=1, max_length=20_000)


def _spec(cls: Any, llm: bool) -> dict[str, Any]:
    spec = {"id": cls.id if llm else cls.kind, "label": cls.label, "description": cls.description,
            "fields": [{k: v for k, v in asdict(f).items() if v is not None} for f in cls.fields]}
    if llm:
        spec |= {"default_model": cls.default_model, "models": cls.models}
    return spec


@router.get("/settings")
def get_settings_view(_: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return {"llm": settings_store.public_llm(db), "datasource": settings_store.public_datasource(db)}


@router.get("/settings/providers")
def providers(_: User = Depends(current_user)) -> dict:
    return {"llm": [_spec(p, True) for p in PROVIDERS.values()],
            "datasource": [_spec(a, False) for a in ADAPTERS.values()]}


def _llm_from_body(body: LlmIn, db: Session) -> LLMConfig:
    api_key = body.api_key
    if not api_key:  # testing with the stored key
        stored = settings_store.load_llm_config(db)
        if stored and stored.provider == body.provider:
            api_key = stored.api_key
    return LLMConfig(body.provider, body.model.strip(), api_key, (body.base_url or "").strip() or None)


@router.post("/settings/llm/test")
def test_llm(body: LlmIn, _: User = Depends(admin_user), db: Session = Depends(get_db)) -> dict:
    llm = build_llm(_llm_from_body(body, db))
    started = time.perf_counter()
    try:
        llm.complete_json('Reply with JSON only.', 'Return exactly {"ok": true}.')
    except ApiError as e:
        return {"ok": False, "message": e.message, "latency_ms": None}
    latency = int((time.perf_counter() - started) * 1000)
    return {"ok": True, "message": f"Connected to {llm.label} ({llm.config.model})", "latency_ms": latency}


@router.put("/settings/llm")
def save_llm(body: LlmIn, _: User = Depends(admin_user), db: Session = Depends(get_db)) -> dict:
    cfg = _llm_from_body(body, db)
    build_llm(cfg)  # validates provider / key / base_url presence
    settings_store.save_llm_config(db, cfg.provider, cfg.model, body.api_key or None, cfg.base_url)
    return {"llm": settings_store.public_llm(db)}


@router.post("/settings/datasource/test")
def test_datasource(body: DatasourceTestIn, _: User = Depends(admin_user), db: Session = Depends(get_db)) -> dict:
    config = dict(body.config)
    current = settings_store.load_datasource(db)
    if current and current[0] == body.kind:
        for f in ADAPTERS[body.kind].fields:
            if f.secret and not config.get(f.name):
                config[f.name] = current[2].get(f.name)
    try:
        warehouse = build_warehouse(body.kind, config)
        tables = warehouse.introspect()
        warehouse.close()
    except ApiError as e:
        return {"ok": False, "message": e.message, "table_count": 0}
    except Exception as e:
        msg = str(e).strip().splitlines()[0][:300] if str(e).strip() else type(e).__name__
        return {"ok": False, "message": f"Connection failed: {msg}", "table_count": 0}
    if not tables:
        return {"ok": False, "message": "Connected, but no tables are visible to this user.", "table_count": 0}
    return {"ok": True, "message": f"Connected. Found {len(tables)} tables.", "table_count": len(tables)}


@router.put("/settings/datasource")
def save_datasource(body: DatasourceIn, _: User = Depends(admin_user), db: Session = Depends(get_db)) -> dict:
    if body.kind not in ADAPTERS:
        raise ApiError(400, "bad_request", f"Unknown datasource kind: {body.kind}")
    settings_store.save_datasource(db, body.kind, body.name.strip(), dict(body.config))
    return {"datasource": settings_store.public_datasource(db)}


@router.post("/settings/datasource/demo")
def use_demo(user: User = Depends(admin_user), db: Session = Depends(get_db)) -> dict:
    settings_store.save_datasource(db, "demo", "Olist e-commerce (demo)", {})
    settings_store.get_schema(db, refresh=True)  # builds the DuckDB file now, not on first question
    if not db.scalar(select(KnowledgeDoc).limit(1)):
        db.add_all(KnowledgeDoc(title=t, kind=k, content=c, created_by=user.id) for t, k, c in DEMO_KNOWLEDGE)
        db.commit()
    return {"datasource": settings_store.public_datasource(db)}


def _schema_json(db: Session, refresh: bool) -> dict:
    wh = settings_store.get_warehouse(db)
    if wh is None:
        raise ApiError(409, "no_datasource", "No datasource is connected yet.")
    tables = settings_store.get_schema(db, refresh=refresh)
    return {"datasource": wh[1], "tables": [
        {"name": t.name, "row_count": t.row_count, "columns": [{"name": c.name, "type": c.type} for c in t.columns]}
        for t in sorted(tables, key=lambda t: t.name)
    ]}


@router.get("/schema")
def schema(_: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return _schema_json(db, refresh=False)


@router.post("/schema/refresh")
def refresh_schema(_: User = Depends(admin_user), db: Session = Depends(get_db)) -> dict:
    return _schema_json(db, refresh=True)


@router.get("/suggestions")
def suggestions(_: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    ds = settings_store.load_datasource(db)
    if ds and ds[0] == "demo":
        return {"questions": DEMO_SUGGESTIONS}
    tables = settings_store.get_schema(db) if ds else []
    picks = [t.name for t in sorted(tables, key=lambda t: -(t.row_count or 0))[:3]]
    questions = [f"How many rows are in {t}?" for t in picks[:1]]
    questions += [f"Show the 10 most recent records in {t}" for t in picks[1:2]]
    questions += [f"Summarise {t} by its most important category" for t in picks[2:3]]
    return {"questions": questions or ["What tables do I have?"]}


@router.get("/knowledge")
def list_knowledge(_: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    docs = db.scalars(select(KnowledgeDoc).order_by(KnowledgeDoc.created_at.desc()))
    return {"documents": [_doc_json(d) for d in docs]}


def _doc_json(d: KnowledgeDoc) -> dict:
    return {"id": d.id, "title": d.title, "kind": d.kind, "content": d.content, "chars": len(d.content),
            "created_at": d.created_at.isoformat() + "Z"}


@router.post("/knowledge")
def add_knowledge(body: KnowledgeIn, user: User = Depends(admin_user), db: Session = Depends(get_db)) -> dict:
    doc = KnowledgeDoc(title=body.title.strip(), kind=body.kind, content=body.content.strip(), created_by=user.id)
    db.add(doc)
    db.commit()
    return {"document": _doc_json(doc)}


@router.delete("/knowledge/{doc_id}")
def delete_knowledge(doc_id: str, _: User = Depends(admin_user), db: Session = Depends(get_db)) -> dict:
    doc = db.get(KnowledgeDoc, doc_id)
    if doc is None:
        raise not_found("Document")
    db.delete(doc)
    db.commit()
    return {"ok": True}


@router.get("/audit")
def audit(limit: int = Query(100, ge=1, le=1000), _: User = Depends(admin_user),
          db: Session = Depends(get_db)) -> dict:
    rows = db.execute(
        select(Message, User.email).join(User, Message.user_id == User.id)
        .order_by(Message.created_at.desc()).limit(limit)
    ).all()
    return {"events": [{
        "id": m.id, "user_email": email, "question": m.question, "status": m.status, "sql": m.sql,
        "row_count": m.row_count, "elapsed_ms": m.elapsed_ms, "created_at": m.created_at.isoformat() + "Z",
    } for m, email in rows]}
