"""

config.py

Central configuration for the NSE/BSE Agentic PDF Alert System.
All thresholds derived from Saswata's requirements (July 2026).
"""
import os
from dotenv import load_dotenv

load_dotenv(override=True)

# ── API KEYS (set as environment variables, never hardcode) ──────────
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")   # from @BotFather
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")       # your personal chat id

# ── OPENAI MODEL ────────────────────────────────────────────────────
# gpt-4o-mini is the cost-efficient choice for high-frequency document
# classification like this. Swap to "gpt-4o" if you want higher reasoning
# quality on ambiguous filings (costs ~15-20x more per call).
OPENAI_MODEL = "gpt-4o-mini"
OPENAI_MAX_TOKENS = 2000

# ── SOURCES ───────────────────────────────────────────────────────────
NSE_ANNOUNCEMENTS_RSS = "https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml"
NSE_ANNOUNCEMENTS_API = "https://www.nseindia.com/api/corporate-announcements?index=equities"
BSE_ANNOUNCEMENTS_API = "https://api.bseindia.com/BseIndiaAPI/api/AnnGetData/w"
NSE_HOMEPAGE = "https://www.nseindia.com"  # needed for cookie bootstrap

# ── POLLING ───────────────────────────────────────────────────────────
POLL_INTERVAL_SECONDS = 120          # every 2 min during market hours
MARKET_OPEN = "09:00"                # start polling (pre-market announcements matter)
MARKET_CLOSE = "18:30"               # NSE announcements keep flowing post-close
PRICE_TRACK_CHECKPOINTS_HRS = [1, 24, 48]   # self-learning price snapshots

# ── WATCHLIST ─────────────────────────────────────────────────────────
WATCHLIST_FILE = "data/nifty500_symbols.csv"   # broad Nifty 500 universe

# ── ALERT PRIORITY THRESHOLDS ────────────────────────────────────────
# Priority is decided by the agentic analyzer + these rupee thresholds
CRITICAL_REVENUE_IMPACT_CR = 5000    # ₹5,000 Cr+ -> 🔴
HIGH_ACQUISITION_PCT_MCAP = 10       # acquisition >10% of market cap -> 🟠
INSIDER_BUY_THRESHOLD_CR = 10        # promoter/insider buy > ₹10 Cr -> alert (user rule)
RELATED_PARTY_HIGH_CR = 100          # RPT > ₹100 Cr -> 🔴
LITIGATION_HIGH_CR = 100

# Minimum GPT confidence (0-100) to send an alert at all
MIN_CONFIDENCE_TO_ALERT = 70

# ── SELF-LEARNING ────────────────────────────────────────────────────
DB_PATH = "data/alerts.db"
LEARNING_MIN_SAMPLES = 5             # need >=5 outcomes before adjusting a category threshold
LEARNING_HIT_DEFINITION_PCT = 1.0    # price moved >=1% in predicted direction within 48h = "hit"
CONFIDENCE_ADJUST_STEP = 5           # raise/lower category threshold by 5 pts based on hit rate

# ── USER RULES (Saswata, July 2026) ──────────────────────────────────
# 1. IGNORE ex-dividend date reminders (only NEW dividend declarations alert)
# 2. Board-meeting INTIMATION -> alert (so alarms can be set for actual results)
# 3. RESULTS announced 3-5 days later -> alert (the real trade trigger)
# 4. Universe: Nifty 500
# 5. Insider/promoter buys: alert ONLY if > ₹10 Cr

# ── GOOGLE SHEETS LIVE PRICE FEED ─────────────────────────────────────
# Public "Anyone with link can view" Google Sheet using GOOGLEFINANCE()
# formulas. Exported as plain CSV — no OAuth/API key needed.
GOOGLE_SHEET_CSV_URL = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vQJL9wJXhUZQCD6qLDr03YOBTmqbytzLUJ2iZ1xT23HQnMy8Kg1bVj2U-Q8ej63yrZfA_4o2eXwwgfL/"
    "pub?gid=1140263743&single=true&output=csv"
)
SHEET_PRICE_CACHE_MINUTES = 4