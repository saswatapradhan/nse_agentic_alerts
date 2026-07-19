"""

trade_spec.py


Trade Specification Generator.

Converts a GPT signal + real live price/momentum data into a suggested
entry/target/stop-loss, using empirically-cited reaction ranges (from
NSE-focused research on dividends, buybacks, M&A, earnings, contract
wins, etc.) — NOT a fabricated multiplier chain. We deliberately do not
compute precision-looking multiplied percentages (e.g. base x D/E_mult
x ICR_mult x sector_mult) because we have no live fundamentals feed;
doing so would manufacture false confidence.

What's real here:
- Entry price: live, from the Google Sheet
- Target/stop range: cited empirical bands per announcement category
- Momentum check: real weekly/monthly % change from the Sheet, used to
  flag "already extended" moves — same logic as research's "avoid
  chasing if already up >2%" rule, but with real data instead of a guess
- Position sizing: fixed conservative risk convention (~1-1.5% risk per
  trade), not a fabricated formula

What's NOT real / not attempted:
- True ATR (needs 14 days of persisted daily ranges — we don't store this yet)
- Volume confirmation vs 20-day average (Sheet only gives today's snapshot)
- Fundamentals-driven adjustments (D/E, ICR, FCF — no data source for these)
"""

# (category, is_positive) -> (min_pct, max_pct, typical_pct, holding_days_min, holding_days_max)
# Ranges sourced from NSE-focused announcement-reaction research (dividend/
# buyback/rights/M&A/earnings studies). Categories not covered by solid
# research are intentionally excluded — no trade spec is generated for them.
REACTION_RANGES = {
    ("DIVIDEND", True):                    (1.5, 3.5, 2.5, 3, 5),
    ("DIVIDEND", False):                   (-4.5, -2.5, -3.5, 3, 5),
    ("BONUS_ISSUE", True):                 (0.8, 2.2, 1.5, 7, 10),
    ("BUYBACK", True):                     (1.8, 3.2, 2.5, 4, 7),
    ("RIGHTS_ISSUE", False):               (-3.8, -2.0, -2.9, 5, 7),
    ("RESULTS", True):                     (2.0, 5.0, 3.0, 5, 10),
    ("RESULTS", False):                    (-6.0, -3.0, -4.0, 5, 10),
    ("GUIDANCE_CHANGE", True):             (1.5, 4.0, 2.5, 5, 10),
    ("GUIDANCE_CHANGE", False):            (-6.0, -2.5, -3.5, 5, 10),
    ("CONTRACT_WIN", True):                (2.5, 4.5, 3.0, 4, 7),
    ("SEBI_ACTION", False):                (-2.0, -0.5, -1.2, 1, 3),
    ("CAPACITY_EXPANSION", True):          (1.5, 3.0, 2.0, 5, 10),
    ("LITIGATION", False):                 (-3.0, -1.0, -1.8, 5, 15),
    ("INSIDER_TRADE", True):               (1.0, 3.0, 1.8, 3, 7),
    ("RESTRUCTURING_DIVESTMENT", True):    (-1.0, 3.0, 0.5, 5, 15),  # genuinely ambiguous, wide range
    ("RESTRUCTURING_DIVESTMENT", False):   (-4.0, -1.0, -2.5, 5, 15),
    # ACQUISITION_OR_MERGER handled separately below (role-dependent)
}

ACQUISITION_RANGES = {
    "ACQUIRER": (-2.0, -0.5, -1.2, 5, 30),
    "TARGET":   (3.0, 8.0, 5.0, 5, 30),
}

# Categories where no trade spec is generated — informational alerts only.
# Either not tradeable in this style (delisting), too context-dependent to
# put a number on responsibly, or purely an alarm-setting signal.
NO_TRADE_SPEC_CATEGORIES = {
    "BOARD_MEETING_INTIMATION", "DELISTING_SUSPENSION", "RELATED_PARTY_TXN",
    "LEADERSHIP_CHANGE", "AUDITOR_ISSUE", "FRAUD_ALLEGATION", "OTHER_MATERIAL",
}

MAX_STOP_LOSS_PCT = 2.5   # hard cap on risk per trade, regardless of category
MIN_STOP_LOSS_PCT = 1.0
EXTENDED_MOVE_THRESHOLD_PCT = 8.0  # weekly move beyond which we flag "already extended"


def _get_range(category: str, sentiment: str, acquisition_role: str):
    if category == "ACQUISITION_OR_MERGER":
        return ACQUISITION_RANGES.get(acquisition_role)
    is_positive = sentiment == "POSITIVE"
    return REACTION_RANGES.get((category, is_positive))


def generate_trade_spec(signal: dict, current_price: float, sheet_row: dict | None) -> dict | None:
    """
    Returns a trade spec dict, or None if this category/direction combo
    doesn't have a responsible empirical basis to generate one.
    """
    category = signal["category"]
    sentiment = signal["sentiment"]
    direction = signal["predicted_direction"]
    role = signal.get("acquisition_role", "NOT_APPLICABLE")

    if category in NO_TRADE_SPEC_CATEGORIES or direction == "FLAT" or current_price is None:
        return None

    range_data = _get_range(category, sentiment, role)
    if range_data is None:
        return None

    min_pct, max_pct, typical_pct, hold_min, hold_max = range_data
    bullish = direction == "UP"

    # Momentum check — real data, not a guess
    caution_note = None
    if sheet_row and sheet_row.get("weekly_pct") is not None:
        weekly = sheet_row["weekly_pct"]
        if bullish and weekly >= EXTENDED_MOVE_THRESHOLD_PCT:
            caution_note = f"Already up {weekly:.1f}% this week — extended, consider waiting for a pullback"
            typical_pct = min_pct  # use conservative end of range
        elif not bullish and weekly <= -EXTENDED_MOVE_THRESHOLD_PCT:
            caution_note = f"Already down {weekly:.1f}% this week — extended, downside may be limited"
            typical_pct = max_pct  # least-negative end

    target_price = current_price * (1 + typical_pct / 100)

    # Conservative stop: half the range's lower magnitude, capped
    stop_pct = min(max(abs(min_pct) / 2, MIN_STOP_LOSS_PCT), MAX_STOP_LOSS_PCT)
    stop_price = current_price * (1 - stop_pct / 100) if bullish else current_price * (1 + stop_pct / 100)

    reward = abs(target_price - current_price)
    risk = abs(current_price - stop_price)
    risk_reward = round(reward / risk, 1) if risk > 0 else None

    return {
        "entry_price": round(current_price, 2),
        "target_price": round(target_price, 2),
        "target_pct": round(typical_pct, 1),
        "stop_price": round(stop_price, 2),
        "stop_pct": round(stop_pct, 1),
        "holding_period_days": f"{hold_min}-{hold_max}",
        "risk_reward_ratio": risk_reward,
        "caution_note": caution_note,
        "range_basis": f"{min_pct:+.1f}% to {max_pct:+.1f}% (cited research range)",
    }