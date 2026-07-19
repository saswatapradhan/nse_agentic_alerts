"""

main.py

Main Orchestrator — ties ingestion -> filtering -> agentic analysis ->
alerting -> self-learning into one scheduled loop.

Run this as a long-lived process:
    python main.py

Press Ctrl+C to stop.
"""
import csv
from datetime import datetime, timezone
from apscheduler.schedulers.blocking import BlockingScheduler

from config import POLL_INTERVAL_SECONDS, WATCHLIST_FILE, INSIDER_BUY_THRESHOLD_CR
from db import init_db, insert_alert, mark_whatsapp_sent, daily_summary
from ingestion import poll_new_announcements
from false_positive_filters import apply_filters
from agentic_analyzer import analyze_pdf_text, decide_alert
from alert_service import send_whatsapp_alert, send_daily_summary
from self_learning import check_and_update_outcomes, get_learning_report, get_current_price

def find_symbol_safe(name_or_symbol: str) -> str:
    from symbol_lookup import find_symbol
    return find_symbol(name_or_symbol) or name_or_symbol


def load_watchlist() -> set:
    """Load the Nifty 500 symbol set (just the ticker column) for the universe filter."""
    try:
        with open(WATCHLIST_FILE, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return {row["symbol"].strip().upper() for row in reader if row.get("symbol")}
    except FileNotFoundError:
        print(f"[main] WARNING: {WATCHLIST_FILE} not found — universe filter disabled (all symbols pass)")
        return set()


WATCHLIST = load_watchlist()


def _process_single_item(item: dict):
    """
    Process exactly one announcement through the full pipeline.
    Isolated into its own function so one bad/slow item (e.g. a 404,
    a malformed PDF, an unexpected API hiccup) can never take down
    the processing of every other item in the same poll cycle.
    """
    symbol = item["symbol"]
    subject = item["subject"]
    pdf_text = item["pdf_text"]

    # Stage 1: cheap keyword filters
    filt = apply_filters(subject, pdf_text[:500], symbol, WATCHLIST, INSIDER_BUY_THRESHOLD_CR)
    if filt.skip:
        print(f"[filter] SKIP {symbol}: {filt.reason}")
        return
    print(f"[filter] PASS {symbol}: {filt.reason}")

    # Stage 2: agentic GPT analysis
    signal = analyze_pdf_text(pdf_text, symbol_hint=symbol, subject_hint=subject)
    if signal is None:
        print(f"[main] Analysis failed for {symbol}, skipping")
        return

    if filt.force_priority:
        signal["_forced_priority"] = filt.force_priority

    decision = decide_alert(signal)
    if not decision["should_alert"]:
        print(f"[decision] NO ALERT {symbol}: {decision['reason']}")
        print(f"GPT reasoning: {signal.get('materiality_reasoning', 'none given')}")
        return

    priority = signal.get("_forced_priority") or decision["priority"]

    from sheet_prices import get_stock_row
    from trade_spec import generate_trade_spec

    current_price = get_current_price(symbol)
    sheet_row = get_stock_row(symbol) or get_stock_row(find_symbol_safe(symbol))
    spec = generate_trade_spec(signal, current_price, sheet_row)


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
    }

    alert_id = insert_alert(alert)
    sent = send_whatsapp_alert(alert)
    if sent:
        mark_whatsapp_sent(alert_id)

    print(f"[main] ALERT SENT: {symbol} | {priority} | {signal['category']} | conf={signal['confidence']}")


def process_cycle():
    """One full poll -> filter -> analyze -> alert cycle."""
    print(f"\n[{datetime.now(timezone.utc).isoformat()}] Polling for new announcements...")
    new_items = poll_new_announcements()
    print(f"[main] {len(new_items)} new announcement(s) found")

    for item in new_items:
        try:
            _process_single_item(item)
        except Exception as e:
            print(f"[main] Unexpected error processing {item.get('symbol', 'UNKNOWN')}: {e}")
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
    print("[main] Database initialized")
    print(f"[main] Watchlist loaded: {len(WATCHLIST)} symbols")

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

    print("[main] Scheduler started. Press Ctrl+C to stop.")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        print("[main] Shutting down.")


if __name__ == "__main__":
    main()