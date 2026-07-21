# check_k2infragen.py
import csv

with open("data/nifty500_symbols.csv", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    matches = [row for row in reader if "k2" in row["company_name"].lower() or "infragen" in row["company_name"].lower()]

print(f"Rows containing 'k2' or 'infragen': {len(matches)}")
for row in matches:
    print(row)

if not matches:
    print("\nNot in the CSV at all — likely a recent listing. Re-run refresh_watchlist.py.")