# test_intraday_cost_model.py
from intraday_cost_model import calculate_intraday_net_return

print("=== CSM Technologies intraday SHORT: sell 99.57, cover 98.08 ===\n")
result = calculate_intraday_net_return(
    entry_price=99.57, exit_price=98.08, quantity=100, is_short=True,
)
print(f"Gross P&L:          ₹{result.gross_pnl}")
print(f"Brokerage:           ₹{result.brokerage_total}")
print(f"STT (sell-side only):₹{result.stt_total}")
print(f"Exchange charges:    ₹{result.exchange_charges}")
print(f"SEBI charges:        ₹{result.sebi_charges}")
print(f"GST:                 ₹{result.gst}")
print(f"Stamp duty:          ₹{result.stamp_duty}")
print(f"Total txn costs:     ₹{result.total_transaction_costs}")
print(f"Taxable gain:        ₹{result.taxable_gain}")
print(f"Speculative tax:     ₹{result.speculative_tax}")
print(f"NET P&L:             ₹{result.net_pnl}")
print(f"NET P&L %:           {result.net_pnl_pct}%")
print(f"Breakeven cover price: ₹{result.breakeven_price}")

# Sanity checks
assert result.gross_pnl > 0, "Short profiting from a price DROP should show positive gross"
print("\nOK: gross_pnl positive for a successful short (price dropped)")
assert result.net_pnl < result.gross_pnl, "Net must be less than gross after costs+tax"
print("OK: net_pnl < gross_pnl")
assert result.breakeven_price < 99.57, "Breakeven cover price must be BELOW entry for a short"
print("OK: breakeven_price correctly below entry (short needs price to drop enough to cover costs)")

print("\n=== Comparison: delivery model would have shown ===")
from cost_model import calculate_net_return
delivery_result = calculate_net_return(entry_price=99.57, exit_price=95.59, quantity=100)
print(f"Delivery (wrong instrument for this case) NET: {delivery_result.net_pnl_pct}%")
print(f"Intraday (correct instrument) NET: {result.net_pnl_pct}%")