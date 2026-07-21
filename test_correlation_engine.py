# test_correlation_engine.py
from datetime import datetime, timezone, timedelta
from correlation_engine import correlate

now = datetime.now(timezone.utc)

# Case 1: scraper caught it 2 hours before NSE filed — should be news_led
nse_items = [
    {"symbol": "RELIANCE", "published": now.isoformat()},
    # Case 2: NSE filed first, scraper caught it 30 min later — nse_led
    {"symbol": "TCS", "published": (now - timedelta(hours=1)).isoformat()},
    # Case 3: no scraper match at all — unmatched
    {"symbol": "INFY", "published": now.isoformat()},
]

scraper_items = [
    {"symbol": "RELIANCE", "published_time": (now - timedelta(hours=2)).isoformat()},
    {"symbol": "TCS", "published_time": (now - timedelta(minutes=30)).isoformat()},
    # Case 4: scraper story with no NSE match (e.g. pure brokerage commentary)
    {"symbol": "HDFCBANK", "published_time": now.isoformat()},
]

results = correlate(nse_items, scraper_items)

print(f"{'Symbol':<12} {'Relationship':<12} {'Hours Lead':<12} {'Has NSE':<8} {'Has Scraper':<10}")
print("-" * 60)
for r in results:
    print(f"{r.symbol:<12} {r.relationship:<12} "
          f"{str(r.hours_lead):<12} {str(r.matched_nse_item is not None):<8} "
          f"{str(r.matched_scraper_item is not None):<10}")

# Sanity checks
print("\n=== Sanity checks ===")
by_symbol = {r.symbol: r for r in results if r.matched_nse_item}
assert by_symbol["RELIANCE"].relationship == "news_led", "RELIANCE should be news_led"
assert by_symbol["RELIANCE"].hours_lead == 2.0, f"Expected 2.0hr lead, got {by_symbol['RELIANCE'].hours_lead}"
print("OK: RELIANCE correctly tagged news_led, 2.0hr lead")

assert by_symbol["TCS"].relationship == "nse_led", "TCS should be nse_led"
print("OK: TCS correctly tagged nse_led")

assert by_symbol["INFY"].relationship == "unmatched", "INFY should be unmatched"
print("OK: INFY correctly tagged unmatched (no scraper match)")

unmatched_scrapers = [r for r in results if r.matched_nse_item is None]
hdfc_unmatched = [r for r in unmatched_scrapers if r.symbol == "HDFCBANK"]
assert len(hdfc_unmatched) == 1, "HDFCBANK scraper-only item should appear as unmatched"
print("OK: HDFCBANK scraper-only story correctly logged as unmatched")

print("\n=== All checks passed ===")