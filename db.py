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
from datetime import datetime, timezone, timedelta
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

CREATE TABLE IF NOT EXISTS outcomes_bucketed (
    category TEXT NOT NULL,
    sector TEXT NOT NULL,
    mcap_tier TEXT NOT NULL,          -- LARGE_CAP / MID_CAP / SMALL_CAP / MICRO_CAP
    total_alerts INTEGER DEFAULT 0,
    hits INTEGER DEFAULT 0,
    hit_rate REAL DEFAULT 0.0,
    avg_magnitude_pct REAL,           -- mean actual % move across all outcomes in this bucket
    avg_days_to_hit REAL,             -- mean days taken to reach the 3-5% target, for hits only
    last_updated TEXT,
    PRIMARY KEY (category, sector, mcap_tier)
);

CREATE TABLE IF NOT EXISTS feedback_raw (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    raw_text TEXT NOT NULL,
    FOREIGN KEY (alert_id) REFERENCES alerts(id)
);

CREATE TABLE IF NOT EXISTS feedback_structured (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    feedback_raw_id INTEGER NOT NULL,
    alert_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    direction_correct INTEGER,        -- 1/0/NULL (NULL = unclear from user's text)
    magnitude_assessment TEXT,        -- OVERESTIMATED / UNDERESTIMATED / ACCURATE / UNCLEAR
    timing_assessment TEXT,           -- TOO_SLOW / TOO_FAST / ACCURATE / UNCLEAR
    attribution TEXT,                 -- ANNOUNCEMENT_DRIVEN / MARKET_WIDE / UNRELATED_NEWS / UNCLEAR
    structured_json TEXT NOT NULL,    -- full GPT interpretation, for anything not captured in columns above
    FOREIGN KEY (feedback_raw_id) REFERENCES feedback_raw(id),
    FOREIGN KEY (alert_id) REFERENCES alerts(id)
);

CREATE TABLE IF NOT EXISTS rule_change_proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    category TEXT NOT NULL,
    sector TEXT NOT NULL,
    mcap_tier TEXT NOT NULL,
    old_range_min REAL,
    old_range_max REAL,
    new_range_min REAL,
    new_range_max REAL,
    sample_size INTEGER NOT NULL,
    hit_rate REAL NOT NULL,
    status TEXT DEFAULT 'PENDING',    -- PENDING / APPROVED / REJECTED
    reviewed_at TEXT
);

CREATE TABLE IF NOT EXISTS scraper_items_cache (
    link TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    company_name TEXT,
    subject TEXT NOT NULL,
    text_snippet TEXT,
    category_hint TEXT,
    published TEXT NOT NULL,
    source TEXT NOT NULL,
    extracted_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS symbol_resolution_cache (
    raw_name TEXT PRIMARY KEY,
    resolved_symbol TEXT,             -- NULL if genuinely not found in universe
    resolved_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sme_membership_cache (
    raw_name TEXT PRIMARY KEY,
    is_sme INTEGER NOT NULL,
    sme_symbol TEXT,
    checked_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sme_multibagger_cache (
    symbol TEXT PRIMARY KEY,
    score INTEGER NOT NULL,
    max_score INTEGER NOT NULL,
    breakdown_json TEXT NOT NULL,
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


def _migrate_alerts_correlation_columns():
    """Adds columns to an EXISTING alerts table if they're missing.
    CREATE TABLE IF NOT EXISTS in SCHEMA only helps fresh installs —
    this handles your already-existing alerts.db safely and idempotently.
    Covers: correlation-bump tracking (news_led/hours_lead/reason) and
    Research Agent output (sector/mcap_tier)."""
    with get_conn() as conn:
        existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(alerts)").fetchall()}
        if "news_led" not in existing_cols:
            conn.execute("ALTER TABLE alerts ADD COLUMN news_led INTEGER")
        if "hours_lead" not in existing_cols:
            conn.execute("ALTER TABLE alerts ADD COLUMN hours_lead REAL")
        if "confidence_bump_reason" not in existing_cols:
            conn.execute("ALTER TABLE alerts ADD COLUMN confidence_bump_reason TEXT")
        if "sector" not in existing_cols:
            conn.execute("ALTER TABLE alerts ADD COLUMN sector TEXT")
        if "mcap_tier" not in existing_cols:
            conn.execute("ALTER TABLE alerts ADD COLUMN mcap_tier TEXT")


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)
    _migrate_alerts_correlation_columns()


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
             pdf_source_url, price_at_alert, raw_llm_json,
             news_led, hours_lead, confidence_bump_reason, sector, mcap_tier)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                datetime.now(timezone.utc).isoformat(),
                alert["symbol"], alert["category"], alert["sentiment"],
                alert["priority"], alert["confidence"], alert["predicted_direction"],
                alert.get("rupee_amount_cr"), alert["subject"], alert["summary"],
                alert.get("pdf_source_url"), alert.get("price_at_alert"),
                json.dumps(alert.get("raw_llm_json", {})),
                alert.get("news_led"), alert.get("hours_lead"),
                alert.get("confidence_bump_reason"),
                alert.get("sector"), alert.get("mcap_tier"),
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


def upsert_outcome_bucket(category: str, sector: str, mcap_tier: str,
                           total: int, hits: int, avg_magnitude: float | None,
                           avg_days: float | None):
    hit_rate = hits / total if total else 0.0
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO outcomes_bucketed
               (category, sector, mcap_tier, total_alerts, hits, hit_rate,
                avg_magnitude_pct, avg_days_to_hit, last_updated)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(category, sector, mcap_tier) DO UPDATE SET
                 total_alerts=excluded.total_alerts,
                 hits=excluded.hits,
                 hit_rate=excluded.hit_rate,
                 avg_magnitude_pct=excluded.avg_magnitude_pct,
                 avg_days_to_hit=excluded.avg_days_to_hit,
                 last_updated=excluded.last_updated""",
            (category, sector, mcap_tier, total, hits, hit_rate,
             avg_magnitude, avg_days, datetime.now(timezone.utc).isoformat()),
        )


def get_outcome_bucket(category: str, sector: str, mcap_tier: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            """SELECT * FROM outcomes_bucketed
               WHERE category=? AND sector=? AND mcap_tier=?""",
            (category, sector, mcap_tier),
        ).fetchone()
    return dict(row) if row else None


def insert_feedback_raw(alert_id: int, raw_text: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO feedback_raw (alert_id, created_at, raw_text) VALUES (?,?,?)",
            (alert_id, datetime.now(timezone.utc).isoformat(), raw_text),
        )
        return cur.lastrowid


def insert_feedback_structured(feedback_raw_id: int, alert_id: int, structured: dict) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO feedback_structured
               (feedback_raw_id, alert_id, created_at, direction_correct,
                magnitude_assessment, timing_assessment, attribution, structured_json)
               VALUES (?,?,?,?,?,?,?,?)""",
            (feedback_raw_id, alert_id, datetime.now(timezone.utc).isoformat(),
             structured.get("direction_correct"), structured.get("magnitude_assessment"),
             structured.get("timing_assessment"), structured.get("attribution"),
             json.dumps(structured)),
        )
        return cur.lastrowid


def insert_rule_proposal(category: str, sector: str, mcap_tier: str,
                          old_range: tuple, new_range: tuple,
                          sample_size: int, hit_rate: float) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO rule_change_proposals
               (created_at, category, sector, mcap_tier,
                old_range_min, old_range_max, new_range_min, new_range_max,
                sample_size, hit_rate, status)
               VALUES (?,?,?,?,?,?,?,?,?,?,'PENDING')""",
            (datetime.now(timezone.utc).isoformat(), category, sector, mcap_tier,
             old_range[0], old_range[1], new_range[0], new_range[1],
             sample_size, hit_rate),
        )
        return cur.lastrowid


def get_pending_proposals() -> list:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM rule_change_proposals WHERE status='PENDING'"
        ).fetchall()


def resolve_proposal(proposal_id: int, approved: bool):
    with get_conn() as conn:
        conn.execute(
            "UPDATE rule_change_proposals SET status=?, reviewed_at=? WHERE id=?",
            ("APPROVED" if approved else "REJECTED",
             datetime.now(timezone.utc).isoformat(), proposal_id),
        )


def already_extracted_scraper_item(link: str) -> bool:
    """Dedup check for rss_ingestion.py — has this link already gone
    through headline_extractor.py's GPT call? Prevents re-running
    extraction on the same headline every poll cycle."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM scraper_items_cache WHERE link = ?", (link,)
        ).fetchone()
        return row is not None


def cache_scraper_item(item: dict):
    """Stores an already-extracted scraper item so it remains available
    for correlation matching across multiple poll cycles, even after
    dedup prevents it from being re-extracted."""
    with get_conn() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO scraper_items_cache
               (link, symbol, company_name, subject, text_snippet,
                category_hint, published, source, extracted_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (item["link"], item["symbol"], item.get("company_name"),
             item["subject"], item.get("text_snippet"), item.get("category_hint"),
             item["published"], item["source"],
             datetime.now(timezone.utc).isoformat()),
        )


def get_recent_scraper_items(hours: float = 6.0) -> list[dict]:
    """Pulls all cached scraper items from the last N hours, regardless
    of which poll cycle originally extracted them — this is what
    correlation_engine.py's matching actually needs."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM scraper_items_cache
               WHERE extracted_at >= datetime('now', ?)""",
            (f"-{hours} hours",),
        ).fetchall()
        return [dict(row) for row in rows]


def get_cached_symbol_resolution(raw_name: str):
    """Returns (found: bool, symbol: str|None). found=False means never
    looked up before; found=True with symbol=None means previously
    confirmed NOT in the universe (still a cache hit — don't re-ask GPT)."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT resolved_symbol FROM symbol_resolution_cache WHERE raw_name = ?",
            (raw_name,),
        ).fetchone()
    if row is None:
        return False, None
    return True, row["resolved_symbol"]


def cache_symbol_resolution(raw_name: str, resolved_symbol: str | None):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO symbol_resolution_cache (raw_name, resolved_symbol, resolved_at)
               VALUES (?,?,?)
               ON CONFLICT(raw_name) DO UPDATE SET
                 resolved_symbol=excluded.resolved_symbol,
                 resolved_at=excluded.resolved_at""",
            (raw_name, resolved_symbol, datetime.now(timezone.utc).isoformat()),
        )


def get_cached_sme_membership(raw_name: str):
    """Returns (found: bool, is_sme: bool, sme_symbol: str|None)."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT is_sme, sme_symbol FROM sme_membership_cache WHERE raw_name = ?",
            (raw_name,),
        ).fetchone()
    if row is None:
        return False, False, None
    return True, bool(row["is_sme"]), row["sme_symbol"]


def cache_sme_membership(raw_name: str, is_sme: bool, sme_symbol: str | None):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO sme_membership_cache (raw_name, is_sme, sme_symbol, checked_at)
               VALUES (?,?,?,?)
               ON CONFLICT(raw_name) DO UPDATE SET
                 is_sme=excluded.is_sme, sme_symbol=excluded.sme_symbol,
                 checked_at=excluded.checked_at""",
            (raw_name, int(is_sme), sme_symbol, datetime.now(timezone.utc).isoformat()),
        )


def get_cached_multibagger_score(symbol: str, ignore_expiry: bool = False) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM sme_multibagger_cache WHERE symbol = ?", (symbol,)
        ).fetchone()
    if row is None:
        return None
    if not ignore_expiry:
        valid_until = datetime.fromisoformat(row["valid_until"])
        if datetime.now(timezone.utc) > valid_until:
            return None
    return {
        "score": row["score"],
        "max_score": row["max_score"],
        "breakdown": json.loads(row["breakdown_json"]),
    }


def cache_multibagger_score(symbol: str, score: int, max_score: int, breakdown: dict, cache_days: int = 30):
    now = datetime.now(timezone.utc)
    valid_until = now + timedelta(days=cache_days)
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO sme_multibagger_cache
               (symbol, score, max_score, breakdown_json, generated_at, valid_until)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(symbol) DO UPDATE SET
                 score=excluded.score, max_score=excluded.max_score,
                 breakdown_json=excluded.breakdown_json,
                 generated_at=excluded.generated_at, valid_until=excluded.valid_until""",
            (symbol, score, max_score, json.dumps(breakdown), now.isoformat(), valid_until.isoformat()),
        )