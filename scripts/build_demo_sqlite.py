"""Build data/olist/demo.sqlite.xz from the Parquet demo files.

The serverless (Vercel) bundle can't fit DuckDB, so the demo ships as an xz-compressed SQLite file that
the API decompresses into /tmp on first use. Re-run this after changing the demo data or schema:

    backend/.venv/bin/python scripts/build_demo_sqlite.py
"""

import lzma
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import duckdb  # noqa: E402

from inquira.engine.demo import _DDL, _LOADS  # noqa: E402

SRC = ROOT / "data" / "olist"
OUT = SRC / "demo.sqlite.xz"


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "demo.sqlite"
        lite = sqlite3.connect(db_path)
        lite.executescript(_DDL)  # same typed schema and foreign keys as the DuckDB demo
        reader = duckdb.connect()
        for table in _LOADS:
            cur = reader.execute(f"SELECT * FROM read_parquet('{SRC / table}.parquet')")
            width = len(cur.description)
            lite.executemany(f"INSERT INTO {table} VALUES ({','.join('?' * width)})", cur.fetchall())
        lite.commit()
        lite.execute("VACUUM")
        lite.close()
        OUT.write_bytes(lzma.compress(db_path.read_bytes(), preset=9 | lzma.PRESET_EXTREME))
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
