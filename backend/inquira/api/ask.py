"""Question answering (streamed over SSE) and conversation history."""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from collections.abc import Iterator
from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from inquira.api.deps import client_ip, current_user
from inquira.core import ratelimit
from inquira.core.config import get_settings
from inquira.core.errors import ApiError, not_found
from inquira.db import Conversation, KnowledgeDoc, Message, SessionLocal, User, _now, get_db
from inquira.engine.context import KnowledgeItem
from inquira.engine.llm.providers import build_llm
from inquira.engine.pipeline import PipelineInput, PipelineOutput, run_pipeline
from inquira.services import settings_store

router = APIRouter()
log = logging.getLogger(__name__)
_DONE = object()
_HEARTBEAT_SECONDS = 10


class AskIn(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    conversation_id: str | None = Field(None, max_length=32)


class FeedbackIn(BaseModel):
    rating: Literal[1, -1]


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@router.post("/ask")
def ask(body: AskIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    settings = get_settings()
    ratelimit.enforce("ask", user.id, settings.ask_rate_limit)
    ratelimit.enforce("ask-ip", client_ip(request), settings.ask_rate_limit)

    # Resolve everything that can fail fast *before* we start streaming.
    llm_cfg = settings_store.load_llm_config(db)
    if llm_cfg is None:
        raise ApiError(409, "llm_not_configured", "No AI model is configured. An admin can set one in Settings.")
    llm = build_llm(llm_cfg)
    wh = settings_store.get_warehouse(db)
    if wh is None:
        raise ApiError(409, "no_datasource", "No datasource is connected. An admin can connect one in Settings.")
    warehouse, _ = wh

    if body.conversation_id:
        conv = db.get(Conversation, body.conversation_id)
        if conv is None or conv.user_id != user.id:
            raise not_found("Conversation")
    else:
        conv = Conversation(user_id=user.id, title=body.question.strip()[:120])
        db.add(conv)
        db.flush()
    history = [
        {"question": m.question, "sql": m.sql}
        for m in db.scalars(select(Message).where(Message.conversation_id == conv.id, Message.status == "ok")
                            .order_by(Message.created_at.desc()).limit(3))
    ][::-1] if body.conversation_id else []
    msg = Message(conversation_id=conv.id, user_id=user.id, question=body.question.strip())
    db.add(msg)
    conv.updated_at = _now()
    db.commit()
    knowledge = [KnowledgeItem(d.title, d.kind, d.content) for d in db.scalars(select(KnowledgeDoc))]
    conv_id, msg_id = conv.id, msg.id

    # Release the request's pooled DB connection now; otherwise it stays checked out for the whole
    # stream and a handful of concurrent questions exhausts the pool.
    db.close()
    question = body.question

    def run_worker(events: queue.Queue, out: PipelineOutput, cancel: threading.Event, deadline: float) -> None:
        try:
            with SessionLocal() as sdb:
                tables = settings_store.get_schema(sdb)
            inp = PipelineInput(
                question=question, warehouse=warehouse, tables=tables, knowledge=knowledge, llm=llm,
                history=history, max_rows=settings.max_result_rows, timeout_seconds=settings.query_timeout_seconds,
                max_repairs=settings.max_repair_attempts, deadline=deadline, cancel=cancel,
            )
            for item in run_pipeline(inp, out):
                if cancel.is_set():
                    return
                events.put(item)
        except Exception as e:  # e.g. schema introspection failed
            log.exception("ask worker failed")
            out.status, out.error = "error", getattr(e, "message", None) or "Couldn't read the datasource schema."
            events.put(("error", {"code": "datasource_error", "message": out.error}))
        finally:
            events.put(_DONE)

    def stream() -> Iterator[str]:
        started = time.monotonic()
        deadline = started + settings.question_deadline_seconds
        yield _sse("meta", {"conversation_id": conv_id, "message_id": msg_id})
        out, events, cancel = PipelineOutput(), queue.Queue(), threading.Event()
        worker = threading.Thread(target=run_worker, args=(events, out, cancel, deadline), daemon=True)
        worker.start()
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    cancel.set()
                    out.status, out.error = "error", (
                        "This question took too long to answer. Try a narrower question, or try again shortly.")
                    yield _sse("error", {"code": "timeout", "message": out.error})
                    break
                try:
                    item = events.get(timeout=min(_HEARTBEAT_SECONDS, remaining))
                except queue.Empty:
                    # SSE comment: keeps proxies/load balancers from closing an idle stream.
                    yield ": ping\n\n"
                    continue
                if item is _DONE:
                    break
                yield _sse(*item)
        finally:
            cancel.set()  # also covers client disconnects (generator closed)
            elapsed = int((time.monotonic() - started) * 1000)
            with SessionLocal() as sdb:
                m = sdb.get(Message, msg_id)
                if m is not None:
                    m.status, m.sql, m.answer, m.error = out.status, out.sql, out.answer, out.error
                    m.chart, m.result, m.row_count, m.elapsed_ms = out.chart, out.result, out.row_count, elapsed
                    sdb.commit()
        yield _sse("done", {"message_id": msg_id, "conversation_id": conv_id, "elapsed_ms": elapsed})

    return StreamingResponse(stream(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})


def _message_json(m: Message) -> dict:
    result = m.result or {}
    return {
        "id": m.id, "question": m.question, "status": m.status if m.status != "pending" else "error",
        "sql": m.sql, "answer": m.answer, "error": m.error if m.status != "pending" else "Interrupted",
        "chart": m.chart, "columns": result.get("columns", []), "rows": result.get("rows", []),
        "row_count": m.row_count, "truncated": bool(result.get("truncated")), "elapsed_ms": m.elapsed_ms,
        "rating": m.rating, "created_at": m.created_at.isoformat() + "Z",
    }


@router.get("/conversations")
def list_conversations(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    counts = (select(Message.conversation_id, func.count().label("n")).group_by(Message.conversation_id).subquery())
    rows = db.execute(
        select(Conversation, counts.c.n).outerjoin(counts, counts.c.conversation_id == Conversation.id)
        .where(Conversation.user_id == user.id).order_by(Conversation.updated_at.desc()).limit(200)
    ).all()
    return {"conversations": [
        {"id": c.id, "title": c.title, "updated_at": c.updated_at.isoformat() + "Z", "message_count": n or 0}
        for c, n in rows
    ]}


def _own_conversation(db: Session, conv_id: str, user: User) -> Conversation:
    conv = db.get(Conversation, conv_id)
    if conv is None or conv.user_id != user.id:
        raise not_found("Conversation")
    return conv


@router.get("/conversations/{conv_id}")
def get_conversation(conv_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    conv = _own_conversation(db, conv_id, user)
    return {"id": conv.id, "title": conv.title, "messages": [_message_json(m) for m in conv.messages]}


@router.delete("/conversations/{conv_id}")
def delete_conversation(conv_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    db.delete(_own_conversation(db, conv_id, user))
    db.commit()
    return {"ok": True}


@router.post("/messages/{msg_id}/feedback")
def feedback(msg_id: str, body: FeedbackIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    msg = db.get(Message, msg_id)
    if msg is None or msg.user_id != user.id:
        raise not_found("Message")
    msg.rating = body.rating
    db.commit()
    return {"ok": True}
