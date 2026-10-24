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

# Functions that read files/network, run nested queries, sleep/lock, leak server or session
# details, or load code. Matched by prefix, suffix, or exact name (case-insensitive).
_FORBIDDEN_FUNCTION_PREFIXES = (
    # Postgres: every pg_* admin/introspection function, large objects, dblink, network info
    "pg_", "lo_", "dblink", "inet_", "txid_", "has_", "current_setting", "set_config",
    # file / external scans (DuckDB and friends)
    "read_", "glob", "sniff_csv", "parquet_", "iceberg_", "delta_scan", "sqlite_scan", "postgres_scan",
    "mysql_scan", "query_table", "duckdb_", "pragma_", "getvariable", "getenv", "which_secret",
    # MySQL
    "load_file", "sleep", "benchmark", "sys_exec", "sys_eval", "get_lock", "release_lock", "master_pos_wait",
    # Snowflake
    "system$", "result_scan", "last_query_id", "get_ddl", "identifier", "external_", "infer_schema",
    "get_presigned_url", "build_scoped_file_url", "build_stage_file_url",
    # SQLite
    "load_extension", "readfile", "writefile", "fts3_tokenizer", "sqlite_", "edit",
    "copy",
)
_FORBIDDEN_FUNCTION_SUFFIXES = ("_to_xml", "_to_xmlschema", "_and_xmlschema")  # query_to_xml & co run nested SQL
_FORBIDDEN_FUNCTIONS = {
    # names as written and as sqlglot normalises them (version() parses to CURRENT_VERSION)
    "version", "current_version", "user", "current_user", "session_user", "current_role", "system_user",
    "current_account", "current_ip_address", "current_client", "database_to_xml",
    "table", "generator", "query",
}

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


def _is_forbidden_function(name: str) -> bool:
    return (name in _FORBIDDEN_FUNCTIONS or name.startswith(_FORBIDDEN_FUNCTION_PREFIXES)
            or name.endswith(_FORBIDDEN_FUNCTION_SUFFIXES))


def validate_sql(
    sql: str, dialect: str, known_tables: set[str], max_rows: int, allowed_schemas: set[str] | None = None
) -> GuardedSql:
    """`allowed_schemas` are the only schema qualifiers accepted (e.g. {"public"}); catalogs never are."""
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
        if _is_forbidden_function(name):
            raise SqlRejected(f"Function '{name}' is not allowed.")

    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    known = {t.lower() for t in known_tables}
    referenced: list[str] = []
    schemas_ok = {s.lower() for s in (allowed_schemas or set())}
    for table in tree.find_all(exp.Table):
        name = table.name.lower()
        if not name or not isinstance(table.this, exp.Identifier):
            raise SqlRejected("Table-valued functions are not allowed.")
        schema = (table.db or "").lower()
        if schema in _SYSTEM_SCHEMAS or name in _SYSTEM_SCHEMAS:
            raise SqlRejected("System catalogs cannot be queried.")
        # A qualifier could point the allow-listed name at another schema/database: only the
        # configured schema is accepted, and cross-database (catalog) references never are.
        if table.catalog or (schema and schema not in schemas_ok):
            raise SqlRejected(f"Table '{table.sql(dialect=dialect)}' is outside the connected schema.")
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
