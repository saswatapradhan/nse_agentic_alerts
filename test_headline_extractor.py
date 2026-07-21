# test_headline_extractor.py
from headline_extractor import extract_headline_info

test_headlines = [
    ("Sobha Ltd Q1 Results: Profit jumps over 3-fold to Rs 51 crore, revenue rises to Rs 1,330 crore", ""),
    ("Bonus bonanza! Aastha Spintex to consider bonus issue, dividend less than a month since debut on July 23", ""),
    ("Suzlon Energy board to consider Q1FY27 results on July 28; shares down 10% in July", ""),
    ("US stocks to buy for short term: From Nvidia to Netflix- Appreciate CEO suggests picking these 5 shares", ""),
    ("US stock market today: Wall Street futures gain as easing oil prices offset lingering Middle East tensions", ""),
]

for headline, summary in test_headlines:
    result = extract_headline_info(headline, summary)
    print(f"\nHeadline: {headline[:70]}...")
    print(f"  company_name:     {result['company_name']}")
    print(f"  relevance:        {result['relevance']}")
    print(f"  category_hint:    {result['category_hint']}")
    print(f"  resolved_symbol:  {result['resolved_symbol']}")