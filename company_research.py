"""
company_research.py

GPT-powered company research using OpenAI's Responses API with the
hosted web_search tool. Produces sector, technical snapshot, financial
snapshot, and SWOT for a symbol — cached 30 days in SQLite since this
data doesn't change hour to hour and web-search-enabled calls cost
more than plain chat.completions calls.

Note: combines a hosted tool (web_search) with structured JSON output
in a single Responses API call. The model is instructed to search THEN
emit JSON matching RESEARCH_SCHEMA as its final text output.
"""
import json
from datetime import datetime, timezone, timedelta
from openai import OpenAI

from config import OPENAI_API_KEY
from db import get_conn

_client = None
CACHE_DAYS = 30
RESEARCH_MODEL = "gpt-4.1"  # supports Responses API + web_search tool


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=OPENAI_API_KEY or "sk-not-set")
    return _client


RESEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "sector": {"type": "string"},
        "industry": {"type": "string"},
        "company_type": {
            "type": "string",
            "description": "e.g. 'large-cap PSU bank', 'mid-cap IT services exporter'",
        },
        "market_cap_tier": {"type": "string", "enum": ["LARGE_CAP", "MID_CAP", "SMALL_CAP", "MICRO_CAP"]},
        "technical_snapshot": {
            "type": "string",
            "description": "2-3 sentences: trend direction, key support/resistance if findable, recent momentum",
        },
        "financial_snapshot": {
            "type": "string",
            "description": "2-3 sentences: revenue/profit trend, debt levels, most recent quarter highlights",
        },
        "swot": {
            "type": "object",
            "properties": {
                "strengths": {"type": "array", "items": {"type": "string"}},
                "weaknesses": {"type": "array", "items": {"type": "string"}},
                "opportunities": {"type": "array", "items": {"type": "string"}},
                "threats": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["strengths", "weaknesses", "opportunities", "threats"],
        },
        "key_risks": {"type": "array", "items": {"type": "string"}},
        "confidence_note": {
            "type": "string",
            "description": "Brief note if search results were sparse/stale for this company",
        },
    },
    "required": [
        "sector", "industry", "company_type", "market_cap_tier",
        "technical_snapshot", "financial_snapshot", "swot", "key_risks", "confidence_note",
    ],
}

RESEARCH_PROMPT_TEMPLATE = """Research the Indian-listed company "{company_name}" (NSE symbol: {symbol}).

Use web search to find:
1. Sector and industry classification
2. Approximate market cap tier (large/mid/small/micro cap, Indian market context)
3. Current technical picture — recent price trend, any notable support/resistance levels
4. Recent financial performance — latest quarter results, revenue/profit trend, debt situation
5. SWOT: strengths, weaknesses, opportunities, threats specific to this company right now

Be concise and factual. If search results are sparse or you're uncertain about any field, \
say so plainly in confidence_note rather than guessing.

Respond with ONLY a JSON object matching this exact structure (no markdown fences, no preamble):
{schema}"""


def _fetch_from_gpt(symbol: str, company_name: str) -> dict | None:
    prompt = RESEARCH_PROMPT_TEMPLATE.format(
        company_name=company_name or symbol,
        symbol=symbol,
        schema=json.dumps(RESEARCH_SCHEMA, indent=2),
    )
    try:
        response = _get_client().responses.create(
            model=RESEARCH_MODEL,
            tools=[{"type": "web_search"}],
            input=prompt,
        )
        raw_text = response.output_text.strip()
        # Strip markdown fences if the model added them despite instructions
        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]
        data = json.loads(raw_text)

        # Pull source URLs from web_search citations if present, for auditability
        sources = []
        for item in getattr(response, "output", []):
            if getattr(item, "type", None) == "message":
                for content in getattr(item, "content", []):
                    for annotation in getattr(content, "annotations", []) or []:
                        url = getattr(annotation, "url", None)
                        if url:
                            sources.append(url)
        data["sources"] = list(dict.fromkeys(sources))  # dedup, preserve order
        return data
    except json.JSONDecodeError as e:
        print(f"[company_research] Failed to parse GPT JSON for {symbol}: {e}")
        return None
    except Exception as e:
        print(f"[company_research] Research call failed for {symbol}: {e}")
        return None


def get_company_research(symbol: str, company_name: str = "", force_refresh: bool = False) -> dict | None:
    """
    Main entry point. Returns cached research if fresh (<30 days old),
    otherwise fetches new research via GPT web search and caches it.
    """
    symbol = symbol.strip().upper()

    if not force_refresh:
        cached = _get_cached(symbol)
        if cached:
            return cached

    print(f"[company_research] Fetching fresh research for {symbol} (cache miss or stale)")
    data = _fetch_from_gpt(symbol, company_name)
    if data is None:
        stale = _get_cached(symbol, ignore_expiry=True)
        if stale:
            print(f"[company_research] Using stale cache for {symbol} as fallback")
            return stale
        return None

    _save_to_cache(symbol, data)
    return data


def _get_cached(symbol: str, ignore_expiry: bool = False) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT data_json, valid_until FROM company_research WHERE symbol = ?",
            (symbol,),
        ).fetchone()
    if row is None:
        return None
    if not ignore_expiry:
        valid_until = datetime.fromisoformat(row["valid_until"])
        if datetime.now(timezone.utc) > valid_until:
            return None
    return json.loads(row["data_json"])


def _save_to_cache(symbol: str, data: dict):
    now = datetime.now(timezone.utc)
    valid_until = now + timedelta(days=CACHE_DAYS)
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO company_research (symbol, data_json, generated_at, valid_until)
               VALUES (?,?,?,?)
               ON CONFLICT(symbol) DO UPDATE SET
                 data_json=excluded.data_json,
                 generated_at=excluded.generated_at,
                 valid_until=excluded.valid_until""",
            (symbol, json.dumps(data), now.isoformat(), valid_until.isoformat()),
        )