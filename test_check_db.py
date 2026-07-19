from db import get_conn

with get_conn() as conn:
    alerts = conn.execute("SELECT symbol, category, priority, created_at FROM alerts").fetchall()
    processed = conn.execute("SELECT COUNT(*) as cnt FROM processed_pdfs").fetchone()

print(f"Total alerts sent so far: {len(alerts)}")
for a in alerts:
    print(f"  {a['symbol']} | {a['category']} | {a['priority']} | {a['created_at']}")

print(f"\nTotal PDFs marked as processed: {processed['cnt']}")