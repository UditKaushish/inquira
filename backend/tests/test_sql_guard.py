import pytest

from inquira.engine.sql_guard import SqlRejected, validate_sql

TABLES = {"orders", "customers", "order_items"}


def ok(sql: str, dialect: str = "duckdb") -> str:
    return validate_sql(sql, dialect, TABLES, 500).sql


@pytest.mark.parametrize("sql", [
    "SELECT * FROM orders",
    "WITH x AS (SELECT * FROM orders) SELECT * FROM x LIMIT 10",
    "SELECT COUNT(*) FROM orders UNION ALL SELECT COUNT(*) FROM customers",
    "SELECT o.order_id FROM orders o JOIN customers c ON o.customer_id = c.customer_id",
    "select date_trunc('month', order_purchase_timestamp) m, count(*) from orders group by 1 order by 1",
])
def test_allows_read_queries(sql):
    assert ok(sql)


@pytest.mark.parametrize("sql", [
    "SELECT * FROM orders; DROP TABLE orders",
    "DELETE FROM orders",
    "UPDATE orders SET order_status = 'x'",
    "INSERT INTO orders VALUES (1)",
    "DROP TABLE orders",
    "CREATE TABLE t AS SELECT * FROM orders",
    "SELECT * INTO t2 FROM orders",
    "COPY orders TO '/tmp/out.csv'",
    "ATTACH '/tmp/other.db' AS other",
    "SELECT * FROM read_csv('/etc/passwd')",
    "SELECT * FROM read_parquet('s3://bucket/x.parquet')",
    "SELECT * FROM information_schema.tables",
    "SELECT * FROM pg_catalog.pg_user",
    "SELECT pg_sleep(10)",
    "SELECT * FROM secrets",
    "PRAGMA database_list",
    "SET threads = 1",
    "",
])
def test_rejects_unsafe_queries(sql):
    with pytest.raises(SqlRejected):
        ok(sql)


def test_rejects_postgres_file_functions():
    with pytest.raises(SqlRejected):
        validate_sql("SELECT pg_read_file('/etc/passwd')", "postgres", TABLES, 500)


def test_enforces_limit():
    assert ok("SELECT * FROM orders").rstrip().endswith("LIMIT 500")
    assert ok("SELECT * FROM orders LIMIT 100000").rstrip().endswith("LIMIT 500")
    assert ok("SELECT * FROM orders LIMIT 5").rstrip().endswith("LIMIT 5")


def test_cte_names_are_not_treated_as_tables():
    assert "recent" in ok("WITH recent AS (SELECT * FROM orders) SELECT * FROM recent")


# Regressions for bypasses found in the security review.
@pytest.mark.parametrize("dialect,sql,schema", [
    ("postgres", "SELECT * FROM otherschema.orders", "public"),
    ("snowflake", "SELECT * FROM OTHER_DB.PUBLIC.ORDERS", "PUBLIC"),
    ("mysql", "SELECT * FROM mysql2.orders", "shop"),
    ("postgres", "SELECT query_to_xml('select * from pg_authid', true, true, '')", "public"),
    ("postgres", "SELECT database_to_xml(true, true, '')", "public"),
    ("postgres", "SELECT table_to_xml('pg_shadow', true, true, '')", "public"),
    ("postgres", "SELECT pg_advisory_lock(1)", "public"),
    ("postgres", "SELECT version()", "public"),
    ("postgres", "SELECT inet_server_addr()", "public"),
    ("postgres", "SELECT has_table_privilege('orders', 'select')", "public"),
    ("snowflake", "SELECT * FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()))", "PUBLIC"),
    ("snowflake", "SELECT * FROM IDENTIFIER('secrets')", "PUBLIC"),
    ("snowflake", "SELECT SYSTEM$WHITELIST()", "PUBLIC"),
    ("sqlite", "SELECT load_extension('x')", "main"),
    ("duckdb", "SELECT getenv('HOME')", "main"),
    ("duckdb", "SELECT * FROM other_db.main.orders", "main"),
])
def test_rejects_known_bypasses(dialect, sql, schema):
    with pytest.raises(SqlRejected):
        validate_sql(sql, dialect, TABLES, 500, {schema})


@pytest.mark.parametrize("dialect,sql,schema", [
    ("postgres", "SELECT * FROM public.orders", "public"),
    ("duckdb", "SELECT * FROM main.orders", "main"),
    ("snowflake", "SELECT COUNT(*) FROM PUBLIC.ORDERS", "PUBLIC"),
    ("postgres", "SELECT date_trunc('month', created_at) m, round(avg(total)::numeric, 2) FROM orders GROUP BY 1",
     "public"),
    ("duckdb", "SELECT strftime(order_purchase_timestamp, '%Y-%m') m, coalesce(sum(1), 0) FROM orders GROUP BY 1",
     "main"),
])
def test_configured_schema_and_common_functions_still_allowed(dialect, sql, schema):
    assert validate_sql(sql, dialect, TABLES, 500, {schema}).sql
