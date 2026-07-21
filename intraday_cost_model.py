"""
intraday_cost_model.py

Cost + tax model for Kotak Neo INTRADAY equity trades (MIS/Cover
Order) — separate from cost_model.py's delivery-only model, because
intraday differs in two structurally important ways:

1. FEES: brokerage is min(₹10, 0.05% of value) per leg — LOWER of the
   two, opposite of delivery's "higher of 0.25%/₹20". STT is zero on
   the buy side, charged only on sell. No DP charges (delivery-only).

2. TAX (the bigger difference): intraday equity trades are NOT capital
   gains — under Indian tax law they're SPECULATIVE BUSINESS INCOME,
   taxed at your income slab rate, not the flat 20% STCG rate delivery
   trades get. This is a materially different (usually higher, for
   anyone above the 20% slab) tax treatment. Speculative losses can
   also only be set off against speculative gains, not other income —
   not modeled here (this function only computes the cost of a single
   trade, not portfolio-level loss offsetting).

Rates current as of mid-2026, sourced from Kotak Neo's own pricing
page and cross-referenced against independent brokerage-calculator
sites. Re-verify periodically — broker fee structures change.
"""
from dataclasses import dataclass

# ── Kotak Neo Trade Free Plan — Intraday (post 30-day free period) ───
BROKERAGE_FLAT = 10.0             # ₹10 per order...
BROKERAGE_PCT = 0.0005            # ...or 0.05% of value, WHICHEVER IS LOWER
STT_INTRADAY_SELL_PCT = 0.00025   # 0.025% — SELL SIDE ONLY, zero on buy
EXCHANGE_TXN_PCT_NSE = 0.0000325  # ₹3.25 per lakh — same as delivery
SEBI_CHARGES_PCT = 0.000002       # ₹20 per crore — same as delivery, confirmed
                                    # unchanged across segments by Kotak's own docs
GST_PCT = 0.18                    # on (brokerage + exchange + SEBI charges)
STAMP_DUTY_BUY_PCT = 0.00003      # 0.003% — buy side only, intraday rate
                                    # (vs delivery's 0.015%, per Finance Act 2019
                                    # uniform stamp duty structure)
# No DP charges for intraday — delivery-only, confirmed.

# ── Tax — SPECULATIVE BUSINESS INCOME, not capital gains ──────────────
# Taxed at your income slab rate. Default below is a PLACEHOLDER
# assumption (30% slab + 15% surcharge + 4% cess) — same caveat as
# cost_model.py's STCG surcharge: confirm your actual slab and update.
DEFAULT_SLAB_RATE = 0.30
DEFAULT_SURCHARGE = 0.15
CESS_RATE = 0.04


@dataclass
class IntradayCostBreakdown:
    gross_pnl: float
    brokerage_total: float
    stt_total: float
    exchange_charges: float
    sebi_charges: float
    gst: float
    stamp_duty: float
    total_transaction_costs: float
    taxable_gain: float
    speculative_tax: float
    net_pnl: float
    net_pnl_pct: float
    breakeven_price: float


def _leg_costs(value: float, is_buy: bool) -> dict:
    brokerage = min(BROKERAGE_FLAT, value * BROKERAGE_PCT)  # LOWER, not higher
    stt = 0.0 if is_buy else value * STT_INTRADAY_SELL_PCT   # sell-side only
    exchange = value * EXCHANGE_TXN_PCT_NSE
    sebi = value * SEBI_CHARGES_PCT
    gst = (brokerage + exchange + sebi) * GST_PCT
    stamp = value * STAMP_DUTY_BUY_PCT if is_buy else 0.0
    return {"brokerage": brokerage, "stt": stt, "exchange": exchange,
            "sebi": sebi, "gst": gst, "stamp": stamp}


def calculate_intraday_net_return(
    entry_price: float, exit_price: float, quantity: int,
    is_short: bool = False,   # True for a short (sell first, buy back later)
    slab_rate: float = DEFAULT_SLAB_RATE,
    surcharge_pct: float = DEFAULT_SURCHARGE,
) -> IntradayCostBreakdown:
    """
    For a short (is_short=True): entry_price is the SELL (short) price,
    exit_price is the BUY-BACK (cover) price — gross profit when
    exit_price < entry_price, matching a DOWN-prediction intraday short.
    """
    if is_short:
        # Sell first at entry_price, buy back at exit_price
        sell_value = entry_price * quantity
        buy_value = exit_price * quantity
        gross_pnl = sell_value - buy_value
        first_leg_costs = _leg_costs(sell_value, is_buy=False)   # opening sell
        second_leg_costs = _leg_costs(buy_value, is_buy=True)    # closing buy
    else:
        buy_value = entry_price * quantity
        sell_value = exit_price * quantity
        gross_pnl = sell_value - buy_value
        first_leg_costs = _leg_costs(buy_value, is_buy=True)     # opening buy
        second_leg_costs = _leg_costs(sell_value, is_buy=False)  # closing sell

    total_costs = sum(first_leg_costs.values()) + sum(second_leg_costs.values())

    taxable_gain = max(0.0, gross_pnl - total_costs)
    effective_tax_rate = slab_rate * (1 + surcharge_pct) * (1 + CESS_RATE)
    speculative_tax = taxable_gain * effective_tax_rate

    net_pnl = gross_pnl - total_costs - speculative_tax
    reference_value = sell_value if is_short else buy_value
    net_pnl_pct = (net_pnl / reference_value) * 100 if reference_value else 0.0

    cost_pct_of_value = total_costs / reference_value if reference_value else 0
    if is_short:
        breakeven_price = entry_price * (1 - cost_pct_of_value)  # cover price below which you lose
    else:
        breakeven_price = entry_price * (1 + cost_pct_of_value)

    return IntradayCostBreakdown(
        gross_pnl=round(gross_pnl, 2),
        brokerage_total=round(first_leg_costs["brokerage"] + second_leg_costs["brokerage"], 2),
        stt_total=round(first_leg_costs["stt"] + second_leg_costs["stt"], 2),
        exchange_charges=round(first_leg_costs["exchange"] + second_leg_costs["exchange"], 2),
        sebi_charges=round(first_leg_costs["sebi"] + second_leg_costs["sebi"], 2),
        gst=round(first_leg_costs["gst"] + second_leg_costs["gst"], 2),
        stamp_duty=round(first_leg_costs["stamp"] + second_leg_costs["stamp"], 2),
        total_transaction_costs=round(total_costs, 2),
        taxable_gain=round(taxable_gain, 2),
        speculative_tax=round(speculative_tax, 2),
        net_pnl=round(net_pnl, 2),
        net_pnl_pct=round(net_pnl_pct, 2),
        breakeven_price=round(breakeven_price, 2),
    )