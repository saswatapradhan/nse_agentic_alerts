"""
main_v2.py

Integration smoke test — proves NSE ingestion + scraper ingestion +
correlation_engine.py + agentic_analyzer.py (with correlation bump) +
trade_spec.py (with cost_model.py net returns) work together on LIVE
data, end to end.

Still does NOT send real Telegram alerts — that's the next integration
step after this is confirmed working. This script prints what WOULD be
sent, including the full net-of-cost/tax trade spec.

COST WARNING: each item processed makes 1 real GPT call (gpt-4o-mini)
via analyze_pdf_text(). max_items caps this — raise cautiously.
"""
import csv

from ingestion import fetch_nse_rss_announcements, poll_new_announcements
from rss_ingestion import poll_all_sources
from correlation_engine import correlate
from false_positive_filters import apply_filters
from agentic_analyzer import analyze_pdf_text, apply_correlation_bump, decide_alert
from trade_spec import generate_trade_spec
from sheet_prices import get_stock_row
from self_learning import get_current_price
from symbol_lookup import find_symbol
from db import init_db
from config import WATCHLIST_FILE, INSIDER_BUY_THRESHOLD_CR


def load_watchlist() -> set:
    try:
        with open(WATCHLIST_FILE, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return {row["symbol"].strip().upper() for row in reader if row.get("symbol")}
    except FileNotFoundError:
        print(f"WARNING: {WATCHLIST_FILE} not found — universe filter disabled")
        return set()


def find_symbol_safe(name_or_symbol: str) -> str:
    return find_symbol(name_or_symbol) or name_or_symbol


def build_correlation_lookup() -> dict:
    """Fetches NSE + scraper items fresh, correlates them, returns a
    dict keyed by pdf_url -> CorrelationResult, for lookup during the
    main processing loop (which uses poll_new_announcements()'s
    separate dedup-aware fetch)."""
    print("=== Building correlation lookup ===")
    nse_raw = fetch_nse_rss_announcements(max_age_minutes=1440)
    scraper_raw = poll_all_sources(max_age_minutes=1440)
    scraper_adapted = [{**item, "published_time": item["published"]} for item in scraper_raw]

    results = correlate(nse_raw, scraper_adapted)

    lookup = {}
    for r in results:
        if r.matched_nse_item and r.matched_nse_item.get("pdf_url"):
            lookup[r.matched_nse_item["pdf_url"]] = r

    news_led_count = sum(1 for r in lookup.values() if r.relationship == "news_led")
    print(f"Correlation lookup built: {len(lookup)} NSE items have a scraper match, "
          f"{news_led_count} are news_led\n")
    return lookup


def print_trade_spec(spec: dict):
    """Pretty-prints a trade spec dict, highlighting net vs gross."""
    print(f"    Entry:  Rs.{spec['entry_price']}")
    print(f"    Target: Rs.{spec['target_price']} (gross {spec['target_pct']:+.1f}%, "
          f"NET {spec['net_target_pct']:+.2f}% after costs+tax)")
    print(f"    Stop:   Rs.{spec['stop_price']} ({spec['stop_pct']:.1f}% risk)")
    print(f"    Hold:   {spec['holding_period_days']} days")
    print(f"    R:R:    {spec['risk_reward_ratio']}")
    print(f"    Breakeven price: Rs.{spec['cost_breakdown']['breakeven_price']}")
    print(f"    Total costs+tax: Rs.{spec['cost_breakdown']['total_transaction_costs'] + spec['cost_breakdown']['stcg_tax']:.2f}")
    if spec['net_worthwhile']:
        print(f"    >>> NET WORTHWHILE (net target >= {0.5}% floor)")
    else:
        print(f"    >>> MARGINAL/NOT WORTHWHILE — net target below the worthwhile floor")
    if spec.get("caution_note"):
        print(f"    Caution: {spec['caution_note']}")


def run_smoke_test(max_items: int = 5):
    init_db()
    watchlist = load_watchlist()
    correlation_lookup = build_correlation_lookup()

    print(f"=== Fetching + processing up to {max_items} NEW items (with PDF text) ===")
    new_items = poll_new_announcements()
    print(f"poll_new_announcements returned {len(new_items)} new items total\n")

    items_to_process = new_items[:max_items]
    print(f"Processing {len(items_to_process)} (capped at max_items={max_items})\n")

    for i, item in enumerate(items_to_process):
        print(f"\n{'='*60}")
        print(f"Item {i+1}/{len(items_to_process)}: {item['symbol']}")
        print(f"{'='*60}")

        correlation_result = correlation_lookup.get(item["pdf_url"])
        if correlation_result:
            print(f"Correlation: {correlation_result.relationship}, "
                  f"hours_lead={correlation_result.hours_lead}")
        else:
            print("Correlation: no scraper match found for this item")

        filt = apply_filters(item["subject"], item["pdf_text"][:500],
                              item["symbol"], watchlist, INSIDER_BUY_THRESHOLD_CR)
        if filt.skip:
            print(f"[FILTER] SKIP: {filt.reason}")
            continue
        print(f"[FILTER] PASS: {filt.reason}")

        print("[GPT] Calling analyze_pdf_text (real API call)...")
        signal = analyze_pdf_text(item["pdf_text"], symbol_hint=item["symbol"],
                                    subject_hint=item["subject"])
        if signal is None:
            print("[GPT] Analysis failed")
            continue

        print(f"[GPT] category={signal['category']}, confidence={signal['confidence']} (pre-bump)")

        signal = apply_correlation_bump(signal, correlation_result)
        if signal["news_led"]:
            print(f"[BUMP] Applied: confidence now {signal['confidence']}, "
                  f"reason: {signal['confidence_bump_reason']}")
        else:
            print(f"[BUMP] Not applied (no news_led match or below threshold)")

        if filt.force_priority:
            signal["_forced_priority"] = filt.force_priority

        decision = decide_alert(signal)
        print(f"[DECISION] should_alert={decision['should_alert']}, reason={decision['reason']}")

        if not decision["should_alert"]:
            continue

        priority = signal.get("_forced_priority") or decision["priority"]
        print(f"[DECISION] priority={priority}")

        print("[PRICE] Fetching current price...")
        current_price = get_current_price(item["symbol"])
        if current_price is None:
            print("[PRICE] Could not fetch current price — skipping trade spec")
            continue
        print(f"[PRICE] Current: Rs.{current_price}")

        sheet_row = get_stock_row(item["symbol"]) or get_stock_row(find_symbol_safe(item["symbol"]))

        spec = generate_trade_spec(signal, current_price, sheet_row)
        if spec is None:
            print(f"[SPEC] No trade spec generated for category={signal['category']} "
                  f"(informational-only category or FLAT direction)")
            continue

        print("[SPEC] Trade spec generated:")
        print_trade_spec(spec)

    print(f"\n{'='*60}")
    print("Smoke test complete. No alerts were sent to Telegram —")
    print("this validates ingestion -> correlation -> analysis -> decision -> trade spec.")
    print(f"{'='*60}")


if __name__ == "__main__":
    run_smoke_test(max_items=5)