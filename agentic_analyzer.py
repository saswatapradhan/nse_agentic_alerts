"""
agentic_analyzer.py

Agentic PDF Analyzer — the reasoning core.

GPT reads the full PDF text and reasons about materiality using textual
context clues (leverage mentions, beat/miss language, deal structure,
distress signals) rather than a fixed numeric formula. We deliberately do
NOT hard-code multiplier chains (D/E ratio x sector x macro, etc.) because
we have no live fundamentals data feed — GPT can only use what's actually
in the filing text. This is a scope decision, not an oversight: fabricating
precise-looking multipliers from data we don't have would create false
confidence, not real accuracy.
"""
from openai import OpenAI
import json

from config import OPENAI_API_KEY, OPENAI_MODEL, OPENAI_MAX_TOKENS
from db import get_category_threshold

_client = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=OPENAI_API_KEY or "sk-not-set")
    return _client


SIGNAL_FUNCTION = {
    "type": "function",
    "function": {
        "name": "extract_stock_signal",
        "description": "Extract a structured trading signal from a corporate announcement.",
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "NSE ticker symbol"},
                "category": {
                    "type": "string",
                    "enum": [
                        "ACQUISITION_OR_MERGER", "RIGHTS_ISSUE", "BUYBACK", "BONUS_ISSUE",
                        "FUNDRAISING", "DIVIDEND", "RESULTS", "GUIDANCE_CHANGE",
                        "BOARD_MEETING_INTIMATION", "CONTRACT_WIN",
                        "SEBI_ACTION", "FRAUD_ALLEGATION", "AUDITOR_ISSUE",
                        "INSIDER_TRADE", "CAPACITY_EXPANSION", "LEADERSHIP_CHANGE",
                        "LITIGATION", "DELISTING_SUSPENSION", "RELATED_PARTY_TXN",
                        "RESTRUCTURING_DIVESTMENT", "OTHER_MATERIAL"
                    ],
                },
                "acquisition_role": {
                    "type": "string",
                    "enum": ["ACQUIRER", "TARGET", "NOT_APPLICABLE"],
                    "description": "Only relevant for ACQUISITION_OR_MERGER: is the filing company "
                                    "the one buying (acquirer) or being bought (target)? Markets react "
                                    "very differently to each role.",
                },
                "sentiment": {"type": "string", "enum": ["POSITIVE", "NEGATIVE", "NEUTRAL"]},
                "predicted_direction": {"type": "string", "enum": ["UP", "DOWN", "FLAT"]},
                "confidence": {
                    "type": "number",
                    "description": "0-100 confidence this will move the price >=1% within 48h. "
                                    "Reserve >80 for genuinely rare, unambiguous, large-magnitude events "
                                    "(fraud, insolvency, high-premium acquisition of the filer, guidance "
                                    "withdrawal, severe earnings miss/beat). Most confirmed announcement-"
                                    "driven moves are modest (1-6%) — don't inflate confidence just "
                                    "because news sounds generically positive.",
                },
                "rupee_amount_cr": {
                    "type": "number",
                    "description": "Key monetary figure in ₹ Crore mentioned. 0 if none.",
                },
                "materiality_reasoning": {
                    "type": "string",
                    "description": "1-2 sentences citing the SPECIFIC textual context clues used "
                                    "(e.g. 'company explicitly states this improves its debt position' "
                                    "or 'no mention of financial distress, framed as routine capacity "
                                    "addition' or 'target company, all-cash offer at stated premium').",
                },
                "summary": {
                    "type": "string",
                    "description": "One crisp sentence summarizing the announcement for a Telegram alert",
                },
                "is_false_positive": {
                    "type": "boolean",
                    "description": "True if this is actually routine/immaterial despite passing keyword filters",
                },
            },
            "required": [
                "symbol", "category", "acquisition_role", "sentiment", "predicted_direction",
                "confidence", "rupee_amount_cr", "materiality_reasoning",
                "summary", "is_false_positive",
            ],
        },
    },
}

SYSTEM_PROMPT = """You are a financial analyst agent embedded in a real-time trading alert \
system for the Indian stock market (NSE/BSE). You will be given the text of a corporate \
announcement filed with the exchange.

Your job: decide whether this announcement is likely to move the stock price by 1% or more \
within 48 hours, and extract a structured signal using the extract_stock_signal function.

CORE PRINCIPLE — same keyword, different meaning depending on context:
The same announcement type can produce opposite market reactions depending on details actually \
stated in the filing. Do not treat category labels as automatically bullish or bearish — read for \
these context clues in the text itself:

- DIVIDEND changes: an increase from a company that also mentions strong cash position, low debt, \
  or a sustainable payout reads as genuine strength. An increase from a company that also mentions \
  financial stress, covenant issues, "going concern," or an unusually high payout ratio can actually \
  be a red flag (market reads it as denial/distraction), not a positive.
- ACQUISITION/MERGER: determine whether the filing company is the ACQUIRER (buying) or the TARGET \
  (being bought) — set acquisition_role accordingly. Targets typically see meaningfully stronger \
  positive reactions (control premium) than acquirers, who are frequently flat-to-negative \
  (market skepticism about M&A value creation), especially for stock-funded deals or already-\
  leveraged acquirers. An all-cash deal at a clearly stated premium is a stronger signal than a \
  vague "exploring strategic options" filing.
- RIGHTS ISSUE: almost always dilutive and reads negatively regardless of stated purpose — do not \
  treat "for growth capital" framing as making this positive.
- RESULTS: judge based on explicit beat/miss language or guidance commentary in the text, not just \
  the existence of a results filing. "In line with expectations" is a much weaker signal than an \
  explicit large beat, miss, or guidance revision.
- GUIDANCE_CHANGE: raised, lowered, or withdrawn guidance is one of the stronger real signals \
  available — magnitude matters (a small tweak is much weaker than a large raise/cut), and a \
  withdrawal (no clear number given at all) usually signals higher uncertainty than a lowered but \
  still-stated number.
- CAPACITY_EXPANSION / capex announcements: read for whether the company frames this as funded by \
  its own cash flow (stronger, less risky) versus needing fresh debt/equity (weaker, more caveated).
- RESTRUCTURING_DIVESTMENT: highly context-dependent — selling a genuinely non-core or underperforming \
  business to pay down debt reads differently than an unclear or apparently forced sale.

OTHER RULES:
1. Judge MATERIALITY relative to company size when inferable from context (a ₹200 Cr contract means \
   very different things for a small-cap versus a large-cap).
2. Be skeptical by default. Most filings are routine. Reserve confidence >80 for genuinely rare, \
   unambiguous, large events — not just because the news sounds generically positive.
3. If the announcement is actually routine despite matching keyword filters, set \
   is_false_positive=true and confidence low.
4. Never hallucinate rupee figures — if none stated, use 0.
5. Fraud, auditor resignation, SEBI enforcement, insolvency deserve high confidence (80+) and \
   NEGATIVE sentiment almost always, regardless of company size — these override the "be skeptical" \
   default.
6. In materiality_reasoning, name the SPECIFIC textual clue you used, not a generic restatement of \
   the category.
7. Always call extract_stock_signal exactly once."""


def analyze_pdf_text(pdf_text: str, symbol_hint: str = "", subject_hint: str = "") -> dict:
    pdf_text = pdf_text[:15000]

    user_msg = f"""Announcement subject: {subject_hint}
Ticker hint: {symbol_hint}

--- TEXT START ---
{pdf_text}
--- TEXT END ---

Analyze this and call extract_stock_signal."""

    try:
        response = _get_client().chat.completions.create(
            model=OPENAI_MODEL,
            max_tokens=OPENAI_MAX_TOKENS,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            tools=[SIGNAL_FUNCTION],
            tool_choice={"type": "function", "function": {"name": "extract_stock_signal"}},
            timeout=30,
        )
        message = response.choices[0].message
        if message.tool_calls:
            call = message.tool_calls[0]
            if call.function.name == "extract_stock_signal":
                return json.loads(call.function.arguments)
        return None
    except Exception as e:
        print(f"[analyzer] OpenAI API error: {e}")
        return None


# ── Correlation-based confidence bump ──────────────────────────────
# Applied AFTER analyze_pdf_text() returns a signal, BEFORE decide_alert()
# is called on it — so decide_alert's threshold check sees the bumped
# confidence, same as everything else that reads signal["confidence"].
#
# Pipeline order: analyze_pdf_text() -> apply_correlation_bump() -> decide_alert()

NEWS_LED_CONFIDENCE_BUMP = 7  # STARTING ASSUMPTION — validate via learning loop
MIN_LEAD_HOURS_FOR_BUMP = 0.5  # ignore trivial/noisy leads under 30 min


def apply_correlation_bump(signal: dict, correlation_result=None) -> dict:
    """
    Mutates signal's confidence (capped at 100) and materiality_reasoning
    if correlation_result indicates a genuine news_led lead. Also stamps
    news_led/hours_lead onto the signal dict so callers can pass them
    through to insert_alert() for tracking.

    correlation_result: a CorrelationResult from correlation_engine.py,
    or None if no correlation data is available (e.g. NSE-only run with
    no scraper data) — in which case this is a no-op.
    """
    if signal is None:
        return signal

    signal["news_led"] = False
    signal["hours_lead"] = None
    signal["confidence_bump_reason"] = None

    if correlation_result is None:
        return signal

    if (correlation_result.relationship == "news_led"
            and correlation_result.hours_lead is not None
            and correlation_result.hours_lead >= MIN_LEAD_HOURS_FOR_BUMP):

        original_confidence = signal["confidence"]
        bumped = min(100, original_confidence + NEWS_LED_CONFIDENCE_BUMP)
        bump_reason = (
            f"+{NEWS_LED_CONFIDENCE_BUMP} confidence: scraper reported this "
            f"{correlation_result.hours_lead:.1f}hrs before NSE filing (news_led)"
        )

        signal["confidence"] = bumped
        signal["materiality_reasoning"] = (
            signal.get("materiality_reasoning", "") + " | " + bump_reason
        )
        signal["news_led"] = True
        signal["hours_lead"] = correlation_result.hours_lead
        signal["confidence_bump_reason"] = bump_reason

    return signal


def decide_alert(signal: dict) -> dict:
    if signal is None:
        return {"should_alert": False, "reason": "Analysis failed"}

    if signal.get("is_false_positive"):
        return {"should_alert": False, "reason": "GPT flagged as false positive on closer read"}

    category = signal["category"]
    confidence = signal["confidence"]
    threshold = get_category_threshold(category)

    if confidence < threshold:
        return {
            "should_alert": False,
            "reason": f"Confidence {confidence} below learned threshold {threshold} for {category}",
        }

    rupee = signal.get("rupee_amount_cr", 0) or 0
    role = signal.get("acquisition_role", "NOT_APPLICABLE")

    if category in ("FRAUD_ALLEGATION", "AUDITOR_ISSUE", "DELISTING_SUSPENSION") or rupee >= 5000:
        priority = "CRITICAL"
    elif category == "SEBI_ACTION" or rupee >= 500 or confidence >= 80:
        priority = "HIGH"
    elif category == "ACQUISITION_OR_MERGER" and role == "TARGET":
        priority = "HIGH"  # targets typically see the strongest reactions
    elif category == "GUIDANCE_CHANGE" and confidence >= 65:
        priority = "HIGH"
    elif category in ("DIVIDEND", "RELATED_PARTY_TXN", "LEADERSHIP_CHANGE", "RIGHTS_ISSUE",
                       "BUYBACK", "RESTRUCTURING_DIVESTMENT") or confidence >= 65:
        priority = "MEDIUM"
    else:
        priority = "LOW"

    return {"should_alert": True, "priority": priority, "reason": "Passed all checks"}