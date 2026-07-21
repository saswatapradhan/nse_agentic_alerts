# test_dedup_logic.py
"""
Directly tests already_extracted_scraper_item() / cache_scraper_item()
against the DB, bypassing live RSS entirely — removes dependency on
whether real feeds happen to have fresh items right now.
"""
from db import init_db, already_extracted_scraper_item, cache_scraper_item, get_recent_scraper_items

init_db()

TEST_LINK = "https://test-dedup-verification.example.com/fake-article-12345"

# Clean slate check — this exact test link shouldn't exist from a prior run
# (if it does, a previous test run wasn't cleaned up; that's fine, dedup
# should still behave correctly either way, but flag it for visibility)
already_exists_before = already_extracted_scraper_item(TEST_LINK)
print(f"Before caching: already_extracted_scraper_item = {already_exists_before} "
      f"(expected False on a fresh test link)")

fake_item = {
    "link": TEST_LINK,
    "symbol": "TESTSYM",
    "company_name": "Test Company Ltd",
    "subject": "TEST: Dedup verification article",
    "text_snippet": "This is a fake item for testing dedup logic only.",
    "category_hint": "RESULTS",
    "published": "2026-07-21T20:00:00+05:30",
    "source": "TEST_SOURCE",
}

print("\nCaching the item for the first time...")
cache_scraper_item(fake_item)

after_first_cache = already_extracted_scraper_item(TEST_LINK)
print(f"After 1st cache: already_extracted_scraper_item = {after_first_cache} "
      f"(expected True)")

print("\nAttempting to cache the SAME link again (simulates 2nd poll cycle seeing it)...")
cache_scraper_item(fake_item)  # should be INSERT OR IGNORE — no error, no duplicate row

recent = get_recent_scraper_items(hours=1.0)
matching = [item for item in recent if item["link"] == TEST_LINK]
print(f"\nRows matching TEST_LINK in get_recent_scraper_items(): {len(matching)} "
      f"(expected exactly 1, NOT 2 — proves INSERT OR IGNORE prevented a duplicate row)")

print("\n=== Result ===")
checks = [
    ("Fresh link starts unresolved", already_exists_before == False),
    ("Link marked extracted after caching", after_first_cache == True),
    ("No duplicate row created on re-cache", len(matching) == 1),
]
all_passed = all(passed for _, passed in checks)
for label, passed in checks:
    print(f"  {'OK' if passed else 'FAIL'}: {label}")

print(f"\n{'ALL CHECKS PASSED' if all_passed else 'SOME CHECKS FAILED — investigate before trusting dedup in main_v3.py'}")