# test_symbol_resolver_agent.py
from db import init_db
from symbol_resolver_agent import resolve_symbol_agent

init_db()

test_cases = [
    "K2 Infragen Limited",       # the real failure case
    "Reliance Industries Limited",  # should resolve easily, sanity check
    "CSM Technologies Limited",  # confirmed real, alerted today
    "Some Totally Fake Company That Does Not Exist Pvt Ltd",  # should return None
]

for name in test_cases:
    print(f"\nResolving: {name}")
    symbol = resolve_symbol_agent(name)
    print(f"  -> {symbol}")

print("\n=== Second pass (should be instant, cache hits) ===")
import time
for name in test_cases:
    start = time.time()
    symbol = resolve_symbol_agent(name)
    elapsed = time.time() - start
    print(f"{name}: {symbol} ({elapsed:.3f}s)")