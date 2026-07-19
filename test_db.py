from db import init_db, insert_alert, get_conn

init_db()
print("Database created successfully at data/alerts.db")

# Insert one fake test alert to prove it works
fake_alert = {
    "symbol": "TCS", "category": "ACQUISITION", "sentiment": "POSITIVE",
    "priority": "HIGH", "confidence": 85, "predicted_direction": "UP",
    "rupee_amount_cr": 600, "subject": "Test acquisition announcement",
    "summary": "TCS acquires XYZ for Rs 600 Cr", "pdf_source_url": "https://example.com/test.pdf",
    "price_at_alert": 3500.0, "raw_llm_json": {"test": "data"}
}
alert_id = insert_alert(fake_alert)
print(f"Inserted test alert with id: {alert_id}")

# Read it back to prove the round-trip works
with get_conn() as conn:
    row = conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
    print(f"Read back from database: {row['symbol']} | {row['category']} | confidence={row['confidence']}")