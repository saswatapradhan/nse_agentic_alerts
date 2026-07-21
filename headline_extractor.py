"""
headline_extractor.py

GPT-powered extraction agent for scraped RSS headlines. Replaces the
n-gram/regex symbol-extraction approach — GPT reliably identifies the
actual company name even through marketing lead-ins ("Bonus bonanza!"),
and classifies whether the item is even about a specific NSE company
at all vs general market/global commentary.

Uses gpt-4o-mini (not the full analysis model) since this is pure NER +
classification, not deep reasoning — keeps cost low for what could be
a high-volume call (every scraped headline, before the expensive
agentic_analyzer.py analysis even runs).

GPT identifies the company NAME as text — final ticker resolution still
goes through symbol_lookup.find_symbol() against your actual Nifty 500
list, so GPT never invents a ticker; it only points at which text to
resolve.
"""
from openai import OpenAI
import json

from config import OPENAI_API_KEY
from symbol_lookup import find_symbol

_client = None
EXTRACTOR_MODEL = "gpt-4o-mini"


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=OPENAI_API_KEY or "sk-not-set")
    return _client


EXTRACTION_FUNCTION = {
    "type": "function",
    "function": {
        "name": "extract_headline_info",
        "description": "Identify the specific company (if any) a news headline is about, and classify its relevance.",
        "parameters": {
            "type": "object",
            "properties": {
                "company_name": {
                    "type": ["string", "null"],
                    "description": "The specific company name mentioned, exactly as written in the headline "
                                    "(e.g. 'Aastha Spintex', 'Sobha Ltd', 'Suzlon Energy'). Null if the "
                                    "headline is not about one specific company.",
                },
                "relevance": {
                    "type": "string",
                    "enum": ["NSE_COMPANY_SPECIFIC", "MACRO_COMMENTARY", "NON_INDIAN_MARKET", "OTHER"],
                    "description": "NSE_COMPANY_SPECIFIC: about one identifiable Indian-listed company. "
                                    "MACRO_COMMENTARY: general Indian market mood/index/sector commentary, "
                                    "no single company. NON_INDIAN_MARKET: about US/global markets, not "
                                    "India-specific. OTHER: doesn't fit the above.",
                },
                "category_hint": {
                    "type": "string",
                    "description": "Rough category guess (e.g. 'RESULTS', 'BONUS_ISSUE', 'CONTRACT_WIN') "
                                    "for triage only — the real categorization happens later in "
                                    "agentic_analyzer.py with full text. Use 'UNKNOWN' if unclear.",
                },
            },
            "required": ["company_name", "relevance", "category_hint"],
        },
    },
}

SYSTEM_PROMPT = """You extract structured info from Indian stock market news headlines for a \
trading alert pipeline. Identify the specific company being discussed (ignore marketing \
lead-ins like "Bonus bonanza!" or "Breaking:" — find the actual company name), and classify \
whether this headline is about one specific NSE-listed company or general market commentary. \
Always call extract_headline_info exactly once."""


def extract_headline_info(headline: str, summary: str = "") -> dict:
    """
    Returns: {
        "company_name": str | None,
        "relevance": "NSE_COMPANY_SPECIFIC" | "MACRO_COMMENTARY" | "NON_INDIAN_MARKET" | "OTHER",
        "category_hint": str,
        "resolved_symbol": str | None,  # added after GPT call, via symbol_lookup
    }
    Falls back to relevance="OTHER", everything else None, on any API failure —
    caller should treat that as "skip, don't block the pipeline on this."
    """
    user_msg = f"Headline: {headline}\nSummary: {summary or '(none)'}"

    try:
        response = _get_client().chat.completions.create(
            model=EXTRACTOR_MODEL,
            max_tokens=200,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            tools=[EXTRACTION_FUNCTION],
            tool_choice={"type": "function", "function": {"name": "extract_headline_info"}},
            timeout=15,
        )
        message = response.choices[0].message
        if not message.tool_calls:
            return {"company_name": None, "relevance": "OTHER", "category_hint": "UNKNOWN", "resolved_symbol": None}

        result = json.loads(message.tool_calls[0].function.arguments)

        resolved_symbol = None
        if result.get("company_name") and result.get("relevance") == "NSE_COMPANY_SPECIFIC":
            resolved_symbol = find_symbol(result["company_name"])

        result["resolved_symbol"] = resolved_symbol
        return result

    except Exception as e:
        print(f"[headline_extractor] Extraction failed: {e}")
        return {"company_name": None, "relevance": "OTHER", "category_hint": "UNKNOWN", "resolved_symbol": None}