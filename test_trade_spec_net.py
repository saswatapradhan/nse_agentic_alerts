# test_trade_spec_net.py
from trade_spec import generate_trade_spec

test_cases = [
    # (label, signal, current_price)
    ("DIVIDEND positive - small magnitude, likely marginal", {
        "category": "DIVIDEND", "sentiment": "POSITIVE",
        "predicted_direction": "UP", "acquisition_role": "NOT_APPLICABLE",
    }, 500.0),
    ("RESULTS positive - larger magnitude, should be clearly worthwhile", {
        "category": "RESULTS", "sentiment": "POSITIVE",
        "predicted_direction": "UP", "acquisition_role": "NOT_APPLICABLE",
    }, 500.0),
    ("BONUS_ISSUE - smallest magnitude in the whole table", {
        "category": "BONUS_ISSUE", "sentiment": "POSITIVE",
        "predicted_direction": "UP", "acquisition_role": "NOT_APPLICABLE",
    }, 500.0),
]

for label, signal, price in test_cases:
    spec = generate_trade_spec(signal, price, sheet_row=None)
    print(f"\n=== {label} ===")
    if spec is None:
        print("No spec generated (category/direction not covered)")
        continue
    print(f"Gross target: {spec['target_pct']}%")
    print(f"Net target:   {spec['net_target_pct']}%")
    print(f"Worthwhile:   {spec['net_worthwhile']}")
    print(f"Breakeven price: {spec['cost_breakdown']['breakeven_price']}")
    print(f"Total costs+tax: {spec['cost_breakdown']['total_transaction_costs'] + spec['cost_breakdown']['stcg_tax']:.2f}")