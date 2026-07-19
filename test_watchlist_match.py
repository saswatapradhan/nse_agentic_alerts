from false_positive_filters import apply_filters
import csv

with open("data/nifty500_symbols.csv", encoding="utf-8") as f:
    watchlist = {row["symbol"].strip().upper() for row in csv.DictReader(f)}

tests = ["NTPC Limited", "Power Grid Corporation of India Limited",
         "Punjab National Bank", "RBL Bank Limited", "Oberoi Realty Limited"]

for name in tests:
    result = apply_filters("Board Meeting Intimation", "test body", name, watchlist)
    print(f"{name:45} | skip={result.skip} | {result.reason}")