"""

alert_service.py

Alert Delivery — Telegram Bot API integration.

Cost: $0. No message caps, no trial credit, no per-message fee.
Telegram's Bot API is a plain HTTPS endpoint — no SDK dependency needed
beyond `requests`.

Message format shows: NET target % (after Kotak Neo fees + STCG, via
cost_model.py through trade_spec.py) alongside gross %, a clear
worthwhile/marginal flag, the news_led confidence-bump reason when
applicable, SME multibagger score when applicable, sector + top-SWOT
snippet from the Research Agent for HIGH/CRITICAL alerts, and the
Trade Decision Agent's mechanism-aware review (CASH_DELIVERY_MULTIDAY
vs INTRADAY_SHORT_MIS vs NOT_TRADEABLE) with correctly-computed net %
per mechanism.
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

MECHANISM_LABEL = {
    "CASH_DELIVERY_MULTIDAY": "Cash delivery (multi-day)",
    "INTRADAY_SHORT_MIS": "Intraday short (MIS/CO)",
    "NOT_TRADEABLE": "Not tradeable",
}

RECOMMENDATION_EMOJI = {"CONFIRM": "✅", "ADJUST": "🔧", "DO_NOT_TRADE": "🚫"}


def format_alert_message(alert: dict) -> str:
    p_emoji = PRIORITY_EMOJI.get(alert["priority"], "⚪")
    s_emoji = SENTIMENT_EMOJI.get(alert["sentiment"], "")
    rupee_line = f"\n💰 ₹{alert['rupee_amount_cr']:.0f} Cr" if alert.get("rupee_amount_cr") else ""
    role = alert.get("acquisition_role", "NOT_APPLICABLE")
    role_line = f"\n🎭 Role: {role.title()}" if role != "NOT_APPLICABLE" else ""
    time_line = f"\n🕒 Filed: {alert.get('announcement_time', 'unknown')}"

    # news_led confidence bump — shown explicitly so the "why" behind
    # confidence is visible, per the correlation_engine.py integration.
    news_led_line = ""
    if alert.get("news_led") and alert.get("confidence_bump_reason"):
        news_led_line = f"\n⚡ {alert['confidence_bump_reason']}"

    # SME multibagger score — always shown when applicable, per user
    # decision (no minimum-score gate; score visible regardless of value).
    sme_line = ""
    if alert.get("is_sme"):
        score_info = alert.get("sme_score")
        if score_info:
            sme_line = (
                f"\n🌱 SME (Emerge) stock | Multibagger score: "
                f"{score_info['score']}/{score_info['max_score']}"
            )
        else:
            sme_line = "\n🌱 SME (Emerge) stock | Multibagger score: unavailable"

    # Research Agent output — sector/mcap_tier + top strength/threat,
    # only populated for HIGH/CRITICAL alerts (see main_v3.py gating).
    research_line = ""
    if alert.get("sector") or alert.get("mcap_tier"):
        research_line = f"\n🏢 {alert.get('sector', 'Unknown sector')} | {alert.get('mcap_tier', 'Unknown tier')}"
        swot = alert.get("research_swot")
        if swot and swot.get("strengths"):
            research_line += f"\n💪 {swot['strengths'][0]}"
        if swot and swot.get("threats"):
            research_line += f"\n⚠️ {swot['threats'][0]}"

    body = (
        f"{p_emoji} *{alert['priority']}* | {alert['symbol']}\n"
        f"{s_emoji} {alert['category'].replace('_', ' ').title()}"
        f"{role_line}\n\n"
        f"{alert['summary']}"
        f"{rupee_line}\n"
        f"🎯 Confidence: {alert['confidence']:.0f}%"
        f"{news_led_line}"
        f"{sme_line}"
        f"{research_line}\n"
        f"↕️ Predicted: {alert['predicted_direction']}"
        f"{time_line}\n\n"
        f"_{alert.get('materiality_reasoning', '')}_"
    )

    spec = alert.get("trade_spec")
    if spec:
        # NET is the headline number now — gross shown for reference only.
        # This is the MULTI-DAY numerical spec, before the Trade Decision
        # Agent's mechanism-aware review below (which may override it
        # entirely, e.g. for a DOWN signal that needs an intraday path).
        worthwhile_tag = "✅ Net-worthwhile" if spec.get("net_worthwhile") else "⚠️ MARGINAL after costs+tax"

        body += (
            f"\n\n📊 *Numerical Spec* (research-range based, pre-review)\n"
            f"Entry: ₹{spec['entry_price']}\n"
            f"Target: ₹{spec['target_price']} "
            f"(gross {spec['target_pct']:+.1f}%, NET {spec['net_target_pct']:+.2f}%)\n"
            f"Stop: ₹{spec['stop_price']} ({spec['stop_pct']:.1f}% risk)\n"
            f"Hold: {spec['holding_period_days']} days\n"
            f"R:R: {spec['risk_reward_ratio']}\n"
            f"Basis: {spec['range_basis']}\n"
            f"{worthwhile_tag}"
        )
        cost_breakdown = spec.get("cost_breakdown")
        if cost_breakdown:
            total_drag = cost_breakdown["total_transaction_costs"] + cost_breakdown["stcg_tax"]
            body += (
                f"\nBreakeven: ₹{cost_breakdown['breakeven_price']} "
                f"(costs+tax ≈ ₹{total_drag:.0f} on this position)"
            )
        if spec.get("caution_note"):
            body += f"\n⚠️ {spec['caution_note']}"

        # Trade Decision Agent — the FINAL word, reviews the numerical
        # spec above against live web context and determines the actual
        # executable mechanism. This is what the user should act on,
        # not the raw numerical spec above (which assumes multi-day
        # cash delivery regardless of direction).
        review = alert.get("decision_review")
        if review:
            rec = review.get("recommendation", "")
            mechanism = review.get("trade_mechanism", "")
            rec_emoji = RECOMMENDATION_EMOJI.get(rec, "")
            mechanism_label = MECHANISM_LABEL.get(mechanism, mechanism)

            body += f"\n\n{rec_emoji} *GPT Review: {rec}* — {mechanism_label}"
            body += f"\n{review.get('execution_feasibility', '')}"

            if rec == "ADJUST":
                if review.get("adjusted_entry"):
                    entry_label = "Sell (short)" if mechanism == "INTRADAY_SHORT_MIS" else "Entry"
                    body += f"\n{entry_label}: ₹{review['adjusted_entry']}"
                if review.get("adjusted_target"):
                    target_label = "Cover (buy back)" if mechanism == "INTRADAY_SHORT_MIS" else "Target"
                    body += f"\n{target_label}: ₹{review['adjusted_target']}"
                if review.get("adjusted_stop"):
                    body += f"\nStop: ₹{review['adjusted_stop']}"
                if review.get("adjusted_holding_days"):
                    body += f"\nHold: {review['adjusted_holding_days']}"

            if review.get("net_pct") is not None:
                body += f"\n*NET: {review['net_pct']:+.2f}%* ({review.get('net_pct_source', '')})"

            if review.get("intraday_risk_note"):
                body += f"\n⚠️ *Intraday risk*: {review['intraday_risk_note']}"

            if review.get("reasoning"):
                body += f"\n_{review['reasoning']}_"
            if review.get("confidence_in_recommendation"):
                body += f"\n(review confidence: {review['confidence_in_recommendation']})"
        else:
            body += "\n\n⚠️ _GPT review unavailable — treat the numerical spec above with extra caution, especially for DOWN/short signals which it cannot execute as a multi-day cash position._"

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
    """Name kept for compatibility with main.py/main_v3.py. Delivers via Telegram."""
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