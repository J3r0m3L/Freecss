"""Notes (update_log) CRUD + convenience routes (DESIGN.md §7.1, §11.D).

Two scopes:
- per-symbol (instrument_id NOT NULL) — bound to a watch's drill-down Notes tab
- global    (instrument_id IS NULL)   — surfaces on /notes route and on per-
  symbol drill-downs via cosine ≥ 0.55 vs instrument.profile_embedding.

`/api/notes/from-news/:id` and `/from-social/:id` pre-fill a note from the
source row and auto-attach to the first watchlist symbol present in the row's
tickers, falling back to a global note if no match.
"""
from __future__ import annotations

import json

from flask import Blueprint, jsonify, request

from server.db import execute, one, rows
from server.nlp.finbert import (
    blob_to_embedding,
    cosine,
    embedding_to_blob,
    get_finbert,
)

bp = Blueprint("notes", __name__, url_prefix="/api")


def _view(r: dict) -> dict:
    """Notes carry their linked-entity ids; the UI fetches details lazily.

    `symbol` is denormalized in the SELECT (LEFT JOIN instrument) so the global
    /notes feed can show a chip without a second round-trip per row.
    """
    return {
        "id": r["id"],
        "instrument_id": r["instrument_id"],
        "symbol": r.get("symbol"),
        "ts": r["ts"],
        "body": r["body"],
        "linked_alert_id": r["linked_alert_id"],
        "linked_news_id": r["linked_news_id"],
        "linked_social_post_id": r["linked_social_post_id"],
    }


_NOTE_COLS = (
    "u.id, u.instrument_id, u.ts, u.body, "
    "u.linked_alert_id, u.linked_news_id, u.linked_social_post_id, "
    "i.symbol "
)
_NOTE_FROM = "FROM update_log u LEFT JOIN instrument i ON i.id = u.instrument_id"


def _insert_note(*, body: str, instrument_id: int | None,
                 linked_alert_id: int | None = None,
                 linked_news_id: int | None = None,
                 linked_social_post_id: int | None = None) -> int:
    body_emb_blob = None
    if instrument_id is None:
        # Global note: embed so the "Related market notes" panel can cosine it.
        emb = get_finbert().score(body or "").embedding
        body_emb_blob = embedding_to_blob(emb)
    cur = execute(
        "INSERT INTO update_log(instrument_id, body, body_embedding, "
        "linked_alert_id, linked_news_id, linked_social_post_id) "
        "VALUES(?,?,?,?,?,?)",
        (instrument_id, body, body_emb_blob, linked_alert_id,
         linked_news_id, linked_social_post_id),
    )
    return cur.lastrowid


@bp.get("/notes")
def list_notes():
    scope = (request.args.get("scope") or "all").lower()
    instrument_id = request.args.get("instrument_id", type=int)
    since = request.args.get("since")

    where = []
    params: list = []
    if scope == "global":
        where.append("u.instrument_id IS NULL")
    elif scope == "symbol":
        if instrument_id is None:
            return jsonify({"error": "instrument_id required for scope=symbol"}), 400
        where.append("u.instrument_id=?")
        params.append(instrument_id)
    elif instrument_id is not None:
        where.append("u.instrument_id=?")
        params.append(instrument_id)
    if since:
        where.append("u.ts >= ?")
        params.append(since)
    sql = f"SELECT {_NOTE_COLS} {_NOTE_FROM}"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY u.ts DESC LIMIT 200"
    return jsonify([_view(r) for r in rows(sql, tuple(params))])


@bp.post("/notes")
def create_note():
    body = request.get_json(silent=True) or {}
    text = (body.get("body") or "").strip()
    if not text:
        return jsonify({"error": "body is required"}), 400
    if body.get("linked_news_id") and body.get("linked_social_post_id"):
        return jsonify({
            "error": "at most one of linked_news_id / linked_social_post_id"
        }), 400
    note_id = _insert_note(
        body=text,
        instrument_id=body.get("instrument_id"),
        linked_alert_id=body.get("linked_alert_id"),
        linked_news_id=body.get("linked_news_id"),
        linked_social_post_id=body.get("linked_social_post_id"),
    )
    r = one(f"SELECT {_NOTE_COLS} {_NOTE_FROM} WHERE u.id=?", (note_id,))
    return jsonify(_view(r)), 201


def _first_watched_instrument_id(tickers_json: str | None) -> int | None:
    """Pick the first ticker in `tickers_json` that's currently watched."""
    if not tickers_json:
        return None
    try:
        tickers = json.loads(tickers_json)
    except Exception:  # noqa: BLE001
        return None
    for sym in tickers:
        r = one(
            "SELECT i.id FROM instrument i JOIN watch w ON w.instrument_id=i.id "
            "WHERE w.active=1 AND i.symbol=?", (sym,),
        )
        if r:
            return r["id"]
    return None


@bp.post("/notes/from-news/<int:news_id>")
def from_news(news_id: int):
    news = one("SELECT * FROM news WHERE id=?", (news_id,))
    if not news:
        return jsonify({"error": "news not found"}), 404
    override = (request.get_json(silent=True) or {}).get("instrument_id")
    iid = override if override is not None else _first_watched_instrument_id(
        news["tickers_json"]
    )
    body = f"{news['title']}\n{news.get('url') or ''}".strip()
    note_id = _insert_note(body=body, instrument_id=iid, linked_news_id=news_id)
    r = one(f"SELECT {_NOTE_COLS} {_NOTE_FROM} WHERE u.id=?", (note_id,))
    return jsonify(_view(r)), 201


@bp.post("/notes/from-social/<int:post_id>")
def from_social(post_id: int):
    post = one("SELECT * FROM social_post WHERE id=?", (post_id,))
    if not post:
        return jsonify({"error": "social_post not found"}), 404
    override = (request.get_json(silent=True) or {}).get("instrument_id")
    iid = override if override is not None else _first_watched_instrument_id(
        post["tickers_json"]
    )
    body = f"{post['body']}\n{post.get('url') or ''}".strip()
    note_id = _insert_note(body=body, instrument_id=iid,
                           linked_social_post_id=post_id)
    r = one(f"SELECT {_NOTE_COLS} {_NOTE_FROM} WHERE u.id=?", (note_id,))
    return jsonify(_view(r)), 201


@bp.post("/notes/from-alert/<int:alert_id>")
def from_alert(alert_id: int):
    """Pre-fill a note from an alert row. Attaches to the alert's instrument
    automatically (alerts always have one), unless overridden in the body."""
    alert = one(
        "SELECT a.id, a.kind, a.severity, a.payload_json, a.ts, "
        "       a.instrument_id, i.symbol "
        "FROM alert a JOIN instrument i ON i.id = a.instrument_id "
        "WHERE a.id=?",
        (alert_id,),
    )
    if not alert:
        return jsonify({"error": "alert not found"}), 404
    override = (request.get_json(silent=True) or {}).get("instrument_id")
    iid = override if override is not None else alert["instrument_id"]
    body = (f"{alert['symbol']} {alert['kind']}/{alert['severity']} "
            f"at {alert['ts']}").strip()
    note_id = _insert_note(body=body, instrument_id=iid,
                           linked_alert_id=alert_id)
    r = one(f"SELECT {_NOTE_COLS} {_NOTE_FROM} WHERE u.id=?", (note_id,))
    return jsonify(_view(r)), 201


@bp.delete("/notes/<int:note_id>")
def delete_note(note_id: int):
    if not one("SELECT 1 FROM update_log WHERE id=?", (note_id,)):
        return jsonify({"error": "note not found"}), 404
    execute("DELETE FROM update_log WHERE id=?", (note_id,))
    return jsonify({"ok": True})


@bp.get("/instrument/<symbol>/related_notes")
def related_notes(symbol: str):
    """Global notes whose body_embedding has cosine ≥ threshold with the
    instrument's profile_embedding (§11.D, §7.1)."""
    cutoff = float(request.args.get("cosine_min", 0.55))
    inst = one("SELECT id, profile_embedding FROM instrument WHERE symbol=?",
               (symbol.upper(),))
    if inst is None:
        return jsonify({"error": "instrument not found"}), 404
    profile_emb = blob_to_embedding(inst["profile_embedding"])
    if not profile_emb:
        return jsonify([])  # nothing to compare against yet
    out: list[dict] = []
    for r in rows(
        "SELECT id, ts, body, body_embedding FROM update_log "
        "WHERE instrument_id IS NULL AND body_embedding IS NOT NULL "
        "ORDER BY ts DESC LIMIT 500"
    ):
        emb = blob_to_embedding(r["body_embedding"])
        if not emb:
            continue
        sim = cosine(profile_emb, emb)
        if sim >= cutoff:
            out.append({
                "id": r["id"], "ts": r["ts"], "body": r["body"],
                "cosine": round(sim, 4),
            })
    out.sort(key=lambda x: x["cosine"], reverse=True)
    return jsonify(out)
