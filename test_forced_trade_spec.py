"""
test_forced_trade_spec.py

Forces a fake high-confidence signal through decide_alert() -> price
fetch -> generate_trade_spec() -> alert_service.format_alert_message(),
to visually confirm the full downstream path renders correctly on a
REAL current price, without needing to wait for a live item to
naturally clear all the upstream filters.

No GPT call made here — signal is hand-constructed. This only proves
the plumbing from decision onward; analyze_pdf_text() and the filter
stage are already separately proven in main_v2.py's live runs.
"""
from db import init_db
from agentic_analyzer import decide_alert
from trade_spec import generate_trade_spec
from sheet_prices import get_stock_row
from self_learning import get_current_price
from symbol_lookup import find_symbol
from alert_service import format_alert_message

init_db()


def find_symbol_safe(name_or_symbol: str) -> str:
    return find_symbol(name_or_symbol) or name_or_symbol


# A deliberately high-confidence, clean RESULTS signal — should sail
# through decide_alert() regardless of learned thresholds (60 default,
# and 85 confidence clears any realistic threshold).
fake_signal = {
    "symbol": "RELIANCE",
    "category": "RESULTS",
    "acquisition_role": "NOT_APPLICABLE",
    "sentiment": "POSITIVE",
    "predicted_direction": "UP",
    "confidence": 85,
    "rupee_amount_cr": 0,
    "materiality_reasoning": "TEST INJECTION: explicit large earnings beat with raised guidance.",
    "summary": "TEST INJECTION — not a real filing. Verifying trade spec pipeline end to end.",
    "is_false_positive": False,
    # These three normally get set by apply_correlation_bump(); setting
    # them directly here since we're skipping that stage on purpose.
    "news_led": False,
    "hours_lead": None,
    "confidence_bump_reason": None,
}

print("=== Forced trade spec pipeline test ===\n")

print("[DECISION] Testing decide_alert() with fake high-confidence signal...")
decision = decide_alert(fake_signal)
print(f"[DECISION] should_alert={decision['should_alert']}, "
      f"priority={decision.get('priority')}, reason={decision['reason']}")

if not decision["should_alert"]:
    print("\n[FAIL] Even a hand-crafted 85-confidence RESULTS signal didn't clear "
          "decide_alert() — something is wrong with decide_alert() or the learned "
          "threshold for RESULTS is unexpectedly high. Investigate before proceeding.")
else:
    priority = decision["priority"]

    print("\n[PRICE] Fetching REAL current price for RELIANCE...")
    current_price = get_current_price("RELIANCE")
    if current_price is None:
        print("[FAIL] Could not fetch a real price for RELIANCE — check sheet_prices.py "
              "/ Google Sheet connectivity before proceeding.")
    else:
        print(f"[PRICE] Current: Rs.{current_price}")

        sheet_row = get_stock_row("RELIANCE") or get_stock_row(find_symbol_safe("RELIANCE"))
        print(f"[SHEET] Row found: {sheet_row is not None}")

        print("\n[SPEC] Generating trade spec...")
        spec = generate_trade_spec(fake_signal, current_price, sheet_row)

        if spec is None:
            print("[FAIL] generate_trade_spec() returned None for a RESULTS/POSITIVE/UP "
                  "signal — this category+direction should always produce a spec. Check "
                  "REACTION_RANGES and _get_range() in trade_spec.py.")
        else:
            print("[SPEC] Generated successfully:")
            print(f"    Entry:  Rs.{spec['entry_price']}")
            print(f"    Target: Rs.{spec['target_price']} "
                  f"(gross {spec['target_pct']:+.1f}%, NET {spec['net_target_pct']:+.2f}%)")
            print(f"    Stop:   Rs.{spec['stop_price']} ({spec['stop_pct']:.1f}% risk)")
            print(f"    Net worthwhile: {spec['net_worthwhile']}")
            print(f"    Breakeven: Rs.{spec['cost_breakdown']['breakeven_price']}")

            print("\n[ALERT] Building full alert dict + formatting Telegram message...")
            alert = {
                "symbol": fake_signal["symbol"],
                "category": fake_signal["category"],
                "acquisition_role": fake_signal["acquisition_role"],
                "sentiment": fake_signal["sentiment"],
                "priority": priority,
                "confidence": fake_signal["confidence"],
                "predicted_direction": fake_signal["predicted_direction"],
                "rupee_amount_cr": fake_signal["rupee_amount_cr"],
                "subject": "TEST INJECTION",
                "summary": fake_signal["summary"],
                "materiality_reasoning": fake_signal["materiality_reasoning"],
                "pdf_source_url": "TEST",
                "announcement_time": "TEST",
                "price_at_alert": current_price,
                "trade_spec": spec,
                "news_led": fake_signal["news_led"],
                "confidence_bump_reason": fake_signal["confidence_bump_reason"],
            }

            message = format_alert_message(alert)
            print("\n" + "=" * 60)
            print("RENDERED TELEGRAM MESSAGE (not sent, just printed):")
            print("=" * 60)
            print(message)
            print("=" * 60)

print("\n=== Test complete. No Telegram message was actually sent. ===")