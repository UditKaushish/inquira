"""Warehouse adapter contract.

Every adapter must open connections in a *read-only* mode at the driver or
session level. That is the second line of defence behind `sql_guard`, which
statically rejects anything that is not a single SELECT.
"""

from __future__ import annotations

import base64
import datetime as dt
import decimal
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar


@dataclass
class Column:
    name: str
    type: str


@dataclass
class Table:
    name: str
    columns: list[Column]
    row_count: int | None = None
    # Foreign keys as (column, referenced_table, referenced_column)
    foreign_keys: list[tuple[str, str, str]] = field(default_factory=list)


@dataclass
class QueryResult:
    columns: list[dict[str, str]]
    rows: list[list[Any]]
    truncated: bool


@dataclass
class FieldSpec:
    name: str
    label: str
    type: str = "text"  # text | password | number
    required: bool = True
    secret: bool = False
    placeholder: str | None = None
    help: str | None = None


class Warehouse(ABC):
    kind: ClassVar[str]
    label: ClassVar[str]
    description: ClassVar[str]
    dialect: ClassVar[str]  # sqlglot dialect
    fields: ClassVar[list[FieldSpec]] = []

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    @abstractmethod
    def introspect(self) -> list[Table]: ...

    @abstractmethod
    def _run(self, sql: str, max_rows: int, timeout: int) -> tuple[list[str], list[tuple], bool]:
        """Execute a single read-only statement. Returns (column names, rows, truncated)."""

    def execute(self, sql: str, max_rows: int, timeout: int) -> QueryResult:
        names, raw_rows, truncated = self._run(sql, max_rows, timeout)
        rows = [[to_json_value(v) for v in r] for r in raw_rows]
        columns = [{"name": n, "type": infer_type(raw_rows, i)} for i, n in enumerate(names)]
        return QueryResult(columns=columns, rows=rows, truncated=truncated)

    def close(self) -> None:  # noqa: B027 - optional hook
        pass


def to_json_value(v: Any) -> Any:
    if v is None or isinstance(v, (bool, int, str)):
        return v
    if isinstance(v, float):
        return v if v == v and v not in (float("inf"), float("-inf")) else None
    if isinstance(v, decimal.Decimal):
        return int(v) if v == v.to_integral_value() and abs(v) < 2**53 else float(v)
    if isinstance(v, (dt.datetime, dt.date, dt.time)):
        return v.isoformat()
    if isinstance(v, dt.timedelta):
        return v.total_seconds()
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, (bytes, bytearray, memoryview)):
        return base64.b64encode(bytes(v)).decode()
    return str(v)


def infer_type(rows: list[tuple], idx: int) -> str:
    seen = None
    for r in rows[:200]:
        v = r[idx]
        if v is None:
            continue
        if isinstance(v, bool):
            t = "boolean"
        elif isinstance(v, (int, float, decimal.Decimal)):
            t = "number"
        elif isinstance(v, (dt.date, dt.datetime)):
            t = "date"
        else:
            t = "string"
        if seen and seen != t:
            return "string"
        seen = t
    return seen or "string"
