"""
rss_ingestion.py

RSS-based scraping layer for news commentary sources (ET, LiveMint).
Runs ALONGSIDE the existing ingestion.py (NSE RSS + PDF extraction) —
does NOT replace it. main.py's NSE pipeline is untouched by this file.

Dedup + caching: extracted items are checked against
already_extracted_scraper_item() before spending a GPT call on them,
and stored via cache_scraper_item() so they remain available for
correlation_engine.py matching across multiple poll cycles (up to its
6-hour MATCH_WINDOW_HOURS), even after this file's own returned list
stops including them (which happens once they're deduped).

poll_all_sources() returns only NEWLY extracted items this cycle (for
logging/visibility) — for correlation matching, callers should use
db.get_recent_scraper_items() instead, which pulls the full rolling
window regardless of which cycle first saw each item.
"""
import feedparser
import requests
from datetime import datetime, timezone, timedelta

from ingestion import should_skip_announcement
from headline_extractor import extract_headline_info
from db import already_extracted_scraper_item, cache_scraper_item

IST = timezone(timedelta(hours=5, minutes=30))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
}

RSS_SOURCES = {
    "ET_Stocks": {
        "url": "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",
        "enabled": True,
    },
    "LiveMint_Markets": {
        "url": "https://www.livemint.com/rss/markets",
        "enabled": True,
    },
    "BusinessStandard_Markets": {
        "url": "https://www.business-standard.com/rss/markets-106.rss",
        "enabled": False,  # 403 in earlier tests — revisit later
    },
    "BSE_Corporate": {
        "url": "https://www.bseindia.com/rss/corporate-announcements.xml",
        "enabled": False,  # JS-rendered SPA, no real XML — revisit later
    },
}


def _parse_published(entry) -> datetime:
    if getattr(entry, "published_parsed", None):
        return datetime(*entry.published_parsed[:6], tzinfo=timezone.utc).astimezone(IST)
    return datetime.now(IST)


def fetch_source(source_name: str, url: str, max_age_minutes: int = 120) -> list[dict]:
    """Fetch, filter, dedup, and GPT-extract company info for one RSS
    source. Returns only NEWLY extracted (not previously cached)
    NSE_COMPANY_SPECIFIC items with a resolved symbol. Each returned
    item is also persisted via cache_scraper_item()."""
    items = []
    dropped_irrelevant = 0
    skipped_already_extracted = 0
    cutoff = datetime.now(IST).timestamp() - (max_age_minutes * 60)

    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)

        if feed.bozo:
            print(f"[rss_ingestion] WARNING: {source_name} feed malformed: {feed.bozo_exception}")

        for entry in feed.entries:
            title = entry.get("title", "").strip()
            summary = entry.get("summary", entry.get("description", "")).strip()
            link = entry.get("link", "")

            if not title or not link:
                continue

            # Dedup FIRST, before any GPT spend — this is the cost guard
            if already_extracted_scraper_item(link):
                skipped_already_extracted += 1
                continue

            check_text = summary or title
            if should_skip_announcement(check_text):
                continue

            published_dt = _parse_published(entry)
            if published_dt.timestamp() < cutoff:
                continue

            extracted = extract_headline_info(title, summary)

            if extracted["relevance"] != "NSE_COMPANY_SPECIFIC" or not extracted["resolved_symbol"]:
                dropped_irrelevant += 1
                continue

            item = {
                "symbol": extracted["resolved_symbol"],
                "company_name": extracted["company_name"],
                "subject": title,
                "text_snippet": summary,
                "category_hint": extracted["category_hint"],
                "published": published_dt.isoformat(),
                "source": source_name,
                "link": link,
            }

            cache_scraper_item(item)  # persist for correlation matching across cycles
            items.append(item)

    except requests.RequestException as e:
        print(f"[rss_ingestion] Failed to fetch {source_name}: {e}")
    except Exception as e:
        print(f"[rss_ingestion] Unexpected error parsing {source_name}: {e}")

    if dropped_irrelevant > 0:
        print(f"[rss_ingestion] {source_name}: dropped {dropped_irrelevant} macro/non-Indian/unresolved items")
    if skipped_already_extracted > 0:
        print(f"[rss_ingestion] {source_name}: skipped {skipped_already_extracted} already-cached items (dedup)")

    return items


def poll_all_sources(max_age_minutes: int = 120) -> list[dict]:
    """Returns only NEWLY extracted items this call. For correlation
    matching against a rolling window, use db.get_recent_scraper_items()
    instead — this function's return value is for visibility/logging."""
    all_items = []
    for source_name, config in RSS_SOURCES.items():
        if not config["enabled"]:
            continue
        print(f"[rss_ingestion] Fetching {source_name}...")
        items = fetch_source(source_name, config["url"], max_age_minutes)
        print(f"[rss_ingestion]   -> {len(items)} NEW company-specific items resolved")
        all_items.extend(items)

    return all_items


if __name__ == "__main__":
    results = poll_all_sources()
    print(f"\n=== Total: {len(results)} newly-extracted company-specific items ===")
    for item in results:
        print(f"[{item['source']}] {item['symbol']} ({item['company_name']}) — {item['category_hint']}")
        print(f"    {item['subject'][:70]}")
        print(f"    published: {item['published']}")