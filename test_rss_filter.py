from ingestion import fetch_nse_rss_announcements

items_15min = fetch_nse_rss_announcements(max_age_minutes=15)
print(f"Items in last 15 minutes: {len(items_15min)}")

items_2min = fetch_nse_rss_announcements(max_age_minutes=2)
print(f"Items in last 2 minutes: {len(items_2min)}")

if items_15min:
    print(f"\nMost recent item's published time: {items_15min[0]['published']}")