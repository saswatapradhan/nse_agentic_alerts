import time
from ingestion import poll_new_announcements

print("Starting poll_new_announcements()...")
start = time.time()

items = poll_new_announcements()

elapsed = time.time() - start
print(f"\nCompleted in {elapsed:.1f} seconds")
print(f"Found {len(items)} new items")