"""

sheet_prices.py


Live price + momentum lookup via a public Google Sheet using GOOGLEFINANCE()
formulas. Caches the entire sheet in memory, refreshed periodically.
"""
import requests
import csv
import io
import time

from config import GOOGLE_SHEET_CSV_URL, SHEET_PRICE_CACHE_MINUTES

_cache = {}          # {symbol: full row dict}
_cache_timestamp = 0


def _to_float(val):
    try:
        return float(str(val).strip().replace("%", ""))
    except (ValueError, TypeError):
        return None


def _refresh_cache():
    global _cache, _cache_timestamp
    try:
        resp = requests.get(GOOGLE_SHEET_CSV_URL, timeout=15)
        resp.raise_for_status()
        text = resp.content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))

        new_cache = {}
        for row in reader:
            symbol = (row.get("SYMBOL") or "").strip().upper()
            price = _to_float(row.get("Live Price"))
            if not symbol or price is None:
                continue
            new_cache[symbol] = {
                "price": price,
                "daily_change_pct": _to_float(row.get("Daily Change (%)")),
                "volume": _to_float(row.get("Trading Volume")),
                "today_high": _to_float(row.get("Today's High")),
                "today_low": _to_float(row.get("Today's Low")),
                "week52_high": _to_float(row.get("52-Week High")),
                "week52_low": _to_float(row.get("52-Week Low")),
                "weekly_pct": _to_float(row.get("Weekly (7 Days)")),
                "monthly_pct": _to_float(row.get("Monthly (30 Days)")),
            }

        if new_cache:
            _cache = new_cache
            _cache_timestamp = time.time()
            print(f"[sheet_prices] Cache refreshed: {len(_cache)} symbols")
        else:
            print("[sheet_prices] Refresh returned 0 usable rows — keeping old cache")
    except Exception as e:
        print(f"[sheet_prices] Cache refresh failed: {e} — keeping old cache")


def _ensure_fresh():
    cache_age_minutes = (time.time() - _cache_timestamp) / 60
    if not _cache or cache_age_minutes >= SHEET_PRICE_CACHE_MINUTES:
        _refresh_cache()


def get_price_from_sheet(symbol: str) -> float | None:
    """Backward-compatible: just the live price."""
    _ensure_fresh()
    row = _cache.get(symbol.strip().upper())
    return row["price"] if row else None


def get_stock_row(symbol: str) -> dict | None:
    """Full row: price, volume, daily/weekly/monthly momentum, 52w range."""
    _ensure_fresh()
    return _cache.get(symbol.strip().upper())