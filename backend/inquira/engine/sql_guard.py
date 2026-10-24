"""Static validation of model-generated SQL.

LLM output is untrusted input. Before anything reaches a warehouse we parse it
into an AST and require:

  * exactly one statement, and it is a read query (SELECT / WITH / set ops)
  * no DDL/DML/session commands anywhere in the tree (e.g. SELECT ... INTO)
  * no file/network/system functions (read_csv, pg_read_file, sleep, ...)
  * every referenced table exists in the introspected schema (no system catalogs)
  * a LIMIT, so a bad query can't stream millions of rows

Adapters additionally open read-only sessions; this is defence in depth.
"""

from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

_FORBIDDEN_NODES = {
    "Insert", "Update", "Delete", "Merge", "Drop", "Create", "Alter", "AlterTable", "TruncateTable",
    "Command", "Into", "Set", "Use", "Pragma", "Transaction", "Commit", "Rollback", "Grant", "Revoke",
    "Copy", "Attach", "Detach", "Install", "Load", "LoadData", "Analyze", "Kill", "Export",
}

_FORBIDDEN_FUNCTION_PREFIXES = (
    "read_", "pg_read", "pg_ls", "pg_stat_file", "pg_sleep", "pg_terminate", "pg_cancel", "lo_",
    "dblink", "load_file", "sleep", "benchmark", "system$", "glob", "query_table", "sniff_csv",
    "parquet_", "iceberg_", "delta_scan", "sqlite_scan", "postgres_scan", "mysql_scan",
    "current_setting", "set_config", "getvariable", "pragma_", "duckdb_", "copy",
)

_SYSTEM_SCHEMAS = {"information_schema", "pg_catalog", "mysql", "performance_schema", "sys", "sqlite_master"}


class SqlRejected(ValueError):
    pass


@dataclass
class GuardedSql:
    sql: str
    tables: list[str]


def _function_names(tree: exp.Expression) -> set[str]:
    names = set()
    for fn in tree.find_all(exp.Func):
        if isinstance(fn, exp.Anonymous):
            names.add(str(fn.name).lower())
        else:
            names.add(fn.sql_name().lower())
    return names


def validate_sql(sql: str, dialect: str, known_tables: set[str], max_rows: int) -> GuardedSql:
    sql = sql.strip().rstrip(";").strip()
    if not sql:
        raise SqlRejected("The model returned an empty query.")
    try:
        statements = [s for s in sqlglot.parse(sql, read=dialect) if s is not None]
    except ParseError as e:
        raise SqlRejected(f"SQL could not be parsed: {str(e).splitlines()[0]}") from e
    if len(statements) != 1:
        raise SqlRejected("Exactly one SQL statement is allowed.")
    tree = statements[0]

    if not isinstance(tree, (exp.Select, exp.Union, exp.Intersect, exp.Except, exp.Subquery)):
        raise SqlRejected(f"Only read-only SELECT queries are allowed (got {tree.key.upper()}).")

    for node in tree.walk():
        if type(node).__name__ in _FORBIDDEN_NODES:
            raise SqlRejected(f"Forbidden SQL construct: {type(node).__name__.upper()}.")

    for name in _function_names(tree):
        if name.startswith(_FORBIDDEN_FUNCTION_PREFIXES):
            raise SqlRejected(f"Function '{name}' is not allowed.")

    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    known = {t.lower() for t in known_tables}
    referenced: list[str] = []
    for table in tree.find_all(exp.Table):
        name = table.name.lower()
        if not name:
            raise SqlRejected("Table-valued functions are not allowed.")
        schema = (table.db or "").lower()
        if schema in _SYSTEM_SCHEMAS or name in _SYSTEM_SCHEMAS:
            raise SqlRejected("System catalogs cannot be queried.")
        if name in cte_names:
            continue
        if name not in known:
            raise SqlRejected(f"Unknown table '{table.name}'. Use only tables from the schema.")
        referenced.append(name)

    limit = tree.args.get("limit")
    limit_value = None
    if isinstance(limit, exp.Limit):
        try:
            limit_value = int(limit.expression.name)
        except (AttributeError, ValueError):
            limit_value = None
    if limit_value is None or limit_value > max_rows:
        tree = tree.limit(max_rows, copy=False)

    return GuardedSql(sql=tree.sql(dialect=dialect, pretty=True), tables=sorted(set(referenced)))
