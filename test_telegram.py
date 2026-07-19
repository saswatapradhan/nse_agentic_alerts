
from alert_service import _post_message

result = _post_message("🚀 Test alert from your trading system! If you see this, Telegram delivery works.")
print(f"\nDelivery success: {result}")