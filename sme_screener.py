"""
sme_screener.py

Two GPT-powered checks for NSE SME (Emerge) stocks:
1. check_sme_membership() — confirms whether a company is SME-listed
   and finds its ticker, via web search. Replaces needing a separate
   NSE Emerge master-list CSV (none found at a stable public URL,
   unlike the main board's EQUITY_L.csv) — GPT does this lookup
   directly instead.
2. get_multibagger_score() — scores a confirmed SME stock against 7
   researched criteria (market cap deliberately excluded — most SME
   IPOs raise far less than the ₹200Cr+ band that criterion assumes,
   per user decision). Returns a 0-7 score + per-criterion findings,
   NOT a pass/fail gate — user reviews the score themselves.

Both cached (membership indefinitely since it rarely changes;
multibagger score 30 days, financials/fundamentals move slowly).
"""
import json
from openai import OpenAI

from config import OPENAI_API_KEY
from db import (
    get_cached_sme_membership, cache_sme_membership,
    get_cached_multibagger_score, cache_multibagger_score,
)

_client = None
SCREENER_MODEL = "gpt-4.1"  # Responses API + web_search, same as company_research.py


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=OPENAI_API_KEY or "sk-not-set")
    return _client


# ── SME membership check ───────────────────────────────────────────

def check_sme_membership(raw_name: str) -> tuple[str | None, bool]:
    """Returns (sme_symbol_or_None, is_sme). Cached indefinitely per
    raw_name — SME listing status doesn't change day to day."""
    found, is_sme, symbol = get_cached_sme_membership(raw_name)
    if found:
        return symbol, is_sme

    prompt = f"""Is the company "{raw_name}" listed on the NSE Emerge (SME) platform in India \
(not the NSE main board)? Search to confirm. If yes, what is its NSE ticker symbol?

Respond with ONLY a JSON object, no markdown fences, no preamble:
{{"is_sme": true/false, "symbol": "TICKER" or null}}"""

    try:
        response = _get_client().responses.create(
            model=SCREENER_MODEL,
            tools=[{"type": "web_search"}],
            input=prompt,
        )
        raw_text = response.output_text.strip()
        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]
        data = json.loads(raw_text)
        is_sme = bool(data.get("is_sme"))
        symbol = data.get("symbol") if is_sme else None

        cache_sme_membership(raw_name, is_sme, symbol)
        return symbol, is_sme

    except Exception as e:
        print(f"[sme_screener] Membership check failed for '{raw_name}': {e}")
        return None, False  # NOT cached — transient failure, retry next time


# ── Multibagger scoring ─────────────────────────────────────────────

MULTIBAGGER_CRITERIA = [
    "revenue_cagr",       # >20% over 3-5 years, consistent
    "margin_trend",       # stable or improving alongside revenue growth
    "roce",                # >20% for 3 consecutive years
    "roe",                  # >20% for 3-5 consecutive years
    "debt_to_equity",      # <0.5
    "promoter_holding",    # >45%, zero pledging
    "peg_ratio",            # <1.0
]
MAX_SCORE = len(MULTIBAGGER_CRITERIA)

SCORING_PROMPT_TEMPLATE = """Research the Indian SME-listed company "{name}" (NSE symbol: {symbol}) \
and evaluate it against these 7 multibagger-potential criteria, based on established Indian \
equity research frameworks (Univest, Equitymaster, and similar):

1. revenue_cagr: Revenue CAGR >20% over the last 3-5 years, consistent (not a single spike quarter)
2. margin_trend: Operating margins stable or improving alongside revenue growth (not eroding)
3. roce: Return on Capital Employed >20% for at least 3 consecutive years
4. roe: Return on Equity >20% for 3-5 consecutive years
5. debt_to_equity: D/E ratio below 0.5
6. promoter_holding: Promoter holding above 45%, with zero share pledging
7. peg_ratio: PEG ratio (P/E ÷ earnings growth rate) below 1.0

SME companies often have thin public data coverage — if a criterion genuinely cannot be verified \
via available sources, mark it "UNVERIFIABLE" rather than guessing. Be honest about data \
limitations; do not fabricate precise-looking numbers you can't actually find.

Respond with ONLY a JSON object, no markdown fences, no preamble:
{{
  "revenue_cagr": {{"meets_criterion": true/false/"UNVERIFIABLE", "finding": "brief note with actual number if found"}},
  "margin_trend": {{"meets_criterion": true/false/"UNVERIFIABLE", "finding": "..."}},
  "roce": {{"meets_criterion": true/false/"UNVERIFIABLE", "finding": "..."}},
  "roe": {{"meets_criterion": true/false/"UNVERIFIABLE", "finding": "..."}},
  "debt_to_equity": {{"meets_criterion": true/false/"UNVERIFIABLE", "finding": "..."}},
  "promoter_holding": {{"meets_criterion": true/false/"UNVERIFIABLE", "finding": "..."}},
  "peg_ratio": {{"meets_criterion": true/false/"UNVERIFIABLE", "finding": "..."}}
}}"""


def get_multibagger_score(symbol: str, company_name: str = "", force_refresh: bool = False) -> dict | None:
    """
    Returns {"score": int, "max_score": 7, "breakdown": {...}} — score
    counts only criteria where meets_criterion is explicitly True.
    UNVERIFIABLE and False both count as 0 (score is deliberately
    conservative: unverifiable is NOT treated as a pass).
    """
    symbol = symbol.strip().upper()

    if not force_refresh:
        cached = get_cached_multibagger_score(symbol)
        if cached:
            return cached

    prompt = SCORING_PROMPT_TEMPLATE.format(name=company_name or symbol, symbol=symbol)

    try:
        response = _get_client().responses.create(
            model=SCREENER_MODEL,
            tools=[{"type": "web_search"}],
            input=prompt,
        )
        raw_text = response.output_text.strip()
        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]
        breakdown = json.loads(raw_text)

        score = sum(
            1 for criterion in MULTIBAGGER_CRITERIA
            if breakdown.get(criterion, {}).get("meets_criterion") is True
        )

        cache_multibagger_score(symbol, score, MAX_SCORE, breakdown)
        return {"score": score, "max_score": MAX_SCORE, "breakdown": breakdown}

    except Exception as e:
        print(f"[sme_screener] Multibagger scoring failed for {symbol}: {e}")
        stale = get_cached_multibagger_score(symbol, ignore_expiry=True)
        if stale:
            print(f"[sme_screener] Using stale cached score for {symbol} as fallback")
            return stale
        return None