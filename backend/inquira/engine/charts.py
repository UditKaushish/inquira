"""Chart selection: validate the model's suggestion against the actual result, else infer one."""

from __future__ import annotations

import re
from typing import Any

_TIME_NAME = re.compile(r"(date|day|week|month|quarter|year|time|period)", re.I)


def infer_chart(columns: list[dict[str, str]], rows: list[list[Any]]) -> dict[str, Any]:
    numeric = [c["name"] for c in columns if c["type"] == "number"]
    dims = [c for c in columns if c["type"] != "number"]
    if not rows or not numeric:
        return {"type": "table"}
    if len(rows) == 1 and len(numeric) <= 3 and not dims:
        return {"type": "kpi", "y": numeric}
    timeish = next((c["name"] for c in columns if c["type"] == "date" or _TIME_NAME.search(c["name"])), None)
    if timeish and len(rows) >= 3:
        return {"type": "line", "x": timeish, "y": [n for n in numeric if n != timeish][:3] or numeric[:1]}
    if dims and len(rows) <= 50:
        return {"type": "bar", "x": dims[0]["name"], "y": numeric[:2]}
    return {"type": "table"}


def choose_chart(
    suggestion: dict[str, Any] | None, columns: list[dict[str, str]], rows: list[list[Any]]
) -> dict[str, Any]:
    names = {c["name"] for c in columns}
    numeric = {c["name"] for c in columns if c["type"] == "number"}
    inferred = infer_chart(columns, rows)
    if not isinstance(suggestion, dict):
        return inferred
    kind = suggestion.get("type")
    x = suggestion.get("x")
    y = [v for v in (suggestion.get("y") or []) if v in numeric]
    title = str(suggestion.get("title") or "")[:120] or None
    ok = (
        kind == "table"
        or (kind == "kpi" and y and len(rows) == 1)
        or (kind in {"bar", "line"} and x in names and y and len(rows) <= 500)
        or (kind == "pie" and x in names and len(y) == 1 and 2 <= len(rows) <= 8)
    )
    if not ok:
        return {**inferred, "title": title} if title else inferred
    chart: dict[str, Any] = {"type": kind, "title": title}
    if kind != "table":
        chart["y"] = y
    if kind in {"bar", "line", "pie"}:
        chart["x"] = x
    return chart
