"""Grounding context for the model: relevant tables plus business knowledge.

Small schemas are sent whole. Large ones are ranked with BM25 over table and
column names so prompt size stays bounded no matter how big the warehouse is.
Foreign-key neighbours of selected tables are pulled in so joins stay possible.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from inquira.engine.warehouse.base import Table

FULL_SCHEMA_TABLE_LIMIT = 40
MAX_TABLES = 20
MAX_DOCS = 8
FULL_KNOWLEDGE_CHAR_LIMIT = 6000

_STOP = {"the", "a", "an", "of", "by", "for", "in", "on", "to", "and", "or", "what", "which", "how", "is",
         "are", "was", "were", "show", "me", "list", "give", "top", "each", "per", "with", "from", "do", "did"}


def tokenize(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", re.sub(r"([a-z])([A-Z])", r"\1 \2", text).lower())
    out = []
    for w in words:
        if w in _STOP:
            continue
        out.append(w)
        if len(w) > 3 and w.endswith("s"):
            out.append(w[:-1])  # crude singularisation: orders -> order
    return out


def bm25_rank(query: str, docs: list[str], k1: float = 1.4, b: float = 0.75) -> list[float]:
    q = tokenize(query)
    toks = [tokenize(d) for d in docs]
    if not docs or not q:
        return [0.0] * len(docs)
    avg = sum(len(t) for t in toks) / len(toks) or 1
    df = Counter(term for t in toks for term in set(t))
    n = len(docs)
    scores = []
    for t in toks:
        tf = Counter(t)
        s = 0.0
        for term in q:
            if term not in tf:
                continue
            idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
            s += idf * tf[term] * (k1 + 1) / (tf[term] + k1 * (1 - b + b * len(t) / avg))
        scores.append(s)
    return scores


@dataclass
class KnowledgeItem:
    title: str
    kind: str
    content: str


def select_tables(question: str, tables: list[Table]) -> list[Table]:
    if len(tables) <= FULL_SCHEMA_TABLE_LIMIT:
        return tables
    docs = [f"{t.name} {t.name} " + " ".join(c.name for c in t.columns) for t in tables]
    ranked = sorted(zip(bm25_rank(question, docs), range(len(tables))), reverse=True)
    chosen = {tables[i].name for s, i in ranked[: MAX_TABLES // 2] if s > 0} or {tables[ranked[0][1]].name}
    by_name = {t.name: t for t in tables}
    for name in list(chosen):  # add FK neighbours
        for _, ref, _ in by_name[name].foreign_keys:
            if ref in by_name and len(chosen) < MAX_TABLES:
                chosen.add(ref)
    for s, i in ranked:
        if len(chosen) >= MAX_TABLES or s <= 0:
            break
        chosen.add(tables[i].name)
    return [t for t in tables if t.name in chosen]


def select_knowledge(question: str, docs: list[KnowledgeItem]) -> list[KnowledgeItem]:
    if sum(len(d.content) for d in docs) <= FULL_KNOWLEDGE_CHAR_LIMIT:
        return docs
    scores = bm25_rank(question, [f"{d.title} {d.content}" for d in docs])
    ranked = sorted(zip(scores, range(len(docs))), reverse=True)
    return [docs[i] for s, i in ranked[:MAX_DOCS] if s > 0]


def render_schema(tables: list[Table]) -> str:
    lines = []
    for t in tables:
        rows = f"  -- ~{t.row_count:,} rows" if t.row_count else ""
        lines.append(f"TABLE {t.name}{rows}")
        for c in t.columns:
            lines.append(f"  {c.name} {c.type}")
        for col, ref, ref_col in t.foreign_keys:
            lines.append(f"  FOREIGN KEY ({col}) REFERENCES {ref}({ref_col})")
    return "\n".join(lines)


def render_knowledge(docs: list[KnowledgeItem]) -> str:
    return "\n".join(f"- [{d.kind}] {d.title}: {d.content.strip()}" for d in docs) or "(none provided)"
