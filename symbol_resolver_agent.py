"""
symbol_resolver_agent.py

GPT-based company-name -> NSE ticker resolution. Replaces
symbol_lookup.find_symbol()'s RapidFuzz threshold scoring, which was
producing false negatives on real companies (e.g. K2 Infragen Limited
failed to match despite being present, or being a very recent listing
not yet reflected — either way, the fixed-threshold fuzzy score was
too brittle).

GPT is given the company name to resolve PLUS the full current
watchlist (all ~2400 NSE-listed symbols + names) as context, and
decides the correct match itself — no pre-filtering, no scoring
heuristic. Every resolution is cached (including confirmed
NOT_IN_UNIVERSE results) so the same company is never re-resolved via
GPT twice, keeping the ongoing cost bounded despite the large one-time
context per fresh lookup.
"""
import csv
from openai import OpenAI
import json

from config import OPENAI_API_KEY, WATCHLIST_FILE
from db import get_cached_symbol_resolution, cache_symbol_resolution

_client = None
_watchlist_context_cache = None  # rebuilt once per process run, not per call

RESOLVER_MODEL = "gpt-4o-mini"


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=OPENAI_API_KEY or "sk-not-set")
    return _client


def _build_watchlist_context() -> str:
    """Loads the full watchlist CSV once per process and formats it as
    compact SYMBOL|NAME lines for GPT context. Cached in memory for the
    life of the process — rebuild by restarting after refresh_watchlist.py
    runs, or call _reset_watchlist_context() explicitly."""
    global _watchlist_context_cache
    if _watchlist_context_cache is not None:
        return _watchlist_context_cache

    lines = []
    try:
        with open(WATCHLIST_FILE, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                symbol = row.get("symbol", "").strip()
                name = row.get("company_name", "").strip()
                if symbol and name:
                    lines.append(f"{symbol}|{name}")
    except FileNotFoundError:
        print(f"[symbol_resolver_agent] WARNING: {WATCHLIST_FILE} not found")

    _watchlist_context_cache = "\n".join(lines)
    return _watchlist_context_cache


def _reset_watchlist_context():
    """Call after refresh_watchlist.py runs mid-process, if ever needed,
    so the next resolution picks up newly-listed symbols."""
    global _watchlist_context_cache
    _watchlist_context_cache = None


RESOLVE_FUNCTION = {
    "type": "function",
    "function": {
        "name": "resolve_symbol",
        "description": "Determine the correct NSE ticker symbol for a given company name, using the provided watchlist.",
        "parameters": {
            "type": "object",
            "properties": {
                "matched_symbol": {
                    "type": ["string", "null"],
                    "description": "The exact SYMBOL from the watchlist that corresponds to the given "
                                    "company name, or null if genuinely no entry in the watchlist matches "
                                    "this company (e.g. it's a very recent listing not yet in the list, "
                                    "or a non-equity entity).",
                },
                "confidence": {
                    "type": "string",
                    "enum": ["HIGH", "MEDIUM", "LOW"],
                    "description": "HIGH: exact or near-exact name match. MEDIUM: same company, "
                                    "significant formatting/abbreviation difference. LOW: uncertain guess.",
                },
            },
            "required": ["matched_symbol", "confidence"],
        },
    },
}

SYSTEM_PROMPT = """You resolve Indian company names (as they appear in NSE corporate \
announcements) to their correct NSE ticker symbol, using the watchlist provided.

The watchlist format is SYMBOL|COMPANY NAME, one per line.

Company names in announcements may differ from the watchlist in formatting (Ltd vs Limited), \
punctuation, or abbreviation — use your judgment to match the same real-world company, not just \
exact string matches. If the company genuinely isn't in the watchlist (e.g. a very recent IPO, \
or a non-equity entity like a mutual fund or bond issuer), return matched_symbol=null rather than \
guessing at a wrong match. Always call resolve_symbol exactly once."""


def resolve_symbol_agent(raw_name: str) -> str | None:
    """
    Main entry point. Returns the resolved NSE symbol, or None if
    genuinely not in the current watchlist. Checks cache first —
    only calls GPT on a true cache miss.
    """
    raw_name = raw_name.strip()
    if not raw_name:
        return None

    found, cached_symbol = get_cached_symbol_resolution(raw_name)
    if found:
        return cached_symbol  # cache hit — even if it's a cached None (confirmed not-found)

    watchlist_context = _build_watchlist_context()
    if not watchlist_context:
        return None

    user_msg = f"""Watchlist:
{watchlist_context}

Company name to resolve: {raw_name}

Call resolve_symbol with the matching ticker, or null if not found."""

    try:
        response = _get_client().chat.completions.create(
            model=RESOLVER_MODEL,
            max_tokens=100,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            tools=[RESOLVE_FUNCTION],
            tool_choice={"type": "function", "function": {"name": "resolve_symbol"}},
            timeout=30,
        )
        message = response.choices[0].message
        if not message.tool_calls:
            cache_symbol_resolution(raw_name, None)
            return None

        result = json.loads(message.tool_calls[0].function.arguments)
        resolved = result.get("matched_symbol")

        cache_symbol_resolution(raw_name, resolved)
        return resolved

    except Exception as e:
        print(f"[symbol_resolver_agent] Resolution failed for '{raw_name}': {e}")
        return None  # NOT cached — a transient API failure shouldn't be
                      # permanently remembered as "not found"