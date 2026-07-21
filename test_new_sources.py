# test_new_sources.py
import requests
import feedparser

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}

# ── RSS sources ──
RSS_CANDIDATES = {
    "BusinessLine_Stocks": "https://www.thehindubusinessline.com/markets/stock-markets/feeder/default.rss",
    "Moneycontrol_LatestNews": "https://www.moneycontrol.com/rss/latestnews.xml",
}

for name, url in RSS_CANDIDATES.items():
    print(f"\n=== {name} ===")
    print(f"URL: {url}")
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        print(f"Status: {resp.status_code}")
        if resp.status_code == 200:
            feed = feedparser.parse(resp.content)
            print(f"Entries: {len(feed.entries)}")
            if feed.bozo:
                print(f"WARNING: malformed - {feed.bozo_exception}")
            if feed.entries:
                e = feed.entries[0]
                print(f"Sample title: {e.get('title', 'MISSING')}")
                print(f"Sample published: {e.get('published', 'MISSING')}")
        else:
            print(f"Failed. Snippet: {resp.text[:200]}")
    except requests.RequestException as e:
        print(f"Request error: {e}")

# ── StockEdge JSON API (not RSS) ──
print(f"\n=== StockEdge_API ===")
url = "https://api.stockedge.com/Api/DailyDashboardApi/GetLatestNewsItems"
try:
    resp = requests.get(url, headers=HEADERS, timeout=10)
    print(f"Status: {resp.status_code}")
    print(f"Content-Type: {resp.headers.get('Content-Type')}")
    if resp.status_code == 200:
        try:
            data = resp.json()
            print(f"Response type: {type(data)}")
            if isinstance(data, list):
                print(f"Items: {len(data)}")
                if data:
                    print(f"Sample item keys: {list(data[0].keys())}")
                    print(f"Sample item: {data[0]}")
            else:
                print(f"Response: {str(data)[:500]}")
        except ValueError:
            print(f"Not valid JSON. Snippet: {resp.text[:300]}")
    else:
        print(f"Failed. Snippet: {resp.text[:300]}")
except requests.RequestException as e:
    print(f"Request error: {e}")