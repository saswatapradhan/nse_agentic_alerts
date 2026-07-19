from self_learning import get_current_price

# Direct symbol - should work immediately
price = get_current_price("TCS")
print(f"TCS current price: Rs.{price}")

# Full company name - should resolve via fuzzy lookup fallback
price2 = get_current_price("Infosys Limited")
print(f"Infosys Limited current price: Rs.{price2}")

# Genuinely outside Nifty 500 - should correctly return None, not crash
price3 = get_current_price("Sambhv Steel Tubes Limited")
print(f"Sambhv Steel Tubes current price: {price3}")