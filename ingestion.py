"""
ingestion.py

Ingestion Layer — polls NSE/BSE for new announcement PDFs.

IMPORTANT: NSE's website is protected by bot-detection and requires
session cookies bootstrapped from a browser-like request before their
JSON APIs respond. This module handles that handshake. If NSE changes
their anti-bot measures, this is the first place to fix.
"""
import requests
import feedparser
import re
import io
import time
from datetime import datetime, timezone, timedelta
from pypdf import PdfReader

from config import NSE_ANNOUNCEMENTS_RSS, NSE_HOMEPAGE, BSE_ANNOUNCEMENTS_API
from db import already_processed, mark_processed

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

# India Standard Time (UTC+5:30)
IST = timezone(timedelta(hours=5, minutes=30))

# Skip keywords for non-equity instruments that should be filtered out
# IMPORTANT: Items that could be trading signals are intentionally NOT in this list:
# - credit rating, security cover, dividend payout, scrutinizer report
# - proceedings of, payment of interest, report, record date
# - disclosure under regulation, reg 30, reg 57
# - spurt in volume, price movement, monthly business updates
# - unitholding pattern, integrated filing, governance
# - board meeting outcomes, analyst/investor meets, acquisitions
# - appointments/resignations, allotments, etc.
SKIP_KEYWORDS = [
    # AMCs / Fund Houses - skip all mutual fund related announcements
    "mutual fund", "amc", "asset management",
    "dsp", "kotak", "icici prudential", "nippon", "sbi mutual",
    "hdfc mutual", "axis mutual", "mirae asset", "bandhan",
    "zerodha", "groww", "uti mutual", "edelweiss mutual",
    "aditya birla sun life", "motilal oswal", "quant",
    "lic mutual", "baroda bnp", "angel one", "360 one",
    "bajaj finserv", "hsbc mutual", "invesco", "choice",
    "union mutual", "wealth company", "reliance mutual",
    "hsbc", "nippon life india", "quantum",
    
    # ETF variations - skip all ETF announcements
    "etf", "bees", "exchange traded",
    "nifty 1d", "gold etf", "silver etf", "bank etf",
    "nifty 50 etf", "nifty next", "nifty midcap",
    "nifty psu bank", "nifty private bank", "nifty it",
    "nifty healthcare", "nifty fmcg", "nifty consumption",
    "bse sensex", "bse liquid rate", "bse top 10 banks",
    "nifty india manufacturing", "nifty energy",
    "nifty metal", "nifty auto", "nifty pharma",
    "nifty oil & gas", "nifty infrastructure",
    "nifty 100", "nifty 200", "nifty 500",
    "bse 500", "bse 200", "sensex",
    
    # Specific ETF identifiers from feed
    "liqiuidetf", "liquidadd", "bank10add", "niftyadd",
    "fmcgadd", "next30add", "flexiadd", "goldadd",
    "healthadd", "top10add", "msciadd", "itadd",
    "silveradd", "next50add", "sensexadd", "midq50add",
    "smalladd", "midcapadd", "bankadd",
    
    # Mutual fund schemes
    "interval fund", "fixed maturity plan", "fmp",
    "hybrid long-short", "active asset allocator",
    "liquid fund", "gilt fund", "income fund",
    
    # Pure debt instruments (skip these as they're not equity)
    "commercial paper", "cp", "ncd", "non convertible",
    "non-convertible", "secured redeemable",
    "gilt", "t-bill", "treasury", "government security",
    "listed debt", "debt",
    
    # Other non-equity instruments
    "option", "future", "derivative", "warrant",
    "sgb", "gold bond", "silver bond", "adr", "gdr",
    "unit", "invit", "reit", "trust", "depository receipt",
    "preference shares",
    
    # These are skipped as they're not trading signals
    "structural digital database", "sdd", "sdd compliance",
   
    "trading window", "closure of trading window",  # note: "spurt in volume" is NOT skipped

  
    "press release (revised)",
    "news verification",
    "voting results",  # note: "scrutinizer" and "proceedings of" are NOT skipped
    "nav as on",  # note: "net asset value" is NOT skipped (could be important)
    "fortnightly portfolios",  # note: "portfolio" is NOT skipped
    "statement of utilization"
]


def should_skip_announcement(title: str) -> bool:
    """Check if an announcement should be skipped based on its title.
    Uses word-boundary matching so single-word keywords (e.g. "unit",
    "trust", "debt") can't accidentally match inside a company's own
    name (e.g. "United Breweries", "Trust Fintech")."""
    title_lower = title.lower()
    for keyword in SKIP_KEYWORDS:
        pattern = r"\b" + re.escape(keyword) + r"\b"
        if re.search(pattern, title_lower):
            return True
    return False


class NSESession:
    """Handles the cookie bootstrap NSE requires before API calls succeed."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self._bootstrap()

    def _bootstrap(self):
        try:
            self.session.get(NSE_HOMEPAGE, timeout=10)
        except requests.RequestException as e:
            print(f"[ingestion] NSE cookie bootstrap failed: {e}")

    def get_json(self, url: str, retries: int = 2):
        for attempt in range(retries + 1):
            try:
                resp = self.session.get(url, timeout=10)
                if resp.status_code == 200:
                    return resp.json()
                elif resp.status_code in (401, 403):
                    self._bootstrap()
            except (requests.RequestException, ValueError) as e:
                print(f"[ingestion] NSE API attempt {attempt} failed: {e}")
            time.sleep(1)
        return None


def fetch_nse_rss_announcements(max_age_minutes: int = 15) -> list[dict]:
    results = []
    cutoff = datetime.now(IST).timestamp() - (max_age_minutes * 60)
    skipped_parse_fail = 0
    skipped_non_equity = 0

    try:
        resp = requests.get(NSE_ANNOUNCEMENTS_RSS, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)

        for entry in feed.entries:
            pdf_url = entry.get("link", "")
            if not pdf_url.lower().endswith(".pdf"):
                continue

            title = entry.get("title", "").strip()          # company name only
            description = entry.get("description", "").strip()  # real subject text

            # Filter using the DESCRIPTION, not the title. NSE's <title> is
            # just the company name (e.g. "Trust Fintech Limited"), so
            # matching skip-keywords against it caused false skips for real
            # stocks whose names contain common words. The actual subject
            # ("...|SUBJECT: Closure of Trading Window") lives in <description>.
            check_text = description or title
            if should_skip_announcement(check_text):
                skipped_non_equity += 1
                continue

            published_str = entry.get("published", "")
            parsed_ok = False
            try:
                published_dt = datetime.strptime(published_str, "%d-%b-%Y %H:%M:%S").replace(tzinfo=IST)
                parsed_ok = True
            except ValueError:
                try:
                    published_dt = datetime.strptime(published_str, "%d-%b-%Y %H:%M").replace(tzinfo=IST)
                    parsed_ok = True
                except (ValueError, TypeError):
                    skipped_parse_fail += 1

            if not parsed_ok:
                continue
            if published_dt.timestamp() < cutoff:
                continue

            results.append({
                "symbol": title,
                "subject": description or title,
                "pdf_url": pdf_url,
                "published": published_str,
                "source": "NSE",
            })
    except Exception as e:
        print(f"[ingestion] NSE RSS fetch failed: {e}")

    if skipped_parse_fail > 0:
        print(f"[ingestion] Skipped {skipped_parse_fail} entries due to unparseable dates")
    if skipped_non_equity > 0:
        print(f"[ingestion] Skipped {skipped_non_equity} non-equity/routine entries")

    return results

def download_and_extract_text(pdf_url: str, timeout: int = 15) -> str:
    """Download a PDF and extract its text content."""
    try:
        resp = requests.get(pdf_url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        reader = PdfReader(io.BytesIO(resp.content))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        return text.strip()
    except Exception as e:
        print(f"[ingestion] Failed to extract {pdf_url}: {e}")
        return ""


def poll_new_announcements() -> list[dict]:
    """Main entry point. Returns only NEW (unprocessed) announcements with PDF text."""
    all_items = fetch_nse_rss_announcements()
    print(f"[ingestion] RSS returned {len(all_items)} total items, checking each...")
    new_items = []
    skipped_duplicates = 0
    skipped_extraction_fail = 0

    for i, item in enumerate(all_items):
        print(f"[ingestion] ({i+1}/{len(all_items)}) Checking {item['symbol']}...")

        if already_processed(item["pdf_url"]):
            print(f"[ingestion]   -> already processed, skipping (dedup)")
            skipped_duplicates += 1
            continue
        
        mark_processed(item["pdf_url"])

        print(f"[ingestion]   -> downloading PDF...")
        text = download_and_extract_text(item["pdf_url"])
        if not text:
            print(f"[ingestion]   -> extraction failed/empty, skipping")
            skipped_extraction_fail += 1
            continue

        print(f"[ingestion]   -> extracted {len(text)} chars successfully")
        item["pdf_text"] = text
        new_items.append(item)

    print(f"[ingestion] Summary: {len(new_items)} new items, "
          f"{skipped_duplicates} duplicates skipped, "
          f"{skipped_extraction_fail} extraction failures, "
          f"{len(all_items) - len(new_items) - skipped_duplicates - skipped_extraction_fail} other skips")
    return new_items