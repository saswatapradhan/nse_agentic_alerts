"""

db.py


Database layer — SQLite (free, zero-ops).
Stores every alert, its GPT-derived prediction, and later the
actual price outcome at 1h / 24h / 48h checkpoints so the system
can self-learn category-level accuracy from the day of deployment
forward (no backfill of historical data, per user's requirement).
"""
import sqlite3
import json
from datetime import datetime, timezone
from contextlib import contextmanager

DB_PATH = "data/alerts.db"


SCHEMA = """
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    symbol TEXT NOT NULL,
    category TEXT NOT NULL,          -- e.g. ACQUISITION, RESULTS, INSIDER_BUY
    sentiment TEXT NOT NULL,         -- POSITIVE / NEGATIVE / NEUTRAL
    priority TEXT NOT NULL,          -- CRITICAL / HIGH / MEDIUM / LOW
    confidence REAL NOT NULL,        -- GPT's 0-100 confidence
    predicted_direction TEXT NOT NULL, -- UP / DOWN / FLAT
    rupee_amount_cr REAL,
    subject TEXT,
    summary TEXT,
    pdf_source_url TEXT,
    price_at_alert REAL,
    whatsapp_sent INTEGER DEFAULT 0,
    price_1h REAL,
    price_24h REAL,
    price_48h REAL,
    outcome_hit INTEGER,             -- 1 = predicted direction confirmed >=1% move, 0 = miss, NULL = pending
    raw_llm_json TEXT
);

CREATE TABLE IF NOT EXISTS category_accuracy (
    category TEXT PRIMARY KEY,
    total_alerts INTEGER DEFAULT 0,
    hits INTEGER DEFAULT 0,
    hit_rate REAL DEFAULT 0.5,       -- Bayesian prior = 50% until data comes in
    current_confidence_threshold REAL DEFAULT 60,
    last_updated TEXT
);

CREATE TABLE IF NOT EXISTS processed_pdfs (
    pdf_url TEXT PRIMARY KEY,
    processed_at TEXT NOT NULL
);


CREATE TABLE IF NOT EXISTS company_research (
    symbol TEXT PRIMARY KEY,
    data_json TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    valid_until TEXT NOT NULL
);


"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def already_processed(pdf_url: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM processed_pdfs WHERE pdf_url = ?", (pdf_url,)
        ).fetchone()
        return row is not None


def mark_processed(pdf_url: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO processed_pdfs (pdf_url, processed_at) VALUES (?, ?)",
            (pdf_url, datetime.now(timezone.utc).isoformat()),
        )


def insert_alert(alert: dict) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO alerts
            (created_at, symbol, category, sentiment, priority, confidence,
             predicted_direction, rupee_amount_cr, subject, summary,
             pdf_source_url, price_at_alert, raw_llm_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                datetime.now(timezone.utc).isoformat(),
                alert["symbol"], alert["category"], alert["sentiment"],
                alert["priority"], alert["confidence"], alert["predicted_direction"],
                alert.get("rupee_amount_cr"), alert["subject"], alert["summary"],
                alert.get("pdf_source_url"), alert.get("price_at_alert"),
                json.dumps(alert.get("raw_llm_json", {})),
            ),
        )
        return cur.lastrowid


def mark_whatsapp_sent(alert_id: int):
    with get_conn() as conn:
        conn.execute("UPDATE alerts SET whatsapp_sent = 1 WHERE id = ?", (alert_id,))


def get_pending_price_checks(hours_elapsed_min: float):
    """Alerts created more than N hours ago that haven't had that checkpoint filled."""
    with get_conn() as conn:
        return conn.execute(
            """SELECT * FROM alerts
               WHERE created_at <= datetime('now', ?)
               AND outcome_hit IS NULL""",
            (f"-{hours_elapsed_min} hours",),
        ).fetchall()


def update_price_checkpoint(alert_id: int, checkpoint: str, price: float):
    col = {"1h": "price_1h", "24h": "price_24h", "48h": "price_48h"}[checkpoint]
    with get_conn() as conn:
        conn.execute(f"UPDATE alerts SET {col} = ? WHERE id = ?", (price, alert_id))


def finalize_outcome(alert_id: int, hit: bool):
    with get_conn() as conn:
        conn.execute("UPDATE alerts SET outcome_hit = ? WHERE id = ?", (int(hit), alert_id))


def get_category_threshold(category: str, default: float = 60.0) -> float:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT current_confidence_threshold FROM category_accuracy WHERE category = ?",
            (category,),
        ).fetchone()
        return row["current_confidence_threshold"] if row else default


def update_category_accuracy(category: str, step: float = 5.0, min_samples: int = 5):
    """Recompute hit rate; nudge confidence threshold based on the self-learning loop."""
    with get_conn() as conn:
        stats = conn.execute(
            """SELECT COUNT(*) as total, SUM(outcome_hit) as hits
               FROM alerts WHERE category = ? AND outcome_hit IS NOT NULL""",
            (category,),
        ).fetchone()
        total, hits = stats["total"] or 0, stats["hits"] or 0
        if total < min_samples:
            return  # not enough data yet

        hit_rate = hits / total
        row = conn.execute(
            "SELECT current_confidence_threshold FROM category_accuracy WHERE category = ?",
            (category,),
        ).fetchone()
        current = row["current_confidence_threshold"] if row else 60.0

        if hit_rate < 0.40:
            new_threshold = min(95, current + step)
        elif hit_rate > 0.70:
            new_threshold = max(40, current - step)
        else:
            new_threshold = current

        conn.execute(
            """INSERT INTO category_accuracy (category, total_alerts, hits, hit_rate,
               current_confidence_threshold, last_updated)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(category) DO UPDATE SET
                 total_alerts=excluded.total_alerts,
                 hits=excluded.hits,
                 hit_rate=excluded.hit_rate,
                 current_confidence_threshold=excluded.current_confidence_threshold,
                 last_updated=excluded.last_updated""",
            (category, total, hits, hit_rate, new_threshold,
             datetime.now(timezone.utc).isoformat()),
        )


def daily_summary() -> dict:
    with get_conn() as conn:
        row = conn.execute(
            """SELECT COUNT(*) as total,
                      SUM(CASE WHEN outcome_hit=1 THEN 1 ELSE 0 END) as hits,
                      SUM(CASE WHEN outcome_hit=0 THEN 1 ELSE 0 END) as misses
               FROM alerts WHERE created_at >= datetime('now', '-1 day')"""
        ).fetchone()
        return dict(row)