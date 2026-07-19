"""

self_learning.py


Self-Learning Engine.

Checks alerts that have crossed the 1h / 24h / 48h checkpoints, fetches
actual price, determines HIT/MISS, and feeds that back into
category_accuracy so future alerts in the same category get a
recalibrated confidence bar.

Learning starts from zero on deployment day — no historical backfill.
"""
import yfinance as yf
from symbol_lookup import find_symbol

from sheet_prices import get_price_from_sheet

from db import (
    get_pending_price_checks, update_price_checkpoint,
    finalize_outcome, update_category_accuracy, get_conn,
)
from config import LEARNING_HIT_DEFINITION_PCT, LEARNING_MIN_SAMPLES, CONFIDENCE_ADJUST_STEP

from symbol_lookup import find_symbol

def get_current_price(company_name_or_symbol: str) -> float | None:
    """
    Fetch current price, preferring the Google Sheet (GOOGLEFINANCE) feed
    since it's more reliable for NSE symbols than yfinance. Falls back to
    yfinance only if the Sheet doesn't have the symbol or is unreachable.

    Accepts either a raw NSE symbol (e.g. "TCS") or a full company name
    (e.g. "Tata Consultancy Services Limited") — resolves company names
    to tickers via fuzzy lookup before checking either source.
    """
    symbol = company_name_or_symbol.strip().upper()

    # If this looks like a full company name rather than a short ticker,
    # resolve it first so both the Sheet and yfinance get a real symbol.
    if len(symbol.split()) > 1 or len(symbol) > 12:
        resolved = find_symbol(company_name_or_symbol)
        if resolved:
            symbol = resolved

    # 1. Try the Google Sheet feed first
    price = get_price_from_sheet(symbol)
    if price is not None:
        return price

    # 2. Fall back to yfinance with the resolved symbol
    price = _try_yfinance(symbol)
    if price is not None:
        return price

    # 3. Last resort: original input, unresolved, straight to yfinance
    #    (covers edge cases where fuzzy lookup picked the wrong match)
    if symbol != company_name_or_symbol:
        return _try_yfinance(company_name_or_symbol)

    return None


def _try_yfinance(nse_symbol: str) -> float | None:
    try:
        ticker = yf.Ticker(f"{nse_symbol}.NS")
        data = ticker.history(period="1d", interval="1m")
        if data.empty:
            return None
        return float(data["Close"].iloc[-1])
    except Exception as e:
        print(f"[learning] Price fetch failed for {nse_symbol}: {e}")
        return None
    

    
def check_and_update_outcomes():
    """Called periodically. Checks 1h/24h/48h price checkpoints for pending alerts."""
    for checkpoint, hours in [("1h", 1), ("24h", 24), ("48h", 48)]:
        pending = get_pending_price_checks(hours_elapsed_min=hours)
        for alert in pending:
            col = {"1h": alert["price_1h"], "24h": alert["price_24h"], "48h": alert["price_48h"]}[checkpoint]
            if col is not None:
                continue

            price = get_current_price(alert["symbol"])
            if price is None:
                continue
            update_price_checkpoint(alert["id"], checkpoint, price)
            print(f"[learning] {alert['symbol']} {checkpoint} price recorded: Rs.{price:.2f}")

            if checkpoint == "48h":
                _finalize(alert, price)


def _finalize(alert, price_48h: float):
    entry_price = alert["price_at_alert"]
    if not entry_price:
        return

    pct_move = ((price_48h - entry_price) / entry_price) * 100
    direction = alert["predicted_direction"]

    if direction == "UP":
        hit = pct_move >= LEARNING_HIT_DEFINITION_PCT
    elif direction == "DOWN":
        hit = pct_move <= -LEARNING_HIT_DEFINITION_PCT
    else:
        hit = abs(pct_move) < LEARNING_HIT_DEFINITION_PCT

    finalize_outcome(alert["id"], hit)
    update_category_accuracy(alert["category"], step=CONFIDENCE_ADJUST_STEP, min_samples=LEARNING_MIN_SAMPLES)
    print(f"[learning] {alert['symbol']} {alert['category']}: predicted {direction}, "
          f"actual {pct_move:+.2f}%, {'HIT' if hit else 'MISS'}")


def get_learning_report() -> str:
    """Human-readable snapshot of what the system has learned so far."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM category_accuracy ORDER BY total_alerts DESC"
        ).fetchall()
    if not rows:
        return "No learning data yet — system just deployed, gathering first outcomes."

    lines = ["Category Learning Report\n"]
    for r in rows:
        lines.append(
            f"{r['category']}: {r['hits']}/{r['total_alerts']} hits "
            f"({r['hit_rate']*100:.0f}%) | threshold: {r['current_confidence_threshold']:.0f}%"
        )
    return "\n".join(lines)