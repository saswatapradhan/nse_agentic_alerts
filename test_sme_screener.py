# test_sme_screener.py
from db import init_db
from sme_screener import check_sme_membership, get_multibagger_score

init_db()

print("=== SME membership check: K2 Infragen ===")
symbol, is_sme = check_sme_membership("K2 Infragen Limited")
print(f"is_sme={is_sme}, symbol={symbol}")

if is_sme:
    print("\n=== Multibagger score: K2 Infragen ===")
    result = get_multibagger_score(symbol or "K2INFRA", company_name="K2 Infragen Limited")
    if result:
        print(f"Score: {result['score']}/{result['max_score']}")
        for criterion, details in result["breakdown"].items():
            print(f"  {criterion}: {details}")
    else:
        print("Scoring failed")

print("\n=== Non-SME sanity check: Reliance Industries (should be False) ===")
symbol2, is_sme2 = check_sme_membership("Reliance Industries Limited")
print(f"is_sme={is_sme2}, symbol={symbol2}")

print("\n=== Second pass on K2 Infragen (should hit cache, be fast) ===")
import time
start = time.time()
symbol3, is_sme3 = check_sme_membership("K2 Infragen Limited")
print(f"is_sme={is_sme3}, symbol={symbol3} ({time.time()-start:.3f}s)")