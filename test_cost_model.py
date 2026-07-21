# test_cost_model.py
from cost_model import calculate_net_return

# Example: a ₹100 stock, 100 shares, 3% gross target move
result = calculate_net_return(entry_price=100.0, exit_price=103.0, quantity=100)

print("=== Cost Model Test: 3% gross move, ₹10,000 position ===\n")
print(f"Gross P&L:          ₹{result.gross_pnl}")
print(f"Brokerage:           ₹{result.brokerage_total}")
print(f"STT:                 ₹{result.stt_total}")
print(f"Exchange charges:    ₹{result.exchange_charges}")
print(f"SEBI charges:        ₹{result.sebi_charges}")
print(f"GST:                 ₹{result.gst}")
print(f"Stamp duty:          ₹{result.stamp_duty}")
print(f"DP charge:           ₹{result.dp_charge}")
print(f"Total txn costs:     ₹{result.total_transaction_costs}")
print(f"Taxable gain:        ₹{result.taxable_gain}")
print(f"STCG tax (15% sur.): ₹{result.stcg_tax}")
print(f"NET P&L:             ₹{result.net_pnl}")
print(f"NET P&L %:           {result.net_pnl_pct}%")
print(f"Breakeven price:     ₹{result.breakeven_price}")

# Sanity checks
print("\n=== Sanity checks ===")
assert result.gross_pnl == 300.0, "Gross P&L should be exactly ₹300 (103-100)*100"
print("OK: gross_pnl correct")

assert result.net_pnl < result.gross_pnl, "Net must be less than gross after costs+tax"
print("OK: net_pnl < gross_pnl (costs/tax reduce return, as expected)")

assert result.breakeven_price > 100.0, "Breakeven must be above entry (costs exist)"
print("OK: breakeven_price > entry_price")

# Edge case: a loss-making trade shouldn't show negative tax
result_loss = calculate_net_return(entry_price=100.0, exit_price=98.0, quantity=100)
print(f"\n=== Loss scenario check ===")
print(f"Gross P&L: ₹{result_loss.gross_pnl}, Taxable gain: ₹{result_loss.taxable_gain}, Tax: ₹{result_loss.stcg_tax}")
assert result_loss.taxable_gain == 0.0, "No tax should apply on a loss"
assert result_loss.stcg_tax == 0.0, "Tax must be zero when there's no gain"
print("OK: loss scenario correctly shows zero taxable gain and zero tax")

print("\n=== All checks passed ===")