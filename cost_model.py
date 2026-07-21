"""
cost_model.py

Transaction cost + tax model for Kotak Neo (Trade Free plan) delivery
trades. Computes true net return after brokerage, STT, exchange/SEBI
charges, GST, stamp duty, DP charges, and STCG (20% + surcharge + cess).

Rates current as of FY 2025-26 (verified July 2026). Broker/exchange
fees change periodically — re-verify against your actual Kotak Neo
contract note if this hasn't been checked in a few months.
"""
from dataclasses import dataclass

# ── Kotak Neo Trade Free Plan — Delivery ──────────────────────────────
BROKERAGE_PCT = 0.0025          # 0.25% or flat min, whichever higher
BROKERAGE_MIN = 20.0            # ₹20 flat minimum per leg
STT_DELIVERY_PCT = 0.001        # 0.1% — charged on BOTH buy and sell legs
EXCHANGE_TXN_PCT_NSE = 0.0000325  # ₹3.25 per lakh
SEBI_CHARGES_PCT = 0.000002       # ₹20 per crore
GST_PCT = 0.18                    # on (brokerage + exchange + SEBI charges)
STAMP_DUTY_BUY_PCT = 0.00015      # 0.015% — buy side only (delivery, standard rate)
DP_CHARGE_FLAT = 20.0             # + GST, sell side only, per scrip per day

# ── Tax ─────────────────────────────────────────────────────────────
STCG_RATE = 0.20                  # flat, Section 111A, all your holding periods qualify
CESS_RATE = 0.04                  # Health & Education Cess, on tax + surcharge


@dataclass
class CostBreakdown:
    gross_pnl: float
    brokerage_total: float
    stt_total: float
    exchange_charges: float
    sebi_charges: float
    gst: float
    stamp_duty: float
    dp_charge: float
    total_transaction_costs: float
    taxable_gain: float
    stcg_tax: float
    net_pnl: float
    net_pnl_pct: float
    breakeven_price: float


def _leg_costs(value: float, is_buy: bool) -> dict:
    brokerage = max(value * BROKERAGE_PCT, BROKERAGE_MIN)
    stt = value * STT_DELIVERY_PCT  # both legs, delivery
    exchange = value * EXCHANGE_TXN_PCT_NSE
    sebi = value * SEBI_CHARGES_PCT
    gst = (brokerage + exchange + sebi) * GST_PCT
    stamp = value * STAMP_DUTY_BUY_PCT if is_buy else 0.0
    return {"brokerage": brokerage, "stt": stt, "exchange": exchange,
            "sebi": sebi, "gst": gst, "stamp": stamp}


def calculate_net_return(
    entry_price: float, exit_price: float, quantity: int,
    surcharge_pct: float = 0.15,  # placeholder per your earlier answer — update when confirmed
) -> CostBreakdown:
    buy_value = entry_price * quantity
    sell_value = exit_price * quantity
    gross_pnl = sell_value - buy_value

    buy_costs = _leg_costs(buy_value, is_buy=True)
    sell_costs = _leg_costs(sell_value, is_buy=False)
    dp_charge = (DP_CHARGE_FLAT * (1 + GST_PCT))  # sell side only, per scrip/day

    total_costs = (
        buy_costs["brokerage"] + sell_costs["brokerage"]
        + buy_costs["stt"] + sell_costs["stt"]
        + buy_costs["exchange"] + sell_costs["exchange"]
        + buy_costs["sebi"] + sell_costs["sebi"]
        + buy_costs["gst"] + sell_costs["gst"]
        + buy_costs["stamp"]  # buy side only
        + dp_charge
    )

    taxable_gain = max(0.0, gross_pnl - total_costs)  # tax applies to net gain after costs, not gross
    effective_tax_rate = STCG_RATE * (1 + surcharge_pct) * (1 + CESS_RATE)
    stcg_tax = taxable_gain * effective_tax_rate

    net_pnl = gross_pnl - total_costs - stcg_tax
    net_pnl_pct = (net_pnl / buy_value) * 100 if buy_value else 0.0

    cost_pct_of_value = total_costs / buy_value if buy_value else 0
    breakeven_price = entry_price * (1 + cost_pct_of_value)

    return CostBreakdown(
        gross_pnl=round(gross_pnl, 2),
        brokerage_total=round(buy_costs["brokerage"] + sell_costs["brokerage"], 2),
        stt_total=round(buy_costs["stt"] + sell_costs["stt"], 2),
        exchange_charges=round(buy_costs["exchange"] + sell_costs["exchange"], 2),
        sebi_charges=round(buy_costs["sebi"] + sell_costs["sebi"], 2),
        gst=round(buy_costs["gst"] + sell_costs["gst"], 2),
        stamp_duty=round(buy_costs["stamp"], 2),
        dp_charge=round(dp_charge, 2),
        total_transaction_costs=round(total_costs, 2),
        taxable_gain=round(taxable_gain, 2),
        stcg_tax=round(stcg_tax, 2),
        net_pnl=round(net_pnl, 2),
        net_pnl_pct=round(net_pnl_pct, 2),
        breakeven_price=round(breakeven_price, 2),
    )