"""
test_rss_sources.py

Test all RSS sources with proper session handling.
"""
import feedparser
import requests
from rss_feeds import RSS_FEEDS, get_business_standard_session

def test_rss_source(name: str, config: dict):
    """Test a single RSS source."""
    print(f"\n=== {name} ===")
    print(f"URL: {config['url']}")
    print(f"Enabled: {config.get('enabled', True)}")
    
    if not config.get('enabled', True):
        print("SKIP: Source disabled")
        return
    
    try:
        # Use session if required
        if config.get('session_required', False) and config.get('session'):
            session = config['session']
            resp = session.get(config['url'], timeout=10)
        else:
            resp = requests.get(config['url'], timeout=10, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            })
        
        print(f"HTTP status: {resp.status_code}")
        if resp.status_code != 200:
            # Try alternative URLs if this is BSE
            if name == "BSE_Corporate" and config.get('alt_urls'):
                print("Trying alternative URLs...")
                for alt_url in config['alt_urls']:
                    print(f"  Trying: {alt_url}")
                    alt_resp = requests.get(alt_url, timeout=10, headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
                    })
                    if alt_resp.status_code == 200:
                        print(f"  ✓ Found working URL: {alt_url}")
                        resp = alt_resp
                        break
                else:
                    print("SKIP: All BSE URLs failed")
                    return
            else:
                print("SKIP: non-200 response")
                return
        
        # Parse feed
        feed = feedparser.parse(resp.content)
        print(f"Entries found: {len(feed.entries)}")
        
        if feed.bozo:
            print(f"WARNING: feedparser flagged malformed XML: {feed.bozo_exception}")
        
        if feed.entries:
            first = feed.entries[0]
            print(f"Sample title: {first.get('title', 'MISSING')}")
            print(f"Sample link: {first.get('link', 'MISSING')}")
            published = first.get('published', first.get('pubDate', 'MISSING'))
            print(f"Sample published: {published}")
            
            # Test timestamp quality
            if published and published != 'MISSING':
                # Simple check if it has timezone
                if '+' in published or 'GMT' in published or 'UTC' in published:
                    print("✓ Timestamp includes timezone - good for correlation")
                else:
                    print("⚠️ Timestamp might lack timezone - may need parsing")
        else:
            print("NO ENTRIES FOUND")
            
    except requests.RequestException as e:
        print(f"FAILED: {e}")
    except Exception as e:
        print(f"ERROR: {e}")

def main():
    """Test all RSS sources."""
    print("Testing RSS Sources...")
    print("=" * 50)
    
    for name, config in RSS_FEEDS.items():
        test_rss_source(name, config)
    
    print("\n" + "=" * 50)
    print("Test complete!")
    print("\nSummary:")
    working_sources = []
    for name, config in RSS_FEEDS.items():
        if config.get('enabled', True):
            working_sources.append(name)
    print(f"✓ Total enabled sources: {len(working_sources)}")
    print(f"Sources: {', '.join(working_sources)}")
    
    print("\nNext steps:")
    print("1. If all sources show 'Entries found', run: python ingestion.py")
    print("2. To check specific source quality, use: python test_rss_sources.py --source ET_Stocks")

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--source":
        source_name = sys.argv[2]
        if source_name in RSS_FEEDS:
            test_rss_source(source_name, RSS_FEEDS[source_name])
        else:
            print(f"Source '{source_name}' not found")
    else:
        main()