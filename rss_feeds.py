"""
rss_feeds.py

Complete RSS feed configuration for all sources.
Includes working ET, LiveMint, Business Standard (with session fix), and BSE.
"""
import requests
from datetime import datetime, timezone
from typing import List, Dict, Optional

# Business Standard needs a session with proper headers to bypass 403
def get_business_standard_session():
    """Create a session configured for Business Standard RSS."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Referer": "https://www.business-standard.com/",
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
    })
    return session

RSS_FEEDS = {
    "ET_Stocks": {
        "url": "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",
        "source": "Economic Times",
        "category": "stocks",
        "enabled": True,
        "session_required": False,
        "feed_type": "rss",
        "priority": 1
    },
    "LiveMint_Markets": {
        "url": "https://www.livemint.com/rss/markets",
        "source": "LiveMint",
        "category": "markets",
        "enabled": True,
        "session_required": False,
        "feed_type": "rss",
        "priority": 1
    },
    "BusinessStandard_Markets": {
        "url": "https://www.business-standard.com/rss/markets-106.rss",
        "source": "Business Standard",
        "category": "markets",
        "enabled": True,
        "session_required": True,
        "session": get_business_standard_session(),
        "feed_type": "rss",
        "priority": 2
    },
    "BSE_Corporate": {
        "url": "https://www.bseindia.com/rss/corporate-announcements.xml",
        "source": "BSE India",
        "category": "corporate_announcements",
        "enabled": True,
        "session_required": True,
        "feed_type": "rss",
        "priority": 1,
        "alt_urls": [
            "https://www.bseindia.com/rss/market-announcements.xml",
            "https://www.bseindia.com/rss/notices.xml"
        ]
    },
    "NSE_Corporate": {
        "url": "https://www.nseindia.com/api/corporate-announcements",
        "source": "NSE India",
        "category": "corporate_announcements",
        "enabled": True,
        "session_required": True,
        "feed_type": "api",
        "priority": 1
    }
}

def get_feed_config(source_name: str) -> Optional[Dict]:
    """Get configuration for a specific RSS feed."""
    return RSS_FEEDS.get(source_name)

def get_enabled_feeds() -> List[Dict]:
    """Get list of enabled feeds with their configurations."""
    return [config for config in RSS_FEEDS.values() if config.get("enabled", True)]

def get_feed_priority(source_name: str) -> int:
    """Get priority of a feed (lower number = higher priority)."""
    config = get_feed_config(source_name)
    return config.get("priority", 999) if config else 999

def validate_feed_url(url: str, session_required: bool = False, session: Optional[requests.Session] = None) -> bool:
    """Validate if a feed URL is accessible."""
    try:
        if session_required and session:
            resp = session.get(url, timeout=10)
        else:
            resp = requests.get(url, timeout=10, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            })
        return resp.status_code == 200
    except:
        return False

def get_bse_url_with_fallback() -> Optional[str]:
    """Try multiple BSE URLs until one works."""
    config = get_feed_config("BSE_Corporate")
    if not config:
        return None
    
    urls_to_try = [config["url"]] + config.get("alt_urls", [])
    
    for url in urls_to_try:
        if validate_feed_url(url, config.get("session_required", False), config.get("session")):
            return url
    return None