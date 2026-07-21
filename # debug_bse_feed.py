# debug_bse_feed.py
import requests

resp = requests.get(
    "https://www.bseindia.com/rss/corporate-announcements.xml",
    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"},
    timeout=10,
)
print(f"Status: {resp.status_code}")
print(f"Content-Type: {resp.headers.get('Content-Type')}")
print(f"Content length: {len(resp.text)}")

with open("bse_raw_response.xml", "w", encoding="utf-8") as f:
    f.write(resp.text)
print("Saved to bse_raw_response.xml")

# Show the specific region around the reported error (line 72)
lines = resp.text.splitlines()
if len(lines) >= 72:
    print("\n--- Lines 68-76 (around the reported error) ---")
    for i in range(67, min(76, len(lines))):
        print(f"{i+1}: {lines[i]}")
else:
    print(f"\nOnly {len(lines)} lines total — response may be truncated or an error page, not real feed content")