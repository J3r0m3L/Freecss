"""Buckets API (Phase 5 — candidate-basket editor, DESIGN.md §16).

Read + write surface for the 80-bucket universe. Users add or remove ETFs from
a bucket's candidate basket and can trigger an on-demand PCA refit for that
bucket alone (no need to wait for the quarterly cron).

Endpoints:
  GET    /api/buckets                        — all buckets + rep summary
  GET    /api/buckets/<bid>                  — one bucket + candidates + loadings
  POST   /api/buckets/<bid>/candidates       — body {symbol} adds an ETF to the basket
  DELETE /api/buckets/<bid>/candidates/<sym> — removes (won't drop the current rep)
  POST   /api/buckets/<bid>/refit_pca        — re-run PCA *for this bucket only*
"""
from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from server.adapters.massive_daily import fetch_daily_bars
from server.analytics.bucket_pca import DEFAULT_LOOKBACK_DAYS, fit_bucket
from server.db import execute, one, rows
from server.jobs.historical_bars_warmup import _persist as persist_daily_bars

log = logging.getLogger("deleveraging_watch.api.buckets")

bp = Blueprint("buckets", __name__, url_prefix="/api")


def _bucket_view(r: dict) -> dict:
    return {
        "id": r["id"],
        "kind": r["kind"],
        "label": r["label"],
        "active": bool(r["active"]),
        "pc1_var_explained": r["pc1_var_explained"],
        "selected_at": r["selected_at"],
        "representative_id": r["representative_id"],
        "representative_symbol": r["rep_symbol"],
    }


def _candidate_view(r: dict) -> dict:
    return {
        "instrument_id": r["instrument_id"],
        "symbol": r["symbol"],
        "pc1_loading": r["pc1_loading"],
        "last_pca_at": r["last_pca_at"],
        "is_representative": bool(r["is_representative"]),
    }


@bp.get("/buckets")
def list_buckets():
    data = rows(
        "SELECT b.id, b.kind, b.label, b.active, b.pc1_var_explained, "
        "       b.selected_at, b.representative_id, "
        "       ri.symbol AS rep_symbol "
        "FROM factor_bucket b "
        "LEFT JOIN instrument ri ON ri.id = b.representative_id "
        "ORDER BY b.kind, b.label"
    )
    return jsonify([_bucket_view(r) for r in data])


@bp.get("/buckets/<int:bucket_id>")
def get_bucket(bucket_id: int):
    bucket = one(
        "SELECT b.id, b.kind, b.label, b.active, b.pc1_var_explained, "
        "       b.selected_at, b.representative_id, "
        "       ri.symbol AS rep_symbol "
        "FROM factor_bucket b "
        "LEFT JOIN instrument ri ON ri.id = b.representative_id "
        "WHERE b.id=?",
        (bucket_id,),
    )
    if not bucket:
        return jsonify({"error": "bucket not found"}), 404
    candidates = rows(
        "SELECT c.instrument_id, c.pc1_loading, c.last_pca_at, i.symbol, "
        "       CASE WHEN c.instrument_id = b.representative_id THEN 1 ELSE 0 END "
        "         AS is_representative "
        "FROM factor_bucket_candidate c "
        "JOIN instrument i ON i.id = c.instrument_id "
        "JOIN factor_bucket b ON b.id = c.bucket_id "
        "WHERE c.bucket_id=? "
        "ORDER BY (c.pc1_loading IS NULL), c.pc1_loading DESC, i.symbol",
        (bucket_id,),
    )
    body = _bucket_view(bucket)
    body["candidates"] = [_candidate_view(r) for r in candidates]
    return jsonify(body)


@bp.post("/buckets/<int:bucket_id>/candidates")
def add_candidate(bucket_id: int):
    if not one("SELECT 1 FROM factor_bucket WHERE id=?", (bucket_id,)):
        return jsonify({"error": "bucket not found"}), 404
    body = request.get_json(silent=True) or {}
    symbol = (body.get("symbol") or "").strip().upper()
    if not symbol:
        return jsonify({"error": "symbol is required"}), 400

    inst = one("SELECT id FROM instrument WHERE symbol=?", (symbol,))
    if inst is None:
        cur = execute(
            "INSERT INTO instrument(symbol, display_name, asset_class, data_adapter) "
            "VALUES(?,?,?,?)",
            (symbol, symbol, body.get("asset_class", "etf"), "massive"),
        )
        instrument_id = cur.lastrowid
        # Warm the daily history so the next PCA fit has data to work with.
        try:
            persist_daily_bars(instrument_id, fetch_daily_bars(symbol, days=180))
        except Exception:  # noqa: BLE001
            log.exception("daily-bars warmup failed for newly added candidate %s",
                          symbol)
    else:
        instrument_id = inst["id"]

    existing = one(
        "SELECT 1 FROM factor_bucket_candidate WHERE bucket_id=? AND instrument_id=?",
        (bucket_id, instrument_id),
    )
    if existing:
        return jsonify({"error": f"{symbol} already a candidate"}), 409

    execute(
        "INSERT INTO factor_bucket_candidate(bucket_id, instrument_id) VALUES(?,?)",
        (bucket_id, instrument_id),
    )
    return jsonify({"ok": True, "symbol": symbol,
                    "instrument_id": instrument_id}), 201


@bp.delete("/buckets/<int:bucket_id>/candidates/<symbol>")
def remove_candidate(bucket_id: int, symbol: str):
    symbol = symbol.upper()
    bucket = one("SELECT representative_id FROM factor_bucket WHERE id=?",
                 (bucket_id,))
    if not bucket:
        return jsonify({"error": "bucket not found"}), 404
    inst = one("SELECT id FROM instrument WHERE symbol=?", (symbol,))
    if inst is None:
        return jsonify({"error": "instrument not found"}), 404
    if bucket["representative_id"] == inst["id"]:
        # Removing the rep mid-flight would break factor_refresh + bucket_alerts
        # silently. Force the user to refit_pca first (or pick another rep).
        return jsonify({
            "error": f"{symbol} is the current representative; "
                     "refit PCA first or add a replacement before removing"
        }), 409

    cur = execute(
        "DELETE FROM factor_bucket_candidate WHERE bucket_id=? AND instrument_id=?",
        (bucket_id, inst["id"]),
    )
    if cur.rowcount == 0:
        return jsonify({"error": f"{symbol} not a candidate"}), 404
    return jsonify({"ok": True})


@bp.post("/buckets/<int:bucket_id>/refit_pca")
def refit_pca(bucket_id: int):
    """Re-run PCA over the bucket's candidate basket on-demand (Phase 5).

    Same lookback as the quarterly cron. Returns the new representative + PC1
    variance explained so the UI doesn't have to re-fetch.
    """
    from datetime import datetime, timezone

    bucket = one("SELECT id, label FROM factor_bucket WHERE id=?", (bucket_id,))
    if not bucket:
        return jsonify({"error": "bucket not found"}), 404

    candidates = rows(
        "SELECT c.instrument_id, i.symbol FROM factor_bucket_candidate c "
        "JOIN instrument i ON i.id = c.instrument_id "
        "WHERE c.bucket_id=? ORDER BY i.symbol",
        (bucket_id,),
    )
    pairs = [(r["instrument_id"], r["symbol"]) for r in candidates]
    res = fit_bucket(bucket_id, pairs, lookback_days=DEFAULT_LOOKBACK_DAYS)

    if res.representative_id is None:
        return jsonify({"error": f"PCA could not select a representative: "
                                  f"{res.note}"}), 400

    now_iso = datetime.now(timezone.utc).isoformat()
    execute(
        "UPDATE factor_bucket SET representative_id=?, pc1_var_explained=?, "
        "selected_at=? WHERE id=?",
        (res.representative_id, res.pc1_var_explained, now_iso, bucket_id),
    )
    for iid, loading in res.loadings.items():
        execute(
            "UPDATE factor_bucket_candidate SET pc1_loading=?, last_pca_at=? "
            "WHERE bucket_id=? AND instrument_id=?",
            (loading, now_iso, bucket_id, iid),
        )
    return jsonify({
        "ok": True,
        "representative_id": res.representative_id,
        "representative_symbol": res.representative_symbol,
        "pc1_var_explained": res.pc1_var_explained,
        "n_obs": res.n_obs,
        "note": res.note,
    })
