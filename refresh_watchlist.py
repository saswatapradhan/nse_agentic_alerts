"""

refresh_watchlist.py


Fetches NSE's complete master list of all listed equity securities —
not index-derived subsets like Nifty 500 or Nifty Total Market, but
literally every symbol NSE has listed on the main board.

Source: NSE's own "Securities Available for Trading" list, the same
file NSE itself publishes for market participants.
https://www.nseindia.com/market-data/securities-available-for-trading

Re-run this periodically (monthly is reasonable) since new listings
and delistings happen continuously, unlike quarterly index rebalances.
"""
import requests
import csv
import io

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
}

EQUITY_LIST_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
OUTPUT_PATH = "data/nifty500_symbols.csv"  # keeping the same filename other files reference


def refresh():
    session = requests.Session()
    session.headers.update(HEADERS)
    session.get("https://www.nseindia.com", timeout=10)  # cookie bootstrap

    print("Fetching complete NSE equity list (all listed securities)...")
    resp = session.get(EQUITY_LIST_URL, timeout=15)
    resp.raise_for_status()

    # NSE's CSV has inconsistent spacing in header names (e.g. "SYMBOL,NAME OF
    # COMPANY, SERIES, ...") — strip whitespace from both headers and values
    # so lookups by key don't silently fail.
    raw_text = resp.content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(raw_text))
    reader.fieldnames = [f.strip() for f in reader.fieldnames]

    rows = []
    for row in reader:
        row = {k.strip(): (v.strip() if v else v) for k, v in row.items()}
        symbol = row.get("SYMBOL", "")
        name = row.get("NAME OF COMPANY", "")
        if symbol and name:
            rows.append((name, symbol))

    if not rows:
        print("ERROR: parsed 0 rows — NSE may have changed the CSV format. "
              "Check the raw file manually before retrying.")
        return

    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["company_name", "symbol"])
        for name, symbol in rows:
            writer.writerow([name, symbol])

    print(f"Wrote {len(rows)} symbols to {OUTPUT_PATH}")
    print("This is NSE's full equity list — covers small/micro-caps outside "
          "any index, not just the top 750 or top 500.")


if __name__ == "__main__":
    refresh()