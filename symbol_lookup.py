"""

symbol_lookup.py


Company name -> NSE ticker symbol lookup.

Uses fuzzy string matching against the Nifty 500 CSV (free, instant,
no API cost). Normalizes corporate suffixes ("Limited", "Ltd.", etc.)
before comparing, since NSE's official names and announcement text
often differ only in this formatting, not in actual company identity.
"""
import csv
import re
from rapidfuzz import process, fuzz

_lookup_cache = None
_normalized_lookup_cache = None


def _normalize(name: str) -> str:
    name = name.lower().strip()
    name = re.sub(r"^the\s+", "", name)
    name = re.sub(r"\b(limited|ltd\.?|pvt\.?|private)\b", "", name)
    name = re.sub(r"[^\w\s]", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name

def _load_lookup() -> dict:
    global _lookup_cache, _normalized_lookup_cache
    if _lookup_cache is not None:
        return _normalized_lookup_cache

    _lookup_cache = {}
    _normalized_lookup_cache = {}
    try:
        with open("data/nifty500_symbols.csv", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                original_name = row["company_name"]
                symbol = row["symbol"]
                _lookup_cache[original_name] = symbol
                _normalized_lookup_cache[_normalize(original_name)] = symbol
    except FileNotFoundError:
        print("[symbol_lookup] Nifty 500 CSV not found — run refresh_watchlist.py first")
    return _normalized_lookup_cache


def find_symbol(company_name: str, min_score: float = 90.0) -> str | None:
    """
    Fuzzy-match a company name to its NSE ticker symbol.
    Returns None if no confident match found (score below min_score).
    """
    lookup = _load_lookup()
    if not lookup:
        return None

    normalized_query = _normalize(company_name)
    match = process.extractOne(normalized_query, lookup.keys(), scorer=fuzz.token_sort_ratio)
    if match is None:
        return None

    matched_name, score, _ = match
    if score < min_score:
        return None

    return lookup[matched_name]