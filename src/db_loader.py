"""
Project Nexus | Phase 2 runner
Builds data/nexus.db from the Phase 1 CSV and executes sql/analytical_queries.sql.

Run from the project root:
    python src/db_loader.py
"""

import csv
import re
import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DB_FILE = ROOT / "data" / "nexus.db"
CSV_FILE = ROOT / "data" / "processed" / "clean_crm_migration.csv"
SQL_FILE = ROOT / "sql" / "analytical_queries.sql"
EXPORT_DIR = ROOT / "data" / "processed"


def split_blocks(sql_text: str):
    """Yield (kind, name, sql) for every '-- @block:' or '-- @query:' marker."""
    parts = re.split(r"^-- @(block|query):\s*(\S+)\s*$", sql_text, flags=re.M)
    for i in range(1, len(parts), 3):
        yield parts[i], parts[i + 1], parts[i + 2].strip()


def load_staging(con: sqlite3.Connection) -> int:
    with open(CSV_FILE, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)
    cols = ", ".join(header)
    marks = ", ".join("?" for _ in header)
    con.executemany(f"INSERT INTO stg_crm_migration ({cols}) VALUES ({marks})", rows)
    return len(rows)


def main() -> None:
    if not CSV_FILE.exists():
        raise SystemExit("Run src/pipeline_engine.py first: clean CSV not found.")

    con = sqlite3.connect(DB_FILE)
    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 20)

    for kind, name, sql in split_blocks(SQL_FILE.read_text(encoding="utf-8")):
        if kind == "block":
            con.executescript(sql)
            if name == "schema":
                print(f"Staged {load_staging(con):,} rows into stg_crm_migration")
            if name == "transform":
                n = con.execute("SELECT COUNT(*) FROM uk_ecommerce_pipeline").fetchone()[0]
                print(f"Loaded {n:,} typed rows into uk_ecommerce_pipeline")
            con.commit()
        else:
            df = pd.read_sql_query(sql, con)
            df.to_csv(EXPORT_DIR / f"sql_{name}.csv", index=False)
            print(f"\n=== {name} ({len(df):,} rows) ===")
            print(df.head(15).to_string(index=False))

    con.close()
    print(f"\nDatabase ready: {DB_FILE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
