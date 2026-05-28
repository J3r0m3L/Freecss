"""SQLite access: WAL connections, schema init, and one-time seed loading.

Single-process, single-user (DESIGN.md §4) — a thread-local connection per
worker thread is plenty. WAL mode is essential because APScheduler writes while
the UI reads (§6 Notes).
"""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

import yaml

from server.config import config

_SCHEMA = Path(__file__).with_name("schema.sql")
_SEEDS = Path(__file__).with_name("seeds")
_local = threading.local()


def get_db() -> sqlite3.Connection:
    """Thread-local WAL connection with row access by name and FKs enforced."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(config.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        _local.conn = conn
    return conn


def rows(sql: str, params: tuple = ()) -> list[dict]:
    """Run a SELECT and return a list of plain dicts."""
    cur = get_db().execute(sql, params)
    return [dict(r) for r in cur.fetchall()]


def one(sql: str, params: tuple = ()) -> dict | None:
    cur = get_db().execute(sql, params)
    r = cur.fetchone()
    return dict(r) if r else None


def execute(sql: str, params: tuple = ()) -> sqlite3.Cursor:
    db = get_db()
    cur = db.execute(sql, params)
    db.commit()
    return cur


def init_db() -> None:
    """Create the schema (idempotent) and load seeds on an empty DB."""
    db = get_db()
    db.executescript(_SCHEMA.read_text())
    db.commit()
    _seed_factor_buckets()
    _seed_social_watch()


def _seed_factor_buckets() -> None:
    """Load the 80-bucket universe (§9). Representatives are picked later by PCA,
    so we insert buckets + candidate instruments but leave representative_id NULL."""
    if one("SELECT 1 FROM factor_bucket LIMIT 1"):
        return
    path = _SEEDS / "factor_buckets.yaml"
    if not path.exists():
        return
    data = yaml.safe_load(path.read_text()) or {}
    db = get_db()
    for bucket in data.get("buckets", []):
        kind = bucket["kind"]
        label = bucket["label"]
        cur = db.execute(
            "INSERT INTO factor_bucket(kind, label, active) VALUES(?,?,1)",
            (kind, label),
        )
        bucket_id = cur.lastrowid
        for sym in bucket.get("candidates", []):
            instrument_id = _ensure_instrument(db, sym, asset_class="etf")
            db.execute(
                "INSERT OR IGNORE INTO factor_bucket_candidate(bucket_id, instrument_id) "
                "VALUES(?,?)",
                (bucket_id, instrument_id),
            )
    db.commit()


def _seed_social_watch() -> None:
    """Load default curated X accounts (§10.3) if the table is empty."""
    if one("SELECT 1 FROM social_account_watch LIMIT 1"):
        return
    path = _SEEDS / "social_watch.yaml"
    if not path.exists():
        return
    data = yaml.safe_load(path.read_text()) or {}
    db = get_db()
    for acct in data.get("x_accounts", []):
        db.execute(
            "INSERT OR IGNORE INTO social_account_watch(source, handle, label) VALUES('x',?,?)",
            (acct["handle"], acct.get("label")),
        )
    db.commit()


def _ensure_instrument(db: sqlite3.Connection, symbol: str, *, asset_class: str) -> int:
    """Insert a bare instrument row if absent; return its id. Real metadata
    (sector/industry/profile) is populated later by meta_refresh / profile jobs."""
    row = db.execute("SELECT id FROM instrument WHERE symbol=?", (symbol,)).fetchone()
    if row:
        return row["id"]
    cur = db.execute(
        "INSERT INTO instrument(symbol, display_name, asset_class, data_adapter) "
        "VALUES(?,?,?,?)",
        (symbol, symbol, asset_class, config.data_adapter if config.data_adapter != "stub" else "massive"),
    )
    return cur.lastrowid


def get_setting(key: str, default=None):
    row = one("SELECT value_json FROM setting WHERE key=?", (key,))
    return json.loads(row["value_json"]) if row else default


def set_setting(key: str, value) -> None:
    execute(
        "INSERT INTO setting(key, value_json) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
        (key, json.dumps(value)),
    )
