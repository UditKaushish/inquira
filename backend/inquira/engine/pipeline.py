"""The NL→SQL pipeline.

    schema → context → plan (LLM) → validate (AST guard) → execute (read-only)
                          ↑______________ self-repair on error ______|
                                                                      → summarise (LLM) → chart

Each stage yields events so the UI can show progress live. The pipeline is a
pure function of its inputs (no web or DB concerns), which keeps it testable
and lets it run in a worker process later without changes.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from inquira.core.errors import ApiError
from inquira.engine import prompts
from inquira.engine.charts import choose_chart, infer_chart
from inquira.engine.context import KnowledgeItem, render_knowledge, render_schema, select_knowledge, select_tables
from inquira.engine.llm.providers import LLMError, LLMProvider
from inquira.engine.sql_guard import SqlRejected, validate_sql
from inquira.engine.warehouse.base import Table, Warehouse

log = logging.getLogger(__name__)

Event = tuple[str, dict[str, Any]]


@dataclass
class PipelineInput:
    question: str
    warehouse: Warehouse
    tables: list[Table]
    knowledge: list[KnowledgeItem]
    llm: LLMProvider
    history: list[dict[str, Any]] = field(default_factory=list)
    max_rows: int = 500
    timeout_seconds: int = 30
    max_repairs: int = 2
    summarize_with_data: bool = True
    deadline: float | None = None  # time.monotonic() value after which work stops
    cancel: threading.Event | None = None


@dataclass
class PipelineOutput:
    status: str = "error"
    sql: str | None = None
    answer: str | None = None
    error: str | None = None
    chart: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    row_count: int = 0


class PipelineError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _check_budget(inp: PipelineInput) -> None:
    if inp.cancel is not None and inp.cancel.is_set():
        raise PipelineError("cancelled", "The request was cancelled.")
    if inp.deadline is not None and time.monotonic() > inp.deadline:
        raise PipelineError("timeout", "This question took too long to answer. Try a narrower question.")


def _out_of_time(inp: PipelineInput) -> bool:
    try:
        _check_budget(inp)
        return False
    except PipelineError:
        return True


def _step(step_id: str, label: str, status: str, detail: str | None = None) -> Event:
    data = {"id": step_id, "label": label, "status": status}
    if detail:
        data["detail"] = detail
    return "step", data


def run_pipeline(inp: PipelineInput, out: PipelineOutput) -> Iterator[Event]:
    try:
        yield from _run(inp, out)
    except PipelineError as e:
        out.status, out.error = "error", e.message
        yield "error", {"code": e.code, "message": e.message}
    except ApiError as e:
        out.status, out.error = "error", e.message
        yield "error", {"code": e.code, "message": e.message}
    except Exception:
        log.exception("pipeline crashed")
        out.status, out.error = "error", "Something went wrong while answering. Please try again."
        yield "error", {"code": "internal", "message": out.error}


def _run(inp: PipelineInput, out: PipelineOutput) -> Iterator[Event]:
    yield _step("schema", "Reading schema", "running")
    if not inp.tables:
        raise PipelineError("no_schema", "The connected datasource has no tables I can see.")
    yield _step("schema", "Reading schema", "done", f"{len(inp.tables)} tables")

    yield _step("context", "Finding relevant context", "running")
    tables = select_tables(inp.question, inp.tables)
    docs = select_knowledge(inp.question, inp.knowledge)
    known = {t.name for t in inp.tables}
    yield _step("context", "Finding relevant context", "done",
                f"{len(tables)} tables · {len(docs)} knowledge notes")

    dialect = inp.warehouse.dialect
    system = prompts.SQL_SYSTEM.format(dialect=prompts.DIALECT_NAMES.get(dialect, dialect))
    prompt = prompts.SQL_USER.format(
        schema=render_schema(tables), knowledge=render_knowledge(docs),
        history=prompts.history_block(inp.history), question=inp.question.strip(),
    )

    assumptions: list[str] = []
    result = None
    sql = None
    for attempt in range(inp.max_repairs + 1):
        label = "Writing SQL" if attempt == 0 else f"Fixing SQL (attempt {attempt + 1})"
        _check_budget(inp)
        yield _step("plan", label, "running")
        try:
            plan = inp.llm.complete_json(system, prompt)
        except LLMError as e:
            if "JSON" not in e.message:  # auth, quota, network: not something a retry prompt fixes
                raise
            yield _step("plan", label, "error", "The model's reply wasn't valid JSON")
            prompt += "\n\nYour previous reply was not valid JSON. Respond with the JSON object only."
            continue
        if plan.get("cannot_answer") and not plan.get("sql"):
            raise PipelineError("cannot_answer", str(plan["cannot_answer"])[:500])
        raw_sql = str(plan.get("sql") or "")
        assumptions = [str(a) for a in (plan.get("assumptions") or [])][:5]
        yield _step("plan", label, "done")

        yield _step("validate", "Validating query", "running")
        try:
            schema = inp.warehouse.default_schema
            sql = validate_sql(raw_sql, dialect, known, inp.max_rows, {schema} if schema else None).sql
        except SqlRejected as e:
            yield _step("validate", "Validating query", "error", str(e))
            prompt += "\n\n" + prompts.REPAIR_USER.format(sql=raw_sql or "(empty)", error=prompts.error_text(str(e)))
            continue
        yield _step("validate", "Validating query", "done", "Read-only · single statement")

        _check_budget(inp)
        yield _step("execute", "Running query", "running")
        started = time.perf_counter()
        try:
            result = inp.warehouse.execute(sql, inp.max_rows, inp.timeout_seconds)
        except ApiError:
            raise
        except Exception as e:
            message = str(e).strip().splitlines()[0][:400] if str(e).strip() else type(e).__name__
            yield _step("execute", "Running query", "error", message)
            prompt += "\n\n" + prompts.REPAIR_USER.format(sql=sql, error=prompts.error_text(message))
            result = None
            continue
        elapsed = int((time.perf_counter() - started) * 1000)
        yield _step("execute", "Running query", "done", f"{len(result.rows):,} rows in {elapsed} ms")
        break

    if result is None or sql is None:
        raise PipelineError("sql_failed", "I couldn't produce a working query for that question. "
                                          "Try rephrasing it or naming the metric and table you mean.")

    out.sql = sql
    yield "sql", {"sql": sql}
    out.result = {"columns": result.columns, "rows": result.rows, "truncated": result.truncated}
    out.row_count = len(result.rows)
    yield "result", {**out.result, "row_count": out.row_count}

    yield _step("summarize", "Summarising", "running")
    chart = infer_chart(result.columns, result.rows)
    answer = None
    if inp.summarize_with_data and result.rows and not _out_of_time(inp):
        try:
            summary = inp.llm.complete_json(prompts.SUMMARY_SYSTEM, prompts.SUMMARY_USER.format(
                question=inp.question, assumptions="; ".join(assumptions) or "none", sql=sql,
                row_count=len(result.rows), truncated=", truncated" if result.truncated else "",
                columns=", ".join(c["name"] for c in result.columns),
                rows=prompts.rows_block(result.columns, result.rows),
            ))
            answer = str(summary.get("answer") or "").strip() or None
            chart = choose_chart(summary.get("chart"), result.columns, result.rows)
        except ApiError as e:
            log.warning("summary failed: %s", e.message)
    if not answer:
        answer = (f"The query returned **{len(result.rows):,}** row{'s' if len(result.rows) != 1 else ''}."
                  if result.rows else "The query ran successfully but returned no rows.")
    if assumptions:
        answer += "\n\n_Assumptions: " + "; ".join(assumptions) + "_"
    yield _step("summarize", "Summarising", "done")

    out.chart, out.answer, out.status = chart, answer, "ok"
    yield "chart", chart
    yield "answer", {"text": answer}
