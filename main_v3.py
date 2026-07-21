"""
main_v3.py

Production orchestrator v3 — same cycle for NSE + scraper polling,
correlation, filtering (main-board + SME universe with multibagger
scoring), GPT analysis with correlation-based confidence bump,
Research Agent (sector/mcap_tier/SWOT, conditional on HIGH/CRITICAL
priority), decision, trade spec (net of costs + tax), Trade Decision
Agent (GPT-5.4 + web search review of the numerical spec — determines
CASH_DELIVERY_MULTIDAY vs INTRADAY_SHORT_MIS vs NOT_TRADEABLE, adjusts
numbers accordingly, computes correct net % per mechanism), and REAL
Telegram delivery.

No timeout on the Trade Decision Agent call — per user decision, it's
allowed to take as long as it needs (observed 20-40+ seconds), accepting
the delay to other items in that poll cycle.

Run as a long-lived process:
    python main_v3.py

Press Ctrl+C to stop.

Do NOT run this alongside the old main.py at the same time — both would
poll NSE and could send duplicate alerts. Retire main.py once this has
been observed running cleanly.
"""
import csv
from datetime import datetime, timezone
from apscheduler.schedulers.blocking import BlockingScheduler

from config import POLL_INTERVAL_SECONDS, WATCHLIST_FILE, INSIDER_BUY_THRESHOLD_CR
from db import init_db, insert_alert, mark_whatsapp_sent, daily_summary, get_recent_scraper_items
from ingestion import poll_new_announcements, fetch_nse_rss_announcements
from rss_ingestion import poll_all_sources
from correlation_engine import correlate, MATCH_WINDOW_HOURS
from false_positive_filters import apply_filters
from agentic_analyzer import analyze_pdf_text, apply_correlation_bump, decide_alert
from company_research import get_company_research
from trade_spec import generate_trade_spec
from trade_decision_agent import review_trade_spec
from sheet_prices import get_stock_row
from alert_service import send_whatsapp_alert, send_daily_summary
from self_learning import check_and_update_outcomes, get_learning_report, get_current_price
from symbol_lookup import find_symbol


def find_symbol_safe(name_or_symbol: str) -> str:
    return find_symbol(name_or_symbol) or name_or_symbol


def load_watchlist() -> set:
    try:
        with open(WATCHLIST_FILE, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return {row["symbol"].strip().upper() for row in reader if row.get("symbol")}
    except FileNotFoundError:
        print(f"[main_v3] WARNING: {WATCHLIST_FILE} not found — universe filter disabled")
        return set()


WATCHLIST = load_watchlist()


def build_correlation_lookup(nse_items: list[dict]) -> dict:
    """Runs scraper polling (dedup-aware, cost-guarded via
    rss_ingestion.py's cache), then correlates fresh NSE items against
    a ROLLING window of cached scraper items (not just this cycle's
    fresh fetch) — this is what makes correlation work correctly even
    though dedup prevents re-returning already-seen scraper items."""
    poll_all_sources()  # side effect: extracts + caches any new items

    recent_scraper_items = get_recent_scraper_items(hours=MATCH_WINDOW_HOURS)
    scraper_adapted = [{**item, "published_time": item["published"]} for item in recent_scraper_items]

    results = correlate(nse_items, scraper_adapted)

    lookup = {}
    for r in results:
        if r.matched_nse_item and r.matched_nse_item.get("pdf_url"):
            lookup[r.matched_nse_item["pdf_url"]] = r

    news_led_count = sum(1 for r in lookup.values() if r.relationship == "news_led")
    print(f"[correlation] {len(lookup)} NSE items matched against "
          f"{len(recent_scraper_items)} cached scraper items ({MATCH_WINDOW_HOURS}h window), "
          f"{news_led_count} news_led")
    return lookup


def _process_single_item(item: dict, correlation_lookup: dict):
    """Processes exactly one NSE announcement through the full pipeline,
    isolated so one bad item can't take down the rest of the cycle."""
    symbol = item["symbol"]
    subject = item["subject"]
    pdf_text = item["pdf_text"]

    filt = apply_filters(subject, pdf_text[:500], symbol, WATCHLIST, INSIDER_BUY_THRESHOLD_CR)
    if filt.skip:
        print(f"[filter] SKIP {symbol}: {filt.reason}")
        return
    print(f"[filter] PASS {symbol}: {filt.reason}")

    signal = analyze_pdf_text(pdf_text, symbol_hint=symbol, subject_hint=subject)
    if signal is None:
        print(f"[main_v3] Analysis failed for {symbol}, skipping")
        return

    correlation_result = correlation_lookup.get(item["pdf_url"])
    signal = apply_correlation_bump(signal, correlation_result)
    if signal["news_led"]:
        print(f"[bump] {symbol}: {signal['confidence_bump_reason']}")

    if filt.force_priority:
        signal["_forced_priority"] = filt.force_priority

    decision = decide_alert(signal)
    if not decision["should_alert"]:
        print(f"[decision] NO ALERT {symbol}: {decision['reason']}")
        return

    priority = signal.get("_forced_priority") or decision["priority"]

    # Research Agent — conditional on priority, cached 30 days per symbol.
    # Feeds sector/mcap_tier (needed for future outcome bucketing) and a
    # SWOT snippet surfaced in the Telegram alert, and used as context
    # for the Trade Decision Agent below.
    research = None
    if priority in ("HIGH", "CRITICAL"):
        print(f"[research] {symbol}: priority={priority}, fetching company research...")
        research = get_company_research(symbol)
        if research:
            print(f"[research] {symbol}: sector={research.get('sector')}, "
                  f"mcap_tier={research.get('market_cap_tier')}")
        else:
            print(f"[research] {symbol}: research fetch failed, proceeding without it")

    current_price = get_current_price(symbol)
    sheet_row = get_stock_row(symbol) or get_stock_row(find_symbol_safe(symbol))
    spec = generate_trade_spec(signal, current_price, sheet_row)

    # Trade Decision Agent — reviews the numerical spec with GPT-5.4 +
    # web search. Determines execution mechanism (multi-day cash
    # delivery vs intraday short vs not tradeable), adjusts entry/
    # target/stop for the correct mechanism, and computes the correct
    # net % (delivery cost_model.py vs intraday_cost_model.py) based
    # on which mechanism applies. No timeout — allowed to take as long
    # as needed (observed 20-40+ seconds), per explicit decision.
    decision_review = None
    if spec is not None:
        print(f"[decision_agent] {symbol}: reviewing numerical spec with GPT-5.4...")
        decision_review = review_trade_spec(
            {**signal, "symbol": symbol}, spec, research,
            filt.sme_score if filt.is_sme else None, sheet_row,
        )
        if decision_review:
            print(f"[decision_agent] {symbol}: {decision_review['recommendation']} "
                  f"({decision_review.get('trade_mechanism')}) — "
                  f"{decision_review['execution_feasibility']}")
        else:
            print(f"[decision_agent] {symbol}: review failed, using numerical spec as-is")

    alert = {
        "symbol": symbol,
        "category": signal["category"],
        "acquisition_role": signal.get("acquisition_role", "NOT_APPLICABLE"),
        "sentiment": signal["sentiment"],
        "priority": priority,
        "confidence": signal["confidence"],
        "predicted_direction": signal["predicted_direction"],
        "rupee_amount_cr": signal.get("rupee_amount_cr", 0),
        "subject": subject,
        "summary": signal["summary"],
        "materiality_reasoning": signal.get("materiality_reasoning", ""),
        "pdf_source_url": item["pdf_url"],
        "announcement_time": item["published"],
        "price_at_alert": current_price,
        "trade_spec": spec,
        "news_led": signal.get("news_led", False),
        "hours_lead": signal.get("hours_lead"),
        "confidence_bump_reason": signal.get("confidence_bump_reason"),
        "is_sme": filt.is_sme,
        "sme_score": filt.sme_score,
        "sector": research.get("sector") if research else None,
        "mcap_tier": research.get("market_cap_tier") if research else None,
        "research_swot": research.get("swot") if research else None,
        "decision_review": decision_review,
    }

    alert_id = insert_alert(alert)
    sent = send_whatsapp_alert(alert)
    if sent:
        mark_whatsapp_sent(alert_id)

    print(f"[main_v3] ALERT SENT: {symbol} | {priority} | {signal['category']} | conf={signal['confidence']}")


def process_cycle():
    """One full poll -> correlate -> filter -> analyze -> decide -> research -> spec -> decision_agent -> alert cycle."""
    print(f"\n[{datetime.now(timezone.utc).isoformat()}] Polling for new announcements...")

    nse_raw_for_correlation = fetch_nse_rss_announcements(max_age_minutes=15)
    correlation_lookup = build_correlation_lookup(nse_raw_for_correlation)

    new_items = poll_new_announcements()
    print(f"[main_v3] {len(new_items)} new announcement(s) found (with PDF text extracted)")

    for item in new_items:
        try:
            _process_single_item(item, correlation_lookup)
        except Exception as e:
            print(f"[main_v3] Unexpected error processing {item.get('symbol', 'UNKNOWN')}: {e}")
            continue


def learning_cycle():
    print(f"\n[{datetime.now(timezone.utc).isoformat()}] Running self-learning price checks...")
    check_and_update_outcomes()


def morning_recap():
    summary = daily_summary()
    send_daily_summary(summary)
    print(get_learning_report())


def main():
    init_db()
    print("[main_v3] Database initialized")
    print(f"[main_v3] Watchlist loaded: {len(WATCHLIST)} symbols")

    scheduler = BlockingScheduler(timezone="Asia/Kolkata")

    scheduler.add_job(
        process_cycle, "interval", seconds=POLL_INTERVAL_SECONDS,
        id="poll_announcements", max_instances=1,
        misfire_grace_time=60,
    )

    scheduler.add_job(
        learning_cycle, "interval", minutes=15,
        id="learning_checkpoints", max_instances=1,
    )

    scheduler.add_job(
        morning_recap, "cron", hour=8, minute=0, id="morning_recap",
    )

    print("[main_v3] Scheduler started. Press Ctrl+C to stop.")
    print("[main_v3] WARNING: this sends REAL Telegram alerts. Do not run alongside main.py.")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        print("[main_v3] Shutting down.")


if __name__ == "__main__":
    main()