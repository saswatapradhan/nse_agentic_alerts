from db import init_db
from ingestion import poll_new_announcements
from false_positive_filters import apply_filters
from agentic_analyzer import analyze_pdf_text, decide_alert
from alert_service import send_whatsapp_alert

init_db()

print("Polling NSE/BSE for new announcements...")
items = poll_new_announcements()
print(f"Found {len(items)} new (unprocessed) announcements\n")

for item in items:
    symbol = item["symbol"]
    subject = item["subject"]
    pdf_text = item["pdf_text"]

    print(f"--- Processing: {symbol} ---")
    print(f"Subject: {subject}")

    # Stage 1: cheap filters
    filt = apply_filters(subject, pdf_text[:500], symbol, set())  # empty watchlist = allow all, for this test
    print(f"Filter result: skip={filt.skip} | {filt.reason}")

    if filt.skip:
        print()
        continue

    # Stage 2: GPT analysis
    print("Sending to GPT...")
    signal = analyze_pdf_text(pdf_text, symbol_hint=symbol, subject_hint=subject)

    if signal is None:
        print("GPT analysis failed\n")
        continue

    print(f"Category: {signal['category']} | Confidence: {signal['confidence']} | False positive: {signal['is_false_positive']}")

    decision = decide_alert(signal)
    print(f"Decision: {decision}")

    if decision["should_alert"]:
        alert = {
            "symbol": symbol,
            "category": signal["category"],
            "sentiment": signal["sentiment"],
            "priority": decision["priority"],
            "confidence": signal["confidence"],
            "predicted_direction": signal["predicted_direction"],
            "rupee_amount_cr": signal.get("rupee_amount_cr", 0),
            "summary": signal["summary"],
            "materiality_reasoning": signal.get("materiality_reasoning", ""),
        }
        sent = send_whatsapp_alert(alert)
        print(f"Telegram alert sent: {sent}")

    print()

print("Pipeline test complete.")