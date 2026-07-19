from sheet_prices import get_price_from_sheet
import time

print("First call (will fetch + cache)...")
start = time.time()
price = get_price_from_sheet("TCS")
print(f"TCS: Rs.{price} (took {time.time()-start:.1f}s)")

print("\nSecond call (should use cache, be instant)...")
start = time.time()
price2 = get_price_from_sheet("NTPC")
print(f"NTPC: Rs.{price2} (took {time.time()-start:.1f}s)")

print("\nSymbol that shouldn't exist...")
price3 = get_price_from_sheet("FAKESTOCK123")
print(f"FAKESTOCK123: {price3} (should be None)")