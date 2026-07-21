# clear_k2infragen_dedup.py
from db import get_conn

with get_conn() as conn:
    result = conn.execute(
        "DELETE FROM processed_pdfs WHERE pdf_url LIKE '%k2%' OR pdf_url LIKE '%K2%'"
    )
    print(f"Deleted {result.rowcount} matching row(s)")

    # Show what's left, to confirm we got the right one(s)
    remaining = conn.execute("SELECT pdf_url FROM processed_pdfs ORDER BY processed_at DESC LIMIT 5").fetchall()
    print("\nMost recent remaining processed_pdfs entries:")
    for row in remaining:
        print(f"  {row['pdf_url']}")