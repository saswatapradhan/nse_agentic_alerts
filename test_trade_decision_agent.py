# test_trade_decision_agent.py (same as before, re-run against the updated module)
from trade_decision_agent import review_trade_spec

signal = {
    "symbol": "CSM",
    "category": "RESULTS",
    "sentiment": "NEGATIVE",
    "predicted_direction": "DOWN",
    "confidence": 80,
    "materiality_reasoning": "Auditor's report notes operational losses and material uncertainty regarding going concern for subsidiaries.",
    "news_led": False,
}

spec = {
    "entry_price": 99.57,
    "target_price": 95.59,
    "target_pct": -4.0,
    "stop_price": 102.06,
    "stop_pct": 2.5,
    "holding_period_days": "5-10",
    "risk_reward_ratio": 1.6,
    "net_target_pct": -5.03,
    "range_basis": "-6.0% to -3.0% (cited research range)",
}

print("=== Re-testing with intraday-aware decision agent ===\n")
result = review_trade_spec(signal, spec, research=None, sme_score=None, sheet_row=None)

if result is None:
    print("[FAIL] review_trade_spec returned None")
else:
    import json
    print(json.dumps(result, indent=2))