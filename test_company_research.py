"""
test_company_research.py

Standalone test for company_research.py — run this BEFORE wiring it
into main.py, so any issues with the OpenAI Responses API call, JSON
parsing, or citation extraction show up here with a clean traceback
instead of buried inside _process_single_item's try/except.
"""
from company_research import get_company_research
from db import init_db

# Make sure the company_research table exists (safe to call repeatedly)
init_db()

# Pick a well-known, heavily-covered large-cap first — best chance of
# good web search results, so if THIS fails, the problem is the code,
# not sparse data for an obscure symbol.
TEST_SYMBOL = "RELIANCE"
TEST_COMPANY_NAME = "Reliance Industries Limited"

print(f"=== Testing company_research for {TEST_SYMBOL} ===\n")

# First call: should be a cache MISS (nothing in DB yet), triggers a
# real GPT + web_search call. This is the expensive one — watch for
# how long it takes and whether it errors.
print("--- First call (expect cache miss, live GPT call) ---")
result = get_company_research(TEST_SYMBOL, TEST_COMPANY_NAME)

if result is None:
    print("\n[FAIL] get_company_research returned None — check the error")
    print("printed above (from company_research.py's except blocks).")
else:
    print("\n[SUCCESS] Got research data:\n")
    import json
    print(json.dumps(result, indent=2))

    # Sanity checks on the shape of what came back
    print("\n--- Field checks ---")
    expected_fields = [
        "sector", "industry", "company_type", "market_cap_tier",
        "technical_snapshot", "financial_snapshot", "swot", "key_risks",
        "confidence_note", "sources",
    ]
    for field in expected_fields:
        present = field in result
        print(f"  {'OK' if present else 'MISSING'}: {field}")

    swot = result.get("swot", {})
    for k in ["strengths", "weaknesses", "opportunities", "threats"]:
        count = len(swot.get(k, []))
        print(f"  swot.{k}: {count} item(s)")

    sources = result.get("sources", [])
    print(f"  sources: {len(sources)} URL(s) extracted")
    if not sources:
        print("  [NOTE] No sources extracted — citation parsing in "
              "company_research.py may need adjusting to match your "
              "SDK's actual response.output structure. Not fatal, but "
              "worth checking if you want auditable sources.")

# Second call: should be a cache HIT — should return instantly with no
# new API call. This confirms the 30-day caching logic actually works.
print("\n--- Second call (expect cache HIT, no new API call, instant) ---")
import time
start = time.time()
result2 = get_company_research(TEST_SYMBOL, TEST_COMPANY_NAME)
elapsed = time.time() - start

print(f"Elapsed: {elapsed:.2f}s")
if elapsed < 1.0:
    print("[SUCCESS] Fast return — cache is working.")
else:
    print("[WARNING] Slow return on second call — cache may not be "
          "hitting (check _get_cached / valid_until logic).")

if result == result2:
    print("[SUCCESS] Cached data matches first call.")
else:
    print("[WARNING] Cached data differs from first call — unexpected.")

# Third call: force_refresh=True should bypass cache and hit GPT again
print("\n--- Third call (force_refresh=True, expect live call again) ---")
start = time.time()
result3 = get_company_research(TEST_SYMBOL, TEST_COMPANY_NAME, force_refresh=True)
elapsed = time.time() - start
print(f"Elapsed: {elapsed:.2f}s")
if elapsed > 1.0:
    print("[SUCCESS] force_refresh correctly bypassed cache.")
else:
    print("[WARNING] force_refresh returned instantly — may not be "
          "bypassing cache correctly.")

print("\n=== Test complete ===")