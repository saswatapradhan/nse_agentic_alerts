from symbol_lookup import find_symbol

tests = [
    "Sambhv Steel Tubes Limited",  # not in Nifty 500 - should return None
    "Tata Consultancy Services Limited",
    "Infosys Limited",
    "Britannia Industries Limited",
]

for name in tests:
    symbol = find_symbol(name)
    print(f"{name:40} -> {symbol}")