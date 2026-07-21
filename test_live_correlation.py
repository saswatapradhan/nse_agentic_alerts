"""
test_live_correlation.py

First real end-to-end test: pulls LIVE NSE announcements and LIVE
scraped RSS items, runs them through correlation_engine.py, and shows
actual news_led/nse_led/unmatched results on real data — not the
synthetic fake timestamps used to unit-test correlation_engine.py
earlier.

Note: SOBHA and SUZLON results were company Q1 announcements — good
chance NSE has (or will soon have) a board-meeting-intimation or
results filing for these exact symbols today, which is the real test
of whether correlation actually finds a match.
"""
from ingestion import fetch_nse_rss_announcements
from rss_ingestion import poll_all_sources
from correlation_engine import correlate

print("=== Fetching live NSE announcements ===")
nse_items = fetch_nse_rss_announcements(max_age_minutes=1440)  # last 24h, wider than production's 15min
print(f"NSE items: {len(nse_items)}")

print("\n=== Fetching live scraped RSS items ===")
scraper_items_raw = poll_all_sources(max_age_minutes=1440)  # last 24h, same wider window
print(f"Scraper items: {len(scraper_items_raw)}")

# correlation_engine.py expects "published_time" key, rss_ingestion.py
# produces "published" — adapt here rather than change either module's
# established interface
scraper_items = [
    {**item, "published_time": item["published"]}
    for item in scraper_items_raw
]

print("\n=== Running correlation ===")
results = correlate(nse_items, scraper_items)

print(f"\n{'Symbol':<15} {'Relationship':<12} {'Hours Lead':<12}")
print("-" * 45)
for r in results:
    print(f"{r.symbol:<15} {r.relationship:<12} {str(r.hours_lead):<12}")

# Add to test_live_correlation.py, replace the results print loop:
for r in results:
    origin = "NSE-only" if r.matched_scraper_item is None and r.matched_nse_item else \
              "Scraper-only" if r.matched_nse_item is None else "MATCHED"
    if origin == "MATCHED":
        print(f"{r.symbol:<15} {r.relationship:<12} {str(r.hours_lead):<12} [{origin}]")

print(f"\n=== Matches only (the actual signal) ===")
matched = [r for r in results if r.matched_nse_item and r.matched_scraper_item]
for r in matched:
    print(f"{r.symbol}: {r.relationship}, {r.hours_lead}hr lead")
print(f"\nTotal genuine matches: {len(matched)} out of {len(nse_items)} NSE items, {len(scraper_items)} scraper items")

news_led = [r for r in results if r.relationship == "news_led"]
nse_led = [r for r in results if r.relationship == "nse_led"]
unmatched = [r for r in results if r.relationship == "unmatched"]

print(f"\n=== Summary ===")
print(f"news_led:  {len(news_led)}")
print(f"nse_led:   {len(nse_led)}")
print(f"unmatched: {len(unmatched)}")