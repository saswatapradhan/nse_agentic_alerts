"""

alert_service.py

Alert Delivery — Telegram Bot API integration.

Cost: $0. No message caps, no trial credit, no per-message fee.
Telegram's Bot API is a plain HTTPS endpoint — no SDK dependency needed
beyond `requests`.
"""
import requests
import time

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}/sendMessage"

PRIORITY_EMOJI = {
    "CRITICAL": "🔴",
    "HIGH": "🟠",
    "MEDIUM": "🟡",
    "LOW": "🟢",
}

SENTIMENT_EMOJI = {"POSITIVE": "📈", "NEGATIVE": "📉", "NEUTRAL": "➖"}


def format_alert_message(alert: dict) -> str:
    p_emoji = PRIORITY_EMOJI.get(alert["priority"], "⚪")
    s_emoji = SENTIMENT_EMOJI.get(alert["sentiment"], "")
    rupee_line = f"\n💰 ₹{alert['rupee_amount_cr']:.0f} Cr" if alert.get("rupee_amount_cr") else ""
    role = alert.get("acquisition_role", "NOT_APPLICABLE")
    role_line = f"\n🎭 Role: {role.title()}" if role != "NOT_APPLICABLE" else ""
    time_line = f"\n🕒 Filed: {alert.get('announcement_time', 'unknown')}"

    body = (
        f"{p_emoji} *{alert['priority']}* | {alert['symbol']}\n"
        f"{s_emoji} {alert['category'].replace('_', ' ').title()}"
        f"{role_line}\n\n"
        f"{alert['summary']}"
        f"{rupee_line}\n"
        f"🎯 Confidence: {alert['confidence']:.0f}%\n"
        f"↕️ Predicted: {alert['predicted_direction']}"
        f"{time_line}\n\n"
        f"_{alert.get('materiality_reasoning', '')}_"
    )

    spec = alert.get("trade_spec")
    if spec:
        body += (
            f"\n\n📊 *Suggested Trade Spec* (research-range based, not guaranteed)\n"
            f"Entry: ₹{spec['entry_price']}\n"
            f"Target: ₹{spec['target_price']} ({spec['target_pct']:+.1f}%)\n"
            f"Stop: ₹{spec['stop_price']} ({spec['stop_pct']:.1f}% risk)\n"
            f"Hold: {spec['holding_period_days']} days\n"
            f"R:R: {spec['risk_reward_ratio']}\n"
            f"Basis: {spec['range_basis']}"
        )
        if spec.get("caution_note"):
            body += f"\n⚠️ {spec['caution_note']}"

    return body


def _post_message(text: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[alerts] Telegram credentials not configured — printing instead:")
        print(text)
        return False

    url = TELEGRAM_API_BASE.format(token=TELEGRAM_BOT_TOKEN)
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }

    for attempt in range(3):
        try:
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                print(f"[alerts] Sent via Telegram")
                return True
            else:
                print(f"[alerts] Telegram API returned {resp.status_code}: {resp.text}")
        except requests.RequestException as e:
            print(f"[alerts] Attempt {attempt+1} failed: {e}")
        if attempt < 2:
            time.sleep(2 ** attempt)
    return False


def send_whatsapp_alert(alert: dict) -> bool:
    """Name kept for compatibility with main.py. Delivers via Telegram."""
    body = format_alert_message(alert)
    return _post_message(body)


def send_daily_summary(summary: dict):
    total = summary.get("total", 0) or 0
    hits = summary.get("hits", 0) or 0
    misses = summary.get("misses", 0) or 0
    hit_rate = f"{(hits/total*100):.0f}%" if total else "N/A"

    body = (
        f"📊 *Yesterday's Alert Recap*\n\n"
        f"Total alerts: {total}\n"
        f"✅ Hits: {hits}\n"
        f"❌ Misses: {misses}\n"
        f"📈 Hit rate: {hit_rate}\n\n"
        f"_System is recalibrating category thresholds based on this data._"
    )
    _post_message(body)