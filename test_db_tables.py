# test_db_tables.py
from db import get_conn

with get_conn() as conn:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    print([r["name"] for r in rows])