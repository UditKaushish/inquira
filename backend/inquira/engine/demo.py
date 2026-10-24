"""Builds the bundled demo warehouse (Olist Brazilian e-commerce) as DuckDB."""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

from inquira.core.config import get_settings

log = logging.getLogger(__name__)
_lock = threading.Lock()
_VERSION = "2"  # bump when the demo build changes so stale files are rebuilt

_DDL = """
CREATE TABLE customers (
  customer_id VARCHAR PRIMARY KEY,
  customer_unique_id VARCHAR,
  customer_zip_code_prefix VARCHAR,
  customer_city VARCHAR,
  customer_state VARCHAR
);
CREATE TABLE sellers (
  seller_id VARCHAR PRIMARY KEY,
  seller_zip_code_prefix VARCHAR,
  seller_city VARCHAR,
  seller_state VARCHAR
);
CREATE TABLE products (
  product_id VARCHAR PRIMARY KEY,
  product_category_name VARCHAR,
  product_name_length INTEGER,
  product_description_length INTEGER,
  product_photos_qty INTEGER,
  product_weight_g INTEGER,
  product_length_cm INTEGER,
  product_height_cm INTEGER,
  product_width_cm INTEGER
);
CREATE TABLE orders (
  order_id VARCHAR PRIMARY KEY,
  customer_id VARCHAR REFERENCES customers(customer_id),
  order_status VARCHAR,
  order_purchase_timestamp TIMESTAMP,
  order_approved_at TIMESTAMP,
  order_delivered_carrier_date TIMESTAMP,
  order_delivered_customer_date TIMESTAMP,
  order_estimated_delivery_date TIMESTAMP
);
CREATE TABLE order_items (
  order_id VARCHAR REFERENCES orders(order_id),
  order_item_id INTEGER,
  product_id VARCHAR REFERENCES products(product_id),
  seller_id VARCHAR REFERENCES sellers(seller_id),
  shipping_limit_date TIMESTAMP,
  price DECIMAL(10, 2),
  freight_value DECIMAL(10, 2)
);
CREATE TABLE order_payments (
  order_id VARCHAR REFERENCES orders(order_id),
  payment_sequential INTEGER,
  payment_type VARCHAR,
  payment_installments INTEGER,
  payment_value DECIMAL(10, 2)
);
"""

# Load order respects foreign keys. Source files are zstd Parquet (17 MB vs 48 MB as CSV), all-text
# columns that the typed DDL above casts on insert.
_LOADS = ["customers", "sellers", "products", "orders", "order_items", "order_payments"]

DEMO_KNOWLEDGE = [
    ("Revenue", "metric",
     "Revenue (GMV) = SUM(order_items.price). Include freight only when the user asks for 'total paid' "
     "(price + freight_value). Payments in order_payments.payment_value already include freight."),
    ("Delivered orders", "metric",
     "An order counts as delivered when orders.order_status = 'delivered'. Delivery time in days = "
     "date_diff('day', order_purchase_timestamp, order_delivered_customer_date)."),
    ("Late delivery", "metric",
     "An order is late when order_delivered_customer_date > order_estimated_delivery_date."),
    ("Average order value", "metric",
     "AOV = SUM(order_items.price) / COUNT(DISTINCT order_items.order_id)."),
    ("Unique customers", "glossary",
     "customers.customer_id is per-order. Use customers.customer_unique_id to count real people."),
    ("Geography", "glossary",
     "customer_state / seller_state are 2-letter Brazilian state codes (SP = São Paulo, RJ = Rio de Janeiro, "
     "MG = Minas Gerais). Prices are in Brazilian reais (BRL)."),
    ("Product categories", "glossary",
     "product_category_name is in Portuguese, e.g. beleza_saude = health & beauty, cama_mesa_banho = bed & bath, "
     "esporte_lazer = sports & leisure, informatica_acessorios = computer accessories, "
     "moveis_decoracao = furniture & decor, utilidades_domesticas = housewares, relogios_presentes = watches & gifts. "
     "Translate category names to English in answers."),
    ("Data window", "note",
     "Orders span 2016-09 to 2018-10; 2016 and the final months of 2018 are sparse. Relative dates such as "
     "'last month' should be computed relative to MAX(order_purchase_timestamp), not today."),
]

DEMO_SUGGESTIONS = [
    "What was total revenue by month in 2017?",
    "Which 10 product categories generate the most revenue?",
    "What share of orders were delivered late, by customer state?",
    "How do customers pay? Show the split by payment type.",
    "Who are the top 5 sellers by number of orders?",
    "What is the average delivery time in days by state?",
]


def demo_path() -> Path:
    return get_settings().data_dir / f"demo_v{_VERSION}.duckdb"


def demo_available() -> bool:
    return (get_settings().demo_data_dir / "orders.parquet").exists() or demo_path().exists()


def ensure_demo_database() -> Path:
    path = demo_path()
    if path.exists():
        return path
    with _lock:
        if path.exists():
            return path
        import duckdb

        src = get_settings().demo_data_dir
        if not (src / "orders.parquet").exists():
            raise FileNotFoundError(f"Demo data not found in {src}")
        # Unique temp file + atomic rename: safe when several worker processes race.
        tmp = path.with_suffix(f".{os.getpid()}.building")
        tmp.unlink(missing_ok=True)
        log.info("Building demo warehouse at %s", path)
        conn = duckdb.connect(str(tmp))
        try:
            conn.execute(_DDL)
            for table in _LOADS:
                source = str(src / f"{table}.parquet").replace("'", "''")
                conn.execute(f"INSERT INTO {table} SELECT * FROM read_parquet('{source}')")
            conn.execute("CHECKPOINT")
        finally:
            conn.close()
        os.replace(tmp, path)
        return path
