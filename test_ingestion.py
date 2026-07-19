from ingestion import fetch_nse_rss_announcements

print("Fetching NSE RSS announcements...")
items = fetch_nse_rss_announcements()

print(f"\nFound {len(items)} announcements")

if items:
    print("\n--- First 3 announcements ---")
    for item in items[:3]:
        print(f"\nSymbol: {item['symbol']}")
        print(f"Subject: {item['subject']}")
        print(f"PDF URL: {item['pdf_url']}")
else:
    print("No items found — check error messages above")