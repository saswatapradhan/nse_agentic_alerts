from rapidfuzz import process, fuzz
from symbol_lookup import _load_lookup

lookup = _load_lookup()

query = "Infosys Limited"
matches = process.extract(query, lookup.keys(), scorer=fuzz.token_sort_ratio, limit=5)

print(f"Top 5 matches for '{query}':")
for name, score, _ in matches:
    print(f"  {score:.1f}  {name}")