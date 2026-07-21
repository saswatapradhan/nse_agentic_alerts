"""
correlation_engine.py

Matches scraped news items to NSE RSS announcements by symbol + time
window. Tags each pair as:
  - "news_led": scraper caught the story BEFORE the NSE PDF appeared
  - "nse_led":  NSE PDF appeared BEFORE or at the same time as the scraper
  - "unmatched": no corresponding item found on the other side within
                 the matching window

This does NOT decide anything about confidence/priority itself — it
only produces the timing relationship + hours_lead. agentic_analyzer.py
consumes this output to apply the (visible, labeled) confidence bump.

Symbol matching uses the same fuzzy lookup as the rest of the pipeline
(symbol_lookup.find_symbol) since scraped article text won't always
use NSE's exact ticker.
"""
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

from symbol_lookup import find_symbol

# How far apart (in hours) two items can be and still be considered
# "about the same announcement." Wider than you might expect because
# scraped news can precede official filings by a few hours, and NSE
# sometimes files late relative to when news breaks.
MATCH_WINDOW_HOURS = 6.0


@dataclass
class CorrelationResult:
    symbol: str
    relationship: str          # "news_led" / "nse_led" / "unmatched"
    hours_lead: float | None   # positive = scraper led by this many hours; None if unmatched
    matched_nse_item: dict | None
    matched_scraper_item: dict | None


def _resolve_symbol(raw_symbol_or_name: str) -> str:
    """Normalize to a ticker so NSE's company-name format and scraper's
    (possibly different) naming don't cause false non-matches."""
    resolved = find_symbol(raw_symbol_or_name)
    return resolved or raw_symbol_or_name.strip().upper()


def _parse_dt(dt_value) -> datetime | None:
    """Accepts a datetime object, an ISO string (from rss_ingestion.py),
    or NSE's raw RSS format (from ingestion.py: '%d-%b-%Y %H:%M:%S' or
    '%d-%b-%Y %H:%M', both naive IST) — tries all known formats before
    giving up, mirroring ingestion.py's own two-format fallback."""
    if dt_value is None:
        return None
    if isinstance(dt_value, datetime):
        return dt_value if dt_value.tzinfo else dt_value.replace(tzinfo=timezone.utc)

    dt_str = str(dt_value)

    # Try ISO first (rss_ingestion.py's format)
    try:
        parsed = datetime.fromisoformat(dt_str)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        pass

    # Try NSE's raw formats (ingestion.py's format) — assume IST, same
    # as ingestion.py itself assumes for these exact formats
    IST = timezone(timedelta(hours=5, minutes=30))
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M"):
        try:
            return datetime.strptime(dt_str, fmt).replace(tzinfo=IST)
        except (ValueError, TypeError):
            continue

    return None


def correlate(nse_items: list[dict], scraper_items: list[dict],
              window_hours: float = MATCH_WINDOW_HOURS) -> list[CorrelationResult]:
    """
    nse_items: list of dicts with at least {"symbol": str, "published": datetime|str}
               (matches ingestion.py's existing output shape)
    scraper_items: list of dicts with at least {"symbol"|"company": str, "published_time": datetime|str}
                   (matches the planned news_scraper.py output shape)

    Returns one CorrelationResult per NSE item (NSE remains the anchor
    since it's the authoritative announcement source), plus separate
    results for any scraper items that never found an NSE match at all.
    """
    results = []

    # Pre-resolve + pre-parse scraper items once, not per NSE item (avoids
    # O(n*m) repeated symbol lookups on larger batches)
    resolved_scraper = []
    for item in scraper_items:
        raw_symbol = item.get("symbol") or item.get("company", "")
        symbol = _resolve_symbol(raw_symbol)
        published = _parse_dt(item.get("published_time"))
        if symbol and published:
            resolved_scraper.append({**item, "_symbol": symbol, "_published": published})

    matched_scraper_indices = set()

    for nse_item in nse_items:
        nse_symbol = _resolve_symbol(nse_item.get("symbol", ""))
        nse_published = _parse_dt(nse_item.get("published"))

        if not nse_symbol or nse_published is None:
            results.append(CorrelationResult(
                symbol=nse_symbol or nse_item.get("symbol", "UNKNOWN"),
                relationship="unmatched", hours_lead=None,
                matched_nse_item=nse_item, matched_scraper_item=None,
            ))
            continue

        best_match = None
        best_match_idx = None
        smallest_gap = None

        for idx, s_item in enumerate(resolved_scraper):
            if idx in matched_scraper_indices:
                continue
            if s_item["_symbol"] != nse_symbol:
                continue

            gap = abs((s_item["_published"] - nse_published).total_seconds()) / 3600
            if gap > window_hours:
                continue

            if smallest_gap is None or gap < smallest_gap:
                smallest_gap = gap
                best_match = s_item
                best_match_idx = idx

        if best_match is None:
            results.append(CorrelationResult(
                symbol=nse_symbol, relationship="unmatched", hours_lead=None,
                matched_nse_item=nse_item, matched_scraper_item=None,
            ))
            continue

        matched_scraper_indices.add(best_match_idx)
        lead_hours = (nse_published - best_match["_published"]).total_seconds() / 3600

        if lead_hours > 0:
            relationship = "news_led"   # scraper's timestamp is earlier
            hours_lead = round(lead_hours, 2)
        elif lead_hours < 0:
            relationship = "nse_led"    # NSE's timestamp is earlier
            hours_lead = round(abs(lead_hours), 2)
        else:
            relationship = "nse_led"    # simultaneous — NSE treated as authoritative anchor
            hours_lead = 0.0

        results.append(CorrelationResult(
            symbol=nse_symbol, relationship=relationship, hours_lead=hours_lead,
            matched_nse_item=nse_item, matched_scraper_item=best_match,
        ))

    # Scraper items that never matched any NSE item — logged separately.
    # These matter for your Google Drive archive (a scraper story might
    # never get an official NSE filing at all, e.g. brokerage commentary)
    # but they don't get a hours_lead since there's no NSE anchor.
    for idx, s_item in enumerate(resolved_scraper):
        if idx not in matched_scraper_indices:
            results.append(CorrelationResult(
                symbol=s_item["_symbol"], relationship="unmatched", hours_lead=None,
                matched_nse_item=None, matched_scraper_item=s_item,
            ))

    return results