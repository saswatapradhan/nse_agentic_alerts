# fix_and_debug_sources.py
import requests
import feedparser

HEADERS_BASE = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
}

# ── 1. Business Standard retry with session + referer ──────────────
print("=== Business Standard retry ===")
s = requests.Session()
s.headers.update({
    **HEADERS_BASE,
    "Referer": "https://www.business-standard.com/",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
})
try:
    resp = s.get("https://www.business-standard.com/rss/markets-106.rss", timeout=10)
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        feed = feedparser.parse(resp.content)
        print(f"Entries: {len(feed.entries)}")
        if feed.entries:
            print(f"Sample title: {feed.entries[0].get('title', 'MISSING')}")
            print(f"Sample published: {feed.entries[0].get('published', 'MISSING')}")
    else:
        print(f"Still failing. Response snippet: {resp.text[:300]}")
except requests.RequestException as e:
    print(f"Request failed: {e}")

# ── 2. BSE — inspect the actual malformed response ──────────────
print("\n=== BSE raw response inspection ===")
try:
    resp = requests.get(
        "https://www.bseindia.com/rss/corporate-announcements.xml",
        headers=HEADERS_BASE, timeout=10,
    )
    print(f"Status: {resp.status_code}")
    print(f"Content-Type: {resp.headers.get('Content-Type')}")
    print(f"Content length: {len(resp.text)}")

    with open("bse_raw_response.xml", "w", encoding="utf-8") as f:
        f.write(resp.text)
    print("Saved full response to bse_raw_response.xml")

    lines = resp.text.splitlines()
    print(f"Total lines: {len(lines)}")
    if len(lines) >= 72:
        print("\n--- Lines 68-76 (around the reported parse error) ---")
        for i in range(67, min(76, len(lines))):
            print(f"{i+1}: {lines[i]}")
    else:
        print(f"\nOnly {len(lines)} lines — likely an error/redirect page, not real feed content")
        print("\n--- First 500 chars ---")
        print(resp.text[:500])
except requests.RequestException as e:
    print(f"Request failed: {e}")