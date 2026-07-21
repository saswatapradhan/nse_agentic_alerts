"""
trade_decision_agent.py

Final reasoning layer on top of trade_spec.py's numerical calculation.
Reasons through which execution path actually applies for a retail
Kotak Neo cash-delivery account:

- CASH_DELIVERY_MULTIDAY: normal case, typically UP signals — the
  numerical spec (or an adjusted version) applies as-is. Net % is
  carried through from trade_spec.py's own cost_model.py calculation.
- INTRADAY_SHORT_MIS: typically DOWN signals — cannot carry a
  multi-day short in cash delivery, but CAN short intraday via
  MIS/Cover Order. Requires DIFFERENT entry/target/stop numbers
  (same-day move expectations are much smaller than a 5-10 day drift,
  and the position must be squared off by ~3:20pm regardless of
  target/stop being hit). Net % is computed fresh via
  intraday_cost_model.py, since intraday has different fees AND
  different tax treatment (speculative business income at slab rate,
  not flat 20% STCG) than delivery.
- NOT_TRADEABLE: genuinely no viable path (e.g. illiquid, circuit-
  limited, T2T-only segment restrictions, timing doesn't allow entry).

Not cached — tied to a specific point-in-time announcement + numeric
spec, no reuse across alerts.
"""
import json
from openai import OpenAI

from config import OPENAI_API_KEY
from intraday_cost_model import calculate_intraday_net_return

_client = None
DECISION_MODEL = "gpt-5.4"


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=OPENAI_API_KEY or "sk-not-set")
    return _client


DECISION_PROMPT_TEMPLATE = """You are the final review layer for a trading alert system, before it \
reaches a retail investor trading via Kotak Neo. Their account is a standard cash-delivery account: \
they can hold multi-day LONG positions normally, but CANNOT carry a short position overnight in the \
cash segment. They CAN short intraday via MIS/Cover Order, but that position must be squared off by \
~3:20pm the same day regardless of whether target or stop was hit.

A numerical model already computed a suggested spec from a hardcoded, research-cited multi-day \
reaction range — that range assumes a MULTI-DAY hold, which is only directly executable for UP/long \
signals. Your job is to determine which execution path actually applies here, and give the right \
numbers for THAT path — not just reject a DOWN signal outright, since intraday shorting is a real, \
usable path for those.

--- ANNOUNCEMENT CONTEXT ---
Symbol: {symbol}
Category: {category}
Sentiment: {sentiment}
Predicted direction: {direction}
GPT confidence: {confidence}%
Materiality reasoning: {materiality_reasoning}
News-led timing bump: {news_led_info}

--- NUMERICAL MULTI-DAY SPEC (already computed, this is the LONG/multi-day version only) ---
Entry: ₹{entry_price}
Target: ₹{target_price} (gross {target_pct}%)
Stop: ₹{stop_price} ({stop_pct}% risk)
Holding period: {holding_period_days} days
Risk:Reward: {risk_reward_ratio}
Net % after Kotak Neo delivery costs + STCG: {net_target_pct}%
Basis: {range_basis}

--- ADDITIONAL CONTEXT (may be partial/unavailable) ---
Sector: {sector}
Market cap tier: {mcap_tier}
Company SWOT (if available): {swot_summary}
SME multibagger score (if applicable): {sme_score_info}
Recent price momentum (weekly %, if available): {weekly_momentum}

Search the web for anything current and material the numerical model couldn't have known — recent \
news, sector conditions, analyst commentary, trading segment restrictions (e.g. T2T/BE segment, \
which blocks intraday trading entirely), or liquidity concerns.

Determine trade_mechanism:
- CASH_DELIVERY_MULTIDAY: if this is a genuine multi-day-hold-appropriate LONG opportunity
- INTRADAY_SHORT_MIS: if this is a DOWN signal AND the stock is liquid enough AND not T2T/BE-\
  restricted — give intraday-appropriate entry/target/stop (same-day moves are typically much \
  smaller than a multi-day drift; target should reflect a realistic SAME-SESSION move, not the \
  multi-day gross % above)
- NOT_TRADEABLE: if genuinely no path exists (T2T/BE segment blocks intraday, stock too illiquid, \
  or timing doesn't allow safe entry)

If INTRADAY_SHORT_MIS, explicitly note in your reasoning that this involves MIS/Cover Order \
leverage, requires active monitoring during market hours, and must be squared off by ~3:20pm — \
this is meaningfully higher risk than a multi-day cash position and the user should know that.

Respond with ONLY a JSON object, no markdown fences, no preamble:
{{
  "trade_mechanism": "CASH_DELIVERY_MULTIDAY" or "INTRADAY_SHORT_MIS" or "NOT_TRADEABLE",
  "recommendation": "CONFIRM" or "ADJUST" or "DO_NOT_TRADE",
  "execution_feasibility": "brief note on the mechanism and why",
  "adjusted_entry": number or null,
  "adjusted_target": number or null,
  "adjusted_stop": number or null,
  "adjusted_holding_days": "string or null (e.g. 'intraday, square off by 3:20pm')",
  "intraday_risk_note": "string or null - ONLY populate if trade_mechanism is INTRADAY_SHORT_MIS, "
                          "explaining the leverage/monitoring/same-day-squareoff risk plainly",
  "reasoning": "2-3 sentences citing SPECIFIC current findings from web search, not generic restatement",
  "confidence_in_recommendation": "HIGH" or "MEDIUM" or "LOW"
}}"""


def _attach_net_return(decision: dict, spec: dict, quantity: int = 100) -> dict:
    """
    Computes and attaches the correct net % based on trade_mechanism.

    CASH_DELIVERY_MULTIDAY: spec['net_target_pct'] is already correct
    (computed by trade_spec.py via cost_model.py, delivery fees +
    flat 20% STCG) — just carry it through as-is.

    INTRADAY_SHORT_MIS: computed FRESH here using
    intraday_cost_model.py, on the ADJUSTED entry/target GPT returned
    (these are different numbers than the original multi-day spec,
    and intraday has different fees AND different tax treatment —
    speculative business income at slab rate, not flat STCG).

    NOT_TRADEABLE: no net return applicable.
    """
    mechanism = decision.get("trade_mechanism")

    if mechanism == "CASH_DELIVERY_MULTIDAY":
        decision["net_pct"] = spec.get("net_target_pct")
        decision["net_pct_source"] = "delivery (cost_model.py)"

    elif mechanism == "INTRADAY_SHORT_MIS":
        entry = decision.get("adjusted_entry") or spec["entry_price"]
        target = decision.get("adjusted_target") or spec["target_price"]
        try:
            intraday_result = calculate_intraday_net_return(
                entry_price=entry, exit_price=target, quantity=quantity, is_short=True,
            )
            decision["net_pct"] = intraday_result.net_pnl_pct
            decision["net_pct_source"] = (
                "intraday short (intraday_cost_model.py, speculative business income tax)"
            )
        except Exception as e:
            print(f"[trade_decision_agent] Intraday cost calc failed: {e}")
            decision["net_pct"] = None
            decision["net_pct_source"] = "calculation failed"

    else:  # NOT_TRADEABLE
        decision["net_pct"] = None
        decision["net_pct_source"] = "N/A — not tradeable"

    return decision


def review_trade_spec(signal: dict, spec: dict, research: dict | None,
                       sme_score: dict | None, sheet_row: dict | None) -> dict | None:
    """
    Main entry point. Returns the decision dict (with net_pct/
    net_pct_source attached), or None on failure — caller should fall
    back to the numerical spec as-is if this fails, since a failed
    review shouldn't block an alert that already passed every other
    gate.
    """
    news_led_info = "N/A"
    if signal.get("news_led"):
        news_led_info = signal.get("confidence_bump_reason", "news_led=True")

    swot_summary = "Not available"
    if research and research.get("swot"):
        swot = research["swot"]
        parts = []
        if swot.get("strengths"):
            parts.append(f"Strength: {swot['strengths'][0]}")
        if swot.get("threats"):
            parts.append(f"Threat: {swot['threats'][0]}")
        if parts:
            swot_summary = " | ".join(parts)

    sme_score_info = "N/A (not an SME stock)"
    if sme_score:
        sme_score_info = f"{sme_score['score']}/{sme_score['max_score']}"

    weekly_momentum = "Not available"
    if sheet_row and sheet_row.get("weekly_pct") is not None:
        weekly_momentum = f"{sheet_row['weekly_pct']:.1f}%"

    prompt = DECISION_PROMPT_TEMPLATE.format(
        symbol=signal.get("symbol", "UNKNOWN"),
        category=signal["category"],
        sentiment=signal["sentiment"],
        direction=signal["predicted_direction"],
        confidence=signal["confidence"],
        materiality_reasoning=signal.get("materiality_reasoning", ""),
        news_led_info=news_led_info,
        entry_price=spec["entry_price"],
        target_price=spec["target_price"],
        target_pct=spec["target_pct"],
        stop_price=spec["stop_price"],
        stop_pct=spec["stop_pct"],
        holding_period_days=spec["holding_period_days"],
        risk_reward_ratio=spec["risk_reward_ratio"],
        net_target_pct=spec["net_target_pct"],
        range_basis=spec["range_basis"],
        sector=research.get("sector") if research else "Not available",
        mcap_tier=research.get("market_cap_tier") if research else "Not available",
        swot_summary=swot_summary,
        sme_score_info=sme_score_info,
        weekly_momentum=weekly_momentum,
    )

    try:
        response = _get_client().responses.create(
            model=DECISION_MODEL,
            reasoning={"effort": "medium"},
            tools=[{"type": "web_search"}],
            input=prompt,
        )
        raw_text = response.output_text.strip()
        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]
        result = json.loads(raw_text)
        return _attach_net_return(result, spec)

    except Exception as e:
        print(f"[trade_decision_agent] Review failed for {signal.get('symbol')}: {e}")
        return None