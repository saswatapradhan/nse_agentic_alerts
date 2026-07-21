"""
false_positive_filters.py

False Positive Filter Layer.
Runs BEFORE the expensive GPT API call — cheap regex/keyword rules
eliminate ~70% of routine announcements, saving cost and noise.

Design pattern: Chain of Responsibility — each rule returns
(should_skip: bool, reason: str). First rule that fires short-circuits.
"""
import re
from dataclasses import dataclass

# GPT-based symbol resolution (replaces symbol_lookup.find_symbol()'s
# RapidFuzz threshold scoring — that approach produced false negatives
# on real companies, e.g. K2 Infragen Limited failed a 90%-threshold
# fuzzy match despite being a genuine listing. resolve_symbol_agent()
# gives GPT the full watchlist as context and lets it judge the match
# directly; every resolution is cached so repeat mentions of the same
# company never re-spend a GPT call.
from symbol_resolver_agent import resolve_symbol_agent

# SME screening – multibagger scoring for emerging stocks
from sme_screener import check_sme_membership, get_multibagger_score


@dataclass
class FilterResult:
    skip: bool
    reason: str = ""
    force_priority: str = ""   # a rule can also PROMOTE (e.g. auditor resignation)
    is_sme: bool = False
    sme_score: dict | None = None   # {"score": int, "max_score": 7, "breakdown": {...}}


# ── HARD-SKIP PATTERNS (routine, never price-moving) ─────────────────
HARD_SKIP_PATTERNS = [
    # (regex on subject/title, reason)
    (r"trading window.*(clos|open)", "Routine trading-window closure (pre-earnings, automatic)"),
    (r"closure of trading window", "Routine trading-window closure"),
    (r"ex[- ]?dividend.*reminder|reminder.*ex[- ]?date", "Ex-dividend date reminder (user rule: ignore)"),
    (r"book closure", "Routine book-closure timing"),
    (r"record date.*(dividend|interest)", "Record-date housekeeping (price already adjusts on ex-date)"),
 
    (r"newspaper (publication|advertisement)", "Newspaper publication of already-known info"),
    (r"change (of|in) (registered office|address|company secretary|compliance officer|rta|registrar)",
     "Administrative change, zero material impact"),
    (r"loss of share certificate|duplicate share certificate", "Share-certificate housekeeping"),
    (r"annual report submission|submission of annual report", "Annual report: historical data, already priced in"),
    (r"business responsibility.*sustainability", "BRSR filing — routine ESG compliance"),
    (r"secretarial compliance report", "Routine compliance filing"),
    (r"investor (grievance|complaint).*(nil|resolved|redressal report)", "Routine complaint-status filing"),
    (r"reg(ulation)?\s*74\s*\(5\)", "Routine RTA share-dematerialization certificate"),
    (r"certificate under regulation", "Routine regulatory certificate"),
    (r"shareholding pattern", "Quarterly SHP — analyze only via scheduled review, not real-time"),
    (r"clarification.*(spurt|volume|price movement)", "Exchange-sought clarification; usually 'no info' reply"),
    (r"intimation.*analyst.*(meet|call|conference)", "Analyst-meet scheduling notice"),
    (r"earnings call transcript|transcript of", "Transcript of already-held call — info already public"),
    (r"esop|employee stock option.*allotment", "Routine ESOP allotment (tiny dilution)"),
]

# ── CONDITIONAL RULES (need context beyond regex) ─────────────────────

INSIDER_TRADE_RE = re.compile(
    r"(insider trading|sast|reg(ulation)?\s*(29|31|7)|pit disclosure|acquisition of shares.*promoter)",
    re.I,
)
BOARD_MEETING_RE = re.compile(r"board meeting.*(intimation|scheduled|consider)", re.I)
RESULTS_RE = re.compile(r"(financial results|un-?audited results|audited results).*(approved|announce|outcome)", re.I)
NEW_DIVIDEND_RE = re.compile(r"(declar|recommend).{0,30}dividend", re.I)

# Promotion patterns — never skip, escalate even if wording looks routine
PROMOTE_PATTERNS = [
    (r"resignation.*(auditor|statutory auditor)", "CRITICAL"),
    (r"qualified opinion|disclaimer of opinion|adverse opinion", "CRITICAL"),
    (r"(sebi|exchange).*(show.?cause|penalty|investigation|enforcement)", "HIGH"),
    (r"insolvency|nclt|ibc|corporate insolvency", "CRITICAL"),
    (r"default.*(payment|interest|principal)", "CRITICAL"),
    (r"(fraud|forensic audit)", "CRITICAL"),
]


def extract_crore_amounts(text: str) -> list[float]:
    """Pull ₹ amounts in crore from text. Handles 'Rs. 1,234.5 Cr', '₹500 crore', 'INR 12 cr'."""
    amounts = []
    for m in re.finditer(
        r"(?:rs\.?|₹|inr)\s*([\d,]+(?:\.\d+)?)\s*(cr|crore)", text, re.I
    ):
        amounts.append(float(m.group(1).replace(",", "")))
    # lakh -> crore conversion
    for m in re.finditer(r"(?:rs\.?|₹|inr)\s*([\d,]+(?:\.\d+)?)\s*lakh", text, re.I):
        amounts.append(float(m.group(1).replace(",", "")) / 100)
    return amounts


def apply_filters(subject: str, body_snippet: str, symbol: str,
                  watchlist: set, insider_threshold_cr: float = 10) -> FilterResult:
    """
    Main entry. Returns FilterResult(skip, reason, force_priority, is_sme, sme_score).
    Order matters: promotions checked first (never miss a fraud signal),
    then universe filter (main-board OR SME), then hard skips, then
    conditional rules.
    """
    text = f"{subject} {body_snippet}".lower()

    # Resolve SME status ONCE, up front — cheap on cache hit, and needed
    # regardless of which rule below ends up firing.
    is_sme = False
    sme_score = None
    resolved_symbol = None

    if watchlist:
        resolved_symbol = resolve_symbol_agent(symbol) or symbol.upper()
        if resolved_symbol not in watchlist:
            sme_symbol, is_sme = check_sme_membership(symbol)
            if is_sme:
                sme_score = get_multibagger_score(sme_symbol or symbol, company_name=symbol)

    result = _apply_rule_chain(text, symbol, resolved_symbol, watchlist,
                                insider_threshold_cr, is_sme)
    result.is_sme = is_sme
    result.sme_score = sme_score
    return result


def _apply_rule_chain(text: str, symbol: str, resolved_symbol: str | None,
                       watchlist: set, insider_threshold_cr: float, is_sme: bool) -> FilterResult:
    """The original rule chain (steps 0, 1, 2-7) — logic unchanged from
    the tested original, just extracted so apply_filters() can attach
    is_sme/sme_score to whichever branch fires."""

    # 0. PROMOTE rules — safety first, these bypass every skip rule
    for pattern, priority in PROMOTE_PATTERNS:
        if re.search(pattern, text, re.I):
            return FilterResult(skip=False, force_priority=priority,
                                reason=f"Promoted: matched '{pattern}'")

    # 1. Universe filter — main-board (full NSE equity list) OR SME.
    # SME stocks are NEVER hard-skipped here — they always pass through
    # with their multibagger score attached, per user decision. Only
    # symbols matching NEITHER main-board NOR SME get skipped.
    if watchlist:
        if resolved_symbol not in watchlist:
            if is_sme:
                return FilterResult(skip=False,
                    reason=f"{symbol}: SME (Emerge) stock — not main-board, multibagger score attached")
            return FilterResult(skip=True,
                reason=f"{symbol} not found in NSE main-board or SME universe")

    # 2. Insider trading — user rule: alert ONLY if buy > ₹10 Cr
    if INSIDER_TRADE_RE.search(text):
        amounts = extract_crore_amounts(text)
        if amounts and max(amounts) >= insider_threshold_cr:
            return FilterResult(skip=False, force_priority="HIGH",
                                reason=f"Insider/promoter transaction ₹{max(amounts):.0f} Cr ≥ ₹{insider_threshold_cr} Cr")
        return FilterResult(skip=True,
                            reason="Insider disclosure below ₹10 Cr threshold (user rule)")

    # 3. New dividend declaration -> keep (user tracks dividend cycles)
    if NEW_DIVIDEND_RE.search(text):
        return FilterResult(skip=False, reason="New dividend declaration")

    # 4. Board meeting intimation -> ALERT (user rule: alarm-setting signal)
    if BOARD_MEETING_RE.search(text) and not RESULTS_RE.search(text):
        return FilterResult(skip=False, force_priority="LOW",
                            reason="Board-meeting intimation (user wants alarm-setting signal)")

    # 5. Actual results announced -> ALERT
    if RESULTS_RE.search(text):
        return FilterResult(skip=False, force_priority="HIGH",
                            reason="Financial results announced — the real trade trigger")

    # 6. Hard skip list
    for pattern, reason in HARD_SKIP_PATTERNS:
        if re.search(pattern, text, re.I):
            return FilterResult(skip=True, reason=reason)

    # 7. Default: pass to GPT for deep analysis
    return FilterResult(skip=False, reason="Passed pre-filters → agentic analysis")