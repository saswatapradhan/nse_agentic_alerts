# test_correlation_bump.py
from db import init_db
from agentic_analyzer import apply_correlation_bump
from correlation_engine import CorrelationResult

init_db()  # runs the migration, safe to call repeatedly

fake_signal_base = {
    "confidence": 65,
    "materiality_reasoning": "Company reports strong Q1 results, revenue beat guidance.",
}

# Case 1: genuine news_led with meaningful lead — should bump
result_leading = CorrelationResult(
    symbol="SOBHA", relationship="news_led", hours_lead=2.1,
    matched_nse_item={}, matched_scraper_item={},
)
signal1 = apply_correlation_bump(dict(fake_signal_base), result_leading)
print("=== Case 1: news_led, 2.1hr lead ===")
print(f"confidence: {signal1['confidence']} (expected 72)")
print(f"news_led: {signal1['news_led']} (expected True)")
print(f"hours_lead: {signal1['hours_lead']} (expected 2.1)")
print(f"reasoning: {signal1['materiality_reasoning']}")

# Case 2: nse_led — should NOT bump
result_nse_led = CorrelationResult(
    symbol="TCS", relationship="nse_led", hours_lead=0.5,
    matched_nse_item={}, matched_scraper_item={},
)
signal2 = apply_correlation_bump(dict(fake_signal_base), result_nse_led)
print("\n=== Case 2: nse_led ===")
print(f"confidence: {signal2['confidence']} (expected 65, unchanged)")
print(f"news_led: {signal2['news_led']} (expected False)")

# Case 3: news_led but lead too small (under 30 min threshold) — should NOT bump
result_trivial = CorrelationResult(
    symbol="INFY", relationship="news_led", hours_lead=0.1,
    matched_nse_item={}, matched_scraper_item={},
)
signal3 = apply_correlation_bump(dict(fake_signal_base), result_trivial)
print("\n=== Case 3: news_led but only 0.1hr lead (below threshold) ===")
print(f"confidence: {signal3['confidence']} (expected 65, unchanged)")
print(f"news_led: {signal3['news_led']} (expected False)")

# Case 4: no correlation data at all — should NOT crash, no-op
signal4 = apply_correlation_bump(dict(fake_signal_base), None)
print("\n=== Case 4: no correlation data ===")
print(f"confidence: {signal4['confidence']} (expected 65, unchanged)")
print(f"news_led: {signal4['news_led']} (expected False)")

# Case 5: confidence near 100 — should cap, not overflow
fake_signal_high = {"confidence": 97, "materiality_reasoning": "High conviction fraud signal."}
signal5 = apply_correlation_bump(dict(fake_signal_high), result_leading)
print("\n=== Case 5: near-max confidence, should cap at 100 ===")
print(f"confidence: {signal5['confidence']} (expected 100, not 104)")

print("\n=== Verify DB migration ===")
import sqlite3
conn = sqlite3.connect("data/alerts.db")
cols = {row[1] for row in conn.execute("PRAGMA table_info(alerts)").fetchall()}
conn.close()
for col in ("news_led", "hours_lead", "confidence_bump_reason"):
    print(f"  {col}: {'OK present' if col in cols else 'MISSING'}")