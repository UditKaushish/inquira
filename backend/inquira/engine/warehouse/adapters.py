"""Concrete warehouse adapters. Optional drivers are imported lazily."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any

from inquira.core.errors import bad_request
from inquira.engine.warehouse.base import Column, FieldSpec, Table, Warehouse


def _fetch(cur: Any, max_rows: int) -> tuple[list[str], list[tuple], bool]:
    names = [d[0] for d in (cur.description or [])]
    rows = cur.fetchmany(max_rows + 1) if names else []
    return names, [tuple(r) for r in rows[:max_rows]], len(rows) > max_rows


def _group_columns(rows: list[tuple]) -> dict[str, list[Column]]:
    tables: dict[str, list[Column]] = {}
    for table, column, dtype in rows:
        tables.setdefault(table, []).append(Column(column, str(dtype)))
    return tables


# --------------------------------------------------------------------------- DuckDB


class DuckDBWarehouse(Warehouse):
    kind = "duckdb"
    label = "DuckDB"
    description = "A local DuckDB database file. Fast, embedded analytics."
    dialect = "duckdb"
    fields = [FieldSpec("path", "Database file path", placeholder="/data/analytics.duckdb")]

    _lock = threading.Lock()
    _connections: dict[str, Any] = {}

    def _conn(self) -> Any:
        import duckdb

        path = str(Path(self.config["path"]).expanduser())
        if not Path(path).exists():
            raise bad_request(f"DuckDB file not found: {path}", "datasource_error")
        with self._lock:
            if path not in self._connections:
                # read_only=True: the engine itself refuses writes.
                conn = duckdb.connect(path, read_only=True)
                conn.execute("SET enable_external_access = false")  # block read_csv/httpfs/ATTACH tricks
                conn.execute("SET lock_configuration = true")
                self._connections[path] = conn
            return self._connections[path].cursor()

    def introspect(self) -> list[Table]:
        cur = self._conn()
        cols = cur.execute(
            "SELECT table_name, column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'main' ORDER BY table_name, ordinal_position"
        ).fetchall()
        fks = cur.execute(
            "SELECT table_name, constraint_column_names, referenced_table, referenced_column_names "
            "FROM duckdb_constraints() WHERE constraint_type = 'FOREIGN KEY'"
        ).fetchall()
        counts = dict(cur.execute("SELECT table_name, estimated_size FROM duckdb_tables()").fetchall())
        tables = [Table(t, c, row_count=counts.get(t)) for t, c in _group_columns(cols).items()]
        by_name = {t.name: t for t in tables}
        for table, cols_from, ref_table, cols_to in fks:
            if table in by_name:
                by_name[table].foreign_keys.extend(zip(cols_from, [ref_table] * len(cols_from), cols_to))
        return tables

    def _run(self, sql: str, max_rows: int, timeout: int) -> tuple[list[str], list[tuple], bool]:
        cur = self._conn()
        timer = threading.Timer(timeout, cur.interrupt)
        timer.start()
        try:
            cur.execute(sql)
            return _fetch(cur, max_rows)
        finally:
            timer.cancel()
            cur.close()


class DemoWarehouse(DuckDBWarehouse):
    kind = "demo"
    label = "Demo: Brazilian e-commerce"
    description = "100k real, anonymised orders from Olist (2016–2018). Perfect for a first look."
    fields = []

    def __init__(self, config: dict[str, Any]) -> None:
        from inquira.engine.demo import ensure_demo_database

        super().__init__({"path": str(ensure_demo_database())})


# --------------------------------------------------------------------------- SQLite


class SQLiteWarehouse(Warehouse):
    kind = "sqlite"
    label = "SQLite"
    description = "A local SQLite database file, opened read-only."
    dialect = "sqlite"
    fields = [FieldSpec("path", "Database file path", placeholder="/data/app.db")]

    def _conn(self) -> sqlite3.Connection:
        path = Path(self.config["path"]).expanduser()
        if not path.exists():
            raise bad_request(f"SQLite file not found: {path}", "datasource_error")
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)

    def introspect(self) -> list[Table]:
        with self._conn() as conn:
            names = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%'"
            )]
            tables = []
            for name in names:
                quoted = '"' + name.replace('"', '""') + '"'
                cols = [Column(r[1], r[2] or "TEXT") for r in conn.execute(f"PRAGMA table_info({quoted})")]
                fks = [(r[3], r[2], r[4]) for r in conn.execute(f"PRAGMA foreign_key_list({quoted})")]
                tables.append(Table(name, cols, foreign_keys=fks))
            return tables

    def _run(self, sql: str, max_rows: int, timeout: int) -> tuple[list[str], list[tuple], bool]:
        import time

        deadline = time.monotonic() + timeout
        with self._conn() as conn:
            conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 10_000)
            return _fetch(conn.execute(sql), max_rows)


# --------------------------------------------------------------------------- Postgres


class PostgresWarehouse(Warehouse):
    kind = "postgres"
    label = "PostgreSQL"
    description = "PostgreSQL, plus compatible engines like Supabase, Neon, Redshift, and CockroachDB."
    dialect = "postgres"
    fields = [
        FieldSpec("host", "Host", placeholder="db.example.com"),
        FieldSpec("port", "Port", "number", required=False, placeholder="5432"),
        FieldSpec("database", "Database"),
        FieldSpec("schema", "Schema", required=False, placeholder="public"),
        FieldSpec("user", "User", help="Use a dedicated read-only role."),
        FieldSpec("password", "Password", "password", secret=True),
    ]

    def _connect(self, timeout: int = 30) -> Any:
        try:
            import psycopg
        except ImportError as e:
            raise bad_request("Postgres driver not installed: pip install 'inquira[postgres]'") from e
        c = self.config
        return psycopg.connect(
            host=c["host"], port=int(c.get("port") or 5432), dbname=c["database"],
            user=c["user"], password=c.get("password"), connect_timeout=10,
            options=f"-c default_transaction_read_only=on -c statement_timeout={timeout * 1000}",
        )

    @property
    def schema(self) -> str:
        return self.config.get("schema") or "public"

    def introspect(self) -> list[Table]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT table_name, column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = %s ORDER BY table_name, ordinal_position", (self.schema,))
            tables = [Table(t, c) for t, c in _group_columns(cur.fetchall()).items()]
            cur.execute(
                """SELECT tc.table_name, kcu.column_name, ccu.table_name, ccu.column_name
                   FROM information_schema.table_constraints tc
                   JOIN information_schema.key_column_usage kcu ON tc.constraint_name = kcu.constraint_name
                   JOIN information_schema.constraint_column_usage ccu ON tc.constraint_name = ccu.constraint_name
                   WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = %s""", (self.schema,))
            by_name = {t.name: t for t in tables}
            for t, col, rt, rc in cur.fetchall():
                if t in by_name:
                    by_name[t].foreign_keys.append((col, rt, rc))
            return tables

    def _run(self, sql: str, max_rows: int, timeout: int) -> tuple[list[str], list[tuple], bool]:
        with self._connect(timeout) as conn, conn.cursor() as cur:
            cur.execute(f'SET search_path TO "{self.schema}"')
            cur.execute(sql)
            return _fetch(cur, max_rows)


# --------------------------------------------------------------------------- MySQL


class MySQLWarehouse(Warehouse):
    kind = "mysql"
    label = "MySQL / MariaDB"
    description = "MySQL 8+, MariaDB, PlanetScale, or Aurora MySQL."
    dialect = "mysql"
    fields = [
        FieldSpec("host", "Host"),
        FieldSpec("port", "Port", "number", required=False, placeholder="3306"),
        FieldSpec("database", "Database"),
        FieldSpec("user", "User", help="Use a dedicated read-only user."),
        FieldSpec("password", "Password", "password", secret=True),
    ]

    def _connect(self) -> Any:
        try:
            import pymysql
        except ImportError as e:
            raise bad_request("MySQL driver not installed: pip install 'inquira[mysql]'") from e
        c = self.config
        return pymysql.connect(
            host=c["host"], port=int(c.get("port") or 3306), database=c["database"],
            user=c["user"], password=c.get("password") or "", connect_timeout=10,
        )

    def introspect(self) -> list[Table]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT table_name, column_name, data_type FROM information_schema.columns "
                    "WHERE table_schema = DATABASE() ORDER BY table_name, ordinal_position")
                tables = [Table(t, c) for t, c in _group_columns(cur.fetchall()).items()]
                cur.execute(
                    "SELECT table_name, column_name, referenced_table_name, referenced_column_name "
                    "FROM information_schema.key_column_usage "
                    "WHERE table_schema = DATABASE() AND referenced_table_name IS NOT NULL")
                by_name = {t.name: t for t in tables}
                for t, col, rt, rc in cur.fetchall():
                    if t in by_name:
                        by_name[t].foreign_keys.append((col, rt, rc))
                return tables
        finally:
            conn.close()

    def _run(self, sql: str, max_rows: int, timeout: int) -> tuple[list[str], list[tuple], bool]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(f"SET SESSION max_execution_time = {int(timeout) * 1000}")
                cur.execute("SET SESSION TRANSACTION READ ONLY")
                cur.execute("START TRANSACTION READ ONLY")
                cur.execute(sql)
                return _fetch(cur, max_rows)
        finally:
            conn.rollback()
            conn.close()


# --------------------------------------------------------------------------- Snowflake


class SnowflakeWarehouse(Warehouse):
    kind = "snowflake"
    label = "Snowflake"
    description = "Snowflake Data Cloud. Grant a role with SELECT-only privileges."
    dialect = "snowflake"
    fields = [
        FieldSpec("account", "Account identifier", placeholder="orgname-account"),
        FieldSpec("user", "User"),
        FieldSpec("password", "Password", "password", secret=True),
        FieldSpec("warehouse", "Warehouse", placeholder="COMPUTE_WH"),
        FieldSpec("database", "Database"),
        FieldSpec("schema", "Schema", placeholder="PUBLIC"),
        FieldSpec("role", "Role", required=False, help="Should be a read-only role, never ACCOUNTADMIN."),
    ]

    def _connect(self, timeout: int = 30) -> Any:
        try:
            import snowflake.connector
        except ImportError as e:
            raise bad_request("Snowflake driver not installed: pip install 'inquira[snowflake]'") from e
        c = self.config
        return snowflake.connector.connect(
            account=c["account"], user=c["user"], password=c.get("password"),
            warehouse=c["warehouse"], database=c["database"], schema=c["schema"],
            role=c.get("role") or None, login_timeout=15, application="Inquira",
            session_parameters={"STATEMENT_TIMEOUT_IN_SECONDS": timeout, "QUERY_TAG": "inquira"},
        )

    def introspect(self) -> list[Table]:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT table_name, column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = %s ORDER BY table_name, ordinal_position", (self.config["schema"].upper(),))
            cols = _group_columns(cur.fetchall())
            cur.execute("SELECT table_name, row_count FROM information_schema.tables WHERE table_schema = %s",
                        (self.config["schema"].upper(),))
            counts = dict(cur.fetchall())
            return [Table(t, c, row_count=counts.get(t)) for t, c in cols.items()]

    def _run(self, sql: str, max_rows: int, timeout: int) -> tuple[list[str], list[tuple], bool]:
        with self._connect(timeout) as conn:
            cur = conn.cursor()
            cur.execute(sql)
            return _fetch(cur, max_rows)


ADAPTERS: dict[str, type[Warehouse]] = {
    a.kind: a
    for a in (DemoWarehouse, DuckDBWarehouse, PostgresWarehouse, MySQLWarehouse, SnowflakeWarehouse, SQLiteWarehouse)
}


def build_warehouse(kind: str, config: dict[str, Any]) -> Warehouse:
    if kind not in ADAPTERS:
        raise bad_request(f"Unknown datasource kind: {kind}")
    adapter = ADAPTERS[kind]
    missing = [f.label for f in adapter.fields if f.required and not str(config.get(f.name) or "").strip()]
    if missing:
        raise bad_request(f"Missing required fields: {', '.join(missing)}")
    return adapter(config)
